# Feature gaps

A snapshot of REAPER functionality vs. the unified MCP / CLI surface, as of
2026-06-20. Generated from a multi-agent audit and iteratively closed across
multiple passes. The bulk of identified gaps are now addressed; this file
remains as a record of what shipped and the few items deliberately deferred.

## All known gaps — current status

### High impact — **all addressed**

- **Razor edits** — Done as `tools/razor_edits.py`. `add_razor_area`,
  `list_razor_areas`, `clear_razor_areas`, `list_all_razor_areas`, plus an
  `about_razor_edits` orientation primer covering the action IDs.
- **Tempo map (multi-marker + curves)** — Done as `tools/tempo_map.py`.
  `add_tempo_marker`, `modify_tempo_marker`, `delete_tempo_marker`,
  `list_tempo_markers`, `get_tempo_marker`, `get_tempo_at` (with
  linear-vs-square curve flag).
- **Stretch markers + take markers** — Done in `takes.py`. Take markers:
  `add_take_marker`, `list_take_markers`, `delete_take_marker`. Stretch
  markers: `add_stretch_marker`, `list_stretch_markers`,
  `set_stretch_marker_slope`, `delete_stretch_marker`.
- **Track grouping / VCA** — Done as `tools/track_groups.py`. 23 group flags
  × 64 groups via `set_track_group_membership`, `get_track_group_membership`,
  `get_track_groups`, `list_group_members`, `about_track_groups`.
- **Fixed item lanes (FIPM)** — Done as `tools/lanes.py`.
  `set_track_lane_mode` (off / free / fixed lanes), `get_track_lane_mode`,
  `set_item_lane_position`, `get_item_lane_position`.

### Medium impact — **all addressed**

- **Item fades & crossfades** — Done in `items.py`. `set_item_fade` covers
  in/out lengths + 0–6 shape curves + curve direction. `set_item_auto_fade`
  covers `D_FADEINLEN_AUTO` / `D_FADEOUTLEN_AUTO` auto-crossfade lengths.
- **Take playback parameters** — Done in `takes.py`. `set_take_preserve_pitch`,
  `set_take_channel_mode`, `set_take_start_offset`, `set_take_pitch_mode`,
  `get_take_playback_params`.
- **Region render matrix & render queue** — Done in `render.py`.
  `set_region_render_matrix`, `get_region_render_matrix`,
  `clear_region_render_matrix`, `queue_render`, `process_render_queue`,
  `render_regions_via_matrix`.
- **Automation items + non-FX-param envelopes** — Done in `envelopes.py`.
  `show_track_envelope`, `get_take_envelopes`, `add_take_envelope_point`,
  `insert_automation_item`, `list_automation_items`.
- **Track view & layout** — Done in `tracks.py`. `set_track_height` (with
  lock), `set_track_visible` (TCP + Mixer), `set_track_icon`,
  `set_track_automation_mode`, `get_track_automation_mode`,
  `set_track_mixer_order`, `move_track`.
- **MIDI input device / channel mapping** — Done in `tracks.py`.
  `set_track_midi_input(device_index, channel, all_channels)` covers the
  full `I_RECINPUT` encoding.
- **Recording mode** — Done in `tracks.py`. `set_recording_mode` exposes all
  13 modes (input, stereo_out, none, MIDI overdub/replace/touch/latch,
  multichannel, …).

### Lower impact — **mostly addressed**

- **Snap toggle + grid division** — Done. `set_snap_enabled` in `system.py`
  for the toggle; `get_grid_division` / `set_grid_division` in `project.py`
  for the value (covering `swing_mode` / `swing_amount` as well).
- **Metronome** — Toggle done (`get_metronome_enabled` /
  `set_metronome_enabled` in `system.py`). Volume / synth / pattern config
  is intentionally not wrapped — it lives in REAPER config vars and isn't a
  commonly-automated surface; reach for `system.set_reaper_pref` if needed.
- **Ripple-edit mode** — Done. `get_ripple_edit_mode` / `set_ripple_edit_mode`
  in `system.py` (modes ``"off"``, ``"per_track"``, ``"all_tracks"``).
- **Track + item selection helpers** — Done. Tracks: `select_track`,
  `deselect_track`, `get_selected_tracks`. Items: `select_item`,
  `deselect_item`, `clear_item_selection`, `select_all_items`,
  `select_items_in_range`.
- **FX management depth** — Done in `fx.py`. `move_fx` (in-track reorder),
  `copy_fx_to_track` (with `move=True` for cross-track moves), `bypass_all_fx`.

## Deliberately deferred

These have known reasons not to ship as-is. They are NOT bugs to fix later
without thinking — each has a real reason:

### Save-FX-preset
REAPER's ReaScript API has no `TrackFX_SavePreset` function. The "save
current FX state as a preset" workflow is GUI-only. Options:
- Write `.rpl` / `.vstpreset` files directly (per-host format complexity)
- Use SWS extension actions if the host has SWS installed
- Drive the GUI via key automation (out of scope for a headless API)

`load_fx_preset` works fine because `TrackFX_SetPreset` exists.

### ReaPack write-side
The `reapack` module is read-only (state inspection + sync). Programmatic
`install_package` / `update_package` would require driving ReaPack's
internal command set, which is mostly GUI dialog plumbing. The
`about_reapack` tool already documents the GUI fallback. Genuine research
needed before wrapping.

### Audio device / driver settings
REAPER exposes audio device prefs via the GUI (action 40016) and a small
set of config vars, but not via a structured API. The few useful knobs
(buffer size, sample rate) are read/writable via `system.get_reaper_pref` /
`set_reaper_pref` if you know the right keys.

## Reference shapes

These existing modules are the right pattern to copy when adding new ones:

- **Symmetric CRUD**: `render_presets.py` (`list / get / save / apply / delete`)
- **Dual time/measure positions**: every position-taking tool in the codebase
- **Dual hex/RGB color**: `items.py:set_item_color`,
  `markers.py:set_marker_color` / `set_region_color`
- **Group orientation primer**: `reapack.py:about_reapack`,
  `track_groups.py:about_track_groups`, `razor_edits.py:about_razor_edits`,
  `render.py:about_render` — call when a module needs cross-cutting context
  the per-tool descriptions can't fit.
