"""
Upload the two asset folders the app can serve remotely — 01_data/pdf (EPD /
tech-sheet documents) and 01_data/img (product-image originals) — to the
configured Supabase Storage and/or Cloudflare R2 buckets, so the app can read
them remote-first (see libs/lib_doc_storage.py) instead of needing the full
~1.25 GB locally.

Layout in the bucket (one bucket holds both):

    <object>                 documents, keyed by their 01_data/pdf filename
    img/<object>             image originals, keyed by their 01_data/img filename
    img/_index.json          {sha256(url)[:16]: filename} for every image above

The index exists so the app can resolve an image without probing five
extensions over HTTP — see the PRODUCT IMAGES note in libs/lib_doc_storage.py.
It is rewritten from the local folder on every run that touches images.

Reads credentials from .streamlit/secrets.toml ([supabase], [cloudflare_r2]).
The app itself never uses the keys below (service_role_key / access keys) —
only this offline migration script does, since the buckets are public-read.

Usage (PowerShell):
    python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --dry-run
    python 04_tools/07_upload_pdfs_to_buckets.py --target r2
    python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --what images
    python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --checksum --dry-run
    python 04_tools/07_upload_pdfs_to_buckets.py --target both --force

Re-running is cheap and idempotent: one HEAD per object, and an object is sent
again only when its bytes differ from the remote copy.

    (default)     skip when remote size == local size
    --checksum    also compare MD5 vs the remote ETag (same-size edits)
    --force       re-upload everything, no comparison

Existence alone is deliberately NOT the test. These keys are not content
hashes -- a document key is its registration number, an image key is sha256 of
its SOURCE url -- so re-issuing an EPD under the same registration, or a
manufacturer swapping the picture behind a stable url, leaves the key unchanged
while the bytes change. Skipping on existence would pin that stale copy in the
bucket forever. Note that a replaced object can still be served from the CDN
edge for up to --cache-seconds (7 days by default); purge it in the Cloudflare
dashboard when a correction is urgent.

Deletions are never propagated: removing a local file leaves its object in
place as an orphan, to be removed by hand.

Cache-Control defaults to 7 days rather than the year-long "immutable" that
content-addressed assets usually get, because these keys are NOT content
hashes: an image key is sha256 of its SOURCE URL, and a document key is its
registration number. Re-issue an EPD under the same registration, or let a
manufacturer swap the picture behind a stable URL, and the key is unchanged
while the bytes are not. Seven days still serves almost every view from the
CDN edge for free. Pass --cache-seconds to change it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

import requests

# The asset folders and secrets are resolved from a root that defaults to this
# script's app directory, but can be redirected with --root / MATLIB_ASSET_ROOT.
# A git checkout of this project deliberately does NOT carry 01_data/pdf,
# static/docs or .streamlit/secrets.toml (see .gitignore and
# REMOTE_ASSET_STORAGE.md), so running the committed copy of this script has to
# be told where the real working copy lives.
_ENV_ROOT = "MATLIB_ASSET_ROOT"
_ROOT = Path(__file__).resolve().parent.parent
_PDF_DIR = _ROOT / "01_data" / "pdf"
_IMG_DIR = _ROOT / "01_data" / "img"
_SECRETS_PATH = _ROOT / ".streamlit" / "secrets.toml"


def _set_root(root: Path) -> None:
    """Point the asset folders and secrets at ``root``."""
    global _ROOT, _PDF_DIR, _IMG_DIR, _SECRETS_PATH
    _ROOT = root.expanduser().resolve()
    _PDF_DIR = _ROOT / "01_data" / "pdf"
    _IMG_DIR = _ROOT / "01_data" / "img"
    _SECRETS_PATH = _ROOT / ".streamlit" / "secrets.toml"


def _resolve_root(cli_root: str | None) -> Path:
    """``--root`` beats ``$MATLIB_ASSET_ROOT`` beats this script's app dir."""
    chosen = cli_root or os.environ.get(_ENV_ROOT) or None
    if chosen is None:
        return Path(__file__).resolve().parent.parent
    root = Path(chosen).expanduser()
    if not root.is_dir():
        sys.exit(f"--root is not a directory: {root}")
    return root.resolve()


def _missing_dir_hint(missing: Path) -> str:
    """Say *why* the folder is absent, not just that it is."""
    lines = [f"No such directory: {missing}"]
    if (_ROOT / ".git").exists() or not _SECRETS_PATH.is_file():
        lines += [
            "",
            f"{_ROOT} looks like a git checkout. This project excludes the heavy",
            "asset folders (01_data/pdf, static/docs, static/*_cache) and",
            ".streamlit/secrets.toml from version control -- see .gitignore and",
            "REMOTE_ASSET_STORAGE.md -- so a checkout cannot upload on its own.",
        ]
    lines += [
        "",
        "Point --root at the working copy that holds the assets and secrets:",
        "",
        f'    python {Path(__file__).name} --root "<path to the app folder>" '
        "--target r2 --dry-run",
        "",
        f"or set {_ENV_ROOT} once in your shell.",
    ]
    return "\n".join(lines)

# ── Run logging ──────────────────────────────────────────────────────────────
# Every run writes a timestamped file under logs/ (gitignored) so a transfer can
# be audited after the fact: one line per object decision, not just the totals
# the console shows. Credentials are never logged -- the account id is masked
# and the access keys are not referenced at all, so a log file is safe to share.
_LOGGER = logging.getLogger("r2_upload")
_LOG_DIR_NAME = "logs"
_RULE = "=" * 78


def _merge_stats(into: dict, other: dict) -> None:
    for k in ("uploaded", "replaced", "skipped", "failed", "bytes"):
        into[k] += other[k]
    into["failures"].extend(other["failures"])


# A head_object that fails because the key is absent and one that fails because
# the credentials are wrong look identical to a bare `except Exception`.
# Conflating them is dangerous here: a bad key reports every object as "would
# upload", which is indistinguishable from an empty bucket.
_ABSENT_CODES = {"404", "NoSuchKey", "NotFound"}
_FATAL_CODES = {
    "401", "403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch",
    "NoSuchBucket", "InvalidBucketName", "ExpiredToken", "TokenRefreshRequired",
}


def _s3_error_code(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if not isinstance(resp, dict):
        return ""
    code = str(resp.get("Error", {}).get("Code", ""))
    if code:
        return code
    status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return str(status) if status else ""


def _r2_preflight(client, bucket: str) -> None:
    """One head_bucket before the loop, so a bad key fails once and loudly."""
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        code = _s3_error_code(exc) or exc.__class__.__name__
        _LOGGER.error("[cloudflare_r2] preflight FAILED on bucket %r: %s", bucket, code)
        hint = {
            "NoSuchBucket": "bucket does not exist - check `bucket` in secrets.toml",
            "InvalidAccessKeyId": "access_key_id is wrong (watch for a stray space)",
            "SignatureDoesNotMatch": "secret_access_key is wrong",
            "AccessDenied": "the API token lacks Object Read & Write on this bucket",
            "403": "the API token lacks permission on this bucket",
        }.get(code, "check account_id, bucket and the API token in secrets.toml")
        sys.exit(f"[cloudflare_r2] cannot access bucket {bucket!r}: {code} - {hint}")
    _LOGGER.debug("preflight   : bucket %s reachable, credentials accepted", bucket)


def _empty_stats() -> dict:
    return {"uploaded": 0, "replaced": 0, "skipped": 0, "failed": 0,
            "bytes": 0, "failures": []}


def _mask(value: str, keep: int = 6) -> str:
    """Enough of an identifier to recognise it, not enough to reuse it."""
    value = str(value)
    if len(value) <= keep + 4:
        return "***"
    return value[:keep] + "..." + value[-4:]


def _setup_logging(root: Path, log_file: str | None, no_log: bool, dry_run: bool) -> Path | None:
    """Console stays as it was (INFO, bare text); the file gets DEBUG detail."""
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.handlers.clear()
    _LOGGER.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(console)

    if no_log:
        return None

    if log_file:
        path = Path(log_file).expanduser()
    else:
        mode = "dryrun" if dry_run else "upload"
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = root / _LOG_DIR_NAME / f"r2_{mode}_{stamp}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        # A missing log destination must never cost a 1.28 GB transfer.
        print(f"WARNING: could not open log file {path}: {exc} -- continuing without one")
        return None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _LOGGER.addHandler(handler)
    return path


def _log_header(args, root: Path, log_path: Path | None, secrets: dict) -> None:
    mode = "DRY RUN -- nothing is transferred" if args.dry_run else "LIVE UPLOAD"
    _LOGGER.debug(_RULE)
    _LOGGER.debug("R2 asset upload -- %s", mode)
    _LOGGER.debug(_RULE)
    _LOGGER.debug("started     : %s", datetime.now().astimezone().isoformat(timespec="seconds"))
    _LOGGER.debug("root        : %s", root)
    _LOGGER.debug("target      : %s", args.target)
    _LOGGER.debug("what        : %s", args.what)
    _LOGGER.debug("compare     : %s", "force (no comparison)" if args.force
                  else ("size + checksum" if args.checksum else "size"))
    _LOGGER.debug("cache-control: public, max-age=%s", args.cache_seconds)
    r2 = secrets.get("cloudflare_r2", {})
    _LOGGER.debug("r2 bucket   : %s", r2.get("bucket", "<unset>"))
    _LOGGER.debug("r2 account  : %s", _mask(r2.get("account_id", "")))
    _LOGGER.debug("r2 endpoint : https://%s.r2.cloudflarestorage.com",
                  _mask(r2.get("account_id", "")))
    _LOGGER.debug("log file    : %s", log_path or "<none>")
    _LOGGER.debug(_RULE)


def _log_outcome(provider: str, stats: dict, elapsed: float) -> None:
    sent_mb = stats["bytes"] / (1024 * 1024)
    rate = f"{sent_mb / elapsed:.2f} MB/s" if elapsed > 0 and sent_mb else "n/a"
    _LOGGER.debug(_RULE)
    _LOGGER.debug("[%s] finished in %.1fs", provider, elapsed)
    _LOGGER.debug("[%s]   new objects    : %d", provider, stats["uploaded"])
    _LOGGER.debug("[%s]   replaced       : %d", provider, stats["replaced"])
    _LOGGER.debug("[%s]   skipped        : %d", provider, stats["skipped"])
    _LOGGER.debug("[%s]   failed         : %d", provider, stats["failed"])
    _LOGGER.debug("[%s]   bytes sent     : %d (%.1f MB, %s)",
                  provider, stats["bytes"], sent_mb, rate)
    if stats["failures"]:
        _LOGGER.debug("[%s]   failures:", provider)
        for key, why in stats["failures"]:
            _LOGGER.debug("[%s]     %s -- %s", provider, key, why)
    _LOGGER.debug(_RULE)


_IMG_PREFIX = "img/"
_IMG_INDEX_KEY = "img/_index.json"
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_DEFAULT_CACHE_SECONDS = 7 * 24 * 3600

# Documents are not all PDFs: the pipeline also saves manufacturer technical
# sheets that were served as HTML, plus a handful of .php endpoints that
# returned a document. Serving those as application/pdf makes the browser
# download a file it cannot open, so every object gets the type its extension
# implies rather than one hardcoded type for the whole folder.
_EXTRA_TYPES = {
    ".pdf": "application/pdf",
    ".htm": "text/html; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".php": "text/html; charset=utf-8",
    ".webp": "image/webp",
}


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _EXTRA_TYPES:
        return _EXTRA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _load_secrets() -> dict:
    if not _SECRETS_PATH.is_file():
        sys.exit(
            f"Missing {_SECRETS_PATH}\n\n"
            "secrets.toml is not committed to version control. Point --root at the "
            f"working copy that holds it, or set {_ENV_ROOT}."
        )
    with open(_SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def _remote_head(url: str) -> tuple[bool, int | None]:
    """``(exists, remote_size_bytes)``. Size is ``None`` when not advertised."""
    try:
        resp = requests.head(url, timeout=10)
        if resp.status_code != 200:
            return False, None
        raw = resp.headers.get("Content-Length")
        return True, (int(raw) if raw and raw.isdigit() else None)
    except requests.RequestException:
        return False, None


def _local_md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - matching S3 ETag, not a security digest
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _needs_upload(
    path: Path,
    remote_size: int | None,
    remote_etag: str | None,
    checksum: bool,
) -> str | None:
    """Why ``path`` must be re-sent, or ``None`` when the remote copy matches.

    Size is the primary test: an object key here is a registration number or a
    source-URL hash, never a content hash, so the same key legitimately maps to
    new bytes when an EPD is re-issued or a manufacturer swaps the picture
    behind a stable URL. Existence alone therefore cannot mean "up to date".

    ETag is only consulted under ``--checksum``, and only when it is a plain
    MD5 — a multipart upload produces ``<md5>-<parts>``, which is not
    comparable to a whole-file digest, so those are left to the size test.
    """
    local_size = path.stat().st_size
    if remote_size is not None and remote_size != local_size:
        return f"size {remote_size} -> {local_size}"
    if checksum and remote_etag:
        etag = remote_etag.strip('"')
        if "-" not in etag and etag != _local_md5(path):
            return "checksum differs"
    return None


def _collect(what: str) -> list[tuple[Path, str]]:
    """[(local_path, object_key), ...] for the selected asset classes."""
    items: list[tuple[Path, str]] = []
    if what in ("docs", "both"):
        if not _PDF_DIR.is_dir():
            sys.exit(_missing_dir_hint(_PDF_DIR))
        for p in sorted(_PDF_DIR.iterdir()):
            if p.is_file():
                items.append((p, p.name))
    if what in ("images", "both"):
        if not _IMG_DIR.is_dir():
            sys.exit(_missing_dir_hint(_IMG_DIR))
        for p in sorted(_IMG_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in _IMG_EXTS:
                items.append((p, f"{_IMG_PREFIX}{p.name}"))
    if not items:
        sys.exit(f"Nothing to upload for --what {what}")
    return items


def _build_image_index() -> dict[str, str]:
    """``{sha256(url)[:16]: filename}`` — the stem IS the key (see lib_data)."""
    if not _IMG_DIR.is_dir():
        return {}
    return {
        p.stem: p.name
        for p in sorted(_IMG_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in _IMG_EXTS
    }


# ── Supabase Storage ─────────────────────────────────────────────────────────

def upload_to_supabase(secrets: dict, items, force: bool, dry_run: bool, cache_seconds: int,
                       checksum: bool = False) -> None:
    cfg = secrets.get("supabase", {})
    base = str(cfg.get("url", "")).rstrip("/")
    bucket = str(cfg.get("bucket", ""))
    key = str(cfg.get("service_role_key", ""))
    if not base or "YOUR-PROJECT" in base or not key or "YOUR_SUPABASE" in key:
        _LOGGER.info("[supabase] Skipping - url/service_role_key still placeholders in secrets.toml.")
        return _empty_stats()

    public_base = f"{base}/storage/v1/object/public/{bucket}"
    upload_base = f"{base}/storage/v1/object/{bucket}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key}

    stats = {"uploaded": 0, "replaced": 0, "skipped": 0, "failed": 0,
             "bytes": 0, "failures": []}
    for i, (path, object_name) in enumerate(items, 1):
        size = path.stat().st_size
        reason = None
        if not force:
            exists, remote_size = _remote_head(f"{public_base}/{object_name}")
            if exists:
                # Supabase's public HEAD does not expose a comparable ETag.
                reason = _needs_upload(path, remote_size, None, checksum)
                if reason is None:
                    stats["skipped"] += 1
                    _LOGGER.debug("SKIP      %s (%d bytes, unchanged)", object_name, size)
                    continue
        if dry_run:
            verb = f"would replace ({reason})" if reason else "would upload"
            _LOGGER.debug("DRY-RUN   %s (%d bytes, %s) %s",
                          object_name, size, _content_type(path), verb)
            stats["uploaded"] += 1
            stats["bytes"] += size
            continue
        try:
            with open(path, "rb") as fh:
                resp = requests.post(
                    f"{upload_base}/{object_name}",
                    headers={
                        **headers,
                        "Content-Type": _content_type(path),
                        "Cache-Control": f"public, max-age={cache_seconds}",
                        "x-upsert": "true",
                    },
                    data=fh,
                    timeout=120,
                )
            if resp.status_code in (200, 201):
                stats["bytes"] += size
                if reason:
                    stats["replaced"] += 1
                    _LOGGER.info("[supabase] replaced %s (%s)", object_name, reason)
                    _LOGGER.debug("REPLACE   %s (%d bytes) %s", object_name, size, reason)
                else:
                    stats["uploaded"] += 1
                    _LOGGER.debug("UPLOAD    %s (%d bytes, %s)",
                                  object_name, size, _content_type(path))
            else:
                why = f"{resp.status_code} {resp.text[:200]}"
                stats["failed"] += 1
                stats["failures"].append((object_name, why))
                _LOGGER.error("[supabase] FAILED %s: %s", object_name, why)
        except requests.RequestException as exc:
            stats["failed"] += 1
            stats["failures"].append((object_name, str(exc)))
            _LOGGER.error("[supabase] FAILED %s: %s", object_name, exc)
        if i % 50 == 0:
            _LOGGER.info("[supabase] %d/%d processed...", i, len(items))

    _LOGGER.info(
        "[supabase] done: uploaded=%d replaced=%d skipped(unchanged)=%d failed=%d",
        stats["uploaded"], stats["replaced"], stats["skipped"], stats["failed"],
    )
    return stats


def upload_image_index_supabase(secrets: dict, index: dict, dry_run: bool) -> None:
    cfg = secrets.get("supabase", {})
    base = str(cfg.get("url", "")).rstrip("/")
    bucket = str(cfg.get("bucket", ""))
    key = str(cfg.get("service_role_key", ""))
    if not base or "YOUR-PROJECT" in base or not key or "YOUR_SUPABASE" in key:
        return
    if dry_run:
        print(f"[supabase] (dry-run) would write {_IMG_INDEX_KEY} ({len(index)} entries)")
        return
    try:
        resp = requests.post(
            f"{base}/storage/v1/object/{bucket}/{_IMG_INDEX_KEY}",
            headers={
                "Authorization": f"Bearer {key}",
                "apikey": key,
                "Content-Type": "application/json",
                "Cache-Control": "public, max-age=3600",
                "x-upsert": "true",
            },
            data=json.dumps(index, separators=(",", ":")).encode("utf-8"),
            timeout=60,
        )
        if resp.status_code in (200, 201):
            print(f"[supabase] wrote {_IMG_INDEX_KEY} ({len(index)} entries)")
        else:
            print(f"[supabase] FAILED {_IMG_INDEX_KEY}: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] FAILED {_IMG_INDEX_KEY}: {exc}")


# ── Cloudflare R2 (S3-compatible API) ───────────────────────────────────────

def _r2_client(secrets: dict):
    """``(client, bucket, public_base)``, or ``(None, "", "")`` when unconfigured."""
    cfg = secrets.get("cloudflare_r2", {})
    account_id = str(cfg.get("account_id", ""))
    bucket = str(cfg.get("bucket", ""))
    access_key = str(cfg.get("access_key_id", ""))
    secret_key = str(cfg.get("secret_access_key", ""))
    public_base = str(cfg.get("public_base_url", "")).rstrip("/")
    if (
        not account_id or "YOUR_CLOUDFLARE" in account_id
        or not access_key or "YOUR_R2" in access_key
        or not secret_key or "YOUR_R2" in secret_key
    ):
        missing = [n for n, v in (("account_id", account_id), ("access_key_id", access_key),
                                  ("secret_access_key", secret_key))
                   if not v or v.startswith("YOUR_")]
        _LOGGER.info("[cloudflare_r2] Skipping - still placeholders in secrets.toml: %s",
                     ", ".join(missing))
        return None, "", ""

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.exit("boto3 is required for R2 uploads: pip install boto3")

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return client, bucket, public_base


def upload_to_r2(secrets: dict, items, force: bool, dry_run: bool, cache_seconds: int,
                 checksum: bool = False) -> dict:
    client, bucket, public_base = _r2_client(secrets)
    if client is None:
        return _empty_stats()

    _r2_preflight(client, bucket)

    stats = {"uploaded": 0, "replaced": 0, "skipped": 0, "failed": 0,
             "bytes": 0, "failures": []}
    for i, (path, object_name) in enumerate(items, 1):
        size = path.stat().st_size
        reason = None
        if not force:
            # head_object already carries ContentLength and ETag, so change
            # detection costs no extra request over the old existence check.
            try:
                head = client.head_object(Bucket=bucket, Key=object_name)
            except Exception as exc:
                code = _s3_error_code(exc)
                if code in _FATAL_CODES:
                    _LOGGER.error("[cloudflare_r2] fatal on %s: %s", object_name, code)
                    sys.exit(f"[cloudflare_r2] aborting at {object_name}: {code}")
                if code not in _ABSENT_CODES:
                    _LOGGER.warning("[cloudflare_r2] head_object(%s) -> %s; "
                                    "treating as absent", object_name,
                                    code or exc.__class__.__name__)
                head = None
            if head is not None:
                reason = _needs_upload(
                    path, head.get("ContentLength"), head.get("ETag"), checksum
                )
                if reason is None:
                    stats["skipped"] += 1
                    _LOGGER.debug("SKIP      %s (%d bytes, unchanged)", object_name, size)
                    continue
        if dry_run:
            verb = f"would replace ({reason})" if reason else "would upload"
            _LOGGER.debug("DRY-RUN   %s (%d bytes, %s) %s",
                          object_name, size, _content_type(path), verb)
            stats["uploaded"] += 1
            stats["bytes"] += size
            continue
        try:
            client.upload_file(
                str(path), bucket, object_name,
                ExtraArgs={
                    "ContentType": _content_type(path),
                    "CacheControl": f"public, max-age={cache_seconds}",
                },
            )
            stats["bytes"] += size
            if reason:
                stats["replaced"] += 1
                _LOGGER.info("[cloudflare_r2] replaced %s (%s)", object_name, reason)
                _LOGGER.debug("REPLACE   %s (%d bytes, %s) %s",
                              object_name, size, _content_type(path), reason)
            else:
                stats["uploaded"] += 1
                _LOGGER.debug("UPLOAD    %s (%d bytes, %s)",
                              object_name, size, _content_type(path))
        except Exception as exc:
            stats["failed"] += 1
            stats["failures"].append((object_name, str(exc)))
            _LOGGER.error("[cloudflare_r2] FAILED %s: %s", object_name, exc)
            _LOGGER.debug("FAIL      %s (%d bytes) %s", object_name, size, exc)
        if i % 50 == 0:
            _LOGGER.info("[cloudflare_r2] %d/%d processed...", i, len(items))

    _LOGGER.info(
        "[cloudflare_r2] done: uploaded=%d replaced=%d skipped(unchanged)=%d failed=%d",
        stats["uploaded"], stats["replaced"], stats["skipped"], stats["failed"],
    )
    if public_base and "XXXXXXXX" in public_base:
        _LOGGER.warning(
            "[cloudflare_r2] Reminder: public_base_url in secrets.toml is still a "
            "placeholder - enable public access (r2.dev subdomain or custom domain) "
            "on the bucket, then set it."
        )
    return stats


def upload_image_index_r2(secrets: dict, index: dict, dry_run: bool) -> None:
    client, bucket, _public_base = _r2_client(secrets)
    if client is None:
        return
    if dry_run:
        print(f"[cloudflare_r2] (dry-run) would write {_IMG_INDEX_KEY} ({len(index)} entries)")
        return
    try:
        client.put_object(
            Bucket=bucket,
            Key=_IMG_INDEX_KEY,
            Body=json.dumps(index, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
            CacheControl="public, max-age=3600",
        )
        print(f"[cloudflare_r2] wrote {_IMG_INDEX_KEY} ({len(index)} entries)")
    except Exception as exc:
        print(f"[cloudflare_r2] FAILED {_IMG_INDEX_KEY}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None,
                    help="App folder holding 01_data/ and .streamlit/secrets.toml. "
                         f"Defaults to this script's app folder, or ${_ENV_ROOT}. "
                         "Needed when running a git checkout, which carries neither.")
    ap.add_argument("--target", choices=["supabase", "r2", "both"], default="both")
    ap.add_argument("--what", choices=["docs", "images", "both"], default="both",
                    help="Which asset folders to upload (default: both).")
    ap.add_argument("--force", action="store_true",
                    help="Re-upload every object, even one whose remote copy already matches.")
    ap.add_argument("--checksum", action="store_true",
                    help="Also compare MD5 against the remote ETag, catching same-size edits. "
                         "Reads every local file that exists remotely, so it is slower; "
                         "the default size comparison already catches almost all real revisions.")
    ap.add_argument("--dry-run", action="store_true", help="List what would be uploaded without transferring anything.")
    ap.add_argument("--cache-seconds", type=int, default=_DEFAULT_CACHE_SECONDS,
                    help=f"Cache-Control max-age for uploaded objects (default: {_DEFAULT_CACHE_SECONDS}).")
    ap.add_argument("--log-file", default=None,
                    help="Write the run log here instead of "
                         "<root>/logs/r2_<mode>_<timestamp>.log.")
    ap.add_argument("--no-log", action="store_true",
                    help="Do not write a run log file (console output only).")
    args = ap.parse_args()
    _set_root(_resolve_root(args.root))
    log_path = _setup_logging(_ROOT, args.log_file, args.no_log, args.dry_run)

    started = time.monotonic()
    _LOGGER.info("Root: %s", _ROOT)
    if args.dry_run:
        _LOGGER.info("DRY RUN - nothing will be transferred")

    items = _collect(args.what)
    total_bytes = sum(p.stat().st_size for p, _ in items)
    total_mb = total_bytes / (1024 * 1024)
    n_docs = sum(1 for _, k in items if not k.startswith(_IMG_PREFIX))
    n_imgs = len(items) - n_docs
    _LOGGER.info("Found %d objects to consider (%d documents, %d images, %.1f MB)",
                 len(items), n_docs, n_imgs, total_mb)

    secrets = _load_secrets()
    _log_header(args, _ROOT, log_path, secrets)
    _LOGGER.debug("candidates  : %d objects, %d documents, %d images, %d bytes (%.1f MB)",
                  len(items), n_docs, n_imgs, total_bytes, total_mb)
    _LOGGER.debug(_RULE)

    totals = _empty_stats()
    if args.target in ("supabase", "both"):
        t0 = time.monotonic()
        st = upload_to_supabase(secrets, items, args.force, args.dry_run,
                                args.cache_seconds, args.checksum)
        _log_outcome("supabase", st, time.monotonic() - t0)
        _merge_stats(totals, st)
    if args.target in ("r2", "both"):
        t0 = time.monotonic()
        st = upload_to_r2(secrets, items, args.force, args.dry_run,
                          args.cache_seconds, args.checksum)
        _log_outcome("cloudflare_r2", st, time.monotonic() - t0)
        _merge_stats(totals, st)

    if args.what in ("images", "both"):
        index = _build_image_index()
        _LOGGER.debug("image index : %d entries", len(index))
        if args.target in ("supabase", "both"):
            upload_image_index_supabase(secrets, index, args.dry_run)
        if args.target in ("r2", "both"):
            upload_image_index_r2(secrets, index, args.dry_run)

    elapsed = time.monotonic() - started
    verb = "would transfer" if args.dry_run else "transferred"
    sent = totals["uploaded"] + totals["replaced"]
    _LOGGER.debug(_RULE)
    _LOGGER.debug("RUN COMPLETE %s",
                  "(DRY RUN - nothing was transferred)" if args.dry_run else "")
    _LOGGER.debug("finished    : %s",
                  datetime.now().astimezone().isoformat(timespec="seconds"))
    _LOGGER.debug("duration    : %.1fs", elapsed)
    _LOGGER.debug("%-12s: %d objects, %d bytes (%.1f MB)",
                  verb, sent, totals["bytes"], totals["bytes"] / (1024 * 1024))
    _LOGGER.debug("skipped     : %d unchanged", totals["skipped"])
    _LOGGER.debug("failed      : %d", totals["failed"])
    _LOGGER.debug("exit status : %s",
                  "FAILURES PRESENT" if totals["failed"] else "clean")
    _LOGGER.debug(_RULE)

    _LOGGER.info("")
    _LOGGER.info("Run finished in %.1fs - %s %d objects, %.1f MB; %d skipped, %d failed",
                 elapsed, verb, sent, totals["bytes"] / (1024 * 1024),
                 totals["skipped"], totals["failed"])
    if log_path:
        _LOGGER.info("Log written to %s", log_path)
    _LOGGER.info("Once uploads finish, set [doc_storage] enabled = true in "
                 ".streamlit/secrets.toml to switch the app to remote-first "
                 "document loading.")
    if totals["failed"]:
        sys.exit(f"{totals['failed']} object(s) failed - see "
                 f"{log_path or 'the console output'}")


if __name__ == "__main__":
    main()
