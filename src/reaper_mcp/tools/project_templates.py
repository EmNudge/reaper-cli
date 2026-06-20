"""Project-template tools — save / apply / list `.RPP` project templates.

Project templates live in REAPER's resource directory under ``ProjectTemplates/``.
File → New project from template loads one; this module exposes the same set
programmatically.

For *track* templates (single track + FX chain) see ``templates.py``. For *FX
chain* templates (just the FX chain without the surrounding track) see
``fx_chain_templates.py``.
"""

import logging
import os
from pathlib import Path

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.project_templates")


def _resource_path() -> Path:
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac


def _templates_dir() -> Path:
    return _resource_path() / "ProjectTemplates"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()


def _resolve_template_path(template_name: str) -> Path:
    parts = [_sanitize(seg) for seg in template_name.replace("\\", "/").split("/")]
    parts[-1] = parts[-1].removesuffix(".RPP").removesuffix(".rpp")
    return _templates_dir().joinpath(*parts).with_suffix(".RPP")


def register_tools(mcp):
    @mcp.tool()
    def list_project_templates() -> dict:
        """List every ``.RPP`` file under REAPER's ProjectTemplates folder.

        Supports nested subdirectories — name them like ``"Songwriter/Demo"``.
        """
        try:
            root = _templates_dir()
            if not root.exists():
                return {
                    "success": True,
                    "templates_dir": str(root),
                    "count": 0,
                    "templates": [],
                    "note": "ProjectTemplates directory does not exist yet",
                }
            templates = []
            for p in root.rglob("*.RPP"):
                rel = p.relative_to(root)
                templates.append(
                    {
                        "name": p.stem,
                        "relative_path": str(rel),
                        "absolute_path": str(p),
                        "size_bytes": p.stat().st_size,
                    }
                )
            templates.sort(key=lambda t: t["relative_path"])
            return {
                "success": True,
                "templates_dir": str(root),
                "count": len(templates),
                "templates": templates,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def save_project_as_template(template_name: str) -> dict:
        """Save the current project as a project template under ProjectTemplates/.

        ``template_name`` may include subdirectories (``"Songwriter/Demo"``).
        Uses ``Main_SaveProjectEx`` with the save-as-copy flag so the current
        project's saved-path association is not disturbed.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            target = _resolve_template_path(template_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            # options bitmask: 1 = save as copy (don't change current project's path)
            try:
                RPR.Main_SaveProjectEx(project.id, str(target), 1)
            except Exception:
                # Fallback: write the project's existing chunk if available.
                # (Some reapy versions don't wrap Main_SaveProjectEx.)
                return {
                    "success": False,
                    "error": "Main_SaveProjectEx not available; cannot save as copy",
                }
            return {
                "success": True,
                "template_name": template_name,
                "saved_to": str(target),
                "size_bytes": target.stat().st_size if target.exists() else 0,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_project_template(template_name: str) -> dict:
        """Delete a ``.RPP`` project template from REAPER's ProjectTemplates folder."""
        try:
            path = _resolve_template_path(template_name)
            if not path.exists():
                return {"success": False, "error": f"Template not found: {path}"}
            path.unlink()
            return {
                "success": True,
                "template_name": template_name,
                "deleted": str(path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_project_template(template_name: str) -> dict:
        """Open a project template as the current project.

        The opened project is initially associated with the template's path;
        ``Save As…`` (or ``save_project`` with a new path) to commit edits to
        a different file.
        """
        from reapy import reascript_api as RPR

        try:
            path = _resolve_template_path(template_name)
            if not path.exists():
                return {"success": False, "error": f"Template not found: {path}"}
            RPR.Main_openProject(str(path))
            return {
                "success": True,
                "template_name": template_name,
                "loaded_from": str(path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_default_project_template(template_name: str | None = None, clear: bool = False) -> dict:
        """Mark a project template as the default loaded on REAPER startup.

        REAPER stores this as the ``deftemplate`` config var (an absolute path
        to a ``.RPP`` file). Pass ``clear=True`` to remove the default and have
        REAPER open an empty project on startup.

        This is best-effort — older REAPER versions used different var names,
        and the change takes effect on next REAPER launch. Verify via
        ``system get-reaper-pref deftemplate`` afterwards.
        """
        from reapy import reascript_api as RPR

        try:
            if clear:
                ok = RPR.set_config_var_string("deftemplate", "")
                if not ok:
                    return {
                        "success": False,
                        "error": "set_config_var_string returned False — couldn't clear deftemplate",
                    }
                return {"success": True, "cleared": True}
            if not template_name:
                return {
                    "success": False,
                    "error": "Provide template_name or set clear=True",
                }
            path = _resolve_template_path(template_name)
            if not path.exists():
                return {"success": False, "error": f"Template not found: {path}"}
            ok = RPR.set_config_var_string("deftemplate", str(path))
            if not ok:
                return {
                    "success": False,
                    "error": "set_config_var_string returned False — couldn't set deftemplate",
                    "template_name": template_name,
                    "default_path": str(path),
                }
            return {
                "success": True,
                "template_name": template_name,
                "default_path": str(path),
                "note": "Takes effect on next REAPER launch",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
