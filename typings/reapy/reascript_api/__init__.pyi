"""Stub for reapy.reascript_api — REAPER's ReaScript bindings are populated at
import time, not statically declared. Without this stub ty flags every
``RPR.<func>`` call as unresolved."""

from typing import Any

def __getattr__(name: str) -> Any: ...
