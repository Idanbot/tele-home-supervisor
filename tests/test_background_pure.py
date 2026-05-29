from tele_home_supervisor.background import (
    _format_completion_message,
    _get_torrent_hash,
)
from tele_home_supervisor.models.torrent_snapshot import TorrentSnapshot


class TestGetTorrentHash:
    def test_hash_attribute(self) -> None:
        class Obj:
            hash = "abc123"

        assert _get_torrent_hash(Obj()) == "abc123"

    def test_info_hash_attribute(self) -> None:
        class Obj:
            info_hash = "def456"

        assert _get_torrent_hash(Obj()) == "def456"

    def test_hash_string_attribute(self) -> None:
        class Obj:
            hashString = "ghi789"

        assert _get_torrent_hash(Obj()) == "ghi789"

    def test_priority_order(self) -> None:
        class Obj:
            hash = "first"
            info_hash = "second"
            hashString = "third"

        assert _get_torrent_hash(Obj()) == "first"

    def test_no_hash_returns_none(self) -> None:
        class Obj:
            pass

        assert _get_torrent_hash(Obj()) is None

    def test_empty_hash_falls_through(self) -> None:
        class Obj:
            hash = ""
            info_hash = "fallback"

        assert _get_torrent_hash(Obj()) == "fallback"

    def test_converts_to_string(self) -> None:
        class Obj:
            hash = 12345

        assert _get_torrent_hash(Obj()) == "12345"


class TestFormatCompletionMessage:
    def test_basic_message(self) -> None:
        t = TorrentSnapshot(
            torrent_hash="hash1",
            name="Ubuntu ISO",
            is_complete=True,
            total_size=0,
            downloaded=0,
        )
        msg = _format_completion_message(t)
        assert "Ubuntu ISO" in msg
        assert "completed" in msg

    def test_message_with_size(self) -> None:
        t = TorrentSnapshot(
            torrent_hash="hash1",
            name="Big File",
            is_complete=True,
            total_size=1000000000,
            downloaded=1000000000,
        )
        msg = _format_completion_message(t)
        assert "Big File" in msg
        assert "1.0GB" in msg

    def test_message_without_size(self) -> None:
        t = TorrentSnapshot(
            torrent_hash="hash1",
            name="Small",
            is_complete=True,
            total_size=0,
            downloaded=0,
        )
        msg = _format_completion_message(t)
        assert "Small" in msg
        assert "GB" not in msg
