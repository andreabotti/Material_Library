"""
19_voc_body_cleanup.py — make ``VO__VOC_Body`` a vocabulary field.

Why this exists
---------------
``VO__VOC_Body`` was labelled "VOC Description" and hidden from the form, so it
collected whatever each data-entry session put there: mostly a laboratory or
scheme owner, sometimes the manufacturer's own name, once a whole paragraph.
The field is now **VOC Testing / Certifying Body**, a dropdown over
``lib_revalu_map.VOC_BODIES``, so the stored values have to be the same shape.

What this changes
-----------------
  Eurofin                                 → Eurofins                        (typo, 221 rows)
  UL Solution                             → UL Solutions                    (typo)
  Building Information Foundation RTS sr  → Building Information Foundation RTS
  Cipa Gres / Mapei / Gold Art / EcoCocon → Manufacturer (in-house)
        The row's own manufacturer name, on rows whose report type is
        Self-Declaration. A__Manufacturer already says who they are; what this
        field has to answer is whether anyone independent was involved.
  ANSI National Accreditation Board       → CRI (Carpet and Rug Institute)
        ANAB accredits laboratories, it does not certify products. The row's
        claim is CRI Green Label Plus, so CRI is the body.
  "Manufacturer technical datasheet …"    → SCS Global Services, and the
        sentence moves to S__Comments. The row holds a FloorScore certificate
        with an SCS number, so SCS is the body; the note about the original
        certificate being unverified is a comment, not a body name.

Left alone, and reported at the end of the run:

  * ``n/r``, ``n/a``, ``*`` and blanks;
  * laboratories that are simply not on the curated list (they stay as typed —
    the form keeps them through "➕ New body…");
  * **Green Top** (7 rows, IPM Italia): these rows carry a certificate number
    but no certification, standard or report type, so what "Green Top" refers
    to cannot be settled from the data. They need a look at the documents.

Records are appended to ``edits_data.parquet`` exactly as the Add/Edit page
would; only rows that change get one, so re-running is a no-op.

Usage
-----
    python 04_tools/19_voc_body_cleanup.py            # dry run
    python 04_tools/19_voc_body_cleanup.py --apply    # write
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

from libs.lib_revalu_map import VOC_BODIES  # noqa: E402

BASE_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

COL = "VO__VOC_Body"
COMMENTS = "S__Comments"
EDIT_USER = "voc_body_cleanup"

IN_HOUSE = "Manufacturer (in-house)"

# Whole-value rewrites: {current value: (new value, why)}
VALUE_FIXES: dict[str, tuple[str, str]] = {
    "Eurofin": ("Eurofins", "spelling"),
    "UL Solution": ("UL Solutions", "spelling"),
    "Building Information Foundation RTS sr": (
        "Building Information Foundation RTS", "spelling"),
    "Cipa Gres S.p.A.": (IN_HOUSE, "manufacturer's own declaration"),
    "Mapei S.p.A.": (IN_HOUSE, "manufacturer's own declaration"),
    "Gold Art Ceramica S.p.A.": (IN_HOUSE, "manufacturer's own declaration"),
    "EcoCocon s.r.o.": (IN_HOUSE, "manufacturer's own declaration"),
    "ANSI National Accreditation Board (ANAB)": (
        "CRI (Carpet and Rug Institute)", "ANAB accredits labs, CRI certifies the product"),
}

# The one row whose body held a paragraph: the text becomes a comment.
PROSE_PREFIX = "Manufacturer technical datasheet"
PROSE_BODY = "SCS Global Services"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def _blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() in ("", "-", "nan", "None", "<NA>")


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

    values = df[COL].astype(str).str.strip()
    changes: dict[int, dict[str, str]] = {}
    summary: list[tuple[int, str, str, str]] = []

    for old, (new, why) in VALUE_FIXES.items():
        hits = df.index[values == old]
        if not len(hits):
            continue
        summary.append((len(hits), old, new, why))
        for idx in hits:
            changes.setdefault(idx, {})[COL] = new

    prose = df.index[values.str.startswith(PROSE_PREFIX, na=False)]
    for idx in prose:
        text = str(df.at[idx, COL]).strip()
        changes.setdefault(idx, {})[COL] = PROSE_BODY
        if COMMENTS in df.columns:
            existing = df.at[idx, COMMENTS]
            changes[idx][COMMENTS] = text if _blank(existing) else f"{str(existing).strip()} {text}"
    if len(prose):
        summary.append((len(prose), PROSE_PREFIX + " …", PROSE_BODY, "paragraph moved to Comments"))

    print(f"Effective dataset: {len(df)} rows")
    print(f"Distinct {COL} values before: {values[~values.isin(['', 'nan', '<NA>'])].nunique()}\n")
    for n, old, new, why in sorted(summary, key=lambda r: -r[0]):
        print(f"  {n:4d}  {old[:46]:48s} → {new[:34]:36s} ({why})")
    print(f"\nRows to update: {len(changes)}")

    after = values.map(lambda v: VALUE_FIXES.get(v, (v,))[0])
    known = {b.lower() for b in VOC_BODIES}
    off_list = sorted({
        v for v in after.unique()
        if not _blank(v) and v != "*" and v.lower() not in known
        and not v.startswith(PROSE_PREFIX)
    })
    if off_list:
        print("\nNot on the curated list — left as typed:")
        for value in off_list:
            print(f"  {int((after == value).sum()):4d}  {value}")

    if not changes:
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to edits_data.parquet.")
        return 0

    records = df.loc[list(changes)].copy()
    for idx, updates in changes.items():
        for col, value in updates.items():
            records.at[idx, col] = value

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
