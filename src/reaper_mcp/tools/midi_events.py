"""MIDI events beyond notes — CC, pitch bend, program change, channel pressure, sysex.

For notes (add/remove/query), see ``midi_notes.py``. This module covers every
other MIDI event type.

Position arguments accept either seconds (float) OR ``"M:B,F"`` (string); they
are converted to PPQ (pulses per quarter note) internally for REAPER's API.
"""

import logging
from typing import Any

from reaper_mcp.connection import get_project
from reaper_mcp.utils.items import get_item_by_id_or_index
from reaper_mcp.utils.positions import resolve_start, time_to_measure

logger = logging.getLogger("reaper_mcp.tools.midi_events")

# Channel-message status bytes
_CC = 0xB0
_PROGRAM_CHANGE = 0xC0
_CHANNEL_PRESSURE = 0xD0
_PITCH_BEND = 0xE0


def _get_midi_take(track_index, item):
    project = get_project()
    track = project.tracks[track_index]
    it = get_item_by_id_or_index(track, item)
    if it is None:
        raise ValueError(f"Item not found on track {track_index}")
    take = it.active_take
    if take is None or not take.is_midi:
        raise ValueError("Item has no MIDI take")
    return project, track, it, take


def _ppq_at(take, position_time, position_measure, project):
    """Resolve a position to PPQ. Returns ``(ppq, seconds, measure_string)``."""
    from reapy import reascript_api as RPR

    seconds, measure_str = resolve_start(position_time, position_measure, project)
    ppq = RPR.MIDI_GetPPQPosFromProjTime(take.id, seconds)
    return ppq, seconds, measure_str


def _time_from_ppq(take, ppq, project):
    from reapy import reascript_api as RPR

    seconds = RPR.MIDI_GetProjTimeFromPPQPos(take.id, ppq)
    return seconds, time_to_measure(seconds, project)


def register_tools(mcp):
    @mcp.tool()
    def add_midi_cc(
        track_index: int,
        item: int | str,
        cc_number: int,
        value: int,
        channel: int = 0,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Insert a single MIDI CC (control change) event.

        cc_number: 0-127. Common: 1=mod wheel, 7=volume, 10=pan, 11=expression,
        64=sustain pedal, 71=resonance, 74=brightness/cutoff, 91=reverb send.
        value: 0-127. channel: 0-15.
        Position accepts seconds (float) or M:B,F (string).
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq, seconds, ms = _ppq_at(take, position_time, position_measure, project)
            RPR.MIDI_InsertCC(
                take.id,
                False,
                False,
                ppq,
                _CC,
                int(channel),
                int(cc_number),
                int(value),
            )
            return {
                "success": True,
                "cc_number": int(cc_number),
                "value": int(value),
                "channel": int(channel),
                "position": {"time": seconds, "measure": ms, "ppq": ppq},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_ccs(
        track_index: int,
        item: int | str,
        events: list[dict[str, Any]],
    ) -> dict:
        """Insert multiple MIDI CC events in one call.

        Each ``events`` entry: ``cc_number`` (int), ``value`` (int), optional
        ``channel`` (default 0), and one of ``position_time`` (float seconds)
        or ``position_measure`` (M:B,F string).

        Useful for drawing automation curves — e.g. a 32-point modwheel ramp.
        """
        try:
            results, errors = [], []
            for i, ev in enumerate(events):
                r = add_midi_cc(
                    track_index=track_index,
                    item=item,
                    cc_number=int(ev["cc_number"]),
                    value=int(ev["value"]),
                    channel=int(ev.get("channel", 0)),
                    position_time=ev.get("position_time"),
                    position_measure=ev.get("position_measure"),
                )
                (results if r.get("success") else errors).append(
                    {"index": i, "event": ev, "result": r}
                )
            return {
                "success": not errors,
                "partial": bool(results) and bool(errors),
                "added": len(results),
                "failed": len(errors),
                "successful_events": results,
                "failed_events": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_pitch_bend(
        track_index: int,
        item: int | str,
        value: int,
        channel: int = 0,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Insert a MIDI pitch-bend event.

        value: -8192 (full down) to +8191 (full up); 0 is center.
        REAPER stores pitch bend as 14 bits split across two 7-bit message bytes.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq, seconds, ms = _ppq_at(take, position_time, position_measure, project)
            v = max(-8192, min(8191, int(value))) + 8192  # → 0..16383 unsigned
            lsb = v & 0x7F
            msb = (v >> 7) & 0x7F
            RPR.MIDI_InsertCC(take.id, False, False, ppq, _PITCH_BEND, int(channel), lsb, msb)
            return {
                "success": True,
                "value": int(value),
                "channel": int(channel),
                "position": {"time": seconds, "measure": ms, "ppq": ppq},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_program_change(
        track_index: int,
        item: int | str,
        program: int,
        channel: int = 0,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Insert a MIDI program-change event.

        program: 0-127 (GM patch number, 0=Acoustic Grand Piano, etc.).
        channel: 0-15.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq, seconds, ms = _ppq_at(take, position_time, position_measure, project)
            RPR.MIDI_InsertCC(
                take.id,
                False,
                False,
                ppq,
                _PROGRAM_CHANGE,
                int(channel),
                int(program),
                0,
            )
            return {
                "success": True,
                "program": int(program),
                "channel": int(channel),
                "position": {"time": seconds, "measure": ms, "ppq": ppq},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_channel_pressure(
        track_index: int,
        item: int | str,
        value: int,
        channel: int = 0,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Insert a MIDI channel-pressure (aftertouch) event.

        value: 0-127. channel: 0-15.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq, seconds, ms = _ppq_at(take, position_time, position_measure, project)
            RPR.MIDI_InsertCC(
                take.id,
                False,
                False,
                ppq,
                _CHANNEL_PRESSURE,
                int(channel),
                int(value),
                0,
            )
            return {
                "success": True,
                "value": int(value),
                "channel": int(channel),
                "position": {"time": seconds, "measure": ms, "ppq": ppq},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_sysex(
        track_index: int,
        item: int | str,
        data_hex: str,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Insert a raw MIDI sysex event.

        data_hex: hex-encoded bytes WITHOUT the F0/F7 framing, e.g.
        ``"43 10 4C 00 00 7E 00"`` (Yamaha sysex). Whitespace is ignored.
        REAPER adds F0/F7 framing automatically.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq, seconds, ms = _ppq_at(take, position_time, position_measure, project)
            cleaned = data_hex.replace(" ", "").replace(",", "").lower()
            if cleaned.startswith("0x"):
                cleaned = cleaned[2:]
            byte_str = bytes.fromhex(cleaned).decode("latin-1")
            RPR.MIDI_InsertTextSysexEvt(take.id, False, False, ppq, -1, byte_str, len(byte_str))
            return {
                "success": True,
                "byte_count": len(byte_str),
                "position": {"time": seconds, "measure": ms, "ppq": ppq},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_midi_ccs(
        track_index: int,
        item: int | str,
        cc_number: int | None = None,
        channel: int | None = None,
    ) -> dict:
        """Return all MIDI CC / pitch-bend / program-change / channel-pressure events on an item.

        Optional filters: ``cc_number`` limits to a specific CC, ``channel`` to a
        single MIDI channel (0-15).

        Each returned event has a ``type`` field — ``cc``, ``pitch_bend``,
        ``program_change``, or ``channel_pressure`` — plus the appropriate
        decoded fields.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            counts = RPR.MIDI_CountEvts(take.id, 0, 0, 0)
            cc_count = counts[2] if isinstance(counts, tuple) else 0
            out = []
            for i in range(cc_count):
                result = RPR.MIDI_GetCC(take.id, i, False, False, 0, 0, 0, 0, 0)
                # Expected unpack: (ok, sel, muted, ppq, chanmsg, chan, msg2, msg3)
                if not isinstance(result, tuple) or len(result) < 8:
                    continue
                ok, _sel, _muted, ppq, chanmsg, chan, msg2, msg3 = result[:8]
                if not ok:
                    continue
                if channel is not None and int(chan) != int(channel):
                    continue
                seconds, ms = _time_from_ppq(take, ppq, project)
                base = {
                    "index": i,
                    "channel": int(chan),
                    "position": {"time": seconds, "measure": ms, "ppq": ppq},
                }
                if chanmsg == _CC:
                    if cc_number is not None and int(msg2) != int(cc_number):
                        continue
                    out.append({**base, "type": "cc", "cc_number": int(msg2), "value": int(msg3)})
                elif chanmsg == _PITCH_BEND:
                    raw14 = (int(msg3) << 7) | int(msg2)
                    out.append({**base, "type": "pitch_bend", "value": raw14 - 8192})
                elif chanmsg == _PROGRAM_CHANGE:
                    out.append({**base, "type": "program_change", "program": int(msg2)})
                elif chanmsg == _CHANNEL_PRESSURE:
                    out.append({**base, "type": "channel_pressure", "value": int(msg2)})
                else:
                    out.append({**base, "type": "unknown", "chanmsg_hex": hex(int(chanmsg))})
            return {"success": True, "count": len(out), "events": out}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_midi_sysex(track_index: int, item: int | str) -> dict:
        """Return all sysex (and text) events on a MIDI item.

        Each event has ``type``: ``"sysex"`` or one of REAPER's text-event
        flavors (lyric, marker, text, copyright, instrument, …) plus the raw
        bytes as a hex string.
        """
        from reapy import reascript_api as RPR

        _TEXT_TYPE_NAMES = {
            -1: "sysex",
            1: "text",
            2: "copyright",
            3: "lyric",
            4: "marker",
            5: "cue",
            6: "channel_prefix",
            7: "instrument",
        }
        try:
            project, _, _, take = _get_midi_take(track_index, item)
            counts = RPR.MIDI_CountEvts(take.id, 0, 0, 0)
            sysex_count = counts[3] if isinstance(counts, tuple) and len(counts) > 3 else 0
            out = []
            for i in range(sysex_count):
                result = RPR.MIDI_GetTextSysexEvt(take.id, i, False, False, 0, 0, "", 4096)
                if not isinstance(result, tuple) or len(result) < 5:
                    continue
                # Expected: (ok, sel, muted, ppq, type, msg, msg_len)
                ok = result[0]
                ppq = result[3]
                type_id = result[4] if len(result) > 4 else -1
                payload = next(
                    (s for s in result if isinstance(s, str) and s != ""),
                    "",
                )
                if not ok:
                    continue
                seconds, ms = _time_from_ppq(take, ppq, project)
                hex_data = payload.encode("latin-1").hex()
                out.append(
                    {
                        "index": i,
                        "type": _TEXT_TYPE_NAMES.get(int(type_id), f"unknown_{int(type_id)}"),
                        "position": {"time": seconds, "measure": ms, "ppq": ppq},
                        "data_hex": " ".join(
                            hex_data[j : j + 2] for j in range(0, len(hex_data), 2)
                        ),
                        "byte_count": len(payload),
                    }
                )
            return {"success": True, "count": len(out), "events": out}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_midi_cc(track_index: int, item: int | str, cc_index: int) -> dict:
        """Delete a single CC / pitch-bend / program-change / channel-pressure event by index.

        Use ``get_midi_ccs`` to discover indices. Indices shift after a delete,
        so iterate from the highest to the lowest if you delete several.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, _, take = _get_midi_take(track_index, item)
            ok = RPR.MIDI_DeleteCC(take.id, int(cc_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"MIDI_DeleteCC returned False (cc_index={cc_index} out of range?)",
                }
            return {"success": True, "deleted_index": int(cc_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_midi_ccs(
        track_index: int,
        item: int | str,
        cc_number: int | None = None,
        channel: int | None = None,
    ) -> dict:
        """Remove every CC event from a MIDI item, with optional filters.

        ``cc_number``: only delete this CC. ``channel``: only delete this channel.
        Returns the number of events removed.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            counts = RPR.MIDI_CountEvts(take.id, 0, 0, 0)
            cc_count = counts[2] if isinstance(counts, tuple) else 0
            to_delete: list[int] = []
            for i in range(cc_count):
                result = RPR.MIDI_GetCC(take.id, i, False, False, 0, 0, 0, 0, 0)
                if not isinstance(result, tuple) or len(result) < 8:
                    continue
                ok, _sel, _muted, _ppq, chanmsg, chan, msg2, _msg3 = result[:8]
                if not ok or chanmsg != _CC:
                    continue
                if cc_number is not None and int(msg2) != int(cc_number):
                    continue
                if channel is not None and int(chan) != int(channel):
                    continue
                to_delete.append(i)
            for i in reversed(to_delete):  # delete back-to-front to keep indices stable
                RPR.MIDI_DeleteCC(take.id, i)
            return {"success": True, "deleted_count": len(to_delete)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_cc_curve(
        track_index: int,
        item: int | str,
        cc_number: int,
        start_value: int,
        end_value: int,
        steps: int = 16,
        channel: int = 0,
        start_time: float | None = None,
        start_measure: str | None = None,
        end_time: float | None = None,
        end_measure: str | None = None,
        shape: str = "linear",
    ) -> dict:
        """Generate a smooth CC ramp between two values.

        Inserts ``steps`` CC events linearly (or with shape ``"exp"`` /
        ``"log"``) between start and end positions. Useful for fades, swells,
        cutoff sweeps, etc.
        """
        from reapy import reascript_api as RPR

        try:
            project, _, _, take = _get_midi_take(track_index, item)
            ppq_start, t_start, _ = _ppq_at(take, start_time, start_measure, project)
            if end_time is None and end_measure is None:
                raise ValueError("Provide end_time or end_measure")
            seconds_end, _ = resolve_start(end_time, end_measure, project)
            ppq_end = RPR.MIDI_GetPPQPosFromProjTime(take.id, seconds_end)
            steps = max(2, int(steps))
            inserted = 0
            for i in range(steps):
                t = i / (steps - 1)
                if shape == "exp":
                    t = t * t
                elif shape == "log":
                    t = t**0.5
                ppq = ppq_start + (ppq_end - ppq_start) * t
                value = round(start_value + (end_value - start_value) * t)
                value = max(0, min(127, int(value)))
                RPR.MIDI_InsertCC(
                    take.id,
                    False,
                    False,
                    ppq,
                    _CC,
                    int(channel),
                    int(cc_number),
                    value,
                )
                inserted += 1
            return {
                "success": True,
                "cc_number": int(cc_number),
                "channel": int(channel),
                "events_inserted": inserted,
                "start_value": int(start_value),
                "end_value": int(end_value),
                "shape": shape,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
