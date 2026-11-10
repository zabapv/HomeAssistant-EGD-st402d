"""UI configuration using the target Home Assistant 2026.11 schema API."""
import asyncio
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from .const import DEFAULT_HOST, DEFAULT_NAME, DEFAULT_PORT, DOMAIN
from .protocol.tcp_client import TcpClientConfig


async def async_probe(config: TcpClientConfig) -> None:
    """Check TCP reachability only, without writing or waiting for a push period."""
    async with asyncio.timeout(config.connect_timeout):
        _reader, writer = await asyncio.open_connection(config.host, config.port)
    writer.close()
    try:
        async with asyncio.timeout(config.close_timeout):
            await writer.wait_closed()
    except (OSError, TimeoutError):
        writer.transport.abort()
    except asyncio.CancelledError:
        writer.transport.abort()
        raise


class MeterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_form("user", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_form("reconfigure", user_input)

    async def _async_form(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry() if step == "reconfigure" else None
        defaults = dict(entry.data) if entry is not None else {
            CONF_HOST: DEFAULT_HOST, CONF_PORT: DEFAULT_PORT, CONF_NAME: DEFAULT_NAME,
        }
        if entry is not None:
            defaults[CONF_NAME] = entry.title
        errors: dict[str, str] = {}
        if user_input is not None:
            defaults.update(user_input)
            try:
                host = str(user_input[CONF_HOST]).strip().lower()
                name = str(user_input[CONF_NAME]).strip()
                config = TcpClientConfig(host=host, port=user_input[CONF_PORT])
                if not name:
                    raise ValueError("Empty name")
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_input"
            else:
                if any(
                    (entry is None or other.entry_id != entry.entry_id)
                    and other.data.get(CONF_HOST, "").lower() == host
                    and other.data.get(CONF_PORT) == config.port
                    for other in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                try:
                    await async_probe(config)
                except OSError:
                    errors["base"] = "cannot_connect"
                else:
                    data = {CONF_HOST: host, CONF_PORT: config.port, CONF_NAME: name}
                    if entry is not None:
                        return self.async_update_reload_and_abort(entry, title=name, data=data)
                    await self.async_set_unique_id(f"endpoint:{host}:{config.port}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=name, data=data)
        schema = probatio.Schema({
            probatio.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
            probatio.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
            probatio.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
        })
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)
