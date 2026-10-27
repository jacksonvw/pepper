"""Tests for the shared AppearanceConfig + emit/coerce helpers."""

from __future__ import annotations

import tomllib

from viewer_core.core.config import (
    AppearanceConfig,
    app_config_path,
    coerce_appearance,
    emit_appearance_lines,
)


def test_defaults():
    cfg = AppearanceConfig()
    assert cfg.window_opacity == 1.0
    assert cfg.blur_behind is True
    assert cfg.bg_color == [0, 0, 0]
    assert cfg.bg_tint_strength == 70


def test_coerce_handles_partial():
    cfg = coerce_appearance({"window_opacity": 0.5})
    assert cfg.window_opacity == 0.5
    assert cfg.blur_behind is True


def test_coerce_clamps_opacity():
    assert coerce_appearance({"window_opacity": 1.5}).window_opacity == 1.0
    assert coerce_appearance({"window_opacity": -0.5}).window_opacity == 0.0


def test_coerce_clamps_bg_color():
    cfg = coerce_appearance({"bg_color": [-5, 300, 128]})
    assert cfg.bg_color == [0, 255, 128]


def test_coerce_invalid_bg_color_falls_back():
    cfg = coerce_appearance({"bg_color": "red"})
    assert cfg.bg_color == [0, 0, 0]


def test_emit_roundtrip():
    cfg = AppearanceConfig(
        window_opacity=0.42, blur_behind=False,
        bg_color=[10, 20, 30], bg_tint_strength=55,
    )
    body = "[appearance]\n" + "\n".join(emit_appearance_lines(cfg)) + "\n"
    data = tomllib.loads(body)
    assert data["appearance"]["window_opacity"] == 0.42
    assert data["appearance"]["blur_behind"] is False
    assert data["appearance"]["bg_color"] == [10, 20, 30]
    assert data["appearance"]["bg_tint_strength"] == 55


def test_app_config_path_uses_xdg_default(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = app_config_path("widget")
    assert p.parts[-3:] == (".config", "widget", "config.toml")


def test_app_config_path_honours_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_config_path("widget") == tmp_path / "widget" / "config.toml"


def test_app_config_path_ignores_relative_xdg_config_home(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
    p = app_config_path("widget")
    assert p.parts[-3:] == (".config", "widget", "config.toml")
