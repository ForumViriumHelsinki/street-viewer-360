"""Tests for config loading and CLI override merging."""

from __future__ import annotations

from pathlib import Path

import pytest

from street_viewer_360.config import load_config


def test_load_config_defaults_only(tmp_path: Path) -> None:
    cfg = load_config(None)
    assert cfg.default_zoom == 13
    assert cfg.recursive is True
    assert cfg.overwrite is False
    assert cfg.device == "auto"
    assert cfg.anonymization.enabled is True
    assert cfg.metadata.include_without_gps is False
    assert len(cfg.map_layers) == 1
    assert cfg.map_layers[0].default is True


def test_load_config_from_yaml(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        """
default_zoom: 9
recursive: false
anonymization:
  enabled: false
  blur_sigma: 25
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.default_zoom == 9
    assert cfg.recursive is False
    assert cfg.anonymization.enabled is False
    assert cfg.anonymization.blur_sigma == 25


def test_cli_overrides_win(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("default_zoom: 5\nrecursive: true\n", encoding="utf-8")
    cfg = load_config(p, overrides={"default_zoom": 17, "recursive": None})
    assert cfg.default_zoom == 17
    assert cfg.recursive is True


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")


def test_bad_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("default_zoom: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse"):
        load_config(p)


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("nonsense_key: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid configuration"):
        load_config(p)
