"""Power, cumulative energy, tariff and device diagnostics."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MeterConfigEntry, MeterCoordinator
from .entity import MeterEntity
from .protocol.dlms import normalize_egd_value


@dataclass(frozen=True, kw_only=True)
class MeterSensorDescription(SensorEntityDescription):
    obis: str | None = None
    kind: str = "measurement"


POWER_SENSORS = tuple(
    MeterSensorDescription(
        key=key, translation_key=key, obis=f"1-0:{quantity}.7.0.255",
        device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    )
    for key, quantity in (
        ("import_power", 1), ("import_power_l1", 21), ("import_power_l2", 41),
        ("import_power_l3", 61), ("export_power", 2), ("export_power_l1", 22),
        ("export_power_l2", 42), ("export_power_l3", 62),
    )
)
ENERGY_SENSORS = tuple(
    MeterSensorDescription(
        key=key, translation_key=key, obis=obis,
        device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )
    for key, obis in (
        ("import_energy", "1-0:1.8.0.255"), ("import_energy_t1", "1-0:1.8.1.255"),
        ("import_energy_t2", "1-0:1.8.2.255"), ("import_energy_t3", "1-0:1.8.3.255"),
        ("import_energy_t4", "1-0:1.8.4.255"), ("export_energy", "1-0:2.8.0.255"),
    )
)
SENSORS = POWER_SENSORS + ENERGY_SENSORS + (
    MeterSensorDescription(key="active_tariff", translation_key="active_tariff",
                           obis="0-0:96.14.0.255", kind="text"),
    MeterSensorDescription(key="serial_number", translation_key="serial_number",
                           kind="identity", entity_category=EntityCategory.DIAGNOSTIC),
    MeterSensorDescription(key="last_received", translation_key="last_received", kind="timestamp",
                           device_class=SensorDeviceClass.TIMESTAMP,
                           entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(hass: HomeAssistant, entry: MeterConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(MeterSensor(entry.runtime_data, description) for description in SENSORS)


class MeterSensor(MeterEntity, SensorEntity):
    entity_description: MeterSensorDescription

    def __init__(self, coordinator: MeterCoordinator, description: MeterSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        description = self.entity_description
        if description.kind == "identity":
            return self.coordinator.serial_number is not None
        if description.kind == "timestamp":
            return self.coordinator.data is not None
        return (super().available and description.obis is not None
                and self.coordinator.get_object(description.obis) is not None)

    @property
    def native_value(self) -> Decimal | str | datetime | None:
        description = self.entity_description
        if description.kind == "identity":
            return self.coordinator.serial_number
        if description.kind == "timestamp":
            return self.coordinator.data.received_at if self.coordinator.data is not None else None
        if description.obis is None or (obj := self.coordinator.get_object(description.obis)) is None:
            return None
        if description.kind == "text":
            return obj.as_text()
        measurement = normalize_egd_value(obj)
        return measurement.value if measurement is not None else None
