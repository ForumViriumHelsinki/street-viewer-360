"""Image discovery: find supported panorama files in an input directory."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from street_viewer_360.config import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of scanning the input directory.

    Attributes:
        images: Supported panorama image paths, sorted for deterministic output.
        skipped: Files that were skipped because their extension is unsupported.
    """

    images: list[Path]
    skipped: list[Path]


def discover_images(
    input_dir: Path,
    *,
    recursive: bool = True,
    supported_extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> DiscoveryResult:
    """Find supported panorama images in `input_dir`.

    Args:
        input_dir: Directory to scan.
        recursive: Whether to descend into subdirectories.
        supported_extensions: Lowercase extensions (with leading dot) to accept.

    Returns:
        DiscoveryResult with supported images and skipped files.

    Raises:
        FileNotFoundError: input_dir does not exist.
        NotADirectoryError: input_dir is not a directory.
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()

    images: list[Path] = []
    skipped: list[Path] = []
    extensions = {ext.lower() for ext in supported_extensions}

    for path in iterator:
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() in extensions:
            images.append(path)
        else:
            skipped.append(path)

    images.sort()
    skipped.sort()

    logger.info("Discovered %d image(s), skipped %d file(s) in %s", len(images), len(skipped), input_dir)
    return DiscoveryResult(images=images, skipped=skipped)
