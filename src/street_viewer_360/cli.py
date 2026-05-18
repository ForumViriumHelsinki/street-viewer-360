"""Typer-based command-line interface for street-viewer-360."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from street_viewer_360 import __version__
from street_viewer_360.config import Device, load_config
from street_viewer_360.frontend import write_frontend
from street_viewer_360.generator import generate as run_generate

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="street-viewer-360",
    help="Turn a folder of 360 panoramas into a static, browsable web package.",
    no_args_is_help=True,
    add_completion=False,
)


def setup_logging(log_level: str) -> None:
    """Configure root logging.

    Args:
        log_level: Level string (DEBUG, INFO, WARNING, ERROR).
    """
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _version_callback(value: bool) -> None:
    """Print the version and exit when --version is set.

    Args:
        value: True if --version was passed.
    """
    if value:
        typer.echo(f"street-viewer-360 {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Top-level entry point. Subcommands do the actual work."""


@app.command()
def generate(
    input_dir: Annotated[Path, typer.Option("--input", "-i", help="Source directory containing panoramas.")],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination directory for the static package."),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Optional YAML configuration file."),
    ] = None,
    recursive: Annotated[
        bool | None,
        typer.Option("--recursive/--no-recursive", help="Recurse into subdirectories."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an existing output directory."),
    ] = False,
    device: Annotated[
        Device | None,
        typer.Option("--device", help="Compute device for anonymization."),
    ] = None,
    default_zoom: Annotated[
        int | None,
        typer.Option("--default-zoom", help="Initial map zoom level."),
    ] = None,
    include_without_gps: Annotated[
        bool,
        typer.Option(
            "--include-without-gps",
            help="Include non-geotagged images in metadata (still excluded from map markers).",
        ),
    ] = False,
    face_model: Annotated[
        Path | None,
        typer.Option("--face-model", help="Path to a YOLOv8 face-detection model (.pt)."),
    ] = None,
    plate_model: Annotated[
        Path | None,
        typer.Option("--plate-model", help="Path to a YOLOv8 license-plate-detection model (.pt)."),
    ] = None,
    no_anonymization: Annotated[
        bool,
        typer.Option("--no-anonymization", help="Skip anonymization regardless of config."),
    ] = False,
    max_gap_meters: Annotated[
        float | None,
        typer.Option("--max-gap-meters", help="Break the map polyline between consecutive panoramas farther apart than this."),
    ] = None,
    max_gap_seconds: Annotated[
        float | None,
        typer.Option("--max-gap-seconds", help="Break the map polyline between consecutive panoramas with a larger time gap."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Inspect inputs without writing output."),
    ] = False,
    log: Annotated[str, typer.Option("--log", help="Log level.")] = "INFO",
) -> None:
    """Generate a static web package from a directory of panorama images."""
    setup_logging(log)

    overrides: dict[str, Any] = {
        "output_dir": output_dir,
        "recursive": recursive,
        "overwrite": overwrite if overwrite else None,
        "device": device,
        "default_zoom": default_zoom,
    }

    try:
        cfg = load_config(config_path, overrides=overrides)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        raise typer.Exit(code=2) from exc

    if include_without_gps:
        cfg.metadata.include_without_gps = True
    if face_model is not None:
        cfg.anonymization.face_model_path = face_model
    if plate_model is not None:
        cfg.anonymization.plate_model_path = plate_model
    if no_anonymization:
        cfg.anonymization.enabled = False
    if max_gap_meters is not None:
        cfg.path.max_gap_meters = max_gap_meters
    if max_gap_seconds is not None:
        cfg.path.max_gap_seconds = max_gap_seconds

    try:
        result = run_generate(input_dir, cfg, dry_run=dry_run)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2) from exc
    except FileExistsError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=3) from exc
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=4) from exc

    typer.echo(
        "\n".join(
            [
                "Generation summary:",
                f"  output:             {result.output_dir}",
                f"  discovered:         {result.total_discovered}",
                f"  included:           {result.included}",
                f"  without GPS:        {result.without_gps}",
                f"  skipped (ext):      {result.skipped_unsupported}",
                f"  failed:             {result.failed}",
            ]
        )
    )

    if result.anonymized:
        typer.echo(
            f"  anonymized:         {result.anonymized} (faces={result.faces_blurred}, plates={result.plates_blurred})"
        )

    if result.included == 0:
        logger.warning("No panoramas were included in the output.")
        sys.exit(5)


@app.command("refresh-frontend")
def refresh_frontend(
    output_dir: Annotated[Path, typer.Option("--output", "-o", help="Existing package directory to refresh.")],
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Optional YAML configuration file."),
    ] = None,
    title: Annotated[
        str,
        typer.Option("--title", help="Title shown in the HTML header."),
    ] = "Street Viewer 360",
    max_gap_meters: Annotated[
        float | None,
        typer.Option("--max-gap-meters", help="Break the map polyline between consecutive panoramas farther apart than this."),
    ] = None,
    max_gap_seconds: Annotated[
        float | None,
        typer.Option("--max-gap-seconds", help="Break the map polyline between consecutive panoramas with a larger time gap."),
    ] = None,
    log: Annotated[str, typer.Option("--log", help="Log level.")] = "INFO",
) -> None:
    """Rewrite index.html and assets/ in an existing package without re-processing images."""
    setup_logging(log)

    metadata_path = output_dir / "metadata.json"
    if not output_dir.exists() or not metadata_path.exists():
        logger.error("Output directory %s does not look like a generated package (missing metadata.json).", output_dir)
        raise typer.Exit(code=2)

    try:
        cfg = load_config(config_path, overrides={"output_dir": output_dir, "overwrite": True})
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        raise typer.Exit(code=2) from exc

    if max_gap_meters is not None:
        cfg.path.max_gap_meters = max_gap_meters
    if max_gap_seconds is not None:
        cfg.path.max_gap_seconds = max_gap_seconds

    import json

    metadata_doc = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_doc["path"] = {
        "max_gap_meters": cfg.path.max_gap_meters,
        "max_gap_seconds": cfg.path.max_gap_seconds,
    }
    metadata_doc["viewer"] = {
        "min_hfov": cfg.viewer.min_hfov,
        "max_hfov": cfg.viewer.max_hfov,
    }
    metadata_path.write_text(json.dumps(metadata_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    write_frontend(output_dir, cfg, title=title)
    typer.echo(f"Refreshed frontend in {output_dir}")


@app.command("download-models")
def download_models_command(
    target: Annotated[
        Path,
        typer.Option("--target", "-t", help="Directory to download model weights into."),
    ] = Path("./models"),
    log: Annotated[str, typer.Option("--log", help="Log level.")] = "INFO",
) -> None:
    """Download default YOLOv8 face and license plate models.

    Update your config.yaml to point `anonymization.face_model_path` and
    `anonymization.plate_model_path` at the downloaded files.
    """
    setup_logging(log)
    try:
        from street_viewer_360.models import download_models
    except ImportError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=10) from exc

    try:
        paths = download_models(target)
    except (ImportError, RuntimeError) as exc:
        logger.error("Model download failed: %s", exc)
        raise typer.Exit(code=11) from exc

    typer.echo("Downloaded models:")
    for path in paths:
        typer.echo(f"  {path}")


if __name__ == "__main__":
    app()
