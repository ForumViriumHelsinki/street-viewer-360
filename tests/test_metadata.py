"""Tests for EXIF metadata extraction.

Uses Pillow to write a synthetic JPEG with EXIF GPS data so the test does not
depend on bundled fixture binaries.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import piexif
import pytest
from PIL import Image

from street_viewer_360.metadata import extract_metadata


def _deg_to_dms_rationals(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Convert decimal degrees to ((d,1),(m,1),(s/100,100)) rationals for EXIF."""
    abs_value = abs(value)
    degrees = int(abs_value)
    minutes_full = (abs_value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    seconds_frac = Fraction(seconds).limit_denominator(1000)
    return (degrees, 1), (minutes, 1), (seconds_frac.numerator, seconds_frac.denominator)


def _write_jpeg_with_gps(path: Path, lat: float, lon: float, heading: float | None) -> None:
    img = Image.new("RGB", (16, 8), color=(0, 0, 0))
    gps_ifd: dict[int, object] = {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _deg_to_dms_rationals(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _deg_to_dms_rationals(lon),
    }
    if heading is not None:
        gps_ifd[piexif.GPSIFD.GPSImgDirectionRef] = b"T"
        gps_ifd[piexif.GPSIFD.GPSImgDirection] = (int(heading * 100), 100)
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"TestMake",
            piexif.ImageIFD.Model: b"TestModel",
            piexif.ImageIFD.DateTime: b"2026:05:12 10:00:00",
        },
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:05:12 09:30:00"},
        "GPS": gps_ifd,
        "1st": {},
        "thumbnail": None,
    }
    exif_bytes = piexif.dump(exif_dict)
    img.save(path, "jpeg", exif=exif_bytes)


def test_extract_metadata_with_gps(tmp_path: Path) -> None:
    pytest.importorskip("piexif")
    p = tmp_path / "test.jpg"
    _write_jpeg_with_gps(p, lat=60.1699, lon=24.9384, heading=90.0)
    meta = extract_metadata(p)
    assert meta.lat is not None
    assert meta.lon is not None
    assert meta.lat == pytest.approx(60.1699, abs=1e-3)
    assert meta.lon == pytest.approx(24.9384, abs=1e-3)
    assert meta.heading == pytest.approx(90.0, abs=1e-3)
    assert meta.captured_at is not None
    assert meta.captured_at.startswith("2026-05-12T09:30:00")
    assert meta.camera_make == "TestMake"
    assert meta.camera_model == "TestModel"


def test_extract_metadata_without_gps(tmp_path: Path) -> None:
    p = tmp_path / "plain.jpg"
    Image.new("RGB", (16, 8)).save(p, "jpeg")
    meta = extract_metadata(p)
    assert meta.lat is None
    assert meta.lon is None
    assert meta.heading is None


def test_extract_metadata_negative_hemisphere(tmp_path: Path) -> None:
    pytest.importorskip("piexif")
    p = tmp_path / "south.jpg"
    _write_jpeg_with_gps(p, lat=-33.8688, lon=-58.3816, heading=None)
    meta = extract_metadata(p)
    assert meta.lat == pytest.approx(-33.8688, abs=1e-3)
    assert meta.lon == pytest.approx(-58.3816, abs=1e-3)
    assert meta.heading is None
