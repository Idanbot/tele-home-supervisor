from tele_home_supervisor.handlers import ai


def test_markdown_preserves_basic_styles() -> None:
    text = "Bold **b**, __bb__, italic *i*, _ii_, ~~s~~."
    out = ai._to_markdown_v2(text, done=True)
    assert "**b**" in out
    assert "__bb__" in out
    assert "*i*" in out
    assert "_ii_" in out
    assert "~~s~~" in out


def test_markdown_escapes_plain_asterisk() -> None:
    text = "5 * 3"
    out = ai._to_markdown_v2(text, done=True)
    assert "5 \\* 3" in out


def test_inline_code_preserved_and_links_escaped() -> None:
    text = "value is `x*y` and [link](https://a.b)"
    out = ai._to_markdown_v2(text, done=True)
    assert "`x*y`" in out
    assert "\\[link\\]\\(https://a\\.b\\)" in out


def test_code_fence_preserved_with_language() -> None:
    text = "```py\nprint(1)\n```\nAfter"
    out = ai._to_markdown_v2(text, done=True)
    assert "```py\nprint(1)\n```" in out
    assert out.endswith("After")


def test_format_text_strips_html_and_escapes() -> None:
    text = "Hello <b>world</b>!"
    out = ai._format_text(text, done=True)
    assert "<b>" not in out
    assert "Hello world\\!" in out


def test_streaming_appends_closing_fence_when_unbalanced() -> None:
    text = "```py\nprint('hi')\n"
    out = ai._to_markdown_v2(text, done=False)
    tail = out.splitlines()[-1]
    assert tail and set(tail) == {"`"}
    assert len(tail) >= 3


def test_streaming_appends_closing_backtick_when_unbalanced_inline() -> None:
    text = "Inline `code"
    out = ai._to_markdown_v2(text, done=False)
    assert out.endswith("`")


def test_streaming_does_not_append_when_balanced() -> None:
    text = "```txt\nok\n```\nInline `code`."
    out = ai._to_markdown_v2(text, done=False)
    assert not out.endswith("```")
    assert not out.endswith("`")


def test_inline_backticks_inside_text_preserved() -> None:
    text = "Use `x_y` not x_y."
    out = ai._to_markdown_v2(text, done=True)
    assert "`x_y`" in out
    assert "x\\_y" in out


def test_format_text_streaming_adds_cursor() -> None:
    text = "Answer"
    out = ai._format_text(text, done=False)
    assert out.endswith("▌")


def test_format_text_escapes_exclamation_from_stream() -> None:
    # Matches the observed Ollama stream "Hello" + "!" -> "Hello!"
    out = ai._format_text("Hello!", done=True)
    assert out == "Hello\\!"


def test_format_text_streaming_escapes_and_cursor() -> None:
    out = ai._format_text("Hello!", done=False)
    assert out.endswith("▌")
    assert "Hello\\!" in out


def test_format_text_empty_returns_thinking() -> None:
    assert ai._format_text("   ", done=True) == "⏳ thinking..."


def test_sanitize_strips_angle_brackets() -> None:
    assert ai._sanitize_output("<b>Hello</b>") == "Hello"
