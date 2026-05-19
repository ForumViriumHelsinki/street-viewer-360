"""Unified image load/save with EXIF + XMP preservation and format choice.

Loading goes through OpenCV (BGR numpy array). Saving uses Pillow so we can
embed EXIF and XMP bytes regardless of output format (JPEG or WebP).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

OutputFormat = Literal["jpeg", "webp"]

_FORMAT_SUFFIX: dict[OutputFormat, str] = {"jpeg": ".jpg", "webp": ".webp"}


def output_suffix(fmt: OutputFormat) -> str:
    """Return the canonical filename suffix for an output format."""
    return _FORMAT_SUFFIX[fmt]


def load_bgr(image_path: Path) -> np.ndarray:
    """Load an image as a HxWx3 uint8 BGR numpy array.

    Args:
        image_path: Path to the source image.

    Returns:
        BGR image array.

    Raises:
        OSError: If the file cannot be decoded.
    """
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise OSError(f"Failed to read image: {image_path}")
    return image


def _read_metadata_chunks(image_path: Path) -> tuple[bytes | None, bytes | None]:
    """Return ``(exif, xmp)`` byte chunks from a source image, or (None, None).

    Works for both JPEG and WebP by going through Pillow's ``info`` dict.
    """
    try:
        with Image.open(image_path) as img:
            return img.info.get("exif"), img.info.get("xmp")
    except Exception as exc:
        logger.debug("Metadata read failed for %s: %s", image_path, exc)
        return None, None


_POSE_TAGS = ("PosePitchDegrees", "PoseRollDegrees", "PoseHeadingDegrees")


def _zero_pose_in_xmp(xmp: bytes) -> bytes:
    """Rewrite GPano pose angles to 0.0 in an XMP packet.

    Handles both attribute and element forms. Leaves everything else intact.

    Args:
        xmp: Raw XMP packet bytes.

    Returns:
        Modified XMP bytes.
    """
    text = xmp.decode("utf-8", errors="replace")
    for tag in _POSE_TAGS:
        text = re.sub(
            r"(GPano:" + tag + r'\s*=\s*")[^"]*(")',
            r"\g<1>0.0\g<2>",
            text,
        )
        text = re.sub(
            r"(<GPano:" + tag + r"[^>]*>)[^<]*(</GPano:" + tag + r">)",
            r"\g<1>0.0\g<2>",
            text,
        )
    return text.encode("utf-8")


def save(
    image: np.ndarray,
    destination: Path,
    *,
    fmt: OutputFormat,
    quality: int,
    source_path: Path | None = None,
    preserve_metadata: bool = True,
    zero_pose_metadata: bool = False,
) -> None:
    """Encode a BGR numpy image to disk in the requested format.

    EXIF and XMP segments from ``source_path`` are embedded when
    ``preserve_metadata`` is True. When ``zero_pose_metadata`` is True the
    GPano pose-angle tags are reset to 0.0 so downstream viewers do not
    re-apply a correction that has already been baked into the pixels.

    Args:
        image: HxWx3 uint8 BGR image.
        destination: Output file path.
        fmt: "jpeg" or "webp".
        quality: 1-100. Mapped to Pillow's ``quality`` parameter.
        source_path: Original file for metadata carry-over.
        preserve_metadata: Embed EXIF + XMP from source.
        zero_pose_metadata: Reset GPano pose angles to zero in the embedded XMP.
    """
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)

    exif_bytes: bytes | None = None
    xmp_bytes: bytes | None = None
    if preserve_metadata and source_path is not None:
        exif_bytes, xmp_bytes = _read_metadata_chunks(source_path)
        if xmp_bytes is not None and zero_pose_metadata:
            xmp_bytes = _zero_pose_in_xmp(xmp_bytes)

    save_kwargs: dict[str, object] = {"quality": quality}
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes
    if xmp_bytes:
        save_kwargs["xmp"] = xmp_bytes

    if fmt == "jpeg":
        pil_image.save(destination, "JPEG", **save_kwargs)
    elif fmt == "webp":
        # method=6 = slowest/best compression. Worth it for one-off generation.
        save_kwargs["method"] = 6
        pil_image.save(destination, "WEBP", **save_kwargs)
    else:  # pragma: no cover - guarded by Literal type
        raise ValueError(f"Unsupported output format: {fmt}")


def copy_with_format(
    source_path: Path,
    destination: Path,
    *,
    fmt: OutputFormat,
    quality: int,
    preserve_metadata: bool = True,
) -> None:
    """Re-encode an untouched source file to the requested output format.

    Used when no in-memory processing happened (e.g. anonymization disabled
    and horizon correction skipped) but the user still wants the chosen
    output format/quality.

    Args:
        source_path: Source image path.
        destination: Output path.
        fmt: Output format.
        quality: Encoder quality.
        preserve_metadata: Carry EXIF + XMP from the source.
    """
    image = load_bgr(source_path)
    save(
        image,
        destination,
        fmt=fmt,
        quality=quality,
        source_path=source_path,
        preserve_metadata=preserve_metadata,
        zero_pose_metadata=False,
    )
