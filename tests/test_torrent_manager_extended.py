from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from tele_home_supervisor import torrent


class FakeClient:
    def __init__(self, torrents=None) -> None:
        self._torrents = torrents or []
        self.paused = []
        self.resumed = []
        self.deleted = []
        self.added = []

    def torrents_info(self):
        return self._torrents

    def torrents_add(self, **kwargs):
        self.added.append(kwargs)

    def torrents_pause(self, **kwargs):
        self.paused.append(kwargs)

    def torrents_resume(self, **kwargs):
        self.resumed.append(kwargs)

    def torrents_delete(self, **kwargs):
        self.deleted.append(kwargs)
        hashes = kwargs.get("hashes") or kwargs.get("torrent_hashes")
        if isinstance(hashes, str):
            delete_hashes = set(hashes.split("|"))
        else:
            delete_hashes = set(hashes or [])
        self._torrents = [
            item
            for item in self._torrents
            if getattr(item, "hash", "") not in delete_hashes
        ]


def torrent_obj(**kwargs):
    defaults = {
        "name": "Ubuntu ISO",
        "hash": "abcdef123456",
        "state": "downloading",
        "progress": 0.5,
        "dlspeed": 2048,
        "upspeed": 1024,
        "total_size": 2_000_000,
        "completed": 1_000_000,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def manager_with(client: FakeClient) -> torrent.TorrentManager:
    manager = torrent.TorrentManager(host="qb", port=8080, username="u", password="p")
    manager.qbt_client = client
    return manager


def test_fmt_bytes_compact_decimal_boundaries():
    assert torrent.fmt_bytes_compact_decimal(-1) == "0B"
    assert torrent.fmt_bytes_compact_decimal(999) == "999B"
    assert torrent.fmt_bytes_compact_decimal(1_500) == "1.5KB"
    assert torrent.fmt_bytes_compact_decimal(2_000_000) == "2.0MB"


def test_add_magnet_extracts_display_name():
    client = FakeClient()
    manager = manager_with(client)

    result = manager.add_magnet("magnet:?xt=urn:btih:abc&dn=Ubuntu+ISO")

    assert "Ubuntu ISO" in result
    assert client.added == [
        {"urls": "magnet:?xt=urn:btih:abc&dn=Ubuntu+ISO", "save_path": "/downloads"}
    ]


def test_name_based_torrent_actions_and_previews():
    client = FakeClient([torrent_obj(), torrent_obj(name="Other", hash="222")])
    manager = manager_with(client)

    assert manager.stop_by_name("ubuntu").startswith("Paused:")
    assert client.paused == [{"hashes": "abcdef123456"}]
    assert manager.start_by_name("ubuntu").startswith("Resumed:")
    assert client.resumed == [{"hashes": "abcdef123456"}]

    preview = manager.preview_by_name("ubuntu")
    assert "Matching torrents" in preview
    assert "Ubuntu ISO" in preview

    assert manager.delete_by_name("other", delete_files=False).startswith("Deleted")
    assert client.deleted[-1] == {"hashes": "222", "delete_files": False}


def test_name_based_torrent_actions_handle_no_matches_and_missing_hashes(monkeypatch):
    manager = manager_with(FakeClient([torrent_obj(hash=None)]))

    assert manager.stop_by_name("missing") == "No matching torrents found."
    assert (
        manager.start_by_name("ubuntu")
        == "Found matching torrents but could not determine their hashes."
    )
    assert (
        manager.delete_by_name("ubuntu")
        == "Found matching torrents but could not determine their hashes."
    )

    monkeypatch.setattr(manager, "_call_pause_resume", Mock(return_value=False))
    assert (
        manager.stop_by_name("ubuntu")
        == "Found matching torrents but could not determine their hashes."
    )


def test_status_and_torrent_list_formatting():
    client = FakeClient(
        [
            torrent_obj(),
            torrent_obj(
                name="Broken Size",
                hash="222",
                total_size="not-int",
                completed="bad",
                progress=0.25,
            ),
        ]
    )
    manager = manager_with(client)

    status = manager.get_status()
    listing = manager.get_torrent_list()

    assert "Ubuntu ISO" in status
    assert "1.0MB/2.0MB" in status
    assert listing[0]["hash"] == "abcdef123456"
    assert listing[0]["size_summary"] == "1.0MB/2.0MB"
    assert listing[1]["size_summary"] == ""


def test_hash_based_torrent_actions():
    client = FakeClient([torrent_obj()])
    manager = manager_with(client)

    assert manager.info_by_hash("abc").startswith("<b>Ubuntu ISO</b>")
    assert manager.stop_by_hash("abc").startswith("⏸️ Paused:")
    assert manager.start_by_hash("abc").startswith("▶️ Resumed:")
    assert manager.delete_by_hash("abc", delete_files=True).startswith("🗑️ Deleted:")
    assert manager.info_by_hash("missing") == "Torrent not found."


def test_missing_files_preview_and_clean():
    client = FakeClient(
        [
            torrent_obj(name="Missing One", state="missingFiles"),
            torrent_obj(name="Complete", hash="222", state="uploading"),
        ]
    )
    manager = manager_with(client)

    matches = manager.find_missing_files_torrents()
    assert matches == [
        {"name": "Missing One", "hash": "abcdef123456", "state": "missingfiles"}
    ]
    assert "Missing One" in manager.preview_missing_files()
    assert "Cleaned 1 torrent" in manager.clean_missing_files(delete_files=True)


def test_call_delete_handles_empty_and_failed_verification():
    client = FakeClient([torrent_obj()])
    manager = manager_with(client)

    assert manager._call_delete([], delete_files=True) is False

    def no_delete(**kwargs):
        client.deleted.append(kwargs)

    client.torrents_delete = no_delete
    assert manager._call_delete(["abcdef123456"], delete_files=True) is False


def test_pause_resume_handles_empty_and_unknown_client_failures():
    client = FakeClient([torrent_obj()])
    manager = manager_with(client)

    assert manager._call_pause_resume([], "pause") is False

    def fail(**kwargs):
        raise RuntimeError("boom")

    client.torrents_pause = fail
    assert manager._call_pause_resume(["abcdef123456"], "pause") is False
