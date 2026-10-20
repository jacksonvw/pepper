"""Shared fixtures for the viewer_core package tests.

Same pattern as pepper/tests and salt/tests: `QT_QPA_PLATFORM=offscreen`
before any Qt import, raw QApplication fixture, no pytest-qt.
"""

from __future__ import annotations

import os

# Must be set BEFORE importing PySide6.QtWidgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def fresh_blur():
    """Yield the blur module with its dlopen cache cleared, and restore it.

    _resolve() caches both success and failure in module globals, so tests
    that simulate a missing library must reset them or they leak.
    """
    from viewer_core.core import blur

    saved = (blur._resolved, blur._enable_blur_behind)
    blur._resolved = False
    blur._enable_blur_behind = None
    yield blur
    blur._resolved, blur._enable_blur_behind = saved
