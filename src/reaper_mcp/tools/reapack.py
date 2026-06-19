"""ReaPack tools — package-manager state inspection + workflow shortcuts.

ReaPack is REAPER's de-facto third-party package manager. It maintains a list of
*repositories* (each one a remote ``index.xml`` URL describing available scripts,
themes, JSFX, extensions, etc.), and tracks *installed packages* + the files
they put on disk.

This module wraps the on-disk state (SQLite registry + INI config) so an LLM
can read ReaPack's state without screen-scraping the GUI, plus provides
shortcuts for the few actions that don't carry parameters (sync, browse).

See ``about_reapack()`` for an orientation blob targeting LLM use of these
tools — it covers concepts, file layout, common workflows, and the gaps where
ReaPack must be driven through the GUI instead of programmatically.
"""

import configparser
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger("reaper_mcp.tools.reapack")


def _resource_path() -> Path:
    mac = Path.home() / "Library" / "Application Support" / "REAPER"
    linux = Path.home() / ".config" / "REAPER"
    windows = Path(os.environ.get("APPDATA", "")) / "REAPER"
    for p in (mac, linux, windows):
        if p.exists():
            return p
    return mac


def _reapack_dir() -> Path:
    return _resource_path() / "ReaPack"


def _reapack_ini() -> Path:
    return _resource_path() / "reapack.ini"


def _registry_db() -> Path:
    return _reapack_dir() / "registry.db"


# ReaPack package-type integer codes from registry.db. Source: ReaPack's
# Package::Type enum in src/package.hpp.
_PACKAGE_TYPES = {
    1: "script",
    2: "extension",
    3: "effect",
    4: "data",
    5: "theme",
    6: "langpack",
    7: "webinterface",
    8: "projecttpl",
    9: "tracktpl",
    10: "midinotenames",
    11: "autoitem",
}


def _parse_remotes(ini_path: Path) -> list[dict]:
    """Parse the ``[remotes]`` section of reapack.ini into structured entries.

    Each remote line looks like:
        remoteN=Name|URL|enabled|state
    where ``enabled`` is 0/1 and ``state`` is ReaPack's internal sync marker.
    """
    if not ini_path.exists():
        return []
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # preserve key case
    cp.read(ini_path)
    if "remotes" not in cp:
        return []
    remotes: list[dict] = []
    for key, value in cp.items("remotes"):
        if not key.startswith("remote"):
            continue
        parts = value.split("|")
        if len(parts) < 2:
            continue
        remotes.append(
            {
                "key": key,
                "name": parts[0],
                "url": parts[1],
                "enabled": parts[2] == "1" if len(parts) > 2 else True,
                "state": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
            }
        )
    return remotes


def register_tools(mcp):
    @mcp.tool()
    def about_reapack() -> dict:
        """Orientation primer for ReaPack — concepts, file layout, workflows, limitations.

        This is the LLM-targeted overview to call first when working with the
        ``reapack`` tool group. It returns the kind of background information
        that doesn't fit naturally in any single tool's ``--help`` but that
        callers need in order to choose the right tool and understand the
        boundaries of what ReaPack can be driven to do programmatically.
        """
        return {
            "success": True,
            "what_is_reapack": (
                "Third-party REAPER package manager. Tracks remote repositories "
                "(each one an index.xml URL describing available scripts/themes/"
                "JSFX/extensions/etc.) and maintains the list of installed packages "
                "+ their files. Conceptually similar to brew/apt for REAPER content."
            ),
            "key_concepts": {
                "repository": (
                    "A remote URL hosting an index.xml. Each repository advertises "
                    "many packages organized into categories. Examples: ReaTeam "
                    "Scripts (github.com/ReaTeam/ReaScripts), ReaPack default repo."
                ),
                "package": (
                    "A single installable unit (script, theme, JSFX, extension, "
                    "track template, language pack, etc.). Identified by "
                    "(remote, category, package_name)."
                ),
                "file": (
                    "A concrete file installed on disk for a package. One package "
                    "may install many files. Tracked in registry.db so ReaPack "
                    "knows what to remove on uninstall."
                ),
                "sync": (
                    "Refresh cached index.xml files from all enabled repositories. "
                    "Required before searching for new packages or installing "
                    "updates. Run via the sync_repositories tool."
                ),
            },
            "file_layout": {
                "registry_db": str(_registry_db()),
                "config_ini": str(_reapack_ini()),
                "cache_dir": str(_reapack_dir() / "cache"),
                "notes": (
                    "registry.db is SQLite with `entries` (installed packages) "
                    "and `files` (concrete file paths). reapack.ini holds the "
                    "[remotes] section (configured repositories) plus user "
                    "preferences. cache/ holds downloaded index.xml files per "
                    "repository — empty until first sync."
                ),
            },
            "what_this_tool_group_can_do": [
                "Read what packages are currently installed (list_installed_packages)",
                "Read what files each installed package put on disk (list_installed_files)",
                "Read configured repositories (list_repositories)",
                "Trigger a repository sync (sync_repositories)",
                "Open the package browser GUI (open_package_browser)",
            ],
            "what_this_tool_group_cannot_do": [
                "Install a specific package by name. ReaPack exposes no action "
                "for programmatic install — the user picks packages in the "
                "browser GUI (open_package_browser). After install, the "
                "registry.db reflects what changed.",
                "Search the catalogue of available (not-yet-installed) packages. "
                "That would mean parsing the cached index.xml files; not "
                "wrapped today. Sync first, then browse via the GUI.",
                "Programmatically add or remove a repository. Use ReaPack's "
                "GUI (_REAPACK_IMPORT or _REAPACK_MANAGE actions) or edit "
                "reapack.ini directly while REAPER is quit.",
            ],
            "common_workflows": [
                {
                    "intent": "Update installed packages to latest versions",
                    "steps": ["sync_repositories", "open_package_browser → click Update"],
                },
                {
                    "intent": "See what scripts the user already has from ReaTeam",
                    "steps": ["list_installed_packages(repo='ReaTeam Scripts')"],
                },
                {
                    "intent": "Find every file a specific package installed",
                    "steps": ["list_installed_packages → pick one → list_installed_files(package=...)"],
                },
                {
                    "intent": "Install something new",
                    "steps": [
                        "sync_repositories",
                        "open_package_browser  (user picks + installs in GUI)",
                        "list_installed_packages  (verify it appeared)",
                    ],
                },
            ],
            "related_actions_in_system_group": {
                "_REAPACK_BROWSE": "Open the package browser",
                "_REAPACK_SYNC": "Sync all repositories",
                "_REAPACK_MANAGE": "Open the repository manager",
                "_REAPACK_IMPORT": "Open the 'import repository' dialog",
                "note": (
                    "These can be invoked directly via "
                    "system run-reaper-action <named_command>; this group "
                    "provides higher-level wrappers + state inspection."
                ),
            },
        }

    @mcp.tool()
    def list_repositories() -> dict:
        """List ReaPack's configured repositories from reapack.ini.

        Returns each repository's name, index.xml URL, and enabled state.
        Note: this reads the on-disk config — newly added repos in the GUI
        only become visible here after the user clicks Apply / OK.
        """
        try:
            remotes = _parse_remotes(_reapack_ini())
            return {
                "success": True,
                "config_path": str(_reapack_ini()),
                "count": len(remotes),
                "repositories": remotes,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_installed_packages(
        repo: Optional[str] = None,
        category_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        package_type: Optional[str] = None,
    ) -> dict:
        """List packages currently installed via ReaPack.

        Reads ``registry.db::entries``. All filters are case-insensitive
        substrings. ``package_type`` can be ``script``, ``extension``,
        ``effect``, ``data``, ``theme``, ``langpack``, ``webinterface``,
        ``projecttpl``, ``tracktpl``, ``midinotenames``, or ``autoitem``.

        Each entry includes the version installed, author, and which
        repository it came from.
        """
        db_path = _registry_db()
        if not db_path.exists():
            return {
                "success": True,
                "count": 0,
                "packages": [],
                "note": "registry.db does not exist yet — no ReaPack packages installed",
            }
        try:
            type_int = None
            if package_type:
                rev = {v: k for k, v in _PACKAGE_TYPES.items()}
                if package_type.lower() not in rev:
                    return {
                        "success": False,
                        "error": (
                            f"Unknown package_type {package_type!r}. "
                            f"Valid: {sorted(rev)}"
                        ),
                    }
                type_int = rev[package_type.lower()]

            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id, remote, category, package, desc, type, version, author "
                "FROM entries ORDER BY remote, category, package"
            ).fetchall()
            db.close()

            packages = []
            r_q = (repo or "").lower()
            c_q = (category_filter or "").lower()
            n_q = (name_filter or "").lower()
            for row in rows:
                if r_q and r_q not in row["remote"].lower():
                    continue
                if c_q and c_q not in row["category"].lower():
                    continue
                if n_q and n_q not in row["package"].lower():
                    continue
                if type_int is not None and row["type"] != type_int:
                    continue
                packages.append(
                    {
                        "id": row["id"],
                        "remote": row["remote"],
                        "category": row["category"],
                        "package": row["package"],
                        "description": row["desc"],
                        "type": _PACKAGE_TYPES.get(row["type"], f"unknown_{row['type']}"),
                        "version": row["version"],
                        "author": row["author"],
                    }
                )
            return {
                "success": True,
                "registry_path": str(db_path),
                "count": len(packages),
                "packages": packages,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_installed_files(
        package_id: Optional[int] = None,
        package_name: Optional[str] = None,
    ) -> dict:
        """List files installed by a specific package.

        Provide either ``package_id`` (from ``list_installed_packages``) or
        ``package_name`` (substring match — first match wins if multiple).
        Returns each installed file's absolute path, whether it's the
        package's main entry point, and its REAPER asset type.
        """
        db_path = _registry_db()
        if not db_path.exists():
            return {"success": False, "error": "registry.db does not exist"}
        try:
            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row

            if package_id is None and not package_name:
                return {
                    "success": False,
                    "error": "Provide package_id or package_name",
                }

            if package_id is None:
                row = db.execute(
                    "SELECT id, package FROM entries WHERE LOWER(package) LIKE ? "
                    "ORDER BY id LIMIT 1",
                    (f"%{package_name.lower()}%",),
                ).fetchone()
                if row is None:
                    db.close()
                    return {
                        "success": False,
                        "error": f"No installed package matching {package_name!r}",
                    }
                entry_id = row["id"]
                resolved_name = row["package"]
            else:
                entry_id = int(package_id)
                row = db.execute(
                    "SELECT package FROM entries WHERE id = ?", (entry_id,)
                ).fetchone()
                resolved_name = row["package"] if row else None

            files = db.execute(
                "SELECT path, main, type FROM files WHERE entry = ? ORDER BY path",
                (entry_id,),
            ).fetchall()
            db.close()

            resource = _resource_path()
            return {
                "success": True,
                "package_id": entry_id,
                "package_name": resolved_name,
                "count": len(files),
                "files": [
                    {
                        "relative_path": f["path"],
                        "absolute_path": str(resource / f["path"]),
                        "is_main": bool(f["main"]),
                        "type_code": f["type"],
                    }
                    for f in files
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def sync_repositories() -> dict:
        """Run ReaPack's sync — refresh cached index.xml files from every enabled repo.

        Equivalent to ``system run-reaper-action _REAPACK_SYNC``. After this
        runs, ``cache/`` contains up-to-date index.xml files and the package
        browser will show the latest catalogue. Required before installing
        new packages or updating existing ones.

        Note: REAPER's UI for ReaPack will show a progress dialog briefly.
        The tool returns immediately; the sync continues in the background.
        """
        from reapy import reascript_api as RPR

        try:
            cmd_id = int(RPR.NamedCommandLookup("_REAPACK_SYNC"))
            if cmd_id == 0:
                return {
                    "success": False,
                    "error": (
                        "_REAPACK_SYNC not registered — is ReaPack loaded? "
                        "Check with system lookup-reaper-action _REAPACK_SYNC."
                    ),
                }
            RPR.Main_OnCommand(cmd_id, 0)
            return {
                "success": True,
                "action_id": cmd_id,
                "note": "Sync started; continues asynchronously in REAPER.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def open_package_browser() -> dict:
        """Open ReaPack's package browser window in REAPER.

        Equivalent to ``system run-reaper-action _REAPACK_BROWSE``. The window
        is the only way to install / uninstall specific packages — there is
        no headless install action. Sync first if you want the latest
        catalogue.
        """
        from reapy import reascript_api as RPR

        try:
            cmd_id = int(RPR.NamedCommandLookup("_REAPACK_BROWSE"))
            if cmd_id == 0:
                return {
                    "success": False,
                    "error": "_REAPACK_BROWSE not registered — is ReaPack loaded?",
                }
            RPR.Main_OnCommand(cmd_id, 0)
            return {"success": True, "action_id": cmd_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
