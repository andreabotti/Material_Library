"""
libs/lib_ui.py — EETRA MatLib UI module
=========================================
fn301–fn399  Widgets, product cards, field visibility, HTML rendering, constants

  fn301  get_unique_sorted_values        unique sorted values from a Series
  fn302  render_filter_widgets           sidebar filter toggles + selectboxes
  fn303  custom_hr                       CSS horizontal rule
  fn304  slim_divider                    thin configurable divider (= render_horizontal_divider)
  fn305  group_by_column                 DataFrame group-by aggregation
  fn306  render_filter_widgets_clean     filter widgets with cleaned col names
  fn307  custom_hr_compact               compact horizontal rule
  fn308  import_certification_table      load certification CSV
  fn309  create_checkboxes_in_columns    grouped checkbox widgets
  fn310  create_input_lifecycle_gwp      lifecycle GWP number-input grid
  fn311  apply_dataframe_filters         inline filter widgets (non-sidebar)
  fn312  get_manufacturer_logo_mapping   manufacturer → logo path from config
  fn313  get_manufacturer_color_mapping  manufacturer → hex colour from config
  fn314  extract_dominant_color          dominant non-white colour from a logo
  fn315  normalize_product_type          normalise D__ProductType_ENG strings
  fn316  make_session_key_fragment       safe session key fragment
  fn317  get_field_visibility            field visibility config for product type
  fn318  get_tabular_column_visibility   tabular column visibility per product type
  fn319  filter_columns_by_visibility    filter column list using visibility config
  fn320  round_numeric_columns           round numeric DataFrame columns
  fn321  get_column_completeness_stats   per-column completeness stats
  fn322  get_value_counts_for_treemap    value counts for px.treemap
  fn343  get_value_category_matrix       per-cell category (empty/n_r/n_a/zero/value) for a set of columns
  fn344  build_dev_missmatrix_payload    ECharts heatmap payload for Developer completeness view
  fn323  is_building_boards_selected     True when Building boards filter is active
  fn324  get_val                         safe row accessor (→ "-" for NaN)
  fn325  get_thickness_val               thickness with multi-column fallback
  fn326  format_recycling_rate           format recycling % to 1 dp
  fn327  parse_technical_details         tech-details text → icon+tooltip HTML
  fn328  country_to_flag                 country name/code → emoji flag
  fn329  render_product_card             full product card HTML in Streamlit
  fn330  extract_resistance_class        EN 206 class label from a row
  fn331  resistance_sort_key             numeric sort key for resistance labels
  fn332  extract_thickness_value         numeric thickness in mm from a row
  fn333  thickness_sort_key              sort key for thickness floats
  fn334  cached_logo_image               @cache_data logo image loader + resizer
  fn335  render_detail_panel             persistent right-hand detail panel
  fn336  render_catalogue_flipcard       flip-card catalogue HTML component
  fn337  render_catalogue                product card grid HTML (render module)
  fn338  render_revalu                   Revalu EPD matching table HTML
  fn339  render_filter_summary           inline filter summary bar HTML
  fn340  filter_cleaned_by_allowed       filter cleaned cols by original allowlist
  fn341  inject_custom_styles_legacy     delegate to lib_header inject_global_css
  fn342  catalogue_card_border_override_html  optional style block to hide card borders
  fn346  voc_cert_composite_data_uri         VOC cert badges (list view / composite PNG)
  fn360  start_catalogue_payload_warmup      background-warm JS2 catalogue @cache_data
"""

from __future__ import annotations
import streamlit as st

import pandas as pd
import re, os, json, colorsys, base64, hashlib, unicodedata, time, threading
import textwrap
from functools import lru_cache as _lru_cache
import html as _html
from datetime import datetime
import pathlib as _pathlib
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import plotly.express as px
import requests
from .lib_data import fn128_clean_column_name, fn128a_display_label_for_original, HIDDEN_APP_COLUMNS

# ── Lazy image fetch (avoids circular import with lib_data) ──────────────────
def _lazy_fetch_image(url, *, eetra_id=None, product_name=None):
    """Catalogue cards use high-res profile (downscale-only) for sharp display."""
    from .lib_data import fn110_cached_fetch_image
    return fn110_cached_fetch_image(
        url, "catalogue", eetra_id=eetra_id, product_name=product_name
    )


# ════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL CONSTANTS (from shared.py)
# ════════════════════════════════════════════════════════════════════════════

# ── App settings ─────────────────────────────────────────────────────────────
# Startup login is always shown until ``auth_user`` is set (see app.py + fn112a).
# When True, the app uses startup login only (no secondary Developer password form).
REQUIRE_AUTH  = True
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "pwd"
EXCLUDE_KEYWORDS = ["void"]

# ── Static colour map ─────────────────────────────────────────────────────────
CUSTOM_COLOR_MAP = {
    "Knauf":         "#00a0e6",
    "Fassa Bortolo": "#12275e",
    "Gyproc":        "#025aaf",
    "Siniat":        "#c32dfb",
    "Ediltec":       "#F7931E",
}

# ── UI config loaded at import time ──────────────────────────────────────────
_UI_CONFIG_PATH = "aux_10__ui_config.json"
_UI_CONFIG: dict = {}
try:
    with open(_UI_CONFIG_PATH, "r", encoding="utf-8") as _f:
        _UI_CONFIG = json.load(_f)
except Exception:
    pass

FIELD_VISIBILITY          = _UI_CONFIG.get("field_visibility",           {"default": {}})
FIELD_META                = _UI_CONFIG.get("field_meta",                 {})
FIELD_UI_SETTINGS         = _UI_CONFIG.get("field_ui_settings",          {})
TABULAR_COLUMN_VISIBILITY = _UI_CONFIG.get("tabular_column_visibility",  {"default": {}})
MANUFACTURER_LOGOS        = _UI_CONFIG.get("manufacturer_logos",         {})
CATALOGUE_VIEW_SETTINGS   = _UI_CONFIG.get("catalogue_view",             {})
FILTER_WIDGET_SETTINGS    = _UI_CONFIG.get("filter_widget",              {})
CHART_WIDGET_SETTINGS     = _UI_CONFIG.get("chart_widget",               {})

if "default" not in FIELD_VISIBILITY:
    FIELD_VISIBILITY["default"] = {}

FIELD_VISIBILITY_INDEX   = {k.lower(): v for k, v in FIELD_VISIBILITY.items()}
FIELD_VISIBILITY_KEY_MAP = {k.lower(): k for k in FIELD_VISIBILITY.keys()}

# Bump when catalogue display-parameter defaults change so saved checkbox state resets once.
DISPLAY_PARAMS_SESSION_VER = "v3"


# ── Catalogue views (customise in lib_ui_catalogues.py) ───────────────────────
from . import lib_ui_catalogues as _catalogues  # noqa: E402

_catalogues.init_catalogue_layout_globals(_UI_CONFIG)

from .lib_ui_catalogues import (  # noqa: E402
    CATALOGUE_COMPONENT_PATH,
    STREAMLIT_CATALOGUE_LIST_COLUMN_WIDTHS,
    JS_CATALOGUE_FIELD_MAP,
    JS_CATALOGUE_NUMERIC_FIELDS,
    JS_CATALOGUE_GRID_SIZE_PRESETS,
    JS_CATALOGUE_THEME,
    JS2_LIST_VIEW_COLUMNS,
    JS2_LIST_VIEW_COL_WIDTHS,
    JS2_LIST_COLUMN_LABELS,
    JS2_LIST_OPTIONAL_COLUMNS,
    JS2_DETAIL_VIEW_MODE,
    ECOPORTAL_CATALOGUE_LIST_COLUMN_WIDTHS,
    CATALOGUE_FLIPCARD_FIELD_MAP,
    CATALOGUE_FLIPCARD_NUMERIC_FIELDS,
    CATALOGUE_LIST_VIEW_COLUMNS,
    CATALOGUE_LIST_VIEW_COL_WIDTHS,
    CATALOGUE_GRID_SIZE_PRESETS,
    CATALOGUE_JS_THEME,
    CATALOGUE_CARD_SURFACE_CLASS,
    CATALOGUE_FONT_SIZE_PX,
    CATALOGUE_LINE_HEIGHT,
    CATALOGUE_TITLE_LINE_HEIGHT,
    CATALOGUE_GWP_LINE_HEIGHT,
    CATALOGUE_JS_TITLE_FONT_SIZE_PX,
    CATALOGUE_JS_BODY_FONT_SIZE_PX,
    CATALOGUE_JS_TITLE_LINE_HEIGHT,
    CATALOGUE_JS_BODY_LINE_HEIGHT,
    CATALOGUE_JS_GWP_LINE_HEIGHT,
    CATALOGUE_STREAMLIT_GRID_HEIGHT_PX,
    CATALOGUE_ROW_SPACING,
    CATALOGUE_GWP_TO_DATA_SPACING,
    CATALOGUE_STREAMLIT_CARD_MIN_HEIGHT_PX,
    CATALOGUE_STREAMLIT_CARD_MAX_HEIGHT_PX,
    CATALOGUE_JS_CARD_MIN_HEIGHT_PX,
    CATALOGUE_CARD_IMAGE_HEIGHT_PX,
    CATALOGUE_IMAGE_FETCH_MAX_WIDTH,
    CATALOGUE_IMAGE_FETCH_MAX_HEIGHT,
    CATALOGUE_CARD_IMAGE_ASPECT_RATIO,
    CATALOGUE_CARD_IMAGE_OBJECT_FIT,
    CATALOGUE_CARD_IMAGE_OBJECT_POSITION,
    CATALOGUE_CARD_IMAGE_ZOOM,
    CATALOGUE_CARD_IMAGE_BINDER_ZOOM,
    CATALOGUE_CARD_IMAGE_BINDER_OBJECT_FIT,
    CATALOGUE_CARD_IMAGE_ZOOM_ORIGIN,
    CATALOGUE_CARD_IMAGE_BAND_BACKGROUND,
    CATALOGUE_CARD_IMAGE_MIN_HEIGHT,
    CATALOGUE_CARD_IMAGE_MAX_HEIGHT,
    CATALOGUE_CARD_BORDER_WIDTH,
    CATALOGUE_CARD_BORDER_STYLE,
    CATALOGUE_CARD_BORDER_COLOR,
    CATALOGUE_CARD_BORDER_RADIUS,
    CATALOGUE_CARD_BACKGROUND,
    CATALOGUE_CARD_BODY_PADDING_X,
    CATALOGUE_CARD_BODY_PADDING_BOTTOM,
    CATALOGUE_CARD_HOVER_BOX_SHADOW,
    CATALOGUE_CARD_HOVER_BORDER_COLOR,
    CATALOGUE_GROUP_TITLE_SPACING_TOP_PX,
    CATALOGUE_GROUP_TITLE_SPACING_BOTTOM_PX,
    CATALOGUE_GROUP_SEPARATOR_LINE_PX,
    CATALOGUE_GROUP_SEPARATOR_WIDTH_PCT,
    CATALOGUE_GROUP_SEPARATOR_COLOR,
    CATALOGUE_GROUP_SEPARATOR_SPACING_TOP_PX,
    CATALOGUE_GROUP_SEPARATOR_SPACING_BOTTOM_PX,
    CATALOGUE_PAGE_CONTROLS_SHOW,
    CATALOGUE_MATERIAL_BAND_APPEND_IMPORTANT,
    CATALOGUE_MATERIAL_BAND_POSITION,
    CATALOGUE_MATERIAL_BAND_TOP,
    CATALOGUE_MATERIAL_BAND_BOTTOM,
    CATALOGUE_MATERIAL_BAND_LEFT,
    CATALOGUE_MATERIAL_BAND_Z_INDEX,
    CATALOGUE_MATERIAL_BAND_MAX_WIDTH_PCT,
    CATALOGUE_MATERIAL_BAND_BACKGROUND_COLOR,
    CATALOGUE_MATERIAL_BAND_COLOR,
    CATALOGUE_MATERIAL_BAND_FONT_SIZE_PX,
    CATALOGUE_MATERIAL_BAND_FONT_STYLE,
    CATALOGUE_MATERIAL_BAND_FONT_WEIGHT,
    CATALOGUE_MATERIAL_BAND_LINE_HEIGHT,
    CATALOGUE_MATERIAL_BAND_PADDING,
    CATALOGUE_MATERIAL_BAND_MARGIN,
    CATALOGUE_MATERIAL_BAND_BORDER_RADIUS,
    CATALOGUE_MATERIAL_BAND_POINTER_EVENTS,
    CATALOGUE_MATERIAL_BAND_WHITE_SPACE,
    CATALOGUE_MATERIAL_BAND_OVERFLOW,
    CATALOGUE_MATERIAL_BAND_TEXT_OVERFLOW,
    CATALOGUE_MATERIAL_BAND_BOX_SIZING,
    CATALOGUE_MATERIAL_BAND_FONT_FAMILY,
    CHARTS_BOX_HEIGHT_PX,
    CHARTS_BAR_HEIGHT_SCALE,
    CHARTS_BAR_LINE_HEIGHT_PX,
    CHARTS_BAR_MAX_ROWS,
    CHARTS_BAR_MAX_HEIGHT_PX,
    CHARTS_CORRELATION_PLOTLY_HEIGHT_PX,
    CHARTS_CORRELATION_ALTAIR_HEIGHT_PX,
    _GWP_PILL_MARGIN_TOP_PX,
    _GWP_PILL_MARGIN_BOTTOM_PX,
    _GWP_PILL_MARGIN_LEFT_PX,
    _GWP_PILL_MARGIN_RIGHT_PX,
    _GWP_NEEDLE_WIDTH_PX,
    _GWP_NEEDLE_HEIGHT_PX,
    _GWP_NEEDLE_COLOR,
    _GWP_LABEL_FONT_SIZE_PX,
    _GWP_LABEL_COLOR,
    _CATALOGUE_CARD_BLOCK,
    _CATALOGUE_CARD_COLUMN,
    _CATALOGUE_CARD_SURFACE_CLASS,
    _CATALOGUE_OBJECT_FIT_ALLOWED,
    catalogue_material_band_css_var_declarations,
    catalogue_material_band_important_suffix,
    card_name_divider_root_css,
    js2_list_view_col_widths_css,
    js2_typography_root_css,
    js_catalogue_theme_root_css,
    js_catalogue_window_config_json,
    catalogue_list_view_col_widths_css,
    catalogue_js_theme_root_css,
    catalogue_js_window_config_json,
    _catalogue_css_sanitize_position,
    _catalogue_image_zoom_scale,
    fn342_catalogue_card_border_override_html,
    load_merged_catalogue_layout,
    charts_dimensions_from_layout,
)


def fn341_get_charts_dimensions() -> dict:
    """
    Current chart pixel sizes from merged catalogue layout.

    Re-reads ``aux_01__catalogue_layout.json`` on every call so edits apply on the next
    Streamlit rerun (unlike module-level ``CHARTS_*``, which are fixed at import).
    """
    return charts_dimensions_from_layout(load_merged_catalogue_layout(_UI_CONFIG))


# ── Charts: per-product-type default value column ─────────────────────────────

CHART_VALUE_DEFAULTS_FILENAME = "aux_02__chart_value_defaults.json"


def fn344_load_chart_value_defaults() -> dict:
    """Read ``aux_02__chart_value_defaults.json`` fresh so backend edits apply on rerun."""
    path = Path(__file__).resolve().parent.parent / CHART_VALUE_DEFAULTS_FILENAME
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def fn345_dominant_product_type(df, group_by_col: str = "D__ProductType_ENG") -> str:
    """Product type of the rows in view, or '' when the view spans several types.

    Read from the dataframe rather than the filter widgets so it works whichever
    way the view was narrowed (sidebar filters, collections, search).
    """
    if df is None or group_by_col not in getattr(df, "columns", []):
        return ""
    try:
        vals = df[group_by_col].dropna().astype(str).str.strip()
        vals = vals[(vals != "") & (vals != "-")]
        uniq = vals.unique()
        return str(uniq[0]) if len(uniq) == 1 else ""
    except Exception:
        return ""


def fn347_filter_value_columns_by_product_type(df, numeric_cols_cleaned):
    """Drop value columns restricted to other product types.

    Reads ``value_column_visibility`` from ``aux_02__chart_value_defaults.json``: a
    column listed there is offered only when the rows in view are all of an allowed
    product type. Columns absent from that map are always offered. Never returns an
    empty list — if every option would be filtered out the input is passed through.
    """
    if not numeric_cols_cleaned:
        return numeric_cols_cleaned
    cfg = fn344_load_chart_value_defaults()
    settings = cfg.get("settings") or {}
    vis = cfg.get("value_column_visibility") or {}
    if not cfg or not settings.get("enabled", True) or not vis:
        return numeric_cols_cleaned

    restrictions = {
        col: {str(t).strip() for t in allowed}
        for col, allowed in vis.items()
        if not col.startswith("_") and isinstance(allowed, list)
    }
    if not restrictions:
        return numeric_cols_cleaned

    ptype = fn345_dominant_product_type(df, settings.get("group_by_column") or "D__ProductType_ENG")

    from .lib_data import fn125_get_original_column_name

    kept = []
    for cleaned in numeric_cols_cleaned:
        try:
            original = fn125_get_original_column_name(df, cleaned)
        except Exception:
            kept.append(cleaned)
            continue
        allowed = restrictions.get(original)
        if allowed is not None and ptype not in allowed:
            continue
        kept.append(cleaned)
    return kept or numeric_cols_cleaned


def fn346_default_value_column_index(df, numeric_cols_cleaned, fallback_index: int = 0) -> int:
    """Index into *numeric_cols_cleaned* for the configured default value column.

    Walks the product type's ordered preference list from
    ``aux_02__chart_value_defaults.json`` and returns the first candidate that is both
    offered by the selectbox and has at least ``settings.min_coverage`` non-null
    values in the rows in view. Falls back to ``global_default``, then to
    *fallback_index* — so a missing/broken JSON leaves the previous behaviour intact.
    """
    if not numeric_cols_cleaned:
        return 0
    cfg = fn344_load_chart_value_defaults()
    settings = cfg.get("settings") or {}
    if not cfg or not settings.get("enabled", True):
        return fallback_index

    try:
        min_cov = int(settings.get("min_coverage", 3))
    except Exception:
        min_cov = 3
    group_col = settings.get("group_by_column") or "D__ProductType_ENG"

    from .lib_data import fn125_get_original_column_name

    # cleaned selectbox entries → original parquet column names
    by_original: dict[str, str] = {}
    for cleaned in numeric_cols_cleaned:
        try:
            by_original.setdefault(fn125_get_original_column_name(df, cleaned), cleaned)
        except Exception:
            continue

    ptype = fn345_dominant_product_type(df, group_col)
    entry = (cfg.get("by_product_type") or {}).get(ptype) or {}
    candidates = list(entry.get("value_columns") or [])
    candidates += list((cfg.get("global_default") or {}).get("value_columns") or [])

    def _coverage(original: str) -> int:
        try:
            return int(pd.to_numeric(df[original], errors="coerce").notna().sum())
        except Exception:
            return -1

    # Selectable candidates, preference order preserved.
    usable = [
        (o, by_original[o]) for o in candidates
        if o in by_original and o in getattr(df, "columns", [])
    ]

    # Prefer well-populated columns; then any data at all; then the configured
    # first choice even when empty — a semantically right axis beats an arbitrary
    # positional default for sparse product types.
    for threshold in (min_cov, 1):
        for original, cleaned in usable:
            if _coverage(original) >= threshold:
                return numeric_cols_cleaned.index(cleaned)
    if usable:
        return numeric_cols_cleaned.index(usable[0][1])

    return fallback_index if 0 <= fallback_index < len(numeric_cols_cleaned) else 0


# ── CSS helpers ───────────────────────────────────────────────────────────────
def _css_size_token(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    lower = s.lower()
    if lower.endswith(("px", "em", "rem", "vh", "vw", "%")):
        return s
    try:
        float(s)
        return f"{s}px"
    except ValueError:
        return s


# fn301 – fn311  Widget / filter functions (from fn_libs.py)
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(max_entries=64)   # one entry per distinct subset — was unbounded
def fn301_get_unique_sorted_values(series):
    """Return unique sorted non-empty values from a Series."""
    vals = []
    try:
        for v in series.dropna().unique().tolist():
            s = str(v).strip()
            if s == "" or s == "-" or s.lower() == "nan":
                continue
            if s.startswith("*"):
                continue
            vals.append(v)
    except Exception:
        try:
            vals = [v for v in series.dropna().unique().tolist()]
        except Exception:
            vals = []
    return sorted(vals, key=lambda x: str(x).strip().lower())


def _fn302_tv(column: str, value) -> str:
    """Translated display text for a dataset value, falling back to the raw one."""
    try:
        from libs.lib_i18n import fn708_translate_value
        return fn708_translate_value(column, value)
    except Exception:
        return "" if value is None else str(value).strip()


def _fn302_t(key: str, fallback: str, **fmt) -> str:
    """Translated sidebar string, falling back to the English literal (fn704)."""
    try:
        from libs.lib_i18n import fn704_t
        return fn704_t(key, fallback, **fmt)
    except Exception:
        return fallback


def _fn302_tu(text: str, **fmt) -> str:
    """Translated in-page control string, keyed by the English literal (fn714)."""
    try:
        from libs.lib_i18n import fn714_tu
        return fn714_tu(text, **fmt)
    except Exception:
        return text.format(**fmt) if fmt else text


def fn302_render_filter_widgets(df, all_cols, default_cols=None, default_vals=None):
    """Sidebar filter toggles + selectboxes (3 filters)."""
    # Honour a queued "Clear all" from a page's active-filters strip. This has to
    # happen here, before the toggles exist, because Streamlit forbids writing a
    # widget's key once the widget has been instantiated in the same run.
    fn355_apply_pending_filter_reset()

    df_filtered = df

    def _strip_prefix(col_name: str) -> str:
        try:
            return re.sub(r"^[A-Za-z]__", "", str(col_name).strip())
        except Exception:
            return str(col_name)

    def _display_col(col_name: str) -> str:
        # Translated field name when the catalogue has one (fn703). The English
        # fallback is _fn355_column_label — the same human label the active-filter
        # chips use — rather than this function's original bare _strip_prefix,
        # which left the dropdown reading "ProductType_ENG" next to a chip
        # saying "Product Type". _strip_prefix remains the last resort.
        try:
            return _fn355_column_label(col_name)
        except Exception:
            return _strip_prefix(col_name)

    configured_cols = []
    try:
        configured_cols = st.session_state.get("FILTER_WIDGET_COLUMNS", []) or []
    except Exception:
        configured_cols = []

    if configured_cols:
        eligible_cols = [
            c for c in configured_cols
            if c in all_cols and c not in HIDDEN_APP_COLUMNS and not str(c).strip().startswith("*")
        ]
    else:
        eligible_cols = [
            col for col in all_cols
            if col.startswith(("A__", "B__", "D__", "G__", "P__", "R__", "VO__", "VV__", "V__"))
            and col not in HIDDEN_APP_COLUMNS
            and not str(col).strip().startswith("*")
        ]
    if not eligible_cols:
        st.sidebar.warning(_fn302_t("no_eligible_columns", "No eligible columns available for filters."))
        st.session_state["FILTERED_DATA"] = df_filtered
        return df_filtered

    if default_cols is None:
        cfg_defaults = []
        try:
            cfg_defaults = st.session_state.get("FILTER_WIDGET_DEFAULT_COLS", []) or []
        except Exception:
            cfg_defaults = []
        default_cols = [c for c in cfg_defaults if c in eligible_cols]
        if len(default_cols) < 3:
            for i in range(3 - len(default_cols)):
                default_cols.append(eligible_cols[min(i, len(eligible_cols) - 1)])
    if default_vals is None:
        default_vals = [None, None, None]

    filtered_snapshots = [df]

    # The two selectboxes below show *translated* option text. Streamlit's
    # frontend keeps a selectbox's displayed label while the widget identity is
    # unchanged, so after a language flip the label stayed in the old language
    # until that widget was next touched. Scoping the widget key by language
    # gives the new language a fresh widget; the canonical `filter_col_{i}` /
    # `filter_val_{i}` keys are mirrored from it right after, because those are
    # what the chips (fn355), the Charts page and lib_data all read.
    try:
        from libs.lib_i18n import fn702_current_language
        _lang_suffix = f"__{fn702_current_language()}"
    except Exception:
        _lang_suffix = ""

    for i in range(1, 4):
        enable_key = f"enable_filter_{i}"
        col_state  = f"filter_col_{i}"
        val_state  = f"filter_val_{i}"
        col_key    = f"{col_state}{_lang_suffix}"
        val_key    = f"{val_state}{_lang_suffix}"

        def _carried(widget_key: str, canonical_key: str, fallback):
            """
            Current selection for a language-scoped widget.

            On the first run in a new language the widget key does not exist
            yet, so fall back to the canonical key — the selection the user had
            before the flip — and only then to ``fallback``.
            """
            if widget_key in st.session_state:
                return st.session_state[widget_key]
            if canonical_key in st.session_state:
                return st.session_state[canonical_key]
            return fallback

        # All three filters start OFF. The app previously opened with Dataset
        # Filter 1 enabled and silently pinned to the first available value, so
        # a first-time user's first view was a narrowed subset with nothing on
        # screen explaining why (and any ?open_product deep link missed).
        # Active filters are now surfaced by fn355_render_active_filters().
        # Init via session state only — do not also pass value= (Streamlit warns).
        if enable_key not in st.session_state:
            st.session_state[enable_key] = False

        enable = st.sidebar.toggle(
            _fn302_t("dataset_filter", f"Dataset Filter {i}", i=i),
            key=enable_key
        )

        if enable:
            current_df  = filtered_snapshots[-1]
            default_col = default_cols[i - 1]
            if i == 1:
                _col1_cfg = FILTER_WIDGET_SETTINGS.get("column_1_options") or []
                col_options = [c for c in _col1_cfg if c in all_cols]
                if not col_options:
                    col_options = [
                        c for c in (
                            "D__ProductType_ENG",
                            "D__MaterialType_ENG",
                            "A__Manufacturer",
                            "E__ManuCountry",
                        )
                        if c in all_cols
                    ]
            else:
                col_options = eligible_cols
            col_value = _carried(col_key, col_state, default_col)
            if col_value not in col_options:
                col_value = default_col if default_col in col_options else col_options[0]
            # Session state owns the default — do not also pass index= (Streamlit warns).
            st.session_state[col_key] = col_value

            filter_col = st.sidebar.selectbox(
                _fn302_t("filter_column", f"Filter Column {i}", i=i),
                col_options,
                key=col_key,
                format_func=_display_col,
            )
            st.session_state[col_state] = filter_col

            if filter_col == "D__ProductType_ENG" and "A__Map_yn" in current_df.columns:
                try:
                    _map_mask = current_df["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"
                    options   = fn301_get_unique_sorted_values(current_df.loc[_map_mask, filter_col])
                except Exception:
                    options = fn301_get_unique_sorted_values(current_df[filter_col])
            else:
                options = fn301_get_unique_sorted_values(current_df[filter_col])

            if not options:
                st.sidebar.warning(_fn302_t(
                    "no_options_found",
                    f"No options found in column '{filter_col}'. Skipping filter {i}.",
                    col=filter_col, i=i,
                ))
                continue

            # Prefer configured Product Type default (Floor (Tiles)) when that column is active.
            preferred = None
            if filter_col == "D__ProductType_ENG":
                preferred = str(
                    FILTER_WIDGET_SETTINGS.get("product_type_default_value") or "Floor (Tiles)"
                ).strip()
                if preferred not in options:
                    preferred = None

            configured = default_vals[i - 1]
            if configured in options:
                default_val = configured
            elif preferred is not None:
                default_val = preferred
            else:
                default_val = options[0]

            # Before the widget: settle on the starting value and write it to
            # the widget key. Setting session state (not index=) is required —
            # Streamlit's frontend keeps the selection it already shows for an
            # existing widget, so a value that went stale (after switching
            # Filter Column, or carried over from the other language) stays on
            # screen unless the session value says otherwise. Do not also pass
            # index=: Streamlit warns when both are set for the same key.
            val_value = _carried(val_key, val_state, default_val)
            if val_value not in options:
                val_value = default_val
            st.session_state[val_key] = val_value

            def _format_option(opt):
                try:
                    s = str(opt).strip()
                except Exception:
                    s = ""
                if filter_col == "D__ProductType_ENG" and s.lower().startswith("in situ"):
                    s = "In situ Concrete"
                # Display only — the selectbox's value stays the English one
                # the data is filtered on (fn708).
                return _fn302_tv(filter_col, s)

            filter_val = st.sidebar.selectbox(
                _fn302_t("filter_value", f"Value for Filter {i}", i=i),
                options,
                key=val_key,
                format_func=_format_option,
            )
            st.session_state[val_state] = filter_val

            df_filtered = current_df[current_df[filter_col] == filter_val]
            filtered_snapshots.append(df_filtered)

    st.session_state["FILTERED_DATA"] = df_filtered
    return df_filtered


def fn303_custom_hr():
    """CSS horizontal rule with negative margin.

    The ``.hr-line`` rule is sent once per script run (fn351 guard): this is
    called several times per run (twice in the app.py sidebar, more on Charts),
    and each call used to append another copy of the same <style> block.
    """
    if fn351_once_per_run("custom_hr_css"):
        st.markdown("""
        <style>
            .hr-line {
                margin-top: -5px;
                margin-bottom: -10px;
                padding: 0px;
                height: 1px;
                border: none;
                background-color: #ccc;
            }
        </style>
        """, unsafe_allow_html=True)
    st.markdown('<div class="hr-line"></div>', unsafe_allow_html=True)


def _horizontal_divider_css_len(value, fallback: str) -> str:
    """Normalise a length token to a CSS length string."""
    if value is None or str(value).strip() == "":
        return fallback
    s = str(value).strip()
    if s.endswith(("%", "px", "rem", "em", "vh", "vw")):
        return s
    try:
        float(s)
        return f"{s}px"
    except (TypeError, ValueError):
        return s


def horizontal_divider_html(
    *,
    width: str | None = None,
    thickness: str | None = None,
    color: str | None = None,
    margin_top: str | None = None,
    margin_bottom: str | None = None,
    align: str | None = None,
    preset: str | None = None,
    height: str | None = None,
) -> str:
    """Build HTML for an in-content horizontal divider (no Streamlit call).

    Defaults and named presets live in ``theme.json → chrome.horizontal_divider``.
    Any keyword overrides the theme / preset value for that property.
    ``height`` is accepted as an alias of ``thickness`` (legacy ``fn304``).
    """
    from libs.lib_tokens import theme_section

    root = theme_section("chrome", "horizontal_divider") or {}
    cfg: dict = {
        k: v for k, v in root.items()
        if not str(k).startswith("_") and k != "presets"
    }
    if preset:
        presets = root.get("presets") or {}
        slot = presets.get(str(preset)) or {}
        if isinstance(slot, dict):
            cfg.update({
                k: v for k, v in slot.items() if not str(k).startswith("_")
            })

    def _pick(override, *keys, default):
        if override is not None and str(override).strip() != "":
            return override
        for key in keys:
            val = cfg.get(key)
            if val is not None and str(val).strip() != "":
                return val
        return default

    _thickness = _pick(thickness if thickness is not None else height,
                       "thickness", "height", default="1.5px")
    _width = _pick(width, "width", default="60%")
    _color = _pick(color, "color", default="#2a7d2e")
    _mt = _pick(margin_top, "margin_top", default="12px")
    _mb = _pick(margin_bottom, "margin_bottom", default="12px")
    _align = str(_pick(align, "align", default="left")).strip().lower()
    ml, mr = {
        "left": ("0", "auto"),
        "right": ("auto", "0"),
    }.get(_align, ("auto", "auto"))  # centre

    return (
        f"<div class='eetra-h-divider' role='separator' "
        f"style='height:{_horizontal_divider_css_len(_thickness, '1.5px')};"
        f"width:{_horizontal_divider_css_len(_width, '60%')};"
        f"background:{_color};border:none;"
        f"margin-top:{_horizontal_divider_css_len(_mt, '12px')};"
        f"margin-bottom:{_horizontal_divider_css_len(_mb, '12px')};"
        f"margin-left:{ml};margin-right:{mr};'></div>"
    )


def render_horizontal_divider(
    *,
    width: str | None = None,
    thickness: str | None = None,
    color: str | None = None,
    margin_top: str | None = None,
    margin_bottom: str | None = None,
    align: str | None = None,
    preset: str | None = None,
    height: str | None = None,
) -> None:
    """App-wide customisable horizontal divider (length, colour, thickness, spacing).

    Configure defaults / presets in ``theme.json → chrome.horizontal_divider``.
    Override any property per call, or pass ``preset="…"`` for a named style.

    Example::

        render_horizontal_divider()
        render_horizontal_divider(preset="add_edit_before_product_info")
        render_horizontal_divider(width="40%", color="#94a3b8", thickness="2px",
                                  margin_top="8px", margin_bottom="8px", align="center")
    """
    st.markdown(
        horizontal_divider_html(
            width=width,
            thickness=thickness,
            color=color,
            margin_top=margin_top,
            margin_bottom=margin_bottom,
            align=align,
            preset=preset,
            height=height,
        ),
        unsafe_allow_html=True,
    )


def render_add_edit_section_title_with_divider(
    title: str,
    *,
    margin_top: str | None = None,
) -> None:
    """Light-grey full-width rule above an Add/Edit section label (all-caps).

    Layout: white space → full-width light-grey divider → tight gap → all-caps
    title in the same grey as the rule. One markdown block so tab-panel row-gap
    does not inflate spacing. Lives in ``lib_ui`` so ``fn354_run_embedded_page``
    resolves it via star-import even with a stale page bytecode cache.
    """
    _mt = "20px" if margin_top is None else str(margin_top)
    st.markdown(
        horizontal_divider_html(
            width="100%",
            thickness="1px",
            color="#d1d5db",
            margin_top=_mt,
            margin_bottom="2px",
            align="left",
            preset="add_edit_section_above_title",
        )
        + f'<h5 class="add-edit-section-serif-title">'
        f'{_html.escape(_fn302_tu(str(title)))}</h5>',
        unsafe_allow_html=True,
    )


def fn304_slim_divider(
    width: str | None = None,
    height: str | None = None,
    color: str | None = None,
    margin_top: str | None = None,
    margin_bottom: str | None = None,
    *,
    thickness: str | None = None,
    align: str | None = None,
    preset: str | None = None,
):
    """Thin configurable horizontal divider — alias of ``render_horizontal_divider``."""
    render_horizontal_divider(
        width=width,
        thickness=thickness,
        color=color,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        align=align,
        preset=preset,
        height=height,
    )


def fn305_group_by_column(df, group_col, value_col, aggfunc="sum"):
    """DataFrame group-by aggregation."""
    df = df.copy()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=[value_col])
    if aggfunc == "sum":
        grouped = df.groupby(group_col)[value_col].sum().reset_index()
    elif aggfunc == "count":
        grouped = df.groupby(group_col)[value_col].count().reset_index()
    elif aggfunc == "mean":
        grouped = df.groupby(group_col)[value_col].mean().reset_index()
    else:
        raise ValueError("Unsupported aggregation function")
    return grouped.sort_values(by=value_col, ascending=True)


def fn306_render_filter_widgets_clean(df, all_cols, default_cols=None, default_vals=None):
    """Filter widgets with cleaned column names."""
    df_filtered = df.copy()
    eligible_cols = [
        col for col in all_cols
        if col.startswith(("A__", "B__", "D__", "P__", "G__FU")) and col not in HIDDEN_APP_COLUMNS
    ]
    cleaned_cols  = [fn128_clean_column_name(col) for col in eligible_cols]
    col_mapping   = {cleaned: original for cleaned, original in zip(cleaned_cols, eligible_cols)}
    _disp_labels = st.session_state.get("COLUMN_DISPLAY_LABELS") or {}

    if default_cols is None:
        default_cols = [eligible_cols[min(i, len(eligible_cols) - 1)] for i in range(3)]
    if default_vals is None:
        default_vals = [None, None, None]

    filtered_snapshots = [df.copy()]

    for i in range(1, 4):
        enable_key = f"enable_filter_{i}"
        col_key    = f"filter_col_{i}"
        val_key    = f"filter_val_{i}"

        enable_default = True if i == 1 else False
        enable_value   = st.session_state.get(enable_key, enable_default)
        enable = st.sidebar.toggle(f"Enable Dataset Filter {i}", value=enable_value, key=enable_key)

        if enable:
            current_df     = filtered_snapshots[-1]
            default_col    = default_cols[i - 1]
            default_cleaned = fn128_clean_column_name(default_col)
            col_value      = st.session_state.get(col_key, default_cleaned)
            col_index      = cleaned_cols.index(col_value) if col_value in cleaned_cols else 0

            filter_col_cleaned = st.sidebar.selectbox(
                _fn302_t("filter_column", f"Filter Column {i}", i=i),
                cleaned_cols,
                index=col_index,
                key=col_key,
                format_func=lambda c, _m=col_mapping, _lbl=_disp_labels: fn128a_display_label_for_original(
                    _m.get(c, c), _lbl
                ),
            )
            filter_col = col_mapping.get(filter_col_cleaned)
            if not filter_col:
                continue

            options = fn301_get_unique_sorted_values(current_df[filter_col])
            if not options:
                st.sidebar.warning(f"No options found in column '{filter_col_cleaned}'. Skipping filter {i}.")
                continue

            default_val = default_vals[i - 1] if default_vals[i - 1] in options else options[0]
            val_value   = st.session_state.get(val_key, default_val)
            val_index   = options.index(val_value) if val_value in options else 0

            filter_val = st.sidebar.selectbox(
                _fn302_t("filter_value", f"Value for Filter {i}", i=i), options, index=val_index, key=val_key
            )
            df_filtered = current_df[current_df[filter_col] == filter_val]
            filtered_snapshots.append(df_filtered)

    st.session_state["FILTERED_DATA"] = df_filtered
    return df_filtered


def fn307_custom_hr_compact():
    """Compact horizontal rule."""
    st.markdown("""
        <style>.hr-line-compact { margin-top: -5px; margin-bottom: -5px; }</style>
    """, unsafe_allow_html=True)
    st.markdown('<hr class="hr-line-compact">', unsafe_allow_html=True)


def fn308_import_certification_table(csv_path="certification_df.csv"):
    """Load certification table from CSV."""
    return pd.read_csv(csv_path)


def fn309_create_checkboxes_in_columns(df, column_name, n_columns):
    """Create grouped checkboxes displayed in top-to-bottom columns."""
    sorted_items = sorted(df[column_name])
    n_rows       = -(-len(sorted_items) // n_columns)
    columns      = st.columns(n_columns)
    selected_items = []
    for col_index in range(n_columns):
        with columns[col_index]:
            for row_index in range(n_rows):
                item_index = col_index * n_rows + row_index
                if item_index < len(sorted_items):
                    item = sorted_items[item_index]
                    if st.checkbox(item):
                        selected_items.append(item)
    return selected_items


def fn310_create_input_lifecycle_gwp():
    """Render grouped number inputs for lifecycle GWP values."""
    col_width = [3] + [2] * 17
    stages = ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5", "B6", "B7",
              "C1", "C2", "C3", "C4", "D"]
    results = []
    for gwp_type, label in [("t", "GWP Total"), ("f", "GWP Fossil"),
                             ("b", "GWP Biogenic"), ("l", "GWP LULUC")]:
        cols = st.columns(col_width)
        cols[0].markdown(" ")
        cols[0].markdown(" ")
        cols[0].markdown(f"###### {label}")
        inputs = [cols[i + 1].number_input(f"{s}-{gwp_type}", format="%0.4f")
                  for i, s in enumerate(stages)]
        results.append(inputs)
    return tuple(results)


def fn311_apply_dataframe_filters(df, max_filters=3):
    """Inline (non-sidebar) filter widgets."""
    df_filtered = df.copy()
    for i in range(max_filters):
        with st.container():
            cols = st.columns([1, 2])
            with cols[0]:
                filter_col = st.selectbox(
                    f"Filter {i+1}: Column",
                    options=[None] + list(df_filtered.columns),
                    key=f"filter_col_{i}"
                )
            if filter_col:
                unique_vals = sorted(df_filtered[filter_col].dropna().unique())
                with cols[1]:
                    filter_val = st.selectbox(
                        f"Filter {i+1}: Value",
                        options=[None] + unique_vals,
                        key=f"filter_val_{i}"
                    )
                if filter_val is not None:
                    df_filtered = df_filtered[df_filtered[filter_col] == filter_val]
    return df_filtered


# ════════════════════════════════════════════════════════════════════════════
# fn312 – fn334  UI config / product card functions (from fn_ui.py)
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(max_entries=4)
def fn312_get_manufacturer_logo_mapping(mapping_path: str = "aux_10__ui_config.json"):
    """Return normalized manufacturer → logo path mapping."""
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s).strip()).lower()

    raw = None
    try:
        raw = st.session_state.get("MANUFACTURER_LOGOS")
    except Exception:
        raw = None
    if not isinstance(raw, dict) or not raw:
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("manufacturer_logos", data) if isinstance(data, dict) else data
        except Exception:
            raw = {}
    if isinstance(raw, dict):
        return {_norm(k): v for k, v in raw.items()}
    return {}


def fn313_get_manufacturer_color_mapping(mapping_path: str = "aux_10__ui_config.json"):
    """Return normalized manufacturer → hex color mapping."""
    colors = {}
    data   = None
    try:
        data = st.session_state.get("MANUFACTURER_LOGOS")
    except Exception:
        data = None
    if not isinstance(data, dict) or not data:
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload.get("manufacturer_logos", payload) if isinstance(payload, dict) else payload
        except Exception as e:
            data = None
            print(f"Error reading colors from {mapping_path}: {e}")
    if isinstance(data, dict):
        for name, meta in data.items():
            key = re.sub(r"\s+", " ", str(name).strip()).lower()
            hex_color = meta.get("color")
            if hex_color and isinstance(hex_color, str):
                if not hex_color.startswith("#"):
                    hex_color = f"#{hex_color}"
                colors[key] = hex_color
            else:
                path = meta.get("logo_path")
                if path:
                    color_hex = fn314_extract_dominant_color(path)
                    if color_hex:
                        colors[key] = color_hex
    return colors


def fn314_extract_dominant_color(image_path: str) -> str | None:
    """Extract dominant non-white color from a logo image → #RRGGBB."""
    try:
        candidate = Path(image_path)
        if not candidate.exists():
            candidate = Path(__file__).resolve().parent.joinpath(image_path)
        p = str(candidate)
        if p.lower().endswith(".svg"):
            return None
        img    = Image.open(p).convert("RGBA")
        img    = img.resize((64, 64), Image.LANCZOS)
        pixels = list(img.getdata())
        counts = {}
        for r, g, b, a in pixels:
            if a < 128:
                continue
            if r > 230 and g > 230 and b > 230:
                continue
            key = (r, g, b)
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return None
        (r, g, b), _ = max(counts.items(), key=lambda kv: kv[1])
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception as e:
        print(f"Failed to extract color from {image_path}: {e}")
        return None


def fn315_normalize_product_type(value):
    """Normalise D__ProductType_ENG strings."""
    from .lib_data import canonical_product_type

    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text       = str(value).strip()
    normalized = canonical_product_type(text)
    normalized_lower = normalized.lower()
    key_map = {}
    try:
        key_map = st.session_state.get("FIELD_VISIBILITY_KEY_MAP", {}) or {}
    except Exception:
        key_map = {}
    if normalized_lower in key_map:
        return key_map[normalized_lower]
    return normalized


def fn316_make_session_key_fragment(value):
    """Create a safe fragment for Streamlit session keys."""
    if not value:
        return "default"
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).lower()).strip("_")
    return safe or "default"


def fn317_get_field_visibility(product_type, detail_level="Compact"):
    """Get field visibility settings for a given product type and detail level."""
    fv       = st.session_state.get("FIELD_VISIBILITY")
    fv_index = st.session_state.get("FIELD_VISIBILITY_INDEX", {})
    fv_key_map = st.session_state.get("FIELD_VISIBILITY_KEY_MAP", {})
    if fv is None:
        try:
            with open("aux_10__ui_config.json", "r", encoding="utf-8") as f:
                payload = json.load(f)
            fv = payload.get("field_visibility", {})
        except Exception:
            fv = {"default": {}}
    if not fv_index and isinstance(fv, dict):
        fv_index = {key.lower(): value for key, value in fv.items()}
    if not fv_key_map and isinstance(fv, dict):
        fv_key_map = {key.lower(): key for key in fv.keys()}
    if product_type is None:
        product_type_normalized = ""
    else:
        text = str(product_type).strip()
        product_type_normalized = fv_key_map.get(text.lower(), text)
    product_config = fv.get(product_type_normalized)
    if product_config is None:
        product_config = fv_index.get(str(product_type_normalized).lower(), fv.get("default", {}))
    if isinstance(product_config, dict) and detail_level in product_config:
        visibility = product_config[detail_level]
    else:
        visibility = product_config
    if not isinstance(visibility, dict):
        visibility = {}
    try:
        pt = "" if product_type is None else str(product_type).strip().lower()
        if "tile" in pt or "tiles" in pt:
            visibility = dict(visibility)
            visibility["Fire rating"] = False
            visibility["Conductivity (ʎ)"] = False
            visibility["U-value"] = False
        elif "rebar" in pt or "steel" in pt:
            visibility = dict(visibility)
            visibility["Conductivity (ʎ)"] = False
            visibility["U-value"] = False
        elif "framing" in pt:
            visibility = dict(visibility)
            visibility["Fire rating"] = False
    except Exception:
        pass
    return visibility


def fn318_get_tabular_column_visibility(product_type):
    """Get tabular column visibility settings for a given product type."""
    tcv = st.session_state.get("TABULAR_COLUMN_VISIBILITY")
    if tcv is None:
        try:
            with open("aux_10__ui_config.json", "r", encoding="utf-8") as f:
                payload = json.load(f)
            tcv = payload.get("tabular_column_visibility", {})
        except Exception:
            tcv = {"default": {}}
    return tcv.get(product_type, tcv.get("default", {}))


def fn319_filter_columns_by_visibility(columns, prefix, product_type):
    """Filter a list of columns based on visibility settings for the product type."""
    visibility_config = fn318_get_tabular_column_visibility(product_type)
    if prefix not in visibility_config:
        return columns
    prefix_config = visibility_config[prefix]
    return [col for col in columns if prefix_config.get(col, True)]


def fn320_round_numeric_columns(df, decimal_places=2):
    """Round numeric columns in a DataFrame to specified decimal places."""
    df_rounded = df.copy()
    try:
        numeric_cols = df_rounded.select_dtypes(
            include=["float64", "float32", "int64", "int32"]
        ).columns
    except Exception:
        numeric_cols = []
    for col in numeric_cols:
        try:
            df_rounded[col] = pd.to_numeric(df_rounded[col], errors="coerce").round(decimal_places)
        except Exception:
            continue
    return df_rounded


def fn321_get_column_completeness_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-column completeness stats."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["column", "dtype", "rows_total", "rows_non_empty",
                                     "rows_empty", "empty_pct"])
    rows_total = int(len(df))
    out_rows = []
    for col in df.columns:
        s          = df[col]
        empty_mask = s.isna() | (s.astype(str).str.strip() == "") | (s.astype(str).str.strip() == "-")
        rows_empty    = int(empty_mask.sum())
        rows_non_empty = rows_total - rows_empty
        empty_pct  = (rows_empty / rows_total * 100.0) if rows_total else 0.0
        out_rows.append({
            "column": col, "dtype": str(s.dtype), "rows_total": rows_total,
            "rows_non_empty": rows_non_empty, "rows_empty": rows_empty,
            "empty_pct": round(empty_pct, 2),
        })
    return pd.DataFrame(out_rows).sort_values(["empty_pct", "column"], ascending=[False, True])


def fn322_get_value_counts_for_treemap(
    df: pd.DataFrame, column: str, top_n: int | None = 30,
    include_empty: bool = True, include_na: bool = True,
    include_nr: bool = True, include_symbols: bool = True,
) -> pd.DataFrame:
    """Return value counts for a column, capped to top_n with an 'Other' bucket."""
    if df is None or df.empty or not column or column not in df.columns:
        return pd.DataFrame(columns=["value", "count"])
    s  = df[column]
    s2 = s.copy()
    empty_mask   = s2.isna() | (s2.astype(str).str.strip() == "") | (s2.astype(str).str.strip() == "-")
    s_norm       = s2.astype(str).str.strip().str.lower()
    na_mask      = s_norm.isin(["n/a", "n\\a", "na"])
    nr_mask      = s_norm.isin(["n/r", "n\\r", "nr"])
    s_str        = s2.astype(str).str.strip()
    symbols_mask = (s_str.str.len() == 1) & (~s_str.str.isalnum()) & (~empty_mask) & (~na_mask) & (~nr_mask)

    exclude_mask = pd.Series(False, index=s2.index)
    if not include_na:
        exclude_mask = exclude_mask | na_mask
    if not include_nr:
        exclude_mask = exclude_mask | nr_mask
    if not include_symbols:
        exclude_mask = exclude_mask | symbols_mask
    if exclude_mask.any():
        s2 = s2[~exclude_mask]
        empty_mask   = empty_mask[~exclude_mask]
        na_mask      = na_mask[~exclude_mask]
        nr_mask      = nr_mask[~exclude_mask]
        symbols_mask = symbols_mask[~exclude_mask]

    if include_empty:
        s2 = s2.astype(object)
        s2[empty_mask] = "(empty)"
    else:
        s2 = s2[~empty_mask]

    try:
        s2 = s2.astype(object)
        if include_na:
            s2[na_mask] = "(n/a)"
        if include_nr:
            s2[nr_mask] = "(n/r)"
        if include_symbols:
            s2[symbols_mask] = "(symbols)"
    except Exception:
        pass

    expanded_values = []
    for val in s2.astype(str):
        if ";" in val:
            expanded_values.extend([part.strip() for part in val.split(";") if part.strip()])
        else:
            expanded_values.append(val)

    s_expanded = pd.Series(expanded_values)
    vc = s_expanded.value_counts(dropna=False).sort_values(ascending=False)
    if top_n is not None and top_n > 0 and len(vc) > top_n:
        top   = vc.iloc[:top_n]
        other = int(vc.iloc[top_n:].sum())
        vc    = top
        vc.loc["Other"] = other
        vc = vc.sort_values(ascending=False)
    return pd.DataFrame({"value": vc.index.astype(str).tolist(), "count": vc.values.astype(int).tolist()})


def _fn322_cell_sector_labels(
    raw,
    *,
    include_empty: bool,
    include_na: bool,
    include_nr: bool,
    include_symbols: bool,
) -> list[str]:
    """Labels a single cell contributes to the treemap (mirrors fn322 rules)."""
    try:
        is_missing = raw is None or bool(pd.isna(raw))
    except (TypeError, ValueError):
        is_missing = False
    if is_missing:
        return ["(empty)"] if include_empty else []
    text = str(raw).strip()
    if not text or text == "-":
        return ["(empty)"] if include_empty else []
    low = text.lower()
    if low in ("n/a", "n\\a", "na"):
        return ["(n/a)"] if include_na else []
    if low in ("n/r", "n\\r", "nr"):
        return ["(n/r)"] if include_nr else []
    if len(text) == 1 and not text.isalnum():
        return ["(symbols)"] if include_symbols else []
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [text]


def fn322a_rows_matching_treemap_value(
    df: pd.DataFrame,
    column: str,
    value: str,
    *,
    include_empty: bool = True,
    include_na: bool = True,
    include_nr: bool = True,
    include_symbols: bool = True,
) -> pd.DataFrame:
    """Rows that feed a treemap sector for *column* / *value* (same rules as fn322).

    Semicolon-separated cells match if any part equals *value*. Special buckets
    ``(empty)``, ``(n/a)``, ``(n/r)``, ``(symbols)`` reverse the labelling in
    :func:`fn322_get_value_counts_for_treemap`. The aggregate ``Other`` bucket
    cannot be expanded and returns an empty frame.
    """
    if (
        df is None
        or df.empty
        or not column
        or column not in df.columns
        or value is None
        or str(value).strip() == ""
        or str(value).strip() == "Other"
    ):
        return df.iloc[0:0].copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    target = str(value).strip()
    mask = df[column].map(
        lambda v: target
        in _fn322_cell_sector_labels(
            v,
            include_empty=include_empty,
            include_na=include_na,
            include_nr=include_nr,
            include_symbols=include_symbols,
        )
    )
    return df.loc[mask].copy()


FN343_VALUE_CATEGORIES = ["empty", "n/r", "n/a", "zero", "value"]
FN343_CATEGORY_COLORS = {
    "empty": "#ebedf0",  # no data at all (blank/NaN/"-")
    "n/r":   "#b0b0b0",  # not relevant
    "n/a":   "#f1c40f",  # not available
    "zero":  "#9be9a8",  # numeric zero (github "light" green)
    "value": "#196127",  # populated number/text (github "dark" green)
}
FN343_CATEGORY_LABELS = {
    "empty": "Empty",
    "n/r":   "n/r (not relevant)",
    "n/a":   "n/a (not available)",
    "zero":  "Zero value",
    "value": "Has a value",
}


def fn343_get_value_category_matrix(df: pd.DataFrame, columns: list, id_col: str | None = None) -> pd.DataFrame:
    """Classify each cell into one of FN343_VALUE_CATEGORIES: empty, n/r, n/a, zero, value.

    Row index is id_col's values when provided and unique, otherwise the row position.
    """
    if df is None or df.empty or not columns:
        return pd.DataFrame()
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return pd.DataFrame()

    def _categorize(series: pd.Series) -> pd.Series:
        stripped = series.astype(str).str.strip()
        lower = stripped.str.lower()
        empty_mask = series.isna() | (stripped == "") | (stripped == "-")
        nr_mask = lower.isin(["n/r", "n\\r", "nr"])
        na_mask = lower.isin(["n/a", "n\\a", "na"])
        numeric = pd.to_numeric(stripped, errors="coerce")
        zero_mask = (~empty_mask) & (~nr_mask) & (~na_mask) & numeric.notna() & (numeric == 0)

        cat = pd.Series("value", index=series.index)
        cat[empty_mask] = "empty"
        cat[nr_mask] = "n/r"
        cat[na_mask] = "n/a"
        cat[zero_mask] = "zero"
        return cat

    out = {col: _categorize(df[col]) for col in cols}
    matrix = pd.DataFrame(out)
    if id_col and id_col in df.columns and df[id_col].is_unique:
        matrix.index = df[id_col].astype(str).values
    else:
        matrix.index = [str(i) for i in range(len(matrix))]
    return matrix


def fn344_build_dev_missmatrix_payload(
    df: pd.DataFrame,
    columns: list[str],
    *,
    id_col: str | None = "A__EETRA_ID",
    name_col: str = "A__ProductName",
    mfr_col: str = "A__Manufacturer",
    prefix_order: tuple[str, ...] = ("A__", "D__", "P__", "C__", "G__", "E__", "R__", "VO__", "VV__", "V__"),
    batch_size: int = 30,
) -> dict:
    """Build JSON payload for the Developer missing-data ECharts heatmap iframe."""
    import re as _re

    _prefix_re = _re.compile(r"^([A-Z]__)")
    columns = [c for c in columns if c not in HIDDEN_APP_COLUMNS]
    matrix = fn343_get_value_category_matrix(df, columns, id_col=id_col)
    if matrix.empty:
        return {}

    cat_to_code = {c: i for i, c in enumerate(FN343_VALUE_CATEGORIES)}
    dup_ids: set[str] = set()
    if id_col and id_col in df.columns:
        _vc = df[id_col].astype(str).value_counts()
        dup_ids = {str(k) for k in _vc[_vc > 1].index.tolist()}

    labels: list[str] = []
    seen_plain: dict[str, int] = {}
    for pos in range(len(df)):
        row = df.iloc[pos]
        name = str(row.get(name_col, "")).strip() if name_col in df.columns else ""
        mfr = str(row.get(mfr_col, "")).strip() if mfr_col in df.columns else ""
        eid = str(row.get(id_col, "")).strip() if id_col and id_col in df.columns else ""

        if eid in dup_ids:
            parts = [p for p in (name, mfr) if p and p != "-"]
            label = f"{' — '.join(parts)} ({eid})" if parts else eid
        elif not name or name == "-":
            label = eid or str(pos)
        else:
            label = name

        if label in seen_plain:
            seen_plain[label] += 1
            label = f"{label} #{seen_plain[label]}"
        else:
            seen_plain[label] = 1
        labels.append(label)

    prefix_groups: dict[str, list[str]] = {}
    for col in columns:
        m = _prefix_re.match(col)
        pfx = m.group(1) if m else "Other"
        prefix_groups.setdefault(pfx, []).append(col)

    ordered_prefixes = [p for p in prefix_order if prefix_groups.get(p)]
    ordered_prefixes.extend(sorted(p for p in prefix_groups if p not in prefix_order))

    groups: dict[str, dict] = {}
    for pfx in ordered_prefixes:
        cols = sorted(prefix_groups[pfx])
        fields = [_re.sub(r"^[A-Z]__", "", c) for c in cols]
        products = []
        for pos in range(len(matrix)):
            cells = [int(cat_to_code.get(matrix.iloc[pos][c], 0)) for c in cols]
            products.append({"label": labels[pos], "cells": cells})
        groups[pfx] = {"fields": fields, "products": products}

    return {
        "batchSize": int(batch_size),
        "prefixOrder": ordered_prefixes,
        "groups": groups,
        "categories": FN343_VALUE_CATEGORIES,
        "categoryColors": FN343_CATEGORY_COLORS,
        "categoryLabels": FN343_CATEGORY_LABELS,
        "totalProducts": len(matrix),
        "duplicateIds": sorted(dup_ids),
    }


def fn323_is_building_boards_selected():
    """True when 'Building boards' is selected for D__ProductType_ENG in any filter."""
    for i in range(1, 4):
        if st.session_state.get(f"enable_filter_{i}", False):
            filter_col = st.session_state.get(f"filter_col_{i}", "")
            filter_val = st.session_state.get(f"filter_val_{i}", "")
            if (filter_col == "D__ProductType_ENG"
                    and isinstance(filter_val, str)
                    and "building boards" in filter_val.lower()):
                return True
    return False


def fn324_get_val(row, col):
    """Get value from row, returning '-' if empty or NaN."""
    val = row.get(col, "")
    return "-" if pd.isna(val) or str(val).strip() == "" else str(val)


def fn324_get_val_first(row, *cols: str) -> str:
    """First non-empty value among ``cols`` (SharePoint renames / legacy headers)."""
    for col in cols:
        v = fn324_get_val(row, col)
        if v != "-":
            return v
    return "-"


def _row_cell_first(row: pd.Series, *cols: str) -> str:
    """First non-empty cell among column names (for pd.Series rows)."""
    for col in cols:
        if col not in row.index:
            continue
        v = row.get(col, "")
        if v is None or pd.isna(v):
            continue
        s = str(v).strip()
        if s and s not in ("-", "nan", "None"):
            return s
    return ""


def _tiles_gwp_fu_primary_line(fu_raw: str) -> str | None:
    """
    For **Tiles**, map ``G__GWP_FU`` (EPD declared functional unit) to the single
    catalogue line that carries the declared GWP: ``'m2'``, ``'m3'``, or ``'kg'``.
    """
    if fu_raw is None or str(fu_raw).strip() in ("", "-"):
        return None
    s = re.sub(r"\s+", " ", str(fu_raw).strip().lower())
    s_cmp = (
        s.replace("m²", "m2")
        .replace("m³", "m3")
        .replace("²", "2")
        .replace("³", "3")
    )
    if "m3" in s_cmp or "m^3" in s or "cbm" in s or s_cmp.endswith(" m3"):
        return "m3"
    if "m2" in s_cmp or "m^2" in s or "sqm" in s_cmp or "sq m" in s:
        return "m2"
    if "ton" in s or "tonne" in s or re.search(r"\b([0-9.]+\s*)?t\b", s_cmp):
        return "kg"
    if "kg" in s and "m2" not in s_cmp and "m3" not in s_cmp:
        return "kg"
    return None


def fn325_get_thickness_val(row):
    """Get thickness value with fallback to different column formats."""
    thickness_columns = ["P__Thick_mm", "P__Thickness_mm", "B__Thickness_mm",
                         "D__Thickness_mm", "A__Thickness_mm"]
    for col in thickness_columns:
        if col in row.index:
            val = fn324_get_val(row, col)
            if val != "-":
                return val
    return "-"


def fn326_format_recycling_rate(value):
    """Format recycling rate to 1 decimal place."""
    if value == "-" or pd.isna(value) or str(value).strip() == "":
        return "-"
    try:
        return f"{float(value):.1f}"
    except (ValueError, TypeError):
        return str(value)


# Inline SVG icons for technical-details row (stroke-only, matches catalogue monospace look).
_FN327_ICON_THERMAL_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' width='16' height='16' "
    "style='vertical-align:-0.25em;color:inherit' aria-hidden='true'>"
    "<g fill='none' stroke='currentColor' stroke-width='1.35' stroke-linecap='round'>"
    "<line x1='12' y1='3' x2='12' y2='21'/>"
    "<path d='M12 6 L8.5 8.5 M12 9.5 L7 10.5 M12 13 L8 14.5 M12 16.5 L9 18'/>"
    "<path d='M12 7 A5 5 0 0 1 12 17'/>"
    "<line x1='16.5' y1='6.5' x2='19' y2='4.5'/>"
    "<line x1='19.5' y1='12' x2='22.2' y2='12'/>"
    "<line x1='16.5' y1='17.5' x2='19' y2='19.5'/>"
    "</g></svg>"
)
_FN327_ICON_IMPACT_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' width='16' height='16' "
    "style='vertical-align:-0.25em;color:inherit' aria-hidden='true'>"
    "<g fill='none' stroke='currentColor' stroke-width='1.35' stroke-linecap='round' stroke-linejoin='round'>"
    "<line x1='2' y1='9' x2='5.5' y2='8.5'/><line x1='1.5' y1='12' x2='5.5' y2='12'/>"
    "<line x1='2' y1='15' x2='5.5' y2='15.5'/><line x1='3.5' y1='6.5' x2='6.5' y2='8'/>"
    "<line x1='3.5' y1='17.5' x2='6.5' y2='16'/><line x1='4.5' y1='10.5' x2='7' y2='9.5'/>"
    "<line x1='4.5' y1='13.5' x2='7' y2='14.5'/>"
    "<path d='M8.5 16.5c-.2-2.8.9-5.8 3-7.5 1-.8 2.4-.9 3.6-.3 1.4 1.4 2 3.7 1.9 6.7'/>"
    "<path d='M10.8 9.6 l0.3 2.2 2.8 -0.9 0.3 2.2'/><path d='M14 8.7 c1 0 1.8 0.6 1.9 1.6 v2.8'/>"
    "</g></svg>"
)


def fn327_parse_technical_details(tech_details_text):
    """Replace known technical-detail phrases with emoji or inline SVG; phrase in ``title`` (hover)."""
    if not tech_details_text or tech_details_text == "-" or pd.isna(tech_details_text):
        return ""
    icon_mappings = {
        "fire resistance":    {"icon": "🔥", "description": "Fire Resistance"},
        "fire resistant":     {"icon": "🔥", "description": "Fire Resistance"},
        "moisture-resistant": {"icon": "💧", "description": "Moisture-resistant"},
        "moisture resistant": {"icon": "💧", "description": "Moisture Resistant"},
        "moisture resistance": {"icon": "💧", "description": "Moisture Resistance"},
        "acoustic":           {"icon": "👂", "description": "Acoustic Properties"},
        "sound":              {"icon": "🔊", "description": "Sound Properties"},
        "active air":         {"icon": "🌬️", "description": "Active Air Properties"},
        "thermal resistance": {"icon": _FN327_ICON_THERMAL_SVG, "description": "Thermal resistance (cold & heat)"},
        "thermal":            {"icon": _FN327_ICON_THERMAL_SVG, "description": "Thermal resistance (cold & heat)"},
        "insulation":         {"icon": "🧱", "description": "Insulation Properties"},
        "impact resistance":  {"icon": _FN327_ICON_IMPACT_SVG, "description": "Impact / shock resistance"},
        "shock resistance":   {"icon": _FN327_ICON_IMPACT_SVG, "description": "Impact / shock resistance"},
        "shock resistant":    {"icon": _FN327_ICON_IMPACT_SVG, "description": "Impact / shock resistance"},
        "impact":             {"icon": _FN327_ICON_IMPACT_SVG, "description": "Impact / shock resistance"},
        "shock":              {"icon": _FN327_ICON_IMPACT_SVG, "description": "Impact / shock resistance"},
        "durable":            {"icon": "💪", "description": "Durability"},
        "waterproof":         {"icon": "🛡️", "description": "Waterproof"},
        "vapor":              {"icon": "💨", "description": "Vapor Properties"},
        "breathable":         {"icon": "🫁", "description": "Breathable"},
        "mold":               {"icon": "🦠", "description": "Mold Resistance"},
        "rot":                {"icon": "🍂", "description": "Rot Resistance"},
        "termite":            {"icon": "🐛", "description": "Termite Resistance"},
        "chemical":           {"icon": "🧪", "description": "Chemical Resistance"},
        "uv":                 {"icon": "☀️", "description": "UV Resistance"},
        "weather":            {"icon": "🌤️", "description": "Weather Resistance"},
    }
    text = str(tech_details_text).strip()
    if not text:
        return ""
    keys_longest_first = sorted(icon_mappings.keys(), key=len, reverse=True)
    pattern = "|".join(re.escape(k) for k in keys_longest_first)
    rx = re.compile(pattern, re.IGNORECASE)

    def _repl(m: re.Match) -> str:
        feat = icon_mappings.get(m.group(0).lower())
        if not feat:
            return m.group(0)
        tip = _html.escape(feat["description"], quote=True)
        _ico = feat["icon"]
        if isinstance(_ico, str) and _ico.lstrip().startswith("<svg"):
            _style = "display:inline-block;line-height:1;margin:0 2px;cursor:help;"
        else:
            _style = (
                "display:inline-block;font-size:16px;line-height:1;margin:0 1px;"
                "cursor:help;filter:grayscale(1);-webkit-filter:grayscale(1);"
            )
        return f'<span title="{tip}" style="{_style}">{_ico}</span>'

    return rx.sub(_repl, text)


def fn328_country_to_flag(country_value: str) -> str:
    """Return emoji flag for a given country code or name."""
    if not country_value or str(country_value).strip() == "-" or pd.isna(country_value):
        return ""
    text = str(country_value).strip()
    if len(text) == 2 and text.isalpha():
        code = text.upper()
        base = 127397
        try:
            return chr(ord(code[0]) + base) + chr(ord(code[1]) + base)
        except Exception:
            return ""
    name_to_code = {
        "italy": "IT", "germany": "DE", "france": "FR", "spain": "ES",
        "portugal": "PT", "netherlands": "NL", "belgium": "BE", "austria": "AT",
        "switzerland": "CH", "poland": "PL", "czech republic": "CZ", "czechia": "CZ",
        "united kingdom": "GB", "uk": "GB", "ireland": "IE", "sweden": "SE",
        "norway": "NO", "finland": "FI", "denmark": "DK", "greece": "GR",
        "romania": "RO", "hungary": "HU", "slovakia": "SK", "slovenia": "SI",
        "croatia": "HR", "bulgaria": "BG", "estonia": "EE", "latvia": "LV",
        "lithuania": "LT", "luxembourg": "LU",
    }
    code = name_to_code.get(text.lower())
    if code:
        base = 127397
        return chr(ord(code[0]) + base) + chr(ord(code[1]) + base)
    return ""


# ── GWP gradient pill — ``_GWP_*`` set from ``aux_01__catalogue_layout.json`` ─────

def _gwp_pill_html(row, product_type_raw: str) -> tuple[str, str]:
    """Return (co2_color, pill_html) for the fn329 GWP peer-group indicator.

    co2_color — CSS colour for the co2-value text (falls back to var(--cat-co2-green)).
    pill_html — gradient pill HTML, empty string when no range data is available.
    """
    _fallback = "var(--cat-co2-green)", ""
    try:
        ranges = (st.session_state.get("_catalogue_gwp_ranges") or {}).get(str(product_type_raw))
        if not ranges or ranges["max"] == ranges["min"]:
            return _fallback
        gv_raw = fn324_get_val(row, "G__GWP_A1A3")
        if gv_raw == "-":
            return _fallback
        gv = float(gv_raw)
    except (TypeError, ValueError, KeyError):
        return _fallback
    pct = max(0.0, min(1.0, (gv - ranges["min"]) / (ranges["max"] - ranges["min"])))
    if pct < 0.20:   text_color = "#2a7d2e"
    elif pct < 0.45: text_color = "#5a9e3a"
    elif pct < 0.65: text_color = "#c8a020"
    elif pct < 0.85: text_color = "#d97706"
    else:            text_color = "#c0392b"
    needle_pct = f"{pct * 100:.1f}"
    fmt_min = f"{ranges['min']:.2f}"
    fmt_max = f"{ranges['max']:.2f}"
    _mt = _GWP_PILL_MARGIN_TOP_PX
    _mb = _GWP_PILL_MARGIN_BOTTOM_PX
    _ml = _GWP_PILL_MARGIN_LEFT_PX
    _mr = _GWP_PILL_MARGIN_RIGHT_PX
    pill = (
        f"<div style='margin:{_mt}px {_mr}px {_mb}px {_ml}px'>"
        f"<div style='font-size:9px;color:#94a3b8;margin-bottom:3px;letter-spacing:.02em'>"
        f"GWP \u00b7 peer group percentile</div>"
        f"<div style='position:relative;height:7px;border-radius:3.5px;"
        f"background:linear-gradient(to right,#2a7d2e,#7cb87e,#d4c84a,#e8742a,#c0392b);"
        f"overflow:visible'>"
        f"<div style='position:absolute;top:50%;left:{needle_pct}%;"
        f"width:{_GWP_NEEDLE_WIDTH_PX}px;height:{_GWP_NEEDLE_HEIGHT_PX}px;"
        f"border-radius:2px;background:{_GWP_NEEDLE_COLOR};"
        f"transform:translate(-50%,-50%);pointer-events:none'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between;margin-top:2px'>"
        f"<span style='font-size:{_GWP_LABEL_FONT_SIZE_PX}px;color:{_GWP_LABEL_COLOR}'>{fmt_min}</span>"
        f"<span style='font-size:{_GWP_LABEL_FONT_SIZE_PX}px;color:{_GWP_LABEL_COLOR}'>{fmt_max}</span>"
        f"</div>"
        f"</div>"
    )
    return text_color, pill


def _gwp_contrast_text_for_bg(bg_css: str) -> str:
    """Choose near-white or near-black text for a solid ``bg_css`` (hex or CSS ``var()``)."""
    s = (bg_css or "").strip()
    if not s.startswith("#") or len(s) not in (7, 4):
        return "#ffffff"
    h = s[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#ffffff"
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "#ffffff" if lum < 0.58 else "#111827"


def fn329_render_product_card(row, gwp_spacing=3):
    """Render a product card with CSS-toggled Compact/Extended tab panels (no Tech button)."""
    # ── Unique card ID ─────────────────────────────────────────────────────────
    _epd  = fn324_get_val(row, "E__EPD_RegNumber")
    _name = fn324_get_val(row, "A__ProductName")
    _uid  = hashlib.md5(f"{_epd}\0{_name}".encode()).hexdigest()[:12]

    # ── Core values ────────────────────────────────────────────────────────────
    img_url      = fn324_get_val(row, "U__Img_URL")
    eetra_id     = fn324_get_val(row, "0__EETRA_ID")
    brand        = fn324_get_val(row, "A__Manufacturer")
    product_name = fn324_get_val(row, "A__ProductName")
    product_url  = fn324_get_val(row, "U__ProductInfo_URL")

    # Product photo: embedded in Compact panel HTML only (fixed height + object-fit:cover).
    # Extended tab hides it automatically because the whole .cat-cpanel is visibility:hidden — not st.image above the tabs.

    # ── Product type flags ─────────────────────────────────────────────────────
    product_type_raw   = row.get("D__ProductType_ENG", "")
    product_type       = fn315_normalize_product_type(product_type_raw)
    is_in_situ         = bool(product_type and "in situ"        in product_type.lower())
    is_insulation      = bool(product_type and "insulation"     in product_type.lower())
    is_building_boards = bool(product_type and "building boards" in product_type.lower())
    is_tiles           = bool(product_type and "tile"           in product_type.lower())

    def _to_float_pct(v) -> float | None:
        s = str(v).strip() if v is not None else ""
        if not s or s in ("-", "nan", "None"):
            return None
        s = s.replace("%", "").replace(",", ".").strip()
        try:
            return float(s)
        except Exception:
            return None

    def _cam_2025_below_threshold_tooltip() -> str | None:
        # Show CAM badge only when recycled content is below the matched CAM 2025 target.
        rec_raw = fn324_get_val(row, "R__Rec_Reco_ByProd_%")
        if rec_raw == "-":
            rec_raw = fn324_get_val(row, "R__Reco_Tot_%")
        rec_pct = _to_float_pct(rec_raw)
        if rec_pct is None:
            return None
        target = None
        try:
            from .lib_charts import fn217_match_cam_target

            for _lbl in (
                fn324_get_val(row, "D__MaterialType_ENG"),
                product_type_raw,
                product_name,
            ):
                target = fn217_match_cam_target(_lbl)
                if target is not None:
                    break
        except Exception:
            target = None
        if target is None or rec_pct >= float(target):
            return None
        return (
            "CAM 2025 recycled content: below threshold "
            f"({rec_pct:.1f}% < {float(target):.1f}%)."
        )

    # ── UI config helpers ──────────────────────────────────────────────────────
    _ui = {}
    try:
        _ui = st.session_state.get("FIELD_UI_SETTINGS", {}) or {}
    except Exception:
        _ui = {}

    def _ui_int(key: str, default: int) -> int:
        try:
            v = str(_ui.get(key, "")).strip()
            return int(float(v)) if v else default
        except Exception:
            return default

    def _ui_str(key: str, default: str) -> str:
        try:
            v = str(_ui.get(key, "")).strip()
            return v if v else default
        except Exception:
            return default

    _DIVIDER_THRESHOLD = _ui_int("divider_order_threshold", 100)
    _DIVIDER_COLOR     = _ui_str("divider_color", "#2a7d2e")
    _DIVIDER_WIDTH     = _ui_int("divider_width_pct", 50)
    _DIVIDER_BORDER    = _ui_int("divider_border_px", 1)
    _DIVIDER_MT        = _ui_int("divider_margin_top_px", 1)
    _DIVIDER_MB        = _ui_int("divider_margin_bottom_px", 1)
    _GREEN_DIVIDER_HTML = (
        f"<div style='border-top:{_DIVIDER_BORDER}px solid {_DIVIDER_COLOR};"
        f"width:{_DIVIDER_WIDTH}%;margin:{_DIVIDER_MT}px 0 {_DIVIDER_MB}px 0;'></div>"
    )
    # Full-width rule between sustainability block (GWP + recycled + EPD) and other parameters
    _SUSTAINABILITY_SECTION_DIVIDER_HTML = (
        f"<div style='border-top:{_DIVIDER_BORDER}px solid {_DIVIDER_COLOR};"
        f"width:60%;margin:8px 0 -5px 0;'></div>"
    )

    # ── Field-meta helpers ─────────────────────────────────────────────────────
    _field_meta = {}
    try:
        _field_meta = st.session_state.get("FIELD_META", {}) or {}
    except Exception:
        _field_meta = {}

    def _catalog_label(field_key: str, default_label: str) -> str:
        try:
            meta = _field_meta.get(field_key, {}) or {}
            return str(meta.get("catalog_label") or meta.get("display_name") or default_label)
        except Exception:
            return default_label

    def _field_order(field_key: str) -> int:
        try:
            return int((_field_meta.get(field_key, {}) or {}).get("order", 9999))
        except Exception:
            return 9999

    def _is_naish(v: str) -> bool:
        try:
            return str(v).strip().lower() in ("", "-", "n/a", "n\\a", "na", "n/r", "n\\r", "nr")
        except Exception:
            return True

    def _fmt(v) -> str:
        try:
            vf = float(v)
            return f"{vf:.2f}" if vf < 10 else f"{vf:.1f}"
        except (ValueError, TypeError):
            return str(v)

    # ── Build one panel's HTML (compact or extended) ───────────────────────────
    def _build_panel(panel_dl: str) -> tuple:
        """Return (html_string, estimated_line_count) for the given detail level."""
        is_ext = panel_dl.strip().lower() == "extended"
        parts  = []

        # Extended view: tag GWP figures tied to the EPD declared unit (``G__GWP_FU``).
        _gwp_fu = fn324_get_val(row, "G__GWP_FU")
        _suf_epd = (" (EPD)" if is_ext and _gwp_fu != "-" else "")
        _gwp_peer_color, _gwp_pill_preview = _gwp_pill_html(row, product_type_raw)
        _gwp_fu_hi_fg = _gwp_contrast_text_for_bg(_gwp_peer_color)

        def _gwp_fu_hl(line: str, *, fu_line: bool) -> str:
            """Extended FU line: tight chip using peer-gradient text colour (``_gwp_pill_html``)."""
            if not fu_line or not is_ext:
                return line
            low = (line or "").strip().lower()
            if low in ("n/a", "gwp/m²: n/a", "gwp: n/a"):
                return line
            _st = (
                f"background:{_gwp_peer_color};color:{_gwp_fu_hi_fg};"
                "padding:0 2px;border-radius:2px;display:inline-block;font-weight:500;"
            )
            return f"<span style='{_st}'>{line}</span>"

        # GWP block
        gwp_parts = []
        if is_in_situ:
            gwp_m3 = fn324_get_val(row, "G__GWP_A1A3_m3")
            _ln = (
                f"{_fmt(gwp_m3)} kgCO₂e/m³{_suf_epd}" if gwp_m3 != "-"
                else f"GWP: Not available{_suf_epd}"
            )
            gwp_parts.append(_gwp_fu_hl(_ln, fu_line=True))
        elif product_type in ["Binder", "Filler"]:
            gv = fn324_get_val(row, "G__GWP_A1A3"); gu = fn324_get_val(row, "G__GWP_FU")
            _ln = (
                f"{_fmt(gv)} kgCO₂e/{gu}{_suf_epd}" if gv != "-"
                else f"GWP: Not available / {gu}{_suf_epd}"
            )
            gwp_parts.append(_gwp_fu_hl(_ln, fu_line=True))
        elif product_type and "rebar" in product_type.lower():
            gv = fn324_get_val(row, "G__GWP_A1A3"); gu = fn324_get_val(row, "G__GWP_FU")
            if gv != "-" and gu != "-":
                _ln = f"{_fmt(gv)} kgCO₂e/{gu}{_suf_epd}"
            else:
                _ln = f"GWP: Not available / {gu}{_suf_epd}"
            gwp_parts.append(_gwp_fu_hl(_ln, fu_line=True))
        elif is_insulation:
            gv   = fn324_get_val(row, "G__GWP_A1A3")
            gu_raw = fn324_get_val(row, "G__GWP_FU")
            gu = gu_raw
            gm3  = fn324_get_val(row, "G__GWP_A1A3_m3")
            gm2r = fn324_get_val(row, "G__GWP_A1A3_m2R1")
            if gu != "-":
                gu = str(gu).replace("m2", "m²").replace("m3", "m³")
            if is_ext:
                _in_pri = _tiles_gwp_fu_primary_line(gu_raw if gu_raw != "-" else "")
                _s_in_g = _suf_epd if _in_pri != "m3" else ""
                _s_in_m3 = _suf_epd if _in_pri == "m3" else ""
                gwp_parts.append(
                    f"{_fmt(gv)} kgCO₂e/{gu}{_s_in_g}" if gv != "-" and gu != "-"
                    else f"GWP: Not available / {gu}{_s_in_g}"
                )
                gwp_parts.append(
                    f"{_fmt(gm3)} kgCO₂e/m³{_s_in_m3}" if gm3 != "-" else "n/a"
                )
            _ln_m2r = f"{_fmt(gm2r)} kgCO₂e/m² R=1" if gm2r != "-" else "n/a"
            gwp_parts.append(_gwp_fu_hl(_ln_m2r, fu_line=True))
        elif is_building_boards:
            gv  = fn324_get_val(row, "G__GWP_A1A3")
            gu  = fn324_get_val(row, "G__GWP_FU")
            gm2 = fn324_get_val(row, "G__GWP_A1A3_m2")
            gm3 = fn324_get_val(row, "G__GWP_A1A3_m3")
            _bb_pri = _tiles_gwp_fu_primary_line(gu if gu != "-" else "")
            _m2u = "kgCO₂e/m<sup>2</sup>"
            if not is_ext:
                if gm2 != "-":
                    gwp_parts.append(f"{_fmt(gm2)} {_m2u}")
                elif gv != "-" and _bb_pri not in ("m3", "kg"):
                    gwp_parts.append(f"{_fmt(gv)} {_m2u}")
                else:
                    gwp_parts.append("GWP/m²: n/a")
            else:
                _s_bb_g = _suf_epd if _bb_pri != "m3" else ""
                _s_bb_m3 = _suf_epd if _bb_pri == "m3" else ""
                _ln_g = (
                    f"{_fmt(gv)} kgCO₂e/{gu}{_s_bb_g}" if gv != "-" and gu != "-"
                    else f"GWP: Not available/{gu}{_s_bb_g}"
                )
                _ln_m3 = f"{_fmt(gm3)} kgCO₂e/m³{_s_bb_m3}" if gm3 != "-" else "n/a"
                if _bb_pri == "m3":
                    gwp_parts.append(_gwp_fu_hl(_ln_g, fu_line=False))
                    gwp_parts.append(_gwp_fu_hl(_ln_m3, fu_line=True))
                else:
                    gwp_parts.append(_gwp_fu_hl(_ln_g, fu_line=True))
                    gwp_parts.append(_gwp_fu_hl(_ln_m3, fu_line=False))
        elif is_tiles:
            gm2    = fn324_get_val(row, "G__GWP_A1A3_m2")
            gm3    = fn324_get_val(row, "G__GWP_A1A3_m3")
            gdecl  = fn324_get_val(row, "G__GWP_A1A3")
            gfu_r  = fn324_get_val(row, "G__GWP_FU")
            gfu    = str(gfu_r).strip().lower() if gfu_r != "-" else ""
            _tile_pri = _tiles_gwp_fu_primary_line(gfu_r if gfu_r != "-" else "")
            _s_m2 = _suf_epd if _tile_pri == "m2" else ""
            _s_m3 = _suf_epd if _tile_pri == "m3" else ""
            _s_kg = _suf_epd if _tile_pri == "kg" else ""
            if not is_ext:
                gwp_parts.append(f"{_fmt(gm2)} kgCO₂e/m²" if gm2 != "-" else "GWP/m²: n/a")
            else:
                _lm2 = f"{_fmt(gm2)} kgCO₂e/m²{_s_m2}" if gm2 != "-" else "n/a"
                gwp_parts.append(_gwp_fu_hl(_lm2, fu_line=(_tile_pri == "m2")))
                _lm3 = f"{_fmt(gm3)} kgCO₂e/m³{_s_m3}" if gm3 != "-" else "n/a"
                gwp_parts.append(_gwp_fu_hl(_lm3, fu_line=(_tile_pri == "m3")))
                kg_line = None
                _kg_is_epd_decl = False
                if gdecl != "-":
                    try:
                        gd = float(gdecl)
                        if "kg" in gfu and "m2" not in gfu and "m3" not in gfu:
                            kg_line = f"{_fmt(gd)} kgCO₂e/kg"
                            _kg_is_epd_decl = True
                        elif "ton" in gfu or "tonne" in gfu or gfu in ("t", "to"):
                            kg_line = f"{_fmt(gd / 1000.0)} kgCO₂e/kg"
                            _kg_is_epd_decl = True
                    except (ValueError, TypeError):
                        kg_line = f"{gdecl} kgCO₂e/kg"
                        _kg_is_epd_decl = True
                if kg_line is None and gm2 != "-" and fn324_get_val(row, "P__Mass_kgm2") != "-":
                    try:
                        m2v = float(gm2); kgm2 = float(fn324_get_val(row, "P__Mass_kgm2"))
                        if kgm2:
                            kg_line = f"{_fmt(m2v / kgm2)} kgCO₂e/kg"
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass
                _kl = kg_line or "n/a"
                _kg_suf = _s_kg if _kg_is_epd_decl else ""
                _lkg = f"{_kl}{_kg_suf}" if (is_ext and _kl != "n/a") else _kl
                gwp_parts.append(
                    _gwp_fu_hl(
                        _lkg,
                        fu_line=(
                            _tile_pri == "kg"
                            and _kg_is_epd_decl
                            and _kl != "n/a"
                        ),
                    )
                )
        else:
            gv   = fn324_get_val(row, "G__GWP_A1A3")
            gu   = fn324_get_val(row, "G__GWP_FU")
            gm3  = fn324_get_val(row, "G__GWP_A1A3_m3")
            _else_pri = _tiles_gwp_fu_primary_line(gu if gu != "-" else "")
            _s_el0 = _suf_epd if _else_pri != "m3" else ""
            _s_el_m3 = _suf_epd if _else_pri == "m3" else ""
            if gv != "-":
                _ln0 = f"{_fmt(gv)} kgCO₂e/{gu}{_s_el0}"
            else:
                alt_val = next(
                    (fn324_get_val(row, f) for f in
                     ["G__GWP_A1A3_Total", "G__GWP_Total", "G__GWP_A1A3_Fossil"]
                     if f in row.index and fn324_get_val(row, f) != "-"), "-"
                )
                _ln0 = (
                    f"{_fmt(alt_val)} kgCO₂e/{gu} (alternative)" if alt_val != "-"
                    else f"GWP: Not available / {gu}{_s_el0}"
                )
            _ln_m3 = f"{_fmt(gm3)} kgCO₂e/m³{_s_el_m3}" if gm3 != "-" else "n/a"
            if _else_pri == "m3":
                gwp_parts.append(_gwp_fu_hl(_ln0, fu_line=False))
                gwp_parts.append(_gwp_fu_hl(_ln_m3, fu_line=True))
            else:
                gwp_parts.append(_gwp_fu_hl(_ln0, fu_line=True))
                gwp_parts.append(_gwp_fu_hl(_ln_m3, fu_line=False))

        if gwp_parts:
            gwp_style = (
                f"line-height:{CATALOGUE_GWP_LINE_HEIGHT};"
                if (is_insulation or is_building_boards or (is_tiles and is_ext)) else ""
            )
            _gwp_color, _pill = _gwp_peer_color, _gwp_pill_preview
            parts.append(
                f"<div style='margin:0;padding:0;'>"
                f"<div class='co2-value' style='{gwp_style}margin:0 0 {gwp_spacing}px 0;padding:0;color:{_gwp_color};'>"
                f"{'<br>'.join(gwp_parts)}</div>"
                f"{'' if is_ext else _pill}"
                f"</div>"
            )

        # Field visibility for this panel
        _pt_key   = fn316_make_session_key_fragment(product_type) if product_type else "default"
        _sess_key = (
            f"display_params_{_pt_key}_{panel_dl}_{DISPLAY_PARAMS_SESSION_VER}"
        )
        fv = (
            st.session_state[_sess_key]
            if _sess_key in st.session_state
            else fn317_get_field_visibility(product_type, panel_dl)
        )
        _pt_low_vis = str(product_type or "").lower()
        if "framing" in _pt_low_vis:
            fv = dict(fv)
            fv["Fire rating"] = False

        # Field renderers — tech URL now always shown inline via _render_technical_details
        def _render_density():
            v = fn324_get_val(row, "P__Mass_kgm3")
            unit = " kg/m³"
            label_default = "Vol. Density"
            if is_building_boards and _is_naish(v):
                v = fn324_get_val(row, "P__Mass_kgm2")
                unit = " kg/m²"
                label_default = "Sup. Density"
            return f"<b>{_catalog_label('Density', label_default)}:</b> {v}" + ("" if _is_naish(v) else unit)

        def _render_thickness():
            v = fn325_get_thickness_val(row)
            return f"<b>{_catalog_label('Thickness','Thickness')}:</b> {v}" + ("" if _is_naish(v) else " mm")

        def _render_conductivity():
            v = fn324_get_val(row, "P__L_WmK")
            if v == "-" and "E__L_WmK" in row.index:
                v = fn324_get_val(row, "E__L_WmK")
            return f"<b>{_catalog_label('Conductivity (ʎ)','Conductivity (ʎ)')}:</b> {v}" + ("" if _is_naish(v) else " W/mK")

        def _render_recycling():
            raw = fn324_get_val(row, "R__Rec_Reco_ByProd_%")
            if raw == "-":
                raw = fn324_get_val(row, "R__Reco_Tot_%")
            r = fn326_format_recycling_rate(raw)
            line = f"<b>{_catalog_label('Recycling Rate','Recycled Content')}:</b> {r}" + (
                "" if _is_naish(r) else "%"
            )
            _cam_tip = _cam_2025_below_threshold_tooltip()
            if _cam_tip:
                _tip = _html.escape(_cam_tip, quote=True)
                line += (
                    f" <span title='{_tip}' style='display:inline-flex;align-items:center;"
                    "justify-content:center;width:14px;height:14px;border-radius:999px;"
                    "border:1px solid #d4a429;background:#fffbeb;color:#854d0e;"
                    "font-size:10px;font-weight:700;line-height:1;vertical-align:middle;"
                    "cursor:help;'>i</span>"
                )
            url = fn324_get_val(row, "R__Rec_Reco_ByProd_URL")
            if url and str(url).strip() not in ("", "-"):
                u = _html.escape(str(url).strip(), quote=True)
                line += (
                    f' <a href="{u}" target="_blank" rel="noopener noreferrer" '
                    f'title="Recycled content documentation">🔗</a>'
                )
            return line

        def _render_content():
            v = fn324_get_val(row, "D__Content")
            return None if _is_naish(v) else f"<b>{_catalog_label('Content','Content')}:</b> {v}"

        def _render_epd():
            eu = fn324_get_val(row, "E__EPD_URL")
            ed = fn324_get_val(row, "E__EPD_DecNumber")
            er = fn324_get_val(row, "E__EPD_RegNumber")
            lbl_dec = _catalog_label("EPD Dec.", "EPD Dec. n.")
            lbl_reg = _catalog_label("EPD Num.", "EPD Reg. n.")
            dec_disp = _html.escape(ed) if ed != "-" else "—"
            from .lib_data import fn142a_is_usable_document_url, prefer_local_document_href

            if fn142a_is_usable_document_url(eu):

                href = prefer_local_document_href(eu, eetra_id, product_name, "epd")
                if not href:
                    href = eu
                he = _html.escape(str(href), quote=True)
                if er != "-":
                    reg_inner = (
                        f"<a href=\"{he}\" target='_blank' rel='noopener noreferrer'>"
                        f"{_html.escape(er)}</a>"
                    )
                else:
                    reg_inner = (
                        f"<a href=\"{he}\" target='_blank' rel='noopener noreferrer'>"
                        f"Open EPD ↗</a>"
                    )
            elif er != "-":
                reg_inner = _html.escape(er)
            else:
                reg_inner = "—"
            line_dec = f"<b>{lbl_dec}:</b> {dec_disp}"
            line_reg = f"<b>{lbl_reg}:</b> {reg_inner}"
            if is_ext:
                return f"{line_dec}<br>{line_reg}"
            return line_reg

        def _render_fire():
            return f"<b>{_catalog_label('Fire rating','Fire rating')}:</b> {fn324_get_val(row, 'P__FireRating')}"

        def _render_service_life():
            return f"<b>{_catalog_label('Service Life','Service Life')}:</b> {fn324_get_val(row, 'P__ServiceLife')}"

        def _render_technical_details():
            is_glazing = product_type and "glazing" in product_type.lower()
            if is_glazing and not is_ext:
                return None
            lbl    = _catalog_label("Technical Details", "Details")
            td_url = fn324_get_val(row, "U__TechDetails_URL")
            is_ins = bool(product_type and "insulation" in product_type.lower())
            if is_ins and td_url and td_url != "-":
                from .lib_data import prefer_local_document_href

                href = prefer_local_document_href(td_url, eetra_id, product_name, "tech")
                link_text = "Link" if is_ext else "🔗"
                he = _html.escape(str(href), quote=True)
                return f"<b>{lbl}:</b> <a href='{he}' target='_blank' rel='noopener noreferrer'>{link_text}</a>"
            td = fn324_get_val(row, "D__TechDetails")
            if td == "-":
                # Fallback: surface tech URL even for non-insulation products
                if td_url and td_url != "-":
                    from .lib_data import prefer_local_document_href

                    href = prefer_local_document_href(td_url, eetra_id, product_name, "tech")
                    he = _html.escape(str(href), quote=True)
                    return f"<b>{lbl}:</b> <a href='{he}' target='_blank' rel='noopener noreferrer'>Link</a>"
                return None
            parsed = fn327_parse_technical_details(td)
            return f"<b>{lbl}:</b> {parsed}" if parsed else f"<b>{lbl}:</b> {td}"

        def _render_comments():
            is_glazing = product_type and "glazing" in product_type.lower()
            if is_glazing and not is_ext:
                return None
            return f"<b>{_catalog_label('Comments','Comments')}:</b> {fn324_get_val(row, 'S__Comments')}"

        def _render_plant():
            cr = fn324_get_val(row, "E__ManuCountry"); pt = fn324_get_val(row, "E__ManuPlant")
            flag = fn328_country_to_flag(cr)
            bits = [x for x in [flag, pt if pt != "-" else (cr if not flag and cr != "-" else None)] if x]
            return None if not bits else f"<b>{_catalog_label('Manufacturing Plant','Plant')}:</b> {' '.join(bits)}"

        def _render_voc():
            # Same rules as detail panel: strip http(s) from text; show 🔗 (card HTML).
            # When cert badges render in the card footer, omit duplicate cert imagery from this line.
            try:
                _vt, _vu = _voc_detail_texts_and_urls(row)
            except Exception:
                _vt, _vu = [], []
            if not _vt and not _vu:
                return None
            _vl = _catalog_label("VOC", "VOC")
            _pieces: list[str] = []
            for _frag in _vt:
                _xn = _voc_cert_normalize_label(str(_frag))
                if _voc_badge_kinds and _voc_cert_token_re().search(_xn):
                    _rem = _voc_cert_remainder_plain(_xn)
                    if _rem:
                        _pieces.append(_html.escape(_rem))
                else:
                    _pieces.append(_voc_catalog_fragment_to_html(_frag))
            _lab = " - ".join(p for p in _pieces if p)
            if _vu:
                _href = str(_vu[0]).strip().replace(" ", "%20")
                _he = _html.escape(_href, quote=True)
                _link = (
                    f'<a href="{_he}" target="_blank" rel="noopener noreferrer" '
                    'title="VOC documentation">🔗</a>'
                )
                if _lab:
                    return f"<b>{_vl}:</b> {_lab} {_link}"
                return f"<b>{_vl}:</b> {_link}"
            return f"<b>{_vl}:</b> {_lab}" if _lab else None

        _renderers = {
            "Density":            _render_density,
            "Thickness":          _render_thickness,
            "Content":            _render_content,
            "Conductivity (ʎ)":  _render_conductivity,
            "Recycling Rate":     _render_recycling,
            "EPD Num.":           _render_epd,
            "Fire rating":        _render_fire,
            "Service Life":       _render_service_life,
            "Technical Details":  _render_technical_details,
            "Comments":           _render_comments,
            "Manufacturing Plant": _render_plant,
            "VOC":                _render_voc,
        }

        _sustainability_tail_keys = ("Recycling Rate", "EPD Num.")
        _sustainability_emitted = bool(gwp_parts)
        _done_keys: set[str] = set()
        for _sk in _sustainability_tail_keys:
            if not fv.get(_sk, False):
                continue
            try:
                _out_s = _renderers[_sk]()
            except Exception:
                _out_s = None
            if _out_s:
                parts.append(_out_s)
                _sustainability_emitted = True
                _done_keys.add(_sk)

        # Extended: Plant sits under EPD, still above the first green section divider
        if is_ext and fv.get("Manufacturing Plant", False):
            try:
                _out_plant = _renderers["Manufacturing Plant"]()
            except Exception:
                _out_plant = None
            if _out_plant:
                parts.append(_out_plant)
                _sustainability_emitted = True
                _done_keys.add("Manufacturing Plant")

        if is_ext:
            _ordered_middle = [
                "Thickness", "Density", "Fire rating", "Technical Details", "VOC", "Comments",
            ]
        else:
            # Compact: include VOC here so it is emitted with other headline parameters (not only
            # via the trailing sorted pass, which is easy to miss when middle fields dominate).
            _ordered_middle = ["Fire rating", "Thickness", "VOC"]

        _keys_emit_before_voc: set[str] = set()
        for _fk in _ordered_middle:
            if _fk == "VOC":
                break
            _keys_emit_before_voc.add(_fk)

        _middle_key_set = set(_ordered_middle)
        if not is_ext:
            _middle_key_set.add("Conductivity (ʎ)")

        def _emit_fk(fk: str) -> bool:
            if fk not in _renderers or not fv.get(fk, False):
                return False
            try:
                _out = _renderers[fk]()
            except Exception:
                _out = None
            if not _out:
                return False
            if fk == "VOC" and (_done_keys & _keys_emit_before_voc):
                parts.append(_SUSTAINABILITY_SECTION_DIVIDER_HTML)
            parts.append(_out)
            _done_keys.add(fk)
            return True

        _conductivity_relevant = bool(is_insulation or is_building_boards)

        def _middle_will_emit() -> bool:
            if any(fv.get(k, False) and k in _renderers for k in _ordered_middle):
                return True
            return bool(
                not is_ext
                and fv.get("Conductivity (ʎ)", False)
                and _conductivity_relevant
            )

        def _counts_as_trailing_preview(fk: str) -> bool:
            if fk in _sustainability_tail_keys:
                return False
            if is_ext and fk == "Manufacturing Plant":
                return False
            if fk in _middle_key_set:
                return False
            return bool(fv.get(fk, False))

        _has_trailing_preview = any(
            _counts_as_trailing_preview(fk) for fk in _renderers
        ) or bool(fv.get("EN197-1", False))

        if _sustainability_emitted and (_middle_will_emit() or _has_trailing_preview):
            parts.append(_SUSTAINABILITY_SECTION_DIVIDER_HTML)

        _middle_emitted = 0
        for fk in _ordered_middle:
            if not fv.get(fk, False):
                continue
            if _emit_fk(fk):
                _middle_emitted += 1

        if not is_ext and fv.get("Conductivity (ʎ)", False) and _conductivity_relevant:
            if _emit_fk("Conductivity (ʎ)"):
                _middle_emitted += 1

        _has_trailing_after_middle = any(
            fv.get(fk, False) and fk not in _done_keys
            for fk in _renderers
        ) or bool(fv.get("EN197-1", False))

        if is_ext and _middle_emitted > 0 and _has_trailing_after_middle:
            parts.append(_SUSTAINABILITY_SECTION_DIVIDER_HTML)

        # EN197-1 cement block (Binder only). Full EN 197-1 classification (decoded lines,
        # section titles, Special Properties) is Extended only; Compact shows the raw code.
        if fv.get("EN197-1", False):
            en1971_value = fn324_get_val(row, "D__EN197-1")
            if en1971_value != "-":
                if product_type == "Binder":
                    if not is_ext:
                        parts.append(f"<b>EN197-1:</b> {en1971_value}")
                    else:
                        try:
                            from .lib_data import fn129_decode_cement_marking
                            cement_data   = fn129_decode_cement_marking(en1971_value)
                            cement_details = []
                            if cement_data["family_code"]:
                                family_display = cement_data["family_code"]
                                if cement_data["subclass"]:
                                    family_display += f"/{cement_data['subclass']}"
                                type_tooltip_parts = []
                                if cement_data["family_it"]:
                                    type_tooltip_parts.append(cement_data["family_it"])
                                if cement_data["subclass"]:
                                    if cement_data["family_code"] == "CEM II":
                                        if cement_data["subclass"] == "A":
                                            type_tooltip_parts.append(
                                                "/A = Minor clinker substitution (6-20%)"
                                            )
                                        elif cement_data["subclass"] == "B":
                                            type_tooltip_parts.append(
                                                "/B = Higher clinker substitution (21-35%)"
                                            )
                                    elif cement_data["family_code"] in ["CEM III", "CEM IV", "CEM V"]:
                                        if cement_data["subclass_range_it"]:
                                            type_tooltip_parts.append(
                                                f"/{cement_data['subclass']} = "
                                                f"{cement_data['subclass_range_it']}"
                                            )
                                type_tooltip = (
                                    " | ".join(type_tooltip_parts) if type_tooltip_parts else ""
                                )
                                if type_tooltip:
                                    cement_details.append(
                                        f"<b>Type:</b> {family_display} "
                                        f"<span title='{type_tooltip}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>"
                                    )
                                else:
                                    cement_details.append(f"<b>Type:</b> {family_display}")
                                content_value = fn324_get_val(row, "D__Content")
                                content_tooltip = (
                                    "Percentage of non-clinker additions "
                                    "(lower clinker = lower embodied carbon)"
                                )
                                if content_value != "-":
                                    cement_details.append(
                                        f"<b>Content:</b> {content_value} "
                                        f"<span title='{content_tooltip}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>"
                                    )
                                elif cement_data["subclass_range_it"]:
                                    cement_details.append(
                                        f"<b>Content:</b> {cement_data['subclass_range_it']} "
                                        f"<span title='{content_tooltip}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>"
                                    )
                            if cement_data["additions_codes"]:
                                additions_display = (
                                    f"<b>Additions:</b> {', '.join(cement_data['additions_codes'])}"
                                )
                                if cement_data["additions_it"]:
                                    pairs = [
                                        f"{code}={cement_data['additions_it'][i].replace(chr(39), '&#39;')}"
                                        for i, code in enumerate(cement_data["additions_codes"])
                                        if i < len(cement_data["additions_it"])
                                    ]
                                    additions_display += (
                                        f" <span title='{', '.join(pairs)}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>"
                                    )
                                cement_details.append(additions_display)
                            if cement_data["special_marks"]:
                                special_display = (
                                    f"<b>Special Properties:</b> "
                                    f"{', '.join(cement_data['special_marks'])}"
                                )
                                if cement_data["special_it"]:
                                    _sp = [
                                        f"{code}={cement_data['special_it'][i].replace(chr(39), '&#39;')}"
                                        for i, code in enumerate(cement_data["special_marks"])
                                        if i < len(cement_data["special_it"])
                                    ]
                                    special_display += (
                                        f" <span title='{', '.join(_sp)}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>"
                                    )
                            else:
                                special_display = "<b>Special Properties:</b> n/a"
                            cement_details.append(special_display)
                            if cement_data["strength_class"]:
                                _st_tip = "Minimum guaranteed compressive strength at 28 days"
                                _st_disp = (
                                    f"<b>Strength Class:</b> {cement_data['strength_class']} MPa "
                                    f"<span title='{_st_tip}' style='color:#666;cursor:help;"
                                    f"font-family:Material Symbols Rounded;font-size:12px;"
                                    f"vertical-align:super;'>help</span>"
                                )
                                if cement_data["early_strength_code"]:
                                    ec = cement_data["early_strength_code"]
                                    eh = (
                                        "R = Rapid early strength gain"
                                        if ec == "R"
                                        else "N = Normal early strength gain"
                                        if ec == "N"
                                        else cement_data.get("early_strength_it", "")
                                    )
                                    _st_disp += (
                                        f" ({ec}<span title='{eh}' style='color:#666;cursor:help;"
                                        f"font-family:Material Symbols Rounded;font-size:12px;"
                                        f"vertical-align:super;'>help</span>)"
                                    )
                                cement_details.append(_st_disp)
                            if cement_details:
                                _norm = "EN 197-1, la norma europea per i cementi comuni"
                                parts.append(
                                    f"<b style='background-color:#f0f0f0;padding:2px 4px;border-radius:3px;'>"
                                    f"EN197-1 Classification "
                                    f"<span title='{_norm}' style='color:#666;cursor:help;"
                                    f"font-family:Material Symbols Rounded;font-size:12px;"
                                    f"vertical-align:super;'>help</span>"
                                    f"</b><br>{'<br>'.join(cement_details)}"
                                )
                                parts.append(" ")
                                parts.append(
                                    "<b style='background-color:#f0f0f0;padding:2px 4px;"
                                    "border-radius:3px;'>Other parameters</b>"
                                )
                            else:
                                parts.append(f"<b>EN197-1:</b> {en1971_value}")
                        except Exception:
                            parts.append(f"<b>EN197-1:</b> {en1971_value}")
                else:
                    parts.append(f"<b>EN197-1:</b> {en1971_value}")

        # Remaining fields (Content, Service Life, …) in configured order
        _field_keys_ordered = sorted(_renderers.keys(), key=_field_order)
        _DIVIDER_SENTINEL = "__CATALOGUE_DIVIDER__"
        _divider_inserted = False
        for fk in _field_keys_ordered:
            if fk in _done_keys:
                continue
            if fk in _sustainability_tail_keys:
                continue
            if is_ext and fk == "Manufacturing Plant":
                continue
            if not fv.get(fk, False):
                continue
            try:
                if not _divider_inserted and _field_order(fk) > _DIVIDER_THRESHOLD:
                    if parts:
                        parts.append(_DIVIDER_SENTINEL)
                    _divider_inserted = True
                out = _renderers[fk]()
            except Exception:
                out = None
            if out:
                if fk == "VOC" and (_done_keys & _keys_emit_before_voc):
                    parts.append(_SUSTAINABILITY_SECTION_DIVIDER_HTML)
                parts.append(out)
                _done_keys.add(fk)

        # Assemble final HTML
        html_out = []
        for part in parts:
            if part == _DIVIDER_SENTINEL:
                html_out.append(_GREEN_DIVIDER_HTML)
            else:
                html_out.append(part)
        raw = "<br>".join(html_out)
        return raw.replace("<br>" + _GREEN_DIVIDER_HTML + "<br>", _GREEN_DIVIDER_HTML)

    # ── Brand + name header (always visible) ──────────────────────────────────
    _name_html = (
        f"<a href='{product_url}' target='_blank' style='color:inherit;text-decoration:none;'>"
        f"{product_name}</a>"
        if product_url != "-" else product_name
    )

    # ── Build both panels ─────────────────────────────────────────────────────
    _voc_badge_kinds = _voc_cert_kinds_from_row(row)
    compact_html  = _build_panel("Compact")
    extended_html = _build_panel("Extended")
    _voc_footer_html = _voc_cert_footer_bar_html(_voc_badge_kinds)

    def _san_obj_pos(s: str) -> str:
        t = re.sub(r"[^a-zA-Z0-9\s.%\-,/()]+", "", str(s or "").strip())
        return t.strip() or "center"

    try:
        _band_h = max(0, int(CATALOGUE_CARD_IMAGE_HEIGHT_PX))
    except (TypeError, ValueError):
        _band_h = 0

    _compact_lead = ""
    _material_raw = fn324_get_val(row, "D__MaterialType_ENG")
    _mr_s = str(_material_raw).strip() if _material_raw is not None else ""
    _material_band = ""
    if _mr_s and _mr_s not in ("-",) and _mr_s.lower() not in (
        "", "n/a", "n\\a", "na", "n/r", "n\\r", "nr",
    ):
        # Styling from ``aux_01__catalogue_layout.json`` → ``material_type_band`` (:root vars + global CSS).
        _material_band = (
            f'<div class="eetra-cat-material-band" aria-hidden="true">'
            f"{_html.escape(_mr_s)}</div>"
        )
    if _band_h > 0 and img_url and str(img_url).strip() not in ("", "-"):
        _src_raw = str(img_url).strip()
        _src = _html.escape(_src_raw, quote=True)
        if eetra_id not in ("", "-") and product_name not in ("", "-"):
            from .lib_data import image_path_to_data_uri, resolve_local_product_image_path

            _lp = resolve_local_product_image_path(_src_raw, eetra_id, product_name)
            if _lp is not None:
                _du = image_path_to_data_uri(_lp)
                if _du:
                    _src = _html.escape(_du, quote=True)
        _rad = str(CATALOGUE_CARD_BORDER_RADIUS).strip()
        _bg = _html.escape(str(CATALOGUE_CARD_IMAGE_BAND_BACKGROUND or "#ffffff"), quote=True)
        _op = _html.escape(_san_obj_pos(str(CATALOGUE_CARD_IMAGE_OBJECT_POSITION or "center")))
        _zo = _san_obj_pos(str(CATALOGUE_CARD_IMAGE_ZOOM_ORIGIN or "center center"))
        if str(product_type or "").strip().lower() == "binder":
            _fit_img = str(CATALOGUE_CARD_IMAGE_BINDER_OBJECT_FIT or "contain").strip().lower()
            if _fit_img not in _CATALOGUE_OBJECT_FIT_ALLOWED:
                _fit_img = "contain"
            try:
                _z_b = float(CATALOGUE_CARD_IMAGE_BINDER_ZOOM)
            except (TypeError, ValueError):
                _z_b = 0.88
            _z_b = max(0.25, min(1.5, _z_b))
            _tf = (
                f"transform:scale({_z_b});transform-origin:{_zo};"
                if abs(_z_b - 1.0) > 1e-6
                else ""
            )
        else:
            _fit_img = "cover"
            _tf = ""
        _compact_lead = (
            f'<div class="eetra-cat-img-band" style="position:relative;height:{_band_h}px;overflow:hidden;'
            f"margin:0 0 6px 0;border-radius:{_rad} {_rad} 0 0;background:{_bg}\">"
            f"{_material_band}"
            f'<img src="{_src}" alt="" loading="lazy" decoding="async" '
            f'style="display:block;width:100%;height:100%;object-fit:{_fit_img};object-position:{_op};{_tf}" '
            f"onerror=\"this.closest('.eetra-cat-img-band').style.display='none'\"/></div>"
        )
    elif _band_h <= 0 and img_url and str(img_url).strip() not in ("", "-"):
        _im = _lazy_fetch_image(
            img_url,
            eetra_id=None if eetra_id in ("", "-") else eetra_id,
            product_name=None if product_name in ("", "-") else product_name,
        )
        st.image(_im, width="stretch")

    # ── Pure-CSS tab toggle — no Streamlit button, no rerun ───────────────────
    # Two hidden radio inputs act as state. CSS :checked + ~ sibling selectors
    # swap visibility on the two stacked panels and highlight the active label.
    # Both panels occupy grid-area 1/1 so card height is always the taller one.
    # Initial selection follows the page "Detail Level" control (catalogue_detail_level).
    try:
        _dl_raw = st.session_state.get("catalogue_detail_level", "Compact")
        _prefer_extended = str(_dl_raw).strip().lower() == "extended"
    except Exception:
        _prefer_extended = False
    _ci = f"ctc{_uid}"   # compact input id
    _ei = f"cte{_uid}"   # extended input id
    _pg = f"cpg{_uid}"   # panel-grid class (unique per card for CSS scoping)
    _tb = f"ctb{_uid}"   # tab-bar class
    _surface_style = "display:flex;flex-direction:column;box-sizing:border-box;"
    try:
        _card_min_inline = max(0, int(CATALOGUE_STREAMLIT_CARD_MIN_HEIGHT_PX))
        if _card_min_inline > 0:
            _surface_style = (
                f"min-height:{_card_min_inline}px;"
                "display:flex;flex-direction:column;box-sizing:border-box;"
            )
    except (TypeError, ValueError):
        pass

    st.markdown(
        # Per-card style: only the "extended active" override is needed;
        # compact-active is the default defined in global CSS.
        f"<style>"
        f"#{_ei}:checked~.{_pg} .cat-cpanel{{visibility:hidden;pointer-events:none}}"
        f"#{_ei}:checked~.{_pg} .cat-epanel{{visibility:visible;pointer-events:auto}}"
        f"#{_ei}:checked~.{_tb} .cat-tab-c{{background:#f9fafb;color:#6b7280;border-top:1px solid #e5e7eb}}"
        f"#{_ei}:checked~.{_tb} .cat-tab-e{{background:#fff;color:#111;border-top:2px solid #2a7d2e}}"
        f"</style>"
        f"<div class='{_CATALOGUE_CARD_SURFACE_CLASS}' style='{_surface_style}'>"
        # Radios (hidden; default matches sidebar Detail Level)
        f'<input type="radio" name="ctab{_uid}" id="{_ci}"{" checked" if not _prefer_extended else ""}>'
        f'<input type="radio" name="ctab{_uid}" id="{_ei}"{" checked" if _prefer_extended else ""}>'
        # Header
        f"<div class='brand'>{brand}</div>"
        f"<div class='product-title'>{_name_html}</div>"
        # Stacked panels — both in DOM, only one visible at a time
        f"<div class='product-details cat-panel-grid {_pg}' style='margin:0'>"
        f"<div class='cat-cpanel' style='grid-area:1/1'>{_compact_lead}{compact_html}</div>"
        f"<div class='cat-epanel' style='grid-area:1/1'>{extended_html}</div>"
        f"</div>"
        f"{_voc_footer_html}"
        # Tab bar — pure HTML labels, zero reruns
        f"<div class='cat-tab-bar {_tb}'>"
        f"<label for='{_ci}' class='cat-tab-c'>Compact</label>"
        f"<label for='{_ei}' class='cat-tab-e'>Extended</label>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Tag strip lives outside the card HTML and uses Streamlit widgets for safe writes.
    try:
        from . import lib_tags as _lt
    except Exception:
        _lt = None
    if _lt is not None and _lt.fn400_is_valid_product_id(eetra_id):
        _tag_items = _lt.fn407_get_tags_for_product(eetra_id)
        if _tag_items:
            _chips_html = " ".join(
                [
                    (
                        "<span style='display:inline-block;margin:2px 6px 2px 0;"
                        "padding:4px 10px;border-radius:999px;background:#F4F1EA;"
                        "font-size:11px;line-height:1.2;'>"
                        f"{_html.escape(str(t.get('label', '')))}</span>"
                    )
                    for t in _tag_items
                ]
            )
            st.markdown(f"<div class='eetra-cat-card-tags'>{_chips_html}</div>", unsafe_allow_html=True)
        fn329a_render_tag_popover(
            eetra_id,
            embedded=False,
            key_prefix=f"tags_pop_{eetra_id}_{_uid}",
        )


def fn329a_render_tag_popover(
    eetra_id: str,
    *,
    embedded: bool = False,
    key_prefix: str | None = None,
) -> None:
    """Render tag editor UI for a product (popover by default, inline in dialogs when embedded=True)."""
    from . import lib_tags as _lt

    if not _lt.fn400_is_valid_product_id(eetra_id):
        return
    _kp = key_prefix or f"tags_pop_{eetra_id}"
    _current = _lt.fn407_get_tags_for_product(eetra_id)
    _current_slugs = [str(x.get("slug", "")) for x in _current if x.get("slug")]

    def _render_editor_block() -> None:
        _all = _lt.fn414_list_all_tags()
        _opts = _all["tag_slug"].astype(str).tolist() if not _all.empty else []
        _label_map = {}
        if not _all.empty:
            _label_map = {
                str(r["tag_slug"]): str(r["tag_label"])
                for _, r in _all[["tag_slug", "tag_label"]].iterrows()
            }

        _sel = st.multiselect(
            "Existing tags",
            options=_opts,
            default=[s for s in _current_slugs if s in _opts],
            format_func=lambda s: _label_map.get(s, s),
            key=f"{_kp}_ms",
        )
        _sel_set = set(_sel)
        _cur_set = set(_current_slugs)
        for _slug in sorted(_sel_set - _cur_set):
            _lt.fn410_add_tag_to_product(eetra_id, _label_map.get(_slug, _slug))
        for _slug in sorted(_cur_set - _sel_set):
            _lt.fn411_remove_tag_from_product(eetra_id, _slug)
        if _sel_set != _cur_set:
            st.rerun()

        _new_label = st.text_input(
            "Or create a new tag",
            key=f"{_kp}_new",
            placeholder="Type a tag label…",
        )
        _add_cols = st.columns([1, 5], gap="small")
        with _add_cols[0]:
            _do_add = st.button("Add", key=f"{_kp}_add_btn")
        if _do_add:
            _text = str(_new_label or "").strip()
            if _text:
                _lt.fn410_add_tag_to_product(eetra_id, _text)
            st.rerun()

        if _current:
            st.caption("Remove existing tags")
            _rm_cols = st.columns(min(4, max(1, len(_current))))
            for i, _item in enumerate(_current):
                with _rm_cols[i % len(_rm_cols)]:
                    _slug = str(_item.get("slug", ""))
                    _label = str(_item.get("label", _slug))
                    if st.button(f"✕ {_label}", key=f"{_kp}_rm_{_slug}"):
                        _lt.fn411_remove_tag_from_product(eetra_id, _slug)
                        st.rerun()

        st.caption("Tags are reusable. Group products into Collections from the Collections tab.")

    if embedded:
        _render_editor_block()
    else:
        with st.popover("+ Tag", width='content'):
            _render_editor_block()


def fn330_extract_resistance_class(row) -> str:
    """Extract resistance class like 'C25/30' from D__EN206 or product name."""
    try:
        pattern = r"(C\s*\d{1,2}\s*/\s*\d{1,2})"
        texts   = []
        if "D__EN206" in row.index:
            texts.append(str(row.get("D__EN206", "")))
        texts.append(str(row.get("A__ProductName", "")))
        for t in texts:
            if t and t.strip() and str(t).strip() != "-" and not pd.isna(t):
                m = re.search(pattern, str(t), flags=re.IGNORECASE)
                if m:
                    return m.group(1).upper().replace(" ", "")
    except Exception:
        pass
    return "Unspecified"


def fn331_resistance_sort_key(label: str):
    """Numeric sort key for resistance labels."""
    if not isinstance(label, str):
        return (999, 999, "zz")
    if label.lower() == "unspecified":
        return (998, 998, label)
    m = re.match(r"C\s*(\d{1,2})\s*/\s*(\d{1,2})", label, flags=re.IGNORECASE)
    if m:
        try:
            return (int(m.group(1)), int(m.group(2)), label)
        except Exception:
            return (997, 997, label)
    return (996, 996, label)


def fn332_extract_thickness_value(row) -> float:
    """Extract thickness value in mm for sorting."""
    try:
        thickness_val = fn325_get_thickness_val(row)
        if thickness_val == "-" or pd.isna(thickness_val) or str(thickness_val).strip() == "":
            return 999999.0
        thickness_str = re.sub(r"[^\d.]", "", str(thickness_val).strip().lower())
        if thickness_str:
            return float(thickness_str)
    except Exception:
        pass
    return 999999.0


def fn333_thickness_sort_key(thickness_val: float):
    """Sort key for thickness floats."""
    return thickness_val


@st.cache_data(max_entries=256)
def fn334_cached_logo_image(logo_path: str, size: tuple[int, int] = (22, 22)):
    """Cached logo image loader + resizer (returns base64 data URI)."""
    try:
        from .lib_charts import fn202_create_logo_image
        return fn202_create_logo_image(logo_path, size=size)
    except Exception:
        return None


_MFR_LOGO_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "mfr_logos"


@st.cache_data(show_spinner=False, max_entries=1)
def _fn_catalogue_mfr_logo_urls() -> dict[str, str]:
    """Normalized manufacturer name → ``/app/static/mfr_logos/…`` URL.

    Copies files from ``img/`` / ``03_img/`` into Streamlit's static folder so
    the sandboxed catalogue iframe can load them. Missing files are skipped.
    """
    mapping = fn312_get_manufacturer_logo_mapping()
    if not mapping:
        return {}
    root = Path(__file__).resolve().parent.parent
    try:
        _MFR_LOGO_STATIC_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    urls: dict[str, str] = {}
    for name, meta in mapping.items():
        rel = ""
        if isinstance(meta, dict):
            rel = str(meta.get("logo_path") or "").strip()
        elif isinstance(meta, str):
            rel = meta.strip()
        if not rel:
            continue
        src = next(
            (p for p in (root / rel, root / "03_img" / Path(rel).name) if p.is_file()),
            None,
        )
        if src is None:
            continue
        dest = _MFR_LOGO_STATIC_DIR / src.name
        try:
            if (not dest.exists()) or dest.stat().st_mtime_ns < src.stat().st_mtime_ns:
                dest.write_bytes(src.read_bytes())
        except OSError:
            continue
        urls[str(name)] = f"/app/static/mfr_logos/{dest.name}"
    return urls


# In-page iframe preview; keep under ~5MB to avoid browser data-URI limits.
_MAX_PDF_IFRAME_BYTES = 5 * 1024 * 1024


def fn346_fetch_document_pdf_bytes(
    remote_url: str,
    eetra_id: str,
    product_name: str,
    kind: str,
    row=None,
) -> tuple[bytes | None, str | None, str | None]:
    """Return ``(pdf_bytes, file_name, source_tag)`` for preview/download."""
    from .lib_data import (
        fn142a_is_usable_document_url,
        pdf_object_name_from_row,
        resolve_local_pdf_from_row,
        resolve_local_product_pdf_path,
    )
    from .lib_doc_storage import fn_fetch_document_bytes, fn_fetch_public_url_bytes

    if row is not None:
        local_p = resolve_local_pdf_from_row(row, kind)
        remote_filename = pdf_object_name_from_row(row, kind)
    else:
        local_p = resolve_local_product_pdf_path(eetra_id, product_name, kind)
        remote_filename = local_p.name if local_p is not None else None
    bdata, source = fn_fetch_document_bytes(remote_filename, local_p)
    if bdata is None and fn142a_is_usable_document_url(remote_url):
        href = str(remote_url).strip()
        if href and "://" not in href:
            href = "https://" + href.lstrip("/")
        bdata = fn_fetch_public_url_bytes(href)
        if bdata:
            source = "url"
            file_name = Path(href.split("?", 1)[0]).name or f"{eetra_id}_{kind}.pdf"
            return bdata, file_name, source
    if bdata is None:
        return None, None, None
    file_name = local_p.name if local_p is not None else f"{eetra_id}_{kind}.pdf"
    return bdata, file_name, source


def fn347_pdf_preview_iframe_html(pdf_bytes: bytes, *, height: int = 720) -> str:
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return (
        f"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>html,body{{margin:0;padding:0;}} "
        f"iframe{{width:100%;height:{height}px;border:0;display:block;}}</style>"
        f"</head><body>"
        f"<iframe title=\"PDF preview\" src=\"data:application/pdf;base64,{b64}\"></iframe>"
        f"</body></html>"
    )


@st.dialog("VOC document", width="large")
def fn348_voc_document_pdf_dialog(pdf_bytes: bytes) -> None:
    """Modal in-app PDF preview (same window, not a new browser tab)."""
    if len(pdf_bytes) > _MAX_PDF_IFRAME_BYTES:
        st.warning("PDF is too large for in-page preview. Use Download instead.")
        return
    iframe_h = 720
    st.iframe(fn347_pdf_preview_iframe_html(pdf_bytes, height=iframe_h), height=iframe_h + 8)


# ── "View documents" popup — EPD / Technical sheet / VOC cert, with detected  ──
# document-type info from libs.lib_doc_classifier (via 01_data/pdf_manifest.csv,
# built by 04_tools/08_build_pdf_manifest.py). Triggered from the Catalogue JS2
# modal's "📑 View documents" button (bottom of the Sustainability column) via
# the ?view_docs_for= query param — see pages/2_Catalogue.py.

_PDF_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "01_data" / "pdf_manifest.csv"

_DOC_KIND_LABELS = {"epd": "EPD", "tech": "Technical sheet", "voc": "VOC certificate"}
_DOC_KIND_URL_COLS = {
    "epd": ("E__EPD_URL",),
    "tech": ("U__TechDetails_URL",),
    "voc": ("VO__VOC_URL", "U__VOC_URL"),
}

# ── Side-rail document kinds for the catalogue doc panel ──────────────────────
# Superset of _DOC_KIND_LABELS. Only epd/tech/voc are mirrored to 01_data/pdf by
# 04_tools/03_excel_to_parquet.py (see its _URL_COLS), so those preview instantly
# from disk. The rest are URL-only in the dataset: the panel attempts a cached
# fetch and otherwise offers the source link, so the rail still shows what exists.
_DOC_PANEL_KINDS: tuple[str, ...] = ("epd", "tech", "voc", "cam", "dop", "msds", "rc")
_DOC_PANEL_LABELS = {
    "epd": "EPD",
    "tech": "Tech sheet",
    "voc": "VOC",
    "cam": "CAM",
    "dop": "DoP",
    "msds": "MSDS",
    "rc": "Recycled",
}
_DOC_PANEL_URL_COLS = {
    **_DOC_KIND_URL_COLS,
    "cam": ("VV__CAM_Compliance",),
    "dop": ("VV__DOP",),
    "msds": ("VV__MSDS__URL",),
    "rc": ("R__Rec_Reco_ByProd_URL",),
}
# Kinds the pipeline downloads locally; the others are remote-only.
_DOC_PANEL_LOCAL_KINDS = frozenset({"epd", "tech", "voc"})


@st.cache_data(ttl=3600, show_spinner=False)
def fn349_load_pdf_manifest() -> dict:
    """01_data/pdf_manifest.csv keyed by filename (forward-slash, relative to project
    root). Returns {} if the manifest hasn't been generated yet — callers treat that
    as "no classification available" rather than an error."""
    import csv
    if not _PDF_MANIFEST_PATH.is_file():
        return {}
    out: dict[str, dict] = {}
    with open(_PDF_MANIFEST_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("filename") or "").replace("\\", "/")
            if key:
                out[key] = row
    return out


def fn350_manifest_info_for_path(local_path) -> dict | None:
    """Manifest row (declared_type/detected_type/confidence/mismatch/notes) for a
    resolved local PDF path, or None if unknown / manifest not built."""
    if local_path is None:
        return None
    manifest = fn349_load_pdf_manifest()
    if not manifest:
        return None
    root = Path(__file__).resolve().parent.parent
    try:
        rel = Path(local_path).resolve().relative_to(root).as_posix()
    except ValueError:
        rel = Path(local_path).as_posix()
    return manifest.get(rel)


def _document_kind_url_from_row(row, kind: str) -> str:
    from .lib_data import fn142a_is_usable_document_url
    for col in _DOC_PANEL_URL_COLS.get(kind, ()):
        if hasattr(row, "index") and col not in row.index:
            continue
        try:
            val = row.get(col) if hasattr(row, "get") else row[col]
        except (KeyError, TypeError):
            continue
        if fn142a_is_usable_document_url(val):
            return str(val).strip()
    return ""


_DOC_LOCAL_COLS = (
    "E__EPD_Local", "U__TechDetails_Local", "VO__VOC_Local", "U__VOC_Local_alt",
)
@st.cache_data(ttl=3600, show_spinner=False)
def fn352_local_pdf_paths_by_id() -> dict:
    """{EETRA_ID: {local_col: path}} from the effective dataset (base ⊕ edits).

    The app's live dataframe often comes straight from the SharePoint Excel, which
    has no ``*_Local`` columns — those are written by 04_tools/03_excel_to_parquet.py.
    Without this fallback every document would resolve to an external link only,
    never the local file, so no in-app preview would ever be possible.

    Read from the merge rather than the retired ``live_data.parquet``, which was a
    materialised copy of exactly this and one of four identical parquets.
    """
    try:
        from .lib_data import fn159_effective_dataset

        df = fn159_effective_dataset(["0__EETRA_ID", *_DOC_LOCAL_COLS])
    except Exception:
        return {}
    if df.empty or "0__EETRA_ID" not in df.columns:
        return {}
    out: dict[str, dict] = {}
    for rec in df.to_dict("records"):
        eid = str(rec.get("0__EETRA_ID", "") or "").strip()
        if not eid:
            continue
        out[eid] = {
            c: str(rec[c]).strip()
            for c in _DOC_LOCAL_COLS
            if rec.get(c) is not None and str(rec.get(c)).strip() not in ("", "None", "nan", "<NA>")
        }
    return out


def _row_with_local_paths(row, eetra_id: str):
    """Row augmented with ``*_Local`` columns from the parquet when it lacks them."""
    # No ``or ""`` here: these columns are pandas "string" dtype when the row came
    # from the parquet, so a missing value is pd.NA and ``NA or ""`` raises
    # "boolean value of NA is ambiguous". str(pd.NA) is "<NA>", already excluded.
    have = any(
        str(row.get(c, "")).strip() not in ("", "None", "nan", "<NA>")
        for c in _DOC_LOCAL_COLS
    )
    if have:
        return row
    extra = fn352_local_pdf_paths_by_id().get(str(eetra_id).strip())
    if not extra:
        return row
    merged = row.copy() if hasattr(row, "copy") else dict(row)
    for col, val in extra.items():
        merged[col] = val
    return merged


def _catalogue_bridge_payload(key: str = "catalogue_bridge"):
    """The bridge component's current value, rendering it at most once per run.

    The bridge carries several action types on one component instance, so callers
    ask about each type in turn. Re-rendering the component per question would
    raise a duplicate-key error, hence the per-run cache.
    """
    try:
        from .catalogue_bridge import catalogue_bridge
    except Exception:
        return None

    run_seq = st.session_state.get(_RUN_SEQ_KEY)
    cache_key = f"_{key}_payload_cache"
    cached = st.session_state.get(cache_key)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == run_seq:
        return cached[1]

    payload = catalogue_bridge(key=key)
    st.session_state[cache_key] = (run_seq, payload)
    return payload


def fn352_catalogue_bridge_action(action_type: str, key: str = "catalogue_bridge") -> str | None:
    """Return a fresh ``eetraId`` for *action_type* from the catalogue bridge, or None.

    The component value persists across reruns, so each payload is returned
    exactly once — tracked by its ``nonce`` in session state. Without that, a
    panel opened from the returned id would reopen on every subsequent rerun
    (including the one triggered by closing it).
    """
    payload = _catalogue_bridge_payload(key)
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != action_type:
        return None
    eetra_id = str(payload.get("eetraId") or "").strip()
    if not eetra_id:
        return None

    nonce = payload.get("nonce")
    seen_key = f"_{key}_{action_type}_nonce"
    if nonce is not None and st.session_state.get(seen_key) == nonce:
        return None
    st.session_state[seen_key] = nonce
    return eetra_id


def fn353_catalogue_bridge_action_kind(
    action_type: str, key: str = "catalogue_bridge"
) -> str:
    """The ``kind`` on the bridge's current payload for *action_type*, or ``""``.

    Read-only companion to :func:`fn352_catalogue_bridge_action`: it deliberately
    does *not* consume the nonce, so callers ask for the id first and then for the
    kind that came with it, on the same payload.
    """
    payload = _catalogue_bridge_payload(key)
    if not isinstance(payload, dict) or payload.get("type") != action_type:
        return ""
    return str(payload.get("kind") or "").strip()


def fn351_render_document_viewer(row, eetra_id: str, product_name: str) -> None:
    """One tab per document kind present (EPD / Technical sheet / VOC cert): declared
    vs. detected type + confidence/mismatch badge, then an in-page PDF preview.

    ``row`` must support ``.get(col)`` (a pandas Series or dict-like row).
    """
    from .lib_data import resolve_local_pdf_from_row

    row = _row_with_local_paths(row, eetra_id)
    kinds_present = []
    for kind in ("epd", "tech", "voc"):
        url = _document_kind_url_from_row(row, kind)
        local_p = resolve_local_pdf_from_row(row, kind)
        if url or local_p is not None:
            kinds_present.append((kind, url, local_p))

    if not kinds_present:
        st.info("No EPD, technical sheet, or VOC document is on file for this product.", icon="ℹ️")
        return

    tabs = st.tabs([_DOC_KIND_LABELS[k] for k, _, _ in kinds_present])
    for (kind, url, local_p), tab in zip(kinds_present, tabs):
        with tab:
            info = fn350_manifest_info_for_path(local_p)
            if info:
                declared = info.get("declared_type", "") or "—"
                detected = info.get("detected_type", "") or "—"
                confidence = info.get("confidence", "") or "—"
                mismatch = (info.get("mismatch", "") or "").strip().lower() == "true"
                badge = "⚠️ possible mismatch" if mismatch else "✅ consistent"
                st.caption(
                    f"Declared: **{declared}** · Detected: **{detected}** "
                    f"({confidence} confidence) · {badge}"
                )
                # Heuristic notes are raw score dumps ("scores: {...}") — internal
                # debug detail, not something to show end users. Claude-written
                # notes are prose and worth surfacing on a mismatch.
                _notes = (info.get("notes") or "").strip()
                if mismatch and _notes and not _notes.startswith("scores:"):
                    st.caption(f"_{_notes}_")
                elif mismatch:
                    st.caption(
                        "_The file on record doesn't look like the declared document "
                        "type — the source URL may point at a web page rather than the "
                        "certificate itself._"
                    )
            elif local_p is not None:
                st.caption(
                    "Not yet classified — run `04_tools/08_build_pdf_manifest.py` "
                    "to add document-type detection."
                )

            bdata, file_name, _source = fn346_fetch_document_pdf_bytes(
                url, eetra_id, product_name, kind, row=row
            )
            if bdata is None:
                if url:
                    st.link_button(
                        f"Open {_DOC_KIND_LABELS[kind]} (external link)", url, width="stretch"
                    )
                else:
                    st.warning("File not available locally or remotely.")
                continue

            # Not every file on record is really a PDF: a source URL that pointed
            # at a web page was downloaded and stored as ".pdf" anyway (see the
            # mismatch cases in 01_data/pdf_manifest.csv). Handing those to the
            # viewer renders a tall blank pane, so check the magic bytes and say
            # what's actually wrong instead.
            if not bdata.startswith(b"%PDF"):
                st.warning(
                    "This file isn't a valid PDF — it looks like a saved web page, "
                    "so there's nothing to preview. The source URL for this product "
                    "probably needs correcting.",
                    icon="⚠️",
                )
            elif len(bdata) <= _MAX_PDF_IFRAME_BYTES:
                iframe_h = 640
                st.iframe(fn347_pdf_preview_iframe_html(bdata, height=iframe_h), height=iframe_h + 8)
            else:
                st.caption("PDF is too large for in-page preview. Use Download instead.")

            dl_col, link_col = st.columns(2)
            with dl_col:
                st.download_button(
                    "Download PDF",
                    data=bdata,
                    file_name=file_name or f"{eetra_id}_{kind}.pdf",
                    mime="application/pdf",
                    width="stretch",
                    key=f"docview_dl_{kind}_{eetra_id}",
                )
            with link_col:
                if url:
                    st.link_button(
                        "Open source link", url, width="stretch",
                        key=f"docview_link_{kind}_{eetra_id}",
                    )


# ── Catalogue doc panel payload (side-rail PDF preview inside the JS2 iframe) ──
# The JS2 component is a srcdoc iframe, so it cannot read 01_data/pdf itself.
# Python resolves every document a product has and hands the bytes over as data
# URIs in one payload, which lets the rail switch between EPD / VOC / CAM etc.
# entirely client-side — no rerun per tab.

@st.cache_data(ttl=3600, show_spinner=False)
def _sync_static_docs_once() -> dict:
    """Hard-link 01_data/pdf into static/docs, at most once an hour per session.

    Cached rather than called per render: warm it costs a 900-entry directory
    walk, and the catalogue re-renders on every rerun. A pipeline run that adds
    PDFs is picked up when the cache expires, or on the next app restart.
    """
    from .lib_doc_storage import fn_sync_static_doc_links

    try:
        return fn_sync_static_doc_links()
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _static_doc_file_info() -> dict:
    """``{filename: {"pdf": bool, "kb": int, "ts": "YYYY-MM-DD"}}`` for static/docs.

    Cached because the catalogue re-renders on every rerun and this stats + reads
    the first bytes of ~900 files. Two reasons it happens server-side:

    * Some stored files are a saved web page the pipeline wrote as ".pdf" (see
      01_data/pdf_manifest.csv). The browser can't sniff the magic bytes without
      fetching the file, so the check has to happen here.
    * The document list shows each file's size and date, which the browser
      likewise can't know without downloading it first.

    ``ts`` is the file's modification time — i.e. when the pipeline retrieved it,
    NOT when the manufacturer issued the document. Labelled accordingly in the UI.
    """
    from .lib_doc_storage import fn_static_docs_dir

    info: dict[str, dict] = {}
    d = fn_static_docs_dir()
    if not d.is_dir():
        return info
    # scandir: iterdir + is_file + stat was three syscalls per file where the
    # directory enumeration already carries the answer to two of them. The open()
    # below stays — the magic-byte check genuinely has to read the file.
    with os.scandir(d) as it:
        entries = list(it)
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            stat = entry.stat()
            with open(entry.path, "rb") as fh:
                is_pdf = fh.read(5) == b"%PDF-"
            info[entry.name] = {
                "pdf": is_pdf,
                "kb": max(1, int(round(stat.st_size / 1024))),
                "ts": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y"),
            }
        except OSError:
            info[entry.name] = {"pdf": False, "kb": 0, "ts": ""}
    return info


def _attach_static_doc_urls(df_slim: "pd.DataFrame", df_source: "pd.DataFrame") -> None:
    """Add a ``docMeta`` column: ``{kind: {url, kb, ts, bad}}`` per product.

    This is what lets the document panel open with no Streamlit rerun — the iframe
    fetches the PDF over HTTP itself, and the document list can show each file's
    size and retrieval date. Only kinds the pipeline mirrors locally (EPD / tech
    sheet / VOC) appear here; the rest stay remote-only and are derived in the
    browser from the product's URL fields.

    ``bad`` marks a stored file that isn't really a PDF (a saved web page written
    with a .pdf extension), so the panel can explain instead of showing a blank
    pane. Resolved from the parquet's ``*_Local`` columns, falling back to the
    by-id map because the live dataframe usually comes from the SharePoint Excel,
    which has no ``*_Local`` columns at all.
    """
    from .lib_doc_storage import fn_static_doc_url

    _sync_static_docs_once()

    id_col = "0__EETRA_ID"
    if id_col not in df_source.columns:
        df_slim["docMeta"] = [{} for _ in range(len(df_slim))]
        return

    try:
        by_id = fn352_local_pdf_paths_by_id()
    except Exception:
        by_id = {}

    kind_cols = {
        "epd": ("E__EPD_Local",),
        "tech": ("U__TechDetails_Local",),
        "voc": ("VO__VOC_Local", "U__VOC_Local_alt"),
    }
    file_info = _static_doc_file_info()
    probe_cache: dict[str, dict] = {}

    def _probe(name: str) -> dict:
        """``{url, kb, ts, bad}`` for a stored path, or ``{}`` when absent."""
        if name not in probe_cache:
            url = fn_static_doc_url(name)
            if not url:
                probe_cache[name] = {}
            else:
                meta = file_info.get(Path(name.replace("\\", "/")).name, {})
                probe_cache[name] = {
                    "url": url,
                    "kb": meta.get("kb", 0),
                    "ts": meta.get("ts", ""),
                    "bad": not meta.get("pdf", False),
                }
        return probe_cache[name]

    ids = df_source[id_col].astype(str).str.strip().tolist()

    # The four *_Local columns as plain lists, once. The loop below wants a
    # single cell, but reached it through df_source.iloc[pos][col] — a full
    # 135-column row materialisation, run up to four times per product, for one
    # string. Column-at-a-time costs one pass and makes the lookup an index.
    col_values: dict[str, list] = {}
    for _cols in kind_cols.values():
        for _col in _cols:
            if _col in df_source.columns and _col not in col_values:
                col_values[_col] = df_source[_col].tolist()

    out: list[dict] = []
    for pos, eid in enumerate(ids):
        local = by_id.get(eid) or {}
        meta: dict[str, dict] = {}
        for kind, cols in kind_cols.items():
            for col in cols:
                raw = local.get(col)
                if not raw and col in col_values:
                    try:
                        val = col_values[col][pos]
                        raw = "" if pd.isna(val) else str(val).strip()
                    except Exception:
                        raw = ""
                if raw and str(raw) not in ("None", "nan", "<NA>"):
                    probed = _probe(str(raw))
                    if probed:
                        meta[kind] = probed
                        break
        out.append(meta)
    df_slim["docMeta"] = out


# Raster preview limits. The panel is a narrow side rail, so 1.6× the PDF's
# natural size is already finer than the pane can show. JPEG rather than PNG:
# these images are base64-inlined into the component's srcdoc, and on a real
# 14-page data sheet PNG costs 7.7 MB against JPEG's 1.7 MB at identical zoom —
# a preview pane (with Download alongside for the real file) does not warrant
# quadrupling the payload for lossless text edges. The two caps are backstops
# for pathological documents; the page cap normally binds first.
_DOC_RASTER_ZOOM = 1.6
_DOC_RASTER_JPEG_QUALITY = 78
_DOC_RASTER_MAX_PAGES = 24
_DOC_RASTER_MAX_BYTES = 6 * 1024 * 1024


@st.cache_data(show_spinner=False, max_entries=24)
def fn358_rasterize_pdf_pages(pdf_bytes: bytes) -> tuple[list[str], int]:
    """``([JPEG data URI per page], total_page_count)`` for an in-panel preview.

    Server-side rendering with PyMuPDF, the same approach the EPD Parse page uses
    for its docked preview. The catalogue component is a *sandboxed srcdoc*
    iframe, and inside it every browser-native PDF route is unavailable: framing
    a PDF (static URL or ``data:`` URI) in a further-nested iframe is blocked,
    and pdf.js can't run either because ``location.origin`` is the literal string
    ``"null"`` there, which defeats its worker same-origin check. Plain ``<img>``
    tags have none of those constraints — so the pages are rasterised here and
    the component only ever displays images.

    Cached on the PDF bytes: paging back and forth in the panel (each a rerun)
    re-renders nothing.
    """
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        total = doc.page_count
        mat = fitz.Matrix(_DOC_RASTER_ZOOM, _DOC_RASTER_ZOOM)
        pages: list[str] = []
        spent = 0
        for i in range(min(total, _DOC_RASTER_MAX_PAGES)):
            img = doc.load_page(i).get_pixmap(matrix=mat, alpha=False).tobytes(
                "jpg", jpg_quality=_DOC_RASTER_JPEG_QUALITY
            )
            uri = "data:image/jpeg;base64," + base64.b64encode(img).decode("ascii")
            # Always keep page 1, then stop before the budget is exceeded rather
            # than after — the panel reports how many of the total it is showing.
            if pages and spent + len(uri) > _DOC_RASTER_MAX_BYTES:
                break
            pages.append(uri)
            spent += len(uri)
    return pages, total


def fn357_build_doc_panel_payload(
    row,
    eetra_id: str,
    product_name: str,
    *,
    fetch_remote: bool = True,
    raster_kind: str = "",
) -> dict:
    """``{eetraId, productName, docs:[…]}`` for the catalogue side-rail doc panel.

    One entry per document kind the product actually has, in ``_DOC_PANEL_KINDS``
    order. ``dataUri`` is set only when real PDF bytes were resolved and are small
    enough to inline; otherwise the entry carries ``url``/``note`` so the panel can
    offer the source link instead of rendering a blank pane.

    ``fetch_remote=False`` restricts resolution to bytes already on disk or in the
    bucket cache, so a caller can avoid network latency during a rerun.

    ``raster_kind`` names the one document the user asked to preview: its pages are
    rasterised to PNG data URIs (``pages``/``pageCount``) so the component can
    display them as plain images — see :func:`fn358_rasterize_pdf_pages` for why
    that is the only viable route inside the catalogue iframe. Only that document
    is rendered, since rasterising every kind on the chance one gets opened would
    cost far more than the preview itself.
    """
    from .lib_data import resolve_local_pdf_from_row

    row = _row_with_local_paths(row, eetra_id)
    docs: list[dict] = []
    # Several fields legitimately cite the SAME file — most commonly the EPD is
    # also the recycled-content evidence (863 rows share E__EPD_URL with
    # R__Rec_Reco_ByProd_URL). Collapse those so the rail doesn't offer one
    # document under two labels, and so its bytes are only inlined once.
    by_source: dict[str, dict] = {}

    for kind in _DOC_PANEL_KINDS:
        url = _document_kind_url_from_row(row, kind)
        local_p = resolve_local_pdf_from_row(row, kind) if kind in _DOC_PANEL_LOCAL_KINDS else None
        if not url and local_p is None:
            continue

        label = _DOC_PANEL_LABELS.get(kind, kind.upper())
        # Index under every identifier the entry has: one kind may be recognised
        # by its local file and another only by its URL, and they still point at
        # the same document (EPD vs recycled-content evidence).
        keys = [k for k in (url, str(local_p) if local_p is not None else "") if k]
        dup = next((by_source[k] for k in keys if k in by_source), None)
        if dup is not None:
            dup.setdefault("alsoLabels", []).append(label)
            continue

        entry = {
            "kind": kind,
            "label": label,
            "url": url or "",
            "dataUri": "",
            "fileName": "",
            "note": "",
            "pages": [],
            "pageCount": 0,
        }
        for k in keys:
            by_source[k] = entry

        bdata = file_name = None
        if local_p is not None or fetch_remote:
            try:
                bdata, file_name, _src = fn346_fetch_document_pdf_bytes(
                    url if fetch_remote else "", eetra_id, product_name, kind, row=row
                )
            except Exception:
                bdata = file_name = None

        if bdata is None:
            entry["note"] = (
                # A fetch was actually attempted and failed — most often the
                # manufacturer's site blocking automated requests (Cloudflare bot
                # checks on the Saint-Gobain family of sites return this way), not
                # a data problem. A real browser tab isn't automated, so it works.
                "Couldn't retrieve this document automatically — the source may "
                "block automated requests. Use Source ↗ to open it directly."
                if url else "File not available locally or remotely."
            )
        elif not bdata.startswith(b"%PDF"):
            # A source URL that pointed at a web page was still saved as ".pdf";
            # handing that to the viewer renders a blank pane (see pdf_manifest.csv).
            entry["note"] = (
                "This file isn't a valid PDF — it looks like a saved web page, so "
                "there's nothing to preview. The source URL likely needs correcting."
            )
        else:
            entry["fileName"] = file_name or f"{eetra_id}_{kind}.pdf"
            if kind == raster_kind:
                # Rendered server-side, so the file's own size no longer limits
                # previewing — only the rasterised pages travel to the browser,
                # and those are capped by page count rather than by source bytes.
                try:
                    pages, total = fn358_rasterize_pdf_pages(bdata)
                except Exception as _e:  # corrupt/encrypted PDF
                    entry["note"] = f"Couldn't render this document for preview: {_e}"
                else:
                    entry["pages"] = pages
                    entry["pageCount"] = total
            elif len(bdata) > _MAX_PDF_IFRAME_BYTES:
                entry["note"] = "PDF is too large to preview in-page — use the source link."
            else:
                # No raster requested for this kind: carry the bytes so the panel
                # can still tell that a preview *is* available (and offer it).
                entry["dataUri"] = (
                    "data:application/pdf;base64,"
                    + base64.b64encode(bdata).decode("ascii")
                )

        docs.append(entry)

    return {
        "eetraId": str(eetra_id or "").strip(),
        "productName": str(product_name or ""),
        "docs": docs,
    }


def _catalogue_detail_pdf_actions(
    link_label: str,
    preview_label: str,
    remote_url: str,
    eetra_id: str,
    product_name: str,
    kind: str,
    row=None,
) -> None:
    """
    Local ``data/pdf`` files: in-page preview via ``st.expander`` + iframe
    (``data:application/pdf;base64``). No pop-ups. Oversize files: download + link only.

    ``row`` (the catalogue dataframe row), when given, resolves the actual
    on-disk file via its hash-named ``*_Local`` column — this is also the
    filename used as the bucket object key for the remote lookup, so a local
    file and its bucket mirror always share one name. Without ``row`` this
    falls back to the legacy product-name-based filename convention.
    """
    from .lib_data import prefer_local_document_href

    href = prefer_local_document_href(remote_url, eetra_id, product_name, kind)
    bdata, file_name, source = fn346_fetch_document_pdf_bytes(
        remote_url, eetra_id, product_name, kind, row=row
    )
    if bdata is None:
        st.link_button(link_label, href, width='stretch')
        return
    path_key = hashlib.md5(f"{source}:{eetra_id}:{product_name}:{kind}".encode()).hexdigest()[:14]
    if len(bdata) <= _MAX_PDF_IFRAME_BYTES:
        iframe_h = 720
        with st.expander(preview_label, expanded=False, type="compact"):
            st.iframe(fn347_pdf_preview_iframe_html(bdata, height=iframe_h), height=iframe_h + 8)
    else:
        st.caption("PDF is too large for in-page preview; use Download or Open.")
    st.download_button(
        "Download PDF",
        data=bdata,
        file_name=file_name,
        mime="application/pdf",
        width='stretch',
        key=f"eetra_pdf_dl_{kind}_{path_key}",
    )
    st.link_button(link_label, href, width='stretch')


# ── VOC certification badges (``03_img/``, see _VOC_CERT_KINDS) ──────────────
# Catalogue footer raster height (was ~22px; +100% for card footer strip).
_VOC_CERT_FOOTER_RASTER_MAX_H = 56

# One entry per certification scheme that has (or will get) a badge image.
#   pattern  matched case-insensitively against VO__VOC_Cert, NBSP normalised; hyphens or
#            spaces between words (e.g. "Indoor-Air Gold"), and the spellings found in the data
#   alt      tooltip / alt text;  short  text fallback when the image cannot be read
#   files    candidate files under 03_img/ (first one found wins)
# A scheme whose image file is missing simply stays plain text: drop the PNG into
# 03_img/ and restart the app to switch its badge on. Order is the order badges appear in.
_VOC_CERT_KINDS: dict[str, dict] = {
    "iag": {
        "pattern": r"\b(?:indoor[-\s]+air(?:[-\s]+comfort)?[-\s]+gold|iac[-\s]*gold)\b",
        "alt": "Indoor Air Gold", "short": "IAG",
        "files": ("logo-ef-indoor-air-comfort-gold.png", "IAG_small.png", "iag_small.png"),
    },
    "m1": {
        "pattern": r"\bm1\b(?:\s+(?:class|classification))?",
        "alt": "M1", "short": "M1",
        "files": ("M1-logo_RGB_english.png", "M1_small.png", "m1_small.png"),
    },
    "floorscore": {
        "pattern": r"\bfloor[-\s]*score\b",
        "alt": "FloorScore", "short": "FS",
        "files": ("floorscore.png",),
    },
    "greenguard_gold": {
        # the data holds "Greengaurd Gold" and "GREENGUARD GOLD"
        "pattern": r"\bgreen[-\s]*g(?:ua|au)rd[-\s]+gold\b",
        "alt": "UL GREENGUARD Gold", "short": "GG",
        "files": ("greenguard-gold.png",),
    },
    "blue_angel": {
        "pattern": r"\bblue[-\s]+angel\b",
        "alt": "Blue Angel", "short": "BA",
        "files": ("blue-angel.png",),
    },
    "emicode_ec1plus": {
        # EC1PLUS only: the "plus" is required, so plain "EMICODE EC1" (and EC2)
        # stay unbadged rather than borrowing the EC1 PLUS badge.
        "pattern": r"\b(?:emicode[-\s]+)?ec1[-\s]*(?:plus|\+)",
        "alt": "EMICODE EC1 PLUS", "short": "EC1+",
        "files": ("emicode-ec1plus.png",),
    },
    "french_a_plus": {
        # A+ only: "french" must be followed by an A+ class within the same claim
        # (brackets allowed, separators not), so "French VOC Label (A)" and the
        # B/C classes do not pick up the A+ badge.
        "pattern": r"\bfrench\b[^/,;]{0,40}?\ba\s*\+",
        "alt": "French VOC label A+", "short": "A+",
        "files": ("french-voc-a-plus.png",),
    },
}


def _voc_cert_normalize_label(s: str) -> str:
    """Collapse odd whitespace / unicode spaces so regexes match Excel/PDF exports."""
    t = unicodedata.normalize("NFKC", str(s))
    t = t.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    return " ".join(t.split()).strip()


def _voc_cert_resolve_badge_path(rel_name: str) -> Path | None:
    """Resolve ``img/<rel_name>`` or ``data/img/<rel_name>`` under known project roots."""
    roots: list[Path] = []
    try:
        roots.append(Path(__file__).resolve().parent.parent)
    except Exception:
        pass
    try:
        cwd = Path.cwd().resolve()
        if cwd not in roots:
            roots.append(cwd)
    except Exception:
        pass
    er = os.environ.get("EETRA_MATLIB_ROOT", "").strip()
    if er:
        ep = Path(er).expanduser().resolve()
        if ep not in roots:
            roots.append(ep)
    rel_dirs = (Path("03_img"), Path("01_data") / "img")
    for root in roots:
        for rd in rel_dirs:
            cand = root / rd / rel_name
            if cand.is_file():
                return cand
    return None


def _voc_cert_badge_path_for_kind(kind: str) -> Path | None:
    for n in _VOC_CERT_KINDS.get(kind, {}).get("files", ()):
        p = _voc_cert_resolve_badge_path(n)
        if p is not None:
            return p
    return None


@_lru_cache(maxsize=1)
def _voc_cert_available_kinds() -> tuple[str, ...]:
    """Kinds whose badge image exists, in registry order.

    Only these are recognised in the cert text: a scheme without an image must keep
    its wording on the card rather than be stripped for a badge that cannot render.
    Process-lifetime memo, like the composite badges: the files are static assets.
    """
    return tuple(k for k in _VOC_CERT_KINDS if _voc_cert_badge_path_for_kind(k) is not None)


@_lru_cache(maxsize=1)
def _voc_cert_token_re() -> re.Pattern:
    """One alternation of the available kinds' patterns; group name = kind."""
    parts = [f"(?P<{k}>{_VOC_CERT_KINDS[k]['pattern']})" for k in _voc_cert_available_kinds()]
    return re.compile("(?i)" + ("|".join(parts) if parts else r"(?!x)x"))


def _voc_cert_kinds_in_text(s: str) -> list[str]:
    """Available badge kinds named in a cert string, in registry order."""
    t = _voc_cert_normalize_label(s)
    if not t:
        return []
    return [k for k in _voc_cert_available_kinds()
            if re.search("(?i)" + _VOC_CERT_KINDS[k]["pattern"], t)]


def _voc_cert_raster_to_data_uri(path: Path, *, max_height: int = _VOC_CERT_FOOTER_RASTER_MAX_H) -> str | None:
    """Load a badge file, downscale for inline HTML, return PNG data URI."""
    try:
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        if max_height > 0 and h > max_height:
            nh = max_height
            nw = max(1, int(w * (nh / float(h))))
            _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
            im = im.resize((nw, nh), _LANCZOS)
        buf = BytesIO()
        im.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def _voc_cert_badge_data_uri(kind: str, *, max_raster_height: int = _VOC_CERT_FOOTER_RASTER_MAX_H) -> str | None:
    p = _voc_cert_badge_path_for_kind(kind)
    if p is None:
        return None
    u = _voc_cert_raster_to_data_uri(p, max_height=max_raster_height)
    if u:
        return u
    from .lib_data import image_path_to_data_uri

    return image_path_to_data_uri(p)


def _voc_cert_kinds_from_row(row: pd.Series) -> list[str]:
    """Badge kinds detected from ``VO__VOC_Cert`` (same rules as composite list column)."""
    return _voc_cert_kinds_in_text(_row_cell_first(row, "VO__VOC_Cert", "V__VOC_Cert"))


def _voc_cert_footer_bar_html(kinds: list[str]) -> str:
    """Bottom-of-card badge strip for fn329 (images only, no duplicate cert text)."""
    if not kinds:
        return ""
    mh = _VOC_CERT_FOOTER_RASTER_MAX_H
    parts: list[str] = []
    for k in kinds:
        u = _voc_cert_badge_data_uri(k, max_raster_height=mh)
        if not u:
            continue
        alt = _VOC_CERT_KINDS[k]["alt"]
        he = _html.escape(u, quote=True)
        ea = _html.escape(alt, quote=True)
        parts.append(
            f'<img class="eetra-voc-cert-badge eetra-voc-cert-badge--footer" src="{he}" alt="" title="{ea}" '
            f'style="height:{mh}px;width:auto;max-width:{mh * 6}px;object-fit:contain;vertical-align:middle;'
            f'border:none;background:transparent;padding:0;" />'
        )
    if not parts:
        return ""
    return '<div class="eetra-voc-cert-footer" role="presentation">' + "".join(parts) + "</div>"


def _voc_cert_inline_img_html(kind: str) -> str:
    uri = _voc_cert_badge_data_uri(kind, max_raster_height=_VOC_CERT_FOOTER_RASTER_MAX_H)
    alt = _VOC_CERT_KINDS[kind]["alt"]
    short = _VOC_CERT_KINDS[kind]["short"]
    if not uri:
        ta = _html.escape(alt, quote=True)
        ts = _html.escape(short)
        return (
            f'<span class="eetra-voc-cert-fallback" title="{ta}" '
            'style="display:inline-block;font-size:9px;font-weight:700;line-height:1.15;'
            "vertical-align:middle;padding:1px 6px;border-radius:4px;border:1px solid #64748b;"
            'color:#0f172a;background:#f1f5f9;">'
            f"{ts}</span>"
        )
    he = _html.escape(uri, quote=True)
    ea = _html.escape(alt, quote=True)
    return (
        f'<img class="eetra-voc-cert-badge" src="{he}" alt="{ea}" title="{ea}" '
        f'style="height:{_VOC_CERT_FOOTER_RASTER_MAX_H}px;width:auto;max-width:{_VOC_CERT_FOOTER_RASTER_MAX_H * 6}px;'
        'min-height:12px;vertical-align:middle;display:inline-block;object-fit:contain;" />'
    )


def _voc_text_with_cert_icon_html(s: str) -> str:
    """Escape ``s`` but replace known VOC certification phrases with inline badge images."""
    if not s:
        return ""
    s = _voc_cert_normalize_label(s)
    if not s:
        return ""
    out: list[str] = []
    pos = 0
    for m in _voc_cert_token_re().finditer(s):
        if m.start() > pos:
            out.append(_html.escape(s[pos : m.start()]))
        out.append(_voc_cert_inline_img_html(m.lastgroup))
        pos = m.end()
    if pos < len(s):
        out.append(_html.escape(s[pos:]))
    return "".join(out)


def _voc_catalog_fragment_to_html(fragment: str) -> str:
    """One VOC line from :func:`_voc_detail_texts_and_urls` — keep ``Cat. …`` as plain text."""
    t = _voc_cert_normalize_label(str(fragment))
    if re.match(r"(?i)Cat\.\s", t):
        return _html.escape(fragment)
    return _voc_text_with_cert_icon_html(fragment)


def fn346_voc_cert_composite_data_uri(cert: str | None) -> str | None:
    """Side-by-side badge PNG as a data URI (Streamlit ``ImageColumn`` / list view)."""
    if cert is None:
        return None
    s = _voc_cert_normalize_label(str(cert))
    if not s or s.lower() in ("-", "nan", "none"):
        return None
    kinds = _voc_cert_kinds_in_text(s)
    if not kinds:
        return None
    return _voc_cert_composite_for_kinds(tuple(kinds))


@_lru_cache(maxsize=16)
def _voc_cert_composite_for_kinds(kinds: tuple[str, ...]) -> str | None:
    """The composite badge itself, memoised on the badge kinds it is built from.

    There are few reachable results here — one per scheme and the handful of
    combinations that occur — but the catalogue asked for one per row: 1,198 calls per
    render, each re-opening the badge PNGs and redoing a resize, a paste and a
    PNG encode, for about 40% of the whole payload build. Keying on the derived
    kinds rather than on the certification text collapses the many spellings
    ("M1", "M1 class", "M1 classification", …) onto the same entry.

    Process-lifetime rather than @st.cache_data: the inputs are static PNGs
    under 03_img, so there is nothing for a TTL to pick up, and this is called
    from inside a df.apply where cache-machinery overhead would show.
    """
    imgs: list[Image.Image] = []
    for k in kinds:
        p = _voc_cert_badge_path_for_kind(k)
        if p is None:
            continue
        try:
            im = Image.open(p).convert("RGBA")
            mh = _VOC_CERT_FOOTER_RASTER_MAX_H
            w, h = im.size
            if mh > 0 and h > mh:
                nh = mh
                nw = max(1, int(w * (nh / float(h))))
                _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
                im = im.resize((nw, nh), _LANCZOS)
            imgs.append(im)
        except Exception:
            continue
    if not imgs:
        return None
    gap = 2
    h = max(im.height for im in imgs)
    w = sum(im.width for im in imgs) + gap * max(0, len(imgs) - 1)
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    x = 0
    for im in imgs:
        y = max(0, (h - im.height) // 2)
        canvas.paste(im, (x, y), im)
        x += im.width + gap
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _voc_cert_remainder_plain(cert: str) -> str:
    """Text left in ``V__VOC_Cert`` after removing the phrases a badge stands for (list view)."""
    if not cert or not str(cert).strip():
        return ""
    s = _voc_cert_normalize_label(str(cert))
    t = _voc_cert_token_re().sub("", s)
    t = re.sub(r"[\s,;/]+", " ", t).strip(" ,;/")
    return t


# VOC cells may include http(s) URLs; strip for display and attach 🔗. Allow query strings etc.
_VOC_INLINE_URL_RE = re.compile(r"https?://[^\s<>\[\]()]+", re.I)


def _detail_panel_green_separator_html() -> str:
    """Match catalogue card green rule (``field_ui_settings`` divider colour)."""
    try:
        ui = st.session_state.get("FIELD_UI_SETTINGS", {}) or {}
    except Exception:
        ui = {}
    col = str(ui.get("divider_color", "#2a7d2e")).strip() or "#2a7d2e"
    try:
        wpx = max(1, int(float(str(ui.get("divider_border_px", "1")).strip() or "1")))
    except Exception:
        wpx = 1
    ec = _html.escape(col, quote=True)
    return (
        f'<div style="border-top:{wpx}px solid {ec};'
        'width:60%;margin:10px 0 12px 0;"></div>'
    )


def _voc_detail_scan_strings(*parts: str) -> tuple[list[str], list[str]]:
    """Return (non-url text fragments per scanned string, URLs in order, de-duplicated)."""
    texts: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        if not raw:
            continue
        s = " ".join(str(raw).split()).strip()
        if not s:
            continue
        pos = 0
        chunks: list[str] = []
        for m in _VOC_INLINE_URL_RE.finditer(s):
            if m.start() > pos:
                ch = s[pos:m.start()].strip(" -;,\t")
                if ch:
                    chunks.append(ch)
            u = m.group(0).rstrip(").,;]")
            if u not in seen:
                seen.add(u)
                urls.append(u)
            pos = m.end()
        tail = s[pos:].strip(" -;,\t")
        if tail:
            chunks.append(tail)
        if chunks:
            texts.append(" - ".join(chunks))
        elif not _VOC_INLINE_URL_RE.search(s):
            texts.append(s)
    return texts, urls


def _js2_product_type_lower(row: pd.Series, *, catalog: bool = False) -> str:
    col = "D__ProductType_ENG" if catalog else "productType"
    return str(row.get(col) or "").lower()


def _js2_density_relevant_product_type(pt: str) -> bool:
    pt = (pt or "").lower()
    return "building board" in pt or "insulation" in pt or "tile" in pt


def _gwp_list_num(raw: str) -> str:
    if raw == "-" or not str(raw).strip():
        return ""
    try:
        f = float(str(raw).replace(",", "."))
        if f == 0:
            return ""
        s = f"{f:.2f}".rstrip("0").rstrip(".")
        return s if s else "0"
    except (TypeError, ValueError):
        s = str(raw).strip()
        return s if s and s != "-" else ""


def _gwp_list_fu_suffix(fu_raw: str) -> str:
    """Declared FU token for ``kgCO₂e/{fu}`` (m², m³, kg, …)."""
    u = str(fu_raw or "").strip()
    if not u or u == "-":
        return ""
    u = u.replace("m2", "m²").replace("m3", "m³")
    u = re.sub(r"\bco2\b", "CO₂", u, flags=re.I).replace("CO2", "CO₂")
    u = re.sub(r"^1\s+", "", u).strip()
    if re.match(r"^kg\s*CO₂e\s*/", u, re.I) or re.match(r"^kgCO₂e/", u, re.I):
        parts = u.split("/", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return u.strip("/ ").strip()


def _fmt_js2_gwp_list(cat: pd.Series) -> str:
    """Single list-cell GWP line: value + kgCO₂e per declared functional unit."""
    pt = _js2_product_type_lower(cat, catalog=True)

    if "in situ" in pt:
        n = _gwp_list_num(fn324_get_val(cat, "G__GWP_A1A3_m3"))
        return f"{n} kgCO₂e/m³" if n else ""

    if "building board" in pt or "tile" in pt:
        gm2 = fn324_get_val(cat, "G__GWP_A1A3_m2")
        if gm2 != "-":
            n = _gwp_list_num(gm2)
            if n:
                return f"{n} kgCO₂e/m²"
        gv = fn324_get_val(cat, "G__GWP_A1A3")
        fu = _gwp_list_fu_suffix(fn324_get_val(cat, "G__GWP_FU"))
        n = _gwp_list_num(gv)
        if n and fu:
            return f"{n} kgCO₂e/{fu}"
        return f"{n} kgCO₂e" if n else ""

    if "insulation" in pt:
        gv = fn324_get_val(cat, "G__GWP_A1A3")
        fu = _gwp_list_fu_suffix(fn324_get_val(cat, "G__GWP_FU"))
        n = _gwp_list_num(gv)
        if n and fu:
            return f"{n} kgCO₂e/{fu}"
        gm3 = fn324_get_val(cat, "G__GWP_A1A3_m3")
        if gm3 != "-":
            n3 = _gwp_list_num(gm3)
            if n3:
                return f"{n3} kgCO₂e/m³"
        return ""

    gv = fn324_get_val(cat, "G__GWP_A1A3")
    fu = _gwp_list_fu_suffix(fn324_get_val(cat, "G__GWP_FU"))
    n = _gwp_list_num(gv)
    if n and fu:
        return f"{n} kgCO₂e/{fu}"
    return f"{n} kgCO₂e" if n else ""


def _density_val_empty_js2(v) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return True
    s = str(v).strip()
    if not s or s == "-":
        return True
    # pandas StringDtype / object NA often arrives as the literal "<NA>"
    return s.lower() in ("<na>", "nan", "none", "n/a", "na", "n/r", "nr")


def _fmt_js2_density_vol(v) -> str:
    """Volumetric density for Tech. Details — always from ``P__Mass_kgm3``."""
    if _density_val_empty_js2(v):
        return ""
    s = str(v).strip()
    if "kg/m³" in s or "kg/m3" in s.lower():
        return s.replace("kg/m3", "kg/m³")
    try:
        return f"{float(s.replace(',', '.')):.0f} kg/m³"
    except (TypeError, ValueError):
        return s


def _fmt_js2_density_area(v) -> str:
    """Surface density for Tech. Details — always from ``P__Mass_kgm2``."""
    if _density_val_empty_js2(v):
        return ""
    s = str(v).strip()
    if "kg/m²" in s or "kg/m2" in s.lower():
        return s.replace("kg/m2", "kg/m²")
    try:
        return f"{float(s.replace(',', '.')):.0f} kg/m²"
    except (TypeError, ValueError):
        return s


def _js2_parse_leading_float(raw) -> float | None:
    if _density_val_empty_js2(raw):
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(raw).strip())
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _js2_fill_derived_densities(df_slim: "pd.DataFrame") -> None:
    """Fill missing vol ↔ surface density from ρ = m_A / d (d in metres).

    Tech. Details shows both bases; when only one is on file, derive the other
    from thickness rather than leaving N/A (e.g. 10 kg/m² at 20 mm → 500 kg/m³).
    """
    if "thickness" not in df_slim.columns:
        return
    if "densityVol" not in df_slim.columns and "densityKgm2" not in df_slim.columns:
        return
    if "densityVol" not in df_slim.columns:
        df_slim["densityVol"] = ""
    if "densityKgm2" not in df_slim.columns:
        df_slim["densityKgm2"] = ""
    thick_i = df_slim.columns.get_loc("thickness")
    vol_i = df_slim.columns.get_loc("densityVol")
    area_i = df_slim.columns.get_loc("densityKgm2")
    for i in range(len(df_slim)):
        thick = _js2_parse_leading_float(df_slim.iat[i, thick_i])
        if thick is None or thick <= 0:
            continue
        vol_n = _js2_parse_leading_float(df_slim.iat[i, vol_i])
        area_n = _js2_parse_leading_float(df_slim.iat[i, area_i])
        if vol_n is None and area_n is not None:
            df_slim.iat[i, vol_i] = f"{round(area_n * 1000.0 / thick):.0f} kg/m³"
        elif area_n is None and vol_n is not None:
            df_slim.iat[i, area_i] = f"{round(vol_n * (thick / 1000.0)):.0f} kg/m²"


def _fmt_js2_density_list(slim: pd.Series, cat: pd.Series) -> str:
    """kg/m² or kg/m³ only — boards, tiles, insulation; empty for other types."""
    pt = _js2_product_type_lower(slim)
    if not _js2_density_relevant_product_type(pt):
        return ""
    use_m2 = "building board" in pt or "tile" in pt
    v3 = slim.get("density")
    if use_m2:
        v2 = cat.get("P__Mass_kgm2") if "P__Mass_kgm2" in cat.index else None
        if _density_val_empty_js2(v3) and not _density_val_empty_js2(v2):
            try:
                return f"{float(str(v2).replace(',', '.')):.0f} kg/m²"
            except (TypeError, ValueError):
                return str(v2).strip()
    if _density_val_empty_js2(v3):
        return ""
    s = str(v3).strip()
    if "kg/m²" in s or "kg/m2" in s.lower():
        return s.replace("kg/m2", "kg/m²")
    if "kg/m³" in s or "kg/m3" in s.lower():
        return s.replace("kg/m3", "kg/m³")
    try:
        return f"{float(s.replace(',', '.')):.0f} kg/m³"
    except (TypeError, ValueError):
        return s


def _voc_is_category_fragment(s: str) -> bool:
    """True for ``Cat. …`` product-category segments in VOC display text."""
    return bool(re.match(r"(?i)^Cat\.\s*\S", str(s or "").strip()))


def _js2_list_voc_fields(row: pd.Series) -> dict[str, str]:
    """VOC text, composite cert badge (data URI), and doc URL for JS2 list rows."""
    texts, urls = _voc_detail_texts_and_urls(row)
    # Detail panel is narrow: drop ``Cat. …`` (product category) and keep lab + cert.
    parts = [
        str(t).strip()
        for t in texts
        if str(t).strip() and not _voc_is_category_fragment(str(t))
    ]

    def _already_in_parts(fragment: str) -> bool:
        """True when ``fragment`` is already covered by a joined VOC text part."""
        needle = _voc_cert_normalize_label(fragment).casefold()
        if not needle:
            return True
        for p in parts:
            hay = _voc_cert_normalize_label(p).casefold()
            if needle == hay or needle in hay:
                return True
        return False

    cert = fn324_get_val_first(row, "VO__VOC_Cert", "V__VOC_Cert")
    cert_uri = ""
    if cert != "-":
        badge = fn346_voc_cert_composite_data_uri(cert)
        if badge:
            cert_uri = badge
            # Badge replaces M1/IAG phrases; keep any leftover cert text once.
            rem = _voc_cert_remainder_plain(cert)
            if rem and not _voc_is_category_fragment(rem) and not _already_in_parts(rem):
                parts.append(rem)
        # No badge: ``parts`` already includes VO__VOC_Cert via
        # ``_voc_detail_texts_and_urls`` — do not append it again (was
        # producing ``Greengaurd Gold · Greengaurd Gold``).
    voc_url = ""
    for col in ("U__VOC_URL", "VO__VOC_URL", "V__VOC_URL"):
        u = fn324_get_val(row, col)
        if u != "-":
            voc_url = u
            break
    if not voc_url and urls:
        voc_url = str(urls[0]).strip()
    return {
        "vocText": " · ".join(parts) if parts else "",
        "vocCertBadge": cert_uri,
        "vocUrl": voc_url,
        # Lookup key into window.__VOC_ALIGN__ (label or alias, lowercased):
        # the card resolves the LEED / WELL / CAM pills from it, so the notes
        # travel once per page instead of once per row.
        "vocCertKey": "" if cert == "-" else _voc_cert_normalize_label(cert).lower(),
    }


_JS2_DETAIL_FIELD_TO_FV: dict[str, str] = {
    "thickness": "Thickness",
    "density": "Density",
    "conductivity": "Conductivity (ʎ)",
    "thermalConductivity": "Conductivity (ʎ)",
    "fireRating": "Fire rating",
    "recyclingRate": "Recycling Rate",
    "serviceLife": "Service Life",
}


def _js2_field_visibility_for_product(product_type: str) -> dict[str, bool]:
    """Per-product detail-row visibility (matches Streamlit catalogue / aux_10__ui_config.json)."""
    pt = (
        fn315_normalize_product_type(product_type)
        if str(product_type or "").strip()
        else "default"
    )
    fv = fn317_get_field_visibility(pt, "Compact")
    return {
        js_key: bool(fv.get(fv_key, True))
        for js_key, fv_key in _JS2_DETAIL_FIELD_TO_FV.items()
    }


def _js2_raw_fields_cell(val) -> str:
    """One catalogue cell as the plain string JS2 grid size XL displays."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (list, dict)):
        return str(val)
    s = str(val).strip()
    return "" if s in ("nan", "None") else s


def _js2_raw_fields_from_row(row: "pd.Series") -> dict[str, str]:
    """All catalogue row columns as plain strings for JS2 grid size XL (no formatting)."""
    return {str(col): _js2_raw_fields_cell(row.get(col)) for col in row.index}


def _js2_raw_fields_bulk(df: "pd.DataFrame") -> list[dict[str, str]]:
    """:func:`_js2_raw_fields_from_row` for a whole frame, without pandas indexing.

    Per row this read all 135 columns through ``row.get(col)``; across the
    catalogue that is ~305,000 Series lookups, and it was the largest remaining
    cost in the payload build. Going through the underlying object array does
    the same work as plain Python attribute access on lists.
    """
    cols = [str(c) for c in df.columns]
    return [
        dict(zip(cols, [_js2_raw_fields_cell(v) for v in row_vals]))
        for row_vals in df.to_numpy(dtype=object).tolist()
    ]


def _js2_build_field_vis_map(
    df_slim: "pd.DataFrame",
    pt_series: "pd.Series",
) -> dict[int, dict[str, bool]]:
    """``{product id: {js field: visible}}``.

    Visibility depends only on the product *type*, of which a catalogue view
    holds a couple of dozen at most — so resolve each type once and share the
    result. This used to call fn317_get_field_visibility once per row, and reach
    the row's id through ``df_slim.iloc[i]["id"]``, which materialises a whole
    Series per row just to read one integer.
    """
    ids = df_slim["id"].astype(int).tolist()
    types = pt_series.astype(str).tolist()
    per_type: dict[str, dict[str, bool]] = {}
    out: dict[int, dict[str, bool]] = {}
    for i, pid in enumerate(ids):
        pt = types[i] if i < len(types) else ""
        vis = per_type.get(pt)
        if vis is None:
            vis = _js2_field_visibility_for_product(pt)
            per_type[pt] = vis
        out[pid] = vis
    return out


def _js2_list_fields_visibility(df_catalog: pd.DataFrame) -> dict[str, bool]:
    """Optional JS2 list columns (conductivity, density) from product types in view."""
    show_cond = False
    show_density = False
    if "D__ProductType_ENG" in df_catalog.columns:
        pt = df_catalog["D__ProductType_ENG"].astype(str).str.lower()
        rel = pt.str.contains("insulation", na=False) | pt.str.contains("building board", na=False)
        if bool(rel.any()):
            show_cond = True
            for k, v in st.session_state.items():
                if not str(k).startswith("display_params_"):
                    continue
                if not str(k).endswith(DISPLAY_PARAMS_SESSION_VER):
                    continue
                if isinstance(v, dict) and v.get("Conductivity (ʎ)") is False:
                    show_cond = False
                break
        show_density = bool(
            (
                pt.str.contains("insulation", na=False)
                | pt.str.contains("building board", na=False)
                | pt.str.contains("tile", na=False)
            ).any()
        )
    return {"conductivity": bool(show_cond), "density": bool(show_density)}


def _derive_epd_programme_label(reg_number: str) -> str:
    r = (reg_number or "").strip().upper()
    if not r or r in ("-", "NAN", "NONE"):
        return ""
    if "INIES" in r:
        return "INIES"
    if "EPDITALY" in r or "EPD-IT" in r:
        return "EPD Italy Hub"
    if "EPDNOR" in r or "EPD-NO" in r:
        return "EPD Norway"
    if r.startswith("DAP") or "-FR-" in r:
        return "DAP"
    if "IBU" in r or (r.startswith("EPD-") and "-DE-" in r):
        return "IBU"
    return ""


def _voc_detail_texts_and_urls(row: pd.Series) -> tuple[list[str], list[str]]:
    """VOC labels (no raw URLs in text) + link targets (dedicated URL columns first, then in-cell URLs)."""
    def _cell(col: str) -> str:
        if col not in row.index:
            return ""
        v = row.get(col, "")
        if v is None or pd.isna(v):
            return ""
        s = str(v).strip()
        return "" if s in ("", "-", "nan", "None") else s

    urls: list[str] = []
    seen: set[str] = set()
    for col in ("U__VOC_URL", "VO__VOC_URL", "V__VOC_URL"):
        u = _cell(col)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # The line shows the certification only: VO__Product_Category is hidden
    # app-wide as uninformative, and VO__VOC_Body (the testing / certifying
    # body) is kept off the card by aux_10__ui_config.json — the card says what
    # the claim is, the detail panel says who issued it. Neither column
    # carries a document URL.
    v_cert = _row_cell_first(row, "VO__VOC_Cert", "V__VOC_Cert")
    v_dop = _row_cell_first(row, "VV__DOP", "V__DOP")
    scan: list[str] = []
    if v_cert:
        scan.append(v_cert)
    if not scan and v_dop:
        scan.append(v_dop)

    texts, inline_urls = _voc_detail_scan_strings(*scan)
    for u in inline_urls:
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return texts, urls


def fn335_render_detail_panel():
    """Render persistent right-hand product detail panel for the catalogue page."""
    selected = st.session_state.get("SELECTED_PRODUCT")
    with st.container(border=True, height=600):
        st.markdown("#### Product details")
        if not selected:
            st.info("Select a product to view details.")
            return
        row          = pd.Series(selected)
        product_name = fn324_get_val(row, "A__ProductName")
        manufacturer = fn324_get_val(row, "A__Manufacturer")
        product_url  = fn324_get_val(row, "U__ProductInfo_URL")
        epd_url      = fn324_get_val(row, "E__EPD_URL")
        tech_url     = fn324_get_val(row, "U__TechDetails_URL")
        img_url      = fn324_get_val(row, "U__Img_URL")
        _eid         = fn324_get_val(row, "0__EETRA_ID")
        image        = _lazy_fetch_image(
            img_url if img_url != "-" else None,
            eetra_id=None if _eid in ("", "-") else _eid,
            product_name=None if product_name in ("", "-") else product_name,
        )
        if image is not None:
            st.image(image, width="stretch")
        if product_url != "-":
            st.markdown(f"**[{product_name}]({product_url})**")
        else:
            st.markdown(f"**{product_name}**")
        if manufacturer != "-":
            st.caption(manufacturer)
        st.markdown("#### Environmental impact")
        gwp_rows = []
        for label, col, unit in [
            ("GWP A1-A3",           "G__GWP_A1A3",       None),
            ("GWP A1-A3 / m²",      "G__GWP_A1A3_m2",    "kgCO₂e/m²"),
            ("GWP A1-A3 / m³",      "G__GWP_A1A3_m3",    "kgCO₂e/m³"),
            ("GWP A1-A3 / m² R=1",  "G__GWP_A1A3_m2R1",  "kgCO₂e/m² R=1"),
        ]:
            val = fn324_get_val(row, col)
            if val != "-":
                gwp_rows.append(f"- **{label}:** {val}{'' if unit is None else f' {unit}'}")
        if gwp_rows:
            st.markdown("\n".join(gwp_rows))
        else:
            st.caption("No GWP data available.")
        st.markdown("#### Technical")
        thickness     = fn325_get_thickness_val(row)
        density       = fn324_get_val(row, "P__Mass_kgm3")
        density_unit  = "kg/m³"
        density_label = "Vol. Density"
        _pt_eng       = str(row.get("D__ProductType_ENG", "") or "")
        if "building boards" in _pt_eng.lower() and density == "-":
            density = fn324_get_val(row, "P__Mass_kgm2")
            density_unit = "kg/m²"
            density_label = "Sup. Density"
        conductivity  = fn324_get_val(row, "P__L_WmK")
        if conductivity == "-" and "E__L_WmK" in row.index:
            conductivity = fn324_get_val(row, "E__L_WmK")
        rec_raw = fn324_get_val(row, "R__Rec_Reco_ByProd_%")
        if rec_raw == "-":
            rec_raw = fn324_get_val(row, "R__Reco_Tot_%")
        recycling  = fn326_format_recycling_rate(rec_raw)
        _rec_url = fn324_get_val(row, "R__Rec_Reco_ByProd_URL")
        if recycling != "-":
            if _rec_url and str(_rec_url).strip() not in ("", "-"):
                _u = _html.escape(str(_rec_url).strip(), quote=True)
                _rec_line = (
                    f'- **Recycled content:** {recycling}% '
                    f'<a href="{_u}" target="_blank" rel="noopener noreferrer">🔗</a>'
                )
            else:
                _rec_line = f"- **Recycled content:** {recycling}%"
        else:
            _rec_line = None
        tech_lines = [
            f"- **Thickness:** {thickness}"            if thickness != "-" else None,
            f"- **{density_label}:** {density} {density_unit}" if density != "-" else None,
            f"- **Conductivity:** {conductivity} W/mK" if conductivity != "-" else None,
            _rec_line,
            f"- **Fire rating:** {fn324_get_val(row, 'P__FireRating')}"    if fn324_get_val(row, "P__FireRating") != "-" else None,
            f"- **Service life:** {fn324_get_val(row, 'P__ServiceLife')}"  if fn324_get_val(row, "P__ServiceLife") != "-" else None,
        ]
        tech_lines = [x for x in tech_lines if x]
        if tech_lines:
            _tech_html = any("<a " in t for t in tech_lines)
            st.markdown("\n".join(tech_lines), unsafe_allow_html=_tech_html)
        else:
            st.caption("No technical data available.")
        content     = fn324_get_val(row, "D__Content")
        comments    = fn324_get_val(row, "S__Comments")
        tech_details = fn324_get_val(row, "D__TechDetails")
        manu_plant  = fn324_get_val(row, "E__ManuPlant")
        manu_country = fn324_get_val(row, "E__ManuCountry")
        epd_declared = fn324_get_val(row, "E__EPD_DecNumber")
        epd_number   = fn324_get_val(row, "E__EPD_RegNumber")

        _voc_texts, _voc_urls = _voc_detail_texts_and_urls(row)
        _voc_show = bool(_voc_texts or _voc_urls)

        meta_before_voc: list[str] = []
        if manu_plant != "-" or manu_country != "-":
            place = " / ".join([x for x in [manu_plant, manu_country] if x != "-"])
            meta_before_voc.append(f"- **Manufacturing plant:** {place}")
        if comments != "-":
            meta_before_voc.append(f"- **Comments:** {comments}")
        if tech_details != "-":
            meta_before_voc.append(f"- **Technical details:** {tech_details}")

        meta_after_voc: list[str] = []
        from .lib_data import fn142a_is_usable_document_url

        meta_after_voc.append(
            f"- **EPD Dec. n.:** {epd_declared if epd_declared != '-' else '—'}"
        )
        if fn142a_is_usable_document_url(epd_url) and epd_number != "-":
            _eu = str(epd_url).strip().replace(" ", "%20")
            meta_after_voc.append(f"- **EPD Reg. n.:** [{epd_number}]({_eu})")
        elif fn142a_is_usable_document_url(epd_url):
            _eu = str(epd_url).strip().replace(" ", "%20")
            meta_after_voc.append(
                f"- **EPD Reg. n.:** [Open document ↗]({_eu})"
            )
        elif epd_number != "-":
            meta_after_voc.append(f"- **EPD Reg. n.:** {epd_number}")
        else:
            meta_after_voc.append("- **EPD Reg. n.:** —")
        if tech_url != "-":
            _tu = str(tech_url).strip().replace(" ", "%20")
            meta_after_voc.append(
                f"- **Technical sheet (public):** [Open document ↗]({_tu})"
            )

        if content != "-":
            st.markdown("#### Composition")
            st.write(content)

        _has_add = bool(meta_before_voc or meta_after_voc or _voc_show)
        if _has_add:
            st.markdown("#### Additional information")
        if meta_before_voc:
            st.markdown("\n".join(meta_before_voc))
        if _voc_show:
            st.markdown(_detail_panel_green_separator_html(), unsafe_allow_html=True)
            st.markdown("#### VOC")
            st.markdown(_detail_panel_green_separator_html(), unsafe_allow_html=True)
            _voc_body = " - ".join(_voc_catalog_fragment_to_html(x) for x in _voc_texts) if _voc_texts else ""
            _href = ""
            if _voc_urls:
                from .lib_data import prefer_local_document_href

                _raw_h = str(_voc_urls[0]).strip().replace(" ", "%20")
                _href = prefer_local_document_href(_raw_h, _eid, product_name, "voc") or _raw_h
            _href_esc = _html.escape(_href, quote=True) if _href else ""
            if _voc_body:
                if _href_esc:
                    _voc_html = (
                        f'<p style="margin:0;">{_voc_body} '
                        f'<a href="{_href_esc}" target="_blank" rel="noopener noreferrer" '
                        f'title="VOC documentation">🔗</a></p>'
                    )
                else:
                    _voc_html = f'<p style="margin:0;">{_voc_body}</p>'
            elif _href_esc:
                _voc_html = (
                    f'<p style="margin:0;"><strong>VOC</strong> '
                    f'<a href="{_href_esc}" target="_blank" rel="noopener noreferrer" '
                    f'title="VOC documentation">🔗</a></p>'
                )
            else:
                _voc_html = ""
            if _voc_html:
                st.markdown(_voc_html, unsafe_allow_html=True)
        if meta_after_voc:
            st.markdown("\n".join(meta_after_voc))
        link_cols = st.columns(2)
        with link_cols[0]:
            from .lib_data import fn142a_is_usable_document_url

            if fn142a_is_usable_document_url(epd_url):
                _catalogue_detail_pdf_actions(
                    "Open EPD ↗",
                    "EPD (preview)",
                    epd_url,
                    _eid,
                    product_name,
                    "epd",
                    row=row,
                )
        with link_cols[1]:
            if tech_url != "-":
                _catalogue_detail_pdf_actions(
                    "Open technical sheet ↗",
                    "Technical sheet (preview)",
                    tech_url,
                    _eid,
                    product_name,
                    "tech",
                    row=row,
                )


def fn336_js2_extended_back_panel_html(
    catalog_row: "pd.Series",
    product_type: str,
) -> str:
    """Build the Extended back-panel HTML per product for the JS2 flip-card.

    Uses the same field order and visibility config as the Streamlit Extended panel
    (fn317_get_field_visibility). Output is stored as ``extendedPanelHtml`` in the
    per-product JSON so the JS card back face can render it directly.
    """
    import html as _html

    def _v(col: str) -> str:
        raw = catalog_row.get(col)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return ""
        s = str(raw).strip()
        return "" if s in ("-", "nan", "None") else s

    fv = fn317_get_field_visibility(product_type, "Extended")

    parts: list[str] = []

    def _row(label: str, value: str) -> str:
        if not value:
            return ""
        return (
            f'<div class="ext-field-row">'
            f'<span class="ext-field-label">{_html.escape(label)}</span>'
            f'<span class="ext-field-value">{value}</span>'
            f'</div>'
        )

    def _box(label: str, value: str) -> str:
        if not value:
            return ""
        return (
            f'<div class="ext-field-content">'
            f'<div class="ext-field-label">{_html.escape(label)}</div>'
            f'<div class="ext-field-box">{_html.escape(value)}</div>'
            f'</div>'
        )

    # Recycling Rate
    if fv.get("Recycling Rate", False):
        rr = _v("R__Rec_Reco_ByProd_%") or _v("R__Reco_Tot_%")
        if rr:
            try:
                rr_fmt = f"{float(rr):.1f}%"
            except Exception:
                rr_fmt = rr if rr.endswith("%") else rr
            rr_url = _v("R__Rec_Reco_ByProd_URL")
            link = (
                f' <a href="{_html.escape(rr_url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">🔗</a>'
            ) if rr_url else ""
            parts.append(_row("Recycled content", _html.escape(rr_fmt) + link))

    # EPD (declared + registration lines)
    if fv.get("EPD Num.", False):
        ed = _v("E__EPD_DecNumber")
        er = _v("E__EPD_RegNumber")
        eu = _v("E__EPD_URL")
        dec_disp = _html.escape(ed) if ed else "—"
        from .lib_data import fn142a_is_usable_document_url

        if fn142a_is_usable_document_url(eu):
            _inner = _html.escape(er) if er else "Open EPD ↗"
            reg_inner = (
                f'<a href="{_html.escape(eu, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{_inner}</a>'
            )
        elif er:
            reg_inner = _html.escape(er)
        else:
            reg_inner = "—"
        parts.append(
            f'<div class="ext-field-row">'
            f'<span class="ext-field-label">EPD Dec. n.</span>'
            f'<span class="ext-field-value">{dec_disp}</span>'
            f'</div>'
            f'<div class="ext-field-row">'
            f'<span class="ext-field-label">EPD Reg. n.</span>'
            f'<span class="ext-field-value">{reg_inner}</span>'
            f'</div>'
        )

    # Manufacturing Plant
    if fv.get("Manufacturing Plant", False):
        plant = _v("E__ManuPlant")
        country = _v("E__ManuCountry")
        bits = [x for x in [plant, country] if x]
        if bits:
            parts.append(_row("Plant", _html.escape(" · ".join(bits))))

    # Thickness
    if fv.get("Thickness", False):
        thick = _v("P__Thick_mm")
        if thick:
            try:
                thick_fmt = f"{float(thick.replace(',', '.')):.0f} mm"
            except Exception:
                thick_fmt = thick
            parts.append(_row("Thickness", _html.escape(thick_fmt)))

    # Vol. Density
    if fv.get("Density", False):
        dens = _v("P__Mass_kgm3")
        if dens:
            parts.append(_row("Vol. Density", _html.escape(dens) + " kg/m³"))

    # Fire rating
    if fv.get("Fire rating", False):
        fire = _v("P__FireRating")
        if fire:
            parts.append(_row("Fire rating", _html.escape(fire)))

    # Technical Details
    if fv.get("Technical Details", False):
        td_url = _v("U__TechDetails_URL")
        td = _v("D__TechDetails")
        if td_url:
            parts.append(
                f'<div class="ext-field-row">'
                f'<span class="ext-field-label">Technical Details</span>'
                f'<span class="ext-field-value">'
                f'<a href="{_html.escape(td_url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">Link</a>'
                f'</span></div>'
            )
        elif td:
            parts.append(_row("Technical Details", _html.escape(td)))

    # VOC
    if fv.get("VOC", False):
        try:
            _voc_texts, _voc_urls = _voc_detail_texts_and_urls(catalog_row)
        except Exception:
            _voc_texts, _voc_urls = [], []
        _voc_parts = [str(t).strip() for t in _voc_texts if str(t).strip()]
        _voc_text = " · ".join(_voc_parts) if _voc_parts else ""
        _voc_url = str(_voc_urls[0]).strip() if _voc_urls else ""
        if _voc_text or _voc_url:
            _link = (
                f' <a href="{_html.escape(_voc_url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">🔗</a>'
            ) if _voc_url else ""
            parts.append(_row("VOC", (_html.escape(_voc_text) if _voc_text else "") + _link))

    # Comments (content box — label on top, scrollable value)
    if fv.get("Comments", False):
        cmt = _v("S__Comments")
        if cmt:
            parts.append(_box("Comments", cmt))

    # Content (content box)
    if fv.get("Content", False):
        content = _v("D__Content")
        if content:
            parts.append(_box("Content", content))

    # Service Life
    if fv.get("Service Life", False):
        sl = _v("P__ServiceLife")
        if sl:
            parts.append(_row("Service Life", _html.escape(sl)))

    # EN197-1 (Binder only)
    if fv.get("EN197-1", False) and product_type == "Binder":
        en1 = _v("D__EN197-1")
        if en1:
            parts.append(_row("EN197-1", _html.escape(en1)))

    if not parts:
        return ""
    return '<div class="ext-back-panel">' + "".join(parts) + "</div>"


def _fn336_payload_config_signature() -> str:
    """Everything outside ``df_catalog`` that the catalogue payload depends on.

    The build reads field-visibility config and the per-column display params out
    of session state, and tags out of tags.parquet — none of which the frame
    itself carries. Folding them into one hash gives
    :func:`_fn336_cached_catalogue_payload` a key that changes whenever the
    payload would, so a config edit or a tag change is picked up on the next
    rerun rather than serving a stale catalogue until the process restarts.
    """
    parts: list[str] = []
    try:
        parts.append(
            json.dumps(st.session_state.get("FIELD_VISIBILITY", {}), sort_keys=True, default=str)
        )
    except Exception:
        parts.append("fv?")
    try:
        parts.append(
            json.dumps(
                {
                    str(k): v
                    for k, v in st.session_state.items()
                    if str(k).startswith("display_params_")
                },
                sort_keys=True,
                default=str,
            )
        )
    except Exception:
        parts.append("dp?")
    try:
        from . import lib_tags as _lt

        parts.append(str(_lt._mtime_or_zero(_lt._tags_file())))
    except Exception:
        parts.append("tags?")
    try:
        # Field-map edits (new catalogue columns) must bust the payload cache.
        parts.append("|".join(f"{s}>{t}" for s, t in JS_CATALOGUE_FIELD_MAP.items()))
    except Exception:
        parts.append("fmap?")
    try:
        _js2_fields_path = Path(__file__).resolve().parent.parent / "aux_07__js2_card_fields.json"
        parts.append(str(_js2_fields_path.stat().st_mtime_ns))
    except Exception:
        parts.append("js2f?")
    try:
        # Re-running 04_tools/20_fetch_product_ranges.py must bust the payload
        # cache too, or the gallery keeps the previous range.
        _ranges_path = Path(__file__).resolve().parent.parent / "aux_09__product_ranges.json"
        parts.append(str(_ranges_path.stat().st_mtime_ns))
    except Exception:
        parts.append("rng?")
    try:
        # The payload carries the card labels in the active language (fn707),
        # so the language belongs in the cache key — without it, switching
        # ITA/ENG leaves the cards on the previously cached labels.
        from libs.lib_i18n import fn702_current_language, _TRANSLATIONS_PATH
        parts.append(fn702_current_language())
        parts.append(str(_TRANSLATIONS_PATH.stat().st_mtime_ns))
    except Exception:
        parts.append("lang?")
    # Bust cached payloads that still embed /app/static/img_cache/… URLs
    # (unservable on Community Cloud — see static_img_payload_url).
    parts.append("img:datauri-v1")
    return hashlib.md5("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


def _fn_range_img_for_payload(cached_path: str, remote_url: str = "") -> str:
    """Image URL for range index / collection cards in the catalogue iframe.

    Prefer a data URI from ``static/img_cache`` when the file exists. Otherwise
    use the manufacturer HTTPS URL (``img_src`` / member ``img``). Never emit
    ``/app/static/img_cache/…`` — on Community Cloud those paths return SPA HTML.
    """
    cached = str(cached_path or "").strip()
    remote = str(remote_url or "").strip()
    if cached.startswith(("http://", "https://", "data:")):
        return cached
    if cached.startswith("/app/static/img_cache/"):
        try:
            from .lib_data import static_img_payload_url
            data_uri = static_img_payload_url(cached)
            if data_uri:
                return data_uri
        except Exception:
            pass
        return remote if remote.startswith(("http://", "https://")) else ""
    if remote.startswith(("http://", "https://", "data:")):
        return remote
    return cached


@st.cache_data(show_spinner=False, max_entries=1)
def _fn_product_range_index() -> dict:
    """``aux_09__product_ranges.json`` → flat {lower-cased name: member} index.

    One library row is one EPD; the commercial range behind it (48 SapienStone
    slabs, a colour run of an Iris Ceramica collection) lives in the aux file
    rather than as more rows, and the row points at it through
    ``D__IncludedProducts``. Missing or unreadable file → {}, and the
    included-products popup silently stays the plain text list it was.

    Each entry's ``img`` is rewritten for the iframe (data URI or ``img_src``
    HTTPS) so clay-tile / collection galleries work on Community Cloud.
    """
    path = Path(__file__).resolve().parent.parent / "aux_09__product_ranges.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    index = data.get("index")
    if not isinstance(index, dict):
        return {}
    out: dict = {}
    for key, meta in index.items():
        if not isinstance(meta, dict):
            out[key] = meta
            continue
        entry = dict(meta)
        entry["img"] = _fn_range_img_for_payload(
            entry.get("img") or entry.get("img_cached") or "",
            entry.get("img_src") or "",
        )
        out[key] = entry
    return out


@st.cache_data(show_spinner=False, max_entries=1)
def _fn_product_range_collections() -> dict:
    """``aux_09__product_ranges.json`` → {range id: collection summary}.

    The sibling of ``_fn_product_range_index``, one level up: that one keys every
    individual colour, this one keys the *collection* it belongs to. The
    catalogue's Expanded entry mode needs exactly this — one entry per
    "Collezione" (Emilceramica Essenza Frammenti, Provenza Unique Concrete) —
    and it needs it without the members, which are 899 objects and already
    travel in the index.

    Deliberately summary-only: the label, where it came from, what the colours
    have in common, and one representative thumbnail (the first member that has
    a cached one, else its remote ``img``). Missing or unreadable file → {}, and
    the toggle falls back to Condensed with nothing to expand.
    """
    path = Path(__file__).resolve().parent.parent / "aux_09__product_ranges.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    ranges = data.get("ranges")
    if not isinstance(ranges, dict):
        return {}
    out: dict[str, dict] = {}
    for rid, rng in ranges.items():
        if not isinstance(rng, dict):
            continue
        members = rng.get("members") or []
        thumb = ""
        for m in members:
            if not isinstance(m, dict):
                continue
            thumb = _fn_range_img_for_payload(
                m.get("img_cached") or "",
                m.get("img") or "",
            )
            if thumb:
                break
        out[str(rid)] = {
            "label": rng.get("label") or str(rid),
            "brand": rng.get("brand") or "",
            "manufacturer": rng.get("manufacturer") or "",
            "source": rng.get("source") or "",
            "note": rng.get("note") or "",
            "img": thumb,
            "n": len(members),
            "thickness_mm": rng.get("thickness_mm") or [],
            "sizes": rng.get("sizes") or [],
            "finishes": rng.get("finishes") or [],
        }
    return out


@st.cache_data(show_spinner="🔄 Building catalogue…", max_entries=4)
def _fn336_cached_catalogue_payload(
    df_catalog: "pd.DataFrame",
    is_js2: bool,
    config_signature: str,
) -> "dict[str, str] | None":
    """Serialise a catalogue view: the whole payload, cached on the view.

    This is the expensive half of fn336 — image resolution, the per-row field
    formatting, the JSON — and it used to run on *every* rerun of the Catalogue
    page: a search keystroke, a tag toggle, opening the document rail. Only
    ``df_catalog`` and ``_config_signature`` change what it produces, so caching
    on those turns everything except an actual filter change into a lookup.

    Progress is the decorator's own spinner, not a progress bar. A first version
    took a ``_progress`` handle and drove a bar through the build, which raises
    ``CacheReplayClosureError`` the moment the cache is *hit*: @st.cache_data
    records the Streamlit element calls made inside the function so it can replay
    them on a hit, and that bar belongs to a placeholder created by the caller —
    a block that no longer exists at replay time. Anything drawn from in here has
    to be created in here; a spinner the decorator owns sidesteps that entirely.

    ``is_js2`` and ``config_signature`` must NOT be underscore-prefixed, or
    Streamlit would silently exclude them from the cache key and the cache would
    answer every config change with a stale payload.

    ``max_entries=4`` because each entry holds a ~11 MB JSON string: enough to
    keep a couple of recent filter states warm without pinning much memory.
    """
    rename_map: dict[str, str] = {}
    extra_cols: list[tuple[str, str]] = []
    seen_sources: set[str] = set()
    for src, tgt in JS_CATALOGUE_FIELD_MAP.items():
        if src not in df_catalog.columns:
            continue
        if src in seen_sources:
            extra_cols.append((src, tgt))
        else:
            rename_map[src] = tgt
            seen_sources.add(src)
    if not rename_map:
        # Reported by the caller, not here: st.* calls inside a cached function
        # render on the miss and then vanish on every hit.
        return None
    df_slim = df_catalog[list(rename_map.keys())].rename(columns=rename_map).copy()
    if "gwp" in df_slim.columns:
        df_slim["a1a3"] = df_slim["gwp"]
    for src, tgt in extra_cols:
        mapped_src = rename_map.get(src)
        if mapped_src and mapped_src in df_slim.columns:
            df_slim[tgt] = df_slim[mapped_src]
    for field in JS_CATALOGUE_NUMERIC_FIELDS:
        if field in df_slim.columns:
            df_slim[field] = pd.to_numeric(df_slim[field], errors="coerce").fillna(0.0)
    df_slim = df_slim.reset_index(drop=True)
    df_slim.insert(0, "id", df_slim.index + 1)

    if is_js2:
        _attach_static_doc_urls(df_slim, df_catalog)


    def _norm_img(u):
        if u is None or (isinstance(u, float) and pd.isna(u)):
            return ""
        try:
            if pd.isna(u):
                return ""
        except (TypeError, ValueError):
            pass
        s = str(u).strip()
        # pandas StringDtype NA stringifies to "<NA>"; if it reaches an <img src>
        # Streamlit's static server tries to open that path and crashes on Windows
        # (WinError 123 — `<`/`>` illegal in filenames).
        return "" if (not s or s in ("-", "nan", "None", "NaN", "<NA>", "NA")) else s

    def _norm_fu(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        s = str(x).strip()
        return "" if s == "-" else s

    def _norm_url(x):
        from .lib_data import fn142a_is_usable_document_url

        if not fn142a_is_usable_document_url(x):
            return ""
        return str(x).strip()

    def _fmt_thick(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        if not s or s == "-":
            return ""
        try:
            return f"{float(s.replace(',', '.')):.0f} mm"
        except Exception:
            return s

    def _density_val_empty(v) -> bool:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return True
        s = str(v).strip()
        return not s or s == "-"

    def _fmt_content(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        return "" if (not s or s == "-") else s

    def _fmt_rec_pct(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        if not s or s == "-":
            return ""
        if s.endswith("%"):
            return s
        try:
            return f"{float(s.replace(',', '.')):.1f}%"
        except Exception:
            return s

    if "imageUrl"   in df_slim.columns: df_slim["imageUrl"]   = df_slim["imageUrl"].apply(_norm_img)
    if "gwpUnit"    in df_slim.columns: df_slim["gwpUnit"]     = df_slim["gwpUnit"].apply(_norm_fu)
    if "epdUrl"     in df_slim.columns: df_slim["epdUrl"]      = df_slim["epdUrl"].apply(_norm_url)
    if "thickness"  in df_slim.columns: df_slim["thickness"]   = df_slim["thickness"].apply(_fmt_thick)
    # Keep both density bases for Tech. Details (list column still collapses
    # into ``density`` via ``_fmt_js2_density_list`` later).
    if "density" in df_slim.columns:
        df_slim["densityVol"] = df_slim["density"].apply(_fmt_js2_density_vol)
    if "densityKgm2" in df_slim.columns:
        df_slim["densityKgm2"] = df_slim["densityKgm2"].apply(_fmt_js2_density_area)
    _js2_fill_derived_densities(df_slim)
    if "content"    in df_slim.columns: df_slim["content"]     = df_slim["content"].apply(_fmt_content)
    if "productDescription" in df_slim.columns:
        df_slim["productDescription"] = df_slim["productDescription"].apply(_fmt_content)
    if "includedProducts" in df_slim.columns:
        def _fmt_included(v):
            s = _fmt_content(v)
            return "" if s.lower() in ("n/a", "na", "n/r", "nr") else s
        df_slim["includedProducts"] = df_slim["includedProducts"].apply(_fmt_included)
    if "comments" in df_slim.columns:
        df_slim["comments"] = df_slim["comments"].apply(_fmt_content)
    if "materialType" in df_slim.columns:
        df_slim["materialType"] = df_slim["materialType"].apply(_fmt_content)

    if "recyclingRate" in df_slim.columns:
        df_slim["recyclingRate"] = df_slim["recyclingRate"].apply(_fmt_rec_pct)
        if "R__Reco_Tot_%" in df_catalog.columns:
            tot = df_catalog["R__Reco_Tot_%"].reset_index(drop=True).apply(_fmt_rec_pct)
            rr_loc = df_slim.columns.get_loc("recyclingRate")
            for idx in range(len(df_slim)):
                cur = df_slim.iat[idx, rr_loc]
                if cur is None or (isinstance(cur, str) and not cur.strip()):
                    if idx < len(tot):
                        df_slim.iat[idx, rr_loc] = tot.iat[idx] or ""
    elif "R__Reco_Tot_%" in df_catalog.columns:
        df_slim["recyclingRate"] = df_catalog["R__Reco_Tot_%"].reset_index(drop=True).apply(_fmt_rec_pct)

    if "recyclingUrl" in df_slim.columns:
        df_slim["recyclingUrl"] = df_slim["recyclingUrl"].apply(_norm_url)
    for _url_col in ("dopUrl", "techDetailsUrl"):
        if _url_col in df_slim.columns:
            df_slim[_url_col] = df_slim[_url_col].apply(_norm_url)

    for field in ("certifications", "additions"):
        if field in df_slim.columns:
            def _to_list(v):
                if pd.isna(v) or v == "" or v == "-":
                    return []
                if isinstance(v, list):
                    return v
                return [s.strip() for s in str(v).split(",") if s.strip()]
            df_slim[field] = df_slim[field].apply(_to_list)

    def _row_cell_str(val) -> str:
        if val is None:
            return ""
        try:
            if pd.isna(val):
                return ""
        except (TypeError, ValueError):
            pass
        s = str(val).strip()
        return "" if s in ("-", "nan", "None", "NaN", "<NA>", "NA") else s

    # Pre-fetch images server-side → base64 data URIs so the JS iframe
    # doesn't need to make authenticated/CORS-restricted network requests.
    _pre_img_band_h = max(0, int(CATALOGUE_CARD_IMAGE_HEIGHT_PX)) if CATALOGUE_CARD_IMAGE_HEIGHT_PX else 0
    if "imageUrl" in df_slim.columns and _pre_img_band_h > 0:
        from io import BytesIO as _BytesIO
        from .lib_data import (
            catalogue_image_cache_is_valid,
            ensure_static_img_cache_from_path,
            image_path_to_data_uri,
            normalize_product_image_url,
            resolve_hash_local_image_path,
            resolve_local_image_path_from_column,
            resolve_local_product_image_path,
            save_static_img_cache,
            static_img_cache_url,
            static_img_payload_url,
        )

        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _as_completed
        from .lib_data import fn110_cached_fetch_image as _fn110
        # Use the unwrapped function in threads to avoid @st.cache_data context warnings.
        _fetch_image_raw = getattr(_fn110, "__wrapped__", _fn110)

        _img_n = len(df_slim)

        # Process-lifetime memo: image URL → the URL the payload should carry.
        #
        # Keyed on the image URL alone. It used to include the product
        # id and name, which meant the 552 distinct images behind these rows were
        # resolved and encoded 1,580 times — once per referencing row — and
        # appeared that many times in the payload. static/img_cache is itself
        # keyed on the image URL, so URL-only is the key that matches how the
        # images are actually stored, and it collapses those repeats to one entry
        # each. (The id/name are still used below, to resolve the by-product-name
        # file convention; they just don't partition the cache.)
        _uri_cache = globals().setdefault("_FN336_IMG_URI_CACHE", {})

        def _url_to_data_uri_row(row: dict) -> "tuple[str, str]":
            _u = _row_cell_str(row.get("imageUrl"))
            if not _u:
                return ("", "")
            _u_norm = normalize_product_image_url(_u)
            eid = _row_cell_str(row.get("eetraId"))
            name = _row_cell_str(row.get("name"))
            # Key on the raw URL, matching how static/img_cache names files:
            # _static_img_cache_key hashes the *first* fetch candidate, which is
            # the raw URL, while static_img_cache_url probes both raw and
            # normalised. Hashing _u_norm here instead would write under one name
            # and look up another, so every rerun would miss and re-encode.
            _ck = _u
            _hit = _uri_cache.get(_ck)
            if _hit is not None:
                return _hit
            # Resolution yields a (card, detail) pair. The card URL is what the
            # 1,600-card grid loads; the detail URL is the larger tier the
            # right-hand panel loads for one product at a time. detail falls back
            # to card wherever only one size exists (a tiny source, or the
            # base64/remote fallbacks below).
            out_u = ""
            out_d = ""

            def _take(tiers: dict) -> str:
                nonlocal out_d
                if not tiers:
                    return ""
                out_d = tiers.get("detail") or tiers.get("card") or ""
                return tiers.get("card") or out_d

            cached_static = static_img_cache_url(_u)
            if cached_static:
                out_u = cached_static
                out_d = static_img_cache_url(_u, "detail") or cached_static
            # Local sources are converted into static/img_cache rather than
            # base64-inlined: downscaled thumbnails on disk, short URLs in the
            # payload. image_path_to_data_uri stays as the fallback for an image
            # that can't be re-encoded (an unsupported format, a read-only static
            # dir) — better a heavy card than a missing one.
            if not out_u:
                lp_col = resolve_local_image_path_from_column(_row_cell_str(row.get("imgLocal")))
                if lp_col is not None:
                    out_u = _take(ensure_static_img_cache_from_path(_u, lp_col)) or (
                        image_path_to_data_uri(lp_col) or ""
                    )
            if not out_u:
                lp_hash = resolve_hash_local_image_path(_u_norm)
                if lp_hash is not None:
                    out_u = _take(ensure_static_img_cache_from_path(_u, lp_hash)) or (
                        image_path_to_data_uri(lp_hash) or ""
                    )
            if not out_u and eid and name and eid != "-" and name != "-":
                lp = resolve_local_product_image_path(_u_norm, eid, name)
                if lp is not None:
                    out_u = _take(ensure_static_img_cache_from_path(_u, lp)) or (
                        image_path_to_data_uri(lp) or ""
                    )
            if not out_u:
                try:
                    pil_img = _fetch_image_raw(
                        _u,
                        "catalogue",
                        eetra_id=eid if eid and eid != "-" else None,
                        product_name=name if name and name != "-" else None,
                    )
                    if pil_img is not None and catalogue_image_cache_is_valid(pil_img):
                        static_u = _take(ensure_static_img_cache(_u, pil_img))
                        if static_u:
                            out_u = static_u
                        else:
                            buf = _BytesIO()
                            pil_img.save(buf, format="PNG", optimize=True)
                            b64 = base64.b64encode(buf.getvalue()).decode()
                            out_u = f"data:image/png;base64,{b64}"
                except Exception:
                    pass
            if not out_u:
                # Never fall back to pandas NA placeholders — they become
                # literal img src="<NA>" and break Streamlit static serving.
                out_u = "" if _u in ("-", "nan", "None", "NaN", "<NA>", "NA") else _u
            # /app/static/img_cache is unservable on Community Cloud (SPA HTML
            # 200). Always rewrite to a data URI; if the file is missing, fall
            # back to the original remote URL rather than a dead static path.
            def _payload_img(candidate: str) -> str:
                c = str(candidate or "").strip()
                if not c.startswith("/app/static/"):
                    return c
                converted = static_img_payload_url(c)
                if converted:
                    return converted
                return "" if _u in ("-", "nan", "None", "NaN", "<NA>", "NA") else _u

            out_u = _payload_img(out_u)
            out_d = _payload_img(out_d) if out_d else out_u
            if not out_d:
                out_d = out_u
            _uri_cache[_ck] = (out_u, out_d)
            return _uri_cache[_ck]

        _has_img_local = "U__Img_Local" in df_catalog.columns
        _img_local_series = (
            df_catalog["U__Img_Local"].reset_index(drop=True) if _has_img_local else None
        )
        _rows_as_dicts = [dict(df_slim.iloc[i]) for i in range(_img_n)]
        if _img_local_series is not None:
            for _i, _row in enumerate(_rows_as_dicts):
                _row["imgLocal"] = _row_cell_str(
                    _img_local_series.iloc[_i] if _i < len(_img_local_series) else ""
                )
        _img_uris: list[str] = [""] * _img_n
        _img_detail: list[str] = [""] * _img_n
        with _TPE(max_workers=min(12, max(1, _img_n))) as _pool:
            _futures = {_pool.submit(_url_to_data_uri_row, row): idx for idx, row in enumerate(_rows_as_dicts)}
            _img_done = 0
            for _fut in _as_completed(_futures):
                _card, _detail = _fut.result()
                _img_uris[_futures[_fut]] = _card
                _img_detail[_futures[_fut]] = _detail
                _img_done += 1
        df_slim["imageUrl"] = _img_uris
        # Only carried where it differs — a duplicate URL per row would add ~80 KB
        # to the payload to say nothing. The component falls back to imageUrl.
        df_slim["imageUrlDetail"] = [
            d if d and d != c else "" for c, d in zip(_img_uris, _img_detail)
        ]

    # ── Per-type GWP percentile range (min/max) injected as a lookup table ──
    # Top-level min/max = declared G__GWP_A1A3 (cards / list). Nested m2/m3/kg/m2R1
    # = peer ranges for the detail-panel FU switcher.
    _gwp_ranges: dict[str, dict] = {}
    _fu_range_cols = (
        ("m2", "gwpM2"),
        ("m3", "gwpM3"),
        ("kg", "gwpKg"),
        ("m2R1", "gwpM2R1"),
    )
    if "productType" in df_slim.columns:
        for _ptype, _grp in df_slim.groupby("productType"):
            _entry: dict = {}
            if "gwp" in df_slim.columns:
                _vals = pd.to_numeric(_grp["gwp"], errors="coerce").dropna()
                if len(_vals) > 0:
                    _entry["min"] = float(_vals.min())
                    _entry["max"] = float(_vals.max())
            for _fu_key, _col in _fu_range_cols:
                if _col not in df_slim.columns:
                    continue
                _fvals = pd.to_numeric(_grp[_col], errors="coerce").dropna()
                if len(_fvals) > 0:
                    _entry[_fu_key] = {
                        "min": float(_fvals.min()),
                        "max": float(_fvals.max()),
                    }
            if _entry:
                _gwp_ranges[str(_ptype)] = _entry
    gwp_ranges_json = json.dumps(_gwp_ranges, ensure_ascii=False)

    # ── Per-type recycled-content range (min/max) injected as a lookup table ──
    _rc_ranges: dict[str, dict] = {}
    if "recyclingRate" in df_slim.columns and "productType" in df_slim.columns:
        def _parse_rc(v):
            try:
                return float(str(v or "").strip().rstrip("%").replace(",", "."))
            except Exception:
                return float("nan")
        _rc_vals = df_slim["recyclingRate"].apply(_parse_rc)
        for _ptype, _grp in df_slim.groupby("productType"):
            _rvals = pd.to_numeric(_rc_vals[_grp.index], errors="coerce").dropna()
            _ptype_norm = str(_ptype or "").strip().lower()
            if _ptype_norm == "building boards":
                _rvals = _rvals[_rvals >= 0]
                if len(_rvals) >= 1 and float(_rvals.max()) > 0:
                    _rc_ranges[str(_ptype)] = {
                        "min": 0.0,
                        "max": float(_rvals.max()),
                    }
                continue
            _rvals = _rvals[_rvals > 0]
            if len(_rvals) >= 2:
                _rc_ranges[str(_ptype)] = {
                    "min": float(_rvals.min()),
                    "max": float(_rvals.max()),
                }
    _rc_ranges_json = json.dumps(_rc_ranges, ensure_ascii=False)

    try:
        from . import lib_tags as _lt

        if "eetraId" in df_slim.columns:
            # One grouped pass over tags.parquet, not one lookup per product.
            # fn407_get_tags_for_product calls fn403_load_tags, which .copy()s the
            # whole tags frame and re-resolves its path on every call — so asking
            # it per row meant 1,609 frame copies and 1,609 path resolutions per
            # render. Same result, read once.
            _tags_df = _lt.fn403_load_tags()
            _tags_by_id: dict[str, list[dict]] = {}
            if not _tags_df.empty:
                _td = _tags_df[["eetra_id", "tag_slug", "tag_label"]].drop_duplicates()
                _td = _td.sort_values(
                    "tag_label", key=lambda s: s.fillna("").astype(str).str.lower()
                )
                for _eid_val, _grp in _td.groupby("eetra_id", sort=False):
                    _tags_by_id[str(_eid_val)] = [
                        {"slug": str(_s), "label": str(_l)}
                        for _s, _l in zip(_grp["tag_slug"], _grp["tag_label"])
                    ]

            def _row_tags(_eid):
                if not _lt.fn400_is_valid_product_id(_eid):
                    return []
                return _tags_by_id.get(str(_eid).strip(), [])

            df_slim["tags"] = df_slim["eetraId"].apply(_row_tags)
    except Exception:
        # Fallback mode: JS cards still render when tags layer is unavailable.
        df_slim["tags"] = [[] for _ in range(len(df_slim))]

    # Row-wise work below runs against object-dtype copies. df_catalog arrives
    # with ~125 "string" columns and ~10 "Float64" ones, and pandas rebuilds the
    # common dtype across all 135 on *every* row extraction — so each .iloc[i] or
    # .apply(axis=1) pays a search that dominated the build (8s of a 14s profile
    # in find_common_type alone). One dtype throughout removes that search
    # entirely; the values are unchanged, only how they are boxed per row.
    _cat_obj = df_catalog.astype(object)

    # ── JS2 list table: GWP (kgCO₂e/FU), density, VOC, conductivity, EPD programme ─
    df_slim["gwpDisplay"] = _cat_obj.apply(_fmt_js2_gwp_list, axis=1).values
    if "density" in df_slim.columns:
        # Snapshot after gwpDisplay lands, so the rows passed below carry exactly
        # the columns the per-row read used to see.
        _slim_obj = df_slim.astype(object)
        df_slim["density"] = [
            _fmt_js2_density_list(_slim_obj.iloc[i], _cat_obj.iloc[i])
            for i in range(len(df_slim))
        ]

    _voc_df = pd.DataFrame(
        _cat_obj.apply(_js2_list_voc_fields, axis=1).tolist(),
        columns=["vocText", "vocCertBadge", "vocUrl", "vocCertKey"],
    )
    for _vc in ("vocText", "vocCertBadge", "vocUrl", "vocCertKey"):
        df_slim[_vc] = _voc_df[_vc].values

    if "conductivityAlt" in df_slim.columns:
        def _blank_cond(v) -> bool:
            if v is None:
                return True
            try:
                if pd.isna(v):
                    return True
            except (TypeError, ValueError):
                pass
            if isinstance(v, str) and v.strip() in ("", "-", "nan", "None", "<NA>"):
                return True
            try:
                return float(v) == 0.0
            except (TypeError, ValueError):
                return False

        if "conductivity" not in df_slim.columns:
            df_slim["conductivity"] = df_slim["conductivityAlt"]
        else:
            def _fill_cond(row):
                v = row.get("conductivity")
                if _blank_cond(v):
                    alt = row.get("conductivityAlt")
                    if not _blank_cond(alt):
                        return alt
                return v
            df_slim["conductivity"] = df_slim.apply(_fill_cond, axis=1)
        df_slim = df_slim.drop(columns=["conductivityAlt"])

    if "conductivity" in df_slim.columns:
        def _fmt_cond_cell(v):
            if v is None or (isinstance(v, float) and (pd.isna(v) or v == 0.0)):
                return ""
            try:
                f = float(v)
                if f == 0:
                    return ""
                return f"{f:.3g} W/mK"
            except (TypeError, ValueError):
                s = str(v).strip()
                return s if s and s != "-" else ""
        df_slim["conductivity"] = df_slim["conductivity"].apply(_fmt_cond_cell)

    if "epdProgramme" not in df_slim.columns:
        df_slim["epdProgramme"] = ""

    if "epdNumber" in df_slim.columns:
        def _epd_prog_row(row):
            prog = _row_cell_str(row.get("epdProgramme"))
            if prog:
                return prog
            return _derive_epd_programme_label(_row_cell_str(row.get("epdNumber")))

        df_slim["epdProgramme"] = df_slim.apply(_epd_prog_row, axis=1)

    for _drop in ("vocRaw", "vocCategory", "vocCertRaw", "vocUrlPrimary", "vocUrlAlt"):
        if _drop in df_slim.columns:
            df_slim = df_slim.drop(columns=[_drop])

    # Impact Framework manufacturer card (Manufacturer's Sustainability section).
    if is_js2 and "manufacturer" in df_slim.columns:
        try:
            from .lib_data import fn140c_manufacturer_impact_summaries_by_name

            _mfr_names = (
                df_slim["manufacturer"].fillna("").astype(str).map(str.strip).unique().tolist()
            )
            _mfr_map = fn140c_manufacturer_impact_summaries_by_name(_mfr_names)
            df_slim["mfrSust"] = [
                _mfr_map.get(str(m or "").strip()) or None
                for m in df_slim["manufacturer"].tolist()
            ]
        except Exception:
            df_slim["mfrSust"] = [None] * len(df_slim)

    # EN 520 board-type designation (Tech. Details → "EN 520:2004+A1:2009").
    if is_js2 and "productType" in df_slim.columns:
        from .lib_en520 import fn_en520_payload

        _blank = [None] * len(df_slim)
        # Raw thickness: df_slim["thickness"] is already rounded to "12 mm",
        # which would understate the Type R loads of 12.5 mm boards.
        df_slim["en520"] = [
            fn_en520_payload(_eid, _pt, _cm, _th)
            for _eid, _pt, _cm, _th in zip(
                df_slim["eetraId"].tolist() if "eetraId" in df_slim.columns else _blank,
                df_slim["productType"].tolist(),
                df_slim["comments"].tolist() if "comments" in df_slim.columns else _blank,
                df_catalog["P__Thick_mm"].tolist() if "P__Thick_mm" in df_catalog.columns else _blank,
            )
        ]

    # ── Extended back-panel HTML per product ──────────────────────────────────
    _pt_series = (
        df_slim["productType"].fillna("").astype(str)
        if "productType" in df_slim.columns
        else pd.Series([""] * len(df_slim))
    )
    if not is_js2:
        df_slim["extendedPanelHtml"] = [
            fn336_js2_extended_back_panel_html(_cat_obj.iloc[_ei], _pt_series.iloc[_ei])
            for _ei in range(len(df_slim))
        ]

    _field_vis_map: dict[int, dict[str, bool]] = {}
    if is_js2:
        _field_vis_map = _js2_build_field_vis_map(df_slim, _pt_series)
        df_slim["rawFields"] = _js2_raw_fields_bulk(_cat_obj)

    _field_vis_json = json.dumps(_field_vis_map, ensure_ascii=False)
    # LEED / WELL / CAM alignment per VOC claim (aux_12__voc_rating_alignment.json),
    # sent once per page: the cards look it up by ``vocCertKey``.
    from .lib_revalu_map import voc_alignment_lookup, voc_rating_frameworks

    _voc_align_json = json.dumps(
        {k: [{"short": r["short"], "label": r["label"], "credit": r["credit"],
              "status": r["status"], "note": r["note"]} for r in v]
         for k, v in voc_alignment_lookup().items()},
        ensure_ascii=False,
    )
    _voc_fw_json = json.dumps(
        [{"id": f.get("id", ""), "short": f.get("short", ""), "label": f.get("label", "")}
         for f in voc_rating_frameworks()],
        ensure_ascii=False,
    )
    _list_fields_json = json.dumps(_js2_list_fields_visibility(df_catalog), ensure_ascii=False)

    products_json = df_slim.to_json(orient="records", force_ascii=False)

    # Load JS2 field-visibility config (injected as window.__JS2_FIELDS__)
    _js2_fields_json = "{}"
    _js2_fields_path = Path(__file__).resolve().parent.parent / "aux_07__js2_card_fields.json"
    if _js2_fields_path.exists():
        try:
            _js2_fields_json = _js2_fields_path.read_text(encoding="utf-8")
        except Exception:
            pass
    # Card labels live inside the HTML component, so they never reach fn703 —
    # swap them here, in the payload, for the active language (fn707).
    try:
        from libs.lib_i18n import fn707_translate_card_fields
        _js2_fields_json = fn707_translate_card_fields(_js2_fields_json)
    except Exception:
        pass

    # stella.png as a data URI — the CAM compliance indicator on the cards.
    _stella_img_uri = ""
    _stella_path = Path(__file__).resolve().parent.parent / "03_img" / "stella.png"
    if _stella_path.exists():
        try:
            _stella_b64 = base64.b64encode(_stella_path.read_bytes()).decode()
            _stella_img_uri = f"data:image/png;base64,{_stella_b64}"
        except Exception:
            pass

    return {
        "products_json": products_json,
        # Content address for the static copy the JS2 iframe fetches (see
        # _fn336_static_products_url). Computed here so a cache hit costs nothing.
        "products_md5": hashlib.md5(products_json.encode("utf-8")).hexdigest(),
        "gwp_ranges_json": gwp_ranges_json,
        "rc_ranges_json": _rc_ranges_json,
        "stella_img_uri": _stella_img_uri,
        "js2_fields_json": _js2_fields_json,
        "field_vis_json": _field_vis_json,
        "list_fields_json": _list_fields_json,
        "voc_align_json": _voc_align_json,
        "voc_fw_json": _voc_fw_json,
    }


_CAT_STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "cat_cache"
# Each filter combination is its own file (full catalogue ~10 MB, filtered subsets
# far smaller). Prune oldest-first past this budget, which keeps static/ well under
# Streamlit's 1 GiB startup cap — but never a file this process served recently,
# since an open iframe may still need to fetch it.
_CAT_STATIC_BUDGET_BYTES = 80 * 1024 * 1024
_CAT_STATIC_PROTECT_S = 2 * 3600
_CAT_STATIC_LAST_USED: dict[str, float] = {}


def _fn336_safe_script_json(json_text: str) -> str:
    """Make a JSON text safe to embed inside an HTML ``<script>`` element.

    The HTML parser closes ``<script>`` on the literal characters ``</script>``
    even when they sit inside a JS string. Escaping ``<`` to ``\\u003c`` keeps
    the JS value identical while preventing breakout. Also neutralise the
    Unicode line separators that are legal in JSON strings but terminate JS
    statements in some engines.
    """
    return (
        str(json_text)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .replace("<", "\\u003c")
    )


def _fn336_inline_products_js(products_json: str) -> str:
    """JS that defines ``window.__DATA__`` for the catalogue iframe.

    Prefer a gzip+base64 blob (``window.__DATA_GZ__``): ~11 MB of product JSON
    shrinks to ~1–2 MB, stays clear of ``</script>`` breakouts (base64 alphabet
    has no ``<``), and survives Community Cloud websocket size pressure better
    than a raw array literal. The iframe loader inflates it with
    ``DecompressionStream``.

    Falls back to a ``<``-escaped raw assignment if compression fails.
    """
    import base64
    import gzip

    text = str(products_json or "")
    if not text:
        return "window.__DATA__=[];"

    # pandas ``to_json`` can emit NaN/Infinity, which JSON.parse rejects.
    try:
        json.loads(text)
        raw = text.encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError):
        cleaned = (
            text
            .replace(":NaN", ":null")
            .replace(":Infinity", ":null")
            .replace(":-Infinity", ":null")
        )
        try:
            json.loads(cleaned)
            raw = cleaned.encode("utf-8")
        except (TypeError, ValueError, json.JSONDecodeError):
            return f"window.__DATA__={_fn336_safe_script_json(text)};"

    try:
        b64 = base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")
        return f"window.__DATA_GZ__={json.dumps(b64)};"
    except Exception:
        return f"window.__DATA__={_fn336_safe_script_json(raw.decode('utf-8'))};"


def _fn336_on_streamlit_cloud() -> bool:
    """True when the browser URL looks like Streamlit Community Cloud."""
    try:
        from .lib_data import fn_on_streamlit_cloud
        return bool(fn_on_streamlit_cloud())
    except Exception:
        return False


def _fn336_static_products_url(products_json: str, products_md5: str) -> "str | None":
    """Serve catalogue rows out-of-band; return a URL the JS2 iframe can fetch.

    The JS2 iframe used to carry ``window.__DATA__`` inline, so the full ~11 MB
    products JSON went over the websocket — and was re-parsed by the browser — on
    every Catalogue rerun. Serving the rows by URL keeps the srcdoc small.

    Order of preference:
      1. Streamlit ``MediaFileManager`` — runtime-generated bytes; works on
         Community Cloud (``from streamlit import runtime``, not
         ``streamlit.runtime.runtime``).
      2. ``static/cat_cache/<md5>.json`` when ``enableStaticServing`` is on —
         local only. On Cloud, runtime-written ``static/`` files are not
         reliably served and a miss returns the SPA HTML (``<!doctype html>``),
         which breaks the iframe loader.
      3. ``None`` → caller inlines ``window.__DATA__`` (legacy fallback).
    """
    if not products_md5 or not products_json:
        return None

    data = products_json.encode("utf-8")
    on_cloud = _fn336_on_streamlit_cloud()

    # 1) MediaFileManager — content-addressed within the session; identical
    # payloads reuse the same URL across Catalogue reruns.
    try:
        from streamlit import runtime as _st_runtime

        if _st_runtime.exists():
            media_url = _st_runtime.get_instance().media_file_mgr.add(
                data,
                "application/json",
                coordinates=f"cat_cache.{products_md5}",
                file_name=f"{products_md5}.json",
            )
            if media_url:
                # Ensure a root-absolute path so origin + url resolves correctly.
                if not str(media_url).startswith(("http://", "https://", "/")):
                    media_url = "/" + str(media_url).lstrip("/")
                return media_url
    except Exception:
        pass

    # 2) static/cat_cache — local only. Never on Community Cloud.
    if on_cloud:
        return None

    try:
        if not st.get_option("server.enableStaticServing"):
            return None
    except Exception:
        return None

    target = _CAT_STATIC_DIR / f"{products_md5}.json"
    now = time.time()
    _CAT_STATIC_LAST_USED[target.name] = now
    try:
        if not target.exists():
            _CAT_STATIC_DIR.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(f".{os.getpid()}.{id(products_json)}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            _fn336_prune_static_products(now)
    except OSError:
        return None
    return f"/app/static/cat_cache/{target.name}"


def _fn336_prune_static_products(now: float) -> None:
    """Delete the oldest cat_cache files once the folder exceeds its byte budget."""
    try:
        entries = [
            (e.stat().st_mtime, e.stat().st_size, e.name, e.path)
            for e in os.scandir(_CAT_STATIC_DIR)
            if e.is_file() and e.name.endswith(".json")
        ]
    except OSError:
        return
    total = sum(sz for _, sz, _, _ in entries)
    for _mt, sz, name, path in sorted(entries):          # oldest first
        if total <= _CAT_STATIC_BUDGET_BYTES:
            break
        if now - _CAT_STATIC_LAST_USED.get(name, 0.0) < _CAT_STATIC_PROTECT_S:
            continue
        try:
            os.remove(path)
            total -= sz
            _CAT_STATIC_LAST_USED.pop(name, None)
        except OSError:
            pass


def fn336_render_catalogue_flipcard(
    df_catalog: "pd.DataFrame",
    cols: int = 4,
    height: int = 740,
    _component_path: "Path | None" = None,
    _progress: "Any | None" = None,
    open_product: "str | None" = None,
    _return_payload_only: bool = False,
    doc_preview: "dict | None" = None,
    price_tables: "dict | None" = None,
) -> "dict[str, str] | None":
    """Render flip-card product catalogue as an embedded HTML component.

    ``doc_preview`` is the :func:`fn357_build_doc_panel_payload` result for the
    product whose document rail should open with the view (see pages/2_Catalogue.py).

    ``price_tables`` is :func:`libs.lib_prices.fn512_price_tables_payload` — the
    manufacturer's full listino table per product, opened as a popup from the
    card's list-price row.

    The serialised catalogue itself comes from :func:`_fn336_cached_catalogue_payload`,
    so only the parts that vary per rerun — the theme/session CSS, the open
    product, the document rail — are rebuilt here.

    ``_progress`` is accepted and ignored: the build now reports through the
    cache decorator's spinner, because a progress bar owned by the caller cannot
    be replayed on a cache hit (see the note on the cached function). The
    parameter stays so existing call sites keep working.
    """
    _is_js2 = bool(
        _component_path is not None
        and getattr(_component_path, "name", "") == "catalogue_component_js2.html"
    )
    _payload = _fn336_cached_catalogue_payload(
        df_catalog,
        _is_js2,
        _fn336_payload_config_signature(),
    )
    if _payload is None:
        st.warning("fn336: no recognised columns found in df_catalog.")
        return None
    if _return_payload_only:
        return _payload

    products_json = _payload["products_json"]
    gwp_ranges_json = _payload["gwp_ranges_json"]
    _rc_ranges_json = _payload["rc_ranges_json"]
    _stella_img_uri = _payload["stella_img_uri"]
    _js2_fields_json = _payload["js2_fields_json"]
    # Product/Material Type value translations for the card badges, list
    # cells and group headers. Display only — the payload rows keep the
    # English values every rule and filter in the component runs on.
    try:
        from libs.lib_i18n import fn709_value_maps_for_component
        _value_i18n_json = json.dumps(fn709_value_maps_for_component(), ensure_ascii=False)
    except Exception:
        _value_i18n_json = "{}"
    # The component's own toolbar and filter bar, keyed by their English text.
    try:
        from libs.lib_i18n import fn713_chrome_strings
        _chrome_i18n_json = json.dumps(fn713_chrome_strings(), ensure_ascii=False)
    except Exception:
        _chrome_i18n_json = "{}"
    _field_vis_json = _payload["field_vis_json"]
    _list_fields_json = _payload["list_fields_json"]
    _voc_align_json = _payload.get("voc_align_json", "{}")
    _voc_fw_json = _payload.get("voc_fw_json", "[]")

    from .lib_html import read_iframe_component

    _tpl_path = _component_path if _component_path is not None else CATALOGUE_COMPONENT_PATH
    if not _tpl_path.exists():
        st.error(
            f"Catalogue component not found at `{_tpl_path}`.\n\n"
            "Expected at `html/catalogue_component.html`."
        )
        return
    html_template = read_iframe_component(_tpl_path)
    if _is_js2:
        from .lib_tokens import font_links_html

        _iframe_font_links = font_links_html()
        if _iframe_font_links:
            html_template = html_template.replace("<head>", f"<head>{_iframe_font_links}", 1)
        html_template = re.sub(
            r'<link href="https://fonts\.googleapis\.com/css2\?family=Inter[^"]*" rel="stylesheet">\s*',
            "",
            html_template,
            count=1,
        )
    try:
        _js_card_min = max(0, int(CATALOGUE_JS_CARD_MIN_HEIGHT_PX))
    except (TypeError, ValueError):
        _js_card_min = 0
    try:
        _js_card_max = max(0, int(CATALOGUE_STREAMLIT_CARD_MAX_HEIGHT_PX))
    except (TypeError, ValueError):
        _js_card_max = 0
    try:
        _js_img_band_h = max(0, int(CATALOGUE_CARD_IMAGE_HEIGHT_PX))
    except (TypeError, ValueError):
        _js_img_band_h = 100
    _js_img_pos = _catalogue_css_sanitize_position(str(CATALOGUE_CARD_IMAGE_OBJECT_POSITION or "center"))
    try:
        _js_show_borders = bool(st.session_state.get("catalogue_show_card_borders", True))
    except Exception:
        _js_show_borders = True
    try:
        _dl_raw = st.session_state.get("catalogue_detail_level", "Compact")
        _initial_detail_js = (
            "Extended" if str(_dl_raw).strip().lower() == "extended" else "Compact"
        )
    except Exception:
        _initial_detail_js = "Compact"
    if _js_show_borders:
        _js_cat_border = f"{CATALOGUE_CARD_BORDER_WIDTH} {CATALOGUE_CARD_BORDER_STYLE} {CATALOGUE_CARD_BORDER_COLOR}"
        _js_cat_radius = str(CATALOGUE_CARD_BORDER_RADIUS).strip()
        _js_hov_shadow = str(CATALOGUE_CARD_HOVER_BOX_SHADOW or "").strip() or "none"
        _js_hov_bdr = str(CATALOGUE_CARD_HOVER_BORDER_COLOR or "").strip() or "transparent"
    else:
        _js_cat_border = "none"
        _js_cat_radius = "0"
        _js_hov_shadow = "none"
        _js_hov_bdr = "transparent"

    _typo_css = js2_typography_root_css() if _is_js2 else (
        f"--cat-title-fs:{int(CATALOGUE_JS_TITLE_FONT_SIZE_PX)}px;--cat-title-lh:{float(CATALOGUE_JS_TITLE_LINE_HEIGHT)};"
        f"--cat-body-fs:{int(CATALOGUE_JS_BODY_FONT_SIZE_PX)}px;--cat-body-lh:{float(CATALOGUE_JS_BODY_LINE_HEIGHT)};"
        f"--cat-gwp-lh:{float(CATALOGUE_JS_GWP_LINE_HEIGHT)};"
    )
    _root_css = (
        ":root{"
        f"{catalogue_material_band_css_var_declarations()}"
        f"{_typo_css}"
        f"--cat-border:{_js_cat_border};"
        f"--cat-radius:{_js_cat_radius};"
        f"--cat-bg:{CATALOGUE_CARD_BACKGROUND};"
        f"--cat-pad-x:{CATALOGUE_CARD_BODY_PADDING_X};"
        f"--cat-pad-bottom:{CATALOGUE_CARD_BODY_PADDING_BOTTOM};"
        f"--cat-img-h:{_js_img_band_h}px;"
        f"--cat-img-bg:{CATALOGUE_CARD_IMAGE_BAND_BACKGROUND};"
        f"--cat-img-pos:{_js_img_pos};"
        f"--cat-gwp-pill-mt:{int(_GWP_PILL_MARGIN_TOP_PX)};"
        f"--cat-gwp-pill-mr:{int(_GWP_PILL_MARGIN_RIGHT_PX)};"
        f"--cat-gwp-pill-mb:{int(_GWP_PILL_MARGIN_BOTTOM_PX)};"
        f"--cat-gwp-pill-ml:{int(_GWP_PILL_MARGIN_LEFT_PX)};"
        f"{js_catalogue_theme_root_css()}"
        f"{card_name_divider_root_css() if _is_js2 else ''}"
        f"--cat-hover-shadow:{_js_hov_shadow};"
        f"--cat-hover-border:{_js_hov_bdr};"
        f"--cat-card-min-h:{_js_card_min}px;"
        f"--cat-card-max-h:{f'{_js_card_max}px' if _js_card_max > 0 else 'none'};"
        "}"
    )
    _binder_img = json.dumps(
        {
            "fit": str(CATALOGUE_CARD_IMAGE_BINDER_OBJECT_FIT or "contain"),
            "zoom": float(CATALOGUE_CARD_IMAGE_BINDER_ZOOM),
        },
        ensure_ascii=False,
    )
    # Commercial ranges behind an EPD row (aux_09__product_ranges.json): the
    # included-products popup resolves each D__IncludedProducts name against
    # this index and shows the range as a gallery when it finds images.
    _range_index_json = json.dumps(_fn_product_range_index(), ensure_ascii=False)
    # Collection-level view of the same file, for the Condensed/Expanded entry
    # toggle: Expanded turns one EPD row into one card per "Collezione".
    _range_collections_json = json.dumps(_fn_product_range_collections(), ensure_ascii=False)
    _load_pct = 0
    # Inline product rows into the srcdoc (no /app/static or /media fetch — those
    # return SPA HTML on Community Cloud). Gzip+base64 keeps the payload smaller
    # and avoids </script> breakouts from product text; see _fn336_inline_products_js.
    _sj = _fn336_safe_script_json
    _data_js = _fn336_inline_products_js(products_json)
    data_injection = (
        f"<style>{_root_css}</style>\n"
        f"{js2_list_view_col_widths_css()}\n"
        f"<script>{_data_js} window.__COLS__={int(cols)}; "
        f"window.__INITIAL_DETAIL__={json.dumps(_initial_detail_js)}; "
        f"window.__GWP_RANGES__={_sj(gwp_ranges_json)}; "
        f"window.__RC_RANGES__={_sj(_rc_ranges_json)}; "
        f"window.__CAT_IMG_BINDER__={_sj(_binder_img)}; "
        f"window.__LIST_FIELDS__={_sj(_list_fields_json)}; "
        f"window.__STELLA_IMG__={json.dumps(_stella_img_uri)}; "
        f"window.__CAT_CFG__={_sj(js_catalogue_window_config_json())}; "
        f"window.__JS2_FIELDS__={_sj(_js2_fields_json)}; "
        f"window.__VALUE_I18N__={_sj(_value_i18n_json)}; "
        f"window.__CHROME_I18N__={_sj(_chrome_i18n_json)}; "
        f"window.__VOC_ALIGN__={_sj(_voc_align_json)}; "
        f"window.__VOC_FW__={_sj(_voc_fw_json)}; "
        f"window.__FIELD_VIS__={_sj(_field_vis_json)}; "
        f"window.__RANGE_INDEX__={_sj(_range_index_json)}; "
        f"window.__RANGE_COLLECTIONS__={_sj(_range_collections_json)}; "
        f"window.__MFR_LOGOS__={_sj(json.dumps(_fn_catalogue_mfr_logo_urls(), ensure_ascii=False))}; "
        f"window.__LOAD_PCT__={_load_pct};"
    )
    if _is_js2:
        data_injection += (
            f" window.__IFRAME_HEIGHT__={int(height)};"
            f" window.__JS2_DETAIL_VIEW__={json.dumps(JS2_DETAIL_VIEW_MODE)};"
            f" window.__CAN_EDIT_ITEM__={json.dumps(bool(fn353_is_admin()))};"
        )
        if open_product:
            data_injection += f" window.__OPEN_PRODUCT__={json.dumps(str(open_product))};"
        if doc_preview and doc_preview.get("docs"):
            data_injection += (
                f" window.__DOC_PREVIEW__={_sj(json.dumps(doc_preview))};"
            )
        if price_tables:
            data_injection += (
                f" window.__PRICE_TABLES__={_sj(json.dumps(price_tables, ensure_ascii=False))};"
            )
    data_injection += "</script>\n"
    html_out = html_template.replace("</head>", data_injection + "</head>", 1)
    st.iframe(html_out, height=height)


def fn338_js2_chart_products_payload(df_catalog: "pd.DataFrame") -> dict[str, str]:
    """Serialize JS2 catalogue rows for chart marker detail panel."""
    from .lib_html import CATALOGUE_JS2_COMPONENT_PATH

    payload = fn336_render_catalogue_flipcard(
        df_catalog,
        _component_path=CATALOGUE_JS2_COMPONENT_PATH,
        _return_payload_only=True,
    )
    return payload or {}


@st.cache_resource(max_entries=2, show_spinner="🔄 Preparing product details…")
def _fn338a_cached_chart_rows(_df: "pd.DataFrame", rows_sig: tuple, config_signature: str) -> tuple[dict, list]:
    """(payload without products_json, parsed product rows). Shared and read-only."""
    payload = _fn336_cached_catalogue_payload.__wrapped__(_df, True, config_signature)
    if not payload:
        return {}, []
    rows = json.loads(payload["products_json"])
    for r in rows:
        r.pop("rawFields", None)
    rest = {k: v for k, v in payload.items() if k != "products_json"}
    # Keyed by product id, like the rows, so it can be trimmed to the plotted ids too.
    try:
        rest["_field_vis"] = json.loads(rest.get("field_vis_json") or "{}")
    except ValueError:
        rest["_field_vis"] = None
    return rest, rows


def fn338a_chart_products_payload_slim(
    df_catalog: "pd.DataFrame", ids: "Iterable[int] | None" = None
) -> dict[str, str]:
    """fn338 for the Charts scatter popup, built once per filter state.

    fn338 was called with the axis-filtered frame, so every axis or colour change
    was a payload-cache miss (~1.2 s rebuild, ~3 MB iframe), and its entries
    shared ``max_entries=4`` with the Catalogue, evicting the Catalogue's warm
    payloads. This version parses the rows once from the caller's *stable* frame
    (all charted products), keeps them in their own small cache, drops
    ``rawFields`` (every column as strings, for the Catalogue's XL view — the
    popup never reads it), and serialises only the rows in *ids* (the markers
    actually plotted).

    Product ids are positions in *df_catalog* (``id = row position + 1``), so the
    caller must emit marker ids against this same frame and row order.
    """
    id_col = (df_catalog["0__EETRA_ID"].astype(str) if "0__EETRA_ID" in df_catalog.columns
              else df_catalog.index.astype(str).to_series())
    rows_sig = (
        len(df_catalog),
        # index=True on a fresh RangeIndex: the hash covers position, not just the set.
        int(pd.util.hash_pandas_object(id_col.reset_index(drop=True), index=True).sum()),
        tuple(st.session_state.get("_data_fingerprint") or ()),
        tuple(df_catalog.columns),
    )
    rest, rows = _fn338a_cached_chart_rows(df_catalog, rows_sig, _fn336_payload_config_signature())
    out = {k: v for k, v in rest.items() if k != "_field_vis"}
    if ids is not None:
        wanted = {int(i) for i in ids}
        rows = [r for r in rows if int(r.get("id", 0)) in wanted]
        fv = rest.get("_field_vis")
        if isinstance(fv, dict):
            out["field_vis_json"] = json.dumps(
                {k: v for k, v in fv.items() if str(k).isdigit() and int(k) in wanted},
                ensure_ascii=False)
    out["products_json"] = json.dumps(rows, ensure_ascii=False)
    return out


# ════════════════════════════════════════════════════════════════════════════
# fn337–fn339  HTML renderers (from render/fn_render.py)
# ════════════════════════════════════════════════════════════════════════════

def _base_css() -> str:
    """Design tokens + shared component CSS for **iframe** HTML builders.

    Tokens come from theme.json (``_tokens.css``); component classes come from
    ``02_html/base.html``. Callers are the ``st.iframe`` HTML string builders
    (fn337, fn338, fn339 …) — page headers must NOT use this, because
    ``base.html`` carries a ``*`` / ``body`` reset that has no business in the
    main Streamlit document.
    """
    from .lib_html import read_base_css
    from .lib_tokens import tokens_css_text

    _tokens = tokens_css_text().strip()
    _token_style = f"<style>{_tokens}</style>" if _tokens else ""
    _file_css = read_base_css()
    if _file_css:
        return _token_style + _file_css
    return _token_style + """<style>
body{font-family:var(--font,sans-serif);font-size:var(--base-size,13px);
color:var(--text,#1e293b);background:var(--bg,#fff);}
</style>"""


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _val(p: dict, col: str) -> str:
    v = p.get(col, "")
    if v is None or str(v).strip() in ("", "nan", "None", "NaN"):
        return "-"
    return str(v).strip()


def _gwp_display_html(p: dict) -> str:
    product_type = _val(p, "D__ProductType_ENG")

    def _fmt(n: str) -> str:
        try:
            f = float(n)
            return f"{f:.2f}" if f < 10 else f"{f:.1f}"
        except Exception:
            return n

    if product_type and "in situ" in product_type.lower():
        gwp_m3 = _val(p, "G__GWP_A1A3_m3")
        return f"{_fmt(gwp_m3)} kgCO₂e/m³" if gwp_m3 != "-" else "GWP: n/a"
    gwp = _val(p, "G__GWP_A1A3")
    fu  = _val(p, "G__GWP_FU")
    if gwp != "-":
        fu_display = fu.replace("m2", "m²").replace("m3", "m³") if fu != "-" else ""
        sep = "/" if fu_display else ""
        return f"{_fmt(gwp)} kgCO₂e{sep}{fu_display}"
    return "GWP: n/a"


def _render_single_card_html(p: dict, detail_level: str, display_params: dict) -> str:
    brand    = _val(p, "A__Manufacturer")
    name     = _val(p, "A__ProductName")
    img_url  = _val(p, "U__Img_URL")
    info_url = _val(p, "U__ProductInfo_URL")
    gwp_str  = _gwp_display_html(p)

    img_html = (
        f'<img src="{_esc(img_url)}" alt="{_esc(name)}" loading="lazy" '
        f'onerror="this.parentNode.innerHTML=\'<div class=card-no-img>📦</div>\'">'
        if img_url != "-"
        else '<div class="card-no-img">📦</div>'
    )
    name_html = (
        f'<a href="{_esc(info_url)}" target="_blank">{_esc(name)}</a>'
        if info_url != "-"
        else _esc(name)
    )
    body_extra = ""
    if detail_level == "Extended" or display_params:
        detail_lines = []
        thick = "-"
        for tc in ["P__Thick_mm", "P__Thickness_mm", "B__Thickness_mm", "D__Thickness_mm"]:
            v = _val(p, tc)
            if v != "-":
                thick = v
                break
        if thick != "-" and display_params.get("Thickness", True):
            detail_lines.append(f'<span class="label">Thickness</span> {_esc(thick)} mm')
        rc = _val(p, "R__RecycledContent_pct")
        if rc != "-" and display_params.get("Recycled Content", True):
            try:
                rc_fmt = f"{float(rc):.1f}%"
            except Exception:
                rc_fmt = rc
            detail_lines.append(f'<span class="label">Recycled</span> {_esc(rc_fmt)}')
        epd = _val(p, "E__EPD_RegNumber")
        if epd != "-" and display_params.get("EPD Number", True):
            detail_lines.append(f'<span class="label">EPD</span> {_esc(epd)}')
        country = _val(p, "E__ManuCountry")
        plant   = _val(p, "E__ManuPlant")
        if country != "-" and display_params.get("Country", True):
            detail_lines.append(f'<span class="label">Made in</span> {_esc(country)}')
        if plant != "-" and display_params.get("Plant", True):
            detail_lines.append(f'<span class="label">Plant</span> {_esc(plant)}')
        if detail_lines:
            body_extra = f'<div class="card-detail">{"<br>".join(detail_lines)}</div>'

    chips = []
    cam_ok = _val(p, "C__CAM")
    if cam_ok not in ("-", "N", "No", ""):
        chips.append('<span class="chip cam">CAM ✓</span>')
    rc_pct = _val(p, "R__RecycledContent_pct")
    if rc_pct not in ("-", "0", "0.0"):
        try:
            if float(rc_pct) > 0:
                chips.append(f'<span class="chip recl">♻ {float(rc_pct):.0f}%</span>')
        except Exception:
            pass
    chips_html = f'<div class="card-chips">{"".join(chips)}</div>' if chips else ""

    return f"""
<div class="product-card">
  <div class="card-img-wrap">{img_html}</div>
  <div class="card-body">
    <div class="card-brand">{_esc(brand)}</div>
    <div class="card-name">{name_html}</div>
    <div class="card-gwp">{_esc(gwp_str)}</div>
    {body_extra}
    {chips_html}
  </div>
</div>"""


def fn337_render_catalogue(
    groups_json: str,
    cols_per_row: int = 5,
    display_params: dict | None = None,
    detail_level: str = "Compact",
) -> str:
    """Returns HTML for the full product card grid."""
    try:
        groups = json.loads(groups_json) if groups_json else [{"label": None, "products": []}]
    except Exception:
        groups = [{"label": None, "products": []}]
    display_params = display_params or {}
    cards_html = ""
    for group in groups:
        label    = group.get("label")
        products = group.get("products", [])
        if label:
            cards_html += f'<div class="group-header">{_esc(label)}</div>\n'
        cards_html += f'<div class="card-grid" style="grid-template-columns: repeat({cols_per_row}, 1fr);">\n'
        for p in products:
            cards_html += _render_single_card_html(p, detail_level, display_params)
        cards_html += "</div>\n"
    total = sum(len(g.get("products", [])) for g in groups)
    return f"""{_base_css()}
<style>
.catalogue-wrap {{ padding: 0 0 24px; }}
.result-count {{ font-size:12px;color:var(--text2);margin-bottom:12px;padding:6px 0;border-bottom:1px solid var(--border); }}
.group-header {{ font-family:var(--font-serif);font-style:italic;font-weight:400;font-size:15px;color:var(--green);margin:16px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--border); }}
.card-grid {{ display:grid;gap:10px;margin-bottom:12px; }}
.product-card {{ background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;display:flex;flex-direction:column;transition:box-shadow .15s,border-color .15s;font-size:12px; }}
.product-card:hover {{ box-shadow:0 4px 12px rgba(0,0,0,.09);border-color:#c8e6c9; }}
.card-img-wrap {{ background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:center;min-height:90px;overflow:hidden; }}
.card-img-wrap img {{ width:100%;height:90px;object-fit:contain;padding:6px; }}
.card-no-img {{ width:100%;height:90px;display:flex;align-items:center;justify-content:center;font-size:24px;color:var(--text3); }}
.card-body {{ padding:8px 9px 10px;flex:1;display:flex;flex-direction:column;gap:2px; }}
.card-brand {{ font-size:10px;color:var(--text2);font-weight:500; }}
.card-name {{ font-size:11.5px;font-weight:600;color:var(--text);line-height:1.3; }}
.card-name a {{ color:var(--text);text-decoration:none; }}
.card-name a:hover {{ color:var(--green); }}
.card-gwp {{ font-family:var(--font-serif);font-style:italic;font-weight:600;font-size:13px;color:var(--green);margin-top:3px; }}
.card-detail {{ font-size:11px;color:var(--text2);line-height:1.35; }}
.card-detail .label {{ color:var(--text3);font-size:10px;text-transform:uppercase;letter-spacing:.04em; }}
.card-chips {{ display:flex;flex-wrap:wrap;gap:3px;margin-top:4px; }}
.chip {{ display:inline-block;padding:1px 6px;border-radius:999px;font-size:10px;font-weight:600;background:var(--surface2);color:var(--text2);border:1px solid var(--border); }}
.chip.epd {{ background:#dbeafe;color:#1e40af;border-color:#bfdbfe; }}
.chip.cam {{ background:#dcfce7;color:#15803d;border-color:#bbf7d0; }}
.chip.recl {{ background:#fef3c7;color:#92400e;border-color:#fde68a; }}
.no-results {{ text-align:center;padding:40px 20px;color:var(--text2);font-size:14px; }}
</style>
<div class="catalogue-wrap">
  <div class="result-count">{total} product{'s' if total != 1 else ''} shown</div>
  {cards_html if total > 0 else '<div class="no-results">🔍 No products match the current filters.</div>'}
</div>"""


def fn338_render_revalu(data_json: str) -> str:
    """Returns HTML for the Revalu EPD matching results table."""
    try:
        products = json.loads(data_json) if data_json else []
    except Exception:
        products = []

    def _status_chip(status: str) -> str:
        mapping = {
            "linked":  ("epd",  "Linked"),
            "number":  ("recl", "Has Number"),
            "missing": ("chip", "Missing"),
            "expired": ("chip", "Expired"),
        }
        cls, label = mapping.get(status.lower(), ("chip", status))
        return f'<span class="chip {cls}">{_esc(label)}</span>'

    rows_html = ""
    for p in products:
        name   = _val(p, "A__ProductName")
        brand  = _val(p, "A__Manufacturer")
        epd_n  = _val(p, "E__EPD_RegNumber")
        status = str(p.get("revalu_status", "missing")).lower()
        links  = p.get("revalu_links", {}) or {}
        link_chips = (
            " ".join(
                f'<a href="{_esc(url)}" target="_blank" class="chip blue" style="text-decoration:none">{_esc(reg)}</a>'
                for reg, url in links.items()
            ) if links else '<span style="color:var(--text3);font-size:11px">—</span>'
        )
        rows_html += f"""
<tr>
  <td style="max-width:220px">
    <div style="font-weight:600;font-size:12px">{_esc(name)}</div>
    <div style="font-size:11px;color:var(--text2)">{_esc(brand)}</div>
  </td>
  <td style="font-size:11px;font-family:monospace;color:var(--text2)">{_esc(epd_n)}</td>
  <td>{_status_chip(status)}</td>
  <td style="min-width:180px">{link_chips}</td>
</tr>"""

    return f"""{_base_css()}
<style>
.revalu-wrap {{ padding: 0 0 20px; }}
.revalu-header {{ display:flex;align-items:center;gap:12px;padding:14px 18px;background:linear-gradient(135deg,#0d1f3c 0%,#1a3a6b 50%,#2a7d2e 100%);border-radius:var(--radius);margin-bottom:14px; }}
.revalu-header h2 {{ color:white;font-size:15px;font-weight:700;margin:0; }}
.revalu-header p {{ color:rgba(255,255,255,.7);font-size:11px;margin:2px 0 0; }}
.revalu-badge {{ margin-left:auto;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:6px;padding:5px 12px;color:white;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap; }}
.revalu-search-wrap {{ margin-bottom:10px; }}
.revalu-search {{ width:100%;padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius);font-size:13px;outline:none;transition:border-color .15s; }}
.revalu-search:focus {{ border-color:var(--green); }}
.tbl-wrap {{ border:1px solid var(--border);border-radius:var(--radius);overflow:hidden; }}
.eetra-table {{ width:100%;border-collapse:collapse;font-size:12px; }}
.eetra-table th {{ background:var(--surface2);color:var(--text2);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap; }}
.eetra-table td {{ padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:middle; }}
.eetra-table tr:last-child td {{ border-bottom:none; }}
.eetra-table tr:hover td {{ background:var(--surface); }}
.chip {{ display:inline-block;padding:2px 7px;border-radius:999px;font-size:10px;font-weight:600;background:var(--surface2);color:var(--text2);border:1px solid var(--border); }}
.chip.epd {{ background:#dbeafe;color:#1e40af;border-color:#bfdbfe; }}
.chip.recl {{ background:#fef3c7;color:#92400e;border-color:#fde68a; }}
.chip.blue {{ background:#dbeafe;color:#1e40af;border-color:#bfdbfe; }}
#revalu-count {{ font-size:12px;color:var(--text2);margin-bottom:8px; }}
</style>
<div class="revalu-wrap">
  <div class="revalu-header">
    <div><h2>Revalu EPD Registry Cross-Match</h2><p>Finding publicly available EPD documents for products in the EETRA database</p></div>
    <div class="revalu-badge">Partnership Tool</div>
  </div>
  <div class="revalu-search-wrap">
    <input class="revalu-search" id="revalu-search" type="text"
           placeholder="🔍  Search by product name, manufacturer, or EPD number…"
           oninput="filterRevalu(this.value)">
  </div>
  <div id="revalu-count">{len(products)} products</div>
  <div class="tbl-wrap">
    <table class="eetra-table" id="revalu-tbl">
      <thead><tr><th>Product</th><th>EPD Number</th><th>Status</th><th>Registry Links</th></tr></thead>
      <tbody id="revalu-body">{rows_html}</tbody>
    </table>
  </div>
</div>
<script>
function filterRevalu(q) {{
  var rows = document.querySelectorAll('#revalu-body tr');
  var n = 0; var lq = q.toLowerCase();
  rows.forEach(function(r) {{
    var show = lq === '' || r.textContent.toLowerCase().indexOf(lq) !== -1;
    r.style.display = show ? '' : 'none';
    if (show) n++;
  }});
  document.getElementById('revalu-count').textContent = n + ' product' + (n !== 1 ? 's' : '');
}}
</script>"""


def fn339_render_filter_summary(filters_json: str) -> str:
    """DEPRECATED — returns a small HTML filter summary strip for an ``st.iframe``.

    Superseded by :func:`fn355_render_active_filters`, which renders the same
    information natively (no 48 px iframe), adds a Clear-all control and is used
    by every filtered page. Kept only so nothing breaks if an external caller
    still imports it; do not use it in new code.
    """
    try:
        filters = json.loads(filters_json) if filters_json else []
    except Exception:
        filters = []
    if not filters:
        chips_html = '<span style="color:var(--text3);font-size:12px">No filters applied</span>'
    else:
        chips = []
        for f in filters:
            col = str(f.get("col", "")).split("__")[-1].replace("_", " ")
            val = str(f.get("val", ""))
            chips.append(
                f"<span style='display:inline-flex;align-items:center;gap:4px;padding:3px 8px;"
                f"background:var(--green-light);border:1px solid #c8e6c9;border-radius:999px;"
                f"font-size:11px;font-weight:600;color:var(--green)'>"
                f"{_esc(col)}: {_esc(val)}</span>"
            )
        chips_html = " ".join(chips)
    return f"""{_base_css()}
<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:4px 0 8px">
  <span style="font-size:11px;color:var(--text3);font-weight:500;text-transform:uppercase;letter-spacing:.05em;margin-right:4px">Filters:</span>
  {chips_html}
</div>"""


# ════════════════════════════════════════════════════════════════════════════
# fn340–fn342  Utility + legacy
# ════════════════════════════════════════════════════════════════════════════

def fn340_filter_cleaned_by_allowed(df, cleaned_list, allowed_map):
    """Keep only cleaned column names whose original column is in the allowlist."""
    if not isinstance(allowed_map, dict) or not allowed_map:
        return cleaned_list
    allowed_originals = {k for k, v in allowed_map.items() if v}
    if not allowed_originals:
        return cleaned_list
    from .lib_data import fn125_get_original_column_name
    filtered = [c for c in cleaned_list if fn125_get_original_column_name(df, c) in allowed_originals]
    return filtered or cleaned_list


def fn341_inject_custom_styles_legacy():
    """Delegate to lib_header inject_global_css (single source of truth)."""
    from .lib_header import fn005_inject_global_css
    fn005_inject_global_css()


# ════════════════════════════════════════════════════════════════════════════
# fn350–fn360  Shared app-shell helpers
# ---------------------------------------------------------------------------
# One implementation each for: per-run guards, embedded-page hosting, role
# checks, empty states, loading, debug captions, iframe heights, and catalogue
# payload warm-up. Pages must use these instead of hand-rolling their own
# variant — that divergence is what made the app look and behave differently
# page by page.
# ════════════════════════════════════════════════════════════════════════════

EMBEDDED_PAGE_KEY = "_eetra_embedded_page"
_RUN_SEQ_KEY = "_eetra_run_seq"


def fn350_begin_run() -> int:
    """Bump the per-run counter. Called once by ``app.py`` at the top of a run."""
    n = int(st.session_state.get(_RUN_SEQ_KEY, 0)) + 1
    st.session_state[_RUN_SEQ_KEY] = n
    return n


def fn351_once_per_run(key: str) -> bool:
    """True the first time it is called with *key* in the current script run.

    Used to stop the 20 KB global stylesheet being injected several times per
    run (``app.py`` + every page that re-injected it defensively). Fragment
    reruns keep the same counter, which is correct: CSS already in the document
    does not need re-sending.
    """
    seq = st.session_state.get(_RUN_SEQ_KEY)
    if seq is None:
        return True
    marker = f"_eetra_once_{key}"
    if st.session_state.get(marker) == seq:
        return False
    st.session_state[marker] = seq
    return True


def fn352_is_embedded_page() -> bool:
    """True when the running page file is embedded in another page's tab."""
    return bool(st.session_state.get(EMBEDDED_PAGE_KEY))


def fn353_is_admin() -> bool:
    return str(st.session_state.get("auth_role", "")).strip().lower() == "admin"


import datetime as _dt_mod  # noqa: E402 — the module; `datetime` here is the class
_KEEP_SCALAR_TYPES = (str, int, float, bool, _dt_mod.date)


def fn353a_keep_widget_state(*prefixes: str, exclude: "tuple[str, ...]" = ()) -> None:
    """Keep widget values alive while their lazy tab is hidden.

    Lazy tabs (``st.tabs(..., on_change="rerun")`` + ``if tab.open:``) only run
    the selected tab's code. Streamlit drops the state of any widget not rendered
    in a run, so without this, every chart setting in a tab would reset to its
    default the moment the user looked at another tab. Re-saving a widget's value
    through the Session State API at the top of the run turns it into
    user-owned state, which survives (the documented "interrupt the cleanup"
    pattern).

    Only plain values are re-saved (str/number/bool/date, or lists of those).
    **Do not pass prefixes that cover ``st.button`` / ``st.download_button`` /
    ``st.file_uploader`` / ``st.data_editor`` keys** — Streamlit refuses Session
    State writes for those and raises when the widget is next created. Name such
    keys in ``exclude`` if a prefix must include them.

    Call once per run, before the tabs are created.
    """
    ss = st.session_state
    for k in list(ss.keys()):
        if not isinstance(k, str) or not k.startswith(prefixes) or k in exclude:
            continue
        try:
            v = ss[k]
        except Exception:
            continue
        if isinstance(v, _KEEP_SCALAR_TYPES) or (
            isinstance(v, (list, tuple))
            and all(isinstance(x, (str, int, float)) for x in v)
        ):
            try:
                ss[k] = v
            except Exception:
                pass


@st.cache_resource(show_spinner=False)
def _fn354_compiled_page(path_str: str, mtime_ns: int, size: int):
    """Compile an embedded page script once per file version (mtime + size).

    Size is included because OneDrive can leave ``st_mtime_ns`` unchanged across
    quick successive writes, which otherwise leaves a stale bytecode cache.
    """
    return compile(Path(path_str).read_text(encoding="utf-8"), path_str, "exec")


def fn354_run_embedded_page(path, label: str, **session_flags) -> None:
    """Render another page file inline, as a section of the host page.

    Replaces the three near-identical copies that lived in ``2_Catalogue.py``,
    ``5_Developer.py`` and ``14_FurtherDataSources.py``. Sets the single
    ``EMBEDDED_PAGE_KEY`` flag (embedded pages suppress their own page header
    via ``fn352_is_embedded_page``) plus any page-specific flags passed as
    keyword arguments, and always clears them again.
    """
    path = Path(path)
    if not path.exists():
        fn356_empty_state(f"{path.name} not found.", kind="error")
        return
    _previous = {k: st.session_state.get(k) for k in session_flags}
    st.session_state[EMBEDDED_PAGE_KEY] = True
    st.session_state.update(session_flags)
    try:
        _stat = path.stat()
        _code = _fn354_compiled_page(str(path), _stat.st_mtime_ns, _stat.st_size)
        exec(_code, {"__name__": f"embedded_{path.stem}", "__file__": str(path)})
    except Exception as _e:
        fn356_empty_state(f"{label} could not be loaded: {_e}", kind="error")
    finally:
        st.session_state.pop(EMBEDDED_PAGE_KEY, None)
        for _k in session_flags:
            if _previous.get(_k) is None:
                st.session_state.pop(_k, None)
            else:
                st.session_state[_k] = _previous[_k]


_FILTER_RESET_KEY = "_eetra_filter_reset_request"


def fn355_request_filter_reset(extra_keys: "list[str] | None" = None) -> None:
    """Queue a filter reset to be applied at the start of the next run."""
    queued = set(st.session_state.get(_FILTER_RESET_KEY) or [])
    queued.update(extra_keys or [])
    st.session_state[_FILTER_RESET_KEY] = sorted(queued)


def fn355_apply_pending_filter_reset() -> bool:
    """Consume a queued reset. Must run before the filter widgets are created.

    Deleting a widget key restores that widget's default, which is why this is a
    pop rather than an assignment.
    """
    if _FILTER_RESET_KEY not in st.session_state:
        return False
    extra = st.session_state.pop(_FILTER_RESET_KEY) or []
    for i in range(1, 4):
        st.session_state.pop(f"enable_filter_{i}", None)
    for key in extra:
        st.session_state.pop(key, None)
    return True


def _fn355_column_label(col: str) -> str:
    """Human label for a raw column name, matching the rest of the UI."""
    labels = st.session_state.get("COLUMN_DISPLAY_LABELS") or {}
    if isinstance(labels, dict) and labels.get(col):
        label = str(labels[col])
    else:
        stem = re.sub(r"^[A-Za-z0-9]__", "", str(col)).replace("_", " ")
        stem = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)      # ProductType -> Product Type
        label = re.sub(r"\bENG\b", "", stem).strip() or str(col)
    try:
        from libs.lib_i18n import fn703_translate_field
        return fn703_translate_field(col, label)
    except Exception:
        return label


def fn355_active_filter_chips(extra: "list[tuple[str, str]] | None" = None) -> list:
    """Active sidebar dataset filters (+ optional page-level pairs) as label/value."""
    chips: list = []
    for i in range(1, 4):
        if not st.session_state.get(f"enable_filter_{i}"):
            continue
        col = str(st.session_state.get(f"filter_col_{i}") or "").strip()
        val = st.session_state.get(f"filter_val_{i}")
        if not col or val in (None, ""):
            continue
        chips.append((_fn355_column_label(col), _fn302_tv(col, val)))
    for pair in (extra or []):
        if pair and pair[1] not in (None, "", []):
            chips.append((str(pair[0]), str(pair[1])))
    return chips


def fn355_render_active_filters(
    extra: "list[tuple[str, str]] | None" = None,
    *,
    key_prefix: str = "flt",
    clear_keys: "list[str] | None" = None,
    show_clear: bool = True,
) -> None:
    """One shared "what am I looking at" strip, used by Catalogue and Charts.

    Replaces the Charts-only iframe summary (``fn339_render_filter_summary``,
    which cost a 48 px iframe) and gives every filtered page the same chip row
    plus an optional Clear-all control — previously there was no way to see that
    the sidebar was narrowing the data, and no way to reset it in one action.
    """
    chips = fn355_active_filter_chips(extra)

    def _render_chips() -> None:
        if not chips:
            st.markdown(
                "<div class='eetra-filterbar'>"
                f"<span class='eetra-filterbar-label'>{_fn302_tu('Filters')}</span>"
                "<span class='eetra-filterbar-none'>"
                f"{_fn302_tu('none — showing all products')}</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            return
        _items = "".join(
            f"<span class='eetra-filter-chip'>"
            f"<span class='eetra-filter-chip-key'>{_html.escape(k)}</span>"
            f"{_html.escape(v)}</span>"
            for k, v in chips
        )
        st.markdown(
            "<div class='eetra-filterbar'>"
            f"<span class='eetra-filterbar-label'>{_fn302_tu('Filters')}</span>"
            f"{_items}</div>",
            unsafe_allow_html=True,
        )

    if not show_clear:
        _render_chips()
        return

    _col_chips, _col_btn = st.columns([8, 1], gap="small", vertical_alignment="center")
    with _col_chips:
        _render_chips()
    with _col_btn:
        if st.button(
            _fn302_tu("Clear all"),
            key=f"{key_prefix}_clear_all",
            width="stretch",
            disabled=not chips,
            help=_fn302_tu(
                "Turn off every dataset filter and clear this page's search and tags."
            ),
        ):
            # The sidebar toggles are instantiated by app.py *before* this page
            # body runs, and the page's own search/tag widgets are created above
            # this button — so their keys cannot be written to now. Queue the
            # reset and let fn302_render_filter_widgets apply it at the top of
            # the next run, before any of those widgets exist.
            fn355_request_filter_reset(clear_keys)
            st.rerun()


_EMPTY_STATE_ICONS = {
    "info": "ℹ️",
    "empty": None,   # nothing-here states read better without an icon
    "locked": "🔒",
    "error": "⚠️",
    "warn": "⚠️",
}


def fn356_empty_state(
    message: str,
    *,
    kind: str = "info",
    action_label: str = "",
    action_key: str = "",
    hint: str = "",
) -> bool:
    """The app's single empty / blocked / error state.

    ``kind``: ``info`` · ``empty`` · ``locked`` · ``warn`` · ``error``.
    Returns True when the optional action button was clicked this run.
    """
    icon = _EMPTY_STATE_ICONS.get(kind, "ℹ️")
    # Translated here, so every page's empty state follows the app language
    # without each call site having to wrap its own message.
    message = _fn302_tu(str(message))
    hint = _fn302_tu(str(hint)) if hint else hint
    action_label = _fn302_tu(action_label) if action_label else action_label
    text = message if not hint else f"{message}  \n{hint}"
    if kind == "error":
        st.error(text, icon=icon)
    elif kind == "warn":
        st.warning(text, icon=icon)
    else:
        st.info(text, icon=icon)
    # NOTE: icons must be a single emoji character — Streamlit rejects anything
    # else (including "—" and shortcodes), so `empty` deliberately passes None.
    if action_label:
        return st.button(action_label, key=action_key or f"empty_action_{abs(hash(message)) % 10**8}")
    return False


def fn357_loading(label: str):
    """The app's single loading indicator (context manager)."""
    return st.spinner(label, show_time=False)


def fn358_debug_caption(text: str) -> None:
    """Diagnostics caption — timings, cache-miss notes, paths. Admins only.

    Load timings used to be printed to every user on ECOportal and ICE DB;
    they are developer information, not product copy.
    """
    if fn353_is_admin():
        st.caption(text)


def fn359_iframe_height(name: str = "") -> int:
    """Shared iframe height from ``theme.json → layout`` (see lib_tokens)."""
    from .lib_tokens import iframe_height

    return iframe_height(name)


# ── Catalogue payload warm-up (background, once per view) ───────────────────
# The JS2 catalogue serialisation (_fn336_cached_catalogue_payload) is the slow
# first hit when opening Catalogue (~image resolve + per-row formatting + JSON).
# app.py kicks this off after FILTERED_DATA is ready so Welcome / other pages
# stay responsive while the cache fills.
_CATALOGUE_WARM_LOCK = threading.Lock()
_CATALOGUE_WARM_INFLIGHT: set[str] = set()
_CATALOGUE_WARM_DONE: set[str] = set()


def _fn360_warmup_arrange_default(df: "pd.DataFrame") -> str:
    """Match pages/2_Catalogue.py arrange default for the product types in *df*."""
    types: list[str] = []
    if "D__ProductType_ENG" in df.columns:
        for v in df["D__ProductType_ENG"].dropna().astype(str).unique():
            nv = fn315_normalize_product_type(v)
            if nv and nv not in types:
                types.append(nv)
    if len(types) == 1:
        pt = types[0].lower()
        if "building boards" in pt:
            return "Thickness"
        if "insulation" in pt:
            return "MaterialType"
        if "binder" in pt or "cement" in pt:
            return "D__EN197-1"
        if "in situ" in pt or "concrete" in pt:
            return "D__EN206"
    return "Manufacturer"


def fn360_catalogue_warmup_frame(df_filtered: "pd.DataFrame") -> "pd.DataFrame":
    """Map_yn=Y + the same default sort/arrange the Catalogue page applies cold."""
    if df_filtered is None or getattr(df_filtered, "empty", True):
        return pd.DataFrame()
    df = df_filtered
    if "A__Map_yn" in df.columns:
        df = df[df["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"]
    if df.empty:
        return df

    sort_field = str(st.session_state.get("catalogue_sort_field") or "Product Name")
    sort_order = str(st.session_state.get("catalogue_sort_order") or "A-Z (low-high)")
    ascending = sort_order != "Z-A (high-low)"
    sort_cols = {
        "Product Name": "A__ProductName",
        "Manufacturer": ["A__Manufacturer", "A__ProductName"],
        "EPD Number": "E__EPD_RegNumber",
        "GWP": "G__GWP_A1A3",
    }
    sort_col = sort_cols.get(sort_field, "A__ProductName")
    if isinstance(sort_col, list):
        present = [c for c in sort_col if c in df.columns]
        out = df.sort_values(by=present, ascending=ascending) if present else df.copy()
    elif sort_col in df.columns:
        out = df.copy()
        if sort_col in ("P__Mass_kgm3", "G__GWP_A1A3"):
            out[sort_col] = pd.to_numeric(out[sort_col], errors="coerce")
        out = out.sort_values(by=sort_col, ascending=ascending)
    else:
        out = df.copy()

    arrange = str(
        st.session_state.get("catalogue_arrange_by")
        or _fn360_warmup_arrange_default(out)
    )
    if arrange == "Thickness":
        out = out.copy()
        out["__ARR_TV"] = out.apply(fn332_extract_thickness_value, axis=1)
        out["__ARR_TV"] = out["__ARR_TV"].apply(
            lambda v: 15.0 if abs(v - 15.5) < 1e-9 else v
        )
        out = out.sort_values("__ARR_TV", kind="mergesort")
        out.drop(columns=["__ARR_TV"], inplace=True, errors="ignore")
    elif arrange == "MaterialType" and "D__MaterialType_ENG" in out.columns:
        out = out.sort_values("D__MaterialType_ENG", kind="mergesort")
    elif arrange == "D__EN197-1" and "D__EN197-1" in out.columns:
        out = out.sort_values("D__EN197-1", kind="mergesort")
    elif arrange == "D__EN206":
        if "D__EN206" in out.columns or "A__ProductName" in out.columns:
            out = out.copy()
            out["__ARR_RC"] = out.apply(fn330_extract_resistance_class, axis=1)
            out["__ARR_RC_SORT"] = out["__ARR_RC"].apply(fn331_resistance_sort_key)
            out = out.sort_values("__ARR_RC_SORT", kind="mergesort")
            out.drop(columns=["__ARR_RC", "__ARR_RC_SORT"], inplace=True, errors="ignore")
    elif arrange == "Manufacturer" and "A__Manufacturer" in out.columns:
        out = out.sort_values("A__Manufacturer", kind="mergesort")
    return out


def fn360_start_catalogue_payload_warmup(
    df_filtered: "pd.DataFrame",
    *,
    skip: bool = False,
) -> None:
    """Fire-and-forget: populate ``_fn336_cached_catalogue_payload`` for the current view.

    Called from ``app.py`` after ``FILTERED_DATA`` is ready. Skipped when the
    Catalogue page itself is about to build the payload (*skip*), when the frame
    is empty, or when a matching warm-up is already done / in flight this
    session. The worker reuses the active ScriptRunContext so ``@st.cache_data``
    and session-backed config (field visibility, language) resolve correctly.
    """
    if skip or df_filtered is None or getattr(df_filtered, "empty", True):
        return
    try:
        config_sig = _fn336_payload_config_signature()
        warm_df = fn360_catalogue_warmup_frame(df_filtered)
        if warm_df.empty:
            return
        try:
            id_sig = (
                int(pd.util.hash_pandas_object(
                    warm_df["0__EETRA_ID"].astype(str), index=False).sum())
                if "0__EETRA_ID" in warm_df.columns else len(warm_df)
            )
        except Exception:
            id_sig = len(warm_df)
        warm_key = "|".join(
            (
                str(st.session_state.get("_data_fingerprint") or ()),
                config_sig,
                str(len(warm_df)),
                str(id_sig),
            )
        )
        with _CATALOGUE_WARM_LOCK:
            if warm_key in _CATALOGUE_WARM_DONE or warm_key in _CATALOGUE_WARM_INFLIGHT:
                return
            _CATALOGUE_WARM_INFLIGHT.add(warm_key)
    except Exception:
        return

    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        ctx = None
        add_script_run_ctx = None  # type: ignore[assignment]

    def _worker() -> None:
        ok = False
        try:
            if ctx is not None and add_script_run_ctx is not None:
                add_script_run_ctx(threading.current_thread(), ctx)
            # Populate the same @st.cache_data the Catalogue page reads.
            _fn336_cached_catalogue_payload(warm_df, True, config_sig)
            ok = True
        except Exception:
            # Best-effort: Catalogue still builds on demand. Leave DONE unset
            # so the next app run can retry.
            pass
        finally:
            with _CATALOGUE_WARM_LOCK:
                _CATALOGUE_WARM_INFLIGHT.discard(warm_key)
                if ok:
                    _CATALOGUE_WARM_DONE.add(warm_key)

    try:
        threading.Thread(
            target=_worker,
            name="eetra-catalogue-warmup",
            daemon=True,
        ).start()
    except Exception:
        with _CATALOGUE_WARM_LOCK:
            _CATALOGUE_WARM_INFLIGHT.discard(warm_key)
