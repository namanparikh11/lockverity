# Core Intake and Scan Orchestration (v0.2)

v0.2 turns the v0.1 architecture baseline into a working core: it
registers a repository from a public GitHub URL or an uploaded ZIP
archive, validates and extracts the archive into a safe workspace,
seeds a scan against that workspace, and drives the scan through a
bounded local worker pool.

The provider implementations for OSV, deps.dev, OpenSSF, and
parsers for npm/PyPI are **not** part of v0.2. Every stage that
needs them is marked `not_requested` and recorded truthfully in
the database. A v0.2 scan therefore completes with a partial
result: the only stages that ever run to `completed` are the ones
that operate purely on local state.

## High-level shape

```
                           +-------------------+
                           |   FastAPI (HTTP)  |
                           +---------+---------+
                                     |
            +------------+-----------+-----------+--------------+
            |                        |           |              |
            v                        v           v              v
   +-----------------+   +------------------+  +------+  +-----------+
   | repository      |   | workspace        |  | scan |  | system    |
   | intake          |   | service          |  | orch.|  | / health  |
   | (github + zip)  |   | (create/qa/...)  |  |      |  | / limits  |
   +--------+--------+   +---------+--------+  +--+---+  +-----------+
            |                      |              |
            v                      v              v
   +-----------------+   +------------------+  +-----------+
   | GitHub provider |   | Workspace        |  | Local     |
   | (bounded HTTP)  |   | filesystem       |  | worker    |
   +--------+--------+   +------------------+  +-----+-----+
            |                                         |
            v                                         v
   +-----------------+                       +----------------+
   | provider cache  |                       | stage runner   |
   | (SQL-backed)    |                       | (synchronous   |
   +-----------------+                       |  in-process)   |
                                             +----------------+
```

## Components

### Intake

Two intake paths, both produce a `Repository` row, a `Workspace`
row, and an extracted tree on disk:

1. **GitHub URL** - `POST /api/v1/repositories/github`. The URL is
   normalized to a public GitHub URL, the GitHub API is consulted
   for default branch and resolved commit SHA, the resolved
   commit's tarball is downloaded through a bounded HTTP client,
   validated as an archive, and extracted into a per-scan
   workspace.
2. **ZIP upload** - `POST /api/v1/repositories/upload`. The upload
   is streamed to a temporary quarantine path while its SHA-256 is
   computed. On full receipt the archive's central directory is
   inspected, every entry is validated against the existing
   `archive_validation` contract, and the validated entries are
   extracted into a per-scan workspace.

Both paths go through the same `WorkspaceService` after the bytes
are on disk. The workspace is the unit of cleanup.

### Workspace

A workspace is uniquely identified by an opaque, non-guessable
`workspace_key`. The key is the only handle returned to the rest of
the application. The on-disk layout under
`LOCKVERITY_WORKSPACE_ROOT` is:

```
<workspace_root>/
  workspaces/
    <workspace_key>/
      quarantine/
        archive.bin         # the bytes as received
        archive.sha256      # hex digest of archive.bin
      contents/             # only populated after successful validation
      manifest.json         # safe metadata: counts, hash, limits
```

The API never returns an absolute path, and the API and frontend
never mount `workspace_root`. The workspace is removed entirely
on failure, cancellation, or successful completion (unless kept for
inspection, which is a v0.3 concern).

### Worker and executor

A small, in-process executor that:

- accepts explicit `start` and `cancel` calls,
- has a configurable concurrency cap,
- keeps a heartbeat row in the database so a scan left "running"
  after a process crash can be recovered on the next startup,
- never spawns uncontrolled background processes,
- is easy to mock in tests (an `InlineExecutor` runs the scan
  synchronously on the calling thread).

The worker is intentionally narrow. v0.3 can replace it with
Celery, RQ, or a third-party broker without changing the
orchestrator contract.

### Scan orchestrator

The orchestrator implements the stage pipeline:

```
queued  ->  running  ->  {completed | partial | failed | cancelled}
```

It transitions a scan and its stages through the same state
machine the service layer already exposes. New in v0.2:

- explicit `cancel` between stages (the running task is allowed
  to finish its current stage, then the scan is marked
  `cancelled`),
- `run` endpoint that asks the executor to start a queued scan,
- idempotency: re-running a queued scan is a no-op; re-running a
  running scan is rejected; re-running a terminal scan is
  rejected,
- bounded failure summary (`failure_code` + `failure_summary`
  with a fixed max length, redaction applied before persistence),
- recovery: on startup, scans in `running` whose heartbeat is
  older than the configured threshold are marked `failed` with
  the code `lost_heartbeat`,
- provider-honesty: every stage records a `ProviderObservation`
  describing whether the stage had work to do (`not_requested`,
  `unavailable`, or `available`); the truth is never faked.

For v0.2 the only stages that can be `completed` are the local
ones: `repository_intake`, `archive_validation`,
`manifest_discovery` (returns `not_requested` because no parsers
exist), `dependency_parsing` (returns `not_requested`),
`dependency_enrichment` (returns `not_requested`),
`vulnerability_query` (returns `not_requested`),
`workflow_analysis` (returns `not_requested`),
`repository_posture` (returns `not_requested`),
`finding_reconciliation` (returns `not_requested`),
`export_generation` (returns `not_requested`).

`manifest_discovery` walks the workspace and records what *would*
be parsed, but it does not run any parser. The same is true for
all later stages. The whole point of v0.2 is to make the
orchestration honest before any provider is plugged in.

### Provider cache

A small SQL-backed cache for provider responses. v0.2 does not
populate it from any external provider; the infrastructure exists
so the analysis branch can add a provider in v0.3 without
redesigning the cache. The cache records:

- a normalized, redacted key (no credentials),
- the provider name,
- the operation name,
- the response SHA-256,
- the ETag and Last-Modified headers (when present),
- expiry,
- the maximum payload size, which the cache enforces.

### Security controls

The v0.2 surface keeps the v0.1 guarantees and adds:

- **GitHub host allowlist.** The intake layer only talks to
  `github.com` and `codeload.github.com` (the documented archive
  host). Any redirect to a different host is rejected.
- **Content-type check.** The tarball and API responses are
  validated against a small allowlist of `application/...` and
  `text/...` media types.
- **Bounded download size.** The HTTP client enforces a per-stream
  byte cap identical to the archive limits.
- **Timeouts and retries.** Every external call has a connect and
  read timeout, and a bounded retry budget. 429 responses surface
  as `ProviderObservation(status=RATE_LIMITED)` and are not
  retried automatically.
- **Token redaction.** A server-side `LOCKVERITY_GITHUB_TOKEN`
  may be configured; the value is never logged, never returned in
  the API, and never embedded in cache keys.
- **Error redaction.** Provider error summaries go through the
  existing redaction utility before they touch the database.

## What is still out of scope

- Concrete parsers (npm, PyPI, Go, etc.) and concrete providers
  (OSV, deps.dev, OpenSSF, GitHub Actions security rules).
- CycloneDX, SARIF, and other exporters.
- A real, multi-host deployment (the worker is in-process).
- A web UI for v0.2; the v0.1 shell already exposes the
  endpoints it needs.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `LOCKVERITY_WORKSPACE_ROOT` | `./var/workspace` | root for the workspace tree |
| `LOCKVERITY_GITHUB_TOKEN` | unset | optional, server-side only |
| `LOCKVERITY_GITHUB_TIMEOUT_SECONDS` | `15` | HTTP timeout for the GitHub API |
| `LOCKVERITY_GITHUB_MAX_RESPONSE_BYTES` | `10 MiB` | API response cap |
| `LOCKVERITY_GITHUB_MAX_DOWNLOAD_BYTES` | `200 MiB` | tarball download cap |
| `LOCKVERITY_GITHUB_RETRY_LIMIT` | `2` | bounded retry budget |
| `LOCKVERITY_SCAN_WORKER_CONCURRENCY` | `2` | local worker fan-out |
| `LOCKVERITY_SCAN_HEARTBEAT_SECONDS` | `15` | expected heartbeat interval |
| `LOCKVERITY_SCAN_HEARTBEAT_TIMEOUT_SECONDS` | `120` | recovery threshold |
| `LOCKVERITY_PROVIDER_CACHE_MAX_PAYLOAD_BYTES` | `1 MiB` | cache payload cap |
| `LOCKVERITY_PROVIDER_CACHE_DEFAULT_TTL_SECONDS` | `3600` | default cache TTL |
