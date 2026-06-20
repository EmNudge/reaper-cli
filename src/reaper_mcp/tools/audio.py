"""Audio import + transport tools."""

import logging
import os
import time

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import position_to_time, resolve_start, time_to_measure

logger = logging.getLogger("reaper_mcp.tools.audio")


def register_tools(mcp):
    @mcp.tool()
    def import_audio_file(
        track_index: int,
        file_path: str,
        start_time: float | None = None,
        start_measure: str | None = None,
    ) -> dict:
        """Import an audio file onto a track at the given position.

        Position is ``0.0s`` if neither ``start_time`` nor ``start_measure`` is given.
        Supports every format REAPER can read (wav, aiff, mp3, flac, ogg, …).
        """
        from reapy import reascript_api as RPR

        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"File not found: {file_path}"}
            project = get_project()
            track = project.tracks[track_index]
            if start_time is None and start_measure is None:
                pos = 0.0
                pos_ms = "0:0,000"
            else:
                pos, pos_ms = resolve_start(start_time, start_measure, project)

            RPR.SetOnlyTrackSelected(track.id)
            project.cursor_position = pos
            n_before = len(track.items)
            RPR.InsertMedia(file_path, 0)
            time.sleep(0.1)
            track = project.tracks[track_index]  # refresh
            if len(track.items) <= n_before:
                return {"success": False, "error": "Insert succeeded but no item appeared"}
            item = track.items[-1]
            return {
                "success": True,
                "track_index": track_index,
                "item_index": len(track.items) - 1,
                "direct_item_id": str(item.id),
                "position": {"time": item.position, "measure": pos_ms},
                "length": item.length,
                "file_path": file_path,
            }
        except Exception as e:
            logger.error(f"import_audio_file failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def start_recording(track_index: int) -> dict:
        """Arm a track and start recording. Call ``stop_transport`` when done."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            track.armed = True
            RPR.Main_OnCommand(1013, 0)  # Transport: Record
            return {
                "success": True,
                "track_index": track_index,
                "message": "Recording started — call stop_transport to stop.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def stop_transport() -> dict:
        """Stop playback or recording."""
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(1016, 0)  # Transport: Stop
            return {"success": True, "message": "Transport stopped"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def play_project() -> dict:
        """Start playback from the current cursor position."""
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(1007, 0)
            return {"success": True, "message": "Playback started"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def pause_project() -> dict:
        """Pause playback (cursor stays at the current play position).

        Use ``play_project`` to resume, or ``stop_transport`` to stop and
        return the cursor to its pre-play position.
        """
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(1008, 0)  # Transport: Pause
            return {"success": True, "message": "Playback paused"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_cursor_position(
        position_time: float | None = None, position_measure: str | None = None
    ) -> dict:
        """Move the edit cursor. Accept seconds OR ``M:B,F`` string."""
        try:
            project = get_project()
            pos, pos_ms = resolve_start(position_time, position_measure, project)
            project.cursor_position = pos
            return {
                "success": True,
                "position": {"time": project.cursor_position, "measure": pos_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def adjust_pitch(track_index: int, item_index: int, semitones: float) -> dict:
        """Adjust pitch of an audio item's active take, in semitones (fractional OK)."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            item = track.items[item_index]
            take = item.active_take
            take.pitch = semitones
            return {
                "success": True,
                "track_index": track_index,
                "item_index": item_index,
                "pitch_semitones": take.pitch,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def adjust_playback_rate(track_index: int, item_index: int, rate: float) -> dict:
        """Adjust take playback rate. ``1.0`` = normal speed."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            item = track.items[item_index]
            take = item.active_take
            take.playback_rate = rate
            return {
                "success": True,
                "track_index": track_index,
                "item_index": item_index,
                "playback_rate": take.playback_rate,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_playback_state() -> dict:
        """Return current transport state — whether playback / recording is active.

        REAPER's GetPlayState bitmask: 1 = playing, 2 = paused, 4 = recording.
        """
        from reapy import reascript_api as RPR

        try:
            state = int(RPR.GetPlayState())
            return {
                "success": True,
                "playing": bool(state & 1),
                "paused": bool(state & 2),
                "recording": bool(state & 4),
                "raw_flags": state,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_playhead_position() -> dict:
        """Return current playback position (in seconds and M:B,F)."""
        try:
            project = get_project()
            pos = project.play_position
            return {
                "success": True,
                "position": {"time": pos, "measure": time_to_measure(pos, project)},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_cursor_position() -> dict:
        """Return current edit-cursor position (in seconds and M:B,F)."""
        try:
            project = get_project()
            pos = project.cursor_position
            return {
                "success": True,
                "position": {"time": pos, "measure": time_to_measure(pos, project)},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_time_selection() -> dict:
        """Return the project's time selection — start, end, length, both formats.

        Start == end == 0 means no time selection is active.
        """
        try:
            project = get_project()
            ts = project.time_selection
            start, end = ts.start, ts.end
            return {
                "success": True,
                "start": {"time": start, "measure": time_to_measure(start, project)},
                "end": {"time": end, "measure": time_to_measure(end, project)},
                "length": end - start,
                "active": end > start,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_time_selection(
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
    ) -> dict:
        """Set the project's time selection. Accept seconds or M:B,F for both ends."""
        try:
            project = get_project()
            s, s_ms = resolve_start(start_time, start_measure, project)
            if end_time is not None:
                e = float(end_time)
                e_ms = time_to_measure(e, project)
            elif end_measure is not None:
                e = position_to_time(end_measure, project)
                e_ms = end_measure
            else:
                return {"success": False, "error": "Provide end_time or end_measure"}
            project.time_selection = (s, e)
            return {
                "success": True,
                "start": {"time": s, "measure": s_ms},
                "end": {"time": e, "measure": e_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_time_selection() -> dict:
        """Clear (deactivate) the project's time selection."""
        try:
            project = get_project()
            project.time_selection = (0.0, 0.0)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_loop_enabled() -> dict:
        """Return whether the loop / repeat playback state is currently on."""
        from reapy import reascript_api as RPR

        try:
            state = int(RPR.GetSetRepeat(-1))
            return {"success": True, "loop_enabled": bool(state)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_loop_enabled(enabled: bool) -> dict:
        """Turn the loop / repeat playback state on or off."""
        from reapy import reascript_api as RPR

        try:
            RPR.GetSetRepeat(1 if enabled else 0)
            return {"success": True, "loop_enabled": bool(enabled)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def edit_audio_item(
        track_index: int,
        item_index: int,
        start_trim: float = 0.0,
        end_trim: float = 0.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> dict:
        """Trim and/or fade an audio item. All values in seconds."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            item = track.items[item_index]
            if start_trim > 0:
                item.position += start_trim
                item.length -= start_trim
                take = item.active_take
                if take:
                    take.start_offset += start_trim
            if end_trim > 0:
                item.length -= end_trim
            if fade_in > 0:
                item.fade_in_length = fade_in
            if fade_out > 0:
                item.fade_out_length = fade_out
            return {
                "success": True,
                "track_index": track_index,
                "item_index": item_index,
                "position": item.position,
                "length": item.length,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
