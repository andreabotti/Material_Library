"""
pages/3_Charts.py  —  Box chart and Bar chart with Plotly dropdown slicing
Hybrid pattern: Streamlit handles all interactive widgets and Plotly renders
charts. An HTML filter summary panel is injected at top.
"""
# ── Shared imports ──────────────────────────────────────────────────────────
from libs.page_imports import *  # noqa: F401,F403
from libs.lib_header import fn003a_page_header
from libs.lib_i18n import fn711_t_page as _t_page, fn714_tu as _tu
from libs.lib_ui import (
    fn346_default_value_column_index,
    fn347_filter_value_columns_by_product_type,
    fn355_render_active_filters,
    fn356_empty_state,
)
import html as _html
import json

import libs.lib_charts as _lib_charts

# Chart Engine label shortened; migrate any persisted "ECharts JS" session values.
for _eng_key in ("box_engine", "corr_engine", "strip_engine"):
    if st.session_state.get(_eng_key) == "ECharts JS":
        st.session_state[_eng_key] = "ECharts"


def _chart_fmt_stat(val: float, display_label: str, original_col: str | None = None) -> str:
    """Format a numeric for summary lines; % when label has % or original column is a %-style field."""
    lab = display_label or ""
    oc = original_col or ""
    is_pct = "%" in lab or "_%" in oc or oc.endswith("%")
    if is_pct:
        return f"{val:.2f}%"
    return f"{val:.2f}"


def _chart_example_product(sub_df: pd.DataFrame, product_col: str = "A__ProductName") -> str:
    if product_col not in sub_df.columns:
        return "—"
    names = sub_df[product_col].dropna().astype(str).str.strip()
    names = names[names.ne("") & names.ne("-")]
    if names.empty:
        return "—"
    return sorted(names.unique(), key=str.lower)[0]


def _box_chart_groups_order(df: pd.DataFrame, group_col: str, value_col: str, sort_method: str):
    """Match ``fn201_plot_box_chart`` group ordering for narrative summaries."""
    _df = df.copy()
    _df[value_col] = pd.to_numeric(_df[value_col], errors="coerce")
    _df = _df.dropna(subset=[value_col])
    _su = _lib_charts._sorted_unique_categories
    if sort_method == "alphabetical":
        groups = _su(_df[group_col].unique())
    elif sort_method == "alphabetical_desc":
        groups = _su(_df[group_col].unique(), reverse=True)
    elif sort_method == "value_mean":
        group_means = _df.groupby(group_col)[value_col].mean().sort_values()
        groups = group_means.index.tolist()
    elif sort_method == "value_median":
        group_medians = _df.groupby(group_col)[value_col].median().sort_values()
        groups = group_medians.index.tolist()
    else:
        groups = list(_df[group_col].unique())
    return _df, groups


def _trace_summary_table_one_metric(
    df: pd.DataFrame,
    categories: list,
    category_col: str,
    value_col: str,
    value_label: str,
    *,
    product_col: str = "A__ProductName",
) -> pd.DataFrame | None:
    """One row per category: example product and median only."""
    rows = []
    _df = df.copy()
    _df[value_col] = pd.to_numeric(_df[value_col], errors="coerce")
    _df = _df.dropna(subset=[value_col])
    for cat in categories:
        sub = _df[_df[category_col] == cat]
        if sub.empty:
            continue
        med = float(sub[value_col].median())
        ex = _chart_example_product(sub, product_col)
        rows.append({
            "Category": cat,
            "Example": ex,
            value_label: _chart_fmt_stat(med, value_label, value_col),
        })
    return pd.DataFrame(rows) if rows else None


def _trace_summary_table_xy(
    df: pd.DataFrame,
    categories: list,
    color_col: str,
    x_col: str,
    y_col: str,
    x_label: str,
    y_label: str,
    *,
    product_col: str = "A__ProductName",
) -> pd.DataFrame | None:
    """One row per colour category: example product and median x/y only."""
    rows = []
    _df = df.copy()
    _df[x_col] = pd.to_numeric(_df[x_col], errors="coerce")
    _df[y_col] = pd.to_numeric(_df[y_col], errors="coerce")
    _df = _df.dropna(subset=[x_col, y_col])
    for cat in categories:
        sub = _df[_df[color_col].fillna("(blank)").astype(str) == str(cat)]
        if sub.empty:
            continue
        mx = float(sub[x_col].median())
        my = float(sub[y_col].median())
        ex = _chart_example_product(sub, product_col)
        rows.append({
            "Category": cat,
            "Example": ex,
            x_label: _chart_fmt_stat(mx, x_label, x_col),
            y_label: _chart_fmt_stat(my, y_label, y_col),
        })
    return pd.DataFrame(rows) if rows else None


def _dismiss_strip_fullscreen() -> None:
    st.session_state["strip_fs_open"] = False


@st.dialog("Strip Chart", width="large", on_dismiss=_dismiss_strip_fullscreen)
def _strip_chart_fullscreen_dialog(payload: dict) -> None:
    """Wide overlay for strip chart (Plotly / Altair / ECharts); chart sized to fit."""
    # large = 1280px max; nudge wider so dense strip labels still fit in-frame.
    st.markdown(
        "<style>"
        'div[data-testid="stDialog"] > div:first-child {'
        "width: min(96vw, 1520px) !important;"
        "max-width: min(96vw, 1520px) !important;"
        "}"
        'div[data-testid="stDialog"] [data-testid="stVerticalBlockBorderWrapper"],'
        'div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {'
        "max-height: 88vh; overflow: hidden;"
        "}"
        "</style>",
        unsafe_allow_html=True,
    )
    kind = payload.get("kind")
    # Keep height inside the dialog chrome so the whole chart is visible.
    ht = min(int(payload.get("height") or 640), 720)
    if kind == "plotly":
        import plotly.graph_objects as _go_fs

        _fig = _go_fs.Figure(payload["fig"])
        _fig.update_layout(height=ht, autosize=True)
        st.plotly_chart(
            _fig,
            width="stretch",
            key="strip_fs_plotly",
            config={"responsive": True, "displayModeBar": True},
        )
    elif kind == "altair":
        _chart = payload["chart"]
        try:
            _chart = _chart.properties(height=ht)
        except Exception:
            pass
        st.altair_chart(_chart, use_container_width=True)
    elif kind == "echarts":
        st.components.v1.html(payload["html"], height=ht + 8)


def _render_trace_summary_table(summary_df: pd.DataFrame, title: str) -> None:
    # Title and headers translate here rather than at the eight call sites; the
    # metric columns are already display labels, so they fall through unchanged.
    st.markdown(f"**{_tu(title)}**")
    cols = list(summary_df.columns)
    th_cells = "".join(
        f'<th scope="col">{_html.escape(_tu(str(c)))}</th>' for c in cols
    )
    body_rows = []
    for _, row in summary_df.iterrows():
        cells = "".join(
            f"<td>{_html.escape(str(row[c]))}</td>" for c in cols
        )
        body_rows.append(f"<tr>{cells}</tr>")
    table_html = (
        "<style>"
        ".chart-trace-summary { border-collapse: collapse; width: 100%; "
        "border: none; background: transparent; font-size: 0.875rem; }"
        ".chart-trace-summary th, .chart-trace-summary td { "
        "border: none !important; background: transparent !important; "
        "box-shadow: none !important; "
        "padding: 0.2rem 1.5rem 0.2rem 0; text-align: left; vertical-align: top; }"
        ".chart-trace-summary th { font-weight: 600; }"
        ".chart-trace-summary tr { border: none !important; background: transparent !important; }"
        "</style>"
        f'<table class="chart-trace-summary"><thead><tr>{th_cells}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )
    st.markdown(table_html, unsafe_allow_html=True)


# ── Pull shared data from session state (written by app.py every run) ────
df_filtered  = st.session_state.get("FILTERED_DATA",  pd.DataFrame())
df_original  = st.session_state.get("ORIGINAL_DATA",  pd.DataFrame())

# Page header — same helper, style and spacing as every other page.
fn003a_page_header("Charts")

if st.session_state.get("df_filtered_ready", False):
    # Apply A__Map_yn filter: only show items with A__Map_yn == "Y"
    if "A__Map_yn" in df_filtered.columns:
        df_charts = df_filtered[df_filtered["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"].copy()
    else:
        df_charts = df_filtered.copy()

    # Fresh JSON read each run (module-level CHARTS_* are only set at import).
    _ch_dims = fn341_get_charts_dimensions()
    _col_disp = st.session_state.get("COLUMN_DISPLAY_LABELS") or {}

    def _dl(cleaned: str) -> str:
        return fn128b_display_label_for_cleaned(df_charts, cleaned, _col_disp)

    # ── Active filters ──────────────────────────────────────────────────
    # Shared chip strip (same component as the Catalogue). Replaces this page's
    # private 48 px iframe summary, which no other page had.
    fn355_render_active_filters(key_prefix="charts")

    # Chart tabs — plain labels, as everywhere else in the app.
    # Lazy tabs: only the selected chart is built on a rerun (previously all three
    # figures, plus three EPD-programme mini bars, were rebuilt on every widget
    # change in any one of them). fn353a keeps each hidden tab's settings alive.
    fn353a_keep_widget_state("box_", "bar_", "corr_", "strip_")
    box_chart_tab, bar_chart_tab, corr_chart_tab = st.tabs(
        [_t_page(t) for t in ("Box chart", "Bar chart", "Scatter chart")],
        on_change="rerun", key="charts_active_tab",
    )
    
    # ================= BOX CHART TAB =================
    if box_chart_tab.open:
        with box_chart_tab:
            col_settings, _, col_chart = st.columns([10, 1, 50])
        with col_settings:

            # st.markdown("###### 📊 Chart Settings")
        
            # Get cleaned column names for display
            cleaned_cols = fn124_get_cleaned_column_names(df_charts)
            numeric_cols = fn127_get_cleaned_numeric_column_names(df_charts)

            # Apply chart widget column allowlists from JSON (original column names)
            chart_group_map = CHART_WIDGET_SETTINGS.get("group_by_columns", {})
            chart_value_map = CHART_WIDGET_SETTINGS.get("value_columns", {})
            cleaned_cols = fn340_filter_cleaned_by_allowed(df_charts, cleaned_cols, chart_group_map)
            numeric_cols = fn340_filter_cleaned_by_allowed(df_charts, numeric_cols, chart_value_map)

            # Exclude L_WmK, Thick_mm, Mass_kgm3, Mass_kgm2 from value column options
            _exclude_orig = {'P__L_WmK', 'E__L_WmK', 'P__Thick_mm', 'P__Mass_kgm3', 'P__Mass_kgm2'}
            numeric_cols = [c for c in numeric_cols if fn125_get_original_column_name(df_charts, c) not in _exclude_orig]

            # Hide type-specific bases (e.g. per-m2 R=1 outside Insulation) per JSON config.
            numeric_cols = fn347_filter_value_columns_by_product_type(df_charts, numeric_cols)

            # Find default indices for cleaned columns
            default_group_index = 0  # Default to 3rd column
            default_value_index = min(9, len(numeric_cols) - 1) if numeric_cols else 0

            # Adjust indices if they're out of range
            if default_group_index >= len(cleaned_cols):
                default_group_index = 0
            if default_value_index >= len(numeric_cols) or default_value_index < 0:
                default_value_index = 0

            # Per-product-type default from aux_02__chart_value_defaults.json (the FU/DU
            # column mixes kg/ton/m2/m3 across rows, so the right basis varies by type).
            default_value_index = fn346_default_value_column_index(
                df_charts, numeric_cols, fallback_index=default_value_index
            )

            group_col_cleaned = st.selectbox(
                _tu("Group By Column (categorical)"),
                cleaned_cols,
                index=default_group_index,
                format_func=_dl,
            )
            value_col_cleaned = st.selectbox(
                _tu("Value Column (numeric)"),
                numeric_cols,
                index=default_value_index,
                format_func=_dl,
            )
        
            # Convert back to original column names
            group_col = fn125_get_original_column_name(df_charts, group_col_cleaned)
            value_col = fn125_get_original_column_name(df_charts, value_col_cleaned)

        
            # Add sorting controls
            # st.markdown("###### 📈 Sort Y-Axis Labels")
            sort_options = {
                "No Sorting": "none",
                "Alphabetical (A-Z)": "alphabetical", 
                "Alphabetical (Z-A)": "alphabetical_desc",
                "By Value (Mean)": "value_mean",
                "By Value (Median)": "value_median"
            }
            sort_by = st.selectbox(_tu("Sort Y-Axis Labels by:"), list(sort_options.keys()), index=0, format_func=_tu)
            sort_method = sort_options[sort_by]

            showpoints = st.toggle(_tu("Show Data Points"), value=True)

            box_engine = st.radio(
                _tu("Chart Engine"),
                ["Plotly", "Altair", "ECharts"],
                index=0,
                horizontal=True,
                key="box_engine",
            )

            # ── Benchmark toggles (no section title / divider) ────────────────
            _box_is_rc  = _lib_charts.fn216_is_recycled_content_metric(value_col)
            _box_ice_fu = _lib_charts.fn223a_ice_benchmark_fu(value_col)
            show_cam_box = False
            show_ice_box = False
            if _box_is_rc or _box_ice_fu:
                st.markdown(
                    "<div style='height:0.85rem'></div>",
                    unsafe_allow_html=True,
                )
            if _box_is_rc:
                show_cam_box = st.checkbox(
                    _tu("CAM 2025 recycled-content targets"),
                    value=True,
                    key="box_show_cam",
                    help=_tu("Draw a dotted line at the CAM 2025 minimum recycled-content threshold for each material group"),
                )
            if _box_ice_fu:
                _box_ice_unit = {"kg": "kg CO₂e/kg", "m2": "kg CO₂e/m²", "m3": "kg CO₂e/m³"}[_box_ice_fu]
                show_ice_box = st.checkbox(
                    _tu("ICE DB GWP benchmarks"),
                    value=True,
                    key="box_show_ice",
                    help=_tu(
                        "Draw dashed lines at ICE DB V4.1 embodied carbon ({unit}). "
                        "For GWP A1–A3 per kg: one line per ICE material. "
                        "For per m² / m³: one median per ICE category.",
                        unit=_box_ice_unit,
                    ),
                )

            # Add cement type styling option (only when ProductType is "binder")
            use_cement_styling = False
            if 'A__ProductName' in df_charts.columns:
                # Check if ProductType is "binder"
                is_binder = False
                if 'D__ProductType_ENG' in df_charts.columns:
                    unique_product_types = df_charts['D__ProductType_ENG'].dropna().unique()
                    is_binder = 'Binder' in unique_product_types
            
                if is_binder:
                    use_cement_styling = st.toggle(
                        _tu("Style by Cement Type"),
                        value=False, 
                        help=_tu("Color and shape markers based on UNI EN 197-1 cement classification from product names (available only for Binder products)")
                    )
                
                    # Show note about legend location if styling is enabled
                    # Hidden per user request - legend is visible in chart
                    # if use_cement_styling:
                    #     st.info("🏗️ **Cement Type Legend**: The legend is displayed inside the chart on the top-left corner.")

            show_logos = False  # Logo display removed per user request

            _box_prog_fig = _lib_charts.fn228_epd_programme_mini_bar(df_charts)
            if _box_prog_fig is not None:
                fn303_custom_hr()
                st.caption(_tu("EPD programme"))
                st.plotly_chart(_box_prog_fig, use_container_width=True, config={"displayModeBar": False}, key="box_epd_programme_mini_bar")
            fn303_custom_hr()

        with col_chart:
            # Filter summary displayed via HTML component above

            _df_box, _box_groups = _box_chart_groups_order(df_charts, group_col, value_col, sort_method)
            _box_ice_benchmarks = []
            if show_ice_box and _box_ice_fu:
                _box_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_charts)
                _box_ice_benchmarks = _lib_charts.fn224_get_ice_benchmarks(
                    _box_ice_cats, fu=_box_ice_fu,
                )
            _box_x_disp = _dl(value_col_cleaned)
            _box_y_disp = _dl(group_col_cleaned)
            _box_ht = _ch_dims["box_height_px"]
            # Insulation + Material Type → pale yellow / warm gray palette (also drives ICE line colours).
            _box_ins_mat = (
                _lib_charts._df_is_insulation_products(df_charts)
                and group_col == "D__MaterialType_ENG"
            )
            _box_cmap = _lib_charts.fn231_insulation_material_color_map(
                df_charts, group_col, CUSTOM_COLOR_MAP,
            )

            # ── Plotly ────────────────────────────────────────────────────────
            if box_engine == "Plotly":
                chart_settings = {
                    "width": 1000,
                    "height": _box_ht,
                    "font_family": _ch_dims["chart_font_family"],
                    "font_size": _ch_dims["chart_font_size"],
                    "bar_color": 'grey',
                    "bar_opacity": 0.7,
                    "title": '',
                    "title_font_size": _ch_dims["chart_title_font_size"],
                    "xaxis_title": _box_x_disp,
                    "yaxis_title": _box_y_disp,
                    "margin": BOX_CHART_MARGINS,
                    "showpoints": showpoints,
                }

                cement_marker_styles = None
                if use_cement_styling and 'A__ProductName' in df_charts.columns:
                    cement_marker_styles = fn204_get_cement_marker_styles(df_charts, 'A__ProductName')

                fig = fn201_plot_box_chart(
                    df_charts, group_col, value_col, settings=chart_settings, color_map=_box_cmap, sort_by=sort_method,
                    show_logos=show_logos, cement_marker_styles=cement_marker_styles, gwp_visualization='lines',
                    should_add_gwp_visualization=fn209_is_in_situ_selected())
                if show_cam_box:
                    fig = _lib_charts.fn218_add_cam_targets_to_box_chart(fig, _box_groups, value_col)
                if _box_ice_benchmarks:
                    fig = _lib_charts.fn225_add_ice_benchmarks_to_chart(fig, _box_ice_benchmarks)
                st.plotly_chart(fig, width='stretch', key="box_chart")

            # ── Altair ────────────────────────────────────────────────────────
            elif box_engine == "Altair":
                try:
                    import altair as alt  # noqa: F401
                except ImportError:
                    st.error("Altair is not installed. Run `pip install altair` to enable this view.")
                    st.stop()
                if use_cement_styling:
                    st.caption(_tu("Cement-type marker styling is available in the Plotly engine only."))
                _alt_cam = None
                # CAM ticks on Altair are per-group; reuse Plotly resolver when checked.
                if show_cam_box:
                    st.caption(_tu("CAM target ticks are shown in the Plotly engine; ICE lines are included below."))
                _box_alt = _lib_charts.fn229_plot_box_chart_altair(
                    df_charts,
                    group_col,
                    value_col,
                    groups=_box_groups,
                    showpoints=showpoints,
                    x_title=_box_x_disp,
                    y_title=_box_y_disp,
                    height=_box_ht,
                    ice_benchmarks=_box_ice_benchmarks or None,
                    cam_targets=_alt_cam,
                    color_map=_box_cmap if _box_ins_mat else None,
                )
                st.altair_chart(_box_alt, use_container_width=True)

            # ── ECharts ───────────────────────────────────────────────────────
            else:
                if use_cement_styling or show_cam_box:
                    st.caption(_tu(
                        "Cement-type styling and CAM target ticks are available in the Plotly engine; "
                        "ICE lines are included below."
                    ))
                _box_ec_html = _lib_charts.fn230_build_echarts_box_html(
                    df_charts,
                    group_col,
                    value_col,
                    groups=_box_groups,
                    showpoints=showpoints,
                    x_title=_box_x_disp,
                    y_title=_box_y_disp,
                    height=_box_ht,
                    ice_benchmarks=_box_ice_benchmarks or None,
                    color_map=_box_cmap if _box_ins_mat else None,
                )
                st.components.v1.html(_box_ec_html, height=_box_ht + 24)

            _box_summary = _trace_summary_table_one_metric(
                _df_box, _box_groups, group_col, value_col, _box_x_disp,
            )
            if _box_summary is not None:
                _render_trace_summary_table(_box_summary, "By group (median)")

            # Show GWP class legend if "In situ" is selected in any filter
            if fn209_is_in_situ_selected():
                st.markdown("---")
                fn210_display_gwp_class_legend()

    # ================= BAR CHART TAB =================
    if bar_chart_tab.open:
        with bar_chart_tab:
            # Detect in-situ view both from filters and from product types (for robustness)
            product_types_normalized = set()
            if 'D__ProductType_ENG' in df_charts.columns:
                raw_product_types = df_charts['D__ProductType_ENG'].dropna().unique().tolist()
                for raw_type in raw_product_types:
                    normalized_type = fn315_normalize_product_type(raw_type)
                    if normalized_type:
                        product_types_normalized.add(normalized_type)
            is_in_situ_view = (
                fn209_is_in_situ_selected()
                or (len(product_types_normalized) == 1 and any('in situ' in t.lower() for t in product_types_normalized))
            )

            col_settings_bar, _, col_chart_bar = st.columns([10, 1, 50])
        
            with col_settings_bar:
                # Get cleaned column names for display
                cleaned_cols = fn124_get_cleaned_column_names(df_charts)
                numeric_cols = fn127_get_cleaned_numeric_column_names(df_charts)

                chart_group_map = CHART_WIDGET_SETTINGS.get("group_by_columns", {})
                chart_value_map = CHART_WIDGET_SETTINGS.get("value_columns", {})
                chart_color_map = CHART_WIDGET_SETTINGS.get("color_by_columns", {})
                cleaned_cols = fn340_filter_cleaned_by_allowed(df_charts, cleaned_cols, chart_group_map)
                numeric_cols = fn340_filter_cleaned_by_allowed(df_charts, numeric_cols, chart_value_map)

                # Exclude L_WmK, Thick_mm, Mass_kgm3, Mass_kgm2 from value column options
                _exclude_orig = {'P__L_WmK', 'E__L_WmK', 'P__Thick_mm', 'P__Mass_kgm3', 'P__Mass_kgm2'}
                numeric_cols = [c for c in numeric_cols if fn125_get_original_column_name(df_charts, c) not in _exclude_orig]
                numeric_cols = fn347_filter_value_columns_by_product_type(df_charts, numeric_cols)

                default_value_index = min(9, len(numeric_cols) - 1) if numeric_cols else 0
                if default_value_index >= len(numeric_cols) or default_value_index < 0:
                    default_value_index = 0
                default_value_index = fn346_default_value_column_index(
                    df_charts, numeric_cols, fallback_index=default_value_index
                )

                # GWP visualization options (always show widget, but colored bands only when "In situ" is selected)
                gwp_help_bar = _tu(
                    "Bars: horizontal bars per product with GWP class boundary lines. "
                    "Circles: marker dots per product with GWP class color bands."
                    if fn209_is_in_situ_selected() else
                    "Bars: horizontal bars per product. Circles: marker dots per product."
                )
                gwp_visualization_bar = st.radio(
                    _tu("Chart Visualization Style"),
                    options=["Bars", "Circles"],
                    index=0,
                    horizontal=True,
                    format_func=_tu,
                    help=gwp_help_bar,
                    key="bar_gwp_viz",
                )

                value_col_cleaned_bar = st.selectbox(
                    _tu("Value Column (numeric)"),
                    numeric_cols,
                    index=default_value_index,
                    key="bar_value_col",
                    format_func=_dl,
                )
            
                # Convert back to original column names
                value_col_bar = fn125_get_original_column_name(df_charts, value_col_cleaned_bar)
            
                # Color coding column selection (similar to Group by Column)
                color_col_cleaned = st.selectbox(
                    _tu("Color By Column (categorical)"),
                    fn340_filter_cleaned_by_allowed(df_charts, cleaned_cols, chart_color_map),
                    index=2,
                    key="bar_color_col",
                    format_func=_dl,
                )
                color_col_bar = fn125_get_original_column_name(df_charts, color_col_cleaned)
                _bar_cmap = _lib_charts.fn231_insulation_material_color_map(
                    df_charts, color_col_bar, CUSTOM_COLOR_MAP,
                )

                # Aggregate duplicates toggle
                aggregate_by_base = False
                if 'A__ProductName' in df_charts.columns:
                    # Disable aggregation when a dropdown slice dimension is active:
                    # aggregating would collapse the per-class/per-thickness/per-material rows
                    # that the embedded dropdown needs in order to filter the chart.
                    _agg_disabled_for_en206    = fn209_is_in_situ_selected() and 'D__EN206' in df_charts.columns
                    _agg_disabled_for_boards   = fn323_is_building_boards_selected()
                    _agg_disabled_for_insul    = any(
                        'insulation' in str(v).lower()
                        for v in df_charts.get('D__ProductType_ENG', pd.Series()).dropna().unique()
                    ) if 'D__ProductType_ENG' in df_charts.columns else False
                    disable_agg_for_dropdown = _agg_disabled_for_en206 or _agg_disabled_for_boards or _agg_disabled_for_insul
                    default_agg_value = not disable_agg_for_dropdown
                    aggregate_by_base = st.toggle(
                        _tu("Aggregate duplicates by base product"),
                        value=default_agg_value,
                        help=_tu("Average values for the same product (text before ' | ') produced in multiple plants"),
                        key="bar_aggregate_duplicates",
                        disabled=disable_agg_for_dropdown
                    )
            
                # Add sorting controls for bar chart
                sort_options_bar = {
                    "No Sorting": "none",
                    "Alphabetical (A-Z)": "alphabetical", 
                    "Alphabetical (Z-A)": "alphabetical_desc",
                    "By Value (High to Low)": "value_desc",
                    "By Value (Low to High)": "value_asc"
                }
                sort_by_bar = st.selectbox(_tu("Sort Products by:"), list(sort_options_bar.keys()), index=3, key="bar_sort", format_func=_tu)
                sort_method_bar = sort_options_bar[sort_by_bar]

                # ── Benchmark toggles (no section title / divider) ────────────
                _bar_is_rc  = _lib_charts.fn216_is_recycled_content_metric(value_col_bar)
                _bar_ice_fu = _lib_charts.fn223a_ice_benchmark_fu(value_col_bar)
                show_cam_bar = False
                show_ice_bar = False
                if _bar_is_rc or _bar_ice_fu:
                    st.markdown(
                        "<div style='height:0.85rem'></div>",
                        unsafe_allow_html=True,
                    )
                if _bar_is_rc:
                    show_cam_bar = st.checkbox(
                        _tu("CAM 2025 recycled-content targets"),
                        value=True,
                        key="bar_show_cam",
                        help=_tu("Draw a dotted line at the CAM 2025 minimum recycled-content threshold"),
                    )
                if _bar_ice_fu:
                    _bar_ice_unit = {"kg": "kg CO₂e/kg", "m2": "kg CO₂e/m²", "m3": "kg CO₂e/m³"}[_bar_ice_fu]
                    show_ice_bar = st.checkbox(
                        _tu("ICE DB GWP benchmarks"),
                        value=True,
                        key="bar_show_ice",
                        help=_tu(
                            "Draw dashed lines at ICE DB V4.1 embodied carbon ({unit}). "
                            "For GWP A1–A3 per kg: one line per ICE material. "
                            "For per m² / m³: one median per ICE category.",
                            unit=_bar_ice_unit,
                        ),
                    )

                _bar_prog_fig = _lib_charts.fn228_epd_programme_mini_bar(df_charts)
                if _bar_prog_fig is not None:
                    fn303_custom_hr()
                    st.caption(_tu("EPD programme"))
                    st.plotly_chart(_bar_prog_fig, use_container_width=True, config={"displayModeBar": False}, key="bar_epd_programme_mini_bar")
                fn303_custom_hr()

            with col_chart_bar:
                df_bar = df_charts.copy()
                df_bar[value_col_bar] = pd.to_numeric(df_bar[value_col_bar], errors='coerce')
                df_bar_numeric = df_bar.dropna(subset=[value_col_bar]).copy()

                if df_bar_numeric.empty:
                    st.warning(_tu("No data available for the selected value column after removing empty values."))
                    st.stop()

                # Aggregate duplicates across plants by base product name if enabled
                if 'A__ProductName' in df_bar_numeric.columns:
                    try:
                        if 'aggregate_by_base' in locals() and aggregate_by_base:
                            carry_cols = []
                            if color_col_bar in df_bar_numeric.columns:
                                carry_cols.append(color_col_bar)
                            if 'A__Manufacturer' in df_bar_numeric.columns and 'A__Manufacturer' not in carry_cols:
                                carry_cols.append('A__Manufacturer')
                            # Preserve dimension columns used by the embedded dropdown
                            # EN206 (In situ), thickness cols (Building boards), MaterialType (Insulation)
                            _DROPDOWN_DIM_COLS = [
                                'D__EN206',
                                'D__MaterialType_ENG',
                                'P__Thick_mm', 'P__Thickness_mm', 'B__Thickness_mm',
                                'D__Thickness_mm', 'A__Thickness_mm',
                            ]
                            for _dc in _DROPDOWN_DIM_COLS:
                                if _dc in df_bar_numeric.columns and _dc not in carry_cols:
                                    carry_cols.append(_dc)
                            df_bar_numeric = fn120_aggregate_value_by_base_product(
                                df_bar_numeric, value_col_bar, product_col='A__ProductName', carry_cols=carry_cols
                            )
                            st.caption(_tu("Averaging duplicates by base product name (before ' | ')."))
                    except Exception as _agg_err:
                        # Fail-safe: keep original data
                        pass
            # Filter summary displayed via HTML component above

                margins_bar = BAR_CHART_MARGINS

                # Create bar chart (with optional EN206 slicing for In situ products)
                gwp_viz_param = 'bands' if gwp_visualization_bar == 'Circles' else 'lines'
                should_add_gwp_visualization = fn209_is_in_situ_selected()

                def calc_chart_height(num_rows: int) -> int:
                    """
                    Bar chart height from number of y-axis rows (one horizontal bar per product).
                    Caps come from ``aux_01__catalogue_layout.json`` → ``charts`` (``bar_chart_line_height_px``,
                    ``bar_chart_max_rows``) so thickness slices with many products stay readable.
                    """
                    if not num_rows:
                        num_rows = 1
                    _line = _ch_dims["bar_line_height_px"]
                    _max_h = _ch_dims["bar_max_height_px"]
                    padding = 80 if num_rows <= 3 else BAR_CHART_HEIGHT_PADDING_PX
                    if num_rows > 35:
                        padding += 100
                    calculated_height = (num_rows * _line) + padding
                    h = max(BAR_CHART_HEIGHT_MIN_PX, min(_max_h, calculated_height))
                    return max(120, int(round(h * _ch_dims["bar_height_scale"])))

                def extract_categories_from_fig(fig):
                    # fn212 pins the product order on the axis (its traces are one
                    # per colour, so trace order no longer equals product order).
                    _arr = getattr(fig.layout.yaxis, "categoryarray", None)
                    if _arr is not None and len(_arr):
                        return list(_arr)
                    categories = []
                    for trace in fig.data:
                        y_vals = getattr(trace, "y", None)
                        if y_vals is None:
                            continue
                        for value in y_vals:
                            if value is None:
                                continue
                            if value not in categories:
                                categories.append(value)
                    return categories

                # ── Dropdown-slice detection ─────────────────────────────────────────────
                # Determine whether the current data warrants an embedded Plotly dropdown that
                # slices the chart by a categorical dimension.  Three product types get this:
                #
                #   • In situ Concrete  →  split by EN206 resistance class (D__EN206)
                #   • Building boards   →  split by Thickness (first populated thickness column)
                #   • Insulation        →  split by Material Type (D__MaterialType_ENG)
                #
                # The dropdown is only added when the split column has ≥2 distinct non-null
                # values so it is never shown with a pointless single-item menu.

                import plotly.graph_objects as go  # idempotent; already imported at module level

                # ── helper: resolve (split_col, slice_values, label_prefix) for current data ──
                _THICKNESS_COLS = [
                    'P__Thick_mm', 'P__Thickness_mm', 'B__Thickness_mm',
                    'D__Thickness_mm', 'A__Thickness_mm'
                ]

                def _resolve_split_dimension(df):
                    """
                    Inspect df and the active product-type filter to decide which column to use
                    for the embedded dropdown.  Returns (split_col, sorted_values, label_prefix)
                    or (None, [], '') when no split is appropriate.
                    """
                    # ── In situ Concrete: EN206 resistance class ──────────────────────────────
                    if fn209_is_in_situ_selected() and 'D__EN206' in df.columns:
                        df['D__EN206_Normalized'] = df['D__EN206'].apply(fn213_normalize_en206_class)
                        vals = sorted({
                            v for v in df['D__EN206_Normalized'].dropna().astype(str).str.strip()
                            if v and v.lower() != 'nan'
                        })
                        if len(vals) >= 2:
                            return 'D__EN206_Normalized', vals, 'EN206'

                    # ── Building boards: Thickness ────────────────────────────────────────────
                    if fn323_is_building_boards_selected():
                        thick_col = next((c for c in _THICKNESS_COLS if c in df.columns), None)
                        if thick_col:
                            # Normalise to a clean display string, e.g. "12 mm"
                            _NORM_COL = '__ThicknessDisplay'
                            def _fmt_thickness(v):
                                try:
                                    s = str(v).strip()
                                    if not s or s.lower() in ('nan', '-', ''):
                                        return 'Unspecified'
                                    # Strip trailing ".0" from whole numbers for cleaner labels
                                    num = float(re.sub(r'[^\d.]', '', s))
                                    return f"{int(num)} mm" if num == int(num) else f"{num} mm"
                                except Exception:
                                    return str(v).strip() or 'Unspecified'
                            df[_NORM_COL] = df[thick_col].apply(_fmt_thickness)
                            # Sort numerically: extract leading number for ordering
                            def _thick_sort_key(label):
                                try:
                                    return float(re.sub(r'[^\d.]', '', label))
                                except Exception:
                                    return float('inf')
                            vals = sorted(
                                {v for v in df[_NORM_COL].unique() if v and v != 'Unspecified'},
                                key=_thick_sort_key
                            )
                            # Append "Unspecified" at the end if present
                            if 'Unspecified' in df[_NORM_COL].values:
                                vals = vals + ['Unspecified']
                            if len(vals) >= 2:
                                return _NORM_COL, vals, 'Thickness'

                    # ── Insulation: Material Type ─────────────────────────────────────────────
                    # Detect insulation from the product-type filter column values in the df
                    _is_insulation = False
                    if 'D__ProductType_ENG' in df.columns:
                        _is_insulation = any(
                            'insulation' in str(v).lower()
                            for v in df['D__ProductType_ENG'].dropna().unique()
                        )
                    # Also check session-state filter widgets for robustness
                    if not _is_insulation:
                        for _i in range(1, 4):
                            if st.session_state.get(f'enable_filter_{_i}', False):
                                _fc = st.session_state.get(f'filter_col_{_i}', '')
                                _fv = str(st.session_state.get(f'filter_val_{_i}', ''))
                                if _fc == 'D__ProductType_ENG' and 'insulation' in _fv.lower():
                                    _is_insulation = True
                                    break
                    if _is_insulation and 'D__MaterialType_ENG' in df.columns:
                        vals = sorted({
                            v for v in df['D__MaterialType_ENG'].dropna().astype(str).str.strip()
                            if v and v.lower() not in ('nan', '-', '')
                        })
                        if len(vals) >= 2:
                            return 'D__MaterialType_ENG', vals, 'Material'

                    return None, [], ''

                split_col, split_values, split_label_prefix = _resolve_split_dimension(df_bar_numeric)

                # ── helper: build the combined Plotly figure with embedded dropdown ──────────
                def _build_dropdown_chart(df_all, split_col, split_values, split_label_prefix):
                    """
                    Build a single Plotly figure that contains an "All" view plus one view per
                    split_value, controlled by an embedded dropdown menu.
                    Returns the combined figure, or None if building fails.
                    """
                    figs_by_slice = []
                    trace_ranges = []
                    total_traces = 0
                    height_values = []

                    # "All" view
                    fig_all = fn212_create_bar_chart(
                        df_all, value_col_bar, color_col_bar, sort_method_bar,
                        _bar_cmap,
                        gwp_visualization=gwp_viz_param,
                        should_add_gwp_visualization=should_add_gwp_visualization,
                        margins=margins_bar, show_logos=False,
                        font_family=_ch_dims["chart_font_family"],
                        font_size=_ch_dims["chart_font_size"],
                        title_font_size=_ch_dims["chart_title_font_size"],
                        axis_title_font_size=_ch_dims["chart_axis_title_size"],
                        legend_font_size=_ch_dims["chart_legend_font_size"],
                        tick_font_size=_ch_dims["chart_tick_font_size"],
                    )
                    if show_cam_bar:
                        fig_all = _lib_charts.fn219_add_cam_target_to_bar_chart(
                            fig_all, df_all, value_col_bar, color_col_bar
                        )
                    if show_ice_bar and _bar_ice_fu:
                        _all_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_all)
                        _all_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_all_ice_cats, fu=_bar_ice_fu)
                        fig_all = _lib_charts.fn225_add_ice_benchmarks_to_chart(fig_all, _all_benchmarks)
                    h_all = calc_chart_height(len(df_all))
                    fig_all.update_layout(height=h_all)
                    cats_all = extract_categories_from_fig(fig_all)
                    figs_by_slice.append(("All", fig_all, cats_all))
                    trace_ranges.append((0, len(fig_all.data)))
                    total_traces = len(fig_all.data)
                    height_values.append(h_all)

                    # One view per slice value
                    for sv in split_values:
                        mask = df_all[split_col].astype(str).str.strip() == sv
                        df_sub = df_all[mask]
                        if df_sub.empty:
                            continue
                        fig_sub = fn212_create_bar_chart(
                            df_sub, value_col_bar, color_col_bar, sort_method_bar,
                            _bar_cmap,
                            gwp_visualization=gwp_viz_param,
                            should_add_gwp_visualization=should_add_gwp_visualization,
                            margins=margins_bar, show_logos=False,
                            font_family=_ch_dims["chart_font_family"],
                            font_size=_ch_dims["chart_font_size"],
                            title_font_size=_ch_dims["chart_title_font_size"],
                            axis_title_font_size=_ch_dims["chart_axis_title_size"],
                            legend_font_size=_ch_dims["chart_legend_font_size"],
                            tick_font_size=_ch_dims["chart_tick_font_size"],
                        )
                        h_sub = calc_chart_height(len(df_sub))
                        fig_sub.update_layout(height=h_sub)
                        if show_cam_bar:
                            fig_sub = _lib_charts.fn219_add_cam_target_to_bar_chart(
                                fig_sub, df_sub, value_col_bar, color_col_bar
                            )
                        if show_ice_bar and _bar_ice_fu:
                            _sub_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_sub)
                            _sub_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_sub_ice_cats, fu=_bar_ice_fu)
                            fig_sub = _lib_charts.fn225_add_ice_benchmarks_to_chart(fig_sub, _sub_benchmarks)
                        cats_sub = extract_categories_from_fig(fig_sub)
                        figs_by_slice.append((sv, fig_sub, cats_sub))
                        trace_ranges.append((total_traces, total_traces + len(fig_sub.data)))
                        total_traces += len(fig_sub.data)
                        height_values.append(h_sub)

                    if not figs_by_slice:
                        return None

                    # Merge all traces into a single figure
                    combined = go.Figure()
                    cats_per_view = []
                    for idx, (_, fig_v, cats_v) in enumerate(figs_by_slice):
                        cats_per_view.append(cats_v)
                        for trace in fig_v.data:
                            trace.visible = (idx == 0)
                            combined.add_trace(trace)

                    combined.update_layout(figs_by_slice[0][1].layout)
                    _raw_title = getattr(combined.layout.title, 'text', '') or ''
                    if isinstance(_raw_title, dict):
                        _raw_title = _raw_title.get('text', '')
                    default_title = _raw_title or "Bar Chart"
                    combined.update_layout(height=height_values[0])

                    if cats_per_view and cats_per_view[0]:
                        combined.update_layout(yaxis=dict(
                            categoryorder='array',
                            categoryarray=cats_per_view[0],
                            automargin=True,
                            range=[-0.5, max(len(cats_per_view[0]) - 0.5, 0.5)]
                        ))

                    # Dropdown buttons
                    total_n = len(combined.data)
                    buttons = []
                    for idx, (label, _, _) in enumerate(figs_by_slice):
                        vis = [False] * total_n
                        start, end = trace_ranges[idx]
                        for ti in range(start, end):
                            vis[ti] = True
                        suffix = "" if label == "All" else f" | {split_label_prefix}: {label}"
                        cat_args = {}
                        if idx < len(cats_per_view) and cats_per_view[idx]:
                            cat_args = {"yaxis": {
                                "categoryorder": "array",
                                "categoryarray": cats_per_view[idx],
                                "automargin": True,
                                "range": [-0.5, max(len(cats_per_view[idx]) - 0.5, 0.5)]
                            }}
                        buttons.append(dict(
                            label=label,
                            method="update",
                            args=[
                                {"visible": vis},
                                {
                                    "title": f"{default_title}{suffix}",
                                    "height": height_values[idx] if idx < len(height_values) else height_values[0],
                                    **cat_args
                                }
                            ]
                        ))

                    combined.update_layout(
                        updatemenus=[dict(
                            buttons=buttons,
                            direction="down",
                            showactive=True,
                            x=0.0, xanchor="left",
                            y=1.12, yanchor="top"
                        )],
                        title=default_title,
                        margin={**margins_bar, "t": max(margins_bar.get("t", 30), 60)}
                    )
                    return combined, default_title, split_label_prefix

                # ── Render ───────────────────────────────────────────────────────────────────
                if split_col is not None:
                    result = _build_dropdown_chart(df_bar_numeric, split_col, split_values, split_label_prefix)
                    if result:
                        combined_fig, _title, _prefix = result
                        st.plotly_chart(combined_fig, width='stretch', key="bar_dropdown_chart")
                        _caption_map = {
                            'EN206':     "Use the dropdown to filter by EN206 resistance class.",
                            'Thickness': "Use the dropdown to filter by product thickness.",
                            'Material':  "Use the dropdown to filter by material type.",
                        }
                        st.caption(_tu(_caption_map.get(_prefix, "Use the dropdown to filter the chart.")))
                    else:
                        st.warning(_tu("No data available to display."))
                else:
                    fig_bar = fn212_create_bar_chart(
                        df_bar_numeric,
                        value_col_bar,
                        color_col_bar,
                        sort_method_bar,
                        _bar_cmap,
                        gwp_visualization=gwp_viz_param,
                        should_add_gwp_visualization=should_add_gwp_visualization,
                        margins=margins_bar,
                        show_logos=False,
                        font_family=_ch_dims["chart_font_family"],
                        font_size=_ch_dims["chart_font_size"],
                        title_font_size=_ch_dims["chart_title_font_size"],
                        axis_title_font_size=_ch_dims["chart_axis_title_size"],
                        legend_font_size=_ch_dims["chart_legend_font_size"],
                        tick_font_size=_ch_dims["chart_tick_font_size"],
                    )
                    if show_cam_bar:
                        fig_bar = _lib_charts.fn219_add_cam_target_to_bar_chart(
                            fig_bar, df_bar_numeric, value_col_bar, color_col_bar
                        )
                    if show_ice_bar and _bar_ice_fu:
                        _bar_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_bar_numeric)
                        _bar_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_bar_ice_cats, fu=_bar_ice_fu)
                        fig_bar = _lib_charts.fn225_add_ice_benchmarks_to_chart(fig_bar, _bar_benchmarks)
                    fig_bar.update_layout(height=calc_chart_height(len(df_bar_numeric)))
                    st.plotly_chart(fig_bar, width='stretch', key="bar_chart")

                if _lib_charts.fn216_is_recycled_content_metric(value_col_bar) and show_cam_bar:
                    st.caption(
                        _tu("CAM 2025 dotted line: minimum recycled-content threshold for the material type(s) in view.")
                    )
                if show_ice_bar and _bar_ice_fu:
                    _bar_cap_unit = {"kg": "kg CO₂e/kg", "m2": "kg CO₂e/m²", "m3": "kg CO₂e/m³"}[_bar_ice_fu]
                    if _bar_ice_fu == "kg":
                        st.caption(_tu(
                            "ICE DB dashed lines: V4.1 embodied carbon ({unit}) — "
                            "one line per ICE material · Circular Ecology.",
                            unit=_bar_cap_unit,
                        ))
                    else:
                        st.caption(_tu(
                            "ICE DB dashed lines: V4.1 median embodied carbon ({unit}) "
                            "per material category · Circular Ecology.",
                            unit=_bar_cap_unit,
                        ))

                _bar_cats = _lib_charts._sorted_unique_categories(df_bar_numeric[color_col_bar].unique())
                _bar_summ = _trace_summary_table_one_metric(
                    df_bar_numeric,
                    list(_bar_cats),
                    color_col_bar,
                    value_col_bar,
                    _dl(value_col_cleaned_bar),
                )
                if _bar_summ is not None:
                    _render_trace_summary_table(_bar_summ, "By legend category (median)")

                # Show GWP class legend if "In situ" is selected in any filter
                if fn209_is_in_situ_selected():
                    st.markdown("---")
                    fn210_display_gwp_class_legend()

    # ================= SCATTER CHART TAB =================
    if corr_chart_tab.open:
        with corr_chart_tab:
            col_settings_corr, _, col_chart_corr = st.columns([10, 1, 50])

            with col_settings_corr:
                cleaned_cols_corr = fn124_get_cleaned_column_names(df_charts)
                numeric_cols_corr = fn127_get_cleaned_numeric_column_names(df_charts)

                _cg_map = CHART_WIDGET_SETTINGS.get("group_by_columns", {})
                _cv_map = CHART_WIDGET_SETTINGS.get("value_columns", {})
                _cc_map = CHART_WIDGET_SETTINGS.get("color_by_columns", {})

                cleaned_cols_corr = fn340_filter_cleaned_by_allowed(df_charts, cleaned_cols_corr, _cg_map)
                numeric_cols_corr = fn340_filter_cleaned_by_allowed(df_charts, numeric_cols_corr, _cv_map)

                _excl = {'P__L_WmK', 'E__L_WmK', 'P__Thick_mm', 'P__Mass_kgm3', 'P__Mass_kgm2'}
                numeric_cols_corr = [c for c in numeric_cols_corr
                                      if fn125_get_original_column_name(df_charts, c) not in _excl]
                numeric_cols_corr = fn347_filter_value_columns_by_product_type(df_charts, numeric_cols_corr)

                _color_cols_corr = fn340_filter_cleaned_by_allowed(df_charts, cleaned_cols_corr, _cc_map)

                def _idx(lst, orig_col):
                    """Return index of orig_col in a cleaned-name list, or 0."""
                    for i, c in enumerate(lst):
                        if fn125_get_original_column_name(df_charts, c) == orig_col:
                            return i
                    return 0

                # ── Chart type selector ───────────────────────────────────────
                scatter_type = st.radio(
                    _tu("Chart Type"),
                    ["Standard Scatter", "Strip Chart"],
                    index=0,
                    horizontal=True,
                    key="corr_scatter_type",
                    format_func=_tu,
                    help=_tu(
                        "**Standard Scatter**: X vs Y axis — explore correlations between two metrics. "
                        "**Strip Chart**: one vertical column of dots per material group — compare a "
                        "single metric across groups (replicates the EPD literature dot-plot style)."
                    ),
                )

                # ── Standard Scatter controls ─────────────────────────────────
                if scatter_type == "Standard Scatter":
                    x_col_cleaned_corr = st.selectbox(
                        _tu("X Axis — Value Column"),
                        numeric_cols_corr,
                        index=_idx(numeric_cols_corr, 'R__Rec_Reco_ByProd_%'),
                        key="corr_x_col",
                        format_func=_dl,
                    )
                    y_col_cleaned_corr = st.selectbox(
                        _tu("Y Axis — Value Column"),
                        numeric_cols_corr,
                        index=fn346_default_value_column_index(
                            df_charts,
                            numeric_cols_corr,
                            fallback_index=_idx(numeric_cols_corr, 'G__GWP_A1A3'),
                        ),
                        key="corr_y_col",
                        format_func=_dl,
                    )
                    color_col_cleaned_corr = st.selectbox(
                        _tu("Color By Column (categorical)"),
                        _color_cols_corr,
                        index=_idx(_color_cols_corr, 'A__Manufacturer'),
                        key="corr_color_col",
                        format_func=_dl,
                    )

                    x_col_corr     = fn125_get_original_column_name(df_charts, x_col_cleaned_corr)
                    y_col_corr     = fn125_get_original_column_name(df_charts, y_col_cleaned_corr)
                    color_col_corr = fn125_get_original_column_name(df_charts, color_col_cleaned_corr)

                    chart_engine_corr = st.radio(
                        _tu("Chart Engine"), ["Plotly", "Altair", "ECharts"],
                        index=0, horizontal=True, key="corr_engine",
                    )

                    # Benchmark toggles (no section title / divider)
                    _corr_x_is_rc  = _lib_charts.fn216_is_recycled_content_metric(x_col_corr)
                    _corr_ice_fu = _lib_charts.fn223a_ice_benchmark_fu(y_col_corr)
                    show_cam_corr = False
                    show_ice_corr = False
                    if _corr_x_is_rc or _corr_ice_fu:
                        st.markdown(
                            "<div style='height:0.85rem'></div>",
                            unsafe_allow_html=True,
                        )
                    if _corr_x_is_rc:
                        show_cam_corr = st.checkbox(
                            _tu("CAM 2025 RC target (X axis)"),
                            value=True,
                            key="corr_show_cam",
                            help=_tu("Draw a vertical dotted line at the CAM 2025 recycled-content threshold on the X axis"),
                        )
                    if _corr_ice_fu:
                        _corr_ice_unit = {"kg": "kg CO₂e/kg", "m2": "kg CO₂e/m²", "m3": "kg CO₂e/m³"}[_corr_ice_fu]
                        show_ice_corr = st.checkbox(
                            _tu("ICE DB GWP benchmarks (Y axis)"),
                            value=True,
                            key="corr_show_ice",
                            help=_tu(
                                "Draw horizontal dashed lines at ICE DB V4.1 embodied "
                                "carbon ({unit}). For GWP A1–A3 per kg: one line per ICE "
                                "material. For per m² / m³: one median per ICE category.",
                                unit=_corr_ice_unit,
                            ),
                        )

                # ── Strip Chart controls ──────────────────────────────────────
                else:
                    strip_group_cleaned = st.selectbox(
                        _tu("Group By Column (X axis)"),
                        cleaned_cols_corr,
                        index=_idx(cleaned_cols_corr, 'D__MaterialType_ENG'),
                        key="strip_group_col",
                        format_func=_dl,
                    )
                    strip_y_cleaned = st.selectbox(
                        _tu("Y Axis — Value Column"),
                        numeric_cols_corr,
                        index=fn346_default_value_column_index(
                            df_charts,
                            numeric_cols_corr,
                            fallback_index=_idx(numeric_cols_corr, 'G__GWP_A1A3'),
                        ),
                        key="strip_y_col",
                        format_func=_dl,
                    )
                    strip_color_cleaned = st.selectbox(
                        _tu("Color By Column (categorical)"),
                        ["— (color by group)"] + list(_color_cols_corr),
                        index=0,
                        key="strip_color_col",
                        format_func=lambda c: _tu("(color each group)") if c.startswith("—") else _dl(c),
                    )
                    strip_jitter = st.slider(
                        _tu("Jitter Width"),
                        min_value=0.0, max_value=0.8, value=0.35, step=0.05,
                        key="strip_jitter",
                        help=_tu("Horizontal spread of dots within each group column"),
                    )
                    strip_engine = st.radio(
                        _tu("Chart Engine"), ["Plotly", "Altair", "ECharts"],
                        index=0, horizontal=True, key="strip_engine",
                    )
                    strip_show_legend = st.toggle(
                        _tu("Show legend"),
                        value=True,
                        key="strip_show_legend",
                        help=_tu("Hide the legend to free horizontal space for the strip chart."),
                    )
                    # No widget key — only set a separate flag (button keys are read-only).
                    if st.button(
                        _tu("Enlarge to full screen"),
                        use_container_width=True,
                        help=_tu("Open the strip chart in a large overlay."),
                    ):
                        st.session_state["strip_fs_open"] = True

                    strip_group_col = fn125_get_original_column_name(df_charts, strip_group_cleaned)
                    strip_y_col     = fn125_get_original_column_name(df_charts, strip_y_cleaned)
                    strip_color_col = (
                        None if strip_color_cleaned.startswith("—")
                        else fn125_get_original_column_name(df_charts, strip_color_cleaned)
                    )

                    # Benchmark toggles (Y axis only; no section title / divider)
                    _strip_ice_fu = _lib_charts.fn223a_ice_benchmark_fu(strip_y_col)
                    show_ice_strip = False
                    if _strip_ice_fu:
                        st.markdown(
                            "<div style='height:0.85rem'></div>",
                            unsafe_allow_html=True,
                        )
                        _strip_ice_unit = {"kg": "kg CO₂e/kg", "m2": "kg CO₂e/m²", "m3": "kg CO₂e/m³"}[_strip_ice_fu]
                        show_ice_strip = st.checkbox(
                            _tu("ICE DB GWP benchmarks (Y axis)"),
                            value=True,
                            key="strip_show_ice",
                            help=_tu(
                                "Draw horizontal dashed lines at ICE DB V4.1 embodied "
                                "carbon ({unit}). For GWP A1–A3 per kg: one line per ICE "
                                "material. For per m² / m³: one median per ICE category.",
                                unit=_strip_ice_unit,
                            ),
                        )

                _corr_prog_fig = _lib_charts.fn228_epd_programme_mini_bar(df_charts)
                if _corr_prog_fig is not None:
                    fn303_custom_hr()
                    st.caption(_tu("EPD programme"))
                    st.plotly_chart(_corr_prog_fig, use_container_width=True, config={"displayModeBar": False}, key="corr_epd_programme_mini_bar")
                fn303_custom_hr()

            # ── Chart rendering ───────────────────────────────────────────────
            with col_chart_corr:

                # ── Standard Scatter rendering ────────────────────────────────
                if scatter_type == "Standard Scatter":
                    df_corr = df_charts.copy()
                    df_corr[x_col_corr] = pd.to_numeric(df_corr[x_col_corr], errors='coerce')
                    df_corr[y_col_corr] = pd.to_numeric(df_corr[y_col_corr], errors='coerce')
                    df_corr = df_corr.dropna(subset=[x_col_corr, y_col_corr])

                    if df_corr.empty:
                        st.warning(_tu("No data available for the selected columns after removing empty values."))
                    else:
                        _x_disp = _dl(x_col_cleaned_corr)
                        _y_disp = _dl(y_col_cleaned_corr)
                        _color_disp = _dl(color_col_cleaned_corr)
                        _categories_corr = (
                            df_corr[color_col_corr].fillna("(blank)").astype(str).unique().tolist()
                        )
                        _corr_cmap = _lib_charts.fn231_insulation_material_color_map(
                            df_corr, color_col_corr, CUSTOM_COLOR_MAP,
                        )
                        _fallback_palette = px.colors.qualitative.Set2
                        _color_seq_corr = [
                            _corr_cmap.get(c, _fallback_palette[i % len(_fallback_palette)])
                            for i, c in enumerate(_categories_corr)
                        ]

                        # ── Plotly ────────────────────────────────────────────
                        if chart_engine_corr == "Plotly":
                            fig_corr = go.Figure()
                            _has_name = 'A__ProductName' in df_corr.columns
                            for i, cat in enumerate(_categories_corr):
                                _mask = df_corr[color_col_corr].fillna("(blank)").astype(str) == cat
                                _sub  = df_corr[_mask]
                                fig_corr.add_trace(go.Scatter(
                                    x=_sub[x_col_corr],
                                    y=_sub[y_col_corr],
                                    mode='markers',
                                    name=cat,
                                    marker=dict(
                                        symbol='circle-open',
                                        size=9,
                                        color=_color_seq_corr[i],
                                        line=dict(width=1.8, color=_color_seq_corr[i]),
                                    ),
                                    text=_sub['A__ProductName'] if _has_name else None,
                                    hovertemplate=(
                                        "<b>%{text}</b><br>"
                                        + f"{_x_disp}: %{{x}}<br>"
                                        + f"{_y_disp}: %{{y}}"
                                        + "<extra></extra>"
                                    ) if _has_name else (
                                        f"{_x_disp}: %{{x}}<br>"
                                        + f"{_y_disp}: %{{y}}"
                                        + "<extra></extra>"
                                    ),
                                ))
                            fig_corr.update_layout(
                                xaxis_title=_x_disp,
                                yaxis_title=_y_disp,
                                height=_ch_dims["correlation_plotly_height_px"],
                                margin=BOX_CHART_MARGINS,
                                legend=dict(
                                    title=_color_disp,
                                    font=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_legend_font_size"],
                                    ),
                                ),
                                font=dict(
                                    family=_ch_dims["chart_font_family"],
                                    size=_ch_dims["chart_font_size"],
                                ),
                                xaxis=dict(
                                    title_font=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_axis_title_size"],
                                    ),
                                    tickfont=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_tick_font_size"],
                                    ),
                                    tickangle=_ch_dims.get("chart_tick_label_angle", 0),
                                ),
                                yaxis=dict(
                                    title_font=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_axis_title_size"],
                                    ),
                                    tickfont=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_tick_font_size"],
                                    ),
                                ),
                            )
                            if show_cam_corr:
                                _corr_cam_target = _lib_charts.fn220_resolve_cam_target_from_df(
                                    df_corr, color_col=color_col_corr
                                )
                                if _corr_cam_target is not None:
                                    _x_vals = pd.to_numeric(df_corr[x_col_corr], errors="coerce").dropna()
                                    _frac = bool(len(_x_vals) > 0 and float(_x_vals.max()) <= 1.5)
                                    _xt = (_corr_cam_target / 100.0) if _frac else _corr_cam_target
                                    fig_corr.add_vline(
                                        x=_xt, line_width=2, line_dash="dot",
                                        line_color="rgba(50,50,50,0.9)",
                                    )
                                    fig_corr.add_annotation(
                                        x=_xt, y=1.0, xref="x", yref="paper",
                                        text=f"CAM limit = {_corr_cam_target:.0f}%",
                                        showarrow=False, textangle=-90,
                                        yanchor="bottom", xanchor="left",
                                        font=dict(size=10, color="rgba(50,50,50,0.95)"),
                                        bgcolor="rgba(255,255,255,0.65)",
                                    )
                            if show_ice_corr and _corr_ice_fu:
                                _corr_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_corr)
                                _corr_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_corr_ice_cats, fu=_corr_ice_fu)
                                fig_corr = _lib_charts.fn226_add_ice_hlines_to_chart(fig_corr, _corr_benchmarks)
                            st.plotly_chart(fig_corr, width='stretch', key="corr_scatter_chart")
                            _corr_cats_order = _lib_charts._sorted_unique_categories(
                                df_corr[color_col_corr].fillna("(blank)").astype(str).unique()
                            )
                            _corr_summ = _trace_summary_table_xy(
                                df_corr, list(_corr_cats_order), color_col_corr,
                                x_col_corr, y_col_corr, _x_disp, _y_disp,
                            )
                            if _corr_summ is not None:
                                _render_trace_summary_table(
                                    _corr_summ, "By legend category (median X and median Y)"
                                )

                        # ── Altair ────────────────────────────────────────────
                        elif chart_engine_corr == "Altair":
                            try:
                                import altair as alt
                            except ImportError:
                                st.error("Altair is not installed. Run `pip install altair` to enable this view.")
                                st.stop()

                            _alt_cols = [x_col_corr, y_col_corr, color_col_corr]
                            if 'A__ProductName' in df_corr.columns:
                                _alt_cols.append('A__ProductName')
                            _df_alt = df_corr[_alt_cols].copy()
                            _df_alt[color_col_corr] = _df_alt[color_col_corr].fillna("(blank)").astype(str)

                            _color_scale_alt = alt.Scale(domain=_categories_corr, range=_color_seq_corr)
                            _tooltip_alt = (
                                [alt.Tooltip('A__ProductName:N', title='Product')]
                                if 'A__ProductName' in _df_alt.columns else []
                            ) + [
                                alt.Tooltip(f'{x_col_corr}:Q', title=_x_disp, format='.3f'),
                                alt.Tooltip(f'{y_col_corr}:Q', title=_y_disp, format='.3f'),
                                alt.Tooltip(f'{color_col_corr}:N', title=_color_disp),
                            ]
                            _base_alt = (
                                alt.Chart(_df_alt)
                                .mark_point(filled=False, opacity=0.85, size=65, strokeWidth=1.8)
                                .encode(
                                    x=alt.X(f'{x_col_corr}:Q', title=_x_disp),
                                    y=alt.Y(f'{y_col_corr}:Q', title=_y_disp),
                                    color=alt.Color(
                                        f'{color_col_corr}:N',
                                        title=_color_disp,
                                        scale=_color_scale_alt,
                                    ),
                                    tooltip=_tooltip_alt,
                                )
                                .properties(height=_ch_dims["correlation_altair_height_px"])
                            )
                            _layers_alt = [_base_alt]
                            if show_cam_corr:
                                _alt_cam = _lib_charts.fn220_resolve_cam_target_from_df(
                                    df_corr, color_col=color_col_corr
                                )
                                if _alt_cam is not None:
                                    _x_va = pd.to_numeric(df_corr[x_col_corr], errors="coerce").dropna()
                                    _fr_a = bool(len(_x_va) > 0 and float(_x_va.max()) <= 1.5)
                                    _xt_a = (_alt_cam / 100.0) if _fr_a else _alt_cam
                                    _cam_df_a = pd.DataFrame({"x": [_xt_a], "label": [f"CAM {_alt_cam:.0f}%"]})
                                    _layers_alt += [
                                        alt.Chart(_cam_df_a)
                                        .mark_rule(strokeDash=[4, 4], color='#333', strokeWidth=2)
                                        .encode(x=alt.X('x:Q')),
                                        alt.Chart(_cam_df_a)
                                        .mark_text(angle=-90, align='left', dy=-4, fontSize=10, color='#333')
                                        .encode(x=alt.X('x:Q'), y=alt.value(8), text=alt.Text('label:N')),
                                    ]
                            if show_ice_corr and _corr_ice_fu:
                                _alt_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_corr)
                                _alt_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_alt_ice_cats, fu=_corr_ice_fu)
                                for _i_bm_a, _bm_a in enumerate(_alt_benchmarks):
                                    _bm_df_a = pd.DataFrame({"y": [_bm_a["value"]]})
                                    _layers_alt.append(
                                        alt.Chart(_bm_df_a)
                                        .mark_rule(
                                            strokeDash=[6, 3],
                                            color=_lib_charts.fn232_ice_line_color(_bm_a, _i_bm_a),
                                            strokeWidth=1.5,
                                        )
                                        .encode(y=alt.Y('y:Q'))
                                    )
                            _af_corr = _lib_charts.fn233a_altair_font_config(_ch_dims)
                            st.altair_chart(
                                alt.layer(*_layers_alt)
                                .configure(font=_af_corr["font"])
                                .configure_axis(
                                    labelFont=_af_corr["labelFont"],
                                    titleFont=_af_corr["titleFont"],
                                    labelFontSize=_af_corr["labelFontSize"],
                                    titleFontSize=_af_corr["titleFontSize"],
                                    labelAngle=_af_corr["tick_angle"],
                                )
                                .configure_legend(
                                    labelFont=_af_corr["labelFont"],
                                    titleFont=_af_corr["titleFont"],
                                    labelFontSize=_af_corr["legendLabelFontSize"],
                                    titleFontSize=_af_corr["legendTitleFontSize"],
                                )
                                .interactive(),
                                use_container_width=True,
                            )
                            _corr_cats_order_a = _lib_charts._sorted_unique_categories(
                                df_corr[color_col_corr].fillna("(blank)").astype(str).unique()
                            )
                            _corr_summ_a = _trace_summary_table_xy(
                                df_corr, list(_corr_cats_order_a), color_col_corr,
                                x_col_corr, y_col_corr, _x_disp, _y_disp,
                            )
                            if _corr_summ_a is not None:
                                _render_trace_summary_table(
                                    _corr_summ_a, "By legend category (median X and median Y)"
                                )

                        # ── ECharts ───────────────────────────────────────────
                        else:
                            # Marker ids point into the detail payload, which is built
                            # once per filter state from df_charts (all charted
                            # products), not from this axis-filtered frame — so an
                            # axis change no longer rebuilds it. pid = row position in
                            # df_charts + 1 (the payload's id rule); df_corr keeps
                            # df_charts' index labels, which map back to positions.
                            _ec_stable = df_charts.index.is_unique
                            _ec_pos = (pd.Series(range(1, len(df_charts) + 1), index=df_charts.index)
                                       if _ec_stable else None)
                            df_corr_ec = df_corr if _ec_stable else df_corr.reset_index(drop=True)
                            _has_name_ec = 'A__ProductName' in df_corr_ec.columns
                            _series_ec = []
                            for _i_ec, _cat_ec in enumerate(_categories_corr):
                                _mask_ec = df_corr_ec[color_col_corr].fillna("(blank)").astype(str) == _cat_ec
                                _sub_ec = df_corr_ec[_mask_ec]
                                _col_ec = _color_seq_corr[_i_ec]
                                _series_ec.append({
                                    "name": _cat_ec,
                                    "type": "scatter",
                                    "data": [
                                        {
                                            "value": [float(_xv), float(_yv)],
                                            "name": str(_nm) if _has_name_ec else _cat_ec,
                                            "pid": int(_ec_pos[_lab]) if _ec_stable else int(_lab) + 1,
                                        }
                                        for _lab, _xv, _yv, _nm in zip(
                                            _sub_ec.index, _sub_ec[x_col_corr], _sub_ec[y_col_corr],
                                            _sub_ec["A__ProductName"] if _has_name_ec else [None] * len(_sub_ec),
                                        )
                                    ],
                                    "symbolSize": 12,
                                    "symbol": "circle",
                                    "cursor": "pointer",
                                    "itemStyle": {
                                        "color": "rgba(255,255,255,0.01)",
                                        "borderColor": _col_ec,
                                        "borderWidth": 2,
                                    },
                                    "emphasis": {"scale": True, "focus": "self"},
                                })
                            if show_cam_corr:
                                _ec_cam = _lib_charts.fn220_resolve_cam_target_from_df(
                                    df_corr, color_col=color_col_corr
                                )
                                if _ec_cam is not None and _series_ec:
                                    _xv_ec = pd.to_numeric(df_corr[x_col_corr], errors="coerce").dropna()
                                    _fr_ec = bool(len(_xv_ec) > 0 and float(_xv_ec.max()) <= 1.5)
                                    _series_ec[0]["markLine"] = {
                                        "silent": True,
                                        "symbol": ["none", "none"],
                                        "lineStyle": {"type": "dotted", "color": "#333", "width": 2},
                                        "label": {
                                            "formatter": f"CAM {_ec_cam:.0f}%",
                                            "position": "insideEndTop", "fontSize": 10,
                                        },
                                        "data": [{"xAxis": (_ec_cam / 100.0) if _fr_ec else _ec_cam}],
                                    }
                            if show_ice_corr and _corr_ice_fu:
                                _ec_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_corr)
                                _ec_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_ec_ice_cats, fu=_corr_ice_fu)
                                _ec_ice_ml = [
                                    {
                                        "name": _bm["label"],
                                        "yAxis": _bm["value"],
                                        "lineStyle": {
                                            "color": _lib_charts.fn232_ice_line_color(_bm, _j),
                                            "type": "dashed", "width": 1.5,
                                        },
                                        "label": {
                                            "formatter": _lib_charts._ice_chart_short_label(_bm["label"]),
                                            "position": "insideEndTop",
                                            "fontSize": 9,
                                            "color": _lib_charts.fn232_ice_line_color(_bm, _j),
                                        },
                                        "tooltip": {
                                            "formatter": (
                                                f"<b>{_bm['label']}</b><br/>"
                                                f"{_bm['value']:.3f}"
                                            ),
                                        },
                                    }
                                    for _j, _bm in enumerate(_ec_benchmarks)
                                ]
                                if _ec_ice_ml:
                                    _series_ec.append({
                                        "name": "", "type": "scatter", "data": [],
                                        "markLine": {
                                            "silent": False, "symbol": ["none", "none"],
                                            "data": _ec_ice_ml,
                                        },
                                    })
                            _ec_ty_corr = _lib_charts.fn233b_echarts_text_style(_ch_dims)
                            _ec_option = {
                                "textStyle": _ec_ty_corr["textStyle"],
                                "tooltip": {
                                    "trigger": "item",
                                    "formatter": "TOOLTIP_FN",
                                    "textStyle": _ec_ty_corr["textStyle"],
                                },
                                "legend": {
                                    "data": _categories_corr, "type": "scroll",
                                    "right": 10, "top": 20, "orient": "vertical",
                                    "textStyle": _ec_ty_corr["legendTextStyle"],
                                },
                                "xAxis": {
                                    "type": "value", "name": _x_disp,
                                    "nameLocation": "middle", "nameGap": 35,
                                    "nameTextStyle": _ec_ty_corr["nameTextStyle"],
                                    "axisLabel": {
                                        **_ec_ty_corr["axisLabel"],
                                        "rotate": _ch_dims.get("chart_tick_label_angle", 0),
                                    },
                                },
                                "yAxis": {
                                    "type": "value", "name": _y_disp,
                                    "nameLocation": "middle", "nameGap": 55,
                                    "nameTextStyle": _ec_ty_corr["nameTextStyle"],
                                    "axisLabel": _ec_ty_corr["axisLabel"],
                                },
                                "series": _series_ec,
                                "grid": {"left": 70, "right": 220, "top": 30, "bottom": 60},
                                "dataZoom": [{"type": "inside"}],
                            }
                            _ec_tooltip_fn = (
                                "function(p){if(!p.data||p.seriesName===''){return ''}"
                                " return (p.name?'<b>'+p.name+'</b><br/>':'')"
                                "+'X: '+p.value[0].toFixed(3)+'<br/>Y: '+p.value[1].toFixed(3)"
                                "+'<br/><i>'+p.seriesName+'</i><br/><span style=\"color:#64748b;font-size:11px\">Click for product details</span>'; }"
                            )
                            _ht_ec = _ch_dims["correlation_plotly_height_px"]
                            _ec_products = (
                                fn338a_chart_products_payload_slim(
                                    df_charts, ids=[pt["pid"] for se in _series_ec for pt in se["data"]],
                                ) if _ec_stable
                                else fn338_js2_chart_products_payload(df_corr_ec)
                            )
                            _ec_html = _lib_charts.fn239_build_echarts_scatter_popup_html(
                                _ec_option,
                                _ec_products,
                                height=_ht_ec,
                                tooltip_formatter_js=_ec_tooltip_fn,
                            )
                            st.components.v1.html(_ec_html, height=_ht_ec + 20)
                            _corr_cats_ec = _lib_charts._sorted_unique_categories(
                                df_corr[color_col_corr].fillna("(blank)").astype(str).unique()
                            )
                            _corr_summ_ec = _trace_summary_table_xy(
                                df_corr, list(_corr_cats_ec), color_col_corr,
                                x_col_corr, y_col_corr, _x_disp, _y_disp,
                            )
                            if _corr_summ_ec is not None:
                                _render_trace_summary_table(
                                    _corr_summ_ec, "By legend category (median X and median Y)"
                                )

                # ── Strip Chart rendering ─────────────────────────────────────
                else:
                    df_strip = df_charts.copy()
                    df_strip[strip_y_col] = pd.to_numeric(df_strip[strip_y_col], errors='coerce')
                    df_strip = df_strip.dropna(subset=[strip_y_col])
                    df_strip[strip_group_col] = (
                        df_strip[strip_group_col].fillna("(unspecified)").astype(str).str.strip()
                    )
                    df_strip = df_strip[df_strip[strip_group_col].ne("")]

                    if df_strip.empty:
                        st.warning(_tu("No data available for the selected columns after removing empty values."))
                    else:
                        _strip_x_disp = _dl(strip_group_cleaned)
                        _strip_y_disp = _dl(strip_y_cleaned)
                        _strip_color_disp = (
                            _dl(strip_color_cleaned) if strip_color_col else _strip_x_disp
                        )
                        _strip_ht = _ch_dims["correlation_plotly_height_px"]
                        _strip_ht_alt = _ch_dims["correlation_altair_height_px"]
                        _strip_fs_ht = min(
                            int(_ch_dims["correlation_fullscreen_plotly_height_px"]),
                            720,
                        )
                        _strip_fs_ht_alt = min(
                            int(_ch_dims["correlation_fullscreen_altair_height_px"]),
                            680,
                        )
                        _strip_fs_open = bool(st.session_state.get("strip_fs_open"))

                        # ── Plotly ────────────────────────────────────────────
                        if strip_engine == "Plotly":
                            strip_settings = dict(
                                xaxis_title=_strip_x_disp,
                                yaxis_title=_strip_y_disp,
                                legend_title=_strip_color_disp,
                                height=_strip_ht,
                                font_family=_ch_dims["chart_font_family"],
                                font_size=_ch_dims["chart_font_size"],
                                legend_font_size=_ch_dims["chart_legend_font_size"],
                                tick_font_size=_ch_dims["chart_tick_font_size"],
                                axis_title_font_size=_ch_dims["chart_axis_title_size"],
                                tick_label_angle=_ch_dims.get("chart_tick_label_angle", 0),
                                tick_wrap_chars=_ch_dims.get(
                                    "strip_tick_wrap_chars",
                                    _ch_dims.get("chart_tick_wrap_chars", 9),
                                ),
                                tick_max_lines=_ch_dims.get("strip_tick_max_lines", 4),
                                show_legend=strip_show_legend,
                            )
                            _strip_cmap = _lib_charts.fn231_insulation_material_color_map(
                                df_strip,
                                strip_color_col or strip_group_col,
                                CUSTOM_COLOR_MAP,
                            )
                            fig_strip = _lib_charts.fn227_plot_strip_chart(
                                df_strip,
                                group_col=strip_group_col,
                                value_col=strip_y_col,
                                color_col=strip_color_col,
                                settings=strip_settings,
                                jitter_width=strip_jitter,
                                color_map=_strip_cmap,
                                show_legend=strip_show_legend,
                            )
                            if show_ice_strip and _strip_ice_fu:
                                _strip_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_strip)
                                _strip_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_strip_ice_cats, fu=_strip_ice_fu)
                                fig_strip = _lib_charts.fn226_add_ice_hlines_to_chart(fig_strip, _strip_benchmarks)
                            st.plotly_chart(fig_strip, width='stretch', key="corr_strip_chart")
                            if _strip_fs_open:
                                _strip_chart_fullscreen_dialog({
                                    "kind": "plotly",
                                    "fig": fig_strip,
                                    "height": _strip_fs_ht,
                                })
                            _strip_groups_ord = _lib_charts._sorted_unique_categories(
                                df_strip[strip_group_col].dropna().unique()
                            )
                            _strip_summ = _trace_summary_table_one_metric(
                                df_strip, list(_strip_groups_ord),
                                strip_group_col, strip_y_col, _strip_y_disp,
                            )
                            if _strip_summ is not None:
                                _render_trace_summary_table(_strip_summ, "By group (median)")

                        # ── Altair ────────────────────────────────────────────
                        elif strip_engine == "Altair":
                            try:
                                import altair as alt
                            except ImportError:
                                st.error("Altair is not installed. Run `pip install altair` to enable this view.")
                                st.stop()
                            import numpy as _np_sa

                            _groups_sa = _lib_charts._sorted_unique_categories(
                                df_strip[strip_group_col].dropna().unique()
                            )
                            _gidx_sa = {g: i for i, g in enumerate(_groups_sa)}
                            _rng_sa = _np_sa.random.default_rng(42)
                            _jit_vals_sa = _rng_sa.uniform(
                                -strip_jitter / 2, strip_jitter / 2, len(df_strip)
                            )
                            _df_sa = df_strip.copy()
                            _df_sa['__x_jitter'] = [
                                float(_gidx_sa.get(g, 0)) + float(jv)
                                for g, jv in zip(_df_sa[strip_group_col], _jit_vals_sa)
                            ]
                            _color_col_sa = strip_color_col or strip_group_col
                            _strip_cmap_sa = _lib_charts.fn231_insulation_material_color_map(
                                df_strip, _color_col_sa, CUSTOM_COLOR_MAP,
                            )
                            _cats_sa = _lib_charts._sorted_unique_categories(
                                _df_sa[_color_col_sa].fillna("(blank)").astype(str).unique()
                            )
                            _fallback_sa = px.colors.qualitative.Set2
                            _range_sa = [
                                _strip_cmap_sa.get(c, _fallback_sa[i % len(_fallback_sa)])
                                for i, c in enumerate(_cats_sa)
                            ]
                            _tooltip_sa = (
                                [alt.Tooltip('A__ProductName:N', title='Product')]
                                if 'A__ProductName' in _df_sa.columns else []
                            ) + [
                                alt.Tooltip(f'{strip_group_col}:N', title=_strip_x_disp),
                                alt.Tooltip(f'{strip_y_col}:Q', title=_strip_y_disp, format='.3f'),
                            ]
                            _n_sa = len(_groups_sa)
                            # Narrow wrap so strip X labels fit in ~3–4 horizontal lines.
                            _wrap_sa = int(_ch_dims.get("strip_tick_wrap_chars", 9))
                            _max_ln_sa = int(_ch_dims.get("strip_tick_max_lines", 4))
                            _wrapped_sa = {
                                str(i): _lib_charts.fn234_wrap_tick_label(
                                    g, _wrap_sa, joiner="\n", max_lines=_max_ln_sa,
                                )
                                for i, g in enumerate(_groups_sa)
                            }
                            _n_ln_sa = max(
                                (lab.count("\n") + 1 for lab in _wrapped_sa.values()),
                                default=1,
                            )
                            _lbl_map_sa = json.dumps(_wrapped_sa)
                            _label_expr_sa = f"({_lbl_map_sa})['' + round(datum.value)]"
                            _af_sa = _lib_charts.fn233a_altair_font_config(_ch_dims)
                            _color_enc_sa = alt.Color(
                                f'{_color_col_sa}:N',
                                title=_strip_color_disp,
                                scale=alt.Scale(domain=list(_cats_sa), range=_range_sa),
                                legend=alt.Legend() if strip_show_legend else None,
                            )
                            _bot_pad_sa = (
                                max(72, 28 + _n_ln_sa * 16)
                                if int(_af_sa["tick_angle"]) == 0
                                else 170
                            )

                            _base_sa = (
                                alt.Chart(_df_sa)
                                .mark_circle(size=60, opacity=0.78)
                                .encode(
                                    x=alt.X(
                                        '__x_jitter:Q',
                                        title=_strip_x_disp,
                                        scale=alt.Scale(domain=[-0.7, _n_sa - 0.3]),
                                        axis=alt.Axis(
                                            values=list(range(_n_sa)),
                                            labelExpr=_label_expr_sa,
                                            labelAngle=_af_sa["tick_angle"],
                                            labelLimit=0,
                                            labelOverlap=False,
                                            labelSeparation=2,
                                            labelFlush=False,
                                            labelBound=False,
                                            labelFont=_af_sa["labelFont"],
                                            labelFontSize=_af_sa["labelFontSize"],
                                            titleFont=_af_sa["titleFont"],
                                            titleFontSize=_af_sa["titleFontSize"],
                                            titlePadding=max(8, 4 + _n_ln_sa * 2),
                                            tickCount=_n_sa,
                                            tickMinStep=1,
                                        ),
                                    ),
                                    y=alt.Y(f'{strip_y_col}:Q', title=_strip_y_disp),
                                    color=_color_enc_sa,
                                    tooltip=_tooltip_sa,
                                )
                            )
                            _zero_df_sa = pd.DataFrame({"y": [0.0]})
                            _layers_sa = [
                                _base_sa,
                                alt.Chart(_zero_df_sa)
                                .mark_rule(strokeDash=[4, 4], color='#aaa', opacity=0.6)
                                .encode(y=alt.Y('y:Q')),
                            ]
                            if show_ice_strip and _strip_ice_fu:
                                _sa_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_strip)
                                _sa_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_sa_ice_cats, fu=_strip_ice_fu)
                                for _i_bm_sa, _bm_sa in enumerate(_sa_benchmarks):
                                    _bm_df_sa = pd.DataFrame({"y": [_bm_sa["value"]]})
                                    _layers_sa.append(
                                        alt.Chart(_bm_df_sa)
                                        .mark_rule(
                                            strokeDash=[6, 3],
                                            color=_lib_charts.fn232_ice_line_color(_bm_sa, _i_bm_sa),
                                            strokeWidth=1.5,
                                        )
                                        .encode(y=alt.Y('y:Q'))
                                    )
                            _alt_strip = (
                                alt.layer(*_layers_sa)
                                .properties(
                                    height=_strip_ht_alt,
                                    padding={
                                        "top": 8,
                                        "left": 4,
                                        "right": 8,
                                        "bottom": _bot_pad_sa,
                                    },
                                )
                                .configure(font=_af_sa["font"])
                                .configure_axis(
                                    labelFont=_af_sa["labelFont"],
                                    titleFont=_af_sa["titleFont"],
                                    labelFontSize=_af_sa["labelFontSize"],
                                    titleFontSize=_af_sa["titleFontSize"],
                                    labelAngle=_af_sa["tick_angle"],
                                )
                            )
                            if strip_show_legend:
                                _alt_strip = _alt_strip.configure_legend(
                                    labelFont=_af_sa["labelFont"],
                                    titleFont=_af_sa["titleFont"],
                                    labelFontSize=_af_sa["legendLabelFontSize"],
                                    titleFontSize=_af_sa["legendTitleFontSize"],
                                )
                            else:
                                _alt_strip = _alt_strip.configure_legend(disable=True)
                            _alt_strip_view = _alt_strip.interactive()
                            st.altair_chart(_alt_strip_view, use_container_width=True)
                            if _strip_fs_open:
                                _strip_chart_fullscreen_dialog({
                                    "kind": "altair",
                                    "chart": _alt_strip_view,
                                    "height": _strip_fs_ht_alt,
                                })
                            _strip_groups_ord_sa = _lib_charts._sorted_unique_categories(
                                df_strip[strip_group_col].dropna().unique()
                            )
                            _strip_summ_sa = _trace_summary_table_one_metric(
                                df_strip, list(_strip_groups_ord_sa),
                                strip_group_col, strip_y_col, _strip_y_disp,
                            )
                            if _strip_summ_sa is not None:
                                _render_trace_summary_table(_strip_summ_sa, "By group (median)")

                        # ── ECharts ───────────────────────────────────────────
                        else:
                            import numpy as _np_ec_s

                            _groups_ec_s = _lib_charts._sorted_unique_categories(
                                df_strip[strip_group_col].dropna().unique()
                            )
                            _gidx_ec_s = {g: i for i, g in enumerate(_groups_ec_s)}
                            _rng_ec_s = _np_ec_s.random.default_rng(42)
                            _n_ec_s = len(_groups_ec_s)
                            _has_nm_ec_s = 'A__ProductName' in df_strip.columns
                            _pal_ec_s = (
                                px.colors.qualitative.D3
                                + px.colors.qualitative.Set2
                                + px.colors.qualitative.Set1
                            )
                            _color_col_ec_s = strip_color_col or strip_group_col
                            _strip_cmap_ec = _lib_charts.fn231_insulation_material_color_map(
                                df_strip, _color_col_ec_s, CUSTOM_COLOR_MAP,
                            )
                            _cgroups_ec_s = _lib_charts._sorted_unique_categories(
                                df_strip[_color_col_ec_s].fillna("(blank)").astype(str).unique()
                            )
                            _strip_series_ec_s = []
                            for _ci_ec_s, _cg_ec_s in enumerate(_cgroups_ec_s):
                                _cmask = df_strip[_color_col_ec_s].fillna("(blank)").astype(str) == str(_cg_ec_s)
                                _csub = df_strip[_cmask]
                                _cc = _strip_cmap_ec.get(
                                    str(_cg_ec_s),
                                    _pal_ec_s[_ci_ec_s % len(_pal_ec_s)],
                                )
                                _data_pts = []
                                for _grp in _groups_ec_s:
                                    _grow = _csub[_csub[strip_group_col] == _grp]
                                    if _grow.empty:
                                        continue
                                    _npts = len(_grow)
                                    _jit = _rng_ec_s.uniform(-strip_jitter / 2, strip_jitter / 2, _npts)
                                    _names = (_grow["A__ProductName"].astype(str).tolist()
                                              if _has_nm_ec_s else [str(_grp)] * _npts)
                                    for _jv, _yv, _nm in zip(_jit, _grow[strip_y_col], _names):
                                        _data_pts.append({
                                            "value": [float(_gidx_ec_s[_grp]) + float(_jv), float(_yv)],
                                            "name": _nm,
                                        })
                                _strip_series_ec_s.append({
                                    "name": str(_cg_ec_s), "type": "scatter",
                                    "data": _data_pts,
                                    "symbolSize": 8,
                                    "itemStyle": {"color": _cc, "opacity": 0.78},
                                })
                            _ml_zero = [{
                                "yAxis": 0,
                                "lineStyle": {"color": "#bbb", "width": 1, "type": "solid"},
                                "label": {"show": False},
                            }]
                            if show_ice_strip and _strip_ice_fu:
                                _ec_s_ice_cats = _lib_charts.fn222_resolve_ice_categories(df_strip)
                                _ec_s_benchmarks = _lib_charts.fn224_get_ice_benchmarks(_ec_s_ice_cats, fu=_strip_ice_fu)
                                for _j_ec_s, _bm_ec_s in enumerate(_ec_s_benchmarks):
                                    _ice_col_s = _lib_charts.fn232_ice_line_color(_bm_ec_s, _j_ec_s)
                                    _ml_zero.append({
                                        "name": _bm_ec_s["label"],
                                        "yAxis": _bm_ec_s["value"],
                                        "lineStyle": {
                                            "color": _ice_col_s,
                                            "type": "dashed", "width": 1.5,
                                        },
                                        "label": {
                                            "formatter": _lib_charts._ice_chart_short_label(
                                                _bm_ec_s["label"]
                                            ),
                                            "position": "insideEndTop",
                                            "fontSize": 9,
                                            "color": _ice_col_s,
                                        },
                                        "tooltip": {
                                            "formatter": (
                                                f"<b>{_bm_ec_s['label']}</b><br/>"
                                                f"{_bm_ec_s['value']:.3f}"
                                            ),
                                        },
                                    })
                            _all_series_ec_s = _strip_series_ec_s + [{
                                "name": "", "type": "scatter", "data": [],
                                "markLine": {
                                    "silent": False, "symbol": ["none", "none"], "data": _ml_zero,
                                },
                            }]
                            _wrap_ec_s = int(_ch_dims.get("strip_tick_wrap_chars", 9))
                            _max_ln_ec = int(_ch_dims.get("strip_tick_max_lines", 4))
                            _grp_lbl_ec_s = [
                                _lib_charts.fn234_wrap_tick_label(
                                    g, _wrap_ec_s, joiner="\n", max_lines=_max_ln_ec,
                                )
                                for g in _groups_ec_s
                            ]
                            _lbl_map_ec_s = json.dumps(
                                {str(i): lab for i, lab in enumerate(_grp_lbl_ec_s)}
                            )
                            _ec_ty_s = _lib_charts.fn233b_echarts_text_style(_ch_dims)
                            _tick_ang_s = int(_ch_dims.get("chart_tick_label_angle", 0))
                            _n_ln_ec = max((lab.count("\n") + 1 for lab in _grp_lbl_ec_s), default=1)

                            _strip_ec_opt = {
                                "textStyle": _ec_ty_s["textStyle"],
                                "tooltip": {
                                    "trigger": "item",
                                    "formatter": "STRIP_TT",
                                    "textStyle": _ec_ty_s["textStyle"],
                                },
                                "legend": {
                                    "show": bool(strip_show_legend),
                                    "data": [s["name"] for s in _strip_series_ec_s],
                                    "type": "scroll", "right": 10, "top": 20, "orient": "vertical",
                                    "textStyle": _ec_ty_s["legendTextStyle"],
                                },
                                "grid": {
                                    "left": 70,
                                    "right": 220 if strip_show_legend else 24,
                                    "top": 30,
                                    "bottom": max(72, 28 + _n_ln_ec * 16),
                                    "containLabel": False,
                                },
                                "xAxis": {
                                    "type": "value",
                                    "min": -0.7, "max": _n_ec_s - 0.3,
                                    "axisTick": {
                                        "show": True,
                                        "customValues": list(range(_n_ec_s)),
                                    },
                                    "axisLabel": {
                                        **_ec_ty_s["axisLabel"],
                                        "rotate": _tick_ang_s,
                                        "interval": 0,
                                        "hideOverlap": False,
                                        "customValues": list(range(_n_ec_s)),
                                        "formatter": "XFMT",
                                        "overflow": "break",
                                        "width": max(48, _wrap_ec_s * 7),
                                    },
                                    "name": _strip_x_disp,
                                    "nameLocation": "middle",
                                    "nameGap": max(48, 12 + _n_ln_ec * 14) if _tick_ang_s == 0 else 155,
                                    "nameTextStyle": _ec_ty_s["nameTextStyle"],
                                    "splitLine": {"show": False},
                                },
                                "yAxis": {
                                    "type": "value", "name": _strip_y_disp,
                                    "nameLocation": "middle", "nameGap": 50,
                                    "nameTextStyle": _ec_ty_s["nameTextStyle"],
                                    "axisLabel": _ec_ty_s["axisLabel"],
                                    "splitLine": {"lineStyle": {"color": "#eee"}},
                                },
                                "series": _all_series_ec_s,
                                "dataZoom": [
                                    {"type": "inside", "xAxisIndex": 0, "filterMode": "none"},
                                    {"type": "inside", "yAxisIndex": 0, "filterMode": "none"},
                                ],
                            }
                            _strip_ec_json = json.dumps(_strip_ec_opt, ensure_ascii=False, default=str)
                            _strip_tt_js = (
                                "function(p){if(!p.data||p.seriesName===''){return ''}"
                                " return (p.name?'<b>'+p.name+'</b><br/>':'')"
                                "+'Y: '+p.value[1].toFixed(3)"
                                "+'<br/><i>'+p.seriesName+'</i>'; }"
                            )
                            _xfmt_js = (
                                f"function(v){{var m={_lbl_map_ec_s};"
                                f"return m[''+Math.round(v)]||'';}}"
                            )
                            _strip_ec_json = _strip_ec_json.replace('"STRIP_TT"', _strip_tt_js)
                            _strip_ec_json = _strip_ec_json.replace('"XFMT"', _xfmt_js)

                            _ht_ec_s = _strip_ht
                            _ec_strip_html = (
                                '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
                                f'<div id="ec_strip" style="width:100%;height:{_ht_ec_s}px"></div>'
                                f'<script>var c=echarts.init(document.getElementById("ec_strip"),null,{{renderer:"canvas"}});'
                                f'c.setOption({_strip_ec_json});'
                                'window.addEventListener("resize",function(){c.resize();});</script>'
                            )
                            st.components.v1.html(_ec_strip_html, height=_ht_ec_s + 20)
                            if _strip_fs_open:
                                _ec_strip_fs_html = (
                                    '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
                                    f'<div id="ec_strip_fs" style="width:100%;height:{_strip_fs_ht}px"></div>'
                                    f'<script>var c=echarts.init(document.getElementById("ec_strip_fs"),null,{{renderer:"canvas"}});'
                                    f'c.setOption({_strip_ec_json});'
                                    'window.addEventListener("resize",function(){c.resize();});</script>'
                                )
                                _strip_chart_fullscreen_dialog({
                                    "kind": "echarts",
                                    "html": _ec_strip_fs_html,
                                    "height": _strip_fs_ht,
                                })
                            _strip_groups_ord_ec = _lib_charts._sorted_unique_categories(
                                df_strip[strip_group_col].dropna().unique()
                            )
                            _strip_summ_ec = _trace_summary_table_one_metric(
                                df_strip, list(_strip_groups_ord_ec),
                                strip_group_col, strip_y_col, _strip_y_disp,
                            )
                            if _strip_summ_ec is not None:
                                _render_trace_summary_table(_strip_summ_ec, "By group (median)")

                        if _strip_ice_fu and show_ice_strip:
                            _strip_cap_unit = {
                                "kg": "kg CO₂e/kg",
                                "m2": "kg CO₂e/m²",
                                "m3": "kg CO₂e/m³",
                            }[_strip_ice_fu]
                            if _strip_ice_fu == "kg":
                                st.caption(_tu(
                                    "ICE DB dashed lines: V4.1 embodied carbon ({unit}) — "
                                    "one line per ICE material · Circular Ecology.",
                                    unit=_strip_cap_unit,
                                ))
                            else:
                                st.caption(_tu(
                                    "ICE DB dashed lines: V4.1 median embodied carbon ({unit}) "
                                    "per material category · Circular Ecology.",
                                    unit=_strip_cap_unit,
                                ))



else:
    # Previously this page rendered a blank screen when data was not ready.
    fn356_empty_state(
        "Charts need the product dataset.",
        hint="Give the data a moment to load, or check the data source on the Welcome page.",
    )
