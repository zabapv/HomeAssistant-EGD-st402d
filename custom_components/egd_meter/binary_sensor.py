"""Socket connection diagnostic; independent from measurement freshness."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MeterConfigEntry, MeterCoordinator
from .entity import MeterEntity
from .protocol.tcp_client import ConnectionState


async def async_setup_entry(hass: HomeAssistant, entry: MeterConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([MeterConnectionSensor(entry.runtime_data)])


class MeterConnectionSensor(MeterEntity, BinarySensorEntity):
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MeterCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.connection_state is ConnectionState.CONNECTED
