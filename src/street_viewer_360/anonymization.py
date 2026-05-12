"""Face and license plate anonymization.

Loads YOLO detector(s) lazily so that the package can be installed without the
heavy optional `anonymization` dependency group.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    Image = NDArray[np.uint8]
else:
    Image = Any

from street_viewer_360.config import AnonymizationConfig
from street_viewer_360.device import ResolvedDevice

logger = logging.getLogger(__name__)

DetectionLabel = Literal["face", "license_plate"]


@dataclass(frozen=True)
class Detection:
    """One detected privacy-sensitive region.

    Attributes:
        x: Left coordinate in pixels.
        y: Top coordinate in pixels.
        width: Box width in pixels.
        height: Box height in pixels.
        label: Either "face" or "license_plate".
        confidence: Detector confidence in [0, 1].
    """

    x: int
    y: int
    width: int
    height: int
    label: DetectionLabel
    confidence: float


class Detector(Protocol):
    """Protocol for object detectors used by the anonymizer."""

    label: DetectionLabel

    def detect(self, image: Image) -> list[Detection]:
        """Run detection on a BGR image.

        Args:
            image: HxWx3 uint8 numpy array in BGR order.

        Returns:
            List of detected regions.
        """
        ...


class YOLOv8Detector:
    """Detector backed by an ultralytics YOLOv8 model.

    Attributes:
        label: Label assigned to all detections produced by this detector.
    """

    def __init__(
        self,
        model_path: Path,
        label: DetectionLabel,
        *,
        confidence_threshold: float,
        device: ResolvedDevice,
        imgsz: int = 1280,
    ) -> None:
        """Load a YOLOv8 .pt model from disk.

        Args:
            model_path: Path to the model weights.
            label: Label to attach to every detection.
            confidence_threshold: Minimum confidence to keep a prediction.
            device: torch device string ("cpu", "cuda", or "mps").
            imgsz: Image size passed to ultralytics' predict(). Should be near
                the tile size when running tiled inference.

        Raises:
            ImportError: ultralytics is not installed (optional dep group).
            FileNotFoundError: model_path does not exist.
        """
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError("ultralytics is not installed. Run: uv sync --extra anonymization") from exc

        if not model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {model_path}")

        self._model = YOLO(str(model_path))
        self._confidence_threshold = confidence_threshold
        self._device = device
        self._imgsz = imgsz
        self.label: DetectionLabel = label

    def detect(self, image: Image) -> list[Detection]:
        """Run inference and return filtered detections.

        Args:
            image: HxWx3 uint8 BGR image.

        Returns:
            Detections that exceed the configured confidence threshold.
        """
        results = self._model.predict(
            image,
            conf=self._confidence_threshold,
            device=self._device,
            imgsz=self._imgsz,
            verbose=False,
        )
        detections: list[Detection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else boxes.xyxy
            confidences = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else boxes.conf
            for (x1, y1, x2, y2), conf in zip(xyxy, confidences, strict=False):
                detections.append(
                    Detection(
                        x=int(x1),
                        y=int(y1),
                        width=int(x2 - x1),
                        height=int(y2 - y1),
                        label=self.label,
                        confidence=float(conf),
                    )
                )
        return detections


def iter_tiles(
    image_width: int,
    image_height: int,
    tile_size: int,
    overlap: int,
) -> list[tuple[int, int, int, int]]:
    """Compute tile rectangles that cover an image with overlap.

    Args:
        image_width: Source image width in pixels.
        image_height: Source image height in pixels.
        tile_size: Edge length of each square tile.
        overlap: Pixels of overlap between adjacent tiles. The effective stride
            is `tile_size - overlap`.

    Returns:
        List of (x1, y1, x2, y2) tuples in image coordinates. Tiles are clamped
        to the image bounds; the right and bottom edges may be smaller than
        `tile_size`.
    """
    if tile_size <= 0:
        return [(0, 0, image_width, image_height)]

    stride = max(1, tile_size - max(0, overlap))
    tiles: list[tuple[int, int, int, int]] = []

    y = 0
    while True:
        y2 = min(image_height, y + tile_size)
        x = 0
        while True:
            x2 = min(image_width, x + tile_size)
            tiles.append((x, y, x2, y2))
            if x2 >= image_width:
                break
            x += stride
        if y2 >= image_height:
            break
        y += stride

    return tiles


def _iou(a: Detection, b: Detection) -> float:
    """Intersection-over-union for two boxes.

    Args:
        a: First detection.
        b: Second detection.

    Returns:
        IoU in [0, 1].
    """
    ax2, ay2 = a.x + a.width, a.y + a.height
    bx2, by2 = b.x + b.width, b.y + b.height
    inter_x1 = max(a.x, b.x)
    inter_y1 = max(a.y, b.y)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def non_max_suppression(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    """Remove overlapping boxes via greedy NMS (per label).

    Args:
        detections: Candidate detections.
        iou_threshold: Boxes with IoU above this against a kept box are dropped.

    Returns:
        Filtered list, sorted by descending confidence.
    """
    by_label: dict[DetectionLabel, list[Detection]] = {}
    for det in detections:
        by_label.setdefault(det.label, []).append(det)

    kept: list[Detection] = []
    for group in by_label.values():
        group.sort(key=lambda d: d.confidence, reverse=True)
        while group:
            head = group.pop(0)
            kept.append(head)
            group = [d for d in group if _iou(head, d) < iou_threshold]
    kept.sort(key=lambda d: d.confidence, reverse=True)
    return kept


def apply_blur(image: Image, detections: list[Detection], *, blur_sigma: float, expand_ratio: float = 0.0) -> Image:
    """Apply Gaussian blur to every detected region in `image`.

    Args:
        image: HxWx3 uint8 BGR image. Modified in place.
        detections: Regions to blur.
        blur_sigma: Standard deviation for the Gaussian kernel.
        expand_ratio: Fractional expansion of each box (e.g. 0.1 = 10% on each side)
            to widen the blur margin slightly past the detected region.

    Returns:
        The (in-place) modified image, for convenience.
    """
    import cv2  # local import keeps the dep optional

    height, width = image.shape[:2]
    kernel_size = max(3, int(blur_sigma * 4) | 1)  # odd, >= 3

    for det in detections:
        pad_x = int(det.width * expand_ratio)
        pad_y = int(det.height * expand_ratio)
        x1 = max(0, det.x - pad_x)
        y1 = max(0, det.y - pad_y)
        x2 = min(width, det.x + det.width + pad_x)
        y2 = min(height, det.y + det.height + pad_y)
        if x2 <= x1 or y2 <= y1:
            continue
        roi = image[y1:y2, x1:x2]
        image[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kernel_size, kernel_size), blur_sigma)

    return image


@dataclass
class AnonymizationOutcome:
    """Result of anonymizing a single image.

    Attributes:
        status: "processed", "disabled", or "no_models".
        face_count: Number of detected faces.
        plate_count: Number of detected license plates.
        image: BGR numpy image with blurs applied, or None if status != "processed".
    """

    status: Literal["processed", "disabled", "no_models"]
    face_count: int
    plate_count: int
    image: Image | None


class Anonymizer:
    """High-level anonymizer that combines face and plate detectors."""

    def __init__(self, detectors: list[Detector], anonymization_config: AnonymizationConfig) -> None:
        """Store detectors and runtime parameters.

        Args:
            detectors: Detectors to run on every image (may be empty).
            anonymization_config: Resolved anonymization config.
        """
        self._detectors = detectors
        self._config = anonymization_config

    @property
    def has_detectors(self) -> bool:
        """True if at least one detector is configured."""
        return bool(self._detectors)

    def process(self, image_path: Path) -> AnonymizationOutcome:
        """Read an image, run detectors, and apply blur.

        Args:
            image_path: Path to the source image.

        Returns:
            Outcome including the blurred image and per-label detection counts.
        """
        if not self._config.enabled:
            return AnonymizationOutcome(status="disabled", face_count=0, plate_count=0, image=None)
        if not self._detectors:
            return AnonymizationOutcome(status="no_models", face_count=0, plate_count=0, image=None)

        import cv2

        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError(f"Failed to read image: {image_path}")

        all_detections = self._run_detectors(image)
        all_detections = non_max_suppression(all_detections, self._config.nms_iou_threshold)

        apply_blur(
            image,
            all_detections,
            blur_sigma=self._config.blur_sigma,
            expand_ratio=self._config.expand_box_ratio,
        )

        faces = sum(1 for d in all_detections if d.label == "face")
        plates = sum(1 for d in all_detections if d.label == "license_plate")
        return AnonymizationOutcome(status="processed", face_count=faces, plate_count=plates, image=image)

    def _run_detectors(self, image: Image) -> list[Detection]:
        """Run all detectors over the image, optionally tiled for high-res inputs.

        Args:
            image: HxWx3 uint8 BGR image.

        Returns:
            Detections in full-image coordinates, pre-NMS.
        """
        height, width = image.shape[:2]
        tile_size = self._config.tile_size
        use_tiling = tile_size > 0 and (width > tile_size or height > tile_size)

        if not use_tiling:
            detections: list[Detection] = []
            for detector in self._detectors:
                detections.extend(detector.detect(image))
            return detections

        tiles = iter_tiles(width, height, tile_size, self._config.tile_overlap)
        logger.info(
            "Tiled inference: %d tiles (%dx%d, overlap %d) for %dx%d image",
            len(tiles),
            tile_size,
            tile_size,
            self._config.tile_overlap,
            width,
            height,
        )
        merged: list[Detection] = []
        for x1, y1, x2, y2 in tiles:
            tile = image[y1:y2, x1:x2]
            for detector in self._detectors:
                for det in detector.detect(tile):
                    merged.append(
                        Detection(
                            x=det.x + x1,
                            y=det.y + y1,
                            width=det.width,
                            height=det.height,
                            label=det.label,
                            confidence=det.confidence,
                        )
                    )
        return merged


def build_anonymizer(config: AnonymizationConfig, device: ResolvedDevice) -> Anonymizer:
    """Construct an Anonymizer based on configuration.

    Args:
        config: Anonymization settings.
        device: Resolved torch device string.

    Returns:
        Anonymizer instance. Detector list may be empty if no model paths are set.
    """
    detectors: list[Detector] = []
    if not config.enabled:
        return Anonymizer(detectors, config)

    if config.face_model_path is not None:
        try:
            detectors.append(
                YOLOv8Detector(
                    config.face_model_path,
                    label="face",
                    confidence_threshold=config.confidence_threshold,
                    device=device,
                    imgsz=config.inference_imgsz,
                )
            )
        except (ImportError, FileNotFoundError) as exc:
            logger.warning("Failed to load face model: %s", exc)
    else:
        logger.warning("No face model configured (anonymization.face_model_path)")

    if config.plate_model_path is not None:
        try:
            detectors.append(
                YOLOv8Detector(
                    config.plate_model_path,
                    label="license_plate",
                    confidence_threshold=config.confidence_threshold,
                    device=device,
                    imgsz=config.inference_imgsz,
                )
            )
        except (ImportError, FileNotFoundError) as exc:
            logger.warning("Failed to load plate model: %s", exc)
    else:
        logger.warning("No license plate model configured (anonymization.plate_model_path)")

    return Anonymizer(detectors, config)


def save_image(image: Image, destination: Path) -> None:
    """Write a BGR numpy image to disk as JPEG (or PNG if suffix says so).

    Args:
        image: HxWx3 uint8 BGR image.
        destination: Output path; the suffix determines the encoder.
    """
    import cv2

    ok = cv2.imwrite(str(destination), image)
    if not ok:
        raise OSError(f"Failed to write image: {destination}")
