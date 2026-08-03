"""Wrapper that runs the b3b_acceptance.py with the
documented Unicode-spaces path on the command line, where
PowerShell's Start-Process -ArgumentList mangles the
multibyte Omega character.

The script is a tiny one-shot and is *not* part of the
shipped B3B installer workflow; it exists only to make the
acceptance test reproducible from a non-interactive shell.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

sys.argv = [
    "b3b_acceptance",
    "--installer",
    str(REPO_ROOT / "build" / "installer" / "Lockverity-2.1.0-windows-x64-setup.exe"),
    "--install-dir",
    r"C:\Temp\Lockverity B3B Unicode Ω\Lockverity",
    "--home-dir",
    r"C:\Temp\Lockverity B3B Unicode Ω\Home",
    "--port",
    "18780",
    "--log-dir",
    str(REPO_ROOT / "build" / "installer" / "logs" / "b3b"),
]

# Import the b3b_acceptance module and run main().
spec_path = BACKEND_ROOT / "scripts" / "b3b_acceptance.py"
spec = importlib.util.spec_from_file_location("b3b_acceptance", spec_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
raise SystemExit(mod.main())
