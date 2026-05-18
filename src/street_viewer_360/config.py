"""Configuration loading and merging for street-viewer-360.

Defaults live here. A YAML config file (if given) overrides defaults, and CLI
options (passed as a dict of explicitly provided values) override both.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from street_viewer_360.device import Device

logger = logging.getLogger(__name__)

__all__ = ["SUPPORTED_EXTENSIONS", "AppConfig", "Device", "load_config"]

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".36p")


class AnonymizationConfig(BaseModel):
    """Anonymization-related settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    blur_sigma: float = 15.0
    detector: str = "yolov8"
    confidence_threshold: float = 0.25
    face_confidence_threshold: float | None = None
    plate_confidence_threshold: float | None = None
    face_model_path: Path | None = None
    plate_model_path: Path | None = None
    expand_box_ratio: float = 0.1
    inference_imgsz: int = 1280
    tile_size: int = 1280
    tile_overlap: int = 256
    nms_iou_threshold: float = 0.45


class PathConfig(BaseModel):
    """Map polyline segmentation thresholds."""

    model_config = ConfigDict(extra="forbid")

    max_gap_meters: float = 50.0
    max_gap_seconds: float = 10.0


class MetadataConfig(BaseModel):
    """Metadata extraction settings."""

    model_config = ConfigDict(extra="forbid")

    include_without_gps: bool = False
    timezone: str = "local"


class ViewerConfig(BaseModel):
    """Panorama viewer (Pannellum) view-limit settings."""

    model_config = ConfigDict(extra="forbid")

    min_hfov: float = 30.0
    max_hfov: float = 120.0


class MapLayer(BaseModel):
    """A single Leaflet tile layer definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    attribution: str = ""
    default: bool = False


def _default_map_layers() -> list[MapLayer]:
    """Return the built-in default map layer list.

    Returns:
        List with a single OpenStreetMap layer marked as default.
    """
    return [
        MapLayer(
            name="OpenStreetMap",
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attribution="(c) OpenStreetMap contributors",
            default=True,
        )
    ]


class AppConfig(BaseModel):
    """Top-level configuration for the generator."""

    model_config = ConfigDict(extra="forbid")

    default_zoom: int = 13
    output_dir: Path = Path("./dist")
    recursive: bool = True
    overwrite: bool = False
    device: Device = "auto"
    anonymization: AnonymizationConfig = Field(default_factory=AnonymizationConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    path: PathConfig = Field(default_factory=PathConfig)
    viewer: ViewerConfig = Field(default_factory=ViewerConfig)
    map_layers: list[MapLayer] = Field(default_factory=_default_map_layers)


def load_config(config_path: Path | None, overrides: dict[str, Any] | None = None) -> AppConfig:
    """Load configuration from YAML and apply CLI overrides.

    Args:
        config_path: Path to a YAML config file, or None to use defaults only.
        overrides: Mapping of explicitly set CLI values that should win over
            both defaults and the file. Keys with a None value are ignored so
            that unset CLI options do not clobber config-file values.

    Returns:
        Fully resolved AppConfig.

    Raises:
        FileNotFoundError: The given config_path does not exist.
        ValueError: The YAML cannot be parsed or fails validation.
    """
    data: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse config file {config_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file {config_path} must contain a mapping at top level")
        data = loaded

    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            data[key] = value

    try:
        return AppConfig.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Invalid configuration: {exc}") from exc
