"""
EETRA MatLib — database completeness & quality inspection

Usage:
    python tools/04_db_inspection.py                        # reads 01_data/base_data.parquet
    python tools/04_db_inspection.py --excel                # reads directly from Excel
    python tools/04_db_inspection.py --out report.html      # custom HTML output path

Produces:
    • console summary (always)
    • tools/db_inspection_report.html (unless --no-html)

Column-prefix convention used throughout:
    0__  identifiers
    A__  product / manufacturer info
    D__  classification & content descriptors
    E__  environmental & EPD metadata
    G__  GWP lifecycle values
    P__  physical properties
    R__  recycling
    S__  comments / notes
    U__  URLs + unit declarations
    VO__ VOC (emissions certificates)
    VV__ Various (CAM, LEED, MSDS, DOP, …)
"""
import argparse
import html as _html
import pathlib
import sys
from collections import defaultdict
from datetime import datetime

import math
import pandas as pd

# ── paths ─────────────────────────────────────────────────────────────────────
_ROOT        = pathlib.Path(__file__).resolve().parent.parent
PARQUET_PATH = _ROOT / "01_data" / "base_data.parquet"
EXCEL_PATH   = (
    r"E:\0D_OneDrive\EETRA srl SB\05_Ricerca e Sviluppo - Documenti"
    r"\RES12__EETRA_MaterialLIbrary\EETRA_MaterialLibrary.xlsx"
)
EXCEL_SHEET  = "_live_data"
DEFAULT_HTML = pathlib.Path(__file__).resolve().parent / "db_inspection_report.html"

# ── column-prefix metadata ────────────────────────────────────────────────────
PREFIX_LABEL = {
    "0":  "Identifiers",
    "A":  "Product / Manufacturer",
    "D":  "Classification",
    "E":  "Environmental / EPD",
    "G":  "GWP Lifecycle",
    "P":  "Physical Properties",
    "R":  "Recycling",
    "S":  "Comments",
    "U":  "URLs & Units",
    "VO": "VOC",
    "VV": "Various (CAM / LEED / MSDS / DOP)",
}

# Columns where emptiness is acceptable (optional fields)
OPTIONAL_COLS = {
    "A__ProductDescription", "A__Map_yn",
    "D__Additions", "D__Strength",
    "E__ManuPlant", "E__L_WmK", "E__EPD_DecNumber",
    "E__Rvalue", "E__EPD_MultFactor", "E__EPD_ConvFactor", "E__EPD_kg-FU",
    "G__GWP_A4", "G__GWP_A5", "G__GWP_C4", "G__GWP_D", "G__GWP_A1A3_m3",
    "G__GWP_A1", "G__GWP_A2", "G__GWP_A3",
    "G__GWP_B1", "G__GWP_B2", "G__GWP_B3", "G__GWP_B4",
    "G__GWP_B5", "G__GWP_B6", "G__GWP_B7", "G__GWP_C1", "G__GWP_C2", "G__GWP_C3",
    "G__GWP_A1A3_kg", "G__GWP_A1A3_m2", "G__GWP_A1A3_m2R1",
    "P__Mass_kgm2", "P__Thick_mm",
    "R__Rec_Reco_ByProd_URL",
    "S__Comments",
    "VV__DOP", "VO__VOC_Cert", "VO__VOC_URL", "VO__Exp_Date",
    "VO__Application_Scope", "VO__Product_Category", "VV__Other",
    "VV__MSDS__URL", "VV__CAM__Evidence", "VV__LEED_MR_RawMat",
}

# Columns expected to hold HTTP URLs
URL_COLS = {
    "U__Img_URL", "U__ProductInfo_URL", "U__TechDetails_URL",
    "E__EPD_URL", "VO__VOC_URL", "VV__DOP", "VV__MSDS__URL",
    "R__Rec_Reco_ByProd_URL",
}

# Cross-metric definitions: (label, set of columns that must all be non-empty)
CROSS_METRICS = [
    ("Has image URL",           {"U__Img_URL"}),
    ("Has EPD (any number)",    {"E__EPD_RegNumber"}),
    ("Has EPD URL",             {"E__EPD_URL"}),
    ("Has GWP A1-A3",           {"G__GWP_A1A3"}),
    ("Has full GWP (A1-A3+A4+A5+C4+D)", {"G__GWP_A1A3", "G__GWP_A4", "G__GWP_A5", "G__GWP_C4", "G__GWP_D"}),
    ("Has lambda (conductivity)", {"P__L_WmK"}),
    ("Has density (kg/m³)",      {"P__Mass_kgm3"}),
    ("Has tech-sheet PDF",       {"U__TechDetails_URL"}),
    ("Has VOC data",             {"VO__VOC_Body"}),
    ("Has VOC cert URL",         {"VO__VOC_URL"}),
    ("Has CAM compliance",       {"VV__CAM__Status"}),
    ("Has product URL",          {"U__ProductInfo_URL"}),
    ("Has manufacturer country", {"E__ManuCountry"}),
    ("EPD + image + GWP (complete card)", {"E__EPD_RegNumber", "U__Img_URL", "G__GWP_A1A3"}),
]

TOP_N_CATEGORICAL = 12   # top N values shown for categorical columns
MAX_CATEGORICAL_UNIQUE = 60  # columns with more unique values are treated as free-text

# ── palette ───────────────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

def _rate_color(r: float) -> str:
    if r >= 0.90: return _GREEN
    if r >= 0.60: return _YELLOW
    return _RED

def _rate_html_class(r: float) -> str:
    if r >= 0.90: return "good"
    if r >= 0.60: return "warn"
    return "bad"


# ===== DATA LOADING ===========================================================

def _is_empty(s: pd.Series) -> pd.Series:
    """True where a cell is missing or a blank-equivalent string."""
    empty_str = s.astype(str).str.strip().isin({"", "-", "–", "—", "n/a", "N/A", "nan", "None", "none"})
    return s.isna() | empty_str


def load_data(use_excel: bool = False) -> pd.DataFrame:
    if use_excel:
        print(f"Reading Excel: {EXCEL_PATH}")
        df = pd.read_excel(EXCEL_PATH, sheet_name=EXCEL_SHEET)
    else:
        if not PARQUET_PATH.exists():
            print(f"Parquet not found: {PARQUET_PATH}\nRun 03_excel_to_parquet.py first, or use --excel.")
            sys.exit(1)
        print(f"Reading Parquet: {PARQUET_PATH}")
        df = pd.read_parquet(PARQUET_PATH)

    # ── column cleanup (mirrors fn122_clean_dataframe in lib_data.py) ─────────
    # 1. Drop *-marker columns (Excel section separators)
    star_cols = [c for c in df.columns if str(c).strip().startswith("*") or
                 str(c).strip() in ("*", "*.1", "*.2", "*.3", "*.4")]
    if star_cols:
        df = df.drop(columns=star_cols)
    # 2. Drop Unnamed / blank columns
    unnamed = [c for c in df.columns if str(c).strip() == "" or
               str(c).strip().lower().startswith("unnamed")]
    if unnamed:
        df = df.drop(columns=unnamed)
    # 3. Keep only columns that follow the X__ convention (real data columns)
    known_cols = [c for c in df.columns if "__" in str(c)]
    df = df[known_cols] if known_cols else df
    # (no column truncation: inspect all X__ columns in the database)

    # ── row cleanup ────────────────────────────────────────────────────────────
    df = df.dropna(how="all")
    # Drop rows where ProductName AND Manufacturer are both empty
    _nm = "A__ProductName"
    _mn = "A__Manufacturer"
    if _nm in df.columns and _mn in df.columns:
        bad = _is_empty(df[_nm]) & _is_empty(df[_mn])
        df = df[~bad]
    # Drop section-header rows (contain * as first non-empty value)
    _cands = [c for c in df.columns if str(c).startswith(
        ("A__", "B__", "D__", "E__", "G__", "P__"))]
    if _cands:
        star_rows = df[_cands].astype(str).apply(
            lambda s: s.str.strip().str.startswith("*")).any(axis=1)
        df = df[~star_rows]

    return df.reset_index(drop=True)


# ===== METRICS ================================================================

def col_prefix(col: str) -> str:
    return col.split("__")[0] if "__" in col else "?"


def column_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column completeness and basic stats."""
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        empty_mask = _is_empty(s)
        filled     = int((~empty_mask).sum())
        fill_rate  = filled / n if n else 0
        n_unique   = int(s[~empty_mask].nunique())
        is_url_col = col in URL_COLS

        # URL validity (among filled cells)
        url_valid_rate = None
        if is_url_col:
            non_empty = s[~empty_mask].astype(str)
            url_valid_rate = float((non_empty.str.startswith("http")).mean()) if len(non_empty) else None

        # Numeric stats
        num_min = num_max = num_mean = num_median = None
        if pd.api.types.is_numeric_dtype(s):
            vals = pd.to_numeric(s, errors="coerce").dropna()
            if len(vals):
                num_min    = float(vals.min())
                num_max    = float(vals.max())
                num_mean   = float(vals.mean())
                num_median = float(vals.median())

        rows.append({
            "column":         col,
            "prefix":         col_prefix(col),
            "filled":         filled,
            "total":          n,
            "fill_rate":      fill_rate,
            "n_unique":       n_unique,
            "optional":       col in OPTIONAL_COLS,
            "is_url":         is_url_col,
            "url_valid_rate": url_valid_rate,
            "num_min":        num_min,
            "num_max":        num_max,
            "num_mean":       num_mean,
            "num_median":     num_median,
        })
    return pd.DataFrame(rows)


def value_frequencies(df: pd.DataFrame, stats: pd.DataFrame) -> dict[str, pd.Series]:
    """Top-N value counts for categorical columns."""
    result = {}
    for _, row in stats.iterrows():
        col = row["column"]
        if row["is_url"] or row["n_unique"] > MAX_CATEGORICAL_UNIQUE:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        if row["n_unique"] == 0:
            continue
        s = df[col][~_is_empty(df[col])]
        vc = s.astype(str).value_counts(normalize=True).head(TOP_N_CATEGORICAL)
        result[col] = vc
    return result


def cross_metrics(df: pd.DataFrame) -> list[tuple[str, int, float]]:
    """(label, count, fraction) for each cross-metric definition."""
    n = len(df)
    out = []
    for label, cols in CROSS_METRICS:
        present_cols = [c for c in cols if c in df.columns]
        if not present_cols:
            out.append((label, 0, 0.0, "— column missing"))
            continue
        mask = pd.Series([True] * n, index=df.index)
        for c in present_cols:
            mask &= ~_is_empty(df[c])
        count = int(mask.sum())
        out.append((label, count, count / n if n else 0.0, ""))
    return out


def group_summary(stats: pd.DataFrame) -> pd.DataFrame:
    """Average fill rate per prefix group, split by required vs optional."""
    rows = []
    for pfx, grp in stats.groupby("prefix"):
        label = PREFIX_LABEL.get(pfx, pfx)
        req   = grp[~grp["optional"]]
        opt   = grp[grp["optional"]]
        rows.append({
            "prefix":    pfx,
            "label":     label,
            "n_cols":    len(grp),
            "req_fill":  float(req["fill_rate"].mean()) if len(req) else None,
            "opt_fill":  float(opt["fill_rate"].mean()) if len(opt) else None,
        })
    return pd.DataFrame(rows).sort_values("prefix")


# ===== CONSOLE OUTPUT =========================================================

def _bar(rate: float, width: int = 20) -> str:
    filled = round(rate * width)
    return "█" * filled + "░" * (width - filled)


def print_report(df: pd.DataFrame, stats: pd.DataFrame, freqs: dict, cross: list, grp: pd.DataFrame) -> None:
    n = len(df)
    sep = "─" * 80

    print(f"\n{_BOLD}{'═'*80}")
    print(f"  EETRA MatLib — Database Inspection   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*80}{_RESET}")
    print(f"  Rows: {n:,}    Columns: {len(df.columns)}")
    if PARQUET_PATH.exists():
        mtime = datetime.fromtimestamp(PARQUET_PATH.stat().st_mtime)
        print(f"  Parquet last written: {mtime.strftime('%Y-%m-%d %H:%M')}")

    # ── group summary ─────────────────────────────────────────────────────────
    print(f"\n{_BOLD}GROUP COMPLETENESS (required columns only){_RESET}")
    print(sep)
    print(f"  {'Prefix':<4}  {'Group':<30}  {'Cols':>4}  {'Req fill':>8}  {'Opt fill':>8}")
    print(sep)
    for _, r in grp.iterrows():
        req_s = f"{r['req_fill']*100:5.1f}%" if r['req_fill'] is not None else "  —   "
        opt_s = f"{r['opt_fill']*100:5.1f}%" if r['opt_fill'] is not None else "  —   "
        req_c = _rate_color(r['req_fill']) if r['req_fill'] is not None else ""
        print(f"  {r['prefix']:<4}  {r['label']:<30}  {r['n_cols']:>4}  {req_c}{req_s}{_RESET}  {opt_s}")

    # ── per-column table ──────────────────────────────────────────────────────
    print(f"\n{_BOLD}PER-COLUMN COMPLETENESS{_RESET}")
    print(sep)
    print(f"  {'Column':<35}  {'Fill':>5}   {'Bar':<20}  {'Uniq':>5}  {'Flag'}")
    print(sep)
    for _, r in stats.iterrows():
        rate = r["fill_rate"]
        col  = r["column"]
        flag = ""
        if r["optional"]:            flag += " optional"
        if r["is_url"] and r["url_valid_rate"] is not None and r["url_valid_rate"] < 1.0:
            bad_pct = (1 - r["url_valid_rate"]) * 100
            flag += f" ⚠ {bad_pct:.0f}% invalid URLs"
        c = _rate_color(rate) if not r["optional"] else ""
        print(f"  {col:<35}  {c}{rate*100:5.1f}%{_RESET}  {_bar(rate)}  {r['n_unique']:>5}{flag}")

    # ── numeric summaries ─────────────────────────────────────────────────────
    num_rows = stats[stats["num_mean"].notna()]
    if len(num_rows):
        print(f"\n{_BOLD}NUMERIC COLUMNS — RANGE & DISTRIBUTION{_RESET}")
        print(sep)
        print(f"  {'Column':<30}  {'Min':>10}  {'Median':>10}  {'Mean':>10}  {'Max':>10}")
        print(sep)
        for _, r in num_rows.iterrows():
            print(
                f"  {r['column']:<30}  "
                f"{r['num_min']:>10.3g}  "
                f"{r['num_median']:>10.3g}  "
                f"{r['num_mean']:>10.3g}  "
                f"{r['num_max']:>10.3g}"
            )

    # ── value frequencies ─────────────────────────────────────────────────────
    print(f"\n{_BOLD}CATEGORICAL VALUE FREQUENCIES{_RESET}")
    for col, vc in freqs.items():
        print(f"\n  {col}")
        for val, pct in vc.items():
            bar = "▪" * round(pct * 30)
            print(f"    {str(val):<40}  {bar:<30}  {pct*100:5.1f}%")

    # ── cross-metrics ─────────────────────────────────────────────────────────
    print(f"\n{_BOLD}CROSS-FIELD COVERAGE{_RESET}")
    print(sep)
    for label, count, frac, note in cross:
        c = _rate_color(frac)
        print(f"  {label:<50}  {c}{count:>5}/{len(df):<5}  {frac*100:5.1f}%{_RESET}  {note}")

    print(f"\n{'═'*80}\n")


# ===== HTML REPORT ============================================================

_HTML_STYLE = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px;
       background: #f5f6fa; color: #222; padding: 24px; }
h1 { font-size: 20px; margin-bottom: 4px; color: #1a1a2e; }
h2 { font-size: 14px; font-weight: 600; color: #444; margin: 28px 0 8px;
     border-bottom: 2px solid #ddd; padding-bottom: 4px; }
.meta { color: #777; font-size: 12px; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 16px;
        background: #fff; border-radius: 6px; overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,.1); }
th { background: #2d3561; color: #fff; padding: 7px 10px; text-align: left;
     font-weight: 600; white-space: nowrap; }
td { padding: 5px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f0f4ff; }
.good { color: #1a7f37; font-weight: 600; }
.warn { color: #b08000; font-weight: 600; }
.bad  { color: #cc2200; font-weight: 600; }
.opt  { color: #888; font-style: italic; }
.bar-wrap { background: #eee; border-radius: 4px; height: 10px; width: 120px; display:inline-block; vertical-align:middle; }
.bar-fill { height: 10px; border-radius: 4px; display:block; }
.bar-good { background: #34a853; }
.bar-warn { background: #fbbc04; }
.bar-bad  { background: #ea4335; }
.freq-bar { display:inline-block; background:#4285f4; height:8px; border-radius:2px; vertical-align:middle; margin-right:4px; }
.section { margin-bottom: 8px; }
.cross-good { background: #e6f4ea; }
.cross-warn { background: #fef9e7; }
.cross-bad  { background: #fce8e6; }
details summary { cursor: pointer; padding: 4px 0; font-weight: 600; color: #2d3561; }
details[open] summary { margin-bottom: 6px; }
</style>
"""

def _pct(r, digits: int = 1) -> str:
    if r is None or (isinstance(r, float) and math.isnan(r)): return "—"
    return f"{r*100:.{digits}f}%"

def _html_bar(rate) -> str:
    if rate is None or (isinstance(rate, float) and math.isnan(rate)): return "—"
    cls = _rate_html_class(rate)
    w   = round(rate * 120)
    return (
        f'<span class="bar-wrap">'
        f'<span class="bar-fill bar-{cls}" style="width:{w}px"></span>'
        f'</span> <span class="{cls}">{_pct(rate)}</span>'
    )

def _freq_bar(pct: float) -> str:
    w = round(pct * 200)
    return f'<span class="freq-bar" style="width:{w}px"></span>'


def build_html(df: pd.DataFrame, stats: pd.DataFrame, freqs: dict, cross: list, grp: pd.DataFrame) -> str:
    n = len(df)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    src = f"Parquet ({PARQUET_PATH})" if PARQUET_PATH.exists() else "Excel"

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>EETRA MatLib — DB Inspection {ts}</title>",
        _HTML_STYLE,
        "</head><body>",
        f"<h1>EETRA MatLib — Database Inspection</h1>",
        f"<p class='meta'>Generated {ts} &nbsp;|&nbsp; Source: {_html.escape(src)}"
        f" &nbsp;|&nbsp; <strong>{n:,}</strong> products &nbsp;|&nbsp; "
        f"<strong>{len(df.columns)}</strong> columns</p>",
    ]

    # ── group summary ─────────────────────────────────────────────────────────
    parts.append("<h2>Group Completeness</h2>")
    parts.append("<table><tr><th>Prefix</th><th>Group</th><th>Columns</th>"
                 "<th>Required fill</th><th>Optional fill</th></tr>")
    for _, r in grp.iterrows():
        req_cls = _rate_html_class(r["req_fill"]) if r["req_fill"] is not None else ""
        parts.append(
            f"<tr>"
            f"<td>{_html.escape(str(r['prefix']))}</td>"
            f"<td>{_html.escape(str(r['label']))}</td>"
            f"<td>{r['n_cols']}</td>"
            f"<td>{_html_bar(r['req_fill']) if r['req_fill'] is not None else '—'}</td>"
            f"<td>{_html_bar(r['opt_fill']) if r['opt_fill'] is not None else '—'}</td>"
            f"</tr>"
        )
    parts.append("</table>")

    # ── per-column table ──────────────────────────────────────────────────────
    parts.append("<h2>Per-Column Completeness</h2>")
    parts.append("<table><tr><th>Column</th><th>Fill rate</th>"
                 "<th>Filled / Total</th><th>Unique values</th><th>Notes</th></tr>")
    for _, r in stats.iterrows():
        rate = r["fill_rate"]
        opt_cls = "opt" if r["optional"] else ""
        notes = []
        if r["optional"]:
            notes.append("optional")
        if r["is_url"] and r["url_valid_rate"] is not None and r["url_valid_rate"] < 1.0:
            bad_n = round((1 - r["url_valid_rate"]) * r["filled"])
            notes.append(f"⚠ {bad_n} invalid URLs")
        bar_html = _html_bar(rate) if not r["optional"] else f'<span class="opt">{_pct(rate)}</span>'
        parts.append(
            f"<tr>"
            f"<td class='{opt_cls}'>{_html.escape(r['column'])}</td>"
            f"<td>{bar_html}</td>"
            f"<td>{r['filled']:,} / {r['total']:,}</td>"
            f"<td>{r['n_unique']:,}</td>"
            f"<td class='opt'>{'; '.join(notes)}</td>"
            f"</tr>"
        )
    parts.append("</table>")

    # ── numeric columns ───────────────────────────────────────────────────────
    num_rows = stats[stats["num_mean"].notna()]
    if len(num_rows):
        parts.append("<h2>Numeric Columns — Range &amp; Distribution</h2>")
        parts.append("<table><tr><th>Column</th><th>Fill</th><th>Min</th>"
                     "<th>Median</th><th>Mean</th><th>Max</th></tr>")
        for _, r in num_rows.iterrows():
            def _fmt(v): return f"{v:.4g}" if v is not None else "—"
            parts.append(
                f"<tr>"
                f"<td>{_html.escape(r['column'])}</td>"
                f"<td>{_pct(r['fill_rate'])}</td>"
                f"<td>{_fmt(r['num_min'])}</td>"
                f"<td>{_fmt(r['num_median'])}</td>"
                f"<td>{_fmt(r['num_mean'])}</td>"
                f"<td>{_fmt(r['num_max'])}</td>"
                f"</tr>"
            )
        parts.append("</table>")

    # ── value frequencies ─────────────────────────────────────────────────────
    parts.append("<h2>Categorical Value Frequencies</h2>")
    for col, vc in freqs.items():
        parts.append(f"<details class='section'><summary>{_html.escape(col)}"
                     f" &nbsp;<small>({len(vc)} top values shown)</small></summary>")
        parts.append("<table><tr><th>Value</th><th>Frequency</th><th>%</th></tr>")
        for val, pct in vc.items():
            bar = _freq_bar(pct)
            parts.append(
                f"<tr><td>{_html.escape(str(val))}</td>"
                f"<td>{bar}</td>"
                f"<td>{pct*100:.1f}%</td></tr>"
            )
        parts.append("</table></details>")

    # ── cross-metrics ─────────────────────────────────────────────────────────
    parts.append("<h2>Cross-Field Coverage</h2>")
    parts.append("<table><tr><th>Metric</th><th>Coverage</th><th>Count</th><th>Notes</th></tr>")
    for label, count, frac, note in cross:
        row_cls = f"cross-{_rate_html_class(frac)}"
        parts.append(
            f"<tr class='{row_cls}'>"
            f"<td>{_html.escape(label)}</td>"
            f"<td>{_html_bar(frac)}</td>"
            f"<td>{count:,} / {n:,}</td>"
            f"<td class='opt'>{_html.escape(note)}</td>"
            f"</tr>"
        )
    parts.append("</table>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ===== ENTRY POINT ============================================================

def main():
    parser = argparse.ArgumentParser(description="EETRA MatLib — DB inspection")
    parser.add_argument("--excel",   action="store_true", help="Read from Excel instead of Parquet")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML report")
    parser.add_argument("--out",     default=str(DEFAULT_HTML), help="HTML output path")
    args = parser.parse_args()

    df    = load_data(use_excel=args.excel)
    stats = column_stats(df)
    freqs = value_frequencies(df, stats)
    cross = cross_metrics(df)
    grp   = group_summary(stats)

    print_report(df, stats, freqs, cross, grp)

    if not args.no_html:
        html_path = pathlib.Path(args.out)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(build_html(df, stats, freqs, cross, grp), encoding="utf-8")
        print(f"HTML report written → {html_path}")


if __name__ == "__main__":
    main()
