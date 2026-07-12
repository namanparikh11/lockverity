"""Tests for :mod:`app.utils.csv_safety`."""

from __future__ import annotations

import pytest
from app.utils.csv_safety import CsvCellError, csv_escape_field, sanitize_cell


def test_passthrough_safe_text() -> None:
    assert sanitize_cell("hello world") == "hello world"


def test_none_renders_as_empty_string() -> None:
    assert sanitize_cell(None) == ""


def test_formula_trigger_equals_prefixed() -> None:
    assert sanitize_cell("=SUM(A1:A2)").startswith("\u200b=")


def test_formula_trigger_plus_prefixed() -> None:
    assert sanitize_cell("+1+1").startswith("\u200b+")


def test_formula_trigger_dash_prefixed() -> None:
    assert sanitize_cell("-2+3").startswith("\u200b-")


def test_formula_trigger_at_prefixed() -> None:
    assert sanitize_cell("@cmd").startswith("\u200b@")


def test_only_first_char_protected() -> None:
    # Only the leading character is neutralised; the rest of the
    # string is preserved as-is.
    sanitized = sanitize_cell("=safe text starting with = sign")
    assert sanitized == "\u200b=safe text starting with = sign"


def test_embedded_newline_replaced() -> None:
    sanitized = sanitize_cell("line1\nline2")
    assert "\n" not in sanitized
    assert sanitized == "line1 line2"


def test_embedded_carriage_return_replaced() -> None:
    sanitized = sanitize_cell("a\rb")
    assert "\r" not in sanitized


def test_embedded_tab_replaced() -> None:
    sanitized = sanitize_cell("a\tb")
    assert "\t" not in sanitized


def test_rejects_non_string() -> None:
    with pytest.raises(CsvCellError):
        sanitize_cell(123)  # type: ignore[arg-type]


def test_rejects_oversize_cell() -> None:
    with pytest.raises(CsvCellError):
        sanitize_cell("a" * 1001, max_length=1000)


def test_csv_escape_field_quotes_and_escapes() -> None:
    assert csv_escape_field('hello "world"') == '"hello ""world"""'
    assert csv_escape_field("plain") == '"plain"'
    assert csv_escape_field("with,comma") == '"with,comma"'


def test_dangerous_payload_neutralised() -> None:
    dangerous = "=cmd|'/c calc'!A1"
    sanitized = sanitize_cell(dangerous)
    # First char becomes a U+200B so the formula trigger is broken.
    assert not sanitized.startswith("=")
    assert sanitized.startswith("\u200b=")
