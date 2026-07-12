"""GitHub Actions workflow analyzer.

The analyzer walks the input file list for ``.github/workflows``
YAML files, loads them with the bounded safe-YAML loader, and
emits a deterministic set of :class:`FindingEvidence` records.
Each finding is anchored to a workflow file path and (when
possible) a YAML key path or line number.

The analyzer is a :class:`StaticAnalyzer`: it operates on the
bytes the orchestrator already holds and never executes any
content of the workflow.

Rules implemented:

- ``LOCK-WF-001`` Unpinned third-party action
- ``LOCK-WF-002`` Mutable container tag
- ``LOCK-WF-003`` write-all permissions
- ``LOCK-WF-004`` Missing explicit permissions
- ``LOCK-WF-005`` Dangerous pull_request_target combination
- ``LOCK-WF-006`` Untrusted checkout in privileged context
- ``LOCK-WF-007`` Untrusted expression inside run block
- ``LOCK-WF-008`` Persisted checkout credentials
- ``LOCK-WF-009`` Broad id-token permissions
- ``LOCK-WF-010`` Unsafe workflow_run usage
- ``LOCK-WF-011`` Secrets passed in command arguments
- ``LOCK-WF-012`` Unsafe artifact paths
- ``LOCK-WF-013`` Broad triggers
- ``LOCK-WF-014`` Unpinned setup / deployment action
- ``LOCK-WF-015`` Self-hosted runner on untrusted trigger
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.providers.results import (
    AnalyzerResult,
    FindingEvidence,
    ParserWarning,
)
from app.utils.finding_keys import stable_finding_key
from app.utils.yaml_safe import BoundedYamlError, safe_load_yaml_bytes

WORKFLOW_DIR_PREFIX = ".github/workflows/"
WORKFLOW_EXTENSIONS: tuple[str, ...] = (".yml", ".yaml")

# Self-hosted runner labels.
SELF_HOSTED_LABELS: frozenset[str] = frozenset(
    {"self-hosted", "self hosted", "linux", "windows", "macos", "ubuntu", "mac"}
)

# Default branches commonly used as mutable container tags.
MUTABLE_TAGS: frozenset[str] = frozenset(
    {"latest", "main", "master", "edge", "stable", "nightly", "dev", "develop", "release"}
)

# Actions considered setup/deploy by name prefix.
SETUP_PREFIXES: tuple[str, ...] = ("setup-", "configure-", "install-")
DEPLOY_PREFIXES: tuple[str, ...] = ("deploy-", "publish-", "release-")


@dataclass(frozen=True, slots=True)
class _LineIndex:
    """Maps dotted key paths in a workflow to their 1-indexed line numbers."""

    mapping: dict[tuple[str, ...], int]

    def lookup(self, path: Sequence[str]) -> int | None:
        if not path:
            return None
        return self.mapping.get(tuple(path))


def _index_lines_from_yaml(text: str) -> _LineIndex:
    """Walk the YAML text and return a best-effort key-path -> line index.

    The implementation is deliberately a *text* scan rather than a
    PyYAML node walk. It is good enough for finding the line of
    a top-level key or a job key; nested scalar values are
    approximate. False positives are not a security issue because
    every finding is still evidence-bound to the file path.
    """
    mapping: dict[tuple[str, ...], int] = {}
    # Track the indent stack.
    stack: list[tuple[int, str]] = []
    list_index_stack: list[int] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("- "):
            # List item - don't add to the key path, but record
            # the current path as a sequence index.
            while stack and stack[-1][0] >= indent:
                stack.pop()
                if list_index_stack:
                    list_index_stack.pop()
            list_index_stack.append(list_index_stack.pop() + 1 if list_index_stack else 1)
            continue
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        # Pop the stack down to the current indent.
        while stack and stack[-1][0] >= indent:
            stack.pop()
        new_path = (*tuple(s[1] for s in stack), key)
        mapping[new_path] = line_no
        stack.append((indent, key))
        list_index_stack = []
    return _LineIndex(mapping=mapping)


def _is_workflow_file(path: str) -> bool:
    # A file is a workflow when its normalized path contains the
    # ``.github/workflows/`` segment and ends with a YAML
    # extension. We accept the segment anywhere in the path so
    # synthetic fixtures can live under a fixture root.
    if WORKFLOW_DIR_PREFIX not in path:
        return False
    return path.endswith(WORKFLOW_EXTENSIONS)


def _evidence(
    rule_id: str,
    *,
    file_path: str,
    yaml_path: str,
    line: int | None,
    observed: dict[str, Any],
    title: str,
    summary: str,
    severity: str,
    confidence: str,
    remediation: str,
    limitations: str,
) -> FindingEvidence:
    evidence: dict[str, Any] = {
        "yaml_path": yaml_path,
        "observed": observed,
        "title": title,
        "summary": summary,
        "remediation": remediation,
        "limitations": limitations,
    }
    stable_key = stable_finding_key(
        rule_id,
        {
            "yaml_path": yaml_path,
            "observed": _stable_observed(observed),
            "file_path": file_path,
        },
    )
    evidence["stable_key"] = stable_key
    return FindingEvidence(
        rule_id=rule_id,
        location_path=file_path,
        location_start_line=line,
        location_end_line=line,
        raw=evidence,
    )


def _stable_observed(observed: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, order-independent view of ``observed`` for stable keys.

    We strip non-serializable bits and keep only the textual
    observations that the rule cares about.
    """

    def _norm(value: Any) -> Any:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return sorted(_norm(v) for v in value)
        if isinstance(value, dict):
            return {k: _norm(v) for k, v in sorted(value.items())}
        return repr(value)

    return {k: _norm(v) for k, v in sorted(observed.items())}


def _parse_uses(value: Any) -> tuple[str, str, str] | None:
    """Return ``(owner, repo, ref)`` for an action reference, or ``None``."""
    if not isinstance(value, str):
        return None
    if value.startswith("./") or value.startswith("docker://"):
        return None
    # owner/repo@ref
    if "@" not in value:
        owner, _, repo = value.partition("/")
        if not owner or not repo:
            return None
        return owner, repo, ""
    owner_repo, _, ref = value.partition("@")
    if "/" not in owner_repo:
        return None
    owner, _, repo = owner_repo.partition("/")
    if not owner or not repo:
        return None
    return owner, repo, ref


def _is_pinned(ref: str) -> bool:
    if not ref:
        return False
    # SHA pin: 40 hex characters (optionally wrapped in a tag).
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", ref))


def _is_third_party(owner: str, repo: str, first_party_owners: frozenset[str]) -> bool:
    return owner.lower() not in {o.lower() for o in first_party_owners}


def _is_self_hosted(runs_on: Any) -> bool:
    if isinstance(runs_on, str):
        return runs_on.strip().lower() in {label.lower() for label in SELF_HOSTED_LABELS}
    if isinstance(runs_on, list):
        for entry in runs_on:
            if isinstance(entry, str) and entry.strip().lower() in {
                label.lower() for label in SELF_HOSTED_LABELS
            }:
                return True
    if isinstance(runs_on, dict):
        group = runs_on.get("group") or runs_on.get("labels")
        if isinstance(group, list):
            for entry in group:
                if isinstance(entry, str) and entry.strip().lower() in {
                    label.lower() for label in SELF_HOSTED_LABELS
                }:
                    return True
        labels = runs_on.get("labels")
        if isinstance(labels, list):
            for entry in labels:
                if isinstance(entry, str) and entry.strip().lower() in {
                    label.lower() for label in SELF_HOSTED_LABELS
                }:
                    return True
    return False


def _on_keys(workflow: dict[str, Any]) -> list[str]:
    on_section = workflow.get(True) or workflow.get("on") or workflow.get("On") or workflow.get("ON")
    if on_section is None:
        return []
    if isinstance(on_section, str):
        return [on_section]
    if isinstance(on_section, list):
        return [s for s in on_section if isinstance(s, str)]
    if isinstance(on_section, dict):
        return [k for k in on_section if isinstance(k, str)]
    return []


def _has_on(on_keys: Iterable[str], *names: str) -> bool:
    wanted = {n.lower() for n in names}
    return any(key.lower() in wanted for key in on_keys)


def _has_untrusted_event(on_keys: Iterable[str]) -> bool:
    return _has_on(
        on_keys,
        "pull_request_target",
        "workflow_run",
    )


def _has_filter(on_section: Any, event: str) -> bool:
    """Return True if the on-section has any branch/path filter for ``event``."""
    if not isinstance(on_section, dict):
        return False
    inner = on_section.get(event)
    if not isinstance(inner, dict):
        return False
    return bool(any(key in inner for key in ("branches", "branches-ignore", "paths", "paths-ignore")))


def _scan_untrusted_expressions(text: str) -> list[str]:
    """Return a list of suspicious expressions found in ``text``."""
    # Things like ${{ github.event.issue.title }} or ${{ github.event.pull_request.body }}
    suspicious = (
        "github.event.issue.title",
        "github.event.issue.body",
        "github.event.pull_request.title",
        "github.event.pull_request.body",
        "github.event.pull_request.head.ref",
        "github.event.pull_request.head.label",
        "github.event.discussion.title",
        "github.event.discussion.body",
        "github.event.review.body",
        "github.event.comment.body",
        "github.event.pages.*.page_name",
        "github.event.workflow_run.head_branch",
        "github.event.workflow_run.head_commit.message",
        "github.head_ref",
    )
    found: list[str] = []
    for token in suspicious:
        if token in text:
            found.append(token)
    return found


def _scan_secret_interpolations(text: str) -> list[str]:
    """Return the names of secret references found in ``text``."""
    found: list[str] = []
    for match in re.finditer(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}", text):
        found.append(match.group(1))
    return found


def _is_checkout_step(uses: Any) -> bool:
    if not isinstance(uses, str):
        return False
    return uses.startswith("actions/checkout@") or uses == "actions/checkout"


@dataclass(slots=True)
class _WorkflowContext:
    file_path: str
    workflow: dict[str, Any]
    on_keys: list[str]
    on_section: Any
    permissions_top_level: Any
    line_index: _LineIndex


class GitHubActionsAnalyzer:
    """Static analyzer for GitHub Actions workflow files."""

    name = "github_actions"

    def __init__(
        self,
        *,
        first_party_owners: frozenset[str] = frozenset({"actions", "github"}),
    ) -> None:
        self._first_party = first_party_owners

    def analyze(
        self,
        *,
        files: list[tuple[str, bytes]],
        scan_run_id: int,
    ) -> AnalyzerResult:
        findings: list[FindingEvidence] = []
        warnings: list[ParserWarning] = []
        for path, content in files:
            if not _is_workflow_file(path):
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                warnings.append(
                    ParserWarning(
                        code="workflow_invalid_encoding",
                        message=str(exc),
                        location=path,
                    )
                )
                continue
            try:
                workflow = safe_load_yaml_bytes(content)
            except BoundedYamlError as exc:
                warnings.append(
                    ParserWarning(
                        code="workflow_invalid_yaml",
                        message=str(exc),
                        location=path,
                    )
                )
                findings.append(
                    _evidence(
                        "LOCK-WF-MALFORMED",
                        file_path=path,
                        yaml_path="$",
                        line=1,
                        observed={"error": str(exc)},
                        title="Workflow file is not valid YAML",
                        summary="The workflow file could not be parsed as YAML.",
                        severity="informational",
                        confidence="high",
                        remediation="Fix the YAML syntax error reported above.",
                        limitations="The analyzer did not run any rules on this file.",
                    )
                )
                continue
            if not isinstance(workflow, dict):
                warnings.append(
                    ParserWarning(
                        code="workflow_not_mapping",
                        message=f"{path}: root is not a mapping",
                        location=path,
                    )
                )
                continue
            line_index = _index_lines_from_yaml(text)
            on_keys = _on_keys(workflow)
            on_section = workflow.get(True) or workflow.get("on")
            permissions_top_level = workflow.get("permissions")
            context = _WorkflowContext(
                file_path=path,
                workflow=workflow,
                on_keys=on_keys,
                on_section=on_section,
                permissions_top_level=permissions_top_level,
                line_index=line_index,
            )
            findings.extend(self._run_rules(context))
        return AnalyzerResult(
            findings=tuple(findings),
            warnings=tuple(warnings),
        )

    # ----- rule runners -----
    def _run_rules(self, context: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        findings.extend(self._rule_unpinned_actions(context))
        findings.extend(self._rule_mutable_container_tags(context))
        findings.extend(self._rule_write_all_permissions(context))
        findings.extend(self._rule_missing_explicit_permissions(context))
        findings.extend(self._rule_dangerous_pull_request_target(context))
        findings.extend(self._rule_untrusted_checkout_in_privileged(context))
        findings.extend(self._rule_untrusted_expressions_in_run(context))
        findings.extend(self._rule_persisted_checkout_credentials(context))
        findings.extend(self._rule_broad_id_token_permissions(context))
        findings.extend(self._rule_unsafe_workflow_run(context))
        findings.extend(self._rule_secrets_in_command_arguments(context))
        findings.extend(self._rule_unsafe_artifact_paths(context))
        findings.extend(self._rule_broad_triggers(context))
        findings.extend(self._rule_unpinned_setup_deploy(context))
        findings.extend(self._rule_self_hosted_untrusted(context))
        return findings

    def _iter_jobs(self, workflow: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            return ()
        for name, body in jobs.items():
            if isinstance(name, str) and isinstance(body, dict):
                yield name, body
        return

    def _iter_steps(self, job: dict[str, Any]) -> Iterable[tuple[int, dict[str, Any]]]:
        steps = job.get("steps")
        if not isinstance(steps, list):
            return ()
        for index, step in enumerate(steps):
            if isinstance(step, dict):
                yield index, step
        return

    def _rule_unpinned_actions(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                parsed = _parse_uses(uses)
                if parsed is None:
                    continue
                owner, repo, ref = parsed
                if not _is_third_party(owner, repo, self._first_party):
                    continue
                if _is_pinned(ref):
                    continue
                yaml_path = f"jobs.{job_name}.steps.{step_index}.uses"
                line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                findings.append(
                    _evidence(
                        "LOCK-WF-001",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"uses": uses, "owner": owner, "repo": repo, "ref": ref},
                        title="Third-party action is not pinned to a SHA",
                        summary=(
                            f"Action {owner}/{repo} is referenced by {ref!r} rather than a "
                            "full 40-character commit SHA. A mutable tag can be replaced "
                            "by the upstream maintainer at any time."
                        ),
                        severity="medium",
                        confidence="high",
                        remediation=(
                            "Pin the action to a full commit SHA, e.g. "
                            f"{owner}/{repo}@<40-char-sha>."
                        ),
                        limitations=(
                            "The analyzer cannot verify the SHA is currently the latest; "
                            "Dependabot / Renovate are still recommended."
                        ),
                    )
                )
        return findings

    def _rule_mutable_container_tags(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith("docker://"):
                    continue
                # docker://image:tag
                ref = uses[len("docker://"):]
                if ":" not in ref:
                    continue
                tag = ref.rsplit(":", 1)[1]
                if tag in MUTABLE_TAGS or _is_numeric_only(tag):
                    yaml_path = f"jobs.{job_name}.steps.{step_index}.uses"
                    line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                    findings.append(
                        _evidence(
                            "LOCK-WF-002",
                            file_path=ctx.file_path,
                            yaml_path=yaml_path,
                            line=line,
                            observed={"uses": uses, "tag": tag},
                            title="Container image uses a mutable tag",
                            summary=(
                                f"Container tag {tag!r} is mutable; the image can be replaced "
                                "by its publisher at any time."
                            ),
                            severity="medium",
                            confidence="high",
                            remediation=(
                                "Pin the container to a content-addressable digest, e.g. "
                                f"{ref}@sha256:<digest>."
                            ),
                            limitations=(
                                "Pinning to a digest does not guarantee the publisher will "
                                "not rotate the underlying tags."
                            ),
                        )
                    )
        return findings

    def _rule_write_all_permissions(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        if ctx.permissions_top_level == "write-all":
            line = ctx.line_index.lookup(("permissions",))
            findings.append(
                _evidence(
                    "LOCK-WF-003",
                    file_path=ctx.file_path,
                    yaml_path="permissions",
                    line=line,
                    observed={"permissions": "write-all"},
                    title="Workflow declares write-all permissions",
                    summary=(
                        "Setting ``permissions: write-all`` grants every GITHUB_TOKEN scope "
                        "available to the workflow, which violates least-privilege."
                    ),
                    severity="high",
                    confidence="high",
                    remediation=(
                        "Replace ``permissions: write-all`` with a minimal mapping, e.g. "
                        "``permissions: { contents: read }``."
                    ),
                    limitations=(
                        "The default token scopes are repository-controlled; the finding is "
                        "based on the explicit value alone."
                    ),
                )
            )
        for job_name, job in self._iter_jobs(ctx.workflow):
            permissions = job.get("permissions")
            if permissions == "write-all":
                line = ctx.line_index.lookup(("jobs", job_name, "permissions"))
                findings.append(
                    _evidence(
                        "LOCK-WF-003",
                        file_path=ctx.file_path,
                        yaml_path=f"jobs.{job_name}.permissions",
                        line=line,
                        observed={"permissions": "write-all"},
                        title="Job declares write-all permissions",
                        summary=(
                            f"Job {job_name!r} grants every GITHUB_TOKEN scope available."
                        ),
                        severity="high",
                        confidence="high",
                        remediation=(
                            "Replace with a minimal mapping. Add ``permissions: { contents: read }`` "
                            "at the top level and override per-job only when necessary."
                        ),
                        limitations="Same as the workflow-level write-all finding.",
                    )
                )
        return findings

    def _rule_missing_explicit_permissions(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        if ctx.permissions_top_level is None:
            line = ctx.line_index.lookup(("permissions",)) or 1
            findings.append(
                _evidence(
                    "LOCK-WF-004",
                    file_path=ctx.file_path,
                    yaml_path="permissions",
                    line=line,
                    observed={"permissions": None},
                    title="Workflow does not declare explicit permissions",
                    summary=(
                        "No top-level ``permissions:`` key is set; the workflow inherits the "
                        "repository or organisation default token scope, which is often broader "
                        "than necessary."
                    ),
                    severity="medium",
                    confidence="medium",
                    remediation=(
                        "Add an explicit ``permissions:`` block, starting with "
                        "``permissions: { contents: read }`` and only adding scopes that are "
                        "actually used."
                    ),
                    limitations=(
                        "The repository's default permissions are not visible to the analyzer."
                    ),
                )
            )
        return findings

    def _rule_dangerous_pull_request_target(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        if not _has_on(ctx.on_keys, "pull_request_target"):
            return []
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                if not _is_checkout_step(uses):
                    continue
                with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
                ref = with_.get("ref") if isinstance(with_, dict) else None
                if not isinstance(ref, str):
                    continue
                if "pull_request.head" in ref or "head_ref" in ref or "head.sha" in ref:
                    yaml_path = f"jobs.{job_name}.steps.{step_index}.with.ref"
                    line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                    findings.append(
                        _evidence(
                            "LOCK-WF-005",
                            file_path=ctx.file_path,
                            yaml_path=yaml_path,
                            line=line,
                            observed={"ref": ref, "uses": uses},
                            title="pull_request_target checks out untrusted head code",
                            summary=(
                                "A job triggered by ``pull_request_target`` checks out the PR "
                                "head code, which runs untrusted code with the workflow's "
                                "privileged GITHUB_TOKEN."
                            ),
                            severity="critical",
                            confidence="high",
                            remediation=(
                                "Do not check out untrusted code in a ``pull_request_target`` "
                                "job. If the workflow must comment on PRs from forks, run the "
                                "checkout of the PR head in a separate ``pull_request`` job "
                                "with no secrets."
                            ),
                            limitations=(
                                "The analyzer does not evaluate ``if:`` conditions; a job that "
                                "only runs on labelled PRs may have a different risk profile."
                            ),
                        )
                    )
        return findings

    def _rule_untrusted_checkout_in_privileged(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        # Same as 005 in spirit; we only emit a 006 finding if the
        # checkout runs after a ``setup-go`` / ``setup-node`` with
        # credentials and the trigger is ``workflow_run``.
        if not _has_on(ctx.on_keys, "workflow_run"):
            return []
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                if not _is_checkout_step(uses):
                    continue
                with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
                ref = with_.get("ref") if isinstance(with_, dict) else None
                if isinstance(ref, str) and (
                    "workflow_run.head" in ref or "head_branch" in ref
                ):
                    yaml_path = f"jobs.{job_name}.steps.{step_index}.with.ref"
                    line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                    findings.append(
                        _evidence(
                            "LOCK-WF-006",
                            file_path=ctx.file_path,
                            yaml_path=yaml_path,
                            line=line,
                            observed={"ref": ref, "uses": uses},
                            title="Untrusted checkout in privileged context",
                            summary=(
                                "A ``workflow_run`` job checks out code from the triggering "
                                "workflow's head branch, which may be attacker-controlled."
                            ),
                            severity="high",
                            confidence="high",
                            remediation=(
                                "Avoid checking out untrusted commits in privileged jobs; "
                                "use a pinned ref or an artifact upload instead."
                            ),
                            limitations=(
                                "The analyzer does not evaluate ``if:`` conditions; the "
                                "actual exposure depends on the gates around the job."
                            ),
                        )
                    )
        return findings

    def _rule_untrusted_expressions_in_run(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                tokens = _scan_untrusted_expressions(run)
                if not tokens:
                    continue
                yaml_path = f"jobs.{job_name}.steps.{step_index}.run"
                line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                findings.append(
                    _evidence(
                        "LOCK-WF-007",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"tokens": tokens},
                        title="Untrusted expression in shell command",
                        summary=(
                            "A ``run:`` block interpolates attacker-controlled input "
                            "from a GitHub event. With an unquoted expansion this can lead "
                            "to script injection."
                        ),
                        severity="high",
                        confidence="high",
                        remediation=(
                            "Pass the value through an ``env:`` variable and quote it inside "
                            "the shell, e.g. ``run: echo \"$BODY\"`` with ``env: { BODY: ${{ "
                            "github.event.comment.body }} }``."
                        ),
                        limitations=(
                            "The analyzer does not evaluate the surrounding shell. Some "
                            "expansions are safe when properly quoted; the finding is the "
                            "presence of the expression, not the impact."
                        ),
                    )
                )
        return findings

    def _rule_persisted_checkout_credentials(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            checkout_persists: list[int] = []
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                if not _is_checkout_step(uses):
                    continue
                with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
                if "persist-credentials" in with_:
                    value = with_["persist-credentials"]
                    if value is True or (isinstance(value, str) and value.lower() == "true"):
                        checkout_persists.append(step_index)
                else:
                    # ``actions/checkout@v3`` defaults to
                    # ``persist-credentials: true``. We treat the
                    # default as a finding only when other steps
                    # in the job push to a remote.
                    if self._job_pushes_remote(job):
                        checkout_persists.append(step_index)
            for step_index in checkout_persists:
                yaml_path = f"jobs.{job_name}.steps.{step_index}.with.persist-credentials"
                line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                findings.append(
                    _evidence(
                        "LOCK-WF-008",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"persist_credentials": True},
                        title="Checkout persists credentials in git config",
                        summary=(
                            "The GITHUB_TOKEN is left configured in the local git config, "
                            "so subsequent steps can push to the repository using the "
                            "workflow's token."
                        ),
                        severity="medium",
                        confidence="medium",
                        remediation=(
                            "Set ``with: { persist-credentials: false }`` on the checkout "
                            "step unless the workflow explicitly needs to push."
                        ),
                        limitations=(
                            "The rule only flags the default when other steps in the job "
                            "look like a push to a remote; some legitimate jobs need the "
                            "token configured."
                        ),
                    )
                )
        return findings

    def _job_pushes_remote(self, job: dict[str, Any]) -> bool:
        for _, step in self._iter_steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if "git push" in run or "gh release" in run:
                return True
        return False

    def _rule_broad_id_token_permissions(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            permissions = job.get("permissions")
            if not isinstance(permissions, dict):
                continue
            id_token = permissions.get("id-token")
            if id_token != "write":  # noqa: S105 - literal permission value
                continue
            yaml_path = f"jobs.{job_name}.permissions.id-token"
            line = ctx.line_index.lookup(("jobs", job_name, "permissions"))
            findings.append(
                _evidence(
                    "LOCK-WF-009",
                    file_path=ctx.file_path,
                    yaml_path=yaml_path,
                    line=line,
                    observed={"id-token": "write"},
                    title="Broad id-token write permissions",
                    summary=(
                        "Granting ``id-token: write`` lets the job mint OIDC tokens for "
                        "cloud workloads. Combined with cloud-deploy actions, this is a "
                        "high-impact capability."
                    ),
                    severity="medium",
                    confidence="high",
                    remediation=(
                        "Restrict the id-token scope to the specific audience and cloud "
                        "provider, and only on jobs that genuinely need it."
                    ),
                    limitations=(
                        "The analyzer does not know which cloud action consumes the OIDC "
                        "token; the finding is the permission grant alone."
                    ),
                )
            )
        return findings

    def _rule_unsafe_workflow_run(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        if not _has_on(ctx.on_keys, "workflow_run"):
            return []
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            if not _is_self_hosted(job.get("runs-on")):
                continue
            yaml_path = f"jobs.{job_name}.runs-on"
            line = ctx.line_index.lookup(("jobs", job_name, "runs-on"))
            findings.append(
                _evidence(
                    "LOCK-WF-010",
                    file_path=ctx.file_path,
                    yaml_path=yaml_path,
                    line=line,
                    observed={"runs_on": job.get("runs-on")},
                    title="Unsafe workflow_run on self-hosted runner",
                    summary=(
                        "A ``workflow_run`` job runs on a self-hosted runner, which means "
                        "the runner executes the triggered workflow's code with the "
                        "self-hosted runner's privileges."
                    ),
                    severity="high",
                    confidence="high",
                    remediation=(
                        "Use ephemeral GitHub-hosted runners for ``workflow_run`` jobs; if "
                        "self-hosted is unavoidable, isolate the runner and gate the job "
                        "with strict ``if:`` conditions."
                    ),
                    limitations=(
                        "The analyzer does not know the runner's isolation profile."
                    ),
                )
            )
        return findings

    def _rule_secrets_in_command_arguments(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                secret_names = _scan_secret_interpolations(run)
                if not secret_names:
                    continue
                yaml_path = f"jobs.{job_name}.steps.{step_index}.run"
                line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                findings.append(
                    _evidence(
                        "LOCK-WF-011",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"secret_names": secret_names},
                        title="Secrets interpolated into shell command",
                        summary=(
                            "A secret value is interpolated directly into a ``run:`` block. "
                            "Even with quoting, a leak via process listings, debug output, "
                            "or echoing the command is possible."
                        ),
                        severity="high",
                        confidence="high",
                        remediation=(
                            "Pass secrets through ``env:`` variables and reference them as "
                            "environment variables, not as inline command arguments. Mask "
                            "the values via ``::add-mask::`` if they must be echoed."
                        ),
                        limitations=(
                            "The analyzer flags the *presence* of the interpolation. The "
                            "actual exposure depends on the surrounding shell."
                        ),
                    )
                )
        return findings

    def _rule_unsafe_artifact_paths(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith("actions/upload-artifact@"):
                    continue
                with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
                path = with_.get("path") if isinstance(with_, dict) else None
                if not isinstance(path, str):
                    continue
                if "${{" in path or "github.event" in path or "github.workspace" in path:
                    yaml_path = f"jobs.{job_name}.steps.{step_index}.with.path"
                    line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                    findings.append(
                        _evidence(
                            "LOCK-WF-012",
                            file_path=ctx.file_path,
                            yaml_path=yaml_path,
                            line=line,
                            observed={"path": path},
                            title="Artifact path uses an interpolated expression",
                            summary=(
                                "An artifact path uses a workflow expression. A malicious "
                                "PR can influence the path and overwrite an artifact with "
                                "attacker-chosen content."
                            ),
                            severity="medium",
                            confidence="high",
                            remediation=(
                                "Use a static path for ``actions/upload-artifact`` and never "
                                "interpolate event data into it."
                            ),
                            limitations=(
                                "The finding is the expression; the actual impact depends on "
                                "what other artifacts are consumed by downstream jobs."
                            ),
                        )
                    )
        return findings

    def _rule_broad_triggers(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        findings: list[FindingEvidence] = []
        on_section = ctx.on_section
        if on_section is None:
            return findings
        # Workflows that fire on every push or every pull_request
        # with no branch filter.
        if isinstance(on_section, str) and on_section in {"push", "pull_request"}:
            yaml_path = f"on.{on_section}"
            line = ctx.line_index.lookup(("on",))
            findings.append(
                _evidence(
                    "LOCK-WF-013",
                    file_path=ctx.file_path,
                    yaml_path=yaml_path,
                    line=line,
                    observed={"on": on_section},
                    title="Broad trigger without branch filter",
                    summary=(
                        f"The workflow runs on every ``{on_section}`` event with no branch "
                        "filter. A malicious or accidental commit on any branch will trigger "
                        "the workflow with the workflow's privileges."
                    ),
                    severity="low",
                    confidence="high",
                    remediation=(
                        f"Add a ``branches:`` filter, e.g. ``on: {on_section}: branches: [main]``."
                    ),
                    limitations=(
                        "Tag-only pushes and ``branches-ignore`` are not interpreted here."
                    ),
                )
            )
        elif isinstance(on_section, dict):
            for event in ("push", "pull_request"):
                if event not in on_section:
                    continue
                inner = on_section.get(event)
                # ``on: push:`` (no value) parses as None and is
                # still a broad trigger; so is an empty dict. We
                # emit the finding for both.
                if inner is None:
                    inner_dict: dict = {}
                elif isinstance(inner, dict):
                    inner_dict = inner
                else:
                    continue
                if _has_filter(on_section, event):
                    continue
                yaml_path = f"on.{event}"
                line = ctx.line_index.lookup(("on",))
                findings.append(
                    _evidence(
                        "LOCK-WF-013",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"on": event, "filters": list(inner_dict.keys())},
                        title="Broad trigger without branch filter",
                        summary=(
                            f"The workflow runs on every ``{event}`` event with no branch "
                            "filter."
                        ),
                        severity="low",
                        confidence="high",
                        remediation=(
                            f"Add a ``branches:`` filter to ``on.{event}``."
                        ),
                        limitations=(
                            "Workflows that legitimately run on every branch (release "
                            "automation) may need to suppress this finding manually."
                        ),
                    )
                )
        return findings

    def _rule_unpinned_setup_deploy(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        # Same shape as 001 but limited to setup-*, deploy-*, etc.
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            for step_index, step in self._iter_steps(job):
                uses = step.get("uses")
                parsed = _parse_uses(uses)
                if parsed is None:
                    continue
                owner, repo, ref = parsed
                if not (repo.startswith(SETUP_PREFIXES) or repo.startswith(DEPLOY_PREFIXES)):
                    continue
                if _is_pinned(ref):
                    continue
                yaml_path = f"jobs.{job_name}.steps.{step_index}.uses"
                line = ctx.line_index.lookup(("jobs", job_name, "steps", str(step_index)))
                findings.append(
                    _evidence(
                        "LOCK-WF-014",
                        file_path=ctx.file_path,
                        yaml_path=yaml_path,
                        line=line,
                        observed={"uses": uses, "owner": owner, "repo": repo, "ref": ref},
                        title="Setup or deploy action is not pinned",
                        summary=(
                            f"Action {owner}/{repo} is a setup or deploy action and is "
                            "referenced by a mutable ref."
                        ),
                        severity="medium",
                        confidence="high",
                        remediation=(
                            "Pin to a full commit SHA. Setup and deploy actions sit on the "
                            "critical path of the workflow."
                        ),
                        limitations=(
                            "Some setup actions (e.g. ``actions/setup-python``) accept a "
                            "``with: python-version:`` argument that itself needs pinning."
                        ),
                    )
                )
        return findings

    def _rule_self_hosted_untrusted(self, ctx: _WorkflowContext) -> list[FindingEvidence]:
        if not _has_untrusted_event(ctx.on_keys):
            return []
        findings: list[FindingEvidence] = []
        for job_name, job in self._iter_jobs(ctx.workflow):
            if not _is_self_hosted(job.get("runs-on")):
                continue
            yaml_path = f"jobs.{job_name}.runs-on"
            line = ctx.line_index.lookup(("jobs", job_name, "runs-on"))
            findings.append(
                _evidence(
                    "LOCK-WF-015",
                    file_path=ctx.file_path,
                    yaml_path=yaml_path,
                    line=line,
                    observed={"runs_on": job.get("runs-on"), "on": ctx.on_keys},
                    title="Self-hosted runner on untrusted trigger",
                    summary=(
                        "A self-hosted runner executes a job that fires on an untrusted "
                        "trigger (``pull_request_target`` or ``workflow_run``). The runner's "
                        "host is then exposed to attacker-controlled code."
                    ),
                    severity="critical",
                    confidence="high",
                    remediation=(
                        "Move untrusted-trigger jobs to ephemeral GitHub-hosted runners, or "
                        "strictly gate the job with an ``if:`` condition and isolate the "
                        "self-hosted runner."
                    ),
                    limitations=(
                        "The analyzer does not know the runner's network isolation."
                    ),
                )
            )
        return findings


def _is_numeric_only(tag: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)*", tag))
