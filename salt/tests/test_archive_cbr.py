"""Tests for the CBR/RAR backend, content sniffing, and the lazy PageSource.

The RAR path shells out to `unar`, and no free tool can *create* a RAR,
so the backend's plumbing is exercised against a stubbed subprocess
rather than a real archive. The parts that can be tested for real —
sniffing, the incomplete-download guard, lazy reads — are.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from salt.core import archive
from salt.core.archive import (
    UnsupportedArchive,
    open_page_source,
    open_source,
)


# -- Content sniffing -----------------------------------------------------

def test_zip_named_cbr_still_opens(misnamed_cbr):
    """Dispatch is by magic bytes, not by extension."""
    entries = open_source(misnamed_cbr)
    assert len(entries) == 3


def test_sniff_identifies_formats(comic_zip, comic_tar, misnamed_cbr):
    assert archive._sniff(comic_zip) == "zip"
    assert archive._sniff(comic_tar) == "tar"
    assert archive._sniff(misnamed_cbr) == "zip"


def test_sniff_rar_signature(tmp_path):
    rar4 = tmp_path / "a.cbr"
    rar4.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 32)
    assert archive._sniff(rar4) == "rar"
    rar5 = tmp_path / "b.cbr"
    rar5.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 32)
    assert archive._sniff(rar5) == "rar"


def test_unknown_format_raises_with_reason(tmp_path):
    junk = tmp_path / "notacomic.cbz"
    junk.write_bytes(b"this is not an archive")
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(junk)
    assert "notacomic.cbz" in str(exc.value)


def test_reasons_read_as_sentences(tmp_path):
    """They're shown verbatim in Salt's error overlay."""
    broken = tmp_path / "broken.cbz"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(broken)
    assert str(exc.value).startswith("Couldn't open broken.cbz")


# -- Incomplete downloads -------------------------------------------------

def test_sparse_file_reported_as_incomplete(sparse_archive):
    """A part-downloaded archive fails fast instead of hanging in lsar."""
    if archive._hole_offset(sparse_archive) is None:
        pytest.skip("filesystem doesn't report holes")
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(sparse_archive)
    assert "incomplete download" in str(exc.value)


def test_complete_file_is_not_flagged(comic_zip):
    assert archive._hole_offset(comic_zip) is None
    # And it opens normally.
    assert len(open_source(comic_zip)) == 3


# -- unar availability ----------------------------------------------------

def test_missing_unar_explains_how_to_install(tmp_path, monkeypatch):
    rar = tmp_path / "x.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    monkeypatch.setattr(archive.shutil, "which", lambda name: None)
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(rar)
    assert "unar" in str(exc.value)
    assert "dnf install" in str(exc.value)


def _fake_lsar(names):
    payload = json.dumps(
        {"lsarFormatVersion": 2,
         "lsarContents": [{"XADFileName": n} for n in names]}
    ).encode()
    return subprocess.CompletedProcess([], 0, stdout=payload, stderr=b"")


def test_rar_listing_sorts_and_filters(tmp_path, monkeypatch):
    rar = tmp_path / "x.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    monkeypatch.setattr(archive.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        archive.subprocess, "run",
        lambda *a, **k: _fake_lsar(
            ["page10.png", "page1.png", "notes.txt", "page2.png"]
        ),
    )
    src = open_page_source(rar)
    # Non-images dropped, natural sort applied.
    assert src.names == ["page1.png", "page2.png", "page10.png"]


def test_rar_listing_failure_surfaces_stderr(tmp_path, monkeypatch):
    rar = tmp_path / "x.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    monkeypatch.setattr(archive.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        archive.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, stdout=b"", stderr=b"Couldn't recognize the archive format."
        ),
    )
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(rar)
    assert "recognize" in str(exc.value)


def test_rar_listing_timeout_is_not_fatal_to_the_process(tmp_path, monkeypatch):
    rar = tmp_path / "x.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    monkeypatch.setattr(archive.shutil, "which", lambda name: f"/usr/bin/{name}")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="lsar", timeout=1)

    monkeypatch.setattr(archive.subprocess, "run", boom)
    with pytest.raises(UnsupportedArchive) as exc:
        open_page_source(rar)
    assert "timed out" in str(exc.value)


def test_rar_read_uses_one_subprocess_for_the_whole_window(
    tmp_path, monkeypatch, sample_image_bytes
):
    """read_many batches — it matters, each call is a process spawn."""
    rar = tmp_path / "x.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 64)
    monkeypatch.setattr(archive.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_run(cmd, **kwargs):
        if cmd[0] == "lsar":
            return _fake_lsar(["p1.png", "p2.png", "p3.png"])
        calls.append(cmd)
        # Emulate unar writing the requested members into -o <dir>.
        dest = cmd[cmd.index("-o") + 1]
        for member in cmd[cmd.index(str(rar)) + 1:]:
            with open(os.path.join(dest, member), "wb") as fh:
                fh.write(sample_image_bytes)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(archive.subprocess, "run", fake_run)

    src = open_page_source(rar)
    got = src.read_many([0, 1, 2])
    assert set(got) == {0, 1, 2}
    assert all(v == sample_image_bytes for v in got.values())
    assert len(calls) == 1, "three pages should cost one unar invocation"
    src.close()


# -- Lazy PageSource contract --------------------------------------------

def test_page_source_lists_without_reading(comic_zip):
    src = open_page_source(comic_zip)
    assert len(src) == 3
    assert src.names == ["page1.png", "page2.png", "page10.png"]
    src.close()


def test_page_source_reads_on_demand(comic_zip, sample_image_bytes):
    with open_page_source(comic_zip) as src:
        assert src.read(0) == sample_image_bytes
        assert src.read(2) == sample_image_bytes


def test_page_source_out_of_range_is_none(comic_zip):
    with open_page_source(comic_zip) as src:
        assert src.read(99) is None
        assert src.read(-1) is None


def test_directory_source_is_lazy(comic_dir):
    with open_page_source(comic_dir) as src:
        assert src.names == ["page1.png", "page2.png", "page10.png"]
        assert isinstance(src.read(1), bytes)


def test_open_source_still_eager(comic_zip):
    """The eager wrapper keeps its old shape for callers that want it."""
    entries = open_source(comic_zip)
    assert [e.name for e in entries] == ["page1.png", "page2.png", "page10.png"]
    assert all(isinstance(e.data, bytes) and e.data for e in entries)
