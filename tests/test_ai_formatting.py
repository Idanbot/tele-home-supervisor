from tele_home_supervisor.handlers import ai


def test_format_text_trims_and_keeps_markdown() -> None:
    text = "  Title\n\n- **Bold** item\n- _Italic_ item\n- Code: `x-y`\n  "
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_format_text_streaming_appends_cursor() -> None:
    text = "Streaming answer with *markdown* and hyphen: AQ-S820W"
    out = ai._format_text(text, done=False)
    assert out == f"{text} ▌"


def test_format_text_empty_returns_thinking() -> None:
    assert ai._format_text("   ", done=True) == "⏳ thinking..."


def test_real_answer_preserved_blocks_and_lists() -> None:
    text = """
The Existence of Aliens

While there is no definitive proof, there are many reasons to believe that the
possibility of life existing elsewhere in the universe is quite high.

Reasons:
- Over 4,000 exoplanets have been discovered so far.
- Biosignatures: Astronomers search for oxygen, methane, or other biomarkers.
- The study of extremophiles shows life can thrive in many environments.

Notable Examples:
- The Roswell Incident (1947)
- The Rendlesham Forest Incident (1980)
- The Phoenix Lights (1997)
"""
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_watch_comparison_preserved() -> None:
    text = """
Short answer: both are good, but pick based on use case.

Casio AQ-S820W
- Analog + digital, solar, thermometer.
- More outdoorsy; slightly bulkier.

Casio AE1200WH
- World time, "Casio Royale" vibe.
- Thinner and more retro.

If you want solar + analog, pick AQ-S820W. If you want compact + world time, pick AE1200WH.
"""
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_code_block_preserved() -> None:
    text = """
Here is a quick example:

```python
def hello(name: str) -> str:
    return f"Hello, {name}"
```
"""
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_inline_code_and_links_preserved() -> None:
    text = (
        "Use `docker compose` (not `docker-compose`) and see "
        "[docs](https://docs.docker.com/compose/)."
    )
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_emojis_and_punctuation_preserved() -> None:
    text = "Status: ✅ success, ⚠️ warning, ❌ failure. Rate: 3.5/5."
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_brackets_parentheses_and_hyphens_preserved() -> None:
    text = "Model (AQ-S820W) vs [AE1200WH] - choose based on size/weight."
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_real_answer_underscores_and_backslashes_preserved() -> None:
    text = r"Use env var MY_VAR and path C:\tools\bin\app.exe"
    out = ai._format_text(text, done=True)
    assert out == text.strip()


def test_streaming_does_not_add_extra_space_when_present() -> None:
    text = "Already has trailing space "
    out = ai._format_text(text, done=False)
    assert out == f"{text}▌"


def test_streaming_adds_space_when_missing() -> None:
    text = "No trailing space"
    out = ai._format_text(text, done=False)
    assert out == f"{text} ▌"
