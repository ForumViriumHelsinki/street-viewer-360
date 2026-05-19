"""Tests for frontend rendering and asset copying."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from street_viewer_360.config import AppConfig
from street_viewer_360.frontend import write_frontend
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


def test_write_frontend_copies_ordered_logos(tmp_path: Path) -> None:
    logo_one = tmp_path / "first-logo.png"
    logo_two = tmp_path / "second-logo.jpg"
    Image.new("RGB", (32, 16), color="red").save(logo_one, "png")
    Image.new("RGB", (32, 16), color="blue").save(logo_two, "jpeg")

    out = tmp_path / "out"
    write_frontend(out, AppConfig(), logo_paths=[logo_one, logo_two])

    assert (out / "assets" / "logos" / "logo_001.png").is_file()
    assert (out / "assets" / "logos" / "logo_002.jpg").is_file()

    html = (out / "index.html").read_text(encoding="utf-8")
    status_index = html.index('id="status"')
    first_index = html.index("assets/logos/logo_001.png")
    second_index = html.index("assets/logos/logo_002.jpg")
    assert status_index < first_index
    assert first_index < second_index
    assert 'alt="first logo"' in html
    assert 'alt="second logo"' in html

    css = (out / "assets" / "styles.css").read_text(encoding="utf-8")
    assert ".brand-logos" in css
    assert "display: none;" in css
