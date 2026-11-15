"""Calibrate the P1S chamber camera from a large checkerboard (10 mm squares), e.g. one covering the bed.

Two ways, best first:
  1. tilted frames: raw frames of the board held at different angles fix the lens (focal length,
     distortion, optical centre); a frame of the board lying flat at a known bed Z then fixes the pose.
  2. fallback, flat frames only: >= 2 frames of the board lying flat, at two known bed Z heights. The
     lens is then fitted from the flat frames with the optical centre held at the image centre.
With >= 2 flat frames the camera's fitted height above the board must change by exactly the Z
difference (the bed moves, the camera does not), which checks the Z values and the moving-bed model.

The board need not be fully visible: corners are found with a ChESS X-corner detector and a grid grown
outward from a seed, so partial and steeply tilted views work. The first flat frame is tied to bed
coordinates by >= 2 board corners clicked at known bed X,Y ("markers", same click page as calibrate-bed).
"""
import itertools
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from . import config as C
from .calib_offline import nominal_focal_px
from .camera import BedCamera

MAX_RMS_PX = 2.0          # corner reprojection error accepted for the lens fit (MJPEG frames)
Z_TOL_MM = 1.5            # height change vs bed Z change
MIN_CORNERS = 40          # corners a frame needs to be used
MIN_TILTED = 3            # tilted frames needed before they are preferred over the flat-only fallback


# ---------------- corner detection ----------------
def _chess(g, r):
    """ChESS X-corner response on a ring of 16 samples of radius r (Bennett & Lasenby 2014)."""
    h, w = g.shape
    ring = []
    for a in np.arange(16) * 2 * np.pi / 16:
        M = np.float32([[1, 0, -r * np.cos(a)], [0, 1, -r * np.sin(a)]])
        ring.append(cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT))
    I = np.stack(ring)
    sum_r = sum(np.abs(I[n] + I[n + 8] - I[n + 4] - I[n + 12]) for n in range(4))
    diff_r = sum(np.abs(I[n] - I[n + 8]) for n in range(8))
    return sum_r - diff_r - 16 * np.abs(I.mean(0) - cv2.blur(g, (3, 3)))


def find_x_corners(gray, radii=(3, 5, 8), rel=0.08):
    """Sub-pixel checkerboard X-corners anywhere in the image -> (N, 2) float32."""
    g = cv2.GaussianBlur(gray.astype(np.float32) / 255.0, (0, 0), 0.8)
    R = np.max([_chess(g, r) for r in radii], 0)
    R[R < 0] = 0
    if R.max() <= 0:
        return np.zeros((0, 2), np.float32)
    peak = (R == cv2.dilate(R, np.ones((7, 7), np.uint8))) & (R > rel * R.max())
    ys, xs = np.nonzero(peak)
    order = np.argsort(-R[ys, xs])
    pts = np.c_[xs[order], ys[order]].astype(np.float32).reshape(-1, 1, 2)
    if len(pts):
        pts = cv2.cornerSubPix(gray, pts, (3, 3), (-1, -1),
                               (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01))
    return pts.reshape(-1, 2)


def _gradient(gray):
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.2)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def _at(img, q):
    return img[int(np.clip(q[1], 0, img.shape[0] - 1)), int(np.clip(q[0], 0, img.shape[1] - 1))]


def _edge_strength(grad, p, q):
    """Gradient along the segment p-q at 1/4, 1/2 and 3/4 (weakest). High only if p-q is a square edge: a
    diagonal crosses square centres and a knight move (2 by 1 squares) crosses a square at 1/4 and 3/4."""
    return min(_at(grad, p + f * (q - p)) for f in (0.25, 0.5, 0.75))


def _grow(pts, tree, i0, grad):
    """Index the corners around pts[i0] on a lattice by repeated local-homography prediction."""
    p0 = pts[i0]
    _, nn = tree.query(p0, k=min(9, len(pts)))
    nb = pts[nn[1:]] - p0
    best = None
    for a, b in itertools.permutations(nb, 2):
        if abs(a[0] * b[1] - a[1] * b[0]) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9) < 0.3:
            continue
        # a, b should be square edges: on a light/dark boundary all along, the square centre flat
        if min(_edge_strength(grad, p0, p0 + a), _edge_strength(grad, p0, p0 + b)) < 2.0 * _at(grad, p0 + (a + b) / 2):
            continue
        err = tree.query(p0 + a + b)[0] + tree.query(p0 - a)[0] + tree.query(p0 - b)[0]
        if best is None or err < best[0]:
            best = (err, a, b)
    if best is None or best[0] > 0.3 * min(np.linalg.norm(best[1]), np.linalg.norm(best[2])) * 3:
        return {}
    _, a, b = best
    grid, used = {}, set()
    for ij, v in (((0, 0), 0 * a), ((1, 0), a), ((0, 1), b), ((1, 1), a + b), ((-1, 0), -a), ((0, -1), -b)):
        k = tree.query(p0 + v)[1]
        if k in used:
            return {}
        grid[ij] = pts[k]
        used.add(k)
    grew = True
    while grew:
        grew = False
        known = np.array(list(grid)); P = np.array([grid[tuple(k)] for k in known])
        cand = {(i + di, j + dj) for (i, j) in grid for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))} - set(grid)
        for (i, j) in cand:
            dist = np.abs(known - [i, j]).sum(1)
            near = np.argsort(dist)[:12]
            near = near[dist[near] <= 4]
            pred = None
            if len(near) >= 4 and len(set(known[near][:, 0])) > 1 and len(set(known[near][:, 1])) > 1:
                H, _ = cv2.findHomography(known[near].astype(np.float32), P[near].astype(np.float32), 0)
                if H is not None:
                    q = H @ [i, j, 1.0]
                    pred = q[:2] / q[2]
            if pred is None:
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if (i - di, j - dj) in grid and (i - 2 * di, j - 2 * dj) in grid:
                        pred = 2 * grid[(i - di, j - dj)] - grid[(i - 2 * di, j - 2 * dj)]
                        break
            if pred is None or not np.all(np.isfinite(pred)):
                continue
            nbrs = [grid[k] for k in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)) if k in grid]
            sp = min(np.linalg.norm(pred - n) for n in nbrs)
            if sp < 5:
                continue
            d, k = tree.query(pred)
            if d < 0.3 * sp and k not in used:
                grid[(i, j)] = pts[k]
                used.add(k)
                grew = True
    return grid


def _fix_axes(grid, grad):
    """The grown lattice can use a diagonal or a knight move as an axis. Re-index so both axes are square
    edges: only the segment between two corners one edge apart lies on a light/dark boundary all along."""
    score = {}
    for e in [e for e in itertools.product(range(-3, 4), repeat=2) if e > (0, 0) and np.gcd(*e) == 1]:
        v = [_edge_strength(grad, p, grid[(k[0] + e[0], k[1] + e[1])])
             for k, p in grid.items() if (k[0] + e[0], k[1] + e[1]) in grid]
        if len(v) >= 10:
            score[e] = float(np.median(v))
    ranked = sorted(score, key=score.get, reverse=True)
    if not ranked:
        return grid
    e1 = ranked[0]
    e2 = next((e for e in ranked[1:] if abs(e1[0] * e[1] - e1[1] * e[0]) == 1), None)
    if e2 is None:
        return grid
    inv = np.linalg.inv(np.array([e1, e2], float).T)
    return {tuple(int(round(c)) for c in inv @ k): p for k, p in grid.items()}


def _clean(grid, tol=0.3):
    """Drop corners their neighbours disagree with (local homography), then keep the largest part connected by
    consistent links."""
    for _ in range(2):
        keys = list(grid)
        K = np.array(keys)
        drop = set()
        for k in keys:
            d = np.abs(K - k).sum(1)
            nb = [tuple(K[i]) for i in np.nonzero((d > 0) & (d <= 2))[0]]
            if len(nb) < 5:
                continue
            H, _ = cv2.findHomography(np.array(nb, np.float32), np.array([grid[n] for n in nb], np.float32), 0)
            if H is None:
                continue
            q = H @ [k[0], k[1], 1.0]
            sp = min(np.linalg.norm(grid[n] - grid[k]) for n in nb if abs(n[0] - k[0]) + abs(n[1] - k[1]) == 1) \
                if any(abs(n[0] - k[0]) + abs(n[1] - k[1]) == 1 for n in nb) else None
            if sp and np.linalg.norm(q[:2] / q[2] - grid[k]) > tol * sp:
                drop.add(k)
        grid = {k: v for k, v in grid.items() if k not in drop}
    # links between index neighbours must look like the other links in that direction nearby; a corner
    # skipped during growth makes a link about twice as long and shifts the indices of everything past it
    links = {}
    for e in ((1, 0), (0, 1)):
        vec = {k: grid[(k[0] + e[0], k[1] + e[1])] - grid[k] for k in grid if (k[0] + e[0], k[1] + e[1]) in grid}
        keys = list(vec)
        if not keys:
            continue
        K = np.array(keys)
        V = np.array([vec[k] for k in keys])
        for n, k in enumerate(keys):
            d = np.abs(K - k).sum(1)
            near = np.nonzero((d > 0) & (d <= 3))[0]
            if len(near) < 3:
                continue
            ref = np.median(V[near], 0)
            if np.linalg.norm(V[n] - ref) < 0.35 * np.linalg.norm(ref):
                a, b = k, (k[0] + e[0], k[1] + e[1])
                links.setdefault(a, []).append(b)
                links.setdefault(b, []).append(a)
    seen, best = set(), []
    for k in links:
        if k in seen:
            continue
        comp, stack = [], [k]
        seen.add(k)
        while stack:
            c = stack.pop()
            comp.append(c)
            for n in links.get(c, []):
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        if len(comp) > len(best):
            best = comp
    return {k: grid[k] for k in best}


def detect_board(image, n_seeds=25):
    """Find and index the checkerboard corners in a frame (partial and oblique boards work).
    Returns (ij (N, 2) int lattice indices, px (N, 2) float32 pixels); indices have an arbitrary origin."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    pts = find_x_corners(gray)
    if len(pts) < 6:
        return np.zeros((0, 2), int), np.zeros((0, 2), np.float32)
    grad, tree = _gradient(gray), cKDTree(pts)
    best = {}
    for i0 in range(min(n_seeds, len(pts))):        # strongest corners first
        g = _grow(pts, tree, i0, grad)
        if len(g) > len(best):
            best = g
        if len(best) > 0.85 * len(pts):            # nearly every candidate indexed: no seed can do better
            break
    best = _clean(_fix_axes(best, grad)) if best else best
    ij = np.array(list(best), int).reshape(-1, 2)
    px = np.array([best[tuple(k)] for k in ij], np.float32).reshape(-1, 2)
    return ij, px


# ---------------- calibration ----------------
@dataclass
class BoardReport:
    mode: str
    n_tilted: int
    n_flat: int
    rms_px: float
    focal_px: float
    k1: float
    heights: list = field(default_factory=list)       # (bed Z, fitted camera height above the board) per flat frame
    ok: bool = False
    notes: list = field(default_factory=list)

    def text(self):
        head = (f"{self.mode} calibration from {self.n_tilted} tilted + {self.n_flat} flat frames: corner RMS "
                f"{self.rms_px:.2f} px, f={self.focal_px:.0f}px k1={self.k1:+.3f}  ->  "
                f"{'OK' if self.ok else 'NOT ACCEPTABLE'}")
        rows = [f"  flat at Z={z:g} mm: camera {h:.2f} mm above the board" for z, h in self.heights]
        return "\n".join([head] + rows + [f"  - {n}" for n in self.notes])


def _fit_lens(views, size, flat_only, min_points=8):
    """cv2.calibrateCamera with outlier rejection; flat_only fixes the optical centre and tries several f.
    A view left with fewer than min_points inliers is dropped (its keep mask becomes all False)."""
    w, h = size
    base = cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_ASPECT_RATIO | cv2.CALIB_FIX_K3
    if flat_only:
        flags = base | cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_PRINCIPAL_POINT
        starts = [nominal_focal_px(w, h, 110.0) * m for m in (1.2, 1.6, 2.0)]
    else:
        flags, starts = base, [float(max(w, h)), nominal_focal_px(w, h, 110.0) * 1.6]
    best = None
    for f in starts:
        K0 = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
        keep = [np.ones(len(o), bool) for o, _ in views]
        fl = flags if f == starts[0] or flat_only else flags | cv2.CALIB_USE_INTRINSIC_GUESS
        try:
            for _ in range(5):
                live = [n for n, k in enumerate(keep) if k.sum() >= min_points]
                if not live or (flat_only and len(live) < 1):
                    raise cv2.error("no usable view")
                rms, K, dist, rv, tv = cv2.calibrateCamera(
                    [views[n][0][keep[n]] for n in live], [views[n][1][keep[n]] for n in live],
                    size, K0.copy(), None, flags=fl)
                errs = {n: np.linalg.norm(cv2.projectPoints(views[n][0], r, t, K, dist)[0].reshape(-1, 2) - views[n][1], axis=1)
                        for n, r, t in zip(live, rv, tv)}
                thr = max(1.5, 3 * float(np.median(np.concatenate([errs[n][keep[n]] for n in live]))))
                keep = [errs[n] < thr if n in errs else np.zeros(len(views[n][0]), bool) for n in range(len(views))]
            keep = [k if k.sum() >= min_points else np.zeros_like(k) for k in keep]
        except cv2.error:
            continue
        if best is None or rms < best[0]:
            best = (rms, K, dist.ravel(), keep)
    if best is None:
        raise RuntimeError("the lens fit failed: not enough usable board corners")
    return best


def _plausible_view(view, size, max_rms=5.0):
    """A frame whose corner indexing went wrong (e.g. a sheared lattice) cannot be explained by a flat board
    seen through any lens: fit it alone and reject it if the error is large."""
    try:
        rms = _fit_lens([view], size, flat_only=True)[0]
    except RuntimeError:
        return False
    return rms <= max_rms


def _height_above_board(K, dist, ij, px, square, keep):
    obj = np.c_[ij[keep] * square, np.zeros(keep.sum())].astype(np.float32)
    ok, r, t = cv2.solvePnP(obj, px[keep], K, dist)
    R, _ = cv2.Rodrigues(r)
    return abs(float((-R.T @ t.reshape(3))[2]))


def _register(ij, px, markers, square, max_px=25.0, n_cand=4):
    """Board lattice -> bed mm from >= 2 clicked corners at known bed X,Y. Returns candidate (S, t) pairs
    (2x2 signed permutation scaled by the square size, offset) that place every marker within a third of a
    square. Far from the camera the squares are only a few pixels deep, so a click can sit closer to a
    neighbouring corner: each marker tries its few nearest corners and the most consistent choice wins."""
    if len(markers) < 2:
        raise ValueError("need >= 2 markers: board corners clicked in the first flat frame with their bed X,Y in mm")
    if len({tuple(np.round(m["mm"], 1)) for m in markers}) < 2:
        raise ValueError("the markers must be at least 2 DIFFERENT board corners (different bed X,Y)")
    tree = cKDTree(px)
    cands, mms = [], []
    for m in markers:
        d, k = tree.query(m["px"], k=min(n_cand, len(px)))
        d, k = np.atleast_1d(d), np.atleast_1d(k)
        if d[0] > max_px:
            raise ValueError(f"marker at pixel {np.round(m['px'], 1).tolist()} is {d[0]:.0f} px from any detected board "
                             "corner: click exactly on a corner (corners near the front-left are easiest)")
        cands.append([(ij[kk].astype(float), dd) for dd, kk in zip(d, k) if dd <= max(3.0, 2.5 * d[0])])
        mms.append(np.asarray(m["mm"], float))
    fits = []                                   # (pixel distance of the picked corners to the clicks, S, t)
    for S in (np.array(s) for s in ([[1, 0], [0, 1]], [[0, 1], [1, 0]])):
        for sign in itertools.product((1, -1), repeat=2):
            Ss = square * np.diag(sign) @ S
            for pick in itertools.product(*cands):
                qs = [q for q, _ in pick]
                t = np.mean([mm - Ss @ q for q, mm in zip(qs, mms)], 0)
                if len({tuple(q) for q in qs}) < 2:          # two clicks snapped to the same corner
                    continue
                if max(np.linalg.norm(Ss @ q + t - mm) for q, mm in zip(qs, mms)) < square / 3:
                    fits.append((sum(dd for _, dd in pick), Ss, t))
    if not fits:
        far = [n + 1 for n, c in enumerate(cands) if min(dd for _, dd in c) > 3.0]
        raise ValueError("the markers do not fit the board grid: check their bed X,Y (10 mm per square)"
                         + (f"; markers {far} are not on a detected corner (the board there may be too far away "
                            "to detect): click corners in the front-left half of the view" if far else ""))
    # clicks all one square off in the same direction also fit, shifted by a square; the pose cannot tell
    # those apart, so only the pick closest to the actual clicks is kept (its mirror images stay for the pose step)
    best = min(f[0] for f in fits)
    return [(Ss, t) for d, Ss, t in fits if d <= best + 1e-6]


def calibrate_from_board(tilted, flat, markers, square_mm=10.0, board_thickness_mm=0.0,
                         camera_height_mm=C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM, z_tol_mm=Z_TOL_MM):
    """tilted: list of BGR frames of the board at different angles (may be empty).
    flat: list of (BGR frame, bed Z mm) with the board lying flat; flat[0] is the pose frame.
    markers: [{"px": [u, v], "mm": [X, Y]}, ...] board corners in flat[0] at known bed positions.
    Returns (BedCamera with calib_z_mm = flat[0]'s Z, BoardReport)."""
    if not flat:
        raise ValueError("need at least one frame of the board lying flat at a known bed Z")
    size = (flat[0][0].shape[1], flat[0][0].shape[0])
    if any((f.shape[1], f.shape[0]) != size for f in list(tilted) + [f for f, _ in flat]):
        raise ValueError(f"all frames must come from the same camera at the same size ({size[0]}x{size[1]}): "
                         "use raw printer frames, not screenshots")
    obj = lambda ij: np.c_[ij * square_mm, np.zeros(len(ij))].astype(np.float32)
    usable = lambda d: len(d[0]) >= MIN_CORNERS and _plausible_view((obj(d[0]), d[1]), size)
    det_t = [d for d in (detect_board(f) for f in tilted) if usable(d)]
    skipped_t = len(tilted) - len(det_t)
    det_f = [(detect_board(f), z) for f, z in flat]
    ok_f = [usable(d) for d, _ in det_f]
    if not ok_f[0]:
        raise RuntimeError(f"the board was not recognised reliably in the first flat frame (Z={det_f[0][1]:g}, "
                           f"{len(det_f[0][0][0])} corners): light the chamber evenly and keep the board in view and in focus")
    dropped = [z for (_, z), ok in zip(det_f, ok_f) if not ok]
    det_f = [d for d, ok in zip(det_f, ok_f) if ok]
    flat_only = len(det_t) < MIN_TILTED
    if flat_only and len({z for _, z in det_f}) < 2:
        raise ValueError(f"only {len(det_t)} usable tilted frames: the flat-only fallback needs flat frames at "
                         ">= 2 different bed Z heights" + (f" (flat frames at Z={dropped} could not be used)"
                                                          if dropped else ""))
    views = [(obj(ij), px) for ij, px in det_t] + [(obj(ij), px) for (ij, px), _ in det_f]
    rms, K, dist, keep = _fit_lens(views, size, flat_only)
    keep_f = keep[len(det_t):]
    if not keep_f[0].any():
        raise RuntimeError("the first flat frame did not fit the lens: retake it")
    dropped += [z for (_, z), k in zip(det_f, keep_f) if not k.any()]
    det_f, keep_f = [d for d, k in zip(det_f, keep_f) if k.any()], [k for k in keep_f if k.any()]
    rep = BoardReport("flat-only (fallback)" if flat_only else "tilted-frame", len(det_t), len(det_f),
                      float(rms), float(K[0, 0]), float(dist[0]))
    if skipped_t:
        rep.notes.append(f"{skipped_t} tilted frames were skipped: board not recognised reliably")
    rep.heights = [(z, _height_above_board(K, dist, ij, px, square_mm, k)) for ((ij, px), z), k in zip(det_f, keep_f)]
    ok = rms <= MAX_RMS_PX
    if dropped:
        rep.notes.append(f"flat frames at Z={dropped} were skipped: board not recognised reliably or did not fit the lens")
    if not ok:
        rep.notes.append(f"corner reprojection RMS {rms:.2f} px is above {MAX_RMS_PX} px: board not flat, motion blur, "
                         "or wrong square size")
    if len(rep.heights) >= 2:
        z0, h0 = rep.heights[0]
        for z, h in rep.heights[1:]:
            if abs((h - h0) - (z - z0)) > z_tol_mm:
                ok = False
                rep.notes.append(f"camera height changed by {h - h0:.1f} mm between Z={z0:g} and Z={z:g} but the bed "
                                 f"moved {z - z0:g} mm: check the Z values on the printer screen and that the board did not shift")
    # pose of the bed frame from the first flat frame and the markers
    (ij, px), z0 = det_f[0]
    k0 = keep_f[0]
    best = None
    poses = []
    for S, t in _register(ij, px, markers, square_mm):           # all corners: clicks may sit on noisy ones
        mm = (S @ ij[k0].T).T + t
        objb = np.c_[mm, np.full(len(mm), board_thickness_mm)].astype(np.float32)
        _, r, tv = cv2.solvePnP(objb, px[k0], K, dist)
        cam = BedCamera(K, dist.copy(), r, tv, float(z0))
        R, _ = cv2.Rodrigues(r)
        if (-R.T @ tv.reshape(3))[2] <= 0:          # mirrored registration puts the camera under the bed
            continue
        err = np.linalg.norm(cv2.projectPoints(objb, r, tv, K, dist)[0].reshape(-1, 2) - px[k0], axis=1).mean()
        poses.append((err, cam))
        if best is None or err < best[0]:
            best = (err, cam)
    centres = [np.array(c.pose()["centre_mm"]) for _, c in poses]
    if len(centres) > 1 and max(np.linalg.norm(c - centres[0]) for c in centres) > 1.0:
        raise ValueError("the markers allow more than one placement of the board (e.g. all on one line): click 3 "
                         "corners that are not in a line")
    if best is None:
        raise ValueError("no marker registration puts the camera above the bed: check the markers' X,Y (front-left origin, "
                         "X to the right, Y toward the back)")
    cam = best[1]
    rep.notes.append(cam.pose_text())
    warn = cam.check_height(camera_height_mm)
    if warn:
        ok = False
        rep.notes.append(warn + " (and --board-thickness)")
    if flat_only:
        rep.notes.append("flat-only fallback: the optical centre was assumed at the image centre; frames of the board "
                         "held at different angles give a better lens fit")
    rep.ok = bool(ok)
    return cam, rep


# ---------------- CLI ----------------
def parse_z(text):
    """Bed Z typed at the capture prompt: '30', 'Z=30', '30 mm', '30,5' -> a number in mm; None if the text is
    not a single bed height the board can be at (above 0, within the P1S's 256 mm)."""
    nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", "."))
    if len(nums) != 1:
        return None
    z = float(nums[0])
    return z if 0 < z <= 256 else None


MARKER_HELP = ("Click the <b>points where four squares meet</b> (not the outer corners of the board): 3 of them, far "
               "apart and not in a line, in the front-left half of the view where the squares look biggest. For each, "
               "type its bed X,Y in mm, e.g. <code>30,20</code>: X from the plate's left edge, Y from its front edge. "
               "Measure one with a ruler; its neighbours are 10 mm further per square (X to the right, Y toward the "
               "back). Then press <b>Save markers.json</b> and move the file into <code>{folder}</code>.")


def _save_shots(folder, shots):
    tmp = folder / "shots.json.tmp"
    tmp.write_text(json.dumps(shots, indent=1))
    tmp.replace(folder / "shots.json")


def capture(ip, code, folder, camera=None, ask=input):
    """Interactive capture of tilted and flat frames into `folder` (+ shots.json and a click page).
    shots.json is updated after every shot, so a mistake or Ctrl-C loses nothing: rerunning with the same
    folder continues where it stopped."""
    from .calib_offline import pick_points_html
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    shots = dict(tilted=[], flat=[])
    if (folder / "shots.json").exists():
        shots.update(json.loads((folder / "shots.json").read_text()))
        print(f"continuing in {folder}: {len(shots['tilted'])} tilted + {len(shots['flat'])} flat shots already "
              "saved (use another --dir to start over)")
    if camera is None:
        from .printer.bambu import BambuCamera
        camera = BambuCamera(ip, code)

    def snap(name):
        """Save a frame that arrived after Enter was pressed (the camera sends about 1 frame/s, so an older one
        could still show the board or bed before it moved)."""
        while True:
            try:
                img = camera.grab(timeout=15.0, newer_than=time.time())
            except TimeoutError:
                if ask("   no new camera frame (LAN mode on? access code right?). Enter = try again, "
                       "'n' + Enter = skip this shot: ").strip().lower() == "n":
                    return False
                continue
            cv2.imwrite(str(folder / name), img)
            return True

    def marker_page():
        if shots["flat"]:
            pick_points_html(shots["flat"][0]["file"], folder / "markers_click.html",
                             intro=MARKER_HELP.format(folder=folder), markers_only=True)

    try:
        print("1) Hold the board at a different angle/place for each shot (8-15 shots, tilted up to ~45 deg, "
              "filling different parts of the view). Enter = capture, 'n' + Enter = done.")
        while ask(f"   tilted shot {len(shots['tilted']) + 1}: ").strip().lower() != "n":
            name = f"tilt_{len(shots['tilted']):02d}.png"
            if snap(name):
                shots["tilted"].append(name)
                _save_shots(folder, shots)
        print("2) Lay the board FLAT on the plate. Home first with the plate empty, then move the bed with the printer "
              "(never home or go to Z=0 with the board on the plate). Take two heights, e.g. Z=10 and Z=30.")
        while True:
            text = ask(f"   bed Z in mm for flat shot {len(shots['flat']) + 1} (blank = done): ").strip()
            if not text:
                break
            z = parse_z(text)
            if z is None:
                print("   not saved: type the bed Z as one number in mm, e.g. 30")
                continue
            if any(abs(z - s["z"]) < 1.0 for s in shots["flat"]):
                print(f"   not saved: there is already a flat shot at Z={z:g}; move the bed to another height first")
                continue
            name = f"flat_{len(shots['flat']):02d}.png"
            if snap(name):
                shots["flat"].append(dict(file=name, z=z))
                _save_shots(folder, shots)
                marker_page()
                print(f"   saved {name} at Z={z:g}")
    except (KeyboardInterrupt, EOFError):
        print(f"\nstopped. Shots so far are kept in {folder}; run the same command again to continue.")
    finally:
        camera.close()
    _save_shots(folder, shots)
    marker_page()
    n_flat = len({s["z"] for s in shots["flat"]})
    if n_flat < 2:
        print(f"note: {n_flat} flat height(s) so far. Take 2 (e.g. Z=10 and Z=30): the Z check needs both, and "
              "without 3+ usable tilted shots the fit does too. Rerun the same command to add them.")
    print(f"saved {len(shots['tilted'])} tilted + {len(shots['flat'])} flat frames in {folder}"
          + (f"; open {folder / 'markers_click.html'}, save markers.json into {folder}, then run "
             f"calibrate-board --dir {folder} --board-thickness <mm>" if shots["flat"] else ""))


def _read_markers(path, folder):
    """markers.json from the click page, with an error that says what to do instead of a traceback."""
    if not path.exists():
        found = sorted(p for p in list(folder.glob("markers*")) + list((Path.home() / "Downloads").glob("markers*.json"))
                       if p.name != "markers_click.html")
        hint = ("; found " + ", ".join(str(p) for p in found) + ": move/rename the right one to " + str(path)
                if found else "")
        raise SystemExit(f"no {path}: open {folder / 'markers_click.html'}, click 3 board corners with their bed X,Y, "
                         f"press 'Save markers.json' and move the file into {folder}{hint}")
    try:
        data = json.loads(path.read_text())
    except (UnicodeDecodeError, ValueError):
        raise SystemExit(f"{path} is not valid JSON (an editor such as TextEdit adds formatting and curly quotes): "
                         "use the click page's 'Save markers.json' button, or in Terminal: pbpaste > " + str(path))
    markers = data.get("markers", []) if isinstance(data, dict) else []
    if len(markers) < 2:
        raise SystemExit(f"{path} has {len(markers)} marker(s): on the click page choose 'marker' and click at least "
                         "3 board corners, typing each one's bed X,Y")
    return markers


def main(a):
    folder = Path(a.dir)
    if a.ip:
        capture(a.ip, a.code, folder)
        return
    if not (folder / "shots.json").exists():
        raise SystemExit(f"no {folder / 'shots.json'}: capture first (calibrate-board --ip ... --code ... --dir {folder})")
    shots = json.loads((folder / "shots.json").read_text())
    def read(n):
        img = cv2.imread(str(folder / n))
        if img is None:
            raise SystemExit(f"cannot read {folder / n} (listed in shots.json)")
        return img
    tilted = [read(n) for n in shots.get("tilted", [])]
    flat = [(read(s["file"]), float(s["z"])) for s in shots["flat"]]
    markers = _read_markers(Path(a.markers) if a.markers else folder / "markers.json", folder)
    try:
        cam, rep = calibrate_from_board(tilted, flat, markers, a.square_mm, a.board_thickness, a.camera_height)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"calibration failed: {e}")
    print(rep.text())
    from .calib_offline import draw_overlay
    out = Path(a.out)
    cv2.imwrite(str(out.with_name(out.stem + "_overlay.png")), draw_overlay(cam, flat[0][0]))
    if not rep.ok and not a.force:
        raise SystemExit("not saved: calibration is not acceptable (see the notes above, or --force)")
    cam.save(out)
    print(f"saved {out}; check {out.stem}_overlay.png: the green outline must sit on the plate edges")
