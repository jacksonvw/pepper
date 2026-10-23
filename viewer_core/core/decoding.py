"""Image decoding limits shared by Pepper and Salt."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader

# Qt refuses to decode any image that needs more than 256 MB, which turns
# away ordinary large photos and scans: 9000×9000 is ~324 MB once decoded.
# A gigabyte covers anything up to about 16000×16000 while still stopping
# a decompression bomb, a small file whose header claims a vast canvas,
# from taking the machine down with it.
DECODE_LIMIT_MB = 1024


def raise_decode_limit() -> None:
    """Lift Qt's image allocation limit to DECODE_LIMIT_MB, process-wide."""
    QImageReader.setAllocationLimit(DECODE_LIMIT_MB)


def too_large(size: QSize) -> bool:
    """Whether an image of `size` is over the current allocation limit.

    Qt reports that case only as "Unable to read image data", which reads
    like a corrupt file.
    """
    limit_mb = QImageReader.allocationLimit()
    if limit_mb <= 0 or not size.isValid():
        return False
    return size.width() * size.height() * 4 > limit_mb * 1024 * 1024
