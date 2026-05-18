"""Static package generator.

Pipeline:
  1. Discover supported images.
  2. Extract EXIF metadata.
  3. Optionally anonymize (faces, license plates).
  4. Write images, metadata.json, generation_report.json, and the frontend.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from street_viewer_360.anonymization import AnonymizationOutcome, Anonymizer, build_anonymizer
from street_viewer_360.config import AppConfig
from street_viewer_360.device import resolve_device
from street_viewer_360.discovery import discover_images
from street_viewer_360.frontend import write_frontend
from street_viewer_360.metadata import ImageMetadata, extract_metadata

logger = logging.getLogger(__name__)

_METADATA_VERSION = 1


@dataclass
class GenerationResult:
    """Summary returned to the CLI after a generate run.

    Attributes:
        output_dir: Root of the generated package.
        total_discovered: Number of supported images found.
        included: Number of panoramas written to metadata.json.
        without_gps: Number of images that lacked usable GPS.
        skipped_unsupported: Files skipped due to extension.
        failed: Images that raised an unrecoverable error.
        anonymized: Number of images that were successfully blurred.
        faces_blurred: Total face detections across all images.
        plates_blurred: Total license plate detections across all images.
    """

    output_dir: Path
    total_discovered: int
    included: int
    without_gps: int
    skipped_unsupported: int
    failed: int
    anonymized: int
    faces_blurred: int
    plates_blurred: int


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    """Create the output directory, optionally clearing any prior contents.

    Args:
        output_dir: Target directory.
        overwrite: If True, remove an existing directory first.

    Raises:
        FileExistsError: Directory exists and overwrite is False.
    """
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory {output_dir} already exists. Pass --overwrite to replace it.")
        if output_dir.is_file():
            output_dir.unlink()
        else:
            shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _panorama_id(index: int) -> str:
    """Build a stable panorama id from a 1-based index.

    Args:
        index: 1-based ordinal among included panoramas.

    Returns:
        Zero-padded id, e.g. "pano_000001".
    """
    return f"pano_{index:06d}"


def _output_image_name(pano_id: str, source: Path) -> str:
    """Build the on-disk filename for an output image.

    Source files like `GSAA0063.36P` (JPEG inside) are renamed to `.jpg` so
    browsers can render them directly.

    Args:
        pano_id: Generated id, e.g. "pano_000001".
        source: Path of the source image.

    Returns:
        Filename for the output image (no directory component).
    """
    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".36p"}:
        return f"{pano_id}.jpg"
    if suffix == ".png":
        return f"{pano_id}.png"
    return f"{pano_id}{suffix}"


def _write_output_image(
    source: Path,
    destination: Path,
    outcome: AnonymizationOutcome,
) -> None:
    """Write the output image either by saving the anonymized array or copying.

    Args:
        source: Path to the source image.
        destination: Where to write the output.
        outcome: Anonymization outcome; if status=="processed" its image is saved,
            otherwise the source is copied verbatim.
    """
    if outcome.status == "processed" and outcome.image is not None:
        from street_viewer_360.anonymization import save_image

        save_image(outcome.image, destination)
    else:
        shutil.copy2(source, destination)


def _build_panorama_entry(
    pano_id: str,
    meta: ImageMetadata,
    image_rel_path: str,
    outcome: AnonymizationOutcome,
) -> dict[str, Any]:
    """Convert ImageMetadata + anonymization outcome to a JSON-serializable dict.

    Args:
        pano_id: Stable id for this panorama.
        meta: Extracted metadata.
        image_rel_path: Path of the generated image relative to the output root.
        outcome: Result of running the anonymizer on this image.

    Returns:
        Dict suitable for inclusion in metadata.json.
    """
    entry: dict[str, Any] = {
        "id": pano_id,
        "source_filename": meta.source_path.name,
        "image_path": image_rel_path,
        "lat": meta.lat,
        "lon": meta.lon,
    }
    if meta.heading is not None:
        entry["heading"] = meta.heading
    if meta.captured_at is not None:
        entry["captured_at"] = meta.captured_at
    if meta.camera_make or meta.camera_model:
        entry["camera"] = {"make": meta.camera_make, "model": meta.camera_model}
    if meta.width and meta.height:
        entry["dimensions"] = {"width": meta.width, "height": meta.height}
    entry["anonymization"] = {
        "status": outcome.status,
        "detections": {
            "faces": outcome.face_count,
            "license_plates": outcome.plate_count,
        },
    }
    return entry


def generate(
    input_dir: Path,
    config: AppConfig,
    *,
    dry_run: bool = False,
    anonymizer: Anonymizer | None = None,
) -> GenerationResult:
    """Run the full generate pipeline.

    Args:
        input_dir: Directory containing source panoramas.
        config: Resolved application configuration. `config.output_dir` is the
            destination root.
        dry_run: If True, scan and extract metadata but do not write any files.
        anonymizer: Optional pre-built Anonymizer. When None, one is constructed
            from `config.anonymization`. Useful for tests.

    Returns:
        GenerationResult summarizing the run.

    Raises:
        FileNotFoundError: Input directory missing.
        FileExistsError: Output directory already exists without overwrite.
    """
    discovery = discover_images(input_dir, recursive=config.recursive)

    if not discovery.images:
        raise RuntimeError(f"No supported images found in {input_dir}. Supported extensions: .jpg, .jpeg, .png, .36p")

    output_dir = config.output_dir
    images_dir = output_dir / "images"

    if not dry_run:
        _prepare_output_dir(output_dir, overwrite=config.overwrite)
        images_dir.mkdir(parents=True, exist_ok=True)

    if anonymizer is None:
        device = resolve_device(config.device)
        anonymizer = build_anonymizer(config.anonymization, device)

    panoramas: list[dict[str, Any]] = []
    without_gps: list[str] = []
    failed: list[dict[str, str]] = []
    anonymized_count = 0
    faces_total = 0
    plates_total = 0
    next_index = 1

    for source in discovery.images:
        try:
            meta = extract_metadata(source)
        except Exception as exc:
            logger.exception("Failed to extract metadata from %s", source)
            failed.append({"source": str(source), "error": str(exc)})
            continue

        has_gps = meta.lat is not None and meta.lon is not None
        if not has_gps:
            logger.warning("No GPS coordinates for %s", source.name)
            without_gps.append(source.name)
            if not config.metadata.include_without_gps:
                continue

        pano_id = _panorama_id(next_index)
        next_index += 1
        image_name = _output_image_name(pano_id, source)
        image_rel_path = f"images/{image_name}"

        try:
            outcome = anonymizer.process(source)
        except Exception as exc:
            logger.exception("Anonymization failed for %s", source)
            failed.append({"source": str(source), "error": f"anonymization: {exc}"})
            outcome = AnonymizationOutcome(status="no_models", face_count=0, plate_count=0, image=None)

        if outcome.status == "processed":
            anonymized_count += 1
            faces_total += outcome.face_count
            plates_total += outcome.plate_count

        if not dry_run:
            _write_output_image(source, images_dir / image_name, outcome)

        panoramas.append(_build_panorama_entry(pano_id, meta, image_rel_path, outcome))

    metadata_doc = {
        "version": _METADATA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "default_zoom": config.default_zoom,
        "map_layers": [layer.model_dump() for layer in config.map_layers],
        "path": {
            "max_gap_meters": config.path.max_gap_meters,
            "max_gap_seconds": config.path.max_gap_seconds,
        },
        "viewer": {
            "min_hfov": config.viewer.min_hfov,
            "max_hfov": config.viewer.max_hfov,
        },
        "panoramas": panoramas,
    }

    report = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "discovered": len(discovery.images),
        "included": len(panoramas),
        "without_gps": without_gps,
        "skipped_unsupported": [str(p) for p in discovery.skipped],
        "failed": failed,
        "anonymization": {
            "enabled": config.anonymization.enabled,
            "has_detectors": anonymizer.has_detectors,
            "anonymized_images": anonymized_count,
            "faces_blurred": faces_total,
            "plates_blurred": plates_total,
        },
        "config": {
            "recursive": config.recursive,
            "overwrite": config.overwrite,
            "device": config.device,
            "include_without_gps": config.metadata.include_without_gps,
        },
    }

    if not dry_run:
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata_doc, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (output_dir / "generation_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote metadata.json and generation_report.json to %s", output_dir)
        write_frontend(output_dir, config)
    else:
        logger.info("Dry run: skipped writing output files")

    return GenerationResult(
        output_dir=output_dir,
        total_discovered=len(discovery.images),
        included=len(panoramas),
        without_gps=len(without_gps),
        skipped_unsupported=len(discovery.skipped),
        failed=len(failed),
        anonymized=anonymized_count,
        faces_blurred=faces_total,
        plates_blurred=plates_total,
    )
