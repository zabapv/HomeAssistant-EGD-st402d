"""Bounded, transport-independent buffering for the observed EG.D profile."""

from .dlms import DecodeLimits, IncompleteMessage, LimitExceeded, Notification, decode_prefix


class NotificationBuffer:
    """Preserve partial input and consume only complete notifications.

    Invalid/unsupported input is left untouched and raised to the owner. No byte
    scanning or silent repair is attempted; a TCP owner must reset the session.
    """

    def __init__(self, *, max_bytes: int = 16384,
                 decode_limits: DecodeLimits = DecodeLimits()) -> None:
        if max_bytes <= 0:
            raise ValueError("Buffer size must be positive")
        self.max_bytes = max_bytes
        self.decode_limits = decode_limits
        self._data = b""

    @property
    def pending_bytes(self) -> int:
        return len(self._data)

    @property
    def remaining_capacity(self) -> int:
        return self.max_bytes - len(self._data)

    def append(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("data must be immutable bytes")
        if len(data) > self.remaining_capacity:
            raise LimitExceeded("Receive buffer limit exceeded", self.pending_bytes)
        self._data += data

    def pop_message(self) -> Notification | None:
        if not self._data:
            return None
        try:
            notification = decode_prefix(self._data, limits=self.decode_limits)
        except IncompleteMessage:
            if not self.remaining_capacity:
                raise LimitExceeded("Receive buffer full with incomplete message", 0)
            return None
        self._data = self._data[notification.bytes_consumed:]
        return notification

    def clear(self) -> None:
        self._data = b""
