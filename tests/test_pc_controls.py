import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import network, pc
from tele_home_supervisor.models.bot_state import BotState
from tele_home_supervisor.models.network_inventory import NetworkDeviceScan


@pytest.fixture
def controls(tmp_path, monkeypatch):
    context = DummyContext()
    context.application.create_task = asyncio.create_task
    state = BotState(_database_file=tmp_path / "state.sqlite3")
    state._state_loaded = True
    monkeypatch.setattr(pc, "get_state", lambda app: state)
    monkeypatch.setattr(pc, "guard_sensitive", AsyncMock(return_value=True))
    resolved = network._ResolvedWolRequest(
        ok=True,
        mac="aa:bb:cc:dd:ee:ff",
        ping_host="192.168.1.10",
    )
    monkeypatch.setattr(pc, "_target", lambda: resolved)
    update = DummyUpdate(123, 123)
    update.callback_query = SimpleNamespace(message=update.message, data="pc1:wake")
    return update, context, state


@pytest.mark.asyncio
async def test_status_uses_latest_mac_observation(controls, monkeypatch):
    update, context, state = controls
    state.network_inventory = {
        "192.168.1.20": [
            NetworkDeviceScan(
                scan_id="scan",
                scanned_at=1000,
                ip="192.168.1.20",
                mac="AA:BB:CC:DD:EE:FF",
            )
        ]
    }
    ping = AsyncMock(return_value=True)
    monkeypatch.setattr(network, "_ping_once", ping)
    await pc.cmd_pc1(update, context)
    ping.assert_awaited_once_with("192.168.1.20")
    assert "Reachable" in update.message.replies[0]
    assert "192.168.1.20" in update.message.replies[0]


@pytest.mark.asyncio
async def test_wake_confirms_reachability_and_cleans_task(controls, monkeypatch):
    update, context, state = controls
    monkeypatch.setattr(network, "_ping_once", AsyncMock(side_effect=[False, True]))
    send = AsyncMock()
    monkeypatch.setattr(network, "_send_wol_packet", send)
    await pc.handle_pc_callback(update, context)
    await state.tasks["pc1:123"]
    send.assert_awaited_once()
    assert "reachable at" in update.message.replies[-1]
    assert "pc1:123" not in state.tasks


@pytest.mark.asyncio
async def test_wake_timeout_does_not_claim_success(controls, monkeypatch):
    update, context, state = controls
    monkeypatch.setattr(
        network, "_ping_once", AsyncMock(side_effect=[False, TimeoutError()])
    )
    monkeypatch.setattr(network, "_send_wol_packet", AsyncMock())
    await pc.handle_pc_callback(update, context)
    await state.tasks["pc1:123"]
    assert "power state is unconfirmed" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_scan_persists_found_device(controls, monkeypatch):
    update, context, state = controls
    update.callback_query.data = "pc1:scan"
    found = NetworkDeviceScan("scan", 1000, "192.168.1.20", mac="aa:bb:cc:dd:ee:ff")
    monkeypatch.setattr(
        network, "_resolve_default_scan_targets", lambda: ["192.168.1.0/24"]
    )
    monkeypatch.setattr(
        pc.network_inventory,
        "find_device_by_mac",
        AsyncMock(
            return_value=(found, [found], SimpleNamespace(error="")),
        ),
    )
    monkeypatch.setattr(network, "_ping_once", AsyncMock(return_value=True))
    monkeypatch.setattr(state, "save_network_inventory", lambda: None)
    monkeypatch.setattr(state, "prune_network_inventory", lambda **kw: None)
    await pc.handle_pc_callback(update, context)
    await state.tasks["pc1:123"]
    assert state.network_inventory[found.ip] == [found]


@pytest.mark.asyncio
async def test_pc_callbacks_require_sensitive_auth(controls, monkeypatch):
    update, context, state = controls
    monkeypatch.setattr(pc, "guard_sensitive", AsyncMock(return_value=False))
    await pc.handle_pc_callback(update, context)
    assert state.tasks == {}


@pytest.mark.asyncio
async def test_already_online_does_not_send_wake(controls, monkeypatch):
    update, context, state = controls
    monkeypatch.setattr(network, "_ping_once", AsyncMock(return_value=True))
    send = AsyncMock()
    monkeypatch.setattr(network, "_send_wol_packet", send)
    await pc.handle_pc_callback(update, context)
    await state.tasks["pc1:123"]
    send.assert_not_awaited()
    assert "already reachable" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_duplicate_operation_is_suppressed(controls):
    update, context, state = controls
    pending = asyncio.get_running_loop().create_future()
    state.tasks["pc1:123"] = pending
    try:
        await pc.handle_pc_callback(update, context)
        assert "already running" in update.message.replies[-1]
        assert state.tasks["pc1:123"] is pending
    finally:
        pending.cancel()


@pytest.mark.asyncio
async def test_missing_pc1_configuration(controls, monkeypatch):
    update, context, _ = controls
    monkeypatch.setattr(pc, "_target", lambda: None)
    await pc.cmd_pc1(update, context)
    assert "MANAGED_HOSTS_JSON" in update.message.replies[-1]
