"""Tests for paging in ComicView: PgDown/PgUp, the wheel, keeping place.

Each page here is 40×60 scaled to the 800-pixel width, so 1200 pixels
tall in a 600-pixel view: the shape of a fit-to-width comic page, which
is where paging used to go wrong.
"""

from __future__ import annotations

import zipfile

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from salt.ui.comic_view import ComicView


@pytest.fixture
def five_pages(tmp_path, sample_image_bytes):
    z = tmp_path / "five.cbz"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(5):
            zf.writestr(f"page{i}.png", sample_image_bytes)
    return z


@pytest.fixture
def view(qapp, five_pages):
    v = ComicView()
    v.resize(800, 600)
    v.show()
    QTest.qWaitForWindowExposed(v)
    assert v.load_source(str(five_pages))
    _settle(v)
    yield v
    v.close()


def _settle(v):
    """Run the rescale that a show or resize schedules, without waiting
    out its debounce."""
    QApplication.processEvents()
    if v._rescale_timer.isActive():
        v._rescale_timer.stop()
        v._invalidate_and_refresh()


def _top(v, index):
    return v._page_span(index)[0]


def _wheel(v, notches):
    """Turn the wheel; negative is down, as on a real mouse."""
    vp = v.viewport()
    pos = QPointF(vp.width() / 2, vp.height() / 2)
    ev = QWheelEvent(
        pos, vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120 * notches),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(vp, ev)


# -- Continuous mode ------------------------------------------------------

def test_pages_are_taller_than_the_view(view):
    assert view._page_span(0)[1] > view.viewport().height()


def test_next_page_shows_the_top_of_the_page(view):
    """It used to centre the page, skipping its top third."""
    view.next_page()
    assert view.current_page() == 1
    assert view.verticalScrollBar().value() == _top(view, 1)


def test_counter_follows_manual_scrolling(view):
    spy = QSignalSpy(view.page_changed)
    view.verticalScrollBar().setValue(_top(view, 3) + 100)
    assert view.current_page() == 3
    assert spy.at(spy.count() - 1) == [4, 5]


def test_next_page_continues_from_where_the_reader_is(view):
    view.verticalScrollBar().setValue(_top(view, 2) + 300)
    view.next_page()
    assert view.current_page() == 3
    assert view.verticalScrollBar().value() == _top(view, 3)


def test_prev_page_mid_page_goes_to_its_top_first(view):
    view.verticalScrollBar().setValue(_top(view, 2) + 300)
    view.prev_page()
    assert view.current_page() == 2
    assert view.verticalScrollBar().value() == _top(view, 2)
    view.prev_page()
    assert view.current_page() == 1
    assert view.verticalScrollBar().value() == _top(view, 1)


def test_the_end_counts_as_the_last_page(view):
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert view.current_page() == 4


def test_a_new_source_starts_at_the_top(view, comic_zip):
    view.verticalScrollBar().setValue(_top(view, 3))
    assert view.load_source(str(comic_zip))
    assert view.verticalScrollBar().value() == 0
    assert view.current_page() == 0


def test_resizing_keeps_the_page_being_read(view):
    """Every page rescales; the old offset would land pages away."""
    view.verticalScrollBar().setValue(_top(view, 3) + 200)
    view.resize(1200, 700)
    _settle(view)
    assert view.current_page() == 3
    value = view.verticalScrollBar().value()
    assert _top(view, 3) < value < _top(view, 4)


def test_switching_modes_keeps_the_page(view):
    view.verticalScrollBar().setValue(_top(view, 3) + 200)
    view.set_scroll_mode("page")
    assert view.current_page() == 3
    assert view.verticalScrollBar().value() == 0
    view.set_scroll_mode("continuous")
    assert view.current_page() == 3
    assert view.verticalScrollBar().value() == _top(view, 3)


# -- Page mode ------------------------------------------------------------

@pytest.fixture
def paged(view):
    view.set_scroll_mode("page")
    return view


def test_wheel_scrolls_a_tall_page_before_turning(paged):
    bar = paged.verticalScrollBar()
    _wheel(paged, -1)
    assert paged.current_page() == 0
    assert bar.value() > 0
    bar.setValue(bar.maximum())
    _wheel(paged, -1)
    assert paged.current_page() == 1
    assert bar.value() == 0


def test_wheel_up_at_the_top_turns_back_to_the_bottom(paged):
    paged.next_page()
    _wheel(paged, 1)
    assert paged.current_page() == 0
    bar = paged.verticalScrollBar()
    assert bar.value() == bar.maximum() > 0


def test_next_page_starts_at_the_top(paged):
    """It used to keep the scroll offset, opening the page at its bottom."""
    bar = paged.verticalScrollBar()
    bar.setValue(bar.maximum())
    paged.next_page()
    assert paged.current_page() == 1
    assert bar.value() == 0


def test_down_key_scrolls_then_turns(paged):
    bar = paged.verticalScrollBar()
    QTest.keyClick(paged, Qt.Key_Down)
    assert paged.current_page() == 0
    assert bar.value() > 0
    bar.setValue(bar.maximum())
    QTest.keyClick(paged, Qt.Key_Down)
    assert paged.current_page() == 1


def test_page_keys_still_turn_straight_away(paged):
    for key, expected in ((Qt.Key_Right, 1), (Qt.Key_Space, 2),
                          (Qt.Key_Left, 1), (Qt.Key_Backspace, 0)):
        QTest.keyClick(paged, key)
        assert paged.current_page() == expected


# -- Horizontal strip -----------------------------------------------------

def test_plain_wheel_scrolls_a_horizontal_strip(view):
    """Pages that fit the height left a vertical-only wheel nothing to do."""
    view.set_orientation("horizontal")
    view.set_fit_mode("vertical")
    _settle(view)
    hbar = view.horizontalScrollBar()
    assert view.verticalScrollBar().maximum() == 0
    assert hbar.maximum() > 0
    _wheel(view, -1)
    assert hbar.value() > 0
    _wheel(view, 1)
    assert hbar.value() == 0


# -- Pages of different shapes --------------------------------------------
# Every fixture above has identical pages. These mix portrait pages with
# double spreads, which is where sizing pages from one placeholder broke.

PORTRAIT, SPREAD = (40, 60), (80, 60)


def _mixed_view(qapp, tmp_path, sizes, mode="continuous", fit="horizontal",
                orientation="vertical"):
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage
    z = tmp_path / "mixed.cbz"
    with zipfile.ZipFile(z, "w") as zf:
        for i, (w, h) in enumerate(sizes):
            img = QImage(w, h, QImage.Format_RGB32)
            img.fill(QColor(20 * i % 255, 90, 120))
            buf = QBuffer()
            buf.open(QBuffer.WriteOnly)
            img.save(buf, "PNG")
            zf.writestr(f"page{i:03d}.png", bytes(buf.data()))
    v = ComicView()
    v.resize(800, 600)
    v.show()
    QTest.qWaitForWindowExposed(v)
    v.set_orientation(orientation)
    v.set_fit_mode(fit)
    v.set_scroll_mode(mode)
    assert v.load_source(str(z))
    _settle(v)
    return v


def _decodes_while_idle(v, ms=360):
    """How many pages get decoded while nothing happens."""
    count = []
    original = v._source.read_many
    v._source.read_many = lambda idx: (count.extend(idx), original(idx))[1]
    QTest.qWait(ms)
    v._source.read_many = original
    return len(count)


@pytest.mark.parametrize("sizes, mode, fit, turns", [
    ([SPREAD, PORTRAIT, PORTRAIT, PORTRAIT], "page", "horizontal", 1),
    ([PORTRAIT, PORTRAIT, SPREAD, PORTRAIT, PORTRAIT], "page", "horizontal", 2),
    ([PORTRAIT, PORTRAIT, (200, 60), PORTRAIT, PORTRAIT, PORTRAIT],
     "continuous", "vertical", 2),
])
def test_mixed_shapes_settle_instead_of_rescaling_forever(
    qapp, tmp_path, sizes, mode, fit, turns
):
    """A scrollbar the placeholder brought in and the decoded page took
    away again restarted the rescale timer every 120 ms."""
    v = _mixed_view(qapp, tmp_path, sizes, mode, fit)
    for _ in range(turns):
        v.next_page()
    QTest.qWait(250)
    assert _decodes_while_idle(v) == 0
    assert not v._rescale_timer.isActive()
    v.close()


def test_paging_lands_on_page_tops_among_spreads(qapp, tmp_path):
    """Evicted spreads used to grow back to a portrait page's height, which
    pushed the page just scrolled to hundreds of pixels down the view."""
    sizes = [SPREAD if i % 3 == 1 else PORTRAIT for i in range(20)]
    v = _mixed_view(qapp, tmp_path, sizes)
    bar = v.verticalScrollBar()

    def lands_on_its_top():
        qapp.processEvents()                 # let any layout change land
        return bar.value() - _top(v, v.current_page())

    for _ in range(8):
        v.next_page()
        assert lands_on_its_top() == 0
    for _ in range(3):
        v.prev_page()
        assert lands_on_its_top() == 0
    bar.setValue(_top(v, 15))                # jump past undecoded pages
    qapp.processEvents()
    for _ in range(2):
        v.prev_page()
        assert lands_on_its_top() == 0
    v.close()


def test_resize_keeps_the_place_on_a_spread(qapp, tmp_path):
    sizes = [SPREAD if i % 3 == 2 else PORTRAIT for i in range(12)]
    v = _mixed_view(qapp, tmp_path, sizes)
    bar = v.verticalScrollBar()
    for _ in range(5):                     # page 5, a spread, now decoded
        v.next_page()
    qapp.processEvents()
    start, extent = v._page_span(5)
    bar.setValue(start + extent * 2 // 5)
    qapp.processEvents()
    v.resize(1000, 700)
    _settle(v)
    qapp.processEvents()
    start, extent = v._page_span(5)
    assert v.current_page() == 5
    assert (bar.value() - start) / extent == pytest.approx(0.4, abs=0.02)
    v.close()


def test_a_new_page_starts_on_the_other_axis_too(qapp, tmp_path):
    """Horizontal strip, fit width: pages are taller than the window, and
    PgDown kept the vertical offset the last page was left at."""
    v = _mixed_view(qapp, tmp_path, [PORTRAIT] * 5, orientation="horizontal")
    vbar = v.verticalScrollBar()
    assert vbar.maximum() > 0
    vbar.setValue(vbar.maximum())
    v.next_page()
    assert vbar.value() == 0
    v.close()
