"""Lazy reapy connection — connects once on first use.

Live tools call ``get_project()`` to obtain the active ``reapy.Project``;
the first call triggers ``reapy.connect()``. Offline tools do not call this.
"""

import logging

logger = logging.getLogger("reaper_mcp.connection")

_connected = False
_remote_path_injected = False


def ensure_connected() -> None:
    global _connected
    if _connected:
        return
    import reapy

    try:
        reapy.connect()
        _connected = True
        logger.info("Connected to REAPER")
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to REAPER: {e}. "
            "Make sure REAPER is running and the distant API is enabled — "
            "from the terminal (with REAPER quit): "
            ".venv/bin/python scripts/setup_reaper_connection.py "
            "then start REAPER and run the activate_reapy_server action once. "
            "See README.md → 'Enable REAPER's distant API' for details."
        ) from e


def reset_connection() -> None:
    """Forget the cached connection + remote-bootstrap state.

    Call before reconnecting to a REAPER that has restarted: the old reapy
    client is dead and the new REAPER process has not had ``sys.path`` injected
    yet, so both flags must be cleared.
    """
    global _connected, _remote_path_injected
    _connected = False
    _remote_path_injected = False


def reconnect(timeout: float = 60.0, interval: float = 1.5) -> bool:
    """Block until a (re)started REAPER's bridge is reachable, or time out.

    Polls ``reapy.reconnect()`` plus a trivial round-trip until one succeeds.
    Used by the restart orchestrator after relaunching REAPER.
    """
    import time

    import reapy

    reset_connection()
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            reapy.reconnect()
            _ = reapy.Project().bpm  # force a real round-trip over the bridge
            global _connected
            _connected = True
            logger.info("Reconnected to REAPER")
            return True
        except Exception as e:  # noqa: BLE001 - REAPER not up yet; keep polling
            last_error = e
            time.sleep(interval)
    raise RuntimeError(f"Could not reconnect to REAPER within {timeout:.0f}s: {last_error}")


def get_project():
    import reapy

    ensure_connected()
    return reapy.Project()


def call_in_reaper(func, *args, **kwargs):
    """Run *func* inside the live REAPER process and return its result.

    The reapy bridge encodes *func* by its ``module_name`` + ``qualname``, ships
    that over the socket, and REAPER's embedded Python imports the module and
    calls it on the main thread (see ``reaper_mcp.inreaper``). This is the
    general code-execution channel the dedicated tools build on; it is *not*
    limited to reapy's own functions.

    Requirements: *func* must live in a module importable on REAPER's Python
    path (the standard venv setup puts ``reaper_mcp`` there) and must return a
    JSON-serializable value.
    """
    import reapy

    ensure_connected()
    if reapy.is_inside_reaper():
        # Degenerate case: we're already the embedded interpreter. Call directly.
        return func(*args, **kwargs)
    # Reach the bridge client via attribute access (resolved through reapy's
    # dynamic stub) rather than importing the private submodule directly.
    client = reapy.tools.network.machines.get_selected_client()
    if client is None:
        raise RuntimeError("reapy client unavailable even though connection reported success.")
    _ensure_remote_importable(client)
    return client.request(func, {"args": list(args), "kwargs": dict(kwargs)})


def _ensure_remote_importable(client) -> None:
    """Make ``reaper_mcp`` importable inside REAPER's embedded Python.

    The package is installed *editable*, so its source dir is only registered
    via a ``.pth`` processed during normal site initialization — which REAPER's
    embedded interpreter skips. Without this, the bridge's request decoder
    (``importlib.import_module("reaper_mcp.inreaper")``) raises
    ``ModuleNotFoundError`` while parsing the request, crashing REAPER's defer
    loop before any tool code runs.

    ``builtins.exec`` is always resolvable across the bridge (no editable
    install involved), so we use it once per process to splice the source dir
    onto REAPER's ``sys.path``. The change persists for the life of the REAPER
    session; the guard makes re-injection a no-op. Localhost only — for a remote
    slave machine the path would differ.
    """
    global _remote_path_injected
    if _remote_path_injected:
        return
    import builtins
    import os

    import reaper_mcp

    src_dir = os.path.dirname(os.path.dirname(reaper_mcp.__file__))
    # Also drop any cached reaper_mcp modules: REAPER's embedded Python persists
    # across CLI invocations, so without this it would keep running whatever
    # version of inreaper.py it first imported, ignoring edits on disk until a
    # REAPER restart. Clearing the cache once per process makes the next import
    # re-read from disk. Safe because the defer loop is single-threaded and this
    # bootstrap request completes before any tool dispatch.
    bootstrap = (
        "import sys\n"
        f"_p = {src_dir!r}\n"
        "if _p not in sys.path:\n"
        "    sys.path.insert(0, _p)\n"
        "for _m in [m for m in list(sys.modules) "
        "if m == 'reaper_mcp' or m.startswith('reaper_mcp.')]:\n"
        "    del sys.modules[_m]\n"
    )
    client.request(builtins.exec, {"args": [bootstrap], "kwargs": {}})
    _remote_path_injected = True
