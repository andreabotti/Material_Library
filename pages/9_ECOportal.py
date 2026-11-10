"""
pages/9_ECOportal.py  —  EETRA MatLib · ECOportal / soda4LCA
═══════════════════════════════════════════════════════════════════════════
Single consolidated page (merges the former ECOportal + ECOportal JS pages).
Built around the client-side EPD Browser — all EPD filtering / inspection
happens in html/ecoportal_component.html with no server round-trips.

Three tabs:
  EPD Browser     — default. Full client-side browser: search + country /
                    programme / product / material / confidence / MatLib
                    filters, grid ⇄ list, per-EPD detail (Overview · LCI ·
                    GWP · other impacts · mapping · raw JSON).
  Overview        — product / material distribution charts + mapping
                    coverage metrics for the whole dataset.
  Data & Pipeline — admin: ① Ingest from soda4LCA nodes, ② run mapping,
                    ③ browse raw output / downloads, plus a slim raw-XML
                    inspector for individual ILCD files.

Shared load / cache logic lives in libs.lib_eco_data (buckets are reused
across warm reruns via a persistent sidecar).

Credentials are read from .streamlit/secrets.toml  [soda4lca] section:
    base_url      = "https://node.example.com/db/resource"
    api_token     = "eyJhbGci..."    # Bearer token
"""
from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Resolve the soda4lca package root (sibling directory) ─────────────────────
_PAGE_FILE  = Path(__file__).resolve()
_APP_ROOT   = _PAGE_FILE.parents[1]           # EETRA_MatLib_2026.06/
_EETRA_ROOT = _PAGE_FILE.parents[2]           # EETRA_MatLib/
_SODA_ROOT  = _EETRA_ROOT / "ECOportal_Downloader" / "soda4lca"

if str(_SODA_ROOT) not in sys.path:
    sys.path.insert(0, str(_SODA_ROOT))

import libs.lib_eco_data as _eco

_MAPPING_INPUT  = _eco.MAPPING_INPUT
_MAPPING_OUTPUT = _eco.MAPPING_OUTPUT
_XML_PROC_DIR   = _eco.XML_PROC_DIR
_MAPPING_SCRIPT = _SODA_ROOT / "generate_mapping.py"
_DEFAULT_OUTPUT = str(_SODA_ROOT / "output")

_prod_label = _eco.prod_label
_mat_label  = _eco.mat_label

# Background fetch for source JSON (hidden iframe — no visible app rerun)
if _MAPPING_OUTPUT.exists():
    _eco.maybe_render_epd_fetch_response(
        st.query_params,
        str(_MAPPING_OUTPUT), _MAPPING_OUTPUT.stat().st_mtime_ns,
    )

# ── Try importing the soda4lca pipeline package (Ingest tab only) ─────────────
try:
    from soda4lca import DATASET_TYPES, PipelineConfig, run_ingestion
    from soda4lca.api_client import SodaApiClient
    from app_paths import (
        DEFAULT_OUTPUT_DIR,
        dataset_count,
        load_manifest,
        resolve_output_dir,
    )
    _PIPELINE_OK = True
    _PIPELINE_ERR = ""
except ImportError as _ie:
    _PIPELINE_OK = False
    _PIPELINE_ERR = str(_ie)
    DATASET_TYPES = ["processes", "flows", "flowproperties", "unitgroups", "sources", "contacts"]

    def resolve_output_dir(p):
        return _SODA_ROOT / "output" if not Path(p).is_absolute() else Path(p)

    def load_manifest(d):
        mp = resolve_output_dir(d) / "manifest.json"
        try:
            return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
        except Exception:
            return None

    def dataset_count(manifest, dtype, _dir):
        return 0

    DEFAULT_OUTPUT_DIR = "output"


# ── Load secrets ──────────────────────────────────────────────────────────────
def _load_secrets() -> dict:
    try:
        s = st.secrets["soda4lca"]
        return {
            "client_id":     s.get("client_id", ""),
            "client_secret": s.get("client_secret", ""),
            "api_token":     s.get("api_token", ""),
            "base_url":      s.get("base_url", ""),
        }
    except Exception:
        return {"client_id": "", "client_secret": "", "api_token": "", "base_url": ""}

_SECRETS = _load_secrets()


# ── Shared app-shell helpers (page header, empty states, iframe heights) ──────
from libs.lib_header import fn003a_page_header
from libs.lib_ui import (
    fn356_empty_state,
    fn357_loading,
    fn358_debug_caption,
    fn359_iframe_height,
)

# CSS note: this page's `.eco-metric` / `.log-box` / `.eco-badge-*` / `.type-*`
# rules used to be duplicated here as a page-level <style> block, byte-identical
# to the copy already emitted by lib_header.fn005_inject_global_css(). The
# duplicate is gone — those classes are part of the global stylesheet and their
# colours resolve from theme.json (palette.code_*, palette.ok_*, …).


# ══════════════════════════════════════════════════════════════════════════════
# Guard: sibling soda4lca folder must exist (nothing works without it)
# ══════════════════════════════════════════════════════════════════════════════
if not _SODA_ROOT.is_dir():
    fn003a_page_header("ECOportal", icon="🌿")
    fn356_empty_state(
        "ECOportal data folder not found.",
        kind="error",
        hint=f"Expected at `{_SODA_ROOT}` — copy **ECOportal_Downloader/soda4lca** next to the app folder.",
    )
    st.stop()

_HAS_DATA = _MAPPING_OUTPUT.exists() and _MAPPING_INPUT.exists()


# ══════════════════════════════════════════════════════════════════════════════
# Load dataset (may be empty on a fresh install — the Pipeline tab still works)
# ══════════════════════════════════════════════════════════════════════════════
_load_t0 = time.perf_counter()
_prog_ph = st.empty()

_base_rows: list[dict] = []
_mapping_data: dict | None = None

if _HAS_DATA:
    _prog = _prog_ph.progress(0, text="Loading mapping data…")
    try:
        _proc_mtime = _MAPPING_INPUT.stat().st_mtime_ns
        _map_mtime  = _MAPPING_OUTPUT.stat().st_mtime_ns
        _xml_mtime  = int(_XML_PROC_DIR.stat().st_mtime_ns) if _XML_PROC_DIR.is_dir() else 0
        _prog.progress(30, text="Building EPD index…")
        _base_rows = _eco.build_cat_rows_base(
            str(_MAPPING_OUTPUT), _map_mtime,
            str(_MAPPING_INPUT),  _proc_mtime,
            str(_XML_PROC_DIR),   _xml_mtime,
        )
        _prog.progress(60, text="Loading coverage stats…")
        _mapping_data = _eco.load_mapping(str(_MAPPING_OUTPUT), _map_mtime)
    except Exception as _e:
        fn356_empty_state(f"EPD index build failed: {str(_e)[:150]}", kind="warn")

# ── MatLib cross-reference (session-specific) ─────────────────────────────────
_MATLIB_EPD_NUMS: set[str] = set()
_MATLIB_NAMES_LC: set[str] = set()
_MATLIB_NORM_TO_ID: dict[str, str] = {}
_MATLIB_NAME_TO_ID: dict[str, str] = {}

def _is_valid_epd_num(s: str) -> bool:
    if not s or s in ("*", "-", "—", "n/a", "na", "none"):
        return False
    if not any(ch.isdigit() for ch in s):
        return False
    return len(s) <= 40

@st.cache_data(show_spinner=False, max_entries=2)
def fn901_matlib_xref(
    data_sig: tuple, _df: pd.DataFrame
) -> tuple[set[str], set[str], dict[str, str], dict[str, str], str]:
    """MatLib → EPD cross-reference sets, cached on the catalogue's data signature.

    Replaces two iterrows() passes over the whole catalogue that ran on every
    rerun. `_df` is excluded from the key (hashing the frame would cost as much
    as the work); `data_sig` changes whenever the data does. Semantics match
    the old loops exactly: str()-then-strip per cell (NaN → "nan"), Dec before
    Reg within a row, first row wins for the *_TO_ID maps.
    Returns (epd_nums, names_lc, norm_to_id, name_to_id, matlib_signature).
    """
    epd_nums: set[str] = set()
    names_lc: set[str] = set()
    norm_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    try:
        if not _df.empty:
            _n_rows = len(_df)
            _has_eid = "0__EETRA_ID" in _df.columns
            _eids = (_df["0__EETRA_ID"].astype(str).str.strip().tolist()
                     if _has_eid else [""] * _n_rows)
            # One normalised-or-None column per EPD-number field (Dec first —
            # the order the old loop visited them, which decides first-wins).
            _norm_cols = []
            for _col in ("E__EPD_DecNumber", "E__EPD_RegNumber"):
                if _col in _df.columns:
                    _raw = _df[_col].astype(str).str.strip()
                    _norm_cols.append(_raw.map(
                        lambda s: _eco.norm_epd_num(s) if _is_valid_epd_num(s) else None
                    ).tolist())
            for _i in range(_n_rows):
                _eid = _eids[_i]
                for _nc in _norm_cols:
                    _n = _nc[_i]
                    if _n:
                        epd_nums.add(_n)
                        if _eid and _n not in norm_to_id:
                            norm_to_id[_n] = _eid
            if "A__ProductName" in _df.columns:
                _nm = _df["A__ProductName"].dropna().astype(str).str.strip()
                names_lc = set(_nm[_nm != ""].str.lower())
                if _has_eid:
                    # All rows (NaN names become "nan", as str(NaN) did before).
                    _names = _df["A__ProductName"].astype(str).str.strip().str.lower().tolist()
                    for _eid, _name in zip(_eids, _names):
                        if _eid and _name and _name not in name_to_id:
                            name_to_id[_name] = _eid
    except Exception:
        pass
    return (epd_nums, names_lc, norm_to_id, name_to_id,
            _eco.matlib_signature(epd_nums, names_lc, norm_to_id, name_to_id))


def _fn902_data_sig(df: pd.DataFrame) -> tuple:
    """Scalar key for fn901: app.py's data fingerprint, else a cheap content hash."""
    fp = st.session_state.get("_data_fingerprint")
    if fp is not None:
        return ("fp", tuple(fp), df.shape)
    cols = [c for c in ("0__EETRA_ID", "A__ProductName", "E__EPD_DecNumber", "E__EPD_RegNumber")
            if c in df.columns]
    try:
        h = int(pd.util.hash_pandas_object(df[cols].astype(str), index=False).sum()) if cols else 0
    except Exception:
        h = id(df)
    return ("hash", df.shape, h)


_matlib_sig = _eco.matlib_signature(set(), set(), {}, {})
if _HAS_DATA:
    _prog.progress(80, text="Building MatLib cross-reference…")
    _ml_df: pd.DataFrame = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
    if not _ml_df.empty:
        (_MATLIB_EPD_NUMS, _MATLIB_NAMES_LC, _MATLIB_NORM_TO_ID,
         _MATLIB_NAME_TO_ID, _matlib_sig) = fn901_matlib_xref(_fn902_data_sig(_ml_df), _ml_df)

# ── Stamp in_matlib + build distribution counters (cached on scalar keys) ────
_n_cat_rows = 0
_n_matlib = 0
_prod_counter: Counter = Counter()
_mat_counter:  Counter = Counter()
_man_mtime = _eco.manifest_mtime_ns()
if _base_rows:
    _n_cat_rows, _n_matlib, _prod_counts, _mat_counts = _eco.matlib_row_stats(
        str(_MAPPING_OUTPUT), _map_mtime,
        str(_MAPPING_INPUT),  _proc_mtime,
        str(_XML_PROC_DIR),   _xml_mtime,
        _man_mtime, _matlib_sig,
        _MATLIB_EPD_NUMS, _MATLIB_NAMES_LC,
    )
    _prod_counter = Counter(_prod_counts)
    _mat_counter = Counter(_mat_counts)

_load_elapsed = time.perf_counter() - _load_t0
_prog_ph.empty()


# ══════════════════════════════════════════════════════════════════════════════
# Page header — standard app header (fn003), then dataset stats
# ══════════════════════════════════════════════════════════════════════════════
_subtitle = "ILCD / EPD data from soda4LCA nodes — browsed fully client-side."
if _n_cat_rows:
    _stats_parts = [f"{_n_cat_rows:,} EPDs"]
    if _n_matlib:
        _stats_parts.append(f"{_n_matlib:,} matched in the catalogue")
    _subtitle += "  ·  " + " · ".join(_stats_parts)
fn003a_page_header("ECOportal", _subtitle, icon="🌿")

# Load timing is developer information, not product copy — admins only.
if _load_elapsed > 0.3:
    fn358_debug_caption(
        f"⏱ Data loaded in {_load_elapsed:.2f} s"
        + (" (cache miss — instant next time)" if _load_elapsed > 2.0 else "")
    )

if not _PIPELINE_OK:
    fn358_debug_caption(f"⚠ Ingestion pipeline unavailable — {_PIPELINE_ERR}. Browsing still works.")


# ══════════════════════════════════════════════════════════════════════════════
# Tabs
# ══════════════════════════════════════════════════════════════════════════════
# Tab labels: plain text. Icons belong to top-level st.Page entries only.
_tab_browser, _tab_overview, _tab_pipeline = st.tabs(
    ["EPD Browser", "Overview", "Data & Pipeline"]
)


# ──────────────────────────────────────────────────────────────────────────────
# 🖥 TAB 1 — EPD Browser  (the star: full client-side component)
# ──────────────────────────────────────────────────────────────────────────────
_EPD_IFRAME_HEIGHT = fn359_iframe_height("ecoportal")

with _tab_browser:
    if not _n_cat_rows:
        fn356_empty_state(
            "No ingested EPD dataset yet.",
            hint="Open the **Data & Pipeline** tab, run **Ingest**, then **Map** to populate the browser.",
        )
    else:
        # The final HTML (rows + gzip + output map) is cached on scalar keys —
        # rebuilding it was ~8 s of every rerun on this page.
        _browser_html = _eco.build_epd_browser_page_html(
            str(_MAPPING_OUTPUT), _map_mtime,
            str(_MAPPING_INPUT),  _proc_mtime,
            str(_XML_PROC_DIR),   _xml_mtime,
            _man_mtime, _eco.browser_template_mtime_ns(),
            int(_EPD_IFRAME_HEIGHT), _matlib_sig,
            _MATLIB_EPD_NUMS, _MATLIB_NAMES_LC,
            _MATLIB_NORM_TO_ID, _MATLIB_NAME_TO_ID,
        )
        _eco.render_epd_browser_cached_html(
            _browser_html,
            str(_MAPPING_OUTPUT), _map_mtime,
            iframe_height=_EPD_IFRAME_HEIGHT,
        )


# ──────────────────────────────────────────────────────────────────────────────
# 📊 TAB 2 — Overview  (distribution charts + mapping coverage)
# ──────────────────────────────────────────────────────────────────────────────
with _tab_overview:
    if not _n_cat_rows:
        fn356_empty_state("Run ingestion and mapping first to see distribution and coverage.")
    else:
        # ── Coverage metrics ──────────────────────────────────────────────────
        if _mapping_data:
            _stats = _mapping_data.get("stats", {})
            _total = _stats.get("total", 0)
            _prod_pct = _stats.get("prod_coverage_pct", 0)
            _mat_pct  = _stats.get("mat_coverage_pct", 0)
            _none_n   = _stats.get("none_mapped", 0)
            _none_pct = round(_none_n / _total * 100, 1) if _total else 0
            _both     = _stats.get("both_mapped", 0)
            _generated = _mapping_data.get("generated", "—")

            st.caption(
                f"Mapping generated: **{_generated}** · "
                f"source: `{_mapping_data.get('source', '—')}` · {_total:,} entries"
            )

            _mc1, _mc2, _mc3, _mc4 = st.columns(4)
            with _mc1:
                st.markdown(
                    f'<div class="eco-metric"><div class="val">{_prod_pct:.1f}%</div>'
                    f'<div class="lbl">ProdType coverage</div></div>',
                    unsafe_allow_html=True,
                )
            with _mc2:
                st.markdown(
                    f'<div class="eco-metric"><div class="val">{_mat_pct:.1f}%</div>'
                    f'<div class="lbl">MatType coverage</div></div>',
                    unsafe_allow_html=True,
                )
            with _mc3:
                st.markdown(
                    f'<div class="eco-metric"><div class="val">{_both:,}</div>'
                    f'<div class="lbl">Both mapped</div></div>',
                    unsafe_allow_html=True,
                )
            with _mc4:
                st.markdown(
                    f'<div class="eco-metric"><div class="val" style="color:#dc2626;">{_none_n:,}</div>'
                    f'<div class="lbl">Not mapped ({_none_pct:.1f}%)</div></div>',
                    unsafe_allow_html=True,
                )

            _conf = _stats.get("confidence", {})
            _conf_html = ""
            for _lvl, _cls in [("high", "eco-badge-green"), ("medium", "eco-badge-orange"),
                               ("none", "eco-badge-red")]:
                _conf_html += f'<span class="eco-badge {_cls}">{_lvl}: {_conf.get(_lvl, 0):,}</span> '
            st.markdown("<div style='margin:10px 0;'>" + _conf_html + "</div>", unsafe_allow_html=True)

        st.divider()

        # ── Distribution charts ───────────────────────────────────────────────
        _ch1, _ch2 = st.columns(2)
        with _ch1:
            if _prod_counter:
                _df_prod = pd.DataFrame(
                    [(_prod_label(c), n) for c, n in _prod_counter.most_common(25)],
                    columns=["Product type", "Count"],
                ).sort_values("Count")
                _fig_prod = px.bar(
                    _df_prod, x="Count", y="Product type", orientation="h",
                    title=f"Product type distribution — {_n_cat_rows:,} EPDs",
                    height=max(320, min(60 * len(_df_prod) + 80, 700)),
                    color="Count", color_continuous_scale="Blues",
                )
                _fig_prod.update_layout(
                    margin=dict(l=10, r=10, t=40, b=10),
                    coloraxis_showscale=False, yaxis_title="", xaxis_title="",
                )
                st.plotly_chart(_fig_prod, width="stretch")
            else:
                fn356_empty_state("No product type data available.", kind="empty")

        with _ch2:
            if _mat_counter:
                _df_mat = pd.DataFrame(
                    [(_mat_label(c), n) for c, n in _mat_counter.most_common(25)],
                    columns=["Material type", "Count"],
                ).sort_values("Count")
                _fig_mat = px.bar(
                    _df_mat, x="Count", y="Material type", orientation="h",
                    title=f"Material type distribution — {_n_cat_rows:,} EPDs",
                    height=max(320, min(60 * len(_df_mat) + 80, 700)),
                    color="Count", color_continuous_scale="Greens",
                )
                _fig_mat.update_layout(
                    margin=dict(l=10, r=10, t=40, b=10),
                    coloraxis_showscale=False, yaxis_title="", xaxis_title="",
                )
                st.plotly_chart(_fig_mat, width="stretch")
            else:
                fn356_empty_state("No material type data available.", kind="empty")


# ──────────────────────────────────────────────────────────────────────────────
# ⚙ TAB 3 — Data & Pipeline  (admin: ingest · map · raw output · raw XML)
# ──────────────────────────────────────────────────────────────────────────────
with _tab_pipeline:

    base_url   = (_SECRETS.get("base_url") or "").strip()
    _has_creds = bool(_SECRETS.get("api_token")) or (
        bool(_SECRETS.get("client_id")) and bool(_SECRETS.get("client_secret"))
    )

    # ═════════════════ ① INGEST ═════════════════
    with st.expander("① Ingest — download from a soda4LCA node", expanded=not _HAS_DATA):
        if not _PIPELINE_OK:
            st.error(f"Pipeline package unavailable: `{_PIPELINE_ERR}`")
        else:
            # ── Settings ──────────────────────────────────────────────────────
            _cfg_col1, _cfg_col2 = st.columns([1, 1], gap="medium")
            with _cfg_col1:
                if not _has_creds:
                    st.markdown(
                        '<span class="eco-badge eco-badge-red">✗ No credentials in secrets.toml</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption("Add a `[soda4lca]` section to `.streamlit/secrets.toml`.")
                elif not base_url:
                    st.markdown(
                        '<span class="eco-badge eco-badge-red">✗ No base_url in secrets.toml</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<span class="eco-badge eco-badge-green">✓ Node configured</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"`{base_url}`")

                st.markdown("**Dataset types**")
                selected_types: list[str] = []
                for _dt in DATASET_TYPES:
                    if st.checkbox(_dt, value=(_dt == "processes"), key=f"eco_cb_{_dt}"):
                        selected_types.append(_dt)

            with _cfg_col2:
                st.markdown("**Performance**")
                max_workers = st.slider("Parallel workers", 1, 20, 8, key="eco_workers")
                rate_limit  = st.slider("Max RPS", 1.0, 30.0, 10.0, step=0.5, key="eco_rps")
                page_size   = st.selectbox("Page size", [100, 250, 500, 1000], index=2, key="eco_page_size")
                max_retries = st.slider("Max retries", 1, 10, 5, key="eco_retries")
                output_dir  = st.text_input(
                    "Output directory", value=_DEFAULT_OUTPUT, key="eco_output_dir",
                    help="Absolute or relative path for downloaded data.",
                )

            st.divider()

            # ── Controls ──────────────────────────────────────────────────────
            c_btn, c_dry, c_status = st.columns([2, 2, 4])
            with c_btn:
                run_clicked = st.button(
                    "▶ Start ingestion",
                    type="primary",
                    disabled=not selected_types or not base_url or not _has_creds,
                    width='stretch',
                    key="eco_run",
                )
            with c_dry:
                dry_run = st.toggle("Dry run (count only)", value=False, key="eco_dry")
            with c_status:
                _status_ph = st.empty()

            # ── Metrics row ───────────────────────────────────────────────────
            _m1, _m2, _m3, _m4, _m5 = st.columns(5)
            _met_total   = _m1.empty()
            _met_ok      = _m2.empty()
            _met_skip    = _m3.empty()
            _met_fail    = _m4.empty()
            _met_elapsed = _m5.empty()

            def _render_metrics(summary: dict | None = None, elapsed: float = 0.0) -> None:
                total = ok = skip = fail = 0
                if summary:
                    for _s in summary.get("byType", {}).values():
                        total += _s.get("total", 0)
                        ok    += _s.get("succeeded", 0)
                        skip  += _s.get("skipped", 0)
                        fail  += _s.get("failed", 0)
                _met_total.metric("Total datasets",   total)
                _met_ok.metric("Downloaded",          ok)
                _met_skip.metric("Skipped (cached)",  skip)
                _met_fail.metric("Failed",            fail)
                _met_elapsed.metric("Elapsed",        f"{elapsed:.0f}s")

            _progress_ph = st.empty()

            def _render_type_progress(stats: dict) -> None:
                rows = []
                for _dt, _s in stats.items():
                    _tot  = _s.get("total", 0)
                    _done = _s.get("succeeded", 0) + _s.get("skipped", 0)
                    _pct  = int(_done / _tot * 100) if _tot else 0
                    _fail = _s.get("failed", 0)
                    _col  = "#dc2626" if _fail else "#16a34a"
                    rows.append(
                        f'<div class="type-row">'
                        f'<span class="type-label">{_dt}</span>'
                        f'<div class="type-bar-wrap">'
                        f'<div class="type-bar" style="width:{_pct}%;background:{_col};"></div>'
                        f'</div>'
                        f'<span class="type-count">{_done}/{_tot}</span>'
                        f'</div>'
                    )
                _progress_ph.markdown(
                    "<div style='padding:8px 0;'>" + "".join(rows) + "</div>",
                    unsafe_allow_html=True,
                )

            # Show last-saved metrics if available
            _saved_stats = None
            _mp = resolve_output_dir(output_dir) / "manifest.json"
            if _mp.exists():
                try:
                    _saved_stats = json.loads(_mp.read_text(encoding="utf-8")).get("stats")
                except Exception:
                    pass

            _render_metrics(_saved_stats, float((_saved_stats or {}).get("elapsedSeconds", 0)))
            _render_type_progress(
                (_saved_stats or {}).get("byType", {dt: {} for dt in selected_types})
            )
            if _saved_stats and not st.session_state.get("eco_ingestion_running"):
                _available = sum(
                    _s.get("succeeded", 0) + _s.get("skipped", 0)
                    for _s in _saved_stats.get("byType", {}).values()
                )
                _status_ph.success(
                    f"Loaded saved output from `{output_dir}` — {_available:,} datasets available."
                )

            # ── Log area ──────────────────────────────────────────────────────
            st.markdown("**Live log**")
            _log_ph   = st.empty()
            _log_lines: list[str] = []

            def _append_log(line: str) -> None:
                _cls = "color:#8b949e"
                _ll  = line.lower()
                if " ok " in _ll or "succeeded" in _ll or "done" in _ll:
                    _cls = "color:#16a34a"
                elif "warn" in _ll or "skip" in _ll:
                    _cls = "color:#d97706"
                elif "fail" in _ll or "error" in _ll:
                    _cls = "color:#dc2626"
                _log_lines.append(f'<span style="{_cls}">{line}</span>')
                _log_ph.markdown(
                    '<div class="log-box">' + "\n".join(_log_lines[-200:]) + "</div>",
                    unsafe_allow_html=True,
                )

            # ── Run ───────────────────────────────────────────────────────────
            if run_clicked:
                if st.session_state.get("eco_ingestion_running"):
                    st.warning("An ingestion is already running. Wait for it to finish or restart Streamlit.")
                elif not selected_types:
                    st.warning("Select at least one dataset type.")
                elif not _has_creds:
                    st.warning("Add credentials under `[soda4lca]` in `.streamlit/secrets.toml`.")
                elif not base_url:
                    st.warning("Set `base_url` in `.streamlit/secrets.toml` under `[soda4lca]`.")
                else:
                    _cfg = PipelineConfig(
                        base_url=base_url,
                        page_size=page_size,
                        max_workers=max_workers,
                        rate_limit_rps=rate_limit,
                        max_retries=max_retries,
                        output_dir=str(resolve_output_dir(output_dir)),
                        dataset_types=selected_types,
                        auth_user=None,
                        auth_pass=None,
                        bearer_token=_SECRETS.get("api_token") or None,
                    )

                    if dry_run:
                        _status_ph.info("🔍 Dry run — counting UUIDs…")
                        _append_log(f"[{datetime.now():%H:%M:%S}] DRY RUN → {base_url}")
                        with SodaApiClient(_cfg) as _client:
                            _dry_res: dict[str, int] = {}
                            for _dt in selected_types:
                                try:
                                    _uuids = _client.fetch_all_uuids(_dt)
                                    _dry_res[_dt] = len(_uuids)
                                    _append_log(f"[{datetime.now():%H:%M:%S}]  {_dt:<16} → {len(_uuids)} datasets")
                                except Exception as _e:
                                    _dry_res[_dt] = 0
                                    _append_log(f"[{datetime.now():%H:%M:%S}]  ERROR {_dt}: {_e}")
                        _total_found = sum(_dry_res.values())
                        _status_ph.success(f"✅ Dry run — {_total_found} datasets across {len(_dry_res)} types")
                        _render_type_progress({
                            _dt: {"total": _n, "succeeded": 0, "skipped": 0, "failed": 0}
                            for _dt, _n in _dry_res.items()
                        })
                    else:
                        st.session_state["eco_ingestion_running"] = True
                        _status_ph.info("⏳ Ingestion running…")

                        _log_q: queue.Queue = queue.Queue()

                        class _QH(logging.Handler):
                            def emit(self, rec: logging.LogRecord):
                                _log_q.put(self.format(rec))

                        _qh = _QH()
                        _qh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"))
                        _root_log = logging.getLogger()
                        _root_log.setLevel(logging.INFO)
                        _root_log.addHandler(_qh)

                        _result_h: dict = {}
                        _exc_h:    dict = {}
                        _t0 = time.monotonic()

                        def _run_ingest():
                            try:
                                _result_h["summary"] = run_ingestion(_cfg)
                            except Exception as _e:
                                _exc_h["error"] = str(_e)
                                logging.exception("Ingestion thread crashed")

                        _thread = threading.Thread(target=_run_ingest, daemon=True)
                        _thread.start()

                        _append_log(f"[{datetime.now():%H:%M:%S}] Started → {base_url}")
                        _append_log(f"[{datetime.now():%H:%M:%S}] Types: {', '.join(selected_types)}  Workers={max_workers}")

                        while _thread.is_alive() or not _log_q.empty():
                            try:
                                _append_log(_log_q.get_nowait())
                            except queue.Empty:
                                pass
                            _elapsed = time.monotonic() - _t0
                            _man_path = resolve_output_dir(output_dir) / "manifest.json"
                            if _man_path.exists():
                                try:
                                    _partial = json.loads(_man_path.read_text())
                                    _render_metrics(_partial.get("stats"), _elapsed)
                                    _render_type_progress(
                                        _partial.get("stats", {}).get("byType",
                                            {_dt: {} for _dt in selected_types})
                                    )
                                except Exception:
                                    pass
                            else:
                                _render_metrics(elapsed=_elapsed)
                            time.sleep(0.25)

                        st.session_state["eco_ingestion_running"] = False
                        _root_log.removeHandler(_qh)
                        _elapsed = time.monotonic() - _t0

                        if "error" in _exc_h:
                            _status_ph.error(f"❌ Ingestion failed: {_exc_h['error']}")
                        elif "summary" in _result_h:
                            _summary = _result_h["summary"]
                            _render_metrics(_summary, _elapsed)
                            _render_type_progress(_summary.get("byType", {}))
                            _nfail = sum(_s.get("failed", 0) for _s in _summary.get("byType", {}).values())
                            if _nfail:
                                _status_ph.warning(f"⚠ Completed with {_nfail} failures. Check log.")
                            else:
                                _status_ph.success(f"✅ Done in {_elapsed:.0f}s — reload the page to browse.")

    # ═════════════════ ② MAP ═════════════════
    with st.expander("② Map — classify ingested processes", expanded=False):
        if _mapping_data:
            _stats = _mapping_data.get("stats", {})
            _total = _stats.get("total", 0)
            st.caption(
                f"Current mapping: **{_mapping_data.get('generated', '—')}** · "
                f"{_total:,} entries · "
                f"ProdType {_stats.get('prod_coverage_pct', 0):.1f}% · "
                f"MatType {_stats.get('mat_coverage_pct', 0):.1f}%"
            )
        else:
            fn356_empty_state("No mapping file yet — run the mapper below after ingestion.")

        _rb1, _rb2 = st.columns([2, 4])
        with _rb1:
            _run_map = st.button(
                "▶ Run mapping",
                type="primary",
                width='stretch',
                key="eco_run_mapping",
                disabled=not _MAPPING_INPUT.exists(),
                help=f"Reads {_MAPPING_INPUT.name} and writes {_MAPPING_OUTPUT.name}",
            )
        with _rb2:
            if not _MAPPING_INPUT.exists():
                st.markdown(
                    '<span class="eco-badge eco-badge-red">✗ processes.json not found — ingest first</span>',
                    unsafe_allow_html=True,
                )
            else:
                _input_mb = _MAPPING_INPUT.stat().st_size / (1024 ** 2)
                st.markdown(
                    f'<span class="eco-badge eco-badge-green">✓ {_input_mb:.1f} MB input ready</span>',
                    unsafe_allow_html=True,
                )

        if _run_map:
            _map_out_ph = st.empty()
            _map_log_ph = st.empty()
            _map_lines: list[str] = []

            def _map_append(line: str):
                _map_lines.append(line)
                _map_log_ph.markdown(
                    '<div class="log-box">' + "\n".join(_map_lines[-100:]) + "</div>",
                    unsafe_allow_html=True,
                )

            _map_append(f"[{datetime.now():%H:%M:%S}] Running {_MAPPING_SCRIPT.name}…")
            with fn357_loading("Running mapping…"):
                try:
                    _proc = subprocess.run(
                        [sys.executable, str(_MAPPING_SCRIPT)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        cwd=str(_SODA_ROOT), timeout=300,
                    )
                    for _ln in (_proc.stdout or "").splitlines():
                        _map_append(_ln)
                    if _proc.stderr:
                        for _ln in _proc.stderr.splitlines():
                            _map_append(f"[STDERR] {_ln}")
                    if _proc.returncode == 0:
                        _map_out_ph.success("✅ Mapping complete — reload the page to see updated stats.")
                    else:
                        _map_out_ph.error(f"❌ Mapping script exited with code {_proc.returncode}")
                except subprocess.TimeoutExpired:
                    _map_out_ph.error("❌ Mapping script timed out (300 s)")
                except Exception as _me:
                    _map_out_ph.error(f"❌ {_me}")

    # ═════════════════ ③ RAW OUTPUT ═════════════════
    with st.expander("③ Raw output — files & aggregated downloads", expanded=False):
        _browse_dir_input = st.text_input(
            "Directory to browse", value=_DEFAULT_OUTPUT, key="eco_browse_dir"
        )
        _browse_root = resolve_output_dir(_browse_dir_input)

        if not _browse_root.exists():
            fn356_empty_state(
                f"Directory `{_browse_root}` does not exist yet.",
                hint="Run ingestion, or point the field above at an existing output folder.",
            )
        else:
            _manifest = load_manifest(_browse_dir_input)
            if _manifest:
                st.markdown("**Last ingestion summary**")
                _dt_counts = _manifest.get("datasetTypes", {})
                if _dt_counts:
                    _mc = st.columns(min(len(_dt_counts), 6) or 1)
                    for _i, (_dt, _cnt) in enumerate(_dt_counts.items()):
                        _mc[_i % len(_mc)].metric(_dt, f"{_cnt:,}")
                st.caption(f"Node: `{_manifest.get('baseUrl', '—')}`")
                st.divider()

            st.markdown("**Saved files**")
            _any_files = False
            for _dt in DATASET_TYPES:
                _json_dir = _browse_root / "json" / _dt
                _xml_dir  = _browse_root / "xml"  / _dt
                if not _json_dir.exists():
                    continue
                _cnt = dataset_count(_manifest, _dt, _browse_dir_input)
                if not _cnt:
                    _cnt = sum(1 for _ in _json_dir.glob("*.json"))
                if not _cnt:
                    continue
                _any_files = True
                with st.expander(f"**{_dt}** — {_cnt:,} datasets", expanded=False):
                    _jf = sorted(_json_dir.glob("*.json"))[:50]
                    _xf = sorted(_xml_dir.glob("*.xml"))[:50] if _xml_dir.exists() else []
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        st.caption(f"JSON — {_cnt:,} files")
                        for _f in _jf:
                            st.text(_f.name)
                        if _cnt > len(_jf):
                            st.caption(f"… first {len(_jf)} of {_cnt:,}")
                    with _c2:
                        st.caption("XML")
                        for _f in _xf:
                            st.text(_f.name)
            if not _any_files:
                fn356_empty_state("No dataset files found — run ingestion first.", kind="empty")

            st.divider()
            st.markdown("**Aggregated JSON downloads**")
            _agg_dir = _browse_root / "aggregated"
            if _agg_dir.exists():
                _agg_files = sorted(_agg_dir.glob("*.json"))
                if _agg_files:
                    _dc = st.columns(min(len(_agg_files), 4))
                    for _i, _af in enumerate(_agg_files):
                        _sz = _af.stat().st_size / (1024 ** 2)
                        with _dc[_i % 4]:
                            st.download_button(
                                f"⬇ {_af.stem}  ({_sz:.1f} MB)",
                                data=_af.read_bytes(),
                                file_name=_af.name,
                                mime="application/json",
                                width='stretch',
                                key=f"eco_dl_{_af.stem}",
                            )
                else:
                    fn356_empty_state("No aggregated files yet.", kind="empty")
            else:
                fn356_empty_state("Aggregated directory not found — run ingestion first.", kind="empty")

    # ═════════════════ ④ RAW XML INSPECTOR ═════════════════
    with st.expander("④ Raw XML inspector — view a single ILCD process file", expanded=False):
        _xml_files: list[Path] = sorted(_XML_PROC_DIR.glob("*.xml")) if _XML_PROC_DIR.exists() else []
        if not _xml_files:
            fn356_empty_state(
                f"No XML files found in `{_XML_PROC_DIR}`.",
                kind="empty",
                hint="Run ingestion to download ILCD XML files, then inspect them here.",
            )
        else:
            st.caption(f"{len(_xml_files):,} ILCD process XML files available.")
            _xml_filter = st.text_input(
                "Filter by name / UUID", key="eco_xml_filter",
                placeholder="type to narrow the list…",
            )
            _shown = _xml_files
            if _xml_filter:
                _needle = _xml_filter.lower()
                _shown = [_f for _f in _xml_files if _needle in _f.name.lower()]
            _shown = _shown[:500]

            if not _shown:
                fn356_empty_state("No files match that filter.", kind="empty")
            else:
                _pick = st.selectbox(
                    f"Select file  ({len(_shown)} shown)",
                    options=_shown,
                    format_func=lambda p: p.name,
                    key="eco_xml_pick",
                )
                if _pick is not None:
                    try:
                        _xml_text = _pick.read_text(encoding="utf-8", errors="replace")
                        st.caption(f"`{_pick}` · {len(_xml_text):,} chars")
                        st.download_button(
                            "⬇ Download XML",
                            data=_pick.read_bytes(),
                            file_name=_pick.name,
                            mime="application/xml",
                            key="eco_xml_dl",
                        )
                        st.code(_xml_text, language="xml")
                    except Exception as _xe:
                        st.error(f"Could not read `{_pick.name}`: {_xe}")
