"""Render-preset tools — save / apply / list named render configurations.

REAPER's native render preset format is internal and version-sensitive, so we
keep our own JSON-backed presets in the user's config directory. Each preset
snapshots a known set of ``RENDER_*`` project info keys (sample rate,
channels, format, output path, dither, tail, resample mode, …).

To use: set up the render dialog the way you like in REAPER, call
``save_render_preset("MyMaster")``, then ``apply_render_preset("MyMaster")``
later or in another project to restore.
"""

import contextlib
import json
import logging
from pathlib import Path

from platformdirs import user_config_dir

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.render_presets")

# Each key listed with the value type REAPER's API expects. Numeric keys go
# through GetSetProjectInfo; string keys through GetSetProjectInfo_String.
_NUMERIC_KEYS = (
    "RENDER_SRATE",
    "RENDER_CHANNELS",
    "RENDER_FORMAT",
    "RENDER_FORMAT2",
    "RENDER_BOUNDSFLAG",
    "RENDER_DITHER",
    "RENDER_TAILMS",
    "RENDER_RESAMPLE",
    "RENDER_ADDTOPROJ",
    "RENDER_NORMALIZE",
    "RENDER_NORMALIZE_TARGET",
)
_STRING_KEYS = (
    "RENDER_FILE",
    "RENDER_PATTERN",
    "RENDER_FORMAT_CUSTOM",
)


def _presets_path() -> Path:
    config_dir = Path(user_config_dir("reaper-mcp"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "render_presets.json"


def _load_presets() -> dict:
    p = _presets_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_presets(presets: dict) -> None:
    _presets_path().write_text(json.dumps(presets, indent=2), encoding="utf-8")


def _read_string_project_info(project_id, key: str) -> str:
    from reapy import reascript_api as RPR

    result = RPR.GetSetProjectInfo_String(project_id, key, "", False)
    if isinstance(result, tuple):
        strings = [s for s in result if isinstance(s, str) and s != key]
        return strings[0] if strings else ""
    return str(result)


def register_tools(mcp):
    @mcp.tool()
    def list_render_presets() -> dict:
        """List every saved render preset (stored in our config dir, not REAPER's)."""
        try:
            presets = _load_presets()
            entries = [
                {
                    "name": name,
                    "keys_stored": len(data),
                    "sample_rate": data.get("RENDER_SRATE"),
                    "format_code": data.get("RENDER_FORMAT"),
                    "output_path": data.get("RENDER_FILE"),
                }
                for name, data in sorted(presets.items())
            ]
            return {
                "success": True,
                "presets_file": str(_presets_path()),
                "count": len(entries),
                "presets": entries,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def save_render_preset(name: str, overwrite: bool = True) -> dict:
        """Snapshot the current project's render settings as a named preset.

        Captures sample rate, channels, format + bit depth, output path,
        filename pattern, render bounds, dither, tail length, resample mode,
        add-to-project flag, and normalization settings.

        Set ``overwrite=False`` to error out if a preset with this name exists.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            presets = _load_presets()
            if name in presets and not overwrite:
                return {
                    "success": False,
                    "error": f"Preset {name!r} already exists; pass overwrite=True to replace",
                }
            data: dict = {}
            for key in _NUMERIC_KEYS:
                with contextlib.suppress(Exception):
                    data[key] = RPR.GetSetProjectInfo(project.id, key, 0.0, False)
            for key in _STRING_KEYS:
                with contextlib.suppress(Exception):
                    data[key] = _read_string_project_info(project.id, key)
            presets[name] = data
            _save_presets(presets)
            return {
                "success": True,
                "name": name,
                "keys_stored": len(data),
                "preset": data,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_render_preset(name: str) -> dict:
        """Apply a saved render preset to the current project."""
        from reapy import reascript_api as RPR

        try:
            presets = _load_presets()
            data = presets.get(name)
            if data is None:
                return {"success": False, "error": f"Preset not found: {name!r}"}
            project = get_project()
            applied: list[str] = []
            errors: list[dict] = []
            for key, value in data.items():
                try:
                    if key in _NUMERIC_KEYS:
                        RPR.GetSetProjectInfo(project.id, key, float(value), True)
                    elif key in _STRING_KEYS:
                        RPR.GetSetProjectInfo_String(project.id, key, str(value), True)
                    else:
                        continue
                    applied.append(key)
                except Exception as e:
                    errors.append({"key": key, "error": str(e)})
            return {
                "success": not errors,
                "partial": bool(applied) and bool(errors),
                "name": name,
                "applied_keys": applied,
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_render_preset(name: str) -> dict:
        """Delete a saved render preset by name."""
        try:
            presets = _load_presets()
            if name not in presets:
                return {"success": False, "error": f"Preset not found: {name!r}"}
            del presets[name]
            _save_presets(presets)
            return {"success": True, "deleted": name}
        except Exception as e:
            return {"success": False, "error": str(e)}
