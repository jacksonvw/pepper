"""Tests for salt.core.archive — directory / zip / tar handling."""

from __future__ import annotations

import pytest

from salt.core.archive import open_page_source, open_source


def test_open_directory(comic_dir):
    entries = open_source(comic_dir)
    # 3 PNGs, decoy .txt excluded.
    assert len(entries) == 3
    names = [e.name for e in entries]
    # Natural sort: page1, page2, page10.
    assert names == ["page1.png", "page2.png", "page10.png"]


def test_open_zip(comic_zip):
    entries = open_source(comic_zip)
    assert len(entries) == 3
    assert [e.name for e in entries] == ["page1.png", "page2.png", "page10.png"]


def test_open_tar(comic_tar):
    entries = open_source(comic_tar)
    assert len(entries) == 3
    assert [e.name for e in entries] == ["page1.png", "page2.png", "page10.png"]


def test_open_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_source(tmp_path / "nope.cbz")


def test_open_image_uses_containing_directory(comic_dir):
    """Pointing Salt at a single image inside a folder should open the folder."""
    target = comic_dir / "page2.png"
    entries = open_source(target)
    # We get the whole directory, not just one image.
    assert len(entries) == 3


def test_image_entries_have_bytes(comic_dir):
    entries = open_source(comic_dir)
    for e in entries:
        assert isinstance(e.data, bytes)
        assert len(e.data) > 0


def test_open_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert open_source(empty) == []


def test_mac_resource_forks_are_not_pages(tmp_path, sample_image_bytes):
    """A zip made on a Mac: AppleDouble entries sorted first and broke it."""
    import zipfile
    z = tmp_path / "from-a-mac.cbz"
    with zipfile.ZipFile(z, "w") as zf:
        for i in (1, 2):
            zf.writestr(f"page{i}.png", sample_image_bytes)
            zf.writestr(f"__MACOSX/._page{i}.png", b"\x00\x05\x16\x07 not an image")
    (tmp_path / "._stray.png").write_bytes(b"\x00\x05\x16\x07 not an image")
    assert [e.name for e in open_source(z)] == ["page1.png", "page2.png"]
    assert "._stray.png" not in open_page_source(tmp_path).names
