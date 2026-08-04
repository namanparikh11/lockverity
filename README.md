# Lockverity

> Local-first software supply-chain evidence and SBOM analysis for
> public GitHub repositories and source archives.

Lockverity inspects the software supply chain of public GitHub
repositories and uploaded source archives. It does not execute
analyzed code; it never calls `npm install`, `pip install`, or any
Makefile / shell script from a repository.

The product is **defensive-only**, **read-only for analyzed evidence**,
**source-honest**, and **provenance-preserving**. Every claim the UI
makes is backed by a file path, a manifest, a provider response, or
an explicit omission marker.

## Current release

**Lockverity v2.1.1** — Hotfix release for the public-repository
scan intake. The Windows x64 installer, Windows x64 portable
package, single-port production runtime, cross-platform local
runtime CLI, original brand assets, and concise About page are
unchanged from v2.1.0; this hotfix is a code-only correction
plus an actionable error taxonomy and a repository-intake
consistency closure. The published v2.1.0 release assets remain
in place under the original ``checkpoint-v2.1.0-public-release``
tag and continue to resolve from the original release URL.

| Field | Value |
| --- | --- |
| Version | `2.1.1` |
| Release tag | [`checkpoint-v2.1.1-public-release`](https://github.com/namanparikh11/lockverity/releases/tag/checkpoint-v2.1.1-public-release) |
| Published | 2026-08-04 |
| Source commit | `1f02e272e78da8341fbc3bbd626d25c89c2285c3` |
| Latest release | https://github.com/namanparikh11/lockverity/releases/latest |
| Previous release | [`checkpoint-v2.1.0-public-release`](https://github.com/namanparikh11/lockverity/releases/tag/checkpoint-v2.1.0-public-release) |

## Download and install

**For most Windows users:** download the Windows installer, verify the
SHA-256, double-click, and follow the wizard.

| Pick this | If you are a normal Windows user who wants the recommended install path |
| --- | --- |
| [Lockverity-2.1.1-windows-x64-setup.exe](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.1-public-release/Lockverity-2.1.1-windows-x64-setup.exe) | Windows x64 installer (per-user, no UAC, no admin) |
| SHA-256 | `2f5670aff6e43025895e510a4e53f4144a3397b505904635426fb97f258067a7` |
| Size | 31,138,386 bytes |
| Privilege mode | per-user, no admin, no UAC |
| Default install path | `%LOCALAPPDATA%\Programs\Lockverity` |
| Runtime home | `%LOCALAPPDATA%\Lockverity` |
| Status | **Unsigned** (see [SmartScreen / unsigned / antivirus](#smartscreen--unsigned--antivirus)) |

> **Code → Download ZIP** downloads the Lockverity **source code**. It
> is not the Windows installer and is not the Windows portable. If
> you want to run Lockverity, use the installer or portable ZIP
> above. The source ZIP is intended for development and auditing only.

| Pick this | If you want Lockverity without a formal install |
| --- | --- |
| [Lockverity-2.1.1-windows-x64-portable.zip](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.1-public-release/Lockverity-2.1.1-windows-x64-portable.zip) | Windows x64 portable (extract anywhere, no install) |
| SHA-256 | `5b4310aae9316f4683e1622ee75764996ebc6dde1b05a904a652561ca1e8defd` |
| Size | 56,110,792 bytes |
| Runtime home | `%LOCALAPPDATA%\Lockverity` (still under LocalAppData) |
| Status | **Unsigned** (see [SmartScreen / unsigned / antivirus](#smartscreen--unsigned--antivirus)) |

The central install guide is in [`docs/install.md`](docs/install.md).
The full release manifest, including every uploaded asset hash, is in
the [`INSTALLER-MANIFEST.json`](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.1-public-release/INSTALLER-MANIFEST.json)
and the
[`Lockverity-2.1.1-SHA256SUMS.txt`](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.1-public-release/Lockverity-2.1.1-SHA256SUMS.txt)
attached to the GitHub Release.

### Previous v2.1.0 release (historical)

The v2.1.0 release remains on the
``checkpoint-v2.1.0-public-release`` tag with all six
original assets. v2.1.1 is a code-only hotfix on top of
v2.1.0; the v2.1.0 binaries are not republished.

| Asset | SHA-256 | Size |
| --- | --- | --- |
| `Lockverity-2.1.0-windows-x64-setup.exe` | `db90854369d2bc0ca09fc935abe3f5213260f12229b979ab3bb55dfb5d73bec6` | 31,128,774 bytes |
| `Lockverity-2.1.0-windows-x64-portable.zip` | `a4414372c964f0f50d6e6a864d5a8b8c288acd8a5008e8d45a0ed67e8e58f302` | 56,088,933 bytes |

## Platform availability

| Platform | Recommended option | Availability |
| --- | --- | --- |
| Windows 10 / 11 x64 | Installer EXE | Available |
| Windows portable | Portable ZIP | Available |
| macOS | Source installation | **No packaged app yet** — source-based only |
| Linux | Source installation | **No packaged app yet** — source-based only |

Lockverity v2.1.0 does not publish a DMG, PKG, AppImage, DEB, or RPM
asset. The macOS and Linux workflows are intended for developers and
technical operators. The Windows installer and portable are the only
packaged, fully-accepted distributions in v2.1.0.

## Windows installer

The Windows installer is the recommended option for most Windows
users. It is per-user (no admin, no UAC), per-architecture (x64 only),
and self-contained.

### Download and verify

1. Download the installer:
   [`Lockverity-2.1.0-windows-x64-setup.exe`](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.0-public-release/Lockverity-2.1.0-windows-x64-setup.exe)
2. Verify the SHA-256 matches:
   `db90854369d2bc0ca09fc935abe3f5213260f12229b979ab3bb55dfb5d73bec6`

   ```powershell
   Get-FileHash .\Lockverity-2.1.0-windows-x64-setup.exe -Algorithm SHA256
   ```

   The output hash must equal the value above. If it does not, do not
   run the installer; re-download from the same URL.
3. Double-click the installer.
4. Read the licence, accept it, and click **Install**. No UAC prompt
   appears because the installer is per-user.
5. Optionally check **Launch Lockverity** on the completion page to
   open the trusted loopback URL in your default browser.

After install, the Start Menu contains a **Lockverity** folder with the
application shortcut, the documentation link, and the
**Uninstall Lockverity** entry. Apps & Features shows the per-user
**Lockverity** entry under the current user.

### SmartScreen / unsigned / antivirus

The installer is **not code-signed**. This is a deliberate choice
documented in the in-tree `INFRASTRUCTURE.md`. On a fresh install,
**Windows SmartScreen** will show
*"Windows protected your PC — Microsoft Defender SmartScreen
prevented an unrecognized app from starting. Running this app might
put your PC at risk."* Click **More info → Run anyway** to proceed.
SmartScreen remembers the choice for the same executable.

Some antivirus products will raise a heuristic flag on a freshly
downloaded unsigned binary. This is a false positive: the source is
committed in this repository and the build is reproducible from
`python backend\scripts\build_windows_installer.py`. Submit the flagged
file to your AV vendor as a false positive if it blocks the install.

### Where things live after install

| What | Path |
| --- | --- |
| Application files | `%LOCALAPPDATA%\Programs\Lockverity\app\` |
| Database | `%LOCALAPPDATA%\Lockverity\data\` |
| Logs | `%LOCALAPPDATA%\Lockverity\logs\` |
| Runtime state | `%LOCALAPPDATA%\Lockverity\run\` |
| Operator overrides | `%LOCALAPPDATA%\Lockverity\config\` |

The runtime home is preserved by uninstall; see below.

### Uninstall

Start the uninstaller from
**Start Menu → Lockverity → Uninstall** or from
**Settings → Apps → Lockverity → Uninstall**. The uninstaller:

- detects a live installed instance and requests a graceful stop;
- removes `%LOCALAPPDATA%\Programs\Lockverity\app\`;
- removes the Start Menu folder and the optional desktop shortcut;
- removes the per-user uninstaller registration;
- **preserves** `%LOCALAPPDATA%\Lockverity\` (databases, logs,
  configuration);
- shows a final dialog pointing at the retained-data path.

To remove runtime data manually after uninstalling:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Lockverity"
```

The full per-user, no-admin, no-service installer contract is
documented in
[`docs/windows-installer.md`](docs/windows-installer.md).

## Windows portable

The Windows portable is a self-contained ZIP that bundles the FastAPI
backend, the cross-platform `lockverity-cli` command, the React
frontend, the Alembic migrations, and the approved Part A brand
assets. No separately installed Python or Node.js is required; no
administrator rights; no Windows service, scheduled task, or registry
autorun.

### Download and verify

1. Download the portable:
   [`Lockverity-2.1.0-windows-x64-portable.zip`](https://github.com/namanparikh11/lockverity/releases/download/checkpoint-v2.1.0-public-release/Lockverity-2.1.0-windows-x64-portable.zip)
2. Verify the SHA-256 matches:
   `a4414372c964f0f50d6e6a864d5a8b8c288acd8a5008e8d45a0ed67e8e58f302`

   ```powershell
   Get-FileHash .\Lockverity-2.1.0-windows-x64-portable.zip -Algorithm SHA256
   ```
3. **Extract the entire archive** to any directory the operator
   controls (for example `C:\Tools\Lockverity` or
   `C:\Users\<you>\Lockverity`). Do not run from inside the ZIP
   viewer; extract first.
4. Double-click `Lockverity.exe` to start the runtime and open the
   trusted local URL in the default browser.
5. From a second terminal, use `lockverity-cli.exe` for the documented
   `start`, `stop`, `status`, `open`, `doctor`, and `logs`
   subcommands. `lockverity-cli.exe doctor --json` prints a
   structured diagnostic report.

### Runtime home

The portable does **not** mean runtime data is stored beside the EXE.
The runtime home still defaults to `%LOCALAPPDATA%\Lockverity` and is
created on first launch. To override the path, set the
`LOCKVERITY_HOME` environment variable.

### SmartScreen / unsigned

The portable is **not code-signed**. Windows SmartScreen may show
*"Windows protected your PC"* on first launch. Verify integrity
against the bundled `SHA256SUMS.txt` and `BUILD-MANIFEST.json`, then
click **More info → Run anyway** to proceed.

### Removal

To remove the portable:

1. Stop the running instance with
   `lockverity-cli.exe stop` (or close the launcher if no instance
   is running).
2. Delete the extracted folder.
3. Optionally delete the runtime home at
   `%LOCALAPPDATA%\Lockverity` to remove all databases, logs, and
   state.

Step 3 is independent of step 2: deleting the extracted folder does
not affect the runtime home, and deleting the runtime home does not
affect the extracted folder.

### Which download should I choose?

| If you are a… | Pick |
| --- | --- |
| Normal Windows user who wants the simplest install | **Windows installer** (`.exe`) |
| Operator who cannot install (locked-down laptop, USB-only workflow) | **Windows portable** (`.zip`) |
| Developer or auditor who wants to read or modify the code | **Source ZIP** (the `Code → Download ZIP` button on the GitHub repository) |
| macOS user | Source-based only; see the [macOS](#macos) section below |
| Linux user | Source-based only; see the [Linux](#linux) section below |

The full portable operator reference is in
[`docs/windows-portable.md`](docs/windows-portable.md).

## macOS

Lockverity v2.1.0 does **not** publish a packaged macOS binary (no
`.dmg`, no `.pkg`, no signed `.app`). The macOS workflow is
**source-based only** and is intended for developers or technical
operators.

### Prerequisites

- **macOS 12 (Monterey)** or newer. The CI and development build is
  on the same Node 22.22.x floor as the Windows portable.
- **Python 3.12** (`brew install python@3.12` or your preferred
  manager). The lockfile pins 3.12.x.
- **Node.js >= 22.22.0** (use `nvm use`, `fnm use`, or `volta pin`).
  The repo ships an `.nvmrc` pinning the floor.
- **Xcode Command Line Tools** for `xcode-select --install`.

### Source-based installation

```bash
# Clone the repository
git clone https://github.com/namanparikh11/lockverity.git
cd lockverity

# Backend: create the venv and install
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend: install and build the production bundle
cd ../frontend
npm ci
npm run build
cd ..

# Bring the database schema up to head
cd backend
alembic upgrade head
cd ..
```

### Start, status, doctor, logs, stop

Lockverity ships a cross-platform `lockverity` CLI. The CLI wraps the
single-port production runtime.

```bash
cd backend
source .venv/bin/activate

export LOCKVERITY_ENVIRONMENT=production
export LOCKVERITY_SERVE_FRONTEND=true
export LOCKVERITY_FRONTEND_DIST="../frontend/dist"
export LOCKVERITY_DATABASE_URL="sqlite:///$HOME/Library/Application Support/Lockverity/data/lockverity.sqlite"

lockverity doctor
lockverity start
lockverity status --json
lockverity open
# ...work...
lockverity stop
```

The runtime home on macOS defaults to
`~/Library/Application Support/Lockverity` and is created on first
start. The state file, the database, the rotating log, and the start
lock all live under that path. Override the path with
`--home <path>` or `LOCKVERITY_HOME=<path>` for one invocation or one
shell respectively.

The full single-port runtime contract is in
[`docs/release-checklist.md` § 4a](docs/release-checklist.md). The CLI
contract is in [`docs/release-checklist.md` § 4b](docs/release-checklist.md).
The macOS source-based workflow is also documented in
[`docs/install.md`](docs/install.md#macos-source-setup).

## Linux

Lockverity v2.1.0 does **not** publish a packaged Linux binary (no
`AppImage`, no `.deb`, no `.rpm`, no Flatpak, no Snap). The Linux
workflow is **source-based only** and is intended for developers or
technical operators.

### Prerequisites

- **Linux x86_64** (the build host for the Windows portable is
  Windows; the application itself is cross-platform Python). glibc
  2.31+ (RHEL 8 / Ubuntu 20.04 equivalent or newer).
- **Python 3.12** (your distribution's package manager, or
  `pyenv install 3.12`).
- **Node.js >= 22.22.0** (use `nvm use`, `fnm use`, or `volta pin`).
  The repo ships an `.nvmrc` pinning the floor.
- **Build tools** for the Python wheels you may need
  (`build-essential`, `libffi-dev`, `libssl-dev`).

### Source-based installation

```bash
# Clone the repository
git clone https://github.com/namanparikh11/lockverity.git
cd lockverity

# Backend: create the venv and install
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend: install and build the production bundle
cd ../frontend
npm ci
npm run build
cd ..

# Bring the database schema up to head
cd backend
alembic upgrade head
cd ..
```

### Start, status, doctor, logs, stop

```bash
cd backend
source .venv/bin/activate

export LOCKVERITY_ENVIRONMENT=production
export LOCKVERITY_SERVE_FRONTEND=true
export LOCKVERITY_FRONTEND_DIST="../frontend/dist"
export LOCKVERITY_DATABASE_URL="sqlite:///${XDG_DATA_HOME:-$HOME/.local/share}/lockverity/data/lockverity.sqlite"

lockverity doctor
lockverity start
lockverity status --json
lockverity open
# ...work...
lockverity stop
```

The runtime home on Linux defaults to
`${XDG_DATA_HOME:-$HOME/.local/share}/lockverity` and is created on
first start. The state file, the database, the rotating log, and the
start lock all live under that path. Override the path with
`--home <path>` or `LOCKVERITY_HOME=<path>` for one invocation or one
shell respectively.

The full single-port runtime contract is in
[`docs/release-checklist.md` § 4a](docs/release-checklist.md). The CLI
contract is in [`docs/release-checklist.md` § 4b](docs/release-checklist.md).
The Linux source-based workflow is also documented in
[`docs/install.md`](docs/install.md#linux-source-setup).

> **macOS and Linux are not at the same packaged-acceptance level as
> Windows.** The v2.1.0 release ships an accepted Windows installer
> and an accepted Windows portable. macOS and Linux are
> source-based developer workflows. The CLI, the single-port runtime,
> the Alembic migrations, and the React build all work on macOS and
> Linux, but Lockverity does not claim a packaged macOS or Linux
> distribution in v2.1.0.

## What Lockverity does

- **Persistent data model** for repositories, scans, stages,
  findings, advisories, components, dependency edges, provider
  observations, scan jobs, workspaces, and provider cache.
- **Two intake paths**: `POST /api/v1/repositories/github` (public
  GitHub URL) and `POST /api/v1/repositories/upload` (ZIP archive
  upload with streaming, validation, and quarantine).
- **Manifest parsers** for npm (`package.json`,
  `package-lock.json`), pnpm, Yarn, Poetry, `pyproject.toml`, and
  `requirements.txt`.
- **Vulnerability rules** (direct, transitive, no fixed version,
  withdrawn advisory, unresolved version, partial provider data,
  provider unavailable, multiple dependency paths, vulnerable
  development dependency, missing lockfile).
- **Licence rules** (unknown licence, multiple assertions, review
  required, provider unavailable, full inventory).
- **GitHub Actions workflow analysis** with a manifest-discovery
  pass and a dependency-graph pass.
- **Provider integrations** for GitHub, OSV, deps.dev, and
  OpenSSF Scorecard, plus a bounded HTTP client and a
  provider-cache layer with TTL.
- **Exports**: CycloneDX 1.5 and 1.7 SBOM (JSON, validated
  against the official 1.7 schema), SARIF 2.1.0 (JSON), findings
  JSON, and findings CSV.
- **CycloneDX 1.7 SBOM evidence preview** on the Export Center
  page (`GET /api/v1/scans/{id}/exports/cyclonedx_1_7/preview`).
- **Component evidence drilldown** on the Dependency Explorer
  page (`GET /api/v1/scans/{id}/components/{cid}/evidence`).
- **Evidence search and filtering** on the Dependency Explorer
  page (`GET /api/v1/scans/{id}/components/evidence-summary`).
- **Human-readable evidence report (Markdown)** on the Export
  Center page.
- **Scan comparison** for diffing two scans of the same repository
  without inventing missing evidence.
- **Local scan worker** with a 10-stage pipeline, per-stage status,
  scan cancellation, and per-scan heartbeat monitoring.
- **API surface**: repositories, scans, stages, findings, provider
  observations, provider health rollup, scan comparison, exports,
  system info, system provider limits, and administrative workspace
  cleanup. All errors use a stable envelope and never leak stack
  traces.
- **Frontend** shell with a typed API client, request
  cancellation, structured error parsing, reduced-motion
  support, visible focus states, and explicit first-run empty
  states that distinguish "no data" from "verified clean".

### What Lockverity explicitly does not claim

Lockverity is **not**:

- A **security verdict**. The CycloneDX 1.7 export, the evidence
  report, the component evidence drilldown, and the search
  results are evidence exports, not certifications.
- A **certification**. No export is signed; no export carries a
  trust assertion; no export is a substitute for human review.
- A **compliance pass / fail**. Lockverity does not score a
  repository against a regulatory framework.
- A **complete dependency-graph claim** unless a positive
  persisted signal exists. The v0.6 dependency-graph coverage
  helper returns `partial` or `empty`; it never returns
  `complete`.
- A **"no findings" verdict** when a provider was unavailable.
  Missing provider data is rendered as `not_persisted` /
  `not_observed`; the UI never converts absence into a clean
  bill of health.
- A **remediation workflow**. Lockverity reports findings; it
  does not stage pull requests, open issues, or contact
  maintainers on the operator's behalf.

See [`docs/security-boundaries.md`](docs/security-boundaries.md) for
the full boundary statement and
[`docs/provider-honesty.md`](docs/provider-honesty.md) for the
provider availability policy.

### Intended users

- **Developers** who want a quiet, evidence-based view of the
  supply chain of a repository they depend on.
- **Maintainers** who want a deterministic baseline before a
  release.
- **Security teams** at small organizations who need a
  self-hostable, defensive-only analyzer with no surprise
  outbound calls.
- **Auditors and reviewers** who need every observation backed
  by a file path, manifest, provider response, or configuration
  knob.
- **Portfolio / client review** — every claim the UI makes is
  backed by code that ships in this repository, never by a
  fixture or a mocked demo.

### Brand

The v2.1 mark is a hand-authored interlocking L and V that suggests
an evidence link. The geometry is not generated from a raster
concept and is not derived from any third-party logo asset.
Lockverity is currently an **unregistered open-source brand**; no
trademark registration has been filed and no claim of trademark
registration is made. The full asset inventory, the originality
note, the documented colour palette, and the use restrictions live
in [`docs/brand-assets.md`](docs/brand-assets.md). The visual
language — colour, typography, spacing, focus, and motion — is
documented in [`docs/design-tokens.md`](docs/design-tokens.md).

## Development and source setup

This section is for developers and auditors. If you installed
Lockverity through the Windows installer or portable, you do not
need any of this.

### Prerequisites

- Python 3.12.
- Node.js >= 22.22.0. The Node.js floor is dictated by
  `react-router@8.3.0`, which declares `engines.node = ">=22.22.0"`
  in `frontend/package-lock.json`. Earlier 22.x releases and the
  entire 20.x line are not supported. The repo ships an `.nvmrc`
  pinning the floor.

### Backend

```bash
git clone https://github.com/namanparikh11/lockverity.git
cd lockverity/backend
python3.12 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8765
```

The default SQLite database is `./lockverity.sqlite`. To use
PostgreSQL instead, set `LOCKVERITY_DATABASE_URL` to a SQLAlchemy
URL like `postgresql+psycopg://user:pass@host:5432/lockverity`.

### Frontend

```bash
cd ../frontend
npm install
npm run dev                       # http://127.0.0.1:5173
```

The frontend reads `VITE_API_BASE_URL` to find the backend. The
default is `/api/v1`, which works out of the box when the frontend
and backend are reverse-proxied from the same host. For local
development you can leave the default and let Vite proxy through
or set `VITE_API_PROXY_TARGET=http://127.0.0.1:8765` so Vite
proxies `/api` to a non-default backend port.

### Single-port production runtime

The single-port production runtime (Part B1) hosts the React UI
from the same FastAPI process when `LOCKVERITY_SERVE_FRONTEND=true`
is set. The CLI is the supported way to start, stop, and inspect
it on every platform.

```bash
cd backend
source .venv/bin/activate
export LOCKVERITY_ENVIRONMENT=production
export LOCKVERITY_SERVE_FRONTEND=true
export LOCKVERITY_FRONTEND_DIST="../frontend/dist"
lockverity doctor
lockverity start
lockverity status --json
lockverity stop
```

The default host is `127.0.0.1` and the default port is `8000`. A
non-loopback host requires the explicit `--allow-remote` flag; the
built-in server does not terminate TLS.

### Test commands

```bash
cd backend
pytest -q                          # full backend suite

cd ../frontend
npm test -- --run                  # full frontend suite
npm run typecheck                  # TypeScript
npm run lint                       # ESLint
npm run build                      # production build
```

The single canonical release-verification command is:

```bash
cd backend
.\.venv\Scripts\python.exe scripts/verify_release.py    # Windows
python scripts/verify_release.py                        # macOS / Linux
```

It runs the 11-step plan (backend pytest, CLI pytest, ruff check,
ruff format --check, pip check, frontend test, typecheck, lint,
build, npm audit --omit=dev, npm audit) in order.

### Architecture overview

```
backend/        FastAPI service, SQLAlchemy 2 + Alembic, Pydantic v2
frontend/       React + Vite + TypeScript + Tailwind
docs/           Threat model, provider honesty, finding model, demo, etc.
fixtures/       Synthetic test data (NEVER used in production)
scripts/        Local development helpers
.github/        CI workflows
```

A single deployable backend talks to a single frontend. There is no
Redis, Celery, or Kubernetes by design; the architecture must
remain simple enough that a single engineer can run, audit, and
modify it. For more detail, see
[`docs/architecture.md`](docs/architecture.md).

## Security and documentation links

- Non-execution guarantee and security boundaries:
  [`docs/security-boundaries.md`](docs/security-boundaries.md)
- Provider-honesty policy:
  [`docs/provider-honesty.md`](docs/provider-honesty.md)
- Archive-processing threat model:
  [`docs/archive-safety.md`](docs/archive-safety.md)
- Threat model: [`docs/threat-model.md`](docs/threat-model.md)
- Finding model: [`docs/finding-model.md`](docs/finding-model.md)
- Analysis engine: [`docs/analysis-engine.md`](docs/analysis-engine.md)
- Orchestration: [`docs/orchestration.md`](docs/orchestration.md)
- Windows installer reference:
  [`docs/windows-installer.md`](docs/windows-installer.md)
- Windows portable reference:
  [`docs/windows-portable.md`](docs/windows-portable.md)
- Central install guide:
  [`docs/install.md`](docs/install.md)
- Release checklist:
  [`docs/release-checklist.md`](docs/release-checklist.md)
- Brand assets: [`docs/brand-assets.md`](docs/brand-assets.md)
- Design tokens: [`docs/design-tokens.md`](docs/design-tokens.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
- Release notes: [`RELEASE_NOTES.md`](RELEASE_NOTES.md)
- Security policy: [`SECURITY.md`](SECURITY.md)
- Demo walkthrough (reviewer guide):
  [`docs/demo-walkthrough.md`](docs/demo-walkthrough.md)
- Demo pack (60-second script + public/private recommendation):
  [`docs/demo-pack.md`](docs/demo-pack.md)
- Screenshot checklist + manual capture guide:
  [`docs/screenshots.md`](docs/screenshots.md)
- Guided intake: open `/analyze` after starting the local
  backend to register a public GitHub repository or upload a
  `zip` source archive.

## License

MIT. See [`LICENSE`](LICENSE).
