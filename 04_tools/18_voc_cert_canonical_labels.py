"""
18_voc_cert_canonical_labels.py — one spelling per VOC claim.

Why this exists
---------------
``VO__VOC_Cert`` collected a spelling per data-entry session: "Greengaurd Gold",
"GREENGUARD GOLD" and "UL Greenguard Gold" are one certification, "EMICODE EC1
Plus" and "EMICODE EC1PLUS" another. The Add/Edit dropdown is built from the
distinct values in the data, so every variant becomes a separate option and the
next entry picks one at random.

This rewrites each value to the canonical label of the catalogue entry it
names (``aux_11__voc_certifications.json``), resolved through the same matcher the
Developer → VOC Bodies & Certifications page uses: labels and aliases, matched
as whole phrases, longest first. Nothing is renamed by hand here — a spelling
is canonicalised only if the catalogue recognises it, so adding an alias to the
catalogue is enough to fold a new variant in on the next run.

Left exactly as they are:

  * ``n/r``, ``n/a``, ``*`` and blanks — these answer "no claim", not "which claim";
  * any value the catalogue does not recognise — those are listed at the end of
    the run, and they belong in the catalogue (or in a data fix) first.

Detail dropped by a rename is checked before it goes: "Blue Angel (DE-UZ 132)"
becomes "Blue Angel" because all 34 rows already name DE-UZ 132 in
``VO__TestStandard``, and "Indoor Air Comfort GOLD(Test Report)" loses a
parenthesis that ``VO__ReportType`` already records.

Records are appended to ``edits_data.parquet`` exactly as the Add/Edit page
would; only rows that change get one, so re-running is a no-op.

Usage
-----
    python 04_tools/18_voc_cert_canonical_labels.py            # dry run
    python 04_tools/18_voc_cert_canonical_labels.py --apply    # write
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
import warnings

import pandas as pd

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from libs.lib_charts import (  # noqa: E402
    _voc_catalog_index,
    _voc_is_placeholder,
    _voc_resolve,
)

BASE_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

COL = "VO__VOC_Cert"
EDIT_USER = "voc_cert_canonical_labels"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


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
    if COL not in df.columns:
        print(f"⚠️  {COL} is absent from the dataset — nothing to do.")
        return 1

    index = _voc_catalog_index()
    values = df[COL].dropna().astype(str).str.strip()

    renames: dict[str, str] = {}
    unknown: dict[str, int] = {}
    for value, n in values.value_counts().items():
        if _voc_is_placeholder(value):
            continue
        entry = _voc_resolve(value, index)
        if entry is None:
            unknown[value] = int(n)
        elif entry["label"] != value:
            renames[value] = entry["label"]

    target = values.map(renames)
    changed = df.index[target.notna().reindex(df.index, fill_value=False)]

    print(f"Effective dataset: {len(df)} rows")
    print(f"Distinct {COL} spellings before: {values.nunique()}\n")
    for old, new in sorted(renames.items(), key=lambda kv: -int((values == kv[0]).sum())):
        print(f"  {int((values == old).sum()):4d}  {old[:50]:52s} → {new}")
    print(f"\nRows to update: {len(changed)}")

    if unknown:
        print("\nNot in the catalogue — left untouched:")
        for value, n in sorted(unknown.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {value}")

    after = sorted({
        renames.get(v, v) for v in values.unique() if not _voc_is_placeholder(v)
    })
    print(f"\nDistinct claims after: {len(after)}")
    for value in after:
        print(f"  · {value}")

    if not len(changed):
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to edits_data.parquet.")
        return 0

    records = df.loc[changed].copy()
    records[COL] = [renames[str(v).strip()] for v in records[COL]]

    stamp = pd.Timestamp.utcnow().isoformat()
    base_ns = time.time_ns()
    records["_edit_id"] = [f"{base_ns + i:d}" for i in range(len(records))]
    records["_edit_ts"] = stamp
    records["_edit_user"] = EDIT_USER
    records["_edit_op"] = "update"

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

    tmp = EDITS_PATH.with_suffix(EDITS_PATH.suffix + ".tmp")
    combined.to_parquet(tmp, index=False)
    os.replace(tmp, EDITS_PATH)
    print(f"\n✅ Wrote {len(records)} records → {EDITS_PATH.relative_to(_PROJECT_ROOT)} "
          f"({len(combined)} rows in the log).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
