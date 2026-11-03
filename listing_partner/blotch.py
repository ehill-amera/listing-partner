"""A local check for a mark a fill leaves on a surface, after the shading correction.

The fill check reads a fill at the scale of the ring and broader, and the shading
correction removes drift at that scale. A mark narrower than one ring width, such
as the gray smudge home-a 008's fill left where the basket's handles had been,
passes both. This check reads at that finer scale.

Per connected part of the mask: the ring of untouched pixels is split into the
surfaces it crosses, the way the fill check and the shading correction split it,
and only surfaces whose ring is flat are judged. A fill pixel is judged when its
colour and its position both place it on that surface, it sits away from the
mask's edge, and no sharp edge (a baseboard line, a rebuilt furniture edge) is
near it. Its brightness, lightly blurred, is compared to what the ring of that
surface predicts for that spot. A connected spot darker or lighter than the
prediction by more than MARK_LEVELS, over at least MIN_AREA pixels, fails the fill.

Thresholds were set on the fill 386a564 shipped for home-a 008 and on clean
controls. See the constants for what each was measured against.
"""

from __future__ import annotations

import cv2
import numpy as np

from listing_partner import shading

#: The fill check's scale: a photo's long side over these.
CELL_SHARE = 500
RING_SHARE = 62
MIN_CELL = 2
MIN_RING = 8
#: Sizes below are for a photo 6000 px on its long side, and scale with it.
REFERENCE_LONG_SIDE = 6000.0
#: The light blur on the fill before it is compared, in pixels.
BLUR_PX = 4.0
#: Brightness change per pixel, after the blur, that makes a sharp edge. Pixels
#: within EDGE_PAD_PX of one are not judged: a real edge is not a mark.
EDGE_LEVELS_PER_PX = 1.0
EDGE_PAD_PX = 12
#: Pixels this close to the mask's edge are not judged; the feathered composite
#: and the ring meet there.
MASK_EDGE_PX = 12
#: A ring whose brightness spreads wider than this (5th to 95th percentile, 8-bit
#: Lab) is not flat, and its surface is not judged. The same line as the fill check.
FLAT_SPREAD_MAX = 20.0
#: Ring cells closer than this in Lab are one surface; a fill cell further than
#: SURFACE_REACH from every surface belongs to none of them.
MIN_RING_CELLS = 8
SURFACE_REACH = 30.0
MIN_WEIGHT = 1e-4
#: A spot fails when it is this many levels (8-bit Lab L) darker or lighter than
#: the ring's prediction, over at least MIN_AREA connected pixels.
#: Measured on 386a564's home-a 008 fill: the mark is 1,893 px past 8 levels and
#: 12.6 levels at its deepest, at the reviewer's core; nothing else on that fill
#: reaches the line (48.5% of the fill judged). The same spot is 1,324 px past 9
#: levels and 868 px past 10.
#: Clean controls, the finished photo against itself after the shading
#: correction, under 300 clutter-sized ellipses placed at random on the 8 home-a
#: and 17 unit-a finished photos: 11 trip this line (3.7%), 3 of the 79 that lie
#: mostly on judged flat surface. Looked at, such hits are real soft shading the
#: ring does not show: a ceiling corner, a shadow under a wall sign. A false alarm
#: costs a retry, or a photo shipped untidied.
#: The fills 386a564 shipped on home-a 003 (tile) and unit-a 016 (siding) had 0%
#: of the fill judged, no flat surface, so their passing says nothing about them.
MARK_LEVELS = 8.0
MIN_AREA = 600


def _ellipse(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _placed(ring_ok: np.ndarray, ring_which: np.ndarray) -> np.ndarray:
    """Per cell, the surface of the nearest ring cell in the photo: the same
    placement the shading correction uses, so a colour alone never places a cell."""
    ring_mask = (ring_ok == 0).astype(np.uint8)
    _, nearest_index = cv2.distanceTransformWithLabels(
        ring_mask, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )
    by_label = np.zeros(nearest_index.max() + 1, dtype=np.int64)
    zeros = np.argwhere(ring_mask == 0)
    by_label[nearest_index[zeros[:, 0], zeros[:, 1]]] = ring_which[zeros[:, 0], zeros[:, 1]]
    return by_label[nearest_index]


def _prediction(ring_cells, ring_here, fill_here, sigma_cells: float, longest: int):
    """The ring's brightness for this surface, smoothed out over the fill, widened
    until it reaches every fill cell of the surface."""
    target, reach = shading._smooth(ring_cells.astype(np.float64), ring_here, sigma_cells)
    scale = sigma_cells
    while (reach[fill_here] < MIN_WEIGHT).any() and scale < 8 * longest:
        scale *= 1.5
        wider, wide_reach = shading._smooth(ring_cells.astype(np.float64), ring_here, scale)
        short = reach < MIN_WEIGHT
        target[short], reach[short] = wider[short], wide_reach[short]
    return target[..., 0]


def _spots(deviation: np.ndarray, judged: np.ndarray, min_area: int, origin: tuple) -> list:
    left, top = origin
    spots = []
    for sign, kind in ((-1.0, "dark"), (1.0, "light")):
        marked = (judged & (sign * deviation > MARK_LEVELS)).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(marked, connectivity=8)
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if area < min_area:
                continue
            depth = float((sign * deviation)[labels == index].max())
            spots.append(
                {
                    "kind": kind,
                    "area": area,
                    "depth": round(depth, 1),
                    "box": [x + left, y + top, x + w + left, y + h + top],
                }
            )
    return spots


def check_marks(finished: np.ndarray, tidied: np.ndarray, mask: np.ndarray) -> dict:
    """The readings for one corrected composite. Passes only if no judged
    surface carries a spot past the line."""
    height, width = mask.shape
    long_side = max(height, width)
    scale = long_side / REFERENCE_LONG_SIDE
    cell = max(MIN_CELL, long_side // CELL_SHARE)
    ring_px = max(MIN_RING, long_side // RING_SHARE)
    sigma_cells = ring_px / cell
    min_area = max(1, int(round(MIN_AREA * scale * scale)))
    blur = max(0.5, BLUR_PX * scale)
    edge_pad = max(1, int(round(EDGE_PAD_PX * scale)))
    mask_edge = max(1, int(round(MASK_EDGE_PX * scale)))
    # A smaller photo carries the same edge over fewer pixels, so a steeper slope.
    edge_levels = EDGE_LEVELS_PER_PX / scale
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
        before = shading._to_lab(finished[top:bottom, left:right])
        after = shading._to_lab(tidied[top:bottom, left:right])
        judged = np.zeros(part.shape, bool)
        deviation = np.zeros(part.shape, np.float32)
        surfaces = []
        fill_cells, fill_share = shading._cells(after, part, cell)
        ring_cells, ring_share = shading._cells(before, ring, cell)
        fill_ok, ring_ok = fill_share > 0.5, ring_share > 0.5
        if ring_ok.sum() >= MIN_RING_CELLS and fill_ok.any():
            centres = shading._surfaces(ring_cells[ring_ok])
            ring_which, _ = shading._nearest(ring_cells, centres)
            fill_which, fill_reach = shading._nearest(fill_cells, centres)
            place = _placed(ring_ok, ring_which)
            light = cv2.GaussianBlur(after[..., 0], (0, 0), blur)
            gx = cv2.Sobel(light, cv2.CV_32F, 1, 0, ksize=3) / 8.0
            gy = cv2.Sobel(light, cv2.CV_32F, 0, 1, ksize=3) / 8.0
            edges = (np.hypot(gx, gy) > edge_levels).astype(np.uint8)
            near_edge = cv2.dilate(edges, _ellipse(edge_pad)) > 0
            inner = cv2.erode(part.astype(np.uint8), _ellipse(mask_edge)) > 0
            crop_h, crop_w = part.shape
            for which in range(len(centres)):
                ring_here = ring_ok & (ring_which == which)
                fill_here = fill_ok & (fill_which == which) & (fill_reach < SURFACE_REACH)
                fill_here &= place == which
                # A cell at a boundary between surfaces is a blend of both.
                fill_here = cv2.erode(fill_here.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
                if ring_here.sum() < MIN_RING_CELLS or not fill_here.any():
                    continue
                brightness = ring_cells[ring_here][:, 0]
                spread = float(np.percentile(brightness, 95) - np.percentile(brightness, 5))
                flat = spread <= FLAT_SPREAD_MAX
                surfaces.append({"spread": round(spread, 1), "flat": flat})
                if not flat:
                    continue
                target = _prediction(ring_cells, ring_here, fill_here, sigma_cells, max(part.shape))
                target = cv2.resize(
                    target.astype(np.float32), (crop_w, crop_h), interpolation=cv2.INTER_LINEAR
                )
                on_surface = (
                    cv2.resize(
                        fill_here.astype(np.uint8),
                        (crop_w, crop_h),
                        interpolation=cv2.INTER_NEAREST,
                    )
                    > 0
                )
                here = on_surface & part & inner & ~near_edge
                deviation[here] = (light - target)[here]
                judged |= here
        spots = _spots(deviation, judged, min_area, (left, top))
        areas.append(
            {
                "box": [x, y, x + w, y + h],
                "judged_share": round(float(judged.sum()) / max(1, int(part.sum())), 3),
                "surfaces": surfaces,
                "spots": spots,
                "pass": not spots,
            }
        )
    spots = [s for area in areas for s in area["spots"]]
    worst = max(spots, key=lambda s: s["depth"], default=None)
    return {
        "pass": all(area["pass"] for area in areas),
        "spots": len(spots),
        "worst_depth": worst["depth"] if worst else None,
        "worst_area": worst["area"] if worst else None,
        "limit_levels": MARK_LEVELS,
        "min_area": min_area,
        "judged_share": min((a["judged_share"] for a in areas), default=0.0),
        "areas": areas,
    }
