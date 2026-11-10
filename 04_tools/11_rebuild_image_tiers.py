"""
11_rebuild_image_tiers.py — regenerate static/img_cache at the two served sizes
===============================================================================

``static/img_cache`` holds what the browser is sent. It now carries two tiers per
image, both derived from the untouched originals in ``01_data/img``:

  card    "<md5>.webp"     grid thumbnails  — theme.json image_band.cache_card_max_px
  detail  "<md5>__d.webp"  the right panel  — theme.json image_band.cache_detail_max_px

The app writes a tier only when it is missing, so changing a tier's size does not
by itself rewrite the files already on disk — in particular the card tier keeps
its bare "<md5>" name, so an existing oversized file still looks present. This
script rewrites both tiers for every image whose original can be resolved.

Originals are only ever read. Files whose source cannot be resolved (typically a
thumbnail fetched from a URL that no longer responds) are reported and left
exactly as they are, since re-deriving them is impossible.

Usage:
    python 04_tools/11_rebuild_image_tiers.py            # report only
    python 04_tools/11_rebuild_image_tiers.py --apply    # rewrite the tiers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

from libs import lib_data as ld  # noqa: E402

CACHE = ld._STATIC_IMG_CACHE_DIR


def _dir_bytes() -> tuple[int, int]:
    files = [p for p in CACHE.iterdir() if p.is_file() and not p.name.endswith(".tmp")]
    return len(files), sum(p.stat().st_size for p in files)


def _source_for(url: str, eetra_id: str, product_name: str) -> Path | None:
    """The original this thumbnail should be derived from, if we still have it."""
    norm = ld.normalize_product_image_url(url)
    p = ld.resolve_hash_local_image_path(norm)
    if p is not None:
        return p
    if eetra_id and product_name:
        p = ld.resolve_local_product_image_path(norm, eetra_id, product_name)
        if p is not None:
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the tiers (default: report only)")
    args = ap.parse_args()

    card_px = ld._static_img_tier_max_px(ld._STATIC_IMG_TIER_CARD)
    detail_px = ld._static_img_tier_max_px(ld._STATIC_IMG_TIER_DETAIL)
    print(f"tier budgets: card {card_px}px · detail {detail_px}px (longest edge)")

    base = ld.fn153_resolve_base_parquet_path()
    df = pd.read_parquet(base)

    jobs: dict[str, Path] = {}
    unresolved: list[str] = []
    for _, row in df.iterrows():
        url = ld._clean_row_field(row.get("U__Img_URL"))
        if not url or url in jobs:
            continue
        # The pipeline's own *_Local column first, then the hash/name conventions.
        col = ld._clean_row_field(row.get("U__Img_Local"))
        src = ld.resolve_local_image_path_from_column(col) if col else None
        if src is None:
            src = _source_for(url, ld._clean_row_field(row.get("0__EETRA_ID")),
                              ld._clean_row_field(row.get("A__ProductName")))
        if src is None:
            unresolved.append(url)
            continue
        jobs[url] = src

    n0, b0 = _dir_bytes()
    print(f"static/img_cache before : {n0} files, {b0/1e6:.2f} MB")
    print(f"images with a local original: {len(jobs)}")
    print(f"no original on disk (left untouched): {len(unresolved)}")

    if not args.apply:
        print("\nReport only. Re-run with --apply to rewrite both tiers.")
        return 0

    CACHE.mkdir(parents=True, exist_ok=True)
    rebuilt = failed = skipped = 0
    for url, src in jobs.items():
        try:
            with Image.open(src) as probe:
                probe.load()
                img = ld._pil_open_safe_loaded(probe)
        except Exception:
            failed += 1
            continue
        if not ld.catalogue_image_cache_is_valid(img):
            # Same admission test the app applies; keeps CDN error graphics out.
            skipped += 1
            continue
        ext = ld._static_img_cache_extension()
        wrote = 0
        for tier in (ld._STATIC_IMG_TIER_CARD, ld._STATIC_IMG_TIER_DETAIL):
            budget = ld._static_img_tier_max_px(tier)
            thumb = ld._pil_downscale_if_needed(img, budget, budget)
            dest = CACHE / f"{ld._static_img_cache_key(url, tier)}{ext}"
            if ld._write_static_img_cache_atomic(thumb, dest):
                wrote += 1
        if wrote == 2:
            rebuilt += 1
        else:
            failed += 1

    n1, b1 = _dir_bytes()
    print(f"\nrebuilt {rebuilt}, skipped {skipped} (failed admission), failed {failed}")
    print(f"static/img_cache after  : {n1} files, {b1/1e6:.2f} MB")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
