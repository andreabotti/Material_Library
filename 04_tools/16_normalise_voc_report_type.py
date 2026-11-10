"""
16_normalise_voc_report_type.py — collapse ``VO__ReportType`` onto the four
agreed values.

Why this exists
---------------
``VO__ReportType`` grew by free text: the effective dataset holds 14 spellings
of what are really four answers, most of them casing variants of "Third Party
Verified" (358 rows). The dropdown in Add/Edit is built from the distinct values
present in the data (``_distinct_field_options``), so the field cannot be tidied
from the UI side — the data has to be normalised first.

Target vocabulary
-----------------
    Third-party Certification   a named scheme certified the product
    Third-party Test Report     an accredited lab tested it; no certification
    Self-Declaration            the manufacturer states it
    n/a                         could carry a claim, none available
    n/r                         VOC testing is not relevant for this product

The hard case is "Third Party Verified", which does not say whether a
certification or a test report is behind it. It is resolved from
``VO__VOC_Cert`` against the tiers of ``aux_11__voc_certifications.json``:

    third_party tier          → Third-party Certification
    regulatory tier           → Third-party Test Report
    rating_systems tier       → Third-party Test Report
    self_declarations tier    → Self-Declaration
    unmatched                 → Third-party Test Report

The regulatory and rating-system tiers are deliberately *not* certifications:
the catalogue's own text calls AgBB a "compliance statement, not a
certification", and the French VOC label is self-applied by the manufacturer on
the basis of an accredited lab report. Unmatched values fall back to the test
report, the weaker of the two claims, so this tool never upgrades evidence it
cannot see.

Rows reading ``n/r``, ``n/a``, ``*`` or nothing at all are left untouched.

Like 12_voc_not_relevant_override.py, this writes full-row snapshots into
``edits_data.parquet`` — the append-only overlay the app merges on read — so
re-running 03_excel_to_parquet.py cannot clobber it, and only rows that
actually change get a record (re-running is a no-op).

Usage
-----
    python 04_tools/16_normalise_voc_report_type.py            # dry run
    python 04_tools/16_normalise_voc_report_type.py --apply    # write
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import warnings

import pandas as pd

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

BASE_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"
CATALOG_PATH = _PROJECT_ROOT / "aux_11__voc_certifications.json"

COL = "VO__ReportType"
CERT_COL = "VO__VOC_Cert"

EDIT_USER = "voc_report_type_normalise"

CERTIFICATION = "Third-party Certification"
TEST_REPORT = "Third-party Test Report"
SELF_DECLARATION = "Self-Declaration"

# Values that mean "no answer to give" and are left exactly as they are.
_LEAVE_ALONE = {"n/r", "nr", "n/a", "na", "*", "", "nan", "none", "<na>", "-"}

# Tier → report type for the "Third Party Verified" family (see module docstring).
_TIER_VERDICT = {
    "third_party": CERTIFICATION,
    "regulatory": TEST_REPORT,
    "rating_systems": TEST_REPORT,
    "self_declarations": SELF_DECLARATION,
}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def _is_blank(value) -> bool:
    """True for None / NaN / pandas NA, without tripping over NA truthiness."""
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_placeholder(value) -> bool:
    """True for n/r, n/a, ``*`` and blanks — tested before _norm, which would
    turn "n/r" into "n r" and no longer match the placeholder set."""
    if _is_blank(value):
        return True
    return str(value).strip().lower() in _LEAVE_ALONE


def _norm(value) -> str:
    """Lowercase, punctuation to spaces, known typos folded in."""
    if value is None or (isinstance(value, float) and value != value) or value is pd.NA:
        return ""
    t = unicodedata.normalize("NFKC", str(value))
    t = t.replace("\xa0", " ").replace("​", "").replace("﻿", "")
    t = t.lower()
    # "Greengaurd Gold" appears 19 times; fold it so the catalogue matches.
    t = t.replace("greengaurd", "greenguard")
    t = re.sub(r"[^a-z0-9+]+", " ", t)
    return " ".join(t.split())


def _load_tier_phrases() -> list[tuple[str, str]]:
    """(normalised label or alias, tier id), longest first so EC1PLUS beats EC1."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for tier in catalog["tiers"]:
        if tier["id"] not in _TIER_VERDICT:
            continue  # the "status" tier (n/a, n/r) says nothing about evidence
        for entry in tier["entries"]:
            for phrase in [entry["label"], *entry.get("aliases", [])]:
                normalised = _norm(phrase)
                if normalised:
                    out.append((normalised, tier["id"]))
    out.sort(key=lambda pair: len(pair[0]), reverse=True)
    return out


_TIER_PHRASES = _load_tier_phrases()

# Wording that settles the tier before any scheme name is looked for. A value
# like "LEED v4.1 BETA Low-Emitting Materials Attestation" names no scheme but
# is plainly an attestation, not a certificate.
_WORDING_TIER = (
    (re.compile(r"\bself[\s-]*declar"), "self_declarations"),
    (re.compile(r"\bleed\b"), "rating_systems"),
    (re.compile(r"\battestation\b|\bcompliance\b|\bdeclaration\b|\btest report\b"), "regulatory"),
)


def _verdict_from_cert(cert) -> tuple[str, str]:
    """(report type, why) for a third-party-family row, from its VOC claim."""
    if _is_placeholder(cert):
        return TEST_REPORT, "no VOC claim recorded"
    text = _norm(cert)
    if not text:
        return TEST_REPORT, "no VOC claim recorded"
    for pattern, tier in _WORDING_TIER:
        if pattern.search(text):
            return _TIER_VERDICT[tier], f"wording → {tier}"
    for phrase, tier in _TIER_PHRASES:
        if phrase in text:
            return _TIER_VERDICT[tier], f"{phrase} → {tier}"
    return TEST_REPORT, "unmatched VOC claim"


def _target(report_type, cert) -> tuple[str | None, str]:
    """(new value or None when unchanged, reason)."""
    if _is_placeholder(report_type):
        return None, "left alone"
    raw = str(report_type).strip()
    text = _norm(raw)
    if raw in (CERTIFICATION, TEST_REPORT, SELF_DECLARATION):
        return None, "already canonical"
    if re.search(r"\bself\b|\bmanufactur\w*\s+declar|\bdeclared\b", text):
        return SELF_DECLARATION, "self-declared wording"
    if "tested but not certified" in text:
        return TEST_REPORT, "tested but not certified"
    if text.startswith("third"):
        return _verdict_from_cert(cert)
    return _verdict_from_cert(cert)


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

    targets: dict = {}
    reasons: dict = {}
    for idx, row in df[[COL, CERT_COL]].iterrows():
        new, why = _target(row[COL], row[CERT_COL])
        if new is not None and new != str(row[COL]).strip():
            targets[idx] = new
            reasons[idx] = why

    print(f"Effective dataset: {len(df)} rows")
    print(f"Distinct {COL} values before: {df[COL].dropna().nunique()}\n")

    if targets:
        moves = pd.DataFrame({
            "from": df.loc[list(targets), COL].astype(str).values,
            "to": list(targets.values()),
            "why": [reasons[i] for i in targets],
        })
        print(moves.groupby(["from", "to", "why"]).size()
                   .sort_values(ascending=False).to_string())

    after = df[COL].astype(str).copy()
    for idx, new in targets.items():
        after.loc[idx] = new
    print(f"\nRows to update: {len(targets)}")
    print("\nDistinct values after:")
    print(after.where(df[COL].notna()).value_counts().to_string())

    if not targets:
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to edits_data.parquet.")
        return 0

    records = df.loc[list(targets)].copy()
    records[COL] = [targets[i] for i in records.index]

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
