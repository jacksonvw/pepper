"""Pepper config — TOML-backed dataclass at ~/.config/pepper/config.toml.

`[appearance]` is the shared `AppearanceConfig`, common to both apps.
`[image]` is Pepper-specific.
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

VALID_ZOOMS = ("fit", "shrink", "actual")


@dataclass
class AppConfig:
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    # Pepper-specific image behaviors.
    default_zoom: str = "fit"
    resize_window_to_image: bool = False


def _default_path() -> Path:
    return app_config_path("pepper")


def load_config(path: Path | None = None) -> AppConfig:
    p = path or _default_path()
    data = read_toml(p)
    appearance = coerce_appearance(data.get("appearance", {}))
    image = data.get("image", {})
    zoom = str(image.get("default_zoom", "fit"))
    if zoom not in VALID_ZOOMS:
        zoom = "fit"
    return AppConfig(
        appearance=appearance,
        default_zoom=zoom,
        resize_window_to_image=bool(image.get("resize_window_to_image", False)),
    )


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    if cfg.default_zoom not in VALID_ZOOMS:
        raise ValueError(f"invalid default_zoom: {cfg.default_zoom!r}")
    p = path or _default_path()
    lines = ["[appearance]", *emit_appearance_lines(cfg.appearance), ""]
    lines.append("[image]")
    lines.append(f'default_zoom = "{cfg.default_zoom}"')
    lines.append(
        f"resize_window_to_image = {'true' if cfg.resize_window_to_image else 'false'}"
    )
    write_toml(p, "\n".join(lines) + "\n")
