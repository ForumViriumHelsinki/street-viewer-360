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

from street_viewer_360 import horizon as horizon_module
from street_viewer_360 import image_io
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
    horizon_corrected: int


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


def _output_image_name(pano_id: str, output_format: str) -> str:
    """Build the on-disk filename for an output image.

    Args:
        pano_id: Generated id, e.g. "pano_000001".
        output_format: "jpeg" or "webp".

    Returns:
        Filename for the output image (no directory component).
    """
    return f"{pano_id}{image_io.output_suffix(output_format)}"  # type: ignore[arg-type]


def _process_one(
    source: Path,
    *,
    anonymizer: Anonymizer,
    decision: horizon_module.HorizonDecision,
    interpolation: str,
) -> AnonymizationOutcome:
    """Load, optionally horizon-correct, then anonymize a single image.

    Loading happens here (not inside Anonymizer.process) so the same in-memory
    array can flow through both stages without an extra decode.

    Args:
        source: Path to the source image.
        anonymizer: Configured anonymizer (may have no detectors).
        decision: Horizon correction plan for this image.
        interpolation: Resampling kernel name for the rotation.

    Returns:
        AnonymizationOutcome. Its ``image`` is set whenever any in-memory
        modification happened (horizon and/or blur), even if anonymization
        itself was disabled.
    """
    if not decision.apply and not anonymizer.is_enabled:
        return AnonymizationOutcome(status="disabled", face_count=0, plate_count=0, image=None)

    image = image_io.load_bgr(source)

    if decision.apply:
        image = horizon_module.correct(
            image,
            pitch_deg=decision.pitch,
            roll_deg=decision.roll,
            heading_deg=decision.heading,
            interpolation=interpolation,  # type: ignore[arg-type]
        )

    outcome = anonymizer.process_image(image)
    # If anonymization didn't run but we rotated, surface the rotated array
    # so it gets saved instead of the source being re-encoded from disk.
    if outcome.image is None and decision.apply:
        return AnonymizationOutcome(
            status=outcome.status,
            face_count=outcome.face_count,
            plate_count=outcome.plate_count,
            image=image,
        )
    return outcome


def _write_output_image(
    *,
    source: Path,
    destination: Path,
    outcome: AnonymizationOutcome,
    horizon_applied: bool,
    output_format: str,
    quality: int,
    webp_method: int,
    preserve_metadata: bool,
) -> None:
    """Persist the panorama in the configured output format.

    When the pipeline produced an in-memory image (anonymization and/or
    horizon correction), it is saved directly. Otherwise the source is
    re-encoded so the chosen output format and quality still apply.

    Args:
        source: Original image path (for metadata carry-over).
        destination: Output file path.
        outcome: Anonymization outcome; its ``image`` is used when present.
        horizon_applied: Whether horizon correction was performed.
        output_format: "jpeg" or "webp".
        quality: Encoder quality.
        preserve_metadata: Carry EXIF + XMP from source.
    """
    if outcome.image is not None:
        image_io.save(
            outcome.image,
            destination,
            fmt=output_format,  # type: ignore[arg-type]
            quality=quality,
            webp_method=webp_method,
            source_path=source,
            preserve_metadata=preserve_metadata,
            zero_pose_metadata=horizon_applied,
        )
    else:
        image_io.copy_with_format(
            source,
            destination,
            fmt=output_format,  # type: ignore[arg-type]
            quality=quality,
            webp_method=webp_method,
            preserve_metadata=preserve_metadata,
        )


def _build_panorama_entry(
    pano_id: str,
    meta: ImageMetadata,
    image_rel_path: str,
    outcome: AnonymizationOutcome,
    horizon_decision: horizon_module.HorizonDecision,
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
    entry["horizon_correction"] = {
        "applied": horizon_decision.apply,
        "pitch": horizon_decision.pitch,
        "roll": horizon_decision.roll,
        "heading": horizon_decision.heading,
        "reason": horizon_decision.reason,
    }
    return entry


def generate(
    input_dir: Path,
    config: AppConfig,
    *,
    dry_run: bool = False,
    anonymizer: Anonymizer | None = None,
    logo_paths: list[Path] | None = None,
) -> GenerationResult:
    """Run the full generate pipeline.

    Args:
        input_dir: Directory containing source panoramas.
        config: Resolved application configuration. `config.output_dir` is the
            destination root.
        dry_run: If True, scan and extract metadata but do not write any files.
        anonymizer: Optional pre-built Anonymizer. When None, one is constructed
            from `config.anonymization`. Useful for tests.
        logo_paths: Optional logo image paths to show in the generated header.

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
    horizon_count = 0
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
        image_name = _output_image_name(pano_id, config.output.format)
        image_rel_path = f"images/{image_name}"

        decision = horizon_module.decide(
            meta.gpano,
            mode=config.horizon.mode,
            min_angle_degrees=config.horizon.min_angle_degrees,
            pitch_offset=config.horizon.pitch_offset_degrees,
            roll_offset=config.horizon.roll_offset_degrees,
            heading_offset=config.horizon.heading_offset_degrees,
            override_metadata=config.horizon.override_metadata,
        )

        try:
            outcome = _process_one(
                source,
                anonymizer=anonymizer,
                decision=decision,
                interpolation=config.horizon.interpolation,
            )
        except Exception as exc:
            logger.exception("Processing failed for %s", source)
            failed.append({"source": str(source), "error": f"processing: {exc}"})
            outcome = AnonymizationOutcome(status="no_models", face_count=0, plate_count=0, image=None)

        if outcome.status == "processed":
            anonymized_count += 1
            faces_total += outcome.face_count
            plates_total += outcome.plate_count
        if decision.apply:
            horizon_count += 1

        if not dry_run:
            _write_output_image(
                source=source,
                destination=images_dir / image_name,
                outcome=outcome,
                horizon_applied=decision.apply,
                output_format=config.output.format,
                quality=config.output.quality,
                webp_method=config.output.webp_method,
                preserve_metadata=config.output.preserve_metadata,
            )

        panoramas.append(_build_panorama_entry(pano_id, meta, image_rel_path, outcome, decision))

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
        "horizon": {
            "mode": config.horizon.mode,
            "min_angle_degrees": config.horizon.min_angle_degrees,
            "corrected_images": horizon_count,
        },
        "output": {
            "format": config.output.format,
            "quality": config.output.quality,
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
        write_frontend(output_dir, config, logo_paths=logo_paths)
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
        horizon_corrected=horizon_count,
    )
