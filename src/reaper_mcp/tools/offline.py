"""Offline tools — operate on ``.RPP`` files and REAPER's plugin cache.

These do NOT require REAPER to be running. They complement the live ``python-reapy``
tools without name collisions.
"""

import json
import logging
from dataclasses import asdict

from reaper_mcp.offline_support.audio_analyzer import AudioAnalyzer
from reaper_mcp.offline_support.fx_finder import FXFinder
from reaper_mcp.offline_support.rpp_finder import RPPFinder
from reaper_mcp.offline_support.rpp_parser import RPPParser
from reaper_mcp.offline_support.utils import remove_empty_strings

logger = logging.getLogger("reaper_mcp.tools.offline")


def register_tools(mcp):
    @mcp.tool()
    def find_reaper_projects(base_directory: str) -> str:
        """Walk ``base_directory`` and return every ``.RPP`` file as JSON.

        Each entry: ``{"path", "project_name", "directory"}``.
        Offline tool — does not require REAPER to be running.
        """
        try:
            finder = RPPFinder(base_directory)
            return json.dumps(finder.find_reaper_projects())
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def parse_rpp_file(project_path: str) -> str:
        """Parse a ``.RPP`` file into a nested project structure (tracks, FX, items) as JSON.

        Offline tool — does not require REAPER to be running.
        """
        try:
            parser = RPPParser(project_path)
            return json.dumps(remove_empty_strings(asdict(parser.project)))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def analyze_rpp_audio(project_path: str, track_filter: str | None = None) -> str:
        """Parse a ``.RPP`` and analyze every referenced audio file for mixing feedback.

        Reports LUFS, true peak, crest factor, frequency band energies, stereo width, and
        warnings (clipping, muddiness, phase issues, over-compression).

        ``track_filter``: optional case-insensitive substring to limit which tracks' items
        are analyzed.

        Offline tool — does not require REAPER to be running.
        """
        try:
            parser = RPPParser(project_path)
            tracks = [
                t
                for t in parser.project.tracks
                if not track_filter or track_filter.lower() in t.name.lower()
            ]
            results = {
                "project_name": parser.project.name,
                "analyzed_files": [],
                "errors": [],
            }
            for track in tracks:
                for item in track.items:
                    try:
                        analyzer = AudioAnalyzer(item.audio_filepath)
                        analysis = analyzer.analyze()
                        if analysis.error:
                            results["errors"].append(
                                {
                                    "track_name": track.name,
                                    "audio_file": item.audio_filepath,
                                    "error": analysis.error,
                                }
                            )
                        else:
                            results["analyzed_files"].append(
                                {
                                    "track_name": track.name,
                                    "audio_file": item.audio_filepath,
                                    "position": item.position,
                                    "length": item.length,
                                    "analysis": asdict(analysis),
                                    "warnings": analysis.warnings,
                                }
                            )
                    except Exception as e:
                        results["errors"].append(
                            {
                                "track_name": track.name,
                                "audio_file": item.audio_filepath,
                                "error": str(e),
                            }
                        )
            return json.dumps(remove_empty_strings(results))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def list_installed_fx(plugin_type: str | None = None, search_query: str | None = None) -> str:
        """Enumerate REAPER's installed plugins by reading the resource-dir INI cache.

        ``plugin_type``: optional filter — ``VST2``, ``VST3``, ``AU``, ``JS``, ``CLAP``.
        ``search_query``: optional substring match across name, manufacturer, type.

        Offline tool — does not require REAPER to be running, but does require REAPER to
        have been launched at least once so the cache files exist.
        """
        try:
            finder = FXFinder()
            if search_query:
                plugins = finder.search_plugins(search_query)
            elif plugin_type:
                plugins = finder.get_plugins_by_type(plugin_type)
            else:
                plugins = finder.find_installed_plugins()
            return json.dumps({"total_count": len(plugins), "plugins": plugins})
        except Exception as e:
            return json.dumps({"error": str(e)})
