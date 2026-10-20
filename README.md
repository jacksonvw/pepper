# Pepper

Pepper, a single-image viewer, and Salt, a comic and image-set viewer: two
minimal-UI PySide6 apps for Fedora KDE Plasma, sharing one core,
`viewer_core`.

- **Pepper** opens one image and gets out of the way: no toolbar, no
  library, just the picture and a status bar you can hide.
- **Salt** opens a `.cbz`, `.cbr`, `.zip` or `.tar` archive, or a folder of
  images, and scrolls through it vertically or horizontally. Pages decode
  on demand, so memory stays flat however long the issue is.

Everything else lives in the right-click menu, including Preferences, where
either window can turn translucent with KWin's blur behind it.

## Setting up a new Fedora machine

Tested on Fedora 44 with KDE Plasma 6 on Wayland.

```bash
git clone https://github.com/jacksonvw/pepper.git
cd pepper

sudo dnf install -y \
    python3-pyside6 qt6-qtwayland qt6-qtsvg qt6-qtimageformats \
    kf6-kimageformats kf6-kwindowsystem unar python3-pytest

desktop/install.sh
```

Everything runs on the system Python against Fedora RPMs, deliberately with
no venv: PySide6 comes from the RPM built for `/usr/bin/python3`, which is
why the launchers pin it. That PySide6 also uses Plasma's own Qt, which is
what gives a native Wayland window, KDE theming and portal file dialogs; a
PyPI wheel bundles its own Qt and loses all three.

| Package | Provides |
|---|---|
| `qt6-qtwayland` | A native Wayland window rather than XWayland |
| `qt6-qtsvg`, `qt6-qtimageformats`, `kf6-kimageformats` | SVG, WebP, TIFF, AVIF, JPEG XL, PSD and other formats |
| `kf6-kwindowsystem` | KWin blur-behind; without it the blur is skipped |
| `unar` | Reading `.cbr` / RAR comics, from Fedora's own repos |
| `python3-pytest` | The test suite |

`desktop/install.sh` links `bin/pepper` and `bin/salt` into `~/bin`,
installs both desktop entries and icons, and makes Pepper the default for
PNG, JPEG, GIF, BMP, WebP, TIFF and SVG, and Salt the default for `.cbz`,
`.cbr` and tar, gzip, bzip2 and xz files. Plain `.zip` files and folders
keep their current handlers, with Salt offered under Open With. The script
needs no root and is safe to re-run, including after moving the checkout.
Logs go to `/tmp/pepper.log` and `/tmp/salt.log`.

Per-machine state stays out of the repo: settings live in
`~/.config/pepper/` and `~/.config/salt/`.

## Keys

| Key | Pepper | Salt |
|---|---|---|
| Ctrl+O | Open an image | Open an archive or image |
| Ctrl+Shift+O | | Open a folder |
| Ctrl+= / Ctrl+- | Zoom in / out (the wheel zooms too) | |
| Ctrl+0 | Actual size | |
| PgDown / PgUp | | Next / previous page |
| F11 | Toggle fullscreen | Toggle fullscreen |
| Esc | Leave fullscreen | Leave fullscreen |
| Ctrl+H | Hide or show the status bar | Hide or show the status bar |
| Ctrl+Q | Quit | Quit |

In Pepper, fit-to-window is in the right-click menu, and dragging pans a
zoomed-in image. In Salt, orientation, fit and scroll mode are in the
right-click menu; in page scroll mode the wheel and arrow keys turn pages.

## Tests

```bash
/usr/bin/python3 -m pytest
```

## License

MIT; see [LICENSE](LICENSE).
