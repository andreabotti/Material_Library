"""
Excel → Parquet pipeline for EETRA MatLib

Usage (PowerShell):
    python tools/03_excel_to_parquet.py

What this script does:
  1) Loads the _live_data sheet from a local Excel file (or SharePoint fallback)
  2) Normalises column dtypes so Parquet writing is robust (fixes mixed int/str object cols)
  3) Downloads product images, EPD PDFs, technical-sheet PDFs, and VOC-cert PDFs —
     deduplicated so no product ever downloads/stores a document twice (see below)
  4) Parses each VOC-cert PDF to extract certificate number and expiry date
     (deterministic regex first, Claude API fallback for whatever regex can't
     find — see libs/lib_voc_extractor.py; use --no-claude-voc to disable),
     and writes the results back into the dataframe as new columns:
       V__VOC_Cert_Number  — certificate / registration number found in the PDF
       V__VOC_Cert_Expiry  — expiry / valid-until date found in the PDF (ISO YYYY-MM-DD)
  5) Writes base_data.parquet (the Excel conversion — this script's only output
     of record). App edits survive the refresh because the app replays
     edits_data.parquet over the new base on every read

File naming convention for media in 01_data/ (see download_media_deduped()):
  Many rows share the same document (thickness/size variants of one product,
  or several products citing the same EPD) — each unique document is stored
  ONCE, and every row referencing it points at that single file.

    01_data/img/<sha256(url)[:16]>.<ext>              product image
    01_data/pdf/<sha256(url)[:16]>.pdf                technical sheet / VOC certificate
    01_data/pdf/dec_<DEC>__reg_<REG>.pdf               EPD, keyed by its own identifier —
                                                        e.g. dec_EPD-IES-0006430-002__reg_S-P-06430.pdf
    01_data/pdf/reg_<REG>.pdf                          EPD with only a registration number
    01_data/pdf/dec_<DEC>.pdf                          EPD with only a declaration number
    01_data/pdf/<sha256(url)[:16]>.pdf                EPD with neither number (URL-hash fallback)

  EPD PDFs are deliberately keyed by the EPD's own registration/declaration
  number rather than by URL: two product rows can cite the *same* EPD through
  two *different* URLs (a manufacturer mirror vs. the registry's own link), in
  which case a pure URL-hash scheme would silently store — and re-download —
  the identical document twice. Keying by EPD number collapses those onto one
  file regardless of which URL each row happens to record. Numbers are
  normalised the same way as libs.lib_data.fn141_norm_epd_num (colons/dots/
  whitespace → '-', upper-cased) so "EPD-IES-0006430:002" and "S-P-06430" become
  filesystem-safe tokens.

# ── MotherDuck upload (disabled) ──────────────────────────────────────────────
# Upload to MotherDuck is intentionally commented out.
# To re-enable: uncomment the "PARQUET -> MOTHERDUCK" section at the bottom.
# ──────────────────────────────────────────────────────────────────────────────
"""
import argparse
import hashlib
import os
import re
import sys
import pathlib
from datetime import datetime
from io import BytesIO

# Windows consoles/pipes often default to a non-UTF-8 codepage (cp1252) that
# can't encode the →/⚠ characters used in this script's progress output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import pandas as pd
import requests as _requests

try:
    from PIL import Image as _Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ── PDF backend (required for VOC cert parsing via libs.lib_voc_extractor) ────
try:
    import fitz  # noqa: F401 (PyMuPDF — availability check only)
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False


# ===== CONFIG =================================================================
EXCEL_PATH = (
    r"E:\0D_OneDrive\EETRA srl SB\05_Ricerca e Sviluppo - Documenti"
    r"\RES12__EETRA_MaterialLIbrary\EETRA_MaterialLibrary.xlsx"
)
# Set EXCEL_PATH = None to use SharePoint instead.

SHEET_NAME  = "_live_data"
# ── Two-file model (see libs/lib_data.py fn153-fn158) ────────────────────────
# This script owns base_data.parquet ONLY — the pure Excel conversion. Anything
# created or edited in the app lives in edits_data.parquet (append-only) and is
# never overwritten here, so re-running the pipeline can't clobber app edits.
# The merge is derived on read by the app, not written here, for the modules that
# still read that file directly (libs/lib_tags.py, libs/lib_ui.py, 04_tools/…).
_PROJECT_ROOT    = pathlib.Path(__file__).resolve().parent.parent
# Both datasets live in 01_data/ with the rest of the project's data. There used
# to be four parquets — these two, a root-level copy of each, and a materialised
# live_data.parquet — all byte-identical. The app derives base + edits on read,
# so the merge is no longer written to disk at all.
PARQUET_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH   = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

# If an object column is "mostly numeric", coerce it to numeric.
NUMERIC_SUCCESS_THRESHOLD = 0.85

# ── media download settings ───────────────────────────────────────────────────
DOWNLOAD_MEDIA  = True   # set False to skip all downloads
OVERWRITE_MEDIA = False  # set True to re-download even if file already exists

DATA_IMG_SUBDIR = "01_data/img"
DATA_PDF_SUBDIR = "01_data/pdf"

# Product images larger than this (long edge, px) are downscaled with LANCZOS
# resampling before being written to 01_data/img — keeps the repo/media folder
# light without visibly degrading thumbnails in the app.
IMG_MAX_DIMENSION = 1000

# ── Excel column names ────────────────────────────────────────────────────────
COL_ID          = "0__EETRA_ID"
COL_NAME        = "A__ProductName"
COL_IMG_URL     = "U__Img_URL"
COL_EPD_URL     = "E__EPD_URL"
COL_EPD_REGNUM  = "E__EPD_RegNumber"  # used to key/dedup EPD PDF filenames (see download_media_deduped)
COL_EPD_DECNUM  = "E__EPD_DecNumber"  # ditto — declaration number, used when reg number is absent
COL_TECH_URL    = "U__TechDetails_URL"
COL_VOC_URL     = "VO__VOC_URL"      # VOC certificate primary URL
COL_VOC_URL_ALT = "U__VOC_URL"      # VOC certificate alternate URL
COL_VOC_CERT    = "VO__VOC_Cert"     # scheme label hint (M1 / Indoor Air Comfort Gold / etc.)
COL_MAP_YN      = "A__Map_yn"       # filter: only "Y" rows go into parquet
COL_MANUFACTURER   = "A__Manufacturer"
COL_PRODUCT_TYPE   = "D__ProductType_ENG"

# ── VOC "not relevant" markers (enter any of these in V__VOC_Cert in Excel) ───
# Products where VOC classification genuinely doesn't apply (stone, metal, glass…)
# get status "not_applicable" instead of "no_url" so gaps are clearly intentional.
# Note: these values survive normalize_for_parquet (not in missing_tokens).
_NOT_APPLICABLE_VOC: frozenset[str] = frozenset({
    "n/r", "nr", "n.r.", "n/a", "na", "n.a.",
    "not relevant", "not applicable", "non pertinente",
    "nicht relevant", "non applicable",
})

# ── Product types where VOC inherently does not apply ─────────────────────────
# When V__VOC_Cert is blank AND V__VOC_URL is absent AND the product type is in
# this set, the pipeline auto-assigns "not_applicable" without requiring manual
# n/r entries in the Excel.
# Rule: add here only if NO product in that category can ever carry an indoor-air
# or emission certificate (pure inorganic / structural materials).
_PRODUCT_TYPES_NO_VOC: frozenset[str] = frozenset({
    # Cement / binders
    "Binder (Cement)",
    "Cement",
    # Structural steel
    "Rebar",
    "Coil",
    # Metal components
    "Metal accessories",
    "Cable trays",
    "Framing profiles (Cladding/stud frame)",
    "Building fasteners",
    "Structural accessories",
    "Structural components",
})

# ── output columns: local file paths (relative to project root) ───────────────
# Many rows can share the same local path when they share a URL.
# Files are named by sha256(url)[:16] + ext so each unique URL maps to one file.
COL_IMG_LOCAL  = "U__Img_Local"           # e.g. data/img/a3b4c5d6e7f80912.jpg
COL_EPD_LOCAL  = "E__EPD_Local"           # e.g. data/pdf/a3b4c5d6e7f80912.pdf
COL_TECH_LOCAL = "U__TechDetails_Local"   # e.g. data/pdf/b4d2e1f3ab012345.pdf
COL_VOC_LOCAL  = "VO__VOC_Local"           # e.g. 01_data/pdf/c5e3f2a1b8901234.pdf
COL_VOC_LOCAL_ALT = "U__VOC_Local_alt"    # e.g. 01_data/pdf/d6f4e3b2a9012345.pdf

# ── output columns: VOC parsing results ──────────────────────────────────────
COL_VOC_CERT_NUMBER  = "VO__VOC_Cert_Number"
COL_VOC_CERT_EXPIRY  = "VO__VOC_Cert_Expiry"
COL_VOC_PARSE_STATUS = "VO__VOC_Cert_Parse_Status"  # ok/no_url/no_file/no_text/parse_failed


# ===== HELPERS ================================================================

def normalize_for_parquet(df: pd.DataFrame, threshold: float = 0.85) -> pd.DataFrame:
    """
    Fix mixed-type 'object' columns so pyarrow can write Parquet without errors.
    - Columns that are mostly numeric → Float64 (nullable)
    - Everything else               → string
    """
    out = df.copy()
    # IMPORTANT: do NOT add "n/r", "nr", "not relevant" etc. here — those are
    # intentional VOC "not applicable" markers read by extract_voc_cert_data.
    missing_tokens = {
        "": None, " ": None, "-": None, "–": None, "—": None,
        "n/a": None, "N/A": None, "na": None, "NA": None,
        "null": None, "NULL": None, "None": None,
    }
    assert "n/r" not in missing_tokens, "n/r must not be treated as missing"
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            continue
        if s.dtype != "object":
            continue
        try:
            s = s.replace(missing_tokens)
        except Exception:
            pass
        s = s.map(lambda x: x.strip() if isinstance(x, str) else x)
        s_num = s.map(lambda x: x.replace(",", ".") if isinstance(x, str) else x)
        numeric = pd.to_numeric(s_num, errors="coerce")
        non_null  = s.notna().sum()
        ok        = numeric.notna().sum()
        if non_null > 0 and (ok / non_null) >= threshold:
            out[col] = numeric.astype("Float64")
        else:
            out[col] = s.astype("string")
    return out


def make_media_filename(eetra_id: str, product_name: str, ext: str) -> str:
    """e.g. make_media_filename("EETRA-0042", "Multipor WI (Ytong)", "_VOC.pdf")
           → "EETRA-0042_Multipor-WI-Ytong_VOC.pdf"
    """
    slug = re.sub(r"[^\w\s-]", "", product_name)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-{2,}", "-", slug)
    return f"{eetra_id}_{slug}{ext.lower()}"


def _ext_from_url(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    ext  = pathlib.Path(path).suffix.lower()
    return ext if len(ext) <= 5 else ""


_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
}


def _origin_from_url(url: str) -> str:
    """Return scheme+host, e.g. 'https://www.british-gypsum.com'."""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def _resize_image_bytes(content: bytes, max_dimension: int = IMG_MAX_DIMENSION) -> bytes:
    """Downscale image bytes so neither side exceeds max_dimension (LANCZOS resample).

    Returns the original bytes unchanged if Pillow is unavailable, the image is
    already within bounds, or it can't be parsed as an image.
    """
    if not _HAS_PIL:
        return content
    try:
        img = _Image.open(BytesIO(content))
        img.load()
    except Exception:
        return content
    width, height = img.size
    if max(width, height) <= max_dimension:
        return content
    fmt = (img.format or "JPEG").upper()
    img.thumbnail((max_dimension, max_dimension), _Image.LANCZOS)
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = BytesIO()
    try:
        img.save(buf, format=fmt)
    except Exception:
        return content
    return buf.getvalue()


def download_url(url: str, dest: pathlib.Path, overwrite: bool = False, is_image: bool = False) -> str:
    """Download url to dest with SSL fallback and 403-referer retry.

    Images (is_image=True) are downscaled to IMG_MAX_DIMENSION before writing.

    Returns: 'ok' | 'skipped' | '403' | '404' | 'error'
    """
    if dest.exists() and not overwrite:
        return "skipped"

    def _get(headers, verify):
        return _requests.get(url, headers=headers, timeout=30, verify=verify)

    try:
        try:
            resp = _get(_DOWNLOAD_HEADERS, verify=True)
        except _requests.exceptions.SSLError:
            resp = _get(_DOWNLOAD_HEADERS, verify=False)

        # 403: retry with Referer + Accept set to browser-like values
        if resp.status_code == 403:
            referer_headers = {
                **_DOWNLOAD_HEADERS,
                "Referer": _origin_from_url(url) + "/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            try:
                resp = _get(referer_headers, verify=True)
            except _requests.exceptions.SSLError:
                resp = _get(referer_headers, verify=False)

        if resp.status_code == 200:
            content = _resize_image_bytes(resp.content) if is_image else resp.content
            dest.write_bytes(content)
            return "ok"
        if resp.status_code == 403:
            return "403"
        if resp.status_code == 404:
            return "404"
        print(f"  ⚠️  {dest.name}: HTTP {resp.status_code}")
        return "error"
    except Exception as exc:
        print(f"  ⚠️  {dest.name}: {exc}")
        return "error"


def _str(val) -> str:
    return "" if pd.isna(val) else str(val).strip()


def _url_to_local_filename(url: str, is_pdf: bool, prefix: str = "") -> str:
    """Deterministic filename for a URL: <prefix>sha256(url)[:16] + extension.

    The same URL always maps to the same filename regardless of which product
    references it — so shared certificates are stored exactly once on disk.

    ``prefix`` (e.g. "tech_", "voc_") makes the document type readable from
    the filename alone — 01_data/pdf mixes EPDs (already keyed by their own
    dec_/reg_ number), technical sheets, and VOC certs in one flat folder;
    see 04_tools/08_build_pdf_manifest.py and 04_tools/09_migrate_pdf_prefixes.py.
    """
    h   = hashlib.sha256(url.encode()).hexdigest()[:16]
    ext = _ext_from_url(url) or (".pdf" if is_pdf else ".jpg")
    return f"{prefix}{h}{ext}"


_EPD_NUM_UNSAFE_RE = re.compile(r"[^A-Z0-9\-]+")


def norm_epd_num_for_filename(raw) -> str | None:
    """Normalise an EPD registration/declaration number into a filesystem-safe
    token. Same normalisation spirit as libs.lib_data.fn141_norm_epd_num
    (colons/dots/whitespace → '-', upper-cased) plus stripping of any
    character that isn't safe in a Windows/Unix filename.

    Examples: "EPD-IES-0006430:002" → "EPD-IES-0006430-002"
              "S-P-06430"           → "S-P-06430"
              "*", "-", "", NaN     → None
    """
    try:
        if raw is None or pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    text = str(raw).strip()
    if not text or text in ("*", "-", "—", "–") or len(text) > 60:
        return None
    if not re.search(r"\d", text):
        return None
    text = re.sub(r"[\s:\.]+", "-", text.upper())
    text = _EPD_NUM_UNSAFE_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or None


def epd_key_filename(dec: str | None, reg: str | None, ext: str) -> str | None:
    """Build ``dec_<DEC>__reg_<REG><ext>`` from whichever EPD number(s) are
    present (either alone is fine). Returns None if both are missing, so the
    caller can fall back to the URL-hash scheme."""
    parts = []
    if dec:
        parts.append(f"dec_{dec}")
    if reg:
        parts.append(f"reg_{reg}")
    if not parts:
        return None
    return "__".join(parts) + ext.lower()


# (url_column, local_path_column, is_pdf, filename_prefix)
# EPD PDFs never get a hash-based filename (see _build_epd_url_dest — they're
# keyed by their own dec_/reg_ number instead), so EPD's prefix here is unused.
_URL_COLS: list[tuple[str, str, bool, str]] = [
    (COL_IMG_URL,     COL_IMG_LOCAL,     False, ""),
    (COL_EPD_URL,     COL_EPD_LOCAL,     True,  ""),
    (COL_TECH_URL,    COL_TECH_LOCAL,    True,  "tech_"),
    (COL_VOC_URL,     COL_VOC_LOCAL,     True,  "voc_"),
    (COL_VOC_URL_ALT, COL_VOC_LOCAL_ALT, True,  "voc_"),
]


def _build_epd_url_dest(df: pd.DataFrame, pdf_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    """{EPD url: dest} keyed by the EPD's own reg/declaration number, not the URL.

    Two rows can cite the *same* EPD via *different* URLs (manufacturer mirror
    vs. registry link). A pure URL-hash scheme would store — and re-download —
    that document twice. Here every unique URL is first matched to whichever
    reg/declaration number is found on a row that references it (first valid
    one wins), then all URLs sharing that same number collapse onto one dest
    file. URLs with no usable number fall back to the URL-hash filename.
    """
    if COL_EPD_URL not in df.columns:
        return {}
    has_reg = COL_EPD_REGNUM in df.columns
    has_dec = COL_EPD_DECNUM in df.columns

    # 1) One (dec, reg) candidate per unique EPD URL.
    url_ids: dict[str, tuple[str | None, str | None]] = {}
    for _, row in df.iterrows():
        url = _str(row.get(COL_EPD_URL, ""))
        if not url.startswith("http"):
            continue
        if url in url_ids and any(url_ids[url]):
            continue  # already have a usable id for this URL
        dec = norm_epd_num_for_filename(row.get(COL_EPD_DECNUM)) if has_dec else None
        reg = norm_epd_num_for_filename(row.get(COL_EPD_REGNUM)) if has_reg else None
        url_ids[url] = (dec, reg)

    # 2) Group URLs by their PRIMARY identifier: registration number when
    #    present, else declaration number, else no grouping (hash fallback).
    #    Keying on reg-alone (rather than the (dec, reg) pair) matters because
    #    two rows for the same EPD don't always carry the same completeness —
    #    e.g. one row has both numbers, another only has the reg number — and
    #    an exact-pair key would wrongly treat those as two different EPDs.
    group_key_of_url: dict[str, tuple[str, str]] = {}
    for url, (dec, reg) in url_ids.items():
        if reg:
            group_key_of_url[url] = ("R", reg)
        elif dec:
            group_key_of_url[url] = ("D", dec)
        # else: no usable number for this URL — stays out, hash fallback below.

    # 3) Within each group, union the most complete (dec, reg) pair seen across
    #    its member URLs, so the filename is as informative as possible even if
    #    no single row carried both numbers.
    group_urls: dict[tuple[str, str], list[str]] = {}
    for url, key in group_key_of_url.items():
        group_urls.setdefault(key, []).append(url)

    epd_dest_by_key: dict[tuple[str, str], pathlib.Path] = {}
    url_dest: dict[str, pathlib.Path] = {}
    for key, urls in group_urls.items():
        best_dec = next((url_ids[u][0] for u in urls if url_ids[u][0]), None)
        best_reg = next((url_ids[u][1] for u in urls if url_ids[u][1]), None)
        ext = _ext_from_url(urls[0]) or ".pdf"
        key_name = epd_key_filename(best_dec, best_reg, ext)
        dest = epd_dest_by_key.setdefault(key, pdf_dir / key_name)
        for u in urls:
            url_dest[u] = dest

    # 4) URLs with no usable EPD number at all: fall back to the URL hash.
    for url, (dec, reg) in url_ids.items():
        if url not in url_dest:
            url_dest[url] = pdf_dir / _url_to_local_filename(url, is_pdf=True)

    return url_dest


def download_media_deduped(
    df: pd.DataFrame,
    img_dir: pathlib.Path,
    pdf_dir: pathlib.Path,
    overwrite: bool = False,
) -> dict[str, pathlib.Path]:
    """Download every unique document once; return {url: local_dest_path}.

    Many product rows may share the same document. Images, technical sheets
    and VOC certificates are deduplicated by URL (sha256(url)[:16] filename).
    EPD PDFs are deduplicated by the EPD's own registration/declaration
    number instead — see _build_epd_url_dest() — because the same EPD can be
    referenced through more than one URL.
    """
    img_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # EPD PDFs: keyed by EPD number (falls back to URL hash internally).
    url_dest: dict[str, pathlib.Path] = _build_epd_url_dest(df, pdf_dir)

    # Everything else: hash-by-URL, same as before.
    for url_col, _local_col, is_pdf, prefix in _URL_COLS:
        if url_col == COL_EPD_URL or url_col not in df.columns:
            continue
        for raw in df[url_col].dropna().unique():
            url = str(raw).strip()
            if not url.startswith("http") or url in url_dest:
                continue
            filename = _url_to_local_filename(url, is_pdf, prefix)
            url_dest[url] = (pdf_dir if is_pdf else img_dir) / filename

    # Download each unique URL exactly once (multiple URLs sharing an EPD dest
    # will download on the first one and skip on the rest, since download_url()
    # returns "skipped" once dest.exists()).
    counts: dict[str, int] = {"ok": 0, "skipped": 0, "403": 0, "404": 0, "error": 0}
    blocked_domains: set[str] = set()

    unique_total = len(url_dest)
    unique_files = len(set(url_dest.values()))
    for url, dest in url_dest.items():
        status = download_url(url, dest, overwrite=overwrite, is_image=(dest.parent == img_dir))
        counts[status] = counts.get(status, 0) + 1
        if status == "403":
            blocked_domains.add(_origin_from_url(url))

    ok      = counts["ok"]
    skipped = counts["skipped"]
    f403    = counts["403"]
    f404    = counts["404"]
    ferr    = counts["error"]
    dedup_note = f" ({unique_total - unique_files} URL(s) collapsed onto a shared file)" if unique_total > unique_files else ""
    print(
        f"  Media: {unique_total} unique URLs → {unique_files} unique files{dedup_note} → "
        f"{ok} downloaded, {skipped} already existed"
        + (f", {f403} blocked (403)" if f403 else "")
        + (f", {f404} not found (404)" if f404 else "")
        + (f", {ferr} other errors" if ferr else "")
    )
    if blocked_domains:
        print(f"  Blocked domains (403): {', '.join(sorted(blocked_domains))}")

    return url_dest


def assign_local_path_columns(
    df: pd.DataFrame,
    url_dest: dict[str, pathlib.Path],
    project_root: pathlib.Path,
) -> pd.DataFrame:
    """Add *_Local columns to df: relative path to the local file for each URL.

    Rows that share the same URL get the same local path. Rows with no URL or
    a failed download get None.
    """
    out = df.copy()
    for url_col, local_col, _is_pdf, _prefix in _URL_COLS:
        def _resolve(url_raw, _ud=url_dest, _root=project_root):
            if pd.isna(url_raw):
                return None
            url = str(url_raw).strip()
            dest = _ud.get(url)
            if dest and dest.exists():
                try:
                    return str(dest.relative_to(_root))
                except ValueError:
                    return str(dest)
            return None
        col_vals = df[url_col].map(_resolve) if url_col in df.columns else pd.Series([None] * len(df))
        out[local_col] = pd.array(col_vals.tolist(), dtype="string")
    return out


# ===== VOC CERTIFICATE PARSING ================================================
#
# Delegates PDF parsing to libs.lib_voc_extractor (deterministic regex first,
# Claude text/vision fallback for whatever regex can't find — see that module
# for the extraction strategy). This section only handles the dataframe
# plumbing: fan a single per-file result out to every row that references it.

from libs.lib_voc_extractor import extract_voc, estimate_cost as _voc_estimate_cost


def resolve_anthropic_api_key() -> tuple[str | None, str | None]:
    """Look for an Anthropic API key in env, .streamlit/secrets.toml, then 01_data/.env.

    Returns (key, source) — source is one of "environment", "secrets.toml",
    "01_data/.env", or (None, None) if nothing was found.
    """
    env = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if env:
        return env, "environment"

    root = pathlib.Path(__file__).resolve().parent.parent
    secrets_path = root / ".streamlit" / "secrets.toml"
    if secrets_path.is_file():
        try:
            import tomllib
            with open(secrets_path, "rb") as f:
                data = tomllib.load(f)
            key = (data.get("anthropic", {}) or {}).get("api_key")
            if key:
                return str(key).strip(), "secrets.toml"
        except Exception:
            pass

    env_file = root / "01_data" / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        return key, "01_data/.env"
        except Exception:
            pass

    return None, None


def extract_voc_cert_data(
    df: pd.DataFrame,
    project_root: pathlib.Path,
    reparse: bool = False,
    client=None,
) -> pd.DataFrame:
    """Parse VOC certificates — one parse per unique PDF, not one per row.

    Uses V__VOC_Local (and U__VOC_Local_alt) columns populated by
    assign_local_path_columns(). Adds three columns:
        V__VOC_Cert_Number      – certificate / registration number
        V__VOC_Cert_Expiry      – expiry date as ISO YYYY-MM-DD
        V__VOC_Cert_Parse_Status – ok / no_url / no_file / no_text / parse_failed

    ``client``: an anthropic.Anthropic instance, or None to run deterministic
    regex only (no API calls, no cost).
    """
    has_existing = (
        not reparse
        and COL_VOC_CERT_NUMBER in df.columns
        and COL_VOC_CERT_EXPIRY in df.columns
    )

    # ── Step 1: classify every row WITHOUT touching the PDF yet ────────────────
    # A row is either resolved here (not_applicable / no_url / carried-forward
    # from an existing parse) or left "pending" — only pending rows' PDFs get
    # parsed below. This matters now that parsing can cost real API calls: we
    # must not re-run Claude on certs that already have a good result on disk.
    row_classification: list[tuple[str, str | None, str | None] | None] = []
    # None => pending (needs PDF lookup); else (status, cert, expiry) already final.
    pending_path_hint: dict[str, str] = {}   # local_path_str -> scheme_hint

    for _, row in df.iterrows():
        has_url = bool(_str(row.get(COL_VOC_URL, "")))
        scheme_label  = _str(row.get(COL_VOC_CERT, ""))
        product_type  = _str(row.get(COL_PRODUCT_TYPE, ""))

        if scheme_label.lower() in _NOT_APPLICABLE_VOC:
            row_classification.append(("not_applicable", None, None))
            continue
        if not has_url and not scheme_label and product_type in _PRODUCT_TYPES_NO_VOC:
            row_classification.append(("not_applicable", None, None))
            continue
        if not has_url:
            row_classification.append(("no_url", None, None))
            continue

        if has_existing:
            existing_num = _str(row.get(COL_VOC_CERT_NUMBER, ""))
            existing_exp = _str(row.get(COL_VOC_CERT_EXPIRY, ""))
            if existing_num or existing_exp:
                row_classification.append(("ok", existing_num or None, existing_exp or None))
                continue

        row_classification.append(None)  # pending — needs PDF result
        for local_col in (COL_VOC_LOCAL, COL_VOC_LOCAL_ALT):
            local = _str(row.get(local_col, ""))
            if local and local not in pending_path_hint:
                pending_path_hint[local] = scheme_label.lower()

    # ── Step 2: parse only the PDFs still needed (once per unique path) ───────
    path_to_result: dict[str, dict] = {}
    total_input_tokens = total_output_tokens = 0
    claude_calls = 0
    for local_path_str, hint in pending_path_hint.items():
        pdf_path = project_root / local_path_str
        result = extract_voc(pdf_path, client=client, scheme_hint=hint)
        path_to_result[local_path_str] = result
        if result.get("_mode") not in ("deterministic", "none"):
            claude_calls += 1
        total_input_tokens += result.get("_input_tokens", 0)
        total_output_tokens += result.get("_output_tokens", 0)

    parsed = no_file = no_text = parse_failed_count = skipped = 0
    unique_pdfs = len(path_to_result)

    # ── Step 3: fan results out to every row ──────────────────────────────────
    cert_numbers: list[str | None] = []
    cert_expiries: list[str | None] = []
    parse_statuses: list[str | None] = []

    for (_, row), classified in zip(df.iterrows(), row_classification):
        if classified is not None:
            status, num, exp = classified
            cert_numbers.append(num)
            cert_expiries.append(exp)
            parse_statuses.append(status)
            if status in ("not_applicable", "no_url"):
                skipped += 1
            else:
                parsed += 1
            continue

        # Find the best result among primary and alt PDFs
        result = None
        for local_col in (COL_VOC_LOCAL, COL_VOC_LOCAL_ALT):
            local = _str(row.get(local_col, ""))
            if not local:
                continue
            r = path_to_result.get(local)
            if r is None:
                continue
            if result is None:
                result = r
            if r.get("cert_number") or r.get("expiry_date"):
                result = r
                break

        if result is None:
            cert_numbers.append(None)
            cert_expiries.append(None)
            parse_statuses.append("no_file")
            no_file += 1
        elif result.get("_mode") == "none" and not (result.get("cert_number") or result.get("expiry_date")):
            cert_numbers.append(None)
            cert_expiries.append(None)
            parse_statuses.append("no_text")
            no_text += 1
        elif result.get("cert_number") or result.get("expiry_date"):
            cert_numbers.append(result["cert_number"])
            cert_expiries.append(result["expiry_date"])
            parse_statuses.append("ok")
            parsed += 1
        else:
            cert_numbers.append(None)
            cert_expiries.append(None)
            parse_statuses.append("parse_failed")
            parse_failed_count += 1

    out = df.copy()
    out[COL_VOC_CERT_NUMBER]  = pd.array(cert_numbers,   dtype="string")
    out[COL_VOC_CERT_EXPIRY]  = pd.array(cert_expiries,  dtype="string")
    out[COL_VOC_PARSE_STATUS] = pd.array(parse_statuses, dtype="string")

    total = len(df)
    cost_note = ""
    if claude_calls:
        cost = _voc_estimate_cost(total_input_tokens, total_output_tokens)
        cost_note = f", {claude_calls} via Claude API (~${cost:.4f} USD)"
    print(
        f"  VOC certs: {unique_pdfs} unique PDFs parsed → "
        f"{parsed} rows ok, {parse_failed_count} parse_failed, "
        f"{no_file} no_file, {no_text} no_text, {skipped} skipped (no URL) "
        f"of {total} rows{cost_note}"
    )
    return out


# ===== PIPELINE SUMMARY =======================================================

# Status display order and short labels for the breakdown tables
_STATUS_ORDER = ["ok", "parse_failed", "no_file", "no_text", "no_url", "not_applicable"]
_STATUS_LABEL = {
    "ok":             "ok",
    "parse_failed":   "parse_fail",
    "no_file":        "no_file",
    "no_text":        "no_text",
    "no_url":         "no_url",
    "not_applicable": "n/r",
}


def _fmt_row(label: str, counts: dict, col_w: int, status_cols: list[str]) -> str:
    parts = [f"  {label:<{col_w}}"]
    for s in status_cols:
        n = counts.get(s, 0)
        parts.append(f"  {n:>5}" if n else "      -")
    return "".join(parts)


def print_pipeline_summary(df: pd.DataFrame, top_n_manufacturers: int = 30) -> None:
    """Print VOC parse-status breakdown by product type and manufacturer."""
    if COL_VOC_PARSE_STATUS not in df.columns:
        return

    # Which statuses actually appear in this run (keep order stable)
    present = [s for s in _STATUS_ORDER if s in df[COL_VOC_PARSE_STATUS].values]
    headers = [_STATUS_LABEL[s] for s in present]
    total_col = "total"

    def _section(group_col: str, title: str, limit: int | None = None) -> None:
        if group_col not in df.columns:
            print(f"\n  (column '{group_col}' not found — skipping {title})\n")
            return

        grp = (
            df.groupby(group_col, dropna=False)[COL_VOC_PARSE_STATUS]
            .value_counts()
            .unstack(fill_value=0)
        )
        # Sort by rows with most actionable gaps (no_file + no_url) descending
        gap_cols = [c for c in ("no_file", "no_url") if c in grp.columns]
        grp["_gap"] = grp[gap_cols].sum(axis=1) if gap_cols else 0
        grp = grp.sort_values("_gap", ascending=False).drop(columns="_gap")

        if limit:
            grp = grp.head(limit)

        col_w = max(len(str(v)) for v in grp.index) + 2
        col_w = max(col_w, 28)

        # Header
        print(f"\n{'─' * 60}")
        print(f"  {title}")
        print(f"{'─' * 60}")
        hdr_parts = [f"  {'':>{col_w}}"] + [f"  {h:>10}" for h in headers] + [f"  {'total':>6}"]
        print("".join(hdr_parts))
        print(f"  {'─' * (col_w + len(present) * 12 + 8)}")

        for name, row_s in grp.iterrows():
            counts = {s: int(row_s.get(s, 0)) for s in present}
            total  = sum(counts.values())
            parts  = [f"  {str(name):<{col_w}}"]
            for s in present:
                n = counts.get(s, 0)
                parts.append(f"  {n:>10}" if n else f"  {'-':>10}")
            parts.append(f"  {total:>6}")
            print("".join(parts))

    print("\n" + "═" * 60)
    print("  VOC certificate status breakdown")
    print("═" * 60)
    print(
        "  Statuses: ok=parsed successfully  parse_fail=PDF found but no data extracted\n"
        "            no_file=URL exists but PDF not downloaded (403/404?)\n"
        "            no_url=no certificate URL in Excel\n"
        "            n/r=marked not relevant in Excel  no_text=image-only PDF"
    )

    _section(COL_PRODUCT_TYPE,  "By product type  (D__ProductType_ENG)")
    _section(COL_MANUFACTURER,  f"By manufacturer  (top {top_n_manufacturers} by gap)", limit=top_n_manufacturers)

    print("\n" + "═" * 60 + "\n")


# ===== LOAD DATA ==============================================================

def load_live_data_from_excel(excel_path: str, sheet_name: str) -> pd.DataFrame:
    print(f"Loading from Excel: {excel_path}")
    return pd.read_excel(excel_path, sheet_name=sheet_name)


def load_live_data_from_sharepoint(sheet_name: str) -> pd.DataFrame:
    """Fallback: load via SharePoint Graph API (requires streamlit secrets)."""
    from libs.lib_data import fn103_load_from_sharepoint
    import streamlit as st
    sp = st.secrets["sharepoint"]
    return fn103_load_from_sharepoint(
        tenant_id=sp["tenant_id"],
        client_id=sp["client_id"],
        client_secret=sp["client_secret"],
        site_hostname="eetra.sharepoint.com",
        site_path="/sites/res",
        document_library="Documenti",
        file_path=sp["file_relative_url"],
        sheet_name=sheet_name,
    )


# ===== LOGGING ================================================================

class _Tee:
    """Write every print() to both stdout and a log file simultaneously."""

    def __init__(self, log_path: pathlib.Path):
        import sys as _sys
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file   = open(log_path, "w", encoding="utf-8", buffering=1)
        self._stdout = _sys.stdout
        _sys.stdout  = self

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        import sys as _sys
        _sys.stdout = self._stdout
        self._file.close()


_LOG_DIR  = pathlib.Path(__file__).resolve().parent.parent / "logs"
_LOG_PATH = _LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_tee      = _Tee(_LOG_PATH)
print(f"Log → {_LOG_PATH}")


# ===== MAIN ===================================================================

_ap = argparse.ArgumentParser(description="Excel/SharePoint → Parquet pipeline")
_ap.add_argument(
    "--reparse-voc",
    action="store_true",
    help="Re-parse all VOC PDFs even if V__VOC_Cert_Number/Expiry already populated",
)
_ap.add_argument(
    "--no-download",
    action="store_true",
    help="Skip media download step (useful when re-running parse only)",
)
_ap.add_argument(
    "--no-claude-voc",
    action="store_true",
    help="Disable Claude API fallback for VOC certs — deterministic regex only, $0 cost",
)
_args = _ap.parse_args()

# ── 1. Load ──────────────────────────────────────────────────────────────────
df: pd.DataFrame | None = None

if EXCEL_PATH:
    if os.path.exists(EXCEL_PATH):
        df = load_live_data_from_excel(EXCEL_PATH, SHEET_NAME)
    else:
        print(f"Excel not found: {EXCEL_PATH}")
        sys.exit(1)
else:
    try:
        df = load_live_data_from_sharepoint(SHEET_NAME)
        print("Loaded from SharePoint.")
    except Exception as exc:
        print(f"SharePoint load failed: {exc}")
        sys.exit(1)

# ── 1b. Filter to mapped products only (A__Map_yn == "Y") ────────────────────
if COL_MAP_YN in df.columns:
    _before = len(df)
    mask = df[COL_MAP_YN].astype(str).str.strip().str.upper() == "Y"
    df = df[mask].reset_index(drop=True)
    print(f"Filtered A__Map_yn == 'Y': {len(df):,} rows (dropped {_before - len(df):,})")
else:
    print(f"⚠️  Column '{COL_MAP_YN}' not found — no filter applied ({len(df):,} rows)")

from libs.lib_data import apply_sharepoint_v_column_renames

df = apply_sharepoint_v_column_renames(df)

# ── 2. Normalise dtypes ───────────────────────────────────────────────────────
print("Normalising dtypes for Parquet…")
df = normalize_for_parquet(df, threshold=NUMERIC_SUCCESS_THRESHOLD)

# ── 3. Download media (images + PDFs incl. VOC certs) ────────────────────────
_root    = pathlib.Path(__file__).resolve().parent.parent
_img_dir = _root / DATA_IMG_SUBDIR
_pdf_dir = _root / DATA_PDF_SUBDIR

_do_download = DOWNLOAD_MEDIA and not _args.no_download
_url_dest: dict[str, pathlib.Path] = {}

if _do_download:
    print(f"Downloading images → {_img_dir}")
    print(f"Downloading PDFs   → {_pdf_dir}")
    _url_dest = download_media_deduped(df, _img_dir, _pdf_dir, overwrite=OVERWRITE_MEDIA)
else:
    reason = "DOWNLOAD_MEDIA=False" if not DOWNLOAD_MEDIA else "--no-download flag"
    print(f"Skipping media download ({reason}).")
    # Still build the map from already-existing files so *_Local columns are populated.
    # EPD PDFs must go through _build_epd_url_dest() — they're keyed by the EPD's own
    # reg/declaration number (dec_X__reg_Y.pdf), not a hash of the URL — otherwise every
    # E__EPD_Local value resolves to a filename that doesn't exist and comes back None.
    _url_dest = _build_epd_url_dest(df, _pdf_dir)
    for url_col, _local_col, is_pdf, prefix in _URL_COLS:
        if url_col == COL_EPD_URL or url_col not in df.columns:
            continue
        for raw in df[url_col].dropna().unique():
            url = str(raw).strip()
            if not url.startswith("http") or url in _url_dest:
                continue
            filename = _url_to_local_filename(url, is_pdf, prefix)
            dest = (_pdf_dir if is_pdf else _img_dir) / filename
            _url_dest[url] = dest

# ── 3b. Add *_Local path columns to dataframe ─────────────────────────────────
print("Assigning local path columns…")
df = assign_local_path_columns(df, _url_dest, _root)

# ── 4. Parse VOC certificates (once per unique PDF) ───────────────────────────
if not _HAS_FITZ:
    print("⚠️  PyMuPDF (fitz) not installed. VOC cert parsing skipped.")
else:
    _voc_client = None
    if _args.no_claude_voc:
        print("Parsing VOC certificate PDFs (deterministic regex only, --no-claude-voc)…")
    else:
        _voc_key, _voc_key_src = resolve_anthropic_api_key()
        if _voc_key:
            import anthropic
            _voc_client = anthropic.Anthropic(api_key=_voc_key)
            print(f"Parsing VOC certificate PDFs (Claude fallback enabled, key from {_voc_key_src})…")
        else:
            print(
                "Parsing VOC certificate PDFs (deterministic regex only — no Anthropic API key found; "
                "set ANTHROPIC_API_KEY, [anthropic] api_key in secrets.toml, or 01_data/.env)…"
            )
    df = extract_voc_cert_data(df, _root, reparse=_args.reparse_voc, client=_voc_client)

# ── 4b. Material-type label renames (the workbook still carries the old wording) ─
_MATERIAL_TYPE_RENAMES = {
    "Mineral wool (Stone wool, Rock wool)": "Mineral wool (Stone, Rock)",
}
if "D__MaterialType_ENG" in df.columns:
    df["D__MaterialType_ENG"] = df["D__MaterialType_ENG"].replace(_MATERIAL_TYPE_RENAMES)

# ── 5. Write base Parquet (root + 01_data/ copy) ─────────────────────────────
PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
print(f"Writing base Parquet → {PARQUET_PATH}")
df.to_parquet(PARQUET_PATH, index=False)

print(f"Done. {len(df):,} base rows written.")

# ── 5b. Report what the refresh means for existing app edits ─────────────────
# The app's Add/Edit page only ever appends to edits_data.parquet, so nothing is
# lost on a refresh: the log is replayed over the new base every time the app
# reads the data. Nothing is written here — the merge used to be materialised to
# live_data.parquet for modules that read it directly, and those now derive it.
from libs.lib_data import (
    fn155_load_edits_dataframe as _load_edits,
    fn157_merge_base_and_edits as _merge_base_edits,
)

_edits = _load_edits(EDITS_PATH)
if _edits.empty:
    print(f"No app edits in {EDITS_PATH.name} — effective dataset = base.")
else:
    _merged = _merge_base_edits(df, _edits)
    _n_ids = _edits["0__EETRA_ID"].nunique() if "0__EETRA_ID" in _edits.columns else 0
    print(
        f"{len(_edits):,} edit record(s) over {_n_ids:,} product(s) in "
        f"{EDITS_PATH.name} will replay over this base "
        f"({len(_merged):,} effective rows)."
    )

# ── Summary ───────────────────────────────────────────────────────────────────
if COL_VOC_PARSE_STATUS in df.columns:
    _counts = df[COL_VOC_PARSE_STATUS].value_counts(dropna=False)
    print("\nVOC parse status summary (totals):")
    for _status, _n in _counts.items():
        print(f"  {str(_status):<20} {_n:>5}")

print_pipeline_summary(df)

print(f"\nLog saved → {_LOG_PATH}")
_tee.close()


# =============================================================================
# ── MotherDuck upload (disabled) ─────────────────────────────────────────────
# =============================================================================
# import duckdb, os
#
# MD_DB    = "eetra_matlib"
# MD_TABLE = "live_data"
#
# token = os.getenv("MOTHERDUCK_TOKEN")
# if not token:
#     import tomllib
#     _sp = pathlib.Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
#     with open(_sp, "rb") as _f:
#         token = tomllib.load(_f).get("motherduck", {}).get("token")
# if not token:
#     raise RuntimeError("Missing MOTHERDUCK_TOKEN")
#
# token = token.strip().strip('"').strip("'")
# os.environ["motherduck_token"] = token
# os.environ["MOTHERDUCK_TOKEN"] = token
#
# con = duckdb.connect("md:")
# con.execute(f"CREATE DATABASE IF NOT EXISTS {MD_DB}")
# con.execute(f"USE {MD_DB}")
# con.execute(f"CREATE OR REPLACE TABLE {MD_TABLE} AS SELECT * FROM '{PARQUET_PATH}'")
# rows = con.execute(f"SELECT COUNT(*) FROM {MD_TABLE}").fetchone()[0]
# print(f"Uploaded to MotherDuck: md:{MD_DB}.{MD_TABLE} ({rows:,} rows)")
# con.close()
