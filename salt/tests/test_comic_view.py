"""Tests for ComicView — load, mode toggles, page navigation."""

from __future__ import annotations

import pytest

from salt.ui.comic_view import ComicView


@pytest.fixture
def view(qapp):
    v = ComicView()
    v.resize(800, 600)
    return v


def test_construction(view):
    assert view.page_count() == 0
    assert view.orientation() == "vertical"
    assert view.fit_mode() == "horizontal"
    assert view.scroll_mode() == "continuous"
    assert view.page_gap() == 8


def test_load_directory(view, comic_dir):
    assert view.load_source(str(comic_dir)) is True
    assert view.page_count() == 3


def test_load_zip(view, comic_zip):
    assert view.load_source(str(comic_zip)) is True
    assert view.page_count() == 3


def test_load_missing_returns_false(view, tmp_path):
    assert view.load_source(str(tmp_path / "nope.cbz")) is False


def test_load_empty_returns_false(view, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert view.load_source(str(empty)) is False


def test_set_orientation(view, comic_dir):
    view.load_source(str(comic_dir))
    view.set_orientation("horizontal")
    assert view.orientation() == "horizontal"


def test_set_fit_mode(view, comic_dir):
    view.load_source(str(comic_dir))
    view.set_fit_mode("both")
    assert view.fit_mode() == "both"


def test_set_scroll_mode(view, comic_dir):
    view.load_source(str(comic_dir))
    view.set_scroll_mode("page")
    assert view.scroll_mode() == "page"


def test_invalid_setters_ignored(view):
    view.set_orientation("diagonal")
    assert view.orientation() == "vertical"
    view.set_fit_mode("bogus")
    assert view.fit_mode() == "horizontal"
    view.set_scroll_mode("turbo")
    assert view.scroll_mode() == "continuous"


def test_fit_mode_none_skips_scaling(view, comic_dir):
    view.load_source(str(comic_dir))
    view.set_fit_mode("none")
    assert view.fit_mode() == "none"
    # With fit_mode=none the pixmap on each label should be the
    # original 40×60 dimensions (per conftest sample_image_bytes).
    label0 = view._labels[0]
    pix = label0.pixmap()
    assert pix.width() == 40
    assert pix.height() == 60


def test_next_prev_page(view, comic_dir):
    view.load_source(str(comic_dir))
    view.set_scroll_mode("page")
    assert view.current_page() == 0
    view.next_page()
    assert view.current_page() == 1
    view.next_page()
    assert view.current_page() == 2
    # Past end is a no-op.
    view.next_page()
    assert view.current_page() == 2
    view.prev_page()
    assert view.current_page() == 1
    # Before start is a no-op.
    view.prev_page()
    view.prev_page()
    view.prev_page()
    assert view.current_page() == 0


def test_page_gap_setter(view):
    view.set_page_gap(20)
    assert view.page_gap() == 20
    # Negative clamps to 0.
    view.set_page_gap(-5)
    assert view.page_gap() == 0


def test_page_changed_signal(view, comic_dir):
    from PySide6.QtTest import QSignalSpy
    spy = QSignalSpy(view.page_changed)
    view.load_source(str(comic_dir))
    # load emits at least once (the initial page).
    assert spy.count() >= 1
