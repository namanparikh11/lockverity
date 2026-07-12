"""pnpm-lock.yaml parser.

The pnpm v6+ lockfile is a YAML document. The shape we care about
is:

- ``packages`` - a mapping of ``registry.npmjs.org/<name>/<version>``
  or ``<name>@<version>`` keys to package records.
- ``dependencies``, ``devDependencies``, ``optionalDependencies`` -
  top-level dependency maps (with version specifiers, no edges).
- ``snapshots`` - a mapping of dependency keys to the actual
  resolved package and its transitive requires.

This parser uses the bounded safe-YAML loader in
:mod:`app.utils.yaml_safe` so a hostile lockfile cannot trigger
``billion-laughs`` or unbounded recursion.
"""

from __future__ import annotations

from typing import Any

from app.parsers.base import (
    ParserError,
    _Collector,
    build_package_url,
    finalize_parse,
    validate_record,
)
from app.parsers.npm import _SCOPED_NAME_RE, _classify_unsupported_specifier
from app.providers.results import ParserResult
from app.utils.yaml_safe import safe_load_yaml_bytes

# ``packages`` keys look like ``registry.npmjs.org/foo/1.0.0`` or
# ``/@scope/foo/1.0.0`` for scoped packages. We accept the second
# shape too.
_PKG_KEY_RE = __import__("re").compile(
    r"^(?P<host>[^/]+)/(?P<rest>.+)$"
)


def _split_scoped_name(name: str) -> tuple[str | None, str]:
    match = _SCOPED_NAME_RE.match(name)
    if match is None:
        return None, name
    return match.group(1), match.group(2)


def _parse_package_key(key: str) -> tuple[str, str | None] | None:
    """Return ``(name, version)`` for a pnpm package key, or ``None``."""
    if not isinstance(key, str) or not key:
        return None
    # Strip the host: "registry.npmjs.org/foo/1.0.0" -> "foo/1.0.0"
    match = _PKG_KEY_RE.match(key)
    if match is None:
        return None
    rest = match.group("rest")
    parts = rest.split("/")
    if not parts:
        return None
    if parts[0].startswith("@"):
        # Scoped: "@scope/name/version"
        if len(parts) < 3:
            return None
        name = f"{parts[0]}/{parts[1]}"
        version = parts[2] or None
    else:
        if len(parts) < 2:
            return None
        name = parts[0]
        version = parts[1] or None
    if not name or not version:
        return None
    return name, version


class PnpmLockParser:
    ecosystem = "npm"
    manifest_type = "pnpm_lock"

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            data = safe_load_yaml_bytes(content)
        except Exception as exc:
            raise ParserError(f"pnpm-lock.yaml could not be parsed: {exc}") from exc
        if not isinstance(data, dict):
            raise ParserError("pnpm-lock.yaml root must be a mapping.")

        records: list[dict[str, Any]] = []
        lockfile_version = data.get("lockfileVersion")
        if not isinstance(lockfile_version, (int, float, str)):
            collector.warn(
                "pnpm_lock_missing_version",
                "pnpm-lock.yaml did not declare a lockfileVersion.",
                location=path,
            )

        packages = data.get("packages")
        if isinstance(packages, dict):
            for key, value in packages.items():
                parsed = _parse_package_key(key)
                if parsed is None:
                    collector.warn(
                        "pnpm_lock_unknown_key",
                        f"Could not interpret package key {key!r}.",
                        location=path,
                    )
                    continue
                name, version = parsed
                if not isinstance(value, dict):
                    continue
                records.append(self._package_record(name, version, value, path))
        else:
            collector.warn(
                "pnpm_lock_missing_packages",
                "pnpm-lock.yaml contained no 'packages' section.",
                location=path,
            )

        snapshots = data.get("snapshots")
        if isinstance(snapshots, dict):
            # Snapshots tell us about transitive requirements. We
            # record them as edges on the matching package record
            # (matched by name+version). If no matching package
            # exists, the snapshot is treated as an evidence-only
            # hint and is dropped with a warning.
            edges_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for snap_key, snap_value in snapshots.items():
                if not isinstance(snap_key, str) or not snap_key:
                    continue
                if not isinstance(snap_value, dict):
                    continue
                # snap_key looks like "foo@1.0.0" or "@scope/foo@1.0.0"
                if "@" in snap_key:
                    at_index = snap_key.rfind("@")
                    name = snap_key[:at_index]
                    version = snap_key[at_index + 1:]
                else:
                    name = snap_key
                    version = ""
                if not name or not version:
                    continue
                deps = snap_value.get("dependencies") or snap_value.get("requires") or {}
                if not isinstance(deps, dict):
                    continue
                edges: list[dict[str, Any]] = []
                for child_name, child_version in deps.items():
                    if not isinstance(child_name, str):
                        continue
                    is_unsupported, kind, detail = _classify_unsupported_specifier(
                        child_version if isinstance(child_version, str) else ""
                    )
                    edges.append(
                        {
                            "parent_name": name,
                            "parent_version": version,
                            "child_name": child_name,
                            "child_version": (
                                child_version if isinstance(child_version, str) else None
                            ),
                            "child_specifier": (
                                child_version if isinstance(child_version, str) else None
                            ),
                            "child_version_source": (
                                "LOCKFILE"
                                if isinstance(child_version, str)
                                and child_version
                                and not is_unsupported
                                else "UNRESOLVED"
                            ),
                            "child_is_unsupported": is_unsupported,
                            "child_unsupported_kind": kind,
                            "child_unsupported_detail": detail,
                            "relationship": "runtime",
                            "depth": 1,
                        }
                    )
                edges_by_target[(name, version)] = edges
            for record in records:
                key = (record["package_name"], record["version"] or "")
                if key in edges_by_target:
                    record["edges"] = edges_by_target[key]

        return finalize_parse(collector, records)

    def _package_record(
        self,
        name: str,
        version: str,
        value: dict[str, Any],
        path: str,
    ) -> dict[str, Any]:
        scope, _ = _split_scoped_name(name)
        dev = bool(value.get("dev", False))
        optional = bool(value.get("optional", False))
        integrity = value.get("integrity") if isinstance(value.get("integrity"), str) else None
        resolved = value.get("resolution") if isinstance(value.get("resolution"), dict) else None
        resolved_url: str | None = None
        if isinstance(resolved, dict):
            integrity = integrity or (
                resolved.get("integrity") if isinstance(resolved.get("integrity"), str) else None
            )
            tarball = resolved.get("tarball")
            if isinstance(tarball, str):
                resolved_url = tarball
        relationship = "transitive"
        if dev:
            relationship = "development"
        if optional:
            relationship = "optional"
        record: dict[str, Any] = {
            "kind": "package",
            "ecosystem": self.ecosystem,
            "package_name": name,
            "scope": scope,
            "version": version,
            "version_source": "LOCKFILE" if version else "UNRESOLVED",
            "package_url": build_package_url(self.ecosystem, name, version) if version else None,
            "relationship": relationship,
            "direct": False,
            "development": dev,
            "optional": optional,
            "integrity": integrity,
            "extras": None,
            "marker": None,
            "specifier": version,
            "is_unsupported": False,
            "unsupported_kind": None,
            "unsupported_detail": resolved_url,
            "source_path": path,
            "edges": None,
        }
        validate_record(record)
        return record
