import pytest

from tele_home_supervisor import media


class DummyResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status
        self.reason = "OK" if status == 200 else "ERROR"
        self.ok = status >= 200 and status < 300


def test_imdb_debug_on_blocked(monkeypatch) -> None:
    def debug_sink(message: str, detail: str | None = None) -> None:
        entries.append((message, detail))

    def fake_get(*_args, **_kwargs):
        return DummyResponse("captcha", status=200)

    entries: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        media, "imdb_suggest", lambda *_args, **_kwargs: [{"id": "tt1234567"}]
    )
    monkeypatch.setattr(media.requests, "get", fake_get)

    with pytest.raises(RuntimeError):
        media.imdb_details("dune", debug_sink=debug_sink)

    assert entries
    assert "imdb blocked" in entries[0][0]


def test_rt_debug_on_missing_next_data(monkeypatch) -> None:
    entries: list[tuple[str, str | None]] = []

    def debug_sink(message: str, detail: str | None = None) -> None:
        entries.append((message, detail))

    def fake_fetch(url: str, accept: str = "text/html", **_kwargs) -> str:
        if accept == "application/json":
            return "{}"
        return "<html></html>"

    monkeypatch.setattr(media, "_fetch", fake_fetch)

    with pytest.raises(RuntimeError):
        media.rt_trending("movies", debug_sink=debug_sink)

    assert any("rt trending next data parse failed" in msg for msg, _ in entries)
