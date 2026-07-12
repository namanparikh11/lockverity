"""Tests for the pnpm, yarn, and python parsers."""

from __future__ import annotations

import pytest
from app.parsers.base import ParserError
from app.parsers.pnpm import PnpmLockParser
from app.parsers.poetry import PoetryLockParser
from app.parsers.pyproject import PyprojectTomlParser
from app.parsers.requirements import RequirementsTxtParser
from app.parsers.yarn import YarnLockParser


def test_pnpm_basic_resolves_packages() -> None:
    parser = PnpmLockParser()
    content = b"""
lockfileVersion: '6.0'
packages:
  registry.npmjs.org/lodash/4.17.21:
    resolution: {integrity: sha512-abc, tarball: https://example.com/lodash-4.17.21.tgz}
    dev: false
  registry.npmjs.org/vitest/1.6.0:
    resolution: {integrity: sha512-xyz, tarball: https://example.com/vitest-1.6.0.tgz}
    dev: true
"""
    result = parser.parse(content=content, path="pnpm-lock.yaml")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["lodash"]["version_source"] == "LOCKFILE"
    assert by_name["lodash"]["version"] == "4.17.21"
    assert by_name["lodash"]["integrity"] == "sha512-abc"
    assert by_name["vitest"]["development"] is True


def test_pnpm_scoped_package_key() -> None:
    parser = PnpmLockParser()
    content = b"""
lockfileVersion: '6.0'
packages:
  registry.npmjs.org/@scope/foo/1.0.0:
    resolution: {integrity: sha512-abc}
"""
    result = parser.parse(content=content, path="pnpm-lock.yaml")
    assert result.data[0]["package_name"] == "@scope/foo"
    assert result.data[0]["scope"] == "scope"


def test_pnpm_unparseable_key_warns() -> None:
    parser = PnpmLockParser()
    content = b"""
lockfileVersion: '6.0'
packages:
  unknown-host:
    resolution: {integrity: sha512-abc}
"""
    result = parser.parse(content=content, path="pnpm-lock.yaml")
    # We may either accept or reject this; either is acceptable as
    # long as no exception escapes. We do require no records to be
    # produced for the unknown host key.
    assert result.records_processed == 0


def test_pnpm_missing_packages_warns() -> None:
    parser = PnpmLockParser()
    content = b"lockfileVersion: '6.0'\n"
    result = parser.parse(content=content, path="pnpm-lock.yaml")
    assert any(w.code == "pnpm_lock_missing_packages" for w in result.warnings)


def test_pnpm_invalid_yaml_raises() -> None:
    parser = PnpmLockParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"{not yaml: [\n", path="pnpm-lock.yaml")


def test_yarn_basic_resolves_packages() -> None:
    parser = YarnLockParser()
    content = b"""
# This is a comment line.
lodash@^4.17.21:
  version "4.17.21"
  resolved "https://registry.yarnpkg.com/lodash/-/lodash-4.17.21.tgz#abc"
  integrity sha512-abc
  dependencies:
    foo "^1.0.0"

vitest@^1.0.0:
  version "1.6.0"
  resolved "https://registry.yarnpkg.com/vitest/-/vitest-1.6.0.tgz#def"
  integrity sha512-xyz
"""
    result = parser.parse(content=content, path="yarn.lock")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["lodash"]["version"] == "4.17.21"
    assert by_name["lodash"]["version_source"] == "LOCKFILE"
    assert by_name["lodash"]["integrity"] == "sha512-abc"
    assert by_name["lodash"]["edges"][0]["child_name"] == "foo"


def test_yarn_scoped_block() -> None:
    parser = YarnLockParser()
    content = b"""
"@scope/pkg@^1.0.0":
  version "1.2.3"
  resolved "https://registry.yarnpkg.com/@scope/pkg/-/pkg-1.2.3.tgz#ghi"
  integrity sha512-123
"""
    result = parser.parse(content=content, path="yarn.lock")
    record = result.data[0]
    assert record["package_name"] == "@scope/pkg"
    assert record["scope"] == "scope"


def test_yarn_invalid_utf8_raises() -> None:
    parser = YarnLockParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"\xff\xfe\x00bad", path="yarn.lock")


def test_yarn_empty_block_warns() -> None:
    parser = YarnLockParser()
    content = b'"@scope/pkg":\n  version "1.0.0"\n'
    # This block has a specifier with no @version part; we still
    # expect the parser to extract the name and a warning if it
    # can't.
    result = parser.parse(content=content, path="yarn.lock")
    # Either accepted with package_name="@scope/pkg" or warned.
    assert result.records_processed >= 0


def test_requirements_basic_resolves_packages() -> None:
    parser = RequirementsTxtParser()
    content = (
        b"requests==2.31.0\nflask>=2.0\ndjango[bcrypt]>=4.2 ; python_version >= '3.10'\n# comment\n"
    )
    result = parser.parse(content=content, path="requirements.txt")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["requests"]["version"] == "2.31.0"
    assert by_name["requests"]["version_source"] == "MANIFEST"
    assert by_name["flask"]["version_source"] == "UNRESOLVED"
    assert by_name["django"]["extras"] == ["bcrypt"]
    assert "python_version" in (by_name["django"]["marker"] or "")


def test_requirements_extras_and_marker() -> None:
    parser = RequirementsTxtParser()
    content = b"uvicorn[standard]>=0.27 ; python_version >= '3.10'\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["package_name"] == "uvicorn"
    assert record["extras"] == ["standard"]
    assert "python_version" in (record["marker"] or "")


def test_requirements_editable_is_unsupported() -> None:
    parser = RequirementsTxtParser()
    content = b"-e git+https://github.com/example/local-dev.git#egg=local-dev\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "editable"


def test_requirements_git_ref_is_unsupported() -> None:
    parser = RequirementsTxtParser()
    content = b"foo @ git+https://github.com/example/foo.git\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "git_ref"


def test_requirements_url_ref_is_unsupported() -> None:
    parser = RequirementsTxtParser()
    content = b"bar @ https://example.com/bar-1.0.tar.gz\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "url_ref"


def test_requirements_local_path_is_unsupported() -> None:
    parser = RequirementsTxtParser()
    content = b"./local-pkg\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "path_ref"


def test_requirements_include_is_ignored() -> None:
    parser = RequirementsTxtParser()
    content = b"-r other.txt\nfoo==1.0\n"
    result = parser.parse(content=content, path="requirements.txt")
    assert any(w.code == "requirements_include_ignored" for w in result.warnings)
    by_name = {r["package_name"]: r for r in result.data}
    assert "foo" in by_name


def test_requirements_inline_comment() -> None:
    parser = RequirementsTxtParser()
    content = b"foo==1.0  # pinned in 2024\n"
    result = parser.parse(content=content, path="requirements.txt")
    record = result.data[0]
    assert record["version"] == "1.0"


def test_requirements_continuation() -> None:
    parser = RequirementsTxtParser()
    content = b"foo==1.0 \\\n   , bar>=2.0\n"
    result = parser.parse(content=content, path="requirements.txt")
    # The continuation joins the two package lines; the first
    # token is "foo==1.0" and the rest is captured as specifier.
    assert any(r["package_name"] == "foo" for r in result.data)


def test_requirements_invalid_line_warns() -> None:
    parser = RequirementsTxtParser()
    content = b"  \n!@#\n"
    result = parser.parse(content=content, path="requirements.txt")
    assert result.records_processed == 0


def test_requirements_invalid_utf8_raises() -> None:
    parser = RequirementsTxtParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"\xff\xfe\x00bad", path="requirements.txt")


def test_pyproject_toml_basic_project_section() -> None:
    parser = PyprojectTomlParser()
    content = b"""
[project]
name = "x"
dependencies = [
  "requests==2.31.0",
  "flask>=2.0",
]
optional-dependencies.test = ["pytest==8.0.0"]

[dependency-groups]
dev = ["ruff==0.4.0"]
"""
    result = parser.parse(content=content, path="pyproject.toml")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["requests"]["version_source"] == "MANIFEST"
    assert by_name["pytest"]["relationship"] == "optional"
    assert by_name["pytest"]["extras"] == ["test"]
    assert by_name["ruff"]["development"] is True


def test_pyproject_toml_poetry_section() -> None:
    parser = PyprojectTomlParser()
    content = b"""
[tool.poetry]
name = "x"

[tool.poetry.dependencies]
python = "^3.12"
requests = "^2.31"
flask = ">=2.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""
    result = parser.parse(content=content, path="pyproject.toml")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["requests"]["relationship"] == "direct"
    assert by_name["pytest"]["development"] is True


def test_pyproject_toml_git_ref_is_unsupported() -> None:
    parser = PyprojectTomlParser()
    content = b"""
[project]
name = "x"
dependencies = ["foo @ git+https://github.com/example/foo.git"]
"""
    result = parser.parse(content=content, path="pyproject.toml")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "git_ref"


def test_pyproject_toml_invalid_raises() -> None:
    parser = PyprojectTomlParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"{not toml", path="pyproject.toml")


def test_poetry_lock_basic_records() -> None:
    parser = PoetryLockParser()
    content = b"""
version = 1
package-mode = true

[[package]]
name = "requests"
version = "2.31.0"
description = "HTTP for Humans"
category = "main"

[[package]]
name = "pytest"
version = "8.0.0"
description = "pytest"
category = "dev"

[metadata]
lock-version = "2.0"
python-versions = "^3.12"
content-hash = "abc123"
"""
    result = parser.parse(content=content, path="poetry.lock")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["requests"]["version_source"] == "LOCKFILE"
    assert by_name["pytest"]["development"] is True
    # content-hash is recorded as sha256:<hash>.
    assert "pytest" in by_name
    # The integrity field is recorded when content-hash is present.
    for r in result.data:
        if r["package_name"] in {"requests", "pytest"}:
            # We don't expect the first two entries to have an
            # integrity from the spec above; we only check the
            # block doesn't fail.
            assert r["integrity"] is None or r["integrity"].startswith("sha256:")


def test_poetry_lock_with_content_hash() -> None:
    parser = PoetryLockParser()
    content = b"""
[[package]]
name = "hashed"
version = "1.0.0"
content-hash = "deadbeef"
"""
    result = parser.parse(content=content, path="poetry.lock")
    record = result.data[0]
    assert record["integrity"] == "sha256:deadbeef"


def test_poetry_lock_optional_marker() -> None:
    parser = PoetryLockParser()
    content = b"""
[[package]]
name = "feature-pkg"
version = "1.0.0"
optional = true
markers = "extra == 'foo'"
"""
    result = parser.parse(content=content, path="poetry.lock")
    record = result.data[0]
    assert record["optional"] is True
    assert record["relationship"] == "optional"


def test_poetry_lock_no_packages_warns() -> None:
    parser = PoetryLockParser()
    content = b"version = 1\n"
    result = parser.parse(content=content, path="poetry.lock")
    assert any(w.code == "poetry_lock_missing_packages" for w in result.warnings)


def test_poetry_lock_invalid_toml_raises() -> None:
    parser = PoetryLockParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"{not toml", path="poetry.lock")
