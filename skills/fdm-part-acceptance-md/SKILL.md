---
name: fdm-part-acceptance-md
description: Decide whether an FDM 3D-printed part that was dented, corrected, paused or resumed mid-print can still be used - KEEP, TEST_BEFORE_USE or REPRINT - from caliper measurements, the part's function spec, its load case and the repair seam. Markdown-only version - work everything out by hand from this document; do not run code, scripts or calculators.
---

# FDM part acceptance after an in-print correction (Markdown-only)

You are acting as a mechanical engineer who signs off printed parts. The part did not come out as designed:
our recovery loop (or a person) paused it, dented it, corrected the remaining layers or resumed it. Your job is
to decide, with reasons a person can check, whether it can be used.

**This version has no tools.** Do every calculation by hand in your answer, showing each formula with numbers
and units substituted, so that a reader can redo it. Do not run Python, a shell, a calculator or an MCP tool.

## 1. When to use this skill, and when not to

Use it when a finished (or nearly finished) part deviates from its design and someone asks "can we use it?",
and the part's function can be judged from a few dimensions plus, at most, one cantilever-like load case.

Do **not** decide, and say so, when any of these hold; hand the case to a person instead:
- The part is safety-critical (holds a person, hangs over people, holds pressure, carries hot liquid), or the
  load is impact, vibration or many cycles (fatigue). Static calculations do not cover these.
- The part works near or above its heat deflection temperature (PLA 57 °C, PETG 69 °C, ABS-M30 104 °C).
- The load path is not a simple bending arm, a clamp or a fit (for example a thin shell in compression, a
  snap-fit, a thread). Say the strength is not assessed.

## 2. Inputs you need (with units and valid ranges)

| Input | Unit | Valid range | If missing |
|---|---|---|---|
| Material (PLA, PETG or ABS) | - | these three only | Ask. Do not assume another material's strength. |
| Each functional feature: measured value(s) | mm | 0-500 | Ask. **Never estimate a measurement.** |
| Each functional feature: limit from the designer (nominal ± tolerance, a range, or a one-sided min/max) | mm | tolerance 0.01-10 | Ask. Only the designer knows it. For a purely cosmetic feature you may use ±1.0 mm and say so. |
| Load (force or mass hung) | N or kg | 0.01-5000 N | Ask. Without a load the strength cannot be judged (then the decision is at best TEST_BEFORE_USE). |
| Where the load acts and where the part is held | mm | - | Use the centre-to-centre distance if the clamp edge is unknown (conservative), and say so. |
| Arm width b and thickness t (as printed) | mm | t 0.8-100, b 1-200 | Use the thinnest reading near the support. |
| Print orientation relative to the bending stress | flat / upright | - | Ask, or infer from "printed flat on the bed" and state the inference. |
| Infill and shells | %, mm | - | If infill < 100 % and walls do not fill the section, use the skins-only section (Step 4). |
| Required safety factor | - | 1-10 | Use the spec's value; if none, use 2.0 and say so. |
| Repair seam height, pause length, visible gaps | mm, min | - | If a pause or correction happened, a seam exists even if nobody saw it. |
| Reprint time and filament | h, g | - | Optional; used only to inform the person. |

Convert before you start: 1 kg hung = 9.81 N; 1 in = 25.4 mm; 1 MPa = 1 N/mm². Keep everything in N, mm, MPa.

When you cannot ask (a non-interactive run), continue with the most conservative assumption, label it
**ASSUMED** in the answer, and add a human check for it. Never let an assumption make the result look better.

## 3. Step-by-step procedure

### Step 0 - Hard stops (no calculation needed)
- The part detached, is spaghetti, or a feature is missing entirely: **REPRINT**.
- A visible crack or open gap runs through the most-stressed region of a load-bearing feature: **REPRINT**.
- Material or load unknown and cannot be asked: you cannot reach KEEP.

### Step 1 - Put every limit into one form
- *Range* `[lo, hi]` (for example a hole that must be 4.0-6.5 mm): nominal = (lo + hi)/2, tolerance =
  (hi - lo)/2. Example: [6.0, 6.4] becomes 6.2 ± 0.2 mm.
- *One-sided* (a minimum wall, a maximum height): check the reading directly against the bound; margin =
  reading - min (or max - reading).
- *Hole position*: a position tolerance `tol_center` is the allowed distance of each hole centre from its true
  position. If you can only measure the centre-to-centre spacing, you cannot tell which hole moved, so be
  conservative: the spacing error must be no more than `tol_center` (as if all of it were at one hole).
- *Cosmetic* features (outer shell, appearance): ± 1.0 mm unless the designer says otherwise. A cosmetic
  feature out of tolerance gives a caution, never a REPRINT by itself, **unless the part's function is its
  appearance** (a display or cosplay part). Ask if unclear.

### Step 2 - Choose the reading that decides
- Repeated readings: the reading **farthest from the nominal** (or closest to a one-sided bound) decides.
  For thickness in a bending arm, use the **thinnest** reading near the support.
- A dented hole becomes oval: the smallest diameter decides whether the bolt passes. Calipers read small holes
  low, so a hole near its lower limit should be checked with the actual bolt or a pin gauge.
- Measurement uncertainty: assume ± 0.05 mm for digital calipers on printed plastic. A margin smaller than
  that is **borderline**, which means TEST_BEFORE_USE (test-fit), not KEEP.

### Step 3 - Judge each feature
Deviation = used reading - nominal. Margin = tolerance - |deviation|. Status: OK if margin >= 0.05 mm,
BORDERLINE if 0 <= margin < 0.05 mm, FAIL if margin < 0. Put every feature in a table with spec, readings,
used value, deviation, margin and status.

### Step 4 - Strength of the load-bearing arm
Model the arm as a cantilever: fixed at the support (the clamp edge), point load F at the free end, length L
from the load to the clamp edge, width b, thickness t in the direction the load bends it.

- Bending moment at the support: **M = F · L** (N·mm).
- **Solid section** (100 % infill or walls fill it): I = b t³ / 12, stress **σ = M (t/2) / I = 6 F L / (b t²)**.
- **Skins-only section** (sparse infill): only the top and bottom shells of thickness s carry bending:
  I = b (t³ - (t - 2s)³) / 12, σ = M (t/2) / I. This ignores walls and infill, so it is a **lower bound** on
  strength; the solid result is the upper bound. Decide on the lower bound when it changes the decision.
- Strength to compare with (Bambu Lab PLA/PETG Basic TDS v2.0, Stratasys ABS-M30 data sheet):

  | Material | In-plane strength (along the lines) | E | HDT (0.45 MPa) |
  |---|---|---|---|
  | PLA | 39 MPa | 2.68 GPa | 57 °C |
  | PETG | 48 MPa | 1.46 GPa | 69 °C |
  | ABS (ABS-M30) | 30.8 MPa | 2.40 GPa | 104 °C |

  If the part was printed **flat** (layers parallel to the bending stress), use the in-plane strength. If it
  was printed **upright** (the bending stress pulls layers apart), use in-plane × 0.5, a conservative
  interlayer factor (Ahn et al. 2002 measured 10-73 % of moulded strength across bonds).
- Safety factor **SF = strength / σ**. Compare with the required factor (spec, or 2.0).
- Tip deflection **δ = F L³ / (3 E I)** with E in MPa (2.68 GPa = 2680 MPa). Flag δ > 2 % of L as a stiffness
  caution; above 10 % of L the small-deflection formulas are not valid.
- Validity: if L/t < 4 the arm is too stubby for beam theory; say the result is rough.
- Also compute SF at the **design** thickness, to show how much the deviation cost. SF scales with t² for a
  solid section, so SF_measured = SF_design × (t_measured / t_design)². Use this as a cross-check.

### Step 5 - The repair seam
Every pause, resume or correction leaves a **seam**: the plane where new plastic was laid on a layer that had
cooled. Its bond is weaker than a normal layer and gets worse the longer the pause (PLA cools below its glass
transition within a minute or two, even on a warm bed). Treat the seam's strength as **unknown, between a
normal layer and zero**.

- A seam that is a full layer crosses every section of the arm, so it is **in the load path**.
- **Flat print:** bending stress runs parallel to the seam, so the seam carries interlaminar **shear**.
  Solid section at height z above the bottom: τ = 6 F z (t - z) / (b t³) (maximum 1.5 F / (b t) at mid-height).
  If the seam lies in the sparse core between skins: τ ≈ F / (b (t - s)). A rough allowable shear is
  0.5 × the interlayer design strength (PLA: 0.5 × 0.5 × 39 = 9.75 MPa).
- **Worst case, seam fully debonded:** the two layers (thicknesses z and t - z) bend as separate beams:
  I_split = b (z³ + (t - z)³) / 12, σ = M · (max(z, t - z) / 2) / I_split, SF = in-plane strength / σ.
- **Upright print:** the seam is pulled apart directly by the bending stress σ_seam = M |z - t/2| / I. A
  calculation cannot vouch for it.
- **Visible gap** (a fingernail catches, light shows through): the bond is not intact. Moment grows linearly
  from the load point to the support, so a gap within the third of the arm nearest the load is in the
  low-moment region; elsewhere it is in the high-moment region.

### Step 6 - Decide (apply the rules in this order; list every rule that fired)
**REPRINT** if any of:
1. a fit or load-bearing feature is out of tolerance (FAIL), or a one-sided bound is violated;
2. the solid-section SF < 1;
3. an open gap at the seam lies in the high-moment region (more than L/3 from the load point);
4. an open gap at a seam that carries bending tension (upright print);
5. there is a visible gap and the fully debonded SF < 1.

**TEST_BEFORE_USE** if no REPRINT rule fired and any of:
1. a repair seam crosses the load path (always, for a full-layer seam in a loaded arm);
2. any visible seam gap in the low-moment region, or of unknown location;
3. the lower-bound SF (skins-only, or solid if solid) is below the required SF;
4. the fully debonded SF is below the required SF;
5. a feature is BORDERLINE;
6. a load-bearing feature exists but no load case was given.

**KEEP** only if no rule above fired: every feature within tolerance with margin, the lower-bound SF meets the
target, and there is no seam or defect in the load path.

Then give the reprint cost if you have the numbers: cost = filament g / 1000 × $23/kg + hours × $0.50/h
(defaults: Bambu PLA price, machine time). If a reprint is cheaper and quicker than the proof test, say so: the
decision label stays as the rules give it, but the person may reasonably choose to reprint.

### Step 7 - Verify before you answer
- Units: every stress in MPa (N/mm²), every moment in N·mm, every length in mm.
- Recompute σ by a second route (σ = M / Z with Z = b t² / 6 for a solid section) and check it matches.
- Ratio check: SF_measured / SF_design should equal (t_measured / t_design)² for a solid section.
- Plausibility: printed brackets usually have SF between 1 and 20; σ above the material strength means a
  mistake or a broken part; δ of several millimetres on a short stiff arm means a units slip.
- Re-read the spec for items you did not check (for example a volume or mass spec you cannot measure) and
  list them as **not checked**, with what measurement would check them.

### Step 8 - Recognise when a person must review
Always hand over to a person, with a clear list, when: the decision is TEST_BEFORE_USE or REPRINT; any input
was ASSUMED; there is any visible seam defect; the case is outside Section 1's scope; or your two calculation
routes disagree by more than 2 %. The person must test-fit fits with the real bolt, inspect the seam, run the
proof test and confirm tolerances and load with the designer.

**Proof test for TEST_BEFORE_USE:** hang the service load on the part for 10 minutes (or load a sacrificial
copy printed with the same pause to SF_target × load), then re-inspect the seam. Any crack, creak or growth of
a gap means REPRINT.

## 4. Worked example (a different part, to show the form)

A PLA shelf hook printed flat: arm L = 40 mm, b = 20 mm, design t = 5.0 mm, readings 4.55 and 4.50 mm, solid
infill, 2 kg hung (F = 2 × 9.81 = 19.62 N), required SF 2, a seam from a 3-minute pause at z = 2.0 mm, no gap.
- M = 19.62 × 40 = 784.8 N·mm. Use t = 4.50 mm. σ = 6 × 19.62 × 40 / (20 × 4.50²) = 4708.8 / 405 = 11.63 MPa.
- SF = 39 / 11.63 = 3.35 ≥ 2. Design: σ = 4708.8 / 500 = 9.42 MPa, SF = 4.14; check 4.14 × (4.5/5)² = 3.35 ✓.
- Seam shear: τ = 6 × 19.62 × 2.0 × 2.5 / (20 × 4.5³) = 588.6 / 1822.5 = 0.32 MPa, far below 9.75 MPa.
- Debonded: I_split = 20 × (2.0³ + 2.5³) / 12 = 20 × 23.625 / 12 = 39.4 mm⁴; σ = 784.8 × 1.25 / 39.4 = 24.9 MPa;
  SF = 39 / 24.9 = 1.57 < 2.
- Rules fired: TEST 1 (seam in load path), TEST 4 (debonded SF 1.57 < 2). Decision **TEST_BEFORE_USE**.

## 5. Answer format
1. **Decision** in one line, then the rules that fired.
2. Feature table (spec, readings, used value, deviation, margin, status).
3. Strength: every formula with numbers, solid and lower-bound SF, design SF, deflection, the cross-check.
4. Seam: location, what it carries, bonded and debonded results, gap region.
5. Assumptions (label each ASSUMED or GIVEN), spec items not checked.
6. Human checks and what result would change the decision.
