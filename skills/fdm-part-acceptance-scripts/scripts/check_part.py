#!/usr/bin/env python3
"""Acceptance check for an FDM part that was dented, corrected or resumed mid-print.

Decides KEEP / TEST_BEFORE_USE / REPRINT from a case file (JSON) of caliper measurements, the part's function
spec, its load case and the repair seam. It reuses the HW5 tools unchanged (fdm_core/new_tools.check_deviated_part
for the tolerance check, fdm_core/print_tools.check_cantilever for the solid-section strength) and adds what those
tools do not cover: range and one-sided limits, repeated readings, measurement uncertainty, a skins-only section
for sparse infill, and the repair seam (shear across it and a fully debonded bound).

    python3 check_part.py case.json                 human-readable report on stdout
    python3 check_part.py case.json --out res.json  also save the full record as JSON
    python3 check_part.py --template                print an example case file
    python3 check_part.py --selftest                check the code against hand-calculated numbers

Exit codes: 0 = decision made, 2 = invalid or missing input (message says what to fix), 1 = internal error.
Only the Python standard library is needed (Python 3.10+).
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fdm_core.new_tools import check_deviated_part                       # noqa: E402  (HW5 tool 6)
from fdm_core.print_tools import MATERIALS, INTERLAYER_FACTOR, ToolInputError, G  # noqa: E402

VERSION = "1.0 (HW6)"
DEFAULT_UNCERTAINTY_MM = 0.05     # digital calipers on printed plastic: resolution 0.01, repeatability ~0.02-0.05
DEFAULT_TARGET_SF = 2.0           # same default as HW5 check_cantilever when the spec gives none
SHEAR_TO_TENSILE = 0.5            # rough shear strength / tensile strength for a printed interface (assumption)

TEMPLATE = {
    "part": "shelf hook (example only: replace every value with your own case)",
    "material": "PLA",
    "measurement_uncertainty_mm": 0.05,
    "features": [
        {"name": "screw hole diameter", "role": "fit", "readings_mm": [5.22, 5.25], "nominal_mm": 5.3,
         "tolerance_mm": 0.15},
        {"name": "rail slot width", "role": "fit", "readings_mm": [6.18], "range_mm": [6.0, 6.4]},
        {"name": "back plate wall", "role": "load_bearing", "readings_mm": [2.9], "min_mm": 2.4},
        {"name": "outer shell length", "role": "cosmetic", "readings_mm": [40.6], "nominal_mm": 40.0},
    ],
    "beam": {"length_mm": 40, "width_mm": 20, "nominal_thickness_mm": 5.0,
             "measured_thickness_readings_mm": [4.55, 4.5], "load_kg": 2, "orientation": "flat",
             "target_safety_factor": 2, "section": "solid"},
    "seam": {"z_mm": 2.0, "pause_min": 3},
    "reprint": {"time_h": 2.5, "filament_g": 38},
}


class CaseError(ValueError):
    pass


def _num(d, key, lo, hi, unit="", required=True, default=None):
    v = d.get(key, default)
    if v is None:
        if required:
            raise CaseError(f"{key} is required ({unit}).".replace(" ()", ""))
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise CaseError(f"{key} must be a number in {unit or 'the stated unit'} (got {v!r}).")
    if math.isnan(v) or not (lo <= v <= hi):
        raise CaseError(f"{key} = {v:g} {unit} is outside the valid range {lo:g}-{hi:g} {unit}.")
    return v


def _readings(f, name):
    if "readings_mm" in f:
        r = f["readings_mm"]
        if not isinstance(r, list) or not r:
            raise CaseError(f"{name}: readings_mm must be a non-empty list of numbers in mm.")
        return [_num({"x": x}, "x", 0, 500, "mm") for x in r]
    if "measured_mm" in f:
        return [_num(f, "measured_mm", 0, 500, "mm")]
    raise CaseError(f"{name}: give the measurement as measured_mm or readings_mm (mm). Never estimate it.")


# --------------------------------------------------------------------------------------------------------------
# 1. Features: normalise every spec form, pick the worst reading, then let the HW5 tool judge the two-sided ones
# --------------------------------------------------------------------------------------------------------------
def normalise_features(features, u):
    two_sided, one_sided, rows = [], [], []
    for i, f in enumerate(features, 1):
        name = str(f.get("name") or f"feature {i}")
        role = str(f.get("role") or "").lower()
        if role not in ("cosmetic", "fit", "load_bearing"):
            raise CaseError(f"{name}: role must be cosmetic, fit or load_bearing (got {f.get('role')!r}).")
        reads = _readings(f, name)
        if "range_mm" in f:
            lo, hi = (float(x) for x in f["range_mm"])
            if not lo < hi:
                raise CaseError(f"{name}: range_mm must be [low, high] with low < high.")
            nom, tol, spec = (lo + hi) / 2, (hi - lo) / 2, f"{lo:g} to {hi:g} mm"
        elif "nominal_mm" in f:
            nom = _num(f, "nominal_mm", 0.1, 500, "mm")
            tol = f.get("tolerance_mm")
            if tol is None and role != "cosmetic":
                raise CaseError(f"{name}: tolerance_mm (or range_mm/min_mm/max_mm) is required for a {role} "
                                f"feature; only the designer knows it. Ask for it instead of guessing.")
            tol = 1.0 if tol is None else _num(f, "tolerance_mm", 0.01, 10, "mm")
            spec = f"{nom:g} ± {tol:g} mm"
        elif "min_mm" in f or "max_mm" in f:
            lo = _num(f, "min_mm", 0, 500, "mm", required=False)
            hi = _num(f, "max_mm", 0, 500, "mm", required=False)
            worst = min(reads) if lo is not None else max(reads)
            margin = (worst - lo) if lo is not None else (hi - worst)
            status = "FAIL" if margin < 0 else ("BORDERLINE" if margin < u else "OK")
            if status == "FAIL" and role == "cosmetic":
                status = "CAUTION"
            one_sided.append({"name": name, "role": role, "spec": (f">= {lo:g} mm" if lo is not None else
                                                                    f"<= {hi:g} mm"),
                              "readings_mm": reads, "used_mm": worst, "margin_mm": round(margin, 3),
                              "status": status})
            continue
        else:
            raise CaseError(f"{name}: give the limit as nominal_mm + tolerance_mm, range_mm [lo, hi], min_mm or max_mm.")
        worst = max(reads, key=lambda x: abs(x - nom))          # the reading farthest from the centre decides
        two_sided.append({"name": name, "role": role, "nominal_mm": round(nom, 4), "measured_mm": worst,
                          "tolerance_mm": round(tol, 4)})
        rows.append({"name": name, "spec": spec, "readings_mm": reads, "used_mm": worst,
                     "margin_mm": round(tol - abs(worst - nom), 3)})
    return two_sided, one_sided, rows


# --------------------------------------------------------------------------------------------------------------
# 2. Strength: solid section (HW5 check_cantilever, via check_deviated_part), skins-only lower bound, seam
# --------------------------------------------------------------------------------------------------------------
def beam_numbers(b, material):
    props = MATERIALS[material]
    L = _num(b, "length_mm", 5, 400, "mm")
    w = _num(b, "width_mm", 1, 200, "mm")
    t0 = _num(b, "nominal_thickness_mm", 0.8, 100, "mm")
    if "measured_thickness_readings_mm" in b:
        reads = [_num({"x": x}, "x", 0.8, 100, "mm") for x in b["measured_thickness_readings_mm"]]
    else:
        reads = [_num(b, "measured_thickness_mm", 0.8, 100, "mm")]
    t = min(reads)                                              # thinnest reading in the high-moment region
    if b.get("load_N") is None and b.get("load_kg") is None:
        raise CaseError("beam: give the service load as load_N or load_kg. Ask for it; do not assume a load.")
    F = _num(b, "load_N", 0.01, 5000, "N") if b.get("load_N") is not None else _num(b, "load_kg", 0.001, 500, "kg") * G
    orient = str(b.get("orientation") or "").lower()
    if orient not in ("flat", "upright"):
        raise CaseError("beam.orientation must be 'flat' (bending stress runs along the layers) or 'upright' "
                        "(bending stress pulls layers apart).")
    target = _num(b, "target_safety_factor", 1, 10, "", required=False) or DEFAULT_TARGET_SF
    k_z = _num(b, "interlayer_factor", 0.1, 1, "", required=False) or INTERLAYER_FACTOR
    section = str(b.get("section") or "solid").lower()
    if section not in ("solid", "skins"):
        raise CaseError("beam.section must be 'solid' (100 % infill or all walls) or 'skins' (sparse infill).")
    s = _num(b, "skin_mm", 0.2, 10, "mm", required=(section == "skins"))
    if section == "skins" and 2 * s >= t:
        section = "solid"                                       # skins meet: the section is solid anyway

    xy = props["xy_strength_MPa"]
    strength = xy if orient == "flat" else xy * k_z
    M = F * L
    I_solid = w * t ** 3 / 12
    I = I_solid if section == "solid" else w * (t ** 3 - (t - 2 * s) ** 3) / 12
    sigma = M * (t / 2) / I
    E = props["E_GPa"] * 1000
    return {"L": L, "w": w, "t0": t0, "t": t, "t_reads": reads, "F": F, "M": M, "orient": orient, "target": target,
            "k_z": k_z, "section": section, "s": s, "xy": xy, "strength": strength, "I_solid": I_solid, "I": I,
            "sigma": sigma, "sf": strength / sigma, "sf_solid": strength / (M * (t / 2) / I_solid),
            "defl": F * L ** 3 / (3 * E * I), "E": E}


def seam_numbers(seam, bn):
    t, w, F, M = bn["t"], bn["w"], bn["F"], bn["M"]
    z = _num(seam, "z_mm", 0.05, 100, "mm")
    if z >= t:
        raise CaseError(f"seam.z_mm = {z:g} mm is above the measured thickness {t:g} mm.")
    interlayer = bn["xy"] * bn["k_z"]                         # tensile design strength across layers
    shear_allow = SHEAR_TO_TENSILE * interlayer
    out = {"z_mm": z, "offset_from_neutral_axis_mm": z - t / 2}
    if bn["orient"] == "flat":
        # bending stress runs parallel to the seam; the seam carries interlaminar shear
        if bn["section"] == "skins" and bn["s"] < z < t - bn["s"]:
            tau = F / (w * (t - bn["s"]))                       # sandwich: core shear ~ V / (b d)
            where = "in the sparse core between the skins"
        else:
            tau = 6 * F * z * (t - z) / (w * t ** 3)            # solid rectangle: V Q / (I b)
            where = "in a solid region"
        out.update({"shear_at_seam_MPa": tau, "where": where, "seam_shear_allowable_MPa": shear_allow,
                    "sf_seam_shear_if_bonded": shear_allow / tau, "seam_carries": "interlaminar shear"})
        # fully debonded bound: the two layers bend as separate beams sharing the moment by stiffness
        t1, t2 = z, t - z
        I_split = w * (t1 ** 3 + t2 ** 3) / 12
        sig_split = M * (max(t1, t2) / 2) / I_split
        out.update({"sf_if_seam_fully_debonded": bn["xy"] / sig_split})
    else:
        sig_seam = M * abs(z - t / 2) / bn["I_solid"]
        out.update({"seam_carries": "bending tension across the layers",
                    "normal_stress_at_seam_MPa": sig_seam,
                    "sf_seam_if_bonded_like_other_layers": interlayer / sig_seam if sig_seam else float("inf"),
                    "sf_if_seam_fully_debonded": 0.0})
    gap = seam.get("visible_gap")
    if gap:
        d = _num(gap, "distance_from_load_mm", 0, 400, "mm", required=False)
        out["visible_gap_length_mm"] = _num(gap, "length_mm", 0.1, 400, "mm", required=False)
        if d is None:
            out["gap_region"] = "unknown"
        else:
            out["gap_moment_fraction"] = min(1.0, d / bn["L"])
            out["gap_region"] = "high_moment" if d > bn["L"] / 3 else "low_moment"
    out["pause_min"] = _num(seam, "pause_min", 0, 10000, "min", required=False)
    return out


# --------------------------------------------------------------------------------------------------------------
# 3. Decision (the same rules as SKILL.md)
# --------------------------------------------------------------------------------------------------------------
def decide(hw5, one_sided, rows, bn, sn, u):
    reprint, test, notes = [], [], []
    for r in hw5["features"]:
        if r["status"] == "FAIL":
            reprint.append(f"{r['name']} is out of tolerance ({r['deviation_mm']:+.3f} mm vs ±{r['tolerance_mm']:g}).")
    for r in rows:
        if 0 <= r["margin_mm"] < u:
            test.append(f"{r['name']} is within {u:g} mm of its limit (margin {r['margin_mm']:.3f} mm): "
                        f"check it with the real mating part.")
    for r in one_sided:
        if r["status"] == "FAIL":
            reprint.append(f"{r['name']} violates {r['spec']} (reading {r['used_mm']:g} mm).")
        elif r["status"] == "BORDERLINE":
            test.append(f"{r['name']} is within {u:g} mm of {r['spec']}.")
    if bn:
        if bn["sf_solid"] < 1:
            reprint.append(f"Even the solid section breaks: safety factor {bn['sf_solid']:.2f} < 1.")
        elif bn["sf"] < bn["target"]:
            test.append(f"Lower-bound safety factor {bn['sf']:.2f} is below the target {bn['target']:g}.")
        if bn["defl"] > 0.02 * bn["L"]:
            notes.append(f"Tip deflection {bn['defl']:.2f} mm is over 2 % of the arm length; check stiffness.")
    if sn:
        if bn and bn["orient"] == "upright":
            if sn.get("gap_region"):
                reprint.append("An open gap at a seam that carries the bending tension (upright print).")
            else:
                test.append("The seam carries the bending tension directly (upright print): proof test required.")
        if sn.get("gap_region") == "high_moment":
            reprint.append("An open gap at the seam lies in the high-moment two-thirds of the arm.")
        elif sn.get("gap_region") in ("low_moment", "unknown"):
            test.append("An open gap at the seam means the bond is not intact"
                        + (" (location unknown)." if sn["gap_region"] == "unknown" else " (low-moment end)."))
        if sn.get("sf_if_seam_fully_debonded", 99) < 1 and sn.get("gap_region"):
            reprint.append(f"With the visible gap, a fully debonded seam would break the arm "
                           f"(safety factor {sn['sf_if_seam_fully_debonded']:.2f}).")
        elif bn and sn.get("sf_if_seam_fully_debonded", 99) < bn["target"]:
            test.append(f"If the seam let go completely the safety factor would drop to "
                        f"{sn['sf_if_seam_fully_debonded']:.2f}, below the target {bn['target']:g}.")
        test.append("A pause/resume seam crosses the load path; its bond strength is unknown.")
    if bn is None and any(r["role"] == "load_bearing" for r in hw5["features"]):
        test.append("A load-bearing feature was listed but no load case was given, so strength was not checked.")
    decision = "REPRINT" if reprint else ("TEST_BEFORE_USE" if test else "KEEP")
    return decision, reprint, test, notes


def run_case(case):
    if not isinstance(case, dict):
        raise CaseError("The case file must be a JSON object.")
    material = str(case.get("material") or "").upper()
    if material not in MATERIALS:
        raise CaseError(f"material must be one of {', '.join(MATERIALS)} (got {case.get('material')!r}).")
    u = _num(case, "measurement_uncertainty_mm", 0, 1, "mm", required=False) or DEFAULT_UNCERTAINTY_MM
    feats = case.get("features") or []
    if not feats:
        raise CaseError("Give at least one measured feature.")
    two_sided, one_sided, rows = normalise_features(feats, u)

    b = case.get("beam")
    bn = beam_numbers(b, material) if b else None
    hw5_beam = None
    if bn:
        hw5_beam = {"material": material, "length_mm": bn["L"], "width_mm": bn["w"],
                    "nominal_thickness_mm": bn["t0"], "measured_thickness_mm": bn["t"], "load_N": bn["F"],
                    "orientation": bn["orient"], "target_safety_factor": bn["target"], "interlayer_factor": bn["k_z"]}
    sn = seam_numbers(case["seam"], bn) if (case.get("seam") and bn) else None
    if case.get("seam") and not bn:
        raise CaseError("A seam was given without a beam load case; give the load case so the seam can be checked.")
    rp = case.get("reprint") or {}
    hw5 = check_deviated_part(features=two_sided or [{"name": "(none)", "role": "cosmetic", "nominal_mm": 1,
                                                      "measured_mm": 1}],
                              beam=hw5_beam, repaired_in_load_path=bool(sn),
                              reprint_time_h=rp.get("time_h"), reprint_filament_g=rp.get("filament_g"))
    decision, why_reprint, why_test, notes = decide(hw5, one_sided, rows, bn, sn, u)
    return {"tool": "check_part", "version": VERSION, "decision": decision,
            "reasons_reprint": why_reprint, "reasons_test": why_test, "notes": notes,
            "features_two_sided": [{**r, **{k: v for k, v in h.items() if k in ("deviation_mm", "tolerance_used_pct",
                                                                                   "status")}}
                                   for r, h in zip(rows, hw5["features"])] if two_sided else [],
            "features_one_sided": one_sided,
            "beam": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in bn.items()} if bn else None,
            "seam": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sn.items()} if sn else None,
            "hw5_check_deviated_part": {"decision": hw5["decision"], "verdict": hw5["verdict"],
                                        "summary": hw5["summary"], "results": hw5["results"]},
            "measurement_uncertainty_mm": u,
            "assumptions": [
                f"Material strengths from data sheets ({material}: in-plane {MATERIALS[material]['xy_strength_MPa']:g} "
                f"MPa); across layers = in-plane x interlayer_factor ({bn['k_z'] if bn else INTERLAYER_FACTOR:g}, "
                "Ahn et al. 2002 range 0.1-0.73).",
                "Cantilever with a rigid clamp and a static point load: sigma = M c / I, M = F L.",
                "The thinnest thickness reading is used; the worst reading of each feature decides it.",
                "Skins-only section ignores walls and infill (lower bound); solid section is the upper bound.",
                f"Seam shear allowable = {SHEAR_TO_TENSILE:g} x the interlayer tensile design value (rough); the "
                "real bond after a pause can be anywhere from that to zero, so the debonded bound is also shown.",
                "Range limits are converted exactly to nominal = midpoint, tolerance = half-width for the HW5 tool.",
            ],
            "human_checks": [
                "Test-fit the real bolt or mating part in every fit feature; calipers read small holes low.",
                "Inspect the seam all round (fingernail, magnifier) and photograph any gap.",
                "For TEST_BEFORE_USE: proof-load to the service load for 10 min (or a sacrificial copy to "
                "target_SF x load), then re-inspect the seam; any crack, creak or growth of a gap means REPRINT.",
                "Confirm the tolerances, load and clamp position with the designer; the script trusts its inputs.",
                "Decide with the owner whether the test is worth it when a reprint is cheap.",
            ]}


def report(r):
    out = [f"DECISION: {r['decision']}", ""]
    for x in r["reasons_reprint"]:
        out.append(f"  REPRINT because: {x}")
    for x in r["reasons_test"]:
        out.append(f"  TEST because:    {x}")
    for x in r["notes"]:
        out.append(f"  note:            {x}")
    out += ["", "Features (worst reading decides):"]
    for f in r["features_two_sided"]:
        out.append(f"  {f['name']:<34} spec {f['spec']:<16} used {f['used_mm']:>7.3f}  dev {f['deviation_mm']:+.3f}  "
                   f"margin {f['margin_mm']:+.3f} mm  {f['status']}")
    for f in r["features_one_sided"]:
        out.append(f"  {f['name']:<34} spec {f['spec']:<16} used {f['used_mm']:>7.3f}  margin {f['margin_mm']:+.3f} mm  "
                   f"{f['status']}")
    b = r["beam"]
    if b:
        out += ["", f"Strength ({b['orient']} print, {b['section']} section, F = {b['F']:.1f} N, L = {b['L']:g} mm, "
                    f"b = {b['w']:g} mm, t = {b['t']:g} mm (min of {b['t_reads']})):",
                f"  moment M = F L           = {b['M']:.0f} N mm",
                f"  stress, solid section    = {b['M'] * (b['t'] / 2) / b['I_solid']:.2f} MPa -> safety factor "
                f"{b['sf_solid']:.2f}",
                (f"  stress, skins section    = {b['sigma']:.2f} MPa -> safety factor {b['sf']:.2f} (lower bound)"
                 if b["section"] == "skins" else "  (solid section: no skins-only lower bound needed)"),
                f"  decision uses safety factor {b['sf']:.2f} vs target {b['target']:g} "
                f"(strength {b['strength']:g} MPa, {'in-plane' if b['orient'] == 'flat' else 'across layers'})",
                f"  design thickness {b['t0']:g} mm, solid  -> safety factor "
                f"{r['hw5_check_deviated_part']['results']['beam_safety_factor_design']['value']:.2f} (HW5 tool)",
                f"  tip deflection            = {b['defl']:.2f} mm ({100 * b['defl'] / b['L']:.1f} % of L)"]
    s = r["seam"]
    if s:
        out += ["", f"Repair seam at z = {s['z_mm']:g} mm ({s['offset_from_neutral_axis_mm']:+.2f} mm from the neutral "
                    f"axis), carries {s['seam_carries']}:"]
        if "shear_at_seam_MPa" in s:
            out += [f"  shear at seam            = {s['shear_at_seam_MPa']:.3f} MPa ({s['where']})",
                    f"  if bonded like a layer   -> shear safety factor {s['sf_seam_shear_if_bonded']:.1f} "
                    f"(rough allowable {s['seam_shear_allowable_MPa']:.2f} MPa)"]
        out.append(f"  if fully debonded        -> bending safety factor {s['sf_if_seam_fully_debonded']:.2f}")
        if "gap_region" in s:
            out.append(f"  visible gap: {s.get('visible_gap_length_mm', '?')} mm, region {s['gap_region']}")
    h = r["hw5_check_deviated_part"]
    out += ["", f"HW5 check_deviated_part (two-sided features + solid beam): {h['decision']}"]
    if "reprint_cost_usd" in h["results"]:
        out.append(f"Reprint: {h['results']['reprint_time_h']['value']:g} h, cost ${h['results']['reprint_cost_usd']['value']:.2f} "
                   f"(filament + machine time)")
    out += ["", "Human checks:"] + [f"  - {x}" for x in r["human_checks"]]
    return "\n".join(out)


def selftest():
    """Numbers checked by hand (HW5 report, Table 1) plus the formulas this script adds."""
    case = {"material": "PLA", "features": [{"name": "hole", "role": "fit", "measured_mm": 5.22, "nominal_mm": 5.3,
                                             "tolerance_mm": 0.15}],
            "beam": {"length_mm": 40, "width_mm": 20, "nominal_thickness_mm": 5.0, "measured_thickness_mm": 5.0,
                     "load_kg": 2, "orientation": "flat", "target_safety_factor": 2}}
    r = run_case(case)
    sigma = 6 * 2 * 9.81 * 40 / (20 * 25)                         # 9.4176 MPa
    assert abs(r["beam"]["sigma"] - sigma) < 1e-3, r["beam"]["sigma"]
    assert abs(r["beam"]["sf"] - 39 / sigma) < 1e-3                 # 4.14
    assert r["decision"] == "TEST_BEFORE_USE" or r["decision"] == "KEEP"
    # skins section: I = b (t^3 - (t-2s)^3) / 12
    case["beam"].update({"section": "skins", "skin_mm": 1.0})
    r = run_case(case)
    I = 20 * (125 - 27) / 12
    assert abs(r["beam"]["sigma"] - 2 * 9.81 * 40 * 2.5 / I) < 1e-3
    # range limits convert exactly
    two, _, rows = normalise_features([{"name": "h", "role": "fit", "readings_mm": [4.86, 5.02],
                                        "range_mm": [4.0, 6.5]}], 0.05)
    assert two[0]["nominal_mm"] == 5.25 and two[0]["tolerance_mm"] == 1.25 and two[0]["measured_mm"] == 4.86
    # a missing tolerance is refused, not guessed
    try:
        normalise_features([{"name": "h", "role": "fit", "measured_mm": 5, "nominal_mm": 5.3}], 0.05)
        raise AssertionError("missing tolerance accepted")
    except CaseError:
        pass
    print("selftest passed: stress 9.42 MPa and safety factor 4.14 match the hand calculation; skins section, "
          "range conversion and missing-tolerance refusal behave as documented.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("case", nargs="?", help="case file (JSON)")
    ap.add_argument("--out", help="save the full result record as JSON")
    ap.add_argument("--template", action="store_true", help="print an example case file and exit")
    ap.add_argument("--selftest", action="store_true", help="check the code against hand-calculated numbers")
    a = ap.parse_args(argv)
    if a.template:
        print(json.dumps(TEMPLATE, indent=2))
        return 0
    if a.selftest:
        selftest()
        return 0
    if not a.case:
        ap.error("give a case file, or --template / --selftest")
    try:
        case = json.loads(pathlib.Path(a.case).read_text())
        r = run_case(case)
    except FileNotFoundError:
        print(f"INPUT ERROR: case file not found: {a.case}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"INPUT ERROR: the case file is not valid JSON ({e}).", file=sys.stderr)
        return 2
    except (CaseError, ToolInputError) as e:
        print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2
    print(report(r))
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(r, indent=2, ensure_ascii=False))
        print(f"\nFull record saved to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
