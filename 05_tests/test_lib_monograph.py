from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from libs import lib_monograph as lm


@pytest.fixture(autouse=True)
def all_columns_visible(monkeypatch):
    monkeypatch.setattr(lm, "fn319_filter_columns_by_visibility", lambda cols, p, t: cols)
    for fn in (lm.fn600_manufacturer_options, lm.fn603_value_counts, lm.fn604_completeness_by_group,
               lm.fn605_richness_per_product, lm.fn607_kpis):
        fn.clear()
    yield


@pytest.fixture
def aliases_file(tmp_path: Path) -> Path:
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"aliases": {
        "Florim Ceramiche S.p.A. SB": "Florim",
        "Ghost S.r.l.": "Not A Profile",
    }}, ensure_ascii=False), encoding="utf-8")
    return path


KNOWN = frozenset({"Florim", "Knauf", "Ceramica d'Imola s.c."})


# ── fn601 ────────────────────────────────────────────────────────────────────

def test_fn601_alias_hit(aliases_file):
    assert lm.fn601_resolve_profile_name("Florim Ceramiche S.p.A. SB", KNOWN, aliases_file) == "Florim"


def test_fn601_exact_match(aliases_file):
    assert lm.fn601_resolve_profile_name("Knauf", KNOWN, aliases_file) == "Knauf"


def test_fn601_normalised_match(aliases_file):
    assert lm.fn601_resolve_profile_name("Ceramica d’Imola  S.C.", KNOWN, aliases_file) == "Ceramica d'Imola s.c."


def test_fn601_no_match(aliases_file):
    assert lm.fn601_resolve_profile_name("Unical", KNOWN, aliases_file) is None


def test_fn601_alias_to_unknown_target(aliases_file):
    assert lm.fn601_resolve_profile_name("Ghost S.r.l.", KNOWN, aliases_file) is None


# ── fn604 ────────────────────────────────────────────────────────────────────

def _comp(df: pd.DataFrame, key: str) -> pd.DataFrame:
    return lm.fn604_completeness_by_group(df, key, ("test", key)).set_index("group")


def test_fn604_na_missing_nr_excluded():
    df = pd.DataFrame({
        "D__ProductType_ENG": ["Panel"],
        "P__A": ["12"], "P__B": ["n/a"], "P__C": ["n/r"],
    })
    row = _comp(df, "na_nr").loc["Physical"]
    assert (row["filled"], row["applicable"], row["pct"]) == (1, 2, 50.0)


def test_fn604_empty_and_dash_are_missing():
    df = pd.DataFrame({
        "D__ProductType_ENG": ["Panel", "Panel", "Panel"],
        "P__A": ["", "-", None],
    })
    row = _comp(df, "empty").loc["Physical"]
    assert (row["filled"], row["applicable"]) == (0, 3)


def test_fn604_zero_applicable_group_is_nan_and_present():
    df = pd.DataFrame({"D__ProductType_ENG": ["Panel"], "P__A": ["1"], "R__X": ["n/r"]})
    out = _comp(df, "nan_group")
    assert list(out.index) == [g for g, _ in lm.FIELD_GROUPS] + ["Overall"]
    assert out.loc["Recycled content", "applicable"] == 0
    assert math.isnan(out.loc["Recycled content", "pct"])


def test_fn604_respects_visibility(monkeypatch):
    monkeypatch.setattr(
        lm, "fn319_filter_columns_by_visibility",
        lambda cols, p, t: [c for c in cols if not (t == "Tiles" and c == "P__B")],
    )
    df = pd.DataFrame({
        "D__ProductType_ENG": ["Tiles", "Panel"],
        "P__A": ["1", "1"], "P__B": ["", ""],
    })
    row = _comp(df, "visibility").loc["Physical"]
    assert (row["filled"], row["applicable"]) == (2, 3)


def test_fn604_excluded_columns_not_counted():
    df = pd.DataFrame({
        "D__ProductType_ENG": ["Panel"], "A__Map_yn": ["Y"], "A__ProductName_Base": [""],
        "D__DataComments": [""], "S__Status": [""], "U__Img_URL": [""], "P__A_CM": [""],
    })
    out = _comp(df, "excluded")
    assert out.loc["Identity", "applicable"] == 1   # D__ProductType_ENG only
    assert out.loc["Physical", "applicable"] == 0


# ── prefix trap ──────────────────────────────────────────────────────────────

def test_vo_and_vv_land_in_different_groups():
    groups = dict(lm._group_columns(["VO__X", "VV__Y", "V__Z"]))
    assert groups["VOC emissions"] == ["VO__X"]
    assert groups["CAM and documents"] == ["VV__Y"]
    assert "V__Z" not in lm.fn608_field_group_columns(["VO__X", "VV__Y", "V__Z"])


# ── fn605 ────────────────────────────────────────────────────────────────────

def test_fn605_per_row_pct_and_bins():
    df = pd.DataFrame({
        "D__ProductType_ENG": ["T", "T", "T"],
        **{f"P__{i}": [""] * 3 for i in range(9)},
    })
    # Row 0: only the product type filled -> 1/10 = 10 %  -> first bin
    # Row 1: 2 of 10 filled -> 20 % -> second bin
    # Row 2: all 10 filled -> 100 % -> last bin
    df.loc[1, "P__0"] = "x"
    for i in range(9):
        df.loc[2, f"P__{i}"] = "x"
    out = lm.fn605_richness_per_product(df, "bins", ("test", "bins"))
    assert out["applicable_n"].tolist() == [10, 10, 10]
    assert out["pct"].tolist() == [10.0, 20.0, 100.0]
    assert out["bin_label"].tolist() == [lm.RICHNESS_BINS[0], lm.RICHNESS_BINS[1], lm.RICHNESS_BINS[-1]]


def test_fn605_zero_pct_first_bin():
    df = pd.DataFrame({"D__ProductType_ENG": [""], "P__A": [""]})
    out = lm.fn605_richness_per_product(df, "zero", ("test", "zero"))
    assert out["pct"].iloc[0] == 0.0
    assert out["bin_label"].iloc[0] == lm.RICHNESS_BINS[0]


# ── fn606 ────────────────────────────────────────────────────────────────────

def test_fn606_counts_only_http_urls():
    df = pd.DataFrame({
        "E__EPD_URL": ["https://epd.example/1", "yes", "-", None],
        "VV__CAM_Compliance": ["yes", "http://cam.example", "", "n/a"],
        "VO__VOC_URL": ["", "", "https://voc.example", ""],
    })
    out = lm.fn606_document_counts(df)
    assert out["EPD"] == 1
    assert out["CAM"] == 1
    assert out["VOC"] == 1
    assert "TDS" not in out   # missing column is skipped


# ── fn600 ────────────────────────────────────────────────────────────────────

def test_fn600_sorted_by_count_then_name_blanks_dropped():
    df = pd.DataFrame({"A__Manufacturer": ["b", "a", "C", "C", " a ", "", "-", None]})
    assert lm.fn600_manufacturer_options(df, ("test", "fn600")) == [("a", 2), ("C", 2), ("b", 1)]


# ── fn607 ────────────────────────────────────────────────────────────────────

def test_fn607_epd_and_gwp():
    df_m = pd.DataFrame({
        "E__EPD_Y/N": ["y", "", "n", "Sì"],
        "E__EPD_RegNumber": ["", "EPD-1", "", ""],
        "G__GWP_A1A3": ["1", "2,5", "x", "4"],
        "G__GWP_FU": ["m2", "m2", "", "m2"],
    })
    k = lm.fn607_kpis(df_m, df_m, "m", ("test", "fn607"))
    assert k["n"] == 4
    assert k["epd_pct"] == 75.0
    assert k["gwp_median"] == 2.5
    assert k["gwp_unit"] == "m2"
