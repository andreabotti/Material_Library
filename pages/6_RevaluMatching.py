"""
pages/6_RevaluMatching.py  —  Revalu Partnership: EPD Registry Cross-Matching
==============================================================================
Finds online EPD documents for each product in the EETRA Material Library by
searching EPD registration numbers against:

  1. EPD International  (environdec.com)  — S-P-XXXXX numbers
  2. EPD Italy          (epditaly.it)     — Italian national registry
  3. IBU               (ibu-epd.com)      — German/European registry
  4. INIES             (inies.fr)         — French registry

For each product the page:
  • Shows current database status (has URL? valid? expired?)
  • Offers one-click "search" links for each registry
  • Parses registration number format to guess likely registry
  • Exports the full cross-match table as CSV for Revalu

Partnership context:
  Revalu (revalu.ai) is building an EPD data aggregation platform.
  EETRA provides curated Italian/European material data. This page is the
  data-handshake tool that identifies which products have publicly-findable
  EPDs online, enriching both databases.
"""

from libs.page_imports import *  # noqa: F401,F403
from libs.lib_header import fn003a_page_header
import urllib.parse
from libs.lib_data import (
    fn141_norm_epd_num    as _norm_epd_num,
    fn142_is_valid_epd_num as _is_valid_epd_num,
    fn143_build_matlib_epd_sets as _build_matlib_epd_sets,
    EPD_XML_REG_RE        as _REG_NUM_RE,
)

# ── Pull shared data from session state ─────────────────────────────────────
df_filtered = st.session_state.get("FILTERED_DATA", pd.DataFrame())
df_original = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())

_EMBED = st.session_state.get("_revalu_embedded_in_developer", False)

if not st.session_state.get("df_filtered_ready"):
    st.info("⏳ Data not yet loaded — navigate to the Welcome page first.")
    if not _EMBED:
        st.stop()

if st.session_state.get("df_filtered_ready"):
    # CSS injected globally via fn005_inject_global_css() in lib_header.py

    # ── Partnership banner ───────────────────────────────────────────────────────
    st.markdown("""
    <div class="revalu-banner">
      <div>
        <h2>🔗 Revalu × EETRA — EPD Registry Cross-Matching</h2>
        <p>Find published EPD documents online for every product in the EETRA Material Library.
        Matches EPD registration numbers against international and Italian EPD registries.
        Export matched data for integration into the Revalu platform.</p>
      </div>
      <div class="revalu-badge">Partnership Preview</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Determine working dataset ────────────────────────────────────────────────
    _epd_cols = ['E__EPD_RegNumber', 'E__EPD_DecNumber', 'E__EPD_URL',
                 'E__EPD_Publisher', 'E__EPD_IssueDate', 'E__EPD_ValidUntil', 'E__EPD_Type']
    _id_cols  = ['A__ProductName', 'A__Manufacturer', 'D__ProductType_ENG']

    # ── Build ECOportal UUID → reg-number lookup (XML-backed, cached 1h) ─────
    # Loads normalised registration numbers from the already-downloaded ILCD XML
    # files so we can show which MatLib products have a matching ECOportal entry.
    _ECO_NUMS: dict[str, list[str]] = {}   # UUID → [norm_num, ...]
    _ECO_NUM_TO_UUID: dict[str, str] = {}  # norm_num → UUID (first hit)
    try:
        from pathlib import Path as _Path
        _EETRA_ROOT = _Path(__file__).resolve().parents[2]
        _XML_DIR = _EETRA_ROOT / "ECOportal_Downloader" / "soda4lca" / "output" / "xml" / "processes"
        if _XML_DIR.is_dir():
            @st.cache_data(show_spinner=False, ttl=3600)
            def _eco_reg_scan(xml_dir: str, mtime: int) -> dict[str, str]:
                """Return normalised_num → UUID for all ECOportal XML files."""
                mapping: dict[str, str] = {}
                for xf in _Path(xml_dir).glob("*.xml"):
                    try:
                        txt = xf.read_text(encoding="utf-8", errors="replace")
                        for m in _REG_NUM_RE.finditer(txt):
                            raw = m.group(1).strip()
                            for tok in re.split(r'[\s\(\)]+', raw):
                                n = _norm_epd_num(tok)
                                if n and n not in mapping:
                                    mapping[n] = xf.stem
                    except Exception:
                        pass
                return mapping
            _dir_mtime = int(_XML_DIR.stat().st_mtime_ns)
            _ECO_NUM_TO_UUID = _eco_reg_scan(str(_XML_DIR), _dir_mtime)
    except Exception:
        pass

    if _EMBED:
        fn003a_page_header("Revalu Matching", icon="🔗", embedded=True)
        _dataset_choice = st.radio(
            "Dataset to analyse",
            ["All products (original)", "Filtered products only"],
            index=0,
            key="revalu_dataset",
        )
        _show_only = st.selectbox(
            "Show products",
            ["All", "Missing EPD URL (needs lookup)", "Has EPD number only",
             "Fully linked (URL present)", "Expired EPDs"],
            index=0,
            key="revalu_show_only",
        )
        fn303_custom_hr()
    else:
        with st.sidebar:
            fn303_custom_hr()
            st.markdown("#### Revalu Matching")
            _dataset_choice = st.radio(
                "Dataset to analyse",
                ["All products (original)", "Filtered products only"],
                index=0,
                key="revalu_dataset",
            )
            _show_only = st.selectbox(
                "Show products",
                ["All", "Missing EPD URL (needs lookup)", "Has EPD number only",
                 "Fully linked (URL present)", "Expired EPDs"],
                index=0,
                key="revalu_show_only",
            )
            fn303_custom_hr()

    df_work = df_original if _dataset_choice.startswith("All") else df_filtered

    # ── EPD column helpers ───────────────────────────────────────────────────────

    def _val(row, col, default="-"):
        """Safe row accessor."""
        v = row.get(col, default)
        return default if pd.isna(v) or str(v).strip() in ("", "-", "nan") else str(v).strip()


    def _classify_status(reg_num: str, url: str, valid_until: str) -> str:
        """Return one of: linked | number_only | missing | expired."""
        has_reg = reg_num not in ("-", "")
        has_url = url not in ("-", "")

        # Expired check: parse ValidUntil if it looks like a date
        if has_url and valid_until not in ("-", ""):
            try:
                import datetime as _dt
                # Accept YYYY-MM-DD, DD/MM/YYYY, DD.MM.YYYY
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"):
                    try:
                        exp = _dt.datetime.strptime(valid_until, fmt).date()
                        if exp < _dt.date.today():
                            return "expired"
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        if has_url:
            return "linked"
        if has_reg:
            return "number_only"
        return "missing"


    def _guess_registry(reg_num: str, publisher: str) -> list[str]:
        """Return probable registry codes based on registration number patterns.

        Covers all formats observed in the ECOportal + MatLib datasets:
          S-P-XXXXX / EPD-IES-...  → EPD International (Environdec)
          NEPD-XXXX-...            → EPD Norge / EPD International
          ECOP-...                 → EPD International
          EPD-IBU-... / IBU-...    → IBU (German/European)
          INIES-...                → INIES France
          EPDITALY... / IT...      → EPD Italy
          HUB-XXXX                 → EPD Hub
          (unmatched)              → offer all three main registries
        """
        rn  = str(reg_num).upper().strip()
        pub = str(publisher).upper().strip()
        guesses: list[str] = []

        # Environdec / EPD International
        if re.match(r'^S-P-', rn) or re.match(r'^EPD-IES-', rn) or re.match(r'^ECOP', rn):
            guesses.append("EPD International")
        # EPD Norway (routes through EPD International website)
        if re.match(r'^NEPD-?', rn) or re.match(r'^NEPD\d', rn):
            guesses.append("EPD International")
        # IBU (German / European)
        if re.match(r'^EPD-IBU', rn) or re.match(r'^IBU-', rn) or "IBU" in pub:
            guesses.append("IBU")
        # INIES (France)
        if re.match(r'^INIES', rn) or "INIES" in pub or "FRANCE" in pub:
            guesses.append("INIES")
        # EPD Italy
        if re.match(r'^IT', rn) or re.match(r'^EPDITALY', rn) or \
                "ITALY" in pub or "ITALIA" in pub or "EPD ITALY" in pub:
            guesses.append("EPD Italy")
        # EPD Hub (hub.epditaly.it)
        if re.match(r'^HUB-', rn):
            guesses.append("EPD Italy")   # hub is part of EPD Italy ecosystem

        # Deduplicate while preserving order
        seen: set[str] = set()
        guesses = [g for g in guesses if not (g in seen or seen.add(g))]  # type: ignore[func-returns-value]

        if not guesses:
            guesses = ["EPD International", "EPD Italy", "IBU"]
        return guesses


    def _build_search_urls(reg_num: str, product_name: str, manufacturer: str) -> dict[str, str]:
        """Build registry search URLs for a product."""
        q_prod = urllib.parse.quote(product_name[:60])
        q_manu = urllib.parse.quote(manufacturer[:40])
        q_reg  = urllib.parse.quote(reg_num)

        urls = {}

        # EPD International — direct lookup by reg number or search
        if reg_num and reg_num != "-":
            urls["EPD International"] = f"https://www.environdec.com/library?epd_id={q_reg}"
        else:
            urls["EPD International"] = (
                f"https://www.environdec.com/library?search={q_manu}+{q_prod}"
            )

        # EPD Italy — search
        if reg_num and reg_num != "-":
            urls["EPD Italy"] = f"https://www.epditaly.it/ricerca/?s={q_reg}"
        else:
            urls["EPD Italy"] = f"https://www.epditaly.it/ricerca/?s={q_manu}+{q_prod}"

        # IBU EPD
        urls["IBU"] = f"https://ibu-epd.com/en/epd-search/?epd_search={q_manu}"

        # INIES
        urls["INIES"] = f"https://www.inies.fr/recherche/?r={q_manu}+{q_prod}"

        return urls


    # ── Build analysis table ─────────────────────────────────────────────────────
    def build_epd_table(df: pd.DataFrame) -> pd.DataFrame:
        """Build per-product EPD status table with ECOportal cross-reference."""
        rows = []
        for _, row in df.iterrows():
            prod   = _val(row, 'A__ProductName')
            manu   = _val(row, 'A__Manufacturer')
            ptype  = _val(row, 'D__ProductType_ENG')
            reg    = _val(row, 'E__EPD_RegNumber')
            dec    = _val(row, 'E__EPD_DecNumber')   # declaration number (may differ)
            url    = _val(row, 'E__EPD_URL')
            pub    = _val(row, 'E__EPD_Publisher')
            issued = _val(row, 'E__EPD_IssueDate')
            valid  = _val(row, 'E__EPD_ValidUntil')
            etype  = _val(row, 'E__EPD_Type')

            status  = _classify_status(reg, url, valid)
            guesses = _guess_registry(reg, pub)

            # Normalise both EPD numbers for consistent matching
            reg_norm = _norm_epd_num(reg) if _is_valid_epd_num(reg) else None
            dec_norm = _norm_epd_num(dec) if _is_valid_epd_num(dec) else None

            # ECOportal cross-reference: check if either normalised number
            # is present in the XML-scanned registration number index.
            eco_uuid = None
            for _n in filter(None, [reg_norm, dec_norm]):
                eco_uuid = _ECO_NUM_TO_UUID.get(_n)
                if eco_uuid:
                    break
            in_ecoportal = eco_uuid is not None

            rows.append({
                'product_name':    prod,
                'manufacturer':    manu,
                'product_type':    ptype,
                'epd_reg_number':  reg,
                'epd_dec_number':  dec,
                'epd_reg_norm':    reg_norm or dec_norm or '-',
                'epd_url':         url,
                'epd_publisher':   pub,
                'epd_issued':      issued,
                'epd_valid_until': valid,
                'epd_type':        etype,
                'status':          status,
                'likely_registry': '; '.join(guesses),
                'in_ecoportal':    in_ecoportal,
                'eco_uuid':        eco_uuid or '-',
            })
        return pd.DataFrame(rows)


    df_epd = build_epd_table(df_work)

    # ── Filter by show_only ──────────────────────────────────────────────────────
    _filter_map = {
        "Missing EPD URL (needs lookup)": ["missing"],
        "Has EPD number only":            ["number_only"],
        "Fully linked (URL present)":     ["linked"],
        "Expired EPDs":                   ["expired"],
    }
    if _show_only in _filter_map:
        df_epd = df_epd[df_epd['status'].isin(_filter_map[_show_only])]

    # ── Summary metrics ──────────────────────────────────────────────────────────
    _total     = len(df_epd)
    _linked    = (df_epd['status'] == 'linked').sum()
    _num_only  = (df_epd['status'] == 'number_only').sum()
    _missing   = (df_epd['status'] == 'missing').sum()
    _expired   = (df_epd['status'] == 'expired').sum()
    _eco_hits  = int(df_epd['in_ecoportal'].sum()) if 'in_ecoportal' in df_epd.columns else 0
    _eco_badge = f'<div class="metric-box ok"><div class="num">{_eco_hits}</div><div class="lbl">In ECOportal</div></div>' if _eco_hits else ''

    st.markdown(f"""
    <div class="metric-grid" style="grid-template-columns:repeat({'5' if _eco_hits else '4'},1fr);">
      <div class="metric-box"><div class="num">{_total}</div><div class="lbl">Products analysed</div></div>
      <div class="metric-box ok"><div class="num">{_linked}</div><div class="lbl">Fully linked</div></div>
      <div class="metric-box warn"><div class="num">{_num_only}</div><div class="lbl">Number only</div></div>
      <div class="metric-box miss"><div class="num">{_missing}</div><div class="lbl">Missing EPD</div></div>
      {_eco_badge}
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs: visual browser + raw table + export ────────────────────────────────
    tab_browse, tab_table, tab_export, tab_about = st.tabs([
        "Browse & Match",
        "Raw Table",
        "Export for Revalu",
        "How This Works",
    ])

    # ── Tab 1: visual browser ────────────────────────────────────────────────────
    with tab_browse:
        col_search, col_status_filter = st.columns([3, 1])
        with col_search:
            _search_term = st.text_input(
                "Search products", placeholder="Product name, manufacturer or EPD number…",
                key="revalu_search", label_visibility="collapsed"
            )
        with col_status_filter:
            _status_colours = {
                "all": "🔘 All",
                "linked":      "✅ Linked",
                "number_only": "🟡 Num only",
                "missing":     "🔴 Missing",
                "expired":     "🟣 Expired",
            }
            _status_choice = st.selectbox(
                "Status", list(_status_colours.values()),
                key="revalu_status_filter", label_visibility="collapsed"
            )

        df_browse = df_epd.copy()
        if _search_term:
            _mask = (
                df_browse['product_name'].str.contains(_search_term, case=False, na=False) |
                df_browse['manufacturer'].str.contains(_search_term, case=False, na=False) |
                df_browse['epd_reg_number'].str.contains(_search_term, case=False, na=False)
            )
            df_browse = df_browse[_mask]

        _chosen_status_key = {v: k for k, v in _status_colours.items()}.get(_status_choice, "all")
        if _chosen_status_key != "all":
            df_browse = df_browse[df_browse['status'] == _chosen_status_key]

        st.caption(f"Showing {len(df_browse):,} products")

        _STATUS_HTML = {
            "linked":      '<span class="status-pill status-linked">✓ Linked</span>',
            "number_only": '<span class="status-pill status-number">№ Number only</span>',
            "missing":     '<span class="status-pill status-missing">✗ Missing</span>',
            "expired":     '<span class="status-pill status-expired">⚠ Expired</span>',
        }
        _REG_CSS = {
            "EPD International": "reg-epdi",
            "EPD Italy":         "reg-italy",
            "IBU":               "reg-ibu",
            "INIES":             "reg-inies",
        }

        # Render product cards (paginated for performance)
        _PAGE_SIZE = 30
        _n_pages = max(1, (len(df_browse) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        # Filter change can shrink _n_pages below a stored page → reset before the
        # widget reads session_state, or st.pagination raises on the stale value.
        if st.session_state.get("revalu_page", 1) > _n_pages:
            st.session_state.pop("revalu_page", None)
        if _n_pages > 1:
            _page = st.pagination(_n_pages, key="revalu_page")
        else:
            _page = 1

        _slice = df_browse.iloc[(_page - 1) * _PAGE_SIZE : _page * _PAGE_SIZE]

        for _, row in _slice.iterrows():
            search_urls = _build_search_urls(
                row['epd_reg_number'], row['product_name'], row['manufacturer']
            )
            guesses = [g.strip() for g in row['likely_registry'].split(';') if g.strip()]
            status_badge = _STATUS_HTML.get(row['status'], '')

            # Build registry link pills
            link_pills = ""
            for reg_name in guesses:
                url = search_urls.get(reg_name, "#")
                css = _REG_CSS.get(reg_name, "reg-open")
                label = reg_name.replace("EPD International", "EPDI").replace("EPD Italy", "IT")
                link_pills += f'<a href="{url}" target="_blank" class="reg-link {css}">🔎 {label}</a>'

            # If we have a direct URL already, add it
            if row['epd_url'] not in ("-", ""):
                link_pills = (
                    f'<a href="{row["epd_url"]}" target="_blank" '
                    f'class="reg-link reg-epdi">📄 Open EPD</a> ' + link_pills
                )

            # Show both reg and dec numbers if they differ
            _reg_raw = row['epd_reg_number']
            _dec_raw = row.get('epd_dec_number', '-')
            _nums_html = ""
            if _reg_raw not in ("-", ""):
                _nums_html += f'<span class="epd-reg-number" title="Registration №">{_reg_raw}</span>'
            if _dec_raw not in ("-", "", _reg_raw):
                _nums_html += f'&nbsp;<span class="epd-reg-number" style="background:#e0f2fe;" title="Declaration №">{_dec_raw}</span>'
            reg_display = _nums_html or '<span style="color:#94a3b8;font-size:0.78rem">No registration number</span>'

            # ECOportal match badge
            eco_badge = ""
            if row.get('in_ecoportal'):
                eco_badge = (
                    '<span style="background:#dcfce7;color:#16a34a;border:1px solid #86efac;'
                    'border-radius:4px;padding:1px 7px;font-size:0.7rem;font-weight:700;'
                    'margin-left:6px;" title="Found in ECOportal (soda4LCA)">🌿 ECOportal</span>'
                )

            validity_note = ""
            if row['epd_valid_until'] not in ("-", ""):
                validity_note = f'<span style="font-size:0.74rem;color:#64748b;margin-left:8px">Valid until: {row["epd_valid_until"]}</span>'
            if row['status'] == 'expired':
                validity_note = f'<span style="font-size:0.74rem;color:#9333ea;margin-left:8px">⚠ Expired: {row["epd_valid_until"]}</span>'

            publisher_note = (
                f'<span style="font-size:0.74rem;color:#64748b;margin-left:8px">'
                f'Publisher: {row["epd_publisher"]}</span>'
                if row['epd_publisher'] not in ("-", "") else ""
            )

            st.markdown(f"""
    <div class="epd-row">
      <div class="epd-row-header">
        <div>
          <div class="epd-product-name">{row['product_name']}</div>
          <div class="epd-manufacturer">{row['manufacturer']}
            {'&nbsp;·&nbsp;<span style="color:#475569">' + row['product_type'] + '</span>'
              if row['product_type'] not in ("-","") else ""}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
          {status_badge}
        </div>
      </div>
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px">
        {reg_display}{eco_badge}
        {publisher_note}
        {validity_note}
      </div>
      <div class="reg-links" style="margin-top:10px">
        {link_pills}
      </div>
    </div>
    """, unsafe_allow_html=True)


    # ── Tab 2: raw table ─────────────────────────────────────────────────────────
    with tab_table:
        _status_emoji = {
            "linked": "✅ Linked", "number_only": "🟡 Num only",
            "missing": "🔴 Missing", "expired": "🟣 Expired",
        }
        df_display = df_epd[[
            'product_name', 'manufacturer', 'product_type',
            'epd_reg_number', 'epd_dec_number', 'epd_reg_norm',
            'status', 'in_ecoportal', 'eco_uuid',
            'epd_publisher', 'epd_issued', 'epd_valid_until',
            'epd_type', 'likely_registry', 'epd_url',
        ]].copy()
        df_display['status'] = df_display['status'].map(_status_emoji).fillna(df_display['status'])
        df_display['in_ecoportal'] = df_display['in_ecoportal'].map({True: '🌿 Yes', False: ''})
        st.dataframe(
            df_display,
            width='stretch',
            height=560,
            hide_index=True,
            column_config={
                'product_name':   st.column_config.TextColumn('Product', width='large'),
                'manufacturer':   st.column_config.TextColumn('Manufacturer', width='medium'),
                'product_type':   st.column_config.TextColumn('Type', width='small'),
                'epd_reg_number': st.column_config.TextColumn('Reg #', width='medium'),
                'epd_dec_number': st.column_config.TextColumn('Dec #', width='medium'),
                'epd_reg_norm':   st.column_config.TextColumn('Normalised #', width='medium'),
                'status':         st.column_config.TextColumn('Status', width='small'),
                'in_ecoportal':   st.column_config.TextColumn('ECOportal', width='small'),
                'eco_uuid':       st.column_config.TextColumn('ECO UUID', width='medium'),
                'epd_publisher':  st.column_config.TextColumn('Publisher', width='medium'),
                'epd_issued':     st.column_config.TextColumn('Issued', width='small'),
                'epd_valid_until':st.column_config.TextColumn('Valid until', width='small'),
                'epd_type':       st.column_config.TextColumn('EPD Type', width='small'),
                'likely_registry':st.column_config.TextColumn('Likely Registry', width='medium'),
                'epd_url':        st.column_config.LinkColumn('EPD URL', width='medium'),
            },
        )


    # ── Tab 3: CSV export ────────────────────────────────────────────────────────
    with tab_export:
        st.markdown("""
        #### Export for Revalu Integration

        This export produces a structured CSV containing every product with its EPD
        registration status, likely registry, and pre-built search URLs. Revalu can
        use this file to:
        - Automatically query each registry API for the matching EPD document
        - Enrich EETRA products with full EPD PDFs and structured LCA data
        - Flag products where the EPD URL is missing or stale
        """)

        col_fmt1, col_fmt2 = st.columns(2)

        with col_fmt1:
            _incl_urls = st.toggle(
                "Include pre-built registry search URLs", value=True,
                key="revalu_incl_urls"
            )
            _incl_all_status = st.toggle(
                "Include all statuses (not just missing)", value=True,
                key="revalu_incl_all"
            )

        with col_fmt2:
            _registry_filter = st.multiselect(
                "Include likely registries",
                ["EPD International", "EPD Italy", "IBU", "INIES"],
                default=["EPD International", "EPD Italy", "IBU"],
                key="revalu_reg_filter"
            )

        # Build export dataframe
        df_export = df_epd.copy() if _incl_all_status else df_epd[df_epd['status'] != 'linked'].copy()

        if _registry_filter:
            _reg_mask = df_export['likely_registry'].apply(
                lambda x: any(r in x for r in _registry_filter)
            )
            df_export = df_export[_reg_mask]

        if _incl_urls:
            search_url_rows = []
            for _, row in df_export.iterrows():
                surls = _build_search_urls(
                    row['epd_reg_number'], row['product_name'], row['manufacturer']
                )
                search_url_rows.append({
                    'search_url_epd_international': surls.get("EPD International", ""),
                    'search_url_epd_italy':         surls.get("EPD Italy", ""),
                    'search_url_ibu':               surls.get("IBU", ""),
                    'search_url_inies':             surls.get("INIES", ""),
                })
            df_export = pd.concat(
                [df_export.reset_index(drop=True),
                 pd.DataFrame(search_url_rows)],
                axis=1
            )

        st.metric("Products in export", len(df_export))

        csv_bytes = df_export.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️  Download Revalu Cross-Match CSV",
            data=csv_bytes,
            file_name="eetra_revalu_epd_crossmatch.csv",
            mime="text/csv",
            width='stretch',
            type="primary",
        )

        with st.expander("Preview first 20 rows", type="compact"):
            st.dataframe(df_export.head(20), width='stretch')


    # ── Tab 4: About / partnership context ───────────────────────────────────────
    with tab_about:
        st.markdown("""
        ### How EPD Registry Cross-Matching Works

        **What is an EPD?**
        An Environmental Product Declaration (EPD) is a standardised, third-party
        verified document that quantifies the environmental impacts of a product
        over its life cycle. EPDs are used in green building certifications (LEED,
        BREEAM, ITACA) and increasingly in procurement decisions.

        ---

        ### Supported Registries

        | Registry | Geography | URL format |
        |----------|-----------|------------|
        | **EPD International** (environdec.com) | Global | `S-P-XXXXX` numbers |
        | **EPD Italy** (epditaly.it) | Italy | Italian national numbers |
        | **IBU** (ibu-epd.com) | Germany / Europe | `EPD-IBU-XXXXXXX-EN` |
        | **INIES** (inies.fr) | France | French national registry |
        | **EPD Hub** (epdhub.com) | Global (aggregator) | All registries |

        ---

        ### Status Definitions

        | Status | Meaning |
        |--------|---------|
        | ✅ **Linked** | Product has an `E__EPD_URL` pointing to a live EPD document |
        | 🟡 **Number only** | `E__EPD_RegNumber` exists but no URL — registry lookup needed |
        | 🔴 **Missing** | No registration number or URL — manual search required |
        | 🟣 **Expired** | EPD has passed its `E__EPD_ValidUntil` date — may need renewal |

        ---

        ### How Registry Is Guessed

        The page reads the registration number format and publisher field to
        infer which registry is most likely:

        - Numbers matching `S-P-XXXXX` or `ECOP-...` → EPD International
        - Numbers matching `EPD-IBU-...` or publisher containing "IBU" → IBU
        - Publisher or number containing "INIES" or "France" → INIES
        - Publisher or number containing "Italy" / "Italia" → EPD Italy
        - No strong signal → all three main registries shown

        ---

        ### For Revalu

        The **Export for Revalu** tab produces a CSV with:
        - Every EETRA product with its EPD status and likely registry
        - Pre-built search URLs for each registry (ready for API calls or browser automation)
        - Products filtered to those needing online lookup

        This enables Revalu to programmatically enrich EETRA data by querying each
        registry's API/search with the registration number, fetching the EPD PDF,
        and cross-populating structured LCA fields back into both databases.

        **Proposed next steps for the partnership:**
        1. Share this CSV export with Revalu's engineering team
        2. Revalu runs automated registry lookups on "number only" products
        3. EETRA reviews and approves new `E__EPD_URL` values
        4. Revalu gains access to EETRA's curated GWP + product data for Italian/European materials
        5. Joint data enrichment pipeline established with agreed update cadence
        """)

        st.info(
            "📧 For partnership enquiries contact: **info@eetra.it** "
            "| Revalu: **hello@revalu.ai**",
            icon="🤝"
        )
