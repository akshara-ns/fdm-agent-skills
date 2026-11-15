# Method behind check_part.py (also the hand fallback when the script cannot run)

Use these only if the script fails, and label the results NOT SCRIPT-VERIFIED.

**Material values** (Bambu Lab PLA/PETG Basic TDS v2.0; Stratasys ABS-M30): in-plane strength PLA 39, PETG 48,
ABS 30.8 MPa; E PLA 2.68, PETG 1.46, ABS 2.40 GPa. Across layers = in-plane × 0.5 (design choice; Ahn et al.
2002 measured 10-73 % of moulded strength across bonds).

**Features.** Range [lo, hi] -> nominal (lo+hi)/2, tolerance (hi-lo)/2. Worst reading = farthest from nominal.
Margin = tolerance - |reading - nominal|; FAIL < 0, BORDERLINE < 0.05 mm, else OK. One-sided: margin =
reading - min (or max - reading). Cosmetic out of tolerance = caution only.

**Cantilever** (fixed at the clamp edge, point load F at distance L):
M = F L; solid I = b t³/12, σ = 6 F L/(b t²); skins-only I = b (t³ - (t-2s)³)/12, σ = M (t/2)/I (lower bound);
SF = strength/σ (in-plane for flat prints, × 0.5 for upright); δ = F L³/(3 E I), caution above 2 % of L;
L/t < 4 means rough.

**Seam at height z** (flat print, carries shear): solid τ = 6 F z (t-z)/(b t³); in a sparse core
τ ≈ F/(b (t-s)); rough allowable 0.5 × 0.5 × in-plane strength. Fully debonded bound:
I_split = b (z³ + (t-z)³)/12, σ = M · max(z, t-z)/2 / I_split. Upright print: σ_seam = M |z - t/2|/I (tension
across the seam). A gap more than L/3 from the load point is in the high-moment region.

**Decision rules:** as listed in SKILL.md Step 5.

**Reprint cost** = g/1000 × $23/kg + h × $0.50/h.
