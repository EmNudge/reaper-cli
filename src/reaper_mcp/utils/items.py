"""Media item helpers — dual integer-index OR REAPER-pointer-string identification."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("reaper_mcp.utils.items")


def get_item_by_id_or_index(track, item_id: int | str):
    """Resolve ``item_id`` (int index OR string pointer like ``MediaItem*0x...``) to a reapy Item."""
    try:
        idx = int(item_id)
        if 0 <= idx < len(track.items):
            return track.items[idx]
    except (ValueError, TypeError):
        s = str(item_id)
        for it in track.items:
            if str(it.id) == s:
                return it
    return None


def get_item_properties(item) -> dict[str, Any]:
    """Snapshot of an item's main properties — name, position, length, MIDI flag, source path."""
    try:
        position = item.position
        length = item.length
        name = item.active_take.name if item.active_take else ""

        is_audio = False
        source_file = ""
        take = item.active_take
        if take and not take.is_midi:
            is_audio = True
            try:
                if hasattr(take, "source") and hasattr(take.source, "filename"):
                    source_file = take.source.filename
            except Exception as e:
                logger.warning(f"Failed to read source filename: {e}")

        return {
            "position": position,
            "length": length,
            "name": name,
            "is_audio": is_audio,
            "file_path": source_file,
            "muted": getattr(item, "muted", False),
            "selected": getattr(item, "selected", False),
        }
    except Exception as e:
        logger.error(f"Failed to get item properties: {e}")
        return {}


def select_item(item) -> bool:
    """Select ``item`` exclusively (clears other media-item selections first)."""
    try:
        from reapy import reascript_api as RPR

        RPR.SelectAllMediaItems(0, False)
        RPR.SetMediaItemSelected(item.id, True)
        return True
    except Exception as e:
        logger.error(f"Failed to select item: {e}")
        return False


def delete_item(item) -> bool:
    """Delete ``item`` and verify deletion (with brief retries)."""
    try:
        item_id = str(item.id)
        track = item.track
        item.delete()
        time.sleep(0.05)
        for _ in range(3):
            try:
                if not any(str(ti.id) == item_id for ti in track.items):
                    return True
                time.sleep(0.05)
            except Exception:
                return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete item: {e}")
        return False
