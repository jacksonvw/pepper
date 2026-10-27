"""Shared config primitives for Pepper and Salt.

Defines `AppearanceConfig` — the bag of fields that drive the translucent
window, KWin blur, bg color and tint — and small coerce/emit helpers used
by each app's own config module. Each app (pepper, salt) owns its own
`AppConfig` dataclass that composes an `AppearanceConfig` plus its own
app-specific fields.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppearanceConfig:
    """The [appearance] TOML section, shared by both apps."""
    window_opacity: float = 1.0
    blur_behind: bool = True
    bg_color: list[int] = field(default_factory=lambda: [0, 0, 0])
    bg_tint_strength: int = 70


def _clamp_unit(v: float) -> float:
    return max(0.0, min(1.0, v))


def _clamp_byte(v: int) -> int:
    return max(0, min(255, int(v)))


def _clamp_pct(v: int) -> int:
    return max(0, min(100, int(v)))


def _coerce_color(raw) -> list[int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return [0, 0, 0]
    try:
        return [_clamp_byte(int(c)) for c in raw]
    except (TypeError, ValueError):
        return [0, 0, 0]


def coerce_appearance(section: dict) -> AppearanceConfig:
    """Build an AppearanceConfig from a raw TOML [appearance] table."""
    try:
        opacity = float(section.get("window_opacity", 1.0))
    except (TypeError, ValueError):
        opacity = 1.0
    try:
        tint = int(section.get("bg_tint_strength", 70))
    except (TypeError, ValueError):
        tint = 70
    return AppearanceConfig(
        window_opacity=_clamp_unit(opacity),
        blur_behind=bool(section.get("blur_behind", True)),
        bg_color=_coerce_color(section.get("bg_color", [0, 0, 0])),
        bg_tint_strength=_clamp_pct(tint),
    )


def emit_appearance_lines(cfg: AppearanceConfig) -> list[str]:
    """Return the lines that go under [appearance] (no header)."""
    opacity = _clamp_unit(float(cfg.window_opacity))
    tint = _clamp_pct(int(cfg.bg_tint_strength))
    color = _coerce_color(cfg.bg_color)
    return [
        f"window_opacity = {opacity:.3f}",
        f"blur_behind = {'true' if cfg.blur_behind else 'false'}",
        f"bg_color = [{color[0]}, {color[1]}, {color[2]}]",
        f"bg_tint_strength = {tint}",
    ]


def app_config_path(app_name: str) -> Path:
    """`$XDG_CONFIG_HOME/<app_name>/config.toml`, `~/.config` by default.

    That is where QSettings already keeps the window geometry. Inside a
    Flatpak it is the app's own ~/.var/app/<id>/config, since the
    sandbox can't write to ~/.config.
    """
    base = os.environ.get("XDG_CONFIG_HOME", "")
    # The XDG spec says to ignore a relative path.
    root = Path(base) if os.path.isabs(base) else Path.home() / ".config"
    return root / app_name / "config.toml"


def write_toml(path: Path, body: str) -> None:
    """Round-trip a TOML body through tomllib (sanity check), then write."""
    tomllib.loads(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def read_toml(path: Path) -> dict:
    """Read a TOML file; return `{}` if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)
