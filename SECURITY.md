# Security

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| v2.1.x  | Yes                |
| v2.0.x  | Best-effort, no feature backports |
| v0.5 – v1.9 | No                 |
| < v0.5  | No                 |

Lockverity is in a `v2.1` local-first release line. Until
`v2.1` reaches its `1.0` (long-term support) milestone, the project
does not commit to long-term compatibility promises; the data
model, the API, and the file formats may change between minor
versions. Security fixes are backported to the current
`v2.1.x` line only.

## Responsible disclosure

Please report security issues through the GitHub Security
Advisories flow at
[`https://github.com/namanparikh11/lockverity/security/advisories/new`](https://github.com/namanparikh11/lockverity/security/advisories/new).
Do not file public issues for suspected vulnerabilities.

We will:

1. Acknowledge receipt within 3 business days.
2. Triage within 10 business days and share an initial assessment.
3. Coordinate a fix and a disclosure date. We aim to issue a patch
   within 90 days of confirmation.

## Non-execution guarantee

Lockverity never executes analyzed repository code. The boundary is
enforced by code, not policy:

- The scanner never calls `npm install`, `npm` scripts,
  `pip install`, `poetry install`, `yarn install`, `pnpm install`,
  `setup.py`, or any Makefile / shell script from a repository.
- The scanner never shells out to arbitrary subprocesses based on
  repository content.
- The only network egress the application makes is to the providers
  it explicitly registers (see `docs/provider-honesty.md`).
- OSV, deps.dev, and OpenSSF Scorecard can be selected independently
  for each scan. Disabled providers are gated before service, cache,
  and network activity. GitHub repository intake necessarily contacts
  GitHub to resolve and download the submitted public repository. See
  the [privacy policy](docs/privacy.md) for transmitted coordinates.

This guarantee extends to:

- Uploaded source archives (validated before any extraction).
- Repository manifests and lockfiles (parsed as data, not imported).
- GitHub Actions workflows (parsed as YAML, never executed).
- Any future source of repository contents.

## Archive-processing threat model

A user-uploaded archive is treated as hostile input from the moment
it enters the workspace. See `docs/archive-safety.md` for the full
model. In summary:

- The archive is *not* extracted until every entry has been
  validated.
- The validation rejects: parent-traversal, absolute POSIX paths,
  Windows drive-letter paths, UNC paths, symbolic links, hard
  links, duplicate normalized entries, excessive directory depth,
  oversized individual entries, excessive cumulative uncompressed
  size, suspicious compression ratios, and excessive file counts.
- The validation thresholds come from `Settings.archive_*` and have
  safe defaults.

If an archive fails validation the entire archive is rejected. A
single bad entry does not result in a partial extraction; there is
no partial extraction.

## Credential handling

- GitHub tokens and external-provider credentials are **server-side
  only**. The frontend bundle never embeds them. The frontend never
  sets `Authorization` headers.
- Provider error messages and response bodies are passed through
  `app.utils.redaction` before being persisted as
  `error_summary`. Authorization headers, API keys, access tokens,
  cookies, and Bearer-prefixed tokens are scrubbed.
- Provider URLs are stripped of query strings and fragments before
  they reach the database; the path is preserved because it
  identifies the resource.
- The application does not write credentials to log lines. Log
  configuration is explicit and contains no secret-shaped fields.

## Scope exclusions

Out of scope for the Lockverity security boundary:

- Vulnerabilities in user-supplied web browsers or Node.js
  installations.
- Vulnerabilities in third-party providers (OSV, deps.dev, OpenSSF,
  GitHub) - we treat their responses as data, not as instructions.
- Compromise of the host operating system running Lockverity.
- Compromise of the developer's local machine while developing
  Lockverity.

## Warning

Source archives are hostile input. Even though Lockverity validates
every entry, never point the application at an archive you do not
trust. The application's behaviour on a *valid* archive is not a
guarantee about its behaviour on a *novel malicious* archive -
defensive defaults narrow the attack surface, they do not eliminate
it.
