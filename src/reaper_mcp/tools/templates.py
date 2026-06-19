"""Track-template tools — save / apply / list ``.RTrackTemplate`` files.

REAPER stores track templates as plain-text chunks under the resource
directory's ``TrackTemplates`` folder. We use the public ``GetTrackStateChunk``
and ``SetTrackStateChunk`` APIs for save and apply; no need for SWS.

Saving a chain like "Vocal: EQ → Comp → De-esser → Reverb Send" once turns
"make a vocal chain" into a single tool call from the LLM.
"""

import logging
import os
from pathlib import Path

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.templates")


def _resource_path() -> Path:
    """Locate the user's REAPER resource directory."""
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac  # default; will error later if missing


def _templates_dir() -> Path:
    return _resource_path() / "TrackTemplates"


def _sanitize(name: str) -> str:
    """Make ``name`` safe for use as a filename."""
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()


def register_tools(mcp):
    @mcp.tool()
    def list_track_templates() -> dict:
        """List every ``.RTrackTemplate`` file under REAPER's TrackTemplates folder.

        Includes nested subdirectories so you can keep templates organized
        (e.g. ``Vocals/Lead.RTrackTemplate``).
        """
        try:
            root = _templates_dir()
            if not root.exists():
                return {
                    "success": True,
                    "count": 0,
                    "templates": [],
                    "templates_dir": str(root),
                    "note": "TrackTemplates directory does not exist yet",
                }
            templates = []
            for p in root.rglob("*.RTrackTemplate"):
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
    def save_track_template(track_index: int, template_name: str) -> dict:
        """Save a track (with its FX chain, sends, params) as a track template.

        ``template_name`` may include subdirectories using forward slashes
        (e.g. ``"Vocals/Lead"``). The ``.RTrackTemplate`` extension is added
        automatically.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            result = RPR.GetTrackStateChunk(track.id, "", 1024 * 1024, False)
            # python-reapy returns a tuple; the chunk is the largest non-empty string
            if isinstance(result, tuple):
                strings = [s for s in result if isinstance(s, str) and len(s) > 32]
                chunk = strings[0] if strings else ""
                ok = result[0] if isinstance(result[0], bool) else True
            else:
                chunk = str(result)
                ok = True
            if not chunk:
                return {"success": False, "error": "Failed to read track state chunk"}

            parts = [_sanitize(seg) for seg in template_name.replace("\\", "/").split("/")]
            parts[-1] = parts[-1].removesuffix(".RTrackTemplate")
            target = _templates_dir().joinpath(*parts).with_suffix(".RTrackTemplate")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chunk, encoding="utf-8")
            return {
                "success": bool(ok),
                "track_index": track_index,
                "template_name": template_name,
                "saved_to": str(target),
                "size_bytes": target.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_track_template(template_name: str, target_track_index: int | None = None) -> dict:
        """Apply a track template to a track.

        Pass ``target_track_index`` to overwrite an existing track's chain.
        Omit it to create a new track at the end of the project with the
        template applied.
        """
        from reapy import reascript_api as RPR

        try:
            # Resolve template file
            parts = [_sanitize(seg) for seg in template_name.replace("\\", "/").split("/")]
            parts[-1] = parts[-1].removesuffix(".RTrackTemplate")
            path = _templates_dir().joinpath(*parts).with_suffix(".RTrackTemplate")
            if not path.exists():
                return {
                    "success": False,
                    "error": f"Template not found: {path}",
                }
            chunk = path.read_text(encoding="utf-8")

            project = get_project()
            if target_track_index is None:
                idx = project.n_tracks
                project.add_track(index=idx, name="")
                track = project.tracks[idx]
                created = True
            else:
                track = project.tracks[int(target_track_index)]
                idx = int(target_track_index)
                created = False

            ok = RPR.SetTrackStateChunk(track.id, chunk, False)
            return {
                "success": bool(ok),
                "template_name": template_name,
                "track_index": idx,
                "created_new_track": created,
                "source_file": str(path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
