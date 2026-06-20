"""One-shot external setup — make REAPER accept reapy connections.

Run this script ONCE, with REAPER fully quit. It edits REAPER's reaper.ini and
reaper-kb.ini to enable Python ReaScripts, register the reapy activation
ReaScript, and open the web interface on port 2307. After it runs, start
REAPER and the reaper-mcp / reaper-cli tools will be able to drive the live
session.

Usage:
    /path/to/.venv/bin/python scripts/setup_reaper_connection.py

This is the modern replacement for the GUI step ("Actions → Run ReaScript")
in older reapy docs. With reapy >= 0.10 it works entirely from outside REAPER.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _resource_path() -> Path:
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac


def _normalize_kb_ini(path: Path) -> bool:
    """Repair reaper-kb.ini line-glue bug. Returns True if file changed.

    reapy's ``configure_reaper`` appends ``SCR …`` entries without first
    checking whether the file ends with a newline. If a previous reapy
    install left the file without a trailing newline (or any earlier append
    did the same), the next append concatenates onto the same line and
    REAPER silently skips the whole malformed line — so the bridge action
    never appears in the Actions list. We defensively split any glued
    ``SCR `` runs and ensure a trailing newline both before and after
    calling configure_reaper.
    """
    if not path.exists():
        return False
    original = path.read_text()
    # Insert newline before any ``SCR `` not at start-of-line.
    fixed = re.sub(r"(?<!\n)(SCR )", r"\n\1", original)
    if not fixed.endswith("\n"):
        fixed += "\n"
    if fixed == original:
        return False
    path.write_text(fixed)
    return True


def main() -> int:
    try:
        import reapy
    except ImportError:
        print(
            "python-reapy is not installed. Install the unified package with "
            "its deps first:\n  pip install -e .",
            file=sys.stderr,
        )
        return 2

    print(
        "Configuring REAPER to accept reapy connections.\n"
        "(REAPER should be fully quit before running this — the configurator\n"
        " edits reaper.ini and reaper-kb.ini directly.)\n"
    )

    kb_ini = _resource_path() / "reaper-kb.ini"
    if _normalize_kb_ini(kb_ini):
        print(f"Pre-pass: repaired glued/unterminated lines in {kb_ini}\n")

    try:
        reapy.configure_reaper()
    except RuntimeError as e:
        # The detect_portable_install probe trips when zero REAPER instances
        # are running — which is exactly the state this script asks for. Fall
        # back to the non-detecting path; portable installs are rare on the
        # platforms we target and the user can override via env if needed.
        if "No REAPER instance" in str(e) or "running" in str(e).lower():
            print(
                "Portable-install detection skipped (no running REAPER found, "
                "as expected). Retrying with detect_portable_install=False.\n"
            )
            try:
                reapy.configure_reaper(detect_portable_install=False)
            except Exception as inner:
                print(f"Couldn't configure REAPER: {inner}", file=sys.stderr)
                return 1
        else:
            print(f"Couldn't configure REAPER: {e}", file=sys.stderr)
            return 1
    except FileNotFoundError as e:
        print(f"Couldn't find REAPER config: {e}", file=sys.stderr)
        return 1

    if _normalize_kb_ini(kb_ini):
        print(f"Post-pass: repaired glued/unterminated lines in {kb_ini}")

    print(
        "Done. Next steps:\n"
        "  1. Start REAPER.\n"
        "  2. First-time only — activate the bridge ReaScript inside REAPER:\n"
        "       Actions menu → Show action list → search 'activate_reapy'\n"
        "       → Run. Right-click → Run on REAPER startup to persist.\n"
        "  3. Verify from the terminal:\n"
        "       reaper-cli audio get-playback-state\n"
        "     You should see JSON, not a hang or recursion error."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
