"""
libs/lib_ui_catalogues.py — Catalogue view settings (by UI surface)
=================================================================
Customise layout per surface below. Shared JSON typography/chrome:
``theme.json`` → ``catalogue`` (merged at import via ``apply_catalogue_layout_globals``).

Surfaces
--------
* **Streamlit** — retired (the native “Grid & table” view and its helpers were removed from ``pages/2_Catalogue.py`` on 2026-10-03)
* **JavaScript** — tab “Cards” (``02_html/catalogue_component_js2.html`` via ``fn336`` + ``JS2_LIST_*``)
* **old_JS** — legacy ``catalogue_component.html`` flip-card (still rendered by ``fn336`` when no component path is given; the hidden Catalogue tab that used it was removed)
* **ECOportal** — ``pages/9_ECOportal.py`` mapping-browser EPD catalogue list
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# SHARED — paths & layout JSON (all MatLib catalogue UIs)
# ══════════════════════════════════════════════════════════════════════════════
from .lib_html import CATALOGUE_COMPONENT_PATH

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE_LAYOUT_FILENAME = "theme.json"

# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT CATALOGUE — tab “Grid & table” (fn329 cards, st.dataframe list)
# ══════════════════════════════════════════════════════════════════════════════
STREAMLIT_CATALOGUE_LIST_COLUMN_WIDTHS: dict[str, str] = {
    "Manufacturer": "medium",
    "Product Name": "large",
    "Type": "medium",
    "GWP A1–A3": "small",
    "Unit": "small",
    "Thickness": "small",
    "Density": "small",
    "VOC": "medium",
    "VOC cert": "small",
    "EPD": "small",
    "CAM": "small",
    "EPD URL": "small",
}

# ══════════════════════════════════════════════════════════════════════════════
# JAVASCRIPT CATALOGUE — flip-card grid (catalogue_component.html · fn336)
# ══════════════════════════════════════════════════════════════════════════════
JS_CATALOGUE_FIELD_MAP: dict[str, str] = {
    "0__EETRA_ID": "eetraId",
    "A__ProductName": "name",
    "A__ProductDescription": "productDescription",
    "A__Manufacturer": "manufacturer",
    "D__ProductType_ENG": "productType",
    "D__MaterialType_ENG": "materialType",
    "D__IncludedProducts": "includedProducts",
    "U__Img_URL": "imageUrl",
    "U__ProductInfo_URL": "productUrl",
    "G__GWP_A1A3": "gwp",
    "G__GWP_FU": "gwpUnit",
    "G__GWP_A1A3_m2": "gwpM2",
    "G__GWP_A1A3_m3": "gwpM3",
    "G__GWP_A1A3_kg": "gwpKg",
    "G__GWP_A1A3_m2R1": "gwpM2R1",
    "E__EPD_RegNumber": "epdNumber",
    "E__EPD_DecNumber": "epdDeclaredNumber",
    "E__EPD_URL": "epdUrl",
    "E__ManuCountry": "country",
    "E__ManuPlant": "plant",
    "P__Thick_mm": "thickness",
    "P__Mass_kgm3": "density",
    "P__Mass_kgm2": "densityKgm2",
    "P__FireRating": "fireRating",
    "P__L_WmK": "conductivity",
    "E__L_WmK": "conductivityAlt",
    "D__Content": "content",
    "S__Comments": "comments",
    "R__Rec_Reco_ByProd_%": "recyclingRate",
    "R__Rec_Reco_ByProd_URL": "recyclingUrl",
    "R__Rec_Cert_No": "recCertNo",
    "R__Rec_Cert_Scheme": "recCertScheme",
    "R__Rec_Cert_Expiry": "recCertExpiry",
    "R__Rec_Cert_Plant": "recCertPlant",
    "VV__DOP": "dopUrl",
    "U__TechDetails_URL": "techDetailsUrl",
    "G__GWP_A4": "a4",
    "G__GWP_A5": "a5",
    "G__GWP_C4": "c4",
    "G__GWP_D": "d",
    "U__DeclaredUnit": "declaredUnit",
    "U__Lifespan_yr": "lifespanYears",
    "D__Strength": "strength",
    "D__Additions": "additions",
    "E__Certifications": "certifications",
    "E__Certifications_URL": "certificationsUrl",
    "E__EPD_Programme": "epdProgramme",
    "VV__MSDS__URL": "msdsUrl",
    "VO__VOC_Body": "vocRaw",
    "VO__Product_Category": "vocCategory",
    "VO__VOC_Cert": "vocCertRaw",
    "U__VOC_URL": "vocUrlPrimary",
    "VO__VOC_URL": "vocUrlAlt",
    "VV__CAM_Compliance": "camCompliance",
    # list prices — derived columns added by libs/lib_prices.py fn507
    "PR__Price_Display": "listPrice",
    "PR__Listino_Edition": "listPriceEdition",
    "PR__Listino_URL": "listPriceUrl",
}
JS_CATALOGUE_NUMERIC_FIELDS: frozenset[str] = frozenset(
    {"gwp", "a1a3", "a4", "a5", "c4", "d", "lifespanYears", "conductivity"}
)
JS_CATALOGUE_GRID_SIZE_PRESETS: dict[str, dict[str, int]] = {
    "S": {"cols_delta": 1, "image_height_px": 80},
    "M": {"cols_delta": 0, "image_height_px": 100},
    "L": {"cols_delta": -1, "image_height_px": 120},
    "XL": {"cols_delta": -3, "image_height_px": 72},  # JS grid: 3 columns (COLS_BY_SIZE)
}
from .lib_tokens import token as _design_token, theme_section as _theme_section

# Populated from theme.json → catalogue.js2.theme on init (see apply_catalogue_layout_globals).
JS_CATALOGUE_THEME: dict[str, str] = {}

# Populated from theme.json → catalogue.js2.card_name_divider on init (ditto).
CATALOGUE_JS2_CARD_NAME_DIVIDER: dict[str, dict] = {}

# ══════════════════════════════════════════════════════════════════════════════
# JS2 CATALOGUE — product detail panel (catalogue_component_js2.html · card click)
# ══════════════════════════════════════════════════════════════════════════════
# Reversible presentation when a grid/list card is clicked:
#   "right_panel"  — fixed right column (default; same pattern as ECOportal JS)
#   "center_modal" — centred overlay popup (legacy)
JS2_DETAIL_VIEW_MODE = "right_panel"

# ══════════════════════════════════════════════════════════════════════════════
# JS2 CATALOGUE — list table (catalogue_component_js2.html · List view · Cards tab)
# ══════════════════════════════════════════════════════════════════════════════
JS2_LIST_VIEW_COLUMNS: tuple[str, ...] = (
    "image",
    "manufacturer",
    "product_type",
    "material_type",
    "product",
    "gwp_m2",
    "gwp_m3",
    "gwp_kg",
    "recycled_content",
    "thickness",
    "density",
    "epd_number",
    "voc",
    "cam",
)
# Widths per column:
#   "90px"        fixed — the column is exactly this wide.
#   "15%"         share of the table width — grows and shrinks with the window.
#   "min:110px"   flexible — takes whatever space is left over, never narrower
#                 than the given width.
JS2_LIST_VIEW_COL_WIDTHS: dict[str, str] = {
    "image": "70px",
    "manufacturer": "15%",
    "product_type": "min:100px",
    "material_type": "min:110px",
    "product": "25%",
    "gwp_m2": "90px",
    "gwp_m3": "90px",
    "gwp_kg": "90px",
    "recycled_content": "95px",
    "thickness": "90px",
    "density": "90px",
    "epd_number": "120px",
    "voc": "72px",
    "cam": "52px",
}
JS2_LIST_COLUMN_LABELS: dict[str, str] = {
    "image": "",
    "manufacturer": "Manufacturer",
    "product": "Product",
    "gwp": "GWP A1–A3",
    "gwp_m2": "GWP/m2",
    "gwp_m3": "GWP/m3",
    "gwp_kg": "GWP/kg",
    "recycled_content": "Rec. Content",
    "product_type": "Product type",
    "material_type": "Material type",
    "thickness": "Thickness",
    "density": "Vol. Density",
    "epd_number": "EPD number",
    "voc": "VOC",
    "cam": "CAM",
}
JS2_LIST_OPTIONAL_COLUMNS: frozenset[str] = frozenset({"density"})

# ══════════════════════════════════════════════════════════════════════════════
# ECOPORTAL CATALOGUE — EPD list (pages/9_ECOportal.py)
# ══════════════════════════════════════════════════════════════════════════════
ECOPORTAL_CATALOGUE_LIST_COLUMN_WIDTHS: dict[str, str] = {
    "Name": "large",
    "Owner": "medium",
    "Country": "small",
    "Year": "small",
    "Valid until": "small",
    "Product type": "medium",
    "Material type": "medium",
    "Confidence": "small",
    "EPD Numbers": "medium",
    "In MatLib": "small",
    "Classification": "medium",
    "UUID": "medium",
}

# Backward-compatible aliases
CATALOGUE_FLIPCARD_FIELD_MAP = JS_CATALOGUE_FIELD_MAP
CATALOGUE_FLIPCARD_NUMERIC_FIELDS = JS_CATALOGUE_NUMERIC_FIELDS
CATALOGUE_LIST_VIEW_COLUMNS = JS2_LIST_VIEW_COLUMNS
CATALOGUE_LIST_VIEW_COL_WIDTHS = JS2_LIST_VIEW_COL_WIDTHS
CATALOGUE_GRID_SIZE_PRESETS = JS_CATALOGUE_GRID_SIZE_PRESETS
CATALOGUE_JS_THEME = JS_CATALOGUE_THEME

# ── Streamlit fn329 card DOM selectors (structural — rarely changed) ────────────
_CATALOGUE_CARD_SURFACE_CLASS = "eetra-cat-card-surface"
# Streamlit >=1.59 dropped the `.main` class from the main area in favour of
# [data-testid="stMain"]. Every rule scoped through `.main` silently stopped
# matching — which is why the catalogue cards had lost their border, radius,
# background, hover shadow and image fit. Scope through the testid instead.
_MAIN_AREA = "div[data-testid=stAppViewContainer] [data-testid=stMain]"
_CATALOGUE_CARD_BLOCK = (
    f"{_MAIN_AREA} "
    f"div.{_CATALOGUE_CARD_SURFACE_CLASS}"
)
_CATALOGUE_CARD_COLUMN = (
    f"{_MAIN_AREA} "
    f"div[data-testid=stColumn]:has(div.{_CATALOGUE_CARD_SURFACE_CLASS})"
)
CATALOGUE_CARD_SURFACE_CLASS = _CATALOGUE_CARD_SURFACE_CLASS

CATALOGUE_OBJECT_FIT_ALLOWED = frozenset({"contain", "cover", "fill", "scale-down", "none"})
_CATALOGUE_OBJECT_FIT_ALLOWED = CATALOGUE_OBJECT_FIT_ALLOWED


# ══════════════════════════════════════════════════════════════════════════════
# Layout JSON → module-level CATALOGUE_* / _GWP_* / CHARTS_*
# ══════════════════════════════════════════════════════════════════════════════


def _catalogue_deep_merge(base: dict, overlay: dict) -> dict:
    if not overlay:
        return base
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _catalogue_deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _catalogue_legacy_view_nested(legacy: dict) -> dict:
    if not legacy:
        return {}
    out: dict = {}
    g = out.setdefault("grid", {})
    if "row_spacing_px" in legacy:
        g["row_spacing_px"] = legacy["row_spacing_px"]
    if "gwp_to_data_spacing_px" in legacy:
        g["gwp_to_data_spacing_px"] = legacy["gwp_to_data_spacing_px"]
    if "title_line_height" in legacy:
        out.setdefault("streamlit", {}).setdefault("typography", {})[
            "title_line_height"
        ] = legacy["title_line_height"]
    return out


def load_merged_catalogue_layout(ui_config: dict | None = None) -> dict:
    """Merge legacy ``catalogue_view`` (ui config) under ``theme.json`` → ``catalogue``."""
    file_data: dict = {}
    path = _PROJECT_ROOT / CATALOGUE_LAYOUT_FILENAME
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        file_data = raw.get("catalogue") if isinstance(raw.get("catalogue"), dict) else raw
    legacy = _catalogue_legacy_view_nested((ui_config or {}).get("catalogue_view") or {})
    return _catalogue_deep_merge(legacy, file_data)


def charts_dimensions_from_layout(m: dict) -> dict:
    """Parse ``charts`` section from merged layout, including font settings."""
    ch = m.get("charts") or {}

    def _ii(key, d, default=0):
        try:
            v = d.get(key, default)
            return int(float(str(v).strip())) if str(v).strip() else int(default)
        except Exception:
            return int(default)

    def _ff(key, d, default):
        try:
            return float(str(d.get(key, default)).strip())
        except Exception:
            return float(default)

    def _ss(key, d, default=""):
        v = d.get(key, default)
        return str(v).strip() if v is not None else str(default).strip()

    _line = max(10, min(36, _ii("bar_chart_line_height_px", ch, 18)))
    _rows = max(30, min(250, _ii("bar_chart_max_rows", ch, 120)))
    _epd_colors = ch.get("epd_programme_colors") or {}
    _epd_logos = ch.get("epd_programme_logos") or {}
    if not isinstance(_epd_colors, dict):
        _epd_colors = {}
    if not isinstance(_epd_logos, dict):
        _epd_logos = {}
    return {
        # ── Dimensions ────────────────────────────────────────────────
        "box_height_px": max(200, min(2000, _ii("box_chart_height_px", ch, 580))),
        "bar_height_scale": max(0.3, min(2.0, _ff("bar_chart_height_scale", ch, 1.0))),
        "bar_line_height_px": _line,
        "bar_max_rows": _rows,
        "bar_max_height_px": _rows * _line,
        "correlation_plotly_height_px": max(
            200, min(2000, _ii("correlation_plotly_height_px", ch, 560))
        ),
        "correlation_altair_height_px": max(
            200, min(2000, _ii("correlation_altair_height_px", ch, 520))
        ),
        "correlation_fullscreen_plotly_height_px": max(
            400, min(2400, _ii("correlation_fullscreen_plotly_height_px", ch, 640))
        ),
        "correlation_fullscreen_altair_height_px": max(
            400, min(2400, _ii("correlation_fullscreen_altair_height_px", ch, 600))
        ),
        # ── Fonts (shared by Plotly / Altair / ECharts) ────────────────
        "chart_font_family":       _ss("font_family", ch, "Miranda Sans, Source Sans Pro, sans-serif"),
        "chart_font_size":         max(6, min(24, _ii("font_size",             ch, 11))),
        "chart_title_font_size":   max(8, min(36, _ii("title_font_size",       ch, 16))),
        "chart_axis_title_size":   max(8, min(24, _ii("axis_title_font_size",  ch, 12))),
        "chart_annotation_size":   max(6, min(18, _ii("annotation_font_size",  ch, 10))),
        "chart_small_font_size":   max(6, min(14, _ii("small_font_size",       ch,  9))),
        "chart_legend_font_size":  max(6, min(18, _ii("legend_font_size",      ch, 10))),
        "chart_tick_font_size":    max(6, min(18, _ii("tick_font_size",        ch, 10))),
        "chart_tick_label_angle":  max(-90, min(90, _ii("tick_label_angle_deg", ch, 0))),
        "chart_tick_wrap_chars":   max(8, min(40, _ii("tick_label_wrap_chars", ch, 16))),
        "strip_tick_wrap_chars":   max(4, min(24, _ii("strip_tick_wrap_chars", ch, 9))),
        "strip_tick_max_lines":    max(2, min(6, _ii("strip_tick_max_lines", ch, 4))),
        "epd_programme_colors": {
            str(k): str(v)
            for k, v in _epd_colors.items()
            if not str(k).startswith("_") and isinstance(v, str) and v.startswith("#")
        },
        "epd_programme_logos": {
            str(k): str(v)
            for k, v in _epd_logos.items()
            if not str(k).startswith("_") and str(v).strip()
        },
    }


def _sanitize_catalogue_material_band_value(val, default: str) -> str:
    raw = default if val is None else val
    s = str(raw).strip()
    if not s:
        s = str(default).strip()
    for ch in ";<>\"'{}\\":
        s = s.replace(ch, "")
    return s.strip() or str(default).strip()


def apply_catalogue_layout_globals(globs: dict, ui_config: dict | None) -> None:
    """Set ``CATALOGUE_*``, ``_GWP_*``, and ``CHARTS_*`` on *globs* from merged layout JSON."""
    m = load_merged_catalogue_layout(ui_config)
    flat_t = m.get("typography") or {}
    st_t = (m.get("streamlit") or {}).get("typography") or {}
    js2_t = (m.get("js2") or {}).get("typography") or {}
    leg_t = (m.get("legacy_js") or {}).get("typography") or {}
    g = m.get("grid") or {}
    cs = m.get("card_surface") or {}
    ib = m.get("image_band") or {}
    cc = m.get("card_chrome") or {}
    gp = m.get("gwp_pill") or {}
    sp = m.get("streamlit_page") or {}
    pc = m.get("page_controls") or {}

    def _i(key, d, default=0):
        try:
            v = d.get(key, default)
            return int(float(str(v).strip())) if str(v).strip() else int(default)
        except Exception:
            return int(default)

    def _f(key, d, default):
        try:
            return float(str(d.get(key, default)).strip())
        except Exception:
            return float(default)

    _st_font_size = _i(
        "body_font_size_px",
        st_t,
        _i("streamlit_body_font_size_px", flat_t, _i("font_size_px", flat_t, 13)),
    )
    _st_line_h = _f(
        "body_line_height",
        st_t,
        _f("streamlit_body_line_height", flat_t, _f("line_height", flat_t, 1.35)),
    )
    _st_title_lh = _f(
        "title_line_height",
        st_t,
        _f("streamlit_title_line_height", flat_t, _f("title_line_height", flat_t, 1.35)),
    )
    _st_gwp_lh = _f(
        "gwp_line_height",
        st_t,
        _f("streamlit_gwp_line_height", flat_t, _f("gwp_line_height", flat_t, 1.25)),
    )

    globs["CATALOGUE_FONT_SIZE_PX"] = _st_font_size
    globs["CATALOGUE_LINE_HEIGHT"] = _st_line_h
    globs["CATALOGUE_TITLE_LINE_HEIGHT"] = max(1.0, min(2.5, _st_title_lh))
    globs["CATALOGUE_GWP_LINE_HEIGHT"] = _st_gwp_lh

    globs["CATALOGUE_JS_TITLE_FONT_SIZE_PX"] = _i(
        "title_font_size_px",
        leg_t,
        _i("js_title_font_size_px", flat_t, 16),
    )
    globs["CATALOGUE_JS_BODY_FONT_SIZE_PX"] = _i(
        "body_font_size_px",
        leg_t,
        _i("js_body_font_size_px", flat_t, int(globs["CATALOGUE_FONT_SIZE_PX"])),
    )
    globs["CATALOGUE_JS_TITLE_LINE_HEIGHT"] = max(
        1.0,
        min(
            2.5,
            _f(
                "title_line_height",
                leg_t,
                _f("js_title_line_height", flat_t, float(globs["CATALOGUE_TITLE_LINE_HEIGHT"])),
            ),
        ),
    )
    globs["CATALOGUE_JS_BODY_LINE_HEIGHT"] = max(
        1.0,
        min(
            2.5,
            _f(
                "body_line_height",
                leg_t,
                _f("js_body_line_height", flat_t, float(globs["CATALOGUE_LINE_HEIGHT"])),
            ),
        ),
    )
    globs["CATALOGUE_JS_GWP_LINE_HEIGHT"] = max(
        1.0,
        min(
            2.5,
            _f(
                "gwp_line_height",
                leg_t,
                _f("js_gwp_line_height", flat_t, float(globs["CATALOGUE_GWP_LINE_HEIGHT"])),
            ),
        ),
    )

    _js2_i = lambda k, d: _i(k, js2_t, d)
    _js2_f = lambda k, d: _f(k, js2_t, d)
    globs["CATALOGUE_JS2_BASE_FONT_SIZE_PX"] = _js2_i("base_font_size_px", 13)
    globs["CATALOGUE_JS2_BASE_LINE_HEIGHT"] = _js2_f("base_line_height", 1.35)
    globs["CATALOGUE_JS2_FILTER_LABEL_FONT_SIZE_PX"] = _js2_i("filter_label_font_size_px", 11)
    globs["CATALOGUE_JS2_CARD_NAME_LINE_HEIGHT"] = _js2_f("card_name_line_height", 1.3)
    globs["CATALOGUE_JS2_CARD_NAME_LINE_HEIGHT_M"] = _js2_f("card_name_line_height_size_m", 1.04)
    globs["CATALOGUE_JS2_CARD_NAME_FONT_SIZE_PX_S"] = _js2_i("card_name_font_size_px_s", 13)
    globs["CATALOGUE_JS2_CARD_NAME_FONT_SIZE_PX_ML"] = _js2_i("card_name_font_size_px_ml", 15)
    globs["CATALOGUE_JS2_CARD_MFR_FONT_SIZE_PX"] = _js2_i("card_manufacturer_font_size_px", 11)
    globs["CATALOGUE_JS2_CARD_DETAIL_FONT_SIZE_PX"] = _js2_i("card_detail_row_font_size_px", 11)
    globs["CATALOGUE_JS2_CARD_DETAIL_LINE_HEIGHT"] = _js2_f("card_detail_row_line_height", 1.3)
    globs["CATALOGUE_JS2_CARD_CONTENT_FONT_SIZE_PX"] = _js2_i("card_content_text_font_size_px", 10)
    globs["CATALOGUE_JS2_CARD_CONTENT_LINE_HEIGHT"] = _js2_f("card_content_text_line_height", 1.4)
    globs["CATALOGUE_JS2_CARD_METRIC_OFFSET_PX"] = _js2_i("card_metric_serif_offset_px", 1)
    globs["CATALOGUE_JS2_CARD_METRIC_LINE_HEIGHT"] = _js2_f("card_metric_serif_line_height", 1.2)
    globs["CATALOGUE_JS2_CARD_GWP_LABEL_FONT_SIZE_PX"] = _js2_i("card_gwp_label_font_size_px", 9)
    globs["CATALOGUE_JS2_CARD_BADGE_FONT_SIZE_PX"] = _js2_i("card_badge_font_size_px", 10)
    globs["CATALOGUE_JS2_CARD_FOOTER_FONT_SIZE_PX"] = _js2_i("card_footer_font_size_px", 10)
    globs["CATALOGUE_JS2_CARD_XL_TABS_FONT_SIZE_PX"] = _js2_i("card_xl_tabs_font_size_px", 11)
    globs["CATALOGUE_JS2_CARD_XL_TAB_FONT_SIZE_PX"] = _js2_i("card_xl_tab_font_size_px", 10)
    globs["CATALOGUE_JS2_LIST_HEADER_OFFSET_PX"] = _js2_i("list_header_font_size_offset_px", -1)
    globs["CATALOGUE_JS2_LIST_CELL_LINE_HEIGHT"] = _js2_f("list_cell_line_height", 1.4)
    globs["CATALOGUE_JS2_LIST_MONO_FONT_SIZE_PX"] = _js2_i("list_mono_font_size_px", 11)
    globs["CATALOGUE_JS2_LIST_PLACEHOLDER_FONT_SIZE_PX"] = _js2_i("list_placeholder_font_size_px", 9)
    globs["CATALOGUE_JS2_DETAIL_TITLE_FONT_SIZE_PX"] = _js2_i("detail_panel_title_font_size_px", 11)
    globs["CATALOGUE_JS2_DETAIL_CLOSE_FONT_SIZE_PX"] = _js2_i("detail_panel_close_font_size_px", 15)
    globs["CATALOGUE_JS2_MODAL_CLOSE_FONT_SIZE_PX"] = _js2_i("modal_close_font_size_px", 16)
    globs["CATALOGUE_JS2_MODAL_NAME_FONT_SIZE_PX"] = _js2_i("modal_name_font_size_px", 17)
    globs["CATALOGUE_JS2_MODAL_MFR_FONT_SIZE_PX"] = _js2_i("modal_manufacturer_font_size_px", 13)
    globs["CATALOGUE_JS2_MODAL_GWP_FONT_SIZE_PX"] = _js2_i("modal_gwp_font_size_px", 18)
    globs["CATALOGUE_JS2_MODAL_SECTION_LABEL_FONT_SIZE_PX"] = _js2_i(
        "modal_section_label_font_size_px", 11
    )

    # Right detail panel layout (Sustainability / Tech. Details row grid + width).
    _js2_dp = (m.get("js2") or {}).get("detail_panel") or {}

    def _css_track(key: str, default: str) -> str:
        raw = str(_js2_dp.get(key) or default).strip() or default
        # Grid track sizes only — block anything that could break out of a var().
        if not re.fullmatch(r"[0-9a-zA-Z%.,\s()/+\-]+", raw):
            return default
        return raw

    globs["CATALOGUE_JS2_DETAIL_PANEL"] = {
        "width_px": max(280, min(900, _i("width_px", _js2_dp, 440))),
        "width_max_vw": max(20, min(90, _i("width_max_vw", _js2_dp, 50))),
        "sus_label_column": _css_track("sus_label_column", "minmax(0, 38fr)"),
        "sus_value_column": _css_track("sus_value_column", "minmax(0, 62fr)"),
        "sus_row_gap_px": max(0, min(32, _i("sus_row_gap_px", _js2_dp, 8))),
        "sus_font_size_px": max(10, min(18, _i("sus_font_size_px", _js2_dp, 12))),
    }

    _js2_theme = (m.get("js2") or {}).get("theme") or {}
    globs["JS_CATALOGUE_THEME"] = {
        "brand_color": str(_js2_theme.get("brand_color") or _design_token("colors", "brand_muted", "#666")),
        "tab_border": str(_js2_theme.get("tab_border") or "#e5e7eb"),
        "tab_active": str(_js2_theme.get("tab_active") or _design_token("colors", "green")),
        "grid_gap": str(_js2_theme.get("grid_gap") or _design_token("spacing", "grid_gap")),
        "co2_green": str(_js2_theme.get("co2_green") or _design_token("colors", "green")),
        "img_fit": str(_js2_theme.get("img_fit") or "cover"),
    }

    # Rules above/below the card product name (Cards view, sizes M/L/XL — see
    # card_name_divider_root_css()). Top and bottom are configured independently:
    # each is its own color/thickness/margins, not a mirrored pair.
    _js2_name_divider = (m.get("js2") or {}).get("card_name_divider") or {}

    def _divider_side(side_key: str, default_color: str) -> dict:
        d = _js2_name_divider.get(side_key) or {}
        return {
            "color": str(d.get("color") or default_color),
            "thickness_px": _i("thickness_px", d, 1),
            "margin_top_px": _i("margin_top_px", d, 2),
            "margin_bottom_px": _i("margin_bottom_px", d, 2),
        }

    globs["CATALOGUE_JS2_CARD_NAME_DIVIDER"] = {
        "top": _divider_side("top", "#f3f4f6"),
        "bottom": _divider_side("bottom", "#f3f4f6"),
    }

    globs["CATALOGUE_STREAMLIT_GRID_HEIGHT_PX"] = _i("streamlit_grid_height_px", g, 1200)
    globs["CATALOGUE_ROW_SPACING"] = _i("row_spacing_px", g, 60)
    globs["CATALOGUE_GWP_TO_DATA_SPACING"] = _i("gwp_to_data_spacing_px", g, -5)

    globs["CATALOGUE_STREAMLIT_CARD_MIN_HEIGHT_PX"] = _i("min_height_px", cs, 500)
    globs["CATALOGUE_STREAMLIT_CARD_MAX_HEIGHT_PX"] = _i("max_height_px", cs, 500)
    globs["CATALOGUE_JS_CARD_MIN_HEIGHT_PX"] = _i("js_min_height_px", cs, 500)

    globs["CATALOGUE_CARD_IMAGE_HEIGHT_PX"] = _i("card_image_height_px", ib, 100)
    globs["CATALOGUE_IMAGE_FETCH_MAX_WIDTH"] = _i("fetch_max_width", ib, 400)
    globs["CATALOGUE_IMAGE_FETCH_MAX_HEIGHT"] = _i("fetch_max_height", ib, 400)
    # Two served thumbnail tiers (see theme.json image_band._cache_tiers_note).
    globs["CATALOGUE_IMAGE_CACHE_CARD_MAX_PX"] = _i("cache_card_max_px", ib, 200)
    globs["CATALOGUE_IMAGE_CACHE_DETAIL_MAX_PX"] = _i("cache_detail_max_px", ib, 400)
    globs["CATALOGUE_CARD_IMAGE_ASPECT_RATIO"] = str(ib.get("aspect_ratio") or "2")
    globs["CATALOGUE_CARD_IMAGE_OBJECT_FIT"] = str(ib.get("object_fit") or "contain")
    globs["CATALOGUE_CARD_IMAGE_OBJECT_POSITION"] = str(ib.get("object_position") or "center")
    globs["CATALOGUE_CARD_IMAGE_ZOOM"] = _f("zoom", ib, 1.0)
    _bz = max(0.25, min(1.5, _f("binder_zoom", ib, 0.88)))
    globs["CATALOGUE_CARD_IMAGE_BINDER_ZOOM"] = _bz
    _bfit = str(ib.get("binder_object_fit") or "contain").strip().lower()
    if _bfit not in {"contain", "cover", "fill", "scale-down", "none"}:
        _bfit = "contain"
    globs["CATALOGUE_CARD_IMAGE_BINDER_OBJECT_FIT"] = _bfit
    globs["CATALOGUE_CARD_IMAGE_ZOOM_ORIGIN"] = str(ib.get("zoom_origin") or "center center")
    globs["CATALOGUE_CARD_IMAGE_BAND_BACKGROUND"] = str(ib.get("band_background") or "#ffffff")
    globs["CATALOGUE_CARD_IMAGE_MIN_HEIGHT"] = str(ib.get("min_height") or "100")
    globs["CATALOGUE_CARD_IMAGE_MAX_HEIGHT"] = str(ib.get("max_height") or "")

    globs["CATALOGUE_CARD_BORDER_WIDTH"] = str(cc.get("border_width") or "1px")
    globs["CATALOGUE_CARD_BORDER_STYLE"] = str(cc.get("border_style") or "solid")
    globs["CATALOGUE_CARD_BORDER_COLOR"] = str(cc.get("border_color") or "#d1d9e6")
    globs["CATALOGUE_CARD_BORDER_RADIUS"] = str(cc.get("border_radius") or "10px")
    globs["CATALOGUE_CARD_BACKGROUND"] = str(cc.get("background") or "#ffffff")
    globs["CATALOGUE_CARD_BODY_PADDING_X"] = str(cc.get("body_padding_x") or "10px")
    globs["CATALOGUE_CARD_BODY_PADDING_BOTTOM"] = str(cc.get("body_padding_bottom") or "10px")
    globs["CATALOGUE_CARD_HOVER_BOX_SHADOW"] = str(
        cc.get("hover_box_shadow") or "0 6px 18px rgba(15, 23, 42, 0.08)"
    )
    globs["CATALOGUE_CARD_HOVER_BORDER_COLOR"] = str(cc.get("hover_border_color") or "#b8c5d8")

    globs["_GWP_PILL_MARGIN_TOP_PX"] = _i("margin_top_px", gp, 10)
    globs["_GWP_PILL_MARGIN_BOTTOM_PX"] = _i("margin_bottom_px", gp, -5)
    globs["_GWP_PILL_MARGIN_LEFT_PX"] = _i("margin_left_px", gp, 0)
    globs["_GWP_PILL_MARGIN_RIGHT_PX"] = _i("margin_right_px", gp, 0)
    globs["_GWP_NEEDLE_WIDTH_PX"] = _i("needle_width_px", gp, 4)
    globs["_GWP_NEEDLE_HEIGHT_PX"] = _i("needle_height_px", gp, 16)
    globs["_GWP_NEEDLE_COLOR"] = str(gp.get("needle_color") or "#444444")
    globs["_GWP_LABEL_FONT_SIZE_PX"] = _i("label_font_size_px", gp, 11)
    globs["_GWP_LABEL_COLOR"] = str(gp.get("label_color") or "#94a3b8")

    globs["CATALOGUE_GROUP_TITLE_SPACING_TOP_PX"] = _i("group_title_spacing_top_px", sp, 100)
    globs["CATALOGUE_GROUP_TITLE_SPACING_BOTTOM_PX"] = _i(
        "group_title_spacing_bottom_px", sp, 30
    )
    globs["CATALOGUE_GROUP_SEPARATOR_LINE_PX"] = _i("group_separator_line_px", sp, 2)
    globs["CATALOGUE_GROUP_SEPARATOR_WIDTH_PCT"] = _i("group_separator_width_pct", sp, 25)
    globs["CATALOGUE_GROUP_SEPARATOR_COLOR"] = str(sp.get("group_separator_color") or "#e5e7eb")
    globs["CATALOGUE_GROUP_SEPARATOR_SPACING_TOP_PX"] = _i(
        "group_separator_spacing_top_px", sp, 6
    )
    globs["CATALOGUE_GROUP_SEPARATOR_SPACING_BOTTOM_PX"] = _i(
        "group_separator_spacing_bottom_px", sp, 6
    )

    globs["CATALOGUE_PAGE_CONTROLS_SHOW"] = bool(pc.get("show", True))

    _ch_dims = charts_dimensions_from_layout(m)
    globs["CHARTS_BOX_HEIGHT_PX"] = _ch_dims["box_height_px"]
    globs["CHARTS_BAR_HEIGHT_SCALE"] = _ch_dims["bar_height_scale"]
    globs["CHARTS_BAR_LINE_HEIGHT_PX"] = _ch_dims["bar_line_height_px"]
    globs["CHARTS_BAR_MAX_ROWS"] = _ch_dims["bar_max_rows"]
    globs["CHARTS_BAR_MAX_HEIGHT_PX"] = _ch_dims["bar_max_height_px"]
    globs["CHARTS_CORRELATION_PLOTLY_HEIGHT_PX"] = _ch_dims["correlation_plotly_height_px"]
    globs["CHARTS_CORRELATION_ALTAIR_HEIGHT_PX"] = _ch_dims["correlation_altair_height_px"]

    mb = m.get("material_type_band") or {}

    def _mb_s(key: str, default: str) -> str:
        v = mb.get(key, default)
        return _sanitize_catalogue_material_band_value(v, str(default))

    def _mb_b(key: str, default: bool) -> bool:
        if key not in mb:
            return default
        return str(mb.get(key)).strip().lower() in ("1", "true", "yes", "on")

    globs["CATALOGUE_MATERIAL_BAND_APPEND_IMPORTANT"] = _mb_b("append_important", True)
    globs["CATALOGUE_MATERIAL_BAND_POSITION"] = _mb_s("position", "absolute") or "absolute"
    globs["CATALOGUE_MATERIAL_BAND_TOP"] = _mb_s("top", "auto") or "auto"
    globs["CATALOGUE_MATERIAL_BAND_BOTTOM"] = _mb_s("bottom", "0") or "0"
    globs["CATALOGUE_MATERIAL_BAND_LEFT"] = _mb_s("left", "0") or "0"
    globs["CATALOGUE_MATERIAL_BAND_Z_INDEX"] = max(0, min(9999, _i("z_index", mb, 2)))
    globs["CATALOGUE_MATERIAL_BAND_MAX_WIDTH_PCT"] = max(1, min(100, _i("max_width_pct", mb, 92)))
    globs["CATALOGUE_MATERIAL_BAND_BACKGROUND_COLOR"] = _mb_s(
        "background_color", "#e8eaed"
    ) or "#e8eaed"
    globs["CATALOGUE_MATERIAL_BAND_COLOR"] = _mb_s("color", "#374151") or "#374151"
    globs["CATALOGUE_MATERIAL_BAND_FONT_SIZE_PX"] = max(6, min(48, _i("font_size_px", mb, 9)))
    globs["CATALOGUE_MATERIAL_BAND_FONT_STYLE"] = _mb_s("font_style", "italic") or "italic"
    globs["CATALOGUE_MATERIAL_BAND_FONT_WEIGHT"] = _mb_s("font_weight", "500") or "500"
    try:
        _lh = float(str(mb.get("line_height", 1.2)).strip())
        globs["CATALOGUE_MATERIAL_BAND_LINE_HEIGHT"] = str(max(0.8, min(3.0, _lh)))
    except Exception:
        globs["CATALOGUE_MATERIAL_BAND_LINE_HEIGHT"] = "1.2"
    globs["CATALOGUE_MATERIAL_BAND_PADDING"] = _mb_s("padding", "0 1px")
    globs["CATALOGUE_MATERIAL_BAND_MARGIN"] = _mb_s("margin", "0")
    globs["CATALOGUE_MATERIAL_BAND_BORDER_RADIUS"] = _mb_s("border_radius", "0")
    globs["CATALOGUE_MATERIAL_BAND_POINTER_EVENTS"] = _mb_s("pointer_events", "none") or "none"
    globs["CATALOGUE_MATERIAL_BAND_WHITE_SPACE"] = _mb_s("white_space", "nowrap") or "nowrap"
    globs["CATALOGUE_MATERIAL_BAND_OVERFLOW"] = _mb_s("overflow", "hidden") or "hidden"
    globs["CATALOGUE_MATERIAL_BAND_TEXT_OVERFLOW"] = _mb_s("text_overflow", "ellipsis") or "ellipsis"
    globs["CATALOGUE_MATERIAL_BAND_BOX_SIZING"] = _mb_s("box_sizing", "border-box") or "border-box"
    globs["CATALOGUE_MATERIAL_BAND_FONT_FAMILY"] = _mb_s("font_family", "inherit") or "inherit"


def catalogue_material_band_css_var_declarations() -> str:
    zi = int(CATALOGUE_MATERIAL_BAND_Z_INDEX)
    mw = int(CATALOGUE_MATERIAL_BAND_MAX_WIDTH_PCT)
    fs = int(CATALOGUE_MATERIAL_BAND_FONT_SIZE_PX)
    return (
        f"--cat-mat-position:{CATALOGUE_MATERIAL_BAND_POSITION};"
        f"--cat-mat-top:{CATALOGUE_MATERIAL_BAND_TOP};"
        f"--cat-mat-bottom:{CATALOGUE_MATERIAL_BAND_BOTTOM};"
        f"--cat-mat-left:{CATALOGUE_MATERIAL_BAND_LEFT};"
        f"--cat-mat-z:{zi};"
        f"--cat-mat-maxw:{mw}%;"
        f"--cat-mat-bg:{CATALOGUE_MATERIAL_BAND_BACKGROUND_COLOR};"
        f"--cat-mat-color:{CATALOGUE_MATERIAL_BAND_COLOR};"
        f"--cat-mat-fs:{fs}px;"
        f"--cat-mat-style:{CATALOGUE_MATERIAL_BAND_FONT_STYLE};"
        f"--cat-mat-weight:{CATALOGUE_MATERIAL_BAND_FONT_WEIGHT};"
        f"--cat-mat-lh:{CATALOGUE_MATERIAL_BAND_LINE_HEIGHT};"
        f"--cat-mat-pad:{CATALOGUE_MATERIAL_BAND_PADDING};"
        f"--cat-mat-margin:{CATALOGUE_MATERIAL_BAND_MARGIN};"
        f"--cat-mat-radius:{CATALOGUE_MATERIAL_BAND_BORDER_RADIUS};"
        f"--cat-mat-pe:{CATALOGUE_MATERIAL_BAND_POINTER_EVENTS};"
        f"--cat-mat-ws:{CATALOGUE_MATERIAL_BAND_WHITE_SPACE};"
        f"--cat-mat-ov:{CATALOGUE_MATERIAL_BAND_OVERFLOW};"
        f"--cat-mat-to:{CATALOGUE_MATERIAL_BAND_TEXT_OVERFLOW};"
        f"--cat-mat-box:{CATALOGUE_MATERIAL_BAND_BOX_SIZING};"
        f"--cat-mat-ff:{CATALOGUE_MATERIAL_BAND_FONT_FAMILY};"
    )


def catalogue_material_band_important_suffix() -> str:
    return " !important" if CATALOGUE_MATERIAL_BAND_APPEND_IMPORTANT else ""


def js2_list_view_col_widths_css() -> str:
    """Column widths for JS2 list table (``data-col`` + ``JS2_LIST_VIEW_COL_WIDTHS``)."""
    rules: list[str] = []
    for key in JS2_LIST_VIEW_COLUMNS:
        w = JS2_LIST_VIEW_COL_WIDTHS.get(key, "").strip()
        if not w:
            continue
        sel = (
            f'.rv-table thead th[data-col="{key}"], '
            f'.rv-table tbody td[data-col="{key}"]'
        )
        if w.startswith("min:"):
            rules.append(f"{sel}{{min-width:{w[4:].strip()};}}")
        elif w.endswith("%"):
            rules.append(f"{sel}{{width:{w};}}")
        else:
            rules.append(f"{sel}{{width:{w};max-width:{w};min-width:{w};}}")
    rules.append(
        '.rv-table td[data-col="product_type"],.rv-table td[data-col="material_type"]'
        "{white-space:normal;padding-left:6px;padding-right:6px;}"
    )
    if not rules:
        return ""
    return "<style>" + "".join(rules) + "</style>"


def catalogue_list_view_col_widths_css() -> str:
    return js2_list_view_col_widths_css()


def js2_typography_root_css() -> str:
    """``:root`` CSS vars for JS2 catalogue iframe (theme.json → catalogue.js2.typography)."""
    g = globals()

    def _i(name: str, default: int) -> int:
        try:
            return int(g.get(name, default))
        except (TypeError, ValueError):
            return default

    def _f(name: str, default: float) -> float:
        try:
            return float(g.get(name, default))
        except (TypeError, ValueError):
            return default

    _base = _i("CATALOGUE_JS2_BASE_FONT_SIZE_PX", 13)
    _hdr_off = _i("CATALOGUE_JS2_LIST_HEADER_OFFSET_PX", -1)
    _metric_off = _i("CATALOGUE_JS2_CARD_METRIC_OFFSET_PX", 1)
    _dp = g.get("CATALOGUE_JS2_DETAIL_PANEL") or {}
    if not isinstance(_dp, dict):
        _dp = {}
    _dp_w = 440
    _dp_vw = 50
    _dp_gap = 8
    _dp_fs = 12
    try:
        _dp_w = int(_dp.get("width_px", 440))
    except (TypeError, ValueError):
        pass
    try:
        _dp_vw = int(_dp.get("width_max_vw", 50))
    except (TypeError, ValueError):
        pass
    try:
        _dp_gap = int(_dp.get("sus_row_gap_px", 8))
    except (TypeError, ValueError):
        pass
    try:
        _dp_fs = int(_dp.get("sus_font_size_px", 12))
    except (TypeError, ValueError):
        pass
    _dp_label = str(_dp.get("sus_label_column") or "minmax(0, 38fr)").strip()
    _dp_value = str(_dp.get("sus_value_column") or "minmax(0, 62fr)").strip()
    return (
        f"--c-fs:{_base}px;"
        f"--c-lh:{_f('CATALOGUE_JS2_BASE_LINE_HEIGHT', 1.35)};"
        f"--js2-filter-label-fs:{_i('CATALOGUE_JS2_FILTER_LABEL_FONT_SIZE_PX', 11)}px;"
        f"--js2-card-name-lh:{_f('CATALOGUE_JS2_CARD_NAME_LINE_HEIGHT', 1.3)};"
        f"--js2-card-name-lh-m:{_f('CATALOGUE_JS2_CARD_NAME_LINE_HEIGHT_M', 1.04)};"
        f"--js2-card-name-fs-s:{_i('CATALOGUE_JS2_CARD_NAME_FONT_SIZE_PX_S', 13)}px;"
        f"--js2-card-name-fs-ml:{_i('CATALOGUE_JS2_CARD_NAME_FONT_SIZE_PX_ML', 15)}px;"
        f"--js2-card-mfr-fs:{_i('CATALOGUE_JS2_CARD_MFR_FONT_SIZE_PX', 11)}px;"
        f"--js2-card-detail-fs:{_i('CATALOGUE_JS2_CARD_DETAIL_FONT_SIZE_PX', 11)}px;"
        f"--js2-card-detail-lh:{_f('CATALOGUE_JS2_CARD_DETAIL_LINE_HEIGHT', 1.3)};"
        f"--js2-card-content-fs:{_i('CATALOGUE_JS2_CARD_CONTENT_FONT_SIZE_PX', 10)}px;"
        f"--js2-card-content-lh:{_f('CATALOGUE_JS2_CARD_CONTENT_LINE_HEIGHT', 1.4)};"
        f"--js2-card-metric-fs:{_base + _metric_off}px;"
        f"--js2-card-metric-lh:{_f('CATALOGUE_JS2_CARD_METRIC_LINE_HEIGHT', 1.2)};"
        f"--js2-card-gwp-lbl-fs:{_i('CATALOGUE_JS2_CARD_GWP_LABEL_FONT_SIZE_PX', 9)}px;"
        f"--js2-card-badge-fs:{_i('CATALOGUE_JS2_CARD_BADGE_FONT_SIZE_PX', 10)}px;"
        f"--js2-card-footer-fs:{_i('CATALOGUE_JS2_CARD_FOOTER_FONT_SIZE_PX', 10)}px;"
        f"--js2-card-xl-tabs-fs:{_i('CATALOGUE_JS2_CARD_XL_TABS_FONT_SIZE_PX', 11)}px;"
        f"--js2-card-xl-tab-fs:{_i('CATALOGUE_JS2_CARD_XL_TAB_FONT_SIZE_PX', 10)}px;"
        f"--js2-list-hdr-fs:{_base + _hdr_off}px;"
        f"--js2-list-cell-lh:{_f('CATALOGUE_JS2_LIST_CELL_LINE_HEIGHT', 1.4)};"
        f"--js2-list-mono-fs:{_i('CATALOGUE_JS2_LIST_MONO_FONT_SIZE_PX', 11)}px;"
        f"--js2-list-ph-fs:{_i('CATALOGUE_JS2_LIST_PLACEHOLDER_FONT_SIZE_PX', 9)}px;"
        f"--js2-detail-title-fs:{_i('CATALOGUE_JS2_DETAIL_TITLE_FONT_SIZE_PX', 11)}px;"
        f"--js2-detail-close-fs:{_i('CATALOGUE_JS2_DETAIL_CLOSE_FONT_SIZE_PX', 15)}px;"
        f"--js2-modal-close-fs:{_i('CATALOGUE_JS2_MODAL_CLOSE_FONT_SIZE_PX', 16)}px;"
        f"--js2-modal-name-fs:{_i('CATALOGUE_JS2_MODAL_NAME_FONT_SIZE_PX', 17)}px;"
        f"--js2-modal-mfr-fs:{_i('CATALOGUE_JS2_MODAL_MFR_FONT_SIZE_PX', 13)}px;"
        f"--js2-modal-gwp-fs:{_i('CATALOGUE_JS2_MODAL_GWP_FONT_SIZE_PX', 18)}px;"
        f"--js2-modal-label-fs:{_i('CATALOGUE_JS2_MODAL_SECTION_LABEL_FONT_SIZE_PX', 11)}px;"
        f"--js2-detail-panel-w:{_dp_w}px;"
        f"--js2-detail-panel-max-vw:{_dp_vw}vw;"
        f"--js2-sus-label-col:{_dp_label};"
        f"--js2-sus-value-col:{_dp_value};"
        f"--js2-sus-row-gap:{_dp_gap}px;"
        f"--js2-sus-fs:{_dp_fs}px;"
        "--js2-ff-serif:var(--eetra-ff-serif,'Source Serif Pro',Georgia,serif);"
    )


def js_catalogue_theme_root_css() -> str:
    """Extra ``:root`` fragment from ``JS_CATALOGUE_THEME`` (fn336 injection)."""
    t = JS_CATALOGUE_THEME
    return (
        f"--cat-brand-color:{t.get('brand_color', '#666')};"
        f"--cat-tab-border:{t.get('tab_border', '#e5e7eb')};"
        f"--cat-tab-active:{t.get('tab_active', '#2a7d2e')};"
        f"--cat-grid-gap:{t.get('grid_gap', '16px')};"
        f"--cat-co2-green:{t.get('co2_green', '#2a7d2e')};"
        f"--cat-img-fit:{t.get('img_fit', 'cover')};"
    )


def catalogue_js_theme_root_css() -> str:
    return js_catalogue_theme_root_css()


def card_name_divider_root_css() -> str:
    """``:root`` fragment for the rules above/below the card product name.

    Cards view, sizes M/L/XL only (``.cat2-name-divider`` is hidden for S in the
    component's own CSS). Top and bottom are independent — edit
    ``theme.json`` → ``catalogue.js2.card_name_divider.{top,bottom}``, no code
    change needed for a color/thickness/spacing tweak.
    """
    cfg = CATALOGUE_JS2_CARD_NAME_DIVIDER or {}
    top = cfg.get("top") or {}
    bottom = cfg.get("bottom") or {}

    def _px(d: dict, key: str, default: int) -> int:
        try:
            return int(d.get(key, default))
        except (TypeError, ValueError):
            return default

    return (
        f"--cat2-name-divider-width-ml:{_px(cfg, 'width_pct_ml', 50)}%;"
        f"--cat2-name-divider-top-color:{top.get('color', '#f3f4f6')};"
        f"--cat2-name-divider-top-thickness:{_px(top, 'thickness_px', 1)}px;"
        f"--cat2-name-divider-top-margin-top:{_px(top, 'margin_top_px', 2)}px;"
        f"--cat2-name-divider-top-margin-bottom:{_px(top, 'margin_bottom_px', 2)}px;"
        f"--cat2-name-divider-bottom-color:{bottom.get('color', '#f3f4f6')};"
        f"--cat2-name-divider-bottom-thickness:{_px(bottom, 'thickness_px', 1)}px;"
        f"--cat2-name-divider-bottom-margin-top:{_px(bottom, 'margin_top_px', 2)}px;"
        f"--cat2-name-divider-bottom-margin-bottom:{_px(bottom, 'margin_bottom_px', 2)}px;"
    )


def js_catalogue_window_config_json() -> str:
    """``window.__CAT_CFG__`` — JS grid presets + JS2 list column metadata."""
    presets = {}
    for label, spec in JS_CATALOGUE_GRID_SIZE_PRESETS.items():
        presets[label] = {
            "colsDelta": int(spec.get("cols_delta", 0)),
            "imageHeightPx": int(spec.get("image_height_px", 100)),
        }
    _globs = globals()
    _bpx = str(_globs.get("CATALOGUE_CARD_BODY_PADDING_X", "8px"))
    _bpb = str(_globs.get("CATALOGUE_CARD_BODY_PADDING_BOTTOM", "10px"))
    return json.dumps(
        {
            "gridSizePresets": presets,
            "listColumns": list(JS2_LIST_VIEW_COLUMNS),
            "listColWidths": dict(JS2_LIST_VIEW_COL_WIDTHS),
            "listColumnLabels": dict(JS2_LIST_COLUMN_LABELS),
            "listOptionalColumns": list(JS2_LIST_OPTIONAL_COLUMNS),
            "bodyPaddingX": _bpx,
            "bodyPaddingBottom": _bpb,
            "filterBar": js2_filter_bar_config(),
        },
        ensure_ascii=False,
    )


def js2_filter_bar_config() -> dict:
    """Which fields the in-iframe filter bar may offer, and its scope label.

    Enforces the app's filter hierarchy: dimensions owned globally by the sidebar
    (product type, material type, manufacturer) are not offered again inside the
    card view, where they would silently compete with the sidebar's answer.
    Configure in ``theme.json → catalogue.js2.filter_bar``.
    """
    cfg = _theme_section("catalogue", "js2", "filter_bar") or {}
    hidden = cfg.get("hidden")
    if hidden is None:
        hidden = ["prod", "mat"]
    return {
        "hidden": [str(h) for h in hidden],
        "scopeLabel": str(cfg.get("scope_label", "Refine within current filters")),
    }


def catalogue_js_window_config_json() -> str:
    return js_catalogue_window_config_json()


def _catalogue_aspect_ratio_css(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if "/" not in s:
        try:
            float(s.replace(",", "."))
            return f"aspect-ratio: {s} / 1;"
        except ValueError:
            return f"aspect-ratio: {s};"
    return f"aspect-ratio: {s};"


def _catalogue_css_sanitize_position(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9\s.%\-,/()]+", "", str(s or "").strip())
    return t.strip() or "center"


def _catalogue_image_zoom_scale() -> float:
    try:
        z = float(CATALOGUE_CARD_IMAGE_ZOOM)
    except (TypeError, ValueError):
        z = 1.0
    return max(0.25, min(4.0, z))


def fn342_catalogue_card_border_override_html(show_border: bool) -> str:
    if show_border:
        return ""
    sel = _CATALOGUE_CARD_BLOCK
    _act = f"{_CATALOGUE_CARD_COLUMN} div[data-testid=stHorizontalBlock]:has(button)"
    return (
        "<style>"
        f"{sel}{{border:none!important;border-radius:0!important;box-shadow:none!important;}}"
        f"{sel}:hover{{box-shadow:none!important;border-color:transparent!important;}}"
        f"{sel} .eetra-cat-img-band{{border-radius:0!important;}}"
        f"{_act} > div[data-testid=stColumn]:nth-child(1) .stButton > button{{border-radius:0!important;}}"
        f"{_act} > div[data-testid=stColumn]:only-child .stButton > button{{border-radius:0!important;}}"
        f"{_act} > div[data-testid=stColumn]:nth-child(2) .stButton > button, "
        f"{_act} > div[data-testid=stColumn]:nth-child(2) .stButton > a, "
        f"{_act} > div[data-testid=stColumn]:nth-child(2) a[href]{{border-radius:0!important;}}"
        "</style>"
    )


def init_catalogue_layout_globals(ui_config: dict | None) -> None:
    """Called once from ``lib_ui`` after ``aux_10__ui_config.json`` is loaded."""
    apply_catalogue_layout_globals(globals(), ui_config)
