"""Tests for frontend rendering and asset copying."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from street_viewer_360.config import AppConfig
from street_viewer_360.generator import generate


def _plain_jpeg(path: Path) -> None:
    Image.new("RGB", (16, 8)).save(path, "jpeg")


def test_generate_writes_frontend(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _plain_jpeg(src / "a.jpg")
    out = tmp_path / "out"
    cfg = AppConfig(output_dir=out)
    cfg.metadata.include_without_gps = True

    generate(src, cfg)

    expected = [
        out / "index.html",
        out / "assets" / "app.js",
        out / "assets" / "styles.css",
        out / "assets" / "leaflet" / "leaflet.js",
        out / "assets" / "leaflet" / "leaflet.css",
        out / "assets" / "leaflet" / "images" / "marker-icon.png",
        out / "assets" / "pannellum" / "pannellum.js",
        out / "assets" / "pannellum" / "pannellum.css",
    ]
    for path in expected:
        assert path.is_file(), f"missing {path}"

    html = (out / "index.html").read_text(encoding="utf-8")
    assert "assets/leaflet/leaflet.js" in html
    assert "assets/pannellum/pannellum.js" in html
    assert "metadata.json" not in html  # loaded at runtime from app.js, not embedded
