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
            "Make sure REAPER is running and the distant API is enabled. "
            "To enable it: in REAPER go to Actions > Run ReaScript, then run: "
            "import reapy; reapy.config.enable_dist_api()"
        ) from e


def get_project():
    import reapy

    ensure_connected()
    return reapy.Project()
