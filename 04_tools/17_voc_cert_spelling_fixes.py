"""
17_voc_cert_spelling_fixes.py — settle the VOC claims the catalogue did not know.

Why this exists
---------------
Developer → VOC Bodies & Certifications lists every claim in the library against
``aux_11__voc_certifications.json``. Seven spellings resolved to nothing. Three of
them were real claims the catalogue was simply missing (Italian CAM, EU Taxonomy
DNSH, a bare emission test report) and have been added to the catalogue; the
rest are handled here, in the data:

    LEED v4 / v4.1 BETA Low-Emitting Materials Attestation   (47 rows)
    LEED v4.1 BETA Low-Emitting Materials Attestation        (6 rows)
        → "LEED v4.1 Low-Emitting Materials Attestation". The BETA belongs to
          the v4.1 credit, and both spellings describe the same evidence
          package. Both are kept as aliases in the catalogue, so incoming data
          that still uses them resolves without another migration.

    EU Taxonomy DNSH Declaration / VOC limits declaration    (1 row)
        → "EU Taxonomy DNSH VOC Declaration", the catalogue's label for it.

    LEED Low-Emitting Materials Declaration                  (1 row)
        → "VOC Emissions Self-Declaration" plus LEED pathway "Inherently
          Non-Emitting". The row is a manufacturer declaration whose test
          standard reads "LEED v4 / v4.1 (Non-emissive materials exemption)",
          so it claims the exemption, not an attestation of testing.

    Bureau Veritas Laboratoires                              (1 row)
        → the certification and the body are swapped: the claim is the French
          VOC Label (A+) and Bureau Veritas is the laboratory. Swapped back.

Rows are matched on value (and on ``0__EETRA_ID`` for the two single-row fixes),
and records are appended to ``edits_data.parquet`` exactly as the Add/Edit page
would. Only rows that still need a change get a record, so re-running is a no-op.

Usage
-----
    python 04_tools/17_voc_cert_spelling_fixes.py            # dry run
    python 04_tools/17_voc_cert_spelling_fixes.py --apply    # write
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

BASE_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

CERT = "VO__VOC_Cert"
BODY = "VO__VOC_Body"
PATHWAY = "VO__LEED_Pathway"

EDIT_USER = "voc_cert_spelling_fixes"

# Whole-value rewrites: {current VO__VOC_Cert: (new value, why)}
VALUE_FIXES: dict[str, tuple[str, str]] = {
    "LEED v4 / v4.1 BETA Low-Emitting Materials Attestation": (
        "LEED v4.1 Low-Emitting Materials Attestation", "BETA spelling of the v4.1 credit"),
    "LEED v4.1 BETA Low-Emitting Materials Attestation": (
        "LEED v4.1 Low-Emitting Materials Attestation", "BETA spelling of the v4.1 credit"),
    "EU Taxonomy DNSH Declaration / VOC limits declaration": (
        "EU Taxonomy DNSH VOC Declaration", "catalogue label for the DNSH declaration"),
}

# Row fixes: {EETRA ID: ({column: new value}, why)}
ROW_FIXES: dict[str, tuple[dict[str, str], str]] = {
    "TIL__POR__1520": (
        {CERT: "VOC Emissions Self-Declaration", PATHWAY: "Inherently Non-Emitting"},
        "self-declared non-emissive exemption, not an attestation",
    ),
    "INS__FIB__0439": (
        {CERT: "French VOC Label (A+)", BODY: "Bureau Veritas Laboratoires"},
        "certification and body were swapped",
    ),
}

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


def _current(row, col: str) -> str:
    value = row.get(col) if hasattr(row, "get") else None
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the records (default is a dry run)")
    args = ap.parse_args()

    df = _effective_dataset()
    if CERT not in df.columns:
        print(f"⚠️  {CERT} is absent from the dataset — nothing to do.")
        return 1

    # column → {row index: new value}
    changes: dict[int, dict[str, str]] = {}
    reasons: list[tuple[str, str, int, str]] = []

    certs = df[CERT].astype(str).str.strip()
    for old, (new, why) in VALUE_FIXES.items():
        hits = df.index[certs == old]
        if len(hits):
            reasons.append((old, new, len(hits), why))
        for idx in hits:
            changes.setdefault(idx, {})[CERT] = new

    ids = df["0__EETRA_ID"].astype(str).str.strip()
    for eid, (updates, why) in ROW_FIXES.items():
        hits = df.index[ids == eid]
        if not len(hits):
            print(f"⚠️  {eid} is not in the dataset — row fix skipped.")
            continue
        for idx in hits:
            pending = {c: v for c, v in updates.items() if _current(df.loc[idx], c) != v}
            if pending:
                changes.setdefault(idx, {}).update(pending)
                reasons.append((eid, ", ".join(f"{c.split('__')[-1]}={v}" for c, v in pending.items()),
                                1, why))

    print(f"Effective dataset: {len(df)} rows\n")
    for old, new, n, why in reasons:
        print(f"  {n:3d}  {old[:56]:58s} → {new[:46]:48s} ({why})")
    print(f"\nRows to update: {len(changes)}")

    if not changes:
        print("Nothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to edits_data.parquet.")
        return 0

    records = df.loc[list(changes)].copy()
    # VO__LEED_Pathway is new: it lives in the overlay until a row carries it,
    # so create the column before writing into it.
    for col in {c for updates in changes.values() for c in updates}:
        if col not in records.columns:
            records[col] = pd.Series([pd.NA] * len(records), dtype="string", index=records.index)
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
