# Calibrating the P1S camera without a checkerboard

`python -m recovery.cli calibrate-bed` replaces the checkerboard with the plate itself: the bed is a
known 256 x 256 mm rectangle and the chamber camera is fixed. Clicking points along the four plate
edges in ONE frame fits focal length, one radial-distortion term and the camera pose
(`recovery/calib_offline.py`). Datasheet values (1280x720, 110 deg diagonal FOV) are only a weak prior.

## Why not datasheet values alone
Bambu publishes no intrinsics, distortion or mount pose, and resellers disagree on the FOV (110 vs 119 deg).
`tools/calibration_sensitivity.py` shows datasheet-level errors give 1.5 to 17 mm mean bed error against a 1 mm alarm threshold.

## Expected accuracy (synthetic test, `tests/test_calib_offline.py`)
8 clicks per edge, 0.7 px click noise, wrong FOV prior, lens distortion k1 from -0.1 to -0.4:
mean bed error about 0.5 mm, worst point 1.5 to 2 mm (at the extremes of the plate). This is a simulation:
real accuracy depends on how well the plate edges can be seen and clicked. Always do the checks in step 5.
The checkerboard method remains the most accurate; use it if the checks fail.

## Camera angle matters (found from the first real clicks)
The first real P1S frame (issue 5) was viewed very obliquely: the near corner of the plate was far outside the image
and the back/right edges were seen at a grazing angle, where one pixel is several mm. Edge clicks alone then gave
4 to 5 mm RMS (not accepted), with the near edges at about 1 mm. Fixes in the tool: several starting focal lengths
(the first fit landed in a local minimum at 58 mm), a second distortion term, per-edge diagnostics, and **markers**.

**Markers are the cure**: any points at known bed positions in the middle of the view. Put 5 to 9 small marks
(tape dots, or the corners of a printed test square) on the plate, measure each position in mm from the plate's
front-left corner (X to the right, Y toward the back) with a ruler or calipers, and in the click page choose
`marker (known X,Y mm)`, click the mark and type `X,Y`. They constrain the interior of the view, which is where parts
are printed, and make the edge clicks much less critical.

## The bed moves: calibration Z
The P1S bed drops by one layer height every layer while the camera stays fixed, so the top of a layer is at
the nozzle height while it is printed, not `z` above where the plate was. The calibration therefore records the
bed Z of its frame (`--calib-z`): the top of the print is `calib-z` above the calibrated plate, lowered by however
far the bed has dropped since that layer when the frame is grabbed (`BedCamera.layer_plane_z`, and the plate at
`calib-z - top - drop` in `p1s_view.plate_z_mm`; see docs/calibration-board.md for the frame timing). Without
this, at a 6 mm print height the print is placed tens of mm off on this camera. The fit also reports the camera's position, its height above
the print plane and how steeply it looks down; the height is checked against the team's measurement of
22.784 mm (`P1S_CAMERA_ABOVE_PRINT_PLANE_MM`), and a disagreement over 1 mm blocks saving (usually a wrong
`--calib-z`). This only catches gross mistakes: 1 mm of height is about 8 mm on the bed. On a grazing view several poses explain the clicks almost equally well; the measured height
is used to pick the physical one, and `--height-prior SIGMA` also adds it to the fit as a soft constraint.

**How sensitive this camera is** (from the issue-5 fit: camera about 32 mm left of and 34 mm behind the
plate's front-left corner, 22.8 mm above the print plane, f about 820 px):

| part at (mm) | distance | looks down | mm per pixel toward / across the camera | XY error per 1 mm of height error |
|---|---|---|---|---|
| 64, 64   | 101 mm | 12.8 deg | 0.57 / 0.13 | 4.4 mm |
| 128, 128 | 186 mm | 7.0 deg  | 1.88 / 0.23 | 8.1 mm |
| 192, 192 | 274 mm | 4.8 deg  | 4.06 / 0.34 | 12.0 mm |

So the bed Z must be exact (use the printer's own Z, not a ruler), and parts should be placed near the
front-left corner, where the view is steepest.

Simulated on that camera (0.7 px click noise, 10 seeds; error over the middle 80 x 80 mm of the print plane):
edge clicks alone give 1.5 to 4 mm mean, edges plus 9 markers 0.6 to 1.0 mm, for a calibration Z anywhere
from 0 to 40 mm (10 mm: 2.4 mm edges only, 0.9 mm with markers and `--height-prior 1`). The height prior
helps by about 20 %. Markers are what matter; the calibration Z is not critical.

## Steps
1. Printer on, bed EMPTY and clean, chamber lit, door closed, printer in LAN mode. Home the printer, then move
   the bed to a known Z from the printer screen (10 mm is a good default) and note it: it is `--calib-z`.
2. Grab a frame and create the click page:
   ```bash
   python -m recovery.cli calibrate-bed --ip <printer-ip> --code <access-code> --out calib.npz
   ```
   (or `--image frame.png` for a saved frame). This writes `calib_frame.png` and `calib_click.html`.
3. Open `calib_click.html` in a browser. For each edge (front = nearest you / the door, then left, right,
   back as you face the printer) pick it in the dropdown and click **8 points spread from end to end along
   the visible plate edge**, including both corners. Click the true edge of the plate, not the bed
   clip or shadow. Press **Save points.json** (it goes to Downloads; move it next to the command). Edges that are cut off by the frame:
   click what is visible; at least 6 per edge are required.
4. Fit:
   ```bash
   python -m recovery.cli calibrate-bed --ip <printer-ip> --code <access-code> --points points.json --calib-z 10 --out calib.npz
   ```
   It prints the edge residual (RMS and max, in mm) and refuses to save if RMS > 1 mm or max > 2 mm, or the focal
   length is implausible, if the camera would be below the bed, or if its height above the print plane is
   more than 1 mm off the measured 22.784 mm. It also prints per-edge residuals and flags an edge
   that is much more curved than the rest. Fixes, in order: re-click the flagged edge, add markers, add more clicks.
5. Check: open `calib_overlay.png`. The green outline and grid must sit on the real plate edges everywhere,
   especially the corners. Then run `watch` on a clean print: every layer should be `ok`.
6. If the camera or printer is moved later, keep the lens and refit only the pose from fresh clicks
   (the four corners are enough, but all four edges with >= 2 clicks each are used to find them):
   ```bash
   python -m recovery.cli calibrate-bed --ip <ip> --code <code> --points points.json --profile calib.npz --calib-z 10 --out calib.npz
   ```
   If the lens profile does not fit this unit the command says so (corner reprojection error), then use step 4.
