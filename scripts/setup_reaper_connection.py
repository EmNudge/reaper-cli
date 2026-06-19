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

import sys


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
        "(Make sure REAPER is fully quit before running this — the configurator\n"
        " needs to edit reaper.ini, and won't if zero or several REAPER instances\n"
        " are detected.)\n"
    )
    try:
        reapy.configure_reaper()
    except RuntimeError as e:
        print(f"Couldn't configure REAPER: {e}", file=sys.stderr)
        print(
            "\nQuit REAPER and re-run this script. If REAPER is already quit,\n"
            "pass detect_portable_install=False (edit this script) to skip the\n"
            "running-instance check.",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError as e:
        print(f"Couldn't find REAPER config: {e}", file=sys.stderr)
        return 1

    print(
        "Done. Next steps:\n"
        "  1. Start REAPER.\n"
        "  2. Verify with:\n"
        "       reaper-cli system get-playback-state\n"
        "     You should see JSON, not a connection error."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
