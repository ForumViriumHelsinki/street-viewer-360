"""End-to-end-ish tests for the generator (without real EXIF)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from street_viewer_360.config import AppConfig
from street_viewer_360.generator import generate


def _plain_jpeg(path: Path) -> None:
    Image.new("RGB", (16, 8)).save(path, "jpeg")


def test_generate_with_no_gps_excludes_by_default(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    cfg = AppConfig(output_dir=out)
    result = generate(src, cfg)
    assert result.total_discovered == 1
    assert result.included == 0
    assert result.without_gps == 1
    doc = json.loads((out / "metadata.json").read_text())
    assert doc["panoramas"] == []
    assert (out / "generation_report.json").exists()


def test_generate_include_without_gps(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    cfg = AppConfig(output_dir=out)
    cfg.metadata.include_without_gps = True
    result = generate(src, cfg)
    assert result.included == 1
    doc = json.loads((out / "metadata.json").read_text())
    assert len(doc["panoramas"]) == 1
    assert doc["panoramas"][0]["id"] == "pano_000001"
    assert doc["panoramas"][0]["image_path"] == "images/pano_000001.jpg"
    assert (out / "images" / "pano_000001.jpg").exists()


def test_generate_refuses_to_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    out.mkdir()
    cfg = AppConfig(output_dir=out)
    cfg.metadata.include_without_gps = True
    with pytest.raises(FileExistsError):
        generate(src, cfg)


def test_generate_overwrite_clears_previous(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old")
    cfg = AppConfig(output_dir=out, overwrite=True)
    cfg.metadata.include_without_gps = True
    generate(src, cfg)
    assert not (out / "stale.txt").exists()
    assert (out / "metadata.json").exists()


def test_generate_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    cfg = AppConfig(output_dir=out)
    cfg.metadata.include_without_gps = True
    generate(src, cfg, dry_run=True)
    assert not out.exists()


def test_generate_renames_36p_to_jpg(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    target = src / "GSAA0001.36P"
    Image.new("RGB", (16, 8)).save(target, "jpeg")
    out = tmp_path / "out"
    cfg = AppConfig(output_dir=out)
    cfg.metadata.include_without_gps = True
    generate(src, cfg)
    assert (out / "images" / "pano_000001.jpg").exists()


def test_generate_empty_input_raises(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    cfg = AppConfig(output_dir=tmp_path / "out")
    with pytest.raises(RuntimeError):
        generate(src, cfg)
