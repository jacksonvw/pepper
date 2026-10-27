#!/bin/bash
# Install Pepper + Salt desktop integration into the user's home directory:
#   - pepper and salt launchers on PATH, symlinked to this checkout's bin/
#   - both .desktop entries and their icons
#   - Pepper as the default for common image types, Salt for comic
#     archives and tarballs
#
# Files land in:
#   ~/bin/pepper, ~/bin/salt                             (symlinks)
#   ~/.local/share/applications/{pepper,salt}.desktop
#   ~/.local/share/icons/hicolor/scalable/apps/{pepper,salt}.svg
#   ~/.config/mimeapps.list                              (default-application entries)
#
# With --flatpak, the Pepper and Salt Flatpaks bring their own launchers,
# entries and icons, so this only makes them the defaults, for the same types.
#
# Run from anywhere — paths resolve relative to the suite root. Safe to
# re-run; re-run it after moving the checkout. Installs no packages —
# README.md has the dnf line.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BIN_DIR="${HOME}/bin"
APPS_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons/hicolor/scalable/apps"

# Defaults are set for these types only. Salt's entry also lists
# application/zip and inode/directory so it appears under Open With, but
# .zip files stay with the archive manager and folders with the file manager.
PEPPER_TYPES=(image/png image/jpeg image/gif image/bmp image/webp image/tiff image/svg+xml)
SALT_TYPES=(
    application/x-cbz application/vnd.comicbook+zip
    application/x-cbr application/vnd.comicbook-rar
    application/x-tar application/gzip application/x-bzip2 application/x-xz
)

if [[ "${1:-}" == "--flatpak" ]]; then
    PEPPER_ENTRY=com.jacksonv.Pepper.desktop
    SALT_ENTRY=com.jacksonv.Salt.desktop
    for id in com.jacksonv.Pepper com.jacksonv.Salt; do
        if ! flatpak info "${id}" >/dev/null 2>&1; then
            echo "The ${id} Flatpak isn't installed; README.md has the build line." >&2
            exit 1
        fi
    done
else
    PEPPER_ENTRY=pepper.desktop
    SALT_ENTRY=salt.desktop

    mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICON_DIR}"

    for app in pepper salt; do
        # --- Launcher: a symlink, so it always runs this checkout ---
        if [[ -e "${BIN_DIR}/${app}" && ! -L "${BIN_DIR}/${app}" ]]; then
            echo "${BIN_DIR}/${app} exists and isn't a symlink; move it aside and re-run." >&2
            exit 1
        fi
        ln -sfn "${PROJECT_ROOT}/bin/${app}" "${BIN_DIR}/${app}"
        echo "Linked launcher: ${BIN_DIR}/${app}"

        # --- Icon (the entry says Icon=${app}) ---
        cp "${PROJECT_ROOT}/${app}/resources/${app}.svg" "${ICON_DIR}/${app}.svg"
        echo "Wrote icon: ${ICON_DIR}/${app}.svg"

        # --- .desktop entry: substitute the absolute project root into Exec ---
        sed "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" "${SCRIPT_DIR}/${app}.desktop.in" \
            > "${APPS_DIR}/${app}.desktop"
        echo "Wrote desktop entry: ${APPS_DIR}/${app}.desktop"
    done

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${APPS_DIR}"
        echo "Refreshed desktop database"
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -t -f "${DATA_HOME}/icons/hicolor" 2>/dev/null || true
    fi
fi

# --- Default applications ---
# gio rather than xdg-mime: under KDE 6, xdg-utils 1.2.1 shells out to an
# unversioned `qtpaths` that Fedora doesn't ship, errors once per type, and
# still exits 0 when it fails to write mimeapps.list. A re-run may prune the
# redundant [Added Associations] lines; [Default Applications] is what decides.
for type in "${PEPPER_TYPES[@]}"; do
    gio mime "${type}" "${PEPPER_ENTRY}" >/dev/null
done
for type in "${SALT_TYPES[@]}"; do
    gio mime "${type}" "${SALT_ENTRY}" >/dev/null
done
echo "Set Pepper as the default for ${#PEPPER_TYPES[@]} MIME types and Salt for ${#SALT_TYPES[@]}"

# KDE caches associations in sycoca; rebuild it, as xdg-mime does.
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 >/dev/null 2>&1 || true
fi

if [[ "${PEPPER_ENTRY}" == pepper.desktop ]]; then
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) echo "Note: ${BIN_DIR} isn't on PATH, so the pepper and salt commands won't resolve (the desktop entries don't need it)." ;;
    esac
fi

echo
echo "Done. Open an image to view it in Pepper, or a .cbz/.cbr to read it in Salt."
