"""One-off / repeatable: copy base_data + edits_data parquet into Neon.

    python 04_tools/15_parquet_to_neon.py              # upload both, then verify
    python 04_tools/15_parquet_to_neon.py --dry-run    # only report
    python 04_tools/15_parquet_to_neon.py --base-only
    python 04_tools/15_parquet_to_neon.py --edits-only

Connection string: env NEON_DATABASE_URL, else ``[neon] database_url`` in
.streamlit/secrets.toml.

Safe to re-run:
  • edits — rows already in Neon (same ``_edit_id``) are skipped
  • base  — always replaced wholesale (matches a fresh Excel → parquet refresh)

The local parquet files are never modified. After ``03_excel_to_parquet.py``
rebuilds base_data.parquet, re-run this script (or ``--base-only``) so Neon
matches.
"""
import argparse, os, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402


def _url() -> str:
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        sec = ROOT / ".streamlit" / "secrets.toml"
        if sec.exists():
            url = tomllib.loads(sec.read_text(encoding="utf-8")).get("neon", {}).get("database_url")
    if not url:
        sys.exit("No Neon connection string: set NEON_DATABASE_URL or [neon] database_url in secrets.toml")
    return url


def _upload_edits(nn, dry_run: bool) -> None:
    from libs.lib_data import EDIT_AUDIT_COLS, _DEFAULT_EDITS_PARQUET

    path = ROOT / _DEFAULT_EDITS_PARQUET
    if not path.exists():
        print(f"edit log: no file at {path} — skipped")
        return
    edits = pd.read_parquet(path)
    with nn._conn() as conn:
        have = {r[0] for r in conn.execute("select edit_id from matlib_edits")}
    todo = edits[~edits["_edit_id"].astype("int64").isin(have)] if len(edits) else edits
    print(f"edit log: {len(edits)} in parquet, {len(have)} in Neon, {len(todo)} to upload")
    if dry_run or todo.empty:
        return
    for i in range(0, len(todo), 200):
        chunk = todo.iloc[i:i + 200]
        nn.append_edits(chunk.astype(object).where(chunk.notna(), None).to_dict("records"), EDIT_AUDIT_COLS)


def _verify_edits(nn) -> None:
    from libs.lib_data import EDIT_AUDIT_COLS, _DEFAULT_EDITS_PARQUET

    path = ROOT / _DEFAULT_EDITS_PARQUET
    if not path.exists():
        return
    edits = pd.read_parquet(path)
    got = nn.load_edits(EDIT_AUDIT_COLS).set_index("_edit_id")
    exp = edits.set_index("_edit_id")
    assert set(got.index) == set(exp.index), "edit ids differ"
    norm = lambda df: df.reindex(index=sorted(exp.index), columns=sorted(exp.columns)).astype("string").fillna("<NA>")
    g, e = norm(got), norm(exp)
    for c in nn._NUMERIC_COLS:
        if c in e.columns:
            g[c] = pd.to_numeric(got[c].reindex(g.index), errors="coerce").astype("string").fillna("<NA>")
            e[c] = pd.to_numeric(exp[c].reindex(e.index), errors="coerce").astype("string").fillna("<NA>")
    bad = (g != e).sum().loc[lambda s: s > 0]
    assert bad.empty, f"edit value mismatch in columns: {bad.to_dict()}"
    print(f"verified edits: {len(got)} records, {len(exp.columns)} columns identical in Neon")


def _upload_base(nn, dry_run: bool) -> None:
    from libs.lib_data import _DEFAULT_BASE_PARQUET

    path = ROOT / _DEFAULT_BASE_PARQUET
    if not path.exists():
        print(f"base: no file at {path} — skipped")
        return
    base = pd.read_parquet(path)
    with nn._conn() as conn:
        have = conn.execute("select count(*) from matlib_base").fetchone()[0]
    print(f"base: {len(base)} in parquet, {have} in Neon — will replace")
    if dry_run:
        return
    n = nn.replace_base(base)
    print(f"base: uploaded {n} rows")


def _verify_base(nn) -> None:
    from libs.lib_data import _DEFAULT_BASE_PARQUET

    path = ROOT / _DEFAULT_BASE_PARQUET
    if not path.exists():
        return
    exp = pd.read_parquet(path)
    exp["0__EETRA_ID"] = exp["0__EETRA_ID"].astype(str)
    exp = exp.set_index("0__EETRA_ID", drop=False)
    got = nn.load_base()
    got["0__EETRA_ID"] = got["0__EETRA_ID"].astype(str)
    got = got.set_index("0__EETRA_ID", drop=False)
    assert set(got.index) == set(exp.index), (
        f"base ids differ: +{len(set(got.index) - set(exp.index))} "
        f"-{len(set(exp.index) - set(got.index))}"
    )
    # Compare cell text after aligning columns; Float64 round-trips via JSON number.
    cols = [c for c in exp.columns if c in got.columns]
    g = got.reindex(index=exp.index, columns=cols)
    e = exp.reindex(columns=cols)

    def _cell(v):
        if v is None or v is pd.NA:
            return "<NA>"
        try:
            if pd.isna(v):
                return "<NA>"
        except (TypeError, ValueError):
            pass
        if isinstance(v, float):
            return f"{v:.10g}"
        return str(v)

    mismatches = []
    for c in cols:
        for eid in e.index:
            if _cell(g.at[eid, c]) != _cell(e.at[eid, c]):
                mismatches.append((eid, c, e.at[eid, c], g.at[eid, c]))
                if len(mismatches) >= 20:
                    break
        if len(mismatches) >= 20:
            break
    assert not mismatches, f"base value mismatch (showing up to 20): {mismatches}"
    print(f"verified base: {len(got)} rows, {len(cols)} columns identical in Neon")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-only", action="store_true")
    ap.add_argument("--edits-only", action="store_true")
    args = ap.parse_args()
    if args.base_only and args.edits_only:
        sys.exit("use only one of --base-only / --edits-only")
    os.environ["NEON_DATABASE_URL"] = _url()

    from libs import lib_neon as nn

    do_base = not args.edits_only
    do_edits = not args.base_only

    if do_base:
        _upload_base(nn, args.dry_run)
    if do_edits:
        _upload_edits(nn, args.dry_run)

    if args.dry_run:
        return

    if do_base:
        _verify_base(nn)
    if do_edits:
        _verify_edits(nn)


if __name__ == "__main__":
    main()
