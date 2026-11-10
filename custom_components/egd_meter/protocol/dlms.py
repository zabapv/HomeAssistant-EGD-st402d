"""Decode the observed EG.D notification profile, not arbitrary DLMS/COSEM.

Object descriptors use a nine-byte packed profile-specific format. Only absent
APDU timestamps and short-form lengths are supported.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum


class DecodeError(ValueError):
    """Invalid or unsupported notification, with an offset relative to its start."""

    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"{message} at byte {offset}")


class IncompleteMessage(DecodeError):
    """More bytes are required; no complete notification has been returned."""

    def __init__(self, offset: int, required_bytes: int) -> None:
        self.required_bytes = required_bytes
        super().__init__(f"Need at least {required_bytes} bytes", offset)


class InvalidMessage(DecodeError):
    """The bytes contradict the supported profile."""


class UnsupportedMessage(DecodeError):
    """A type or variant is outside the explicitly supported subset."""


class LimitExceeded(DecodeError):
    """A configured resource limit was exceeded."""


class DataType(IntEnum):
    UINT32 = 0x06
    OCTET_STRING = 0x09
    ENUM = 0x16


@dataclass(frozen=True)
class DecodeLimits:
    """Engineering limits, not limits claimed by the EG.D specification."""

    max_message_bytes: int = 16384
    max_objects: int = 64
    max_string_bytes: int = 127

    def __post_init__(self) -> None:
        if min(self.max_message_bytes, self.max_objects, self.max_string_bytes) <= 0:
            raise ValueError("Decoder limits must be positive")


@dataclass(frozen=True)
class Obis:
    """All six OBIS groups; shortened sensor names are deliberately not accepted."""

    groups: tuple[int, int, int, int, int, int]

    def __post_init__(self) -> None:
        if len(self.groups) != 6 or any(not 0 <= part <= 255 for part in self.groups):
            raise ValueError("OBIS must contain six bytes")

    @classmethod
    def parse(cls, value: str) -> Obis:
        try:
            ab, cdef = value.split(":")
            a, b = ab.split("-")
            c, d, e, f = cdef.split(".")
            return cls((int(a), int(b), int(c), int(d), int(e), int(f)))
        except (ValueError, TypeError) as err:
            raise ValueError(f"Expected full OBIS A-B:C.D.E.F, got {value!r}") from err

    def __str__(self) -> str:
        a, b, c, d, e, f = self.groups
        return f"{a}-{b}:{c}.{d}.{e}.{f}"


@dataclass(frozen=True)
class ObjectDescriptor:
    class_id: int
    obis: Obis
    attribute_id: int


@dataclass(frozen=True)
class DataObject:
    descriptor: ObjectDescriptor
    data_type: DataType
    raw_value: int | bytes
    offset: int
    byte_length: int
    value_tag_offset: int
    raw_data: bytes

    def as_text(self) -> str:
        """Explicit ASCII interpretation; binary strings remain available as bytes."""
        if not isinstance(self.raw_value, bytes):
            raise TypeError("Object is not an octet-string")
        return self.raw_value.decode("ascii")


@dataclass(frozen=True)
class Notification:
    long_invoke_id_and_priority: int
    profile_marker: int
    objects: tuple[DataObject, ...]
    bytes_consumed: int
    raw_data: bytes

    def get_object(self, obis: str) -> DataObject | None:
        key = Obis.parse(obis)
        return next((obj for obj in self.objects if obj.descriptor.obis == key), None)

    @property
    def serial_number(self) -> str | None:
        obj = self.get_object("0-0:96.1.0.255")
        return obj.as_text() if obj is not None else None

    @property
    def logical_device_name(self) -> str | None:
        obj = self.get_object("0-0:42.0.0.255")
        return obj.as_text() if obj is not None else None

    @property
    def active_tariff(self) -> str | None:
        obj = self.get_object("0-0:96.14.0.255")
        return obj.as_text() if obj is not None else None


@dataclass(frozen=True)
class _ObjectSpec:
    class_id: int
    attribute_id: int
    data_type: DataType
    unit: str | None = None


# Full OBIS, class, attribute and type must match before applying profile units.
_SPECS: dict[str, _ObjectSpec] = {
    "0-0:42.0.0.255": _ObjectSpec(1, 2, DataType.OCTET_STRING),
    "0-2:25.9.0.255": _ObjectSpec(40, 1, DataType.OCTET_STRING),
    "0-0:96.1.0.255": _ObjectSpec(1, 2, DataType.OCTET_STRING),
    "0-0:96.3.10.255": _ObjectSpec(70, 3, DataType.ENUM),
    "0-0:17.0.0.255": _ObjectSpec(71, 3, DataType.UINT32, "W"),
    "0-0:96.14.0.255": _ObjectSpec(1, 2, DataType.OCTET_STRING),
    "0-0:96.13.0.255": _ObjectSpec(1, 2, DataType.OCTET_STRING),
}
_SPECS.update({
    f"0-{phase}:96.3.10.255": _ObjectSpec(70, 3, DataType.ENUM)
    for phase in range(1, 7)
})
_SPECS.update({
    f"1-0:{quantity}.7.0.255": _ObjectSpec(3, 2, DataType.UINT32, "W")
    for quantity in (1, 21, 41, 61, 2, 22, 42, 62)
})
_SPECS.update({
    f"1-0:1.8.{tariff}.255": _ObjectSpec(3, 2, DataType.UINT32, "Wh")
    for tariff in range(5)
})
_SPECS["1-0:2.8.0.255"] = _ObjectSpec(3, 2, DataType.UINT32, "Wh")
_ASCII_OBJECTS = {"0-0:42.0.0.255", "0-0:96.1.0.255", "0-0:96.14.0.255"}


@dataclass(frozen=True)
class ProfileMeasurement:
    """An opt-in document-based conversion, never a meter-reported scaler."""

    raw_value: int
    documented_unit: str
    value: Decimal
    unit: str
    scaler: None = None
    unit_source: str = "EG.D RS485 PDF, page 2"
    scale_verified_on_meter: bool = False


def normalize_egd_value(obj: DataObject) -> ProfileMeasurement | None:
    """Apply the documented EG.D W/Wh rule only to an exact known descriptor.

    Calling this function explicitly selects the documented profile rule.
    Unknown objects and non-measurements have no normalized measurement.
    """
    desc = obj.descriptor
    spec = _SPECS.get(str(desc.obis))
    if (
        spec is None
        or spec.unit is None
        or desc.class_id != spec.class_id
        or desc.attribute_id != spec.attribute_id
        or obj.data_type != spec.data_type
        or not isinstance(obj.raw_value, int)
    ):
        return None
    value = Decimal(obj.raw_value)
    if spec.unit == "Wh":
        whole, fraction = divmod(obj.raw_value, 1000)
        exact_kwh = Decimal(f"{whole}.{fraction:03d}")
        return ProfileMeasurement(obj.raw_value, "Wh", exact_kwh, "kWh")
    return ProfileMeasurement(obj.raw_value, "W", value, "W")


class _Reader:
    def __init__(self, data: bytes, limits: DecodeLimits) -> None:
        self.data = data
        self.limits = limits
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > self.limits.max_message_bytes:
            raise LimitExceeded("Message size limit exceeded", self.pos)
        if end > len(self.data):
            raise IncompleteMessage(self.pos, end)
        result = self.data[self.pos:end]
        self.pos = end
        return result

    def byte(self) -> int:
        return self.take(1)[0]

    def expect(self, value: int) -> None:
        offset = self.pos
        if self.byte() != value:
            raise InvalidMessage(f"Expected 0x{value:02X}", offset)

    def short_length(self) -> int:
        offset = self.pos
        value = self.byte()
        if value >= 128:
            raise UnsupportedMessage("Long-form lengths are not supported", offset)
        return value


def _read_object(reader: _Reader) -> DataObject:
    start = reader.pos
    reader.expect(0x02)
    reader.expect(0x02)
    descriptor = reader.take(9)
    obis = Obis((descriptor[2], descriptor[3], descriptor[4],
                 descriptor[5], descriptor[6], descriptor[7]))
    desc = ObjectDescriptor(int.from_bytes(descriptor[:2], "big"), obis, descriptor[8])
    if desc.class_id == 0 or not 1 <= desc.attribute_id <= 127:
        raise InvalidMessage("Invalid packed object descriptor", start + 2)
    tag_offset = reader.pos
    tag = reader.byte()
    try:
        data_type = DataType(tag)
    except ValueError as err:
        raise UnsupportedMessage(f"Unsupported value type 0x{tag:02X}", tag_offset) from err
    spec = _SPECS.get(str(obis))
    if spec is not None and (
        (desc.class_id, desc.attribute_id, data_type)
        != (spec.class_id, spec.attribute_id, spec.data_type)
    ):
        raise InvalidMessage("Known OBIS has conflicting class, attribute or type", start)
    raw_value: int | bytes
    if data_type == DataType.UINT32:
        raw_value = int.from_bytes(reader.take(4), "big")
    elif data_type == DataType.ENUM:
        raw_value = reader.byte()
    else:
        length = reader.short_length()
        if length > reader.limits.max_string_bytes:
            raise LimitExceeded("String size limit exceeded", tag_offset + 1)
        raw_value = reader.take(length)
        if str(obis) in _ASCII_OBJECTS and not raw_value.isascii():
            raise InvalidMessage("Known identification/tariff is not ASCII", tag_offset)
    return DataObject(desc, data_type, raw_value, start, reader.pos - start,
                      tag_offset, reader.data[start:reader.pos])


def decode_prefix(data: bytes, *, limits: DecodeLimits = DecodeLimits()) -> Notification:
    """Decode one complete notification from the beginning of data.

    Trailing bytes are untouched: bytes_consumed identifies the next boundary.
    IncompleteMessage means retry with more data. Other DecodeError subclasses
    require explicit error handling; this function never scans or repairs input.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be immutable bytes")
    reader = _Reader(data, limits)
    reader.expect(0x0F)
    invoke = int.from_bytes(reader.take(4), "big")
    if reader.byte() != 0:
        raise UnsupportedMessage("Only absent APDU date-time is supported", 5)
    reader.expect(0x02)
    reader.expect(0x02)
    reader.expect(0x16)
    marker = reader.byte()
    if marker != 1:
        raise UnsupportedMessage("Unknown EG.D profile marker", 9)
    reader.expect(0x01)
    count = reader.short_length()
    if count > limits.max_objects:
        raise LimitExceeded("Object count limit exceeded", 11)
    objects: list[DataObject] = []
    seen: set[Obis] = set()
    for _ in range(count):
        obj = _read_object(reader)
        if obj.descriptor.obis in seen:
            raise InvalidMessage("Duplicate or conflicting OBIS", obj.offset)
        seen.add(obj.descriptor.obis)
        objects.append(obj)
    return Notification(invoke, marker, tuple(objects), reader.pos, data[:reader.pos])


def decode_message(data: bytes, *, limits: DecodeLimits = DecodeLimits()) -> Notification:
    """Decode exactly one notification; reject trailing bytes or extra messages."""
    notification = decode_prefix(data, limits=limits)
    if notification.bytes_consumed != len(data):
        raise InvalidMessage("Trailing data after notification", notification.bytes_consumed)
    return notification
