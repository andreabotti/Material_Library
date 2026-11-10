"""
libs/lib_charts.py — EETRA MatLib charts module
=================================================
fn201–fn299  Plotly charts, GWP bands, cement markers, bar/box charts

  fn201  plot_box_chart               horizontal box/candle chart
  fn202  create_logo_image            load logo → base64 data URI for Plotly
  fn203  parse_cement_type            EN 197-1 cement type parser (simplified)
  fn204  get_cement_marker_styles     per-row marker dict for cement products
  fn205  get_gwp_class_bands          UNI/PdR 176:2025 GWP class definitions
  fn206  add_gwp_bands_to_chart       coloured bands on Plotly figure
  fn207  add_gwp_lines_to_chart       threshold vertical lines on Plotly figure
  fn208  is_concrete_material         heuristic: is this a concrete chart?
  fn209  is_in_situ_selected          True when In situ filter is active
  fn210  display_gwp_class_legend     expandable GWP legend widget
  fn211  clean_dataframe_for_streamlit  fix PyArrow-incompatible column types
  fn212  create_bar_chart             full horizontal bar chart with GWP overlay
  fn213  normalize_en206_class        EN 206 resistance class normaliser
  fn214  plot_horizontal_bar_custom   legacy horizontal bar chart (Plotly Express)
  fn215  add_watermark                overlay watermark image on Plotly figure
  fn221  load_ice_db                  cached ICE DB JSON loader
  fn222  resolve_ice_categories       map material/product types → ICE categories
  fn223  is_gwp_metric                heuristic: True when column is a GWP metric
  fn223a ice_benchmark_fu             kg/m2/m3 when value col matches ICE A1–A3 FU
  fn224  get_ice_benchmarks           ICE EC lines: per material (kg) / category median (m²/m³)
  fn225  add_ice_benchmarks_to_chart  labeled dashed vertical lines from ICE data
  fn226  add_ice_hlines_to_chart      horizontal variant for correlation Y-axis
  fn227  plot_strip_chart             jittered dot-plot — X=groups, Y=value (PDF style)
  fn228  epd_programme_mini_bar       compact treemap: EPD programme distribution
  fn229  plot_box_chart_altair        Altair horizontal box (+ ICE vlines)
  fn230  build_echarts_box_html       ECharts JS horizontal box (+ ICE markLines)
  fn231  insulation_material_color_map  pale yellow/gray palette for Insulation × Material Type
  fn232  ice_line_color               ICE line colour matched to insulation materials
  fn233  chart_typo_from_dims         shared Plotly/Altair/ECharts typography from theme
  fn234  wrap_tick_label              word-wrap categorical axis labels (horizontal ticks)

Chart-geometry constants (from shared.py):
  BOX_CHART_MARGINS, BAR_CHART_MARGINS, BAR_CHART_HEIGHT_*
"""

import json as _json
import streamlit as st
import pandas as pd
import re
import textwrap
import colorsys
import base64
from io import BytesIO
from pathlib import Path

import plotly.graph_objects as go
import plotly.express as px
import plotly.colors as pc
from PIL import Image
import requests

_CAM_2025_RECYCLED_TARGETS = {
    # 2.4.7 Isolanti
    "cellulosa": 80.0,
    "lana di vetro": 60.0,
    "vetro cellulare": 50.0,
    "fibre in poliestere": 40.0,
    "lana di roccia": 15.0,
    "polistirene espanso sinterizzato": 15.0,
    "polistirene espanso estruso": 10.0,
    "agglomerato di poliuretano": 70.0,
    "agglomerato di gomma": 60.0,
    "poliuretano espanso flessibile": 20.0,
    "poliuretano espanso rigido": 3.0,
    # 2.4.8 Tramezzature / controsoffitti
    "lastre e pannelli in generale": 10.0,
    "lastre in cartongesso": 5.0,
    "pannelli in gesso": 5.0,
    # 2.4.10 Pavimenti resilienti
    "pavimentazioni in materie plastiche": 20.0,
    "pavimentazioni in gomma": 10.0,
    # 2.4.12 Serramenti
    "profili in pvc": 20.0,
    "profili in alluminio": 40.0,
    # 2.4.6 Legno
    "pannelli a base legnosa": 70.0,
    # Assunzione operativa MatLib per ceramici (tiles)
    "piastrelle ceramiche": 15.0,
    "gres porcellanato": 15.0,
    "ceramica": 15.0,
}

# ── Chart geometry constants ────────────────────────────────────────────────
BOX_CHART_MARGINS = dict(l=20, r=20, t=10, b=10)
BAR_CHART_MARGINS = dict(l=20, r=20, t=10, b=10)

BAR_CHART_HEIGHT_ITEM_THRESHOLD = 30
# Defaults; ``pages/3_Charts.py`` uses ``aux_01__catalogue_layout.json`` → ``charts`` for tunable caps.
BAR_CHART_LINE_HEIGHT_PX  = 18
BAR_CHART_HEIGHT_PADDING_PX = 0
BAR_CHART_MAX_ROWS        = 120
BAR_CHART_HEIGHT_MAX_PX   = BAR_CHART_MAX_ROWS * BAR_CHART_LINE_HEIGHT_PX
BAR_CHART_HEIGHT_MIN_PX   = 300


# ── Lazy imports (avoid circular deps with lib_ui) ───────────────────────────
def _get_manufacturer_logo_mapping():
    from .lib_ui import fn312_get_manufacturer_logo_mapping
    return fn312_get_manufacturer_logo_mapping()


def _get_manufacturer_color_mapping():
    from .lib_ui import fn313_get_manufacturer_color_mapping
    return fn313_get_manufacturer_color_mapping()


def _sorted_unique_categories(values, *, reverse=False):
    """Sort unique grouping/color keys without comparing incompatible types (e.g. int vs str)."""

    def _key(v):
        try:
            if pd.isna(v):
                return ("\uffff", "")
        except (ValueError, TypeError):
            pass
        return (str(v).lower(), type(v).__name__)

    return sorted(values, key=_key, reverse=reverse)


def fn216_is_recycled_content_metric(value_col: str) -> bool:
    """Heuristic: True when value column is recycled/recovered content percentage."""
    s = str(value_col or "").lower()
    return ("rec" in s or "ricicl" in s) and ("%" in s or "pct" in s or "perc" in s)


def fn217_match_cam_target(material_label: str) -> float | None:
    """Return CAM 2025 recycled-content target (%) for a material label, if matched."""
    label = str(material_label or "").strip().lower()
    if not label:
        return None

    # Direct contains match against known labels.
    for k, v in _CAM_2025_RECYCLED_TARGETS.items():
        if k in label:
            return v

    # Lightweight aliases for common ENG labels.
    aliases = {
        "glass wool": "lana di vetro",
        "rock wool": "lana di roccia",
        "cellulose": "cellulosa",
        "cellular glass": "vetro cellulare",
        "polyester": "fibre in poliestere",
        "eps": "polistirene espanso sinterizzato",
        "xps": "polistirene espanso estruso",
        "pvc": "profili in pvc",
        "aluminium": "profili in alluminio",
        "aluminum": "profili in alluminio",
        "wood panel": "pannelli a base legnosa",
        "gypsum": "pannelli in gesso",
        "plasterboard": "lastre in cartongesso",
        "rubber flooring": "pavimentazioni in gomma",
        "plastic flooring": "pavimentazioni in materie plastiche",
        "tile": "piastrelle ceramiche",
        "tiles": "piastrelle ceramiche",
        "ceramic tile": "piastrelle ceramiche",
        "ceramic tiles": "piastrelle ceramiche",
        "porcelain stoneware": "gres porcellanato",
        "porcelain": "gres porcellanato",
        "ceramic": "ceramica",
    }
    for ak, canon in aliases.items():
        if ak in label:
            return _CAM_2025_RECYCLED_TARGETS.get(canon)
    return None


def fn218_add_cam_targets_to_box_chart(fig, groups, value_col: str):
    """
    Add CAM 2025 dotted vertical target ticks per material group on horizontal box chart.
    """
    if not fn216_is_recycled_content_metric(value_col):
        return fig
    # Auto-scale target for % metrics stored as 0-1 fractions.
    x_vals = []
    try:
        for tr in fig.data:
            _x = getattr(tr, "x", None)
            if _x is None:
                continue
            for v in _x:
                try:
                    if v is not None and not pd.isna(v):
                        x_vals.append(float(v))
                except Exception:
                    continue
    except Exception:
        pass
    _use_fraction_scale = bool(x_vals) and max(x_vals) <= 1.5

    for i, grp in enumerate(groups):
        target = fn217_match_cam_target(str(grp))
        if target is None:
            continue
        x_target = (target / 100.0) if _use_fraction_scale else target
        fig.add_shape(
            type="line",
            x0=x_target,
            x1=x_target,
            y0=i - 0.34,
            y1=i + 0.34,
            line=dict(color="rgba(50,50,50,0.9)", width=2, dash="dot"),
            layer="above",
        )
    return fig


def fn219_add_cam_target_to_bar_chart(fig, df, value_col: str, color_col: str):
    """
    Add CAM 2025 dotted vertical line on bar chart when the current view maps to one CAM target.
    """
    if not fn216_is_recycled_content_metric(value_col):
        return fig
    target = fn220_resolve_cam_target_from_df(df, color_col=color_col)
    if target is None:
        return fig
    # Auto-scale target for % metrics stored as 0-1 fractions.
    vals = pd.to_numeric(df.get(value_col, pd.Series(dtype=float)), errors="coerce").dropna()
    use_fraction_scale = (len(vals) > 0) and (float(vals.max()) <= 1.5)
    x_target = (target / 100.0) if use_fraction_scale else target
    fig.add_vline(
        x=x_target,
        line_width=2,
        line_dash="dot",
        line_color="rgba(50,50,50,0.9)",
    )
    fig.add_annotation(
        x=x_target,
        y=1.0,
        xref="x",
        yref="paper",
        text=f"CAM limit = {target:.0f}%",
        showarrow=False,
        textangle=-90,
        yanchor="bottom",
        xanchor="left",
        font=dict(size=10, color="rgba(50,50,50,0.95)"),
        bgcolor="rgba(255,255,255,0.65)",
    )
    return fig


def fn220_resolve_cam_target_from_df(df: pd.DataFrame, color_col: str | None = None) -> float | None:
    """Resolve a single CAM target from visible dataframe context (material/product type/color)."""
    candidates: list[float] = []

    def _collect_from_col(col: str):
        if col not in df.columns:
            return
        for v in df[col].dropna().unique():
            t = fn217_match_cam_target(v)
            if t is not None:
                candidates.append(float(t))

    # Priority 1: explicit material labels
    _collect_from_col("D__MaterialType_ENG")

    # Priority 2: current color grouping, when available
    if color_col:
        _collect_from_col(color_col)

    # Priority 3: product type heuristics for categories without explicit material
    if "D__ProductType_ENG" in df.columns:
        ptypes = {
            str(v).strip().lower()
            for v in df["D__ProductType_ENG"].dropna().unique()
            if str(v).strip()
        }
        for pt in ptypes:
            if "building board" in pt or "board" in pt:
                # CAM 2.4.8: default for boards/partitions
                candidates.append(10.0)
            if "gypsum" in pt or "plasterboard" in pt or "cartongesso" in pt:
                # Specific lower threshold for gypsum boards
                candidates.append(5.0)
            if "insulation" in pt:
                # Insulation is heterogeneous -> rely on material label only
                continue
            if "tile" in pt or "tiles" in pt or "ceramic" in pt or "porcelain" in pt:
                candidates.append(15.0)
    # Priority 4: product-name heuristics (fallback)
    if "A__ProductName" in df.columns:
        names = " ".join(
            str(v).lower() for v in df["A__ProductName"].dropna().astype(str).head(200)
        )
        if any(k in names for k in ("tile", "tiles", "ceramic", "porcelain", "gres")):
            candidates.append(15.0)

    if not candidates:
        return None
    uniq = sorted(set(candidates))
    if len(uniq) == 1:
        return uniq[0]
    return None


# ════════════════════════════════════════════════════════════════════════════
# fn221–fn226 — ICE DB benchmark lines
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def fn221_load_ice_db() -> list[dict]:
    """Load and cache ICE DB materials from 01_data/ice_db.json."""
    p = Path("01_data/ice_db.json")
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return _json.load(f).get("materials", [])
    except Exception:
        return []


# D__MaterialType_ENG label fragments → ICE DB category names
_MATERIAL_TO_ICE_CATS: dict[str, list[str]] = {
    "cement":               ["Cement and Mortar"],
    "mortar":               ["Cement and Mortar"],
    "concrete":             ["Concrete"],
    "gypsum":               ["Plaster"],
    "glass wool":           ["Insulation"],
    "mineral wool":         ["Insulation"],
    "stone wool":           ["Insulation"],
    "rock wool":            ["Insulation"],
    "fibreglass":           ["Insulation"],
    "glass fibre":          ["Insulation"],
    "xps":                  ["Plastics"],
    "extruded polystyren":  ["Plastics"],
    "eps":                  ["Plastics"],
    "expanded polystyren":  ["Plastics"],
    "pir":                  ["Insulation"],
    "polyisocyanurate":     ["Insulation"],
    "polyurethane":         ["Insulation"],
    "phenolic":             ["Insulation"],
    "wood wool":            ["Insulation"],
    "aluminium":            ["Aluminium"],
    "aluminum":             ["Aluminium"],
    "steel":                ["Steel"],
    "porcelain":            ["Ceramics"],
    "ceramic":              ["Ceramics"],
    "clay":                 ["Clay", "Bricks"],
    "timber":               ["Timber"],
    "wood":                 ["Timber"],
    "glass":                ["Glass"],
    "rubber":               ["Rubber"],
    "vinyl":                ["Vinyl"],
    "aggregates":           ["Aggregates and Sand"],
    "copper":               ["Copper"],
    "zinc":                 ["Zinc"],
    "lead":                 ["Lead"],
    "paint":                ["Paint"],
    "paper":                ["Paper"],
    "plastics":             ["Plastics"],
    "polymer":              ["Plastics"],
    "synthetic resin":      ["Plastics"],
    "composite":            ["Miscellaneous"],
    "mineral boards":       ["Miscellaneous"],
    "fibre cement":         ["Cement and Mortar"],
}

# D__ProductType_ENG label fragments → ICE DB category names (secondary fallback)
_PRODUCT_TYPE_TO_ICE_CATS: dict[str, list[str]] = {
    "binder":               ["Cement and Mortar"],
    "in situ concrete":     ["Concrete"],
    "masonry":              ["Concrete", "Bricks"],
    "insulation":           ["Insulation"],
    "tile":                 ["Ceramics"],
    "ceramic":              ["Ceramics"],
    "rebar":                ["Steel"],
    "coil":                 ["Steel"],
    "building board":       ["Plaster"],
    "screed":               ["Concrete"],
    "paving":               ["Stone", "Concrete"],
    "windows":              ["Aluminium", "Plastics"],
    "cladding":             ["Aluminium", "Steel"],
    "grouting":             ["Cement and Mortar"],
    "mortar":               ["Cement and Mortar"],
    "plaster":              ["Plaster"],
    "floor (resin)":        ["Plastics"],
}


def fn222_resolve_ice_categories(df: pd.DataFrame) -> list[str]:
    """Return de-duped ICE DB category names that match the material/product types in df."""
    if "D__ProductType_ENG" in df.columns:
        pt_vals = [
            str(v).strip().lower()
            for v in df["D__ProductType_ENG"].dropna().unique()
            if str(v).strip() and str(v).strip().lower() not in ("nan", "-", "")
        ]
        # Insulation products: material labels like "glass wool" or "wood wool" must
        # not pull in ICE Glass / ICE Timber via substring matches on "glass"/"wood".
        if pt_vals and all("insulation" in v for v in pt_vals):
            return ["Insulation"]

    cats: set[str] = set()

    def _scan(col: str, table: dict[str, list[str]]) -> None:
        if col not in df.columns:
            return
        for val in df[col].dropna().unique():
            label = str(val).strip().lower()
            for key, ice_cats in table.items():
                if key in label:
                    cats.update(ice_cats)

    _scan("D__MaterialType_ENG", _MATERIAL_TO_ICE_CATS)
    _scan("D__ProductType_ENG",  _PRODUCT_TYPE_TO_ICE_CATS)
    return sorted(cats)


def fn223_is_gwp_metric(value_col: str) -> bool:
    """True when value column is a GWP / embodied-carbon metric."""
    s = str(value_col or "").lower()
    return "gwp" in s or "co2" in s or "carbon" in s


# Chart value columns whose unit matches an ICE DB declared-unit / EC basis.
# ICE lines are only meaningful on these A1–A3 bases (not mixed FU/DU or R=1).
_ICE_BENCHMARK_FU_BY_COL: dict[str, str] = {
    "G__GWP_A1A3_kg": "kg",
    "G__GWP_A1A3_m2": "m2",
    "G__GWP_A1A3_m3": "m3",
}

_ICE_FU_UNIT_LABEL: dict[str, str] = {
    "kg": "kg CO₂e/kg",
    "m2": "kg CO₂e/m²",
    "m3": "kg CO₂e/m³",
}


def fn223a_ice_benchmark_fu(value_col: str) -> str | None:
    """Return ``kg`` / ``m2`` / ``m3`` when *value_col* is GWP A1–A3 on that ICE FU.

    ICE DB medians are stored per declared unit (mostly kg; also m² / m³).
    Showing those lines against a mismatched axis (mixed FU/DU, R=1, A1 alone, …)
    is misleading — return ``None`` so the Benchmark checkbox stays hidden.
    """
    raw = str(value_col or "").strip()
    if not raw:
        return None
    if raw in _ICE_BENCHMARK_FU_BY_COL:
        return _ICE_BENCHMARK_FU_BY_COL[raw]
    # Exact stem match only (avoid G__GWP_A1A3_m2 matching inside …_m2R1).
    up = raw.upper().replace(" ", "").replace("–", "-").replace("—", "-")
    for col, fu in _ICE_BENCHMARK_FU_BY_COL.items():
        if up == col.upper().replace(" ", ""):
            return fu
        # Cleaned labels occasionally drop the G__ prefix.
        if up == col.split("__", 1)[-1].upper().replace(" ", ""):
            return fu
    return None


# When FU is kg, emit one line per ICE material unless the category is huge
# (e.g. Concrete ≈ 200 mixes) — then fall back to category / sub-group medians.
_ICE_KG_PER_MATERIAL_MAX = 30

# ICE material name fragments never drawn as benchmark lines (user exclusion).
_ICE_EXCLUDED_NAME_FRAGMENTS = (
    "sanitary",
)


def _ice_material_label(name: str, cat: str) -> str:
    """Full hover label: 'Insulation, Glass Wool' → 'ICE Glass Wool'."""
    n = str(name or "").strip()
    c = str(cat or "").strip()
    if n and c:
        for sep in (", ", " - ", " — ", " – ", " "):
            prefix = f"{c}{sep}"
            if n.lower().startswith(prefix.lower()):
                n = n[len(prefix):].strip()
                break
    # Drop redundant carbon-storage suffix on timber names (subcategory already filters).
    for suffix in (
        " - No Carbon Storage",
        " – No Carbon Storage",
        " — No Carbon Storage",
        " (No Carbon Storage)",
    ):
        if n.lower().endswith(suffix.lower()):
            n = n[: -len(suffix)].strip()
            break
    return f"ICE {n}" if n else f"ICE {c or 'material'}"


# Visible chart text only (hover keeps the full ``label`` from fn224).
_ICE_CHART_SHORT_LABELS: dict[str, str] = {
    "glass wool": "Glass Wool",
    "mineral wool": "Min. Wool",
    "polyisocyanurate (pir)": "PIR",
    "polyisocyanurate": "PIR",
    "polystyrene": "EPS/XPS",
    "polyurethane board": "PUR",
    "polyurethane": "PUR",
}


def _ice_chart_short_label(full_label: str) -> str:
    """Compact on-chart ICE name; hover continues to use the full label."""
    raw = str(full_label or "").strip()
    stem = raw[4:].strip() if raw.upper().startswith("ICE ") else raw
    key = stem.lower()
    if key in _ICE_CHART_SHORT_LABELS:
        return _ICE_CHART_SHORT_LABELS[key]
    # Prefer longer key matches first (e.g. polyisocyanurate (pir) before polyisocyanurate).
    for src, short in sorted(_ICE_CHART_SHORT_LABELS.items(), key=lambda kv: -len(kv[0])):
        if src in key:
            return short
    return stem or raw


def fn224_get_ice_benchmarks(
    ice_categories: list[str],
    *,
    fu: str = "kg",
) -> list[dict]:
    """
    ICE DB embodied-carbon benchmark lines for the matched categories.

    * ``kg`` — **one line per ICE material** with ``ec_kgco2e_per_kg`` (V4.1
      non-legacy). Categories with more than ``_ICE_KG_PER_MATERIAL_MAX``
      materials fall back to a category / sub-group median so charts stay
      readable (Concrete, large Cement sets).
    * ``m2`` / ``m3`` — one **median** of ``ec_kgco2e_per_unit`` per category
      where ``declared_unit`` matches (per-material ICE rows are kg-oriented).

    Cement and Mortar medians are split into 'Cement' and 'Mortar' sub-groups.
    Timber always uses the 'excluding carbon storage' sub-group only.
    Returns [{label, value, n, unit}] sorted by value.
    """
    fu_norm = str(fu or "kg").strip().lower()
    if fu_norm not in ("kg", "m2", "m3"):
        fu_norm = "kg"

    materials = fn221_load_ice_db()
    if not materials:
        return []

    def _allowed(m: dict) -> bool:
        name = str(m.get("name") or "").lower()
        return not any(frag in name for frag in _ICE_EXCLUDED_NAME_FRAGMENTS)

    def _entries_for_cat(cat: str) -> list[dict]:
        base = [
            m for m in materials
            if m.get("category") == cat
            and not m.get("is_legacy", False)
            and _allowed(m)
        ]
        if fu_norm == "kg":
            return [m for m in base if m.get("ec_kgco2e_per_kg") is not None]
        return [
            m for m in base
            if str(m.get("declared_unit") or "").strip().lower() == fu_norm
            and m.get("ec_kgco2e_per_unit") is not None
        ]

    def _timber_excl(entries: list[dict]) -> list[dict]:
        excl = [
            m for m in entries
            if "excluding" in (m.get("subcategory") or "").lower()
        ]
        return excl if excl else entries

    def _ec_vals(entries: list[dict]) -> list[float]:
        key = "ec_kgco2e_per_kg" if fu_norm == "kg" else "ec_kgco2e_per_unit"
        return sorted(float(m[key]) for m in entries)

    def _append_median(label: str, entries: list[dict]) -> None:
        if not entries:
            return
        vals = _ec_vals(entries)
        results.append({
            "label": label,
            "value": vals[len(vals) // 2],
            "n": len(entries),
            "unit": fu_norm,
        })

    results: list[dict] = []
    for cat in ice_categories:
        v4_entries = _entries_for_cat(cat)
        if not v4_entries:
            continue

        if cat == "Timber":
            v4_entries = _timber_excl(v4_entries)

        # kg + manageable category size → one dashed line per ICE material
        if fu_norm == "kg" and len(v4_entries) <= _ICE_KG_PER_MATERIAL_MAX:
            for m in v4_entries:
                results.append({
                    "label": _ice_material_label(m.get("name") or "", cat),
                    "value": float(m["ec_kgco2e_per_kg"]),
                    "n": 1,
                    "unit": fu_norm,
                })
            continue

        # Split Cement and Mortar into meaningful sub-groups (median fallback)
        if cat == "Cement and Mortar":
            cement_e = [
                m for m in v4_entries
                if any(k in (m.get("subcategory") or "").lower()
                       for k in ("cement", "cem", "admixture"))
            ]
            mortar_e = [
                m for m in v4_entries
                if "mortar" in (m.get("subcategory") or "").lower()
            ]
            _append_median("ICE Cement", cement_e)
            _append_median("ICE Mortar", mortar_e)
            continue

        if cat == "Timber":
            _append_median("ICE Timber (excl. C storage)", v4_entries)
            continue

        # Default: category-level median (m²/m³, or oversized kg categories)
        _append_median(f"ICE {cat}", v4_entries)

    results.sort(key=lambda r: r["value"])
    return results


def fn233_chart_typo_from_dims(dims: dict | None = None) -> dict:
    """
    Shared chart typography from ``theme.json → catalogue.charts``.

    Returns keys used by Plotly / Altair / ECharts helpers:
    ``family``, ``size``, ``title_size``, ``axis_title_size``, ``legend_size``,
    ``tick_size``, ``annotation_size``, ``tick_angle``, ``wrap_chars``.
    """
    d = dims or {}
    try:
        if not d:
            from .lib_ui import fn341_get_charts_dimensions
            d = fn341_get_charts_dimensions()
    except Exception:
        d = d or {}
    return {
        "family": d.get("chart_font_family", "Miranda Sans, Source Sans Pro, sans-serif"),
        "size": int(d.get("chart_font_size", 11)),
        "title_size": int(d.get("chart_title_font_size", 16)),
        "axis_title_size": int(d.get("chart_axis_title_size", 12)),
        "legend_size": int(d.get("chart_legend_font_size", 10)),
        "tick_size": int(d.get("chart_tick_font_size", 10)),
        "annotation_size": int(d.get("chart_annotation_size", 10)),
        "tick_angle": int(d.get("chart_tick_label_angle", 0)),
        "wrap_chars": int(d.get("chart_tick_wrap_chars", 16)),
    }


def fn234_wrap_tick_label(
    label,
    width: int = 16,
    *,
    joiner: str = "<br>",
    max_lines: int | None = None,
) -> str:
    """Word-wrap a categorical tick label at spaces / commas / parentheses only.

    Never splits mid-word. When *max_lines* is set (strip charts), *width* is
    chosen so long labels typically land on about that many lines while still
    fitting under the column.
    """
    import re as _re

    raw = str(label or "").strip()
    if not raw:
        return raw

    # Tokenise on whitespace and break punctuation; keep words intact.
    parts = _re.findall(r"[^\s,()]+|[(),]", raw)
    if not parts:
        return raw

    w = max(4, int(width or 16))
    if max_lines and max_lines > 1:
        # Narrow enough to fill ~max_lines, but never narrower than longest word.
        longest = max(len(p) for p in parts if p not in (",", "(", ")"))
        target = max(longest, (len(raw.replace(" ", "")) + max_lines - 1) // max_lines)
        w = max(longest, min(w, target))

    def _join(chunks: list[str]) -> str:
        out = ""
        for c in chunks:
            if not out:
                out = c
            elif c in (",", ")"):
                out += c
            elif out.endswith("("):
                out += c
            else:
                out += " " + c
        return out

    lines: list[str] = []
    cur: list[str] = []
    length = 0
    for tok in parts:
        # Prefer a new line before "(" when the current line already has content.
        prefer_break = tok == "(" and cur and length >= max(3, w // 2)
        add = len(tok) if tok in (",", "(", ")") else (len(tok) + (1 if cur else 0))
        if (prefer_break or (length + add > w and cur)) and tok not in (",", ")"):
            lines.append(_join(cur))
            cur, length = [tok], len(tok)
        else:
            cur.append(tok)
            length += add if cur[:-1] or tok in (",", "(", ")") else len(tok)
            if len(cur) == 1:
                length = len(tok)
    if cur:
        lines.append(_join(cur))

    # If still too many lines, merge adjacent pairs (never split words).
    if max_lines and len(lines) > max_lines:
        while len(lines) > max_lines and len(lines) >= 2:
            best_i, best_len = 0, len(lines[0]) + 1 + len(lines[1])
            for i in range(1, len(lines) - 1):
                cand = len(lines[i]) + 1 + len(lines[i + 1])
                if cand < best_len:
                    best_i, best_len = i, cand
            merged = (lines[best_i] + " " + lines[best_i + 1])
            merged = merged.replace(" ,", ",").replace("( ", "(").replace(" )", ")")
            lines[best_i] = merged
            del lines[best_i + 1]

    return joiner.join(lines)


def fn233a_altair_font_config(dims: dict | None = None):
    """Altair ``.configure*`` chain kwargs for shared chart typography."""
    t = fn233_chart_typo_from_dims(dims)
    return {
        "font": t["family"],
        "labelFont": t["family"],
        "titleFont": t["family"],
        "labelFontSize": t["tick_size"],
        "titleFontSize": t["axis_title_size"],
        "legendLabelFontSize": t["legend_size"],
        "legendTitleFontSize": t["legend_size"],
        "tick_angle": t["tick_angle"],
        "wrap_chars": t["wrap_chars"],
        "size": t["size"],
    }


def fn233b_echarts_text_style(dims: dict | None = None) -> dict:
    """ECharts global ``textStyle`` + axis label defaults from theme."""
    t = fn233_chart_typo_from_dims(dims)
    return {
        "textStyle": {
            "fontFamily": t["family"],
            "fontSize": t["size"],
        },
        "axisLabel": {
            "fontFamily": t["family"],
            "fontSize": t["tick_size"],
            "rotate": t["tick_angle"],
            "width": max(48, t["wrap_chars"] * 7),
            "overflow": "break",
        },
        "nameTextStyle": {
            "fontFamily": t["family"],
            "fontSize": t["axis_title_size"],
        },
        "legendTextStyle": {
            "fontFamily": t["family"],
            "fontSize": t["legend_size"],
        },
    }


# Fallback ICE line colours (non-insulation categories)
_ICE_LINE_PALETTE = [
    "#1565c0",  # blue
    "#2e7d32",  # green
    "#6a1b9a",  # purple
    "#e65100",  # deep orange
    "#00695c",  # teal
    "#c62828",  # red
    "#37474f",  # blue-grey
    "#f9a825",  # amber
]

# Insulation Material Type palette — warm sands + distinct cool greys for EPS/XPS.
_INSULATION_MATERIAL_PALETTE = [
    "#ACA37F",  # Fibreglass — warm sand yellow
    "#9D8A75",  # Mineral wool — warm tan
    "#84968A",  # PIR — former EPS cool green-gray
    "#C5CAD0",  # EPS — cold light grey (blue cast)
    "#A8AEB6",  # XPS — cold light grey (slightly deeper)
    "#8A7568",  # PUR — warm red-brown taupe
    "#A99D70",  # Phenolic — soft gold
    "#73856F",  # Wood wool — sage green-gray
    "#A39193",  # PET — mauve / dusty rose-gray
    "#7A8B84",  # spare — teal-leaning gray
]

# Exact D__MaterialType_ENG → palette colour (Charts when Product Type = Insulation).
_INSULATION_MATERIAL_COLORS: dict[str, str] = {
    "Fibreglass (Glass wool, Mineral fibre)": "#ACA37F",
    "Mineral wool (Stone, Rock)":             "#9D8A75",
    "PIR (Polyisocyanurate)":                 "#84968A",
    "EPS (Expanded Polystyrene)":             "#C5CAD0",
    "XPS (Extruded Polystyrene)":             "#A8AEB6",
    "Polyurethane Foam":                      "#8A7568",
    "Phenolic Foam":                          "#A99D70",
    "Wood wool":                              "#73856F",
    "PET":                                    "#A39193",
}

# ICE full / short label stems → same colours as the matching material type.
# Polystyrene ICE (EPS/XPS) shares the EPS swatch so the benchmark matches one material.
_ICE_INSULATION_COLORS: dict[str, str] = {
    "glass wool":               "#ACA37F",
    "mineral wool":             "#9D8A75",
    "min. wool":                "#9D8A75",
    "polyisocyanurate (pir)":   "#84968A",
    "polyisocyanurate":         "#84968A",
    "pir":                      "#84968A",
    "polystyrene":              "#C5CAD0",
    "eps/xps":                  "#C5CAD0",
    "polyurethane board":       "#8A7568",
    "polyurethane":             "#8A7568",
    "pur":                      "#8A7568",
}


def _df_is_insulation_products(df: pd.DataFrame | None) -> bool:
    """True when the framed product types are insulation (or empty/unknown)."""
    if df is None or "D__ProductType_ENG" not in getattr(df, "columns", []):
        return False
    vals = [
        str(v).strip().lower()
        for v in df["D__ProductType_ENG"].dropna().unique()
        if str(v).strip() and str(v).strip().lower() not in ("nan", "-", "")
    ]
    return bool(vals) and all("insulation" in v for v in vals)


def _is_material_type_col(col: str | None) -> bool:
    c = str(col or "").strip()
    return c == "D__MaterialType_ENG" or c.endswith("MaterialType_ENG")


def fn231_insulation_material_color_map(
    df: pd.DataFrame | None,
    group_or_color_col: str | None,
    base_map: dict | None = None,
) -> dict:
    """
    Merge the insulation Material Type palette into *base_map* when Charts
    group/colour by ``D__MaterialType_ENG`` and the frame is Insulation-only.

    Unknown insulation material labels receive the next unused palette swatches.
    """
    out = dict(base_map or {})
    if not _is_material_type_col(group_or_color_col):
        return out
    if not _df_is_insulation_products(df):
        return out

    out.update(_INSULATION_MATERIAL_COLORS)

    if df is not None and group_or_color_col in df.columns:
        seen = {
            str(v).strip()
            for v in df[group_or_color_col].dropna().unique()
            if str(v).strip() and str(v).strip().lower() not in ("nan", "-", "")
        }
        used = {c.lower() for c in out.values()}
        spare = [c for c in _INSULATION_MATERIAL_PALETTE if c.lower() not in used]
        si = 0
        for mat in sorted(seen):
            if mat in out:
                continue
            out[mat] = spare[si % len(spare)] if spare else _INSULATION_MATERIAL_PALETTE[
                si % len(_INSULATION_MATERIAL_PALETTE)
            ]
            si += 1
    return out


def fn232_ice_line_color(bm: dict, fallback_index: int = 0) -> str:
    """
    Colour for an ICE benchmark line.

    Insulation ICE materials use the Material Type palette (matched by short /
    full label). Other ICE categories keep ``_ICE_LINE_PALETTE``.
    """
    full = str(bm.get("label") or "").strip()
    short = _ice_chart_short_label(full)
    stem = full[4:].strip() if full.upper().startswith("ICE ") else full
    for key in (short.lower(), stem.lower(), full.lower()):
        if key in _ICE_INSULATION_COLORS:
            return _ICE_INSULATION_COLORS[key]
        for src, color in sorted(_ICE_INSULATION_COLORS.items(), key=lambda kv: -len(kv[0])):
            if src in key:
                return color
    # Known insulation short labels without a map entry still stay in-family.
    if short in ("Glass Wool", "Min. Wool", "PIR", "EPS/XPS", "PUR") or any(
        k in stem.lower()
        for k in ("wool", "polystyrene", "polyurethane", "polyisocyanurate", "pir")
    ):
        return _INSULATION_MATERIAL_PALETTE[fallback_index % len(_INSULATION_MATERIAL_PALETTE)]
    return _ICE_LINE_PALETTE[fallback_index % len(_ICE_LINE_PALETTE)]


def _ice_hover_html(bm: dict) -> str:
    """Hover body for an ICE benchmark (value + optional n); label is separate."""
    unit_lbl = _ICE_FU_UNIT_LABEL.get(str(bm.get("unit") or "kg"), "kg CO₂e/kg")
    x_val = float(bm["value"])
    n = bm.get("n")
    n_part = f"<br>n={n}" if n not in (None, 1) else ""
    return f"{x_val:.3f} {unit_lbl}{n_part}"


def _ice_box_y_endpoints(fig: go.Figure) -> tuple[str | float | None, str | float | None]:
    """First/last categorical y names from box traces (for hoverable vertical lines)."""
    cats: list[str] = []
    for tr in fig.data:
        if getattr(tr, "type", None) == "box" and tr.name is not None:
            cats.append(str(tr.name))
    if len(cats) >= 2:
        return cats[0], cats[-1]
    if len(cats) == 1:
        return cats[0], cats[0]
    return None, None


def fn225_add_ice_benchmarks_to_chart(fig: go.Figure, benchmarks: list[dict]) -> go.Figure:
    """
    Add ICE DB EC benchmark lines as vertical dashed lines on box/bar charts.

    Visible label = shortened material name, drawn **above** the plot area.
    Full name + numeric value (+ n) appear on hover.
    """
    if not benchmarks:
        return fig

    # Room above the plot for rotated short labels (do not cover top data rows).
    max_label_len = max(
        len(_ice_chart_short_label(str(bm.get("label") or ""))) for bm in benchmarks
    )
    need_t = max(72, int(max_label_len * 6.2) + 28)
    cur_margin = fig.layout.margin
    cur_t = int(cur_margin.t) if cur_margin and cur_margin.t is not None else 10
    fig.update_layout(
        margin=dict(
            l=cur_margin.l if cur_margin and cur_margin.l is not None else 20,
            r=cur_margin.r if cur_margin and cur_margin.r is not None else 20,
            b=cur_margin.b if cur_margin and cur_margin.b is not None else 10,
            t=max(cur_t, need_t),
        )
    )

    y0, y1 = _ice_box_y_endpoints(fig)

    for i, bm in enumerate(benchmarks):
        color = fn232_ice_line_color(bm, i)
        x_val = float(bm["value"])
        full_label = str(bm.get("label") or f"ICE #{i + 1}")
        short_label = _ice_chart_short_label(full_label)
        hover = _ice_hover_html(bm)

        if y0 is not None and y1 is not None:
            fig.add_trace(go.Scatter(
                x=[x_val, x_val],
                y=[y0, y1],
                mode="lines",
                line=dict(width=1.5, dash="dash", color=color),
                opacity=0.85,
                name=full_label,
                hovertemplate=f"<b>{full_label}</b><br>{hover}<extra></extra>",
                showlegend=False,
            ))
        else:
            fig.add_vline(
                x=x_val,
                line_width=1.5,
                line_dash="dash",
                line_color=color,
                opacity=0.85,
            )

        # Short name only, anchored just above the plot (rises into top margin).
        fig.add_annotation(
            x=x_val,
            y=1.0,
            xref="x",
            yref="paper",
            text=short_label,
            showarrow=False,
            textangle=-90,
            yanchor="bottom",
            xanchor="center",
            yshift=6,
            font=dict(size=9, color=color),
            bgcolor="rgba(255,255,255,0.0)",
            borderpad=0,
        )
    return fig


def fn226_add_ice_hlines_to_chart(fig: go.Figure, benchmarks: list[dict]) -> go.Figure:
    """
    Horizontal variant of fn225 for correlation / strip charts (GWP on Y).

    Short name sits just outside the right edge; full name + value on hover.
    """
    if not benchmarks:
        return fig

    max_label_len = max(
        len(_ice_chart_short_label(str(bm.get("label") or ""))) for bm in benchmarks
    )
    need_r = max(56, int(max_label_len * 6.5) + 16)
    cur_margin = fig.layout.margin
    cur_r = int(cur_margin.r) if cur_margin and cur_margin.r is not None else 20
    fig.update_layout(
        margin=dict(
            l=cur_margin.l if cur_margin and cur_margin.l is not None else 20,
            r=max(cur_r, need_r),
            t=cur_margin.t if cur_margin and cur_margin.t is not None else 30,
            b=cur_margin.b if cur_margin and cur_margin.b is not None else 10,
        )
    )

    # Span full x data range when available (hoverable line).
    x0 = x1 = None
    try:
        xa = fig.layout.xaxis
        if xa is not None and xa.range is not None and len(xa.range) == 2:
            x0, x1 = float(xa.range[0]), float(xa.range[1])
    except Exception:
        x0 = x1 = None
    if x0 is None:
        xs: list[float] = []
        for tr in fig.data:
            xv = getattr(tr, "x", None)
            if xv is None:
                continue
            for v in xv:
                try:
                    if v is not None and str(v).lower() != "none":
                        xs.append(float(v))
                except (TypeError, ValueError):
                    pass
        if xs:
            x0, x1 = min(xs), max(xs)

    for i, bm in enumerate(benchmarks):
        color = fn232_ice_line_color(bm, i)
        y_val = float(bm["value"])
        full_label = str(bm.get("label") or f"ICE #{i + 1}")
        short_label = _ice_chart_short_label(full_label)
        hover = _ice_hover_html(bm)

        if x0 is not None and x1 is not None:
            fig.add_trace(go.Scatter(
                x=[x0, x1],
                y=[y_val, y_val],
                mode="lines",
                line=dict(width=1.5, dash="dash", color=color),
                opacity=0.85,
                name=full_label,
                hovertemplate=f"<b>{full_label}</b><br>{hover}<extra></extra>",
                showlegend=False,
            ))
        else:
            fig.add_hline(
                y=y_val,
                line_width=1.5,
                line_dash="dash",
                line_color=color,
                opacity=0.85,
            )

        fig.add_annotation(
            x=1.0,
            y=y_val,
            xref="paper",
            yref="y",
            text=short_label,
            showarrow=False,
            xanchor="left",
            yanchor="middle",
            xshift=6,
            font=dict(size=9, color=color),
            bgcolor="rgba(255,255,255,0.0)",
            borderpad=0,
        )
    return fig


def fn229_plot_box_chart_altair(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    *,
    groups: list | None = None,
    showpoints: bool = True,
    x_title: str = "",
    y_title: str = "",
    height: int = 520,
    ice_benchmarks: list[dict] | None = None,
    cam_targets: dict | None = None,
    color_map: dict | None = None,
):
    """
    Altair horizontal box chart with optional ICE vertical rules.

    ICE labels sit in the top padding (name only); value is in the rule tooltip.
    When *color_map* is set (insulation Material Type), boxes/points use those colours.
    """
    import altair as alt

    work = df[[group_col, value_col]].copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=[value_col])
    if groups is None:
        groups = list(_sorted_unique_categories(work[group_col].dropna().unique()))
    work[group_col] = work[group_col].astype(str)
    group_order = [str(g) for g in groups]

    color_enc = alt.Undefined
    if color_map:
        domain = [g for g in group_order if g in color_map] or group_order
        rng = [color_map.get(g, _INSULATION_MATERIAL_PALETTE[i % 10]) for i, g in enumerate(domain)]
        color_enc = alt.Color(
            f"{group_col}:N",
            scale=alt.Scale(domain=domain, range=rng),
            legend=None,
        )

    box_enc = dict(
        y=alt.Y(
            f"{group_col}:N",
            title=y_title or group_col,
            sort=group_order,
            scale=alt.Scale(domain=group_order),
        ),
        x=alt.X(f"{value_col}:Q", title=x_title or value_col),
        tooltip=[
            alt.Tooltip(f"{group_col}:N", title=y_title or "Group"),
            alt.Tooltip(f"{value_col}:Q", title=x_title or "Value", format=".3f"),
        ],
    )
    if color_enc is not alt.Undefined:
        box_enc["color"] = color_enc

    box = (
        alt.Chart(work)
        .mark_boxplot(extent="min-max", size=18, outliers=not showpoints)
        .encode(**box_enc)
    )
    layers = [box]
    if showpoints and "A__ProductName" in df.columns:
        pts = df[[group_col, value_col, "A__ProductName"]].copy()
        pts[value_col] = pd.to_numeric(pts[value_col], errors="coerce")
        pts = pts.dropna(subset=[value_col])
        pts[group_col] = pts[group_col].astype(str)
        pt_enc = dict(
            y=alt.Y(f"{group_col}:N", sort=group_order),
            x=alt.X(f"{value_col}:Q"),
            tooltip=[
                alt.Tooltip("A__ProductName:N", title="Product"),
                alt.Tooltip(f"{value_col}:Q", title=x_title or "Value", format=".3f"),
                alt.Tooltip(f"{group_col}:N", title=y_title or "Group"),
            ],
        )
        if color_enc is not alt.Undefined:
            pt_enc["color"] = color_enc
            layers.append(alt.Chart(pts).mark_circle(size=28, opacity=0.65).encode(**pt_enc))
        else:
            layers.append(
                alt.Chart(pts).mark_circle(size=28, opacity=0.55, color="#546e7a").encode(**pt_enc)
            )
    elif showpoints:
        pt_enc = dict(
            y=alt.Y(f"{group_col}:N", sort=group_order),
            x=alt.X(f"{value_col}:Q"),
            tooltip=[
                alt.Tooltip(f"{group_col}:N", title=y_title or "Group"),
                alt.Tooltip(f"{value_col}:Q", title=x_title or "Value", format=".3f"),
            ],
        )
        if color_enc is not alt.Undefined:
            pt_enc["color"] = color_enc
            layers.append(alt.Chart(work).mark_circle(size=28, opacity=0.55).encode(**pt_enc))
        else:
            layers.append(
                alt.Chart(work).mark_circle(size=28, opacity=0.45, color="#546e7a").encode(**pt_enc)
            )

    if cam_targets:
        for g, target in cam_targets.items():
            if target is None:
                continue
            cam_df = pd.DataFrame({"x": [float(target)], "g": [str(g)]})
            layers.append(
                alt.Chart(cam_df)
                .mark_rule(strokeDash=[3, 3], color="#222", strokeWidth=1.5)
                .encode(x="x:Q", y=alt.Y("g:N", sort=group_order))
            )

    ice_top_pad = 12
    if ice_benchmarks:
        max_len = max(
            len(_ice_chart_short_label(str(bm.get("label") or "")))
            for bm in ice_benchmarks
        )
        ice_top_pad = max(56, int(max_len * 5.5) + 20)
        for i, bm in enumerate(ice_benchmarks):
            color = fn232_ice_line_color(bm, i)
            full_label = str(bm.get("label") or f"ICE #{i + 1}")
            short_label = _ice_chart_short_label(full_label)
            unit_lbl = _ICE_FU_UNIT_LABEL.get(str(bm.get("unit") or "kg"), "kg CO₂e/kg")
            val = float(bm["value"])
            n = bm.get("n")
            tip = f"{val:.3f} {unit_lbl}" + (f" · n={n}" if n not in (None, 1) else "")
            bm_df = pd.DataFrame({
                "x": [val],
                "full": [full_label],
                "short": [short_label],
                "tip": [tip],
            })
            layers.append(
                alt.Chart(bm_df)
                .mark_rule(strokeDash=[6, 3], color=color, strokeWidth=1.5)
                .encode(
                    x="x:Q",
                    tooltip=[
                        alt.Tooltip("full:N", title="ICE"),
                        alt.Tooltip("tip:N", title="Value"),
                    ],
                )
            )
            layers.append(
                alt.Chart(bm_df)
                .mark_text(
                    angle=270,
                    align="left",
                    baseline="middle",
                    dy=-10,
                    fontSize=10,
                    color=color,
                    clip=False,
                    fontWeight="normal",
                )
                .encode(x="x:Q", y=alt.value(0), text="short:N")
            )

    _af = fn233a_altair_font_config()
    chart = (
        alt.layer(*layers)
        .properties(height=height, padding={"top": ice_top_pad, "left": 4, "right": 8, "bottom": 4})
        .configure(font=_af["font"])
        .configure_axis(
            labelFont=_af["labelFont"],
            titleFont=_af["titleFont"],
            labelFontSize=_af["labelFontSize"],
            titleFontSize=_af["titleFontSize"],
            labelLimit=220,
            labelAngle=_af["tick_angle"],
        )
        .configure_legend(
            labelFont=_af["labelFont"],
            titleFont=_af["titleFont"],
            labelFontSize=_af["legendLabelFontSize"],
            titleFontSize=_af["legendTitleFontSize"],
        )
        .interactive()
    )
    return chart


def fn230_build_echarts_box_html(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    *,
    groups: list | None = None,
    showpoints: bool = True,
    x_title: str = "",
    y_title: str = "",
    height: int = 520,
    ice_benchmarks: list[dict] | None = None,
    color_map: dict | None = None,
) -> str:
    """
    ECharts JS horizontal boxplot HTML snippet (CDN + inline option).

    ICE markLines use name-only labels above the grid; value is in the tooltip.
    """
    work = df.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=[value_col])
    if groups is None:
        groups = list(_sorted_unique_categories(work[group_col].dropna().unique()))
    group_labels = [str(g) for g in groups]
    cmap = dict(color_map or {})

    # ECharts boxplot datum: [min, Q1, median, Q3, max] (+ optional itemStyle)
    box_data: list = []
    scatter_data: list[list] = []
    for gi, g in enumerate(group_labels):
        vals = work.loc[work[group_col].astype(str) == g, value_col].astype(float)
        mat_color = cmap.get(g) or (
            _INSULATION_MATERIAL_PALETTE[gi % len(_INSULATION_MATERIAL_PALETTE)] if cmap else None
        )
        if vals.empty:
            entry: dict | list = [0, 0, 0, 0, 0]
            if mat_color:
                entry = {"value": [0, 0, 0, 0, 0], "itemStyle": {"color": mat_color, "borderColor": mat_color}}
            box_data.append(entry)
            continue
        q1 = float(vals.quantile(0.25))
        med = float(vals.median())
        q3 = float(vals.quantile(0.75))
        stats = [float(vals.min()), q1, med, q3, float(vals.max())]
        if mat_color:
            box_data.append({"value": stats, "itemStyle": {"color": mat_color, "borderColor": mat_color}})
        else:
            box_data.append(stats)
        if showpoints:
            names = None
            if "A__ProductName" in work.columns:
                names = work.loc[work[group_col].astype(str) == g, "A__ProductName"].tolist()
            for j, v in enumerate(vals.tolist()):
                tip = str(names[j]) if names and j < len(names) else g
                scatter_data.append([v, g, tip, mat_color or "#546e7a"])

    ice_mark_line = []
    top_pad = 48
    if ice_benchmarks:
        max_len = max(
            len(_ice_chart_short_label(str(bm.get("label") or "")))
            for bm in ice_benchmarks
        )
        top_pad = max(72, int(max_len * 6.0) + 36)
        for i, bm in enumerate(ice_benchmarks):
            color = fn232_ice_line_color(bm, i)
            full_label = str(bm.get("label") or f"ICE #{i + 1}")
            short_label = _ice_chart_short_label(full_label)
            unit_lbl = _ICE_FU_UNIT_LABEL.get(str(bm.get("unit") or "kg"), "kg CO₂e/kg")
            val = float(bm["value"])
            n = bm.get("n")
            tip = f"{val:.3f} {unit_lbl}" + (f" · n={n}" if n not in (None, 1) else "")
            ice_mark_line.append({
                "name": full_label,
                "xAxis": val,
                "lineStyle": {"type": "dashed", "width": 1.5, "color": color},
                "label": {
                    "show": True,
                    "formatter": short_label,
                    "position": "end",
                    "distance": 8,
                    "rotate": 90,
                    "color": color,
                    "fontSize": 10,
                },
                "tooltip": {"formatter": f"<b>{full_label}</b><br/>{tip}"},
            })

    series: list[dict] = [
        {
            "name": "Box",
            "type": "boxplot",
            "layout": "horizontal",
            "data": box_data,
            "itemStyle": {"color": "#90caf9", "borderColor": "#1565c0"},
            "boxWidth": [12, 28],
            "markLine": {
                "symbol": ["none", "none"],
                "silent": False,
                "precision": 4,
                "data": ice_mark_line,
                "animation": False,
            } if ice_mark_line else None,
        }
    ]
    if series[0]["markLine"] is None:
        del series[0]["markLine"]

    if scatter_data:
        series.append({
            "name": "Points",
            "type": "scatter",
            "data": [
                {
                    "value": [p[0], p[1]],
                    "product": p[2],
                    "itemStyle": {"color": p[3] if len(p) > 3 else "#546e7a", "opacity": 0.65},
                }
                for p in scatter_data
            ],
            "symbolSize": 7,
            "itemStyle": {"color": "#546e7a", "opacity": 0.55},
            "tooltip": {
                "formatter": "TOOLTIP_POINT",
            },
        })

    _ec_ty = fn233b_echarts_text_style()
    option = {
        "textStyle": _ec_ty["textStyle"],
        "tooltip": {
            "trigger": "item",
            "axisPointer": {"type": "shadow"},
            "textStyle": _ec_ty["textStyle"],
        },
        "grid": {
            "left": 12,
            "right": 24,
            "top": top_pad,
            "bottom": 40,
            "containLabel": True,
        },
        "xAxis": {
            "type": "value",
            "name": x_title or value_col,
            "nameLocation": "middle",
            "nameGap": 28,
            "nameTextStyle": _ec_ty["nameTextStyle"],
            "axisLabel": _ec_ty["axisLabel"],
            "splitLine": {"lineStyle": {"type": "dashed", "opacity": 0.4}},
        },
        "yAxis": {
            "type": "category",
            "data": group_labels,
            "name": y_title or group_col,
            "nameLocation": "middle",
            "nameGap": 70,
            "nameTextStyle": _ec_ty["nameTextStyle"],
            "axisLabel": {
                **_ec_ty["axisLabel"],
                "interval": 0,
                "width": 160,
                "overflow": "break",
                "rotate": 0,
            },
        },
        "series": series,
    }

    opt_json = _json.dumps(option, ensure_ascii=False, default=str)
    # Point tooltip: product name + value
    point_fmt = (
        "function(p){var pr=(p.data&&p.data.product)||'';"
        "var v=(p.value&&p.value[0]!=null)?Number(p.value[0]).toFixed(3):'';"
        "return '<b>'+pr+'</b><br/>'+v;}"
    )
    opt_json = opt_json.replace('"TOOLTIP_POINT"', point_fmt)

    return (
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
        f'<div id="ec_box" style="width:100%;height:{int(height)}px"></div>'
        f"<script>var c=echarts.init(document.getElementById('ec_box'),null,{{renderer:'canvas'}});"
        f"c.setOption({opt_json});"
        "window.addEventListener('resize',function(){c.resize();});</script>"
    )


# ════════════════════════════════════════════════════════════════════════════
# fn202 — Logo image (base64 data URI)
# ════════════════════════════════════════════════════════════════════════════

def fn202_create_logo_image(logo_path, size=(30, 30)):
    """Load a logo file and return a base64 data URI for use in Plotly figures."""
    from .lib_data import _pil_open_safe
    try:
        if logo_path.startswith('http'):
            response = requests.get(logo_path, timeout=5, verify=True)
            response.raise_for_status()
            image = _pil_open_safe(BytesIO(response.content))
        else:
            candidate = Path(logo_path)
            if not candidate.exists():
                candidate = Path(__file__).resolve().parent.parent / logo_path
            if str(candidate).lower().endswith('.svg'):
                return None
            image = _pil_open_safe(str(candidate))
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        image = image.resize(size, Image.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except Exception as e:
        print(f"Error creating logo image for {logo_path}: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# fn201 — Box / candle chart
# ════════════════════════════════════════════════════════════════════════════

def fn201_plot_box_chart(
    df, group_col, value_col, settings, color_map=None, sort_by='none',
    show_logos=False, cement_marker_styles=None,
    gwp_visualization='bands', should_add_gwp_visualization=None,
):
    """Create a horizontal box chart with optional sorting, logos, cement markers, GWP overlay."""
    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors='coerce')
    df = df.dropna(subset=[value_col])

    manu_colors = {}
    if group_col == 'A__Manufacturer':
        manu_colors = _get_manufacturer_color_mapping()
        def _norm(s: str) -> str:
            return re.sub(r"\s+", " ", str(s).strip()).lower()

    if sort_by == 'alphabetical':
        groups = _sorted_unique_categories(df[group_col].unique())
    elif sort_by == 'alphabetical_desc':
        groups = _sorted_unique_categories(df[group_col].unique(), reverse=True)
    elif sort_by == 'value_mean':
        group_means = df.groupby(group_col)[value_col].mean().sort_values()
        groups = group_means.index.tolist()
    elif sort_by == 'value_median':
        group_medians = df.groupby(group_col)[value_col].median().sort_values()
        groups = group_medians.index.tolist()
    else:
        groups = df[group_col].unique()

    fig = go.Figure()
    logo_mapping = None

    for group in groups:
        group_df = df[df[group_col] == group]
        group_values = group_df[value_col]
        color = None
        if color_map and group in color_map:
            color = color_map[group]
        elif group_col == 'A__Manufacturer' and manu_colors:
            color = manu_colors.get(_norm(group))
        if not color:
            color = "#1f77b4"

        hover_text = None
        if settings["showpoints"] and "A__ProductName" in df.columns:
            hover_text = group_df["A__ProductName"].tolist()

        fig.add_trace(go.Box(
            x=group_values,
            name=str(group),
            orientation='h',
            boxpoints='outliers' if cement_marker_styles and settings["showpoints"] else ('all' if settings["showpoints"] else 'outliers'),
            line=dict(width=2, color=color),
            whiskerwidth=0.2,
            boxmean=True if settings["showpoints"] else False,
            text=hover_text,
            hovertemplate='<b>%{text}</b><br>Value: %{x:.2f}<extra></extra>' if hover_text else
                         '<b>Q1:</b> %{q1:.2f}<br><b>Median:</b> %{median:.2f}<br>'
                         '<b>Q3:</b> %{q3:.2f}<br><b>Mean:</b> %{mean:.2f}<br>'
                         '<b>Min:</b> %{lowerfence:.2f}<br><b>Max:</b> %{upperfence:.2f}<extra></extra>',
            showlegend=False,
        ))

        if cement_marker_styles and settings["showpoints"]:
            group_indices = group_df.index.tolist()
            scatter_x, scatter_y, scatter_colors, scatter_symbols = [], [], [], []
            scatter_text, scatter_line_colors = [], []
            for i, idx in enumerate(group_indices):
                scatter_x.append(group_values.iloc[i])
                scatter_y.append(group)
                if idx in cement_marker_styles:
                    scatter_colors.append(cement_marker_styles[idx]['color'])
                    scatter_symbols.append(cement_marker_styles[idx]['shape'])
                    scatter_line_colors.append(cement_marker_styles[idx]['color'])
                else:
                    scatter_colors.append(color)
                    scatter_symbols.append('circle')
                    scatter_line_colors.append(color)
                if idx in cement_marker_styles and hover_text:
                    ci = cement_marker_styles[idx]
                    hi = f"{hover_text[i]}<br>Cement Type: {ci['family']}"
                    if ci['strength_class']:
                        hi += f"<br>Strength: {ci['strength_class']} MPa"
                    if ci['additions']:
                        hi += f"<br>Additions: {', '.join(ci['additions'])}"
                    scatter_text.append(hi)
                else:
                    scatter_text.append(hover_text[i] if hover_text else str(group_values.iloc[i]))

            if gwp_visualization == 'bands':
                marker_style = dict(color='white', symbol=scatter_symbols, size=12, line=dict(width=2, color=scatter_line_colors))
            else:
                marker_style = dict(color=scatter_colors, symbol=scatter_symbols, size=12, line=dict(width=1, color='white'))

            fig.add_trace(go.Scatter(
                x=scatter_x, y=scatter_y, mode='markers',
                marker=marker_style, text=scatter_text,
                hovertemplate='<b>%{text}</b><br>Value: %{x}<extra></extra>',
                showlegend=False, name=f"{group}_points",
            ))

    if cement_marker_styles:
        cement_legend_data = {
            "I": ("circle", "#1B263B", "Portland cement (≥95% clinker)"),
            "II/A": ("square", "#2E86AB", "Portland-composite cement (6–20% additions)"),
            "II/B": ("square", "#A23B72", "Portland-composite cement (21–35% additions)"),
            "III": ("diamond", "#F18F01", "Blastfurnace cement (slag 36–95%)"),
            "IV": ("triangle-up", "#C73E1D", "Pozzolanic cement (natural/artificial pozzolana)"),
            "V": ("triangle-down", "#6A994E", "Composite cement (mix of several additions)"),
        }
        unique_families = {style['family'] for style in cement_marker_styles.values() if style['family'] != 'Unknown'}
        for family in sorted(unique_families):
            if family in cement_legend_data:
                symbol, col, description = cement_legend_data[family]
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='markers',
                    marker=dict(color=col, symbol=symbol, size=12, line=dict(width=1, color='white')),
                    name=f"CEM {family}", showlegend=True, legendgroup="cement_types",
                ))

    if should_add_gwp_visualization is None:
        should_add_gwp_visualization = fn208_is_concrete_material(df, group_col, value_col)

    if should_add_gwp_visualization:
        gwp_classes = fn205_get_gwp_class_bands()
        all_values = df[value_col].dropna()
        if len(all_values) > 0:
            x_min = max(0, all_values.min() - 50)
            x_max = min(600, all_values.max() + 50)
        else:
            x_min, x_max = 0, 600
        y_min = -0.5
        y_max = len(groups) - 0.5
        if gwp_visualization == 'bands':
            fig = fn206_add_gwp_bands_to_chart(fig, gwp_classes, x_range=(x_min, x_max), y_range=(y_min, y_max))
        elif gwp_visualization == 'lines':
            fig = fn207_add_gwp_lines_to_chart(fig, gwp_classes, x_range=(x_min, x_max), y_range=(y_min, y_max))

    fig.update_layout(
        title=settings["title"],
        width=settings["width"],
        height=settings["height"],
        font=dict(family=settings["font_family"], size=settings["font_size"]),
        title_font_size=settings["title_font_size"],
        xaxis_title=settings["xaxis_title"] or value_col,
        yaxis_title=settings["yaxis_title"] or group_col,
        margin=settings["margin"],
        legend=dict(x=0.02, y=0.98, xanchor='left', yanchor='top',
                    bgcolor='rgba(255,255,255,0.8)', bordercolor='rgba(0,0,0,0.2)',
                    borderwidth=1, font=dict(size=10)),
        yaxis=dict(showgrid=False),
    )

    if show_logos and logo_mapping:
        for i, group in enumerate(groups):
            if group in logo_mapping:
                logo_info = logo_mapping[group]
                logo_img = fn202_create_logo_image(logo_info["logo_path"], size=(25, 25))
                if logo_img:
                    fig.add_layout_image(dict(
                        source=logo_img, xref="paper", yref="y",
                        x=0.02, y=i, sizex=0.03, sizey=0.03,
                        xanchor="left", yanchor="middle", layer="above",
                    ))

    return fig


# ════════════════════════════════════════════════════════════════════════════
# fn203-fn213 — Chart helpers
# ════════════════════════════════════════════════════════════════════════════

def fn203_parse_cement_type(product_name):
    """Parse cement classification (UNI EN 197-1) from product name string."""
    if not product_name or pd.isna(product_name):
        return {'family': 'Unknown', 'additions': [], 'strength_class': None, 'early_strength': None, 'color': '#808080', 'shape': 'circle'}
    product_name = str(product_name).upper()
    result = {'family': 'Unknown', 'additions': [], 'strength_class': None, 'early_strength': None, 'color': '#808080', 'shape': 'circle'}
    if 'TIPO II/A' in product_name:
        result.update({'family': 'II/A', 'color': '#2E86AB', 'shape': 'square'})
    elif 'TIPO II/B' in product_name:
        result.update({'family': 'II/B', 'color': '#A23B72', 'shape': 'square'})
    elif 'TIPO III' in product_name:
        result.update({'family': 'III', 'color': '#F18F01', 'shape': 'diamond'})
    elif 'TIPO IV' in product_name:
        result.update({'family': 'IV', 'color': '#C73E1D', 'shape': 'triangle-up'})
    elif 'TIPO V' in product_name:
        result.update({'family': 'V', 'color': '#6A994E', 'shape': 'triangle-down'})
    elif 'TIPO II' in product_name:
        result.update({'family': 'II', 'color': '#2E86AB', 'shape': 'square'})
    elif 'TIPO I' in product_name:
        result.update({'family': 'I', 'color': '#1B263B', 'shape': 'circle'})
    additions_map = {'LL': 'Limestone', 'M': 'Fly ash mix', 'S': 'Blastfurnace slag',
                     'P': 'Natural pozzolana', 'V': 'Siliceous fly ash', 'LH': 'Low Heat', 'SR': 'Sulphate Resistant'}
    for code, name in additions_map.items():
        if code in product_name:
            result['additions'].append(name)
    if '32,5' in product_name or '32.5' in product_name:
        result['strength_class'] = '32.5'
    elif '42,5' in product_name or '42.5' in product_name:
        result['strength_class'] = '42.5'
    elif '52,5' in product_name or '52.5' in product_name:
        result['strength_class'] = '52.5'
    if ' N' in product_name or ' N)' in product_name:
        result['early_strength'] = 'N'
    elif ' R' in product_name or ' R)' in product_name:
        result['early_strength'] = 'R'
    return result


def fn204_get_cement_marker_styles(df, product_name_col='A__ProductName'):
    """Return dict of marker styles (color, shape, family, ...) for each row index."""
    marker_styles = {}
    # The column test is per frame, not per row; zip avoids building a Series per row.
    if product_name_col not in df.columns:
        return {idx: {'color': '#808080', 'shape': 'circle', 'family': 'Unknown',
                      'additions': [], 'strength_class': None, 'early_strength': None}
                for idx in df.index}
    for idx, name in zip(df.index, df[product_name_col]):
        cement_info = fn203_parse_cement_type(name)
        marker_styles[idx] = {
            'color': cement_info['color'], 'shape': cement_info['shape'],
            'family': cement_info['family'], 'additions': cement_info['additions'],
            'strength_class': cement_info['strength_class'], 'early_strength': cement_info['early_strength'],
        }
    return marker_styles


def fn205_get_gwp_class_bands():
    """Return GWP class band definitions per UNI/PdR 176:2025."""
    return [
        {"class": "GWP-50-IT",  "max_value": 50,  "color": "rgba(0, 100, 50, 0.65)",   "description": "≤ 50 kg CO₂/m³"},
        {"class": "GWP-100-IT", "max_value": 100, "color": "rgba(0, 150, 0, 0.65)",    "description": "≤ 100 kg CO₂/m³"},
        {"class": "GWP-150-IT", "max_value": 150, "color": "rgba(100, 200, 0, 0.65)",  "description": "≤ 150 kg CO₂/m³"},
        {"class": "GWP-200-IT", "max_value": 200, "color": "rgba(200, 220, 0, 0.65)",  "description": "≤ 200 kg CO₂/m³"},
        {"class": "GWP-250-IT", "max_value": 250, "color": "rgba(255, 200, 0, 0.65)",  "description": "≤ 250 kg CO₂/m³"},
        {"class": "GWP-300-IT", "max_value": 300, "color": "rgba(255, 150, 0, 0.65)",  "description": "≤ 300 kg CO₂/m³"},
        {"class": "GWP-350-IT", "max_value": 350, "color": "rgba(255, 100, 0, 0.65)",  "description": "≤ 350 kg CO₂/m³"},
        {"class": "GWP-400-IT", "max_value": 400, "color": "rgba(255, 50, 0, 0.65)",   "description": "≤ 400 kg CO₂/m³"},
        {"class": "GWP-450-IT", "max_value": 450, "color": "rgba(200, 0, 0, 0.65)",    "description": "≤ 450 kg CO₂/m³"},
        {"class": "GWP-500-IT", "max_value": 500, "color": "rgba(150, 0, 0, 0.65)",    "description": "≤ 500 kg CO₂/m³"},
        {"class": "GWP-M-IT",   "max_value": 600, "color": "rgba(100, 0, 0, 0.65)",    "description": "500-600 kg CO₂/m³"},
    ]


def fn206_add_gwp_bands_to_chart(fig, gwp_classes, x_range=None, y_range=None):
    """Add coloured GWP bands as background rectangles to Plotly figure."""
    if x_range is None:
        x_range = (0, 600)
    if y_range is None:
        y_range = (-0.5, 10)
    for i, gwp_class in enumerate(gwp_classes):
        x_start = 0 if i == 0 else gwp_classes[i - 1]["max_value"]
        fig.add_shape(
            type="rect", x0=x_start, y0=y_range[0], x1=gwp_class["max_value"], y1=y_range[1],
            fillcolor=gwp_class["color"], line=dict(width=0), layer="below", name=gwp_class["class"],
        )
    return fig


def fn207_add_gwp_lines_to_chart(fig, gwp_classes, x_range=None, y_range=None):
    """Add vertical GWP threshold lines to Plotly figure."""
    if x_range is None:
        x_range = (0, 600)
    if y_range is None:
        y_range = (-0.5, 10)
    for i, gwp_class in enumerate(gwp_classes):
        if i == 0:
            continue
        x_position = gwp_class["max_value"]
        color = gwp_class["color"]
        if color.startswith("rgba"):
            rgb_values = color[5:-1].split(",")[:3]
            line_color = f"rgb({rgb_values[0]}, {rgb_values[1]}, {rgb_values[2]})"
        else:
            line_color = color
        fig.add_shape(
            type="line", x0=x_position, y0=y_range[0], x1=x_position, y1=y_range[1],
            line=dict(color=line_color, width=2, dash="1px 2px"),
            layer="above", name=f"{gwp_class['class']} boundary",
        )
    return fig


def fn208_is_concrete_material(df, group_col, value_col):
    """Heuristic: return True if the chart data likely represents concrete materials."""
    if 'D__ProductType_ENG' in df.columns:
        product_types = df['D__ProductType_ENG'].dropna().astype(str).str.lower()
        if product_types.str.contains('in situ', na=False).any():
            return True
    concrete_keywords = ['concrete', 'cement', 'calcestruzzo', 'cemento', 'binder', 'legante', 'in situ', 'insitu']
    if group_col in df.columns:
        group_values = df[group_col].dropna().astype(str).str.lower()
        for keyword in concrete_keywords:
            if group_values.str.contains(keyword, na=False).any():
                return True
    if 'gwp' in value_col.lower() and 'm3' in value_col.lower():
        try:
            numeric_values = pd.to_numeric(df[value_col], errors='coerce').dropna()
            if len(numeric_values) > 0:
                value_range = numeric_values.max() - numeric_values.min()
                mean_value = numeric_values.mean()
                if 50 <= mean_value <= 500 and value_range > 50:
                    return True
        except Exception:
            pass
    return False


def fn209_is_in_situ_selected():
    """Return True if 'In situ' is selected in any active filter widget."""
    for i in range(1, 4):
        if st.session_state.get(f"enable_filter_{i}", False):
            filter_col = st.session_state.get(f"filter_col_{i}", "")
            filter_val = st.session_state.get(f"filter_val_{i}", "")
            if filter_col == "D__ProductType_ENG" and isinstance(filter_val, str) and "in situ" in filter_val.lower():
                return True
    return False


def fn210_display_gwp_class_legend():
    """Render expandable GWP class legend (Streamlit expander)."""
    gwp_classes = fn205_get_gwp_class_bands()
    with st.expander("🏷️ GWP Classes (UNI/PdR 176:2025)", expanded=False, type="compact"):
        st.markdown("The background bands in the charts represent the following GWP classes:")
        legend_items = []
        for gwp_class in gwp_classes:
            legend_items.append(textwrap.dedent(f"""
            <div style="background-color: {gwp_class['color']}; border: 1px solid #ccc; padding: 8px 10px; margin: 2px; border-radius: 4px; text-align: center; min-width: 120px; flex: 0 0 auto; box-shadow: 0 0 4px rgba(0,0,0,0.15);">
                <strong>{gwp_class['class']}</strong><br><small>{gwp_class['description']}</small>
            </div>
            """).strip())
        legend_html = textwrap.dedent("""
        <div style="display: flex; flex-wrap: nowrap; gap: 6px; overflow-x: auto; padding-bottom: 6px;">
            {items}
        </div>
        """).format(items="".join(legend_items)).strip()
        st.markdown(legend_html, unsafe_allow_html=True)


def fn211_clean_dataframe_for_streamlit(df):
    """Fix PyArrow-incompatible column types for Streamlit display."""
    if df is None or df.empty:
        return df
    df_cleaned = df.copy()
    for col in df_cleaned.columns:
        try:
            numeric_series = pd.to_numeric(df_cleaned[col], errors='coerce')
            if numeric_series.isna().any() and not numeric_series.isna().all():
                df_cleaned[col] = df_cleaned[col].astype(str)
        except Exception as e:
            print(f"Warning: Could not process column '{col}': {e}. Converting to string.")
            df_cleaned[col] = df_cleaned[col].astype(str)
        if df_cleaned[col].dtype == 'object':
            df_cleaned[col] = df_cleaned[col].astype(str)
            df_cleaned[col] = df_cleaned[col].replace({'nan': '', 'None': '', 'NaN': ''})
    return df_cleaned


def fn212_create_bar_chart(
    df, value_col, color_col, sort_by='none', color_map=None,
    gwp_visualization='bands', should_add_gwp_visualization=None,
    margins=None, show_logos=False,
    font_family: str = 'Miranda Sans, Source Sans Pro, sans-serif',
    font_size: int = 11,
    title_font_size: int = 16,
    axis_title_font_size: int = 12,
    legend_font_size: int = 10,
    tick_font_size: int = 10,
):
    """Full horizontal bar chart with products on y-axis, optional GWP overlay."""
    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors='coerce')
    df = df.dropna(subset=[value_col])

    if 'A__ProductName' in df.columns:
        y_axis_col = 'A__ProductName'
    else:
        df['Product'] = df.index.astype(str)
        y_axis_col = 'Product'

    if sort_by == 'alphabetical':
        df_sorted = df.sort_values(by=y_axis_col, ascending=True)
    elif sort_by == 'alphabetical_desc':
        df_sorted = df.sort_values(by=y_axis_col, ascending=False)
    elif sort_by == 'value_asc':
        df_sorted = df.sort_values(by=value_col, ascending=True)
    elif sort_by == 'value_desc':
        df_sorted = df.sort_values(by=value_col, ascending=False)
    else:
        df_sorted = df

    fig = go.Figure()
    unique_colors = _sorted_unique_categories(df_sorted[color_col].unique())

    color_palettes = [
        pc.qualitative.Set1, pc.qualitative.Set2, pc.qualitative.Set3,
        pc.qualitative.Pastel1, pc.qualitative.Pastel2, pc.qualitative.Dark2,
        pc.qualitative.T10, pc.qualitative.Vivid, pc.qualitative.Light24, pc.qualitative.D3,
    ]
    all_colors = []
    for palette in color_palettes:
        try:
            all_colors.extend(palette)
        except AttributeError:
            continue

    manu_colors = {}
    if color_col == 'A__Manufacturer':
        manu_colors = _get_manufacturer_color_mapping()

    color_mapping = {}
    used_colors = set()
    for i, category in enumerate(unique_colors):
        chosen = None
        if color_map and category in color_map:
            chosen = color_map[category]
        if not chosen and manu_colors:
            key_norm = re.sub(r"\s+", " ", str(category).strip()).lower()
            chosen = manu_colors.get(key_norm)
        if chosen:
            color_mapping[category] = chosen
            used_colors.add(chosen)
            continue
        for color in all_colors:
            if color not in used_colors:
                color_mapping[category] = color
                used_colors.add(color)
                break
        else:
            hue = (i * 137.5) % 360
            rgb = colorsys.hsv_to_rgb(hue / 360, 0.7, 0.9)
            generated = f'rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)})'
            color_mapping[category] = generated
            used_colors.add(generated)

    num_rows = max(1, len(df_sorted))
    computed_height = min(400, max(180, num_rows * 20))
    default_margins = dict(l=20, r=20, t=10, b=20)
    initial_margins = margins if isinstance(margins, dict) else default_margins

    fig.update_layout(
        title='', height=computed_height, width=1000,
        barmode='overlay' if gwp_visualization != 'bands' else None,
        margin=initial_margins,
    )

    # One trace per colour category, not one per product. With ~1,600 products the
    # per-row loop built ~1,600 traces (~3,000 on the dropdown-slice path), which
    # was slow to build here and slower still for plotly.js to lay out. Hover text
    # is precomputed per point, so it reads exactly as before.
    _v_label = value_col.replace("__", " ").replace("_", " ").title()
    _c_label = color_col.replace("__", " ").replace("_", " ").title()
    _ys = df_sorted[y_axis_col].tolist()
    _xs = df_sorted[value_col].tolist()
    _cs = df_sorted[color_col].tolist()
    _points: dict = {}
    for _y, _x, _c in zip(_ys, _xs, _cs):
        _pts = _points.setdefault(_c, ([], [], []))
        _pts[0].append(_x)
        _pts[1].append(_y)
        _pts[2].append(f'<b>{_y}</b><br>{_v_label}: {_x}<br>{_c_label}: {_c}<br>')
    for color_value, (_px, _py, _hover) in _points.items():
        bar_color = color_mapping.get(color_value, '#1f77b4')
        if gwp_visualization == 'bands':
            fig.add_trace(go.Scatter(
                x=_px, y=_py, mode='markers+text',
                name=color_value,
                marker=dict(color='white', size=12, line=dict(width=2, color=bar_color)),
                text=[color_value] * len(_px), textposition='middle right',
                textfont=dict(size=9, color=bar_color), showlegend=False,
                customdata=_hover, hovertemplate='%{customdata}<extra></extra>',
            ))
        else:
            fig.add_trace(go.Bar(
                x=_px, y=_py, orientation='h',
                name=color_value, marker=dict(color=bar_color),
                text=[color_value] * len(_px), textposition='outside',
                textfont=dict(size=9, color=bar_color), showlegend=False,
                customdata=_hover, hovertemplate='%{customdata}<extra></extra>',
            ))
    # Grouping by colour would otherwise reorder the y axis (plotly orders
    # categories by first appearance across traces): pin it to the sort order.
    _y_order = list(dict.fromkeys(_ys))
    fig.update_yaxes(categoryorder='array', categoryarray=_y_order)

    for color_value, color in color_mapping.items():
        if gwp_visualization == 'bands':
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode='markers', name=color_value,
                marker=dict(color='white', size=12, line=dict(width=2, color=color)),
                showlegend=True, hoverinfo='skip',
            ))
        else:
            fig.add_trace(go.Bar(
                x=[None], y=[None], name=color_value, marker_color=color,
                showlegend=True, hoverinfo='skip',
            ))

    if should_add_gwp_visualization is None:
        should_add_gwp_visualization = fn208_is_concrete_material(df, y_axis_col, value_col)

    if should_add_gwp_visualization:
        gwp_classes = fn205_get_gwp_class_bands()
        all_values = df[value_col].dropna()
        if len(all_values) > 0:
            x_min = max(0, all_values.min() - 50)
            x_max = min(600, all_values.max() + 50)
        else:
            x_min, x_max = 0, 600
        y_min = -0.5
        y_max = len(df_sorted) - 0.5
        if gwp_visualization == 'bands':
            fig = fn206_add_gwp_bands_to_chart(fig, gwp_classes, x_range=(x_min, x_max), y_range=(y_min, y_max))
        elif gwp_visualization == 'lines':
            fig = fn207_add_gwp_lines_to_chart(fig, gwp_classes, x_range=(x_min, x_max), y_range=(y_min, y_max))

    fig.update_layout(
        font=dict(family=font_family, size=font_size),
        title_font_size=title_font_size, margin=dict(l=20, r=20, t=40, b=20),
        showlegend=True,
        legend=dict(x=1.02, y=1, xanchor='left', yanchor='top',
                    bgcolor='rgba(255,255,255,0.8)', bordercolor='rgba(0,0,0,0.2)',
                    borderwidth=1, font=dict(size=legend_font_size)),
        xaxis=dict(title=value_col.replace('__', ' ').replace('_', ' ').title(),
                   title_font_size=axis_title_font_size, tickfont_size=tick_font_size),
        yaxis=dict(title='Product', title_font_size=axis_title_font_size, tickfont_size=tick_font_size,
                   tickmode='linear', dtick=1, showgrid=False),
        bargap=0.08 if gwp_visualization != 'bands' else None,
        bargroupgap=0 if gwp_visualization != 'bands' else None,
    )

    if show_logos and 'A__Manufacturer' in df_sorted.columns:
        try:
            mapping = _get_manufacturer_logo_mapping()
            def _norm(s: str) -> str:
                return re.sub(r"\s+", " ", str(s).strip()).lower()
            product_to_manu = {}
            if 'A__ProductName' in df_sorted.columns:
                product_to_manu = dict(zip(df_sorted[y_axis_col], df_sorted['A__Manufacturer']))
            all_vals = df_sorted[value_col].dropna()
            x_min = max(0, all_vals.min() - 50) if len(all_vals) else 0
            x_logo = x_min - 10
            for y_label, manu in product_to_manu.items():
                if not manu:
                    continue
                logo_meta = mapping.get(_norm(manu))
                if not logo_meta:
                    continue
                logo_path = logo_meta.get('logo_path')
                logo_img = fn202_create_logo_image(logo_path, size=(22, 22)) if logo_path else None
                if not logo_img:
                    continue
                fig.add_layout_image(dict(
                    source=logo_img, xref="x", yref="y",
                    x=x_logo, y=y_label, xanchor="right", yanchor="middle",
                    sizex=20, sizey=20, sizing="contain", opacity=1.0, layer="above",
                ))
        except Exception as e:
            print(f"Logo overlay failed: {e}")

    return fig


def fn213_normalize_en206_class(value) -> str:
    """Normalize EN 206 resistance class (e.g. 'C25/30', 'c 20/25') → 'C25/30' or 'Unspecified'."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "Unspecified"
        s = str(value).strip()
        if not s or s in ("-", "nan") or s.lower() == "nan":
            return "Unspecified"
        m = re.search(r'(C\s*\d{1,2}\s*/\s*\d{1,2})', s, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper().replace(" ", "")
    except Exception:
        pass
    return "Unspecified"


def fn214_plot_horizontal_bar_custom(df, x_col, y_col, settings):
    """Legacy horizontal bar chart using Plotly Express."""
    fig = px.bar(
        df, x=x_col, y=y_col, orientation='h', text_auto=True,
        color_discrete_sequence=[settings["bar_color"]] if settings["bar_color"] else px.colors.qualitative.Plotly,
    )
    fig.update_layout(
        title=settings["title"], width=settings["width"], height=settings["height"],
        font=dict(family=settings["font_family"], size=settings["font_size"]),
        title_font_size=settings["title_font_size"],
        xaxis_title=settings["xaxis_title"] or x_col,
        yaxis_title=settings["yaxis_title"] or y_col,
        margin=settings["margin"],
    )
    fig.update_traces(opacity=settings["bar_opacity"])
    return fig


def fn215_add_watermark(fig, image, position='bottom-right', opacity=0.2, sizex=0.2, sizey=0.2):
    """Overlay a watermark image on a Plotly figure."""
    position_map = {
        'bottom-right': ('paper', 'paper', 1, 0, 'right', 'bottom'),
        'bottom-left':  ('paper', 'paper', 0, 0, 'left',  'bottom'),
        'top-right':    ('paper', 'paper', 1, 1, 'right', 'top'),
        'top-left':     ('paper', 'paper', 0, 1, 'left',  'top'),
    }
    xref, yref, x, y, xanchor, yanchor = position_map.get(position, position_map['bottom-right'])
    fig.add_layout_image(dict(
        source=image, xref=xref, yref=yref, x=x, y=y,
        sizex=sizex, sizey=sizey, xanchor=xanchor, yanchor=yanchor,
        opacity=opacity, layer="above",
    ))
    return fig


# ════════════════════════════════════════════════════════════════════════════
# fn227 — Strip chart (jittered dot plot, PDF style)
# ════════════════════════════════════════════════════════════════════════════

def fn227_plot_strip_chart(
    df,
    group_col: str,
    value_col: str,
    color_col: str | None = None,
    settings: dict | None = None,
    jitter_width: float = 0.35,
    seed: int = 42,
    color_map: dict | None = None,
    show_legend: bool = True,
) -> go.Figure:
    """
    Jittered dot-plot (strip chart) with one vertical column per group.

    Replicates the style from Grazieschi et al. (2021) where each insulation
    material type occupies one x-position and individual EPD points are scattered
    around it with horizontal jitter to avoid over-plotting.

    Parameters
    ----------
    group_col  : categorical column → one column on the X axis per unique value
    value_col  : numeric column plotted on the Y axis
    color_col  : optional categorical column used to colour/legend the dots
                 (when None, each group gets its own colour)
    jitter_width : total horizontal spread (±) around each group position
    seed         : RNG seed for reproducible jitter
    """
    import numpy as _np

    settings = settings or {}

    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=[value_col])

    if df.empty:
        return go.Figure()

    groups = _sorted_unique_categories(df[group_col].dropna().unique())
    group_index = {g: i for i, g in enumerate(groups)}
    rng = _np.random.default_rng(seed)

    _palette = (
        px.colors.qualitative.D3
        + px.colors.qualitative.Set2
        + px.colors.qualitative.Set1
        + px.colors.qualitative.Light24
    )

    fig = go.Figure()

    has_color = (
        color_col
        and color_col in df.columns
        and color_col != group_col
    )

    _y_title = settings.get("yaxis_title", value_col)

    def _build_hover(texts):
        return (
            "<b>%{text}</b><br>"
            + f"{_y_title}: %{{y:.3f}}"
            + "<extra></extra>"
        )

    cmap = dict(color_map or {})

    if has_color:
        color_groups = _sorted_unique_categories(
            df[color_col].fillna("(blank)").astype(str).unique()
        )
        for ci, cg in enumerate(color_groups):
            mask = df[color_col].fillna("(blank)").astype(str) == str(cg)
            sub = df[mask]
            if sub.empty:
                continue
            color = cmap.get(str(cg), _palette[ci % len(_palette)])
            x_pos, y_vals, texts = [], [], []
            for grp in groups:
                grp_rows = sub[sub[group_col] == grp]
                if grp_rows.empty:
                    continue
                n = len(grp_rows)
                jitter = rng.uniform(-jitter_width / 2, jitter_width / 2, n)
                x_pos.extend(float(group_index[grp] + j) for j in jitter)
                y_vals.extend(grp_rows[value_col].tolist())
                if "A__ProductName" in grp_rows.columns:
                    texts.extend(grp_rows["A__ProductName"].fillna(str(grp)).tolist())
                else:
                    texts.extend([str(grp)] * n)

            fig.add_trace(go.Scatter(
                x=x_pos, y=y_vals,
                mode="markers",
                name=str(cg),
                marker=dict(
                    symbol="circle",
                    size=8,
                    color=color,
                    opacity=0.78,
                    line=dict(width=1, color="white"),
                ),
                text=texts,
                hovertemplate=_build_hover(texts),
            ))
    else:
        # Colour each group independently (same style as the reference chart)
        for gi, grp in enumerate(groups):
            sub = df[df[group_col] == grp]
            if sub.empty:
                continue
            color = cmap.get(str(grp), _palette[gi % len(_palette)])
            n = len(sub)
            jitter = rng.uniform(-jitter_width / 2, jitter_width / 2, n)
            x_pos = [float(group_index[grp] + j) for j in jitter]
            if "A__ProductName" in sub.columns:
                texts = sub["A__ProductName"].fillna(str(grp)).tolist()
            else:
                texts = [str(grp)] * n

            fig.add_trace(go.Scatter(
                x=x_pos, y=sub[value_col].tolist(),
                mode="markers",
                name=str(grp),
                marker=dict(symbol="circle", size=8, color=color, opacity=0.78),
                text=texts,
                hovertemplate=_build_hover(texts),
            ))

    # Zero reference line
    fig.add_hline(y=0, line_width=1, line_color="rgba(0,0,0,0.25)", line_dash="solid")

    typo = fn233_chart_typo_from_dims()
    # Prefer explicit settings when present; else theme defaults from fn233.
    family = (settings.get("font_family") if settings else None) or typo["family"]
    fsize = int((settings.get("font_size") if settings else None) or typo["size"])
    tick_angle = typo["tick_angle"]
    if settings and settings.get("tick_label_angle") is not None:
        tick_angle = int(settings["tick_label_angle"])
    wrap_w = int((settings.get("tick_wrap_chars") if settings else None) or typo["wrap_chars"])
    max_lines = settings.get("tick_max_lines") if settings else None
    if max_lines is not None:
        max_lines = int(max_lines)
    legend_size = int((settings.get("legend_font_size") if settings else None) or typo["legend_size"])
    show_leg = bool(show_legend if settings.get("show_legend") is None else settings.get("show_legend", show_legend)) \
        if settings else bool(show_legend)

    tick_texts = [
        fn234_wrap_tick_label(g, wrap_w, max_lines=max_lines) for g in groups
    ]
    n_lines = max((t.count("<br>") + 1 for t in tick_texts), default=1)
    # Horizontal ticks: room for wrapped lines; rotated ticks keep a larger base.
    if settings and settings.get("margin") is not None:
        default_margin = settings["margin"]
    elif tick_angle == 0:
        default_margin = dict(l=20, r=24 if not show_leg else 160, t=30, b=max(72, 28 + n_lines * 16))
    else:
        default_margin = dict(l=20, r=24 if not show_leg else 160, t=30, b=170)

    fig.update_layout(
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(len(groups))),
            ticktext=tick_texts,
            tickangle=tick_angle,
            title=settings.get("xaxis_title", group_col) if settings else group_col,
            title_font=dict(family=family, size=typo["axis_title_size"]),
            tickfont=dict(family=family, size=typo["tick_size"]),
            showgrid=False,
            range=[-0.7, len(groups) - 0.3],
            automargin=True,
        ),
        yaxis=dict(
            title=_y_title,
            title_font=dict(family=family, size=typo["axis_title_size"]),
            tickfont=dict(family=family, size=typo["tick_size"]),
            zeroline=False,
            showgrid=True,
            gridcolor="rgba(0,0,0,0.08)",
        ),
        height=settings.get("height", 560) if settings else 560,
        margin=default_margin,
        font=dict(family=family, size=fsize),
        showlegend=show_leg,
        legend=dict(
            title=(settings.get("legend_title", "") if settings else ""),
            x=1.02, y=1, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1,
            font=dict(family=family, size=legend_size),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    return fig


# ════════════════════════════════════════════════════════════════════════════
# fn228 — EPD programme distribution mini treemap
# ════════════════════════════════════════════════════════════════════════════

# Defaults; overridden by theme.json → catalogue.charts.epd_programme_colors
_EPD_PROGRAMME_PALETTE: dict[str, str] = {
    "epditaly":   "#009040",  # EPD Italy logo green
    "environdec": "#186050",  # International EPD System teal
    "ibu":        "#2e7d32",
    "dap":        "#e65100",
    "inies":      "#00695c",
    "breeam":     "#c62828",
    "unknown":    "#90a4ae",
}

_EPD_PROGRAMME_LABELS: dict[str, str] = {
    "epditaly":   "EPD Italy",
    "ibu":        "IBU",
    "environdec": "Environdec",
    "dap":        "DAP Costruzioni",
    "inies":      "INIES",
    "breeam":     "BREEAM",
}


def _epd_programme_palette() -> dict[str, str]:
    """Theme-backed EPD programme colours (logos live under ``03_img/epd_*.png``)."""
    out = dict(_EPD_PROGRAMME_PALETTE)
    try:
        from .lib_ui import fn341_get_charts_dimensions
        themed = fn341_get_charts_dimensions().get("epd_programme_colors") or {}
        for k, v in themed.items():
            if isinstance(v, str) and v.startswith("#"):
                out[str(k).lower()] = v
    except Exception:
        pass
    return out


def fn228_epd_programme_mini_bar(df: pd.DataFrame) -> "go.Figure | None":
    """
    Compact treemap of EPD programme share in *df* (sidebar-sized).

    A stacked bar hid minority programmes when one operator dominated; the
    treemap keeps every programme readable by area. Returns None when the
    column is absent or empty. Uses ``E__EPD_Programme``.
    Brand greens for EPD Italy / Environdec come from theme.json (logo colours).
    """
    if "E__EPD_Programme" not in df.columns:
        return None

    raw = (
        df["E__EPD_Programme"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    raw = raw.replace({"": "Unknown", "nan": "Unknown", "None": "Unknown", "-": "Unknown"})
    counts = raw.value_counts()
    if counts.empty or counts.sum() == 0:
        return None

    palette = _epd_programme_palette()
    typo = fn233_chart_typo_from_dims()
    rows: list[dict] = []
    color_map: dict[str, str] = {}
    for prog, cnt in counts.items():
        key = str(prog).lower()
        display = _EPD_PROGRAMME_LABELS.get(key, str(prog))
        color_map[display] = palette.get(key, palette.get("unknown", "#90a4ae"))
        rows.append({
            "programme": display,
            "count": int(cnt),
        })
    tm_df = pd.DataFrame(rows)

    fig = px.treemap(
        tm_df,
        path=["programme"],
        values="count",
        color="programme",
        color_discrete_map=color_map,
    )
    fig.update_traces(
        textinfo="label+value",
        textfont=dict(family=typo["family"], size=typo["size"]),
        marker=dict(line=dict(width=1, color="#ffffff")),
        hovertemplate="<b>%{label}</b><br>n = %{value}<extra></extra>",
    )
    fig.update_layout(
        height=180,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=typo["family"], size=typo["size"]),
    )
    return fig


def fn239_build_echarts_scatter_popup_html(
    ec_option: dict,
    products_payload: dict[str, str],
    *,
    height: int = 520,
    tooltip_formatter_js: str | None = None,
) -> str:
    """Build ECharts scatter iframe HTML with JS catalogue right-panel detail view."""
    from .lib_html import CHARTS_SCATTER_EC_POPUP_HTML, read_iframe_component

    template = read_iframe_component(CHARTS_SCATTER_EC_POPUP_HTML)
    ec_json = _json.dumps(ec_option, ensure_ascii=False, default=str)
    if tooltip_formatter_js and '"TOOLTIP_FN"' in ec_json:
        ec_json = ec_json.replace('"TOOLTIP_FN"', tooltip_formatter_js)
    products_json = products_payload.get("products_json") or "[]"
    gwp_ranges_json = products_payload.get("gwp_ranges_json") or "{}"
    rc_ranges_json = products_payload.get("rc_ranges_json") or "{}"
    stella_json = _json.dumps(products_payload.get("stella_img_uri") or "", ensure_ascii=False)
    js2_fields_json = products_payload.get("js2_fields_json") or "{}"
    field_vis_json = products_payload.get("field_vis_json") or "{}"
    injection = (
        f"<script>"
        f"window.__PRODUCTS__={products_json};"
        f"window.__GWP_RANGES__={gwp_ranges_json};"
        f"window.__RC_RANGES__={rc_ranges_json};"
        f"window.__STELLA_IMG__={stella_json};"
        f"window.__JS2_FIELDS__={js2_fields_json};"
        f"window.__FIELD_VIS__={field_vis_json};"
        f"window.__ECHARTS_OPTION__={ec_json};"
        f"window.__CHART_HEIGHT__={int(height)};"
        f"</script>\n"
    )
    return template.replace("</head>", injection + "</head>", 1)


def fn240_build_dev_missmatrix_html(payload: dict, *, height: int = 780) -> str:
    """Build Developer missing-data ECharts heatmap iframe HTML."""
    from .lib_html import DEV_MISSMATRIX_HTML, read_iframe_component

    template = read_iframe_component(DEV_MISSMATRIX_HTML)
    payload_json = _json.dumps(payload, ensure_ascii=False, default=str)
    injection = (
        f"<script>"
        f"window.__MISSMATRIX__={payload_json};"
        f"window.__IFRAME_HEIGHT__={int(height)};"
        f"</script>\n"
    )
    return template.replace("</head>", injection + "</head>", 1)


def fn630_build_classification_crosswalk_html(counts: dict[str, int] | None = None) -> str:
    """Build Developer → Classification Crosswalk iframe HTML.

    The crosswalk mapping lives in the template; ``counts`` (product type → rows)
    replaces its snapshot counts and surfaces product types not yet mapped.
    """
    from .lib_html import CLASSIFICATION_CROSSWALK_HTML, read_text

    if not CLASSIFICATION_CROSSWALK_HTML.exists():
        return f"<p>HTML component not found: {CLASSIFICATION_CROSSWALK_HTML.name}</p>"
    template = read_text(CLASSIFICATION_CROSSWALK_HTML)
    if not counts:
        return template
    counts_json = _json.dumps(
        {str(k): int(v) for k, v in counts.items()}, ensure_ascii=False
    ).replace("</", "<\\/")
    injection = f"<script>window.__CROSSWALK_COUNTS__={counts_json};</script>\n"
    return template.replace("</head>", injection + "</head>", 1)

# ── VOC bodies & certifications (Developer → one page, fn631) ────────────────
# The catalogue (aux_11__voc_certifications.json) says which organisation stands
# behind each VOC claim; the parquet says which claims the library actually
# holds and which body was recorded against them. This pairs the two so the
# page can show the agreed vocabulary and the data in one table.

_VOC_PLACEHOLDERS = frozenset({
    "", "-", "nan", "none", "<na>", "n/a", "na", "n/r", "nr", "*",
})


def _voc_norm(value) -> str:
    """Lowercase, punctuation to spaces, known spellings folded (matches the data)."""
    import unicodedata
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    t = unicodedata.normalize("NFKC", str(value))
    t = t.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    # "Greengaurd" is the spelling 46 rows of the parquet use.
    t = t.lower().replace("greengaurd", "greenguard")
    t = re.sub(r"[^a-z0-9+]+", " ", t)
    t = " ".join(t.split())
    # "EMICODE EC1 Plus" and "EMICODE EC1PLUS" are the same claim; fold the
    # spaced spelling so the longest-match lookup cannot settle on plain EC1.
    return re.sub(r"\bec1\s*(?:plus|\+)", "ec1plus", t)


def _voc_status_phrases() -> set[str]:
    """Normalised spellings of the catalogue's status tier (n/a, n/r)."""
    from .lib_revalu_map import voc_cert_tiers

    out: set[str] = set()
    for tier in voc_cert_tiers():
        if str(tier.get("id") or "") != "status":
            continue
        for entry in tier.get("entries") or []:
            for phrase in [entry.get("label"), *(entry.get("aliases") or [])]:
                key = _voc_norm(phrase)
                if key:
                    out.add(key)
    return out


def _voc_is_placeholder(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if str(value).strip().lower() in _VOC_PLACEHOLDERS:
        return True
    # "n/a (not available)" and "n/r (not relevant)" are the catalogue's own
    # status labels, not claims — they belong in no body's row.
    return _voc_norm(value) in _voc_status_phrases()


def _voc_catalog_index() -> list[tuple[str, dict]]:
    """(normalised label/alias, entry) longest first, so EC1PLUS beats EC1."""
    from .lib_revalu_map import voc_cert_entries

    out: list[tuple[str, dict]] = []
    for entry in voc_cert_entries():
        if not str(entry.get("body") or "").strip():
            continue  # the status tier (n/a, n/r) names no body
        for phrase in [entry.get("label"), *(entry.get("aliases") or [])]:
            key = _voc_norm(phrase)
            if key:
                out.append((key, entry))
    out.sort(key=lambda pair: len(pair[0]), reverse=True)
    return out


_VOC_PHRASE_RE: dict = {}


def _voc_phrase_re(key: str):
    """Whole-phrase matcher for a catalogue label or alias.

    Plain substring matching misfiled claims: the alias "French VOC A" sits
    inside "French VOC Attestation (A+)", which is the A+ label, not A.
    """
    rx = _VOC_PHRASE_RE.get(key)
    if rx is None:
        rx = re.compile("(?<![a-z0-9+])" + re.escape(key) + "(?![a-z0-9+])")
        _VOC_PHRASE_RE[key] = rx
    return rx


def _voc_resolve(value, index=None):
    """The catalogue entry a stored VOC claim names, or None."""
    if _voc_is_placeholder(value):
        return None
    text = _voc_norm(value)
    if not text:
        return None
    for key, entry in (_voc_catalog_index() if index is None else index):
        if _voc_phrase_re(key).search(text):
            return entry
    return None


def fn631_voc_rating_alignment() -> dict:
    """How each VOC claim lines up with LEED v4.1, WELL v2 and CAM 2025.

    The file is loaded (and memoized) by lib_revalu_map, which also serves the
    Add/Edit form — one reader, so the page and the form cannot disagree.
    """
    from .lib_revalu_map import fn_load_voc_rating_alignment

    return fn_load_voc_rating_alignment()


def fn631_voc_bodies_payload(df: "pd.DataFrame | None" = None) -> dict:
    """One row per catalogue claim, plus a row per claim the data holds alone.

    Each row carries the issuing body, its role, the catalogue tier, how many
    products in the library carry the claim, the report types recorded against
    it and the bodies actually written into ``VO__VOC_Body``.
    """
    index = _voc_catalog_index()
    by_id: dict[str, dict] = {}
    rows: list[dict] = []
    for _key, entry in index:
        if entry["id"] in by_id:
            continue
        by_id[entry["id"]] = entry
        rows.append({
            "id": entry["id"],
            "body": entry.get("body", ""),
            "role": entry.get("body_role", ""),
            "cert": entry.get("label", ""),
            "tier": entry.get("tier_id", ""),
            "tier_label": entry.get("tier", ""),
            "description": entry.get("description", ""),
            "aliases": list(entry.get("aliases") or []),
            "products": 0,
            "report_types": [],
            "bodies_seen": [],
            "body_counts": {},
            "spellings": [],
            "source": "catalogue",
        })
    row_by_id = {e["id"]: r for e, r in zip(by_id.values(), rows)}

    unmapped: dict[str, dict] = {}
    if df is not None and not df.empty and "VO__VOC_Cert" in df.columns:
        cols = ["VO__VOC_Cert", "VO__VOC_Body", "VO__ReportType"]
        frame = df[[c for c in cols if c in df.columns]].copy()
        for _i, rec in frame.iterrows():
            raw = rec.get("VO__VOC_Cert")
            if _voc_is_placeholder(raw):
                continue
            hit = _voc_resolve(raw, index)
            if hit is not None:
                target = row_by_id[hit["id"]]
            else:
                target = unmapped.setdefault(text, {
                    "body": "", "role": "Not in catalogue",
                    "cert": str(raw).strip(), "tier": "unmapped",
                    "tier_label": "Not in the catalogue", "description": "",
                    "id": "", "aliases": [], "products": 0, "report_types": [],
                    "bodies_seen": [], "body_counts": {}, "spellings": [],
                    "source": "data",
                })
            target["products"] += 1
            spelling = str(raw).strip()
            if spelling and spelling not in target["spellings"]:
                target["spellings"].append(spelling)
            rep = rec.get("VO__ReportType")
            if not _voc_is_placeholder(rep) and str(rep).strip() not in target["report_types"]:
                target["report_types"].append(str(rep).strip())
            seen = rec.get("VO__VOC_Body")
            # VO__VOC_Body also holds free prose on some rows — keep it short.
            if not _voc_is_placeholder(seen) and len(str(seen).strip()) <= 60:
                name = str(seen).strip()
                if name not in target["bodies_seen"]:
                    target["bodies_seen"].append(name)
                # Per-body tally, so grouping the page by certification can show
                # which laboratory stands behind how many of the products.
                target["body_counts"][name] = target["body_counts"].get(name, 0) + 1

    rows.extend(unmapped.values())
    for row in rows:
        row["report_types"].sort()
        row["bodies_seen"].sort()
        row["spellings"].sort()

    align = fn631_voc_rating_alignment()
    by_cert = align.get("alignment") or {}
    frameworks = align.get("frameworks") or []
    for row in rows:
        # A claim the catalogue does not know has no reading against any scheme:
        # it has to be mapped (or the data fixed) before it can be judged.
        hit = by_cert.get(row.get("id") or "", {})
        row["align"] = {
            fw["id"]: list(hit.get(fw["id"]) or (["unknown", ""] if row["source"] == "data" else ["no", ""]))
            for fw in frameworks
        }

    total = int(len(df)) if df is not None else 0
    with_claim = sum(r["products"] for r in rows)
    return {
        "frameworks": frameworks,
        "legend": align.get("_status_legend") or {},
        "sources": align.get("_sources") or {},
        "caveat": align.get("_caveat") or "",
        "rows": rows,
        "stats": {
            "bodies": len({r["body"] for r in rows if r["body"]}),
            "certs": len(rows),
            "in_use": sum(1 for r in rows if r["products"]),
            "unmapped": sum(1 for r in rows if r["source"] == "data"),
            "products_with_claim": with_claim,
            "products_total": total,
        },
    }


def fn631_build_voc_bodies_certs_html(payload: dict | None = None) -> str:
    """Build Developer → VOC Bodies & Certifications iframe HTML."""
    from .lib_html import VOC_BODIES_CERTS_HTML, read_iframe_component

    if not VOC_BODIES_CERTS_HTML.exists():
        return f"<p>HTML component not found: {VOC_BODIES_CERTS_HTML.name}</p>"
    # read_iframe_component (not read_text): it prepends _tokens.css, so the page
    # uses the app's own fonts and palette rather than its own.
    template = read_iframe_component(VOC_BODIES_CERTS_HTML)
    if not payload:
        return template
    data = _json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    injection = f"<script>window.__VOC_BODIES__={data};</script>\n"
    return template.replace("</head>", injection + "</head>", 1)
