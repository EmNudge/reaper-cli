"""Tests for the restart orchestrator's pure logic — no REAPER required.

The full quit/relaunch/reconnect flow is validated live; here we cover the
parts that decide *whether* and *how* it runs: the pre-flight gates, the
dry-run plan, and the config snapshot/restore file ops. The bridge call
(``get_session_state``) is mocked.
"""

from __future__ import annotations

from reaper_mcp import inreaper
from reaper_mcp.tools import restart


def _patch_env(monkeypatch, *, macos=True, state=None, resource=None):
    monkeypatch.setattr(restart, "_is_macos", lambda: macos)
    monkeypatch.setattr(restart, "ensure_connected", lambda: None)
    if resource is not None:
        monkeypatch.setattr(restart, "_resource_dir", lambda: resource)

    def fake_call(func, *args, **kwargs):
        if func is inreaper.get_session_state:
            return state
        raise AssertionError(f"unexpected bridge call: {func}")

    monkeypatch.setattr(restart, "call_in_reaper", fake_call)


# ---------- pre-flight gates ----------


def test_non_macos_is_refused(monkeypatch):
    _patch_env(monkeypatch, macos=False)
    out = restart._run_restart(restart.DEFAULT_PROTECT, 90.0, False, False)
    assert out["success"] is False
    assert "macOS" in out["error"]


def test_multiple_tabs_aborts(monkeypatch):
    state = {"tab_count": 2, "active_fn": "/a.rpp", "active_dirty": 1, "active_tracks": 3}
    _patch_env(monkeypatch, state=state)
    out = restart._run_restart(restart.DEFAULT_PROTECT, 90.0, False, False)
    assert out["success"] is False
    assert "tab" in out["error"].lower()


def test_untitled_dirty_aborts_with_save_as(monkeypatch):
    state = {"tab_count": 1, "active_fn": "", "active_dirty": 1, "active_tracks": 2}
    _patch_env(monkeypatch, state=state)
    out = restart._run_restart(restart.DEFAULT_PROTECT, 90.0, False, False)
    assert out["success"] is False
    assert "save" in out["error"].lower() and "untitled" in out["error"].lower()


def test_dry_run_titled_dirty_reports_full_plan(monkeypatch, tmp_path):
    (tmp_path / "reaper-menu.ini").write_text("x")
    state = {
        "tab_count": 1,
        "active_fn": "/proj.rpp",
        "active_dirty": 1,
        "active_tracks": 5,
    }
    _patch_env(monkeypatch, state=state, resource=tmp_path)
    out = restart._run_restart("reaper-menu.ini", 90.0, True, False)
    assert out["success"] is True and out["dry_run"] is True
    assert "save active project" in out["plan"]
    assert out["would_protect"] == [str(tmp_path / "reaper-menu.ini")]


def test_dry_run_clean_reports_config_only_plan(monkeypatch, tmp_path):
    state = {"tab_count": 1, "active_fn": "", "active_dirty": 0, "active_tracks": 0}
    _patch_env(monkeypatch, state=state, resource=tmp_path)
    out = restart._run_restart("reaper-menu.ini", 90.0, True, False)
    assert out["success"] is True
    # No project to preserve → plan must not mention saving the project.
    assert "save active project" not in out["plan"]


def test_dry_run_only_lists_existing_protect_files(monkeypatch, tmp_path):
    (tmp_path / "reaper-menu.ini").write_text("x")  # exists
    # reaper.ini intentionally absent
    state = {"tab_count": 1, "active_fn": "", "active_dirty": 0, "active_tracks": 0}
    _patch_env(monkeypatch, state=state, resource=tmp_path)
    out = restart._run_restart("reaper-menu.ini,reaper.ini", 90.0, True, False)
    assert out["would_protect"] == [str(tmp_path / "reaper-menu.ini")]


# ---------- config snapshot / restore file ops ----------


def test_snapshot_and_restore_round_trip(tmp_path):
    f = tmp_path / "reaper-menu.ini"
    f.write_text("original + declared edit")
    baks = restart._snapshot_config([f])
    # Simulate REAPER's exit-flush clobbering the file with session state.
    f.write_text("CLOBBERED by exit flush")
    restart._restore_files(baks)
    assert f.read_text() == "original + declared edit"
    # The .bak sits beside the original.
    assert list(baks.values()) == [str(f) + restart._BAK_SUFFIX]


def test_cleanup_baks_removes_everything(tmp_path):
    f = tmp_path / "reaper-menu.ini"
    f.write_text("x")
    baks = restart._snapshot_config([f])
    baseline = tmp_path / "proj.rpp.baseline.bak"
    baseline.write_text("baseline")
    # Point the manifest at the temp dir so _clear_manifest is a no-op-safe call.
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(restart, "_resource_dir", lambda: tmp_path)
    try:
        restart._cleanup_baks(baks, str(baseline))
    finally:
        monkeypatch.undo()
    assert not any(p.name.endswith(restart._BAK_SUFFIX) for p in tmp_path.iterdir())
    assert not baseline.exists()
