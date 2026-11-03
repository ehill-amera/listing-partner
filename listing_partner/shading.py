"""A smooth shading correction inside a fill, before the fill is measured.

Navigator decision (Nov 2): a generated fill often carries a broad brightness or
colour drift that the photo around it does not have. Inside the mask only, the
fill's low-frequency brightness and colour are pulled toward what the ring of
untouched pixels around the mask predicts for that spot. The correction fades to
zero at the mask's edge and never writes a pixel outside the mask. Detail finer
than the smoothing scale is left exactly as Muse Image made it, so a blotch or a
speck stays for the fill check and Muse Spark to judge.

The ring is split into the surfaces it crosses (wall, baseboard, floor), so one
surface's colour is never pulled into another. A fill pixel takes the correction
of the surface it already resembles, and a pixel that resembles none is left alone.
"""

from __future__ import annotations

import cv2
import numpy as np

#: The same scale as the fill check's ring: a photo's long side over these.
CELL_SHARE = 500
RING_SHARE = 62
MIN_CELL = 2
MIN_RING = 8
#: Smoothing scale, in ring widths. Shading broader than this is corrected;
#: anything finer is kept as generated.
SIGMA_RINGS = 1.0
#: The correction rises from zero at the mask edge to full over this many ring widths.
FEATHER_RINGS = 0.5
#: Ring cells closer than this in Lab are one surface; a fill cell further than
#: SURFACE_REACH from every surface belongs to none and is not corrected.
SURFACE_MERGE = 14.0
MAX_SURFACES = 4
SURFACE_REACH = 30.0
MIN_RING_CELLS = 8
#: Below this share of kernel weight, a smoothed value is not trusted.
MIN_WEIGHT = 1e-4


def _ellipse(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    """Lab on the 8-bit scale the fill check reads (L 0 to 255)."""
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    lab[..., 0] *= 255.0 / 100.0
    return lab


def _to_rgb(lab: np.ndarray) -> np.ndarray:
    lab = lab.copy()
    lab[..., 0] *= 100.0 / 255.0
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)


def _cells(image: np.ndarray, weight: np.ndarray, cell: int) -> tuple:
    height, width = weight.shape
    size = (max(1, width // cell), max(1, height // cell))
    share = cv2.resize(weight.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    total = cv2.resize(
        image * weight[..., None].astype(np.float32), size, interpolation=cv2.INTER_AREA
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


def _smooth(values: np.ndarray, where: np.ndarray, sigma: float) -> tuple:
    """Normalised Gaussian average of values over the cells in where."""
    weight = where.astype(np.float64)
    blur = lambda a: cv2.GaussianBlur(a, (0, 0), sigma, borderType=cv2.BORDER_CONSTANT)  # noqa: E731
    total = np.stack([blur(values[..., c] * weight) for c in range(3)], axis=-1)
    share = blur(weight)
    return total / np.maximum(share, 1e-12)[..., None], share


def _part_delta(before, after, part, ring, cell: int, sigma_cells: float) -> np.ndarray:
    """The Lab shift, per cell, that the fill in this part needs. Zero where no
    surface is trusted."""
    fill_cells, fill_share = _cells(after, part, cell)
    ring_cells, ring_share = _cells(before, ring, cell)
    fill_ok, ring_ok = fill_share > 0.5, ring_share > 0.5
    delta = np.zeros_like(fill_cells, dtype=np.float64)
    if ring_ok.sum() < MIN_RING_CELLS or not fill_ok.any():
        return delta
    centres = _surfaces(ring_cells[ring_ok])
    ring_which, _ = _nearest(ring_cells, centres)
    fill_which, fill_reach = _nearest(fill_cells, centres)
    # A fill cell's colour is what may be wrong, so colour alone cannot place it.
    # It is placed only where its colour agrees with the surface of the ring cell
    # nearest to it in the photo; where the two disagree, it is left alone.
    ring_mask = (ring_ok == 0).astype(np.uint8)
    _, nearest_index = cv2.distanceTransformWithLabels(
        ring_mask, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )
    by_label = np.zeros(nearest_index.max() + 1, dtype=np.int64)
    zeros = np.argwhere(ring_mask == 0)
    seed_labels = nearest_index[zeros[:, 0], zeros[:, 1]]
    by_label[seed_labels] = ring_which[zeros[:, 0], zeros[:, 1]]
    place = by_label[nearest_index]
    for index in range(len(centres)):
        ring_here = ring_ok & (ring_which == index)
        fill_here = fill_ok & (fill_which == index) & (fill_reach < SURFACE_REACH)
        fill_here &= place == index
        if ring_here.sum() < MIN_RING_CELLS or not fill_here.any():
            continue
        # Widen the scale until the ring reaches every fill cell of this surface.
        target, reach = _smooth(ring_cells.astype(np.float64), ring_here, sigma_cells)
        scale = sigma_cells
        while (reach[fill_here] < MIN_WEIGHT).any() and scale < 8 * max(part.shape):
            scale *= 1.5
            wider, wide_reach = _smooth(ring_cells.astype(np.float64), ring_here, scale)
            short = reach < MIN_WEIGHT
            target[short], reach[short] = wider[short], wide_reach[short]
        current, _ = _smooth(fill_cells.astype(np.float64), fill_here, sigma_cells)
        delta[fill_here] = (target - current)[fill_here]
    # Soften the seams between surfaces at the scale of one cell.
    return cv2.GaussianBlur(delta, (0, 0), 1.0)


def correct(finished: np.ndarray, tidied: np.ndarray, mask: np.ndarray) -> tuple:
    """(corrected composite, readings). Only pixels inside the mask change, and
    the change is zero on the mask's edge."""
    height, width = mask.shape
    long_side = max(height, width)
    cell = max(MIN_CELL, long_side // CELL_SHARE)
    ring_px = max(MIN_RING, long_side // RING_SHARE)
    sigma_cells = SIGMA_RINGS * ring_px / cell
    feather = max(1.0, FEATHER_RINGS * ring_px)
    out = tidied.copy()
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
        before = _to_lab(finished[top:bottom, left:right])
        after = _to_lab(tidied[top:bottom, left:right])
        delta = _part_delta(before, after, part, ring, cell, sigma_cells)
        crop_h, crop_w = part.shape
        field = cv2.resize(delta, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
        # Zero on the edge pixels (distance 1), full a feather's width in.
        inside = cv2.distanceTransform(part.astype(np.uint8), cv2.DIST_L2, 5)
        weight = np.clip((inside - 1.0) / feather, 0.0, 1.0)
        weight[~part] = 0.0
        shift = (field * weight[..., None]).astype(np.float32)
        rgb = _to_rgb(after + shift)
        # Only pixels given a shift are written, so a zero shift is not a round trip.
        moved = part & (np.abs(shift).max(-1) > 0)
        region = out[top:bottom, left:right]
        region[moved] = rgb[moved]
        applied = field[moved] if moved.any() else np.zeros((1, 3))
        areas.append(
            {
                "box": [x, y, x + w, y + h],
                # Share of this part's pixels given any shift. The rest, a fill
                # whose colour matched no surface where it sits, is as generated.
                "corrected_share": round(float(moved.sum()) / max(1, int(part.sum())), 3),
                # Largest shift applied, in the fill check's 8-bit Lab units.
                "max_shift": [round(float(np.abs(applied[:, c]).max()), 1) for c in range(3)],
            }
        )
    worst = [max((a["max_shift"][c] for a in areas), default=0.0) for c in range(3)]
    share = min((a["corrected_share"] for a in areas), default=0.0)
    return out, {"areas": areas, "max_shift_lab": worst, "least_corrected_share": share}
