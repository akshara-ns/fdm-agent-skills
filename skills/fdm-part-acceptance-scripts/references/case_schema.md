# case.json fields for scripts/check_part.py

All lengths in mm, forces in N (or `load_kg` for a hung mass), times in h or min. Unknown keys are ignored.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `part` | string | no | Name, for the record. |
| `material` | `"PLA"`, `"PETG"`, `"ABS"` | yes | Selects the data-sheet strength and stiffness. |
| `measurement_uncertainty_mm` | number 0-1 | no (0.05) | Margins smaller than this are borderline. |
| `features` | list | yes, >= 1 | One item per measured feature (below). |
| `beam` | object | if anything carries load | The load-bearing arm as a cantilever (below). |
| `seam` | object | if the print was paused, resumed or corrected | The repair seam (below). Needs `beam`. |
| `reprint` | `{time_h, filament_g}` | no | Slicer estimate for a reprint; adds its cost. |

**Feature item:** `name`; `role` = `cosmetic`, `fit` or `load_bearing`; the measurement as `readings_mm` (list)
or `measured_mm`; and exactly one limit:
- `nominal_mm` + `tolerance_mm` (symmetric; `tolerance_mm` may be left out only for a cosmetic feature, 1.0 mm),
- `range_mm`: `[lo, hi]` (converted to midpoint ± half-width for the HW5 tool),
- `min_mm` and/or `max_mm` (one-sided, checked directly).

**Beam:** `length_mm` (load line to clamp edge), `width_mm`, `nominal_thickness_mm`, and
`measured_thickness_readings_mm` (list) or `measured_thickness_mm`; `load_N` or `load_kg`; `orientation`
(`flat` or `upright`, required); `target_safety_factor` (default 2.0); `section` (`solid` default, or `skins`
with `skin_mm` = top/bottom shell thickness); `interlayer_factor` (default 0.5).

**Seam:** `z_mm` (height of the first resumed layer above the bed, below the measured thickness); `pause_min`;
optional `visible_gap`: `{length_mm, distance_from_load_mm}`; leave `distance_from_load_mm` out if unknown.
