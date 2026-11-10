"""Push coordinator with explicit connection, freshness and meter identity checks."""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, FIRST_MESSAGE_TIMEOUT, STALE_AFTER
from .protocol.dlms import DataObject
from .protocol.tcp_client import ConnectionState, MeterTcpClient, ReceivedNotification, TcpClientConfig

_LOGGER = logging.getLogger(__name__)


class MeterCoordinator(DataUpdateCoordinator[ReceivedNotification | None]):
    """Keep last valid data; expose availability independently from socket state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=None)
        self.data = None
        self.entry = entry
        self.serial_number: str | None = None
        self.identity_mismatch = False
        self.connection_state = ConnectionState.STOPPED
        self._first_message = asyncio.Event()
        self._fresh = False
        self._closed = False
        self._expiry_unsub: CALLBACK_TYPE | None = None
        self.client = MeterTcpClient(
            TcpClientConfig(host=entry.data[CONF_HOST], port=entry.data[CONF_PORT]),
            self._handle_notification, on_state=self._handle_state,
        )

    @property
    def online(self) -> bool:
        return (not self._closed and self._fresh and not self.identity_mismatch
                and self.connection_state is ConnectionState.CONNECTED)

    def get_object(self, obis: str) -> DataObject | None:
        return self.data.notification.get_object(obis) if self.data is not None else None

    async def async_start(self) -> None:
        self.client.start()
        try:
            async with asyncio.timeout(FIRST_MESSAGE_TIMEOUT):
                await self._first_message.wait()
        except TimeoutError as err:
            raise ConfigEntryNotReady("No identified EG.D push message received within 80 seconds") from err

    @callback
    def _handle_notification(self, sample: ReceivedNotification) -> None:
        if self._closed:
            return
        serial = sample.notification.serial_number
        if not serial:
            return  # Identity is required on each accepted measurement frame.
        if self.serial_number is None:
            if not serial:
                return  # No stable device identity yet; setup continues waiting.
            self.serial_number = serial
        if serial is not None and serial != self.serial_number:
            # Never mix cumulative energy from a replacement/different meter.
            if not self.identity_mismatch:
                _LOGGER.error("Received another meter identity; reconfigure/re-add the integration")
            self.identity_mismatch = True
            self.async_update_listeners()
            return
        if self.identity_mismatch:
            return  # Fail closed until reload; keep the last accepted readings.
        self._fresh = True
        if self._expiry_unsub is not None:
            self._expiry_unsub()
        self._expiry_unsub = async_call_later(self.hass, STALE_AFTER, self._expire)
        self.async_set_updated_data(sample)
        self._first_message.set()

    @callback
    def _handle_state(self, state: ConnectionState) -> None:
        self.connection_state = state
        if state is not ConnectionState.CONNECTED:
            self._fresh = False
        if not self._closed:
            self.async_update_listeners()

    @callback
    def _expire(self, now: datetime) -> None:
        self._expiry_unsub = None
        self._fresh = False
        self.async_update_listeners()

    async def async_shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fresh = False
        if self._expiry_unsub is not None:
            self._expiry_unsub()
            self._expiry_unsub = None
        try:
            await self.client.stop()
        finally:
            await super().async_shutdown()


type MeterConfigEntry = ConfigEntry[MeterCoordinator]
