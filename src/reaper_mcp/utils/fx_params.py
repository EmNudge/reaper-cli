"""FX parameter resolver — shared by tools that address params by index OR name."""

from __future__ import annotations


def resolve_fx_param_index(fx, param: int | str) -> int:
    """Return the integer param index for ``param``.

    ``param`` may be an integer (used directly) or a string parameter name
    (case-insensitive). Returns ``-1`` if no match.

    Works with any FX-like object that exposes ``n_params`` and
    ``params[i].name`` — i.e. ``reapy.Track.fxs[i]`` or master-track FX.
    """
    try:
        idx = int(param)
        if 0 <= idx < fx.n_params:
            return idx
    except (ValueError, TypeError):
        wanted = str(param).lower()
        for i in range(fx.n_params):
            if fx.params[i].name.lower() == wanted:
                return i
    return -1
