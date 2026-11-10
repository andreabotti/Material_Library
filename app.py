"""
app.py — EETRA MatLib entry point
===================================
Handles: page config · shared CSS · config injection · auth · sidebar ·
data loading · session-state init · filter widgets · cache warm-up.

Tab content lives in pages/:
    pages/1_Welcome.py       overview & quick stats
    pages/2_Catalogue.py     product catalogue (Cards / Grid & table / Collections)
    pages/3_Charts.py        box + bar + scatter charts
    pages/14_FurtherDataSources.py  Impact Framework matrix · ICE DB · CAM 2025 · ECOportal · BDI-LCA
    pages/4_Maps.py          geographic maps (embedded from Developer)
    pages/15_Manufacturers.py  manufacturers directory (credentials + Impact Framework entities)
    pages/5_Developer.py     account, add/edit, diagnostics, EPD parse (admin)

Shared app-shell helpers live in libs/lib_ui.py (fn350–fn359): per-run guards,
embedded-page hosting, the active-filter strip, empty states, loading, iframe
heights. Visual values live in theme.json; page headers use lib_header.fn003.
"""
import streamlit as st
import pandas as pd
import json, hashlib, os
import html as _html
import importlib
import sys

# Streamlit's run-on-save reloader can drop the ``libs`` parent package from
# ``sys.modules`` while reloading a submodule (common on OneDrive). Python then
# raises ``KeyError: 'libs'`` on ``from libs.lib_header import ...``.
for _libs_attempt in range(2):
    try:
        importlib.import_module("libs")
        from libs.lib_header import (
            fn001_create_page_header,
            fn001b_render_app_masthead,
            fn005_inject_global_css,
        )
        from libs.lib_data import (
            fn112a_render_auth_gate_screen      as fn_061_render_auth_gate_screen,
            fn112_sync_auth_session_with_secrets as fn_060_sync_auth_session_with_secrets,
            fn114_add_base_product_column       as fn_046_add_base_product_column,
            fn132_session_ui_config_bundle      as session_ui_config_bundle,
            fn149_ensure_data_platform_session  as fn_149_ensure_data_platform_session,
            fn158b_effective_live_mtimes        as fn_158b_effective_live_mtimes,
            fn158c_cached_load_clean_effective_live as fn_158c_cached_load_clean_effective_live,
            fn158d_load_sharepoint_effective    as fn_158d_load_sharepoint_effective,
        )
        from libs.lib_ui import (
            fn302_render_filter_widgets         as fn_004_render_filter_widgets,
            fn303_custom_hr                     as fn_005_custom_hr,
            fn350_begin_run,
            fn360_start_catalogue_payload_warmup,
            CUSTOM_COLOR_MAP,
        )
        from libs.lib_i18n import (
            fn704_t                             as fn_704_t,
            fn706_render_language_selector      as fn_706_render_language_selector,
            fn710_add_italian_product_type      as fn_710_add_italian_product_type,
            fn711_t_page                        as fn_711_t_page,
        )
        break
    except KeyError as _libs_exc:
        if _libs_attempt or "libs" not in str(_libs_exc):
            raise
        for _mod in list(sys.modules):
            if _mod == "libs" or _mod.startswith("libs."):
                sys.modules.pop(_mod, None)


# ── Per-run counter (drives the once-per-run CSS/asset guards) ───────────
fn350_begin_run()

# ── Auth gate (must run before any data/page initialization) ─────────────
# The gate screen pre-fills the default admin credentials (fn112a_render_auth_gate_screen
# -> fn112_default_admin_credentials), so signing in is a single click rather than a
# silent auto-login — the user always sees who they're signing in as before entering.
# fn112a also collapses the sidebar (pages/ auto-nav preview) and paints the splash.
if "auth_user" not in st.session_state:
    fn_061_render_auth_gate_screen()
    st.stop()
fn_060_sync_auth_session_with_secrets()

# ── Page config (masthead rendered after st.navigation — see below) ───────
# Additive after the auth-gate collapsed config; restores width for the app shell.
fn001_create_page_header(show_branding=False)

# ── Push config into session state for all pages ─────────────────────────
# Re-read aux_10__ui_config.json every run so edits (e.g. divider_margin_*_px) apply on Rerun;
# imported ``libs.shared`` constants alone stay cached until process restart.
try:
    _ui_bundle = session_ui_config_bundle()
    _ui_bundle["CUSTOM_COLOR_MAP"] = CUSTOM_COLOR_MAP
    st.session_state.update(_ui_bundle)
except Exception as _e:
    st.warning(f"⚠️ UI config load failed (aux_10__ui_config.json): {str(_e)[:120]}")

# ── Geocode cache ────────────────────────────────────────────────────────
if "GEOCODE_CACHE" not in st.session_state:
    try:
        with open("aux_06__geocoded_locations.json", "r", encoding="utf-8") as _f:
            st.session_state["GEOCODE_CACHE"] = json.load(_f)
    except FileNotFoundError:
        st.session_state["GEOCODE_CACHE"] = {}
        st.toast("Geocode cache missing — maps will geocode live (slower).", icon="🗺️")
    except Exception as _e:
        st.session_state["GEOCODE_CACHE"] = {}
        st.warning(f"⚠️ Geocode cache unreadable (aux_06__geocoded_locations.json): {str(_e)[:120]}")
if "LOCATIONS_PRELOADED" not in st.session_state:
    st.session_state["LOCATIONS_PRELOADED"] = bool(st.session_state.get("GEOCODE_CACHE"))

with st.sidebar:
    _auth_user = str(st.session_state.get("auth_user", "")).strip()
    _auth_role = str(st.session_state.get("auth_role", "user")).strip() or "user"
    # Tighten space around the Logout control (caption → button → Filters hr).
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] div.st-key-global_logout {
            margin-top: -0.55rem !important;
            margin-bottom: -0.35rem !important;
        }
        section[data-testid="stSidebar"] div.st-key-global_logout [data-testid="stButton"] {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }
        /* App Language block (libs/lib_i18n.fn706), directly above Filters. */
        section[data-testid="stSidebar"] .app-language-label {
            font-size: 0.80rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            opacity: 0.80;
            margin: 0.15rem 0 0.20rem 0;
        }
        section[data-testid="stSidebar"] div.st-key-_app_language_picker {
            margin-top: -0.25rem !important;
            margin-bottom: -0.15rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if _auth_user:
        st.caption(f"{fn_704_t('signed_in_as', 'Signed in as')}: **{_auth_user}** ({_auth_role})")
    if st.button(fn_704_t("logout", "Logout"), key="global_logout"):
        st.session_state.pop("auth_user", None)
        st.session_state.pop("auth_role", None)
        # Also drops the Microsoft token cache when signed in via M365.
        from libs.lib_auth_m365 import fn807_m365_sign_out
        fn807_m365_sign_out()
        st.rerun()

    # ── App Language (ITA default) — sits above the Filters block below ──
    # Rendered here, in the always-present sidebar section, so the selector is
    # available even when the dataset is empty and the Filters block is skipped.
    fn_005_custom_hr()
    fn_706_render_language_selector(container=st)

# ── Data source (session default; selector on Developer Dashboard) ────────
# Default is Neon when [neon] database_url is set (see fn149).
fn_149_ensure_data_platform_session()
input_data_platform = st.session_state["data_platform"]
if input_data_platform == "Neon":
    from libs.lib_neon import neon_url as _neon_url
    if not _neon_url():
        st.error(
            "Data Source is **Neon** but `[neon] database_url` is missing in "
            "`.streamlit/secrets.toml` — switch to *Local Parquet* or add the URL."
        )
        st.stop()
if input_data_platform == "EETRA Sharepoint":
    _sp = st.secrets.get("sharepoint", {})
    _sp_missing = [k for k in ("tenant_id", "client_id", "client_secret", "file_relative_url") if not _sp.get(k)]
    if _sp_missing:
        st.error(
            "Missing `[sharepoint]` keys in `.streamlit/secrets.toml`: "
            + ", ".join(f"`{k}`" for k in _sp_missing)
            + " — switch Data Source to *Neon* / *Local Parquet* or complete the secrets."
        )
        st.stop()
    input_data_file_path = _sp["file_relative_url"]
    input_data_sheet_name = "_live_data"
else:
    input_data_file_path = st.secrets.get("sharepoint", {}).get("file_relative_url", "")
    input_data_sheet_name = "_live_data"

# ── Data loading ─────────────────────────────────────────────────────────
df = pd.DataFrame()
# Stat both parquets once per run; reused by the loader and the fingerprint below.
_live_mtimes = fn_158b_effective_live_mtimes()

if input_data_platform in ("Neon", "Local Parquet"):
    # Neon: matlib_base ⊕ matlib_edits. Local Parquet: the two files under 01_data/.
    # Same merge/clean path; libs/lib_neon chooses the backend from Data Source.
    # Cache key is both sides' versions (Neon tokens or file mtimes).
    try:
        df = fn_158c_cached_load_clean_effective_live(*_live_mtimes, key_column="A__Manufacturer")
    except Exception as _e:
        _src = "Neon" if input_data_platform == "Neon" else "Parquet"
        st.error(f"{_src} error: {_e}")
        st.info(
            "💡 Neon: check `[neon] database_url` and re-run `04_tools/15_parquet_to_neon.py`. "
            "Local Parquet: check `01_data/base_data.parquet` / `edits_data.parquet`."
        )
        st.stop()
elif input_data_platform == "EETRA Sharepoint":
    # Workbook ⊕ the same edit log (Neon when configured, else edits_data.parquet),
    # then clean, then the Map_yn filter — the same gates as the Neon/Local branch.
    # All four steps are cached together (fn158d), keyed on the workbook
    # coordinates and the edit log's mtime; a failure is remembered for a minute
    # instead of being retried on every rerun.
    _sp_key = (
        st.secrets["sharepoint"]["tenant_id"],
        st.secrets["sharepoint"]["client_id"],
        st.secrets["sharepoint"]["client_secret"],
        "eetra.sharepoint.com", "/sites/res", "Documenti",
        input_data_file_path, input_data_sheet_name,
    )
    try:
        df, _sp_merge_err = fn_158d_load_sharepoint_effective(_sp_key, key_column="A__Manufacturer")
    except Exception as _e:
        st.error(f"SharePoint data could not be loaded: {str(_e)[:240]}")
        st.info("💡 Switch Data Source to *Neon* or *Local Parquet* on the Developer Dashboard, or try again shortly.")
        st.stop()
    if _sp_merge_err:
        st.warning(f"⚠️ Local edits could not be applied to the SharePoint data: {_sp_merge_err}")

# ── Session state init ───────────────────────────────────────────────────
if not df.empty:
    # Invalidate cached data when the data source changes
    if st.session_state.get("_data_platform_loaded") != input_data_platform:
        for _k in ("ORIGINAL_DATA", "FILTERED_DATA", "all_cols",
                   "df_filtered_ready", "user_filter_defaults_initialized",
                   "LOCATIONS_BY_BASE_PRODUCT"):
            st.session_state.pop(_k, None)
        st.session_state["_data_platform_loaded"] = input_data_platform

    # ORIGINAL_DATA used to be built once per session ("if not in session_state"),
    # so a row saved on the Add/Edit page reached edits_data.parquet and the
    # reloaded `df` above, but never the frame the Catalogue, Charts and Maps
    # actually render — a newly created item stayed invisible until the session
    # restarted or the Data Source was toggled. Rebuild it whenever the data
    # underneath changes instead: both parquet mtimes (exact for Local Parquet,
    # and the edit log applies to either source), plus the loaded frame's shape
    # and id set, which is what moves when a SharePoint refresh brings in rows.
    # Value-only edits to the SharePoint workbook mid-session are still not
    # detected — the same as before this check existed.
    try:
        _id_sig = (
            int(pd.util.hash_pandas_object(
                df["0__EETRA_ID"].astype(str), index=False).sum())
            if "0__EETRA_ID" in df.columns else 0
        )
    except Exception:
        _id_sig = 0
    _data_fingerprint = (
        input_data_platform, *_live_mtimes,
        int(df.shape[0]), int(df.shape[1]), _id_sig,
    )
    if st.session_state.get("_data_fingerprint") != _data_fingerprint:
        # Filters live in their own widget keys and FILTERED_DATA is recomputed
        # from ORIGINAL_DATA on every run, so dropping this does not disturb
        # what the user has filtered to — the new row simply joins the pool.
        st.session_state.pop("ORIGINAL_DATA", None)
        st.session_state["_data_fingerprint"] = _data_fingerprint

    if "ORIGINAL_DATA" not in st.session_state:
        try:
            _df_base = (fn_046_add_base_product_column(df, product_col="A__ProductName")
                        if "A__ProductName" in df.columns else df)
        except Exception as _e:
            st.warning(f"⚠️ Base-product grouping failed — variants won't be grouped: {str(_e)[:120]}")
            _df_base = df
        # Manufacturer list prices (libs/lib_prices.py). Attached here, once, so
        # every page — catalogue cards, charts, exports — sees the same PR__
        # columns on both ORIGINAL_DATA and the filtered view derived from it.
        # `all_cols` stays the raw dataset's columns: PR__ is derived, not data
        # anyone edits.
        try:
            from libs.lib_prices import fn507_attach_prices as _fn507_attach_prices
            _df_base = _fn507_attach_prices(_df_base)
        except Exception as _e:
            st.warning(f"⚠️ List prices unavailable — catalogue shown without them: {str(_e)[:120]}")
        # Italian Product Type, derived from D__ProductType_ENG and the
        # translation catalogue — the counterpart of the D__MaterialType_ITA
        # column the dataset already carries. Derived here, with the other
        # computed columns, so it rides on ORIGINAL_DATA and everything built
        # from it; the stored data is left untouched. `all_cols` below stays
        # the raw dataset's columns, so this does not enter the filter or
        # chart column pickers as a second copy of the same dimension.
        try:
            _df_base = fn_710_add_italian_product_type(_df_base)
        except Exception as _e:
            st.warning(f"⚠️ Italian product types unavailable: {str(_e)[:120]}")
        # `df` is the shared cached frame; never hand it to session state by alias
        # (only reachable when both steps above failed or were skipped).
        if _df_base is df:
            _df_base = df.copy()
        st.session_state["ORIGINAL_DATA"] = _df_base
        st.session_state["all_cols"] = df.columns.tolist()

    # Invalidate display params when config changes
    _cfg_hash = hashlib.md5(
        json.dumps(st.session_state.get("FIELD_VISIBILITY", {}), sort_keys=True).encode()
    ).hexdigest()
    if st.session_state.get("config_hash") != _cfg_hash:
        for _k in [k for k in st.session_state if k.startswith("display_params_")]:
            del st.session_state[_k]
        st.session_state["config_hash"] = _cfg_hash

    _df_original = st.session_state["ORIGINAL_DATA"]

    # Filters
    with st.sidebar:
        fn_005_custom_hr()
        st.markdown(f"#### 🔍 {fn_704_t('filters', 'Filters')}")
    # No seeded filter values: the app used to open pre-filtered to
    # ["Panel", "m2", "Knauf"], so a first-time user's first view of the
    # Catalogue was a silently narrowed subset (and any ?open_product deep link
    # landed on a product that had been filtered out). Start unfiltered.
    st.session_state.setdefault("user_filter_defaults_initialized", True)

    # Filter _df_original, not the raw `df` — it already carries the columns
    # ORIGINAL_DATA adds above (A__ProductName_Base, PR__* list prices). fn302
    # only ever subsets rows, so every extra column rides through untouched;
    # filtering plain `df` here silently dropped those columns from
    # FILTERED_DATA (and therefore from the Catalogue/Charts pages, which read
    # FILTERED_DATA) while ORIGINAL_DATA kept them — the two diverged.
    df_filtered = fn_004_render_filter_widgets(
        _df_original,
        all_cols=df.columns.tolist(),
        default_cols=["D__ProductType_ENG", "A__Manufacturer", "D__MaterialType_ENG"],
        default_vals=["Floor (Tiles)", None, None],
    )
    try:
        df_filtered = fn_046_add_base_product_column(df_filtered, product_col="A__ProductName")
    except Exception as _e:
        st.warning(f"⚠️ Base-product grouping failed on filtered data: {str(_e)[:120]}")
    st.session_state["FILTERED_DATA"] = df_filtered
    st.session_state["df_filtered_ready"] = True
    st.session_state.setdefault("LOCATIONS_BY_BASE_PRODUCT", {})
else:
    st.session_state.setdefault("ORIGINAL_DATA",  pd.DataFrame())
    st.session_state.setdefault("FILTERED_DATA",  pd.DataFrame())
    st.session_state.setdefault("df_filtered_ready", False)

# ── Navigation (must be constructed each run) + global CSS ───────────────
_is_admin = str(st.session_state.get("auth_role", "")).strip().lower() == "admin"
pages = [
    st.Page("pages/1_Welcome.py", title=fn_711_t_page("Welcome"), icon="🏠"),
    st.Page("pages/2_Catalogue.py", title=fn_711_t_page("Catalogue"), icon="📦"),
    st.Page("pages/15_Manufacturers.py", title=fn_711_t_page("Manufacturers"), icon="🏭"),
    # Temporary: was the Catalogue's "Collections" tab, split out to its own
    # page while it gets restructured Revalu-style (per user direction). The
    # page file itself needs no change — it already renders its own header
    # and falls back to an empty dataframe when run outside the embedded-tab
    # context (see fn352_is_embedded_page() inside pages/7_Collections.py).
    #
    # NOTE: confirmed present and correct in this list at runtime (Streamlit
    # builds the page object fine), but does not appear as a link in the top
    # nav bar — reproduced with a second, unrelated trivial page too, at two
    # viewport widths, in every list position. Looks like a real limit on how
    # many flat (ungrouped) pages position="top" renders in this Streamlit
    # version (1.60.0), not anything wrong with this file or this list. Not
    # reachable by URL either — this app's nav has no url_path (see the
    # ?view_docs_for= comment below), so any direct/hard-reload URL bounces
    # to the default page for every entry here, not just this one.
    # Collections page hidden for now (not currently needed) — uncomment to restore,
    # together with the matching st.page_link in pages/1_Welcome.py.
    # st.Page("pages/7_Collections.py", title="Collections", icon="🏷️"),
    st.Page("pages/3_Charts.py", title=fn_711_t_page("Charts"), icon="📊"),
    st.Page("pages/14_FurtherDataSources.py", title=fn_711_t_page("Further Data Sources"), icon="🗄️"),
]
if _is_admin:
    pages.append(st.Page("pages/5_Developer.py", title=fn_711_t_page("Developer Dashboard"), icon="🔧"))
pg = st.navigation(pages, position="top")  # flat list, no Tools grouping
fn005_inject_global_css()
# Full masthead on Welcome only; compact green bar (logo + title) elsewhere.
# CSS first so compact classes exist; compact also carries inline styles as fallback.
# Compare against the *translated* Welcome title — the nav titles now go
# through fn711, so a literal "Welcome" here would never match in Italian and
# every page, Welcome included, would get the compact bar.
fn001b_render_app_masthead(
    compact=str(getattr(pg, "title", "") or "").strip() != fn_711_t_page("Welcome")
)

# ── Catalogue payload warm-up (background) ────────────────────────────────
# Build the JS2 catalogue JSON while the user is on Welcome / another page so
# the first open of Catalogue is a cache hit instead of "Building catalogue…".
# Skip when Catalogue itself is the active page — it builds the payload inline.
_on_catalogue = "catalogue" in str(getattr(pg, "url_path", "") or "").lower()
if st.session_state.get("df_filtered_ready"):
    fn360_start_catalogue_payload_warmup(
        st.session_state.get("FILTERED_DATA", pd.DataFrame()),
        skip=_on_catalogue,
    )

# ── Document-viewer popup (?view_docs_for=<EETRA_ID>) — FALLBACK PATH ────
# The Catalogue card's "📑 View documents" button no longer comes through here:
# it postMessages to libs/catalogue_bridge, which triggers a plain rerun and
# opens the dialog from within the Cards tab (pages/2_Catalogue.py) — so the
# user stays on the catalogue. This query-param entry point is kept because
# st.navigation has no url_path (any hard reload lands on the default page), so
# a URL like "?view_docs_for=BBW__GYP__0047" can only be serviced here. Useful
# for deep links and for debugging the viewer without the catalogue iframe.
_pending_doc_view = str(st.query_params.get("view_docs_for") or "").strip()
if _pending_doc_view:
    _dv_df = st.session_state.get("FILTERED_DATA", pd.DataFrame())
    _dv_match = (
        _dv_df[_dv_df["0__EETRA_ID"].astype(str).str.strip() == _pending_doc_view]
        if "0__EETRA_ID" in getattr(_dv_df, "columns", [])
        else pd.DataFrame()
    )
    if _dv_match.empty:
        st.query_params.clear()
    else:
        _dv_row = _dv_match.iloc[0]
        _dv_name = str(_dv_row.get("A__ProductName", "") or "")

        @st.dialog("Documents", width="large")
        def _document_viewer_dialog(_eid: str, _row, _name: str):
            from libs.lib_ui import fn351_render_document_viewer
            st.markdown(f"##### {_name or _eid}")
            fn351_render_document_viewer(_row, _eid, _name)
            if st.button("Close", key=f"_close_doc_dialog_{_eid}"):
                st.query_params.clear()
                st.rerun()

        _document_viewer_dialog(_pending_doc_view, _dv_row, _dv_name)

# ── Application status (small print under the sidebar widgets) ───────────
with st.sidebar:
    fn_005_custom_hr()
    if st.session_state.get("df_filtered_ready") and not st.session_state.get(
        "ORIGINAL_DATA", pd.DataFrame()
    ).empty:
        _status = fn_704_t("welcome_status_ready",
                           "Application ready. Navigate using the tabs above.")
    elif "ORIGINAL_DATA" not in st.session_state:
        _status = fn_704_t("welcome_status_initialising",
                           "Initialising — please wait a moment.")
    else:
        _status = fn_704_t("welcome_status_loading", "Data is loading or unavailable.")
    _loc_state = fn_704_t(
        "welcome_location_cache", "Location cache: {state}",
        state=(fn_704_t("welcome_location_loaded", "loaded")
               if st.session_state.get("LOCATIONS_PRELOADED")
               else fn_704_t("welcome_location_missing", "missing")),
    )
    st.markdown(
        f'<div style="font-size:0.72rem;line-height:1.35;opacity:0.65;">'
        f"{_html.escape(_status)}<br>{_html.escape(_loc_state)}</div>",
        unsafe_allow_html=True,
    )

pg.run()
