"""``reaper-cli`` — command-line access to every unified tool.

Reuses the same tool functions as the MCP server. Each tool module's
``register_tools()`` is called with a CLI collector that quacks like FastMCP
but registers commands on a Typer sub-app instead.

Output: every command prints the tool's return value as JSON to stdout.
Tools that return a string (the offline tools) print it verbatim.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import types
from typing import Any, Optional, Union, get_args, get_origin

import typer

_INLINE_CODE = re.compile(r"`{1,2}([^`]+)`{1,2}")
_BULLET_OR_INDENT = re.compile(r"^(\s*[-*+]\s|\s{4,}|\s*\d+\.\s)")


def _is_union_origin(origin) -> bool:
    """True for both ``typing.Union[...]`` and PEP 604 ``X | Y`` annotations."""
    return origin is Union or origin is types.UnionType


def _clean_docstring(doc: str | None) -> str | None:
    """Dedent, strip RST backticks, and collapse soft-wraps so Typer can reflow.

    Without this, docstrings written for ~90-char source lines end up double-wrapped
    in the terminal, leaving stray words on their own line.
    """
    if not doc:
        return None
    doc = inspect.cleandoc(doc)
    doc = _INLINE_CODE.sub(r"\1", doc)
    out: list[str] = []
    for para in re.split(r"\n\s*\n", doc):
        lines = para.splitlines()
        if any(_BULLET_OR_INDENT.match(line) for line in lines):
            out.append(para)
        else:
            out.append(" ".join(line.strip() for line in lines if line.strip()))
    return "\n\n".join(out).strip() or None


def _short_help(doc: str | None) -> str | None:
    """First paragraph of the cleaned docstring, used in group command listings."""
    cleaned = _clean_docstring(doc)
    if not cleaned:
        return None
    first = cleaned.split("\n\n", 1)[0]
    return first.strip() or None


app = typer.Typer(
    name="reaper-cli",
    help=(
        "REAPER MCP — command-line access to 200+ unified tools (no LLM client required).\n\n"
        "Commands are grouped by module. Live tools need REAPER running with the "
        "python-reapy distant API enabled; offline tools (under 'offline') do not."
    ),
    no_args_is_help=True,
)


def _is_list_of_dict(ann: Any) -> bool:
    """``list[dict]``, ``list[dict[X, Y]]``, ``List[Dict[...]]`` all qualify."""
    if get_origin(ann) is not list:
        return False
    args = get_args(ann)
    if not args:
        return False
    inner = args[0]
    return inner is dict or get_origin(inner) is dict


def _normalize_annotation_for_cli(ann: Any) -> tuple[Any, str | None]:
    """Reshape tricky type hints to Typer-friendly ones.

    Returns ``(new_annotation, parse_mode)``. ``parse_mode`` is ``None`` unless
    the wrapper needs to post-process the CLI-supplied value (currently only
    ``"json"`` for ``list[dict]`` args).
    """
    origin = get_origin(ann)
    args = get_args(ann)

    # Union[int, str] (with or without None) — collapse to str. The underlying
    # tool functions already handle both via ``int(x)`` fallback.
    if _is_union_origin(origin):
        non_none = tuple(a for a in args if a is not type(None))
        has_none = type(None) in args
        if set(non_none) == {int, str}:
            return (Optional[str] if has_none else str), None
        # Optional[list[dict[...]]] → Optional[str] with JSON parsing
        if len(non_none) == 1 and _is_list_of_dict(non_none[0]):
            return Optional[str], "json"
        # Optional[list[int]] / Optional[list[str]] — Typer dislikes Union
        # wrappers around list, so recurse on the inner list type and keep
        # ``Optional`` semantics via a ``None`` default.
        if len(non_none) == 1 and get_origin(non_none[0]) is list:
            return non_none[0], None

    # Bare list[dict[...]] — accept JSON on the CLI.
    if _is_list_of_dict(ann):
        return Optional[str], "json"

    # list[int] / list[str] — Typer handles via repeated --flag, leave as-is.
    return ann, None


def _wrap_for_cli(fn):
    """Build a Typer-compatible wrapper around an MCP tool function.

    The wrapper has a rewritten ``__signature__`` so Typer sees CLI-friendly
    types, applies JSON parsing for ``list[dict]`` args, then calls the
    underlying function and prints the result as JSON.
    """
    sig = inspect.signature(fn)
    needs_parse: dict[str, str] = {}
    new_params: list[inspect.Parameter] = []
    for name, p in sig.parameters.items():
        new_ann, parse_mode = _normalize_annotation_for_cli(p.annotation)
        if parse_mode:
            needs_parse[name] = parse_mode
        new_params.append(p.replace(annotation=new_ann))
    new_sig = sig.replace(parameters=new_params)

    def wrapper(**kwargs):
        for name, mode in needs_parse.items():
            v = kwargs.get(name)
            if v is None or mode != "json":
                continue
            try:
                kwargs[name] = json.loads(v)
            except json.JSONDecodeError as e:
                raise typer.BadParameter(f"--{name.replace('_', '-')} requires JSON: {e}") from e
        result = fn(**kwargs)
        if isinstance(result, str):
            typer.echo(result)
        else:
            typer.echo(json.dumps(result, indent=2, default=str))

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = _clean_docstring(fn.__doc__)
    # ``inspect.signature`` honors ``__signature__`` if set on a function; type
    # checkers don't model this. ty doesn't honor mypy ``type: ignore`` codes,
    # so we use its own ``ty: ignore`` syntax to silence the warning.
    wrapper.__signature__ = new_sig  # ty: ignore[unresolved-attribute]
    return wrapper


class _CLICollector:
    """Quacks like FastMCP for ``register_tools()``.

    Each ``mcp.tool()`` decoration becomes a Typer command on ``sub_app``,
    with the underscore-named function name converted to kebab-case.
    """

    def __init__(self, sub_app: typer.Typer):
        self.sub_app = sub_app

    def tool(self, *_, **__):
        def decorator(fn):
            wrapped = _wrap_for_cli(fn)
            cli_name = fn.__name__.replace("_", "-")
            self.sub_app.command(
                name=cli_name,
                help=_clean_docstring(fn.__doc__),
                short_help=_short_help(fn.__doc__),
            )(wrapped)
            return fn

        return decorator


def _build() -> None:
    import importlib

    from reaper_mcp.tools import TOOL_MODULES

    for module_name, helptxt in TOOL_MODULES:
        cli_name = module_name.replace("_", "-")
        module = importlib.import_module(f"reaper_mcp.tools.{module_name}")
        sub = typer.Typer(name=cli_name, help=helptxt, no_args_is_help=True)
        module.register_tools(_CLICollector(sub))
        app.add_typer(sub, name=cli_name)


_build()


def main() -> None:
    """Entry point referenced by ``[project.scripts]``."""
    try:
        app()
    except RuntimeError as e:
        # Friendly message when REAPER is not running and a live tool fires.
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
