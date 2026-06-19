"""Stub for python-reapy — its public surface is dynamically populated, so we
declare a permissive __getattr__ instead of stubbing every binding (~4000)."""

from typing import Any

def __getattr__(name: str) -> Any: ...
