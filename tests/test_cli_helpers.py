"""Tests for the CLI's introspection helpers.

The annotation normalizer and docstring cleaner have many edge cases — most
already broke once during development. Lock them in.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from reaper_mcp.cli import (
    _clean_docstring,
    _is_list_of_dict,
    _normalize_annotation_for_cli,
    _short_help,
)

# ---------- _is_list_of_dict ----------


def test_is_list_of_dict_bare():
    assert _is_list_of_dict(list[dict])


def test_is_list_of_dict_with_subscripted_inner():
    assert _is_list_of_dict(list[dict[str, Any]])


def test_is_list_of_dict_rejects_list_of_int():
    assert not _is_list_of_dict(list[int])


def test_is_list_of_dict_rejects_plain_list():
    assert not _is_list_of_dict(list)


def test_is_list_of_dict_rejects_str():
    assert not _is_list_of_dict(str)


# ---------- _normalize_annotation_for_cli ----------


def test_normalize_passes_through_simple_types():
    new_ann, mode = _normalize_annotation_for_cli(int)
    assert new_ann is int
    assert mode is None


def test_normalize_union_int_str_collapses_to_str():
    new_ann, mode = _normalize_annotation_for_cli(Union[int, str])
    assert new_ann is str
    assert mode is None


def test_normalize_optional_union_int_str():
    """Optional[Union[int, str]] → Optional[str]."""
    new_ann, mode = _normalize_annotation_for_cli(Optional[int | str])
    assert new_ann == Optional[str]
    assert mode is None


def test_normalize_pep604_union_collapses_to_str():
    """PEP 604 ``int | str`` must collapse the same as Union[int, str].

    Modern linters rewrite Union → ``|``; both forms have to work because
    ``get_origin()`` returns different things (typing.Union vs types.UnionType).
    This regression test pins the fix.
    """
    new_ann, mode = _normalize_annotation_for_cli(int | str)
    assert new_ann is str
    assert mode is None


def test_normalize_pep604_optional_int_str():
    """``int | str | None`` → ``Optional[str]``."""
    new_ann, mode = _normalize_annotation_for_cli(int | str | None)
    assert new_ann == Optional[str]
    assert mode is None


def test_normalize_pep604_bool_or_none_does_not_crash():
    """``bool | None`` is not the int/str pattern; should pass through cleanly."""
    new_ann, mode = _normalize_annotation_for_cli(bool | None)
    assert mode is None


def test_normalize_list_of_dict_becomes_json_string():
    new_ann, mode = _normalize_annotation_for_cli(list[dict[str, Any]])
    assert new_ann == Optional[str]
    assert mode == "json"


def test_normalize_optional_list_int_unwraps_optional():
    """Typer dislikes Optional[list[...]]; unwrap to list[int] with None default."""
    new_ann, mode = _normalize_annotation_for_cli(Optional[list[int]])
    assert new_ann == list[int]
    assert mode is None


def test_normalize_list_int_passes_through():
    new_ann, mode = _normalize_annotation_for_cli(list[int])
    assert new_ann == list[int]
    assert mode is None


# ---------- _clean_docstring ----------


def test_clean_docstring_none():
    assert _clean_docstring(None) is None
    assert _clean_docstring("") is None


def test_clean_docstring_strips_double_backticks():
    cleaned = _clean_docstring("Set ``item`` to a value.")
    assert "``" not in cleaned
    assert "item" in cleaned


def test_clean_docstring_strips_single_backticks():
    cleaned = _clean_docstring("Set `item` to a value.")
    assert "`" not in cleaned
    assert "item" in cleaned


def test_clean_docstring_collapses_soft_wraps():
    """A paragraph split across lines should reflow into one line."""
    doc = "First sentence.\nSecond on its own line.\nThird also wrapping."
    cleaned = _clean_docstring(doc)
    assert "\n" not in cleaned
    assert cleaned == "First sentence. Second on its own line. Third also wrapping."


def test_clean_docstring_preserves_paragraph_breaks():
    """Blank-line-separated paragraphs must stay separate."""
    doc = (
        "First paragraph wraps\nacross two lines.\n\nSecond paragraph also wraps\nacross two lines."
    )
    cleaned = _clean_docstring(doc)
    parts = cleaned.split("\n\n")
    assert len(parts) == 2
    assert "\n" not in parts[0]
    assert "\n" not in parts[1]


def test_clean_docstring_preserves_bullets():
    doc = "Modes:\n- one\n- two\n- three"
    cleaned = _clean_docstring(doc)
    # bullet block kept as-is (with newlines)
    assert "- one" in cleaned
    assert "- two" in cleaned
    assert cleaned.count("\n") >= 2  # bullets kept on separate lines


def test_clean_docstring_dedents():
    doc = "    First line.\n    Second line."
    cleaned = _clean_docstring(doc)
    assert not cleaned.startswith(" ")


# ---------- _short_help ----------


def test_short_help_returns_first_paragraph():
    doc = "Short summary.\n\nLong detailed explanation\nwith multiple lines."
    short = _short_help(doc)
    assert short == "Short summary."


def test_short_help_strips_backticks():
    short = _short_help("Set ``item`` color.")
    assert "``" not in short


def test_short_help_none():
    assert _short_help(None) is None
    assert _short_help("") is None
