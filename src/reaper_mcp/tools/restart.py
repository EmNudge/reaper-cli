"""Restart orchestration — apply a restart-only config edit without losing work.

Some REAPER settings (toolbars in ``reaper-menu.ini``, the keymap in
``reaper-kb.ini``) are read once at launch and have no live-reload API, so a
change to them only takes effect after a restart. This module performs that
restart *safely*: it preserves the open session and persists **only** the edit
already written to the protected config files, while committing nothing the
user didn't intend.

Guarantees (single-tab v1):

* The active project comes back open and marked **unsaved** — your real project
  file is left at its last-saved baseline, never silently committed.
* Among the protected config files, only their pre-quit on-disk state survives;
  REAPER's exit-flush of incidental in-session changes is reverted.

This is a CLI-side orchestrator, not an in-REAPER tool: it has to keep running
while REAPER quits and relaunches (the bridge drops in between). The mechanism
("approach C") and every primitive it uses were validated live against REAPER
7.73. macOS only for now; other platforms raise a clear error.

Prerequisite: the reapy bridge must auto-start on launch (``Scripts/__startup.lua``)
so the orchestrator can reconnect after relaunch.
"""

import contextlib
import logging
import shutil
import subprocess
import time
from pathlib import Path

from platformdirs import user_config_dir

from reaper_mcp import inreaper
from reaper_mcp.connection import call_in_reaper, ensure_connected, reconnect

logger = logging.getLogger("reaper_mcp.tools.restart")

DEFAULT_PROTECT = "reaper-menu.ini,reaper-kb.ini,reaper.ini"
_BAK_SUFFIX = ".reaper-cli-restart.bak"
_BASELINE_SUFFIX = ".reaper-cli-baseline.bak"
_MANIFEST = "reaper-cli-restart-manifest.json"


def _resource_dir() -> Path:
    return Path(user_config_dir("REAPER"))


def _is_macos() -> bool:
    import platform

    return platform.system() == "Darwin"


def _reaper_running() -> bool:
    proc = subprocess.run(["pgrep", "-x", "REAPER"], capture_output=True, text=True, check=False)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _wait_for_exit(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _reaper_running():
            return True
        time.sleep(1.0)
    return not _reaper_running()


def _relaunch(project_path: str | None) -> None:
    args = ["open", "-a", "REAPER"]
    if project_path:
        args.append(project_path)
    subprocess.run(args, check=True)


def _snapshot_config(protect_files: list[Path]) -> dict[str, str]:
    """Copy each protected file to a ``.bak`` holding its pre-quit state."""
    baks: dict[str, str] = {}
    for f in protect_files:
        bak = f.with_name(f.name + _BAK_SUFFIX)
        shutil.copy2(f, bak)
        baks[str(f)] = str(bak)
    return baks


def _restore_files(mapping: dict[str, str]) -> None:
    """Copy each ``bak`` back over its original (revert REAPER's exit-flush)."""
    for original, bak in mapping.items():
        if Path(bak).is_file():
            shutil.copy2(bak, original)


def _write_manifest(data: dict) -> Path:
    import json

    path = _resource_dir() / _MANIFEST
    path.write_text(json.dumps(data, indent=2))
    return path


def _clear_manifest() -> None:
    path = _resource_dir() / _MANIFEST
    if path.is_file():
        path.unlink()


def _cleanup_baks(config_baks: dict[str, str], baseline_bak: str | None) -> None:
    for bak in config_baks.values():
        Path(bak).unlink(missing_ok=True)
    if baseline_bak:
        Path(baseline_bak).unlink(missing_ok=True)
    _clear_manifest()


def _run_restart(
    protect_config: str,
    reconnect_timeout: float,
    dry_run: bool,
    keep_backups: bool,
) -> dict:
    if not _is_macos():
        return {
            "success": False,
            "error": "restart-reaper is implemented for macOS only so far.",
        }

    ensure_connected()
    state = call_in_reaper(inreaper.get_session_state)
    active_fn = state["active_fn"]
    dirty = bool(state["active_dirty"])
    untitled = active_fn == ""

    # --- pre-flight gates ---
    if state["tab_count"] > 1:
        return {
            "success": False,
            "error": (
                f"{state['tab_count']} project tabs are open; v1 supports a "
                "single tab. Close the extras and re-run."
            ),
            "state": state,
        }
    if dirty and untitled:
        return {
            "success": False,
            "error": (
                "The open project is untitled with unsaved changes. Save it to a "
                "file first (Save As), then re-run so your work can be preserved "
                "across the restart."
            ),
            "state": state,
        }

    res = _resource_dir()
    protect_files = [
        res / name.strip()
        for name in protect_config.split(",")
        if name.strip() and (res / name.strip()).is_file()
    ]

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "state": state,
            "would_protect": [str(p) for p in protect_files],
            "plan": (
                "save active project to clear dirty -> snapshot config -> quit -> "
                "restore config snapshots -> relaunch -> reconnect -> restore "
                "project baseline -> mark unsaved"
            )
            if dirty
            else "snapshot config -> quit -> restore config -> relaunch -> reconnect",
        }

    steps: list[str] = []

    # --- snapshot protected config (pre-quit on-disk state = the declared edit) ---
    config_baks = _snapshot_config(protect_files)
    steps.append(f"snapshot {len(config_baks)} config file(s)")

    # --- approach C: back up baseline, then save edits to the project file ---
    baseline_bak: str | None = None
    if dirty:
        baseline_bak = active_fn + _BASELINE_SUFFIX
        shutil.copy2(active_fn, baseline_bak)
        saved = call_in_reaper(inreaper.save_active_project)
        if saved.get("dirty") != 0:
            # Could not clean the project; bail out before quitting. Nothing
            # destructive has happened that the backups don't cover.
            _restore_files({active_fn: baseline_bak})
            _cleanup_baks(config_baks, baseline_bak)
            return {
                "success": False,
                "error": "Save did not clear the dirty flag; aborted before quit.",
                "saved": saved,
            }
        steps.append("saved edits to project file; backed up baseline")

    _write_manifest(
        {
            "project_path": active_fn or None,
            "baseline_bak": baseline_bak,
            "config_baks": config_baks,
            "dirty": dirty,
        }
    )

    # --- quit REAPER (bridge drops; disconnect is expected) ---
    try:
        call_in_reaper(inreaper.quit_reaper)
    except Exception as e:  # noqa: BLE001 - the bridge dying mid-quit is normal
        logger.info("Quit call returned via disconnect (expected): %s", e)

    if not _wait_for_exit(timeout=30.0):
        # REAPER refused to quit. We're still connected, so put the project back
        # the way we found it (baseline on disk + dirty flag) and abort.
        if dirty and baseline_bak:
            _restore_files({active_fn: baseline_bak})
            with contextlib.suppress(Exception):
                call_in_reaper(inreaper.mark_active_dirty)
        _cleanup_baks(config_baks, baseline_bak)
        return {
            "success": False,
            "error": "REAPER did not exit within 30s; restored project and aborted.",
            "steps": steps,
        }
    steps.append("REAPER exited")

    # --- revert REAPER's exit-flush, re-asserting the declared edit ---
    _restore_files(config_baks)
    steps.append("restored config snapshots (incidental changes reverted)")

    # --- relaunch + reconnect ---
    _relaunch(active_fn or None)
    steps.append("relaunched REAPER")
    reconnect(timeout=reconnect_timeout)
    steps.append("bridge reconnected")

    # --- restore project baseline on disk + re-mark unsaved ---
    if dirty and baseline_bak:
        shutil.copy2(baseline_bak, active_fn)
        marked = call_in_reaper(inreaper.mark_active_dirty)
        steps.append(f"restored project baseline; dirty={marked.get('dirty')}")

    if not keep_backups:
        _cleanup_baks(config_baks, baseline_bak)
        steps.append("cleaned up backups")
    else:
        steps.append("kept backups (keep_backups=True)")

    return {
        "success": True,
        "project": active_fn or "(untitled)",
        "preserved_unsaved": dirty,
        "protected_config": [str(p) for p in protect_files],
        "steps": steps,
    }


def register_tools(mcp):
    @mcp.tool()
    def about_restart() -> dict:
        """Primer for restart orchestration — read before using restart_reaper.

        Explains why some edits need a restart, the data-safety guarantees, the
        single-tab v1 limits, and the prerequisite that the reapy bridge
        auto-starts on launch.
        """
        return {
            "success": True,
            "why": (
                "Toolbar/menu (reaper-menu.ini) and keymap (reaper-kb.ini) edits "
                "are loaded once at startup with no live-reload API, so they only "
                "take effect after a REAPER restart. restart_reaper performs that "
                "restart without losing the open session or committing unsaved work."
            ),
            "guarantees": [
                "Active project returns open and marked UNSAVED; the real project "
                "file is left at its last-saved baseline (never silently committed).",
                "Only the pre-quit on-disk state of the protected config files "
                "survives; REAPER's exit-flush of incidental in-session changes "
                "(including live set-config-var edits) is reverted.",
            ],
            "workflow": (
                "1) Make your restart-only edit on disk (e.g. system add-toolbar-item, "
                "or edit reaper-menu.ini). 2) Run restart_reaper. The edit applies; "
                "everything else is preserved or reverted as above."
            ),
            "limits_v1": [
                "Single project tab only (aborts if more than one is open).",
                "An untitled+dirty project is refused — Save As it first.",
                "macOS only so far.",
            ],
            "prerequisite": (
                "The reapy bridge must auto-start on launch (Scripts/__startup.lua) "
                "so the orchestrator can reconnect after relaunch. Use dry_run=True "
                "to preview the plan without restarting."
            ),
            "recovery": (
                "Backups (.reaper-cli-*.bak) and a manifest "
                "(reaper-cli-restart-manifest.json) are written in the REAPER "
                "resource dir before quitting and removed on success. If the run is "
                "interrupted, restoring each .bak over its original recovers the "
                "prior state."
            ),
        }

    @mcp.tool()
    def restart_reaper(
        protect_config: str = DEFAULT_PROTECT,
        reconnect_timeout: float = 90.0,
        dry_run: bool = False,
        keep_backups: bool = False,
    ) -> dict:
        """Restart REAPER to apply a restart-only config edit, losing no work.

        Preserves the open project (returned marked unsaved, real file untouched)
        and persists only the pre-quit on-disk state of ``protect_config`` (comma
        -separated filenames in the REAPER resource dir), reverting REAPER's
        exit-flush of everything else. Call ``about_restart`` first; use
        ``dry_run=True`` to preview without restarting. Single-tab, macOS-only v1.
        """
        try:
            return _run_restart(protect_config, reconnect_timeout, dry_run, keep_backups)
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": str(e),
                "note": (
                    "If REAPER was already quit, recover by restoring the "
                    f"*{_BAK_SUFFIX} / *{_BASELINE_SUFFIX} backups in the REAPER "
                    "resource dir over their originals."
                ),
            }
