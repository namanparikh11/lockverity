"""requirements.txt parser.

The parser is intentionally conservative: it reads lines, ignores
comments, joins backslash continuations, and emits one record per
``Requirement`` line. Hashes, environment markers, extras, and
exotic PEP 508 syntaxes are handled; git, URL, editable, and local
references are recorded as unsupported evidence and never
attempted.
"""

from __future__ import annotations

import re
from typing import Any

from app.parsers.base import (
    ParserError,
    _Collector,
    build_package_url,
    finalize_parse,
    validate_record,
)
from app.providers.results import ParserResult

_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$")
_EXTRAS_RE = re.compile(r"\[([^\]]+)\]")
_MARKER_RE = re.compile(r";\s*(.+)$")
_PIN_RE = re.compile(r"^(==|===|~=|>=|<=|!=|>|<)\s*([^\s,;]+)")
_HASH_RE = re.compile(r"\s+--hash=[^\s,;]+")


def _split_name_and_rest(raw: str) -> tuple[str, str]:
    """Return ``(name, rest)`` for a PEP 508 name token.

    The name is the leading identifier (alphanumeric plus ``-``,
    ``_``, and ``.``). The remainder of the line (which may
    include version specifiers, extras, and a ``;`` marker) is
    returned as ``rest``.
    """
    match = _NAME_RE.match(raw.strip())
    if match is None:
        raise ValueError(f"could not extract a name from {raw!r}")
    return match.group(1), match.group(2)


def _extract_extras(rest: str) -> list[str]:
    match = _EXTRAS_RE.search(rest)
    if match is None:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def _extract_marker(rest: str) -> str | None:
    # The marker is preceded by ';'. We must skip semicolons that
    # appear inside a quoted string, but requirements files
    # effectively never have quoted strings, so a simple split is
    # safe.
    match = _MARKER_RE.search(rest)
    if match is None:
        return None
    return match.group(1).strip()


def _classify_unsupported(ref: str) -> tuple[bool, str | None, str | None]:
    """Return ``(is_unsupported, kind, detail)`` for a requirements reference."""
    if not isinstance(ref, str) or not ref.strip():
        return False, None, None
    s = ref.strip()
    if s.startswith("-e ") or s.startswith("--editable "):
        return True, "editable", s
    # Handle the PEP 508 ``name @ ref`` syntax.
    if " @ " in s:
        _, _, ref_part = s.partition(" @ ")
        return _classify_unsupported(ref_part)
    if s.startswith("git+") or s.startswith("git://") or "git+" in s:
        return True, "git_ref", s
    if s.startswith("https://") or s.startswith("http://"):
        return True, "url_ref", s
    if s.startswith("file://") or s.startswith("./") or s.startswith("/") or s.startswith(".."):
        return True, "path_ref", s
    return False, None, None


def _parse_pin(rest: str) -> tuple[str | None, str]:
    """Return ``(version, version_source)`` for a pinned requirement."""
    cleaned = _HASH_RE.sub("", rest)
    match = _PIN_RE.search(cleaned)
    if match is None:
        # No pin. The version is unresolved.
        return None, "UNRESOLVED"
    op, version = match.group(1), match.group(2)
    if op == "==":
        return version, "MANIFEST"
    # ``===`` is also a pin per PEP 440.
    if op == "===":
        return version, "MANIFEST"
    # ``~=``, ``>=``, ``<=``, ``!=``, ``>``, ``<`` are ranges; the
    # version is unresolved from a vulnerability-intelligence
    # perspective.
    return version, "UNRESOLVED"


def _name_to_pypi_normalized(name: str) -> str:
    """Normalize a project name the same way ``packaging`` would.

    We do not depend on ``packaging``; we apply the public rules
    (lowercase, dashes for underscores) inline.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


class RequirementsTxtParser:
    ecosystem = "pypi"
    manifest_type = "requirements_txt"

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParserError(f"requirements.txt is not valid UTF-8: {exc}") from exc

        # Join backslash continuations first so a multiline
        # requirement is treated as a single line. The PEP 508 line
        # continuation rule is "trailing backslash followed by a
        # newline" and we only collapse the immediate continuation
        # (a single pass is enough because requirements files
        # rarely chain more than one continuation).
        joined = re.sub(r"\\\r?\n", " ", text)

        records: list[dict[str, Any]] = []
        seen_normalized: set[str] = set()
        for lineno, raw_line in enumerate(joined.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-"):
                # options block (e.g. -r other.txt, --index-url ...).
                # We do not follow includes for safety; record as
                # evidence but ignore. Editable references (-e /
                # --editable) are recorded as a record below.
                if line.startswith("-r ") or line.startswith("--requirement "):
                    collector.warn(
                        "requirements_include_ignored",
                        f"-r / --requirement at line {lineno} is not followed.",
                        location=path,
                    )
                elif line.startswith("-c ") or line.startswith("--constraints "):
                    collector.warn(
                        "requirements_constraints_ignored",
                        f"-c / --constraints at line {lineno} is not followed.",
                        location=path,
                    )
                elif line.startswith("-e ") or line.startswith("--editable "):
                    is_unsupported, kind, detail = _classify_unsupported(line)
                    if is_unsupported:
                        name = self._name_from_unsupported(line)
                        if name is None:
                            collector.warn(
                                "requirements_unknown_ref",
                                f"Could not derive a name from {line!r} at line {lineno}.",
                                location=path,
                            )
                            continue
                        normalized = _name_to_pypi_normalized(name)
                        if normalized in seen_normalized:
                            continue
                        seen_normalized.add(normalized)
                        record: dict[str, Any] = {
                            "kind": "package",
                            "ecosystem": self.ecosystem,
                            "package_name": name,
                            "scope": None,
                            "version": None,
                            "version_source": "UNRESOLVED",
                            "package_url": build_package_url(self.ecosystem, name, None),
                            "relationship": "direct",
                            "direct": True,
                            "development": False,
                            "optional": False,
                            "integrity": None,
                            "extras": None,
                            "marker": None,
                            "specifier": line,
                            "is_unsupported": True,
                            "unsupported_kind": kind,
                            "unsupported_detail": detail,
                            "source_path": path,
                            "edges": None,
                        }
                        validate_record(record)
                        records.append(record)
                    continue
                else:
                    collector.warn(
                        "requirements_option_ignored",
                        f"Unknown option at line {lineno}: {line!r}.",
                        location=path,
                    )
                continue

            # Strip inline comments (not inside extras). We look for
            # a "#" preceded by whitespace, per PEP 508.
            comment_index = _find_inline_comment(line)
            if comment_index >= 0:
                line = line[:comment_index].strip()
            if not line:
                continue

            is_unsupported, kind, detail = _classify_unsupported(line)
            if is_unsupported:
                name = self._name_from_unsupported(line)
                if name is None:
                    collector.warn(
                        "requirements_unknown_ref",
                        f"Could not derive a name from {line!r} at line {lineno}.",
                        location=path,
                    )
                    continue
                normalized = _name_to_pypi_normalized(name)
                if normalized in seen_normalized:
                    continue
                seen_normalized.add(normalized)
                record: dict[str, Any] = {
                    "kind": "package",
                    "ecosystem": self.ecosystem,
                    "package_name": name,
                    "scope": None,
                    "version": None,
                    "version_source": "UNRESOLVED",
                    "package_url": build_package_url(self.ecosystem, name, None),
                    "relationship": "direct",
                    "direct": True,
                    "development": False,
                    "optional": False,
                    "integrity": None,
                    "extras": None,
                    "marker": None,
                    "specifier": line,
                    "is_unsupported": True,
                    "unsupported_kind": kind,
                    "unsupported_detail": detail,
                    "source_path": path,
                    "edges": None,
                }
                validate_record(record)
                records.append(record)
                continue

            try:
                name, rest = _split_name_and_rest(line)
            except ValueError as exc:
                collector.warn(
                    "requirements_invalid_line",
                    f"Could not parse line {lineno}: {exc}",
                    location=path,
                )
                continue
            if not _NAME_RE.match(name):
                collector.warn(
                    "requirements_invalid_name",
                    f"Invalid package name at line {lineno}: {name!r}.",
                    location=path,
                )
                continue
            normalized = _name_to_pypi_normalized(name)
            if normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            extras = _extract_extras(rest)
            marker = _extract_marker(rest)
            version, version_source = _parse_pin(rest)
            record = {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": None,
                "version": version,
                "version_source": version_source,
                "package_url": (
                    build_package_url(self.ecosystem, name, version)
                    if version
                    else build_package_url(self.ecosystem, name, None)
                ),
                "relationship": "direct",
                "direct": True,
                "development": False,
                "optional": False,
                "integrity": None,
                "extras": extras or None,
                "marker": marker,
                "specifier": rest.strip() or None,
                "is_unsupported": False,
                "unsupported_kind": None,
                "unsupported_detail": None,
                "source_path": path,
                "edges": None,
            }
            validate_record(record)
            records.append(record)

        return finalize_parse(collector, records)

    def _name_from_unsupported(self, ref: str) -> str | None:
        """Best-effort: extract a project name from an editable/git/url ref."""
        s = ref.strip()
        # -e / --editable
        for prefix in ("-e ", "--editable "):
            if s.startswith(prefix):
                s = s[len(prefix) :].strip()
                break
        # Strip markers and version-like suffix.
        for sep in (";", "@", "#"):
            if sep in s:
                s = s.split(sep, 1)[0]
        # Strip URL prefix.
        for prefix in ("git+", "https://", "http://", "file://"):
            if s.startswith(prefix):
                s = s[len(prefix) :]
                break
        if not s:
            return None
        # Take the last path segment if we have a path.
        last = s.rsplit("/", 1)[-1]
        # Drop a trailing ".git" if any.
        if last.endswith(".git"):
            last = last[: -len(".git")]
        return last or None


def _find_inline_comment(line: str) -> int:
    """Return the index of the start of an inline ``#`` comment, or ``-1``.

    The PEP 508 rule is "a ``#`` preceded by whitespace starts a
    comment; a ``#`` immediately after a non-whitespace character
    is part of a URL fragment and is not a comment."
    """
    for i, char in enumerate(line):
        if char == "#" and (i == 0 or line[i - 1].isspace()):
            return i
    return -1
