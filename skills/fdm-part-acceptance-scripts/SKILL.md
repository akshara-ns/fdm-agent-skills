---
name: fdm-part-acceptance-scripts
description: Decide whether an FDM 3D-printed part that was dented, corrected, paused or resumed mid-print can still be used - KEEP, TEST_BEFORE_USE or REPRINT - from caliper measurements, the part's function spec, its load case and the repair seam. Script-assisted version - encode the case as JSON and run scripts/check_part.py (reuses the HW5 fdm-mcp tools check_deviated_part and check_cantilever) instead of calculating by hand.
---

# FDM part acceptance after an in-print correction (script-assisted)

You are acting as a mechanical engineer who signs off printed parts. The part did not come out as designed:
our recovery loop (or a person) paused it, dented it, corrected the remaining layers or resumed it. Decide,
with reasons a person can check, whether it can be used.

**Division of labour.** Your job is the engineering judgement: reading the spec and the report, choosing the
right inputs (which reading, which length, which section), handling what is missing, and explaining the result.
The script's job is every number and the decision rules. **Do not compute stresses or safety factors by hand
when the script can run**; copy numbers from its output. The method behind it is in `references/method.md`.

## 1. When to use this skill, and when not to
Use it when a finished part deviates from its design and someone asks "can we use it?", and its function can be
judged from a few dimensions plus at most one cantilever-like load case.

Do **not** decide, and hand the case to a person, when the part is safety-critical (holds a person, hangs over
people, holds pressure or hot liquid), the load is impact, vibration or fatigue, it works near its heat
deflection temperature (PLA 57 °C, PETG 69 °C, ABS 104 °C), or the load path is not a bending arm, a clamp or a
fit. The script cannot see any of these; you must.

## 2. Procedure

### Step 1 - Read the case and collect inputs
Read the part spec and print report completely. You need, in mm / N / kg:
- material (PLA, PETG or ABS);
- every functional feature's readings and the designer's limit;
- the load, where it acts and where the part is held; arm width and thickness readings;
- orientation (flat = bending stress along the layers; upright = bending pulls layers apart);
- infill/shells (sparse infill -> `"section": "skins"` with `skin_mm` = top/bottom shell thickness);
- the required safety factor; the seam height, pause length and any visible gap and where it is;
- reprint time and filament, if known.

**Missing information.** Never invent a measurement, tolerance or load. If one is missing, ask. If you cannot ask
(a non-interactive run), leave it out: the script refuses a fit feature without a limit and a beam without a
load (exit code 2) rather than guess. For non-critical inputs (target safety factor, cosmetic tolerance) the
script applies a stated default (2.0, ± 1.0 mm); report each default as ASSUMED.

### Step 2 - Encode the case as JSON (your judgement goes here)
Write `case.json` following `references/case_schema.md`; `references/example_case.json` shows every field for a
different part (do not copy its numbers). Expert choices the script cannot make for you:
- **Limits:** a range `[lo, hi]` goes in `range_mm`; a minimum wall in `min_mm`. A hole **position tolerance**
  `tol_center`, when you can only measure the centre-to-centre spacing, becomes a spacing feature with
  `nominal_mm` = design spacing and `tolerance_mm` = `tol_center` (conservative: as if one hole moved).
- **Readings:** pass all readings in `readings_mm`; the script uses the worst one. Use the **smallest** diameter
  of an oval (dented) hole and thickness readings taken **near the support**, where the moment is largest.
- **Arm length** `length_mm`: from the load line to the **edge of the clamp**, not to the hole centre. If the
  clamp edge is unknown, use the centre-to-centre distance (conservative) and say so.
- **Width** `width_mm`: the measured width of the section at the clamp edge (subtract a hole only if it cuts
  that section).
- **Seam:** any pause, resume or correction creates one at the resume height `z_mm`. Give
  `visible_gap.distance_from_load_mm` (distance from the load point along the arm) if a gap was seen.

### Step 3 - Run the script
```bash
python3 <skill-dir>/scripts/check_part.py case.json --out result.json
```
`<skill-dir>` is the directory this SKILL.md is in. Only the Python standard library is used (Python 3.10+).
Run `python3 <skill-dir>/scripts/check_part.py --selftest` first if you have not run it in this session: it
checks the code against hand-calculated numbers (σ = 9.42 MPa, SF = 4.14 for the HW5 demo bracket).

### Step 4 - If execution fails
- **Exit code 2, `INPUT ERROR: ...`:** the message names the field. Fix units or a typo and rerun; if the value is
  genuinely missing, ask for it (or, non-interactively, report that the decision cannot go beyond
  TEST_BEFORE_USE without it). Never fill the gap with an invented number just to make the script run.
- **`python3` not found or an import/traceback error:** check you are calling the script by its full path and
  that `scripts/fdm_core/` is next to it; rerun `--selftest`. If it still fails, follow the hand method in
  `references/method.md`, label every number **NOT SCRIPT-VERIFIED**, and ask for a person to recheck.
- **Output that contradicts the inputs** (for example a thickness in the report that is not one you gave):
  stop, fix `case.json`, rerun. Do not edit the script to get a different answer.

### Step 5 - Interpret the output
The report starts with `DECISION:` and lists every rule that fired (`REPRINT because` / `TEST because`).
- **Features:** `used` is the deciding reading; `margin` < 0 is out of tolerance; 0 to 0.05 mm is borderline.
- **Strength:** the solid section is the upper bound and the skins section the lower bound; the decision uses
  the lower bound. `design thickness ... (HW5 tool)` shows what the deviation cost.
- **Seam:** in a flat print the seam carries shear (`if bonded like a layer` is a rough margin); `if fully
  debonded` is the worst case if the seam let go. A large gap between the two is why a test is needed.
- **HW5 check_deviated_part:** the HW5 tool's own decision on the two-sided features and the solid beam. If it
  is *less* strict than the final decision, that is expected (it knows nothing about skins, seams or gaps). If it
  is *stricter*, investigate before answering.

Decision rules the script applies (identical to the Markdown-only skill), in order:
- **REPRINT** if: a fit or load-bearing feature is out of tolerance or a one-sided bound is violated; the solid
  SF < 1; an open seam gap lies in the high-moment region (more than L/3 from the load point); an open gap at a
  seam that carries bending tension (upright print); or a visible gap and the fully debonded SF < 1.
- **TEST_BEFORE_USE** if no REPRINT rule fired and: a repair seam crosses the load path; any visible seam gap in
  the low-moment region or of unknown location; the lower-bound SF is below target; the fully debonded SF is
  below target; a feature is borderline; or a load-bearing feature has no load case.
- **KEEP** only if nothing above fired.

### Step 6 - Verify before answering
- Spot-check one number by hand: σ_solid = 6 F L / (b t²) with the script's F, L, b, t. It must match to 1 %.
- Check that every value in the output's echo came from the report, and that the deciding readings are the ones
  you meant (smallest hole diameter, thinnest thickness near the clamp).
- List spec items the script did not check (for example a volume spec or a minimum wall you had no reading for)
  as **not checked**.
- If the reprint is cheaper and faster than the proof test, say so: the label stays, but the person may choose
  to reprint.

### Step 7 - Recognise when a person must review
Always hand over to a person, with the script's `Human checks` list plus anything you assumed, when the decision
is TEST_BEFORE_USE or REPRINT, any input was assumed, there is any visible seam defect, the case is outside
Section 1, or your hand spot-check disagrees with the script. The script trusts its inputs; it cannot see the
part, test-fit a bolt or proof-load it.

## 3. Equivalent MCP tool
The same HW5 core is served as the MCP tool `check_deviated_part` by the `fdm-mcp` server
(github.com/akshara-ns/fdm-mcp-server). If that server is connected you may call it as an independent check of
the two-sided features and the solid-section safety factor, but it has no range or one-sided limits, skins
section or seam check, so the script is the primary tool for this skill.

## 4. Answer format
1. **Decision** in one line, then the rules that fired (from the script).
2. The exact command you ran and the script's report (or its key lines).
3. Feature table and strength/seam numbers, copied from the output with units.
4. Your input choices (length, width, readings, section) and why; assumptions labelled ASSUMED or GIVEN; spec
   items not checked.
5. Your hand spot-check.
6. Human checks and what result would change the decision.
