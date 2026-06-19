"""System-level tools — REAPER actions, preferences, project settings, undo blocks.

These tools expose the "control plane" of REAPER: anything you can do via
preferences, the Action List, project settings, or undo grouping. The
``run_reaper_action`` escape hatch can drive nearly every menu item even when
there is no dedicated tool for it.
"""

import logging

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.system")


def register_tools(mcp):
    @mcp.tool()
    def run_reaper_action(action_id: int | str) -> dict:
        """Run any REAPER Main-section action by ID. Universal escape hatch.

        ``action_id`` accepts either an integer command ID (e.g. ``1007`` for
        Transport: Play, ``40012`` for Item: Split items at edit cursor) or a
        named command string for SWS/extension actions (e.g. ``"_SWS_AWFADERTOOL"``).

        Discover IDs in REAPER via Actions → Show action list. Most REAPER
        operations have a stable integer ID and can be driven this way even
        without a dedicated MCP tool.
        """
        from reapy import reascript_api as RPR

        try:
            if isinstance(action_id, str):
                try:
                    numeric = int(action_id)
                except ValueError:
                    numeric = RPR.NamedCommandLookup(action_id)
                    if numeric == 0:
                        return {
                            "success": False,
                            "error": f"Named action not found: {action_id!r}",
                        }
            else:
                numeric = int(action_id)
            RPR.Main_OnCommand(numeric, 0)
            return {"success": True, "action_id": numeric}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_action_name(action_id: int) -> dict:
        """Return the display name of a Main-section REAPER action by ID.

        Useful for reverse-looking-up an action ID to confirm what it does
        before invoking it.
        """
        from reapy import reascript_api as RPR

        try:
            section = RPR.SectionFromUniqueID(0)  # 0 = Main section
            name = RPR.kbd_getTextFromCmd(int(action_id), section)
            return {"success": True, "action_id": int(action_id), "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def search_actions(
        query: str = "",
        section: int = 0,
        limit: int = 100,
    ) -> dict:
        """Enumerate REAPER's action list (including SWS / extensions) with optional filter.

        ``query`` is a case-insensitive substring matched against both the
        display name and the named command (Custom ID). Empty query returns
        the first ``limit`` actions.

        ``section`` (default 0 = Main): which action section to scan.
        Other useful sections: 32060 = MIDI Editor, 32062 = Media Explorer,
        32063 = MIDI Inline.

        The Main section can hold several thousand actions when extensions
        like SWS are loaded; the full scan iterates them in a single REAPER
        round-trip via ``reapy.inside_reaper`` so it's still fast (sub-second).

        Each returned entry has ``action_id`` (int), ``name`` (display string),
        and ``named_command`` (the ``_SWS_…``/``_BR_…``/etc. Custom ID if any,
        empty string for built-in REAPER actions).
        """
        import reapy
        from reapy import reascript_api as RPR

        try:
            section_ptr = RPR.SectionFromUniqueID(int(section))
            if not section_ptr:
                return {"success": False, "error": f"Unknown section: {section}"}

            q = (query or "").lower()
            limit_i = int(limit)
            results: list[dict] = []
            scanned = 0
            MAX_SCAN = 20000

            with reapy.inside_reaper():
                for idx in range(MAX_SCAN):
                    cmd_id = RPR.kbd_enumerateActions(section_ptr, idx, "")
                    if not cmd_id:
                        break
                    scanned = idx + 1

                    name_result = RPR.kbd_getTextFromCmd(cmd_id, section_ptr)
                    if isinstance(name_result, tuple):
                        strings = [s for s in name_result if isinstance(s, str) and s]
                        name = strings[-1] if strings else ""
                    else:
                        name = str(name_result or "")

                    # ReverseNamedCommandLookup raises if the action has no
                    # named command (REAPER's Python bridge calls .decode() on
                    # a None return). Most built-in actions are unnamed.
                    try:
                        named = RPR.ReverseNamedCommandLookup(cmd_id)
                    except Exception:
                        named = None
                    named_command = f"_{named}" if named else ""

                    if q and q not in name.lower() and q not in named_command.lower():
                        continue

                    results.append(
                        {
                            "action_id": int(cmd_id),
                            "name": name,
                            "named_command": named_command,
                        }
                    )
                    if len(results) >= limit_i:
                        break

            return {
                "success": True,
                "section": int(section),
                "query": query,
                "scanned": scanned,
                "matched": len(results),
                "truncated": len(results) >= limit_i,
                "actions": results,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def lookup_reaper_action(named_command: str) -> dict:
        """Resolve a named command (e.g. ``"_SWS_AWFADERTOOL"``) to its integer
        action ID without running it.

        Returns ``action_id`` of 0 if the command is not registered — typically
        because the extension that provides it isn't installed or REAPER hasn't
        loaded yet. Useful for verifying SWS / other extension installs:

            lookup_reaper_action("_SWS_AWFADERTOOL")
            → ``{"success": true, "action_id": 12345, "loaded": true}``

        Contrast with ``run_reaper_action`` which executes; this is read-only.
        """
        from reapy import reascript_api as RPR

        try:
            cmd_id = int(RPR.NamedCommandLookup(named_command))
            return {
                "success": True,
                "named_command": named_command,
                "action_id": cmd_id,
                "loaded": cmd_id != 0,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_reaper_pref(name: str) -> dict:
        """Read a REAPER preference (config var) by name. Returns value as string.

        Common var names: ``projsrate``, ``projsiglim``, ``reasamplerate``,
        ``autosaveint``, ``maxrecanal``, ``defrecpath``. See REAPER's
        ``reaper.ini`` for the full list of variable names.

        Some prefs only take effect after restarting REAPER.
        """
        from reapy import reascript_api as RPR

        try:
            result = RPR.get_config_var_string(name, "", 4096)
            if isinstance(result, tuple):
                # python-reapy returns the output tuple; the value buffer is one
                # of the strings, not equal to `name`.
                strings = [s for s in result if isinstance(s, str) and s != name]
                value = strings[0] if strings else ""
            else:
                value = str(result)
            return {"success": True, "name": name, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_reaper_pref(name: str, value: str) -> dict:
        """Set a REAPER preference (config var). Value is coerced as needed.

        Note: most prefs take effect immediately, but some — particularly
        audio device, plugin paths, and other startup-time settings — only
        apply after restarting REAPER.
        """
        from reapy import reascript_api as RPR

        try:
            ok = RPR.set_config_var_string(name, str(value))
            return {"success": bool(ok), "name": name, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_project_setting(key: str) -> dict:
        """Read a project-level setting via REAPER's ``GetSetProjectInfo`` API.

        Returns both ``numeric_value`` and ``string_value`` — use whichever is
        relevant for the key. Common keys:

        Numeric: ``RENDER_SRATE``, ``RENDER_CHANNELS``, ``RENDER_BOUNDSFLAG``,
        ``RENDER_FORMAT``, ``RENDER_DITHER``, ``RENDER_TAILMS``,
        ``RENDER_RESAMPLE``.

        String: ``RENDER_FILE``, ``RENDER_PATTERN``, ``RENDER_FORMAT_CUSTOM``,
        ``PROJECT_AUTHOR``, ``PROJECT_NOTES``.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            numeric = RPR.GetSetProjectInfo(project.id, key, 0.0, False)
            result = RPR.GetSetProjectInfo_String(project.id, key, "", False)
            if isinstance(result, tuple):
                strings = [s for s in result if isinstance(s, str) and s != key]
                string_val = strings[0] if strings else ""
            else:
                string_val = str(result)
            return {
                "success": True,
                "key": key,
                "numeric_value": numeric,
                "string_value": string_val,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_project_setting(
        key: str,
        numeric_value: float | None = None,
        string_value: str | None = None,
    ) -> dict:
        """Set a project-level setting. Provide whichever value type the key expects.

        Key list: see ``get_project_setting``. Numeric keys take ``numeric_value``;
        string keys take ``string_value``. Providing both writes both.
        """
        from reapy import reascript_api as RPR

        try:
            if numeric_value is None and string_value is None:
                return {
                    "success": False,
                    "error": "Provide numeric_value, string_value, or both",
                }
            project = get_project()
            if numeric_value is not None:
                RPR.GetSetProjectInfo(project.id, key, float(numeric_value), True)
            if string_value is not None:
                RPR.GetSetProjectInfo_String(project.id, key, str(string_value), True)
            return {
                "success": True,
                "key": key,
                "numeric_value": numeric_value,
                "string_value": string_value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def begin_undo_block() -> dict:
        """Start a single undo block. Pair with ``end_undo_block(description)``.

        All operations between are merged into one undo entry in REAPER's
        history — so a multi-step LLM batch (create track, add FX, set params,
        add MIDI item) becomes one Cmd-Z step for the user instead of dozens.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            RPR.Undo_BeginBlock2(project.id)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def end_undo_block(description: str = "MCP batch", flags: int = -1) -> dict:
        """End an undo block started with ``begin_undo_block``.

        ``description`` shows in REAPER's undo history list.
        ``flags`` bitmask: ``-1`` = all (default), ``1`` = track mute,
        ``2`` = track FX, ``4`` = items, ``8`` = master FX, ``16`` = freeze.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            RPR.Undo_EndBlock2(project.id, description, int(flags))
            return {"success": True, "description": description, "flags": flags}
        except Exception as e:
            return {"success": False, "error": str(e)}
