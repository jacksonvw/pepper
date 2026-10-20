"""Tests for salt.core.config — defaults, round-trip, validation."""

from __future__ import annotations

import tomllib

import pytest

from viewer_core.core.config import AppearanceConfig
from salt.core.config import AppConfig, load_config, save_config


def test_defaults():
    cfg = AppConfig()
    assert cfg.appearance.window_opacity == 1.0
    assert cfg.appearance.blur_behind is True
    assert cfg.orientation == "vertical"
    assert cfg.fit_mode == "horizontal"
    assert cfg.scroll_mode == "continuous"
    assert cfg.page_gap == 8


def test_load_missing_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "no-such-file.toml")
    assert cfg == AppConfig()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = AppConfig(
        appearance=AppearanceConfig(window_opacity=0.6, bg_tint_strength=30),
        orientation="horizontal",
        fit_mode="both",
        scroll_mode="page",
        page_gap=16,
    )
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.appearance.window_opacity == pytest.approx(0.6, abs=1e-3)
    assert loaded.appearance.bg_tint_strength == 30
    assert loaded.orientation == "horizontal"
    assert loaded.fit_mode == "both"
    assert loaded.scroll_mode == "page"
    assert loaded.page_gap == 16


def test_save_output_is_valid_toml(tmp_path):
    p = tmp_path / "config.toml"
    cfg = AppConfig(orientation="horizontal", fit_mode="vertical")
    save_config(cfg, p)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    assert data["comic"]["orientation"] == "horizontal"
    assert data["comic"]["fit_mode"] == "vertical"
    assert data["comic"]["scroll_mode"] == "continuous"
    assert data["comic"]["page_gap"] == 8


def test_save_rejects_invalid_orientation(tmp_path):
    bad = AppConfig()
    bad.orientation = "diagonal"
    with pytest.raises(ValueError):
        save_config(bad, tmp_path / "out.toml")


def test_save_rejects_invalid_fit(tmp_path):
    bad = AppConfig()
    bad.fit_mode = "bogus"
    with pytest.raises(ValueError):
        save_config(bad, tmp_path / "out.toml")


def test_fit_mode_none_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    save_config(AppConfig(fit_mode="none"), p)
    assert load_config(p).fit_mode == "none"


def test_save_rejects_invalid_scroll(tmp_path):
    bad = AppConfig()
    bad.scroll_mode = "smooth"
    with pytest.raises(ValueError):
        save_config(bad, tmp_path / "out.toml")


def test_load_invalid_orientation_falls_back(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('[comic]\norientation = "diagonal"\n', encoding="utf-8")
    assert load_config(p).orientation == "vertical"


def test_load_clamps_page_gap(tmp_path):
    p = tmp_path / "clamp.toml"
    p.write_text("[comic]\npage_gap = 9999\n", encoding="utf-8")
    assert load_config(p).page_gap == 200
