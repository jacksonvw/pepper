"""ComicView — scrollable image stack with orientation/fit/scroll-mode controls.

Pages are decoded lazily. A label exists for every page from the moment a
source loads, but only the pages near the viewport hold a pixmap; the rest
carry a placeholder geometry so the scrollbar stays honest. HD comic scans
run ~33 MB apiece once decoded, so eagerly decoding a 100-page issue cost
several gigabytes — an LRU window keeps it flat regardless of issue size.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QScrollBar,
    QWidget,
)

from salt.core.archive import PageSource, UnsupportedArchive, open_page_source

log = logging.getLogger(__name__)

VALID_ORIENTATIONS = ("vertical", "horizontal")
VALID_FITS = ("horizontal", "vertical", "both", "none")
VALID_SCROLL_MODES = ("continuous", "page")

# Decoded pages held at once. Sized so a 4K fullscreen viewport (where a
# fit-to-width page is ~78 MB) stays in the hundreds of megabytes.
_CACHE_PAGES = 8
# Pages decoded beyond the visible run, in each direction.
_LOOKAHEAD = 2
_LOOKBEHIND = 1
# Coalesce the burst of resize events an interactive drag produces.
_RESCALE_DEBOUNCE_MS = 120


class ComicView(QScrollArea):
    """Scrollable image stack.

    Signals:
        page_changed(int current_1_indexed, int total)
        source_loaded(int total, str name)

    State is exposed via set_* / property-like accessors; MainWindow drives
    these from config and from the right-click menu.
    """

    page_changed = Signal(int, int)
    source_loaded = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)

        # The viewport and the inner container both need to NOT autofill
        # their background — otherwise an opaque palette-base layer sits
        # between the (potentially translucent) main window paintEvent
        # and the visible content, eating the alpha. Mirrors the
        # autoFillBackground+WA_TranslucentBackground pattern Pepper uses
        # on the QGraphicsView viewport.
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WA_TranslucentBackground, True)

        self._container = QWidget()
        self._container.setAutoFillBackground(False)
        self._container.setAttribute(Qt.WA_TranslucentBackground, True)
        self._layout = QBoxLayout(QBoxLayout.TopToBottom, self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.setWidget(self._container)

        self._source: PageSource | None = None
        self._labels: list[QLabel] = []
        # Natural (pre-scale) size per page, filled in as pages decode.
        self._natural: list[QSize | None] = []
        # index -> scaled pixmap, most-recently-used last.
        self._cache: "OrderedDict[int, QPixmap]" = OrderedDict()
        # Estimated on-screen size for pages that haven't decoded yet,
        # and the value last written across every label.
        self._placeholder = QSize(0, 0)
        self._placeholder_applied = QSize(-1, -1)
        self._last_error: str | None = None

        self._orientation: str = "vertical"
        self._fit_mode: str = "horizontal"
        self._scroll_mode: str = "continuous"
        self._page_gap: int = 8
        self._current_page: int = 0
        # Set while we move the view ourselves, so scrollContentsBy doesn't
        # decode pages at the intermediate positions or re-derive the page.
        self._repositioning: bool = False

        self._rescale_timer = QTimer(self)
        self._rescale_timer.setSingleShot(True)
        self._rescale_timer.setInterval(_RESCALE_DEBOUNCE_MS)
        self._rescale_timer.timeout.connect(self._invalidate_and_refresh)

    # -- Public state setters --------------------------------------------

    def set_background_color(self, color: QColor) -> None:
        """Paint the area between labels with `color` (alpha respected).

        At opacity = 1.0 the alpha will be 255 and the viewport paints
        solidly. At opacity < 1.0 the alpha is fractional; combined with
        the viewport's WA_TranslucentBackground attribute the desktop
        shows through proportionally.

        Note: MainWindow's paintEvent ALSO paints the bg color, but only
        in the chrome region outside the scroll area (around the status
        bar). Inside the scroll area the viewport's stylesheet is what
        controls the look.
        """
        # We paint via stylesheet so the alpha channel survives even when
        # the viewport has WA_TranslucentBackground set.
        if color.alpha() <= 0:
            # Fully transparent → let the MainWindow's paintEvent show through.
            self.viewport().setStyleSheet("")
            return
        self.viewport().setStyleSheet(
            f"background-color: rgba({color.red()}, {color.green()}, "
            f"{color.blue()}, {color.alpha()});"
        )

    def set_orientation(self, orientation: str) -> None:
        if orientation not in VALID_ORIENTATIONS or orientation == self._orientation:
            return
        self._orientation = orientation
        self._apply_layout_direction()
        self._reflow()

    def set_fit_mode(self, mode: str) -> None:
        if mode not in VALID_FITS or mode == self._fit_mode:
            return
        self._fit_mode = mode
        self._invalidate_and_refresh()

    def set_scroll_mode(self, mode: str) -> None:
        if mode not in VALID_SCROLL_MODES or mode == self._scroll_mode:
            return
        self._scroll_mode = mode
        self._rebuild_layout()
        self._reflow()

    def set_page_gap(self, gap: int) -> None:
        gap = max(0, int(gap))
        self._page_gap = gap
        self._layout.setSpacing(gap)

    # -- State readers ---------------------------------------------------

    def orientation(self) -> str:
        return self._orientation

    def fit_mode(self) -> str:
        return self._fit_mode

    def scroll_mode(self) -> str:
        return self._scroll_mode

    def page_gap(self) -> int:
        return self._page_gap

    def page_count(self) -> int:
        return len(self._labels)

    def current_page(self) -> int:
        return self._current_page

    def source_name(self) -> str:
        """The open set's name: the archive, or the folder of pages."""
        return self._source.display if self._source is not None else ""

    def last_error(self) -> str | None:
        """Why the most recent load_source() returned False, if it did."""
        return self._last_error

    # -- Loading ---------------------------------------------------------

    def load_source(self, source: str) -> bool:
        self._last_error = None
        try:
            src = open_page_source(source)
        except FileNotFoundError:
            log.warning("comic source not found: %s", source)
            self._last_error = "That file or folder no longer exists"
            return False
        except UnsupportedArchive as e:
            log.warning("couldn't open %s: %s", source, e)
            self._last_error = str(e)
            return False
        except OSError as e:
            log.warning("couldn't open %s: %s", source, e)
            self._last_error = f"Couldn't open it — {e}"
            return False

        if len(src) == 0:
            src.close()
            log.warning("no readable images in %s", source)
            self._last_error = "No readable images in there"
            return False

        # Probe the page we open at (the first, or the image Salt was
        # pointed at): it both proves the set is decodable and gives us the
        # aspect ratio every placeholder is sized from.
        start = src.start
        probe = self._decode_natural(src, start)
        if probe is None:
            src.close()
            log.warning("page %d of %s wouldn't decode", start + 1, source)
            if src.start_name:
                self._last_error = f"{src.start_name} isn't an image Qt can decode"
            else:
                self._last_error = "Those pages aren't in a format Qt can decode"
            return False

        self._clear_layout()
        for old in self._labels:
            old.setParent(None)
        if self._source is not None:
            self._source.close()

        self._source = src
        self._cache.clear()
        self._natural = [None] * len(src)
        self._natural[start] = probe.size()
        self._current_page = start

        self._labels = []
        for _ in range(len(src)):
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            self._labels.append(label)

        self._rebuild_layout()
        self._refresh(force=True)
        # Start at the top, not at whatever offset the last source was
        # scrolled to. This also emits page_changed.
        self._apply_current_page()

        self.source_loaded.emit(len(self._labels), source)
        return True

    # -- Decoding / cache ------------------------------------------------

    def _decode_natural(self, src: PageSource, index: int) -> QPixmap | None:
        """Full-resolution pixmap for one page, or None if undecodable."""
        data = src.read(index)
        if not data:
            return None
        pix = QPixmap()
        if not pix.loadFromData(data):
            log.info("skipping undecodable %s", src.names[index])
            return None
        return pix

    def _ensure_cached(self, indices: list[int]) -> None:
        """Decode and scale any of `indices` not already cached."""
        if self._source is None:
            return
        # Hard ceiling on one round of decoding. Even if a degenerate
        # layout claims everything is visible, we never pull more than a
        # cache-full of pages off disk in one go.
        missing = [i for i in indices if i not in self._cache][:_CACHE_PAGES]
        if not missing:
            return

        vw, vh = self._viewport_size()
        # One backend round-trip for the whole window — matters for the
        # RAR source, where each call is a subprocess.
        blobs = self._source.read_many(missing)
        for i in missing:
            data = blobs.get(i)
            if not data:
                continue
            pix = QPixmap()
            if not pix.loadFromData(data):
                log.info("skipping undecodable %s", self._source.names[i])
                continue
            self._natural[i] = pix.size()
            # The full-resolution pixmap goes out of scope here; only the
            # scaled copy is retained. That is the whole memory story.
            self._cache[i] = self._scale_pixmap(pix, vw, vh)

        self._evict()

    def _evict(self) -> None:
        while len(self._cache) > _CACHE_PAGES:
            index, _ = self._cache.popitem(last=False)
            if 0 <= index < len(self._labels):
                self._labels[index].clear()
                self._apply_placeholder(index)

    def _touch(self, index: int) -> None:
        if index in self._cache:
            self._cache.move_to_end(index)

    # -- Sizing ----------------------------------------------------------

    def _viewport_size(self) -> tuple[int, int]:
        vp = self.viewport()
        vw, vh = vp.width(), vp.height()
        # Before the first show there is no useful geometry; fall back to
        # the widget's own size so scaling maths stay sane in tests.
        if vw <= 0:
            vw = max(1, self.width())
        if vh <= 0:
            vh = max(1, self.height())
        return vw, vh

    def _scale_pixmap(self, pix: QPixmap, vw: int, vh: int) -> QPixmap:
        iw = pix.width()
        ih = pix.height()
        if iw <= 0 or ih <= 0 or vw <= 0 or vh <= 0:
            return pix
        if self._fit_mode == "none":
            # Native pixel size — no scaling. Scrollbars handle overflow.
            return pix
        if self._fit_mode == "horizontal":
            new_w = vw
            new_h = max(1, int(ih * vw / iw))
        elif self._fit_mode == "vertical":
            new_h = vh
            new_w = max(1, int(iw * vh / ih))
        else:  # "both"
            scale = min(vw / iw, vh / ih)
            new_w = max(1, int(iw * scale))
            new_h = max(1, int(ih * scale))
        return pix.scaled(
            new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

    def _recompute_placeholder(self) -> None:
        """Size undecoded pages from whatever natural size we've seen.

        Every page in a comic is near enough the same shape, so one known
        page is a good enough stand-in to keep the scrollbar proportional.
        """
        known = next((s for s in self._natural if s is not None), None)
        if known is None or known.width() <= 0 or known.height() <= 0:
            self._placeholder = QSize(0, 0)
            return
        if self._fit_mode == "none":
            self._placeholder = known
            return
        vw, vh = self._viewport_size()
        iw, ih = known.width(), known.height()
        if self._fit_mode == "horizontal":
            self._placeholder = QSize(vw, max(1, int(ih * vw / iw)))
        elif self._fit_mode == "vertical":
            self._placeholder = QSize(max(1, int(iw * vh / ih)), vh)
        else:
            scale = min(vw / iw, vh / ih)
            self._placeholder = QSize(max(1, int(iw * scale)),
                                      max(1, int(ih * scale)))

    def _apply_placeholder(self, index: int) -> bool:
        """Size an undecoded label. Returns True if the size changed.

        setFixedSize invalidates the layout even when the size is
        identical, and this runs across every page on a hot path, so the
        comparison is what keeps scrolling cheap.
        """
        if self._placeholder.isEmpty():
            return False
        label = self._labels[index]
        if label.size() == self._placeholder:
            return False
        label.setFixedSize(self._placeholder)
        return True

    # -- Visible range ---------------------------------------------------

    def _visible_indices(self) -> list[int]:
        """Page indices intersecting the viewport, plus the lookahead."""
        n = len(self._labels)
        if n == 0:
            return []
        if self._scroll_mode == "page":
            return [self._current_page]

        vw, vh = self._viewport_size()
        start = self._scroll_bar().value()
        extent = vw if self._orientation == "horizontal" else vh

        first = last = None
        for i in range(n):
            lo, length = self._page_span(i)
            hi = lo + length
            if hi <= start or lo >= start + extent:
                continue
            if first is None:
                first = i
            last = i

        if first is None:
            # No usable geometry yet (nothing shown, or a fresh load) —
            # anchor the window on the current page instead.
            first = last = min(self._current_page, n - 1)

        lo = max(0, first - _LOOKBEHIND)
        hi = min(n - 1, last + _LOOKAHEAD)

        # Never claim more pages than the cache can hold. Before the first
        # real layout every label sits at the same coordinate, so the scan
        # above reports the whole archive as visible; without this clamp we
        # would decode a cache-full, evict it, and do it again on every
        # scroll — thrashing forever and decoding nothing usefully.
        if hi - lo + 1 > _CACHE_PAGES:
            anchor = min(max(self._current_page, lo), hi)
            lo = max(lo, anchor - _LOOKBEHIND)
            hi = min(hi, lo + _CACHE_PAGES - 1)
        return list(range(lo, hi + 1))

    def _refresh(self, *, force: bool = False) -> None:
        """Decode the pages near the viewport and show them."""
        if self._source is None or not self._labels:
            return
        self._apply_placeholders(force=force)

        wanted = self._visible_indices()
        # Promote the pages we're about to show *before* decoding new
        # ones, so a page that is still on screen can't be the LRU victim
        # of the very decode that was meant to fill in around it.
        for i in wanted:
            self._touch(i)
        self._ensure_cached(wanted)
        for i in wanted:
            pix = self._cache.get(i)
            if pix is not None:
                self._labels[i].setFixedSize(pix.size())
                self._labels[i].setPixmap(pix)

    def _apply_placeholders(self, *, force: bool = False) -> None:
        """Size every undecoded label from the current placeholder."""
        self._recompute_placeholder()

        # Give undecoded labels their placeholder geometry *before* asking
        # which ones are visible. Zero-sized labels all stack at the same
        # coordinate, so every page looks on-screen and the visibility
        # query drags the entire archive into memory.
        #
        # Only worth walking every page when the placeholder itself moved
        # (load, fit change, resize). On a plain scroll nothing has
        # changed size, and eviction re-places its own labels.
        if force or self._placeholder != self._placeholder_applied:
            changed = False
            for i, label in enumerate(self._labels):
                if i in self._cache:
                    continue
                if force:
                    label.clear()
                changed |= self._apply_placeholder(i)
            self._placeholder_applied = self._placeholder
            if changed:
                self._layout.activate()

    def _reflow(self) -> None:
        """Rescale for a new orientation or scroll mode, from the current
        page's start."""
        self._cache.clear()
        self._apply_placeholders(force=True)
        self._apply_current_page()

    def _invalidate_and_refresh(self) -> None:
        """Rescale for a new size or fit, keeping the reader's place.

        Every page changes size, so the old scroll offset would land on a
        different page — toggling fullscreen used to jump several pages.
        """
        page, fraction = self._reading_position()
        self._cache.clear()
        self._repositioning = True
        try:
            self._apply_placeholders(force=True)
            self._settle_layout()
            if self._labels and self._scroll_mode == "page":
                bar = self.verticalScrollBar()
                bar.setValue(round(fraction * bar.maximum()))
            elif self._labels:
                start, extent = self._page_span(page)
                self._scroll_bar().setValue(start + round(fraction * extent))
        finally:
            self._repositioning = False
        self._refresh()

    def _reading_position(self) -> tuple[int, float]:
        """The current page, and how far into it the view is (0..1)."""
        page = self._current_page
        if not self._labels:
            return page, 0.0
        if self._scroll_mode == "page":
            bar = self.verticalScrollBar()
            return page, bar.value() / bar.maximum() if bar.maximum() > 0 else 0.0
        start, extent = self._page_span(page)
        if extent <= 0:
            return page, 0.0
        offset = (self._scroll_bar().value() - start) / extent
        return page, min(max(offset, 0.0), 1.0)

    def _settle_layout(self) -> None:
        """Run pending layout work now.

        Page positions and scrollbar ranges only catch up when the posted
        LayoutRequest is processed, and scrolling to a page before then
        clamps to the old range. Settling can also bring in or take away
        a scrollbar, which changes the width pages scale to, so undecoded
        pages are sized again for it; otherwise they shrink or grow as
        they decode and the page scrolled to drifts.
        """
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        if self._labels:
            self._apply_placeholders()
            QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    # -- Positions along the reading axis --------------------------------

    def _scroll_bar(self) -> QScrollBar:
        """The scrollbar that runs along the reading direction."""
        if self._orientation == "horizontal":
            return self.horizontalScrollBar()
        return self.verticalScrollBar()

    def _page_span(self, index: int) -> tuple[int, int]:
        """Where a page starts along the reading axis, and its length."""
        geo = self._labels[index].geometry()
        if self._orientation == "horizontal":
            return geo.x(), geo.width()
        return geo.y(), geo.height()

    def _sync_current_page(self) -> None:
        """Continuous mode: make the page at the top of the view current.

        PgDown, PgUp and the page counter all work from the current page,
        so it has to follow the wheel and the scrollbar too, not just the
        paging keys.
        """
        bar = self._scroll_bar()
        pos = bar.value()
        if bar.maximum() > 0 and pos >= bar.maximum():
            # At the very end the last page may be too short to reach the
            # top of the view, but it is the one being read.
            current = len(self._labels) - 1
        else:
            current = None
            for i in range(len(self._labels)):
                start, extent = self._page_span(i)
                if start > pos:
                    break
                # Zero-length labels haven't been laid out yet.
                if extent > 0:
                    current = i
            if current is None:
                return
        if current != self._current_page:
            self._current_page = current
            self.page_changed.emit(current + 1, len(self._labels))

    # -- Page navigation -------------------------------------------------

    def next_page(self) -> None:
        if not self._labels:
            return
        if self._current_page + 1 >= len(self._labels):
            return
        self._current_page += 1
        self._apply_current_page()

    def prev_page(self) -> None:
        if not self._labels:
            return
        if self._scroll_mode == "continuous":
            # Partway down a page, "previous" first means this page's top.
            start, _ = self._page_span(self._current_page)
            if self._scroll_bar().value() > start:
                self._apply_current_page()
                return
        if self._current_page <= 0:
            return
        self._current_page -= 1
        self._apply_current_page()

    def _turn_back(self) -> None:
        """Page mode: the previous page, shown from its bottom, for
        reading upwards with the wheel or the Up key."""
        if self._current_page <= 0:
            return
        self._current_page -= 1
        self._apply_current_page(at_end=True)

    def _apply_current_page(self, *, at_end: bool = False) -> None:
        """Show the current page from its start (or, in page mode, its end).

        Continuous mode lines the page's start up with the top of the
        view. It used ensureWidgetVisible(), which centres anything taller
        than the view, so PgDown skipped the top of every fit-to-width page.
        """
        if not self._labels:
            return
        self._repositioning = True
        try:
            if self._scroll_mode == "page":
                self._rebuild_layout()
                self._refresh()
                self._settle_layout()
                self.horizontalScrollBar().setValue(0)
                bar = self.verticalScrollBar()
                bar.setValue(bar.maximum() if at_end else 0)
            else:
                self._settle_layout()
                start, _ = self._page_span(self._current_page)
                self._scroll_bar().setValue(start)
        finally:
            self._repositioning = False
        self._refresh()
        self.page_changed.emit(self._current_page + 1, len(self._labels))

    # -- Layout internals ------------------------------------------------

    def _clear_layout(self) -> None:
        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _apply_layout_direction(self) -> None:
        if self._orientation == "horizontal":
            self._layout.setDirection(QBoxLayout.LeftToRight)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self._layout.setDirection(QBoxLayout.TopToBottom)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _rebuild_layout(self) -> None:
        self._clear_layout()
        self._apply_layout_direction()
        self._layout.setSpacing(self._page_gap)
        if self._scroll_mode == "page":
            shown = self._labels[self._current_page:self._current_page + 1]
        else:
            shown = self._labels
        for label in shown:
            self._layout.addWidget(label, 0, Qt.AlignCenter)
            # addWidget() only queues the show of a reparented widget, and
            # a hidden label takes no space, so page positions and the
            # scroll range would lag behind the page we scroll to next.
            label.show()
        self._layout.addStretch(1)

    # -- Events ----------------------------------------------------------

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if self._source is not None and not self._repositioning:
            self._refresh()
            if self._scroll_mode == "continuous":
                self._sync_current_page()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._labels:
            # Rescaling is expensive; wait for the drag to settle.
            self._rescale_timer.start()

    def wheelEvent(self, ev) -> None:
        # Page mode: the wheel scrolls through a page taller than the view
        # and turns the page only at its bottom or top. Turning on every
        # notch left the rest of a fit-to-width page out of reach.
        if self._scroll_mode == "page" and self._labels:
            dy = ev.angleDelta().y()
            bar = self.verticalScrollBar()
            if dy < 0 and bar.value() >= bar.maximum():
                self.next_page()
                ev.accept()
                return
            if dy > 0 and bar.value() <= bar.minimum():
                self._turn_back()
                ev.accept()
                return
        super().wheelEvent(ev)

    def keyPressEvent(self, ev) -> None:
        # Page-mode keys (in addition to whatever MainWindow wires). Down
        # and Up scroll like the wheel, turning only at the page's edges;
        # the rest turn the page straight away.
        if self._scroll_mode == "page":
            key = ev.key()
            bar = self.verticalScrollBar()
            if key == Qt.Key_Down and bar.value() < bar.maximum():
                super().keyPressEvent(ev)
                return
            if key == Qt.Key_Up and bar.value() > bar.minimum():
                super().keyPressEvent(ev)
                return
            if key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space):
                self.next_page()
                ev.accept()
                return
            if key == Qt.Key_Up:
                self._turn_back()
                ev.accept()
                return
            if key in (Qt.Key_Left, Qt.Key_PageUp, Qt.Key_Backspace):
                self.prev_page()
                ev.accept()
                return
        super().keyPressEvent(ev)
