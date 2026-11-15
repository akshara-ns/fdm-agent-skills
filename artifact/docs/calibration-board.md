# Calibrating the P1S camera with a large checkerboard

`python -m recovery.cli calibrate-board` uses a printed checkerboard of 10 mm squares, ideally big enough to
cover the plate (`recovery/calib_board.py`). The board does not have to be fully in view: corners are found
one by one and joined into a grid, so partial and steeply tilted views work.

## Two ways, best first
1. **Tilted frames + a flat frame (preferred).** Raw frames of the board held at different angles fix the lens
   (focal length, distortion, optical centre). A frame of the board lying flat at a known bed Z then fixes where
   the camera is.
2. **Flat frames only (fallback).** Used automatically when fewer than 3 tilted frames are usable. Needs the board
   lying flat at two or more bed heights (e.g. Z=10 and Z=30); the optical centre is assumed at the image centre.

With two or more flat frames, the camera's fitted height above the board must change by exactly the bed's Z
change (the bed moves, the camera does not), within 1.5 mm. This catches a wrong Z value or a board that shifted.
The camera's height above the print plane is also checked against the measured 22.784 mm (within 1 mm). That
check only catches gross mistakes: 1 mm of height is about 8 mm on the bed, so the board thickness and the Z
values themselves must be right (see step 4).

## Steps
1. Printer in LAN mode, chamber lit, door closed. Use **raw frames from the printer**, not screenshots: a
   screenshot is cropped and rescaled, which hides the optical centre.
2. Capture (interactive, saves the frames, `shots.json` and a click page in `--dir`):
   ```bash
   python -m recovery.cli calibrate-board --ip <printer-ip> --code <access-code> --dir calib_shots
   ```
   - Tilted: hold the board at 8 to 15 different angles (up to about 45 deg) and places, filling different parts
     of the view. Keep it still for each shot.
   - Flat: home the printer FIRST with the plate empty, then lay the board flat on the plate and move the bed from
     the printer. Take two heights, e.g. Z=10 and Z=30, typing the bed Z for each (`30`, `Z=30` and `30 mm` are all
     read as 30). Never home or go to Z=0 with the board on the plate: the nozzle would hit it.
   - Every shot is written to `shots.json` straight away and each frame is one that arrived after Enter was pressed.
     A typo is asked again, and after a mistake or Ctrl-C the same command continues in the same folder.
3. Open `calib_shots/markers_click.html` (written after the first flat shot). Click 3 **points where four squares
   meet** (not the outer corners of the board), far apart and not in a line, and type each one's bed X,Y in mm, e.g.
   `30,20` (front-left plate corner = 0,0, X to the right, Y toward the back). Each accepted marker shows its X,Y
   next to the dot. To get the X,Y: lay the board square to the plate edges, measure ONE crossing near the front-left
   with a ruler (X from the plate's left edge, Y from its front edge); every other crossing is 10 mm further per
   square. Pick corners in the front-left half of the view, where the squares look biggest: far away they are only
   a few pixels deep and a click can land on the neighbouring corner. Press **Save markers.json** and move the file
   from Downloads into `calib_shots/` (or pass `--markers ~/Downloads/markers.json`). Do not paste it into TextEdit:
   it adds formatting and curly quotes. A wrong origin (e.g. every X off by 10 mm) cannot be detected by the
   software; the overlay in step 5 shows it.
4. Fit:
   ```bash
   python -m recovery.cli calibrate-board --dir calib_shots --board-thickness 2 --out calib.npz
   ```
   Measure the board thickness with calipers to about 0.1 mm (paper on the plate is about 0.1 mm; foam board 2 to
   5 mm): on this camera 1 mm of height error moves positions about 8 mm in the middle of the bed, and neither the
   Z check nor the height check can see a thickness error. The command prints the corner error, the
   camera height for each flat frame, the Z check and the camera pose, and refuses to save a calibration that
   fails a check (`--force` overrides).
5. Check `calib_overlay.png` (the green outline must sit on the plate edges) and run `watch` on a clean print.

## When frames are taken during a print
A layer counts as done once the printer reports the next one, so by the time the frame is grabbed the bed is
already one layer lower (and lower still if the head parks with a Z-hop for the timelapse).
`BambuPrinter.frame_bed_drop_mm()` gives that drop: `next layer Z - its Z`, plus `frame_extra_drop_mm`
(default 0). It is the `drop_mm` of `p1s_view.plate_z_mm` / `P1SScene`, which place the plate in the camera view.
Measure whether the bed drops further while the head parks and set that value: 0.4 mm unaccounted for is about
3 mm on the bed. The frame after the last layer is taken after the end G-code has moved the bed and is not
reliable.

The layer detector (`recovery/models/p1s_layer.py`) is trained with the plan outline drawn at no drop and
frames taken with a random 0 to 0.4 mm drop, so it already tolerates the one-layer drop; whether to pass the
measured drop to `plan_silhouette` (or widen the training range if the park drop is larger) is open.

## First real frames (screenshots, Nov 2026)
Two screenshots of a bed-sized board at "0 mm" and "10 mm" gave a consistent lens in both and camera heights of
20.7 mm and 38.9 mm above the board. The first agrees with 22.784 mm above the plate if the board is about
2 mm thick; the second implies the bed moved about 18 mm, not 10, so the Z values should be re-read from the
printer screen when the frames are retaken.
