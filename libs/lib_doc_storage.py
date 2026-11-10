"""
libs/lib_doc_storage.py — remote bucket access for documents and product images
===============================================================================
Public-bucket backends for the ~1.28 GB this app would otherwise have to carry
locally: the documents under ``01_data/pdf`` (905 files — EPDs, VOC
certificates, technical sheets) and the product-image originals under
``01_data/img`` (552 files). Two providers are supported, Cloudflare R2 and
Supabase Storage, tried in ``provider_order``; R2 alone is configured, because
its free tier is 10 GB with no egress charges while Supabase's is 1 GB (see
REMOTE_ASSET_STORAGE.md). Both are read via plain public HTTPS URLs — no
signing, no SDK needed at read time (uploading is a separate offline step, see
``04_tools/07_upload_pdfs_to_buckets.py``).

Configure in ``.streamlit/secrets.toml``:

    [doc_storage]
    enabled = false                       # flip to true once buckets are populated
    provider_order = ["supabase", "cloudflare_r2"]

    [supabase]
    url = "https://YOUR-PROJECT.supabase.co"
    bucket = "eetra-mat-lib"

    [cloudflare_r2]
    public_base_url = "https://pub-XXXXXXXX.r2.dev"   # or a custom domain bound to the bucket

Until ``[doc_storage] enabled`` is true (or the section is absent), every
function here is a no-op and the app behaves exactly as before — local-only.

Object keys are plain filenames — the same name the file has (or would have)
under ``01_data/pdf/``, whether hash-based (pipeline-written ``*_Local``
columns) or the legacy product-name convention. That way a bucket mirrors
the local folder 1:1 and one lookup key works for both.

Usage (remote-first, local-fallback):

    from libs.lib_doc_storage import fn_fetch_document_bytes
    data, source = fn_fetch_document_bytes(object_name, local_path)
    # source is one of: "supabase", "cloudflare_r2", "local", None
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import streamlit as st

_HTTP_TIMEOUT = 6  # seconds; buckets should respond fast, fail over quickly otherwise
_DEFAULT_PROVIDER_ORDER = ("supabase", "cloudflare_r2")


def _doc_storage_config() -> dict:
    try:
        return dict(st.secrets.get("doc_storage", {}))
    except Exception:
        return {}


def fn_storage_enabled() -> bool:
    return bool(_doc_storage_config().get("enabled", False))


def fn_provider_order() -> tuple[str, ...]:
    order = _doc_storage_config().get("provider_order")
    if not order:
        return _DEFAULT_PROVIDER_ORDER
    return tuple(str(p) for p in order)


def fn_supabase_public_url(object_name: str) -> Optional[str]:
    """Public Storage URL for an object in a public Supabase bucket."""
    try:
        cfg = st.secrets["supabase"]
        base = str(cfg["url"]).rstrip("/")
        bucket = str(cfg["bucket"])
    except Exception:
        return None
    if not base or not bucket or "YOUR-PROJECT" in base:
        return None
    return f"{base}/storage/v1/object/public/{bucket}/{object_name}"


def fn_cloudflare_r2_public_url(object_name: str) -> Optional[str]:
    """Public URL for an object in a public Cloudflare R2 bucket (r2.dev or custom domain)."""
    try:
        base = str(st.secrets["cloudflare_r2"]["public_base_url"]).rstrip("/")
    except Exception:
        return None
    if not base or "XXXXXXXX" in base:
        return None
    return f"{base}/{object_name}"


_URL_BUILDERS = {
    "supabase": fn_supabase_public_url,
    "cloudflare_r2": fn_cloudflare_r2_public_url,
}


def fn_remote_document_urls(object_name: Optional[str]) -> list[tuple[str, str]]:
    """[(provider_name, url), ...] for configured, enabled providers, in provider_order.
    Only includes providers whose secrets are actually filled in (no placeholders)."""
    if not fn_storage_enabled() or not object_name:
        return []
    out: list[tuple[str, str]] = []
    for provider in fn_provider_order():
        builder = _URL_BUILDERS.get(provider)
        if builder is None:
            continue
        url = builder(object_name)
        if url:
            out.append((provider, url))
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_http_get(url: str) -> Optional[bytes]:
    import requests

    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.content
    except requests.RequestException:
        pass
    return None


def fn_fetch_public_url_bytes(url: str) -> Optional[bytes]:
    """HTTP GET for a public document URL (cached). Returns None on failure."""
    u = str(url or "").strip()
    if not u:
        return None
    return _cached_http_get(u)


def fn_fetch_document_bytes(
    object_name: Optional[str],
    local_path: Optional[Path] = None,
) -> tuple[Optional[bytes], Optional[str]]:
    """Remote-first, local-fallback PDF fetch.

    Tries each enabled bucket provider in turn (public HTTPS GET, cached),
    then falls back to ``local_path`` on disk. Returns ``(bytes, source)``
    where source is the provider name, ``"local"``, or ``None`` if nothing
    was found anywhere. ``object_name`` is the bucket key / filename — see
    :func:`libs.lib_data.pdf_object_name_from_row`.
    """
    for provider, url in fn_remote_document_urls(object_name):
        data = _cached_http_get(url)
        if data:
            return data, provider
    if local_path is not None:
        try:
            return local_path.read_bytes(), "local"
        except OSError:
            pass
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT IMAGES — same buckets, ``img/`` prefix
# ══════════════════════════════════════════════════════════════════════════════
# The pipeline's image originals (``01_data/img/<sha256(url)[:16]>.<ext>``, 552
# files / ~52 MB) live in the SAME bucket as the PDFs, under an ``img/`` prefix,
# so one set of credentials and one public base URL cover both. Keys keep the
# local filename, exactly as documents do, so the bucket mirrors the folder 1:1.
#
# The tier ORDER differs from documents, deliberately. A document is fetched
# once, on demand, when the user opens the panel — remote-first costs nothing
# there and is what makes 01_data/pdf optional. An image is read on every
# catalogue render and the originals are already on disk, so the local tiers win
# and the bucket sits BETWEEN them and the live manufacturer fetch (see
# fn110_cached_fetch_image). That ordering is what turns the bucket into a
# link-rot backstop: a manufacturer reorganising its CDN no longer costs us the
# picture, and nothing gets slower while the local folder is intact.
#
# Resolving a key needs the extension, which the URL hash alone does not carry.
# Probing .jpg/.jpeg/.png/.webp/.gif over HTTP is up to five round trips per
# miss, and on a fresh checkout (no 01_data/img at all) EVERY image misses. So
# the uploader also writes ``img/_index.json`` — {sha256(url)[:16]: filename}
# for every original it uploads — and one cached fetch of that resolves all of
# them. A key the index does not know still falls back to probing, so an object
# dropped into the bucket by hand is found too, just more slowly.

IMG_OBJECT_PREFIX = "img/"
IMG_INDEX_OBJECT = "img/_index.json"
_IMG_PROBE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def fn_image_object_name(local_name) -> str:
    """Bucket key for a product-image original: ``img/<filename>``."""
    name = Path(str(local_name or "").replace("\\", "/")).name
    return f"{IMG_OBJECT_PREFIX}{name}" if name else ""


@st.cache_data(ttl=3600, show_spinner=False)
def fn_remote_image_index() -> dict:
    """``{sha256(url)[:16]: filename}`` from ``img/_index.json``; {} if absent."""
    if not fn_storage_enabled():
        return {}
    for _provider, url in fn_remote_document_urls(IMG_INDEX_OBJECT):
        data = _cached_http_get(url)
        if not data:
            continue
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    return {}


def fn_fetch_image_bytes(
    hash_key: str,
    *,
    ext_hint: str = "",
) -> tuple[Optional[bytes], Optional[str]]:
    """Product-image original from the bucket, keyed by ``sha256(url)[:16]``.

    Returns ``(bytes, provider)``, or ``(None, None)`` when storage is disabled,
    the key is unknown everywhere, or every provider failed. There is no local
    fallback here by design: a caller only reaches this after the local tiers
    have already missed (see :func:`libs.lib_data.fetch_remote_image_original`).
    """
    key = str(hash_key or "").strip()
    if not key or not fn_storage_enabled():
        return None, None

    names: list[str] = []
    indexed = fn_remote_image_index().get(key)
    if indexed:
        names.append(indexed)
    for ext in (ext_hint, *_IMG_PROBE_EXTS):
        if not ext:
            continue
        cand = f"{key}{ext}"
        if cand not in names:
            names.append(cand)

    for name in names:
        for provider, url in fn_remote_document_urls(fn_image_object_name(name)):
            data = _cached_http_get(url)
            if data:
                return data, provider
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# STATIC SERVING — let the browser fetch local PDFs itself
# ══════════════════════════════════════════════════════════════════════════════
# The catalogue's document panel lives inside a srcdoc iframe, which cannot read
# 01_data/pdf. Inlining the bytes as base64 works but costs a full Streamlit
# rerun per product — and a rerun re-serialises the whole catalogue (1,600
# products with inlined thumbnails), which is what made "View documents" slow.
#
# With `enableStaticServing = true` Streamlit serves ./static at /app/static/, so
# the iframe can load a PDF over plain HTTP with no rerun at all. The files
# aren't copied: each is HARD-LINKED into static/docs/, so it costs no extra disk
# and stays byte-identical to 01_data/pdf. Hard links (not a junction/symlink)
# because Streamlit's static handler resolves the real path and rejects anything
# that escapes ./static — a junction returns 400, a hard link resolves inside.
#
# IMPORTANT — Streamlit hard-codes a 1 GiB cap on the whole ./static folder,
# checked ONCE at server startup (streamlit.web.bootstrap, MAX_APP_STATIC_
# FOLDER_SIZE): if the folder is already over 1 GiB when the process boots, it
# silently force-disables static serving app-wide for that process's entire
# lifetime — no error, just a console warning, and every static:// fetch 404s.
# It measures raw per-file size and does NOT dedupe hard links sharing an
# inode, so linking everything doesn't help: 01_data/pdf is ~1.2 GiB, over the
# cap on its own. MAX_STATIC_DOCS_BYTES keeps static/docs itself comfortably
# under that ceiling (with headroom for fonts/vendor/pdf.js) by linking only as
# many files as fit, most-recently-modified first — a fresh pipeline run's
# documents win over stale ones. Whatever doesn't fit isn't a dead end: the
# catalogue's document panel falls back to the server-side "Load preview" fetch
# for any document with no static URL (see showDocPreview() in
# 02_html/catalogue_component_js2.html), just slower — one rerun instead of a
# plain HTTP GET.

STATIC_DOCS_URL_PREFIX = "/app/static/docs/"
MAX_STATIC_DOCS_BYTES = 700 * 1024 * 1024  # 700 MiB — see note above

_PROJECT_ROOT_DS = Path(__file__).resolve().parent.parent
_LOCAL_PDF_SOURCE_DIR = _PROJECT_ROOT_DS / "01_data" / "pdf"
_STATIC_DOCS_DIR = _PROJECT_ROOT_DS / "static" / "docs"


def fn_static_docs_dir() -> Path:
    return _STATIC_DOCS_DIR


def fn_sync_static_doc_links(*, budget_bytes: int = MAX_STATIC_DOCS_BYTES) -> dict:
    """Mirror as much of ``01_data/pdf`` into ``static/docs`` as fits under budget.

    Cheap and idempotent: files already linked and still current are skipped, so
    calling this on every app start costs a directory listing plus a handful of
    stat() calls. Falls back to copying when hard links aren't possible (different
    volume, or a filesystem without them).

    Trimming to budget is unconditional, not opt-in: a file that no longer fits
    (source removed, or pushed out by newer documents once the total exceeds
    *budget_bytes*) is always removed from static/docs, since leaving it would
    either serve stale content or, worse, silently blow through Streamlit's 1 GiB
    static-folder ceiling (see the module docstring above).

    Returns counts: ``{linked, copied, skipped, failed, pruned, budget_skipped}``.
    """
    stats = {"linked": 0, "copied": 0, "skipped": 0, "failed": 0, "pruned": 0, "budget_skipped": 0}
    if not _LOCAL_PDF_SOURCE_DIR.is_dir():
        return stats
    try:
        _STATIC_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return stats

    # os.scandir rather than iterdir + stat: on Windows the directory
    # enumeration already carries size and mtime, so DirEntry.stat() needs no
    # further syscall. Reaching for them through Path.stat() meant two stats per
    # source file and two more per destination — ~4,900 filter-driver round trips
    # on this OneDrive volume every time the app starts.
    sources: list[tuple[str, str, float, int]] = []  # (name, path, mtime, size)
    try:
        with os.scandir(_LOCAL_PDF_SOURCE_DIR) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                    info = entry.stat()
                    sources.append((entry.name, entry.path, info.st_mtime, info.st_size))
                except OSError:
                    continue
    except OSError:
        return stats
    # Most-recently-modified first: when not everything fits, a fresh pipeline
    # run's documents should be the ones kept, not whichever happened to sort
    # first alphabetically.
    sources.sort(key=lambda t: t[2], reverse=True)

    dst_sizes: dict[str, int] = {}
    try:
        with os.scandir(_STATIC_DOCS_DIR) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        dst_sizes[entry.name] = entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass

    wanted: set[str] = set()
    total_bytes = 0
    for name, src_path, _mtime, size in sources:
        dst = _STATIC_DOCS_DIR / name
        # Same size means the link/copy is still current. Hard links share an
        # inode so this is always true for them; the check matters for copies
        # and for a file the pipeline re-downloaded.
        current = dst_sizes.get(name) == size
        if not current and total_bytes + size > budget_bytes:
            stats["budget_skipped"] += 1
            continue
        wanted.add(name)
        total_bytes += size
        if current:
            stats["skipped"] += 1
            continue
        try:
            if name in dst_sizes:
                dst.unlink()
            try:
                os.link(src_path, dst)
                stats["linked"] += 1
            except OSError:
                shutil.copy2(src_path, dst)
                stats["copied"] += 1
        except OSError:
            stats["failed"] += 1

    for stale_name in [n for n in dst_sizes if n not in wanted]:
        try:
            (_STATIC_DOCS_DIR / stale_name).unlink()
            stats["pruned"] += 1
        except OSError:
            pass
    return stats


def fn_static_doc_url(local_path_or_name) -> str:
    """Public ``/app/static/docs/<file>`` URL for a local PDF, or "" if unavailable.

    Accepts a path or a bare filename; only the basename is used, since
    ``static/docs`` is flat.
    """
    if not local_path_or_name:
        return ""
    name = Path(str(local_path_or_name).replace("\\", "/")).name
    if not name:
        return ""
    # Directory listing rather than a stat per document: the catalogue calls this
    # once per document kind per product, and static/docs holds ~650 files on a
    # OneDrive-synced volume where each stat is a filter-driver round trip.
    from .lib_data import _dir_has_file

    if not _dir_has_file(_STATIC_DOCS_DIR, name):
        return ""
    return STATIC_DOCS_URL_PREFIX + quote(name)
