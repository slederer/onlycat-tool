"""Cat door control commands via OnlyCat Socket.IO gateway."""

import asyncio
import logging

import socketio

logger = logging.getLogger(__name__)
GATEWAY_URL = "https://gateway.onlycat.com"


async def send_device_command(token: str, device_id: str, command: str, params: dict = None) -> dict:
    """Connect to OnlyCat, send a command, disconnect."""
    sio = socketio.AsyncClient(reconnection=False)
    connected = asyncio.Event()
    result = {"success": False, "error": None, "data": None}

    @sio.event
    async def connect():
        connected.set()

    try:
        await sio.connect(
            GATEWAY_URL,
            transports=["websocket"],
            headers={"platform": "home-assistant", "device": "onlycat-hass"},
            auth={"token": token},
        )
        await asyncio.wait_for(connected.wait(), timeout=15)

        payload = {"deviceId": device_id}
        if params:
            payload.update(params)

        resp = await sio.call(command, payload)
        result["success"] = True
        result["data"] = resp
    except Exception as exc:
        result["error"] = str(exc)
        logger.exception("Command failed: %s", command)
    finally:
        await sio.disconnect()

    return result


async def set_transit_policy(token: str, device_id: str, policy: str) -> dict:
    """Set cat door transit policy. Policies: 'both', 'in_only', 'out_only', 'locked'."""
    return await send_device_command(
        token, device_id, "activateDeviceTransitPolicy",
        {"policy": policy}
    )


async def run_command(token: str, device_id: str, command_name: str) -> dict:
    """Run a device command."""
    return await send_device_command(
        token, device_id, "runDeviceCommand",
        {"command": command_name}
    )
