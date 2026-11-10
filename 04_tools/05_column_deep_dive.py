"""
EETRA MatLib — per-column deep-dive report
==========================================
Produces one detailed section per column covering:
  • fill rate + null breakdown
  • unique value count
  • for categoricals   : full value_counts with %, anomaly flags
  • for numerics       : min/max/mean/median/std/p5/p95, outlier count, zero/negative counts
  • for URL columns    : domain breakdown, invalid-format count, HTTP vs HTTPS
  • group-level rules  : recycling % sums, GWP sign checks, ID format, EPD date/number consistency

Usage:
    $env:PYTHONUTF8="1"
    python tools/05_column_deep_dive.py                  # reads 01_data/base_data.parquet
    python tools/05_column_deep_dive.py --parquet PATH   # explicit parquet path
    python tools/05_column_deep_dive.py --out report.html

Output: tools/column_deep_dive.html  +  console summary
"""
import argparse
import html as _he
import math
import pathlib
import re
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd

# ── paths ─────────────────────────────────────────────────────────────────────
_ROOT        = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PARQ = _ROOT / "01_data" / "base_data.parquet"
DEFAULT_HTML = pathlib.Path(__file__).resolve().parent / "column_deep_dive.html"

# ── column metadata: (group_label, role, notes) ───────────────────────────────
COL_META: dict[str, tuple[str, str]] = {
    # 0__ identifiers
    "0__EETRA_ID":          ("Identifiers",        "Primary key — format {PT}__{MT}__{NNNN}"),
    "0__NUM":               ("Identifiers",        "4-digit sequential number (global)"),
    # A__ product info
    "A__Manufacturer":      ("Product info",       "Brand / manufacturer name"),
    "A__ProductName":       ("Product info",       "Commercial product name"),
    "A__ProductDescription":("Product info",       "Free-text description"),
    "A__Map_yn":            ("Product info",       "Mapped to project flag (Y/N)"),
    # D__ classification
    "D__ProductType_ENG":   ("Classification",     "Functional product type (English)"),
    "D__MaterialType_ENG":  ("Classification",     "Primary material (English)"),
    "D__MaterialType_ITA":  ("Classification",     "Primary material (Italian)"),
    "D__Int/Ext":           ("Classification",     "Interior / Exterior / Both application scope"),
    "D__Application":       ("Classification",     "Specific application context"),
    "D__Content":           ("Classification",     "Component / ingredient description"),
    "D__Size":              ("Classification",     "Typical product dimensions or range"),
    "D__TechDetails":       ("Classification",     "Key technical detail free text"),
    "D__EN197-1":           ("Classification",     "Cement strength class (EN 197-1)"),
    "D__EN206":             ("Classification",     "Concrete exposure class (EN 206)"),
    "D__DataComments":      ("Classification",     "Data entry provenance / audit note"),
    # S__ status / comments
    "S__Status":            ("Status",             "Data completeness status"),
    "S__Comments":          ("Status",             "Free-text notes"),
    # U__ URLs
    "U__ProductInfo_URL":   ("URLs",               "Manufacturer product page"),
    "U__TechDetails_URL":   ("URLs",               "Technical data sheet PDF"),
    "U__Img_URL":           ("URLs",               "Product photograph"),
    # P__ physical
    "P__U_Wm2K":            ("Physical",           "Thermal transmittance U [W/m²K]"),
    "P__L_WmK":             ("Physical",           "Thermal conductivity λ [W/mK]"),
    "P__Thick_mm":          ("Physical",           "Declared thickness [mm]"),
    "P__Mass_kgm3":         ("Physical",           "Bulk density [kg/m³]"),
    "P__Mass_kgm2":         ("Physical",           "Surface mass [kg/m²]"),
    "P__Mass_kg":           ("Physical",           "Mass per declared unit [kg]"),
    "P__FireRating":        ("Physical",           "Euroclass fire rating (EN 13501-1)"),
    # E__ environmental / EPD
    "E__ManuCountry":       ("Environmental/EPD",  "Country of manufacture"),
    "E__ManuPlant":         ("Environmental/EPD",  "Manufacturing plant name/location"),
    "E__EPD_Y/N":           ("Environmental/EPD",  "EPD available flag (Y/N)"),
    "E__EPD_Programme":     ("Environmental/EPD",  "EPD programme operator"),
    "E__EPD_URL":           ("Environmental/EPD",  "EPD document URL"),
    "E__EPD_DecNumber":     ("Environmental/EPD",  "EPD declaration number"),
    "E__EPD_RegNumber":     ("Environmental/EPD",  "EPD registration / programme number"),
    "E__EPD_Product Name":  ("Environmental/EPD",  "Product name as stated in EPD"),
    "E__EPD_ExpDate":       ("Environmental/EPD",  "EPD expiry / valid-until date"),
    "E__ServiceLife":       ("Environmental/EPD",  "Declared service life"),
    "E__EPD_Density":       ("Environmental/EPD",  "Density as stated in EPD [kg/m³]"),
    "E__L_WmK":             ("Environmental/EPD",  "λ as stated in EPD [W/mK]"),
    "E__EPD_Thick_mm":      ("Environmental/EPD",  "Thickness as stated in EPD [mm]"),
    "E__Rvalue":            ("Environmental/EPD",  "Thermal resistance R [m²K/W]"),
    "E__EPD_MultFactor":    ("Environmental/EPD",  "Multiplication factor to reach FU"),
    "E__EPDRef":            ("Environmental/EPD",  "Internal EPD reference"),
    "E__EPD_ConvFactor":    ("Environmental/EPD",  "Conversion factor (kg→FU)"),
    "E__EPD_kg-FU":         ("Environmental/EPD",  "Mass per functional unit [kg/FU]"),
    # G__ GWP
    "G__GWP_Metric":        ("GWP",                "GWP metric type (e.g. GWP-total)"),
    "G__GWP_FU":            ("GWP",                "Functional unit description"),
    "G__GWP_A1A3_kg":       ("GWP",                "GWP A1-A3 per kg [kg CO₂eq/kg]"),
    "G__GWP_A1A3_m2":       ("GWP",                "GWP A1-A3 per m² [kg CO₂eq/m²]"),
    "G__GWP_A1A3_m3":       ("GWP",                "GWP A1-A3 per m³ [kg CO₂eq/m³]"),
    "G__GWP_A1A3_m2R1":     ("GWP",                "GWP A1-A3 per m² at R=1 [kg CO₂eq/m²·(m²K/W)]"),
    "G__GWP_A1A3":          ("GWP",                "GWP A1-A3 per declared FU [kg CO₂eq/FU]  ← primary"),
    "G__GWP_A1":            ("GWP",                "GWP module A1 (raw material extraction)"),
    "G__GWP_A2":            ("GWP",                "GWP module A2 (transport to factory)"),
    "G__GWP_A3":            ("GWP",                "GWP module A3 (manufacturing)"),
    "G__GWP_A4":            ("GWP",                "GWP module A4 (transport to site)"),
    "G__GWP_A5":            ("GWP",                "GWP module A5 (installation)"),
    "G__GWP_B1":            ("GWP",                "GWP module B1 (in-use emissions)"),
    "G__GWP_B2":            ("GWP",                "GWP module B2 (maintenance)"),
    "G__GWP_B3":            ("GWP",                "GWP module B3 (repair)"),
    "G__GWP_B4":            ("GWP",                "GWP module B4 (replacement)"),
    "G__GWP_B5":            ("GWP",                "GWP module B5 (refurbishment)"),
    "G__GWP_B6":            ("GWP",                "GWP module B6 (operational energy)"),
    "G__GWP_B7":            ("GWP",                "GWP module B7 (operational water)"),
    "G__GWP_C1":            ("GWP",                "GWP module C1 (deconstruction)"),
    "G__GWP_C2":            ("GWP",                "GWP module C2 (transport to waste)"),
    "G__GWP_C3":            ("GWP",                "GWP module C3 (waste processing)"),
    "G__GWP_C4":            ("GWP",                "GWP module C4 (disposal)"),
    "G__GWP_D":             ("GWP",                "GWP module D (beyond system boundary — reuse/recovery)"),
    # R__ recycling
    "R__Rec_Reco_ByProd_URL":("Recycling",         "Recycling / recovery documentation URL"),
    "R__Rec_Pre_%":         ("Recycling",          "Pre-consumer recycled content [%]"),
    "R__Rec_Post_%":        ("Recycling",          "Post-consumer recycled content [%]"),
    "R__Rec_Tot_%":         ("Recycling",          "Total recycled content [%] (pre+post)"),
    "R__Reco_Tot_%":        ("Recycling",          "Total recoverable content [%]"),
    "R__ByProd_%":          ("Recycling",          "By-product content [%]"),
    "R__Rec_Reco_ByProd_%": ("Recycling",          "Combined recycled+recoverable+by-product [%]"),
    # V__ VOC / other
    "V__VOC_Cert":          ("VOC / CAM / DOP",    "VOC certification label / scheme name"),
    "V__VOC_URL":           ("VOC / CAM / DOP",    "VOC certificate document URL"),
    "V__Other":             ("VOC / CAM / DOP",    "Other certifications / notes"),
    "V__CAM_Compliance":    ("VOC / CAM / DOP",    "Italian CAM (Green Public Procurement) compliance status"),
    "V__DOP":               ("VOC / CAM / DOP",    "Declaration of Performance (DoP) URL"),
}

EMPTY_TOKENS = {"", "-", "–", "—", "n/a", "N/A", "n/r", "N/R", "nan", "None",
                "none", "null", "NULL", "na", "NA", "#N/A", "?", "*"}

URL_COLS = {"U__ProductInfo_URL", "U__TechDetails_URL", "U__Img_URL",
            "E__EPD_URL", "V__VOC_URL", "R__Rec_Reco_ByProd_URL", "V__DOP"}

NUMERIC_COLS = {
    "P__U_Wm2K", "P__L_WmK", "P__Thick_mm", "P__Mass_kgm3", "P__Mass_kgm2", "P__Mass_kg",
    "G__GWP_A1A3", "G__GWP_A1A3_kg", "G__GWP_A1A3_m2", "G__GWP_A1A3_m3", "G__GWP_A1A3_m2R1",
    "G__GWP_A1","G__GWP_A2","G__GWP_A3","G__GWP_A4","G__GWP_A5",
    "G__GWP_B1","G__GWP_B2","G__GWP_B3","G__GWP_B4","G__GWP_B5","G__GWP_B6","G__GWP_B7",
    "G__GWP_C1","G__GWP_C2","G__GWP_C3","G__GWP_C4","G__GWP_D",
    "E__EPD_Density","E__L_WmK","E__EPD_Thick_mm","E__Rvalue","E__EPD_MultFactor","E__EPD_kg-FU",
    "R__Rec_Pre_%","R__Rec_Post_%","R__Rec_Tot_%","R__Reco_Tot_%","R__Rec_Reco_ByProd_%",
}

# Expected ranges for physical sanity checks  {col: (min_plausible, max_plausible)}
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "P__L_WmK":    (0.01, 5.0),
    "P__U_Wm2K":   (0.05, 10.0),
    "P__Thick_mm": (1, 5000),
    "P__Mass_kgm3":(1, 8000),
    "P__Mass_kgm2":(0.01, 200),
    "P__Mass_kg":  (0.01, 50000),
    "E__EPD_Density":(1, 8000),
    "E__L_WmK":    (0.01, 5.0),
    "R__Rec_Pre_%":  (0, 100),
    "R__Rec_Post_%": (0, 100),
    "R__Rec_Tot_%":  (0, 100),
    "R__Reco_Tot_%": (0, 100),
    "R__Rec_Reco_ByProd_%": (0, 100),
}

MAX_CAT_SHOW = 20    # max value_counts rows in HTML
MAX_CAT_UNIQUE = 80  # above this → treat as free-text (no freq table)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_empty(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().isin(EMPTY_TOKENS)

def _filled(s: pd.Series) -> pd.Series:
    return ~_is_empty(s)

def _clean_str(s: pd.Series) -> pd.Series:
    return s[_filled(s)].astype(str).str.strip()

def _to_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".", regex=False),
        errors="coerce"
    )

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return "—"


# ── per-column analysis ───────────────────────────────────────────────────────

def analyse_column(col: str, s: pd.Series, n_total: int) -> dict:
    """Return a rich dict of metrics for one column."""
    result: dict = {
        "col": col,
        "group": COL_META.get(col, ("Unknown", ""))[0],
        "role": COL_META.get(col, ("", col))[1],
        "n_total": n_total,
    }

    empty_mask  = _is_empty(s)
    filled_mask = ~empty_mask
    n_filled    = int(filled_mask.sum())
    n_empty     = n_total - n_filled
    fill_rate   = n_filled / n_total if n_total else 0.0

    result.update({"n_filled": n_filled, "n_empty": n_empty, "fill_rate": fill_rate})

    filled_vals = s[filled_mask]

    # Unique count (excluding empties)
    result["n_unique"] = int(filled_vals.nunique())

    # Duplicate check for ID columns
    if col in ("0__EETRA_ID", "0__NUM"):
        dup_vals = filled_vals[filled_vals.duplicated(keep=False)]
        result["n_duplicates"] = int(dup_vals.nunique())
        result["duplicate_examples"] = list(dup_vals.value_counts().head(5).index)

    # ── URL columns ──────────────────────────────────────────────────────────
    if col in URL_COLS:
        urls = _clean_str(s)
        invalid_fmt  = int((~urls.str.startswith("http")).sum())
        https_count  = int(urls.str.startswith("https://").sum())
        http_count   = int(urls.str.startswith("http://").sum())
        # Domain breakdown
        domains = urls[urls.str.startswith("http")].map(_domain).value_counts()
        result.update({
            "url_invalid_fmt": invalid_fmt,
            "url_https": https_count,
            "url_http_only": http_count,
            "url_domains": domains.to_dict(),
        })
        return result

    # ── Numeric columns ──────────────────────────────────────────────────────
    is_numeric_dtype = pd.api.types.is_numeric_dtype(s)
    if col in NUMERIC_COLS or is_numeric_dtype:
        nums = _to_numeric(s) if not is_numeric_dtype else pd.to_numeric(s, errors="coerce")
        nums_clean = nums.dropna()
        if len(nums_clean):
            q = nums_clean.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            iqr  = float(q[0.75] - q[0.25])
            lo   = float(q[0.25] - 1.5 * iqr)
            hi   = float(q[0.75] + 1.5 * iqr)
            outliers_iqr = int(((nums_clean < lo) | (nums_clean > hi)).sum())
            n_zero  = int((nums_clean == 0).sum())
            n_neg   = int((nums_clean < 0).sum())
            n_pos   = int((nums_clean > 0).sum())

            result.update({
                "num_min":    float(nums_clean.min()),
                "num_max":    float(nums_clean.max()),
                "num_mean":   float(nums_clean.mean()),
                "num_median": float(nums_clean.median()),
                "num_std":    float(nums_clean.std()),
                "num_p5":     float(q[0.05]),
                "num_p25":    float(q[0.25]),
                "num_p75":    float(q[0.75]),
                "num_p95":    float(q[0.95]),
                "num_outliers_iqr": outliers_iqr,
                "n_zero": n_zero,
                "n_neg":  n_neg,
                "n_pos":  n_pos,
            })

            # Plausibility check
            if col in PLAUSIBLE_RANGES:
                lo_p, hi_p = PLAUSIBLE_RANGES[col]
                n_implausible = int(((nums_clean < lo_p) | (nums_clean > hi_p)).sum())
                result["n_implausible"] = n_implausible
                result["plausible_range"] = (lo_p, hi_p)
        return result

    # ── Categorical / text columns ───────────────────────────────────────────
    vals = _clean_str(s)
    n_uniq = result["n_unique"]

    if n_uniq <= MAX_CAT_UNIQUE:
        vc = vals.value_counts()
        vc_pct = (vc / n_filled * 100).round(1) if n_filled else vc * 0
        result["value_counts"] = vc.to_dict()
        result["value_counts_pct"] = vc_pct.to_dict()

        # Flag suspicious values (contain *, numbers in text fields, single chars)
        suspicious = [v for v in vc.index
                      if str(v).strip().startswith("*")
                      or str(v).strip() in ("?", "x", "X", "0", "1")
                      or len(str(v).strip()) == 1]
        result["suspicious_values"] = suspicious[:10]

    else:
        # Free-text: show sample and length stats
        result["free_text"] = True
        result["sample_values"] = list(vals.head(5))
        lengths = vals.str.len()
        result["text_len_min"]    = int(lengths.min())
        result["text_len_max"]    = int(lengths.max())
        result["text_len_median"] = float(lengths.median())

    return result


# ── cross-column quality rules ────────────────────────────────────────────────

def cross_checks(df: pd.DataFrame) -> list[dict]:
    issues = []
    n = len(df)

    def _chk(label: str, mask: pd.Series, sample_cols: list[str]) -> None:
        count = int(mask.sum())
        if count == 0:
            return
        ex = df[mask][sample_cols].head(5).to_dict("records")
        issues.append({"label": label, "count": count, "pct": count/n*100, "examples": ex})

    # 1. EPD_Y/N = Y but no EPD number
    if "E__EPD_Y/N" in df.columns and "E__EPD_RegNumber" in df.columns:
        m = (_clean_str(df["E__EPD_Y/N"]) == "Y") & _is_empty(df["E__EPD_RegNumber"])
        _chk("EPD flagged Y but no registration number", m,
             ["0__EETRA_ID","A__ProductName","E__EPD_Y/N","E__EPD_RegNumber"])

    # 2. Has EPD URL but no EPD number
    if "E__EPD_URL" in df.columns and "E__EPD_RegNumber" in df.columns:
        m = _filled(df["E__EPD_URL"]) & _is_empty(df["E__EPD_RegNumber"])
        _chk("Has EPD URL but no registration number", m,
             ["0__EETRA_ID","A__ProductName","E__EPD_URL","E__EPD_RegNumber"])

    # 3. GWP A1+A2+A3 vs A1A3 consistency (where all four present)
    gcols = ["G__GWP_A1","G__GWP_A2","G__GWP_A3","G__GWP_A1A3"]
    if all(c in df.columns for c in gcols):
        sub = df[gcols].copy()
        for c in gcols:
            sub[c] = pd.to_numeric(sub[c].astype(str).str.replace(",","."), errors="coerce")
        sub = sub.dropna()
        if len(sub):
            sub["_sum"] = sub["G__GWP_A1"] + sub["G__GWP_A2"] + sub["G__GWP_A3"]
            sub["_diff_pct"] = ((sub["_sum"] - sub["G__GWP_A1A3"]).abs() /
                                sub["G__GWP_A1A3"].abs().clip(lower=1e-9) * 100)
            bad = sub[sub["_diff_pct"] > 5.0]
            if len(bad):
                ex = df.loc[bad.index, ["0__EETRA_ID","A__ProductName"]].head(5).to_dict("records")
                issues.append({
                    "label": "GWP A1+A2+A3 deviates >5% from A1A3 total",
                    "count": len(bad), "pct": len(bad)/n*100, "examples": ex
                })

    # 4. Recycled % pre + post > total (sanity)
    rcols = ["R__Rec_Pre_%","R__Rec_Post_%","R__Rec_Tot_%"]
    if all(c in df.columns for c in rcols):
        sub = df[rcols].copy()
        for c in rcols:
            sub[c] = pd.to_numeric(sub[c].astype(str).str.replace(",","."), errors="coerce")
        sub = sub.dropna()
        if len(sub):
            bad = sub[(sub["R__Rec_Pre_%"] + sub["R__Rec_Post_%"]) > (sub["R__Rec_Tot_%"] + 1.0)]
            if len(bad):
                ex = df.loc[bad.index, ["0__EETRA_ID","A__ProductName"]].head(5).to_dict("records")
                issues.append({
                    "label": "Recycled pre% + post% exceeds total%",
                    "count": len(bad), "pct": len(bad)/n*100, "examples": ex
                })

    # 5. Products with VOC cert but no VOC URL
    if "V__VOC_Cert" in df.columns and "V__VOC_URL" in df.columns:
        m = _filled(df["V__VOC_Cert"]) & _is_empty(df["V__VOC_URL"])
        _chk("Has VOC cert label but no URL", m,
             ["0__EETRA_ID","A__ProductName","V__VOC_Cert"])

    # 6. GWP A1A3 is positive but D is also positive (D should often be negative/beneficial)
    if "G__GWP_D" in df.columns and "G__GWP_A1A3" in df.columns:
        d  = pd.to_numeric(df["G__GWP_D"].astype(str).str.replace(",","."),  errors="coerce")
        a  = pd.to_numeric(df["G__GWP_A1A3"].astype(str).str.replace(",","."), errors="coerce")
        bad = df[(d > 0) & a.notna() & d.notna()]
        if len(bad):
            ex = bad[["0__EETRA_ID","A__ProductName"]].head(5).to_dict("records")
            issues.append({
                "label": "GWP module D is positive (expected ≤ 0 for net benefit)",
                "count": len(bad), "pct": len(bad)/n*100, "examples": ex
            })

    # 7. Duplicate EETRA_IDs
    if "0__EETRA_ID" in df.columns:
        eid = df["0__EETRA_ID"].dropna().astype(str)
        dups = eid[eid.duplicated(keep=False)]
        if len(dups):
            ex = [{"0__EETRA_ID": v, "count": int(c)}
                  for v, c in dups.value_counts().head(5).items()]
            issues.append({
                "label": "Duplicate EETRA_IDs",
                "count": int(dups.nunique()), "pct": dups.nunique()/n*100, "examples": ex
            })

    # 8. ID format validation  BBW__GYP__0002
    if "0__EETRA_ID" in df.columns:
        ids = df["0__EETRA_ID"].dropna().astype(str)
        bad_fmt = ids[~ids.str.match(r'^[A-Z]{2,4}__[A-Z]{2,4}__\d{4}$')]
        if len(bad_fmt):
            ex = [{"0__EETRA_ID": v} for v in bad_fmt.head(5)]
            issues.append({
                "label": "EETRA_ID does not match expected format XX__YY__NNNN",
                "count": len(bad_fmt), "pct": len(bad_fmt)/n*100, "examples": ex
            })

    # 9. EPD expiry date: already expired
    if "E__EPD_ExpDate" in df.columns:
        today = datetime.today()
        raw = _clean_str(df["E__EPD_ExpDate"])
        parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
        expired = parsed[parsed < today]
        if len(expired):
            ex = df.loc[expired.index, ["0__EETRA_ID","A__ProductName","E__EPD_ExpDate"]].head(5).to_dict("records")
            issues.append({
                "label": f"EPD expired (date < today {today.strftime('%Y-%m-%d')})",
                "count": len(expired), "pct": len(expired)/n*100, "examples": ex
            })

    # 10. Lambda mismatch between P__L_WmK and E__L_WmK (>10% relative diff)
    if "P__L_WmK" in df.columns and "E__L_WmK" in df.columns:
        pl = pd.to_numeric(df["P__L_WmK"].astype(str).str.replace(",","."), errors="coerce")
        el = pd.to_numeric(df["E__L_WmK"].astype(str).str.replace(",","."),  errors="coerce")
        both = pl.notna() & el.notna()
        diff = ((pl - el).abs() / pl.clip(lower=1e-9) * 100)[both]
        bad  = diff[diff > 10.0]
        if len(bad):
            ex = df.loc[bad.index, ["0__EETRA_ID","A__ProductName","P__L_WmK","E__L_WmK"]].head(5).to_dict("records")
            issues.append({
                "label": "Lambda P__L_WmK vs E__L_WmK mismatch > 10%",
                "count": len(bad), "pct": len(bad)/n*100, "examples": ex
            })

    return issues


# ── HTML rendering ────────────────────────────────────────────────────────────

_CSS = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;font-size:12.5px;background:#f4f5f9;color:#222;padding:20px}
h1{font-size:19px;margin-bottom:4px;color:#1a1a2e}
h2{font-size:13px;font-weight:700;color:#2d3561;margin:30px 0 6px;
   border-bottom:3px solid #2d3561;padding-bottom:3px}
h3{font-size:12px;font-weight:700;color:#555;margin:18px 0 4px}
.meta{color:#888;font-size:11px;margin-bottom:18px}
.group-badge{display:inline-block;background:#e8eaf6;color:#3949ab;border-radius:10px;
             padding:1px 8px;font-size:11px;margin-left:6px;vertical-align:middle}
.role{color:#777;font-size:11px;font-style:italic;margin-bottom:8px}

/* card per column */
.col-card{background:#fff;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1);
           margin-bottom:10px;padding:12px 16px;border-left:4px solid #ccc}
.col-card.good{border-left-color:#34a853}
.col-card.warn{border-left-color:#fbbc04}
.col-card.bad {border-left-color:#ea4335}
.col-title{font-weight:700;font-size:13px;margin-bottom:2px}
.fill-bar-wrap{background:#eee;border-radius:3px;height:8px;width:200px;display:inline-block;vertical-align:middle;margin-left:8px}
.fill-bar{height:8px;border-radius:3px;display:block}
.fg{background:#34a853}.fw{background:#fbbc04}.fb{background:#ea4335}

/* tables */
table{border-collapse:collapse;width:100%;margin:6px 0}
th{background:#2d3561;color:#fff;padding:5px 8px;text-align:left;font-size:11px;white-space:nowrap}
td{padding:4px 8px;border-bottom:1px solid #eee;font-size:11px;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f0f4ff}
.pct-bar{display:inline-block;background:#4285f4;height:7px;border-radius:2px;
          vertical-align:middle;margin-right:4px}
.neg-bar{background:#ea4335}
.num-stat{display:inline-grid;grid-template-columns:repeat(4,auto);gap:2px 16px;
           font-size:11px;margin:4px 0}
.num-label{color:#888;font-size:10px}

/* cross-checks */
.issue-card{background:#fff3e0;border-left:4px solid #f57c00;border-radius:4px;
             padding:8px 12px;margin-bottom:8px}
.issue-title{font-weight:700;color:#e65100;font-size:12px}
.issue-count{font-size:11px;color:#555;margin-left:8px}
.ex-table td{font-size:10.5px;color:#444}

/* toc */
#toc{position:fixed;top:0;right:0;width:220px;height:100vh;overflow-y:auto;
     background:#fff;border-left:1px solid #ddd;padding:12px;font-size:11px;z-index:99}
#toc h4{font-size:12px;font-weight:700;color:#2d3561;margin-bottom:8px}
#toc a{display:block;color:#555;text-decoration:none;padding:2px 0;
       border-bottom:1px solid #f0f0f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#toc a:hover{color:#2d3561}
.toc-group{font-weight:700;color:#2d3561;margin-top:6px;margin-bottom:2px;font-size:11px}
body{margin-right:230px}
details summary{cursor:pointer;font-weight:600;color:#2d3561;padding:2px 0}
</style>
"""

def _pct_bar(pct: float, w_max: int = 120, neg: bool = False) -> str:
    w = round(min(pct, 100) / 100 * w_max)
    cls = "pct-bar neg-bar" if neg else "pct-bar"
    return f'<span class="{cls}" style="width:{w}px"></span>'

def _fill_color(r: float) -> str:
    if r >= 0.90: return "good"
    if r >= 0.60: return "warn"
    return "bad"

def _fill_bar(r: float) -> str:
    pct = round(r * 200)
    cls_bar = "fg" if r >= 0.90 else ("fw" if r >= 0.60 else "fb")
    cls_txt = "good" if r >= 0.90 else ("warn" if r >= 0.60 else "bad")
    return (f'<span class="fill-bar-wrap"><span class="fill-bar {cls_bar}" '
            f'style="width:{pct}px"></span></span> '
            f'<strong class="{cls_txt}">{r*100:.1f}%</strong>')

def _fmt(v, digits=4):
    if v is None or (isinstance(v, float) and math.isnan(v)): return "—"
    return f"{v:.{digits}g}"

def render_col_html(a: dict) -> str:
    col    = a["col"]
    group  = a.get("group", "")
    role   = a.get("role", "")
    n_tot  = a["n_total"]
    n_fill = a["n_filled"]
    n_emp  = a["n_empty"]
    r      = a["fill_rate"]
    n_uniq = a.get("n_unique", 0)
    color  = _fill_color(r)
    anchor = _he.escape(col.replace(" ", "_"))

    lines = [
        f'<div class="col-card {color}" id="{anchor}">',
        f'<div class="col-title">{_he.escape(col)}'
        f'<span class="group-badge">{_he.escape(group)}</span></div>',
        f'<div class="role">{_he.escape(role)}</div>',
        f'<table><tr>',
        f'<td>Fill: {_fill_bar(r)}</td>',
        f'<td>Filled: <strong>{n_fill:,}</strong> / {n_tot:,}</td>',
        f'<td>Empty: <strong>{n_emp:,}</strong></td>',
        f'<td>Unique values: <strong>{n_uniq:,}</strong></td>',
        f'</tr></table>',
    ]

    # Duplicates (ID columns)
    if "n_duplicates" in a and a["n_duplicates"] > 0:
        exs = ", ".join(_he.escape(str(x)) for x in a["duplicate_examples"])
        lines.append(f'<p style="color:#c00;font-size:11px">⚠ {a["n_duplicates"]} duplicate values: {exs}</p>')

    # URL analysis
    if "url_domains" in a:
        inv = a.get("url_invalid_fmt", 0)
        lines.append(f'<table><tr><th>Scheme</th><th>Count</th></tr>')
        lines.append(f'<tr><td>https://</td><td>{a["url_https"]:,}</td></tr>')
        lines.append(f'<tr><td>http:// (insecure)</td><td>{a["url_http_only"]:,}</td></tr>')
        if inv: lines.append(f'<tr><td style="color:#c00">Invalid format</td><td style="color:#c00">{inv:,}</td></tr>')
        lines.append('</table>')
        dom = a["url_domains"]
        if dom:
            lines.append('<details><summary>Domain breakdown</summary><table>'
                         '<tr><th>Domain</th><th>Count</th></tr>')
            for d, cnt in list(dom.items())[:20]:
                lines.append(f'<tr><td>{_he.escape(str(d))}</td><td>{cnt:,}</td></tr>')
            lines.append('</table></details>')

    # Numeric stats
    elif "num_min" in a:
        lo = a["num_min"]; hi = a["num_max"]
        med = a["num_median"]; mu = a["num_mean"]; sd = a["num_std"]
        p5  = a["num_p5"];  p95 = a["num_p95"]
        outliers = a.get("num_outliers_iqr", 0)
        n_neg = a.get("n_neg", 0); n_zero = a.get("n_zero", 0)
        n_impl = a.get("n_implausible", 0)
        pr    = a.get("plausible_range")

        lines.append(
            f'<table><tr><th>Min</th><th>P5</th><th>P25</th><th>Median</th>'
            f'<th>Mean</th><th>P75</th><th>P95</th><th>Max</th><th>Std</th></tr>'
            f'<tr><td>{_fmt(lo)}</td><td>{_fmt(p5)}</td><td>{_fmt(a["num_p25"])}</td>'
            f'<td>{_fmt(med)}</td><td>{_fmt(mu)}</td><td>{_fmt(a["num_p75"])}</td>'
            f'<td>{_fmt(p95)}</td><td>{_fmt(hi)}</td><td>{_fmt(sd)}</td></tr>'
            f'</table>'
        )
        flags = []
        if outliers: flags.append(f'{outliers} IQR outliers')
        if n_neg:    flags.append(f'{n_neg} negative values')
        if n_zero:   flags.append(f'{n_zero} zeros')
        if n_impl:   flags.append(f'<span style="color:#c00">{n_impl} outside plausible range {pr}</span>')
        if flags:
            lines.append('<p style="font-size:11px;color:#666;margin-top:4px">'
                         + ' &nbsp;|&nbsp; '.join(flags) + '</p>')

    # Categorical value counts
    elif "value_counts" in a:
        vc   = a["value_counts"]
        vc_p = a["value_counts_pct"]
        susp = a.get("suspicious_values", [])
        lines.append('<details open><summary>Value distribution</summary>')
        lines.append('<table><tr><th>Value</th><th>Count</th><th style="width:180px">%</th></tr>')
        for val, cnt in list(vc.items())[:MAX_CAT_SHOW]:
            pct_v = vc_p.get(val, 0)
            bar   = _pct_bar(pct_v)
            style = ' style="color:#c00"' if str(val) in [str(s) for s in susp] else ''
            lines.append(f'<tr><td{style}>{_he.escape(str(val))}</td>'
                         f'<td>{cnt:,}</td>'
                         f'<td>{bar} {pct_v:.1f}%</td></tr>')
        if len(vc) > MAX_CAT_SHOW:
            lines.append(f'<tr><td colspan="3" style="color:#888">'
                         f'… {len(vc)-MAX_CAT_SHOW} more values not shown</td></tr>')
        lines.append('</table></details>')
        if susp:
            lines.append(f'<p style="color:#c00;font-size:11px">⚠ Suspicious values: '
                         + ', '.join(_he.escape(str(s)) for s in susp) + '</p>')

    # Free text
    elif a.get("free_text"):
        lines.append(f'<p style="font-size:11px;color:#666">'
                     f'Free text — length: min {a["text_len_min"]}, '
                     f'median {a["text_len_median"]:.0f}, max {a["text_len_max"]} chars</p>')
        samples = "; ".join(_he.escape(str(v)) for v in a.get("sample_values", []))
        lines.append(f'<p style="font-size:11px;color:#888">Samples: {samples}</p>')

    lines.append('</div>')
    return "\n".join(lines)


def render_cross_html(issues: list[dict]) -> str:
    if not issues:
        return '<p style="color:#555;font-size:12px">No cross-field issues detected.</p>'
    parts = []
    for iss in issues:
        ex_rows = ""
        for ex in iss.get("examples", []):
            cells = "".join(f"<td>{_he.escape(str(v))}</td>" for v in ex.values())
            headers = "".join(f"<th>{_he.escape(str(k))}</th>" for k in ex.keys())
            ex_rows += f"<tr>{cells}</tr>"
        if ex_rows:
            hdr_str = "".join(f"<th>{_he.escape(str(k))}</th>" for k in iss["examples"][0].keys())
            ex_html = (f'<details><summary>Show examples</summary>'
                       f'<table class="ex-table"><tr>{hdr_str}</tr>{ex_rows}</table></details>')
        else:
            ex_html = ""
        parts.append(
            f'<div class="issue-card">'
            f'<span class="issue-title">{_he.escape(iss["label"])}</span>'
            f'<span class="issue-count">{iss["count"]:,} rows ({iss["pct"]:.1f}%)</span>'
            f'{ex_html}</div>'
        )
    return "\n".join(parts)


def build_toc(analyses: list[dict]) -> str:
    seen_group = None
    lines = ['<div id="toc"><h4>Columns</h4>']
    for a in analyses:
        g = a.get("group", "")
        if g != seen_group:
            lines.append(f'<div class="toc-group">{_he.escape(g)}</div>')
            seen_group = g
        col    = a["col"]
        anchor = _he.escape(col.replace(" ", "_"))
        r      = a["fill_rate"]
        dot    = "🟢" if r >= 0.90 else ("🟡" if r >= 0.60 else "🔴")
        lines.append(f'<a href="#{anchor}">{dot} {_he.escape(col)}</a>')
    lines.append('</div>')
    return "\n".join(lines)


def build_html(df: pd.DataFrame, analyses: list[dict], issues: list[dict]) -> str:
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    n   = len(df)

    # Group analyses by group label
    from collections import OrderedDict
    groups: dict[str, list] = OrderedDict()
    for a in analyses:
        g = a.get("group", "Other")
        groups.setdefault(g, []).append(a)

    body_parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>EETRA MatLib — Column Deep Dive {ts}</title>",
        _CSS,
        "</head><body>",
        build_toc(analyses),
        f"<h1>EETRA MatLib — Column Deep Dive</h1>",
        f"<p class='meta'>Generated {ts} &nbsp;|&nbsp; "
        f"<strong>{n:,}</strong> products &nbsp;|&nbsp; "
        f"<strong>{len(df.columns)}</strong> columns</p>",
        "<h2>Cross-field quality checks</h2>",
        render_cross_html(issues),
    ]

    for group_name, group_analyses in groups.items():
        body_parts.append(f'<h2>{_he.escape(group_name)}</h2>')
        for a in group_analyses:
            body_parts.append(render_col_html(a))

    body_parts.append("</body></html>")
    return "\n".join(body_parts)


# ── main ──────────────────────────────────────────────────────────────────────

def load_clean(parquet_path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    df = df[[c for c in df.columns if "__" in str(c) and not str(c).startswith("*")]]
    nm, mn = "A__ProductName", "A__Manufacturer"
    if nm in df.columns and mn in df.columns:
        df = df[~(_is_empty(df[nm]) & _is_empty(df[mn]))]
    cands = [c for c in df.columns if str(c).startswith(("A__","D__","E__","G__","P__"))]
    if cands:
        df = df[~df[cands].astype(str).apply(lambda s: s.str.strip().str.startswith("*")).any(axis=1)]
    return df.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=str(DEFAULT_PARQ))
    ap.add_argument("--out",     default=str(DEFAULT_HTML))
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    parq = pathlib.Path(args.parquet)
    if not parq.exists():
        # fallback: try project root
        alt = _ROOT / "base_data.parquet"   # pre-migration layout
        if alt.exists():
            parq = alt
        else:
            print(f"Parquet not found: {parq}\nRun 03_excel_to_parquet.py first.")
            sys.exit(1)

    print(f"Reading: {parq}")
    df = load_clean(parq)
    n  = len(df)
    print(f"  {n:,} rows, {len(df.columns)} columns")

    analyses = [analyse_column(col, df[col], n) for col in df.columns]
    issues   = cross_checks(df)

    # Console summary
    print(f"\n{'='*72}")
    print(f"  {'Column':<35} {'Fill':>6}  {'Empty':>6}  {'Unique':>7}  Notes")
    print(f"{'='*72}")
    for a in analyses:
        notes = []
        if a.get("n_duplicates"): notes.append(f"{a['n_duplicates']} dups")
        if a.get("url_invalid_fmt"): notes.append(f"{a['url_invalid_fmt']} bad URLs")
        if a.get("n_implausible"): notes.append(f"{a['n_implausible']} implausible")
        if a.get("suspicious_values"): notes.append("suspicious vals")
        bar = "#" * round(a["fill_rate"] * 16) + "." * (16 - round(a["fill_rate"] * 16))
        print(f"  {a['col']:<35} {a['fill_rate']*100:5.1f}%  "
              f"{a['n_empty']:>6}  {a.get('n_unique',0):>7}  {', '.join(notes)}")

    print(f"\n  Cross-field issues: {len(issues)}")
    for iss in issues:
        print(f"    [{iss['count']:>4} rows / {iss['pct']:4.1f}%]  {iss['label']}")

    if not args.no_html:
        html_path = pathlib.Path(args.out)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(build_html(df, analyses, issues), encoding="utf-8")
        print(f"\nHTML -> {html_path}")


if __name__ == "__main__":
    main()
