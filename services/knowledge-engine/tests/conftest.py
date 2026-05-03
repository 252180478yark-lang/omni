"""pytest-asyncio configuration for knowledge-engine tests.

Sets asyncio_mode=strict and provides a module-scoped event_loop fixture
so that module-scoped async fixtures (like the DB pool) share the same
loop as the test functions within each module.
"""
from __future__ import annotations

import asyncio
import pytest


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop shared between module-scoped fixtures and tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
