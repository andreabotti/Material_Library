"""
libs/lib_monograph.py — Manufacturer monograph data helpers
===========================================================
fn600–fn619  Pure data helpers behind Manufacturers → Monograph (pages/15_Manufacturers.py)

  fn600  manufacturer_options        [(name, n_products)] for the picker (cached)
  fn601  resolve_profile_name        dataset name -> company-profile / Impact Framework key
  fn602  manufacturer_rows           boolean subset of one manufacturer's rows
  fn603  value_counts                treemap value counts for one manufacturer (cached)
  fn604  completeness_by_group       filled / applicable cells per field group (cached)
  fn605  richness_per_product        per-product completeness score + bin (cached)
  fn606  document_counts             products carrying each document URL
  fn607  kpis                        products, EPD share, median GWP A1–A3 (cached)
  fn608  field_group_columns         the columns FIELD_GROUPS covers (completeness + heatmap)

Value conventions match fn321/fn322 in lib_ui: NaN, "" and "-" are empty; n/a is
missing; n/r is not applicable and leaves the denominator. A column hidden for a
product type in ``aux_10__ui_config.json → tabular_column_visibility`` is not
applicable for that product type either.

Cached functions take the frame as ``_df`` (left out of the cache key on purpose)
and are keyed by the manufacturer name and app.py's ``_data_fingerprint``.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

from .lib_ui import fn319_filter_columns_by_visibility, fn322_get_value_counts_for_treemap
from .lib_ui_catalogues import JS_CATALOGUE_FIELD_MAP

_APP_ROOT = Path(__file__).resolve().parent.parent
_ALIASES_PATH = _APP_ROOT / "aux_08__manufacturer_aliases.json"

MFR_COL = "A__Manufacturer"
TYPE_COL = "D__ProductType_ENG"

FIELD_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Identity",          ("A__", "D__")),
    ("Physical",          ("P__",)),
    ("EPD and GWP",       ("E__", "G__")),
    ("Recycled content",  ("R__",)),
    ("VOC emissions",     ("VO__",)),
    ("CAM and documents", ("VV__",)),
]
EXCLUDED_COLUMNS = {
    "0__EETRA_ID", "A__Map_yn", "A__ProductName_Base", "D__DataComments",
    # Hidden app-wide (lib_data.HIDDEN_APP_COLUMNS).
    "D__Int/Ext", "D__Application",
}
# Prefixes never counted: S__ (internal status), U__ (URLs, counted under documents),
# PR__ (derived list prices). None of them is in FIELD_GROUPS, so only the explicit
# exclusions above and the *_CM provenance flags need filtering.

RICHNESS_BINS = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]

_EMPTY = {"", "-", "nan", "none", "<na>"}
_NA = {"n/a", "n\\a", "na"}
_NR = {"n/r", "n\\r", "nr"}
_EPD_YES = {"y", "yes", "si", "sì", "1", "true"}
_NOT_A_NAME = {"", "-", "nan", "none", "<na>"}


# ── fn600 ────────────────────────────────────────────────────────────────────

@st.cache_data(max_entries=4, show_spinner=False)
def fn600_manufacturer_options(_df: pd.DataFrame, data_sig) -> list[tuple[str, int]]:
    """Manufacturers that have products, by product count (desc) then name."""
    if _df is None or _df.empty or MFR_COL not in _df.columns:
        return []
    names = _df[MFR_COL].astype(str).str.strip()
    names = names[~names.str.lower().isin(_NOT_A_NAME)]
    vc = names.value_counts()
    return sorted(((str(n), int(c)) for n, c in vc.items()), key=lambda t: (-t[1], t[0].lower()))


# ── fn601 ────────────────────────────────────────────────────────────────────

_ALIAS_MEMO: dict = {"key": None, "aliases": {}}


def _load_aliases(path: Path | None = None) -> dict[str, str]:
    path = Path(path or _ALIASES_PATH)
    try:
        st_ = os.stat(path)
        key = (str(path), st_.st_mtime_ns, st_.st_size)
    except OSError:
        return {}
    if _ALIAS_MEMO["key"] != key:
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f).get("aliases") or {}
            aliases = {str(k): str(v) for k, v in raw.items()}
        except (OSError, ValueError, AttributeError):
            aliases = {}
        _ALIAS_MEMO.update(key=key, aliases=aliases)
    return _ALIAS_MEMO["aliases"]


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().casefold()


def fn601_resolve_profile_name(name: str, known_names: frozenset[str],
                               aliases_path: Path | None = None) -> str | None:
    """Profile key for a dataset manufacturer: alias, then exact, then normalised match.

    ``known_names`` is the union of the credentials, company-profile and Impact
    Framework manufacturer keys. Returns None when nothing matches.
    """
    if not name:
        return None
    name = str(name).strip()
    target = _load_aliases(aliases_path).get(name)
    if target and target in known_names:
        return target
    if name in known_names:
        return name
    key = _norm_name(name)
    for k in sorted(known_names):
        if _norm_name(k) == key:
            return k
    return None


# ── fn602 / fn603 ────────────────────────────────────────────────────────────

def fn602_manufacturer_rows(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Rows of one manufacturer (boolean subset; the caller must not mutate it)."""
    if df is None or df.empty or MFR_COL not in df.columns:
        return df.iloc[0:0] if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return df[df[MFR_COL].astype(str).str.strip() == name]


@st.cache_data(max_entries=128, show_spinner=False)
def fn603_value_counts(_df_m: pd.DataFrame, column: str, manufacturer: str, data_sig) -> pd.DataFrame:
    """Treemap counts for one column of one manufacturer; "(empty)" reads "Not specified"."""
    vc = fn322_get_value_counts_for_treemap(
        _df_m, column, top_n=12, include_empty=True,
        include_na=False, include_nr=False, include_symbols=False,
    )
    if not vc.empty:
        vc = vc.copy()
        vc["value"] = vc["value"].replace({"(empty)": "Not specified"})
    return vc


# ── Completeness (fn604 / fn605) ─────────────────────────────────────────────

def _group_columns(columns) -> list[tuple[str, list[str]]]:
    """FIELD_GROUPS resolved against the frame's columns, in group order."""
    out = []
    for label, prefixes in FIELD_GROUPS:
        cols = [
            c for c in columns
            if isinstance(c, str) and c.startswith(prefixes)
            and c not in EXCLUDED_COLUMNS and not c.endswith("_CM")
        ]
        out.append((label, cols))
    return out


def fn608_field_group_columns(columns) -> list[str]:
    """Every column the completeness measures cover, in FIELD_GROUPS order."""
    return [c for _, cols in _group_columns(columns) for c in cols]


def _cell_masks(df: pd.DataFrame) -> list[tuple[str, dict[str, tuple[pd.Series, pd.Series]]]]:
    """``[(group, {col: (filled, applicable)})]`` — the one place cells are classified.

    applicable = visible for the row's product type and not n/r;
    filled     = applicable and not empty / "-" / n/a.
    """
    if TYPE_COL in df.columns:
        ptype = df[TYPE_COL].astype(str).str.strip()
    else:
        ptype = pd.Series("", index=df.index)
    types = [t for t in ptype.unique().tolist()]
    hidden_cache: dict[tuple[str, str], set[str]] = {}

    def _hidden(product_type: str, prefix: str, cols: list[str]) -> set[str]:
        key = (product_type, prefix)
        if key not in hidden_cache:
            try:
                kept = set(fn319_filter_columns_by_visibility(list(cols), prefix, product_type))
            except Exception:
                kept = set(cols)
            hidden_cache[key] = set(cols) - kept
        return hidden_cache[key]

    out = []
    for label, cols in _group_columns(df.columns):
        by_prefix: dict[str, list[str]] = {}
        for c in cols:
            by_prefix.setdefault(c.split("__", 1)[0], []).append(c)
        masks: dict[str, tuple[pd.Series, pd.Series]] = {}
        for prefix, pcols in by_prefix.items():
            hidden_types = {c: [t for t in types if c in _hidden(t, prefix, pcols)] for c in pcols}
            for c in pcols:
                s = df[c]
                low = s.astype(str).str.strip().str.lower()
                nr = low.isin(_NR)
                missing = s.isna() | low.isin(_EMPTY) | low.isin(_NA)
                visible = ~ptype.isin(hidden_types[c]) if hidden_types[c] else pd.Series(True, index=df.index)
                applicable = visible & ~nr
                masks[c] = (applicable & ~missing, applicable)
        out.append((label, masks))
    return out


def _completeness_by_group(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    tot_f = tot_a = 0
    for label, masks in _cell_masks(df):
        filled = int(sum(int(f.sum()) for f, _ in masks.values()))
        applicable = int(sum(int(a.sum()) for _, a in masks.values()))
        tot_f += filled
        tot_a += applicable
        rows.append((label, filled, applicable))
    rows.append(("Overall", tot_f, tot_a))
    out = pd.DataFrame(rows, columns=["group", "filled", "applicable"])
    out["pct"] = (100.0 * out["filled"] / out["applicable"].where(out["applicable"] > 0)).astype(float)
    return out


@st.cache_data(max_entries=128, show_spinner=False)
def fn604_completeness_by_group(_df: pd.DataFrame, scope_key: str, data_sig) -> pd.DataFrame:
    """``group, filled, applicable, pct`` per FIELD_GROUPS entry plus a final "Overall" row.

    ``scope_key`` is the manufacturer name, or ``"__library__"`` for the whole dataset.
    """
    return _completeness_by_group(_df)


def _richness_per_product(df: pd.DataFrame) -> pd.DataFrame:
    filled_n = pd.Series(0, index=df.index, dtype="int64")
    applicable_n = pd.Series(0, index=df.index, dtype="int64")
    for _, masks in _cell_masks(df):
        for f, a in masks.values():
            filled_n += f.astype("int64")
            applicable_n += a.astype("int64")
    out = pd.DataFrame({"filled_n": filled_n, "applicable_n": applicable_n})
    out["pct"] = (100.0 * out["filled_n"] / out["applicable_n"].where(out["applicable_n"] > 0)).astype(float)
    out["bin_label"] = pd.cut(
        out["pct"], bins=[0, 20, 40, 60, 80, 100.0001], labels=RICHNESS_BINS, right=False,
    ).astype(object)
    return out


@st.cache_data(max_entries=64, show_spinner=False)
def fn605_richness_per_product(_df: pd.DataFrame, scope_key: str, data_sig) -> pd.DataFrame:
    """Per product: ``filled_n, applicable_n, pct, bin_label`` (bins in RICHNESS_BINS)."""
    return _richness_per_product(_df)


# ── fn606 ────────────────────────────────────────────────────────────────────

def _src_cols(*targets: str) -> list[str]:
    return [src for src, tgt in JS_CATALOGUE_FIELD_MAP.items() if tgt in targets]


DOCUMENT_COLUMNS: list[tuple[str, list[str]]] = [
    ("EPD", _src_cols("epdUrl")),
    ("TDS", _src_cols("techDetailsUrl")),
    ("VOC", _src_cols("vocUrlPrimary", "vocUrlAlt")),
    ("DoP", _src_cols("dopUrl")),
    ("SDS", _src_cols("msdsUrl")),
    ("CAM", ["VV__CAM_Compliance"]),
    ("RC", _src_cols("recyclingUrl")),
]


def fn606_document_counts(df: pd.DataFrame) -> dict[str, int]:
    """Products with an ``http…`` URL per document type (columns as in the catalogue cards)."""
    out: dict[str, int] = {}
    if df is None:
        return out
    for label, cols in DOCUMENT_COLUMNS:
        present = [c for c in cols if c in df.columns]
        if not present:
            continue
        has = pd.Series(False, index=df.index)
        for c in present:
            has |= df[c].astype(str).str.strip().str.lower().str.startswith("http")
        out[label] = int(has.sum())
    return out


# ── fn607 ────────────────────────────────────────────────────────────────────

def _has_value(s: pd.Series) -> pd.Series:
    low = s.astype(str).str.strip().str.lower()
    return ~(s.isna() | low.isin(_EMPTY) | low.isin(_NA) | low.isin(_NR))


def _epd_mask(df: pd.DataFrame) -> pd.Series:
    m = pd.Series(False, index=df.index)
    if "E__EPD_Y/N" in df.columns:
        m |= df["E__EPD_Y/N"].astype(str).str.strip().str.lower().isin(_EPD_YES)
    for c in ("E__EPD_RegNumber", "E__EPD_URL"):
        if c in df.columns:
            m |= _has_value(df[c])
    return m


def _kpis(df_m: pd.DataFrame, df_all: pd.DataFrame) -> dict:
    n = int(len(df_m))
    epd_pct = float(100.0 * _epd_mask(df_m).mean()) if n else float("nan")
    epd_pct_lib = float(100.0 * _epd_mask(df_all).mean()) if len(df_all) else float("nan")
    gwp_median, gwp_unit = None, None
    if "G__GWP_A1A3" in df_m.columns and n:
        gwp = pd.to_numeric(df_m["G__GWP_A1A3"].astype(str).str.strip().str.replace(",", ".", regex=False),
                            errors="coerce")
        if gwp.notna().any():
            gwp_median = float(gwp.median())
            if "G__GWP_FU" in df_m.columns:
                fu = df_m.loc[gwp.notna(), "G__GWP_FU"].astype(str).str.strip()
                fu = fu[~fu.str.lower().isin(_EMPTY | _NA | _NR)]
                if not fu.empty:
                    top = fu.value_counts()
                    gwp_unit = str(top.index[0]) if top.iloc[0] / len(fu) >= 0.8 else "mixed units"
    return {"n": n, "epd_pct": epd_pct, "epd_pct_lib": epd_pct_lib,
            "gwp_median": gwp_median, "gwp_unit": gwp_unit}


@st.cache_data(max_entries=64, show_spinner=False)
def fn607_kpis(_df_m: pd.DataFrame, _df_all: pd.DataFrame, manufacturer: str, data_sig) -> dict:
    """``{n, epd_pct, epd_pct_lib, gwp_median, gwp_unit}`` for the monograph KPI tiles.

    ``gwp_unit`` is the dominant declared unit (≥80 % of rows with a GWP),
    "mixed units" otherwise, or None when no unit is recorded.
    """
    return _kpis(_df_m, _df_all)
