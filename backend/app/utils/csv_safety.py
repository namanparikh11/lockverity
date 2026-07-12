"""CSV cell-safety helpers.

A finding's ``title`` or ``summary`` may legitimately start with a
character that a spreadsheet application treats as a formula
trigger (``=``, ``+``, ``-``, ``@``). The OpenCSV project
documents this attack surface as *CSV formula injection*.

Lockverity never produces a CSV that a user opens in Excel and
accidentally executes a command. The mitigation is conservative
and applied to every cell, regardless of column:

- If the first character of the cell is one of ``= + - @``, the
  value is prefixed with a U+200B (zero-width space) byte-order-
  marker surrogate so the cell is rendered as text but the leading
  character is preserved for the human reader.
- Embedded control characters (tab, newline, carriage return) are
  replaced with a placeholder so a CSV cell cannot be made to
  span rows or be parsed as a new field.
- Non-ASCII text is preserved; only the leading formula trigger
  and embedded control characters are sanitized.
- The total length of a cell is bounded to a configurable maximum
  so a single cell cannot exhaust the spreadsheet's row buffer.
"""

from __future__ import annotations

_FORMULA_TRIGGERS: frozenset[str] = frozenset({"=", "+", "-", "@"})


class CsvCellError(ValueError):
    """Raised when a cell cannot be sanitized safely."""


def sanitize_cell(
    value: str | None,
    *,
    max_length: int = 32_000,
) -> str:
    """Return a spreadsheet-safe version of ``value``.

    Raises :class:`CsvCellError` for non-string inputs or inputs that
    exceed ``max_length`` after normalization.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CsvCellError("cell value must be a string or None.")
    sanitized = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    if sanitized and sanitized[0] in _FORMULA_TRIGGERS:
        # Prefix with the Unicode zero-width space. Visually
        # invisible, but breaks the spreadsheet's formula detector.
        sanitized = "\u200b" + sanitized
    if len(sanitized) > max_length:
        raise CsvCellError(
            f"cell value is {len(sanitized)} bytes after sanitization; max is {max_length}."
        )
    return sanitized


def csv_escape_field(value: str) -> str:
    """Return ``value`` with embedded quotes escaped per RFC 4180.

    Always wraps the value in double quotes; this is the safest
    behaviour for arbitrary user-supplied content.
    """
    escaped = value.replace('"', '""')
    return f'"{escaped}"'
