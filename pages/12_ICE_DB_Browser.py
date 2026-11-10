"""
pages/12_ICE_DB_Browser.py — ICE DB Material Browser
──────────────────────────────────────────────────────
Charts overview + client-side JS browser for ICE DB V4.1 embodied carbon data.
All filtering is client-side inside html/ice_db_component.html.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from libs.lib_header import fn003a_page_header
from libs.lib_ui import fn356_empty_state, fn358_debug_caption, fn359_iframe_height

# ── Paths ─────────────────────────────────────────────────────────────────────
_APP_ROOT = Path(__file__).resolve().parents[1]
_ICE_JSON  = _APP_ROOT / "01_data" / "ice_db.json"
_HTML_TPL  = _APP_ROOT / "02_html" / "ice_db_component.html"

# ── Page ──────────────────────────────────────────────────────────────────────
fn003a_page_header(
    "ICE DB Browser",
    "Inventory of Carbon & Energy V4.1 (Oct 2025), Circular Ecology — filtered client-side.",
    icon="♻️",
)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_ice_db(mtime: int) -> dict:
    with open(_ICE_JSON, encoding="utf-8") as f:
        return json.load(f)

if not _ICE_JSON.exists():
    fn356_empty_state(
        "ICE DB data file not found.",
        kind="error",
        hint="Run `04_tools/06_parse_ice_db.py` to generate `01_data/ice_db.json`.",
    )
    st.stop()

_t0 = time.perf_counter()
_ph = st.empty()
_ph.progress(0, text="Loading ICE DB…")

_db = load_ice_db(int(_ICE_JSON.stat().st_mtime_ns))
_materials: list[dict] = _db.get("materials", [])

_ph.progress(100, text="")
_ph.empty()

_elapsed = time.perf_counter() - _t0
if _elapsed > 0.5:
    fn358_debug_caption(
        f"⏱ Loaded in {_elapsed:.2f} s" + (" (cache miss)" if _elapsed > 2.0 else "")
    )

if not _materials:
    fn356_empty_state("No materials found in `ice_db.json`.", kind="empty")
    st.stop()

# ── Build DataFrame for charts ────────────────────────────────────────────────
_df = pd.DataFrame(_materials)

st.caption(
    f"**{len(_materials):,}** materials · "
    f"**{_df['ec_kgco2e_per_kg'].notna().sum():,}** with EC/kg · "
    f"**{(_df['is_legacy']).sum():,}** legacy entries"
)

# ── Sub-tabs ──────────────────────────────────────────────────────────────────
_tab_charts, _tab_browser = st.tabs(["Charts", "Browser"])

# ─────────────────────────────────────────────────────────────────────────────
with _tab_charts:
    _c1, _c2 = st.columns(2)

    # Category distribution
    with _c1:
        _cat_counts = (
            _df.groupby("category")
            .size()
            .reset_index(name="count")
            .sort_values("count")
        )
        _fig_cat = px.bar(
            _cat_counts, x="count", y="category", orientation="h",
            title=f"Materials by category — {len(_materials):,} total",
            height=max(320, min(55 * len(_cat_counts) + 80, 720)),
            color="count", color_continuous_scale="Greens",
        )
        _fig_cat.update_layout(
            margin=dict(l=10, r=10, t=40, b=10),
            coloraxis_showscale=False,
            yaxis_title="", xaxis_title="Count",
        )
        st.plotly_chart(_fig_cat, width="stretch")

    # Declared unit distribution
    with _c2:
        _unit_counts = (
            _df.groupby("declared_unit")
            .size()
            .reset_index(name="count")
            .sort_values("count")
        )
        _unit_counts["label"] = _unit_counts["declared_unit"].map({
            "kg": "kg  (per mass)",
            "m2": "m²  (per area)",
            "m3": "m³  (per volume)",
            "tonne": "tonne  (per mass)",
            "each": "each / unit",
            "unit": "unit",
            "m": "m  (per length)",
        }).fillna(_unit_counts["declared_unit"])
        _fig_unit = px.bar(
            _unit_counts, x="count", y="label", orientation="h",
            title="Materials by declared unit",
            height=max(260, min(60 * len(_unit_counts) + 80, 480)),
            color="count", color_continuous_scale="Blues",
        )
        _fig_unit.update_layout(
            margin=dict(l=10, r=10, t=40, b=10),
            coloraxis_showscale=False,
            yaxis_title="", xaxis_title="Count",
        )
        st.plotly_chart(_fig_unit, width="stretch")

    # EC value range chart (per-kg entries only)
    _df_kg = _df[_df["ec_kgco2e_per_kg"].notna() & ~_df["is_legacy"]].copy()
    if not _df_kg.empty:
        _df_kg_agg = (
            _df_kg.groupby("category")["ec_kgco2e_per_kg"]
            .agg(["min", "max", "median", "count"])
            .reset_index()
            .sort_values("median")
        )
        _fig_ec = px.scatter(
            _df_kg, x="ec_kgco2e_per_kg", y="category",
            title=f"EC range (kg CO₂e/kg) — {len(_df_kg):,} V4.1 per-kg entries",
            color="category",
            hover_data=["name", "subcategory", "ec_kgco2e_per_kg", "dqi_score"],
            height=max(360, min(55 * _df_kg["category"].nunique() + 80, 720)),
            opacity=0.65,
        )
        _fig_ec.update_layout(
            showlegend=False,
            margin=dict(l=10, r=10, t=40, b=10),
            yaxis_title="", xaxis_title="kg CO₂e / kg",
        )
        st.plotly_chart(_fig_ec, width="stretch", key="fig_ec_range")

    # Top 20 highest EC per kg
    if not _df_kg.empty:
        _top20 = (
            _df_kg.nlargest(20, "ec_kgco2e_per_kg")
            [["name", "category", "ec_kgco2e_per_kg", "dqi_score"]]
            .rename(columns={
                "name": "Material",
                "category": "Category",
                "ec_kgco2e_per_kg": "EC kg CO₂e/kg",
                "dqi_score": "DQI",
            })
        )
        with st.expander("Top 20 highest EC/kg (V4.1, per-mass entries)", expanded=False, type="compact"):
            st.dataframe(_top20.set_index("Material"), width='stretch')

    st.caption(
        "**DQI** = Data Quality Indicator, taken directly from the *DQI Score* column of the "
        "ICE Summary sheet (Circular Ecology). Each datapoint is rated 1–5 on method "
        "compatibility, assurance/review, temporal correlation, geographical compatibility and "
        "transparency, plus category-level population & analytical checks, then normalised to "
        "0–1 (higher = better). Methodology: *Data Quality Matrix* sheet of the ICE workbook. "
        "Legacy (pre-V3.0) entries were never scored, so their DQI is blank."
    )

# ─────────────────────────────────────────────────────────────────────────────
_BROWSER_HEIGHT = fn359_iframe_height("ice_db")

with _tab_browser:
    if not _HTML_TPL.exists():
        fn356_empty_state(f"Browser template not found: `{_HTML_TPL.name}`", kind="error")
        st.stop()

    # Inject data into the HTML template
    _tpl = _HTML_TPL.read_text(encoding="utf-8")

    _inject = (
        f"window.__ICE_DATA__ = {json.dumps(_materials, ensure_ascii=False)};\n"
        f"window.__ICE_IFRAME_H__ = {_BROWSER_HEIGHT};\n"
    )
    _html = _tpl.replace("/* INJECT_ICE_DATA_HERE */", _inject, 1)

    st.iframe(_html, height=_BROWSER_HEIGHT)

    st.caption(
        "Source: [ICE DB Advanced V4.1 – Oct 2025](https://circularecology.com/embodied-energy-and-carbon-footprint-database.html) "
        "· Circular Ecology · Cradle-to-gate (A1–A3)"
    )
