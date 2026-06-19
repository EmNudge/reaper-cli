"""Send routing tools — track-to-track sends, hardware sends, MIDI sends.

For track-level recording config (record input, monitor, arm, bus creation)
see ``tracks.py``. For volume/pan automation see ``envelopes.add_envelope_point``
with envelope names ``"Volume"`` and ``"Pan"``.
"""

import logging

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.sends")


def _db_to_linear(db: float) -> float:
    if db <= -150:
        return 0.0
    return 10 ** (db / 20.0)


def register_tools(mcp):
    @mcp.tool()
    def create_send(source_track_index: int, dest_track_index: int, volume_db: float = 0.0) -> dict:
        """Create a stereo post-fader aux send from one track to another."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            src = project.tracks[source_track_index]
            dst = project.tracks[dest_track_index]
            send_idx = RPR.CreateTrackSend(src.id, dst.id)
            if send_idx < 0:
                return {"success": False, "error": "Failed to create send"}
            RPR.SetTrackSendInfo_Value(src.id, 0, send_idx, "D_VOL", _db_to_linear(volume_db))
            return {
                "success": True,
                "source_track_index": source_track_index,
                "dest_track_index": dest_track_index,
                "send_index": send_idx,
                "volume_db": volume_db,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_sends(track_index: int) -> dict:
        """List all aux sends from a track."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            n = RPR.GetTrackNumSends(track.id, 0)
            sends = []
            for i in range(n):
                vol = RPR.GetTrackSendInfo_Value(track.id, 0, i, "D_VOL")
                pan = RPR.GetTrackSendInfo_Value(track.id, 0, i, "D_PAN")
                muted = bool(RPR.GetTrackSendInfo_Value(track.id, 0, i, "B_MUTE"))
                sends.append(
                    {
                        "send_index": i,
                        "volume_linear": vol,
                        "pan": pan,
                        "muted": muted,
                    }
                )
            return {"success": True, "track_index": track_index, "sends": sends}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def remove_send(source_track_index: int, send_index: int) -> dict:
        """Remove a send from a track by its index."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[source_track_index]
            RPR.RemoveTrackSend(track.id, 0, send_index)
            return {
                "success": True,
                "source_track_index": source_track_index,
                "send_index": send_index,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_send_volume(source_track_index: int, send_index: int, volume_db: float) -> dict:
        """Set the volume of an existing send in dB."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[source_track_index]
            RPR.SetTrackSendInfo_Value(track.id, 0, send_index, "D_VOL", _db_to_linear(volume_db))
            return {
                "success": True,
                "source_track_index": source_track_index,
                "send_index": send_index,
                "volume_db": volume_db,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_hardware_send(
        track_index: int, hw_output_channel: int, volume_db: float = 0.0
    ) -> dict:
        """Send a track's output to a hardware output channel.

        ``hw_output_channel``: 0-based output channel index of your audio
        interface (0 = first output). Stereo sends are routed to a pair starting
        at this channel.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            send_idx = RPR.CreateTrackSend(track.id, None)
            if send_idx < 0:
                return {"success": False, "error": "Failed to create hardware send"}
            RPR.SetTrackSendInfo_Value(track.id, 1, send_idx, "I_DSTCHAN", int(hw_output_channel))
            RPR.SetTrackSendInfo_Value(track.id, 1, send_idx, "D_VOL", _db_to_linear(volume_db))
            return {
                "success": True,
                "track_index": track_index,
                "send_index": send_idx,
                "hw_output_channel": int(hw_output_channel),
                "volume_db": volume_db,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_midi_send(
        source_track_index: int,
        dest_track_index: int,
        source_channel: int = 0,
        dest_channel: int = 0,
    ) -> dict:
        """Create a MIDI-only send from one track to another with channel mapping.

        ``source_channel``: which channels of the source feed the send.
        ``0`` = all MIDI channels, ``1-16`` = specific channel.
        ``dest_channel``: which channel the destination receives on.
        ``0`` = pass through unchanged, ``1-16`` = remap to this channel.

        Common use: one MIDI track triggering several softsynths each on a
        different channel.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            src = project.tracks[source_track_index]
            dst = project.tracks[dest_track_index]
            send_idx = RPR.CreateTrackSend(src.id, dst.id)
            if send_idx < 0:
                return {"success": False, "error": "Failed to create send"}
            midi_flags = (int(source_channel) & 0x1F) | ((int(dest_channel) & 0x1F) << 5)
            RPR.SetTrackSendInfo_Value(src.id, 0, send_idx, "I_MIDIFLAGS", float(midi_flags))
            RPR.SetTrackSendInfo_Value(src.id, 0, send_idx, "I_SRCCHAN", -1.0)
            return {
                "success": True,
                "source_track_index": source_track_index,
                "dest_track_index": dest_track_index,
                "send_index": send_idx,
                "source_channel": int(source_channel),
                "dest_channel": int(dest_channel),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_send_mode(source_track_index: int, send_index: int, mode: str) -> dict:
        """Set a send's routing point relative to the source track's signal chain.

        ``mode``: ``"post_fader"`` (default REAPER position),
        ``"pre_fx"`` (before any FX), or ``"post_fx_pre_fader"`` (after FX, before fader/pan).
        """
        from reapy import reascript_api as RPR

        _MODES = {"post_fader": 0, "pre_fx": 1, "post_fx_pre_fader": 3}
        if mode not in _MODES:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Use {list(_MODES)}.",
            }
        try:
            project = get_project()
            track = project.tracks[source_track_index]
            RPR.SetTrackSendInfo_Value(track.id, 0, send_index, "I_SENDMODE", float(_MODES[mode]))
            return {
                "success": True,
                "source_track_index": source_track_index,
                "send_index": send_index,
                "mode": mode,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_send_phase(source_track_index: int, send_index: int, invert: bool) -> dict:
        """Invert the polarity (phase) of a send."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[source_track_index]
            RPR.SetTrackSendInfo_Value(track.id, 0, send_index, "B_PHASE", 1.0 if invert else 0.0)
            return {
                "success": True,
                "source_track_index": source_track_index,
                "send_index": send_index,
                "invert": bool(invert),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
