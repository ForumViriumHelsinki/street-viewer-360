"""Compute device resolution for anonymization inference."""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

Device = Literal["auto", "cpu", "cuda", "mps"]
ResolvedDevice = Literal["cpu", "cuda", "mps"]


def resolve_device(requested: Device) -> ResolvedDevice:
    """Pick the best available torch device.

    Args:
        requested: User preference. "auto" picks the best available device.
            Other values are returned as-is after a best-effort availability check.

    Returns:
        Concrete device string: "cuda", "mps", or "cpu".
    """
    if requested != "auto":
        try:
            import torch
        except ImportError:
            logger.warning("torch is not installed; falling back to cpu (requested=%s)", requested)
            return "cpu"
        if requested == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available; falling back to cpu")
            return "cpu"
        if requested == "mps" and not torch.backends.mps.is_available():
            logger.warning("MPS requested but not available; falling back to cpu")
            return "cpu"
        return requested

    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
