"""Read-only asynchronous TCP receiver for EG.D notifications.

No Home Assistant dependencies, requests, heartbeat writes or unit conversion.
A protocol error closes the connection; reconnect starts with an empty buffer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import math

from .dlms import DecodeError, DecodeLimits, Notification
from .stream import NotificationBuffer

_LOGGER = logging.getLogger(__name__)


class ConnectionState(Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RETRYING = "retrying"


@dataclass(frozen=True)
class TcpClientConfig:
    host: str
    port: int = 5000
    connect_timeout: float = 10.0
    idle_timeout: float = 150.0
    frame_timeout: float = 10.0
    close_timeout: float = 5.0
    reconnect_initial: float = 1.0
    reconnect_max: float = 60.0
    warning_interval: float = 60.0
    read_size: int = 4096
    max_buffer_bytes: int = 16384
    decode_limits: DecodeLimits = DecodeLimits()

    def __post_init__(self) -> None:
        if not self.host or self.host != self.host.strip():
            raise ValueError("Host must be nonempty without surrounding whitespace")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("TCP port must be an integer between 1 and 65535")
        durations = (self.connect_timeout, self.idle_timeout, self.frame_timeout,
                     self.close_timeout, self.reconnect_initial, self.reconnect_max,
                     self.warning_interval)
        if any(not math.isfinite(value) or value <= 0 for value in durations):
            raise ValueError("Timeouts and retry intervals must be finite and positive")
        if self.reconnect_max < self.reconnect_initial:
            raise ValueError("Maximum retry delay must not be below the initial delay")
        if type(self.read_size) is not int or self.read_size <= 0:
            raise ValueError("Read size must be a positive integer")
        if (type(self.max_buffer_bytes) is not int
                or self.max_buffer_bytes < self.decode_limits.max_message_bytes):
            raise ValueError("Receive buffer must fit the configured maximum message")


@dataclass(frozen=True)
class ReceivedNotification:
    notification: Notification
    received_at: datetime


class _SessionEnded(Exception):
    """Expected session failure which can be retried."""


class MeterTcpClient:
    """One task and connection per instance, used from a single event loop.

    Callbacks are synchronous, fast event-loop callbacks. Exceptions in callbacks
    are logged with rate limiting and do not turn valid data into network errors.
    """

    def __init__(
        self,
        config: TcpClientConfig,
        on_notification: Callable[[ReceivedNotification], None],
        *,
        on_state: Callable[[ConnectionState], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self._on_notification = on_notification
        self._on_state = on_state
        self._logger = logger if logger is not None else _LOGGER
        self._task: asyncio.Task[None] | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.state = ConnectionState.STOPPED
        self.last_notification: ReceivedNotification | None = None
        self.last_error: str | None = None
        self.connection_attempts = 0
        self.notifications_received = 0
        self.failures = 0
        self.retry_delay = 0.0
        self._last_warning = -math.inf
        self._suppressed_warnings = 0

    @property
    def connected(self) -> bool:
        return self.state is ConnectionState.CONNECTED and self._writer is not None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start in the current loop; repeated starts while running are harmless."""
        if self.running:
            return
        if self._task is not None:
            # Surface unexpected programmer failures instead of losing the task.
            self._task.result()
        self._task = asyncio.create_task(self._run(), name="egd_meter_tcp")

    async def stop(self) -> None:
        """Cancel connection/read/backoff, close the socket and wait for cleanup."""
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            if self._task is task:
                self._task = None

    def _warn(self, message: str, *, exc_info: bool = False) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_warning < self.config.warning_interval:
            self._suppressed_warnings += 1
            return
        self._logger.warning("%s (suppressed warnings: %d)", message,
                             self._suppressed_warnings, exc_info=exc_info)
        self._last_warning = now
        self._suppressed_warnings = 0

    def _set_state(self, state: ConnectionState) -> None:
        if self.state is state:
            return
        self.state = state
        if self._on_state is not None:
            try:
                self._on_state(state)
            except Exception:
                self._warn("EG.D state callback failed", exc_info=True)

    def _publish(self, notification: Notification, received_at: datetime) -> None:
        received = ReceivedNotification(notification, received_at)
        self.last_notification = received
        self.notifications_received += 1
        self.last_error = None
        try:
            self._on_notification(received)
        except Exception:
            self._warn("EG.D notification callback failed", exc_info=True)

    async def _close_connection(self) -> None:
        writer, self._writer = self._writer, None
        if writer is None:
            return
        writer.close()
        try:
            async with asyncio.timeout(self.config.close_timeout):
                await writer.wait_closed()
        except (OSError, TimeoutError):
            writer.transport.abort()
        except asyncio.CancelledError:
            writer.transport.abort()
            raise

    async def _run(self) -> None:
        delay = self.config.reconnect_initial
        try:
            while True:
                self.retry_delay = 0.0
                self.connection_attempts += 1
                before = self.notifications_received
                self._set_state(ConnectionState.CONNECTING)
                try:
                    try:
                        async with asyncio.timeout(self.config.connect_timeout):
                            reader, writer = await asyncio.open_connection(
                                self.config.host, self.config.port,
                                limit=self.config.max_buffer_bytes,
                            )
                    except TimeoutError as err:
                        raise _SessionEnded("TCP connect timeout") from err
                    self._writer = writer
                    self._set_state(ConnectionState.CONNECTED)
                    await self._receive(reader)
                except (OSError, DecodeError, _SessionEnded) as err:
                    self.last_error = str(err)
                    self.failures += 1
                    # Report loss immediately, including while closing a socket.
                    if self.notifications_received > before:
                        delay = self.config.reconnect_initial
                    self.retry_delay = delay
                    self._set_state(ConnectionState.RETRYING)
                finally:
                    await self._close_connection()
                # Connecting alone does not reset backoff; decoded data does.
                self._warn(f"EG.D connection ended: {self.last_error}; retry in {delay:g}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.reconnect_max)
        finally:
            self.retry_delay = 0.0
            self._set_state(ConnectionState.STOPPED)

    async def _receive(self, reader: asyncio.StreamReader) -> None:
        # Each connection owns a fresh buffer and its own partial-frame deadline.
        buffer = NotificationBuffer(max_bytes=self.config.max_buffer_bytes,
                                    decode_limits=self.config.decode_limits)
        partial_since: float | None = None
        loop = asyncio.get_running_loop()
        while True:
            timeout = self.config.idle_timeout
            partial_deadline = False
            if partial_since is not None:
                remaining = partial_since + self.config.frame_timeout - loop.time()
                if remaining <= 0:
                    raise _SessionEnded("Incomplete message timeout")
                if remaining <= timeout:
                    timeout = remaining
                    partial_deadline = True
            try:
                async with asyncio.timeout(timeout):
                    data = await reader.read(min(self.config.read_size, buffer.remaining_capacity))
            except TimeoutError as err:
                reason = "Incomplete message timeout" if partial_deadline else "TCP idle timeout"
                raise _SessionEnded(reason) from err
            if not data:
                if buffer.pending_bytes:
                    raise _SessionEnded(f"EOF with {buffer.pending_bytes} incomplete bytes")
                raise _SessionEnded("Peer closed TCP connection")
            arrival = loop.time()
            received_at = datetime.now(timezone.utc)
            if not buffer.pending_bytes:
                partial_since = arrival
            buffer.append(data)
            while (notification := buffer.pop_message()) is not None:
                self._publish(notification, received_at)
                partial_since = arrival if buffer.pending_bytes else None
            # Yield even if read() keeps completing from already-buffered data.
            await asyncio.sleep(0)
