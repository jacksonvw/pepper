"""Open a source path (directory, .zip/.cbz, .cbr/.rar, .tar/.tar.gz/...)
and yield the contained images in sorted order.

Public API:
    open_page_source(path) -> PageSource
        Lazy handle: page names up front, bytes only when asked for.
        This is what ComicView drives, so a 1 GB archive costs a member
        listing rather than a gigabyte of resident pixmaps.

    open_source(path) -> list[ImageEntry]
        Eager convenience wrapper — reads every page into memory. Fine
        for tests and small sets; ComicView deliberately does not use it.

Supported sources:
    - Directory             — non-recursive scan of immediate children
    - .zip / .cbz           — flat or nested; recursion is automatic
    - .cbr / .rar           — needs `unar` on PATH (see _RarSource)
    - .tar / .tar.gz / .tgz / .tar.bz2 / .tbz2 / .tar.xz / .txz

Dispatch sniffs magic bytes first and only falls back to the file
suffix. Misnamed comics are common in the wild — a .cbr that is really
a zip is routine — and extension-only dispatch got those wrong.

If a path is a regular image file (not an archive/dir), we open the
*containing directory* — same UX as Salt being pointed at a single page.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Conservative set — what QImageReader handles out of the box on most
# Qt builds. We don't enumerate `QImageReader.supportedImageFormats()`
# here so this module can be unit-tested without a QApplication.
_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
    ".tif", ".tiff", ".svg", ".ppm", ".xpm", ".pbm", ".pgm",
}

_TAR_SUFFIXES = (
    ".tar", ".tar.gz", ".tgz",
    ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz",
)

_ZIP_SUFFIXES = (".zip", ".cbz")
_RAR_SUFFIXES = (".cbr", ".rar")

# How long we give `lsar`/`unar` before assuming something is wedged.
# Listing is a header walk even on huge archives; extraction of a few
# stored members is milliseconds. Generous, but never infinite.
_UNAR_LIST_TIMEOUT = 60
_UNAR_READ_TIMEOUT = 120


class UnsupportedArchive(Exception):
    """Raised when a source can't be opened, with a user-facing reason.

    The message is shown verbatim in Salt's status bar, so it should
    read as an explanation, not a traceback.
    """


@dataclass(frozen=True)
class ImageEntry:
    name: str       # display name (basename within source)
    data: bytes     # raw image bytes


def _is_image(name: str) -> bool:
    n = name.lower()
    # Zips made on a Mac carry AppleDouble resource forks such as
    # "__MACOSX/._page01.jpg": image-named, but not images. They sorted
    # ahead of the real pages, failed the first-page probe, and got the
    # whole archive rejected.
    parts = n.replace("\\", "/").split("/")
    if "__macosx" in parts or parts[-1].startswith("._"):
        return False
    return any(n.endswith(s) for s in _IMAGE_SUFFIXES)


def _natural_key(name: str) -> tuple:
    """Sort 'page2' before 'page10' (numeric-aware)."""
    parts = re.split(r"(\d+)", name)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


# -- Integrity pre-check --------------------------------------------------

def _hole_offset(path: Path) -> int | None:
    """Offset of the first unallocated range in `path`, or None.

    A part-downloaded archive is typically sparse: the downloader
    preallocates the full length and fills it out of order, leaving holes.
    Handing one of those to `lsar` makes it grind through gigabytes of
    zeroes looking for headers, which reads to the user as a hang.

    SEEK_HOLE is the right question to ask here. Comparing st_blocks to
    st_size is not: on a compressing filesystem such as btrfs with
    compress=zstd, an allocated file legitimately occupies fewer blocks
    than its apparent size.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        size = os.fstat(fd).st_size
        if size <= 0:
            return None
        try:
            offset = os.lseek(fd, 0, os.SEEK_HOLE)
        except (OSError, AttributeError):
            # Filesystem doesn't report holes — no opinion.
            return None
        return offset if offset < size else None
    finally:
        os.close(fd)


def _check_complete(path: Path) -> None:
    """Raise UnsupportedArchive if `path` is a part-downloaded file."""
    hole = _hole_offset(path)
    if hole is None:
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    percent = 100.0 * hole / size if size else 0.0
    raise UnsupportedArchive(
        f"{path.name} looks like an incomplete download — only the first "
        f"{_human_bytes(hole)} of {_human_bytes(size)} ({percent:.1f}%) "
        f"is actually there"
    )


def _human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


# -- Format sniffing ------------------------------------------------------

def _sniff(path: Path) -> str:
    """Return "zip" | "rar" | "tar" | "" from the file's leading bytes."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return ""

    # Local file header, empty archive, or spanned marker.
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    # RAR4 is Rar!\x1a\x07\x00; RAR5 is Rar!\x1a\x07\x01\x00.
    if head[:7] in (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01"):
        return "rar"
    # tarfile handles the compressed variants too, so let it decide.
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, tarfile.TarError):
        pass
    return ""


def _suffix_kind(name: str) -> str:
    n = name.lower()
    if any(n.endswith(s) for s in _ZIP_SUFFIXES):
        return "zip"
    if any(n.endswith(s) for s in _RAR_SUFFIXES):
        return "rar"
    if any(n.endswith(s) for s in _TAR_SUFFIXES):
        return "tar"
    return ""


# -- Page sources ---------------------------------------------------------

class PageSource:
    """A opened image set: ordered page names plus on-demand byte reads.

    Subclasses implement `_read_one`; `read_many` exists so backends with
    per-call overhead (the RAR one spawns a process) can satisfy a whole
    prefetch window in a single shot.
    """

    def __init__(self, display: str, names: list[str]) -> None:
        self.display = display
        self.names = names

    def __len__(self) -> int:
        return len(self.names)

    def _read_one(self, index: int) -> bytes:
        raise NotImplementedError

    def read(self, index: int) -> bytes | None:
        """Bytes for one page, or None if that page can't be read."""
        if not 0 <= index < len(self.names):
            return None
        try:
            return self._read_one(index)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile,
                tarfile.TarError, subprocess.SubprocessError) as e:
            log.warning("couldn't read page %d (%s): %s",
                        index, self.names[index], e)
            return None

    def read_many(self, indices: list[int]) -> dict[int, bytes]:
        out: dict[int, bytes] = {}
        for i in indices:
            data = self.read(i)
            if data is not None:
                out[i] = data
        return out

    def close(self) -> None:
        pass

    def __enter__(self) -> PageSource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class _DirSource(PageSource):
    def __init__(self, root: Path) -> None:
        files = sorted(
            (c for c in root.iterdir() if c.is_file() and _is_image(c.name)),
            key=lambda c: _natural_key(c.name),
        )
        self._paths = files
        super().__init__(root.name or str(root), [c.name for c in files])

    def _read_one(self, index: int) -> bytes:
        return self._paths[index].read_bytes()


class _ZipSource(PageSource):
    def __init__(self, path: Path) -> None:
        self._zf = zipfile.ZipFile(path)
        infos = [
            i for i in self._zf.infolist()
            if not i.is_dir() and _is_image(i.filename)
        ]
        infos.sort(key=lambda i: _natural_key(i.filename))
        self._infos = infos
        super().__init__(path.name, [i.filename for i in infos])

    def _read_one(self, index: int) -> bytes:
        return self._zf.read(self._infos[index])

    def close(self) -> None:
        self._zf.close()


class _TarSource(PageSource):
    def __init__(self, path: Path) -> None:
        self._tf = tarfile.open(path, mode="r:*")
        members = [
            m for m in self._tf.getmembers()
            if m.isfile() and _is_image(m.name)
        ]
        members.sort(key=lambda m: _natural_key(m.name))
        self._members = members
        super().__init__(path.name, [m.name for m in members])

    def _read_one(self, index: int) -> bytes:
        fh = self._tf.extractfile(self._members[index])
        if fh is None:
            raise OSError("member is not a regular file")
        with fh:
            return fh.read()

    def close(self) -> None:
        self._tf.close()


class _RarSource(PageSource):
    """RAR/CBR via The Unarchiver's `lsar` + `unar`.

    RAR cannot be decoded with the stdlib, so this is the one backend
    that shells out. `unar` is preferred over `unrar` because Fedora
    ships it in the main repo under a free licence (unrar lives in
    rpmfusion-nonfree), and unlike Fedora's `7z` — which has the RAR
    codec stripped — it actually reads RAR5.

    Extraction is per-member rather than whole-archive: comic RARs are
    typically stored (uncompressed) and non-solid, so pulling three
    pages out of a 1 GB file costs milliseconds and no scratch space
    beyond those pages.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._tmp: tempfile.TemporaryDirectory | None = None
        names = _rar_list(path)
        images = sorted((n for n in names if _is_image(n)), key=_natural_key)
        super().__init__(path.name, images)

    def _scratch(self) -> Path:
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="salt-cbr-")
        return Path(self._tmp.name)

    def _read_one(self, index: int) -> bytes:
        got = self.read_many([index])
        if index not in got:
            raise OSError(f"unar did not produce {self.names[index]!r}")
        return got[index]

    def read_many(self, indices: list[int]) -> dict[int, bytes]:
        wanted = [i for i in indices if 0 <= i < len(self.names)]
        if not wanted:
            return {}

        # One process for the whole prefetch window, into a private dir
        # so we can identify what actually landed.
        dest = Path(tempfile.mkdtemp(dir=self._scratch()))
        try:
            cmd = [
                "unar",
                "-o", str(dest),
                "-D",            # don't create an enclosing archive-name dir
                "-f",            # overwrite
                "-q",            # quiet
                str(self._path),
            ] + [self.names[i] for i in wanted]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, timeout=_UNAR_READ_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                log.warning("unar timed out reading %s", self._path)
                return {}
            if proc.returncode != 0:
                log.warning(
                    "unar failed on %s: %s",
                    self._path, proc.stderr.decode("utf-8", "replace").strip(),
                )

            out: dict[int, bytes] = {}
            for i in wanted:
                # -D flattens the archive's own top directory but keeps
                # any interior structure, so try the full relative path
                # before falling back to the basename.
                member = self.names[i]
                for candidate in (dest / member, dest / Path(member).name):
                    if candidate.is_file():
                        try:
                            out[i] = candidate.read_bytes()
                        except OSError as e:
                            log.warning("couldn't read extracted %s: %s",
                                        candidate, e)
                        break
            return out
        finally:
            shutil.rmtree(dest, ignore_errors=True)

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


def _require_unar() -> None:
    if shutil.which("unar") is None or shutil.which("lsar") is None:
        raise UnsupportedArchive(
            "CBR/RAR support needs 'unar' — install it with: "
            "sudo dnf install unar"
        )


def _rar_list(path: Path) -> list[str]:
    """Member names inside a RAR, via `lsar -j`."""
    _require_unar()
    try:
        proc = subprocess.run(
            ["lsar", "-j", str(path)],
            capture_output=True, timeout=_UNAR_LIST_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise UnsupportedArchive(f"Listing {path.name} timed out") from e
    except OSError as e:
        raise UnsupportedArchive(f"Couldn't run lsar: {e}") from e

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise UnsupportedArchive(
            f"Couldn't read {path.name}"
            + (f" — {detail}" if detail else "")
        )

    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise UnsupportedArchive(
            f"Couldn't parse the archive listing for {path.name}"
        ) from e

    contents = payload.get("lsarContents") or []
    names: list[str] = []
    for item in contents:
        name = item.get("XADFileName")
        # Directory entries have no size and are skipped by the image
        # filter anyway, but drop anything nameless defensively.
        if isinstance(name, str) and name:
            names.append(name)
    return names


# -- Entry points ---------------------------------------------------------

def open_page_source(source: str | Path) -> PageSource:
    """Open `source` lazily.

    Raises FileNotFoundError if `source` doesn't exist, and
    UnsupportedArchive (with a human-readable reason) if it exists but
    can't be opened as an image set.
    """
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(str(p))

    if p.is_dir():
        return _DirSource(p)

    _check_complete(p)

    kind = _sniff(p) or _suffix_kind(p.name)

    try:
        if kind == "zip":
            return _ZipSource(p)
        if kind == "tar":
            return _TarSource(p)
        if kind == "rar":
            return _RarSource(p)
    except UnsupportedArchive:
        raise
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
        raise UnsupportedArchive(f"Couldn't open {p.name} — {e}") from e

    # A single image: open its containing directory so the rest of the
    # page set comes along.
    if p.is_file() and _is_image(p.name) and p.parent.is_dir():
        return _DirSource(p.parent)

    raise UnsupportedArchive(f"{p.name} isn't an image set Salt can open")


def open_source(source: str | Path) -> list[ImageEntry]:
    """Eagerly read every page. See open_page_source for the lazy form.

    Raises FileNotFoundError if `source` doesn't exist, and
    UnsupportedArchive if it can't be opened. Returns an empty list for
    a source that opens fine but holds no readable images.
    """
    with open_page_source(source) as src:
        entries: list[ImageEntry] = []
        for i, name in enumerate(src.names):
            data = src.read(i)
            if data is not None:
                entries.append(ImageEntry(name=name, data=data))
        return entries
