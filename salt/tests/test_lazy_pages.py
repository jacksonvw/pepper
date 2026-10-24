"""Tests for lazy page decoding and for surviving a failed open.

Between them these cover the two things that made Salt unusable on a real
comic collection: decoding every page of an archive up front, and closing
the window when an open failed.
"""

from __future__ import annotations

import zipfile

import pytest

from salt.ui.comic_view import _CACHE_PAGES, ComicView
from salt.ui.main_window import MainWindow


@pytest.fixture
def big_comic(tmp_path, sample_image_bytes):
    """A 40-page archive — comfortably more than the decode window."""
    z = tmp_path / "big.cbz"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(40):
            zf.writestr(f"page{i:03d}.png", sample_image_bytes)
    return z


@pytest.fixture
def view(qapp):
    v = ComicView()
    v.resize(800, 600)
    return v


# -- Lazy decoding --------------------------------------------------------

def test_all_pages_counted_but_not_all_decoded(view, big_comic):
    assert view.load_source(str(big_comic)) is True
    assert view.page_count() == 40
    assert len(view._cache) <= _CACHE_PAGES


def test_cache_stays_bounded_while_paging(view, big_comic):
    view.load_source(str(big_comic))
    view.set_scroll_mode("page")
    for _ in range(30):
        view.next_page()
        assert len(view._cache) <= _CACHE_PAGES
    assert view.current_page() == 30


def test_every_page_is_reachable(view, big_comic):
    """Lazy loading must not make later pages undecodable."""
    view.load_source(str(big_comic))
    view.set_scroll_mode("page")
    for expected in range(1, 40):
        view.next_page()
        assert view.current_page() == expected
        assert view._labels[expected].pixmap() is not None
        assert not view._labels[expected].pixmap().isNull()


def test_undecoded_labels_still_have_geometry(view, big_comic):
    """Placeholders keep the scrollbar proportional to the whole set."""
    view.load_source(str(big_comic))
    far = view._labels[-1]
    assert far.width() > 0 and far.height() > 0


def test_visible_window_never_exceeds_cache(view, big_comic):
    view.load_source(str(big_comic))
    assert len(view._visible_indices()) <= _CACHE_PAGES


def test_source_closed_and_replaced_on_reload(view, big_comic, comic_zip):
    view.load_source(str(big_comic))
    assert view.page_count() == 40
    view.load_source(str(comic_zip))
    assert view.page_count() == 3
    assert len(view._cache) <= 3


def test_fit_change_reflows_without_growing_cache(view, big_comic):
    view.load_source(str(big_comic))
    for mode in ("vertical", "both", "none", "horizontal"):
        view.set_fit_mode(mode)
        assert view.fit_mode() == mode
        assert len(view._cache) <= _CACHE_PAGES


# -- Failure reporting ----------------------------------------------------

def test_last_error_set_for_unsupported(view, tmp_path):
    junk = tmp_path / "junk.cbz"
    junk.write_bytes(b"nope")
    assert view.load_source(str(junk)) is False
    assert view.last_error()


def test_last_error_cleared_on_success(view, comic_zip, tmp_path):
    junk = tmp_path / "junk.cbz"
    junk.write_bytes(b"nope")
    view.load_source(str(junk))
    assert view.last_error()
    view.load_source(str(comic_zip))
    assert view.last_error() is None


# -- MainWindow stays up --------------------------------------------------

def test_window_survives_a_bad_initial_path(qapp, tmp_path):
    """The original bug: a bad initial path closed the app 1.5s later."""
    junk = tmp_path / "broken.cbr"
    junk.write_bytes(b"not a rar")
    win = MainWindow(initial_path=str(junk))
    # isHidden(), not isVisible(): the window itself hasn't been shown yet,
    # which makes every child "not visible" regardless of its own state.
    assert not win._error_label.isHidden()
    assert win._error_label.text()
    # And it is still a live window rather than a closed one.
    win.show()
    assert win.isVisible()
    assert not win._error_label.isHidden()
    assert win._error_label.width() > 0
    # No status-bar message drawn over the "Couldn't open" label.
    assert win._status_source.text() == "Couldn't open broken.cbr"
    assert win.statusBar().currentMessage() == ""
    win.close()


def test_error_overlay_clears_after_a_good_open(qapp, tmp_path, comic_zip):
    junk = tmp_path / "broken.cbr"
    junk.write_bytes(b"not a rar")
    win = MainWindow(initial_path=str(junk))
    assert not win._error_label.isHidden()
    win._open(str(comic_zip))
    assert win._error_label.isHidden()
    assert "comic.cbz" in win.windowTitle()
    win.close()


def test_incomplete_download_message_reaches_the_window(qapp, sparse_archive):
    from salt.core import archive
    if archive._hole_offset(sparse_archive) is None:
        pytest.skip("filesystem doesn't report holes")
    win = MainWindow(initial_path=str(sparse_archive))
    assert "incomplete download" in win._error_label.text()
    win.close()


def test_tests_keep_out_of_the_real_config(qapp, tmp_path_factory):
    """Saved geometry and config.toml land in scratch dirs, not ~/.config."""
    from salt.core import config
    scratch = str(tmp_path_factory.getbasetemp())
    win = MainWindow()
    assert win._settings().fileName().startswith(scratch)
    assert str(config._default_path()).startswith(scratch)
    win.close()


def test_overlay_stays_centred_when_minimal_mode_hides_the_status_bar(qapp, tmp_path):
    """Hiding the status bar resizes the viewport but not the window."""
    junk = tmp_path / "broken.cbr"
    junk.write_bytes(b"not a rar")
    win = MainWindow(initial_path=str(junk))
    win.resize(600, 400)
    win.show()
    qapp.processEvents()
    vp, label = win._comic_view.viewport(), win._error_label
    before = vp.height()
    win._on_toggle_minimal()
    qapp.processEvents()
    try:
        assert vp.height() != before
        assert abs(label.geometry().center().y() - vp.height() / 2) <= 1
    finally:
        win._on_toggle_minimal()  # the saved setting is shared by later tests
        win.close()


def test_single_image_opens_at_that_page(qapp, comic_dir):
    """It used to open the folder at page 1, titled with the one file."""
    win = MainWindow(initial_path=str(comic_dir / "page10.png"))
    win.resize(800, 600)
    win.show()
    qapp.processEvents()
    view = win._comic_view
    # Nothing can scroll before the first show; the rescale that follows
    # it puts the page in view. Run it now rather than wait out its timer.
    if view._rescale_timer.isActive():
        view._rescale_timer.stop()
        view._invalidate_and_refresh()
    assert view.current_page() == 2
    assert win._status_page.text() == "3/3"
    assert view.verticalScrollBar().value() == view._page_span(2)[0]
    assert win.windowTitle() == "Salt — comic"
    win.close()


def test_a_single_broken_image_is_named(qapp, comic_dir):
    """Not papered over by opening the readable pages next to it."""
    (comic_dir / "page5.png").write_bytes(b"not an image")
    win = MainWindow(initial_path=str(comic_dir / "page5.png"))
    assert win._error_label.text() == "page5.png isn't an image Qt can decode"
    win.close()


def test_a_zip_of_issues_is_explained(view, tmp_path, comic_zip):
    """Not called empty: the pages are inside the archives it holds."""
    pack = tmp_path / "pack.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.write(comic_zip, "Issue 01.cbz")
        zf.write(comic_zip, "Issue 02.cbz")
    assert view.load_source(str(pack)) is False
    assert view.last_error() == (
        "pack.zip holds Issue 01.cbz and 1 more rather than pages — "
        "Salt opens one archive or folder at a time"
    )


def test_a_folder_of_chapters_is_explained(view, tmp_path, sample_image_bytes):
    series = tmp_path / "Series"
    for chapter in ("Chapter 2", "Chapter 10"):
        (series / chapter).mkdir(parents=True)
        (series / chapter / "001.png").write_bytes(sample_image_bytes)
    assert view.load_source(str(series)) is False
    assert view.last_error().startswith("Series holds Chapter 2 and 1 more")


def test_an_archive_with_nothing_in_it_is_still_empty(view, tmp_path):
    empty = tmp_path / "empty.cbz"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no pages")
    assert view.load_source(str(empty)) is False
    assert view.last_error() == "No readable images in there"
