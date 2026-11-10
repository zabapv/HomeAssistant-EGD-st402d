"""Common device identity and coordinator wiring."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MeterCoordinator


class MeterEntity(CoordinatorEntity[MeterCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MeterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        if coordinator.serial_number is None:
            raise ValueError("Cannot create entities without meter identity")
        self._attr_unique_id = f"{coordinator.serial_number}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial_number)},
            name=coordinator.entry.title,
            serial_number=coordinator.serial_number,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.online
