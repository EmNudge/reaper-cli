"""Tests for the in-REAPER scripting bridge.

These exercise the pieces that *don't* need a running REAPER:

* ``inreaper.run_code`` / ``_jsonable`` are pure — ``run_code`` is just an
  ``exec``/``eval`` with output capture, so it runs in-process here. REAPER is
  only involved when the function is dispatched over the bridge.
* ``connection.call_in_reaper`` dispatch is tested with a mocked reapy client.
* The wire contract — that reapy's JSON codec can encode ``run_code`` and decode
  it back to the same function — is what lets REAPER resolve and call the helper.
  If the module is renamed/moved without updating callers, that round-trip test
  fails loudly instead of the bridge silently 404ing inside REAPER.
"""

from __future__ import annotations

import json

import pytest

from reaper_mcp import connection, inreaper

# ---------- _jsonable coercion ----------


def test_jsonable_passes_through_primitives():
    for v in (None, True, False, 0, 3.14, "hi"):
        assert inreaper._jsonable(v) == v


def test_jsonable_recurses_containers():
    assert inreaper._jsonable({"a": [1, 2], "b": (3,)}) == {"a": [1, 2], "b": [3]}
    assert inreaper._jsonable({1, 2}) in ([1, 2], [2, 1])


def test_jsonable_non_serializable_becomes_repr():
    out = inreaper._jsonable(object())
    assert isinstance(out, str) and out.startswith("<object")


def test_jsonable_truncates_width():
    assert len(inreaper._jsonable(list(range(600)))) == 500
    assert len(inreaper._jsonable({i: i for i in range(300)})) == 200


def test_jsonable_bounds_depth():
    deep = current = {}
    for _ in range(12):
        current["next"] = {}
        current = current["next"]
    node = inreaper._jsonable(deep)
    for _ in range(inreaper.MAX_JSON_DEPTH):
        assert isinstance(node, dict)
        node = node["next"]
    # Beyond MAX_JSON_DEPTH the subtree degrades to a repr string.
    assert isinstance(node, str)


def test_jsonable_result_is_always_serializable():
    # Whatever run_code returns must survive json.dumps (the bridge does this).
    json.dumps(inreaper._jsonable({"x": object(), "y": [object()]}))


# ---------- run_code: exec / eval / capture / errors ----------


def test_run_code_exec_returns_result_var():
    out = inreaper.run_code("result = 1 + 1")
    assert out["success"] is True
    assert out["result"] == 2


def test_run_code_custom_return_var():
    out = inreaper.run_code("answer = 42", return_var="answer")
    assert out["result"] == 42


def test_run_code_default_result_is_none():
    out = inreaper.run_code("x = 5")  # no `result` assigned
    assert out["success"] is True
    assert out["result"] is None


def test_run_code_eval_mode_returns_expression():
    out = inreaper.run_code("6 * 7", mode="eval")
    assert out["success"] is True
    assert out["result"] == 42


def test_run_code_captures_stdout():
    out = inreaper.run_code("print('hello from reaper')")
    assert "hello from reaper" in out["stdout"]


def test_run_code_exception_is_returned_not_raised():
    out = inreaper.run_code("raise ValueError('boom')")
    assert out["success"] is False
    assert "ValueError" in out["error"]
    assert "boom" in out["error"]


def test_run_code_non_serializable_result_coerced():
    out = inreaper.run_code("result = object()")
    assert out["success"] is True
    assert isinstance(out["result"], str)


def test_run_code_namespace_has_builtins():
    # The exec namespace must expose builtins so user code can use them.
    out = inreaper.run_code("result = len([1, 2, 3])")
    assert out["result"] == 3


# ---------- the wire contract: reapy can address run_code across the bridge ----


def test_run_code_is_bridge_addressable():
    """reapy's codec must encode run_code and decode it back to the same object.

    This is exactly what REAPER's embedded Python does on the receiving end, so
    if this passes, REAPER can import and call our helper.
    """
    from reapy.tools import json as rjson

    encoded = rjson.dumps(inreaper.run_code)
    blob = json.loads(encoded)
    assert blob["__callable__"] is True
    assert blob["module_name"] == "reaper_mcp.inreaper"
    assert blob["name"] == "run_code"
    # object_hook resolves the blob back to the live function inside REAPER.
    assert rjson.loads(encoded) is inreaper.run_code


def test_inreaper_top_level_imports_are_stdlib_only():
    """inreaper must import in a plain process (no reapy/REAPER at module load).

    The CLI imports it just to obtain function objects to encode; a top-level
    reapy import would break that and, worse, could trip a connection attempt.
    """
    import ast
    from pathlib import Path

    src = Path(inreaper.__file__).read_text()
    tree = ast.parse(src)
    module_level = [
        n
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    names: list[str] = []
    for node in module_level:
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        else:
            names.extend(alias.name for alias in node.names)
    assert not any(n.split(".")[0] == "reapy" for n in names), (
        f"inreaper has a top-level reapy import: {names}"
    )


# ---------- call_in_reaper dispatch ----------


def test_call_in_reaper_inside_reaper_calls_directly(monkeypatch):
    import reapy

    monkeypatch.setattr(connection, "ensure_connected", lambda: None)
    monkeypatch.setattr(reapy, "is_inside_reaper", lambda: True)
    assert connection.call_in_reaper(lambda x: x * 2, 21) == 42


def test_call_in_reaper_outside_dispatches_to_client(monkeypatch):
    import reapy

    monkeypatch.setattr(connection, "ensure_connected", lambda: None)
    monkeypatch.setattr(reapy, "is_inside_reaper", lambda: False)

    captured = {}

    class FakeClient:
        def request(self, func, payload):
            captured["func"] = func
            captured["payload"] = payload
            return {"success": True, "result": "ok"}

    monkeypatch.setattr(
        reapy.tools.network.machines, "get_selected_client", lambda: FakeClient()
    )

    def some_helper(a, b=0):  # pragma: no cover - never actually invoked here
        return a + b

    out = connection.call_in_reaper(some_helper, 1, b=2)
    assert out == {"success": True, "result": "ok"}
    # The function object is passed through verbatim (reapy encodes it on send);
    # args/kwargs are packed into the bridge's expected envelope shape.
    assert captured["func"] is some_helper
    assert captured["payload"] == {"args": [1], "kwargs": {"b": 2}}


def test_call_in_reaper_raises_when_no_client(monkeypatch):
    import reapy

    monkeypatch.setattr(connection, "ensure_connected", lambda: None)
    monkeypatch.setattr(reapy, "is_inside_reaper", lambda: False)
    monkeypatch.setattr(
        reapy.tools.network.machines, "get_selected_client", lambda: None
    )
    with pytest.raises(RuntimeError):
        connection.call_in_reaper(lambda: None)
