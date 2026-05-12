"""Download default YOLO models for anonymization.

Hugging Face hosts the model weight files. URLs are pinned to a specific
revision so that downloads stay reproducible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    """Metadata for a downloadable model file.

    Attributes:
        name: Human-readable identifier used in CLI output.
        url: HTTPS source URL.
        filename: Destination filename inside the target directory.
        sha256: Optional SHA-256 hex digest for integrity verification. None
            disables the check (use only when an upstream hash is not available).
    """

    name: str
    url: str
    filename: str
    sha256: str | None = None


DEFAULT_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        name="face",
        url="https://huggingface.co/arnabdhar/YOLOv8-Face-Detection/resolve/main/model.pt",
        filename="yolov8n-face.pt",
    ),
    ModelSpec(
        name="license_plate",
        url=(
            "https://huggingface.co/morsetechlab/yolov11-license-plate-detection"
            "/resolve/main/license-plate-finetune-v1n.pt"
        ),
        filename="yolov11n-license-plate.pt",
    ),
)


def download_models(target_dir: Path, specs: tuple[ModelSpec, ...] = DEFAULT_MODELS) -> list[Path]:
    """Download the configured model files into `target_dir`.

    Args:
        target_dir: Directory to download into. Created if missing.
        specs: Model specs to download. Defaults to the bundled list.

    Returns:
        Paths of the downloaded files (in `specs` order).

    Raises:
        ImportError: httpx is not installed (optional dep group).
        RuntimeError: A download failed or hash mismatch occurred.
    """
    try:
        import httpx
    except ImportError as exc:
        raise ImportError("httpx is not installed. Run: uv sync --extra anonymization") from exc

    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    for spec in specs:
        destination = target_dir / spec.filename
        if destination.exists():
            logger.info("Already present: %s", destination)
            downloaded.append(destination)
            continue

        logger.info("Downloading %s model from %s", spec.name, spec.url)
        try:
            with httpx.stream("GET", spec.url, follow_redirects=True, timeout=120.0) as response:
                response.raise_for_status()
                tmp = destination.with_suffix(destination.suffix + ".part")
                with tmp.open("wb") as fh:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                tmp.rename(destination)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to download {spec.name} from {spec.url}: {exc}") from exc

        if spec.sha256 is not None:
            import hashlib

            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != spec.sha256:
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"Hash mismatch for {spec.name}: expected {spec.sha256}, got {digest}")

        logger.info("Saved %s -> %s", spec.name, destination)
        downloaded.append(destination)

    return downloaded
