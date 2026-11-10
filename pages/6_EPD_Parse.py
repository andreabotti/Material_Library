"""
6_EPD_Ingestion.py  –  EETRA Material Library · EPD Ingestion page
────────────────────────────────────────────────────────────────────────────
Workflow:
  1. Upload EPD PDF(s) or pick them from `01_data/epd_pdf`
  2. Extract via libs.lib_epd_extractor  (deterministic → text → vision)
  3. Review: structured 3-column form (Field | Parsed | Editable) for
     every section, plus horizontal per-module GWP/LCA tables
  4. Commit approved records to session; export CSV / JSON

Essential fields (always extracted):
  GWP total/fossil/biogenic/LULUC per lifecycle module,
  product name, manufacturer, declared unit, standard,
  EPD declaration number / registration number (legacy epd_number mirrored), validity

Optional detail fields (second Claude call):
  Product description, composition (materials + % mass), production method,
  system boundary, modules declared, flow description, functional unit,
  geographic scope, verifier, PCR, LCA software/database
"""

import base64
import hashlib
import html as _html
import json
import os
import tempfile
from pathlib import Path
import time
from decimal import Decimal, InvalidOperation

import anthropic
import pandas as pd
import streamlit as st

try:
    from libs.lib_epd_extractor import extract_epd, estimate_cost, _ESSENTIAL_KEYS, _DETAIL_KEYS
except ImportError:
    st.error("Cannot import `libs.lib_epd_extractor`. Run the app from the project root.")
    st.stop()

# ── Page config ───────────────────────────────────────────────────────────────
_EMBED = st.session_state.get("_epd_parse_embedded_in_developer", False)
if not _EMBED:
    st.set_page_config(page_title="EPD Ingestion", page_icon="🏗️", layout="wide")

_EPD_SOURCE_UPLOAD = "Upload files"
_EPD_SOURCE_LIBRARY = "Library folder (01_01_data/epd_pdf)"


def _epd_pdf_library_dir() -> Path:
    """Project folder `01_01_data/epd_pdf` (next to `pages/`)."""
    return Path(__file__).resolve().parent.parent / "01_data" / "epd_pdf"


def _list_epd_library_pdf_basenames() -> list[str]:
    d = _epd_pdf_library_dir()
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
    )


def _pdf_jobs_for_extract(
    source: str,
    uploads,
    lib_names: list[str],
) -> list[tuple[str, bytes]]:
    jobs: list[tuple[str, bytes]] = []
    if source == _EPD_SOURCE_UPLOAD:
        for uf in uploads or []:
            jobs.append((uf.name, uf.read()))
        return jobs
    lib_root = _epd_pdf_library_dir().resolve()
    for base in lib_names or []:
        path = (lib_root / base).resolve()
        if not path.is_file():
            continue
        try:
            path.relative_to(lib_root)
        except ValueError:
            continue
        jobs.append((base, path.read_bytes()))
    return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# Field manifest — defines every editable row in the review form
# ═══════════════════════════════════════════════════════════════════════════════

_FIELD_MANIFEST = [
    # ── EPD Identifiers ───────────────────────────────────────────────────────
    {"section": "EPD Identifiers",  "key": "epd_declaration_number", "label": "EPD declaration number"},
    {"section": None,               "key": "epd_registration_number", "label": "Registration number"},
    {"section": None,               "key": "programme_operator",      "label": "Programme Operator"},
    {"section": None,               "key": "validity_date",           "label": "Valid Until"},
    {"section": None,               "key": "issue_date",              "label": "Issue Date"},
    {"section": None,               "key": "revision_date",           "label": "Revision Date"},
    {"section": None,               "key": "reference_standard",      "label": "Standard"},
    # ── Product ───────────────────────────────────────────────────────────────
    {"section": "Product",          "key": "manufacturer",            "label": "Manufacturer"},
    {"section": None,               "key": "product_name",            "label": "Product Name"},
    {"section": None,               "key": "product_description",     "label": "Description",         "multiline": True},
    {"section": None,               "key": "declared_unit",           "label": "Declared Unit"},
    {"section": None,               "key": "functional_unit",         "label": "Functional Unit",     "multiline": True},
    # ── System Boundary ───────────────────────────────────────────────────────
    {"section": "System Boundary",  "key": "system_boundary",        "label": "Scope"},
    {"section": None,               "key": "modules_declared",        "label": "Modules Declared"},
    # ── LCA Methodology ───────────────────────────────────────────────────────
    {"section": "LCA Methodology",  "key": "lca_database",           "label": "LCI Database"},
    {"section": None,               "key": "lca_software",            "label": "LCA Software"},
    {"section": None,               "key": "pcr_reference",           "label": "PCR Reference"},
    {"section": None,               "key": "geographic_scope",        "label": "Geographic Validity"},
    {"section": None,               "key": "third_party_verifier",    "label": "Third-Party Verifier"},
    # ── Content ───────────────────────────────────────────────────────────────
    {"section": "Content",          "key": "recycled_content_pct",   "label": "Recycled Content",          "unit": "%"},
    {"section": None,               "key": "sm",                     "label": "Secondary Material (SM)",   "unit": "kg/FU"},
    # GWP and all other LCA indicators are rendered in the data-driven
    # horizontal indicator tables below — they are intentionally absent here.
    # ── Notes ─────────────────────────────────────────────────────────────────
    {"section": "Notes",            "key": "notes",                  "label": "Extraction Notes",  "multiline": True},
    {"section": None,               "key": "confidence",             "label": "Confidence (high / medium / low)"},
]

# ── Indicator table configuration ────────────────────────────────────────────
# Canonical lifecycle module order and display labels.
# The renderer discovers which of these columns actually exist in each record
# and only shows those — fully data-driven, no hardcoded column lists.

_MODULE_ORDER: list[tuple[str, str]] = [
    # (key_suffix,  display_label)
    ("a1",     "A1"),
    ("a2",     "A2"),
    ("a3",     "A3"),
    ("a1a3",   "A1-A3"),   # combined column (some EPD formats)
    ("a4",     "A4"),
    ("a5",     "A5"),
    ("b1",     "B1"),
    ("b2",     "B2"),
    ("b3",     "B3"),
    ("b4",     "B4"),
    ("b5",     "B5"),
    ("b6",     "B6"),
    ("b7",     "B7"),
    ("b1_b7",  "B1-B7"),   # combined use-stage column (some formats)
    ("c1",     "C1"),
    ("c2",     "C2"),
    ("c3",     "C3"),
    ("c4",     "C4"),
    ("d",      "D"),
    ("declared","Declared"),
]

# Longest module suffix first so e.g. `a1a3` wins over `a3`
_MODULE_SUFFIXES_LONGEST_FIRST: list[tuple[str, str]] = sorted(
    _MODULE_ORDER, key=lambda x: len(x[0]), reverse=True
)

# Indicator groups shown in horizontal EPD-table layout
_INDICATOR_GROUPS: list[tuple[str, str, str]] = [
    # (section_title,  field_prefix,  unit_label)
    ("GWP — Total",      "gwp_total",      "kg CO₂ eq."),
    ("GWP — Fossil",     "gwp_fossil",     "kg CO₂ eq."),
    ("GWP — Biogenic",   "gwp_biogenic",   "kg CO₂ eq."),
    ("GWP — LULUC",      "gwp_luluc",      "kg CO₂ eq."),
    ("ODP",              "odp",            "kg CFC-11 eq."),
    ("AP",               "ap",             "mol H⁺ eq."),
    ("EP — Freshwater",  "ep_freshwater",  "kg P eq."),
    ("EP — Marine",      "ep_marine",      "kg N eq."),
    ("EP — Terrestrial", "ep_terrestrial", "mol N eq."),
    ("POCP",             "pocp",           "kg NMVOC eq."),
    ("ADPE",             "adpe",           "kg Sb eq."),
    ("ADPF",             "adpf",           "MJ"),
    ("WDP",              "wdp",            "m³ world eq."),
    ("PENRE",            "penre",          "MJ"),
    ("PERE",             "pere",           "MJ"),
    ("SM",               "sm",             "kg"),
    ("FW",               "fw",             "m³"),
]

# Horizontal layout subsets — tabs after **Content**
_INDICATOR_GROUPS_GWP: list[tuple[str, str, str]] = list(_INDICATOR_GROUPS[:4])
_INDICATOR_GROUPS_OTHER: list[tuple[str, str, str]] = list(_INDICATOR_GROUPS[4:13])
_INDICATOR_GROUPS_RESOURCE: list[tuple[str, str, str]] = list(_INDICATOR_GROUPS[13:])

# Section names rendered in horizontal block — the vertical form skips these keys
_GWP_SECTION_NAMES = {g[0] for g in _INDICATOR_GROUPS}

def _indicator_columns_present(parsed_dict: dict, prefix: str) -> list[tuple[str, str]]:
    """
    Return ordered list of (field_key, display_label) for every module column
    that has a non-None value for the given indicator prefix in parsed_dict.
    Zero (0.0) is a valid declared value and IS included.
    Preserves canonical module order defined in _MODULE_ORDER.
    """
    present = []
    for suffix, label in _MODULE_ORDER:
        key = f"{prefix}_{suffix}"
        val = parsed_dict.get(key)
        # Include if key exists and value is not None (0.0 is valid and must show)
        if key in parsed_dict and val is not None:
            present.append((key, label))
    return present


def _split_indicator_field_key(field_key: str) -> tuple[str, str] | None:
    """Split `gwp_total_a1a3` → ('gwp_total', 'a1a3'). Longest module suffix wins."""
    for suf, _lab in _MODULE_SUFFIXES_LONGEST_FIRST:
        suf_pat = f"_{suf}"
        if field_key.endswith(suf_pat):
            return field_key[: -len(suf_pat)], suf
    return None


def _decimal_places_component(val) -> int:
    """Fractional digits for rounding consistency (from stored float)."""
    if val is None:
        return 0
    try:
        d = Decimal(str(float(val)))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    exp = d.as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _max_decimal_places_a123(parsed_dict: dict, prefix: str) -> int:
    """Max fractional digits among individual A1 / A2 / A3 columns for this indicator."""
    places = [
        _decimal_places_component(parsed_dict.get(f"{prefix}_{s}"))
        for s in ("a1", "a2", "a3")
        if f"{prefix}_{s}" in parsed_dict and parsed_dict.get(f"{prefix}_{s}") is not None
    ]
    return max(places) if places else 0


def _format_rounded_calculated(val: float, places: int) -> str:
    """String display for A1–A3 sums; decimals match the precision of A1/A2/A3."""
    if places <= 0:
        return str(int(round(val)))
    rounded = round(val, places)
    s = f"{rounded:.{places}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _parsed_display_string_indicator(parsed_dict: dict, field_key: str) -> str:
    """Baseline text for indicator cells (rounded calculated A1–A3 sums vs raw string)."""
    sp = _split_indicator_field_key(field_key)
    if sp:
        prefix, suf = sp
        if suf == "a1a3" and parsed_dict.get(f"{field_key}_source") == "calculated":
            raw_v = parsed_dict.get(field_key)
            if raw_v is None:
                return ""
            try:
                fv = float(raw_v)
            except (TypeError, ValueError):
                return str(raw_v)
            places = _max_decimal_places_a123(parsed_dict, prefix)
            if places == 0 and not any(
                parsed_dict.get(f"{prefix}_{s}") is not None for s in ("a1", "a2", "a3")
            ):
                return _fval(parsed_dict, field_key)
            return _format_rounded_calculated(fv, places)
    return _fval(parsed_dict, field_key)


def _indicator_columns_ordered(parsed_dict: dict, prefix: str) -> list[tuple[str, str]]:
    """
    Like `_indicator_columns_present`, but places **calculated** `*_a1a3` first (left column).
    """
    base = _indicator_columns_present(parsed_dict, prefix)
    calc_key = f"{prefix}_a1a3"
    if parsed_dict.get(f"{calc_key}_source") != "calculated":
        return base
    calc_entry: tuple[str, str] | None = None
    rest: list[tuple[str, str]] = []
    for fk, lab in base:
        if fk == calc_key:
            calc_entry = (fk, "A1–A3 · calculated")
        else:
            rest.append((fk, lab))
    if calc_entry is None:
        return base
    return [calc_entry] + rest


def _baseline_field_value(parsed_dict: dict, key: str) -> str:
    """Parsed baseline for edit-detection: indicators use rounded calculated A1–A3 display."""
    if _split_indicator_field_key(key):
        return _parsed_display_string_indicator(parsed_dict, key)
    return _fval(parsed_dict, key)


def _normalize_epd_identifier_fields(d: dict) -> None:
    """
    Fill declaration / registration from legacy `epd_number` or each other.
    Keeps `epd_number` aligned with declaration for downstream compatibility.
    """
    decl = d.get("epd_declaration_number")
    reg = d.get("epd_registration_number")
    leg = d.get("epd_number")

    if decl is None and reg is None and leg is not None:
        decl = leg
        reg = leg
    elif decl is not None and reg is None:
        reg = decl
    elif reg is not None and decl is None:
        decl = reg

    if decl is not None:
        d["epd_declaration_number"] = decl
    if reg is not None:
        d["epd_registration_number"] = reg
    if d.get("epd_declaration_number") is not None:
        d["epd_number"] = d["epd_declaration_number"]
    elif d.get("epd_registration_number") is not None:
        d["epd_number"] = d["epd_registration_number"]

def _indicator_keys_all(prefix: str) -> set[str]:
    """All possible field keys for a given indicator prefix."""
    return {f"{prefix}_{suffix}" for suffix, _ in _MODULE_ORDER}

# All possible horizontal-block keys across all indicator groups
_GWP_HORIZONTAL_KEYS: set[str] = set()
for _, _prefix, _ in _INDICATOR_GROUPS:
    _GWP_HORIZONTAL_KEYS |= _indicator_keys_all(_prefix)


def _manifest_sections() -> list[tuple[str, list[dict]]]:
    """Group `_FIELD_MANIFEST` rows by section title (non-GWP vertical fields only)."""
    out: list[tuple[str, list[dict]]] = []
    cur_title: str | None = None
    cur_fields: list[dict] = []
    for fs in _FIELD_MANIFEST:
        key = fs["key"]
        sec = fs.get("section")
        if sec in _GWP_SECTION_NAMES or key in _GWP_HORIZONTAL_KEYS:
            continue
        if sec is not None:
            if cur_title is not None:
                out.append((cur_title, cur_fields))
            cur_title = sec
            cur_fields = [fs]
        else:
            if cur_title is None:
                continue
            cur_fields.append(fs)
    if cur_title is not None:
        out.append((cur_title, cur_fields))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: map extractor output → review form namespaced keys
# ═══════════════════════════════════════════════════════════════════════════════

def _build_extended_dict(raw: dict) -> dict:
    """
    Prepare the dict for the review form.

    The IBU table parser already emits fully-namespaced per-module keys
    (gwp_total_a1, gwp_total_a2, gwp_total_a1a3, etc.) with _source tags.

    For Claude-text mode, the extractor emits flat keys (gwp_total, gwp_fossil, ...)
    as A1-A3 values only.  We promote those into the namespaced a1a3 slot so the
    data-driven renderer can find them.
    """
    d = dict(raw)
    # Promote flat A1-A3 values → namespaced keys (only if not already set)
    for flat, namespaced in [
        ("gwp_total",    "gwp_total_a1a3"),
        ("gwp_fossil",   "gwp_fossil_a1a3"),
        ("gwp_biogenic", "gwp_biogenic_a1a3"),
        ("gwp_luluc",    "gwp_luluc_a1a3"),
        ("sm",           "sm_a1a3"),
        ("odp_a1a3",     "odp_a1a3"),    # already namespaced from Claude output
        ("penre_a1a3",   "penre_a1a3"),
        ("pere_a1a3",    "pere_a1a3"),
        ("fw_a1a3",      "fw_a1a3"),
    ]:
        if not d.get(namespaced) and d.get(flat) is not None:
            d[namespaced] = d[flat]
            # Preserve source if set on flat key
            src = d.get(f"{flat}_source")
            if src and not d.get(f"{namespaced}_source"):
                d[f"{namespaced}_source"] = src
    _normalize_epd_identifier_fields(d)
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# UI helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _page_heading(text: str, level: int = 3) -> None:
    tag = f"h{min(max(level, 3), 5)}"
    st.markdown(
        f'<{tag} class="custom-title" style="margin:0 0 0.35rem 0;padding:0;line-height:1.25;">'
        f"{_html.escape(text)}</{tag}>",
        unsafe_allow_html=True,
    )


def _subsection_label(text: str) -> None:
    """Section label — text is HTML-escaped before insertion."""
    st.markdown(
        f"<div style='margin-top:20px;margin-bottom:2px;font-size:0.75rem;"
        f"font-weight:700;color:#888;text-transform:uppercase;letter-spacing:0.06em;'>"
        f"{_html.escape(text)}</div>",
        unsafe_allow_html=True,
    )

def _subsection_label_html(html_content: str) -> None:
    """Section label — html_content is inserted verbatim (caller must sanitise)."""
    st.markdown(
        f"<div style='margin-top:20px;margin-bottom:2px;font-size:0.75rem;"
        f"font-weight:700;color:#888;text-transform:uppercase;letter-spacing:0.06em;'>"
        f"{html_content}</div>",
        unsafe_allow_html=True,
    )


def _thin_rule() -> None:
    st.markdown(
        "<hr style='margin:18px 0 10px 0;border:none;border-top:1px solid #e2e8f0;'>",
        unsafe_allow_html=True,
    )


def _resolve_anthropic_key(sidebar_value: str) -> tuple[str | None, str | None]:
    ui = (sidebar_value or "").strip()
    if ui:
        return ui, "sidebar"
    env = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if env:
        return env, "environment"
    try:
        k = st.secrets["anthropic"]["api_key"]
        s = (str(k) if k is not None else "").strip()
        if s:
            return s, "secrets.toml"
    except Exception:
        pass
    return None, None


def _fval(r: dict, key: str, default: str = "") -> str:
    v = r.get(key)
    return default if v is None else str(v)


# Preview embed limit — larger files use raster pages only (sidebar toggle).
_MAX_PDF_EMBED_BYTES = 6 * 1024 * 1024
_MAX_RASTER_PAGES = 32


def _fixed_pdf_preview_stylesheet(
    *,
    dock_width_css: str = "min(46vw, 560px)",
    narrow_main: bool = True,
) -> str:
    """Reserve space for the fixed dock; optionally cap main block width to prevent overlap."""
    narrow_block = ""
    if narrow_main:
        narrow_block = f"""
  [data-testid="stMain"] {{
    box-sizing: border-box !important;
    overflow-x: hidden !important;
  }}
  [data-testid="stMain"] .block-container,
  [data-testid="stMain"] [data-testid="stMainBlockContainer"] {{
    max-width: calc(100vw - {dock_width_css} - 5.5rem) !important;
    width: 100% !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }}
"""
    return f"""
<style>
  [data-testid="stMain"] {{
    padding-right: {dock_width_css} !important;
  }}
  [data-testid="stMain"] .block-container,
  [data-testid="stMain"] [data-testid="stMainBlockContainer"] {{
    padding-right: 1rem !important;
  }}
{narrow_block}
</style>
"""


# Raster zoom used for the page images in the dock (part of the cache key).
_RASTER_ZOOM = 1.35


def _pdf_sha1_for(filename: str, pdf_bytes: bytes) -> str:
    """sha1 of the PDF bytes, memoised in session state per (filename, size).

    The preview cache is keyed on this digest instead of the raw bytes, so a
    rerun costs a dict lookup rather than re-hashing a multi-MB blob. Entries
    are cleared whenever a new extraction replaces the stored bytes.
    """
    memo = st.session_state.setdefault("epd_pdf_sha1_by_key", {})
    k = f"{filename}::{len(pdf_bytes)}"
    digest = memo.get(k)
    if digest is None:
        digest = hashlib.sha1(pdf_bytes).hexdigest()
        memo[k] = digest
    return digest


@st.cache_data(max_entries=8, show_spinner=False)
def _cached_pdf_preview_html(
    filename: str,
    pdf_sha1: str,
    mode: str,
    page_limit: int,
    zoom: float,
    narrow_main: bool,
    _pdf_bytes: bytes,
) -> str:
    """Build the fixed-dock preview HTML (iframe data URI or raster PNG pages).

    Cached because rasterising up to ``page_limit`` pages + base64-encoding them
    took seconds and used to run on every keystroke in the review form.
    ``_pdf_bytes`` is excluded from hashing — ``pdf_sha1`` identifies the content.
    Pure: no ``st.*`` calls; raises on unreadable PDFs (exceptions are not cached).
    """
    fn_esc = _html.escape(filename)
    if mode == "iframe":
        b64 = base64.standard_b64encode(_pdf_bytes).decode("ascii")
        return (
            _fixed_pdf_preview_stylesheet(narrow_main=narrow_main)
            + f'<div id="epd-pdf-dock" style="position:fixed;top:3.6rem;right:0;width:min(46vw,560px);'
            f"height:calc(100vh - 4rem);z-index:100002;background:#fff;"
            f"border-left:1px solid #cbd5e1;box-shadow:-8px 0 28px rgba(15,23,42,0.12);"
            f'display:flex;flex-direction:column;font-family:system-ui,sans-serif;">'
            f'<div style="flex:0 0 auto;padding:9px 14px;font-size:12px;font-weight:600;'
            f"border-bottom:1px solid #e2e8f0;background:#f8fafc;overflow:hidden;"
            f'text-overflow:ellipsis;white-space:nowrap;" title="{fn_esc}">{fn_esc}</div>'
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'style="flex:1;width:100%;border:none;" title="PDF preview"></iframe>'
            f"</div>"
        )

    import fitz

    doc = fitz.open(stream=_pdf_bytes, filetype="pdf")
    try:
        n_pages = min(doc.page_count, page_limit)
        chunks: list[str] = []
        mat = fitz.Matrix(zoom, zoom)
        for i in range(n_pages):
            pix = doc.load_page(i).get_pixmap(matrix=mat, alpha=False)
            png = pix.tobytes("png")
            ib64 = base64.standard_b64encode(png).decode("ascii")
            chunks.append(
                f'<img alt="PDF page {i + 1}" src="data:image/png;base64,{ib64}" '
                f'style="width:100%;height:auto;display:block;margin:0 0 10px 0;'
                f'border-radius:4px;box-shadow:0 1px 5px rgba(0,0,0,0.07);" />'
            )
        notice = ""
        if doc.page_count > page_limit:
            notice = (
                f"<p style='font-size:11px;color:#64748b;margin:4px 0 10px 0;'>"
                f"Showing first {page_limit} of {doc.page_count} pages.</p>"
            )
        scroll_body = notice + "\n".join(chunks)
    finally:
        doc.close()

    return (
        _fixed_pdf_preview_stylesheet(narrow_main=narrow_main)
        + f'<div id="epd-pdf-dock" style="position:fixed;top:3.6rem;right:0;width:min(46vw,560px);'
        f"height:calc(100vh - 4rem);z-index:100002;background:#f1f5f9;"
        f"border-left:1px solid #cbd5e1;box-shadow:-8px 0 28px rgba(15,23,42,0.12);"
        f'display:flex;flex-direction:column;font-family:system-ui,sans-serif;">'
        f'<div style="flex:0 0 auto;padding:9px 14px;font-size:12px;font-weight:600;'
        f"border-bottom:1px solid #e2e8f0;background:#f8fafc;overflow:hidden;"
        f'text-overflow:ellipsis;white-space:nowrap;" title="{fn_esc}">{fn_esc}'
        f"<span style='font-weight:400;color:#64748b;margin-left:8px;'>(raster)</span></div>"
        f'<div style="flex:1;overflow-y:auto;padding:10px 12px;background:#fff;">'
        f"{scroll_body}</div></div>"
    )


def _inject_fixed_pdf_preview(
    filename: str, pdf_bytes: bytes, *, mode: str, narrow_main: bool
) -> None:
    """Emit the (cached) dock HTML; ``mode`` is ``"iframe"`` or ``"raster"``."""
    try:
        dock_html = _cached_pdf_preview_html(
            filename,
            _pdf_sha1_for(filename, pdf_bytes),
            mode,
            _MAX_RASTER_PAGES,
            _RASTER_ZOOM,
            narrow_main,
            pdf_bytes,
        )
    except Exception as _e:
        st.warning(f"PDF preview unavailable for **{filename}**: {_e}")
        return
    st.markdown(dock_html, unsafe_allow_html=True)


def _render_fixed_pdf_preview(
    filename: str,
    pdf_bytes: bytes | None,
    *,
    use_raster: bool,
    narrow_main: bool = True,
) -> None:
    if not pdf_bytes:
        return
    if use_raster:
        _inject_fixed_pdf_preview(filename, pdf_bytes, mode="raster", narrow_main=narrow_main)
        return
    if len(pdf_bytes) > _MAX_PDF_EMBED_BYTES:
        _inject_fixed_pdf_preview(filename, pdf_bytes, mode="raster", narrow_main=narrow_main)
        st.caption(
            f"PDF exceeds {_MAX_PDF_EMBED_BYTES // (1024 * 1024)} MB embed limit — "
            "showing raster pages. Use sidebar **Raster preview** to force this mode for any file."
        )
        return
    _inject_fixed_pdf_preview(filename, pdf_bytes, mode="iframe", narrow_main=narrow_main)


# ═══════════════════════════════════════════════════════════════════════════════
# Horizontal GWP renderer  (EPD table layout)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_indicator_tables(
    parsed_dict: dict,
    user_values: dict,
    sk: str,
    *,
    groups: list[tuple[str, str, str]] | None = None,
    caption_mode: str = "full",
    pdf_preview_spacer: bool = False,
) -> None:
    """
    Render LCA indicator tables in horizontal EPD layout (subset or full list).

    ``caption_mode``: ``\"full\"`` (GWP tab), ``\"short\"`` (other/resource tabs),
    ``\"none\"`` (e.g. nested reuse).
    Each cell shows:
      module label  ·  value with Parsed/Calculated badge  ·  editable text_input
    """
    group_list = groups if groups is not None else _INDICATOR_GROUPS

    if caption_mode == "full":
        st.caption(
            "LCA indicators in **EPD table layout** — one column per declared lifecycle module. "
            "**A1–A3 · calculated** (when present) is the leftmost column: sum of A1+A2+A3, "
            "rounded to match the decimal precision of those stages. "
            "Grey **Parsed** = read directly from the EPD table · "
            "Purple *Calculated* = derived by summing individual stage columns · "
            "Amber = not found in EPD."
        )
    elif caption_mode == "short":
        st.caption(
            "Same layout as **GWP indicators** — Parsed vs Calculated badges and "
            "one column per lifecycle module."
        )

    if caption_mode != "none":
        st.markdown(
            "<hr style='margin:8px 0 12px 0; border-color:#e0e0e0;'>",
            unsafe_allow_html=True,
        )

    any_shown = False
    for sec_title, prefix, unit_label in group_list:
        columns = _indicator_columns_ordered(parsed_dict, prefix)
        if not columns:
            continue  # skip groups with no data at all

        any_shown = True
        _subsection_label_html(
            f"{_html.escape(sec_title)}&ensp;"
            f"<span style='color:#bbb;font-size:0.68rem;font-weight:400;"
            f"text-transform:none;letter-spacing:0;'>({_html.escape(unit_label)})</span>"
        )

        # Ratios: one slot per module column + optional blank far-right spacer for PDF dock
        ratios = [1.0] * len(columns)
        if pdf_preview_spacer:
            ratios.append(0.42)
        grid = st.columns(ratios)

        for i, (field_key, col_label) in enumerate(columns):
            with grid[i]:
                parsed_val = _parsed_display_string_indicator(parsed_dict, field_key)
                widget_key = f"{sk}_h_{field_key}"
                src = parsed_dict.get(f"{field_key}_source")
                src_label  = "Calculated" if src == "calculated" else "Parsed"
                src_colour = "#7c3aed"    if src == "calculated" else "#888"
                src_style  = "italic"     if src == "calculated" else "normal"

                # Module column label
                st.markdown(
                    f"<div style='font-size:0.72rem;font-weight:600;color:#444;"
                    f"margin-bottom:4px;line-height:1.25;'>{_html.escape(col_label)}</div>",
                    unsafe_allow_html=True,
                )

                # Value display
                if parsed_val.strip() == "":
                    st.markdown(
                        "<div style='font-size:0.78rem;color:#b08800;"
                        "background:#fff8e1;border-left:3px solid #f9a825;"
                        "padding:4px 6px;border-radius:2px;margin-bottom:6px;'>"
                        "—</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    disp = parsed_val if len(parsed_val) <= 18 else parsed_val[:15] + "…"
                    st.markdown(
                        f"<div style='font-size:0.78rem;font-family:monospace;"
                        f"color:#222;line-height:1.35;margin-bottom:2px;'>"
                        f"<span style='color:{src_colour};font-size:0.6rem;"
                        f"font-style:{src_style};'>{src_label}</span><br>"
                        f"{_html.escape(disp)}</div>",
                        unsafe_allow_html=True,
                    )

                # Editable input
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = parsed_val
                user_values[field_key] = st.text_input(
                    "Your value",
                    key=widget_key,
                    label_visibility="collapsed",
                    placeholder="Edit…",
                )

        if pdf_preview_spacer:
            with grid[-1]:
                st.empty()

    if not any_shown:
        st.info("No indicator values in this category for this record.", icon="ℹ️")


# ═══════════════════════════════════════════════════════════════════════════════
# 3-column vertical form renderer
# ═══════════════════════════════════════════════════════════════════════════════

def _render_vertical_form_rows(
    field_rows: list[dict],
    parsed_dict: dict,
    user_values: dict,
    sk: str,
    *,
    show_column_headers: bool,
    pdf_preview_spacer: bool = False,
) -> None:
    """Render manifest rows as Field | Parsed | Editable (+ optional far-right blank column)."""
    row_ratios = [2.0, 3.0, 3.0] + ([0.5] if pdf_preview_spacer else [])

    if show_column_headers:
        hdr = st.columns(row_ratios)
        hdr[0].markdown("**Field**")
        hdr[1].markdown("**Parsed (Claude)**")
        hdr[2].markdown("**Your value**")
        if pdf_preview_spacer:
            hdr[3].empty()
        st.markdown(
            "<hr style='margin:4px 0 14px 0; border-color:#e0e0e0;'>",
            unsafe_allow_html=True,
        )

    for fs in field_rows:
        key       = fs["key"]
        label     = fs["label"]
        unit      = fs.get("unit", "")
        multiline = fs.get("multiline", False)
        widget_key = f"{sk}_v_{key}"

        parsed_val = _fval(parsed_dict, key)
        # Pre-seed session state so the widget initialises to parsed_val
        # (Streamlit ignores value= when key= already exists in session state).
        if widget_key not in st.session_state:
            st.session_state[widget_key] = parsed_val

        is_empty   = parsed_val.strip() == ""
        label_html = _html.escape(label)
        if unit:
            label_html += (
                f" <span style='color:#999;font-size:0.78em;'>"
                f"({_html.escape(unit)})</span>"
            )

        cols = st.columns(row_ratios)

        with cols[0]:
            st.markdown(
                f"<div style='padding-top:7px;font-size:0.875rem;line-height:1.4;'>"
                f"{label_html}</div>",
                unsafe_allow_html=True,
            )

        with cols[1]:
            src = parsed_dict.get(f"{key}_source")
            src_label = "Calculated" if src == "calculated" else "Parsed"
            src_colour = "#7c3aed" if src == "calculated" else "#64748b"
            if is_empty:
                st.markdown(
                    "<div style='padding-top:7px;font-size:0.85rem;color:#b08800;"
                    "background:#fff8e1;border-left:3px solid #f9a825;"
                    "padding-left:6px;border-radius:2px;'>— not found</div>",
                    unsafe_allow_html=True,
                )
            else:
                disp = parsed_val if len(parsed_val) <= 110 else parsed_val[:107] + "…"
                style = f"font-style:{'italic' if src == 'calculated' else 'normal'}"
                st.markdown(
                    f"<div style='padding-top:4px;'>"
                    f"<span style='font-size:0.68rem;color:{src_colour};{style};'>"
                    f"{src_label}</span>"
                    f"<div style='font-size:0.84rem;font-family:monospace;color:#222;line-height:1.4;'>"
                    f"{_html.escape(disp)}</div></div>",
                    unsafe_allow_html=True,
                )

        with cols[2]:
            if multiline:
                user_values[key] = st.text_area(
                    label="",
                    height=80,
                    key=widget_key,
                    label_visibility="collapsed",
                )
            else:
                user_values[key] = st.text_input(
                    label="",
                    key=widget_key,
                    label_visibility="collapsed",
                )

        if pdf_preview_spacer:
            with cols[3]:
                st.empty()


def _render_product_composition_editor(raw: dict, sk: str, composition_state: dict) -> None:
    """Detail-pass composition table — rendered under the **Product** tab."""
    if not raw.get("product_composition"):
        return
    st.markdown(
        "<hr style='margin:16px 0 12px 0; border-color:#e2e8f0;'>",
        unsafe_allow_html=True,
    )
    st.markdown("##### Product composition")
    st.caption(
        "Edit rows directly. Use the **+** row at the bottom to add materials."
    )
    comp = raw["product_composition"]
    if isinstance(comp, list):
        composition_state["edited"] = st.data_editor(
            pd.DataFrame(comp),
            hide_index=True,
            width='stretch',
            num_rows="dynamic",
            key=f"{sk}_composition",
        )
    else:
        st.write(comp)
        composition_state["edited"] = comp


def _render_extraction_diagnostics(raw: dict) -> None:
    """Token/page metrics, optional error, raw JSON — former sidebar of diagnostics tab."""
    d1, d2, d3 = st.columns(3)
    with d1:
        st.metric("Essential pages", raw.get("_pages_sent_essential", "—"))
        st.metric("Input tokens",  f"{raw.get('_input_tokens', 0):,}")
        st.metric("Output tokens", f"{raw.get('_output_tokens', 0):,}")
    with d2:
        st.metric("Detail pages",      raw.get("_pages_sent_detail", "—"))
        st.metric("Detail in tokens",  f"{raw.get('_detail_input_tokens', 0):,}")
        st.metric("Detail out tokens", f"{raw.get('_detail_output_tokens', 0):,}")
    with d3:
        st.metric("Est. cost",  f"~${raw.get('_cost_usd', 0):.4f} USD")
        st.metric("Mode",       raw.get("_mode", "—"))
        st.metric("Programme",  raw.get("_programme", "—"))
    if raw.get("_error"):
        st.error(f"⚠ Extraction error:\n{raw['_error'][:500]}")
    with st.expander("Raw JSON (extractor output)", expanded=False, type="compact"):
        st.json({k: v for k, v in raw.items() if k != "_error"})


def _render_vertical_form_by_sections(
    parsed_dict: dict,
    user_values: dict,
    sk: str,
    *,
    raw_record: dict | None = None,
    composition_state: dict | None = None,
    pdf_preview_on: bool = False,
) -> None:
    """
    Review tabs: one tab per manifest section (**Content** is not its own tab).

    Under **Product**: product fields → optional composition → **Content** fields
    (recycled %, SM). After **LCA Methodology**: **GWP / Other / Resource** indicator tabs.

    Optional trailing ``| Extraction diagnostics`` when ``raw_record`` is passed.

    When ``pdf_preview_on``, the tab strip sits in a left column with a white gutter, and
    each Field | Parsed | Your value row and each GWP/LCA indicator row adds a **blank
    far-right column** so content clears the fixed PDF dock (no tab-panel CSS hacks).
    """
    sections = _manifest_sections()
    content_rows: list[dict] | None = None
    tab_specs: list[tuple] = []

    for title, field_rows in sections:
        if title == "Content":
            content_rows = field_rows
            continue
        tab_specs.append(("manifest", title, field_rows))
        if title == "LCA Methodology":
            tab_specs.extend([
                ("indicators", "gwp", _INDICATOR_GROUPS_GWP),
                ("indicators", "other", _INDICATOR_GROUPS_OTHER),
                ("indicators", "resource", _INDICATOR_GROUPS_RESOURCE),
            ])

    if raw_record is not None:
        tab_specs.append(("diag",))

    if not tab_specs:
        return

    ind_labels = {"gwp": "GWP indicators", "other": "Other indicators", "resource": "Resource use"}
    labels: list[str] = []
    for spec in tab_specs:
        k = spec[0]
        if k == "manifest":
            labels.append(spec[1])
        elif k == "indicators":
            labels.append(ind_labels[spec[1]])
        else:
            labels.append("| Extraction diagnostics")

    def _render_review_tab_slot_content(spec: tuple) -> None:
        k = spec[0]
        if k == "manifest":
            _, sec_title, field_rows = spec
            _render_vertical_form_rows(
                field_rows,
                parsed_dict,
                user_values,
                sk,
                show_column_headers=True,
                pdf_preview_spacer=pdf_preview_on,
            )
            if (
                sec_title == "Product"
                and raw_record is not None
                and composition_state is not None
            ):
                _render_product_composition_editor(raw_record, sk, composition_state)
            if sec_title == "Product" and content_rows:
                st.markdown(
                    "<hr style='margin:16px 0 12px 0; border-color:#e2e8f0;'>",
                    unsafe_allow_html=True,
                )
                st.markdown("##### Content")
                _render_vertical_form_rows(
                    content_rows,
                    parsed_dict,
                    user_values,
                    sk,
                    show_column_headers=True,
                    pdf_preview_spacer=pdf_preview_on,
                )
        elif k == "indicators":
            _, bucket, grp_list = spec
            _render_indicator_tables(
                parsed_dict,
                user_values,
                sk,
                groups=grp_list,
                caption_mode="full" if bucket == "gwp" else "short",
                pdf_preview_spacer=pdf_preview_on,
            )
        elif raw_record is not None:
            _render_extraction_diagnostics(raw_record)

    def _render_tab_strip() -> None:
        tabs = st.tabs(labels)
        for tab_slot, spec in zip(tabs, tab_specs):
            with tab_slot:
                _render_review_tab_slot_content(spec)

    if pdf_preview_on:
        col_tabs, col_ws = st.columns([0.7, 0.3], gap="small")
        with col_tabs:
            _render_tab_strip()
        with col_ws:
            st.markdown(
                "<div style=\"min-height:80vh;background:#ffffff;"
                "border-left:1px solid #eef2f7;\">&nbsp;</div>",
                unsafe_allow_html=True,
            )
    else:
        _render_tab_strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════════════════════

if "epd_results" not in st.session_state:
    st.session_state.epd_results = []     # committed records
if "epd_pending" not in st.session_state:
    st.session_state.epd_pending = []     # freshly extracted, awaiting review
if "epd_client"  not in st.session_state:
    st.session_state.epd_client  = None
if "epd_pdf_bytes_by_filename" not in st.session_state:
    st.session_state.epd_pdf_bytes_by_filename = {}
if "epd_pdf_preview_enabled" not in st.session_state:
    st.session_state.epd_pdf_preview_enabled = True


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    _page_heading("⚙️ Settings", level=4)
    api_key_input = st.text_input(
        "Anthropic API key (optional)",
        type="password",
        placeholder="Leave empty to use secrets.toml or ANTHROPIC_API_KEY",
        key="epd_anthropic_key_input",
    )
    _key, _key_src = _resolve_anthropic_key(api_key_input)
    if _key:
        st.session_state.epd_client = anthropic.Anthropic(api_key=_key)
        src_labels = {
            "sidebar": "from sidebar ✓",
            "environment": "from ANTHROPIC_API_KEY ✓",
            "secrets.toml": "from secrets.toml ✓",
        }
        st.success(f"API key: {src_labels.get(_key_src, '✓')}")
    else:
        st.session_state.epd_client = None
        st.caption("Set `[anthropic]` `api_key` in `.streamlit/secrets.toml`, or enter a key above.")

    st.divider()
    st.markdown("**Extraction modes**")
    st.caption(
        "🟢 **deterministic** — IBU/Environdec regex, $0.00\n\n"
        "🔵 **text** — Claude text API, ~$0.003–0.006\n\n"
        "🟠 **vision** — rasterised pages (scanned PDFs only), ~$0.05–0.15"
    )
    st.divider()
    st.markdown("**Detail pass** (optional)")
    st.caption(
        "Adds a second Claude text call (~same cost as essential) to capture "
        "product composition, production method, system boundary, and flow description."
    )

    st.divider()
    st.markdown("**PDF preview**")
    st.caption("Turn the dock on/off under **① Upload & extract** (right column).")
    st.checkbox(
        "Raster preview (page images)",
        value=False,
        key="epd_pdf_preview_raster",
        help="If the embedded PDF pane is empty in your browser, enable this — "
        "pages are rendered as PNG images in the fixed right-hand dock.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ① Upload & extract
# ═══════════════════════════════════════════════════════════════════════════════

_page_heading("① Upload & extract", level=4)

pdf_source = st.radio(
    "PDF source",
    options=[_EPD_SOURCE_UPLOAD, _EPD_SOURCE_LIBRARY],
    horizontal=True,
    key="epd_pdf_source",
    help="Library reads PDFs from the project `01_data/epd_pdf` directory.",
)

col_up, col_det, col_go, space, col_pv, space = st.columns(
    [2.8, 1.2, 0.7, 0.4, 1, 3], vertical_alignment="center"
)
uploaded_files = None
library_selection: list[str] = []
with col_up:
    if pdf_source == _EPD_SOURCE_UPLOAD:
        uploaded_files = st.file_uploader(
            "Upload EPD PDF(s)", type="pdf", accept_multiple_files=True, key="epd_uploader"
        )
    else:
        lib_dir = _epd_pdf_library_dir()
        lib_pdf_names = _list_epd_library_pdf_basenames()
        st.caption(f"Folder: `{lib_dir}` · {len(lib_pdf_names)} PDF(s)")
        if not lib_pdf_names:
            st.warning(
                "No PDFs found. Create `01_data/epd_pdf` next to the app and add `.pdf` files, "
                "or switch to **Upload files**."
            )
        library_selection = st.multiselect(
            "Choose PDF(s) from library",
            options=lib_pdf_names,
            default=[],
            key="epd_library_pdf_pick",
            placeholder="Select one or more files…",
        )
with col_det:
    run_detail = st.toggle(
        "Detailed extraction",
        value=False,
        help=(
            "Second Claude text call: product description, composition (% by mass), "
            "production method, system boundary, flow description, functional unit, "
            "geographic scope, and LCA methodology. ~Same cost as essential pass."
        ),
    )
with col_go:
    extract_clicked = st.button(
        "▶ Extract", type="primary", width='stretch', key="epd_extract"
    )
with col_pv:
    st.toggle(
        "PDF preview",
        key="epd_pdf_preview_enabled",
        help=(
            "Fixed panel on the right while reviewing. When on, the main column is narrowed "
            "so the form does not sit under the preview."
        ),
    )

if run_detail:
    st.caption(
        "Detailed extraction enabled — extra Claude text call per PDF (~$0.003–0.006 each), "
        "except for vision-only PDFs."
    )

if extract_clicked:
    pdf_jobs = _pdf_jobs_for_extract(pdf_source, uploaded_files, library_selection)
    if not pdf_jobs:
        st.warning(
            "Choose PDFs: upload at least one file, or select one or more names from the "
            "library multiselect, then click **Extract**."
        )
    elif not st.session_state.epd_client:
        st.warning(
            "No Anthropic API key available. Add `[anthropic]` / `api_key` in "
            "`.streamlit/secrets.toml`, set `ANTHROPIC_API_KEY`, or paste a key in the sidebar."
        )
    else:
        progress = st.progress(0, text="Starting…")
        total = len(pdf_jobs)
        new_pending = []
        st.session_state.epd_pdf_bytes_by_filename = {}
        # New bytes may reuse a filename+size; drop memoised digests with them.
        st.session_state.epd_pdf_sha1_by_key = {}

        for i, (fn, pdf_bytes) in enumerate(pdf_jobs):
            progress.progress(i / total, text=f"{fn} ({i+1}/{total})…")
            st.session_state.epd_pdf_bytes_by_filename[fn] = pdf_bytes
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            with st.spinner(f"Extracting `{fn}`…"):
                res = extract_epd(
                    tmp_path,
                    client=st.session_state.epd_client,
                    detail=run_detail,
                )

            res["_filename"] = fn
            res["_cost_usd"] = estimate_cost(
                res["_input_tokens"], res["_output_tokens"],
                res["_detail_input_tokens"], res["_detail_output_tokens"],
            )
            new_pending.append(res)

            mode      = res["_mode"]
            mode_icon = {
                "deterministic": "🟢", "deterministic+text": "🔷",
                "text": "🔵", "vision": "🟠",
            }.get(mode, "⚪")
            conf_icon  = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(res["confidence"], "❓")
            prog_label = f"[{res['_programme']}] " if res["_programme"] else ""
            detail_note = ""
            if run_detail and res.get("_detail_input_tokens"):
                detail_note = (
                    f" | detail: {res['_detail_input_tokens']:,} in / "
                    f"{res['_detail_output_tokens']:,} out"
                )

            st.info(
                f"{conf_icon} **{fn}** {prog_label}— "
                f"{mode_icon} {mode} — confidence: {res['confidence']} — "
                f"{res['_pages_sent_essential']} essential pages — "
                f"{res['_input_tokens']:,} in / {res['_output_tokens']:,} out"
                f"{detail_note} — ~${res['_cost_usd']:.4f} USD"
            )
            if res["_error"]:
                # Check whether it's a short clean message (from the file-open guard)
                # or a full traceback (from unexpected exceptions elsewhere).
                _err_text = res["_error"]
                _is_clean = len(_err_text) < 300 and "\n" not in _err_text
                if _is_clean:
                    st.error(f"⚠ **{fn}** — {_err_text}")
                else:
                    st.error(f"⚠ **{fn}** — extraction failed. See diagnostics in the review form.")
                    st.caption(f"```\n{_err_text[:400]}\n```")

        st.session_state.epd_pending = new_pending
        progress.progress(1.0, text="Done ✓ — review extracted fields below before committing.")


# ═══════════════════════════════════════════════════════════════════════════════
# ② Review form — row1: st.info status ([2]) + legend caption ([3]); …tabs…
# ═══════════════════════════════════════════════════════════════════════════════

# Both blocks below are fragments: typing in a review field reruns only that
# record's fragment (not the PDF dock), and switching the previewed PDF reruns
# only the dock. They take plain args and re-read session state on each run so
# a fragment rerun — which skips the page body and, when embedded in Developer,
# the host's flag setup — still sees current data.


@st.fragment
def _review_pdf_preview_fragment(preview_keys: list[str], use_raster: bool) -> None:
    blob_map: dict = st.session_state.get("epd_pdf_bytes_by_filename") or {}
    pr1, pr2, pr3 = st.columns([2.4, 2.8, 1.1])
    with pr1:
        preview_pick = st.selectbox(
            "PDF for fixed preview",
            preview_keys,
            key="epd_pdf_preview_pick",
        )
    with pr2:
        st.caption(
            "Preview is docked to the **right edge** and stays **fixed** while you scroll the form."
        )
    pdf_bytes = blob_map.get(preview_pick)
    if not pdf_bytes:
        return
    with pr3:
        st.download_button(
            "⬇ PDF",
            pdf_bytes,
            file_name=preview_pick,
            mime="application/pdf",
            key="epd_pdf_preview_download",
            width='stretch',
        )
    _render_fixed_pdf_preview(
        preview_pick,
        pdf_bytes,
        use_raster=use_raster,
        narrow_main=False,
    )


@st.fragment
def _review_record_fragment(rec_idx: int, pdf_preview_on: bool) -> None:
    pending = st.session_state.get("epd_pending") or []
    if rec_idx >= len(pending):
        return
    raw = pending[rec_idx]
    fname     = raw.get("_filename", f"Record #{rec_idx + 1}")
    mode      = raw.get("_mode", "")
    conf      = raw.get("confidence", "low")
    mode_icon = {
        "deterministic": "🟢", "deterministic+text": "🔷",
        "text": "🔵", "vision": "🟠",
    }.get(mode, "⚪")
    conf_icon = {"high": "✅", "medium": "⚠️", "low": "❌"}.get(conf, "❓")

    sk = f"pend_{rec_idx}"

    prog_label = f"[{raw['_programme']}] " if raw.get("_programme") else ""

    status_info_text = (
        f"{conf_icon} **{fname}** {prog_label}— {mode_icon} {mode} "
        f"| confidence: **{conf}**"
    )
    legend_caption = (
        "**Left**: field name and unit  ·  "
        "**Centre**: value extracted by Claude — "
        "grey *Parsed* = read directly from the EPD, "
        "purple *Calculated* = derived by summing individual stage columns "
        "(e.g. A1+A2+A3), amber = not found  ·  "
        "**Right**: editable field pre-filled from parsed data. "
        "**GWP indicators**, **Other indicators**, and **Resource use** "
        "are tabs after **LCA Methodology**. "
        "**Content** (recycled %, SM) sits under **Product**, below "
        "**Product composition** when the detail pass ran."
    )
    if rec_idx == 0:
        info_col, legend_col = st.columns([1, 1.2], gap="medium")
        with info_col:
            st.info(status_info_text)
        with legend_col:
            st.caption(legend_caption)
    else:
        st.info(status_info_text)

    parsed_dict = _build_extended_dict(raw)
    user_values: dict[str, str] = {}
    composition_state: dict = {}

    _render_vertical_form_by_sections(
        parsed_dict,
        user_values,
        sk,
        raw_record=raw,
        composition_state=composition_state,
        pdf_preview_on=pdf_preview_on,
    )

    edited_comp = composition_state.get("edited")

    # ── Edited-field summary ────────────────────────────────────────
    changed = [
        k for k, v in user_values.items()
        if v != _baseline_field_value(parsed_dict, k)
    ]
    if changed:
        st.info(
            f"✏️ **{len(changed)} field(s) edited**: "
            + ", ".join(f"`{k}`" for k in changed[:10])
            + ("…" if len(changed) > 10 else "")
        )

    # ── Commit / Discard ────────────────────────────────────────────
    # Removing a record re-indexes every other record and changes the heading
    # count, so both actions end with a full-app rerun (not a fragment rerun).
    _thin_rule()
    btn1, btn2, _ = st.columns([1.4, 1.2, 5])

    if btn1.button("✅ Commit record", key=f"{sk}_commit", type="primary"):
        committed = dict(raw)
        committed.update(user_values)
        _normalize_epd_identifier_fields(committed)
        committed["_reviewed_at"]   = time.strftime("%Y-%m-%dT%H:%M:%S")
        committed["_fields_edited"] = changed

        if edited_comp is not None and isinstance(edited_comp, pd.DataFrame):
            committed["product_composition"] = edited_comp.to_dict("records")

        # Strip empty GWP placeholder strings
        for k in list(committed.keys()):
            if k.startswith("gwp_") and committed[k] in (None, ""):
                committed[k] = None

        st.session_state.epd_results.append(committed)
        del st.session_state.epd_pending[rec_idx]
        st.success(f"✅ **{fname}** committed to results.")
        st.rerun(scope="app")

    if btn2.button("🗑 Discard", key=f"{sk}_discard", type="secondary"):
        del st.session_state.epd_pending[rec_idx]
        st.info(f"🗑 **{fname}** discarded.")
        st.rerun(scope="app")


if st.session_state.epd_pending:
    _page_heading(
        f"② Review & confirm — {len(st.session_state.epd_pending)} record(s) pending",
        level=4,
    )

    blob_map: dict = st.session_state.get("epd_pdf_bytes_by_filename") or {}
    preview_keys = list(dict.fromkeys(
        fn
        for fn in (
            r.get("_filename")
            for r in st.session_state.epd_pending
        )
        if fn and blob_map.get(fn)
    ))
    use_raster_preview = st.session_state.get("epd_pdf_preview_raster", False)
    preview_on = bool(st.session_state.get("epd_pdf_preview_enabled", True))
    if preview_keys and preview_on:
        _review_pdf_preview_fragment(preview_keys, bool(use_raster_preview))
    elif preview_keys and not preview_on:
        st.caption(
            "**PDF preview** is off — enable **PDF preview** in section **①** (right column) "
            "to show the fixed dock and widen the clear area for the form."
        )
    else:
        st.caption(
            "Fixed PDF preview is available after you **Extract** PDFs in this session "
            "(bytes are kept until the next extraction)."
        )

    for rec_idx in range(len(st.session_state.epd_pending)):
        _review_record_fragment(rec_idx, preview_on and bool(preview_keys))


# ═══════════════════════════════════════════════════════════════════════════════
# ③ Committed results
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.epd_results:
    st.divider()
    _page_heading(
        f"③ Committed results — {len(st.session_state.epd_results)} record(s)",
        level=4,
    )

    has_detail = any(r.get("product_description") for r in st.session_state.epd_results)

    SHOW_COLS = [
        "_filename",
        "product_name", "manufacturer", "declared_unit", "reference_standard",
        "gwp_total_a1a3", "gwp_fossil_a1a3", "gwp_biogenic_a1a3", "gwp_luluc_a1a3",
        "sm", "recycled_content_pct",
        "epd_declaration_number", "epd_registration_number", "epd_number",
        "programme_operator", "validity_date", "issue_date", "revision_date",
        "confidence",
    ]
    if has_detail:
        SHOW_COLS += ["product_description", "production_method", "system_boundary", "modules_declared"]
    SHOW_COLS += ["_mode", "_cost_usd"]

    df = pd.DataFrame([{c: r.get(c) for c in SHOW_COLS} for r in st.session_state.epd_results])
    df.columns = [c.lstrip("_") for c in SHOW_COLS]

    st.dataframe(
        df, width='stretch',
        column_config={
            "gwp_total_a1a3":    st.column_config.NumberColumn("GWP total A1-A3",    format="%.4f"),
            "gwp_fossil_a1a3":   st.column_config.NumberColumn("GWP fossil A1-A3",   format="%.4f"),
            "gwp_biogenic_a1a3": st.column_config.NumberColumn("GWP biogenic A1-A3", format="%.4f"),
            "gwp_luluc_a1a3":    st.column_config.NumberColumn("GWP LULUC A1-A3",    format="%.4f"),
            "sm":                st.column_config.NumberColumn("SM (kg)",             format="%.4f"),
            "recycled_content_pct": st.column_config.NumberColumn("Recycled %",       format="%.1f"),
            "cost_usd":          st.column_config.NumberColumn("Cost USD",            format="$%.4f"),
        },
        hide_index=True,
    )

    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        st.download_button(
            "⬇ CSV", df.to_csv(index=False).encode(), "epd_results.csv", "text/csv"
        )
    with ec2:
        j = json.dumps(
            [{k: v for k, v in r.items() if k != "_error"}
             for r in st.session_state.epd_results],
            indent=2, ensure_ascii=False,
        ).encode()
        st.download_button("⬇ JSON", j, "epd_results.json", "application/json")
    with ec3:
        if st.button("🗑 Clear all committed results", type="secondary"):
            st.session_state.epd_results = []
            st.rerun()

    # ── Per-record detail view (committed) ────────────────────────────────
    st.divider()
    _page_heading("🔍 Record detail (committed)", level=4)
    labels = [r.get("_filename", f"#{i}") for i, r in enumerate(st.session_state.epd_results)]
    sel = st.selectbox("Select record", range(len(labels)), format_func=lambda i: labels[i])

    if sel is not None:
        r = st.session_state.epd_results[sel]
        tab_ess, tab_gwp, tab_other, tab_detail, tab_meta = st.tabs(
            ["Essential", "GWP full", "Other indicators", "Detail", "Metadata"]
        )

        with tab_ess:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**GWP A1-A3 (kg CO₂eq)**")
                st.write({
                    "GWP total":    r.get("gwp_total_a1a3") or r.get("gwp_total"),
                    "GWP fossil":   r.get("gwp_fossil_a1a3") or r.get("gwp_fossil"),
                    "GWP biogenic": r.get("gwp_biogenic_a1a3") or r.get("gwp_biogenic"),
                    "GWP LULUC":    r.get("gwp_luluc_a1a3") or r.get("gwp_luluc"),
                })
            with c2:
                st.markdown("**Resource use & content**")
                st.write({
                    "Secondary material SM (kg)": r.get("sm"),
                    "Recycled content (%)":       r.get("recycled_content_pct"),
                    "Declared unit":              r.get("declared_unit"),
                    "Reference standard":         r.get("reference_standard"),
                })
            mode_icon = {
                "deterministic": "🟢", "deterministic+text": "🔷",
                "text": "🔵", "vision": "🟠",
            }.get(r.get("_mode", ""), "⚪")
            st.caption(
                f"{mode_icon} **{r.get('_mode')}** — "
                f"{r.get('_pages_sent_essential','?')} essential pages — "
                f"{r.get('_input_tokens',0):,} in / {r.get('_output_tokens',0):,} out — "
                f"~${r.get('_cost_usd',0):.4f} USD"
            )
            if r.get("notes"):
                st.caption(f"📎 {r['notes']}")

        with tab_gwp:
            rows = []
            for sec_title, prefix, unit_label in _INDICATOR_GROUPS:
                columns = _indicator_columns_ordered(r, prefix)
                for fk, col_label in columns:
                    v_raw = r.get(fk)
                    src = r.get(f"{fk}_source", "parsed")
                    if v_raw is None:
                        continue
                    sp = _split_indicator_field_key(fk)
                    if sp and sp[1] == "a1a3" and src == "calculated":
                        try:
                            pl = _max_decimal_places_a123(r, prefix)
                            v = round(float(v_raw), pl)
                        except (TypeError, ValueError):
                            v = v_raw
                    else:
                        v = v_raw
                    rows.append({
                        "Indicator": sec_title,
                        "Module":    col_label,
                        "Value":     v,
                        "Unit":      unit_label,
                        "Source":    src or "parsed",
                    })
            if rows:
                st.dataframe(
                    pd.DataFrame(rows), hide_index=True, width='stretch',
                    column_config={
                        "Value": st.column_config.NumberColumn(format="%.6g"),
                        "Source": st.column_config.TextColumn(),
                    },
                )
            else:
                st.info("No per-module indicator values committed for this record.")

        with tab_other:
            other = {
                "ODP (kg CFC-11 eq.)":        r.get("odp_a1a3"),
                "AP (mol H⁺ eq.)":            r.get("ap_a1a3"),
                "EP freshwater (kg PO₄ eq.)": r.get("ep_freshwater_a1a3"),
                "EP marine (kg N eq.)":        r.get("ep_marine_a1a3"),
                "EP terrestrial (mol N eq.)":  r.get("ep_terrestrial_a1a3"),
                "POCP (kg NMVOC eq.)":         r.get("pocp_a1a3"),
                "ADPE (kg Sb eq.)":            r.get("adpe_a1a3"),
                "ADPF (MJ)":                   r.get("adpf_a1a3"),
                "WDP (m³)":                    r.get("wdp_a1a3"),
                "PENRE (MJ)":                  r.get("penre_a1a3"),
                "PERE (MJ)":                   r.get("pere_a1a3"),
                "Freshwater FW (m³)":          r.get("fw_a1a3"),
            }
            filled = {k: v for k, v in other.items() if v not in (None, "")}
            if filled:
                st.write(filled)
            else:
                st.info("No other indicator values committed for this record.")

        with tab_detail:
            if r.get("product_description"):
                st.markdown("**Product description**")
                st.write(r["product_description"])
                if r.get("product_composition"):
                    st.markdown("**Composition**")
                    comp = r["product_composition"]
                    df_c = pd.DataFrame(comp) if isinstance(comp, list) else pd.DataFrame([{"value": comp}])
                    st.dataframe(df_c, hide_index=True, width='stretch')
                c1, c2 = st.columns(2)
                with c1:
                    for fk, lbl in [
                        ("production_method", "Production method"),
                        ("system_boundary",   "System boundary"),
                        ("modules_declared",  "Modules declared"),
                    ]:
                        if r.get(fk):
                            st.markdown(f"**{lbl}**")
                            st.write(r[fk])
                with c2:
                    for fk, lbl in [
                        ("functional_unit",  "Functional unit"),
                        ("geographic_scope", "Geographic scope"),
                        ("flow_description", "Process flow"),
                    ]:
                        if r.get(fk):
                            st.markdown(f"**{lbl}**")
                            st.write(r[fk])
                st.caption(
                    f"Detail confidence: {r.get('detail_confidence')} — "
                    f"{r.get('_pages_sent_detail','?')} pages — "
                    f"{r.get('_detail_input_tokens',0):,} in / "
                    f"{r.get('_detail_output_tokens',0):,} out"
                )
            else:
                st.info(
                    "Detail fields not extracted. Enable **Detailed extraction** before running.",
                    icon="ℹ️",
                )

        with tab_meta:
            st.write({
                "Product":       r.get("product_name"),
                "Manufacturer":  r.get("manufacturer"),
                "EPD declaration number": r.get("epd_declaration_number") or r.get("epd_number"),
                "Registration number":    r.get("epd_registration_number") or r.get("epd_number"),
                "Programme":     r.get("programme_operator"),
                "Valid until":   r.get("validity_date"),
                "Issue date":    r.get("issue_date"),
                "Revision date": r.get("revision_date"),
                "Standard":      r.get("reference_standard"),
                "PCR":           r.get("pcr_reference"),
                "LCA software":  r.get("lca_software"),
                "LCA database":  r.get("lca_database"),
                "Verifier":      r.get("third_party_verifier"),
                "Fields edited": r.get("_fields_edited"),
                "Reviewed at":   r.get("_reviewed_at"),
            })
            if r.get("_error"):
                with st.expander("⚠ Extraction error", type="compact"):
                    st.code(r["_error"])