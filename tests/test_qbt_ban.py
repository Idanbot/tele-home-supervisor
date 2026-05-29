from __future__ import annotations

from unittest.mock import Mock, patch

from tele_home_supervisor import torrent


# Or use time_machine / freezegun if added to your project
def test_qbt_403_ban_blocks_and_expires(monkeypatch):
    """Verify that a 403 error triggers a ban which expires."""
    # 1. Use monkeypatch to ensure state resets after test completes
    monkeypatch.setattr(torrent, "_ban_until", 0.0)
    torrent.reset_manager()

    monkeypatch.setattr(torrent.settings, "QBT_BAN_DURATION_S", 300)

    # 2. Use a stateful mock for time instead of a closure variable
    mock_time = Mock(return_value=1000.0)
    monkeypatch.setattr(torrent.time, "time", mock_time)

    mock_client = Mock()
    mock_client.app.version = "v1.2.3"

    # Set it to raise a real-looking exception
    def auth_log_in_side_effect(*args, **kwargs):
        if mock_time.return_value < 1300.0:
            raise Exception("HTTP 403 Forbidden")
        return None  # Succeed on second attempt

    mock_client.auth_log_in.side_effect = auth_log_in_side_effect

    # 3. Only mock the Client, keep the real exception classes if possible
    with patch(
        "tele_home_supervisor.torrent.qbittorrentapi.Client", return_value=mock_client
    ):
        # First attempt should fail and set the ban
        assert torrent.get_manager() is None
        assert torrent._ban_until == 1300.0
        assert mock_client.auth_log_in.call_count == 1

        # Second attempt immediately should return None without calling connect
        assert torrent.get_manager() is None
        assert mock_client.auth_log_in.call_count == 1  # Still 1

        # Advance time past ban duration
        mock_time.return_value = 1301.0

        # Third attempt should succeed now that the ban is over
        mgr = torrent.get_manager()
        assert mgr is not None
        assert mgr.qbt_client == mock_client
        assert mock_client.auth_log_in.call_count == 2
