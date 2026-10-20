"""Tests for pepper.core.config — defaults, round-trip, hand-rolled writer.

`[appearance]` is shared with Salt via viewer_core.core.config.
`[image]` is Pepper-specific.
"""

from __future__ import annotations

import tomllib

import pytest

from viewer_core.core.config import AppearanceConfig
from pepper.core.config import AppConfig, load_config, save_config


def test_defaults():
    cfg = AppConfig()
    assert cfg.appearance.window_opacity == 1.0
    assert cfg.appearance.blur_behind is True
    assert cfg.appearance.bg_color == [0, 0, 0]
    assert cfg.appearance.bg_tint_strength == 70
    assert cfg.default_zoom == "fit"
    assert cfg.resize_window_to_image is False


def test_load_missing_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "no-such-file.toml")
    assert cfg == AppConfig()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = AppConfig(
        appearance=AppearanceConfig(
            window_opacity=0.85, blur_behind=False,
            bg_color=[20, 40, 60], bg_tint_strength=50,
        ),
        default_zoom="shrink",
        resize_window_to_image=True,
    )
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.appearance.window_opacity == pytest.approx(0.85, abs=1e-3)
    assert loaded.appearance.blur_behind is False
    assert loaded.appearance.bg_color == [20, 40, 60]
    assert loaded.appearance.bg_tint_strength == 50
    assert loaded.default_zoom == "shrink"
    assert loaded.resize_window_to_image is True


def test_save_creates_parent_dir(tmp_path):
    target = tmp_path / "a" / "b" / "c.toml"
    save_config(AppConfig(), target)
    assert target.exists()


def test_load_partial_file(tmp_path):
    p = tmp_path / "partial.toml"
    p.write_text(
        "[appearance]\nwindow_opacity = 0.5\n", encoding="utf-8"
    )
    cfg = load_config(p)
    assert cfg.appearance.window_opacity == 0.5
    # Other fields fall back to defaults.
    assert cfg.appearance.blur_behind is True
    assert cfg.appearance.bg_color == [0, 0, 0]
    assert cfg.appearance.bg_tint_strength == 70


def test_save_output_is_valid_toml(tmp_path):
    p = tmp_path / "config.toml"
    cfg = AppConfig(
        appearance=AppearanceConfig(
            window_opacity=0.75, blur_behind=False,
            bg_color=[10, 20, 30], bg_tint_strength=40,
        ),
        default_zoom="actual",
        resize_window_to_image=True,
    )
    save_config(cfg, p)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    assert data == {
        "appearance": {
            "window_opacity": 0.75,
            "blur_behind": False,
            "bg_color": [10, 20, 30],
            "bg_tint_strength": 40,
        },
        "image": {
            "default_zoom": "actual",
            "resize_window_to_image": True,
        },
    }


def test_save_rejects_invalid_default_zoom(tmp_path):
    bad = AppConfig()
    bad.default_zoom = "huge"
    with pytest.raises(ValueError):
        save_config(bad, tmp_path / "out.toml")


def test_load_invalid_default_zoom_falls_back(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('[image]\ndefault_zoom = "huge"\n', encoding="utf-8")
    assert load_config(p).default_zoom == "fit"


def test_load_clamps_opacity_high(tmp_path):
    p = tmp_path / "clamp.toml"
    p.write_text("[appearance]\nwindow_opacity = 1.5\n", encoding="utf-8")
    assert load_config(p).appearance.window_opacity == 1.0


def test_load_clamps_opacity_low(tmp_path):
    p = tmp_path / "clamp.toml"
    p.write_text("[appearance]\nwindow_opacity = -0.2\n", encoding="utf-8")
    assert load_config(p).appearance.window_opacity == 0.0


def test_load_clamps_tint_strength(tmp_path):
    p = tmp_path / "clamp.toml"
    p.write_text("[appearance]\nbg_tint_strength = 250\n", encoding="utf-8")
    assert load_config(p).appearance.bg_tint_strength == 100


def test_load_invalid_bg_color_falls_back(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('[appearance]\nbg_color = "red"\n', encoding="utf-8")
    assert load_config(p).appearance.bg_color == [0, 0, 0]


def test_load_clamps_bg_color_components(tmp_path):
    p = tmp_path / "clamp.toml"
    p.write_text("[appearance]\nbg_color = [-5, 300, 128]\n", encoding="utf-8")
    assert load_config(p).appearance.bg_color == [0, 255, 128]
