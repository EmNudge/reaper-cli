"""MIDI tools — item creation (dual time/measure positions), single + batch notes,
clear, query, find-by-pitch, chord progressions, drum patterns."""

import contextlib
import logging
from typing import Any

from reaper_mcp.connection import get_project
from reaper_mcp.utils.items import get_item_by_id_or_index, select_item
from reaper_mcp.utils.positions import (
    measure_length_to_time,
    position_to_time,
    resolve_length,
    resolve_start,
    time_to_measure,
)

logger = logging.getLogger("reaper_mcp.tools.midi")

DRUM_MAPPINGS = {
    "k": 36,  # kick   - C1
    "s": 38,  # snare  - D1
    "h": 42,  # closed hihat - F#1
    "o": 46,  # open hihat   - A#1
    "t": 41,  # tom low  - F1
    "m": 45,  # tom mid  - A1
    "f": 48,  # tom high - C2
    "c": 49,  # crash    - C#2
    "r": 51,  # ride     - D#2
}

CHORD_TYPES = {
    "maj": [0, 4, 7],
    "min": [0, 3, 7],
    "m": [0, 3, 7],
    "dim": [0, 3, 6],
    "aug": [0, 4, 8],
    "maj7": [0, 4, 7, 11],
    "min7": [0, 3, 7, 10],
    "m7": [0, 3, 7, 10],
    "7": [0, 4, 7, 10],
    "dom7": [0, 4, 7, 10],
    "dim7": [0, 3, 6, 9],
    "hdim7": [0, 3, 6, 10],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
}

NOTE_TO_NUMBER = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def _parse_chord(chord_str: str) -> tuple[list[int], int]:
    s = chord_str.strip()
    if len(s) >= 2 and s[1] in ("#", "b"):
        root, ctype = s[:2], s[2:] or "maj"
    else:
        root, ctype = s[:1], s[1:] or "maj"
    return CHORD_TYPES.get(ctype, CHORD_TYPES["maj"]), NOTE_TO_NUMBER.get(root, 0)


def register_tools(mcp):
    @mcp.tool()
    def create_midi_item(
        track_index: int,
        start_time: float | None = None,
        start_measure: str | None = None,
        length_time: float | None = None,
        length_measure: str | None = None,
    ) -> dict:
        """Create an empty MIDI item.

        Provide either ``start_time`` (seconds) OR ``start_measure`` (``M:B,F``), and
        either ``length_time`` (seconds) OR ``length_measure``. Returns both
        ``track_pos_idx`` and ``direct_item_id`` for the new item; use either with
        ``add_midi_note``.
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            start_s, start_ms = resolve_start(start_time, start_measure, project)
            length_s, end_ms = resolve_length(length_time, length_measure, start_s, project)
            item = track.add_midi_item(start_s, start_s + length_s)
            if item is None:
                return {"success": False, "error": "Failed to create MIDI item"}
            idx = -1
            for i, ti in enumerate(track.items):
                if ti.id == item.id:
                    idx = i
                    break
            return {
                "success": True,
                "track_pos_idx": idx,
                "direct_item_id": str(item.id),
                "track_index": track_index,
                "position": {"time": start_s, "measure": start_ms},
                "end": {"time": start_s + length_s, "measure": end_ms},
            }
        except Exception as e:
            logger.error(f"create_midi_item failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_note(
        track_index: int,
        item: int | str,
        pitch: int,
        start_time: float | None = None,
        start_measure: str | None = None,
        length_time: float | None = None,
        length_measure: str | None = None,
        velocity: int = 96,
        channel: int = 0,
        relative_start: bool = False,
    ) -> dict:
        """Add a MIDI note to an existing MIDI item.

        ``item`` may be the integer ``track_pos_idx`` OR the string ``direct_item_id``.
        Positions are project-absolute by default. Set ``relative_start=True`` to treat
        them as offsets from the item's start. Notes positioned before the item's start
        are rejected (in absolute mode).
        ``channel``: 0-15. Use 9 for GM drums.
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "MIDI item not found"}
            take = it.active_take
            if take is None or not take.is_midi:
                return {"success": False, "error": "Item is not a MIDI item"}

            item_start = it.position
            if start_time is not None:
                t = item_start + float(start_time) if relative_start else float(start_time)
                start_ms = time_to_measure(t, project)
            elif start_measure is not None:
                if relative_start:
                    offset = measure_length_to_time(start_measure, item_start, project)
                    t = item_start + offset
                else:
                    t = position_to_time(start_measure, project)
                start_ms = time_to_measure(t, project)
            else:
                return {"success": False, "error": "Provide start_time or start_measure"}

            if not relative_start and t < item_start:
                return {
                    "success": False,
                    "error": "Note start is before the item's start; it would not sound",
                }

            length_s, end_ms = resolve_length(length_time, length_measure, t, project)
            rel_start = t - item_start
            with contextlib.suppress(Exception):
                project.select_all_items(False)
            with contextlib.suppress(Exception):
                select_item(it)
            take.add_note(
                start=rel_start,
                end=rel_start + length_s,
                pitch=int(pitch),
                velocity=int(velocity),
                channel=int(channel),
            )
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "pitch": int(pitch),
                "velocity": int(velocity),
                "channel": int(channel),
                "start": {"time": t, "measure": start_ms},
                "end": {"time": t + length_s, "measure": end_ms},
                "relative_start_mode": relative_start,
            }
        except Exception as e:
            logger.error(f"add_midi_note failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_midi_notes(
        track_index: int,
        item: int | str,
        notes: list[dict[str, Any]],
        relative_start: bool = False,
    ) -> dict:
        """Add multiple MIDI notes in one call.

        Each ``notes`` entry: ``pitch`` (int), one of ``start_time`` / ``start_measure``,
        one of ``length_time`` / ``length_measure``, optional ``velocity`` (default 96),
        optional ``channel`` (default 0), optional per-note ``relative_start`` override.
        """
        try:
            results: list[dict] = []
            errors: list[dict] = []
            for i, note in enumerate(notes):
                try:
                    r = add_midi_note(
                        track_index=track_index,
                        item=item,
                        pitch=int(note["pitch"]),
                        start_time=note.get("start_time"),
                        start_measure=note.get("start_measure"),
                        length_time=note.get("length_time"),
                        length_measure=note.get("length_measure"),
                        velocity=int(note.get("velocity", 96)),
                        channel=int(note.get("channel", 0)),
                        relative_start=bool(note.get("relative_start", relative_start)),
                    )
                    if r.get("success"):
                        results.append({"index": i, "note": note, "details": r})
                    else:
                        errors.append({"index": i, "note": note, "error": r.get("error")})
                except Exception as e:
                    errors.append({"index": i, "note": note, "error": str(e)})
            return {
                "success": not errors,
                "partial": bool(results) and bool(errors),
                "added": len(results),
                "failed": len(errors),
                "successful_notes": results,
                "failed_notes": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_midi_note(track_index: int, item: int | str, note_index: int) -> dict:
        """Delete a single MIDI note by its index within the take.

        Note indices come from ``get_midi_notes`` (each note's position in the
        returned list). Indices shift after a delete, so iterate from highest
        to lowest if removing several.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "MIDI item not found"}
            take = it.active_take
            if take is None or not take.is_midi:
                return {"success": False, "error": "Item is not a MIDI item"}
            ok = RPR.MIDI_DeleteNote(take.id, int(note_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"MIDI_DeleteNote returned False (note_index={note_index} out of range?)",
                }
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "deleted_note_index": int(note_index),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_midi_note(
        track_index: int,
        item: int | str,
        note_index: int,
        pitch: int | None = None,
        velocity: int | None = None,
        channel: int | None = None,
        muted: bool | None = None,
        start_time: float | None = None,
        start_measure: str | None = None,
        length_time: float | None = None,
        length_measure: str | None = None,
        relative_start: bool = False,
    ) -> dict:
        """Edit an existing MIDI note in place.

        Pass only the fields you want to change; everything else is preserved.
        Position rules match ``add_midi_note`` — ``relative_start=True`` treats
        ``start_time`` / ``start_measure`` as offsets from the item's start.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "MIDI item not found"}
            take = it.active_take
            if take is None or not take.is_midi:
                return {"success": False, "error": "Item is not a MIDI item"}
            idx = int(note_index)
            cur = RPR.MIDI_GetNote(take.id, idx, False, False, 0.0, 0.0, 0, 0, 0)
            if not isinstance(cur, tuple) or len(cur) < 8:
                return {"success": False, "error": "MIDI_GetNote returned unexpected shape"}
            ok, sel, cur_muted, start_ppq, end_ppq, cur_chan, cur_pitch, cur_vel = cur[:8]
            if not ok:
                return {"success": False, "error": f"Note {idx} not found"}

            new_pitch = int(pitch) if pitch is not None else int(cur_pitch)
            new_vel = int(velocity) if velocity is not None else int(cur_vel)
            new_chan = int(channel) if channel is not None else int(cur_chan)
            new_muted = bool(muted) if muted is not None else bool(cur_muted)
            new_start_ppq = start_ppq
            new_end_ppq = end_ppq

            if start_time is not None or start_measure is not None:
                item_start = it.position
                if start_time is not None:
                    t = item_start + float(start_time) if relative_start else float(start_time)
                elif relative_start:
                    offset = measure_length_to_time(str(start_measure), item_start, project)
                    t = item_start + offset
                else:
                    t = position_to_time(str(start_measure), project)
                new_start_ppq = RPR.MIDI_GetPPQPosFromProjTime(take.id, t)

            if length_time is not None or length_measure is not None:
                start_seconds = RPR.MIDI_GetProjTimeFromPPQPos(take.id, new_start_ppq)
                length_s, _ = resolve_length(length_time, length_measure, start_seconds, project)
                end_seconds = start_seconds + length_s
                new_end_ppq = RPR.MIDI_GetPPQPosFromProjTime(take.id, end_seconds)

            ok2 = RPR.MIDI_SetNote(
                take.id,
                idx,
                bool(sel),
                new_muted,
                new_start_ppq,
                new_end_ppq,
                new_chan,
                new_pitch,
                new_vel,
                False,
            )
            if not ok2:
                return {"success": False, "error": "MIDI_SetNote returned False"}
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "note_index": idx,
                "pitch": new_pitch,
                "velocity": new_vel,
                "channel": new_chan,
                "muted": new_muted,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_midi_item(track_index: int, item: int | str) -> dict:
        """Replace a MIDI item with an empty one at the same position/length."""
        from reaper_mcp.utils.items import delete_item

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "MIDI item not found"}
            position, length = it.position, it.length
            new_item = track.add_midi_item(position, position + length)
            if new_item is None:
                return {"success": False, "error": "Failed to create empty replacement item"}
            if not delete_item(it):
                return {"success": False, "error": "Failed to delete the original item"}
            return {
                "success": True,
                "track_index": track_index,
                "new_item_id": str(new_item.id),
                "position": position,
                "length": length,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_midi_notes(track_index: int, item: int | str, include_invisible: bool = False) -> dict:
        """Return all notes in a MIDI item. By default skips notes outside item bounds."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "MIDI item not found"}
            take = it.active_take
            if take is None or not take.is_midi:
                return {"success": False, "error": "Item is not a MIDI item"}
            notes = []
            item_start, item_length = it.position, it.length
            for n in take.notes:
                rs = n.start - item_start
                re = n.end - item_start
                visible = (0 <= rs < item_length) and (0 < re <= item_length)
                if not visible and not include_invisible:
                    continue
                rec = {
                    "pitch": n.pitch,
                    "start_time": rs,
                    "end_time": re,
                    "velocity": n.velocity,
                    "channel": n.channel,
                }
                if include_invisible:
                    rec["is_visible"] = visible
                notes.append(rec)
            return {"success": True, "count": len(notes), "notes": notes}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def find_midi_notes_by_pitch(pitch_min: int = 0, pitch_max: int = 127) -> dict:
        """Find all MIDI notes within ``pitch_min..pitch_max`` (inclusive) across every track."""
        try:
            project = get_project()
            matches = []
            for ti, track in enumerate(project.tracks):
                for ii, item in enumerate(track.items):
                    take = item.active_take
                    if take is None or not take.is_midi:
                        continue
                    item_start = item.position
                    for n in take.notes:
                        if pitch_min <= n.pitch <= pitch_max:
                            matches.append(
                                {
                                    "track_index": ti,
                                    "item_index": ii,
                                    "pitch": n.pitch,
                                    "start_time": n.start - item_start,
                                    "end_time": n.end - item_start,
                                    "velocity": n.velocity,
                                    "channel": n.channel,
                                }
                            )
            return {"success": True, "count": len(matches), "notes": matches}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_selected_midi_item() -> dict:
        """Return the first selected MIDI item in the project (or none)."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            for ti, track in enumerate(project.tracks):
                for ii, item in enumerate(track.items):
                    if (
                        RPR.IsMediaItemSelected(item.id)
                        and item.active_take
                        and item.active_take.is_midi
                    ):
                        return {
                            "success": True,
                            "track_index": ti,
                            "item_index": ii,
                            "direct_item_id": str(item.id),
                            "position": item.position,
                            "length": item.length,
                        }
            return {"success": False, "error": "No selected MIDI item found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_chord_progression(
        track_index: int,
        chords: str,
        start_time: float | None = None,
        start_measure: str | None = None,
        beats_per_chord: int = 4,
    ) -> dict:
        """Place a chord progression on a track as one MIDI item.

        ``chords``: comma-separated names (e.g. ``"C,G,Am,F"`` or ``"Cm7,Fm7,Bb7,Ebmaj7"``).
        Supported qualities: maj, min/m, dim, aug, maj7, min7/m7, dom7/7, dim7, hdim7, sus2, sus4.
        Chords are voiced around middle C (MIDI 60).
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            start_s, _ = resolve_start(start_time, start_measure, project)
            chord_list = [c.strip() for c in chords.split(",") if c.strip()]
            seconds_per_beat = 60.0 / project.bpm
            chord_length = seconds_per_beat * beats_per_chord
            total_length = chord_length * len(chord_list)
            item = track.add_midi_item(start_s, start_s + total_length)
            take = item.active_take
            placed = []
            for i, chord_str in enumerate(chord_list):
                try:
                    intervals, root = _parse_chord(chord_str)
                    cs = i * chord_length
                    for iv in intervals:
                        take.add_note(
                            start=cs,
                            end=cs + chord_length * 0.95,
                            pitch=60 + root + iv,
                            velocity=80,
                            channel=0,
                        )
                    placed.append({"chord": chord_str, "position": cs, "length": chord_length})
                except Exception as e:
                    logger.warning(f"Skipping chord {chord_str!r}: {e}")
            return {
                "success": True,
                "direct_item_id": str(item.id),
                "chords": placed,
                "start_time": start_s,
                "total_length": total_length,
            }
        except Exception as e:
            logger.error(f"create_chord_progression failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_drum_pattern(
        track_index: int,
        pattern: str,
        start_time: float | None = None,
        start_measure: str | None = None,
        beats: int = 4,
        repeats: int = 1,
    ) -> dict:
        """Create a step-sequencer drum pattern on a MIDI item.

        Characters: ``k`` kick, ``s`` snare, ``h`` closed hihat, ``o`` open hihat,
        ``t`` tom low, ``m`` tom mid, ``f`` tom high, ``c`` crash, ``r`` ride, ``.`` rest.
        Example 16-step rock beat: ``"k...h...s...h..."``. Notes use channel 9 (GM standard).
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            start_s, _ = resolve_start(start_time, start_measure, project)
            seconds_per_beat = 60.0 / project.bpm
            pattern_length = seconds_per_beat * beats
            total_length = pattern_length * repeats
            item = track.add_midi_item(start_s, start_s + total_length)
            take = item.active_take
            time_per_step = pattern_length / len(pattern)
            for r in range(repeats):
                offset = r * pattern_length
                for i, ch in enumerate(pattern):
                    if ch in DRUM_MAPPINGS:
                        ns = offset + i * time_per_step
                        take.add_note(
                            start=ns,
                            end=ns + time_per_step * 0.5,
                            pitch=DRUM_MAPPINGS[ch],
                            velocity=100,
                            channel=9,
                        )
            return {
                "success": True,
                "direct_item_id": str(item.id),
                "pattern": pattern,
                "repeats": repeats,
                "start_time": start_s,
                "total_length": total_length,
            }
        except Exception as e:
            logger.error(f"create_drum_pattern failed: {e}")
            return {"success": False, "error": str(e)}
