"""
libs/lib_eco_data.py — Shared data-loading layer for ECOportal pages 9 & 10.

All heavy @st.cache_data functions live here so both pages share the same
Streamlit cache buckets: one cold miss per cache key instead of two.

Speed stack (fastest first on warm runs):
  1. @st.cache_data in-memory hit   — zero I/O, sub-millisecond
  2. Persistent sidecar JSON        — one file read, replaces all parsing on restart
  3. orjson (if installed)          — 3-8× faster JSON parse than stdlib
  4. Fallback to stdlib json        — always available
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import streamlit as st

# ── JSON backend (orjson if available, stdlib json as fallback) ───────────────
try:
    import orjson as _json

    def _loads(data: bytes | str):
        return _json.loads(data if isinstance(data, bytes) else data.encode())

    def _dumps(obj: object) -> str:
        return _json.dumps(obj, option=_json.OPT_NON_STR_KEYS | _json.OPT_SERIALIZE_NUMPY).decode()

    def _dumps_bytes(obj: object) -> bytes:
        return _json.dumps(obj, option=_json.OPT_NON_STR_KEYS | _json.OPT_SERIALIZE_NUMPY)

    HAS_ORJSON = True

except ImportError:
    import json as _stdjson

    def _loads(data):
        return _stdjson.loads(data)

    def _dumps(obj) -> str:
        return _stdjson.dumps(obj, ensure_ascii=False, default=str)

    def _dumps_bytes(obj) -> bytes:
        return _stdjson.dumps(obj, ensure_ascii=False, default=str).encode()

    HAS_ORJSON = False


def fast_dumps(obj: object) -> str:
    """Fast JSON serialisation — uses orjson when available."""
    return _dumps(obj)


def _inject_headless_script(html: str) -> None:
    """Run a short script without reserving layout space (Streamlit ≥1.41 disallows height=0)."""
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.iframe(html, height=1)


# ── Path resolution ───────────────────────────────────────────────────────────
_LIB_FILE   = Path(__file__).resolve()
_APP_ROOT   = _LIB_FILE.parents[1]          # EETRA_MatLib_2026.05/
_EETRA_ROOT = _APP_ROOT.parent              # EETRA_MatLib/
_SODA_ROOT  = _EETRA_ROOT / "ECOportal_Downloader" / "soda4lca"

# Public path constants (imported by pages)
MAPPING_INPUT    = _SODA_ROOT / "output" / "aggregated" / "processes.json"
MAPPING_OUTPUT   = _SODA_ROOT / "output" / "aggregated" / "process_mapping.json"
XML_PROC_DIR     = _SODA_ROOT / "output" / "xml" / "processes"
JSON_PROC_DIR    = _SODA_ROOT / "output" / "json" / "processes"
EPD_JSON_DIR     = _APP_ROOT / "01_data" / "epd_json" / "json"
from .lib_html import ECO_BROWSER_TPL, read_iframe_component

# Internal paths
_XML_REG_CACHE   = _SODA_ROOT / "output" / "aggregated" / "xml_reg_numbers.json"
_XML_SRC_CACHE   = _SODA_ROOT / "output" / "aggregated" / "xml_source_uuids.json"
_PDF_URL_CACHE   = _SODA_ROOT / "output" / "aggregated" / "source_pdf_urls.json"
_BROWSER_SIDECAR = _SODA_ROOT / "output" / "aggregated" / "epd_browser_ready.json"
_MANIFEST_PATH   = _SODA_ROOT / "output" / "manifest.json"

# Bump this when the row schema changes to force sidecar rebuild.
_SIDECAR_VER = 4

# Maps substrings of a soda4LCA base_url to a short node name used for URL derivation.
_NODE_BY_URL: dict[str, str] = {
    "ibudata.lca-data.com":      "ibu",
    "epdnorway.lca-data.com":    "norway",
    "epditaly.it":               "italy",
    "epdcatalog.environdec.com": "ies",
    "environdec.com":            "ies",
    "inies.fr":                  "inies",
    "oekobaudat.de":             "oekobaudat",
}

# Reverse of _NODE_BY_URL: node short-name → soda4LCA resource root
_BASE_URL_BY_NODE: dict[str, str] = {
    "italy":      "https://node.epditaly.it/resource",
    "ibu":        "https://ibudata.lca-data.com/resource",
    "norway":     "https://epdnorway.lca-data.com/resource",
    "ies":        "https://epdcatalog.environdec.com/resource",
    "oekobaudat": "https://oekobaudat.de/OEKOBAU.DAT/resource",
    "inies":      "https://www.inies.fr/resource",
}


def _get_node_base_url() -> str:
    """Return the soda4LCA resource root URL, reading manifest.json first."""
    try:
        d = _loads(_MANIFEST_PATH.read_bytes())
        url = d.get("baseUrl") or d.get("base_url") or ""
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return _BASE_URL_BY_NODE.get(_detect_node(), "")


def _detect_node() -> str:
    """Return the short node name by reading manifest.json or processes.json metadata."""
    for src in (_MANIFEST_PATH,
                _SODA_ROOT / "output" / "aggregated" / "processes.json"):
        try:
            d = _loads(src.read_bytes())
            for key in ("base_url", "baseUrl", "source_node", "sourceNode", "node", "source"):
                url = (d.get(key) or "")
                if url:
                    for pattern, name in _NODE_BY_URL.items():
                        if pattern in url:
                            return name
        except Exception:
            continue
    return ""
_EPD_CODES_PATH  = _APP_ROOT  / "aux_05__epd_codes.json"
_COUNTRY_CODES_FILE = _SODA_ROOT / "aux__country_codes.json"


# ── Labels (loaded once per process via cache_resource) ───────────────────────
@st.cache_resource
def _load_all_labels() -> tuple[dict, dict, dict]:
    try:
        d = _loads(_EPD_CODES_PATH.read_bytes())
        prod = {str(k): str(v) for k, v in (d.get("prod_type") or {}).items()}
        mat  = {str(k): str(v) for k, v in (d.get("mat_type")  or {}).items()}
    except Exception:
        prod, mat = {}, {}
    try:
        country = _loads(_COUNTRY_CODES_FILE.read_bytes()).get("codes", {})
    except Exception:
        country = {}
    return prod, mat, country


PROD_LABELS, MAT_LABELS, COUNTRY_LABELS = _load_all_labels()

# Pre-serialised label JSON strings (computed once, reused in every HTML assembly)
_PROD_LABELS_JSON    = _dumps(PROD_LABELS)
_MAT_LABELS_JSON     = _dumps(MAT_LABELS)
_COUNTRY_LABELS_JSON = _dumps(COUNTRY_LABELS)


def prod_label(code: str) -> str:
    n = PROD_LABELS.get(code)
    return f"{n} ({code})" if n else (code or "—")


def mat_label(code: str) -> str:
    n = MAT_LABELS.get(code)
    return f"{n} ({code})" if n else (code or "—")


# ── EPD number helpers ────────────────────────────────────────────────────────
_REG_NUM_RE = re.compile(r'<[^>]*:?registrationNumber[^>]*>\s*([^<]+?)\s*</', re.I)
_SRC_UUID_RE = re.compile(
    r'referenceToOriginalEPD[^>]*\srefObjectId="'
    r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"',
    re.I,
)
_PDF_HREF_RE = re.compile(r'referenceToDigitalFile[^>]*\suri="(https?://[^"]+)"', re.I)

EPD_EXTRACT_PATTERNS: list[re.Pattern] = [
    re.compile(r'\b(NEPD[-\s]\d{4,}[-\w]*)',                                re.I),
    re.compile(r'\b(EPD-IES-\d+(?::\d+)?)',                                 re.I),
    re.compile(r'\b(S-P-\d{4,})',                                           re.I),
    re.compile(r'\b(IBU[-\s]\d{3}[-\d\-]+)',                                re.I),
    re.compile(r'\b(HUB-\d{3,})',                                           re.I),
    re.compile(r'(?:registration|declaration)\s*(?:number|no\.?)\s*[:\s]*'
               r'([A-Z0-9][A-Z0-9\-/]{3,24})',                             re.I),
]


def norm_epd_num(s: str) -> str | None:
    s = str(s).strip()
    if len(s) < 4:
        return None
    return re.sub(r'[\s:\.]+', '-', s.upper()).rstrip('-')


# ── Certification patterns ────────────────────────────────────────────────────
CERT_PATTERNS: dict[str, re.Pattern] = {
    "iag":          re.compile(r'indoor\s+air\s+comfort\s+gold|iag\s+(?:certif|scheme|label)', re.I),
    "m1":           re.compile(r'\bm1\b.{0,40}(?:emiss|class|certif|finnish|finland|rtm)|(?:emiss|class).{0,20}\bm1\b', re.I),
    "emicode":      re.compile(r'emicode\s*ec1|ec1\s*(?:plus|\+|r\b)', re.I),
    "nordic_swan":  re.compile(r'nordic\s+swan|svanemerket|\bsvanen\b', re.I),
    "blauer_engel": re.compile(r'blauer\s+engel|blue\s+angel', re.I),
    "natureplus":   re.compile(r'nature\s*plus', re.I),
    "greenguard":   re.compile(r'greenguard\s*gold', re.I),
    "leed":         re.compile(r'\bleed\b.{0,40}(?:certif|gold|silver|platinum|v4|approv)', re.I),
    "indoor_air":   re.compile(r'indoor\s+air\s+comfort(?!\s+gold)', re.I),
    "eurofins":     re.compile(r'eurofins\s*(?:gold|indoor)', re.I),
    "c2c":          re.compile(r'cradle.to.cradle\s*(?:silver|gold|platinum|certified)|\bc2c\b\s*(?:silver|gold|certif)', re.I),
    "breeam":       re.compile(r'\bbreeam\b.{0,30}(?:certif|excellent|very\s*good|approv)', re.I),
}
CERT_PATTERNS_VER = 1  # increment to bust cached process index


# ── Persistent XML reg-number cache ──────────────────────────────────────────
def _build_xml_reg_cache_incremental(xml_dir: Path, cache_file: Path) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    cache_mtime = 0.0
    if cache_file.exists():
        try:
            data = _loads(cache_file.read_bytes())
            cache_mtime = cache_file.stat().st_mtime
        except Exception:
            data = {}
    changed = False
    for xml_file in xml_dir.glob("*.xml"):
        try:
            if xml_file.stat().st_mtime <= cache_mtime:
                continue
        except OSError:
            continue
        uuid = xml_file.stem
        try:
            txt = xml_file.read_text(encoding="utf-8", errors="replace")
            nums: list[str] = []
            for m in _REG_NUM_RE.finditer(txt):
                for token in re.split(r'[\s\(\)]+', m.group(1).strip()):
                    n = norm_epd_num(token)
                    if n and n not in nums:
                        nums.append(n)
            if nums:
                data[uuid] = nums
            elif uuid in data:
                del data[uuid]
        except Exception:
            pass
        changed = True
    if changed or not cache_file.exists():
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(_dumps_bytes(data))
        except Exception:
            pass
    return data


def _build_xml_source_cache_incremental(xml_dir: Path, cache_file: Path) -> dict[str, str]:
    """Extract epd2:referenceToOriginalEPD refObjectId from each process XML.

    Returns {process_uuid: source_uuid}. Reads only files newer than the cache.
    """
    data: dict[str, str] = {}
    cache_mtime = 0.0
    if cache_file.exists():
        try:
            data = _loads(cache_file.read_bytes())
            cache_mtime = cache_file.stat().st_mtime
        except Exception:
            data = {}
    changed = False
    for xml_file in xml_dir.glob("*.xml"):
        try:
            if xml_file.stat().st_mtime <= cache_mtime:
                continue
        except OSError:
            continue
        proc_uuid = xml_file.stem
        try:
            txt = xml_file.read_text(encoding="utf-8", errors="replace")
            m = _SRC_UUID_RE.search(txt)
            if m:
                data[proc_uuid] = m.group(1).lower()
            elif proc_uuid in data:
                del data[proc_uuid]
        except Exception:
            pass
        changed = True
    if changed or not cache_file.exists():
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(_dumps_bytes(data))
        except Exception:
            pass
    return data


def _fetch_and_cache_pdf_urls(
    source_uuids: set[str],
    base_url: str,
    cache_file: Path,
    *,
    max_workers: int = 8,
    timeout: float = 15.0,
) -> dict[str, str]:
    """Fetch source XML for each UUID not yet cached; extract digitalFileReference URI.

    Requests run in parallel (up to max_workers threads) so N EPDs cost ~1 RTT
    instead of N. Results are persisted; only genuinely new UUIDs hit the network.
    Returns {source_uuid: pdf_url}.
    """
    cached: dict[str, str] = {}
    if cache_file.exists():
        try:
            cached = _loads(cache_file.read_bytes())
        except Exception:
            cached = {}

    needed = source_uuids - set(cached)
    if not needed:
        return cached

    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(src_uuid: str) -> tuple[str, str]:
        url = f"{base_url}/sources/{src_uuid}?format=xml"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/xml"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", errors="replace")
            m = _PDF_HREF_RE.search(txt)
            return src_uuid, m.group(1) if m else ""
        except Exception:
            return src_uuid, ""

    new_urls: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(needed))) as pool:
        for src_uuid, pdf_url in pool.map(_fetch_one, needed):
            if pdf_url:
                new_urls[src_uuid] = pdf_url

    if new_urls:
        cached.update(new_urls)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(_dumps_bytes(cached))
        except Exception:
            pass

    return cached


# ── Shared @st.cache_data loaders ────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def load_xml_reg_numbers(xml_dir_str: str, dir_mtime_ns: int) -> dict[str, list[str]]:
    xml_dir = Path(xml_dir_str)
    if not xml_dir.is_dir():
        return {}
    return _build_xml_reg_cache_incremental(xml_dir, _XML_REG_CACHE)


@st.cache_data(show_spinner=False, ttl=3600)
def load_xml_source_uuids(xml_dir_str: str, dir_mtime_ns: int) -> dict[str, str]:
    """Return {process_uuid: source_uuid} extracted from referenceToOriginalEPD."""
    xml_dir = Path(xml_dir_str)
    if not xml_dir.is_dir():
        return {}
    return _build_xml_source_cache_incremental(xml_dir, _XML_SRC_CACHE)


@st.cache_data(show_spinner=False, ttl=300)
def load_processes_index(
    processes_path_str: str,
    mtime_ns: int,
    cert_ver: int = CERT_PATTERNS_VER,
) -> dict[str, dict]:
    try:
        data = _loads(Path(processes_path_str).read_bytes())
        out: dict[str, dict] = {}
        for ds in data.get("datasets", []):
            uid = ds.get("uuid")
            if not uid:
                continue
            owner_raw = ds.get("owner") or {}
            owner = (owner_raw.get("shortName", "") if isinstance(owner_raw, dict) else "") or ""
            cls_parts: list[str] = []
            for cls in (ds.get("classification") or []):
                names = [c.get("name", "") for c in (cls.get("classes") or []) if c.get("name")]
                if names:
                    cls_parts.append(" › ".join(names))
            tech = ds.get("technology") or ""
            certs = [cid for cid, pat in CERT_PATTERNS.items() if pat.search(tech)]
            epd_nums: list[str] = []
            for pat in EPD_EXTRACT_PATTERNS:
                for m in pat.finditer(tech):
                    n = norm_epd_num(m.group(1))
                    if n and n not in epd_nums:
                        epd_nums.append(n)
            out[uid] = {
                "loc":        ds.get("location") or "",
                "owner":      owner,
                "year":       str(ds.get("referenceYear") or ""),
                "valid_until": str(ds.get("validUntil") or ""),
                "version":    str(ds.get("version") or ""),
                "cls_path":   " | ".join(cls_parts[:2]),
                "certs":      certs,
                "epd_nums":   epd_nums,
            }
        return out
    except Exception:
        return {}


@st.cache_data(show_spinner=False, ttl=300)
def load_processes_raw_index(processes_path_str: str, mtime_ns: int) -> dict[str, dict]:
    """UUID → full processes.json dataset (XML converted to JSON)."""
    try:
        data = _loads(Path(processes_path_str).read_bytes())
        out: dict[str, dict] = {}
        for ds in data.get("datasets", []):
            uid = ds.get("uuid")
            if uid:
                out[uid] = ds
        return out
    except Exception:
        return {}


# cache_resource, not cache_data: process_mapping.json is ~8 MB and cache_data
# hands every caller a fresh unpickled deep copy (twice per ECOportal rerun).
# The mtime argument already invalidates it, so no ttl is needed. The result is
# SHARED across sessions — callers must treat it as read-only (all current
# callers only .get() from it or serialise it).
@st.cache_resource(show_spinner=False, max_entries=2)
def load_mapping(mapping_path_str: str, mtime_ns: int) -> dict | None:
    try:
        return _loads(Path(mapping_path_str).read_bytes())
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=300)
def build_merged_proc_index(
    processes_path_str: str,
    proc_mtime_ns: int,
    xml_dir_str: str,
    xml_dir_mtime_ns: int,
    cert_ver: int = CERT_PATTERNS_VER,
) -> dict[str, dict]:
    """Merge processes.json metadata with registration numbers extracted from XMLs.

    Pure file/cache I/O only — no network calls. PDF URL lookup is done once in
    build_cat_rows_base (sidecar-protected) rather than here (ttl=300).
    """
    proc_index   = load_processes_index(processes_path_str, proc_mtime_ns, cert_ver)
    xml_reg_nums = load_xml_reg_numbers(xml_dir_str, xml_dir_mtime_ns)
    if not xml_reg_nums:
        return proc_index
    result: dict[str, dict] = {}
    for uid, entry in proc_index.items():
        xml_nums = xml_reg_nums.get(uid)
        if xml_nums:
            existing = entry.get("epd_nums") or []
            merged = list(existing)
            for n in xml_nums:
                if n not in merged:
                    merged.append(n)
            result[uid] = {**entry, "epd_nums": merged} if merged != existing else entry
        else:
            result[uid] = entry
    for uid, xml_nums in xml_reg_nums.items():
        if uid not in result:
            result[uid] = {"loc": "", "owner": "", "year": "", "valid_until": "",
                           "version": "", "cls_path": "", "certs": [], "epd_nums": xml_nums}
    return result


# cache_resource: the row list (~40k dicts) was deep-copied out of cache_data on
# every rerun. Rows are SHARED and read-only — apply_matlib builds new dicts
# rather than stamping these. ttl kept so a manifest.json change (read inside,
# not part of the key) is still picked up within 5 minutes, as before.
@st.cache_resource(show_spinner=False, ttl=300, max_entries=2)
def build_cat_rows_base(
    mapping_output_str: str,
    mapping_output_mtime: int,
    mapping_input_str: str,
    mapping_input_mtime: int,
    xml_dir_str: str,
    xml_mtime: int,
) -> list[dict]:
    """Build all EPD rows (no MatLib flags). Shared across all sessions.

    Uses a persistent sidecar JSON so cross-restart cold starts skip all JSON
    parsing and merging — the sidecar is read in a single fast pass.
    """
    _man_mtime = int(_MANIFEST_PATH.stat().st_mtime_ns) if _MANIFEST_PATH.exists() else 0
    sidecar_key = f"{mapping_output_mtime}-{mapping_input_mtime}-{xml_mtime}-{_man_mtime}-v{_SIDECAR_VER}"

    # Fast path: valid sidecar → skip all parsing
    if _BROWSER_SIDECAR.exists():
        try:
            sd = _loads(_BROWSER_SIDECAR.read_bytes())
            if sd.get("key") == sidecar_key:
                return sd["rows"]
        except Exception:
            pass

    # Slow path: build from source files (all sub-calls are cached, warm hits fast)
    source_node = _detect_node()
    mapping_data = load_mapping(mapping_output_str, mapping_output_mtime)
    mappings: dict = (mapping_data or {}).get("mappings", {})
    proc_index = build_merged_proc_index(
        mapping_input_str, mapping_input_mtime, xml_dir_str, xml_mtime
    )

    # PDF URL fetch: parallel HTTP, runs once per sidecar rebuild then cached to disk
    xml_src_uuids = load_xml_source_uuids(xml_dir_str, xml_mtime)
    pdf_urls: dict[str, str] = {}
    if xml_src_uuids:
        base_url = _get_node_base_url()
        if base_url:
            pdf_urls = _fetch_and_cache_pdf_urls(
                set(xml_src_uuids.values()), base_url, _PDF_URL_CACHE
            )

    rows: list[dict] = []
    for uuid, v in mappings.items():
        pi = proc_index.get(uuid, {})
        src_uuid = xml_src_uuids.get(uuid, "")
        rows.append({
            "name":        v.get("name", ""),
            "owner":       pi.get("owner", ""),
            "loc":         pi.get("loc", ""),
            "year":        pi.get("year", ""),
            "valid_until": pi.get("valid_until", ""),
            "version":     pi.get("version", ""),
            "cls_path":    pi.get("cls_path", ""),
            "certs":       pi.get("certs", []),
            "epd_nums":    pi.get("epd_nums", []),
            "pdf_url":     pdf_urls.get(src_uuid, "") if src_uuid else "",
            "in_matlib":   False,
            "prod":        v.get("prod_code") or "",
            "mat":         v.get("mat_code")  or "",
            "conf":        v.get("confidence", ""),
            "uuid":        uuid,
            "node":        source_node,
        })

    # Persist sidecar for next restart
    try:
        _BROWSER_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        _BROWSER_SIDECAR.write_bytes(_dumps_bytes({"key": sidecar_key, "rows": rows}))
    except Exception:
        pass

    return rows


def apply_matlib(
    rows: list[dict],
    matlib_set: set[str],
    matlib_names: set[str],
) -> list[dict]:
    """Stamp in_matlib on each row. O(n) set-lookup pass, not cached (session-specific)."""
    out = []
    for row in rows:
        in_ml = bool(matlib_set and any(n in matlib_set for n in row["epd_nums"]))
        if not in_ml and matlib_names and row["name"].strip().lower() in matlib_names:
            in_ml = True
        out.append({**row, "in_matlib": in_ml})
    return out


@st.cache_data(show_spinner=False, ttl=300)
def build_epd_data_json(
    mapping_output_str: str,
    mapping_output_mtime: int,
    mapping_input_str: str,
    mapping_input_mtime: int,
    xml_dir_str: str,
    xml_mtime: int,
) -> str:
    """Return the JSON string for window.__EPD_DATA__ (full dataset, no MatLib).

    Cached: json.dumps only runs on cache miss. Both pages 9 and 10 share this.
    """
    rows = build_cat_rows_base(
        mapping_output_str, mapping_output_mtime,
        mapping_input_str,  mapping_input_mtime,
        xml_dir_str, xml_mtime,
    )
    # Strip in_matlib — JS recomputes it from window.__MATLIB_NUMS__
    return _dumps([{k: v for k, v in r.items() if k != "in_matlib"} for r in rows])


@st.cache_data(show_spinner=False)
def load_browser_template(tpl_mtime_ns: int) -> str:
    """Cache the HTML template. Re-reads only when the file changes."""
    try:
        return read_iframe_component(
            ECO_BROWSER_TPL,
            missing_message="<p>html/ecoportal_component.html not found.</p>",
        )
    except Exception:
        return "<p>html/ecoportal_component.html not found.</p>"


def subset_epd_sources(
    rows: list[dict],
    output_map: dict[str, dict],
    raw_map: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Keep only UUIDs present in the displayed rows."""
    uuids = {r["uuid"] for r in rows if r.get("uuid")}
    return (
        {u: output_map[u] for u in uuids if u in output_map},
        {u: raw_map[u] for u in uuids if u in raw_map},
    )


# ── ILCD XML parser (for popup Overview / LCI / LCIA tabs) ───────────────────

_ILCD_NS = {
    "p":   "http://lca.jrc.it/ILCD/Process",
    "c":   "http://lca.jrc.it/ILCD/Common",
    "epd": "http://www.iai.kit.edu/EPD/2013",
    "ep2": "http://www.indata.network/EPD/2019",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
_ILCD_LANG_ATTR = "{http://www.w3.org/XML/1998/namespace}lang"
_ILCD_MOD_ATTR  = "{http://www.iai.kit.edu/EPD/2013}module"


def _ilcd_text(el, xpath: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(xpath, _ILCD_NS)
    return (found.text or "").strip() if found is not None and found.text else default


def _ilcd_lang(el, tag: str, lang: str = "en", default: str = "") -> str:
    if el is None:
        return default
    for ch in el.findall(tag, _ILCD_NS):
        if ch.get(_ILCD_LANG_ATTR) == lang and ch.text:
            return ch.text.strip()
    for ch in el.findall(tag, _ILCD_NS):
        if ch.text:
            return ch.text.strip()
    return default


def _ilcd_mod_amounts(container) -> dict[str, float]:
    out: dict[str, float] = {}
    for amt in container.findall(f".//{'{http://www.iai.kit.edu/EPD/2013}amount'}"):
        mod = amt.get(_ILCD_MOD_ATTR, "")
        if mod and amt.text:
            try:
                out[mod] = float(amt.text)
            except ValueError:
                pass
    return out


@st.cache_data(show_spinner=False, ttl=3600)
def parse_ilcd_xml(path_str: str, mtime_ns: int) -> dict | None:
    """Parse one ILCD process XML; return overview + LCI exchanges + LCIA results."""
    try:
        root = ET.parse(path_str).getroot()
    except Exception:
        return None

    p_info  = root.find("p:processInformation", _ILCD_NS)
    ds_info = p_info.find("p:dataSetInformation", _ILCD_NS) if p_info else None
    name_el = ds_info.find("p:name", _ILCD_NS) if ds_info else None
    name    = _ilcd_lang(name_el, "p:baseName") if name_el else ""
    comment = _ilcd_lang(ds_info, "c:generalComment") if ds_info else ""

    classifications: list[dict] = []
    if ds_info is not None:
        for cls in ds_info.findall(".//c:classification", _ILCD_NS):
            sys_name = cls.get("name", "")
            parts = [c.text for c in cls.findall("c:class", _ILCD_NS) if c.text]
            if parts:
                classifications.append({"system": sys_name, "path": " › ".join(parts)})

    time_el     = p_info.find("p:time", _ILCD_NS) if p_info else None
    ref_year    = _ilcd_text(time_el, "c:referenceYear")
    valid_until = _ilcd_text(time_el, "c:dataSetValidUntil")
    geo_el = (
        p_info.find("p:geography/p:locationOfOperationSupplyOrProduction", _ILCD_NS)
        if p_info else None
    )
    location = geo_el.get("location", "") if geo_el is not None else ""

    mv_el    = root.find("p:modellingAndValidation", _ILCD_NS)
    lci_el   = mv_el.find("p:LCIMethodAndAllocation", _ILCD_NS) if mv_el else None
    epd_type = _ilcd_text(lci_el, "p:typeOfDataSet")
    sub_el   = (
        lci_el.find(f".//{'{http://www.iai.kit.edu/EPD/2013}subType'}", _ILCD_NS)
        if lci_el else None
    )
    subtype  = (sub_el.text or "").strip() if sub_el is not None else ""

    rev_el   = mv_el.find("p:validation/p:review", _ILCD_NS) if mv_el else None
    reviewer = ""
    if rev_el is not None:
        rev_i    = rev_el.find("c:referenceToNameOfReviewerAndInstitution", _ILCD_NS)
        reviewer = _ilcd_lang(rev_i, "c:shortDescription")

    admin_el   = root.find("p:administrativeInformation", _ILCD_NS)
    pub_el     = admin_el.find("p:publicationAndOwnership", _ILCD_NS) if admin_el else None
    version    = _ilcd_text(pub_el, "c:dataSetVersion")
    reg_number = _ilcd_text(pub_el, "c:registrationNumber")
    owner_el   = pub_el.find("c:referenceToOwnershipOfDataSet", _ILCD_NS) if pub_el else None
    owner      = _ilcd_lang(owner_el, "c:shortDescription")

    exchanges: list[dict] = []
    for ex_el in root.findall(".//p:exchange", _ILCD_NS):
        flow_el   = ex_el.find("p:referenceToFlowDataSet", _ILCD_NS)
        flow_name = _ilcd_lang(flow_el, "c:shortDescription")
        direction = _ilcd_text(ex_el, "p:exchangeDirection")
        mods      = _ilcd_mod_amounts(ex_el)
        if mods:
            exchanges.append({
                "flow": flow_name,
                "dir":  direction[:3] if direction else "",
                "modules": mods,
            })

    lcia: list[dict] = []
    for lr_el in root.findall(".//p:LCIAResult", _ILCD_NS):
        method_el = lr_el.find("p:referenceToLCIAMethodDataSet", _ILCD_NS)
        method    = _ilcd_lang(method_el, "c:shortDescription")
        mods      = _ilcd_mod_amounts(lr_el)
        lcia.append({"method": method, "modules": mods})

    return {
        "name": name, "comment": comment,
        "classifications": classifications,
        "ref_year": ref_year, "valid_until": valid_until, "location": location,
        "epd_type": epd_type, "subtype": subtype,
        "version": version, "reg_number": reg_number,
        "owner": owner, "reviewer": reviewer,
        "exchanges": exchanges,
        "lcia": lcia,
    }


@st.cache_data(show_spinner=False, ttl=300)
def load_epd_source_for_uuid(
    uuid: str,
    mapping_output_str: str,
    mapping_output_mtime: int,
) -> dict:
    """Return mapping output + per-UUID process JSON + parsed ILCD XML for one process UUID."""
    output = None
    mapping_data = load_mapping(mapping_output_str, mapping_output_mtime)
    if mapping_data:
        output = (mapping_data.get("mappings") or {}).get(uuid)

    # Direct lookup: output/json/processes/{uuid}.json — one small file per EPD
    raw = None
    proc_json = JSON_PROC_DIR / (uuid + ".json")
    if proc_json.exists():
        try:
            raw = _loads(proc_json.read_bytes())
        except Exception:
            pass

    ilcd = None
    xml_path = XML_PROC_DIR / (uuid + ".xml")
    if xml_path.exists():
        try:
            ilcd = parse_ilcd_xml(str(xml_path), int(xml_path.stat().st_mtime_ns))
        except Exception:
            pass

    return {"output": output, "raw": raw, "raw_fetched": True, "ilcd": ilcd}


# Cached: re-serialising the whole mappings dict (~8 MB) cost a full orjson pass
# on every ECOportal rerun although it only changes with the file.
@st.cache_data(show_spinner=False, max_entries=2)
def get_output_map_json(mapping_output_str: str, mapping_output_mtime: int) -> str:
    """Serialised process_mapping.json mappings for client-side Output tab."""
    mapping_data = load_mapping(mapping_output_str, mapping_output_mtime)
    return fast_dumps((mapping_data or {}).get("mappings", {}))


def process_epd_source_bridge_request(
    bridge_value,
    mapping_output_str: str,
    mapping_output_mtime: int,
) -> tuple[dict | None, dict | None]:
    """Load source bundle when the invisible bridge component returns a UUID."""
    if not bridge_value or not isinstance(bridge_value, dict):
        return None, None
    uuid = str(bridge_value.get("uuid") or "").strip()
    if not uuid:
        return None, None
    bundle = load_epd_source_for_uuid(uuid, mapping_output_str, mapping_output_mtime)
    return {"uuid": uuid, **bundle}, bridge_value.get("uiState")


def _build_source_bundle_message(bundle: dict, ui_state: dict | None) -> str:
    return fast_dumps({
        "type": "epd:sourceBundle",
        "uuid": bundle["uuid"],
        "data": {
            "output": bundle.get("output"),
            "raw": bundle.get("raw"),
            "raw_fetched": bundle.get("raw_fetched"),
            "ilcd": bundle.get("ilcd"),
        },
        "uiState": ui_state,
    })


@st.fragment
def render_epd_source_loader_fragment(
    mapping_output_str: str,
    mapping_output_mtime: int,
) -> None:
    """Bridge + deliver: reruns on load request without touching the browser iframe."""
    from libs.epd_source_bridge import epd_source_bridge

    relay_payload = st.session_state.pop("_epd_relay_payload", "")
    bridge_val = epd_source_bridge(deliver=relay_payload, key="epd_src_bridge")

    if relay_payload:
        return

    if not bridge_val or not isinstance(bridge_val, dict) or not bridge_val.get("uuid"):
        return
    sig = fast_dumps({
        "uuid": bridge_val.get("uuid"),
        "ui": bridge_val.get("uiState"),
    })
    if st.session_state.get("_epd_last_bridge_sig") == sig:
        return
    st.session_state["_epd_last_bridge_sig"] = sig
    bundle, ui = process_epd_source_bridge_request(
        bridge_val, mapping_output_str, mapping_output_mtime,
    )
    if bundle:
        st.session_state["_epd_relay_payload"] = _build_source_bundle_message(bundle, ui)
        st.rerun(scope="fragment")


def render_epd_browser_iframe(
    cat_rows: list,
    matlib_nums: set[str],
    matlib_names_lc: set[str],
    iframe_height: int = 860,
    output_map_json: str | None = None,
    matlib_norm_to_id: dict | None = None,
    matlib_name_to_id: dict | None = None,
) -> None:
    """Render the EPD browser iframe — stable; not rerun on source load."""
    tpl_path = ECO_BROWSER_TPL
    tpl_mtime = int(tpl_path.stat().st_mtime_ns) if tpl_path.exists() else 0
    tpl = load_browser_template(tpl_mtime)
    js_html = render_epd_browser_html(
        fast_dumps(cat_rows),
        tpl,
        matlib_nums,
        matlib_names_lc,
        iframe_height=iframe_height,
        output_map_json=output_map_json,
        matlib_norm_to_id=matlib_norm_to_id,
        matlib_name_to_id=matlib_name_to_id,
    )
    st.iframe(js_html, height=iframe_height)


def render_epd_browser_with_loader(
    cat_rows: list,
    matlib_nums: set[str],
    matlib_names_lc: set[str],
    mapping_output_str: str,
    mapping_output_mtime: int,
    iframe_height: int = 860,
    output_map_json: str | None = None,
    matlib_norm_to_id: dict | None = None,
    matlib_name_to_id: dict | None = None,
) -> None:
    """EPD browser (stable) + source loader fragment (reruns only on fetch)."""
    render_epd_source_loader_fragment(mapping_output_str, mapping_output_mtime)
    render_epd_browser_iframe(
        cat_rows, matlib_nums, matlib_names_lc,
        iframe_height=iframe_height,
        output_map_json=output_map_json,
        matlib_norm_to_id=matlib_norm_to_id,
        matlib_name_to_id=matlib_name_to_id,
    )


def render_epd_browser_fragment(
    cat_rows: list,
    matlib_nums: set[str],
    matlib_names_lc: set[str],
    mapping_output_str: str,
    mapping_output_mtime: int,
    iframe_height: int = 860,
    output_map_json: str | None = None,
    matlib_norm_to_id: dict | None = None,
    matlib_name_to_id: dict | None = None,
) -> None:
    """Back-compat alias."""
    render_epd_browser_with_loader(
        cat_rows, matlib_nums, matlib_names_lc,
        mapping_output_str, mapping_output_mtime,
        iframe_height=iframe_height,
        output_map_json=output_map_json,
        matlib_norm_to_id=matlib_norm_to_id,
        matlib_name_to_id=matlib_name_to_id,
    )


# ── Cached final browser payload ─────────────────────────────────────────────
# The browser iframe used to be rebuilt from scratch on every rerun: copy ~40k
# rows (apply_matlib), orjson-dump them (~16 MB), gzip + base64 the result and
# re-serialise the output map — ~8 s per rerun, for a page whose inputs only
# change with the source files or the catalogue. Everything below is keyed on
# scalars (file mtimes + a signature of the MatLib sets), so a warm rerun is a
# cache lookup. A stable HTML string also means the frontend receives the same
# bytes each run instead of a fresh gzip stream (gzip stamps the current time
# into its header, so the old per-run output differed every time).

def matlib_signature(
    matlib_nums: set[str],
    matlib_names_lc: set[str],
    matlib_norm_to_id: dict | None,
    matlib_name_to_id: dict | None,
) -> str:
    """Stable digest of the MatLib cross-reference, used as a cache key.

    Hashes exactly the JSON strings render_epd_browser_html injects (sorted sets,
    dicts in insertion order), so two inputs with the same signature produce the
    same HTML.
    """
    h = hashlib.sha1()
    for part in (
        _dumps(sorted(matlib_nums)),
        _dumps(sorted(matlib_names_lc)),
        _dumps(matlib_norm_to_id or {}),
        _dumps(matlib_name_to_id or {}),
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def manifest_mtime_ns() -> int:
    """manifest.json mtime — part of the sidecar key, so part of the HTML key."""
    return int(_MANIFEST_PATH.stat().st_mtime_ns) if _MANIFEST_PATH.exists() else 0


@st.cache_data(show_spinner=False, max_entries=4)
def matlib_row_stats(
    mapping_output_str: str,
    mapping_output_mtime: int,
    mapping_input_str: str,
    mapping_input_mtime: int,
    xml_dir_str: str,
    xml_mtime: int,
    manifest_mtime: int,
    matlib_sig: str,
    _matlib_nums: set[str],
    _matlib_names_lc: set[str],
) -> tuple[int, int, dict, dict]:
    """(n_rows, n_in_matlib, prod_counts, mat_counts) for the page header/charts.

    The sets are `_`-prefixed (not hashed); matlib_sig stands in for them.
    Counts are plain dicts built in row order, so Counter(...).most_common()
    on them breaks ties exactly as the old per-rerun Counter did.
    """
    rows = build_cat_rows_base(
        mapping_output_str, mapping_output_mtime,
        mapping_input_str,  mapping_input_mtime,
        xml_dir_str, xml_mtime,
    )
    cat_rows = apply_matlib(rows, _matlib_nums, _matlib_names_lc) if rows else []
    prod: dict[str, int] = {}
    mat: dict[str, int] = {}
    for r in cat_rows:
        if r["prod"]:
            prod[r["prod"]] = prod.get(r["prod"], 0) + 1
        if r["mat"]:
            mat[r["mat"]] = mat.get(r["mat"], 0) + 1
    n_matlib = sum(1 for r in cat_rows if r["in_matlib"])
    return len(cat_rows), n_matlib, prod, mat


@st.cache_data(show_spinner=False, max_entries=4)
def build_epd_browser_page_html(
    mapping_output_str: str,
    mapping_output_mtime: int,
    mapping_input_str: str,
    mapping_input_mtime: int,
    xml_dir_str: str,
    xml_mtime: int,
    manifest_mtime: int,
    tpl_mtime: int,
    iframe_height: int,
    matlib_sig: str,
    _matlib_nums: set[str],
    _matlib_names_lc: set[str],
    _matlib_norm_to_id: dict | None,
    _matlib_name_to_id: dict | None,
) -> str:
    """Final EPD-browser iframe HTML — same bytes the uncached path produced.

    Pure: no st.* elements. `_`-prefixed MatLib structures are excluded from the
    key on purpose; matlib_sig (see matlib_signature) represents them.
    """
    rows = build_cat_rows_base(
        mapping_output_str, mapping_output_mtime,
        mapping_input_str,  mapping_input_mtime,
        xml_dir_str, xml_mtime,
    )
    cat_rows = apply_matlib(rows, _matlib_nums, _matlib_names_lc) if rows else []
    return render_epd_browser_html(
        fast_dumps(cat_rows),
        load_browser_template(tpl_mtime),
        _matlib_nums,
        _matlib_names_lc,
        iframe_height=iframe_height,
        output_map_json=get_output_map_json(mapping_output_str, mapping_output_mtime),
        matlib_norm_to_id=_matlib_norm_to_id,
        matlib_name_to_id=_matlib_name_to_id,
    )


def browser_template_mtime_ns() -> int:
    return int(ECO_BROWSER_TPL.stat().st_mtime_ns) if ECO_BROWSER_TPL.exists() else 0


def render_epd_browser_cached_html(
    js_html: str,
    mapping_output_str: str,
    mapping_output_mtime: int,
    iframe_height: int = 860,
) -> None:
    """Source-loader fragment + browser iframe from pre-built (cached) HTML."""
    render_epd_source_loader_fragment(mapping_output_str, mapping_output_mtime)
    st.iframe(js_html, height=iframe_height)


def maybe_render_epd_fetch_response(
    query_params,
    mapping_output_str: str,
    mapping_output_mtime: int,
) -> None:
    """Background fetch endpoint: host-level hidden iframe loads this; posts JSON to top."""
    flag = query_params.get("_epd_fetch")
    if flag not in ("1", "true", 1, True):
        return
    uuid_raw = query_params.get("uuid")
    uuid = (uuid_raw[0] if isinstance(uuid_raw, list) else uuid_raw or "").strip()
    if not uuid:
        st.stop()

    bundle = load_epd_source_for_uuid(
        uuid,
        mapping_output_str,
        mapping_output_mtime,
    )
    payload = fast_dumps({"type": "epd:sourceBundle", "uuid": uuid, "data": bundle})
    _script = f'<script>window.top.postMessage({payload}, "*");</script>'
    _inject_headless_script(_script)
    st.stop()


def render_epd_browser_html(
    data_json: str,
    tpl: str,
    matlib_nums: set[str],
    matlib_names_lc: set[str],
    iframe_height: int = 860,
    output_map_json: str | None = None,
    pending_bundle_json: str | None = None,
    pending_ui_json: str | None = None,
    matlib_norm_to_id: dict | None = None,
    matlib_name_to_id: dict | None = None,
) -> str:
    """Assemble the final iframe HTML from pre-built parts. Pure string ops."""
    # Large payloads ship gzipped (base64) and inflate client-side via
    # DecompressionStream — typically 80-90% smaller. Small ones stay plain.
    if len(data_json) > 500_000:
        import base64 as _b64
        import gzip as _gzip
        _gz = _b64.b64encode(_gzip.compress(data_json.encode("utf-8"), 6)).decode("ascii")
        _data_decl = f'window.__EPD_DATA_GZ__ = "{_gz}";\n'
    else:
        _data_decl = f"window.__EPD_DATA__ = {data_json};\n"
    inject = _data_decl + (
        f"window.__EPD_OUTPUT_MAP__ = {output_map_json or '{}'};\n"
        f"window.__EPD_PENDING_BUNDLE__ = {pending_bundle_json or 'null'};\n"
        f"window.__EPD_PENDING_UI__ = {pending_ui_json if pending_ui_json is not None else 'null'};\n"
        f"window.__PROD_LABELS__ = {_PROD_LABELS_JSON};\n"
        f"window.__MAT_LABELS__ = {_MAT_LABELS_JSON};\n"
        f"window.__COUNTRY_LABELS__ = {_COUNTRY_LABELS_JSON};\n"
        f"window.__MATLIB_NUMS__ = {_dumps(sorted(matlib_nums))};\n"
        f"window.__MATLIB_NAMES_LC__ = {_dumps(sorted(matlib_names_lc))};\n"
        f"window.__MATLIB_NORM_TO_ID__ = {_dumps(matlib_norm_to_id or {})};\n"
        f"window.__MATLIB_NAME_TO_ID__ = {_dumps(matlib_name_to_id or {})};\n"
        f"window.__IFRAME_HEIGHT__ = {int(iframe_height)};\n"
    )
    return tpl.replace("/* INJECT_DATA_HERE */", inject, 1)
