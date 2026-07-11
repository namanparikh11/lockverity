# Threat model

The threat model is a living document. v0.1 focuses on the threats
that are most likely to be exercised by accident or by a curious
attacker uploading a malicious archive. Threats outside this
document are not necessarily unmitigated; they are simply out of
scope for the v0.1 review.

## Actors

- **Operator** - the person running Lockverity. They can upload
  archives and point the application at public GitHub repositories.
  They are *trusted* in the sense that they have shell access to
  the host, but their uploads are still treated as hostile input.
- **Upstream maintainer** - the author of a repository being
  scanned. They are not trusted; their manifests, workflows, and
  source code are user input.
- **External provider** - OSV, deps.dev, OpenSSF, GitHub. They are
  trusted to return the data they advertise, but their responses
  are still validated before being persisted.
- **Network attacker** - can observe and modify traffic between
  Lockverity and its upstream providers. We do not defend against
  network attackers in v0.1; deployment is expected to use TLS.

## Threats

### T1. Malicious archive causes arbitrary code execution

A user uploads a tarball or zip that, when extracted, overwrites
files outside the intended workspace (path traversal), uses
symbolic links to read or write host files, or blows up the disk
with a zip bomb.

**Mitigation**: every archive entry is validated before extraction.
The validation rejects traversal, absolute paths, drive letters,
UNC paths, symlinks, hard links, duplicate normalized entries,
excessive depth, oversized entries, suspicious compression ratios,
excessive file counts, and excessive cumulative size. The
thresholds are configurable; the defaults are conservative.

See `docs/archive-safety.md` for the full model.

### T2. Analyzers accidentally execute analyzed code

A future analyzer implementation is tempted to "just import the
module" or "run npm to resolve the lockfile".

**Mitigation**: the non-execution guarantee is codified in
`SECURITY.md` and enforced by review. The application has no
subprocess boundary that takes commands from a repository. Adding
such a boundary requires an explicit, reviewable change.

### T3. Provider error messages leak credentials

A provider's error response includes the request's
`Authorization` header, an API key, or a query-string token.

**Mitigation**: provider errors are run through
`app.utils.redaction.redact_provider_summary` before being
persisted. The redaction strips `Authorization`, `Bearer`,
`api_key`, `access_token`, and similar fields. Long provider
messages are truncated.

### T4. UI shows false confidence

The frontend shows "no vulnerabilities" because no findings were
produced, even when providers were unavailable.

**Mitigation**: the `/scans/{id}/providers` endpoint is the
authoritative source for provider availability. The frontend shows
the provider status page explicitly when scans have no findings,
and the data-completeness banner distinguishes "no data" from
"verified clean". See `docs/provider-honesty.md`.

### T5. Database corruption or schema drift

A bad migration takes the application offline or silently changes
column semantics.

**Mitigation**: the CI pipeline runs `alembic upgrade head`,
`alembic downgrade base`, and `alembic upgrade head` again on
every revision. Each revision is small and reviewable. CHECK
constraints defend against the most common data-quality
regressions.

### T6. Frontend bundle leaks a token

A future change embeds a token in a frontend component.

**Mitigation**: the API client uses `credentials: "omit"`. The
frontend never sets `Authorization` headers. The `VITE_API_BASE_URL`
is the only frontend-facing configuration; no `VITE_*` token-shaped
variable is read by the application.

### T7. Workspace contents are served

A misconfigured reverse proxy serves the workspace root over HTTP.

**Mitigation**: the workspace root is configured via
`LOCKVERITY_WORKSPACE_ROOT` and is not mounted by the API or
frontend. The default path (`./var/workspace`) lives outside the
API's static-file directory.

## Out of scope

- Compromise of the host OS.
- Compromise of the developer's local machine.
- Network attackers (deployments are expected to use TLS).
- Zero-days in OSV, deps.dev, OpenSSF, or GitHub.
- Adversarial ML / prompt injection (we do not use LLMs).

## Reviewing the model

When a new feature is proposed, update this document if the
feature:

- Touches a new code path that handles untrusted input.
- Adds a new outbound network call.
- Adds a new persisted field that could carry sensitive data.
- Changes the state machine for a scan or a stage.
