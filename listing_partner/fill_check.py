"""A measured check of a fill, in place of trusting a model's eye on it.

Two readings, per connected part of the mask, on the composited pixels:

Low frequency: the ring of untouched pixels around the mask is split into the
surfaces it crosses (wall, baseboard, floor). Each surface predicts its own part
of the fill from nearby ring pixels, and the fill's averaged brightness and colour
is compared to that. A surface only counts when its ring is flat; one busy or
strongly lit surface reads "not flat" and is not judged, so a pass on such a
surface says nothing.

Specks: small isolated colour marks on an otherwise quiet patch of the fill, at a
higher density than the same detector finds in the untouched ring.

Thresholds were set on the saved fills of commit 4658909 and on clean areas of the
same photos. See the constants for what each was measured against.
"""

from __future__ import annotations

import cv2
import numpy as np

#: A photo's long side over these is the averaging cell and the ring's width.
CELL_SHARE = 500
RING_SHARE = 62
MIN_CELL = 2
MIN_RING = 8
#: Ring cells closer than this in Lab are one surface.
SURFACE_MERGE = 14.0
MAX_SURFACES = 4
#: A fill cell further than this from every surface belongs to none of them.
SURFACE_REACH = 30.0
MIN_RING_CELLS = 8
MIN_FILL_CELLS = 4
MIN_FILL_SHARE = 0.02
#: A surface's ring, 5th to 95th percentile of brightness in 8-bit Lab, over
#: which it is not flat. Clean areas above this read too widely to judge.
FLAT_SPREAD_MAX = 20.0
#: The fixed limit on a reading (90th percentile of the difference from the
#: ring's prediction, worst of L, a, b). A flatter ring earns a tighter limit.
#: Over 3280 clean flat surface patches on 9 photos, 3.6% read over this line.
#: A false alarm costs one retry, or a photo shipped untidied.
LIMIT_BASE = 3.0
LIMIT_PER_SPREAD = 0.6
READING_PERCENTILE = 90

#: Speck sizes in pixels, for photos around 6000 px on the long side.
SPECK_MEDIAN_PX = 31
SPECK_CHROMA = 6.0
SPECK_QUIET = 3.0
SPECK_MIN_AREA = 4
SPECK_MAX_AREA = 120
SPECK_MAX_SIDE = 16
SPECK_WINDOW = 14
SPECK_EDGE_PX = 12


def _ellipse(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)


def _cells(image: np.ndarray, weight: np.ndarray, cell: int) -> tuple:
    """Average only the weighted pixels into cells, so neither side of the mask
    leaks into the other."""
    height, width = weight.shape
    size = (max(1, width // cell), max(1, height // cell))
    share = cv2.resize(weight.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    total = cv2.resize(
        image.astype(np.float32) * weight[..., None].astype(np.float32),
        size,
        interpolation=cv2.INTER_AREA,
    )
    return total / np.maximum(share, 1e-3)[..., None], share


def _surfaces(points: np.ndarray) -> np.ndarray:
    cv2.setRNGSeed(0)
    count = min(MAX_SURFACES, len(points))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, _, centres = cv2.kmeans(
        points.astype(np.float32), count, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    kept: list[np.ndarray] = []
    for centre in centres:
        if all(np.linalg.norm(centre - other) >= SURFACE_MERGE for other in kept):
            kept.append(centre)
    return np.array(kept)


def _nearest(cells: np.ndarray, centres: np.ndarray) -> tuple:
    distance = np.sqrt(((cells[..., None, :] - centres) ** 2).sum(-1))
    which = distance.argmin(-1)
    return which, np.take_along_axis(distance, which[..., None], -1)[..., 0]


def _read_surfaces(before: np.ndarray, after: np.ndarray, part, ring, cell: int) -> list[dict]:
    fill_cells, fill_share = _cells(after, part, cell)
    ring_cells, ring_share = _cells(before, ring, cell)
    fill_ok, ring_ok = fill_share > 0.9, ring_share > 0.9
    if ring_ok.sum() < MIN_RING_CELLS or fill_ok.sum() < MIN_FILL_CELLS:
        return []
    centres = _surfaces(ring_cells[ring_ok])
    ring_which, _ = _nearest(ring_cells, centres)
    fill_which, fill_reach = _nearest(fill_cells, centres)
    rows = []
    for index in range(len(centres)):
        ring_here = ring_ok & (ring_which == index)
        fill_here = fill_ok & (fill_which == index) & (fill_reach < SURFACE_REACH)
        # A cell at a boundary between surfaces is a blend of both.
        fill_here = cv2.erode(fill_here.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        enough = fill_here.sum() >= max(MIN_FILL_CELLS, MIN_FILL_SHARE * fill_ok.sum())
        if ring_here.sum() < MIN_RING_CELLS or not enough:
            continue
        brightness = ring_cells[ring_here][:, 0]
        spread = float(np.percentile(brightness, 95) - np.percentile(brightness, 5))
        row = {"spread": round(spread, 1), "fill_cells": int(fill_here.sum()), "flat": False}
        if spread <= FLAT_SPREAD_MAX:
            fy, fx = np.nonzero(fill_here)
            ry, rx = np.nonzero(ring_here)
            distance = np.hypot(fy[:, None] - ry[None], fx[:, None] - rx[None])
            weight = 1.0 / np.maximum(distance, 0.5) ** 3
            predicted = (weight @ ring_cells[ring_here].astype(np.float64)) / weight.sum(
                1, keepdims=True
            )
            difference = np.abs(fill_cells[fill_here] - predicted)
            reading = float(np.percentile(difference, READING_PERCENTILE, axis=0).max())
            row.update(
                flat=True,
                reading=round(reading, 1),
                limit=round(LIMIT_BASE + LIMIT_PER_SPREAD * spread, 1),
            )
        rows.append(row)
    return rows


def _chroma_residual(lab: np.ndarray) -> np.ndarray:
    median = cv2.medianBlur(lab, SPECK_MEDIAN_PX)
    return np.sqrt(((lab[..., 1:].astype(np.float32) - median[..., 1:]) ** 2).sum(-1))


def _count_specks(residual: np.ndarray, region: np.ndarray) -> int:
    marks = ((residual > SPECK_CHROMA) & region).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(marks, connectivity=8)
    specks = 0
    for index in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[index])
        if not SPECK_MIN_AREA <= area <= SPECK_MAX_AREA or max(width, height) > SPECK_MAX_SIDE:
            continue
        top, left = max(0, y - SPECK_WINDOW), max(0, x - SPECK_WINDOW)
        bottom, right = y + height + SPECK_WINDOW, x + width + SPECK_WINDOW
        own = cv2.dilate((labels[top:bottom, left:right] == index).astype(np.uint8), _ellipse(3))
        around = region[top:bottom, left:right] & (own == 0)
        if around.sum() < 0.5 * around.size:
            continue
        if np.percentile(residual[top:bottom, left:right][around], 98) < SPECK_QUIET:
            specks += 1
    return specks


def _read_specks(before: np.ndarray, after: np.ndarray, part, ring) -> dict:
    inner = cv2.erode(part.astype(np.uint8), _ellipse(SPECK_EDGE_PX)) > 0
    fill = _count_specks(_chroma_residual(after), inner) if inner.any() else 0
    around = _count_specks(_chroma_residual(before), ring) if ring.any() else 0
    # A speck the surroundings also show, at the same density, is the surface.
    denser = fill / max(1, int(inner.sum())) > around / max(1, int(ring.sum()))
    return {"fill": fill, "ring": around, "flagged": fill if denser else 0}


def check_fill(finished: np.ndarray, tidied: np.ndarray, mask: np.ndarray) -> dict:
    """The readings for one composited photo. Passes only if every flat surface
    is within its limit and no speck is flagged."""
    height, width = mask.shape
    long_side = max(height, width)
    cell = max(MIN_CELL, long_side // CELL_SHARE)
    ring_px = max(MIN_RING, long_side // RING_SHARE)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    areas = []
    for index in range(1, count):
        x, y, w, h = (int(v) for v in stats[index][:4])
        pad = ring_px + 2 * cell
        left, top = max(0, x - pad), max(0, y - pad)
        right, bottom = min(width, x + w + pad), min(height, y + h + pad)
        part = labels[top:bottom, left:right] == index
        ring = (cv2.dilate(part.astype(np.uint8), _ellipse(ring_px)) > 0) & ~(
            mask[top:bottom, left:right]
        )
        before = _lab(finished[top:bottom, left:right])
        after = _lab(tidied[top:bottom, left:right])
        surfaces = _read_surfaces(before, after, part, ring, cell)
        specks = _read_specks(before, after, part, ring)
        over = any(s["flat"] and s["reading"] > s["limit"] for s in surfaces)
        areas.append(
            {
                "box": [x, y, x + w, y + h],
                "surfaces": surfaces,
                "specks": specks,
                "pass": not over and not specks["flagged"],
            }
        )
    flat = [s for area in areas for s in area["surfaces"] if s["flat"]]
    worst = max(flat, key=lambda s: s["reading"] - s["limit"], default=None)
    return {
        "pass": all(area["pass"] for area in areas),
        "flat_surfaces": len(flat),
        "not_flat_surfaces": sum(not s["flat"] for area in areas for s in area["surfaces"]),
        "worst_reading": worst["reading"] if worst else None,
        "worst_limit": worst["limit"] if worst else None,
        "specks": sum(area["specks"]["flagged"] for area in areas),
        "areas": areas,
    }
