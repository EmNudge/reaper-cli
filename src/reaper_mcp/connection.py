"""Lazy reapy connection — connects once on first use.

Live tools call ``get_project()`` to obtain the active ``reapy.Project``;
the first call triggers ``reapy.connect()``. Offline tools do not call this.
"""

import logging

logger = logging.getLogger("reaper_mcp.connection")

_connected = False


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


def get_project():
    import reapy

    ensure_connected()
    return reapy.Project()
