"""Tests for image discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from street_viewer_360.discovery import discover_images


def test_discovery_finds_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.JPEG").write_bytes(b"x")
    (tmp_path / "c.png").write_bytes(b"x")
    (tmp_path / "d.36P").write_bytes(b"x")
    (tmp_path / "ignore.txt").write_bytes(b"x")
    (tmp_path / ".hidden.jpg").write_bytes(b"x")
    res = discover_images(tmp_path)
    names = sorted(p.name for p in res.images)
    assert names == ["a.jpg", "b.JPEG", "c.png", "d.36P"]
    assert [p.name for p in res.skipped] == ["ignore.txt"]


def test_discovery_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "a.jpg").write_bytes(b"x")
    (sub / "b.jpg").write_bytes(b"x")
    res = discover_images(tmp_path, recursive=True)
    assert sorted(p.name for p in res.images) == ["a.jpg", "b.jpg"]
    res_flat = discover_images(tmp_path, recursive=False)
    assert [p.name for p in res_flat.images] == ["a.jpg"]


def test_discovery_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_images(tmp_path / "nope")


def test_discovery_not_a_directory(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_bytes(b"x")
    with pytest.raises(NotADirectoryError):
        discover_images(f)


def test_discovery_is_deterministic(tmp_path: Path) -> None:
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"x")
    res = discover_images(tmp_path)
    assert [p.name for p in res.images] == ["a.jpg", "b.jpg", "c.jpg"]
