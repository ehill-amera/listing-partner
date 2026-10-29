"""Pipeline seam tests: build_inputs carries undistort validity to the crop."""

import glob
from pathlib import Path

import numpy as np

from listing_partner import geometry, hdr, run_finish


def _synthetic_frame(height=120, width=160):
    rows = np.linspace(40, 180, height, dtype=np.float64)[:, None]
    frame = np.repeat(rows, width, axis=1)
    frame[30:70, 60:110] = 220.0  # bright rectangle, a fake window
    return np.stack([frame, frame, frame], axis=-1).astype(np.uint8)


def test_build_inputs_keeps_undistort_invalid_out(monkeypatch):
    """Undistort-invalid borders must reach state['valid'] (and the crop).

    Only the pixel decode is stubbed (the far side); EXIF, the real lens
    profile, the real displacement math and the real combination run.
    Strength is fixed so the invalid-border path is deterministic.
    """
    members = [Path(p) for p in sorted(glob.glob("inputs/unit-a/raw/*.NEF"))[:5]]
    assert len(members) == 5
    fake = _synthetic_frame()
    monkeypatch.setattr(hdr, "decode_frame", lambda path: fake.copy())
    monkeypatch.setattr(geometry, "fit_strength", lambda gray, profile, focal: 0.5)

    record: dict = {"index": 1, "name": "001", "notes": []}
    state = run_finish.build_inputs(members, None, record)

    valid = state["valid"]
    assert valid.shape == fake.shape[:2]
    assert not valid.all(), "no invalid pixels: undistort validity was dropped"
    assert not valid[0, :].all(), "top border kept valid pixels it cannot have"
    assert not valid[-1, :].all(), "bottom border kept valid pixels it cannot have"
    assert not valid[:, 0].all(), "left border kept valid pixels it cannot have"
    assert not valid[:, -1].all(), "right border kept valid pixels it cannot have"
    assert record["distortion_strength"]
