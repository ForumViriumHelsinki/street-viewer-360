"""EXIF metadata extraction for panorama images.

Returns normalized values (decimal-degree GPS, ISO timestamps) suitable for the
generator. Designed to be defensive: any single missing tag must not crash the
pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import exifread
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GPanoMetadata:
    """Subset of XMP GPano tags relevant for horizon correction.

    Attributes:
        projection_type: e.g. "equirectangular", or None if missing.
        pose_pitch: Camera pitch in degrees (positive = nose up), or None.
        pose_roll: Camera roll in degrees (positive = right wing down), or None.
        pose_heading: Camera heading in degrees [0, 360), or None.
    """

    projection_type: str | None
    pose_pitch: float | None
    pose_roll: float | None
    pose_heading: float | None


@dataclass(frozen=True)
class ImageMetadata:
    """Normalized metadata for a single panorama.

    Attributes:
        source_path: Path to the source image on disk.
        lat: GPS latitude in decimal degrees, or None.
        lon: GPS longitude in decimal degrees, or None.
        heading: Compass heading in degrees [0, 360), or None.
        captured_at: ISO 8601 timestamp (UTC if tz known, else naive local), or None.
        width: Image pixel width, if obtainable from EXIF.
        height: Image pixel height, if obtainable from EXIF.
        camera_make: Camera manufacturer, or None.
        camera_model: Camera model, or None.
        gpano: XMP GPano subset (pose angles, projection type), or None.
    """

    source_path: Path
    lat: float | None
    lon: float | None
    heading: float | None
    captured_at: str | None
    width: int | None
    height: int | None
    camera_make: str | None
    camera_model: str | None
    gpano: GPanoMetadata | None


def _to_float(value: Any) -> float | None:
    """Convert an exifread Ratio/IFD value to float.

    Args:
        value: A value pulled from an exifread tag.

    Returns:
        Float representation, or None if it cannot be converted.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dms_to_decimal(dms: Any, ref: str | None) -> float | None:
    """Convert EXIF [deg, min, sec] + ref to decimal degrees.

    Args:
        dms: exifread tag with a `.values` list of three Ratio-like numbers.
        ref: Hemisphere reference: "N", "S", "E", or "W".

    Returns:
        Decimal degrees, or None on bad input.
    """
    if dms is None or not hasattr(dms, "values") or len(dms.values) < 3:
        return None
    parts = [_to_float(v) for v in dms.values[:3]]
    if any(p is None for p in parts):
        return None
    degrees, minutes, seconds = parts  # type: ignore[misc]
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref and ref.upper() in {"S", "W"}:
        decimal = -decimal
    return decimal


def _parse_datetime(raw: str) -> str | None:
    """Parse an EXIF DateTime string into ISO 8601.

    Args:
        raw: EXIF datetime, typically "YYYY:MM:DD HH:MM:SS".

    Returns:
        ISO 8601 string, or None if parsing fails.
    """
    raw = raw.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return None


def _normalize_heading(value: float | None) -> float | None:
    """Wrap a heading into [0, 360).

    Args:
        value: Heading in degrees, or None.

    Returns:
        Normalized heading, or None.
    """
    if value is None:
        return None
    return value % 360.0


def _parse_float(raw: Any) -> float | None:
    """Parse a value as float, returning None on failure or non-string input."""
    if not isinstance(raw, str):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _xmp_description(image_path: Path) -> dict[str, Any] | None:
    """Return the merged ``rdf:Description`` dict from an image's XMP packet.

    Uses Pillow's ``Image.getxmp()`` (backed by defusedxml) which works for
    both JPEG and WebP and strips namespace prefixes. When multiple
    Description blocks exist they are merged left-to-right.

    Args:
        image_path: Source image path.

    Returns:
        Flat dict of XMP attributes, or None if no XMP is present.
    """
    try:
        with Image.open(image_path) as img:
            xmp = img.getxmp()
    except (OSError, ValueError) as exc:
        logger.debug("XMP read failed for %s: %s", image_path, exc)
        return None
    if not xmp:
        return None
    description = xmp.get("xmpmeta", {}).get("RDF", {}).get("Description")
    if description is None:
        return None
    if isinstance(description, list):
        merged: dict[str, Any] = {}
        for item in description:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    if isinstance(description, dict):
        return description
    return None


def extract_gpano(image_path: Path) -> GPanoMetadata | None:
    """Extract the XMP GPano subset needed for horizon correction.

    Args:
        image_path: Source image path.

    Returns:
        GPanoMetadata if any GPano tag was found, otherwise None.
    """
    description = _xmp_description(image_path)
    if description is None:
        return None
    projection = description.get("ProjectionType")
    pitch = _parse_float(description.get("PosePitchDegrees"))
    roll = _parse_float(description.get("PoseRollDegrees"))
    heading = _parse_float(description.get("PoseHeadingDegrees"))
    if projection is None and pitch is None and roll is None and heading is None:
        return None
    return GPanoMetadata(
        projection_type=projection if isinstance(projection, str) else None,
        pose_pitch=pitch,
        pose_roll=roll,
        pose_heading=heading,
    )


def extract_metadata(image_path: Path) -> ImageMetadata:
    """Read EXIF tags from a single image and return normalized metadata.

    Args:
        image_path: Path to the source image.

    Returns:
        ImageMetadata with whatever fields could be extracted; missing values are None.
    """
    tags: dict[str, Any] = {}
    try:
        with image_path.open("rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read EXIF from %s: %s", image_path, exc)

    lat = _dms_to_decimal(
        tags.get("GPS GPSLatitude"),
        str(tags["GPS GPSLatitudeRef"]) if "GPS GPSLatitudeRef" in tags else None,
    )
    lon = _dms_to_decimal(
        tags.get("GPS GPSLongitude"),
        str(tags["GPS GPSLongitudeRef"]) if "GPS GPSLongitudeRef" in tags else None,
    )

    heading: float | None = None
    if "GPS GPSImgDirection" in tags:
        heading = _to_float(tags["GPS GPSImgDirection"].values[0])
    elif "GPS GPSTrack" in tags:
        heading = _to_float(tags["GPS GPSTrack"].values[0])
    heading = _normalize_heading(heading)

    captured_at: str | None = None
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        if key in tags:
            captured_at = _parse_datetime(str(tags[key]))
            if captured_at is not None:
                break

    width = int(str(tags["EXIF ExifImageWidth"])) if "EXIF ExifImageWidth" in tags else None
    height = int(str(tags["EXIF ExifImageLength"])) if "EXIF ExifImageLength" in tags else None
    camera_make = str(tags["Image Make"]).strip() if "Image Make" in tags else None
    camera_model = str(tags["Image Model"]).strip() if "Image Model" in tags else None

    return ImageMetadata(
        source_path=image_path,
        lat=lat,
        lon=lon,
        heading=heading,
        captured_at=captured_at,
        width=width,
        height=height,
        camera_make=camera_make,
        camera_model=camera_model,
        gpano=extract_gpano(image_path),
    )
