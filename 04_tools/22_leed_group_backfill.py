"""
22_leed_group_backfill.py — fill ``VO__LEED_Group`` on the rows that can be
resolved without a judgement call.

Why this exists
---------------
``VO__LEED_Group`` is the first step of the LEED v4.1 Low-Emitting Materials
hierarchy (aux_17__leed_low_emitting.json): the group decides which requirements
a product must demonstrate, so nothing downstream can be evaluated until it is
set. The dataset already carries ``VO__Product_Category``, but it is a free
field whose most common value — ``Ceilings/Walls/Insulation`` — spans three LEED
groups at once, so it cannot simply be renamed.

Two passes, both conservative:

1. ``VO__Product_Category`` values that map one-to-one onto a LEED group.
2. for the combined ``Ceilings/Walls/Insulation`` rows, ``D__ProductType_ENG``,
   but only for the product types that sit squarely inside one group.

Anything else is left empty on purpose. Masonry blocks, screeds, mortars and
concrete repair products are excluded: LEED's Wall panels scope leaves out
vertical structural elements, and a wrong group would produce a confident but
wrong compliance verdict in the Add/Edit form. Those rows are reported at the
end so they can be assigned by hand.

The result is written to the append-only edit log the app merges on read — Neon
when the edit log lives there (``lib_neon.edits_use_neon``), otherwise
``01_data/edits_data.parquet`` — so re-running ``03_excel_to_parquet.py`` cannot
clobber it, and a row that already carries a group is left alone (re-running is
a no-op).

Usage
-----
    python 04_tools/22_leed_group_backfill.py              # dry run
    python 04_tools/22_leed_group_backfill.py --apply      # write where the app reads
    python 04_tools/22_leed_group_backfill.py --apply --parquet   # force the local file
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

from libs.lib_leed_voc import leed_group, leed_pathway_for_group  # noqa: E402

BASE_PATH = _PROJECT_ROOT / "01_data" / "base_data.parquet"
EDITS_PATH = _PROJECT_ROOT / "01_data" / "edits_data.parquet"

GROUP_COL = "VO__LEED_Group"
PATHWAY_COL = "VO__LEED_Pathway"
CATEGORY_COL = "VO__Product_Category"
PRODUCT_TYPE_COL = "D__ProductType_ENG"
EDIT_USER = "leed_group_backfill"

# The combined value that pass 2 reads product types for.
COMBINED = "ceilings/walls/insulation"

# Pass 1 — VO__Product_Category → LEED group name (keys lower-cased).
BY_CATEGORY: dict[str, str] = {
    "flooring": "Flooring",
    "flooring products": "Flooring",
    "modular tile": "Flooring",
    "paints & coatings": "Paints and coatings",
    "adhesives & sealants": "Adhesives and sealants",
    "plasterboards": "Wall panels",
    "plasterboeards": "Wall panels",  # spelling as it stands in the data
    "non-wooden panels": "Wall panels",
}

# Pass 2 — D__ProductType_ENG → LEED group, for the combined category only.
BY_PRODUCT_TYPE: dict[str, str] = {
    "insulation": "Insulation",
    "building boards": "Wall panels",
    "suspended ceiling": "Ceilings",
    "plaster (render)": "Wall panels",
    "plaster (skim)": "Wall panels",
    "adhesive (tile)": "Adhesives and sealants",
}

EDIT_AUDIT_COLS = ("_edit_id", "_edit_ts", "_edit_user", "_edit_op")

_EMPTY = frozenset({"", "-", "nan", "none", "<na>", "*", "n/a", "n/r"})


def _cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _is_empty(value) -> bool:
    return _cell(value).lower() in _EMPTY


def _resolve(row) -> str:
    """The LEED group name for one row, or "" when it needs a human."""
    category = _cell(row.get(CATEGORY_COL)).lower()
    hit = BY_CATEGORY.get(category)
    if hit:
        return hit
    if category == COMBINED:
        return BY_PRODUCT_TYPE.get(_cell(row.get(PRODUCT_TYPE_COL)).lower(), "")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the records (default: dry run)")
    ap.add_argument("--parquet", action="store_true",
                    help="write to 01_data/edits_data.parquet even when the log lives in Neon")
    args = ap.parse_args()

    from libs.lib_data import fn158_load_effective_live_dataframe
    from libs.lib_neon import edits_use_neon

    to_neon = edits_use_neon() and not args.parquet
    df = fn158_load_effective_live_dataframe()
    if CATEGORY_COL not in df.columns:
        print(f"✘ {CATEGORY_COL} is not in the dataset — nothing to map from.")
        return 1

    resolved: list[tuple[int, str]] = []
    for idx, row in df.iterrows():
        if GROUP_COL in df.columns and not _is_empty(row.get(GROUP_COL)):
            continue  # already assigned by hand or by an earlier run
        group = _resolve(row)
        if group:
            resolved.append((idx, group))

    if not resolved:
        print("Nothing to fill — every row either has a group already or needs a human.")
        return 0

    counts = pd.Series([g for _i, g in resolved]).value_counts()
    print(f"Rows that can be filled: {len(resolved)}\n")
    print(counts.to_string())

    # What is deliberately left open, so it can be worked through by hand.
    open_rows = df.loc[
        [i for i in df.index if i not in {i for i, _g in resolved}]
    ]
    if GROUP_COL in open_rows.columns:
        open_rows = open_rows[open_rows[GROUP_COL].map(_is_empty)]
    voc_rows = open_rows[~open_rows[CATEGORY_COL].map(_is_empty)]
    if len(voc_rows):
        print(f"\nLeft for manual assignment (VOC category set, group not resolvable): {len(voc_rows)}")
        print(
            voc_rows.groupby(
                [voc_rows[CATEGORY_COL].map(_cell), voc_rows[PRODUCT_TYPE_COL].map(_cell)]
            ).size().sort_values(ascending=False).head(20).to_string()
        )

    target = "Neon (matlib_edits)" if to_neon else str(EDITS_PATH.relative_to(_PROJECT_ROOT))
    if not args.apply:
        print(f"\nDry run — pass --apply to write to {target}.")
        return 0

    records = df.loc[[i for i, _g in resolved]].copy()
    records[GROUP_COL] = [g for _i, g in resolved]
    # The pathway follows from the group; writing it here keeps the stored value
    # in step with what the form derives and shows read-only.
    records[PATHWAY_COL] = [leed_pathway_for_group(leed_group(g)) for _i, g in resolved]

    stamp = pd.Timestamp.utcnow().isoformat()
    base_ns = time.time_ns()
    records["_edit_id"] = [f"{base_ns + i:d}" for i in range(len(records))]
    records["_edit_ts"] = stamp
    records["_edit_user"] = EDIT_USER
    records["_edit_op"] = "update"

    if to_neon:
        from libs.lib_neon import append_edits

        append_edits(records.to_dict("records"), EDIT_AUDIT_COLS)
        print(f"\n✅ Wrote {len(records)} records → {target}.")
        return 0

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
    os.replace(tmp, EDITS_PATH)
    print(
        f"\n✅ Wrote {len(records)} records → {EDITS_PATH.relative_to(_PROJECT_ROOT)} "
        f"({len(combined)} rows in the log)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
