"""Track-level tools: create/delete/rename, volume/pan/mute/solo, list/info, color (hex or RGB)."""

import logging

from reaper_mcp.connection import get_project
from reaper_mcp.utils.track_props import (
    get_mute,
    get_pan,
    get_solo,
    get_volume_db,
    set_mute,
    set_pan,
    set_solo,
    set_volume_db,
)

logger = logging.getLogger("reaper_mcp.tools.tracks")


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    s = color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Invalid hex color: {color!r}; expected '#RRGGBB'")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def register_tools(mcp):
    @mcp.tool()
    def create_track(name: str | None = None, track_type: str = "audio") -> dict:
        """Create a new track at the end of the project.

        ``track_type``: ``audio`` (default), ``midi``, ``instrument``, or ``folder``.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            idx = project.n_tracks
            project.add_track(index=idx, name=name or "")
            track = project.tracks[idx]
            if track_type in ("midi", "instrument"):
                RPR.SetMediaTrackInfo_Value(track.id, "I_RECINPUT", 4096)  # All MIDI inputs
            elif track_type == "folder":
                RPR.SetMediaTrackInfo_Value(track.id, "I_FOLDERDEPTH", 1)
            return {
                "success": True,
                "track_index": idx,
                "name": track.name,
                "type": track_type,
            }
        except Exception as e:
            logger.error(f"create_track failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_track(track_index: int) -> dict:
        """Delete a track by its 0-based index."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.DeleteTrack(track.id)
            return {"success": True, "deleted_index": track_index}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def rename_track(track_index: int, name: str) -> dict:
        """Rename a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            track.name = name
            return {"success": True, "track_index": track_index, "name": track.name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_volume(track_index: int, volume_db: float) -> dict:
        """Set track volume in dB. Roughly -150 to +12 dB."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            set_volume_db(track, volume_db)
            return {"success": True, "track_index": track_index, "volume_db": get_volume_db(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_pan(track_index: int, pan: float) -> dict:
        """Set track pan. ``-1.0`` = full left, ``0.0`` = center, ``1.0`` = full right."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            set_pan(track, pan)
            return {"success": True, "track_index": track_index, "pan": get_pan(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_mute(track_index: int, muted: bool) -> dict:
        """Mute or unmute a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            set_mute(track, muted)
            return {"success": True, "track_index": track_index, "muted": get_mute(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_solo(track_index: int, soloed: bool) -> dict:
        """Solo or unsolo a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            set_solo(track, soloed)
            return {"success": True, "track_index": track_index, "soloed": get_solo(track)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_color(
        track_index: int,
        color: str | None = None,
        r: int | None = None,
        g: int | None = None,
        b: int | None = None,
    ) -> dict:
        """Set track color. Accept either a hex string (``#FF0000``) or three RGB ints (0-255)."""
        from reapy import reascript_api as RPR

        try:
            if color is not None:
                rv, gv, bv = _hex_to_rgb(color)
            elif r is not None and g is not None and b is not None:
                rv, gv, bv = int(r), int(g), int(b)
            else:
                return {
                    "success": False,
                    "error": "Provide either a hex 'color' or r/g/b integers",
                }
            project = get_project()
            track = project.tracks[track_index]
            native = RPR.ColorToNative(rv, gv, bv) | 0x1000000
            RPR.SetMediaTrackInfo_Value(track.id, "I_CUSTOMCOLOR", native)
            return {
                "success": True,
                "track_index": track_index,
                "color": f"#{rv:02X}{gv:02X}{bv:02X}",
                "r": rv,
                "g": gv,
                "b": bv,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_color(track_index: int) -> dict:
        """Return a track's color as a ``#RRGGBB`` hex string."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            r, g, b = track.color
            return {
                "success": True,
                "track_index": track_index,
                "color": f"#{r:02X}{g:02X}{b:02X}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_count() -> dict:
        """Return the number of tracks in the current project."""
        try:
            project = get_project()
            return {"success": True, "track_count": project.n_tracks}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_tracks() -> dict:
        """List every track with its basic mixing parameters and FX/item counts."""
        try:
            project = get_project()
            tracks = []
            for i in range(project.n_tracks):
                t = project.tracks[i]
                tracks.append(
                    {
                        "index": i,
                        "name": t.name,
                        "volume_db": get_volume_db(t),
                        "pan": get_pan(t),
                        "muted": get_mute(t),
                        "soloed": get_solo(t),
                        "fx_count": t.n_fxs,
                        "item_count": t.n_items,
                    }
                )
            return {"success": True, "count": len(tracks), "tracks": tracks}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_input(track_index: int, input_type: str, input_channel: int = 0) -> dict:
        """Set a track's record input.

        ``input_type``:
        - ``"none"`` — disabled
        - ``"audio_mono"`` — mono input. ``input_channel``: 0-based input number
        - ``"audio_stereo"`` — stereo pair. ``input_channel``: 0 = inputs 1-2,
          1 = inputs 3-4, etc.
        - ``"midi_all"`` — all MIDI inputs / channels
        """
        from reapy import reascript_api as RPR

        try:
            if input_type == "none":
                value = -1
            elif input_type == "audio_mono":
                value = int(input_channel)
            elif input_type == "audio_stereo":
                value = 1024 + int(input_channel)
            elif input_type == "midi_all":
                value = 4096
            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown input_type {input_type!r}. Use 'none', "
                        "'audio_mono', 'audio_stereo', or 'midi_all'."
                    ),
                }
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_RECINPUT", float(value))
            return {
                "success": True,
                "track_index": track_index,
                "input_type": input_type,
                "input_channel": int(input_channel),
                "raw_value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_record_monitor(track_index: int, mode: str) -> dict:
        """Set a track's input-monitoring behavior.

        ``mode``: ``"off"``, ``"on"`` (always monitor), or
        ``"auto"`` (only monitor when armed and not playing back).
        """
        from reapy import reascript_api as RPR

        _MODES = {"off": 0, "on": 1, "auto": 2}
        if mode not in _MODES:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Use 'off', 'on', or 'auto'.",
            }
        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_RECMON", float(_MODES[mode]))
            return {"success": True, "track_index": track_index, "monitor_mode": mode}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_record_arm(track_index: int, armed: bool) -> dict:
        """Arm or disarm a track for recording."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_RECARM", 1.0 if armed else 0.0)
            return {"success": True, "track_index": track_index, "armed": bool(armed)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_bus(name: str, track_indices: list[int]) -> dict:
        """Create a new bus track and route ``track_indices`` to it via sends."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            bus_idx = project.n_tracks
            project.add_track(index=bus_idx, name=name)
            bus = project.tracks[bus_idx]
            sends = []
            for i in track_indices:
                src = project.tracks[i]
                send_i = RPR.CreateTrackSend(src.id, bus.id)
                sends.append({"track_index": i, "send_index": send_i})
            return {
                "success": True,
                "bus_index": bus_idx,
                "bus_name": name,
                "sends": sends,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def freeze_track(track_index: int, mode: str = "stereo") -> dict:
        """Freeze (render to audio) a track's FX chain, lightening CPU load.

        ``mode``: ``"stereo"`` (default), ``"mono"``, or ``"multichannel"``.
        Use ``unfreeze_track`` to restore live FX. Frozen tracks still play
        the rendered audio so a user can keep mixing while a heavy synth or
        plugin chain is dormant.
        """
        from reapy import reascript_api as RPR

        _ACTIONS = {"stereo": 40901, "mono": 41223, "multichannel": 41644}
        action = _ACTIONS.get(mode)
        if action is None:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Use stereo, mono, or multichannel.",
            }
        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetOnlyTrackSelected(track.id)
            RPR.Main_OnCommand(action, 0)
            return {"success": True, "track_index": track_index, "mode": mode}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def unfreeze_track(track_index: int) -> dict:
        """Unfreeze a previously frozen track — restores its live FX chain."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetOnlyTrackSelected(track.id)
            RPR.Main_OnCommand(40902, 0)  # Track: Unfreeze tracks
            return {"success": True, "track_index": track_index}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_peak(track_index: int, channel: int = 0) -> dict:
        """Return current peak meter value for a track channel — linear and dB.

        ``channel``: 0 = left (or mono), 1 = right (stereo). Higher channel
        numbers map to multichannel track outputs.

        Useful for live monitoring during playback or after a render. Returns
        the instantaneous peak; for time-averaged levels use the analysis tools.
        """
        import math

        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            linear = float(RPR.Track_GetPeakInfo(track.id, int(channel)))
            db = float(20 * math.log10(linear)) if linear > 0 else -120.0
            return {
                "success": True,
                "track_index": track_index,
                "channel": int(channel),
                "peak_linear": round(linear, 6),
                "peak_db": round(db, 2),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def select_track(track_index: int, exclusive: bool = False) -> dict:
        """Select a track.

        ``exclusive=True`` deselects every other track first (equivalent to
        REAPER's ``SetOnlyTrackSelected``).
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            if exclusive:
                RPR.SetOnlyTrackSelected(track.id)
            else:
                RPR.SetTrackSelected(track.id, True)
            return {
                "success": True,
                "track_index": track_index,
                "exclusive": bool(exclusive),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def deselect_track(track_index: int) -> dict:
        """Deselect a track without affecting other tracks' selection state."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetTrackSelected(track.id, False)
            return {"success": True, "track_index": track_index}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_selected_tracks() -> dict:
        """List every selected track in the project."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            out = []
            for i in range(project.n_tracks):
                t = project.tracks[i]
                if RPR.IsTrackSelected(t.id):
                    out.append({"index": i, "name": t.name})
            return {"success": True, "count": len(out), "tracks": out}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_recording_mode(track_index: int, mode: str) -> dict:
        """Set a track's record mode (``I_RECMODE``).

        ``mode``:
        - ``"input"`` (0) — record what the input plays
        - ``"stereo_out"`` (1) — record the track's stereo output
        - ``"none"`` (2) — disabled
        - ``"stereo_out_latency_compensated"`` (3)
        - ``"midi_output"`` (4)
        - ``"mono_out"`` (5)
        - ``"mono_out_latency_compensated"`` (6)
        - ``"midi_overdub"`` (7)
        - ``"midi_replace"`` (8)
        - ``"multichannel_out"`` (9)
        - ``"multichannel_out_latency_compensated"`` (10)
        - ``"midi_touch_replace"`` (11)
        - ``"midi_latch_replace"`` (12)
        """
        from reapy import reascript_api as RPR

        _MODES = {
            "input": 0,
            "stereo_out": 1,
            "none": 2,
            "stereo_out_latency_compensated": 3,
            "midi_output": 4,
            "mono_out": 5,
            "mono_out_latency_compensated": 6,
            "midi_overdub": 7,
            "midi_replace": 8,
            "multichannel_out": 9,
            "multichannel_out_latency_compensated": 10,
            "midi_touch_replace": 11,
            "midi_latch_replace": 12,
        }
        if mode not in _MODES:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Valid: {sorted(_MODES)}",
            }
        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_RECMODE", float(_MODES[mode]))
            return {
                "success": True,
                "track_index": track_index,
                "mode": mode,
                "raw_value": _MODES[mode],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_height(track_index: int, height_pixels: int, locked: bool = False) -> dict:
        """Set a track's display height in pixels. ``locked=True`` locks the height."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_HEIGHTOVERRIDE", float(int(height_pixels)))
            RPR.SetMediaTrackInfo_Value(track.id, "B_HEIGHTLOCK", 1.0 if locked else 0.0)
            return {
                "success": True,
                "track_index": track_index,
                "height_pixels": int(height_pixels),
                "locked": bool(locked),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_visible(
        track_index: int,
        show_in_tcp: bool | None = None,
        show_in_mixer: bool | None = None,
    ) -> dict:
        """Show / hide a track in the Track Control Panel and/or Mixer Control Panel.

        Pass ``None`` for either flag to leave it unchanged.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            if show_in_tcp is not None:
                RPR.SetMediaTrackInfo_Value(track.id, "B_SHOWINTCP", 1.0 if show_in_tcp else 0.0)
            if show_in_mixer is not None:
                RPR.SetMediaTrackInfo_Value(
                    track.id, "B_SHOWINMIXER", 1.0 if show_in_mixer else 0.0
                )
            return {
                "success": True,
                "track_index": track_index,
                "show_in_tcp": show_in_tcp,
                "show_in_mixer": show_in_mixer,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_icon(track_index: int, icon_path: str | None) -> dict:
        """Set a track's icon to an image file, or clear it with ``None`` / empty string.

        ``icon_path`` should be an absolute path to a PNG/JPG/etc. file; pass
        ``None`` or ``""`` to remove the current icon.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            value = "" if icon_path is None else str(icon_path)
            ok = RPR.GetSetMediaTrackInfo_String(track.id, "P_ICON", value, True)
            if not ok:
                return {"success": False, "error": "GetSetMediaTrackInfo_String returned False"}
            return {
                "success": True,
                "track_index": track_index,
                "icon_path": value or None,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_automation_mode(track_index: int, mode: str) -> dict:
        """Set a track's automation read/write behaviour (``I_AUTOMODE``).

        ``mode``: ``"trim"`` (read off, fader free), ``"read"``, ``"touch"``,
        ``"latch"``, ``"write"``, ``"latch_preview"``.
        """
        from reapy import reascript_api as RPR

        _MODES = {
            "trim": 0,
            "read": 1,
            "touch": 2,
            "write": 3,
            "latch": 4,
            "latch_preview": 5,
        }
        if mode not in _MODES:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Valid: {sorted(_MODES)}",
            }
        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_AUTOMODE", float(_MODES[mode]))
            return {
                "success": True,
                "track_index": track_index,
                "mode": mode,
                "raw_value": _MODES[mode],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_automation_mode(track_index: int) -> dict:
        """Return a track's automation mode."""
        from reapy import reascript_api as RPR

        _NAMES = {
            0: "trim",
            1: "read",
            2: "touch",
            3: "write",
            4: "latch",
            5: "latch_preview",
        }
        try:
            project = get_project()
            track = project.tracks[track_index]
            value = int(RPR.GetMediaTrackInfo_Value(track.id, "I_AUTOMODE"))
            return {
                "success": True,
                "track_index": track_index,
                "mode": _NAMES.get(value, f"unknown_{value}"),
                "raw_value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_midi_input(
        track_index: int,
        device_index: int,
        channel: int = 0,
        all_channels: bool = False,
    ) -> dict:
        """Set the per-device, per-channel MIDI input for a track.

        ``device_index``: 0-based MIDI input device. ``channel``: 0-15 (one
        channel), or set ``all_channels=True`` to receive every channel from
        that device. The ``midi_all`` convenience case (every device, every
        channel) lives in ``set_track_input(input_type="midi_all")``.
        """
        from reapy import reascript_api as RPR

        try:
            if device_index < 0 or device_index > 62:
                return {"success": False, "error": "device_index must be 0-62"}
            if not 0 <= channel <= 15 and not all_channels:
                return {"success": False, "error": "channel must be 0-15"}
            chan_bits = 0 if all_channels else int(channel) + 1
            value = 4096 | (int(device_index) << 5) | chan_bits
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_RECINPUT", float(value))
            return {
                "success": True,
                "track_index": track_index,
                "device_index": int(device_index),
                "channel": int(channel),
                "all_channels": bool(all_channels),
                "raw_value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_mixer_order(track_index: int, mcp_x: int) -> dict:
        """Reorder a track in the Mixer Control Panel (``I_MCPX`` slot).

        Note: MCP positions are independent of TCP positions; this only moves
        the track horizontally in the Mixer view.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            RPR.SetMediaTrackInfo_Value(track.id, "I_MCPX", float(int(mcp_x)))
            return {
                "success": True,
                "track_index": track_index,
                "mcp_x": int(mcp_x),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def move_track(track_index: int, new_position: int) -> dict:
        """Move a track to a new position in the project (renumbering everything below).

        Uses REAPER's track-reorder commands. ``new_position`` is the target
        0-based index in the TCP; pass ``project.n_tracks`` to move to the end.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            n = project.n_tracks
            if not 0 <= track_index < n:
                return {"success": False, "error": f"track_index {track_index} out of range"}
            if not 0 <= new_position <= n:
                return {"success": False, "error": f"new_position {new_position} out of range"}
            track = project.tracks[track_index]
            # Use ReorderSelectedTracks: select only the source, then call API.
            RPR.SetOnlyTrackSelected(track.id)
            ok = RPR.ReorderSelectedTracks(int(new_position), 0)
            if not ok:
                return {"success": False, "error": "ReorderSelectedTracks returned False"}
            return {
                "success": True,
                "from_index": track_index,
                "to_position": int(new_position),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_info(track_index: int) -> dict:
        """Detailed info about a single track including its FX chain and items."""
        try:
            project = get_project()
            t = project.tracks[track_index]
            fx_list = []
            for i in range(t.n_fxs):
                fx = t.fxs[i]
                fx_list.append({"index": i, "name": fx.name, "enabled": fx.is_enabled})
            items = []
            for i in range(t.n_items):
                it = t.items[i]
                items.append(
                    {
                        "index": i,
                        "position": it.position,
                        "length": it.length,
                        "name": it.name,
                    }
                )
            return {
                "success": True,
                "track_index": track_index,
                "name": t.name,
                "volume_db": get_volume_db(t),
                "pan": get_pan(t),
                "muted": get_mute(t),
                "soloed": get_solo(t),
                "fx_count": t.n_fxs,
                "fx": fx_list,
                "item_count": t.n_items,
                "items": items,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
