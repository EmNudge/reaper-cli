"""Code that executes *inside* the running REAPER process.

The functions here are never called in the CLI's own process. Instead the
reapy dist-API bridge encodes a reference to them (``module_name`` +
``qualname``), ships it over the socket, and REAPER's embedded Python imports
this module and runs the function on its main thread. The return value is
JSON-encoded straight back to the caller.

This is the injection point that gives the CLI full ReaScript-API access: any
operation expressible in Python-ReaScript can run here, including the SWS
``SNM_*ConfigVar`` calls that change settings live which otherwise require
quitting REAPER, hand-editing ``reaper.ini`` and relaunching.

Two hard rules for everything in this file:

* **Top-level imports must be stdlib only.** The CLI imports this module in its
  own process purely to obtain the function objects to encode — that import
  must not need reapy/REAPER. ``reapy``/``RPR`` are imported lazily inside the
  functions, where they resolve to REAPER's live API.
* **Return values must be JSON-safe.** The bridge ``json.dumps`` the result
  with reapy's encoder, which only understands primitives + reapy objects.
  Coerce anything else with ``_jsonable`` before returning.
"""

from __future__ import annotations

MAX_JSON_DEPTH = 6


def _jsonable(value, _depth: int = 0):
    """Coerce *value* into something reapy's JSON encoder can serialize.

    Primitives pass through; containers recurse (bounded in depth and width);
    anything else degrades to ``repr`` so a result is always returned rather
    than crashing the bridge's serializer.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth >= MAX_JSON_DEPTH:
        return repr(value)
    if isinstance(value, dict):
        return {
            str(k): _jsonable(v, _depth + 1) for k, v in list(value.items())[:200]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v, _depth + 1) for v in list(value)[:500]]
    return repr(value)


def _build_namespace() -> dict:
    """Globals dict handed to exec/eval, pre-loaded with REAPER API handles."""
    ns: dict = {"__name__": "__reaper_cli__", "__builtins__": __builtins__}
    try:
        import reapy

        ns["reapy"] = reapy
        from reapy import reascript_api as RPR

        # Both names point at REAPER's live API: `RPR` matches this repo's
        # convention, `reaper` matches stock ReaScript snippets users paste in.
        ns["RPR"] = RPR
        ns["reaper"] = RPR
    except Exception:  # pragma: no cover - only meaningful inside REAPER
        pass
    return ns


def run_code(code: str, mode: str = "exec", return_var: str = "result") -> dict:
    """Execute *code* inside REAPER and return captured output.

    ``mode="exec"`` runs statements and returns the value left in
    ``return_var`` (default ``result``). ``mode="eval"`` evaluates a single
    expression and returns its value. stdout/stderr are captured. Exceptions
    are caught and returned as a formatted traceback rather than raised (an
    unhandled raise here would crash the bridge's defer loop).
    """
    import contextlib
    import io
    import traceback

    namespace = _build_namespace()
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(
            captured
        ):
            if mode == "eval":
                value = eval(compile(code, "<reaper-cli>", "eval"), namespace)
            else:
                exec(compile(code, "<reaper-cli>", "exec"), namespace)
                value = namespace.get(return_var)
        return {
            "success": True,
            "result": _jsonable(value),
            "stdout": captured.getvalue(),
        }
    except Exception:
        return {
            "success": False,
            "error": traceback.format_exc(),
            "stdout": captured.getvalue(),
        }


def _rp():
    """REAPER's injected python module (absent outside REAPER)."""
    import reaper_python  # ty: ignore[unresolved-import]

    return reaper_python


_NULL_PROJ = "0x0000000000000000"


def get_session_state() -> dict:
    """Snapshot the open-project landscape for restart orchestration.

    Returns the tab count plus the active project's file path, dirty flag and
    track count. ``active_fn`` is empty for an untitled project. Operates on the
    active project (index 0) to avoid the reapy pointer round-trip gotcha.
    """
    R = _rp()
    count = 0
    i = 0
    while i < 1000:
        p = R.RPR_EnumProjects(i, "", 4096)[0]
        if (not p) or p.endswith(_NULL_PROJ):
            break
        count += 1
        i += 1
    active = R.RPR_EnumProjects(-1, "", 4096)
    return {
        "success": True,
        "tab_count": count,
        "active_fn": active[2],
        "active_dirty": int(R.RPR_IsProjectDirty(0)),
        "active_tracks": int(R.RPR_CountTracks(0)),
    }


def save_active_project() -> dict:
    """Save the active project to its associated path, clearing the dirty flag.

    Used in the restart "approach C": write the in-memory edits to the project
    file so REAPER can quit without a save prompt; the original baseline is
    restored over it after relaunch. Only valid for a titled project — saving an
    untitled one would pop a file dialog (the orchestrator forbids that path).
    """
    R = _rp()
    R.RPR_Main_SaveProject(0, False)
    active = R.RPR_EnumProjects(-1, "", 4096)
    return {"success": True, "fn": active[2], "dirty": int(R.RPR_IsProjectDirty(0))}


def mark_active_dirty() -> dict:
    """Mark the active project unsaved (restores the dirty flag after restore)."""
    R = _rp()
    R.RPR_MarkProjectDirty(0)
    return {"success": True, "dirty": int(R.RPR_IsProjectDirty(0))}


def quit_reaper() -> dict:
    """Trigger REAPER quit (action 40004). Caller expects the bridge to drop."""
    R = _rp()
    R.RPR_Main_OnCommand(40004, 0)
    return {"success": True, "quitting": True}


def bind_api(name: str, restype, *argtypes):
    """Bind a registered REAPER API function by name, returning a ctypes callable.

    REAPER's shipped ``reaper_python.py`` only defines static ``RPR_*`` wrappers
    for the core API; SWS / extension functions are absent from it even when the
    extension is installed. They *do* live in the native function table
    (``reaper_python._ft``), so we construct a ctypes wrapper from the raw
    function pointer ourselves. This is the general escape hatch for any
    extension API that has no Python binding. Returns ``None`` if the function
    is not registered (extension missing). Only meaningful inside REAPER.
    """
    import ctypes

    import reaper_python  # ty: ignore[unresolved-import]  # REAPER-injected; absent outside REAPER

    pointer = reaper_python._ft.get(name)
    if pointer is None:
        return None
    return ctypes.CFUNCTYPE(restype, *argtypes)(pointer)


def _config_var_api():
    """ctypes bindings for the four SWS config-var functions (or ``None`` each)."""
    import ctypes

    cstr = ctypes.c_char_p
    return {
        "get_int": bind_api("SNM_GetIntConfigVar", ctypes.c_int, cstr, ctypes.c_int),
        "set_int": bind_api("SNM_SetIntConfigVar", ctypes.c_byte, cstr, ctypes.c_int),
        "get_dbl": bind_api(
            "SNM_GetDoubleConfigVar", ctypes.c_double, cstr, ctypes.c_double
        ),
        "set_dbl": bind_api(
            "SNM_SetDoubleConfigVar", ctypes.c_byte, cstr, ctypes.c_double
        ),
    }


def _detect_config_var(api: dict, name_bytes: bytes):
    """Return ``(value, kind)`` for a live config var, or ``None`` if unknown.

    Uses the SWS two-sentinel trick: ``SNM_Get*ConfigVar`` returns the supplied
    error value for unknown vars, so calling twice with different error values
    distinguishes "var holds N" from "var doesn't exist". Tries int first, then
    double.
    """
    get_int = api["get_int"]
    if get_int is not None:
        int_a = get_int(name_bytes, 0)
        int_b = get_int(name_bytes, 1)
        if not (int_a == 0 and int_b == 1):
            return int(int_a), "int"
    get_dbl = api["get_dbl"]
    if get_dbl is not None:
        dbl_a = get_dbl(name_bytes, -1.5)
        dbl_b = get_dbl(name_bytes, -2.5)
        if not (dbl_a == -1.5 and dbl_b == -2.5):
            return float(dbl_a), "double"
    return None


def get_config_var(name: str) -> dict:
    """Read a live REAPER config variable (the in-memory backing for reaper.ini).

    Requires the SWS extension (provides ``SNM_*ConfigVar``).
    """
    api = _config_var_api()
    if api["get_int"] is None and api["get_dbl"] is None:
        return {
            "success": False,
            "error": "SNM_GetConfigVar not registered — is the SWS extension installed?",
        }
    try:
        found = _detect_config_var(api, name.encode("utf-8"))
    except Exception as e:  # pragma: no cover - inside REAPER
        return {"success": False, "error": f"SNM_GetConfigVar failed: {e}"}
    if found is None:
        return {"success": False, "error": f"Unknown config var: {name!r}"}
    value, kind = found
    return {"success": True, "name": name, "value": value, "type": kind}


def set_config_var(name: str, value: float) -> dict:
    """Set a live REAPER config variable, applied immediately (no restart).

    Whole numbers are written via ``SNM_SetIntConfigVar``; fractional values via
    ``SNM_SetDoubleConfigVar``. Requires the SWS extension. Note REAPER persists
    the change to ``reaper.ini`` on its next config flush (e.g. normal exit).
    """
    api = _config_var_api()
    if api["set_int"] is None and api["set_dbl"] is None:
        return {
            "success": False,
            "error": "SNM_SetConfigVar not registered — is the SWS extension installed?",
        }
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return {"success": False, "error": f"value must be numeric, got {value!r}"}
    name_bytes = name.encode("utf-8")
    try:
        if (
            numeric.is_integer()
            and api["set_int"] is not None
            and api["set_int"](name_bytes, int(numeric))
        ):
            return {
                "success": True,
                "name": name,
                "value": int(numeric),
                "type": "int",
            }
        if api["set_dbl"] is not None and api["set_dbl"](name_bytes, numeric):
            return {"success": True, "name": name, "value": numeric, "type": "double"}
    except Exception as e:  # pragma: no cover - inside REAPER
        return {"success": False, "error": f"SNM_SetConfigVar failed: {e}"}
    return {
        "success": False,
        "error": f"Could not set {name!r} (unknown var or wrong numeric type).",
    }
