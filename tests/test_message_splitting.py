"""Tests for message splitting utility."""

from tele_home_supervisor.utils import split_telegram_message


def test_no_split_needed():
    """Test that short text is not split."""
    text = "Hello world"
    chunks = split_telegram_message(text, limit=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_preserves_content_basic():
    """Test that content is preserved across simple splits."""
    text = "Line 1\nLine 2\nLine 3\nLine 4"
    # Limit to roughly one line per chunk
    chunks = split_telegram_message(text, limit=10)

    # We expect multiple chunks
    assert len(chunks) > 1
    # First chunk has Line 1
    assert "Line 1" in chunks[0]
    # Last chunk has Line 4
    assert "Line 4" in chunks[-1]


def test_split_inside_code_block_retention():
    """Test that language identifiers are preserved across splits."""
    text = "start\n```python\nprint(1)\nprint(2)\nprint(3)\n```\nend"

    # Split small enough to break the code block
    # "start\n```python\nprint(1)\n" is ~25 chars
    chunks = split_telegram_message(text, limit=35)

    assert len(chunks) > 1

    # Chunk 0: "start", open python, print(1), FORCE CLOSE
    assert "print(1)" in chunks[0]
    assert chunks[0].strip().endswith("```")

    # Chunk 1: FORCE OPEN python, print(2)...
    assert chunks[1].strip().startswith("```python")
    assert "print(2)" in chunks[1]


def test_mixed_formatting_structure():
    """Test a realistic mix of text and code."""
    text = (
        "Header\n"
        "```bash\n"
        "echo 'long script part 1'\n"
        "echo 'long script part 2'\n"
        "```\n"
        "Footer"
    )
    # Split roughly in the middle of the script
    chunks = split_telegram_message(text, limit=40)

    assert len(chunks) >= 2

    # Chunk 1: Header + start of script + closing fence
    assert "Header" in chunks[0]
    assert "```bash" in chunks[0]
    assert chunks[0].strip().endswith("```")

    # Check that Footer is in the last chunk
    assert "Footer" in chunks[-1]

    # Check that the chunk containing Footer starts correctly if it was split inside code
    # (This is harder to assert strictly without knowing exactly where it split,
    # but we can check that *intermediate* chunks are valid)


def test_massive_single_line_fallback():
    """Test fallback for lines longer than the limit."""
    # 50 'A's
    text = "A" * 50
    chunks = split_telegram_message(text, limit=10)

    assert len(chunks) == 5
    assert all(len(c) == 10 for c in chunks)
    assert "".join(chunks) == text


def test_massive_line_inside_code_block():
    """Test a massive line inside a code block stays inside code blocks."""
    code = "A" * 50
    text = f"```go\n{code}\n```"

    # limit=20. Overhead is ~5 (```go\n).
    chunks = split_telegram_message(text, limit=20)

    # Every chunk (except maybe the very first/last wrapper) should be a valid code block
    for i, chunk in enumerate(chunks):
        stripped = chunk.strip()
        # It must start with a fence (either generic or go)
        assert stripped.startswith("```"), f"Chunk {i} start fail: {chunk}"
        # It must end with a fence
        assert stripped.endswith("```"), f"Chunk {i} end fail: {chunk}"

        # Internal checks for correct language propagation
        if i > 0 and i < len(chunks) - 1:
            # Middle chunks must propagate "go"
            assert stripped.startswith("```go")


def test_exact_limit_boundary():
    """Test behavior when content hits the limit exactly."""
    # "12345" is 5 chars. Limit 5.
    text = "12345\n67890"
    # Note: "12345\n" is 6 chars. So splitting at 5 should force "12345" then "\n..."
    # Or strict split.
    chunks = split_telegram_message(text, limit=5)

    assert len(chunks) >= 2
    assert "12345" in chunks[0]
    assert "67890" in chunks[-1]


def test_malformed_unclosed_block():
    """Test handling of a code block that never closes (common stream interruption)."""
    text = "start\n```python\nprint('forever')\nprint('more')\n"
    # Split between prints
    chunks = split_telegram_message(text, limit=35)

    assert len(chunks) > 1
    # Intermediate split MUST be closed
    assert chunks[0].strip().endswith("```")
    # Next part MUST be reopened
    assert chunks[1].strip().startswith("```python")
