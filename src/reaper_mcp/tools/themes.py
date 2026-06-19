"""Theme tools — install / list / activate REAPER themes.

REAPER themes live under ``<resource>/ColorThemes/`` as either ``.ReaperTheme``
(plain config) or ``.ReaperThemeZip`` (real zip bundling the theme XML plus
image resources). REAPER reads both formats directly — no unzipping needed.

The "active theme" is stored in the ``lastthemefn5`` config var as an absolute
path. Setting it via these tools requires a REAPER restart to take effect.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("reaper_mcp.tools.themes")


def _resource_path() -> Path:
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac


def _themes_dir() -> Path:
    return _resource_path() / "ColorThemes"


def register_tools(mcp):
    @mcp.tool()
    def list_installed_themes() -> dict:
        """List every ``.ReaperTheme`` and ``.ReaperThemeZip`` under ColorThemes/."""
        try:
            root = _themes_dir()
            if not root.exists():
                return {
                    "success": True,
                    "themes_dir": str(root),
                    "count": 0,
                    "themes": [],
                    "note": "ColorThemes directory does not exist yet",
                }
            themes = []
            for ext in ("*.ReaperTheme", "*.ReaperThemeZip"):
                for p in root.glob(ext):
                    themes.append(
                        {
                            "name": p.stem,
                            "filename": p.name,
                            "absolute_path": str(p),
                            "type": "theme_zip"
                            if p.suffix == ".ReaperThemeZip"
                            else "theme",
                            "size_bytes": p.stat().st_size,
                        }
                    )
            themes.sort(key=lambda t: t["name"])
            return {
                "success": True,
                "themes_dir": str(root),
                "count": len(themes),
                "themes": themes,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def install_theme_from_file(source_path: str, activate: bool = False) -> dict:
        """Copy a ``.ReaperTheme`` or ``.ReaperThemeZip`` file into ColorThemes/.

        ``activate=True`` also sets it as the active theme (takes effect after
        restarting REAPER). REAPER reads ``.ReaperThemeZip`` files directly —
        no need to unzip first.
        """
        try:
            src = Path(source_path).expanduser()
            if not src.exists():
                return {"success": False, "error": f"Source file not found: {src}"}
            if src.suffix not in (".ReaperTheme", ".ReaperThemeZip"):
                return {
                    "success": False,
                    "error": (
                        f"Unsupported file extension {src.suffix!r}. "
                        "Expected .ReaperTheme or .ReaperThemeZip."
                    ),
                }
            dest_dir = _themes_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            shutil.copy2(src, dest)

            result = {
                "success": True,
                "source": str(src),
                "installed_to": str(dest),
                "size_bytes": dest.stat().st_size,
            }

            if activate:
                from reapy import reascript_api as RPR

                ok = RPR.set_config_var_string("lastthemefn5", str(dest))
                result["activated"] = bool(ok)
                result["note"] = "Activation takes effect after restarting REAPER"

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_active_theme(theme_name: str) -> dict:
        """Set REAPER's active theme by name. Takes effect after restarting REAPER.

        ``theme_name`` should match a file under ColorThemes/ (with or without
        extension). Use ``list_installed_themes`` to discover names.
        """
        from reapy import reascript_api as RPR

        try:
            root = _themes_dir()
            candidates = [
                root / theme_name,
                root / f"{theme_name}.ReaperTheme",
                root / f"{theme_name}.ReaperThemeZip",
            ]
            target = next((c for c in candidates if c.exists()), None)
            if target is None:
                return {
                    "success": False,
                    "error": (
                        f"Theme not found: {theme_name!r}. "
                        f"Searched: {[str(c) for c in candidates]}"
                    ),
                }
            ok = RPR.set_config_var_string("lastthemefn5", str(target))
            return {
                "success": bool(ok),
                "theme_name": theme_name,
                "theme_path": str(target),
                "note": "Takes effect after restarting REAPER",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_active_theme() -> dict:
        """Return the path of the currently active REAPER theme (from ``lastthemefn5``)."""
        from reapy import reascript_api as RPR

        try:
            result = RPR.get_config_var_string("lastthemefn5", "", 4096)
            if isinstance(result, tuple):
                strings = [
                    s for s in result if isinstance(s, str) and s != "lastthemefn5"
                ]
                value = strings[0] if strings else ""
            else:
                value = str(result)

            theme_path = Path(value) if value else None
            return {
                "success": True,
                "active_theme_path": value,
                "theme_name": theme_path.stem if theme_path else None,
                "exists": theme_path.exists() if theme_path else False,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
