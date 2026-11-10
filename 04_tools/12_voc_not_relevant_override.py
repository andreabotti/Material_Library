"""
12_voc_not_relevant_override.py — stamp ``n/r`` on every VOC field for the
product types where VOC does not apply.

Why this exists
---------------
``base_data.parquet`` is the pure Excel conversion and is never written by the
app. Most rows of the cementitious / metallic product types already carry a
hand-entered ``n/r`` in the source workbook, but not all of them: 41 rows
(Cable trays, Framing profiles, Structural accessories) are simply blank, and
another 34 have ``n/r`` everywhere except ``VO__VOC_Body``. Blank reads as
*missing* in the Add/Edit Summary; ``n/r`` reads as *not relevant*.

Rather than ask for those cells to be filled in by hand in the workbook, this
tool writes the gap into ``edits_data.parquet`` — the append-only overlay the
app merges on read (libs/lib_data.py fn153-fn159). Re-running
``03_excel_to_parquet.py`` cannot clobber it.

The product types come from ``libs.lib_revalu_map.VOC_NOT_RELEVANT_PRODUCT_TYPES``
and the fields from ``VOC_FIELDS``, so this tool, the Add/Edit form's locked VOC
tab and the Summary matrix all read the same rule.

Only rows that actually need a change get a record — a row already reading
``n/r`` in all nine fields is left alone, so re-running is a no-op.

Usage
-----
    python 04_tools/12_voc_not_relevant_override.py            # dry run
    python 04_tools/12_voc_not_relevant_override.py --apply    # write
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
import warnings

import pandas as pd

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from libs.lib_revalu_map import (  # noqa: E402
    VOC_FIELDS,
    VOC_NOT_RELEVANT_PRODUCT_TYPES,
    VOC_NOT_RELEVANT_VALUE as NR,
)

BASE_PATH  = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

EDIT_AUDIT_COLS = ("_edit_id", "_edit_ts", "_edit_user", "_edit_op")
EDIT_USER = "voc_nr_override"

# Written alongside the nine form fields so the cert-parse status agrees with
# what the form now shows. 03_excel_to_parquet.py already assigns this for most
# of these rows; setting it here keeps the overlay self-consistent for the rest.
PARSE_STATUS_COL = "VO__VOC_Cert_Parse_Status"
PARSE_STATUS_NA  = "not_applicable"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def _is_nr(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() == NR


def _effective_dataset() -> pd.DataFrame:
    """base ⊕ edits, matching what the app reads."""
    from libs.lib_data import fn157_merge_base_and_edits

    base = pd.read_parquet(BASE_PATH)
    if not EDITS_PATH.exists():
        return base
    return fn157_merge_base_and_edits(base, pd.read_parquet(EDITS_PATH))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the records (default is a dry run)")
    args = ap.parse_args()

    df = _effective_dataset()
    voc_cols = [c for c in VOC_FIELDS if c in df.columns]
    missing_cols = [c for c in VOC_FIELDS if c not in df.columns]
    if missing_cols:
        print(f"⚠️  columns absent from the dataset, skipped: {', '.join(missing_cols)}")

    in_scope = df["D__ProductType_ENG"].isin(VOC_NOT_RELEVANT_PRODUCT_TYPES)
    scope = df[in_scope]
    print(f"Product types treated as VOC not relevant: {len(VOC_NOT_RELEVANT_PRODUCT_TYPES)}")
    print(f"Rows in scope: {len(scope)} of {len(df)}\n")

    needs = scope.index[
        scope[voc_cols].map(_is_nr).all(axis=1).eq(False)
        | scope.get(PARSE_STATUS_COL, pd.Series(PARSE_STATUS_NA, index=scope.index))
              .astype(str).str.strip().ne(PARSE_STATUS_NA)
    ]

    per_type = (
        scope.assign(_needs=scope.index.isin(needs))
             .groupby("D__ProductType_ENG")
             .agg(rows=("_needs", "size"), to_update=("_needs", "sum"))
             .sort_values("rows", ascending=False)
    )
    print(per_type.to_string())
    print(f"\nRows needing an override record: {len(needs)}")

    if not len(needs):
        print("Nothing to do — every in-scope row already reads n/r.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to edits_data.parquet.")
        return 0

    # One full-row snapshot per changed row, the same shape the Add/Edit page
    # appends (libs/lib_data.py fn156) — newest record per id wins on merge.
    records = df.loc[needs].copy()
    for col in voc_cols:
        records[col] = NR
    if PARSE_STATUS_COL in records.columns:
        records[PARSE_STATUS_COL] = PARSE_STATUS_NA

    stamp = pd.Timestamp.utcnow().isoformat()
    base_ns = time.time_ns()
    records["_edit_id"]   = [f"{base_ns + i:d}" for i in range(len(records))]
    records["_edit_ts"]   = stamp
    records["_edit_user"] = EDIT_USER
    records["_edit_op"]   = "update"

    if EDITS_PATH.exists():
        existing = pd.read_parquet(EDITS_PATH)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            combined = pd.concat([existing, records], ignore_index=True)
    else:
        combined = records.reset_index(drop=True)

    for col in combined.columns:
        if combined[col].dtype == "object":
            combined[col] = combined[col].astype("string")

    EDITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EDITS_PATH.with_suffix(EDITS_PATH.suffix + ".tmp")
    combined.to_parquet(tmp, index=False)
    import os
    os.replace(tmp, EDITS_PATH)
    print(f"\n✅ Wrote {len(records)} records → {EDITS_PATH.relative_to(_PROJECT_ROOT)} "
          f"({len(combined)} rows in the log).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
