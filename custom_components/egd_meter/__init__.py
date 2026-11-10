"""EG.D meter integration for Home Assistant Core 2026.11+."""
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN
from .coordinator import MeterConfigEntry, MeterCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: MeterConfigEntry) -> None:
    coordinator = MeterCoordinator(hass, entry)

    async def stop(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    try:
        await coordinator.async_start()
        unique_id = f"meter:{coordinator.serial_number}"
        if entry.unique_id and entry.unique_id.startswith("meter:") and entry.unique_id != unique_id:
            raise ConfigEntryError("The configured endpoint now reports a different meter")
        if any(other.entry_id != entry.entry_id and other.unique_id == unique_id
               for other in hass.config_entries.async_entries(DOMAIN)):
            raise ConfigEntryError("This meter is already configured at another endpoint")
        if entry.unique_id != unique_id:
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        raise


async def async_unload_entry(hass: HomeAssistant, entry: MeterConfigEntry) -> None:
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    await entry.runtime_data.async_shutdown()
