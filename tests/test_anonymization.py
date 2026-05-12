"""Tests for anonymization with a mocked detector.

These tests use opencv-python (which is part of the optional `anonymization`
extra). When the extra is not installed, the tests are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from street_viewer_360.anonymization import (  # noqa: E402
    Anonymizer,
    Detection,
    apply_blur,
    iter_tiles,
    non_max_suppression,
)
from street_viewer_360.config import AnonymizationConfig, AppConfig  # noqa: E402
from street_viewer_360.generator import generate  # noqa: E402


class FixedDetector:
    """Detector stub that always returns the same boxes."""

    def __init__(self, detections: list[Detection]) -> None:
        self._detections = detections
        self.label = detections[0].label if detections else "face"

    def detect(self, image) -> list[Detection]:
        return list(self._detections)


def _checker_image(size: int = 64) -> np.ndarray:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[::2, ::2] = (255, 0, 0)
    img[1::2, 1::2] = (0, 0, 255)
    return img


def test_apply_blur_changes_only_inside_box() -> None:
    img = _checker_image()
    original = img.copy()
    detection = Detection(x=20, y=20, width=20, height=20, label="face", confidence=0.9)

    apply_blur(img, [detection], blur_sigma=5.0)

    assert not np.array_equal(img[20:40, 20:40], original[20:40, 20:40])
    assert np.array_equal(img[0:10, 0:10], original[0:10, 0:10])
    assert np.array_equal(img[50:60, 50:60], original[50:60, 50:60])


def test_apply_blur_no_detections_is_noop() -> None:
    img = _checker_image()
    original = img.copy()
    apply_blur(img, [], blur_sigma=5.0)
    assert np.array_equal(img, original)


def test_anonymizer_disabled_returns_disabled_status(tmp_path: Path) -> None:
    cfg = AnonymizationConfig(enabled=False)
    anon = Anonymizer([], cfg)
    img_path = tmp_path / "x.jpg"
    cv2.imwrite(str(img_path), _checker_image())
    outcome = anon.process(img_path)
    assert outcome.status == "disabled"
    assert outcome.image is None


def test_anonymizer_no_detectors_returns_no_models(tmp_path: Path) -> None:
    cfg = AnonymizationConfig(enabled=True)
    anon = Anonymizer([], cfg)
    img_path = tmp_path / "x.jpg"
    cv2.imwrite(str(img_path), _checker_image())
    outcome = anon.process(img_path)
    assert outcome.status == "no_models"


def test_anonymizer_counts_per_label(tmp_path: Path) -> None:
    img_path = tmp_path / "x.jpg"
    cv2.imwrite(str(img_path), _checker_image())

    face_det = FixedDetector(
        [
            Detection(x=0, y=0, width=10, height=10, label="face", confidence=0.9),
            Detection(x=10, y=10, width=10, height=10, label="face", confidence=0.8),
        ]
    )
    plate_det = FixedDetector([Detection(x=30, y=30, width=15, height=8, label="license_plate", confidence=0.7)])
    anon = Anonymizer([face_det, plate_det], AnonymizationConfig(enabled=True, blur_sigma=3.0))

    outcome = anon.process(img_path)
    assert outcome.status == "processed"
    assert outcome.face_count == 2
    assert outcome.plate_count == 1
    assert outcome.image is not None


def test_iter_tiles_covers_full_image() -> None:
    tiles = iter_tiles(image_width=2000, image_height=1500, tile_size=1280, overlap=256)
    assert tiles[0] == (0, 0, 1280, 1280)
    assert all(x2 <= 2000 and y2 <= 1500 for _, _, x2, y2 in tiles)
    assert any(x2 == 2000 for _, _, x2, _ in tiles)
    assert any(y2 == 1500 for _, _, _, y2 in tiles)


def test_iter_tiles_small_image_returns_single_tile() -> None:
    tiles = iter_tiles(image_width=800, image_height=600, tile_size=1280, overlap=128)
    assert tiles == [(0, 0, 800, 600)]


def test_nms_dedupes_overlapping_boxes() -> None:
    a = Detection(x=0, y=0, width=100, height=100, label="face", confidence=0.9)
    b = Detection(x=10, y=10, width=100, height=100, label="face", confidence=0.5)
    c = Detection(x=500, y=500, width=50, height=50, label="face", confidence=0.4)
    kept = non_max_suppression([a, b, c], iou_threshold=0.45)
    assert a in kept
    assert b not in kept
    assert c in kept


def test_nms_keeps_different_labels() -> None:
    face = Detection(x=0, y=0, width=100, height=100, label="face", confidence=0.9)
    plate = Detection(x=10, y=10, width=100, height=100, label="license_plate", confidence=0.5)
    kept = non_max_suppression([face, plate], iou_threshold=0.45)
    assert face in kept
    assert plate in kept


def test_anonymizer_tiles_large_image(tmp_path: Path) -> None:
    big = np.zeros((2000, 3000, 3), dtype=np.uint8)
    img_path = tmp_path / "big.jpg"
    cv2.imwrite(str(img_path), big)

    calls: list[tuple[int, int]] = []

    class RecordingDetector:
        label = "face"

        def detect(self, tile):
            calls.append((tile.shape[1], tile.shape[0]))
            return []

    cfg = AnonymizationConfig(enabled=True, tile_size=1280, tile_overlap=256)
    anon = Anonymizer([RecordingDetector()], cfg)
    outcome = anon.process(img_path)
    assert outcome.status == "processed"
    assert len(calls) > 1
    assert all(w <= 1280 and h <= 1280 for w, h in calls)


def test_generate_with_mocked_anonymizer(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    img_path = src / "a.jpg"
    cv2.imwrite(str(img_path), _checker_image())

    cfg = AppConfig(output_dir=tmp_path / "out")
    cfg.metadata.include_without_gps = True

    detector = FixedDetector([Detection(x=10, y=10, width=20, height=20, label="face", confidence=0.95)])
    anon = Anonymizer([detector], cfg.anonymization)

    result = generate(src, cfg, anonymizer=anon)
    assert result.anonymized == 1
    assert result.faces_blurred == 1
    assert result.plates_blurred == 0

    meta = json.loads((cfg.output_dir / "metadata.json").read_text())
    assert meta["panoramas"][0]["anonymization"] == {
        "status": "processed",
        "detections": {"faces": 1, "license_plates": 0},
    }
    report = json.loads((cfg.output_dir / "generation_report.json").read_text())
    assert report["anonymization"]["anonymized_images"] == 1
    assert report["anonymization"]["faces_blurred"] == 1
