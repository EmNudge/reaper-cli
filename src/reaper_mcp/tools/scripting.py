"""Scripting — run arbitrary code inside the live REAPER process.

This is the package's deepest escape hatch. Where ``system run-reaper-action``
can only *fire pre-existing actions*, these tools execute new logic on REAPER's
main thread via the reapy dist-API bridge, with the full ReaScript API in scope
(``RPR`` / ``reaper`` / ``reapy`` are pre-bound). Anything expressible in a
Python ReaScript can run here in one call.

The headline use case is killing the "quit REAPER → hand-edit reaper.ini →
relaunch" loop: ``set_config_var`` writes REAPER's live config variables (the
in-memory backing for reaper.ini) and they take effect immediately.

Call ``about_scripting`` before first use — it documents the execution model,
the pre-bound namespace, and the safety characteristics.
"""

import logging

from reaper_mcp.connection import call_in_reaper

logger = logging.getLogger("reaper_mcp.tools.scripting")


def register_tools(mcp):
    @mcp.tool()
    def about_scripting() -> dict:
        """Orientation primer for the scripting tool group — call before first use.

        Covers the execution model (code runs inside REAPER, not in the CLI),
        the pre-bound API namespace, the exec-vs-eval return convention, how
        live config vars replace the edit-INI-and-restart workflow, and the
        safety characteristics.
        """
        return {
            "success": True,
            "what_it_is": (
                "A general code-execution channel into the running REAPER. The "
                "reapy bridge ships a reference to a helper in "
                "reaper_mcp.inreaper over its socket; REAPER's embedded Python "
                "imports it and runs your code on the main thread. This is "
                "strictly more powerful than run_reaper_action, which can only "
                "fire actions that already exist."
            ),
            "prebound_namespace": (
                "run_python / eval_python run with RPR, reaper (alias of RPR), "
                "and reapy already imported. Use the REAPER ReaScript API "
                "directly, e.g. RPR.CountTracks(0) or "
                "RPR.GetSetProjectInfo_String(...)."
            ),
            "return_convention": {
                "run_python": (
                    "Runs statements. Assign the value you want back to a "
                    "variable named `result` (override with return_var). stdout "
                    "and stderr are captured and returned under 'stdout'."
                ),
                "eval_python": "Evaluates one expression and returns its value.",
                "serialization": (
                    "Results are coerced to JSON-safe values; non-serializable "
                    "objects come back as their repr() string."
                ),
            },
            "live_config_vars": (
                "set_config_var / get_config_var read+write REAPER's live config "
                "variables (the in-memory backing of reaper.ini) via the SWS "
                "SNM_*ConfigVar functions. Changes apply immediately — this "
                "replaces the quit / edit reaper.ini / relaunch cycle for the "
                "large class of settings exposed as config vars. REAPER flushes "
                "the change to reaper.ini on its next config save (e.g. exit). "
                "Requires the SWS extension."
            ),
            "requirements": [
                "REAPER running with the distant API enabled (same as all live tools).",
                "reaper_mcp is an editable install, so it is NOT auto-importable "
                "inside REAPER; connection._ensure_remote_importable injects the "
                "src/ dir onto REAPER's sys.path via a one-time builtins.exec "
                "bootstrap, and clears cached reaper_mcp modules so edits to "
                "inreaper.py take effect without restarting REAPER. Localhost "
                "only (a remote slave machine would have a different path).",
                "Config-var tools additionally require the SWS extension — its "
                "SNM_*ConfigVar functions are bound via ctypes from "
                "reaper_python._ft, since REAPER's static binding omits them.",
            ],
            "safety": (
                "Code runs on REAPER's main thread, so it BLOCKS the UI while "
                "executing — keep snippets short and do not start defer loops "
                "here (they will not yield as expected). Exceptions are caught "
                "and returned as a traceback string rather than raised, so a "
                "bad snippet returns success:false instead of crashing REAPER. "
                "A segfaulting raw API call can still take REAPER down — the "
                "same risk as any ReaScript."
            ),
            "related": {
                "system": "run_reaper_action fires existing actions; prefer it when one exists.",
                "offline": "For editing project files with REAPER closed, use the offline group instead.",
            },
        }

    @mcp.tool()
    def run_python(code: str, return_var: str = "result") -> dict:
        """Execute Python statements inside the live REAPER process.

        ``RPR`` (the ReaScript API), its alias ``reaper``, and ``reapy`` are
        pre-imported into the execution namespace. To return a value, assign it
        to a variable named ``result`` (or pass a different ``return_var``).
        stdout/stderr are captured.

        Example — count tracks and report the first track's name::

            run_python('''
            n = RPR.CountTracks(0)
            first = RPR.GetTrackName(RPR.GetTrack(0, 0), "", 512)[2] if n else None
            result = {"track_count": n, "first_track": first}
            ''')

        Returns ``{success, result, stdout}`` or ``{success: false, error}``
        where ``error`` is the in-REAPER traceback. Runs on REAPER's main
        thread; keep snippets short. See ``about_scripting`` for the full model.
        """
        try:
            return call_in_reaper(_inreaper().run_code, code, "exec", return_var)
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def eval_python(expression: str) -> dict:
        """Evaluate a single Python expression inside the live REAPER process.

        Convenience wrapper over ``run_python`` for one-liners that already are
        an expression, e.g. ``eval_python("RPR.CountTracks(0)")``. The same
        pre-bound namespace (``RPR`` / ``reaper`` / ``reapy``) applies.
        """
        try:
            return call_in_reaper(_inreaper().run_code, expression, "eval", "result")
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_config_var(name: str) -> dict:
        """Read a live REAPER config variable (in-memory backing of reaper.ini).

        ``name`` is a reaper.ini key such as ``"defsplitxfadelen"`` or
        ``"projsamplerate"``. Tries an integer var first, then a double.
        Requires the SWS extension. See ``about_scripting`` → live_config_vars.
        """
        try:
            return call_in_reaper(_inreaper().get_config_var, name)
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_config_var(name: str, value: float) -> dict:
        """Set a live REAPER config variable; applies immediately (no restart).

        Replaces the quit / hand-edit reaper.ini / relaunch loop for settings
        exposed as config vars. Whole numbers are written as ints, fractional
        values as doubles. REAPER persists the change to reaper.ini on its next
        config flush. Requires the SWS extension.
        """
        try:
            return call_in_reaper(_inreaper().set_config_var, name, value)
        except Exception as e:
            return {"success": False, "error": str(e)}


def _inreaper():
    """Import the in-REAPER helper module lazily (keeps registration cheap)."""
    from reaper_mcp import inreaper

    return inreaper
