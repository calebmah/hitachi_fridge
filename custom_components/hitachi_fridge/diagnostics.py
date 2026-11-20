"""Diagnostics support for Hitachi Fridge."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HitachiFridgeConfigEntry
from .const import (
    CONF_CKDN_IV,
    CONF_CKDN_KEY,
    CONF_CKDN_TOKEN,
    CONF_CSPF_ID,
    CONF_DEVICE_IV,
    CONF_DEVICE_KEY,
    CONF_DST,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SRC,
    CONF_USERNAME,
)

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_CSPF_ID,
    CONF_CKDN_TOKEN,
    CONF_CKDN_KEY,
    CONF_CKDN_IV,
    CONF_DEVICE_KEY,
    CONF_DEVICE_IV,
    CONF_DST,
    CONF_SRC,
    CONF_USERNAME,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HitachiFridgeConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a Hitachi Fridge config entry."""
    appliances_diag: list[dict[str, Any]] = []
    for coord in entry.runtime_data.coordinators.values():
        snap = coord.data
        appliances_diag.append(
            {
                "dst_prefix": coord.appliance.dst[:8].upper(),
                "capabilities": asdict(coord.capabilities),
                "transport": snap.transport if snap else None,
                "fridge_ip": snap.fridge_ip if snap else coord.appliance.fridge_ip,
                "update_interval_seconds": (
                    coord.update_interval.total_seconds()
                    if coord.update_interval
                    else None
                ),
                "telemetry": (
                    {
                        **asdict(snap.telemetry),
                        "appliance_timestamp": (
                            snap.telemetry.appliance_timestamp.isoformat()
                            if snap.telemetry.appliance_timestamp
                            else None
                        ),
                    }
                    if snap
                    else None
                ),
                "firmware": asdict(snap.firmware) if snap and snap.firmware else None,
                "door_history_days": len(snap.door_history) if snap else 0,
                "alarm_history": (
                    [asdict(item) for item in snap.alarm_history] if snap else []
                ),
                "disabled_push_ids": (
                    sorted(snap.disabled_push_ids)
                    if snap and snap.disabled_push_ids is not None
                    else None
                ),
            }
        )

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "appliances": appliances_diag,
    }
