"""FX chain template tools — save / apply / list `.RfxChain` files.

An FX chain template captures a track's entire FX chain (effects, params,
presets) without the surrounding track config. Apply it to any track to drop
that chain in.

REAPER stores these under ``<resource>/FXChains/``. The file format is the
``<FXCHAIN ... >`` block from a track state chunk — we read/write that block
directly via ``GetTrackStateChunk`` / ``SetTrackStateChunk``.
"""

import logging
import os
import re
from pathlib import Path

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.fx_chain_templates")


def _resource_path() -> Path:
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac


def _chains_dir() -> Path:
    return _resource_path() / "FXChains"


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip()


def _resolve_chain_path(template_name: str) -> Path:
    parts = [_sanitize(seg) for seg in template_name.replace("\\", "/").split("/")]
    parts[-1] = parts[-1].removesuffix(".RfxChain")
    return _chains_dir().joinpath(*parts).with_suffix(".RfxChain")


def _extract_chunk(result) -> str:
    """Pull the chunk string out of a python-reapy ``GetTrackStateChunk`` return."""
    if isinstance(result, tuple):
        strings = [s for s in result if isinstance(s, str) and len(s) > 32]
        return strings[0] if strings else ""
    return str(result)


def _find_fxchain_block(chunk: str) -> tuple[int, int]:
    """Return ``(start_offset, end_offset_exclusive)`` of the ``<FXCHAIN ... >``
    block in ``chunk``, or ``(-1, -1)`` if not present.

    Handles nested ``< ... >`` blocks (VST entries) via bracket counting.
    """
    m = re.search(r"^\s*<FXCHAIN\b", chunk, re.MULTILINE)
    if not m:
        return -1, -1
    start = m.start()
    depth = 0
    i = start
    while i < len(chunk):
        ch = chunk[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                # Include the line ending after the closing >
                end = chunk.find("\n", i)
                return start, (end + 1 if end != -1 else i + 1)
        i += 1
    return -1, -1


def register_tools(mcp):
    @mcp.tool()
    def list_fx_chain_templates() -> dict:
        """List every ``.RfxChain`` file under REAPER's FXChains folder."""
        try:
            root = _chains_dir()
            if not root.exists():
                return {
                    "success": True,
                    "chains_dir": str(root),
                    "count": 0,
                    "templates": [],
                    "note": "FXChains directory does not exist yet",
                }
            templates = []
            for p in root.rglob("*.RfxChain"):
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
                "chains_dir": str(root),
                "count": len(templates),
                "templates": templates,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def save_fx_chain_template(track_index: int, template_name: str) -> dict:
        """Save a track's current FX chain as a reusable ``.RfxChain`` template.

        ``template_name`` supports subdirectories like ``"Vocals/De-esser+Comp"``.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            chunk = _extract_chunk(RPR.GetTrackStateChunk(track.id, "", 1024 * 1024, False))
            if not chunk:
                return {"success": False, "error": "Failed to read track state chunk"}
            start, end = _find_fxchain_block(chunk)
            if start < 0:
                return {
                    "success": False,
                    "error": "Track has no FXCHAIN block (no FX on this track)",
                }
            target = _resolve_chain_path(template_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chunk[start:end], encoding="utf-8")
            return {
                "success": True,
                "track_index": track_index,
                "template_name": template_name,
                "saved_to": str(target),
                "size_bytes": target.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_fx_chain_template(track_index: int, template_name: str, replace: bool = True) -> dict:
        """Apply a saved FX chain to a track.

        ``replace`` (default True): replace the track's existing FX chain with
        the template. Set to False to append the template's FX after the
        track's current FX.
        """
        from reapy import reascript_api as RPR

        try:
            path = _resolve_chain_path(template_name)
            if not path.exists():
                return {"success": False, "error": f"Template not found: {path}"}
            template_chunk = path.read_text(encoding="utf-8")

            project = get_project()
            track = project.tracks[track_index]
            chunk = _extract_chunk(RPR.GetTrackStateChunk(track.id, "", 1024 * 1024, False))
            if not chunk:
                return {"success": False, "error": "Failed to read track state chunk"}

            start, end = _find_fxchain_block(chunk)
            if start >= 0:
                if replace:
                    new_chunk = chunk[:start] + template_chunk + chunk[end:]
                    mode = "replace"
                else:
                    # Append: splice the template's inner FX entries (everything
                    # between its opening "<FXCHAIN …" line and its closing ">")
                    # in just before the existing FXCHAIN block's closing ">".
                    template_first_nl = template_chunk.find("\n")
                    template_last_gt = template_chunk.rstrip().rfind(">")
                    if template_first_nl < 0 or template_last_gt <= template_first_nl:
                        return {
                            "success": False,
                            "error": "Malformed template — could not extract inner FX entries",
                        }
                    template_inner = template_chunk[template_first_nl + 1 : template_last_gt]
                    block_text = chunk[start:end]
                    existing_last_gt = start + block_text.rstrip("\n").rfind(">")
                    if existing_last_gt < start:
                        return {
                            "success": False,
                            "error": "Could not locate existing FXCHAIN block's closing '>'",
                        }
                    new_chunk = chunk[:existing_last_gt] + template_inner + chunk[existing_last_gt:]
                    mode = "append"
            else:
                # No existing FXCHAIN — insert before the closing track > at end.
                # The track chunk ends with a line containing just `>`; insert before it.
                lines = chunk.rstrip("\n").rsplit("\n", 1)
                if len(lines) == 2 and lines[1].strip() == ">":
                    new_chunk = lines[0] + "\n" + template_chunk + lines[1] + "\n"
                else:
                    new_chunk = chunk + "\n" + template_chunk
                mode = "replace"

            ok = RPR.SetTrackStateChunk(track.id, new_chunk, False)
            if not ok:
                return {
                    "success": False,
                    "error": "SetTrackStateChunk returned False — REAPER rejected the new chunk",
                    "track_index": track_index,
                    "template_name": template_name,
                }
            return {
                "success": True,
                "track_index": track_index,
                "template_name": template_name,
                "mode": mode,
                "source_file": str(path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
