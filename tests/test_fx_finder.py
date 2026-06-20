"""Tests for the FXFinder INI parsers — VST, AU, JS, CLAP.

Each parser handles a different format quirk; mocking a fake REAPER resource
dir lets us cover them all without depending on the user's actual install.
"""

from __future__ import annotations

from reaper_mcp.offline_support.fx_finder import FXFinder


def _make_finder(tmp_path, files: dict[str, str]) -> FXFinder:
    """Build an FXFinder pointed at a fake resource dir containing ``files``."""
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    return FXFinder(reaper_resource_path=str(tmp_path))


# ---------- VST ----------


def test_parses_vst2_entry(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": ("reaeq.dll=ABC123,12345,ReaEQ (Cockos)\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "ReaEQ"
    assert plugins[0]["plugin_type"] == "VST2"
    assert plugins[0]["manufacturer"] == "Cockos"


def test_parses_vst3_entry(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": ("reacomp.vst3=DEF456,67890,ReaComp (Cockos)\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    assert plugins[0]["plugin_type"] == "VST3"


def test_strips_vsti_marker(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": ("synth.dll=AAA,111,SomeSynth (Vendor)!!!VSTi\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    assert plugins[0]["name"] == "SomeSynth"
    assert plugins[0]["manufacturer"] == "Vendor"


def test_skips_comments_and_section_headers(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": (
                "; this is a comment\n[a section header]\nreal.dll=ABC,123,Real (Vendor)\n\n"
            ),
        },
    )
    plugins = finder.find_installed_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "Real"


# ---------- AU ----------


def test_parses_au_entry(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-auplugins64.ini": ("Apple: AUSampler=<inst>\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    au = [p for p in plugins if p["plugin_type"] == "AU"]
    assert len(au) == 1
    assert au[0]["name"] == "AUSampler"
    assert au[0]["manufacturer"] == "Apple"


def test_skips_au_marked_not_installed(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-auplugins64.ini": ("Apple: GoodOne=<inst>\nApple: NotInstalled=<!inst>\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    au_names = {p["name"] for p in plugins if p["plugin_type"] == "AU"}
    assert au_names == {"GoodOne"}


# ---------- JS ----------


def test_parses_js_entry_with_category(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-jsfx.ini": ("Guitar/Saturator=Guitar/Saturator.jsfx\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    js = [p for p in plugins if p["plugin_type"] == "JS"]
    assert len(js) == 1
    assert js[0]["name"] == "Saturator"
    assert js[0]["category"] == "Guitar"
    assert js[0]["manufacturer"] == "JSFX"


def test_parses_js_entry_without_category(tmp_path):
    finder = _make_finder(
        tmp_path,
        {"reaper-jsfx.ini": "Standalone=standalone.jsfx\n"},
    )
    plugins = finder.find_installed_plugins()
    js = [p for p in plugins if p["plugin_type"] == "JS"]
    assert js[0]["name"] == "Standalone"
    assert js[0]["category"] is None


# ---------- CLAP ----------


def test_parses_clap_entry(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-clapplugins64.ini": (
                '"Vendor - Snazzy Synth"=/Library/Audio/Plug-Ins/CLAP/SnazzySynth.clap\n'
            ),
        },
    )
    plugins = finder.find_installed_plugins()
    clap = [p for p in plugins if p["plugin_type"] == "CLAP"]
    assert len(clap) == 1
    assert clap[0]["manufacturer"] == "Vendor"


def test_clap_falls_back_to_path_when_name_lacks_separator(tmp_path):
    """The display name has no ' - ' or ': ' separator, so we walk the path —
    and must skip the leading '/' segment instead of returning it as the
    manufacturer."""
    finder = _make_finder(
        tmp_path,
        {
            "reaper-clapplugins64.ini": (
                '"SnazzySynth"=/Library/Audio/Plug-Ins/CLAP/Surge/SnazzySynth.clap\n'
            ),
        },
    )
    clap = [p for p in finder.find_installed_plugins() if p["plugin_type"] == "CLAP"]
    # Path walk should pick up "Surge" (the vendor sub-dir under CLAP/), not
    # "/", "Library", "Audio", "Plug-Ins", or "CLAP".
    assert clap[0]["manufacturer"] == "Surge"


def test_vst_display_with_multiple_parens_uses_last_group(tmp_path):
    """Names like ``Soothe2 (FF Pro) (oeksound)`` need to bind the manufacturer
    to the *last* parenthesized group — splitting on the first '(' would give
    the wrong answer."""
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": ("soothe2.dll=AAA,1,Soothe2 (FF Pro) (oeksound)\n"),
        },
    )
    plugins = finder.find_installed_plugins()
    assert plugins[0]["name"] == "Soothe2 (FF Pro)"
    assert plugins[0]["manufacturer"] == "oeksound"


# ---------- search / filter ----------


def test_get_plugins_by_type_filters_correctly(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": "x.dll=AAA,1,X (Vendor)\n",
            "reaper-jsfx.ini": "Y=Y.jsfx\n",
        },
    )
    vsts = finder.get_plugins_by_type("VST2")
    assert len(vsts) == 1
    assert vsts[0]["name"] == "X"


def test_search_plugins_matches_name_or_manufacturer(tmp_path):
    finder = _make_finder(
        tmp_path,
        {
            "reaper-vstplugins64.ini": (
                "a.dll=AAA,1,Apple (Cockos)\n"
                "b.dll=BBB,2,Banana (Cockos)\n"
                "c.dll=CCC,3,Cherry (Acme)\n"
            ),
        },
    )
    cockos = finder.search_plugins("cockos")
    assert {p["name"] for p in cockos} == {"Apple", "Banana"}
    banana = finder.search_plugins("banana")
    assert len(banana) == 1
    assert banana[0]["name"] == "Banana"


def test_no_files_returns_empty(tmp_path):
    finder = _make_finder(tmp_path, {})
    assert finder.find_installed_plugins() == []
