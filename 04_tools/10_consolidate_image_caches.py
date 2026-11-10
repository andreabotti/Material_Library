"""
10_consolidate_image_caches.py — fold the legacy .cache/images store into static/img_cache
==========================================================================================

The app used to keep three image caches side by side:

  01_data/img        pipeline originals, keyed sha256(url)[:16] and <ID>_<slug>
  .cache/images      fn110's fetch cache, keyed md5(url), with a "__catalogue" variant
  static/img_cache   downscaled thumbnails the browser is served, keyed md5(url)

``fn110_cached_fetch_image`` no longer reads or writes ``.cache/images`` — its
fetch tier is ``static/img_cache``, the same store the catalogue serves from. That
leaves two directories with distinct jobs (pipeline source of truth, and served
thumbnails) and makes ``.cache/images`` dead weight.

Dead weight is not quite the same as worthless, though: a handful of entries are
the *only* surviving copy of an image whose source URL has since stopped
responding, so they are not in 01_data/img and were never re-fetched into
static/img_cache. Deleting the directory without checking would silently lose
those product images.

This script migrates them. For every ``.cache/images`` entry that a live row
still references and that ``static/img_cache`` does not already hold, it writes a
downscaled WebP into ``static/img_cache`` under the key the app looks up. It only
ever adds files; it never deletes anything.

Usage:
    python 04_tools/10_consolidate_image_caches.py            # report only
    python 04_tools/10_consolidate_image_caches.py --apply    # write the migration

Afterwards ``.cache/images`` is fully redundant and can be removed by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

from libs import lib_data as ld  # noqa: E402

LEGACY_CACHE = _ROOT / ".cache" / "images"


def _live_urls_by_md5() -> dict[str, tuple[str, str, str]]:
    """``{md5(raw_url): (url, eetra_id, product_name)}`` for the current dataset."""
    base = ld.fn153_resolve_base_parquet_path()
    if not base.exists():
        return {}
    df = pd.read_parquet(base)
    out: dict[str, tuple[str, str, str]] = {}
    if "U__Img_URL" not in df.columns:
        return out
    for _, row in df.iterrows():
        url = ld._clean_row_field(row.get("U__Img_URL"))
        if not url:
            continue
        out.setdefault(
            hashlib.md5(url.encode()).hexdigest(),
            (
                url,
                ld._clean_row_field(row.get("0__EETRA_ID")),
                ld._clean_row_field(row.get("A__ProductName")),
            ),
        )
    return out


def _passes_app_validity(path: Path) -> bool:
    """Would the catalogue accept this file as a real product image?"""
    try:
        with Image.open(path) as probe:
            probe.load()
            img = ld._pil_open_safe_loaded(probe)
        return bool(ld.catalogue_image_cache_is_valid(img))
    except Exception:  # noqa: BLE001
        return False


def _available_elsewhere(url: str, eetra_id: str, product_name: str) -> bool:
    norm = ld.normalize_product_image_url(url)
    if ld.resolve_hash_local_image_path(norm) is not None:
        return True
    if eetra_id and product_name:
        if ld.resolve_local_product_image_path(norm, eetra_id, product_name) is not None:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the migration (default: report only)")
    args = ap.parse_args()

    if not LEGACY_CACHE.is_dir():
        print(f"Nothing to do — {LEGACY_CACHE} does not exist.")
        return 0

    by_md5 = _live_urls_by_md5()
    entries = [p for p in LEGACY_CACHE.iterdir() if p.is_file()]

    to_migrate: list[tuple[Path, str]] = []
    already_served = redundant = unreferenced = rejected = 0

    for path in entries:
        key = path.stem.replace("__catalogue", "")
        live = by_md5.get(key)
        if live is None:
            unreferenced += 1
            continue
        url, eid, name = live
        if ld.static_img_cache_url(url):
            already_served += 1
            continue
        if _available_elsewhere(url, eid, name):
            redundant += 1
            continue
        # Apply the app's own admission test before rescuing anything. A good
        # part of what this cache accumulated is not photographs at all but the
        # small square error graphics some CDNs return in place of a 404, and
        # catalogue_image_cache_is_valid (which rejects anything under 64px) is
        # exactly what stops those reaching a card. Migrating without this check
        # would launder a rejected placeholder into the served store, where the
        # catalogue trusts the file's presence and shows it.
        if not _passes_app_validity(path):
            rejected += 1
            continue
        to_migrate.append((path, url))

    total_bytes = sum(p.stat().st_size for p in entries)
    print(f"{LEGACY_CACHE.relative_to(_ROOT)}: {len(entries)} files, {total_bytes / 1e6:.1f} MB")
    print(f"  already in static/img_cache          : {already_served}")
    print(f"  recoverable from 01_data/img         : {redundant}")
    print(f"  not referenced by any row            : {unreferenced}")
    print(f"  rejected (CDN placeholder / < 64px)  : {rejected}")
    print(f"  ONLY copy of a live product image    : {len(to_migrate)}")

    if not to_migrate:
        print("\nNothing needs migrating — .cache/images holds no unique image.")
        return 0

    print()
    for path, url in to_migrate:
        print(f"  {path.name}  <-  {url[:80]}")

    if not args.apply:
        print("\nReport only. Re-run with --apply to migrate these into static/img_cache.")
        return 0

    migrated = failed = 0
    for path, url in to_migrate:
        try:
            with Image.open(path) as probe:
                probe.load()
                img = ld._pil_open_safe_loaded(probe)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED to read {path.name}: {exc}")
            failed += 1
            continue
        if ld.ensure_static_img_cache(url, img):
            migrated += 1
        else:
            print(f"  FAILED to write {path.name}")
            failed += 1

    print(f"\nMigrated {migrated}, failed {failed}.")
    if failed == 0:
        print(".cache/images is now fully redundant and can be deleted.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
