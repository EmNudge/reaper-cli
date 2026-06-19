# NOTICE

This project is a merge of three independent open-source REAPER MCP projects,
all released under the MIT License. The merged code lives in `src/reaper_mcp/`;
the original copyright notices and full license texts are preserved in
`LICENSES/`.

---

## dschuler36/reaper-mcp-server

- Upstream: https://github.com/dschuler36/reaper-mcp-server
- Copyright (c) 2025 David Schuler
- License: MIT — see `LICENSES/LICENSE.dschuler36-reaper-mcp-server`
- Contribution: the offline `.RPP` parser, plugin-cache enumerator, and
  audio-analysis pipeline (LUFS, peak/RMS, frequency bands, stereo width,
  dynamics, warnings). Vendored into `src/reaper_mcp/offline_support/`.

---

## bonfire-audio/reaper-mcp

- Upstream: https://github.com/bonfire-audio/reaper-mcp
- Copyright (c) 2025 Youssef Hemimy
- License: MIT — see `LICENSES/LICENSE.bonfire-audio-reaper-mcp`
- Contribution: live `python-reapy` DAW control patterns, render/analysis
  loop via temp-WAV, mastering chain helpers, lazy connection model,
  modular `register_tools(mcp)` server layout.

---

## wegitor/reaper-reapy-mcp

- Upstream: https://github.com/wegitor/reaper-reapy-mcp
- Copyright (c) 2025 wegitor
- License: MIT — see `LICENSES/LICENSE.wegitor-reaper-reapy-mcp`
- Contribution: `bar:beat,fraction` position format (in `utils/positions.py`),
  dual integer/pointer-string item identification (in `utils/items.py`),
  region/marker tools, time-signature positional control, MIDI item dual-id
  return shape.

---

The MIT License requires that the above copyright notices and the full license
text be included in all copies or substantial portions of the Software. Both
are retained in `LICENSES/` and referenced from this file.
