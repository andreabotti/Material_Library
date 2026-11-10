"""
pages/2_Catalogue.py — Product catalogue

Control hierarchy (deliberate):
  1. Sidebar        — global dataset filters. Apply to every page in the app.
  2. Above the tabs — optional catalogue scope controls (search, tag filter,
                      display settings). Hidden when catalogue.page_controls.show
                      is false in theme.json — the JS Cards view owns those.
  3. Inside a view  — view-local refinements only (the JS card browser's own
                      filter bar; product type / material are omitted there
                      because the sidebar owns those dimensions globally).

Tabs:
  Cards        — JS2 flip-card HTML component (catalogue_component_js2.html)
  Collections  — tag-based collections (pages/7_Collections.py, embedded)

The former "Grid & table" tab (native Streamlit cards / list + detail panel) is
retired — the JS2 Cards view is the only product browser. See the note above
`with tab_collections:` at the bottom for how to restore it.
"""

from libs.page_imports import *  # noqa: F401,F403
import libs.lib_ui as _lib_ui
from libs.lib_header import fn003a_page_header
from libs.lib_ui import (
    fn355_render_active_filters,
    fn356_empty_state,
    fn359_iframe_height,
)
import json
import re

from libs.lib_data import fn142a_is_usable_document_url as _epd_url_usable

try:
    from libs.lib_charts import fn217_match_cam_target as _fn217_match_cam_target
except Exception:
    _fn217_match_cam_target = None

try:
    from libs.lib_eco_data import fast_dumps as _fast_json_dumps
except Exception:
    _fast_json_dumps = lambda obj: json.dumps(obj, ensure_ascii=False)

# ── Pull shared data ──────────────────────────────────────────────────────
df_filtered = st.session_state.get("FILTERED_DATA", pd.DataFrame())
df_original = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())

if not st.session_state.get("df_filtered_ready"):
    fn356_empty_state(
        "Loading data…",
        hint="Give it a moment, or go back to Welcome and check the data source.",
    )
    st.stop()

# A__Map_yn filter — only show catalogue-listed items
if "A__Map_yn" in df_filtered.columns:
    df_catalog = df_filtered[
        df_filtered["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"
    ].copy()
else:
    df_catalog = df_filtered.copy()

# Tag-editor dialog — opened from JS flipcard via query param.
# Fallback note: if iframe->query-param roundtrip is blocked by browser/runtime,
# JS cards remain read-only for tags and editing is done in the Streamlit tab.
_pending_tag_edit = st.query_params.get("edit_tag_for")
if _pending_tag_edit:
    @st.dialog("Edit tags")
    def _tag_editor_dialog(_eid: str):
        from libs.lib_ui import fn329a_render_tag_popover
        fn329a_render_tag_popover(_eid, embedded=True, key_prefix=f"dlg_tag_{_eid}")
        if st.button("Done", key=f"_close_tag_dialog_{_eid}"):
            st.query_params.clear()
            st.rerun()
    _tag_editor_dialog(str(_pending_tag_edit))

if "SELECTED_PRODUCT" not in st.session_state:
    st.session_state["SELECTED_PRODUCT"] = None

def _normalized_product_types(df: pd.DataFrame) -> list[str]:
    """Distinct normalized product types present in *df* (shared helper)."""
    if "D__ProductType_ENG" not in df.columns:
        return []
    out: list[str] = []
    for _v in df["D__ProductType_ENG"].dropna().astype(str).unique():
        _nv = fn315_normalize_product_type(_v)
        if _nv and _nv not in out:
            out.append(_nv)
    return out


def _single_or_mixed_product_type(df: pd.DataFrame, default: str = "default") -> str:
    _types = _normalized_product_types(df)
    if len(_types) == 1:
        return _types[0]
    return "Mixed" if _types else default


# ── Arrange-by widget options (left column) ───────────────────────────────
_arrange_product_type = _single_or_mixed_product_type(df_catalog)

_pt_low = str(_arrange_product_type).lower()
if "building boards" in _pt_low:
    _CAT_ARRANGE_OPTIONS = ["Thickness", "Manufacturer"]
elif "insulation" in _pt_low:
    _CAT_ARRANGE_OPTIONS = ["MaterialType", "Manufacturer"]
elif "binder" in _pt_low or "cement" in _pt_low:
    _CAT_ARRANGE_OPTIONS = ["D__EN197-1", "Manufacturer"]
elif "in situ" in _pt_low or "concrete" in _pt_low:
    _CAT_ARRANGE_OPTIONS = ["D__EN206", "Manufacturer"]
else:
    _CAT_ARRANGE_OPTIONS = ["Manufacturer"]
_CAT_ARRANGE_DEFAULT = _CAT_ARRANGE_OPTIONS[0]

# ── Sort: field (selectbox) + order (radio) — columns for each field ───────
_SORT_FIELD_COLUMNS: dict[str, str | list[str]] = {
    "Product Name": "A__ProductName",
    "Manufacturer": ["A__Manufacturer", "A__ProductName"],
    "EPD Number": "E__EPD_RegNumber",
    "GWP": "G__GWP_A1A3",
}
_SORT_ORDER_ASCENDING = "A-Z (low-high)"
_SORT_ORDER_DESCENDING = "Z-A (high-low)"


def _init_catalogue_widget_defaults() -> None:
    """Seed widget keys once; do not pass value=/index= on widgets when these are set."""
    st.session_state.setdefault("catalogue_detail_level", "Compact")
    if st.session_state.get("catalogue_detail_level") not in ("Compact", "Extended"):
        st.session_state["catalogue_detail_level"] = "Compact"
    st.session_state.setdefault("catalogue_streamlit_view_mode", "Grid")
    if st.session_state.get("catalogue_streamlit_view_mode") not in ("Grid", "List"):
        st.session_state["catalogue_streamlit_view_mode"] = "Grid"
    st.session_state.setdefault("catalogue_sort_field", "Product Name")
    if st.session_state.get("catalogue_sort_field") not in _SORT_FIELD_COLUMNS:
        st.session_state["catalogue_sort_field"] = "Product Name"
    st.session_state.setdefault("catalogue_sort_order", _SORT_ORDER_ASCENDING)
    if st.session_state.get("catalogue_sort_order") not in (
        _SORT_ORDER_ASCENDING,
        _SORT_ORDER_DESCENDING,
    ):
        st.session_state["catalogue_sort_order"] = _SORT_ORDER_ASCENDING
    st.session_state.setdefault("catalogue_arrange_by", _CAT_ARRANGE_DEFAULT)
    if st.session_state.get("catalogue_arrange_by") not in _CAT_ARRANGE_OPTIONS:
        st.session_state["catalogue_arrange_by"] = _CAT_ARRANGE_DEFAULT
    st.session_state.setdefault("selected_tag_filter", [])


def _catalogue_search_query() -> str:
    """Text from the catalogue search box (``catalogue_page_search`` widget key)."""
    return str(st.session_state.get("catalogue_page_search", "") or "").strip()


def _apply_catalogue_text_search(df: pd.DataFrame) -> pd.DataFrame:
    """Filter catalogue rows by the Streamlit-tab search box."""
    q = _catalogue_search_query()
    if not q:
        return df
    _q = q.lower()
    _mask = pd.Series(False, index=df.index)
    for _col in ("A__ProductName", "A__Manufacturer", "E__EPD_RegNumber"):
        if _col in df.columns:
            _mask |= df[_col].astype(str).str.lower().str.contains(_q, na=False)
    return df[_mask]


def _render_catalogue_search_input() -> None:
    """Catalogue text search — render once per run (Streamlit tab viz column)."""
    if "catalogue_page_search" not in st.session_state:
        _legacy = str(st.session_state.get("catalogue_search", "") or "").strip()
        if _legacy:
            st.session_state["catalogue_page_search"] = _legacy
    st.text_input(
        "Search",
        placeholder="Name, manufacturer, EPD…",
        key="catalogue_page_search",
        label_visibility="collapsed",
    )


def _render_display_settings(df_catalog: pd.DataFrame) -> None:
    """Everything that changes how the catalogue is *presented*, in one popover.

    Previously this lived in a sticky right-hand column **inside the Streamlit
    tab**, even though it also drove the JavaScript tab — which was the default
    tab. So the controls governing what you were looking at were on a different
    tab, invisible. It now sits above the tabs and applies to both views.

    The old "Select Display Parameters" nested popover is flattened into this
    one (Streamlit does not allow a popover inside a popover, and one level of
    disclosure is enough).
    """
    _init_catalogue_widget_defaults()
    # The "Grid & table layout" radio lived here; it only drove the retired
    # Grid & table tab, so it is gone. `catalogue_streamlit_view_mode` still
    # gets its default from _init_catalogue_widget_defaults() for any code that
    # reads it.
    # "Columns per row" was removed: the JS2 grid lays out its own columns from
    # its S/M/L/XL size buttons, so the slider changed nothing.
    detail_level = st.radio(
        label="Detail level",
        options=["Compact", "Extended"],
        horizontal=True,
        key="catalogue_detail_level",
        help="Default card face. You can still flip an individual card.",
    )

    _c_sort, _c_order, _c_arrange = st.columns([1.2, 1.4, 1.2], gap="medium")
    with _c_sort:
        st.selectbox("Sort by", list(_SORT_FIELD_COLUMNS.keys()), key="catalogue_sort_field")
    with _c_order:
        st.radio(
            "Order",
            [_SORT_ORDER_ASCENDING, _SORT_ORDER_DESCENDING],
            horizontal=False,
            key="catalogue_sort_order",
        )
    with _c_arrange:
        st.selectbox("Group by", options=_CAT_ARRANGE_OPTIONS, key="catalogue_arrange_by")

    st.divider()

    current_product_type = _single_or_mixed_product_type(df_catalog)
    _pt_key = fn316_make_session_key_fragment(
        current_product_type if current_product_type != "Mixed" else "default"
    )
    _session_key = (
        f"display_params_{_pt_key}_{detail_level}_{_lib_ui.DISPLAY_PARAMS_SESSION_VER}"
    )
    _available = (
        fn317_get_field_visibility("default", detail_level)
        if current_product_type == "Mixed"
        else fn317_get_field_visibility(current_product_type, detail_level)
    )
    _stored = st.session_state.get(_session_key)
    if _stored is None or set(_stored.keys()) != set(_available.keys()):
        st.session_state[_session_key] = _available.copy()
    _cur = st.session_state.get(_session_key, _available)
    st.markdown("**Parameters shown on each card**")
    st.caption(
        f"{current_product_type} · {detail_level} · "
        f"{sum(1 for v in _cur.values() if v)} of {len(_available)} shown"
    )
    _field_meta = (
        st.session_state.get("FIELD_META", {})
        if isinstance(st.session_state, dict)
        else {}
    )

    def _field_sort_key(k: str):
        try:
            return int(_field_meta.get(k, {}).get("order", 9999))
        except Exception:
            return 9999

    _params_ordered = sorted(_available.keys(), key=_field_sort_key)
    _updated = {}
    _param_cols = st.columns(2, gap="small")
    for _i, _p in enumerate(_params_ordered):
        _frag = f"param_{_pt_key}_{detail_level}_{_p}"
        with _param_cols[_i % 2]:
            _updated[_p] = st.checkbox(
                _p,
                value=st.session_state[_session_key].get(_p, _available[_p]),
                key=_frag,
            )
    st.session_state[_session_key] = _updated
    if st.button("Reset to defaults", key=f"reset_{_pt_key}_{detail_level}"):
        st.session_state[_session_key] = _available.copy()
        st.rerun()


def _render_tag_filter() -> None:
    """Tag filter — a filter, so it sits with search rather than in Display settings."""
    from libs.lib_tags import fn414_list_all_tags

    _all_tags_df = fn414_list_all_tags()
    _tag_options = _all_tags_df["tag_slug"].astype(str).tolist() if not _all_tags_df.empty else []
    _tag_labels = (
        {
            str(r["tag_slug"]): str(r["tag_label"])
            for _, r in _all_tags_df[["tag_slug", "tag_label"]].iterrows()
        }
        if not _all_tags_df.empty
        else {}
    )
    _tag_cur = [
        x for x in st.session_state.get("selected_tag_filter", []) if x in _tag_options
    ]
    if st.session_state.get("selected_tag_filter", []) != _tag_cur:
        st.session_state["selected_tag_filter"] = _tag_cur
    st.multiselect(
        "Filter by tag",
        options=_tag_options,
        format_func=lambda slug: _tag_labels.get(slug, slug),
        key="selected_tag_filter",
        label_visibility="collapsed",
        placeholder="Filter by tag…",
    )


def _render_catalogue_controls(df_catalog: pd.DataFrame) -> None:
    """The single control row above the tabs, plus the active-filters strip."""
    _c_search, _c_tags, _c_settings = st.columns([3, 2, 1.2], gap="medium",
                                                 vertical_alignment="center")
    with _c_search:
        _render_catalogue_search_input()
    with _c_tags:
        _render_tag_filter()
    with _c_settings:
        with st.popover("Display settings", width="stretch"):
            _render_display_settings(df_catalog)

    _extra = []
    _q = _catalogue_search_query()
    if _q:
        _extra.append(("search", _q))
    _tags = st.session_state.get("selected_tag_filter") or []
    if _tags:
        _extra.append(("tags", ", ".join(str(t) for t in _tags)))
    fn355_render_active_filters(
        _extra,
        key_prefix="catalogue",
        clear_keys=["catalogue_page_search", "selected_tag_filter"],
    )


def _warm_card_images(df_page: pd.DataFrame) -> None:
    """Pre-fetch card images for the rows about to be rendered.

    Warm-up used to run over the whole sorted result set on every rerun, which
    only worked because the app opened pre-filtered to one manufacturer. Now that
    the catalogue can legitimately show everything, it is scoped to the visible
    page — same benefit, bounded cost.
    """
    if "U__Img_URL" not in df_page.columns or df_page.empty:
        return
    try:
        _has_id = "0__EETRA_ID" in df_page.columns
        _has_name = "A__ProductName" in df_page.columns
        _warm_tasks: list[tuple] = []
        for _, _r in df_page.iterrows():
            u = _r.get("U__Img_URL")
            if u is None or str(u).strip() in ("", "-"):
                continue
            eid = str(_r.get("0__EETRA_ID", "")).strip() if _has_id else ""
            pname = str(_r.get("A__ProductName", "")).strip() if _has_name else ""
            _warm_tasks.append(
                (
                    str(u).strip(),
                    eid if eid and eid != "-" else None,
                    pname if pname and pname != "-" else None,
                )
            )
        if not _warm_tasks:
            return
        with _cf.ThreadPoolExecutor(max_workers=8) as _ex:
            _futs = [
                _ex.submit(
                    fn110_cached_fetch_image, u, "catalogue",
                    eetra_id=eid, product_name=pname,
                )
                for u, eid, pname in _warm_tasks
            ]
            for _f in _futs:
                try:
                    _f.result(timeout=10)
                except Exception:
                    pass
    except Exception:
        pass


def _finalize_catalogue_display_df(
    df_catalog: pd.DataFrame,
    *,
    apply_tag_filter: bool = True,
) -> pd.DataFrame:
    """Sort, arrange and snapshot the display frame for both catalogue views."""
    _selected_tag_filter = st.session_state.get("selected_tag_filter", []) or []
    if apply_tag_filter and _selected_tag_filter:
        from libs.lib_tags import fn408_get_products_for_tag

        _tagged: list[str] = []
        for _slug in _selected_tag_filter:
            _tagged.extend(fn408_get_products_for_tag(_slug))
        _tagged_set = set(_tagged)
        if "0__EETRA_ID" in df_catalog.columns:
            df_catalog = df_catalog[df_catalog["0__EETRA_ID"].astype(str).isin(_tagged_set)]
        else:
            df_catalog = df_catalog.iloc[0:0]

    sort_field = st.session_state.get("catalogue_sort_field", "Product Name")
    sort_order = st.session_state.get("catalogue_sort_order", _SORT_ORDER_ASCENDING)
    sort_col = _SORT_FIELD_COLUMNS[sort_field]
    ascending = sort_order == _SORT_ORDER_ASCENDING
    if isinstance(sort_col, list):
        df_display = df_catalog.copy().sort_values(by=sort_col, ascending=ascending)
    elif sort_col in df_catalog.columns:
        df_display = df_catalog.copy()
        if sort_col in ("P__Mass_kgm3", "G__GWP_A1A3"):
            df_display[sort_col] = pd.to_numeric(df_display[sort_col], errors="coerce")
        df_display = df_display.sort_values(by=sort_col, ascending=ascending)
    else:
        df_display = df_catalog.copy()

    _arrange_by = st.session_state.get("catalogue_arrange_by", _CAT_ARRANGE_DEFAULT)
    if _arrange_by == "Thickness":
        df_display = df_display.copy()
        df_display["__ARR_TV"] = df_display.apply(fn332_extract_thickness_value, axis=1)
        df_display["__ARR_TV"] = df_display["__ARR_TV"].apply(
            lambda v: 15.0 if abs(v - 15.5) < 1e-9 else v
        )
        df_display = df_display.sort_values("__ARR_TV", kind="mergesort")
        df_display.drop(columns=["__ARR_TV"], inplace=True, errors="ignore")
    elif _arrange_by == "MaterialType" and "D__MaterialType_ENG" in df_display.columns:
        df_display = df_display.sort_values("D__MaterialType_ENG", kind="mergesort")
    elif _arrange_by == "D__EN197-1" and "D__EN197-1" in df_display.columns:
        df_display = df_display.sort_values("D__EN197-1", kind="mergesort")
    elif _arrange_by == "D__EN206":
        if "D__EN206" in df_display.columns or "A__ProductName" in df_display.columns:
            df_display = df_display.copy()
            df_display["__ARR_RC"] = df_display.apply(fn330_extract_resistance_class, axis=1)
            df_display["__ARR_RC_SORT"] = df_display["__ARR_RC"].apply(fn331_resistance_sort_key)
            df_display = df_display.sort_values("__ARR_RC_SORT", kind="mergesort")
            df_display.drop(columns=["__ARR_RC", "__ARR_RC_SORT"], inplace=True, errors="ignore")
    elif _arrange_by == "Manufacturer" and "A__Manufacturer" in df_display.columns:
        df_display = df_display.sort_values("A__Manufacturer", kind="mergesort")

    st.session_state["_catalogue_grid_df"] = df_display
    _gwp_ranges: dict = {}
    if "G__GWP_A1A3" in df_display.columns and "D__ProductType_ENG" in df_display.columns:
        for _ptype, _grp in df_display.groupby("D__ProductType_ENG"):
            _vals = pd.to_numeric(_grp["G__GWP_A1A3"], errors="coerce").dropna()
            if len(_vals) > 1:
                _gwp_ranges[str(_ptype)] = {"min": float(_vals.min()), "max": float(_vals.max())}
    st.session_state["_catalogue_gwp_ranges"] = _gwp_ranges
    return df_display


_init_catalogue_widget_defaults()


# Page title: the shared app header (fn003). This page used to hand-roll an
# <h3 class="eetra-catalogue-title-h3"> with `margin:-34px` and an invalid
# `padding-top:-0.5rem` rule to fight the header spacing; that style is now the
# app-wide page-title style in theme.json → chrome.page_title, so every page
# matches this one instead of the other way round.
_cat_layout_css = f"""
<style>
/* Group headings (##### …) in the Streamlit catalogue grid — spacing from theme/aux config. */
div[data-testid="stAppViewContainer"] [data-testid="stMain"] .block-container:has(.eetra-catalogue-page) h5{{
  margin-top: {_lib_ui.CATALOGUE_GROUP_TITLE_SPACING_TOP_PX}px !important;
  margin-bottom: {_lib_ui.CATALOGUE_GROUP_TITLE_SPACING_BOTTOM_PX}px !important;
}}
</style>
<div class="eetra-catalogue-page"></div>
"""
st.markdown(_cat_layout_css, unsafe_allow_html=True)

fn003a_page_header("Product Catalogue")

# The old Streamlit card grid (_streamlit_catalogue_grid), its JS2 data builder
# (_build_js2_materials, _inject_js2_data, _js2_* helpers) and the hidden legacy
# flip-card tab (_render_catalogue_old_js_tab) were removed on 2026-10-03: nothing
# called them. The originals are in _archive_2026-10-03_pre_medium_small/pages/.


# ── Controls first: they govern every view, so they cannot live in one tab ──
if _lib_ui.CATALOGUE_PAGE_CONTROLS_SHOW:
    _render_catalogue_controls(df_catalog)
    _df_for_display = _apply_catalogue_text_search(df_catalog)
    _apply_tag_filter = True
else:
    _df_for_display = df_catalog
    _apply_tag_filter = False

df_display = _finalize_catalogue_display_df(
    _df_for_display,
    apply_tag_filter=_apply_tag_filter,
)

if df_display.empty:
    fn356_empty_state(
        "No products match the current filters.",
        kind="empty",
        hint="Clear a sidebar filter or refine in the catalogue view below.",
    )

# ── Cards view — no tab wrapper ─────────────────────────────────────────────
# Previously "Cards" and "Collections" tabs, side by side. Collections is now
# its own top-level nav page (app.py) — temporary, pending a Revalu-style
# restructure — and Cards is the only view here, so a single-tab bar was just
# a second title-and-underline eating vertical space above the grid for no
# reason (it also used to be where "Grid & table" lived — see the removal
# note that used to sit here; that native view is retired, JS2 Cards only).
_JS_IFRAME_HEIGHT = max(
    int(_lib_ui.CATALOGUE_STREAMLIT_GRID_HEIGHT_PX), fn359_iframe_height("catalogue_js")
)

from libs.lib_html import CATALOGUE_JS2_COMPONENT_PATH

_df_cards = df_display

# ── "📑 View documents" bridge ────────────────────────────────────────
# The card's button postMessages its EETRA_ID; libs/catalogue_bridge turns
# that into a normal rerun (no page reload → we stay on the Catalogue
# instead of bouncing to Welcome, which is what st.navigation does on any
# hard reload).
#
# Read BEFORE rendering the iframe: the documents now display in a side panel
# *inside* the component (a left-side extension of the detail card), so their
# bytes have to be injected with the rest of the component payload rather than
# rendered afterwards as an overlay.
from libs.lib_ui import (
    fn352_catalogue_bridge_action,
    fn353_catalogue_bridge_action_kind,
    fn357_build_doc_panel_payload,
)

_DOC_TARGET_KEY = "_catalogue_doc_target"
_DOC_RASTER_KEY = "_catalogue_doc_raster_kind"

if fn352_catalogue_bridge_action("eetra:closeDocuments") is not None:
    st.session_state.pop(_DOC_TARGET_KEY, None)
    st.session_state.pop(_DOC_RASTER_KEY, None)
_docs_eid_fresh = fn352_catalogue_bridge_action("eetra:viewDocuments")
if _docs_eid_fresh:
    st.session_state[_DOC_TARGET_KEY] = _docs_eid_fresh
    # Which document to render to page images this run, if the click was a
    # "Preview" rather than just opening the Documents list. Persisted for the
    # same reason the target id is: an unrelated rerun mustn't close the preview.
    st.session_state[_DOC_RASTER_KEY] = fn353_catalogue_bridge_action_kind(
        "eetra:viewDocuments"
    )

# Detail-panel "Edit item" → Developer Dashboard → Edit Existing Item.
# The full add/edit form is too large for the ~480px panel, so we deep-link
# into the same section the Developer left-nav already hosts, with this
# product pre-selected.
_edit_eid = fn352_catalogue_bridge_action("eetra:editItem")
if _edit_eid:
    from libs.lib_ui import fn353_is_admin as _fn353_is_admin
    if _fn353_is_admin():
        st.session_state["_pending_edit_eetra_id"] = _edit_eid
        st.session_state["dev_nav_section"] = "✏️ Edit Item"
        st.switch_page("pages/5_Developer.py")
    else:
        st.warning(
            "Sign in as **admin** to edit items in the Developer Dashboard.",
            icon="🔒",
        )

# Persisted so the panel survives unrelated reruns (a filter change, a resize)
# instead of snapping shut; the JS close button clears it via the bridge.
_docs_eid = str(st.session_state.get(_DOC_TARGET_KEY, "") or "")
_doc_payload = None
if _docs_eid:
    _docs_match = (
        df_catalog[df_catalog["0__EETRA_ID"].astype(str).str.strip() == _docs_eid]
        if "0__EETRA_ID" in df_catalog.columns
        else pd.DataFrame()
    )
    if _docs_match.empty:
        st.session_state.pop(_DOC_TARGET_KEY, None)
        _docs_eid = ""
    else:
        _docs_row = _docs_match.iloc[0]
        _doc_payload = fn357_build_doc_panel_payload(
            _docs_row,
            _docs_eid,
            str(_docs_row.get("A__ProductName", "") or ""),
            raster_kind=str(st.session_state.get(_DOC_RASTER_KEY, "") or ""),
        )

_open_product = st.query_params.get("open_product") or _docs_eid or None
# No progress bar here: the payload build is cached, and a bar created on this
# page cannot be driven from inside a cached function — Streamlit replays the
# element calls a cached function makes, and on a hit this block is long gone
# (CacheReplayClosureError). The cache decorator shows its own spinner on a
# miss, and a hit is fast enough to need nothing.
# Full listino table per priced product, opened as a popup from a card's list-price
# row. Built here (not inside the cached payload) because it is keyed on EETRA id
# and costs a dict lookup per row; empty when no price parquet is present.
try:
    from libs.lib_prices import fn512_price_tables_payload as _fn512_price_tables
    _price_tables = _fn512_price_tables(_df_cards)
except Exception:
    _price_tables = {}

fn336_render_catalogue_flipcard(
    _df_cards,
    cols=6,
    height=_JS_IFRAME_HEIGHT,
    _component_path=CATALOGUE_JS2_COMPONENT_PATH,
    open_product=_open_product,
    doc_preview=_doc_payload,
    price_tables=_price_tables,
)
