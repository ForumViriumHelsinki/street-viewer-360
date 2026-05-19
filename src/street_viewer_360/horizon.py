"""Horizon correction for equirectangular panoramas.

Uses the XMP GPano ``Pose{Heading,Pitch,Roll}Degrees`` tags to rotate the
panorama so the horizon is level. Operates entirely on numpy/cv2 — no GPU
needed. A 7680x3840 image takes well under a second on a modern CPU.

Conventions:
  * Equirectangular layout: x in [0, W) maps to longitude in [-pi, pi),
    y in [0, H) maps to latitude in [pi/2, -pi/2] (top row = +pi/2).
  * Pose angles describe the camera's orientation at capture time. We apply
    the *inverse* rotation to bring the scene back to a level frame.
  * Coordinate frame: x = forward (lon=0, lat=0), y = left (lon=+pi/2),
    z = up (lat=+pi/2). Heading rotates around z (up), pitch around y (left),
    roll around x (forward).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from street_viewer_360.metadata import GPanoMetadata

logger = logging.getLogger(__name__)

HorizonMode = Literal["auto", "always", "never"]
Interpolation = Literal["nearest", "bilinear", "bicubic"]

_INTERP_MAP: dict[Interpolation, int] = {
    "nearest": cv2.INTER_NEAREST,
    "bilinear": cv2.INTER_LINEAR,
    "bicubic": cv2.INTER_CUBIC,
}


@dataclass(frozen=True)
class HorizonDecision:
    """Outcome of evaluating whether (and how) to rotate one panorama.

    Attributes:
        apply: True when correction should run.
        pitch: Effective pitch angle in degrees (metadata + override), or 0.
        roll: Effective roll angle in degrees, or 0.
        heading: Effective heading angle in degrees, or 0.
        reason: Short human-readable explanation for logs/report.
    """

    apply: bool
    pitch: float
    roll: float
    heading: float
    reason: str


def decide(
    gpano: GPanoMetadata | None,
    *,
    mode: HorizonMode,
    min_angle_degrees: float,
    pitch_offset: float = 0.0,
    roll_offset: float = 0.0,
    heading_offset: float = 0.0,
    override_metadata: bool = False,
) -> HorizonDecision:
    """Decide whether to correct horizon for a panorama and with what angles.

    Args:
        gpano: GPano metadata from the source file, or None.
        mode: "auto" (only when angles exceed threshold), "always" (whenever
            non-zero pose data or manual offsets are available), "never".
        min_angle_degrees: Threshold for the "auto" mode.
        pitch_offset: Extra pitch added to metadata value (degrees).
        roll_offset: Extra roll added.
        heading_offset: Extra heading added.
        override_metadata: When True, metadata pose is ignored and only the
            offsets are used. Useful for files with missing or wrong tags.

    Returns:
        HorizonDecision describing the chosen action.
    """
    if mode == "never":
        return HorizonDecision(False, 0.0, 0.0, 0.0, "mode=never")

    meta_pitch = 0.0 if override_metadata or gpano is None else (gpano.pose_pitch or 0.0)
    meta_roll = 0.0 if override_metadata or gpano is None else (gpano.pose_roll or 0.0)
    meta_heading = 0.0 if override_metadata or gpano is None else (gpano.pose_heading or 0.0)

    pitch = meta_pitch + pitch_offset
    roll = meta_roll + roll_offset
    heading = meta_heading + heading_offset

    projection = gpano.projection_type if gpano is not None else None
    if projection is not None and projection.lower() != "equirectangular":
        return HorizonDecision(False, pitch, roll, heading, f"projection={projection}")

    has_pose = gpano is not None and any(
        v is not None for v in (gpano.pose_pitch, gpano.pose_roll, gpano.pose_heading)
    )
    has_offset = pitch_offset != 0.0 or roll_offset != 0.0 or heading_offset != 0.0

    if mode == "always":
        if not has_pose and not has_offset:
            return HorizonDecision(False, 0.0, 0.0, 0.0, "no_pose_data")
        return HorizonDecision(True, pitch, roll, heading, "mode=always")

    # mode == "auto"
    max_angle = max(abs(pitch), abs(roll), abs(heading))
    if max_angle < min_angle_degrees:
        return HorizonDecision(False, pitch, roll, heading, f"below_threshold({max_angle:.2f}<{min_angle_degrees})")
    return HorizonDecision(True, pitch, roll, heading, "mode=auto")


def _rotation_matrix(pitch_deg: float, roll_deg: float, heading_deg: float) -> np.ndarray:
    """Build the world-from-camera rotation matrix from pose angles.

    Angles follow the GPano convention (heading-pitch-roll, applied in that
    order to a level frame). To *undo* the camera tilt we invert the matrix,
    which for a rotation equals its transpose.

    Args:
        pitch_deg: Pitch angle in degrees.
        roll_deg: Roll angle in degrees.
        heading_deg: Heading angle in degrees.

    Returns:
        3x3 inverse rotation matrix (level-frame coords from camera coords).
    """
    pitch = np.deg2rad(pitch_deg)
    roll = np.deg2rad(roll_deg)
    heading = np.deg2rad(heading_deg)

    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)
    ch, sh = np.cos(heading), np.sin(heading)

    # x=forward, y=left, z=up. Building the rotation in cam-from-world form
    # directly: each elementary matrix is the standard right-hand-rule rotation
    # that, when fed the GPano-signed angle, expresses a world vector in the
    # camera frame. GPano sign convention: positive pitch = nose up, positive
    # roll = right wing down, positive heading = clockwise from above.
    rz = np.array([[ch, -sh, 0.0], [sh, ch, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    return rz @ ry @ rx


def correct(
    image: np.ndarray,
    pitch_deg: float,
    roll_deg: float,
    heading_deg: float,
    *,
    interpolation: Interpolation = "bilinear",
) -> np.ndarray:
    """Rotate an equirectangular panorama so the horizon is level.

    Args:
        image: HxWx3 uint8 ndarray in BGR (cv2) order. Width must be 2*height
            for a full sphere; non-2:1 inputs work but will warn.
        pitch_deg: Pose pitch in degrees.
        roll_deg: Pose roll in degrees.
        heading_deg: Pose heading in degrees.
        interpolation: Resampling kernel for the remap.

    Returns:
        Rotated image with the same shape and dtype.
    """
    height, width = image.shape[:2]
    if width != 2 * height:
        logger.warning(
            "Panorama dimensions %dx%d are not 2:1; horizon correction may distort.",
            width,
            height,
        )

    rot = _rotation_matrix(pitch_deg, roll_deg, heading_deg).astype(np.float32)

    # Destination grid -> spherical coords (lon, lat).
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)
    lon = (xs / width) * (2.0 * np.pi) - np.pi  # [-pi, pi)
    lat = (np.pi / 2.0) - (ys / height) * np.pi  # [pi/2, -pi/2)

    lon_grid, lat_grid = np.meshgrid(lon, lat)
    cos_lat = np.cos(lat_grid)
    # Convention: +x forward, +y left, +z up.
    vx = cos_lat * np.cos(lon_grid)
    vy = cos_lat * np.sin(lon_grid)
    vz = np.sin(lat_grid)

    # Rotate destination vectors into the source (tilted) frame.
    sx = rot[0, 0] * vx + rot[0, 1] * vy + rot[0, 2] * vz
    sy = rot[1, 0] * vx + rot[1, 1] * vy + rot[1, 2] * vz
    sz = rot[2, 0] * vx + rot[2, 1] * vy + rot[2, 2] * vz

    src_lat = np.arcsin(np.clip(sz, -1.0, 1.0))
    src_lon = np.arctan2(sy, sx)

    map_x = ((src_lon + np.pi) / (2.0 * np.pi)) * width
    map_y = ((np.pi / 2.0) - src_lat) / np.pi * height

    # Horizontal wrap-around so the seam at lon=+/-pi stays seamless.
    map_x = np.mod(map_x, width).astype(np.float32)
    map_y = np.clip(map_y, 0.0, height - 1.0).astype(np.float32)

    return cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=_INTERP_MAP[interpolation],
        borderMode=cv2.BORDER_WRAP,
    )
