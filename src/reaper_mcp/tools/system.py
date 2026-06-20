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
    def import_keymap(
        keymap_path: str,
        kb_ini_path: str | None = None,
        force: bool = False,
    ) -> dict:
        """Append a ``.ReaperKeyMap`` file's entries to REAPER's ``reaper-kb.ini``.

        A KeyMap file is a small text bundle of ``ACT`` (custom action / macro),
        ``KEY`` (binding), and ``SCR`` (script registration) lines that REAPER
        merges into ``reaper-kb.ini`` when you use *Actions → Key bindings → Import*.
        This tool does the same merge headlessly: it parses the keymap, skips
        entries already present in ``reaper-kb.ini`` (so re-running is a no-op),
        and appends the rest.

        REAPER must be **closed** before calling. REAPER rewrites
        ``reaper-kb.ini`` on exit from its in-memory state, so any edits made
        while it's running are silently overwritten. By default this tool
        refuses when it detects a running REAPER process (via ``pgrep`` on
        macOS/Linux); pass ``force=True`` to skip the check.

        ``kb_ini_path`` defaults to the standard REAPER config location for the
        current OS (``~/Library/Application Support/REAPER/reaper-kb.ini`` on
        macOS, ``~/.config/REAPER/reaper-kb.ini`` on Linux,
        ``%APPDATA%\\REAPER\\reaper-kb.ini`` on Windows).

        Dedupe identity per entry kind:
        - ``ACT`` / ``SCR``: the GUID-like ID token (4th field).
        - ``KEY``: the full ``KEY <flags> <key> <id> <section>`` line.

        Returns counts of added vs. skipped lines per kind, plus the kb.ini
        path used. Restart REAPER after a successful import for the new
        action to appear in the Actions list.
        """
        import subprocess
        from pathlib import Path

        from platformdirs import user_config_dir

        try:
            km_path = Path(keymap_path).expanduser()
            if not km_path.is_file():
                return {"success": False, "error": f"Keymap file not found: {km_path}"}

            if kb_ini_path is None:
                kb_path = Path(user_config_dir("REAPER")) / "reaper-kb.ini"
            else:
                kb_path = Path(kb_ini_path).expanduser()
            if not kb_path.is_file():
                return {"success": False, "error": f"reaper-kb.ini not found: {kb_path}"}

            if not force:
                try:
                    proc = subprocess.run(
                        ["pgrep", "-x", "REAPER"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        return {
                            "success": False,
                            "error": (
                                "REAPER appears to be running. Quit REAPER first "
                                "(it overwrites reaper-kb.ini on exit), or pass "
                                "force=True to skip this check."
                            ),
                            "reaper_pids": proc.stdout.strip().splitlines(),
                        }
                except (FileNotFoundError, subprocess.SubprocessError):
                    pass

            existing = kb_path.read_text(encoding="utf-8", errors="replace")
            keymap_text = km_path.read_text(encoding="utf-8", errors="replace")

            def kind_of(line: str) -> str:
                head = line.split(maxsplit=1)[0] if line else ""
                return head if head in ("ACT", "KEY", "SCR") else "OTHER"

            def identity(line: str) -> str | None:
                parts = line.split()
                if not parts:
                    return None
                kind = parts[0]
                if kind in ("ACT", "SCR") and len(parts) >= 4:
                    return parts[3].strip('"')
                if kind == "KEY" and len(parts) >= 5:
                    return f"KEY {parts[1]} {parts[2]} {parts[3]} {parts[4]}"
                return line

            added = {"ACT": 0, "KEY": 0, "SCR": 0, "OTHER": 0}
            skipped = {"ACT": 0, "KEY": 0, "SCR": 0, "OTHER": 0}
            new_lines: list[str] = []

            for raw in keymap_text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                kind = kind_of(line)
                ident = identity(line)
                if ident and ident in existing:
                    skipped[kind] += 1
                    continue
                new_lines.append(line)
                added[kind] += 1

            if not new_lines:
                return {
                    "success": True,
                    "kb_ini": str(kb_path),
                    "added": added,
                    "skipped": skipped,
                    "note": "Nothing to add — all entries already present.",
                }

            sep = "" if not existing or existing.endswith("\n") else "\n"
            appended = sep + "\n".join(new_lines) + "\n"
            with kb_path.open("a", encoding="utf-8") as f:
                f.write(appended)

            return {
                "success": True,
                "kb_ini": str(kb_path),
                "added": added,
                "skipped": skipped,
                "appended_bytes": len(appended.encode("utf-8")),
                "note": "Restart REAPER for the new entries to take effect.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_toolbar_item(
        action: str,
        section: str = "Main toolbar",
        label: str | None = None,
        menu_ini_path: str | None = None,
        force: bool = False,
    ) -> dict:
        """Append an action to a REAPER toolbar by editing ``reaper-menu.ini``.

        REAPER's ReaScript API exposes no toolbar-mutation function (only
        read/refresh: ``GetCustomMenuOrToolbarItemCount``, ``RefreshToolbar``).
        The only programmatic path is to edit ``reaper-menu.ini`` directly, and
        REAPER must be **closed** when we do — REAPER overwrites the file on
        exit. Refuses by default when REAPER is running; pass ``force=True``
        to skip the check.

        ``action`` is an integer action ID (e.g. ``40012``) or a named command
        starting with ``_`` (e.g. ``_2ff47f4b97004dfcb33cfc2353ac5d33``,
        ``_SWS_AWFADERTOOL``).

        ``section`` is the INI header for the target toolbar. Common values:
        ``"Main toolbar"``, ``"Floating toolbar 1"``..``"Floating toolbar 16"``,
        ``"MIDI piano roll toolbar"``, ``"Media explorer toolbar"``.

        ``label`` is the button text. If omitted, defaults to the action token
        itself (REAPER renders it correctly either way; you can edit later via
        Customize toolbar → right-click the button → Rename).

        Defaults-preservation rule: if ``section`` does **not** already exist
        in ``reaper-menu.ini``, creating it would override REAPER's compiled-in
        defaults for that toolbar with just our one item. So we refuse unless
        the section name matches ``Floating toolbar N`` (which is empty by
        default — safe to create). To seed Main toolbar / other built-in
        toolbars: in REAPER, right-click the toolbar → Customize toolbar →
        Save as default, then quit REAPER and re-run.

        ``menu_ini_path`` defaults to the standard REAPER config location for
        the current OS (via platformdirs).
        """
        import re
        import subprocess
        from pathlib import Path

        from platformdirs import user_config_dir

        try:
            if menu_ini_path is None:
                menu_path = Path(user_config_dir("REAPER")) / "reaper-menu.ini"
            else:
                menu_path = Path(menu_ini_path).expanduser()

            if not force:
                try:
                    proc = subprocess.run(
                        ["pgrep", "-x", "REAPER"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        return {
                            "success": False,
                            "error": (
                                "REAPER appears to be running. Quit REAPER first "
                                "(it overwrites reaper-menu.ini on exit), or pass "
                                "force=True to skip this check."
                            ),
                            "reaper_pids": proc.stdout.strip().splitlines(),
                        }
                except (FileNotFoundError, subprocess.SubprocessError):
                    pass

            try:
                int(action)
                action_token = str(int(action))
            except ValueError:
                if not action.startswith("_"):
                    return {
                        "success": False,
                        "error": (
                            f"Action must be a numeric ID or a named command starting "
                            f"with '_' (got {action!r})."
                        ),
                    }
                action_token = action

            display = label if label is not None else action_token

            text = menu_path.read_text(encoding="utf-8") if menu_path.is_file() else ""
            lines = text.splitlines()

            sections: dict[str, list[int]] = {}
            current: str | None = None
            current_indices: list[int] = []
            for i, ln in enumerate(lines):
                s = ln.strip()
                if s.startswith("[") and s.endswith("]"):
                    if current is not None:
                        sections[current] = current_indices
                    current = s[1:-1]
                    current_indices = [i]
                elif current is not None:
                    current_indices.append(i)
            if current is not None:
                sections[current] = current_indices

            section_exists = section in sections
            safe_to_create = bool(re.fullmatch(r"Floating toolbar (1[0-6]|[1-9])", section))

            if not section_exists and not safe_to_create:
                return {
                    "success": False,
                    "error": (
                        f"Section [{section}] does not exist in {menu_path}. "
                        f"Creating it would override REAPER's compiled-in defaults "
                        f"for that toolbar with just this one item. Seed it first: "
                        f"in REAPER, right-click the toolbar → Customize toolbar → "
                        f"Save as default, then quit REAPER and re-run."
                    ),
                    "menu_ini": str(menu_path),
                }

            item_re = re.compile(r"^item_(\d+)\s*=")
            if section_exists:
                section_line_indices = sections[section]
                max_idx = -1
                last_item_line = section_line_indices[0]
                for li in section_line_indices[1:]:
                    m = item_re.match(lines[li].strip())
                    if m:
                        n = int(m.group(1))
                        if n > max_idx:
                            max_idx = n
                        last_item_line = li
                new_n = max_idx + 1
                new_line = f"item_{new_n}={action_token} {display}".rstrip()
                insert_at = last_item_line + 1
                lines.insert(insert_at, new_line)
                new_lines = lines
            else:
                new_n = 0
                new_line = f"item_{new_n}={action_token} {display}".rstrip()
                new_lines = list(lines)
                if new_lines and new_lines[-1].strip():
                    new_lines.append("")
                new_lines.append(f"[{section}]")
                new_lines.append(new_line)

            out = "\n".join(new_lines)
            if not out.endswith("\n"):
                out += "\n"
            menu_path.write_text(out, encoding="utf-8")

            return {
                "success": True,
                "menu_ini": str(menu_path),
                "section": section,
                "item_index": new_n,
                "line": new_line,
                "section_created": not section_exists,
                "note": "Restart REAPER for the toolbar change to take effect.",
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
