"""
09_migrate_pdf_prefixes.py  –  one-time rename of existing 01_data/pdf files

03_excel_to_parquet.py now names newly-downloaded technical sheets and VOC
certs with a type prefix (tech_<hash>.pdf, voc_<hash>.pdf) instead of a bare
hash — see _URL_COLS / _url_to_local_filename(). This script applies that
naming to files already on disk from before the change, and updates every
row's U__TechDetails_Local / VO__VOC_Local / U__VOC_Local_alt value in
01_data/base_data.parquet to match.

EPD PDFs are untouched — they're already self-describing (dec_/reg_ number).

Safe to re-run: already-prefixed files and missing files are skipped.

Usage (PowerShell):
    python 04_tools/09_migrate_pdf_prefixes.py            # apply
    python 04_tools/09_migrate_pdf_prefixes.py --dry-run   # preview only, no renames/writes
"""
import argparse
import pathlib
import sys

import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# One canonical dataset now: 01_data/base_data.parquet. This script used to
# rewrite live_data.parquet and its 01_data twin; both are retired.
PARQUET_PATH = _ROOT / "01_data" / "base_data.parquet"

# (local_path_column, prefix) — must match _URL_COLS in 03_excel_to_parquet.py
_COLUMNS_TO_MIGRATE = [
    ("U__TechDetails_Local", "tech_"),
    ("VO__VOC_Local",        "voc_"),
    ("U__VOC_Local_alt",     "voc_"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Rename existing tech/VOC PDFs with a type prefix")
    ap.add_argument("--dry-run", action="store_true", help="Preview renames without touching disk or parquet")
    args = ap.parse_args()

    if not PARQUET_PATH.exists():
        print(f"Parquet not found: {PARQUET_PATH}")
        sys.exit(1)

    df = pd.read_parquet(PARQUET_PATH)

    renamed = skipped_already = skipped_missing = skipped_collision = 0
    old_to_new: dict[str, str] = {}  # relative path string -> relative path string

    for local_col, prefix in _COLUMNS_TO_MIGRATE:
        if local_col not in df.columns:
            continue
        for raw in df[local_col].dropna().unique():
            rel = str(raw).strip()
            if not rel or rel in old_to_new:
                continue
            old_path = _ROOT / rel
            if old_path.name.startswith(prefix):
                skipped_already += 1
                continue
            if not old_path.exists():
                skipped_missing += 1
                continue
            new_name = f"{prefix}{old_path.name}"
            new_path = old_path.parent / new_name
            if new_path.exists():
                skipped_collision += 1
                print(f"  ⚠️  collision, keeping old name: {rel} (target {new_name} already exists)")
                continue
            if not args.dry_run:
                old_path.rename(new_path)
            old_to_new[rel] = str(new_path.relative_to(_ROOT))
            renamed += 1

    print(
        f"Renamed {renamed} file(s)"
        + (" [dry run — no files actually moved]" if args.dry_run else "")
        + f", {skipped_already} already prefixed, {skipped_missing} missing on disk, "
        f"{skipped_collision} skipped due to name collision."
    )

    if not old_to_new:
        print("Nothing to update in the parquet.")
        return

    for local_col, _prefix in _COLUMNS_TO_MIGRATE:
        if local_col not in df.columns:
            continue
        df[local_col] = df[local_col].map(lambda v: old_to_new.get(str(v).strip(), v) if pd.notna(v) else v)

    if args.dry_run:
        print("Dry run — parquet not written.")
        return

    df.to_parquet(PARQUET_PATH, index=False)
    print(f"Updated parquet written → {PARQUET_PATH}\n                    copy → {PARQUET_PATH_ALT}")


if __name__ == "__main__":
    main()
