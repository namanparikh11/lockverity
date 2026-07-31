# Lockverity v2.1 — Windows x64 per-user installer

The Lockverity v2.1 Windows installer is a per-user, x64, self-contained
EXE that installs the accepted Part B3A portable payload
(`Lockverity-2.1.0-windows-x64-portable.zip`) into
`%LOCALAPPDATA%\Programs\Lockverity`. The installer does **not** modify
the operator's `PATH`, does **not** install a Windows service, does
**not** register an autorun entry, does **not** add a firewall rule,
and does **not** require administrator privilege.

This page documents installation, silent install, runtime data
separation, reinstall / repair, and uninstall. It also explains the
unsigned / SmartScreen / antivirus behaviour you should expect.

## At a glance

| Property | Value |
|---|---|
| Filename | `Lockverity-2.1.0-windows-x64-setup.exe` |
| Architecture | x64 only |
| Privilege mode | per-user, no admin, no UAC |
| Default install path | `%LOCALAPPDATA%\Programs\Lockverity` |
| Stable AppId | `{E5B0C0F4-7C42-4D6A-9B17-1A2B3C4D5E6F}` |
| Runtime data | `%LOCALAPPDATA%\Lockverity` (preserved on uninstall) |
| Code signing | **Unsigned** (see [SmartScreen / unsigned / antivirus](#smartscreen--unsigned--antivirus)) |

## Interactive install

1. Double-click `Lockverity-2.1.0-windows-x64-setup.exe`.
2. The wizard shows the Lockverity licence; click **I accept** to
   continue.
3. The default install path is
   `%LOCALAPPDATA%\Programs\Lockverity`. Change the path only if
   you have a specific reason.
4. The wizard offers an **optional** desktop shortcut. It is
   **unchecked by default** so a fresh install does not add a
   desktop icon unless you ask for one.
5. Click **Install**. No UAC prompt appears.
6. On the completion page, optionally check **Launch Lockverity** to
   open the trusted loopback URL in your default browser.

After install:

- Start Menu: a **Lockverity** folder with the application shortcut,
  the documentation link, and the **Uninstall Lockverity** entry.
- Desktop: the optional shortcut if you opted in.
- Apps & Features (Settings → Apps): the per-user **Lockverity**
  entry under the current user.

## Silent install

Silent install is supported via standard Inno Setup switches. The
operator never sees a UI. No browser is launched in silent mode.

```powershell
Lockverity-2.1.0-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- ^
    /DIR="C:\Apps\Lockverity" ^
    /LOG="C:\Temp\lockverity-install.log"
```

| Switch | Meaning |
|---|---|
| `/VERYSILENT` | No wizard pages or progress UI. |
| `/SUPPRESSMSGBOXES` | Suppresses any blocking message box. |
| `/NORESTART` | Do not request a Windows reboot. |
| `/SP-` | Skip the **Welcome** page. |
| `/DIR=<path>` | Override the install path. Supports spaces and Unicode. |
| `/LOG=<file>` | Write the install log to the given file. |

The installer returns an Inno Setup exit code:

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Initialisation failed (see `/LOG`) |
| 2 | The user clicked **Cancel** (only relevant in interactive mode) |
| Other non-zero | An error occurred (see `/LOG`) |

Silent install never launches the browser and never shows blocking
dialogs. The full accepted payload is installed into `/DIR`.

## Runtime data

Lockverity's runtime data (databases, logs, configuration and
uploads) lives in a separate directory from the application
binaries:

```
%LOCALAPPDATA%\Lockverity\
  data\        # SQLite databases
  logs\        # rotating log files
  run\         # runtime state files (lockverity.state.json)
  config\      # operator overrides
```

The default location is the standard per-user path resolved by the
runtime's `app.cli.home.default_home()`. You can override the
location with the `LOCKVERITY_HOME` environment variable for one
shell, or with the `--home <path>` CLI option for one invocation.

## Launch

After install, click the Start Menu shortcut, or invoke the
installed binary directly:

```powershell
& "$env:LOCALAPPDATA\Programs\Lockverity\app\Lockverity.exe"
```

The launcher starts the runtime in the background, waits for
`/api/v1/health`, then opens the trusted loopback URL in your
default browser. A second invocation of the launcher reuses the
existing instance (same PID, same port, same instance id).

CLI access:

```powershell
& "$env:LOCALAPPDATA\Programs\Lockverity\app\lockverity-cli.exe" --version
& "$env:LOCALAPPDATA\Programs\Lockverity\app\lockverity-cli.exe" doctor
& "$env:LOCALAPPDATA\Programs\Lockverity\app\lockverity-cli.exe" status
& "$env:LOCALAPPDATA\Programs\Lockverity\app\lockverity-cli.exe" stop
```

## Reinstall / repair

Running the installer again performs a safe reinstall of the accepted
payload. The installer:

- detects a live installed instance via the documented Part B2
  identity check (state file + PID + creation time + instance UUID);
- requests a graceful stop via the installed
  `lockverity-cli.exe stop`;
- replaces the application files in
  `%LOCALAPPDATA%\Programs\Lockverity\app\`;
- preserves your runtime data, databases, and logs in
  `%LOCALAPPDATA%\Lockverity\`;
- does not duplicate Start Menu or desktop shortcuts;
- does not rewrite the uninstaller registration.

The reinstall never terminates a process based on a PID alone, and
it never kills unrelated processes. If a safe shutdown cannot be
verified, the installer aborts with an actionable message pointing
at `lockverity-cli.exe doctor` and the runtime log path.

## Uninstall

Uninstall removes the application files and the shortcuts, and
preserves your runtime data. Start the uninstaller from
**Start Menu → Lockverity → Uninstall** or from
**Settings → Apps → Lockverity → Uninstall**.

The uninstaller:

- detects a live installed instance and requests a graceful stop;
- removes `%LOCALAPPDATA%\Programs\Lockverity\app\`;
- removes the Start Menu folder and the optional desktop shortcut;
- removes the per-user uninstaller registration;
- **preserves** `%LOCALAPPDATA%\Lockverity\` (databases, logs,
  configuration);
- shows a final dialog pointing at the retained-data path.

If a live instance is still running when the uninstaller runs, it
prompts you to close Lockverity first. No reboot is required.

### Removing runtime data (manual)

The installer never deletes your runtime data automatically. To
remove it after uninstalling the application, run from PowerShell:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Lockverity"
```

This deletes the `data`, `logs`, `run`, and `config` sub-directories.
The runtime will recreate them on the next start if you reinstall
the application.

## What the installer does NOT do

The Lockverity v2.1 Windows installer intentionally omits a
number of behaviours that are common in commercial installers. None
of these are part of the v2.1 contract; each is a deliberate
omission to keep the install per-user, offline, and operator
controllable.

- **No system PATH modification.** The installer does not write
  `%PATH%` or `HKLM\...\\Path`.
- **No Program Files default.** The default install path is
  `%LOCALAPPDATA%\Programs\Lockverity`, which is outside
  `Program Files` and requires no elevation.
- **No service installation.** The installer never invokes
  `sc.exe` or `New-Service`. Lockverity runs as a regular
  process owned by the operator.
- **No scheduled task.** The installer never invokes
  `schtasks.exe`. Lockverity is started by the operator.
- **No firewall rule.** The installer never invokes `netsh advfirewall`
  or `New-NetFirewallRule`. The runtime binds loopback only.
- **No autorun entry.** The installer never writes
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` or
  `RunOnce`.
- **No automatic updates.** The installer never downloads a
  newer version. Operators update Lockverity manually.
- **No telemetry / no phone-home.** Lockverity never reports
  usage data. The only network access is the operator's local
  browser.
- **No file association / no URL protocol / no shell extension.**
  The installer does not register `.lockverity` or any
  `lockverity://` protocol.

## SmartScreen / unsigned / antivirus

The Lockverity v2.1 release is **not code-signed**. This is a
deliberate choice (see the in-tree `INFRASTRUCTURE.md` for the
rationale) and means:

- On a fresh install, **Windows SmartScreen** will show
  *"Windows protected your PC — Microsoft Defender SmartScreen
  prevented an unrecognized app from starting. Running this app
  might put your PC at risk."* Click **More info → Run anyway**
  to proceed. SmartScreen remembers the choice for the same
  executable.
- Some antivirus products will raise a heuristic flag on a
  freshly-signed or freshly-downloaded unsigned binary. This is
  a false positive: the source is committed in this repository
  and the build is reproducible from the documented
  `python backend\scripts\build_windows_installer.py` command.
  Submit the flagged file to your AV vendor as a false positive
  if it blocks the install.
- The `INSTALLER-MANIFEST.json` next to the installer records
  the unsigned status honestly. The build script never claims
  Microsoft certification, code signing, or SmartScreen
  reputation.

## Troubleshooting

### The installer does not start

1. Verify the SHA-256 of `Lockverity-2.1.0-windows-x64-setup.exe`
   matches the value in `INSTALLER-MANIFEST.json`.
2. Run the installer with `/LOG=<file>` and inspect the log.

### The runtime is not reachable at `http://127.0.0.1:<port>/`

1. Open `lockverity-cli.exe doctor` from
   `%LOCALAPPDATA%\Programs\Lockverity\app\` and read the
   diagnostic output.
2. Read the latest log under
   `%LOCALAPPDATA%\Lockverity\logs\lockverity.log`.
3. Check that no other process is bound to the default port
   (`8000`). Override with `lockverity-cli.exe start --port <N>`.

### Reinstall fails because the runtime is "still running"

The installer uses the Part B2 identity check (PID + creation time
+ instance UUID) to verify the running instance. If you see
"Lockverity is still running" after closing the GUI, the runtime
may be holding the start lock:

1. Open a terminal and run
   `lockverity-cli.exe status` to inspect the recorded
   state.
2. If the recorded PID is dead but the state file is still
   present, run `lockverity-cli.exe stop` to clear the state,
   then retry the install.

### The browser does not open after install

The installer never launches a browser. The launcher opens the
browser on the first manual start. If your default browser
ignores the `webbrowser.open` call, invoke the installed
`Lockverity.exe` directly from a terminal to see any error
output.

## Build source

The installer is built from the committed `backend\installer\lockverity.iss`
source. The canonical build command is:

```powershell
python backend\scripts\build_windows_installer.py --clean --json-report
```

The build script:

1. verifies Windows x64 and a clean Git working tree;
2. verifies the accepted B3A portable payload's hashes (it will
   **refuse** to build if any hash differs);
3. extracts the payload into a dedicated staging directory;
4. invokes Inno Setup 6.x with the committed `.iss` source;
5. emits `INSTALLER-MANIFEST.json` and an external
   `SHA256SUMS.txt` next to the installer EXE;
6. runs a bounded silent-install + health + uninstall smoke if
   `--run-smoke` is passed.

Inno Setup 6.7.3 is the only trusted compiler for this build.
The compiler is fetched and verified by the project's build
script; the source is signed by jrsoftware.org.

## Acceptance contract

The installer's behaviour is tested by:

- `backend\tests\test_installer.py` — static contract tests
  covering AppId, install path, privilege mode, architecture,
  icon, shortcuts, no-service / no-firewall / no-PATH /
  no-telemetry / no-update / no-autorun / no-scheduled-task
  guarantees, and unsigned-status representation.
- `backend\scripts\build_windows_installer.py --run-smoke` —
  end-to-end silent install + health + uninstall smoke.

The v2.1 Part B3B acceptance cycle verifies:

- interactive install under the current non-elevated user;
- silent install into a path containing spaces and Unicode;
- installed `BUILD-MANIFEST.json` reports
  `source_commit = 81b400bc40ae6ada2787470fca8b31c5ea8b1c30`;
- reinstall while the runtime is running performs a verified
  graceful stop;
- uninstall while the runtime is running performs a verified
  graceful stop;
- runtime data is preserved on every variant of uninstall;
- no registry key outside the per-user uninstaller registration
  is created.
