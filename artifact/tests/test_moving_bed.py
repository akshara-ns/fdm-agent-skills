"""The P1S bed drops one layer height per layer while the chamber camera stays put, so the top of the
layer just printed is always at the nozzle plane. A calibration made with the bed at Z = calib_z must
therefore map every frame on the plane calib_z above the calibrated plate, not at the layer's own z."""
import argparse
import json

import cv2
import numpy as np
import pytest

from recovery import config as C
from recovery.calib_offline import EDGES, fit_from_bed_edges, main as calibrate_bed_main
from recovery.camera import CAM, BedCamera

W, H = 1280, 720


def p1s_camera(calib_z, f=818.0, k1=0.0, heading=32.0, tilt=9.0, xy=(-32.0, 34.0)):
    """Chamber camera roughly where the first real P1S clicks (issue 5) put it: front-left, outside the
    plate, looking 9 deg down; its height above the plate is the measured 22.784 mm + calib_z."""
    c = np.array([xy[0], xy[1], C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM + calib_z])
    t, h = np.radians(tilt), np.radians(heading)
    z = np.array([np.cos(t) * np.cos(h), np.cos(t) * np.sin(h), -np.sin(t)])
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x)
    R = np.stack([x, np.cross(z, x), z])
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1.0]])
    return BedCamera(K, np.array([k1, 0, 0, 0, 0.0]), cv2.Rodrigues(R)[0], (-R @ c).reshape(3, 1), calib_z)


def project(cam, pts):
    px, _ = cv2.projectPoints(np.asarray(pts, float), cam.rvec, cam.tvec, cam.K, cam.dist)
    return px.reshape(-1, 2)


def frame_with_square(cam, centre, side, height):
    """Camera frame of a bright square lying on the plane `height` above the calibrated plate."""
    cx, cy = centre
    sq = [(cx - side / 2, cy - side / 2), (cx + side / 2, cy - side / 2),
          (cx + side / 2, cy + side / 2), (cx - side / 2, cy + side / 2)]
    px = project(cam, [(x, y, height) for x, y in sq])
    img = np.zeros((H, W, 3), np.uint8)
    cv2.fillPoly(img, [np.round(px * 16).astype(np.int32)], (255, 255, 255), cv2.LINE_AA, shift=4)
    return img


def centroid_mm(top, centre):
    m = top[..., 0] > 127
    assert m.any(), "square not visible in the top-down view"
    ys, xs = np.nonzero(m)
    x = centre[0] + (xs.mean() + 0.5 - CAM.size / 2) / CAM.px_per_mm
    y = centre[1] + (CAM.size / 2 - ys.mean() - 0.5) / CAM.px_per_mm
    return np.array([x, y])


@pytest.mark.parametrize("layer_z", [0.2, 6.0, 12.0])
def test_layer_top_is_read_at_the_nozzle_plane_whatever_the_layer(layer_z):
    calib_z = 10.0
    cam = p1s_camera(calib_z)
    centre = (128.0, 128.0)
    # with the bed still at layer_z, the part's top surface sits calib_z above the calibrated plate
    frame = frame_with_square(cam, centre, 20.0, calib_z)
    got = centroid_mm(cam.top_down(frame, cam.layer_plane_z(layer_z), centre), centre)
    assert np.linalg.norm(got - centre) < 0.5
    if abs(layer_z - calib_z) > 2:                                 # the previous mapping: plane at layer_z
        old = cam.top_down(frame, layer_z, centre)
        assert not (old[..., 0] > 127).any() or np.linalg.norm(centroid_mm(old, centre) - centre) > 5.0


def test_a_bed_that_has_already_dropped_further_lowers_the_plane():
    cam = p1s_camera(10.0)
    assert cam.layer_plane_z(6.0, bed_z=6.2) == pytest.approx(9.8)          # next layer started
    assert cam.layer_plane_z(6.0, bed_z=6.6) == pytest.approx(9.4)          # plus a 0.4 mm park Z-hop
    assert BedCamera(cam.K, cam.dist, cam.rvec, cam.tvec).layer_plane_z(6.0, bed_z=6.2) == 6.0   # fixed bed


def test_printer_reports_the_bed_drop_when_a_frame_is_grabbed(tmp_path):
    """A layer counts as done once the printer reports the next one, so in the frame the bed is already one layer
    lower than the finished layer (plus any park Z-hop). The drop BambuPrinter reports must place the plate where
    both camera models put it: p1s_view.plate_z_mm (the camera-view outline) and BedCamera.layer_plane_z."""
    from recovery import p1s_view as V
    from recovery.printer.bambu import BambuPrinter
    from recovery.types import Layer
    from shapely.geometry import box
    plan = [Layer(round(0.2 * (i + 1), 3), box(-10, -10, 10, 10)) for i in range(50)]
    pr = BambuPrinter.__new__(BambuPrinter)
    pr.plan, pr._layer = plan, 30
    assert pr.frame_bed_drop_mm() == pytest.approx(0.2)                      # bed already at layer 31
    pr.frame_extra_drop_mm = 0.4
    assert pr.frame_bed_drop_mm() == pytest.approx(0.6)                      # plus a measured park Z-hop
    pr._layer = 50
    assert pr.frame_bed_drop_mm() == pytest.approx(0.4)                      # last layer: no next layer
    cam = p1s_camera(10.0)
    cam.save(tmp_path / "calib.npz")                                         # what calibrate-* write
    pcam = V.P1SCamera.load(tmp_path / "calib.npz")                          # what watch / agent read
    assert pcam.calib_z_mm == 10.0
    pr._layer, pr.frame_extra_drop_mm = 30, 0.0
    top = plan[29].z
    plate = V.plate_z_mm(pcam, top, pr.frame_bed_drop_mm())
    assert plate == pytest.approx(cam.layer_plane_z(top, bed_z=top + pr.frame_bed_drop_mm()) - top)


def test_calibration_z_is_saved_and_old_files_keep_the_fixed_bed_model(tmp_path):
    cam = p1s_camera(12.0)
    cam.save(tmp_path / "c.npz")
    back = BedCamera.load(tmp_path / "c.npz")
    assert back.calib_z_mm == 12.0 and back.layer_plane_z(3.4) == 12.0
    np.savez(tmp_path / "old.npz", K=cam.K, dist=cam.dist, rvec=cam.rvec, tvec=cam.tvec)
    legacy = BedCamera.load(tmp_path / "old.npz")
    assert legacy.calib_z_mm is None and legacy.layer_plane_z(3.4) == 3.4


def test_watch_and_agent_refuse_a_calibration_without_bed_z(tmp_path):
    from recovery import p1s_view as V
    cam = p1s_camera(10.0)
    np.savez(tmp_path / "old.npz", K=cam.K, dist=cam.dist, rvec=cam.rvec, tvec=cam.tvec)
    with pytest.raises(ValueError, match="calib-z"):
        V.P1SCamera.load(tmp_path / "old.npz")


def test_pose_reports_the_camera_height_and_flags_a_wrong_calib_z():
    cam = p1s_camera(10.0)
    p = cam.pose()
    assert abs(p["height_above_print_plane_mm"] - C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM) < 1e-6
    assert abs(p["tilt_deg"] - 9.0) < 1e-6
    assert cam.check_height(C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM) is None
    told_wrong = BedCamera(cam.K, cam.dist, cam.rvec, cam.tvec, 0.0)   # bed was at 10, user typed 0
    assert "measured" in told_wrong.check_height(C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM)


def _edge_clicks(cam, n=10, noise=0.7, seed=0):
    """Clicks along the parts of each plate edge the camera really sees (no lens fold-back)."""
    rng = np.random.default_rng(seed)
    R, _ = cv2.Rodrigues(cam.rvec)
    ts = np.linspace(0, 256, 80)
    lines = {"front": [(t, 0) for t in ts], "right": [(256, t) for t in ts],
             "back": [(t, 256) for t in ts], "left": [(0, t) for t in ts]}
    out = {}
    for e in EDGES:
        P = np.array([[x, y, 0.0] for x, y in lines[e]])
        Pc = (R @ P.T + cam.tvec).T
        px = project(cam, P)
        ok = (Pc[:, 2] > 0) & (np.hypot(Pc[:, 0], Pc[:, 1]) < Pc[:, 2]) & \
             (px[:, 0] > 2) & (px[:, 0] < W - 2) & (px[:, 1] > 2) & (px[:, 1] < H - 2)
        idx = np.linspace(0, ok.sum() - 1, n).round().astype(int)
        out[e] = (px[ok][idx] + rng.normal(0, noise, (n, 2))).tolist()
    return out


def test_grazing_view_fit_finds_the_physical_pose():
    """On this shallow view the original four focal-length starts all converge to a camera ~70 mm up with a
    shorter lens; the added starts must reach the physical pose."""
    truth = p1s_camera(10.0, k1=-0.3)
    pts = _edge_clicks(truth)
    cam, rep = fit_from_bed_edges(pts, calib_z_mm=10.0, camera_height_mm=C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM)
    assert abs(cam.pose()["height_above_print_plane_mm"] - C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM) < 3.0
    assert cam.calib_z_mm == 10.0


def test_measured_height_breaks_a_tie_between_poses(monkeypatch):
    """If a wrong pose fits the clicks slightly better than the physical one, the measured camera height
    picks the physical one; without it the lower cost wins."""
    import recovery.calib_offline as co
    good, wrong = p1s_camera(10.0), p1s_camera(50.0)              # camera 32.8 vs 72.8 mm above the plate
    runs = iter([(5.0, wrong), (5.1, good)] * 20)
    monkeypatch.setattr(co, "_fit_once", lambda *a, **k: next(runs))
    pts = {e: [[0.0, 0.0]] * 6 for e in EDGES}
    picked, _ = co.fit_from_bed_edges(pts, calib_z_mm=10.0, camera_height_mm=C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM)
    assert picked.pose()["height_mm"] == pytest.approx(good.pose()["height_mm"])
    runs = iter([(5.0, wrong), (5.1, good)] * 20)
    picked, _ = co.fit_from_bed_edges(pts, calib_z_mm=10.0)
    assert picked.pose()["height_mm"] == pytest.approx(wrong.pose()["height_mm"])


def test_calibrate_bed_needs_the_bed_z(tmp_path):
    cv2.imwrite(str(tmp_path / "f.png"), np.zeros((H, W, 3), np.uint8))
    pts = {e: [[0.0, 0.0]] * 6 for e in EDGES}
    (tmp_path / "p.json").write_text(json.dumps(pts))
    a = argparse.Namespace(image=str(tmp_path / "f.png"), points=str(tmp_path / "p.json"), out=str(tmp_path / "c.npz"),
                           profile=None, fov=None, bed=256.0, force=False, calib_z=None,
                           camera_height=C.P1S_CAMERA_ABOVE_PRINT_PLANE_MM, height_prior=None)
    with pytest.raises(SystemExit, match="--calib-z"):
        calibrate_bed_main(a)
