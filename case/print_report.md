# Print report: bracket test part after an in-print correction

*Scenario for 24-679 HW6. The part spec (`bracket.yaml`) is the Project 2 team's real bracket spec, copied
unchanged from our repository. The print event and the measurements below are a constructed scenario of the
kind our recovery loop is meant to produce; they are not readings from a real print.*

## Part and use
- Part: `bracket` (see `bracket.yaml`), a 60 x 30 x 8 mm PLA plate with two 5 mm bolt holes 40 mm apart
  (centres at x = -20 and x = +20 mm).
- Use: the right bolt (x = +20) is clamped; the clamp covers x = 17 to 23 mm. The left bolt (x = -20) carries
  a load of 100 N pushing out of the plate's plane (along Z). The spec requires a safety factor of 1.5.

## Print settings (Bambu Lab P1S, Bambu Studio)
- Bambu PLA Basic, 0.25 mm layers (32 layers), printed flat: the 60 x 30 face on the bed.
- 3 wall loops (0.42 mm lines), 4 top and 4 bottom shell layers (1.0 mm each), 15 % gyroid sparse infill.

## What happened during the print
- Layer 17 (z = 4.00 to 4.25 mm): the camera check flagged under-extrusion along the left (load) end.
- The agent paused the printer after layer 17. The part stayed on the 55 °C bed for about 6 minutes while a
  person reviewed the proposal, then approved "correct": layers 18 to 32 were re-planned to return to the
  original outline, and printing resumed at z = 4.25 mm.

## Measurements of the finished part (digital calipers, 0.01 mm resolution)
| Feature | Readings (mm) |
|---|---|
| Plate thickness near the clamp (x about 17) | 7.62, 7.58 |
| Plate thickness near the load end (x about -25) | 7.70, 7.71 |
| Plate width | 30.04 |
| Left (load) hole diameter, two directions | 4.86, 5.02 |
| Right (clamped) hole diameter, two directions | 5.04, 5.08 |
| Hole centre-to-centre spacing | 40.25 |
| Material between the left hole edge and the left end of the plate | 7.00 |

## Visual inspection
- A faint seam line is visible at about z = 4.2 mm on all four side faces.
- On the front face near the load end, a fingernail catches a gap along the seam about 6 mm long.
  Elsewhere the seam feels closed.

## Reprint estimate (Bambu Studio, same settings)
- 48 min, 13.2 g of PLA.
