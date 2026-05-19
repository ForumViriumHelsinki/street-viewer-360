"""Tests for horizon correction math and decision logic."""

from __future__ import annotations

import numpy as np
import pytest

from street_viewer_360 import horizon
from street_viewer_360.metadata import GPanoMetadata


def _make_equirect(width: int, height: int, horizon_row: int) -> np.ndarray:
    """Build a synthetic ERP: white sky above ``horizon_row``, black below."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:horizon_row, :, :] = 255
    return image


def test_decide_never_returns_no_op() -> None:
    d = horizon.decide(None, mode="never", min_angle_degrees=0.2)
    assert d.apply is False


def test_decide_auto_below_threshold() -> None:
    g = GPanoMetadata("equirectangular", pose_pitch=0.1, pose_roll=-0.05, pose_heading=0.0)
    d = horizon.decide(g, mode="auto", min_angle_degrees=0.2)
    assert d.apply is False
    assert "below_threshold" in d.reason


def test_decide_auto_above_threshold() -> None:
    g = GPanoMetadata("equirectangular", pose_pitch=-13.4, pose_roll=0.0, pose_heading=0.0)
    d = horizon.decide(g, mode="auto", min_angle_degrees=0.2)
    assert d.apply is True
    assert d.pitch == pytest.approx(-13.4)


def test_decide_skips_non_equirectangular() -> None:
    g = GPanoMetadata("cubemap", pose_pitch=-20.0, pose_roll=0.0, pose_heading=0.0)
    d = horizon.decide(g, mode="always", min_angle_degrees=0.2)
    assert d.apply is False
    assert "projection" in d.reason


def test_decide_offsets_can_trigger_without_metadata() -> None:
    d = horizon.decide(
        None,
        mode="auto",
        min_angle_degrees=0.2,
        pitch_offset=-10.0,
    )
    assert d.apply is True
    assert d.pitch == pytest.approx(-10.0)


def test_decide_override_metadata_ignores_pose() -> None:
    g = GPanoMetadata("equirectangular", pose_pitch=-13.4, pose_roll=0.0, pose_heading=0.0)
    d = horizon.decide(
        g,
        mode="always",
        min_angle_degrees=0.2,
        pitch_offset=5.0,
        override_metadata=True,
    )
    assert d.apply is True
    assert d.pitch == pytest.approx(5.0)


def test_correct_identity_when_all_zero() -> None:
    img = _make_equirect(64, 32, horizon_row=16)
    out = horizon.correct(img, pitch_deg=0.0, roll_deg=0.0, heading_deg=0.0)
    # Bilinear remap of a perfectly flat image with zero rotation should round-trip
    # to the same content (allowing a 1-px tolerance at the wrap seam).
    assert out.shape == img.shape
    assert np.array_equal(out[:, 1:-1, :], img[:, 1:-1, :])


def test_correct_negative_pitch_moves_horizon_down() -> None:
    # Source has horizon row at 8 (out of 32) -> horizon sits at lat ~+45 deg.
    # That's the same effect a camera pitched -45deg would produce. Correcting
    # it should bring the horizon down toward the centre row.
    height = 64
    width = 128
    horizon_row_in_source = height // 4  # at +45 deg latitude
    img = _make_equirect(width, height, horizon_row=horizon_row_in_source)

    out = horizon.correct(img, pitch_deg=-45.0, roll_deg=0.0, heading_deg=0.0)

    # In the corrected image, the horizon at the centre column should be near
    # the middle row. Check a column at lon=0 (centre).
    col = out[:, width // 2, 0]
    transitions = np.where(np.diff(col.astype(int)) < 0)[0]
    assert len(transitions) >= 1
    horizon_after = int(transitions[0])
    # Allow a few pixels of slack; centre row is height/2.
    assert abs(horizon_after - height // 2) <= 3
