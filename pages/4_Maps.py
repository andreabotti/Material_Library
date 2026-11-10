"""
pages/4_Maps.py  —  Geographic manufacturing maps (PyDeck + Plotly)
"""
# ── Shared imports (every fn__libs function, all lib.shared constants) ─────
from libs.page_imports import *  # noqa: F401,F403
# `import *` skips underscore names, so page_imports' `html as _html` never
# reaches this page; without this the Product Map tab raised NameError.
import html as _html


# ── Page helpers ─────────────────────────────────────────────────────────────
# Normalize plant/country values before cache lookups.
# Important: Excel blanks often arrive as NaN -> "nan" string when cast, causing cache misses.
def _clean_geo_field(v) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if not s or s == "-" or s.lower() == "nan":
        return ""
    return s


def _maps_filter_signature(df: pd.DataFrame) -> str:
    """Which rows this page sees, as a short string for cache keys.

    The maps read FILTERED_DATA, which the sidebar filters change without
    touching ``_data_fingerprint``; hashing the row IDs (cheap) keeps cached
    frames from going stale when the user changes a filter.
    """
    try:
        if "0__EETRA_ID" in df.columns:
            h = pd.util.hash_pandas_object(df["0__EETRA_ID"].astype(str), index=False)
        else:
            h = pd.util.hash_pandas_object(df.index.to_series(), index=False)
        return f"{len(df)}:{hashlib.md5(h.values.tobytes()).hexdigest()}"
    except Exception:
        # Unhashable -> never reuse a cached result (max_entries bounds the waste).
        import uuid
        return f"nohash:{uuid.uuid4().hex}"


@st.cache_data(max_entries=8, show_spinner=False)
def _maps_location_counts(data_fp, filter_sig: str, _df: pd.DataFrame) -> pd.DataFrame:
    """Unique (plant, country, manufacturer) triples with their row counts.

    One groupby instead of a full boolean filter of the frame per location
    (that was O(locations x rows)). ``sort=False`` keeps first-appearance order,
    i.e. the same row order ``drop_duplicates`` produced. Geocoding stays out of
    here: it reads GEOCODE_CACHE from session state via fn115.
    """
    keys = pd.DataFrame({
        "_plant_clean": _df["E__ManuPlant"].apply(_clean_geo_field),
        "_country_clean": _df["E__ManuCountry"].apply(_clean_geo_field),
        "_manu_clean": _df.get("A__Manufacturer", "").astype(str).str.strip(),
    })
    counts = (
        keys.groupby(["_plant_clean", "_country_clean", "_manu_clean"], sort=False, dropna=False)
        .size()
        .reset_index(name="Product_Count")
    )
    return counts[counts["_plant_clean"].astype(str).str.strip() != ""].reset_index(drop=True)


@st.cache_data(max_entries=8, show_spinner=False)
def _maps_multi_plant_bases(data_fp, filter_sig: str, _df: pd.DataFrame) -> list:
    """Base products made in more than one plant (shared by Product Map 1 and 2)."""
    # Normalize plant and country to avoid false duplicates due to casing/whitespace
    df_norm = _df.dropna(subset=['E__ManuPlant']).copy()
    df_norm['_plant_norm'] = (
        df_norm['E__ManuPlant']
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r'\s+', ' ', regex=True)
    )
    df_norm['_country_norm'] = (
        df_norm['E__ManuCountry']
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r'\s+', ' ', regex=True)
    )
    df_norm['__plant_country_norm'] = df_norm['_plant_norm'] + '|' + df_norm['_country_norm']
    plant_counts = (
        df_norm.groupby('A__ProductName_Base')['__plant_country_norm']
        .nunique()
    )
    return sorted(plant_counts[plant_counts > 1].index.tolist())


def _maps_pm2_open(base_name: str) -> None:
    """'Open' on a Product Map 2 mini-map: select that base in the selectbox.

    Runs as a callback (before the script), the only point where the
    selectbox's key may be written; writing it from the button's return value
    raised "cannot be modified after the widget is instantiated".
    """
    st.session_state["product_map2_selected_base"] = base_name


@st.fragment
def _maps_pm2_grid(df_map_base: pd.DataFrame, dup_bases: list) -> None:
    """Product Map 2 slider + mini-map grid.

    A fragment, so dragging the slider re-renders only the grid instead of the
    whole app. Figures are deliberately not st.cache_data'd: unpickling a
    cached plotly Figure measured ~3x slower than building it.
    """
    # (2) Static mini-maps grid (no WebGL contexts) + “Open” buttons
    total = len(dup_bases)
    default_max = min(12, total)
    if total <= 1:
        max_to_show = total
    else:
        max_to_show = st.slider(
            "How many mini-maps to show",
            min_value=1,
            max_value=total,
            value=default_max,
            step=1,
            key="product_map2_max_to_show",
        )
    bases_to_show = dup_bases[:max_to_show]

    COLS = 4
    for i in range(0, len(bases_to_show), COLS):
        cols = st.columns(COLS, gap="medium")
        for j, base_name in enumerate(bases_to_show[i:i+COLS]):
            with cols[j]:
                st.markdown(f"**{base_name}**")

                cached_map = st.session_state.get("LOCATIONS_BY_BASE_PRODUCT", {})
                if isinstance(cached_map, dict) and base_name in cached_map:
                    _loc = cached_map[base_name].copy()
                else:
                    _loc = fn118_get_locations_for_base_product(df_map_base, base_name)
                    if _loc is not None and not _loc.empty:
                        try:
                            st.session_state["LOCATIONS_BY_BASE_PRODUCT"][base_name] = _loc.copy()
                        except Exception:
                            pass

                if _loc is None or _loc.empty:
                    st.caption("No cached coords.")
                else:
                    try:
                        fig_thumb = go.Figure(
                            go.Scattergeo(
                                lat=_loc["lat"],
                                lon=_loc["lon"],
                                mode="markers",
                                marker=dict(size=6, color="rgb(0,122,204)", opacity=0.85),
                                hoverinfo="skip",
                            )
                        )
                        fig_thumb.update_geos(
                            fitbounds="locations",
                            showcountries=True,
                            showland=True,
                            landcolor="rgb(245,245,245)",
                            coastlinecolor="rgb(200,200,200)",
                            projection_type="natural earth",
                        )
                        fig_thumb.update_layout(
                            height=220,
                            margin=dict(l=0, r=0, t=0, b=0),
                            paper_bgcolor="white",
                        )
                        st.plotly_chart(
                            fig_thumb,
                            width='stretch',
                            config={"staticPlot": True, "displayModeBar": False},
                        )
                    except Exception:
                        st.caption("Mini-map unavailable.")

                # The callback sets the selection; the app-scope rerun then
                # refreshes the interactive map above, outside this fragment.
                if st.button("Open", key=f"product_map2_open_{base_name}",
                             on_click=_maps_pm2_open, args=(base_name,)):
                    st.rerun()


# ── Pull shared data from session state (written by app.py every run) ────
df_filtered  = st.session_state.get("FILTERED_DATA",  pd.DataFrame())
df_original  = st.session_state.get("ORIGINAL_DATA",  pd.DataFrame())

if st.session_state.get("df_filtered_ready", False):
    _ch_dims = fn341_get_charts_dimensions()

    # Basemap styles:
    # - Mapbox (requires access to Mapbox + a working token)
    # - Carto (tokenless fallback; fixes "sad face" when Mapbox is blocked/unavailable)
    DEFAULT_MAPBOX_STYLE = "mapbox://styles/mapbox/light-v11"
    CARTO_POSITRON_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

    # Basemap choice widget is rendered at the bottom of the page.
    # Here we only read the stored value from session_state so maps above can render.
    _requested_basemap = st.session_state.get("maps_basemap_choice", "Carto (no token)")
    _basemap_warning = None
    if _requested_basemap == "Mapbox":
        _token, _ = fn006_resolve_mapbox()  # module-level cached resolver
        if _token:
            MAP_STYLE_URL = DEFAULT_MAPBOX_STYLE
            MAP_API_KEYS = {"mapbox": _token}
        else:
            MAP_STYLE_URL = CARTO_POSITRON_STYLE
            MAP_API_KEYS = None
            _basemap_warning = "Mapbox token missing. Using Carto basemap."
    else:
        MAP_STYLE_URL = CARTO_POSITRON_STYLE
        MAP_API_KEYS = None

    # Apply map filter directly on the slice (no intermediate full copy).
    if "A__Map_yn" in df_filtered.columns:
        df_map = df_filtered[df_filtered["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"].copy()
    else:
        df_map = df_filtered.copy()

    # Cache keys for the frames derived from df_map (see the helpers above).
    _maps_data_fp = st.session_state.get("_data_fingerprint")
    _maps_filter_sig = _maps_filter_signature(df_map)

    required_cols = ['A__ProductName', 'E__ManuPlant']
    if not all(col in df_map.columns for col in required_cols):
        st.info("Required columns not present to build the map (need 'A__ProductName' and 'E__ManuPlant').")
    else:
        # Create main category tabs
        in_situ_enabled = fn209_is_in_situ_selected()
        main_tab_labels = ["All Products"]
        if in_situ_enabled:
            main_tab_labels.append("In Situ Concrete")

        # Lazy tabs (only the selected view is built); fn353a keeps the hidden
        # views' selections alive while they are not rendered.
        fn353a_keep_widget_state(
            "charts_map_", "product_map2_selected_base", "product_map2_max_to_show",
        )
        _main_tabs = st.tabs(main_tab_labels, on_change="rerun", key="maps_main_active_tab")
        all_products_tab = _main_tabs[0]
        if in_situ_enabled:
            insitu_tab = _main_tabs[1]
        else:
            insitu_tab = None
        
        # ========== ALL PRODUCTS TAB ==========
        if all_products_tab.open:
            with all_products_tab:
                st.markdown("###### 📦 All Products - Manufacturing Locations")
                df_map_base = df_map  # Base product column already computed on df_filtered above; reuse directly
                if 'E__ManuCountry' not in df_map_base.columns:
                    df_map_base['E__ManuCountry'] = ""

                # Unique plant/country/manufacturer combinations (normalized for
                # reliable lookups) with their product counts, in one groupby.
                df_locations = _maps_location_counts(_maps_data_fp, _maps_filter_sig, df_map_base)

                if df_locations.empty:
                    st.info("No manufacturing plant data found in current filters.")
                else:
                    # Get geocoding for all plants
                    locations_list = []
                    missing_keys = []
                    for plant, country, manufacturer, product_count in zip(
                        df_locations["_plant_clean"], df_locations["_country_clean"],
                        df_locations["_manu_clean"], df_locations["Product_Count"],
                    ):
                        plant = str(plant).strip()
                        country = str(country).strip()
                        manufacturer = str(manufacturer).strip()
                        product_count = int(product_count)

                        # Get geocoding
                        coords = fn115_geocode_location(plant, country if country else None)
                        if coords and coords[0] is not None and coords[1] is not None:
                            locations_list.append({
                                'Plant': plant,
                                'Country': country,
                                'Manufacturer': manufacturer,
                                'lat': coords[0],
                                'lon': coords[1],
                                'Product_Count': product_count
                            })
                        else:
                            missing_keys.append(f"{plant}|{country}")
                
                    if not locations_list:
                        st.info("No geocoding data available for manufacturing plants.")
                        if missing_keys:
                            with st.expander("Show missing geocoding keys (cache lookup)", expanded=False, type="compact"):
                                st.caption("These keys were not found in `aux_06__geocoded_locations.json`.")
                                st.code("\n".join(sorted(set(missing_keys))[:80]))
                    else:
                        import pandas as pd
                        locations_df = pd.DataFrame(locations_list)
                    
                        # Color-code by manufacturer
                        manufacturers = locations_df['Manufacturer'].unique()
                        # Generate distinct colors for each manufacturer
                        import colorsys
                        def get_manufacturer_color(idx, total):
                            """Generate distinct colors using HSV color space"""
                            hue = idx / total
                            rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
                            return [int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), 200]
                    
                        manufacturer_colors = {manu: get_manufacturer_color(i, len(manufacturers)) 
                                             for i, manu in enumerate(manufacturers)}
                    
                        locations_df['color'] = locations_df['Manufacturer'].map(manufacturer_colors)
                        locations_df['Product_Count_Label'] = locations_df['Product_Count'].astype(str)
                    
                        # Prepare view - center on geometric center of all locations
                        center_lat = locations_df['lat'].mean()
                        center_lon = locations_df['lon'].mean()
                    
                        col_left, col_right = st.columns([4, 6], gap="large")
                    
                        with col_right:
                            view_state = pdk.ViewState(
                                latitude=center_lat,
                                longitude=center_lon,
                                zoom=3.6,
                                pitch=0,
                                bearing=0
                            )
                        
                            # Scatter layer for locations
                            # Note: Text overlay is temporarily disabled due to a deck.gl TextLayer bug in this environment
                            layer = pdk.Layer(
                                "ScatterplotLayer",
                                data=locations_df,
                                get_position='[lon, lat]',
                                get_fill_color='color',
                                get_line_color=[50, 50, 50, 255],
                                get_radius=10,
                                radius_units='meters',
                                stroked=True,
                                line_width_min_pixels=1,
                                pickable=True
                            )
                        
                            tooltip = {
                                "html": "<b>{Manufacturer}</b><br/>{Plant} ({Country})<br/>Products: {Product_Count}",
                                "style": {"backgroundColor": "white", "color": "black"}
                            }
                        
                            # Use module-level cached Mapbox resolver
                            mapbox_token, _ = fn006_resolve_mapbox()
                        
                            deck_kwargs = {
                                "layers": [layer],
                                "initial_view_state": view_state,
                                "tooltip": tooltip,
                                "map_style": MAP_STYLE_URL
                            }
                            if MAP_API_KEYS:
                                deck_kwargs["api_keys"] = MAP_API_KEYS
                        
                            deck = pdk.Deck(**deck_kwargs)
                        
                            # Legend for manufacturers
                            fn304_slim_divider(width="50%", margin_top="4px", margin_bottom="4px")
                            st.markdown("**Manufacturers:**")
                            legend_html = '<div style="display:flex;flex-wrap:wrap;align-items:center;margin-bottom:6px;">'
                            for manu in sorted(manufacturers):
                                color = manufacturer_colors[manu]
                                color_str = f"rgb({color[0]},{color[1]},{color[2]})"
                                legend_html += f'<div style="display:flex;align-items:center;margin-right:18px;margin-bottom:4px;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{color_str};border:1px solid rgba(0,0,0,0.3);margin-right:6px;"></span><span style="font-size:11px;color:#444;">{manu}</span></div>'
                            legend_html += '</div>'
                            st.markdown(legend_html, unsafe_allow_html=True)
                        
                            st.pydeck_chart(deck, width='stretch', height=550)
                    
                        with col_left:
                            st.markdown("###### Manufacturing Locations")
                            # Reorder columns for display
                            display_df = locations_df[['Manufacturer', 'Country', 'Plant', 'Product_Count']].copy()
                            display_df = display_df.rename(columns={'Product_Count': '# Products'})
                            display_df = display_df.sort_values(['Manufacturer', 'Country', 'Plant'])
                            # Remove A__Map_yn column if present (shouldn't be, but just in case)
                            if "A__Map_yn" in display_df.columns:
                                display_df = display_df.drop(columns=["A__Map_yn"])
                            st.dataframe(display_df, height=530)
        
        if insitu_tab is not None:
            if insitu_tab.open:
                with insitu_tab:
                    # Create sub-tabs for different map views
                    map_tab1, map_tab2, map_tab3 = st.tabs(
                        ["Product Map", "Product Map 2", "All products per plant"],
                        on_change="rerun", key="maps_insitu_active_tab",
                    )
            
                    # ========== TAB 1: Product Map ==========
                    if map_tab1.open:
                        with map_tab1:
                            st.markdown("###### 🗺️ Product Map")
                            df_map_base = df_map  # Base product column already computed on df_filtered above; reuse directly
                            if 'E__ManuCountry' not in df_map_base.columns:
                                df_map_base['E__ManuCountry'] = ""
                            dup_bases = _maps_multi_plant_bases(_maps_data_fp, _maps_filter_sig, df_map_base)

                            col_left, col_right = st.columns([4, 6], gap="large")

                            # UI: "All Products" toggle + conditional product selector
                            with col_left:
                                sub_a, sub_b = st.columns([1, 3], gap="small")
                                with sub_a:
                                    all_products_mode = st.toggle(
                                        "View All Products",
                                        value=True,
                                        key="charts_map_all_products_toggle",
                                    )
                                with sub_b:
                                    selected_base = st.selectbox(
                                        "Select a base product with multiple plants",
                                        dup_bases if dup_bases else ["(none)"],
                                        index=0,
                                        key="charts_map_selected_base",
                                        disabled=all_products_mode or (not dup_bases),
                                    )

                            # Fallback: if there are no multi-plant bases, force All Products mode
                            if not dup_bases:
                                all_products_mode = True

                            # Determine best GWP column available in current filtered data
                            # In-situ concrete: prefer per-m³ GWP for display in the Locations table
                            gwp_candidates = [
                                'G__GWP_A1A3_m3',
                                'G__GWP_A1A3',         # fallback (per FU) if m³ isn't available
                                'G__GWP_A1A3_Total',
                                'G__GWP_Total'
                            ]
                            gwp_col = next((c for c in gwp_candidates if c in df_map_base.columns), None)

                            # Build locations_df either for all products or for selected base product
                            locations_df = pd.DataFrame()
                            if all_products_mode:
                                df_locations = (
                                    df_map_base[['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer', 'A__ProductName']]
                                    .dropna(subset=['E__ManuPlant'])
                                    .drop_duplicates()
                                )
                                # Build a compact product list per plant (show first N, then ellipsis)
                                _prod_map: dict[tuple[str, str, str], set[str]] = {}
                                try:
                                    for r in df_locations.itertuples(index=False):
                                        plant = str(getattr(r, 'E__ManuPlant', '')).strip()
                                        country = str(getattr(r, 'E__ManuCountry', '')).strip()
                                        manu = str(getattr(r, 'A__Manufacturer', '')).strip()
                                        prod = str(getattr(r, 'A__ProductName', '')).strip()
                                        if not plant or plant == "-":
                                            continue
                                        if not prod or prod == "-":
                                            continue
                                        k = (plant, country, manu)
                                        s = _prod_map.get(k)
                                        if s is None:
                                            s = set()
                                            _prod_map[k] = s
                                        s.add(prod)
                                except Exception:
                                    _prod_map = {}
                                rows = []
                                # zip over the columns (all four are selected above) instead of
                                # iterrows, which builds a Series per row.
                                for _plant_raw, _country_raw, _manu_raw in zip(
                                    df_locations['E__ManuPlant'], df_locations['E__ManuCountry'],
                                    df_locations['A__Manufacturer'],
                                ):
                                    plant = _clean_geo_field(_plant_raw)
                                    country = _clean_geo_field(_country_raw)
                                    manu = str(_manu_raw).strip()
                                    coords = fn115_geocode_location(plant, country if country else None)
                                    if coords:
                                        lat, lon = coords
                                        prods = sorted(_prod_map.get((plant, country, manu), set()))
                                        # Escape to avoid breaking tooltip HTML
                                        prods = [_html.escape(p) for p in prods]
                                        prods_disp = ", ".join(prods[:12]) + (" …" if len(prods) > 12 else "")
                                        rows.append({
                                            "lat": lat,
                                            "lon": lon,
                                            "Plant": plant,
                                            "Country": country,
                                            "Manufacturer": manu,
                                            "Products": prods_disp,
                                        })
                                locations_df = pd.DataFrame(rows)

                                # Add GWP per plant (average across all filtered products)
                                if gwp_col and not locations_df.empty:
                                    try:
                                        df_tmp = df_map_base[['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer', gwp_col]].copy()
                                        df_tmp[gwp_col] = pd.to_numeric(df_tmp[gwp_col], errors='coerce')
                                        df_gwp = (
                                            df_tmp.dropna(subset=[gwp_col])
                                            .groupby(['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer'], as_index=False)[gwp_col]
                                            .mean()
                                            .rename(columns={
                                                'E__ManuPlant': 'Plant',
                                                'E__ManuCountry': 'Country',
                                                'A__Manufacturer': 'Manufacturer',
                                                gwp_col: 'GWP'
                                            })
                                        )
                                        locations_df = locations_df.merge(df_gwp, on=['Plant', 'Country', 'Manufacturer'], how='left')
                                    except Exception:
                                        pass
                            else:
                                # Compute locations after selection (prefer precomputed cache if available)
                                cached_map = st.session_state.get("LOCATIONS_BY_BASE_PRODUCT", {})
                                if isinstance(cached_map, dict) and selected_base in cached_map:
                                    locations_df = cached_map[selected_base].copy()
                                else:
                                    locations_df = fn118_get_locations_for_base_product(df_map_base, selected_base)
                                    if locations_df is not None and not locations_df.empty:
                                        try:
                                            st.session_state["LOCATIONS_BY_BASE_PRODUCT"][selected_base] = locations_df.copy()
                                        except Exception:
                                            pass

                                # Add GWP values per plant (average) and label for display
                                if gwp_col and locations_df is not None and not locations_df.empty:
                                    try:
                                        df_selected = df_map_base[df_map_base['A__ProductName_Base'] == selected_base].copy()
                                        df_selected[gwp_col] = pd.to_numeric(df_selected[gwp_col], errors='coerce')
                                        df_gwp = (
                                            df_selected.dropna(subset=[gwp_col])
                                            .groupby(['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer'], as_index=False)[gwp_col]
                                            .mean()
                                            .rename(columns={
                                                'E__ManuPlant': 'Plant',
                                                'E__ManuCountry': 'Country',
                                                'A__Manufacturer': 'Manufacturer',
                                                gwp_col: 'GWP'
                                            })
                                        )
                                        locations_df = locations_df.merge(df_gwp, on=['Plant', 'Country', 'Manufacturer'], how='left')
                                    except Exception:
                                        pass

                            # Create label string for map (if GWP exists)
                            try:
                                if locations_df is not None and not locations_df.empty:
                                    def _fmt(v):
                                        try:
                                            if pd.isna(v):
                                                return ""
                                            return f"{float(v):.1f}"
                                        except Exception:
                                            return ""
                                    if 'GWP' in locations_df.columns:
                                        # Round for display (requested: 1 decimal)
                                        try:
                                            locations_df['GWP'] = pd.to_numeric(locations_df['GWP'], errors='coerce').round(1)
                                        except Exception:
                                            pass
                                        locations_df['GWP_Label'] = locations_df['GWP'].apply(_fmt)
                                    else:
                                        locations_df['GWP'] = pd.NA
                                        locations_df['GWP_Label'] = ""
                            except Exception:
                                pass

                            if locations_df is None or locations_df.empty:
                                with col_left:
                                    if not dup_bases:
                                        st.info("No products with multiple manufacturing plants found in current filters.")
                                    else:
                                        st.info("No geocoding data available for the current selection.")

                            # The pydeck map is only shown when there is no EN206 split (or the
                            # Plotly map fails), so it is built on demand instead of on every run.
                            def _build_product_map_deck():
                                # Color-code markers by UNI/PdR 176 GWP bands
                                try:
                                    bands = fn205_get_gwp_class_bands()
                                    def _rgba_to_array(rgba: str):
                                        vals = rgba.strip().lower().replace('rgba(', '').replace(')', '').split(',')
                                        r = int(vals[0]); g = int(vals[1]); b = int(vals[2]); a = float(vals[3])
                                        return [r, g, b, max(0, min(255, int(round(a * 255))))]  # pydeck expects 0-255
                                    thresholds = [float(b['max_value']) for b in bands]
                                    colors = [_rgba_to_array(b['color']) for b in bands]
                                    def _color_for_value(v):
                                        try:
                                            if v is None or (isinstance(v, float) and pd.isna(v)):
                                                return [160, 160, 160, 160]
                                            v = float(v)
                                            for i, t in enumerate(thresholds):
                                                if v <= t:
                                                    return colors[i]
                                            return colors[-1]
                                        except Exception:
                                            return [160, 160, 160, 160]
                                    locations_df['color'] = locations_df['GWP'].apply(_color_for_value)
                                    def _outline(c):
                                        try:
                                            r, g, b, a = c
                                            return [max(0, r - 40), max(0, g - 40), max(0, b - 40), min(255, a + 20)]
                                        except Exception:
                                            return [80, 80, 80, 200]
                                    locations_df['line_color'] = locations_df['color'].apply(_outline)
                                except Exception:
                                    locations_df['color'] = [[0, 122, 204, 160]] * len(locations_df)
                                    locations_df['line_color'] = [[0, 82, 164, 200]] * len(locations_df)

                                # Prepare view and layer - center on geometric center of Italy
                                center_lat, center_lon = 42.1, 12.5
                                view_state = pdk.ViewState(
                                    latitude=center_lat,
                                    longitude=center_lon,
                                    zoom=4.7,
                                    pitch=0,
                                    bearing=0
                                )
                                layer = pdk.Layer(
                                    "ScatterplotLayer",
                                    data=locations_df,
                                    get_position='[lon, lat]',
                                    get_fill_color='color',
                                    get_line_color='line_color',
                                    get_radius=5,      # Circle radius (meters)
                                    radius_units='meters',
                                    stroked=True,
                                    line_width_min_pixels=1,
                                    pickable=True
                                )
                                # Text overlay (GWP labels) temporarily disabled to avoid TextLayer issues
                                # Match Plotly chart typography (Charts tab) with a smaller tooltip size
                                _tooltip_font_family = _ch_dims["chart_font_family"]
                                _tooltip_style = {
                                    "backgroundColor": "white",
                                    "color": "black",
                                    "fontFamily": _tooltip_font_family,
                                    "fontSize": "10px",
                                    "padding": "6px",
                                }
                                if st.session_state.get("charts_map_all_products_toggle", True):
                                    tooltip = {
                                        "html": "<b>{Manufacturer}</b><br/>{Plant} ({Country})<br/><span style='opacity:0.85'>Products:</span> {Products}",
                                        "style": _tooltip_style
                                    }
                                else:
                                    tooltip = {
                                        "html": "<b>{Manufacturer}</b><br/>{Plant} ({Country})<br/>GWP: {GWP}",
                                        "style": _tooltip_style
                                    }
                                # Use module-level cached Mapbox resolver (no live HTTP call)
                                mapbox_token, mapbox_style = fn006_resolve_mapbox()
                                map_style_url = MAP_STYLE_URL
                                deck_kwargs = {
                                    "layers": [layer],
                                    "initial_view_state": view_state,
                                    "tooltip": tooltip,
                                    "map_style": map_style_url
                                }
                                if MAP_API_KEYS:
                                    deck_kwargs["api_keys"] = MAP_API_KEYS
                                return pdk.Deck(**deck_kwargs)
                            with col_right:
                                # radio_col, cap_col = st.columns([5, 5])
                                # with radio_col:
                                #     style_choice = st.radio(
                                #         "Basemap Style",
                                #         options=_style_options,
                                #         index=0,
                                #         horizontal=True,
                                #         key="charts_map_style_choice"
                                #     )
                                # with cap_col:
                                #     st.markdown("")
                                #     st.caption(f"Chosen basemap style: {map_style_url}")
                    
                                # Custom slim divider at half width with minimal spacing
                                fn304_slim_divider(width="50%", margin_top="4px", margin_bottom="4px")
                                # Small legend for GWP band colors (avoid leading whitespace so HTML isn't shown as code)
                                try:
                                    _bands = fn205_get_gwp_class_bands()
                                    _items_html = ''.join([
                                        f'<div style="display:flex;align-items:center;margin-right:18px;margin-bottom:4px;">'
                                        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{_b["color"]};border:1px solid rgba(0,0,0,0.2);margin-right:6px;"></span>'
                                        f'<span style="font-size:10px;color:#444;">{_b["class"]}</span>'
                                        f'</div>'
                                        for _b in _bands
                                    ])
                                    st.markdown(
                                        f'<div style="display:flex;flex-wrap:wrap;align-items:center;margin-bottom:6px;">{_items_html}</div>',
                                        unsafe_allow_html=True
                                    )
                                except Exception:
                                    pass

                                # If EN206 resistance classes are available, show a Plotly map with an embedded dropdown
                                # (same UX pattern as the CHARTS tab dropdown), otherwise fall back to pydeck.
                                try:
                                    # Use shared EN206 normaliser (fn213_normalize_en206_class from fn__libs)
                                    # Scope EN206 slicing to the current Product Map scope (all products vs selected base)
                                    df_scope_for_en206 = df_map_base if all_products_mode else df_map_base[df_map_base['A__ProductName_Base'] == selected_base]
                                    should_split_by_en206_map = 'D__EN206' in df_scope_for_en206.columns
                                    en206_values = []
                                    if should_split_by_en206_map:
                                        tmp = df_scope_for_en206['D__EN206'].dropna().astype(str).str.strip()
                                        tmp = tmp[tmp.str.lower() != 'nan']
                                        if len(tmp) > 0:
                                            df_scope_for_en206 = df_scope_for_en206.copy()
                                            df_scope_for_en206['D__EN206_Normalized'] = df_scope_for_en206['D__EN206'].apply(fn213_normalize_en206_class)
                                            en206_values = sorted({
                                                v for v in df_scope_for_en206['D__EN206_Normalized'].dropna().astype(str).str.strip().tolist()
                                                if v and str(v).lower() != 'nan'
                                            })
                                        should_split_by_en206_map = len(en206_values) > 0

                                    if should_split_by_en206_map:
                                        # Helper: build per-class locations (plant/country/manufacturer) with coords and optional products list
                                        def _build_locations_for_map(df_sub: pd.DataFrame) -> pd.DataFrame:
                                            cols_needed = ['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer']
                                            if 'A__ProductName' in df_sub.columns:
                                                cols_needed.append('A__ProductName')
                                            df_l = df_sub[cols_needed].dropna(subset=['E__ManuPlant']).copy()
                                            # average GWP (prefer m³ if available as configured earlier)
                                            if gwp_col and gwp_col in df_sub.columns:
                                                df_g = df_sub[['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer', gwp_col]].copy()
                                                df_g[gwp_col] = pd.to_numeric(df_g[gwp_col], errors='coerce')
                                                df_gwp2 = (
                                                    df_g.dropna(subset=[gwp_col])
                                                    .groupby(['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer'], as_index=False)[gwp_col]
                                                    .mean()
                                                    .rename(columns={
                                                        'E__ManuPlant': 'Plant',
                                                        'E__ManuCountry': 'Country',
                                                        'A__Manufacturer': 'Manufacturer',
                                                        gwp_col: 'GWP'
                                                    })
                                                )
                                            else:
                                                df_gwp2 = pd.DataFrame(columns=['Plant', 'Country', 'Manufacturer', 'GWP'])

                                            # Products list (compact)
                                            prod_map = {}
                                            if 'A__ProductName' in df_l.columns:
                                                for r in df_l[['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer', 'A__ProductName']].itertuples(index=False):
                                                    plant = str(r[0]).strip()
                                                    country = str(r[1]).strip()
                                                    manu = str(r[2]).strip()
                                                    prod = str(r[3]).strip()
                                                    if not plant or plant == "-" or not prod or prod == "-":
                                                        continue
                                                    k = (plant, country, manu)
                                                    prod_map.setdefault(k, set()).add(prod)

                                            unique_pairs = (
                                                df_l[['E__ManuPlant', 'E__ManuCountry', 'A__Manufacturer']]
                                                .drop_duplicates()
                                                .values.tolist()
                                            )
                                            rows = []
                                            for plant, country, manu in unique_pairs:
                                                plant_s = _clean_geo_field(plant)
                                                country_s = _clean_geo_field(country)
                                                manu_s = str(manu).strip()
                                                coords = fn115_geocode_location(plant_s, country_s if country_s else None)
                                                if not coords:
                                                    continue
                                                lat, lon = coords
                                                prods = sorted(prod_map.get((plant_s, country_s, manu_s), set()))
                                                prods = [_html.escape(p) for p in prods]
                                                prods_disp = ", ".join(prods[:12]) + (" …" if len(prods) > 12 else "")
                                                rows.append({
                                                    "lat": lat,
                                                    "lon": lon,
                                                    "Plant": plant_s,
                                                    "Country": country_s,
                                                    "Manufacturer": manu_s,
                                                    "Products": prods_disp,
                                                })
                                            out = pd.DataFrame(rows)
                                            if not out.empty and not df_gwp2.empty:
                                                out = out.merge(df_gwp2, on=['Plant', 'Country', 'Manufacturer'], how='left')
                                                try:
                                                    out['GWP'] = pd.to_numeric(out['GWP'], errors='coerce').round(1)
                                                except Exception:
                                                    pass
                                            return out

                                        # Build per-class location sets (All + each EN206)
                                        loc_by_class = {}
                                        loc_by_class["All"] = _build_locations_for_map(df_scope_for_en206)
                                        for v in en206_values:
                                            df_sub = df_scope_for_en206[df_scope_for_en206['D__EN206_Normalized'].astype(str).str.strip() == v]
                                            if df_sub.empty:
                                                continue
                                            loc_by_class[v] = _build_locations_for_map(df_sub)

                                        # Color by GWP class bands (like other views)
                                        bands = fn205_get_gwp_class_bands()
                                        thresholds = [float(b['max_value']) for b in bands]
                                        colors_rgba = [b['color'] for b in bands]
                                        def _color_for_gwp(v):
                                            try:
                                                if v is None or (isinstance(v, float) and pd.isna(v)):
                                                    return "rgba(160,160,160,0.6)"
                                                v = float(v)
                                                for i, t in enumerate(thresholds):
                                                    if v <= t:
                                                        return colors_rgba[i]
                                                return colors_rgba[-1]
                                            except Exception:
                                                return "rgba(160,160,160,0.6)"

                                        # Build Plotly figure with dropdown
                                        fig_map = go.Figure()
                                        trace_names = list(loc_by_class.keys())
                                        for idx, name in enumerate(trace_names):
                                            dfl = loc_by_class[name]
                                            if dfl is None or dfl.empty:
                                                # still add empty trace so dropdown remains stable
                                                fig_map.add_trace(go.Scattergeo(
                                                    lat=[],
                                                    lon=[],
                                                    mode="markers",
                                                    name=name,
                                                    visible=(idx == 0),
                                                ))
                                                continue
                                            marker_colors = [_color_for_gwp(x) for x in (dfl['GWP'] if 'GWP' in dfl.columns else [None] * len(dfl))]
                                            # Row-wise hover data from whole columns (iterrows built a
                                            # Series per row); a missing column falls back to '' as before.
                                            customdata = [
                                                list(_vals) for _vals in zip(*[
                                                    dfl[_c].tolist() if _c in dfl.columns else [''] * len(dfl)
                                                    for _c in ('Manufacturer', 'Plant', 'Country', 'GWP', 'Products')
                                                ])
                                            ]
                                            fig_map.add_trace(go.Scattergeo(
                                                lat=dfl["lat"],
                                                lon=dfl["lon"],
                                                mode="markers",
                                                name=name,
                                                visible=(idx == 0),
                                                marker=dict(size=8, color=marker_colors, line=dict(color="rgba(0,0,0,0.25)", width=0.5)),
                                                customdata=customdata,
                                                hovertemplate=(
                                                    "<b>%{customdata[0]}</b><br>"
                                                    "%{customdata[1]} (%{customdata[2]})<br>"
                                                    "EN206: " + name + "<br>"
                                                    "GWP: %{customdata[3]}<br>"
                                                    "<span style='opacity:0.85'>Products:</span> %{customdata[4]}<extra></extra>"
                                                ),
                                            ))

                                        buttons = []
                                        for i, name in enumerate(trace_names):
                                            visible = [False] * len(trace_names)
                                            visible[i] = True
                                            title_suffix = "" if name == "All" else f" | EN206: {name}"
                                            buttons.append(dict(
                                                label=name,
                                                method="update",
                                                args=[
                                                    {"visible": visible},
                                                    {"title": f"Product Map{title_suffix}"},
                                                ],
                                            ))

                                        fig_map.update_layout(
                                            title="Product Map",
                                            margin=dict(l=0, r=0, t=40, b=0),
                                            font=dict(family=_ch_dims["chart_font_family"], size=_ch_dims["chart_font_size"]),
                                            hoverlabel=dict(font=dict(family=_ch_dims["chart_font_family"], size=_ch_dims["chart_annotation_size"])),
                                            updatemenus=[dict(
                                                buttons=buttons,
                                                direction="down",
                                                showactive=True,
                                                x=0.0,
                                                xanchor="left",
                                                y=1.12,
                                                yanchor="top",
                                            )],
                                        )
                                        fig_map.update_geos(
                                            fitbounds="locations",
                                            showcountries=True,
                                            showland=True,
                                            landcolor="rgb(245,245,245)",
                                            coastlinecolor="rgb(200,200,200)",
                                            projection_type="natural earth",
                                        )

                                        st.plotly_chart(fig_map, width='stretch')
                                        st.caption("Use the dropdown to view results for each EN206 resistance class.")
                                    else:
                                        st.pydeck_chart(_build_product_map_deck(), width='stretch', height=550)
                                except Exception:
                                    st.pydeck_chart(_build_product_map_deck(), width='stretch', height=550)
                            with col_left:
                                # st.markdown("###### Locations")
                                # Reorder and rename columns for display
                                desired_cols = ['Manufacturer', 'Country', 'Plant', 'GWP']
                                show_cols = [c for c in desired_cols if c in locations_df.columns]
                                df_table = locations_df[show_cols].copy()
                                # Remove A__Map_yn column if present (shouldn't be, but just in case)
                                if "A__Map_yn" in df_table.columns:
                                    df_table = df_table.drop(columns=["A__Map_yn"])
                                if 'GWP' in df_table.columns:
                                    # Ensure 1-decimal rounding and required unit label
                                    try:
                                        df_table['GWP'] = pd.to_numeric(df_table['GWP'], errors='coerce').round(1)
                                    except Exception:
                                        pass
                                    df_table = df_table.rename(columns={'GWP': 'GWP (A1-A3) kgCO2e/m3'})
                                st.dataframe(df_table, height=530)
        
                    # ========== TAB 2: Product Map 2 (multiple base products) ==========
                    if map_tab2.open:
                        with map_tab2:
                            st.markdown("###### 🗺️ Product Map 2")
                            st.caption("Fast view: one interactive map + a 4-column grid of static mini-maps to browse.")
                    
                            df_map_base = df_map  # Base product column already computed on df_filtered above; reuse directly
                            if 'E__ManuCountry' not in df_map_base.columns:
                                df_map_base['E__ManuCountry'] = ""
                    
                            # Base products with multiple plants (same cached helper as Product Map)
                            dup_bases = _maps_multi_plant_bases(_maps_data_fp, _maps_filter_sig, df_map_base)
                    
                            if not dup_bases:
                                st.info("No products with multiple manufacturing plants found in current filters.")
                            else:
                                # (1) One interactive map (WebGL) for the selected base product
                                selected_base2 = st.selectbox(
                                    "Select a base product",
                                    dup_bases,
                                    index=0,
                                    key="product_map2_selected_base",
                                )

                                cached_map = st.session_state.get("LOCATIONS_BY_BASE_PRODUCT", {})
                                if isinstance(cached_map, dict) and selected_base2 in cached_map:
                                    locations_df2 = cached_map[selected_base2].copy()
                                else:
                                    locations_df2 = fn118_get_locations_for_base_product(df_map_base, selected_base2)
                                    if locations_df2 is not None and not locations_df2.empty:
                                        try:
                                            st.session_state["LOCATIONS_BY_BASE_PRODUCT"][selected_base2] = locations_df2.copy()
                                        except Exception:
                                            pass

                                if locations_df2 is None or locations_df2.empty:
                                    st.warning("No cached geocoding data for the selected base product.")
                                else:
                                    try:
                                        center_lat = float(locations_df2['lat'].mean())
                                        center_lon = float(locations_df2['lon'].mean())
                                    except Exception:
                                        center_lat, center_lon = 42.1, 12.5

                                    view_state = pdk.ViewState(
                                        latitude=center_lat,
                                        longitude=center_lon,
                                        zoom=4.7,
                                        pitch=0,
                                        bearing=0
                                    )

                                    layer = pdk.Layer(
                                        "ScatterplotLayer",
                                        data=locations_df2,
                                        get_position='[lon, lat]',
                                        get_fill_color=[0, 122, 204, 160],
                                        get_line_color=[0, 82, 164, 220],
                                        get_radius=6,
                                        radius_units='meters',
                                        stroked=True,
                                        line_width_min_pixels=1,
                                        pickable=True
                                    )

                                    tooltip = {
                                        "html": "<b>{Manufacturer}</b><br/>{Plant} ({Country})",
                                        "style": {"backgroundColor": "white", "color": "black"}
                                    }

                                    deck_kwargs = {
                                        "layers": [layer],
                                        "initial_view_state": view_state,
                                        "tooltip": tooltip,
                                        "map_style": MAP_STYLE_URL
                                    }
                                    if MAP_API_KEYS:
                                        deck_kwargs["api_keys"] = MAP_API_KEYS

                                    st.pydeck_chart(pdk.Deck(**deck_kwargs), width='stretch', height=420)

                                st.markdown("---")

                                # (2) Static mini-maps grid + “Open” buttons, as a fragment so the
                                # slider only re-renders the grid (see _maps_pm2_grid).
                                _maps_pm2_grid(df_map_base, dup_bases)

                    # ========== TAB 3: All products per plant ==========
                    if map_tab3.open:
                        with map_tab3:
                            st.markdown("###### 🏭 All products per plant")
                            df_map_base = df_map  # Base product column already computed on df_filtered above; reuse directly
                            if 'E__ManuCountry' not in df_map_base.columns:
                                df_map_base['E__ManuCountry'] = ""
                
                            # Get all unique plants
                            unique_plants = (
                                df_map_base[['E__ManuPlant', 'E__ManuCountry']]
                                .dropna(subset=['E__ManuPlant'])
                                .drop_duplicates()
                                .sort_values(['E__ManuPlant', 'E__ManuCountry'])
                            )
                
                            if unique_plants.empty:
                                st.info("No manufacturing plants found in current filters.")
                            else:
                                # Create plant selection with plant and country
                                plant_options = []
                                plant_dict = {}
                                for _plant_raw, _country_raw in zip(
                                    unique_plants['E__ManuPlant'], unique_plants['E__ManuCountry'],
                                ):
                                    plant = str(_plant_raw).strip()
                                    country = str(_country_raw).strip()
                                    if country:
                                        display = f"{plant} ({country})"
                                    else:
                                        display = plant
                                    plant_options.append(display)
                                    plant_dict[display] = (plant, country)
                    
                                # Layout: Selectbox and map side by side
                                col_select, col_map_small = st.columns([3, 2], gap="medium")
                    
                                with col_select:
                                    selected_plant_display = st.selectbox(
                                        "Select a manufacturing plant",
                                        plant_options,
                                        index=0,
                                        key="charts_map_selected_plant"
                                    )
                                    selected_plant, selected_country = plant_dict[selected_plant_display]
                    
                                # Get all products for this plant
                                products_df = fn119_get_all_products_for_plant(
                                    df_map_base, 
                                    selected_plant, 
                                    selected_country
                                )
                    
                                if products_df.empty:
                                    st.info("No products found for this plant or no geocoding data for this location.")
                                else:
                                    # Add GWP values per product
                                    try:
                                        gwp_candidates = [
                                            'G__GWP_A1A3',
                                            'G__GWP_A1A3_m3',
                                            'G__GWP_A1A3_Total',
                                            'G__GWP_Total'
                                        ]
                                        df_plant_products = df_map_base[
                                            (df_map_base['E__ManuPlant'].astype(str).str.strip() == selected_plant) &
                                            (df_map_base['E__ManuCountry'].astype(str).str.strip() == selected_country if selected_country else True)
                                        ].copy()
                            
                                        gwp_col = next((c for c in gwp_candidates if c in df_plant_products.columns), None)
                                        if gwp_col:
                                            df_plant_products[gwp_col] = pd.to_numeric(df_plant_products[gwp_col], errors='coerce')
                                            # Group by product to average GWP
                                            df_gwp = (
                                                df_plant_products.dropna(subset=[gwp_col])
                                                .groupby(['A__ProductName', 'A__ProductName_Base', 'A__Manufacturer'], as_index=False)[gwp_col]
                                                .mean()
                                                .rename(columns={
                                                    'A__ProductName': 'Product',
                                                    'A__ProductName_Base': 'Product_Base',
                                                    'A__Manufacturer': 'Manufacturer',
                                                    gwp_col: 'GWP'
                                                })
                                            )
                                            # Merge into products_df
                                            products_df = products_df.merge(
                                                df_gwp, 
                                                on=['Product', 'Product_Base', 'Manufacturer'], 
                                                how='left'
                                            )
                                            # Create label string for map
                                            def _fmt(v):
                                                try:
                                                    if pd.isna(v):
                                                        return ""
                                                    v = float(v)
                                                    return f"{v:.1f}"
                                                except Exception:
                                                    return ""
                                            products_df['GWP_Label'] = products_df['GWP'].apply(_fmt)
                                        else:
                                            products_df['GWP'] = pd.NA
                                            products_df['GWP_Label'] = ""
                                    except Exception:
                                        products_df['GWP'] = pd.NA
                                        products_df['GWP_Label'] = ""
                        
                                    # Build comparison data for bar charts
                                    # Find other plants that produce the same products
                                    product_bases = products_df['Product_Base'].unique().tolist()
                        
                                    # Main app color for selected plant
                                    MAIN_COLOR = "#007acc"  # Blue color
                                    OTHER_COLOR = "#C0C0C0"  # Light grey color
                        
                                    # Prepare comparison data for each product
                                    comparison_data = []
                                    if product_bases and gwp_col:
                                        for product_base in product_bases:
                                            # Get GWP for selected plant
                                            selected_plant_data = products_df[
                                                (products_df['Product_Base'] == product_base) &
                                                (products_df['Plant'].astype(str).str.strip() == selected_plant)
                                            ]
                                
                                            if not selected_plant_data.empty and not pd.isna(selected_plant_data['GWP'].iloc[0]):
                                                selected_gwp = float(selected_plant_data['GWP'].iloc[0])
                                                product_name = selected_plant_data['Product'].iloc[0]
                                    
                                                # Get GWP for other plants producing the same product
                                                other_plants_data = df_map_base[
                                                    (df_map_base['A__ProductName_Base'] == product_base) &
                                                    ~((df_map_base['E__ManuPlant'].astype(str).str.strip() == selected_plant) &
                                                      (df_map_base['E__ManuCountry'].astype(str).str.strip() == selected_country if selected_country else True))
                                                ].copy()
                                    
                                                if not other_plants_data.empty and gwp_col in other_plants_data.columns:
                                                    other_plants_data[gwp_col] = pd.to_numeric(other_plants_data[gwp_col], errors='coerce')
                                                    other_gwp_data = (
                                                        other_plants_data.dropna(subset=[gwp_col])
                                                        .groupby(['E__ManuPlant', 'E__ManuCountry'], as_index=False)[gwp_col]
                                                        .mean()
                                                    )
                                        
                                                    # Build data for this product
                                                    plant_names = [f"{selected_plant} ({selected_country})" if selected_country else selected_plant]
                                                    gwp_values = [selected_gwp]
                                                    colors_list = [MAIN_COLOR]
                                        
                                                    for _op_raw, _oc_raw, _og_raw in zip(
                                                        other_gwp_data['E__ManuPlant'],
                                                        other_gwp_data['E__ManuCountry'],
                                                        other_gwp_data[gwp_col],
                                                    ):
                                                        other_plant = str(_op_raw).strip()
                                                        other_country = str(_oc_raw).strip()
                                                        other_gwp = float(_og_raw)
                                                        plant_display = f"{other_plant} ({other_country})" if other_country else other_plant
                                                        plant_names.append(plant_display)
                                                        gwp_values.append(other_gwp)
                                                        colors_list.append(OTHER_COLOR)
                                        
                                                    comparison_data.append({
                                                        'product': product_name,
                                                        'product_base': product_base,
                                                        'plants': plant_names,
                                                        'gwp_values': gwp_values,
                                                        'colors': colors_list
                                                    })
                        
                                    # Prepare view and layer for map (small map next to selectbox)
                                    with col_map_small:
                                        if not products_df.empty:
                                            center_lat = products_df['lat'].iloc[0]
                                            center_lon = products_df['lon'].iloc[0]
                                        else:
                                            center_lat, center_lon = 42.1, 12.5
                            
                                        view_state = pdk.ViewState(
                                            latitude=center_lat,
                                            longitude=center_lon,
                                            zoom=8,
                                            pitch=0,
                                            bearing=0
                                        )
                            
                                        # Simple marker for the plant location
                                        layer = pdk.Layer(
                                            "ScatterplotLayer",
                                            data=products_df.drop_duplicates(subset=['lat', 'lon']).head(1),
                                            get_position='[lon, lat]',
                                            get_fill_color=[0, 122, 204, 200],
                                            get_line_color=[0, 82, 164, 255],
                                            get_radius=5,
                                            radius_units='meters',
                                            stroked=True,
                                            line_width_min_pixels=2,
                                            pickable=True
                                        )
                            
                                        tooltip = {
                                            "html": "<b>{Plant}</b><br/>{Country}",
                                            "style": {"backgroundColor": "white", "color": "black"}
                                        }
                            
                                        # Resolve mapbox credentials
                                        # Use module-level cached Mapbox resolver (no live HTTP call)
                                        mapbox_token, mapbox_style = fn006_resolve_mapbox()
                                        map_style_url = MAP_STYLE_URL
                            
                                        deck_kwargs = {
                                            "layers": [layer],
                                            "initial_view_state": view_state,
                                            "tooltip": tooltip,
                                            "map_style": map_style_url
                                        }
                                        if MAP_API_KEYS:
                                            deck_kwargs["api_keys"] = MAP_API_KEYS
                                        deck = pdk.Deck(**deck_kwargs)
                            
                                        st.markdown("**Plant Location**")
                                        st.pydeck_chart(deck, width='stretch', height=150)
                        
                                    # Bar charts for each product
                                    if comparison_data:
                                        st.markdown("---")
                            
                                        # Chart configuration
                                        CHART_HEIGHT_BASE = 200  # Base height in pixels
                                        CHART_HEIGHT_PER_PLANT = 12  # Additional height per plant
                            
                                        # Sorting options
                                        sort_options = {
                                            "Alphabetical (A-Z)": "alphabetical_asc",
                                            "Alphabetical (Z-A)": "alphabetical_desc",
                                            "GWP: Low to High": "value_asc",
                                            "GWP: High to Low": "value_desc"
                                        }
                            
                                        col_title, col_sort = st.columns([3, 1])
                                        with col_title:
                                            st.markdown("###### GWP Comparison by Product")
                                        with col_sort:
                                            sort_method = st.selectbox(
                                                "Sort bars",
                                                options=list(sort_options.keys()),
                                                index=3,  # Default to "GWP: High to Low"
                                                key="charts_map_plant_sort_method"
                                            )
                            
                                        # Apply sorting to each product's data
                                        sorted_comparison_data = []
                                        for data in comparison_data:
                                            # Create list of tuples for sorting
                                            items = list(zip(data['plants'], data['gwp_values'], data['colors']))
                                
                                            # Sort based on selected method
                                            if sort_options[sort_method] == "alphabetical_asc":
                                                items.sort(key=lambda x: x[0].lower())
                                            elif sort_options[sort_method] == "alphabetical_desc":
                                                items.sort(key=lambda x: x[0].lower(), reverse=True)
                                            elif sort_options[sort_method] == "value_asc":
                                                items.sort(key=lambda x: x[1])
                                            elif sort_options[sort_method] == "value_desc":
                                                items.sort(key=lambda x: x[1], reverse=True)
                                
                                            # Unpack sorted items
                                            sorted_plants, sorted_gwp, sorted_colors = zip(*items)
                                
                                            # Clean up plant labels - remove "(Italy)" if all labels have it
                                            plant_labels = list(sorted_plants)
                                            if plant_labels:
                                                # Check if all labels end with " (Italy)"
                                                all_have_italy = all(label.endswith(" (Italy)") for label in plant_labels)
                                                if all_have_italy:
                                                    # Remove " (Italy)" from all labels
                                                    plant_labels = [label.replace(" (Italy)", "") for label in plant_labels]
                                
                                            sorted_comparison_data.append({
                                                'product': data['product'],
                                                'product_base': data['product_base'],
                                                'plants': plant_labels,
                                                'gwp_values': list(sorted_gwp),
                                                'colors': list(sorted_colors)
                                            })
                            
                                        num_products = len(sorted_comparison_data)
                                
                                        if num_products == 0:
                                            st.info("No GWP data available for comparison charts.")
                                        else:
                                            # Grid layout (4 charts per row) instead of arrows/carousel
                                            MAX_COLS_PER_ROW = 4
                                            cols_per_row = min(num_products, MAX_COLS_PER_ROW)
                                    
                                            for i in range(0, num_products, cols_per_row):
                                                chart_cols = st.columns(cols_per_row, gap="medium")
                                                for j, col in enumerate(chart_cols):
                                                    if i + j >= num_products:
                                                        continue
                                                    with col:
                                                        data = sorted_comparison_data[i + j]
                                                
                                                        fig = go.Figure()
                                                        fig.add_trace(go.Bar(
                                                            x=data['gwp_values'],
                                                            y=data['plants'],
                                                            orientation='h',
                                                            marker=dict(color=data['colors']),
                                                            text=[f"{gwp:.1f}" for gwp in data['gwp_values']],
                                                            textposition='outside',
                                                            showlegend=False
                                                        ))
                                                
                                                        chart_height = CHART_HEIGHT_BASE + (len(data['plants']) * CHART_HEIGHT_PER_PLANT)
                                                        fig.update_layout(
                                                            title=f"{data['product']}",
                                                            xaxis_title="GWP (A1-A3)",
                                                            yaxis_title="",
                                                            height=chart_height,
                                                            margin=dict(l=10, r=10, t=40, b=10),
                                                            xaxis=dict(showgrid=True, gridcolor='lightgrey', range=[0, 500]),
                                                            yaxis=dict(showgrid=False),
                                                            plot_bgcolor='white'
                                                        )
                                                
                                                        st.plotly_chart(fig, width='stretch')
                                    else:
                                        st.info("No GWP data available for comparison charts.")
        
        # Manufacturing Maps tab intentionally hidden/disabled






    # --- Quick pydeck demo (opt-in; rendering extra maps slows down the page) ---
    st.markdown("---")
    # Basemap picker (moved to bottom as requested)
    _chosen = st.radio(
        "Basemap",
        ["Carto (no token)", "Mapbox"],
        index=0 if st.session_state.get("maps_basemap_choice", "Carto (no token)") != "Mapbox" else 1,
        horizontal=True,
        key="maps_basemap_choice",
    )
    if _basemap_warning:
        st.caption(_basemap_warning)
    with st.expander("🧪 Quick pydeck map demo", expanded=False, type="compact"):
        if st.checkbox("Render demo map", value=False, key="render_pydeck_demo"):
            demo_deck_kwargs = {
                "map_style": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
                "initial_view_state": pdk.ViewState(latitude=45, longitude=10, zoom=5),
                "layers": [
                    pdk.Layer(
                        "ScatterplotLayer",
                        data=[{"lat": 45, "lon": 10}],
                        get_position='[lon, lat]',
                        get_radius=10000,
                        get_fill_color=[0, 128, 255],
                    )
                ]
            }
            demo_deck = pdk.Deck(**demo_deck_kwargs)
            st.pydeck_chart(demo_deck, width='stretch', height=400)



