"""Tests for libs/lib_epd_family.py — EPD reference product → scaled variants.

Synthetic frames modelled on the Tectonic FP family (EPD-IES-0022920): the
100 mm board is the reference (Y), the others are N with the EPD's factor.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from libs import lib_epd_family as ef
from libs.lib_data import fn155_load_edits_dataframe, fn156b_append_edit_records


def _row(eid, name, flag, factor, thick, a1a3=None, reg="EPD-IES-0022920", **kw):
    r = {
        "0__EETRA_ID": eid, "A__ProductName": name,
        "E__EPD_RegNumber": reg, "E__EPD_ConvFactor": flag, "E__EPD_MultFactor": factor,
        "P__Thick_mm": thick, "P__Mass_kgm3": "60", "P__L_WmK": None,
        "G__GWP_Metric": "GWP-T", "G__GWP_FU": "m2", "G__GWP_A1A3": a1a3,
        "G__GWP_A4": "1.3", "G__GWP_B1": "mnd", "G__GWP_D": None,
    }
    r.update(kw)
    return r


@pytest.fixture
def family() -> pd.DataFrame:
    return pd.DataFrame([
        _row("REF", "Tectonic FP Basic - 100 mm", "Y", "1", "100", 2.7),
        _row("V80", "Tectonic FP Basic - 80 mm", "N", "0.87", "80", 2.349),
        # whitespace variant of the same registration number
        _row("V40", "Tectonic FP - 40 mm", "N", "0.61", "40", 1.647, reg="EPD-IES- 0022920"),
        _row("NR", "No factor", "N", "n/r", "50", 9.9),
        _row("OTHER", "Other EPD", "N", "2", "50", 1.0, reg="S-P-00001"),
    ])


def test_registration_numbers_normalise():
    assert ef.fn620_normalise_reg("S-P- 01137") == ef.fn620_normalise_reg("s-p-01137")
    assert ef.fn620_normalise_reg("n/r") == ""
    assert ef.fn620_normalise_reg(pd.NA) == ""


def test_family_and_reference(family):
    assert set(ef.fn624_family(family, "EPD-IES-0022920")["0__EETRA_ID"]) == {"REF", "V80", "V40", "NR"}
    ref, status = ef.fn625_family_reference(family, "EPD-IES-0022920")
    assert status == "ok" and ref["0__EETRA_ID"] == "REF"
    # NR has no numeric factor, OTHER is another EPD
    ids = {r["0__EETRA_ID"] for r in ef.fn626_family_variants(family, "EPD-IES-0022920")}
    assert ids == {"V80", "V40"}


def test_two_references_are_ambiguous(family):
    family.loc[family["0__EETRA_ID"] == "V80", "E__EPD_ConvFactor"] = "Y"
    assert ef.fn625_family_reference(family, "EPD-IES-0022920") == (None, "ambiguous")
    ref = family.loc[family["0__EETRA_ID"] == "REF"].iloc[0].to_dict()
    assert ef.fn629_propagation_plan(family, ref) == []


def test_variant_values_scale_every_module_and_rederive_bases(family):
    ref = family.iloc[0].to_dict()
    var = family.iloc[1].to_dict()
    out = ef.fn628_variant_gwp_values(ref, 0.87, var)
    assert out["G__GWP_A1A3"] == pytest.approx(2.349)
    assert out["G__GWP_A4"] == pytest.approx(1.131)       # modules scale too
    assert out["G__GWP_B1"] == "mnd"                      # declaration status copied
    assert out["G__GWP_D"] is None
    assert out["G__GWP_FU"] == "m2" and out["G__GWP_Metric"] == "GWP-T"
    # FU m2 anchors _m2; _m3 = /d, _kg = /ρ — the variant's own 80 mm, 60 kg/m³
    assert out["G__GWP_A1A3_m2"] == pytest.approx(2.349)
    assert out["G__GWP_A1A3_m3"] == pytest.approx(2.349 / 0.08)
    assert out["G__GWP_A1A3_kg"] == pytest.approx(2.349 / 0.08 / 60)
    assert out["G__GWP_A1A3_m2R1"] is None                # no λ, no R, nothing stored


def test_underivable_basis_is_rescaled_not_left_stale():
    ref = _row("REF", "r", "Y", "1", "100", 2.0)
    var = _row("V", "v", "N", "2", "40-140", 1.0, G__GWP_A1A3_m3="10")  # thickness not numeric
    out = ef.fn628_variant_gwp_values(ref, 2.0, var)
    assert out["G__GWP_A1A3"] == 4.0
    assert out["G__GWP_A1A3_m3"] == pytest.approx(40.0)   # 10 × (4.0 / 1.0)


def test_derive_bases_matches_worked_example():
    # GWP_CONVERSIONS.md §6 — Blocco THERMO 450, declared per m³
    b = ef.fn627_derive_gwp_bases(39.8, "m3", rho=450, d_mm=240, lam=0.108)
    assert b["G__GWP_A1A3_m3"] == 39.8
    assert b["G__GWP_A1A3_kg"] == pytest.approx(0.08844, rel=1e-3)
    assert b["G__GWP_A1A3_m2"] == pytest.approx(9.552)
    assert b["G__GWP_A1A3_m2R1"] == pytest.approx(39.8 * 0.108)
    assert ef.fn627_derive_gwp_bases(1.0, "ton")["G__GWP_A1A3_kg"] == 0.001


def test_plan_lists_only_changed_variants(family):
    ref = family.iloc[0].to_dict()
    plan = ef.fn629_propagation_plan(family, ref)
    assert {p["id"] for p in plan} == {"V80", "V40"}
    v40 = next(p for p in plan if p["id"] == "V40")
    assert v40["values"]["G__GWP_A4"] == pytest.approx(1.3 * 0.61)
    assert "G__GWP_A1A3" not in v40["values"]             # 2.7 × 0.61 already stored

    # new EPD figure on the reference → every variant follows
    ref["G__GWP_A1A3"] = 3.0
    plan = {p["id"]: p for p in ef.fn629_propagation_plan(family, ref)}
    assert plan["V80"]["values"]["G__GWP_A1A3"] == pytest.approx(2.61)
    assert plan["V40"]["values"]["G__GWP_A1A3"] == pytest.approx(1.83)


def test_non_reference_propagates_nothing(family):
    assert ef.fn629_propagation_plan(family, family.iloc[1].to_dict()) == []


def test_batch_append_keeps_ids_increasing(tmp_path):
    path = tmp_path / "edits.parquet"
    rows = [({"0__EETRA_ID": i, "G__GWP_A1A3": str(n)}, i) for n, i in enumerate("ABC")]
    fn156b_append_edit_records(rows, "update", path=path, user="test")
    log = fn155_load_edits_dataframe(path)
    assert list(log["0__EETRA_ID"]) == ["A", "B", "C"]
    ids = [int(x) for x in log["_edit_id"]]
    assert ids == sorted(ids) and len(set(ids)) == 3
    assert not math.isnan(float(log["G__GWP_A1A3"].iloc[2]))
