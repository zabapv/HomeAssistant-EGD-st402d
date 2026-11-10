"""Diagnostics without network address, identity or raw textual payloads."""
from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .coordinator import MeterConfigEntry
from .protocol.dlms import normalize_egd_value


async def async_get_config_entry_diagnostics(hass: HomeAssistant,
                                            entry: MeterConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    sample = coordinator.data
    values = []
    if sample is not None:
        for obj in sample.notification.objects:
            measurement = normalize_egd_value(obj)
            values.append({
                "obis": str(obj.descriptor.obis),
                "class_id": obj.descriptor.class_id,
                "attribute_id": obj.descriptor.attribute_id,
                "type": obj.data_type.name,
                "raw_value": obj.raw_value if isinstance(obj.raw_value, int) else REDACTED,
                "profile_unit": measurement.unit if measurement is not None else None,
                "scaler": None,
            })
    return {
        "entry": {"host": REDACTED, "port": entry.data["port"],
                  "unique_id": REDACTED, "title": REDACTED},
        "state": coordinator.connection_state.value,
        "measurements_available": coordinator.online,
        "identity_mismatch": coordinator.identity_mismatch,
        "serial_number": REDACTED,
        "last_received_at": sample.received_at.isoformat() if sample is not None else None,
        "last_message_bytes": sample.notification.bytes_consumed if sample is not None else None,
        "last_raw_hex": REDACTED,
        "last_error": REDACTED if coordinator.client.last_error else None,
        "connection_attempts": coordinator.client.connection_attempts,
        "failures": coordinator.client.failures,
        "notifications_received": coordinator.client.notifications_received,
        "unit_source": "EG.D RS485 documentation, page 2",
        "scale_verified_on_meter": False,
        "objects": values,
    }
