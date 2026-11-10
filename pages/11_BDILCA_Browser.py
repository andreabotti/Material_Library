"""
pages/11_BDILCA_Browser.py — BDI-LCA ARCADIA Browser
──────────────────────────────────────────────────────
EcoPortal-style interactive browser for the ENEA Italian LCA database.
Reads ILCD XML files from xml_processes/ and renders a two-panel UI:
  left  → searchable/filterable process list
  right → process detail with accordion sections + exchange table
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

from libs.lib_header import fn003a_page_header
from libs.lib_ui import (
    fn352_is_embedded_page,
    fn356_empty_state,
    fn357_loading,
    fn359_iframe_height,
)

# ── Path setup ────────────────────────────────────────────────────────────────
_PAGE_FILE = Path(__file__).resolve()
_APP_ROOT  = _PAGE_FILE.parents[1]          # EETRA_MatLib_2026.05/
_XML_DIR   = _APP_ROOT / "01_data" / "xml_processes"
_HTML_TMPL = _APP_ROOT / "02_html" / "bdilca_browser.html"

if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from bdilca_xml_parse import parse_xml  # noqa: E402

# ── Cached data loader ────────────────────────────────────────────────────────
# cache_resource, not cache_data: cache_data unpickled a full deep copy of every
# process + exchange list on each rerun. The result is SHARED across sessions —
# treat it as read-only (this page only reads/serialises it). It also returns
# the XML file count so the page no longer re-globs the OneDrive folder per rerun.
@st.cache_resource(show_spinner=False, max_entries=2)
def _load_bdilca(xml_dir_mtime: int) -> tuple[list[dict], dict[str, list[dict]], list[str], int]:
    """Parse all ILCD XML files; returns (processes, exchanges_by_uuid, errors, n_files)."""
    xml_files = sorted(_XML_DIR.glob("*.xml"))
    processes: list[dict] = []
    exchanges: dict[str, list[dict]] = {}
    errors: list[str] = []

    for fp in xml_files:
        try:
            meta, excs = parse_xml(fp)
            processes.append(meta)
            exchanges[meta["uuid"]] = excs
        except Exception as e:
            errors.append(f"{fp.name}: {e}")

    return processes, exchanges, errors, len(xml_files)


@st.cache_data(show_spinner=False, max_entries=2)
def _fn1101_bdilca_html(xml_dir_mtime: int, tmpl_mtime: int) -> str:
    """Final iframe HTML (JSON payload injected into the template).

    json.dumps of the whole dataset (~2.5 MB) used to run on every rerun; it only
    changes with the XML folder or the template, which are the cache key.
    """
    processes, exchanges, _errors, _n = _load_bdilca(xml_dir_mtime)
    payload = json.dumps(
        {"processes": processes, "exchanges": exchanges},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    html_src = _HTML_TMPL.read_text(encoding="utf-8")
    return html_src.replace("/*BDILCA_DATA_PLACEHOLDER*/null", payload, 1)


# ── Page header ───────────────────────────────────────────────────────────────
if not fn352_is_embedded_page():
    fn003a_page_header(
        "BDI-LCA ARCADIA Browser",
        "ENEA Italian LCA Database, ILCD format — bancadatiitalianalca.enea.it",
        icon="🇮🇹",
    )

# ── Resolve XML directory ─────────────────────────────────────────────────────
if not _XML_DIR.is_dir():
    fn356_empty_state(
        f"XML directory not found: `{_XML_DIR}`",
        kind="error",
        hint="Run `bdilca_xml_download.py` to populate it.",
    )
    st.stop()

# ── Load data (cache keyed on directory mtime) ────────────────────────────────
# Adding/removing a file bumps the directory mtime, so the file count comes from
# the cached result instead of a per-rerun glob of the OneDrive folder.
_mtime = int(_XML_DIR.stat().st_mtime_ns)

with fn357_loading("Loading ILCD XML files…"):
    processes, exchanges, errors, _n_xml_files = _load_bdilca(_mtime)

if not _n_xml_files:
    fn356_empty_state(
        "No XML files in `01_data/xml_processes/`.",
        kind="empty",
        hint="Run `bdilca_xml_download.py` to download the ARCADIA dataset.",
    )
    st.stop()

if errors:
    with st.expander(f"⚠️ {len(errors)} parse error(s)", expanded=False, type="compact"):
        for e in errors:
            st.text(e)

n_proc = len(processes)
n_excs = sum(len(v) for v in exchanges.values())

col1, col2, col3 = st.columns(3)
col1.metric("Processes", n_proc)
col2.metric("Exchange Flows", n_excs)
col3.metric("XML Files", _n_xml_files)

st.divider()

# ── Load HTML template and inject data (cached) ──────────────────────────────
if not _HTML_TMPL.exists():
    fn356_empty_state(f"HTML template missing: `{_HTML_TMPL}`", kind="error")
    st.stop()

html_out = _fn1101_bdilca_html(_mtime, int(_HTML_TMPL.stat().st_mtime_ns))

# ── Render ────────────────────────────────────────────────────────────────────
_BROWSER_HEIGHT = fn359_iframe_height("bdilca")

st.iframe(html_out, height=_BROWSER_HEIGHT)
