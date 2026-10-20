"""Salt config — TOML-backed dataclass at ~/.config/salt/config.toml.

`[appearance]` is the shared `AppearanceConfig`, common to both apps.
`[comic]` is Salt-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from viewer_core.core.config import (
    AppearanceConfig,
    app_config_path,
    coerce_appearance,
    emit_appearance_lines,
    read_toml,
    write_toml,
)

VALID_ORIENTATIONS = ("vertical", "horizontal")
VALID_FITS = ("horizontal", "vertical", "both", "none")
VALID_SCROLL_MODES = ("continuous", "page")

# Page-gap is clamped to a sane range so the user can't make it
# unreasonable through the config file.
GAP_MIN = 0
GAP_MAX = 200


@dataclass
class AppConfig:
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    # Comic viewer behaviors.
    orientation: str = "vertical"     # "vertical" | "horizontal"
    fit_mode: str = "horizontal"      # "horizontal" | "vertical" | "both"
    scroll_mode: str = "continuous"   # "continuous" | "page"
    page_gap: int = 8                 # pixels between consecutive images


def _default_path() -> Path:
    return app_config_path("salt")


def _clamp_gap(v: int) -> int:
    return max(GAP_MIN, min(GAP_MAX, int(v)))


def load_config(path: Path | None = None) -> AppConfig:
    p = path or _default_path()
    data = read_toml(p)
    appearance = coerce_appearance(data.get("appearance", {}))
    comic = data.get("comic", {})

    orientation = str(comic.get("orientation", "vertical"))
    if orientation not in VALID_ORIENTATIONS:
        orientation = "vertical"
    fit_mode = str(comic.get("fit_mode", "horizontal"))
    if fit_mode not in VALID_FITS:
        fit_mode = "horizontal"
    scroll_mode = str(comic.get("scroll_mode", "continuous"))
    if scroll_mode not in VALID_SCROLL_MODES:
        scroll_mode = "continuous"
    try:
        gap = _clamp_gap(int(comic.get("page_gap", 8)))
    except (TypeError, ValueError):
        gap = 8

    return AppConfig(
        appearance=appearance,
        orientation=orientation,
        fit_mode=fit_mode,
        scroll_mode=scroll_mode,
        page_gap=gap,
    )


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    if cfg.orientation not in VALID_ORIENTATIONS:
        raise ValueError(f"invalid orientation: {cfg.orientation!r}")
    if cfg.fit_mode not in VALID_FITS:
        raise ValueError(f"invalid fit_mode: {cfg.fit_mode!r}")
    if cfg.scroll_mode not in VALID_SCROLL_MODES:
        raise ValueError(f"invalid scroll_mode: {cfg.scroll_mode!r}")
    p = path or _default_path()
    lines = ["[appearance]", *emit_appearance_lines(cfg.appearance), ""]
    lines.append("[comic]")
    lines.append(f'orientation = "{cfg.orientation}"')
    lines.append(f'fit_mode = "{cfg.fit_mode}"')
    lines.append(f'scroll_mode = "{cfg.scroll_mode}"')
    lines.append(f"page_gap = {_clamp_gap(cfg.page_gap)}")
    write_toml(p, "\n".join(lines) + "\n")
