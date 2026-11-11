"""
libs/lib_data.py — EETRA MatLib data module
=============================================
fn101–fn199  Data loading, cleaning, auth, geocoding, cement parser, config

  fn103  load_from_sharepoint          SharePoint Graph API Excel loader
  fn104  cached_load_excel             @cache_data SharePoint wrapper
  fn104a cached_load_parquet           @cache_data local Parquet loader (mtime-keyed)
  fn105  cached_load_motherduck_v1     MotherDuck table loader (deprecated)
  fn106  cached_load_live_data         @cache_data MotherDuck live data
  fn109  cached_clean_dataframe        @cache_data DataFrame cleaner
  fn110  cached_fetch_image            @cache_data remote image fetcher
  fn111  get_auth_users                load user/password list from secrets
  fn112  render_login                  Streamlit login form + auth flow (sidebar)
  fn112a render_auth_gate_screen       full-width login gate (hide chrome until sign-in)
  fn113  get_base_product_name         extract base name (before ' | ')
  fn114  add_base_product_column       add A__ProductName_Base column
  fn115  geocode_location              cache-only geocoder
  fn116  geocode_with_alternatives     live Nominatim geocoder with fallbacks
  fn117  preload_all_locations         bulk-geocode all plant locations
  fn118  get_locations_for_base_product  plant coordinates for a base product
  fn119  get_all_products_for_plant    products at a manufacturing plant
  fn120  aggregate_value_by_base_product  mean-aggregate by base product
  fn121  clean_columns                 convert raw rows → DataFrame, filter cols
  fn122  clean_dataframe               drop empties, markers, Excel artifacts
  fn123  clean_dataframe_columns       strip prefixes, remove URL cols
  fn124  get_cleaned_column_names      list of cleaned column names
  fn125  get_original_column_name      reverse lookup: cleaned → original name
  fn126  get_numeric_columns           predefined numeric column list
  fn127  get_cleaned_numeric_column_names  cleaned names for numeric cols only
  fn128  clean_column_name             human-friendly label for a column name
  fn129  decode_cement_marking         EN 197-1 cement designation parser
  fn130  decode_many_cement            batch cement decoder
  fn131  load_aux_ui_config            read aux__ui_config.json from disk
  fn132  session_ui_config_bundle      session_state keys from JSON config
  fn133  extract_table_with_llm        LLM-based table extraction (OpenAI)
  fn134  fetch_and_resize_image        download + letterbox image (300×160)
  fn135  sustainability_credentials     @cache_data load ``aux_companies_sust_credentials.json``
  fn136  sustainability_sector_list    sector names from fn135
  fn137  get_credentials_matrix       manufacturers × credentials DataFrame
  fn138  get_maturity_ranking         manufacturers sorted by maturity tier
  fn139  get_company_profile_df       narrative profile rows
  fn140  get_sustainability_maturity_counts  counts per maturity tier
  fn140a load_impact_framework        @cache_data load ``aux_companies_impact_framework.json``
  fn140b manufacturer_impact_summary  catalogue-facing IFW card for one manufacturer
  fn140c manufacturer_impact_summaries_by_name  batch lookup for catalogue payload
  fn140d list_manufacturer_names      sorted IFW ∪ sust-credentials names (Add/Edit)
  fn140e load_manufacturer_for_edit   flat form values for one manufacturer
  fn140f save_manufacturer_edit       atomic write-back to IFW (+ sust overlay) + cache clear
  fn140g delete_manufacturer_edit     remove IFW entity (optional sust wipe) + cache clear
  fn140h evaluation_framework         evidence × macroarea table (level / nature / condition)
  fn140i evaluation_questionnaire     supplier questionnaire per macroarea (same block)
  fn145  load_raw_live_dataframe       plain pd.read_parquet, no cleaning (round-trip safe)
  fn146  save_raw_live_dataframe       atomic write-back + cache-bust for fn104a
  fn147  next_eetra_id                 generate a new TYPE__SUBTYPE__NNNN product id
  fn148  upsert_live_data_row          insert/update one row in the raw live-data DataFrame
  fn149  ensure_data_platform_session  default ``data_platform`` in session state
  fn150  render_data_source_selector   Welcome-page Data Source selectbox
  fn151  sidebar_filters_active         whether any sidebar filter row is enabled
  fn152  edit_picker_dataframe          rows shown in Developer / Edit picker (sidebar rules)
  fn153  resolve_base_parquet_path      path to base_data.parquet (Excel conversion, read-only)
  fn153b load_base_dataframe            base snapshot from Neon or parquet
  fn153c base_available                 True when Neon/parquet base has rows
  fn153d base_version                   cache key for base (mtime or Neon upload)
  fn154  resolve_edits_parquet_path     path to edits_data.parquet (append-only edit log)
  fn155  load_edits_dataframe           read the edit log (empty audit-only frame if absent)
  fn156  append_edit_record             append one full-row snapshot + audit cols to the log
  fn156b append_edit_records            same, several snapshots in one atomic write
  fn155c load_corrections_dataframe    correction register, derived from the log's provenance
  fn157  merge_base_and_edits           base ⊕ latest edit per EETRA_ID → effective dataset
  fn158  load_effective_live_dataframe  merged view (uncached)
  fn159  effective_dataset              merged view, cached — replaces live_data.parquet reads
  fn158a cached_load_effective_live     @cache_data merged view, keyed on both file mtimes

Two-file data model (see fn153–fn158)
-------------------------------------
  base_data.parquet   immutable conversion of the SharePoint/local Excel — written
                      ONLY by ``04_tools/03_excel_to_parquet.py``.
  edits_data.parquet  append-only log of everything created/edited/deleted in
                      the app. One record per save: a full row snapshot (same
                      columns as base) plus ``_edit_id / _edit_ts / _edit_user /
                      _edit_op`` (``insert`` / ``update`` / ``delete``) and the
                      provenance of the save — ``_edit_batch / _edit_reason /
                      _edit_evidence / _edit_evidence_url / _edit_fields``, which
                      fn155c reads back as the correction register. A
                      ``delete`` record tombstones the id — fn157 drops it from
                      the merge, nothing is erased, so it can be undone by
                      removing that record.
  (no third file)     The effective dataset is derived on read — never stored.
                      Modules that need it (lib_tags, lib_ui media paths,
                      pages/15_Manufacturers) call ``fn159_effective_dataset``,
                      which is cached on both files' mtimes.

Both parquets live in ``01_data/`` with the rest of the project's data. They
were previously duplicated at the project root and shadowed by a materialised
``live_data.parquet`` — four byte-identical files with no single canonical one.
"""

import streamlit as st
import pandas as pd
import numpy as np
import os, re, time, json, requests, hashlib, base64, mimetypes, threading, warnings
import urllib.request
import urllib3
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential
from msal import ConfidentialClientApplication
from typing import Dict, List, Optional

# ════════════════════════════════════════════════════════════════════════════
# CEMENT MARKING PARSER (EN 197-1 / bilingual)
# ════════════════════════════════════════════════════════════════════════════

FAMILY_NAME_EN = {
    "I": "Portland cement",
    "II": "Portland-composite cement",
    "III": "Blastfurnace cement",
    "IV": "Pozzolanic cement",
    "V": "Composite cement",
}
FAMILY_NAME_IT = {
    "I": "Cemento Portland",
    "II": "Cemento Portland composito",
    "III": "Cemento d'altoforno",
    "IV": "Cemento pozzolanico",
    "V": "Cemento composito",
}

SUBCLASS_RANGES_EN = {
    ("II", "A"): "Additions 6–20%",
    ("II", "B"): "Additions 21–35%",
    ("III", "A"): "Slag 36–65%",
    ("III", "B"): "Slag 66–80%",
    ("III", "C"): "Slag 81–95%",
    ("IV", "A"): "Pozzolana 11–35%",
    ("IV", "B"): "Pozzolana 36–55%",
    ("V", "A"): "Multiple additions 6–20% each (typical)",
    ("V", "B"): "Multiple additions 21–35% each (typical)",
}
SUBCLASS_RANGES_IT = {
    ("II", "A"): "Aggiunte 6–20%",
    ("II", "B"): "Aggiunte 21–35%",
    ("III", "A"): "Gha 36–65%",
    ("III", "B"): "Gha 66–80%",
    ("III", "C"): "Gha 81–95%",
    ("IV", "A"): "Pozzolana 11–35%",
    ("IV", "B"): "Pozzolana 36–55%",
    ("V", "A"): "Aggiunte multiple 6–20% (tipico)",
    ("V", "B"): "Aggiunte multiple 21–35% (tipico)",
}

ADDITIONS_EN = {
    "LL": "Limestone (low organic carbon)",
    "L": "Limestone",
    "S": "Blastfurnace slag",
    "P": "Natural pozzolana",
    "V": "Siliceous fly ash",
    "W": "Calcareous fly ash",
    "M": "Mixed additions (composite)",
}
ADDITIONS_IT = {
    "LL": "Calcare (carbonio organico basso)",
    "L": "Calcare",
    "S": "Loppa d'altoforno",
    "P": "Pozzolana naturale",
    "V": "Cenere volante silicea",
    "W": "Cenere volante calcarea",
    "M": "Aggiunte miste (composito)",
}

EARLY_EN = {"N": "Normal early strength", "R": "Rapid early strength", "L": "Low early strength"}
EARLY_IT = {"N": "Resistenza iniziale normale", "R": "Resistenza iniziale rapida", "L": "Resistenza iniziale lenta"}

SPECIAL_EN = {
    "LH": "Low heat of hydration",
    "MH": "Medium heat of hydration",
    "SR": "Sulphate resistant",
    "HSR": "High sulphate resistance",
    "MSR": "Moderate sulphate resistance",
    "SR/IA": "Suitable for sulphate-bearing waters (Italy)",
    "SR/IAS": "Suitable for aggressive sulphate waters (Italy)",
    "IAS": "Suitable for aggressive sulphate waters (Italy)",
    "HE": "High early strength (ASTM/CSA)",
    "CC": "Chromium VI compliant (REACH)",
    "ES": "Expansive / shrinkage-compensating",
}
SPECIAL_IT = {
    "LH": "Basso calore d'idratazione",
    "MH": "Calore d'idratazione medio",
    "SR": "Resistente ai solfati",
    "HSR": "Alta resistenza ai solfati",
    "MSR": "Moderata resistenza ai solfati",
    "SR/IA": "Idoneo al contatto con acque solfatiche",
    "SR/IAS": "Idoneo al contatto con acque solfatiche aggressive",
    "IAS": "Idoneo al contatto con acque solfatiche aggressive",
    "HE": "Alta resistenza iniziale (ASTM/CSA)",
    "CC": "Conforme Cromo VI (REACH)",
    "ES": "Cemento espansivo / ritiro compensato",
}

SEP_PATTERN = r"[,\s/–\-]+"


def _tokenize(raw: str) -> str:
    s = raw.upper().strip()
    s = s.replace("–", "-").replace("—", "-")
    return s


def _extract_family(text: str):
    m = re.search(r"\b(?:CEM|TIPO)?\s*(I{1,3}|IV|V)\s*(?:/\s*([ABC]))?\b", text)
    if m:
        fam, sub = m.group(1), m.group(2)
        return fam, sub
    return None, None


def _extract_additions(text: str) -> List[str]:
    additions: List[str] = []
    for pm in re.finditer(r"\(([A-Z][A-Z]?(?:[-/][A-Z][A-Z]?)*?)\)", text):
        inside = pm.group(1)
        parts = re.split(r"[-/,+\s]+", inside)
        for p in parts:
            if p and p in ADDITIONS_EN and p not in additions:
                additions.append(p)
    m = re.search(r"(?:I{1,3}|IV|V)\s*/?\s*[ABC]?\s*-\s*([A-Z]{1,2})\b", text)
    if m:
        c = m.group(1)
        if c in ADDITIONS_EN and c not in additions:
            additions.append(c)
    for sm in re.finditer(r"-(LL|L|S|P|V|W|M)\b", text):
        c = sm.group(1)
        if c in ADDITIONS_EN and c not in additions:
            additions.append(c)
    return additions


def _extract_strength(text: str):
    m = re.search(r"\b(22[,\.]5|32[,\.]5|42[,\.]5|52[,\.]5|62[,\.]5)\b", text)
    if not m:
        return None, None
    raw = m.group(1).replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        val = None
    display = m.group(1)
    return display, val


def _extract_early_strength(text: str) -> Optional[str]:
    for m in re.finditer(r"(22[,\.]5|32[,\.]5|42[,\.]5|52[,\.]5|62[,\.]5)\s*([NRL])\b", text):
        return m.group(2)
    m = re.search(r"\b([NRL])\b", text)
    return m.group(1) if m else None


def _extract_special_marks(text: str) -> List[str]:
    specials: List[str] = []
    for seg in re.findall(r"(?:^|[\s\-])([A-Z]{2,}(?:/[A-Z]{2,})+)\b", text):
        parts = seg.split("/")
        for p in parts:
            if p in SPECIAL_EN and p not in specials:
                specials.append(p)
        if "SR" in parts and "IAS" in parts and "SR/IAS" in SPECIAL_EN and "SR/IAS" not in specials:
            specials.append("SR/IAS")
        if "SR" in parts and "IA" in parts and "SR/IA" in SPECIAL_EN and "SR/IA" not in specials:
            specials.append("SR/IA")
    for key in sorted(SPECIAL_EN.keys(), key=len, reverse=True):
        pattern = r"\b" + re.escape(key) + r"\b"
        if re.search(pattern, text) and key not in specials:
            specials.append(key)
    if "IAS" in specials and ("SR/IAS" in specials or "SR/IA" in specials):
        specials = [s for s in specials if s != "IAS"]
    return specials


def fn129_decode_cement_marking(raw: str) -> Dict:
    """Decode a cement designation string (Italian/EN 197-1 style) into structured fields."""
    text = _tokenize(raw)
    family, subclass = _extract_family(text)
    additions_codes = _extract_additions(text)
    strength_raw, strength_val = _extract_strength(text)
    early = _extract_early_strength(text)
    specials = _extract_special_marks(text)
    family_en = FAMILY_NAME_EN.get(family, None) if family else None
    family_it = FAMILY_NAME_IT.get(family, None) if family else None
    subclass_en = SUBCLASS_RANGES_EN.get((family, subclass), None) if family and subclass else None
    subclass_it = SUBCLASS_RANGES_IT.get((family, subclass), None) if family and subclass else None
    additions_en = [ADDITIONS_EN.get(c, c) for c in additions_codes] if additions_codes else []
    additions_it = [ADDITIONS_IT.get(c, c) for c in additions_codes] if additions_codes else []
    early_en = EARLY_EN.get(early, None) if early else None
    early_it = EARLY_IT.get(early, None) if early else None
    specials_en = [SPECIAL_EN.get(s, s) for s in specials] if specials else []
    specials_it = [SPECIAL_IT.get(s, s) for s in specials] if specials else []
    return {
        "raw": raw,
        "family_code": family,
        "subclass": subclass,
        "additions_codes": additions_codes,
        "strength_class": strength_raw,
        "strength_MPa": strength_val,
        "early_strength_code": early,
        "special_marks": specials,
        "family_en": family_en,
        "family_it": family_it,
        "subclass_range_en": subclass_en,
        "subclass_range_it": subclass_it,
        "additions_en": additions_en,
        "additions_it": additions_it,
        "early_strength_en": early_en,
        "early_strength_it": early_it,
        "special_en": specials_en,
        "special_it": specials_it,
    }


def fn130_decode_many_cement(markings: List[str]) -> List[Dict]:
    """Batch cement decoder."""
    return [fn129_decode_cement_marking(m) for m in markings]


# ════════════════════════════════════════════════════════════════════════════
# CONFIG LOADING
# ════════════════════════════════════════════════════════════════════════════

_UI_CONFIG_PATH = "aux__ui_config.json"


_UI_CONFIG_MEMO: dict = {"mtime": None, "cfg": {}}


def fn131_load_aux_ui_config() -> dict:
    """Read aux__ui_config.json, memoized on file mtime.

    Live edits still apply on the next rerun (mtime changes → re-read),
    but unchanged files skip the per-rerun disk read + JSON parse.
    """
    try:
        _mtime = os.stat(_UI_CONFIG_PATH).st_mtime_ns
        if _UI_CONFIG_MEMO["mtime"] != _mtime:
            with open(_UI_CONFIG_PATH, "r", encoding="utf-8") as _f:
                _UI_CONFIG_MEMO["cfg"] = json.load(_f)
            _UI_CONFIG_MEMO["mtime"] = _mtime
        return _UI_CONFIG_MEMO["cfg"]
    except Exception:
        return {}


def _expand_tabular_cv(raw: dict) -> dict:
    """Expand delta-encoded tabular_column_visibility back to full per-type dicts.

    Format in JSON:
      ``_base`` — section → col → default visibility (bool)
      ``<ProductType>`` — section → col → override (only where different from base)

    Calling code receives the same structure as before (full per-type dicts),
    so no downstream changes are needed.
    """
    base = raw.get("_base", {})
    if not base:
        # Legacy format (no _base key) — return as-is
        return {k: v for k, v in raw.items() if not k.startswith("_")}

    import copy
    expanded: dict = {}
    for pt, delta in raw.items():
        if pt.startswith("_"):
            continue
        full: dict = copy.deepcopy(base)
        for sec, cols in delta.items():
            if sec in full:
                full[sec].update(cols)
            else:
                full[sec] = cols
        expanded[pt] = full
    return expanded


def fn132_session_ui_config_bundle() -> dict:
    """Keys for st.session_state.update(...), rebuilt from JSON every run.

    Handles the delta-encoded ``tabular_column_visibility`` format transparently
    via ``_expand_tabular_cv``.
    """
    cfg = fn131_load_aux_ui_config() or {}
    fv = cfg.get("field_visibility") or {"default": {}}
    if "default" not in fv:
        fv = {**fv, "default": {}}
    fvi  = {k.lower(): v for k, v in fv.items()}
    fvkm = {k.lower(): k for k in fv.keys()}
    fw   = cfg.get("filter_widget") or {}
    tcv_raw = cfg.get("tabular_column_visibility") or {"default": {}}
    tcv = _expand_tabular_cv(tcv_raw)
    if "default" not in tcv:
        tcv["default"] = {}
    return {
        "FIELD_VISIBILITY":          fv,
        "FIELD_VISIBILITY_INDEX":    fvi,
        "FIELD_VISIBILITY_KEY_MAP":  fvkm,
        "FIELD_META":                cfg.get("field_meta")      or {},
        "FIELD_UI_SETTINGS":         cfg.get("field_ui_settings") or {},
        "TABULAR_COLUMN_VISIBILITY": tcv,
        "MANUFACTURER_LOGOS":        cfg.get("manufacturer_logos") or {},
        "FILTER_WIDGET_COLUMNS":     fw.get("columns")          or [],
        "FILTER_WIDGET_DEFAULT_COLS":fw.get("default_columns")  or [],
        "CHART_WIDGET_SETTINGS":     cfg.get("chart_widget")    or {},
        "COLUMN_DISPLAY_LABELS":     cfg.get("column_display_labels") or {},
    }


# ════════════════════════════════════════════════════════════════════════════
# DATAFRAME UTILITIES (fn121-fn128)
# ════════════════════════════════════════════════════════════════════════════

def fn121_clean_columns(raw_rows, exclude_keywords=None):
    """Convert raw rows to DataFrame; remove columns matching exclude_keywords."""
    exclude_keywords = exclude_keywords or []
    headers = raw_rows[0]
    data_rows = raw_rows[1:]
    filtered_indices = [
        i for i, h in enumerate(headers)
        if all(kw.lower() not in h.lower() for kw in exclude_keywords)
    ]
    filtered_headers = [headers[i] for i in filtered_indices]
    filtered_data = [[row[i] for i in filtered_indices] for row in data_rows]
    seen = {}
    unique_headers = []
    for h in filtered_headers:
        if h not in seen:
            seen[h] = 1
            unique_headers.append(h)
        else:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
    df = pd.DataFrame(filtered_data, columns=unique_headers)
    return df


# Legacy SharePoint V__ / V_* headers → VO__ (VOC) and VV__ (Various).
SHAREPOINT_LEGACY_V_RENAMES: dict[str, str] = {
    "V__VOC_Body": "VO__VOC_Body",
    "V__VOC_Cert": "VO__VOC_Cert",
    "V_Test_Standard": "VO__TestStandard",
    "V_Report_Type": "VO__ReportType",
    "V__VOC_URL": "VO__VOC_URL",
    "V__VOC_Cert_No": "VO__VOC_Cert_No",
    "V__Exp_Date": "VO__Exp_Date",
    "V__Application_Scope": "VO__Application_Scope",
    "V__Product_Category": "VO__Product_Category",
    "V__LEED_MR_RawMat": "VV__LEED_MR_RawMat",
    "V__Other": "VV__Other",
    "V__SDS__URL": "VV__MSDS__URL",
    "V__CAM__Status": "VV__CAM__Status",
    "V__CAM__Evidence": "VV__CAM__Evidence",
    "V_CAM_Compliance": "VV__CAM_Compliance",
    "V__CAM_Compliance": "VV__CAM_Compliance",
    "V__DOP": "VV__DOP",
    # Retired composite catalogue columns → VO fields
    "V__VOC": "VO__VOC_Body",
    "V__VOC_Cat": "VO__Product_Category",
    "V__VOC_Local": "VO__VOC_Local",
    "V__VOC_Cert_Number": "VO__VOC_Cert_Number",
    "V__VOC_Cert_Expiry": "VO__VOC_Cert_Expiry",
    "V__VOC_Cert_Parse_Status": "VO__VOC_Cert_Parse_Status",
    "V__TestStandard": "VO__TestStandard",
    "V__ReportType": "VO__ReportType",
}


def apply_sharepoint_v_column_renames(df: pd.DataFrame) -> pd.DataFrame:
    """Rename legacy V__/V_* Excel columns when loading older parquet/exports."""
    if df is None or len(df.columns) == 0:
        return df
    renames = {
        old: new
        for old, new in SHAREPOINT_LEGACY_V_RENAMES.items()
        if old in df.columns and new not in df.columns
    }
    if not renames:
        return df
    return df.rename(columns=renames)


# Column-name prefixes the dataset's own schema uses (0__ is the id block).
SCHEMA_COLUMN_PREFIXES: tuple[str, ...] = (
    "0__", "A__", "B__", "C__", "D__", "E__", "G__",
    "P__", "R__", "U__", "V__", "VO__", "VV__",
)


def fn122_clean_dataframe(df, key_column=None):
    """Clean DataFrame: drop empties, markers, Excel artifacts, section headers."""
    df_cleaned = df.dropna(how='all')
    df_cleaned = apply_sharepoint_v_column_renames(df_cleaned)
    try:
        unnamed_cols = [
            c for c in df_cleaned.columns
            if str(c).strip() == "" or str(c).strip().lower().startswith("unnamed")
        ]
        if unnamed_cols:
            df_cleaned = df_cleaned.drop(columns=unnamed_cols)
    except Exception:
        pass
    try:
        # The workbook ends its real columns at VV__DOP and everything past it is
        # Excel scratch, so the frame is cut there — but the edit log can carry
        # columns the base parquet never had (D__IncludedProducts), and a merge
        # appends those at the end, right into the part being cut. Keep anything
        # past VV__DOP that is a properly prefixed data column; drop the rest.
        for _last_col in ("VV__DOP", "V__DOP"):
            if _last_col in df_cleaned.columns:
                cols = list(df_cleaned.columns)
                last_idx = cols.index(_last_col)
                keep = cols[: last_idx + 1] + [
                    c for c in cols[last_idx + 1:]
                    if str(c).startswith(SCHEMA_COLUMN_PREFIXES)
                ]
                df_cleaned = df_cleaned[keep]
                break
    except Exception:
        pass
    try:
        star_cols = [c for c in df_cleaned.columns if str(c).strip().startswith("*")]
        if star_cols:
            df_cleaned = df_cleaned.drop(columns=star_cols)
    except Exception:
        pass
    try:
        if df_cleaned is not None and not df_cleaned.empty:
            candidate_cols = [
                c for c in df_cleaned.columns
                if str(c).startswith(
                    ("A__", "B__", "C__", "D__", "E__", "G__", "P__", "R__", "U__", "V__", "VO__", "VV__")
                )
            ]
            if not candidate_cols:
                candidate_cols = list(df_cleaned.columns)
            starts_star = (
                df_cleaned[candidate_cols]
                .astype(str)
                .apply(lambda s: s.str.strip().str.startswith("*"))
            )
            if hasattr(starts_star, "any"):
                df_cleaned = df_cleaned[~starts_star.any(axis=1)]
    except Exception:
        pass
    if df_cleaned is None or df_cleaned.empty or len(df_cleaned.columns) == 0:
        return df_cleaned
    try:
        def _is_empty_cell_series(s: pd.Series) -> pd.Series:
            s2 = s.astype(str).str.strip()
            return s.isna() | (s2 == "") | (s2 == "-") | (s2.str.lower() == "nan")
        map_col = "A__Map_yn" if "A__Map_yn" in df_cleaned.columns else None
        name_col = "A__ProductName" if "A__ProductName" in df_cleaned.columns else None
        manu_col = "A__Manufacturer" if "A__Manufacturer" in df_cleaned.columns else None
        if name_col and manu_col:
            name_empty = _is_empty_cell_series(df_cleaned[name_col])
            manu_empty = _is_empty_cell_series(df_cleaned[manu_col])
            if map_col:
                map_is_y = df_cleaned[map_col].astype(str).str.strip().str.upper() == "Y"
                df_cleaned = df_cleaned[~((~map_is_y) & name_empty & manu_empty)]
            else:
                df_cleaned = df_cleaned[~(name_empty & manu_empty)]
    except Exception:
        pass
    if key_column is None or key_column not in df_cleaned.columns:
        key_column = df_cleaned.columns[0]
    key_series = df_cleaned[key_column].astype(str).str.strip()
    df_cleaned = df_cleaned[(key_series != None) & (~key_series.str.startswith("*"))]
    return normalize_product_type_column(df_cleaned)


# Canonical D__ProductType_ENG labels (SharePoint renames → app standard).
PRODUCT_TYPE_ALIASES: dict[str, str] = {
    "glazing (doors & windows)": "Windows & Doors - Glazing",
    "glazing (doors and windows)": "Windows & Doors - Glazing",
}


def canonical_product_type(value) -> str:
    """Map legacy SharePoint product-type strings to the canonical label."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or text == "-":
        return ""
    return PRODUCT_TYPE_ALIASES.get(text.lower(), text)


def normalize_product_type_column(df: pd.DataFrame) -> pd.DataFrame:
    """Rewrite D__ProductType_ENG using PRODUCT_TYPE_ALIASES."""
    col = "D__ProductType_ENG"
    if df is None or df.empty or col not in df.columns:
        return df
    out = df.copy()
    out[col] = out[col].apply(canonical_product_type)
    return out


def fn128_filter_map_y_products(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows flagged for catalogue/maps (A__Map_yn == Y)."""
    if df is None or df.empty or "A__Map_yn" not in df.columns:
        return df
    mask = df["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"
    return df.loc[mask].copy()


def fn123_clean_dataframe_columns(df):
    """Strip column prefixes (A__, B__, …), remove URL cols and *-cols."""
    df_cleaned = df.copy()
    df_cleaned = df_cleaned.loc[:, ~df_cleaned.columns.str.startswith('*')]
    df_cleaned = df_cleaned.loc[:, ~df_cleaned.columns.str.contains('URL|url', case=False)]
    column_mapping = {}
    for col in df_cleaned.columns:
        if '__' in col:
            new_name = '__'.join(col.split('__')[1:])
            column_mapping[col] = new_name
        else:
            column_mapping[col] = col
    df_cleaned = df_cleaned.rename(columns=column_mapping)
    return df_cleaned


def _fn123_cleaned_names(columns) -> list[str]:
    """fn123's column renaming, on names alone (same filters, same order)."""
    cols = pd.Index(columns)
    cols = cols[~cols.str.startswith('*')]
    cols = cols[~cols.str.contains('URL|url', case=False)]
    return ['__'.join(c.split('__')[1:]) if '__' in c else c for c in cols]


def fn124_get_cleaned_column_names(df):
    """Return list of cleaned column names.

    Works on the column names only: it used to run fn123 (a copy of the whole
    frame plus a rename) just to read ``.columns``, several times per Charts run.
    """
    return _fn123_cleaned_names(df.columns)


def fn125_get_original_column_name(df, cleaned_name):
    """Reverse lookup: cleaned column name → original column name."""
    for original_col in df.columns:
        if '__' in original_col:
            new_name = '__'.join(original_col.split('__')[1:])
        else:
            new_name = original_col
        if 'URL' in original_col.upper() or original_col.startswith('*'):
            continue
        if new_name == cleaned_name:
            return original_col
    return cleaned_name


def fn126_get_numeric_columns(df):
    """Return predefined numeric column names that exist in df."""
    predefined_numeric_columns = [
        'P__U_Wm2K', 'P__L_WmK', 'P__Thick_mm', 'P__Mass_kgm3', 'P__Mass_kgm2', 'P__Mass_kg',
        'G__GWP_A1A3_m2', 'G__GWP_A1A3_m3', 'G__GWP_A1A3_m2R1', 'G__GWP_A1A3',
        'G__GWP_A1', 'G__GWP_A2', 'G__GWP_A3',
        'R__Rec_Pre_%', 'R__Rec_Post_%', 'R__Rec_Tot_%',
        'R__Reco_Tot_%', 'R__ByProd_Tot_%', 'R__Rec_Reco_ByProd_%',
        # list prices — derived by libs/lib_prices.py fn507, attached in app.py
        'PR__Price_EUR_m2', 'PR__Cost_per_R', 'PR__R_m2KW',
    ]
    return [col for col in predefined_numeric_columns if col in df.columns]


def fn127_get_cleaned_numeric_column_names(df):
    """Return cleaned column names for predefined numeric columns only."""
    return _fn123_cleaned_names(fn126_get_numeric_columns(df))


# Columns kept in the data (and the Revalu export) but hidden everywhere in the
# app: Add/Edit form, sidebar filters, completeness counts and matrices.
HIDDEN_APP_COLUMNS = frozenset({"D__Int/Ext", "D__Application"})


def fn128_clean_column_name(col):
    """Human-friendly display label for a column name."""
    if '__' in col:
        col = '__'.join(col.split('__')[1:])
    replacements = {
        'ProductType_ENG': 'Product Type',
        'MaterialType_ENG': 'Material Type',
        'Mass_kgm3': 'Vol. Density (kg/m³)',
        'Mass_m3': 'Vol. Density (kg/m³)',
        'Mass_kgm2': 'Sup. Density (kg/m²)',
        'Thick_mm': 'Thickness (mm)',
        'Thickness_mm': 'Thickness (mm)',
        'Lambda_WmK': 'Thermal Conductivity (W/mK)',
        'FireRating': 'Fire Rating',
        'ServiceLife': 'Service Life',
        'EPD_RegNumber': 'EPD Registration',
        'EPD_URL': 'EPD Link',
        'Img_URL': 'Image URL',
        'ProductInfo_URL': 'Product Info',
        'TechDetails_URL': 'Technical Details',
        'WaterVaporResistance': 'Water Vapor Resistance',
        'SoundAbsorption': 'Sound Absorption',
        'CompressiveStrength': 'Compressive Strength',
        'DimensionalStability': 'Dimensional Stability',
        'Reco_Tot_%': 'Recycling Rate (%)',
        'Rec_Reco_ByProd_%': 'Recycled Content',
        'GWP_A1A3': 'GWP A1-A3 (FU/DU)',
        'GWP_FU': 'GWP FU/DU',
        'GWP_A1A3_m2R1': 'GWP per m² (R=1)',
        'GWP_A1A3_m3': 'GWP per m³',
        'GWP_A1A3_m2': 'GWP per m²',
        'GWP_Metric': 'GWP Metric',
        'Comments': 'Comments',
        'TechDetails': 'Technical Details',
    }
    for old, new in replacements.items():
        if old in col:
            col = col.replace(old, new)
            break
    col = col.replace('_', ' ')
    col = ' '.join(word.capitalize() for word in col.split())
    return col


def fn128a_display_label_for_original(original_col: str, column_display_labels: dict | None = None) -> str:
    """
    Human-readable label for an Excel/internal column name.

    Prefer ``aux__ui_config.json`` → ``column_display_labels`` (keys = original
    column names such as ``R__Rec_Reco_ByProd_%``). Falls back to ``fn128_clean_column_name``.
    """
    column_display_labels = column_display_labels or {}
    if original_col in column_display_labels:
        label = str(column_display_labels.get(original_col, "")).strip()
        if label:
            return label
    return fn128_clean_column_name(original_col)


def fn128b_display_label_for_cleaned(df, cleaned_name, column_display_labels: dict | None = None) -> str:
    """Resolve fn123-style cleaned name → display label via ``fn125`` + ``fn128a``."""
    orig = fn125_get_original_column_name(df, cleaned_name)
    return fn128a_display_label_for_original(orig, column_display_labels)


# ════════════════════════════════════════════════════════════════════════════
# LOCAL MEDIA (data/img, data/pdf) — names match tools/upload_to_motherduck.py
# ════════════════════════════════════════════════════════════════════════════

_MATLIB_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_IMG_DIR = _MATLIB_ROOT / "01_data" / "img"
_LOCAL_PDF_DIR = _MATLIB_ROOT / "01_data" / "pdf"
_LOCAL_DATA_DIR = _MATLIB_ROOT / "01_data"


def _clean_row_field(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    return "" if s in ("", "-", "nan", "None", "NaN") else s


def make_media_filename(eetra_id: str, product_name: str, suffix_with_ext: str) -> str:
    """Same rules as upload_to_motherduck.make_media_filename (slug + lowercased suffix)."""
    slug = re.sub(r"[^\w\s-]", "", product_name)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-{2,}", "-", slug)
    return f"{eetra_id}_{slug}{suffix_with_ext.lower()}"


def ext_from_url(url: str) -> str:
    if not url:
        return ""
    path = str(url).split("?")[0].split("#")[0]
    suf = Path(path).suffix.lower()
    return suf if len(suf) <= 5 else ""


# ── Directory indexes: one listing instead of a probe per candidate ──────────
# The media resolvers below all work the same way — build a candidate filename,
# ask the filesystem whether it exists, repeat across five or six extensions and
# up to two directories. That is up to a dozen stat() calls to locate one image,
# and this project lives inside a OneDrive folder, where every one of them goes
# through the sync filter driver at roughly a millisecond each. On a cold render
# that measured 11,711 stat calls and ~4.5s, over 3.5s of it in
# static_img_cache_url alone.
#
# Listing a directory once costs a single scandir and answers every candidate
# from a dict. The index is keyed on the directory's mtime, so a file added by
# the pipeline (or by another process) is picked up on the next lookup.
#
# The freshness check is itself rate-limited. Checking the directory's mtime per
# lookup is one stat instead of a dozen, but the catalogue makes thousands of
# lookups and on this volume even a directory stat costs ~0.4ms — that alone
# measured 2,534 calls and 1.0s. Re-checking at most every
# _DIR_INDEX_TTL_S seconds brings it down to a couple of stats per render while
# still noticing a file the pipeline dropped in: the window is shorter than the
# gap between reruns, and files *this* process writes are registered immediately
# by _dir_index_note_added, so the case that matters is never stale.
_DIR_INDEX_TTL_S = 2.0

# key -> (checked_at_monotonic, dir_mtime_ns, {lowercased name: actual name})
_DIR_INDEX_CACHE: "dict[str, tuple[float, int, dict[str, str]]]" = {}


def _dir_mtime_ns(directory: Path) -> int:
    try:
        return os.stat(directory).st_mtime_ns
    except OSError:
        return -1


def _dir_file_index(directory: Path) -> "dict[str, str]":
    """``{lowercased filename: actual filename}`` for *directory*.

    Rebuilt when the directory's mtime moves — which happens when an entry is
    added or removed, exactly the changes that could affect a lookup — and at
    most once per _DIR_INDEX_TTL_S.
    """
    key = str(directory)
    now = time.monotonic()
    hit = _DIR_INDEX_CACHE.get(key)
    if hit is not None and (now - hit[0]) < _DIR_INDEX_TTL_S:
        return hit[2]

    mtime = _dir_mtime_ns(directory)
    if mtime == -1:
        _DIR_INDEX_CACHE.pop(key, None)
        return {}
    if hit is not None and hit[1] == mtime:
        _DIR_INDEX_CACHE[key] = (now, mtime, hit[2])  # unchanged; just re-stamp
        return hit[2]
    try:
        with os.scandir(directory) as it:
            names = {e.name.lower(): e.name for e in it if e.is_file()}
    except OSError:
        names = {}
    _DIR_INDEX_CACHE[key] = (now, mtime, names)
    return names


def _dir_index_note_added(directory: Path, filename: str) -> None:
    """Record a file this process just wrote, without forcing a rescan.

    Writing into an indexed directory moves its mtime, so the next freshness
    check would otherwise rescan — and the catalogue writes hundreds of
    thumbnails in one pass, which would make that O(n²). Adding the entry and
    re-stamping both the mtime and the check time keeps the index correct for
    our own writes while still rescanning if someone else changes the directory.
    """
    key = str(directory)
    hit = _DIR_INDEX_CACHE.get(key)
    if hit is None:
        return
    hit[2][filename.lower()] = filename
    _DIR_INDEX_CACHE[key] = (time.monotonic(), _dir_mtime_ns(directory), hit[2])


def _dir_has_file(directory: Path, filename: str) -> bool:
    return filename.lower() in _dir_file_index(directory)


def resolve_local_product_image_path(url: str, eetra_id: str, product_name: str) -> Optional[Path]:
    """Prefer data/img/, then legacy flat data/. Tries URL extension then common image types."""
    raw_id = _clean_row_field(eetra_id)
    raw_name = _clean_row_field(product_name)
    if not raw_id or not raw_name:
        return None
    ordered_exts: list[str] = []
    eu = ext_from_url(url or "")
    if eu:
        ordered_exts.append(eu)
    for alt in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if alt not in ordered_exts:
            ordered_exts.append(alt)
    for ext in ordered_exts:
        fn = make_media_filename(raw_id, raw_name, ext)
        for base in (_LOCAL_IMG_DIR, _LOCAL_DATA_DIR):
            if _dir_has_file(base, fn):
                return base / fn
    return None


def resolve_hash_local_image_path(url: str) -> Optional[Path]:
    """Pipeline stores images as ``01_data/img/<sha256(url)[:16]>.<ext>``."""
    s = str(url or "").strip()
    if not s or s == "-":
        return None
    for candidate in (s, normalize_product_image_url(s)):
        if not candidate.startswith("http"):
            continue
        key = hashlib.sha256(candidate.encode()).hexdigest()[:16]
        ordered_exts: list[str] = []
        eu = ext_from_url(candidate)
        if eu:
            ordered_exts.append(eu)
        for alt in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".aspx"):
            if alt not in ordered_exts:
                ordered_exts.append(alt)
        for ext in ordered_exts:
            if _dir_has_file(_LOCAL_IMG_DIR, f"{key}{ext}"):
                return _LOCAL_IMG_DIR / f"{key}{ext}"
    return None


def hash_image_object_keys(url: str) -> list[tuple[str, str]]:
    """``[(sha256(url)[:16], ext_hint), ...]`` — the keys 01_data/img would use.

    Shares its key scheme with :func:`resolve_hash_local_image_path` on purpose:
    the bucket mirrors that folder 1:1, so the two must never drift apart on
    naming. ``ext_hint`` is the extension the URL itself suggests, which saves
    the remote tier a probe when it is right.
    """
    s = str(url or "").strip()
    if not s or s == "-":
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in (s, normalize_product_image_url(s)):
        if not candidate.startswith("http"):
            continue
        key = hashlib.sha256(candidate.encode()).hexdigest()[:16]
        if key in seen:
            continue
        seen.add(key)
        out.append((key, ext_from_url(candidate)))
    return out


def fetch_remote_image_original(url):
    """Product-image original from the configured bucket, downscaled, or None.

    Sits between the local tiers and the live manufacturer fetch in
    :func:`fn110_cached_fetch_image`. The bucket holds exactly what 01_data/img
    holds, so a hit here means the picture survived a checkout that has no
    image folder, or a source URL that has since rotted. Every failure path
    returns None and the caller carries on to the live fetch, so switching
    storage on can only add hits, never take any away.

    The import is deferred because lib_doc_storage imports from this module;
    pulling it in at module scope would close the cycle.
    """
    try:
        from .lib_doc_storage import fn_fetch_image_bytes, fn_storage_enabled
    except Exception:
        return None
    try:
        if not fn_storage_enabled():
            return None
        mw, mh = _catalogue_image_max_dims()
        for key, ext_hint in hash_image_object_keys(url):
            data, _provider = fn_fetch_image_bytes(key, ext_hint=ext_hint)
            if not data or not _bytes_look_like_image(data):
                continue
            try:
                return _pil_downscale_if_needed(_pil_open_safe(BytesIO(data)), mw, mh)
            except Exception:
                continue
    except Exception:
        return None
    return None


def resolve_local_image_path_from_column(local_rel: str) -> Optional[Path]:
    """Resolve ``U__Img_Local`` (relative to project root) when the file exists."""
    s = str(local_rel or "").strip()
    if not s or s in ("-", "nan", "None"):
        return None
    p = Path(s.replace("\\", "/"))
    if not p.is_absolute():
        p = _MATLIB_ROOT / p
    return p if p.is_file() else None


def pdf_object_name(eetra_id: str, product_name: str, kind: str) -> Optional[str]:
    """Filename for an EPD/tech-sheet PDF: shared by local disk (01_data/pdf/<name>)
    and remote bucket object keys, so local files and uploaded copies line up 1:1.

    kind: 'epd' → *_EPD.pdf, 'tech' → *_TechSheet.pdf.
    """
    raw_id = _clean_row_field(eetra_id)
    raw_name = _clean_row_field(product_name)
    if not raw_id or not raw_name:
        return None
    if kind == "epd":
        suffix = "_EPD.pdf"
    elif kind == "tech":
        suffix = "_TechSheet.pdf"
    else:
        return None
    return make_media_filename(raw_id, raw_name, suffix)


def resolve_local_product_pdf_path(eetra_id: str, product_name: str, kind: str) -> Optional[Path]:
    """kind: 'epd' → *_epd.pdf, 'tech' → *_techsheet.pdf (per upload script lowercasing)."""
    fn = pdf_object_name(eetra_id, product_name, kind)
    if not fn:
        return None
    for base in (_LOCAL_PDF_DIR, _LOCAL_DATA_DIR):
        p = base / fn
        if p.is_file():
            return p
    return None


def _pdf_local_columns_for_kind(kind: str) -> tuple[str, ...]:
    """``*_Local`` parquet columns for document preview (VO__ for VOC)."""
    if kind == "voc":
        return ("VO__VOC_Local", "V__VOC_Local")
    if kind == "epd":
        return ("E__EPD_Local",)
    if kind == "tech":
        return ("U__TechDetails_Local",)
    return ()


def pdf_object_name_from_row(row, kind: str) -> Optional[str]:
    """Bucket object key / expected filename for a row's PDF, independent of whether
    the file is actually present on local disk (unlike :func:`resolve_local_pdf_from_row`).

    Used so a remote bucket lookup can proceed even when 01_data/pdf isn't checked out
    locally (e.g. a slim deployment). Prefers the pipeline-written ``*_Local`` column
    (hash-based filename); falls back to the product-name-based convention.

    kind: 'voc' | 'epd' | 'tech'
    """
    for local_col in _pdf_local_columns_for_kind(kind):
        val = _clean_row_field(row.get(local_col, ""))
        if val:
            return Path(str(val).replace("\\", "/")).name
    return pdf_object_name(
        row.get("0__EETRA_ID", ""),
        row.get("A__ProductName", ""),
        kind,
    )


def resolve_local_pdf_from_row(row, kind: str) -> Optional[Path]:
    """Resolve a local PDF path for a dataframe row, preferring the pre-computed *_Local column.

    Checks the pipeline-written column first (hash-based filename, shared across rows that
    share the same URL), then falls back to the old product-name-based filename convention.

    kind: 'voc' | 'epd' | 'tech'
    """
    for local_col in _pdf_local_columns_for_kind(kind):
        val = _clean_row_field(row.get(local_col, ""))
        if val:
            # Pipeline rows may store legacy "data/..." relative paths from
            # before the folder was renamed to 01_data — try both.
            _val_fs = str(val).replace("\\", "/")
            _cands = [val]
            if _val_fs.startswith("data/"):
                _cands.append("01_data/" + _val_fs[len("data/"):])
            for _v in _cands:
                for base in (Path("."), _LOCAL_PDF_DIR.parent, _LOCAL_DATA_DIR.parent):
                    p = base / _v
                    if p.is_file():
                        return p
    return resolve_local_product_pdf_path(
        row.get("0__EETRA_ID", ""),
        row.get("A__ProductName", ""),
        kind,
    )


def prefer_local_document_href(
    remote_url: str, _eetra_id: str, _product_name: str, _kind: str
) -> str:
    """Return the public ``remote_url`` for hyperlinks (EPD / technical sheet).

    Local copies under ``data/pdf`` are still used for in-app preview/download via
    :func:`resolve_local_product_pdf_path`; browser ``file://`` links are not used here.
    """
    if remote_url is None:
        return ""
    s = str(remote_url).strip()
    return "" if s in ("", "-") else s


def image_path_to_data_uri(path: Path) -> Optional[str]:
    try:
        raw = path.read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        b64 = base64.b64encode(raw).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# IMAGE FETCH HELPERS (private)
# ════════════════════════════════════════════════════════════════════════════

def _pil_open_safe(source) -> Image.Image:
    """Open PIL image; normalise palette/transparency (avoids PIL UserWarning)."""
    img = Image.open(source)
    if img.mode == "P":
        if "transparency" in img.info:
            return img.convert("RGBA")
        return img.convert("RGB")
    if img.mode in ("RGB", "RGBA"):
        return img
    if img.mode in ("LA", "PA") or "A" in img.mode:
        return img.convert("RGBA")
    return img.convert("RGB")


def _read_excel_bytes(buf, **kwargs) -> pd.DataFrame:
    """Load Excel via openpyxl (bypasses pandas' xlrd probe — legacy xlrd breaks on Py3)."""
    sheet_name = kwargs.pop("sheet_name", 0)
    header = kwargs.pop("header", 0)
    kwargs.pop("engine", None)

    try:
        import openpyxl
    except ImportError as e:
        raise ImportError(
            "Reading Excel requires openpyxl. Install with: pip install openpyxl"
        ) from e

    if hasattr(buf, "seek"):
        buf.seek(0)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Data Validation extension is not supported and will be removed",
            category=UserWarning,
        )
        wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
        try:
            if isinstance(sheet_name, int):
                if sheet_name < 0 or sheet_name >= len(wb.sheetnames):
                    raise ValueError(f"sheet_name index {sheet_name} out of range")
                ws = wb[wb.sheetnames[sheet_name]]
            elif sheet_name is None:
                ws = wb[wb.sheetnames[0]]
            else:
                ws = wb[str(sheet_name)]
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()

    if not rows:
        return pd.DataFrame()

    if header is None:
        return pd.DataFrame(rows)

    header_rows = header if isinstance(header, (list, tuple)) else [int(header)]
    if len(header_rows) == 1:
        h = header_rows[0]
        if h < 0 or h >= len(rows):
            raise ValueError(f"header row {h} out of range")
        colnames = ["" if c is None else str(c) for c in rows[h]]
        body = rows[h + 1 :]
        return pd.DataFrame(body, columns=colnames)

    raise ValueError("Multi-row Excel headers are not supported in _read_excel_bytes")


_CATALOGUE_IMAGE_MAX_WIDTH = 300
_CATALOGUE_IMAGE_MAX_HEIGHT = 300


def _catalogue_image_max_dims():
    try:
        from .lib_ui import CATALOGUE_IMAGE_FETCH_MAX_WIDTH, CATALOGUE_IMAGE_FETCH_MAX_HEIGHT
        return int(CATALOGUE_IMAGE_FETCH_MAX_WIDTH), int(CATALOGUE_IMAGE_FETCH_MAX_HEIGHT)
    except Exception:
        return _CATALOGUE_IMAGE_MAX_WIDTH, _CATALOGUE_IMAGE_MAX_HEIGHT


_DEFAULT_IMAGE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

_STATIC_IMG_CACHE_DIR = _MATLIB_ROOT / "static" / "img_cache"


def _image_request_headers(url: str) -> dict:
    """Browser-like headers; Referer helps CDNs that block bare bot requests."""
    headers = dict(_DEFAULT_IMAGE_REQUEST_HEADERS)
    try:
        from urllib.parse import urlparse

        parsed = urlparse(str(url or "").strip())
        if parsed.scheme and parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return headers


def _bytes_look_like_image(data: bytes) -> bool:
    if not data or len(data) < 12:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    return False


def normalize_product_image_url(url: str) -> str:
    """Fix common CMS image-style URLs that 404 while the source file still exists.

    Drupal (Isover and others) often stores ``/files/styles/<style>/public/...`` in
    spreadsheets; on some sites the live file is at ``/files/...`` without the style
    segment. Multisite Drupal paths (``/sites/<site>/files/styles/...``) must keep
    the styled URL — stripping ``styles/.../public`` yields 404.
    """
    s = str(url or "").strip()
    if not s:
        return s
    if "/sites/" in s and "/files/styles/" in s:
        return s
    return re.sub(r"/files/styles/[^/]+/public/", "/files/", s)


def product_image_fetch_candidates(url: str) -> list[str]:
    """Ordered URLs to try when downloading a product image."""
    raw = str(url or "").strip()
    if not raw or raw == "-":
        return []
    norm = normalize_product_image_url(raw)
    out: list[str] = []
    for candidate in (raw, norm):
        if candidate and candidate not in out:
            out.append(candidate)
    return out


# ── Two served tiers ─────────────────────────────────────────────────────────
# The originals under 01_data/img are never touched; these are the sizes the
# browser is actually sent. One size for everything was wrong in both
# directions: measured on the real catalogue, a grid card paints its image into
# 78x70 CSS px (98x94 at the largest grid size) while the detail panel's CSS
# allows up to 180x130 — so a single 300px file was three times too big for the
# grid and too small for a HiDPI detail panel.
#
#   card    "<md5>.webp"      grid thumbnails — the file the catalogue loads 1,600 of
#   detail  "<md5>__d.webp"   the right-hand panel — one at a time, on click
#
# The card tier keeps the bare "<md5>" name so URLs already in a cached payload
# keep resolving. Both are written from a single decode of the source.
_STATIC_IMG_TIER_CARD = "card"
_STATIC_IMG_TIER_DETAIL = "detail"
_STATIC_IMG_TIER_SUFFIX = {_STATIC_IMG_TIER_CARD: "", _STATIC_IMG_TIER_DETAIL: "__d"}


def _static_img_tier_max_px(tier: str) -> int:
    """Longest-edge budget for a tier, from theme.json → image_band."""
    try:
        from .lib_ui import (
            CATALOGUE_IMAGE_CACHE_CARD_MAX_PX,
            CATALOGUE_IMAGE_CACHE_DETAIL_MAX_PX,
        )

        if tier == _STATIC_IMG_TIER_DETAIL:
            return int(CATALOGUE_IMAGE_CACHE_DETAIL_MAX_PX)
        return int(CATALOGUE_IMAGE_CACHE_CARD_MAX_PX)
    except Exception:
        return 400 if tier == _STATIC_IMG_TIER_DETAIL else 200


def _static_img_cache_key(url: str, tier: str = _STATIC_IMG_TIER_CARD) -> str:
    """Filename stem under static/img_cache for *url* at *tier*."""
    candidates = product_image_fetch_candidates(url)
    primary = candidates[0] if candidates else str(url or "").strip()
    return hashlib.md5(primary.encode()).hexdigest() + _STATIC_IMG_TIER_SUFFIX.get(tier, "")


def fn_on_streamlit_cloud() -> bool:
    """True when the browser URL looks like Streamlit Community Cloud."""
    try:
        url = str(getattr(st.context, "url", None) or "").lower()
    except Exception:
        url = ""
    if "streamlit.app" in url or "share.streamlit.io" in url:
        return True
    try:
        if str(os.environ.get("STREAMLIT_SHARING_MODE") or "").strip():
            return True
    except Exception:
        pass
    return False


def static_img_cache_url(url: str, tier: str = _STATIC_IMG_TIER_CARD) -> str:
    """Same-origin URL for a cached product image at *tier*, or "" if not on disk.

    Hottest filesystem path in the app: the catalogue asks this for every image,
    up to three times each (the lookup, then once inside either ensure_ helper),
    and it probes four extensions per candidate URL. Probing that with stat() was
    3,614 calls and 3.5s of a cold render — the directory index answers all of it
    from one listing.
    """
    index = _dir_file_index(_STATIC_IMG_CACHE_DIR)
    if not index:
        return ""
    suffix = _STATIC_IMG_TIER_SUFFIX.get(tier, "")
    for candidate in product_image_fetch_candidates(url):
        key = hashlib.md5(candidate.encode()).hexdigest() + suffix
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if f"{key}{ext}" in index:
                return f"/app/static/img_cache/{key}{ext}"
    return ""


def static_img_payload_url(url_or_path: str) -> str:
    """URL safe to put in the catalogue iframe ``imageUrl`` field.

    Locally ``/app/static/img_cache/…`` is fine (``enableStaticServing``). On
    Community Cloud, files written under ``static/`` at runtime are not reliably
    served to the browser — the same SPA-HTML miss that broke catalogue JSON —
    so rewrite those to a data URI read from the local cache file. Absolute
    ``https://`` / ``data:`` URLs pass through unchanged.
    """
    u = str(url_or_path or "").strip()
    if not u:
        return ""
    if u.startswith(("data:", "http://", "https://")):
        return u
    if not u.startswith("/app/static/img_cache/"):
        return u
    # Prefer HTTP static URLs only when we know the browser can fetch them.
    use_static_http = False
    if not fn_on_streamlit_cloud():
        try:
            use_static_http = bool(st.get_option("server.enableStaticServing"))
        except Exception:
            use_static_http = False
    if use_static_http:
        return u
    name = Path(u).name
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return ""
    path = _STATIC_IMG_CACHE_DIR / name
    if path.is_file():
        return image_path_to_data_uri(path) or ""
    return ""


# ── static/img_cache: the one place catalogue thumbnails are served from ─────
# The catalogue used to base64-inline whatever the source image happened to be:
# full-resolution originals off 01_data/img, straight into the component's
# srcdoc. Against base_data.parquet that was 237 MB of source bytes (~316 MB
# once base64-encoded) for a 100 px-tall image band, and because the memo key
# carried the product id, the 552 distinct files were re-encoded once per each
# of the 1,580 rows referencing them.
#
# Everything now goes through here instead: downscaled once to the catalogue
# thumbnail budget (theme.json → image_band.fetch_max_*), written under
# static/img_cache keyed on the image URL, and referenced from the payload as a
# short "/app/static/img_cache/<md5>.webp" URL. The component already resolves
# those (productImageSrc → appStaticUrl) and already marks the tags
# loading="lazy", so the browser fetches only what scrolls into view and caches
# it across reruns.
#
# WebP because these are photographic product shots at thumbnail size; PNG is
# the fallback when Pillow was built without the WebP encoder. Note the probe
# order in static_img_cache_url() puts .png first, so entries written by older
# versions keep working and are not rewritten.
_STATIC_IMG_CACHE_WEBP_QUALITY = 82


def _prune_stale_tier_variants(dest: Path) -> None:
    """Delete same-key files at a different extension, so one tier = one file.

    static_img_cache_url probes ``.png`` before ``.webp`` (so entries written by
    older versions of this app keep resolving). That order means a leftover PNG
    silently shadows a newer WebP written beside it: the thumbnail gets rebuilt
    at a new size and the stale one is still what gets served. Removing the
    other-extension sibling on write keeps exactly one file per key, which is
    what the probe assumes.

    Matches on the exact stem, so a card write ("<md5>") never touches its detail
    sibling ("<md5>__d").
    """
    try:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if ext == dest.suffix:
                continue
            stale = dest.with_suffix(ext)
            if stale.is_file():
                stale.unlink()
                _dir_index_drop(stale.parent, stale.name)
    except OSError:
        pass


def _dir_index_drop(directory: Path, filename: str) -> None:
    """Forget a file this process just deleted (mirror of _dir_index_note_added)."""
    key = str(directory)
    hit = _DIR_INDEX_CACHE.get(key)
    if hit is None:
        return
    hit[2].pop(filename.lower(), None)
    _DIR_INDEX_CACHE[key] = (time.monotonic(), _dir_mtime_ns(directory), hit[2])


def _write_static_img_cache_atomic(img, dest: Path) -> bool:
    """Encode *img* to *dest* via a per-thread temp file + os.replace.

    Atomic because the catalogue resolves images from a ThreadPoolExecutor and
    several rows routinely share one image URL: without this, two workers can
    interleave writes and the reader serves a truncated file.
    """
    tmp = dest.with_name(f"{dest.stem}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        if dest.suffix == ".webp":
            img.save(tmp, format="WEBP", quality=_STATIC_IMG_CACHE_WEBP_QUALITY, method=4)
        else:
            img.save(tmp, format="PNG", optimize=True)
        os.replace(tmp, dest)
        _dir_index_note_added(dest.parent, dest.name)
        _prune_stale_tier_variants(dest)
        return True
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _static_img_cache_extension() -> str:
    try:
        from PIL import features

        if features.check("webp"):
            return ".webp"
    except Exception:
        pass
    return ".png"


def ensure_static_img_cache(url: str, img) -> "dict[str, str]":
    """Write both served tiers of *img*, returning ``{tier: url}``.

    One decode of the source produces both sizes. Returns ``{}`` when nothing
    could be written, so callers can fall back to their previous behaviour (a
    data URI, or the remote URL) rather than render a gap; a partial result is
    possible and callers should treat a missing detail tier as "use the card".
    """
    if img is None:
        return {}
    out: dict[str, str] = {}
    try:
        _STATIC_IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ext = _static_img_cache_extension()
        for tier in (_STATIC_IMG_TIER_CARD, _STATIC_IMG_TIER_DETAIL):
            existing = static_img_cache_url(url, tier)
            if existing:
                out[tier] = existing
                continue
            budget = _static_img_tier_max_px(tier)
            # Never upscales, so a small source simply stays its own size and the
            # two tiers can legitimately come out identical.
            thumb = _pil_downscale_if_needed(img, budget, budget)
            key = _static_img_cache_key(url, tier)
            dest = _STATIC_IMG_CACHE_DIR / f"{key}{ext}"
            if _write_static_img_cache_atomic(thumb, dest):
                out[tier] = f"/app/static/img_cache/{key}{ext}"
    except Exception:
        pass
    return out


def ensure_static_img_cache_from_path(url: str, path: Path) -> "dict[str, str]":
    """:func:`ensure_static_img_cache` for an image already on local disk.

    This is the path that used to base64-inline the original file. Decoding the
    source costs the same as reading it did; the saving is that it happens once
    per image instead of once per row, both tiers come out of that one decode,
    and the payload carries URLs afterwards. The file at *path* is only read.
    """
    have = {
        tier: url_
        for tier in (_STATIC_IMG_TIER_CARD, _STATIC_IMG_TIER_DETAIL)
        if (url_ := static_img_cache_url(url, tier))
    }
    if len(have) == 2:
        return have
    try:
        with Image.open(path) as _probe:
            _probe.load()
            img = _pil_open_safe_loaded(_probe)
    except Exception:
        return have
    return ensure_static_img_cache(url, img) or have


def _pil_open_safe_loaded(img: Image.Image) -> Image.Image:
    """:func:`_pil_open_safe`'s normalisation for an already-open image."""
    if img.mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode in ("RGB", "RGBA"):
        return img.copy()
    if img.mode in ("LA", "PA") or "A" in img.mode:
        return img.convert("RGBA")
    return img.convert("RGB")


def save_static_img_cache(url: str, img) -> str:
    """Persist a fetched PIL image under ``static/img_cache``; return its card URL.

    Retained name and single-URL return for the live-fetch call site; tiering,
    downscaling and the atomic write come from :func:`ensure_static_img_cache`.
    """
    written = ensure_static_img_cache(url, img)
    return written.get(_STATIC_IMG_TIER_CARD, "")


_IMG_FETCH_TIMEOUT = (3, 8)   # (connect, read) seconds


def _requests_get_image_url(url: str, *, timeout=_IMG_FETCH_TIMEOUT):
    """GET product image URL; retry without TLS verify when the cert chain fails."""
    headers = _image_request_headers(url)
    try:
        return requests.get(
            url,
            timeout=timeout,
            verify=True,
            headers=headers,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError:
        return requests.get(
            url,
            timeout=timeout,
            verify=False,
            headers=headers,
            allow_redirects=True,
        )


def catalogue_image_is_placeholder(img) -> bool:
    """True for fn134 grey 'Picture Not Available' tile (not a real product photo)."""
    try:
        if img is None or img.size != (300, 160):
            return False
        px = img.getpixel((10, 10))
        rgb = px[:3] if isinstance(px, tuple) else (px, px, px)
        return rgb == (220, 220, 220)
    except Exception:
        return False


def catalogue_image_cache_is_valid(img) -> bool:
    """Reject stale/placeholder catalogue cache entries (e.g. failed SSL prefetch)."""
    if img is None or catalogue_image_is_placeholder(img):
        return False
    try:
        w, h = img.size
        return w >= 64 and h >= 64
    except Exception:
        return False


def _pil_downscale_if_needed(img, max_w, max_h):
    """Shrink only when wider/taller than max; never upscale."""
    try:
        _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
    except Exception:
        _LANCZOS = Image.LANCZOS
    try:
        w, h = img.size
        if w <= max_w and h <= max_h:
            out = img.copy()
        else:
            scale = min(max_w / w, max_h / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            out = img.resize((nw, nh), _LANCZOS)
        if out.mode == "RGBA":
            ch = out.split()
            bg = Image.new("RGB", out.size, (255, 255, 255))
            bg.paste(out, mask=ch[3] if len(ch) >= 4 else None)
            return bg
        if out.mode != "RGB":
            return out.convert("RGB")
        return out
    except Exception:
        return img.convert("RGB") if hasattr(img, "convert") else img


# ── Negative cache for dead image URLs ───────────────────────────────────────
# A URL that failed is not retried for _IMG_FAIL_TTL_S. Without this, every
# process start (and every cache clear) re-attempted the dozen-odd image URLs
# that no longer resolve, each against a 20 s timeout, up to twice per candidate
# URL (the SSL retry) — the largest remaining cost on a cold Catalogue render.
# One marker file per URL (the md5 of the URL), so concurrent fetch threads
# never contend on a shared file; an in-process dict spares the stat after the
# first check. Outside static/ on purpose: nothing here should be served.
_IMG_FAIL_DIR = _MATLIB_ROOT / ".cache" / "img_fetch_fail"
_IMG_FAIL_TTL_S = 24 * 3600
_IMG_FAIL_MEMO: dict[str, float] = {}


def _img_fail_key(url: str) -> str:
    return hashlib.md5(str(url).encode("utf-8")).hexdigest()


def _img_fetch_recently_failed(url: str) -> bool:
    key = _img_fail_key(url)
    ts = _IMG_FAIL_MEMO.get(key)
    if ts is None:
        try:
            ts = os.stat(_IMG_FAIL_DIR / key).st_mtime
        except OSError:
            ts = 0.0
        _IMG_FAIL_MEMO[key] = ts
    return bool(ts) and (time.time() - ts) < _IMG_FAIL_TTL_S


def _img_fetch_mark_failed(url: str) -> None:
    key = _img_fail_key(url)
    _IMG_FAIL_MEMO[key] = time.time()
    try:
        _IMG_FAIL_DIR.mkdir(parents=True, exist_ok=True)
        (_IMG_FAIL_DIR / key).write_text(str(url), encoding="utf-8")
    except OSError:
        pass


def _fetch_catalogue_image_from_url(url: str):
    """Download product image; downscale only if exceeds catalogue max dimensions.

    URLs that failed within the last 24 h are skipped without a request (see
    ``_IMG_FAIL_DIR``); delete that folder to force a retry.
    """
    raw = str(url or "").strip()
    if not raw or raw == "-":
        return None
    if _img_fetch_recently_failed(raw):
        return None
    mw, mh = _catalogue_image_max_dims()
    for fetch_url in product_image_fetch_candidates(raw):
        try:
            response = _requests_get_image_url(fetch_url)
            if response.status_code != 200:
                continue
            content = response.content or b""
            if not _bytes_look_like_image(content):
                continue
            image = _pil_open_safe(BytesIO(content))
            return _pil_downscale_if_needed(image, mw, mh)
        except Exception:
            continue
    _img_fetch_mark_failed(raw)
    return None


# ════════════════════════════════════════════════════════════════════════════
# DATA LOADING (fn103-fn114)
# ════════════════════════════════════════════════════════════════════════════

def fn103_load_from_sharepoint(
    tenant_id, client_id, client_secret,
    site_hostname, site_path, file_path,
    sheet_name=0, document_library=None
):
    """Download Excel from SharePoint via Graph API (MSAL auth)."""
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scope = ["https://graph.microsoft.com/.default"]
    app = ConfidentialClientApplication(
        client_id=client_id, authority=authority, client_credential=client_secret
    )
    token_result = app.acquire_token_for_client(scopes=scope)
    if "access_token" not in token_result:
        raise RuntimeError(f"Token acquisition failed: {token_result.get('error_description')}")
    token = token_result["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Every request is bounded: without a timeout a stalled Graph call hung the
    # script (and with it the whole app run) indefinitely.
    _api_to, _dl_to = (5, 30), (5, 120)
    site_resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/{site_hostname}:{site_path}", headers=headers, timeout=_api_to)
    site_resp.raise_for_status()
    site_id = site_resp.json()["id"]
    drives_resp = requests.get(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives", headers=headers, timeout=_api_to)
    drives_resp.raise_for_status()
    drives = drives_resp.json()["value"]
    if not drives:
        raise RuntimeError("No document libraries found on this site.")
    if document_library:
        drive = next((d for d in drives if d["name"].lower() == document_library.lower()), None)
        if not drive:
            raise ValueError(f"Document library '{document_library}' not found.")
    else:
        drive = drives[0]
    drive_id = drive["id"]
    metadata_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/{file_path}"
    metadata_resp = requests.get(metadata_url, headers=headers, timeout=_api_to)
    metadata_resp.raise_for_status()
    download_url = metadata_resp.json()["@microsoft.graph.downloadUrl"]
    file_resp = requests.get(download_url, timeout=_dl_to)
    file_resp.raise_for_status()
    return _read_excel_bytes(BytesIO(file_resp.content), sheet_name=sheet_name, header=0)


@st.cache_data(show_spinner="🔄 Loading from SharePoint...", ttl=3600)
def fn104_cached_load_excel(*args, **kwargs):
    """@cache_data wrapper for fn103_load_from_sharepoint."""
    return fn103_load_from_sharepoint(*args, **kwargs)


@st.cache_data(show_spinner=False)
def fn104a_cached_load_parquet(path: str, mtime_ns: int) -> pd.DataFrame:
    """@cache_data wrapper for pd.read_parquet, keyed on file mtime.

    ``mtime_ns`` is not used inside the function — it only exists so the
    cache key changes when the file on disk changes, avoiding a full
    re-read + re-hash of the DataFrame on every Streamlit rerun.
    """
    return pd.read_parquet(path)


@st.cache_data(ttl=3600, show_spinner="🔄 Loading data...")
def fn105_cached_load_motherduck_v1() -> pd.DataFrame:
    """Load MotherDuck table (deprecated — use fn106_cached_load_live_data)."""
    try:
        import duckdb
    except ImportError:
        raise ImportError("duckdb package required. Install with: pip install duckdb")
    try:
        cfg = st.secrets["motherduck"]
    except KeyError:
        raise RuntimeError("MotherDuck secrets not found in secrets.toml. Add [motherduck] section.")
    con = duckdb.connect(f"md:{cfg['db']}")
    con.execute("SET motherduck_token=?", [cfg["token"]])
    try:
        return con.table(cfg["table"]).df()
    finally:
        con.close()


@st.cache_data(ttl=3600, show_spinner="🔄 Loading live data...")
def fn106_cached_load_live_data() -> pd.DataFrame:
    """Load live_data from MotherDuck with improved token handling."""
    try:
        import duckdb
    except ImportError:
        raise ImportError("duckdb package required. Install with: pip install duckdb")
    try:
        cfg = st.secrets["motherduck"]
    except KeyError:
        raise RuntimeError("MotherDuck secrets not found in secrets.toml. Add [motherduck] section.")
    token = str(cfg["token"]).strip().strip('"').strip("'")
    os.environ["motherduck_token"] = token
    os.environ["MOTHERDUCK_TOKEN"] = token
    con = duckdb.connect("md:")
    try:
        con.execute(f"USE {cfg['db']}")
        return con.table(cfg["table"]).df()
    finally:
        con.close()


@st.cache_data(max_entries=4)
def fn109_cached_clean_dataframe(df, key_column=None):
    """@cache_data wrapper for fn122_clean_dataframe."""
    return fn122_clean_dataframe(df, key_column)


# Bounded: one entry per (url, profile, id, name) — the catalogue alone has ~560
# distinct images, and an unbounded cache of PIL images grows with every new one.
@st.cache_data(max_entries=1024)
def fn110_cached_fetch_image(
    url,
    profile: str = "default",
    *,
    eetra_id: Optional[str] = None,
    product_name: Optional[str] = None,
):
    """
    Fetch and cache image. Checks 01_data/img (hash + canonical names) →
    img_manifest.csv → static/img_cache → live fetch.

    profile:
      - "default": legacy 300×160 letterboxed thumbnail. No callers remain, and
        it is not disk-cached — see the note at the fetch-cache tier below.
      - "catalogue": up to CATALOGUE_IMAGE_FETCH_MAX_* px, downscale only.
    """
    if not url or url.strip() == "-" or url.strip() == "":
        return fn134_fetch_and_resize_image(url)

    is_cat = str(profile or "").strip().lower() == "catalogue"
    raw_url = url.strip()
    url_norm = normalize_product_image_url(raw_url)

    rid = _clean_row_field(eetra_id)
    rname = _clean_row_field(product_name)
    hash_local = resolve_hash_local_image_path(raw_url)
    if hash_local is not None:
        try:
            cached_img = _pil_open_safe(hash_local)
            if is_cat:
                mw, mh = _catalogue_image_max_dims()
                return _pil_downscale_if_needed(cached_img, mw, mh)
            return cached_img
        except Exception:
            pass
    if rid and rname:
        local_img = resolve_local_product_image_path(raw_url, rid, rname)
        if local_img is not None:
            try:
                cached_img = _pil_open_safe(local_img)
                if is_cat:
                    mw, mh = _catalogue_image_max_dims()
                    return _pil_downscale_if_needed(cached_img, mw, mh)
                size = (300, 160)
                target_width, target_height = size
                img_width, img_height = cached_img.size
                target_ratio = target_width / target_height
                img_ratio = img_width / img_height
                if img_ratio > target_ratio:
                    new_width = target_width
                    new_height = int(target_width / img_ratio)
                else:
                    new_height = target_height
                    new_width = int(target_height * img_ratio)
                resized = cached_img.resize((new_width, new_height), Image.LANCZOS)
                white_bg = Image.new("RGB", size, (255, 255, 255))
                paste_x = (target_width - new_width) // 2
                paste_y = (target_height - new_height) // 2
                if cached_img.mode == "RGBA":
                    white_bg.paste(resized, (paste_x, paste_y), resized)
                else:
                    white_bg.paste(resized, (paste_x, paste_y))
                return white_bg
            except Exception:
                pass

    manifest_path = Path("img_manifest.csv")
    if manifest_path.exists():
        try:
            manifest = pd.read_csv(manifest_path)
            url_to_local = dict(zip(manifest["source_url"], manifest["local_path"]))
            local_path = url_to_local.get(raw_url) or url_to_local.get(url_norm)
            if not local_path:
                for candidate in product_image_fetch_candidates(raw_url):
                    if candidate in url_to_local:
                        local_path = url_to_local[candidate]
                        break
            if local_path and Path(local_path).exists():
                try:
                    cached_img = _pil_open_safe(local_path)
                    if is_cat:
                        mw, mh = _catalogue_image_max_dims()
                        return _pil_downscale_if_needed(cached_img, mw, mh)
                    size = (300, 160)
                    target_width, target_height = size
                    img_width, img_height = cached_img.size
                    target_ratio = target_width / target_height
                    img_ratio = img_width / img_height
                    if img_ratio > target_ratio:
                        new_width = target_width
                        new_height = int(target_width / img_ratio)
                    else:
                        new_height = target_height
                        new_width = int(target_height * img_ratio)
                    resized = cached_img.resize((new_width, new_height), Image.LANCZOS)
                    white_bg = Image.new("RGB", size, (255, 255, 255))
                    paste_x = (target_width - new_width) // 2
                    paste_y = (target_height - new_height) // 2
                    if cached_img.mode == "RGBA":
                        white_bg.paste(resized, (paste_x, paste_y), resized)
                    else:
                        white_bg.paste(resized, (paste_x, paste_y))
                    return white_bg
                except Exception:
                    pass
        except Exception:
            pass

    # Fetch cache: static/img_cache, the same store the catalogue serves from.
    #
    # This tier used to be a third, separate cache under .cache/images, keyed on
    # md5(url) with a "__catalogue" filename variant — 958 files and 55 MB of
    # full-size PNGs holding the same images static/img_cache holds as 5 MB of
    # downscaled WebP, while 01_data/img held the pipeline's originals under a
    # third key scheme (sha256[:16]). Three caches, three key schemes, one set of
    # pictures. Pointing the fetch tier at the store that already exists leaves
    # two directories with clearly separate jobs: 01_data/img is the pipeline's
    # source of truth, static/img_cache is what the browser is served.
    #
    # Only the "catalogue" profile is disk-cached. Every caller passes it (see
    # _lazy_fetch_image, _warm_card_images, app.py's warm-up, and the Add/Edit
    # preview); the legacy 300x160 letterboxed profile has no callers left, and
    # caching it here would collide with the catalogue image under the same key.
    if is_cat:
        cached_static = static_img_cache_url(raw_url)
        if cached_static:
            cached_path = _STATIC_IMG_CACHE_DIR / Path(cached_static).name
            try:
                with Image.open(cached_path) as _probe:
                    _probe.load()
                    cached_img = _pil_open_safe_loaded(_probe)
                if catalogue_image_cache_is_valid(cached_img):
                    return cached_img
            except Exception:
                pass

        # Bucket before the manufacturer's own URL: it holds the same original
        # the pipeline downloaded, so it answers faster than a cold third-party
        # CDN and still answers once that CDN has reorganised its paths. No-op
        # while [doc_storage] enabled is false.
        image = fetch_remote_image_original(raw_url)
        if image is None:
            image = _fetch_catalogue_image_from_url(raw_url)
        if image is not None and catalogue_image_cache_is_valid(image):
            try:
                save_static_img_cache(raw_url, image)
            except Exception:
                pass
        return image

    return fn134_fetch_and_resize_image(raw_url)


def fn111_get_auth_users():
    """Load user credentials from st.secrets (with compatibility fallbacks)."""
    def _with_default_accounts(users_map):
        users_map = dict(users_map or {})
        # Keep demo login always available unless explicitly overridden in secrets.
        users_map.setdefault("demo", {"user": "demo", "pwd": "demo", "role": "user"})
        return users_map

    def _infer_role(default_key, explicit_user, explicit_role):
        if explicit_role:
            return explicit_role
        dk = str(default_key).strip().lower()
        eu = str(explicit_user or "").strip().lower()
        probe = f"{dk} {eu}"
        if "admin" in probe or dk == "admin" or eu == "admin":
            return "admin"
        # "dev" section + default user "dev" => probe "dev dev"; must treat as developer
        if "developer" in probe or dk in ("dev", "developer") or eu in ("dev", "developer"):
            return "developer"
        return "user"

    try:
        users = st.secrets["auth"]["users"]
        return _with_default_accounts({
            key: {
                "user": users[key].get("user"),
                "pwd": users[key].get("pwd"),
                "role": _infer_role(
                    str(key),
                    str(users[key].get("user", "")),
                    users[key].get("role"),
                ),
            }
            for key in users
        })
    except Exception:
        # Backward-compatible format: top-level sections like [dev] password="..."
        # (or pwd=..., optionally user=..., role=...).
        try:
            parsed = {}
            for key, value in st.secrets.items():
                if not isinstance(value, dict):
                    continue
                pwd = value.get("pwd") or value.get("password")
                if not pwd:
                    continue
                _user = value.get("user") or str(key)
                parsed[str(key)] = {
                    "user": _user,
                    "pwd": pwd,
                    "role": _infer_role(str(key), str(_user), value.get("role")),
                }
            if parsed:
                return _with_default_accounts(parsed)
        except Exception:
            pass
        return {
            "demo": {"user": "demo", "pwd": "demo", "role": "user"},
            "eetra": {"user": "eetra", "pwd": "F4rz1", "role": "admin"},
        }


def fn112_default_admin_credentials() -> tuple[str, str] | tuple[None, None]:
    """Return (username, password) for the built-in admin account from secrets / fallbacks."""
    try:
        users = fn111_get_auth_users()
    except Exception:
        return None, None
    entry = users.get("admin")
    if isinstance(entry, dict) and entry.get("pwd"):
        return str(entry.get("user") or "admin").strip(), str(entry["pwd"])
    for v in users.values():
        if not isinstance(v, dict):
            continue
        if str(v.get("role", "")).strip().lower() == "admin" and v.get("pwd"):
            return str(v.get("user") or "").strip(), str(v["pwd"])
    return None, None


def fn112_try_default_admin_login() -> bool:
    """Sign in as admin (used on app startup). Demo remains available via the login form."""
    user, pwd = fn112_default_admin_credentials()
    if not user or not pwd:
        return False
    return fn112_try_login(user, pwd)


def fn112_try_login(username: str, password: str) -> bool:
    """Validate credentials and set ``auth_user`` / ``auth_role``. Returns True on success."""
    if not username or not str(username).strip():
        return False
    users = fn111_get_auth_users()
    found = None
    for k, v in users.items():
        if str(username).strip().lower() in {k.lower(), str(v.get("user", "")).lower()}:
            found = v
            break
    if found and password == found.get("pwd"):
        st.session_state["auth_user"] = found.get("user") or str(username).strip()
        st.session_state["auth_role"] = found.get("role", "user")
        return True
    return False


def fn112_sync_auth_session_with_secrets() -> None:
    """Align ``auth_user`` / ``auth_role`` with ``fn111_get_auth_users()`` for the current session.

    Fixes stale ``auth_role`` (e.g. still ``user`` after signing in as ``dev``) when secrets or
    role inference change without re-login.
    """
    if "auth_user" not in st.session_state:
        return
    if st.session_state.get("auth_method") == "m365":
        # Gli account Microsoft prendono il ruolo da [m365] (lib_auth_m365 fn806),
        # non dalla tabella [auth.users]: lasciare la sessione com'è.
        return
    username = str(st.session_state.get("auth_user", "")).strip()
    if not username:
        return
    try:
        users = fn111_get_auth_users()
    except Exception:
        return
    found = None
    for k, v in users.items():
        if username.lower() in {k.lower(), str(v.get("user", "")).lower()}:
            found = v
            break
    if not found:
        return
    st.session_state["auth_user"] = found.get("user") or username
    st.session_state["auth_role"] = found.get("role", "user")


def fn112_render_login():
    """Streamlit login form + auth flow in sidebar."""
    with st.sidebar:
        st.markdown("#### 🔐 Login")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pwd")
        col_a, col_b = st.columns([1, 1])
        login_clicked = col_a.button("Login")
        if login_clicked:
            if fn112_try_login(username, password):
                st.success("Logged in")
                st.rerun()
            else:
                st.error("Invalid credentials")


# NOTE: st.html runs CSS through DOMPurify. A rejected rule can empty the whole
# <style> block — keep this sheet free of content:/expression/@import quirks, and
# inject password-eye icon CSS separately (or skip it).
_AUTH_GATE_HIDE_CHROME_CSS = """
[data-testid="stSidebar"],
[data-testid="stSidebarContent"],
[data-testid="stSidebarNav"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    pointer-events: none !important;
}
header[data-testid="stHeader"] { display: none !important; }
div[data-testid="stToolbar"] { display: none !important; }
footer[data-testid="stFooter"] { display: none !important; }
div[data-testid="stDecoration"] { display: none !important; }
[data-testid="stAppViewContainer"] { background: #f6f8f5 !important; }
[data-testid="stMain"] {
    position: relative !important;
    overflow: hidden !important;
    background: #f6f8f5 !important;
    min-height: 100vh !important;
}
[data-testid="stMain"] .block-container,
[data-testid="stMain"] [data-testid="stMainBlockContainer"] {
    position: relative !important;
    z-index: 1 !important;
    padding-top: 0 !important;
    padding-bottom: 1.5rem !important;
    max-width: 30rem !important;
    margin-left: auto !important;
    margin-right: auto !important;
    background: transparent !important;
}
div.st-key-login_card {
    background: #ffffff !important;
    border: 1px solid #eef1ee !important;
    border-radius: 16px !important;
    box-shadow: 0 2px 10px rgba(30,41,59,0.04), 0 12px 32px rgba(30,41,59,0.08) !important;
    padding: 1.5rem 2rem 1.35rem 2rem !important;
}
div.st-key-login_card div[data-testid="stVerticalBlock"] { gap: 0.45rem !important; }
div.st-key-login_card div[data-testid="stTextInput"] label p {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: #334155 !important;
    margin-bottom: 0.15rem !important;
}
div.st-key-login_card div[data-testid="stTextInput"] input {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 8px !important;
    min-height: 2.45rem !important;
    font-size: 0.95rem !important;
}
div.st-key-login_card div[data-testid="stTextInput"] input:focus {
    border-color: #2a7d2e !important;
    box-shadow: 0 0 0 3px rgba(42,125,46,0.12) !important;
}
div.st-key-login_card div[data-testid="stButton"] { margin-top: 0.25rem !important; }
div.st-key-login_card div[data-testid="stButton"] > button {
    min-height: 2.45rem !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    color: #ffffff !important;
    background: linear-gradient(135deg, #2a7d2e 0%, #256b29 100%) !important;
    border: none !important;
    border-radius: 8px !important;
    white-space: nowrap !important;
    box-shadow: 0 4px 14px rgba(42,125,46,0.28) !important;
}
div.st-key-login_card div[data-testid="stButton"] > button:hover {
    filter: brightness(1.06) !important;
}
div.st-key-welcome_login_pwd button p,
div.st-key-welcome_login_pwd button span {
    font-size: 0 !important;
    color: transparent !important;
}
.login-gate-or {
    text-align: center;
    color: #94a3b8;
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border-top: 1px solid #eef1ee;
    margin: 0.85rem 0 0.1rem 0;
    padding-top: 0.6rem;
}
a.login-gate-m365 {
    min-height: 2.45rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
    font-weight: 600;
    color: #334155;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(30,41,59,0.06);
    text-decoration: none;
}
a.login-gate-m365:hover {
    border-color: #2a7d2e;
    color: #2a7d2e;
}
"""


def _auth_gate_background_css(image_url: str) -> str:
    """Full-bleed library-wall photo behind the sign-in card (opacity from theme.json).

    Uses ``[data-testid=stMain]::after`` (tagless for Streamlit 1.66+ ``<main>``).
    ``::after`` avoids fighting Streamlit's focus-ring ``::before``.
    """
    from libs.lib_tokens import theme_section

    ag = theme_section("chrome", "auth_gate") or {}
    try:
        opacity = float(ag.get("background_image_opacity", 0.55))
    except (TypeError, ValueError):
        opacity = 0.55
    opacity = max(0.0, min(1.0, opacity))
    return (
        "[data-testid=\"stMain\"]::after { "
        "content: ''; position: fixed; inset: 0; "
        f"background-image: url('{image_url}'); "
        "background-size: cover; background-position: center; background-repeat: no-repeat; "
        f"opacity: {opacity}; z-index: 0; pointer-events: none; "
        "}"
    )


def _auth_gate_background_image_url() -> str:
    """Prefer statically served JPEG; fall back to a compact data-URI."""
    from libs.lib_tokens import theme_section

    static_jpg = _MATLIB_ROOT / "static" / "login" / "MatLib__login_bground.jpg"
    if static_jpg.is_file():
        # enableStaticServing → /app/static/... (see .streamlit/config.toml)
        return "/app/static/login/MatLib__login_bground.jpg"

    ag = theme_section("chrome", "auth_gate") or {}
    bg_rel = ag.get("background_image_path", "03_img/MatLib__login_bground.png")
    bg = _pil_open_safe(str(_MATLIB_ROOT / str(bg_rel).replace("\\", "/")))
    buf = BytesIO()
    bg.convert("RGB").save(buf, format="JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def fn112a_render_auth_gate_screen() -> None:
    """Startup login mask: hide chrome + centred sign-in card (defaults admin). Then ``st.stop()``."""
    import html as _html

    from libs.lib_auth_m365 import fn804_m365_handle_redirect, fn808_m365_render_login_button
    from libs.lib_header import brand
    from libs.lib_tokens import auth_gate_typography_css, font_links_html

    # Microsoft torna sulla root dell'app con ?code=&state=: completare il flow
    # prima di disegnare qualsiasi widget, così un successo fa rerun dentro l'app.
    if fn804_m365_handle_redirect():
        st.rerun()

    # Collapse the auto pages/ sidebar before any widgets paint (additive in 1.66+).
    try:
        st.set_page_config(
            page_title=brand("browser_tab_title", brand("app_name", "EETRA Material Library")),
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except Exception:
        pass

    st.markdown(font_links_html(), unsafe_allow_html=True)
    _bg_css = ""
    try:
        _bg_css = _auth_gate_background_css(_auth_gate_background_image_url())
    except Exception:
        _bg_css = ""
    # Single st.html style sheet (DOMPurify can empty a whole <style> if one rule
    # is rejected — keep hide+card CSS free of content: icon hacks).
    st.html(
        f"<style>{_AUTH_GATE_HIDE_CHROME_CSS}{_bg_css}{auth_gate_typography_css()}</style>"
    )
    # Belt-and-suspenders: force-hide the auto pages/ sidebar if CSS loses a race.
    st.html(
        "<script>(function(){"
        "var sel='[data-testid=stSidebar],[data-testid=stSidebarNav],"
        "[data-testid=stSidebarCollapsedControl],[data-testid=collapsedControl],"
        "[data-testid=stExpandSidebarButton]';"
        "function hide(){document.querySelectorAll(sel).forEach(function(el){"
        "el.style.setProperty('display','none','important');"
        "el.style.setProperty('visibility','hidden','important');"
        "el.style.setProperty('width','0','important');}});"
        "hide();"
        "new MutationObserver(hide).observe(document.body,{childList:true,subtree:true});"
        "})();</script>",
        unsafe_allow_javascript=True,
    )
    _def_user, _def_pwd = fn112_default_admin_credentials()
    st.session_state.setdefault("welcome_login_user", _def_user or "admin")
    st.session_state.setdefault("welcome_login_pwd", _def_pwd or "")

    from libs.lib_tokens import theme_section

    _ag = theme_section("chrome", "auth_gate") or {}
    # Prefer small text wordmark (classic splash); optional logo via show_logo=true.
    _wordmark = str(_ag.get("wordmark") or "EETRA").strip() or "EETRA"
    _brand_mark_html = ""
    if _ag.get("show_logo"):
        try:
            _logo_rel = _ag.get("logo_path", "03_img/EETRA_logo_rect.png")
            _logo = _pil_open_safe(str(_MATLIB_ROOT / str(_logo_rel).replace("\\", "/")))
            _buf = BytesIO()
            _logo.save(_buf, format="PNG")
            _logo_b64 = base64.b64encode(_buf.getvalue()).decode()
            _brand_mark_html = (
                f'<img class="login-gate-logo" src="data:image/png;base64,{_logo_b64}" '
                f'alt="{_html.escape(_wordmark)}" />'
            )
        except Exception:
            _brand_mark_html = ""
    if not _brand_mark_html:
        _brand_mark_html = f'<p class="login-gate-wordmark">{_html.escape(_wordmark)}</p>'
    st.markdown(
        "<div class='login-gate-brand'>"
        f"{_brand_mark_html}"
        f"<h2 class='login-gate-title'>{_html.escape(brand('masthead_title', 'Material Library'))}</h2>"
        f"<p class='login-gate-tagline'>{_html.escape(brand('tagline', 'Low-carbon, circular materials for a regenerative future.'))}</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.container(key="login_card", border=True):
        st.text_input("Username", key="welcome_login_user")
        st.text_input("Password", type="password", key="welcome_login_pwd")
        _login_failed = False
        if st.button("Log in", width='stretch', key="welcome_sign_in"):
            if fn112_try_login(
                st.session_state.get("welcome_login_user", ""),
                st.session_state.get("welcome_login_pwd", ""),
            ):
                st.rerun()
            else:
                _login_failed = True
        if _login_failed:
            st.error("Invalid username or password.")
        fn808_m365_render_login_button()
        st.markdown(
            "<p class='login-gate-demo'>"
            "Demo account: username <b>demo</b>, password <b>demo</b></p>",
            unsafe_allow_html=True,
        )


def fn113_get_base_product_name(product_name) -> str:
    """Return base product name by stripping suffix after ' | '."""
    if product_name is None or (isinstance(product_name, float) and np.isnan(product_name)):
        return ""
    text = str(product_name).strip()
    if not text:
        return ""
    parts = text.split(" | ")
    base = parts[0].strip() if parts else text
    return base or text


def fn114_add_base_product_column(
    df: pd.DataFrame,
    product_col: str = 'A__ProductName',
    new_col: str = 'A__ProductName_Base',
) -> pd.DataFrame:
    """Add A__ProductName_Base column (base name before ' | ')."""
    if new_col in df.columns:
        return df
    if product_col not in df.columns:
        return df
    df2 = df.copy()
    s = df2[product_col].astype(str)
    df2[new_col] = s.str.split(" | ", n=1).str[0].str.strip()
    return df2


def fn134_fetch_and_resize_image(url, size=(300, 160)):
    """Download image from URL and letterbox to size. Returns placeholder on failure."""
    placeholder = Image.new("RGB", size, color=(220, 220, 220))
    draw = ImageDraw.Draw(placeholder)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    text = "Picture Not Available"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except AttributeError:
        text_width, text_height = font.getsize(text)
    text_position = ((size[0] - text_width) / 2, (size[1] - text_height) / 2)
    draw.text(text_position, text, fill=(100, 100, 100), font=font)
    if not url or url.strip() == "-" or url.strip() == "":
        return placeholder
    fetch_url = normalize_product_image_url(url.strip())
    try:
        response = _requests_get_image_url(fetch_url)
        if response.status_code == 200 and _bytes_look_like_image(response.content or b""):
            image = _pil_open_safe(BytesIO(response.content))
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            target_width, target_height = size
            img_width, img_height = image.size
            target_ratio = target_width / target_height
            img_ratio = img_width / img_height
            if img_ratio > target_ratio:
                new_width = target_width
                new_height = int(target_width / img_ratio)
            else:
                new_height = target_height
                new_width = int(target_height * img_ratio)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            white_bg = Image.new("RGB", size, (255, 255, 255))
            paste_x = (target_width - new_width) // 2
            paste_y = (target_height - new_height) // 2
            white_bg.paste(image, (paste_x, paste_y), image)
            return white_bg
        else:
            return placeholder
    except Exception:
        return placeholder


def fn133_extract_table_with_llm(file_content, api_key=None):
    """Extract tabular data from text using OpenAI LLM."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package is required for fn133_extract_table_with_llm") from exc
    resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_api_key:
        try:
            resolved_api_key = st.secrets["openai"]["api_key"]
        except Exception:
            resolved_api_key = None
    if not resolved_api_key:
        raise ValueError("OpenAI API key not provided.")
    client = OpenAI(api_key=resolved_api_key)
    prompt = f"The following content contains LCA data. Extract the table into a structured JSON format:\n{file_content}"
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        extracted_data = response.choices[0].message.content
        try:
            extracted_data_json = json.loads(extracted_data)
        except json.JSONDecodeError:
            extracted_data_json = eval(extracted_data)
    except Exception as e:
        st.error(f"Failed to parse LLM output: {e}")
        return None
    return pd.DataFrame(extracted_data_json)


# ════════════════════════════════════════════════════════════════════════════
# GEOCODING (fn115-fn120)
# ════════════════════════════════════════════════════════════════════════════

def fn115_geocode_location(place: str, country=None):
    """Resolve place to coordinates using precomputed GEOCODE_CACHE only. No live geocoding."""
    try:
        if not place or str(place).strip() == "" or str(place).strip() == "-":
            return None
        place_s = str(place).strip()
        country_s = (str(country).strip() if country else "")
        key = f"{place_s}|{country_s}"
        cache = st.session_state.get("GEOCODE_CACHE", {})
        if isinstance(cache, dict) and key in cache:
            entry = cache[key]
            lat = float(entry.get("lat"))
            lon = float(entry.get("lon"))
            return lat, lon
    except Exception as e:
        print(f"Geocoding cache lookup failed for '{place}' ({country}): {e}")
    return None


def fn116_geocode_with_alternatives(place: str, country=None):
    """Try multiple geocoding strategies to find coordinates. Returns (lat, lon) or None."""
    if not place or str(place).strip() == "" or str(place).strip() == "-":
        return None
    place_s = str(place).strip()
    country_s = (str(country).strip() if country else "").strip()
    if ";" in place_s:
        locations = [loc.strip() for loc in place_s.split(";") if loc.strip()]
        for location in locations:
            coords = _try_single_location_geocoding(location, country_s)
            if coords:
                return coords
        return None
    return _try_single_location_geocoding(place_s, country_s)


def _try_single_location_geocoding(place_s: str, country_s: str):
    has_country = bool(country_s and country_s != "-")
    if has_country:
        coords = _try_geocode_nominatim(f"{place_s}, {country_s}")
        if coords:
            return coords
    coords = _try_geocode_nominatim(place_s)
    if coords:
        return coords
    if "," in place_s:
        first_part = place_s.split(",")[0].strip()
        if first_part and first_part != place_s:
            if has_country:
                coords = _try_geocode_nominatim(f"{first_part}, {country_s}")
                if coords:
                    return coords
            coords = _try_geocode_nominatim(first_part)
            if coords:
                return coords
    cleaned = re.sub(
        r'\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Place|Pl)\s*$',
        '', place_s, flags=re.IGNORECASE,
    )
    if cleaned != place_s:
        if has_country:
            coords = _try_geocode_nominatim(f"{cleaned}, {country_s}")
            if coords:
                return coords
        coords = _try_geocode_nominatim(cleaned)
        if coords:
            return coords
    return None


def _try_geocode_nominatim(query: str):
    try:
        if not query or query.strip() == "":
            return None
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "EETRA-MatLib/1.0 (contact: info@eetra.it)"}
        params = {"q": query, "format": "json", "limit": 1}
        time.sleep(1.1)
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            lat = float(data[0].get("lat"))
            lon = float(data[0].get("lon"))
            return lat, lon
    except Exception:
        pass
    return None


def fn117_preload_all_locations(
    df: pd.DataFrame,
    plant_col: str = 'E__ManuPlant',
    country_col: str = 'E__ManuCountry',
) -> None:
    """Bulk-geocode all unique plant locations; initialize GEOCODE_CACHE."""
    try:
        if df is None or df.empty:
            return
        if plant_col not in df.columns:
            return
        if country_col not in df.columns:
            df = df.copy()
            df[country_col] = ""
        unique_pairs = (
            df[[plant_col, country_col]]
            .dropna(subset=[plant_col])
            .drop_duplicates()
            .values.tolist()
        )
        if "GEOCODE_CACHE" not in st.session_state:
            st.session_state["GEOCODE_CACHE"] = {}
        cache = st.session_state["GEOCODE_CACHE"]
        pairs_list = []
        seen_keys = set()
        for plant, country in unique_pairs:
            plant_s = ("" if pd.isna(plant) else str(plant)).strip()
            country_s = ("" if pd.isna(country) else str(country)).strip()
            key = f"{plant_s}|{country_s}"
            if key not in seen_keys and plant_s:
                pairs_list.append((plant_s, country_s, key))
                seen_keys.add(key)
        pairs_list.sort(key=lambda x: (x[0].lower(), x[1].lower()))
        missing_locations = [(p, c, k) for p, c, k in pairs_list if k not in cache]
        total = len(pairs_list)
        missing_count = len(missing_locations)
        if missing_count > 0:
            print(f"Pre-loading geolocations: {total} total, {missing_count} missing.")
            geocoded_count = 0
            for idx, (plant_s, country_s, key) in enumerate(missing_locations, 1):
                coords = fn116_geocode_with_alternatives(plant_s, country_s if country_s else None)
                if coords:
                    lat, lon = coords
                    cache[key] = {"lat": lat, "lon": lon}
                    st.session_state["GEOCODE_CACHE"] = cache
                    geocoded_count += 1
            print(f"✓ Geocoded {geocoded_count}/{missing_count} missing locations.")
        else:
            print(f"✓ All {total} locations already present in cache.")
    except Exception as e:
        print(f"Error pre-loading locations: {e}")


def fn118_get_locations_for_base_product(
    df: pd.DataFrame,
    base_product_name: str,
    product_col: str = 'A__ProductName',
    plant_col: str = 'E__ManuPlant',
    country_col: str = 'E__ManuCountry',
) -> pd.DataFrame:
    """Return DataFrame of unique plant locations (lat/lon) for a base product."""
    required = [product_col, plant_col]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame(columns=['lat', 'lon', 'Plant', 'Country', 'Manufacturer', 'Product'])
    dfb = fn114_add_base_product_column(df, product_col=product_col)
    mask = dfb.get('A__ProductName_Base', "")
    dfb = dfb[mask == base_product_name]
    if country_col not in dfb.columns:
        dfb[country_col] = ""
    pairs = (
        dfb[[plant_col, country_col, 'A__Manufacturer', product_col]]
        .dropna(subset=[plant_col])
        .drop_duplicates()
    )
    rows = []
    for _, r in pairs.iterrows():
        plant = r.get(plant_col, "")
        country = r.get(country_col, "")
        manu = r.get('A__Manufacturer', "")
        prod = r.get(product_col, "")
        coords = fn115_geocode_location(plant, country)
        if coords:
            lat, lon = coords
            rows.append({"lat": lat, "lon": lon, "Plant": plant, "Country": country, "Manufacturer": manu, "Product": prod})
    return pd.DataFrame(rows)


def fn119_get_all_products_for_plant(
    df: pd.DataFrame,
    selected_plant: str,
    selected_country: str = "",
    product_col: str = 'A__ProductName',
    plant_col: str = 'E__ManuPlant',
    country_col: str = 'E__ManuCountry',
) -> pd.DataFrame:
    """Return DataFrame of all products at a given plant."""
    required = [product_col, plant_col]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame(columns=['lat', 'lon', 'Plant', 'Country', 'Manufacturer', 'Product', 'Product_Base'])
    df_filtered = df.copy()
    if country_col not in df_filtered.columns:
        df_filtered[country_col] = ""
    plant_mask = df_filtered[plant_col].astype(str).str.strip() == str(selected_plant).strip()
    if selected_country:
        country_mask = df_filtered[country_col].astype(str).str.strip() == str(selected_country).strip()
        mask = plant_mask & country_mask
    else:
        mask = plant_mask
    df_plant = df_filtered[mask].copy()
    if df_plant.empty:
        return pd.DataFrame(columns=['lat', 'lon', 'Plant', 'Country', 'Manufacturer', 'Product', 'Product_Base'])
    df_plant = fn114_add_base_product_column(df_plant, product_col=product_col)
    unique_products = (
        df_plant[[plant_col, country_col, 'A__Manufacturer', product_col, 'A__ProductName_Base']]
        .dropna(subset=[product_col])
        .drop_duplicates()
    )
    rows = []
    plant_str = str(selected_plant).strip()
    country_str = str(selected_country).strip() if selected_country else ""
    coords = fn115_geocode_location(plant_str, country_str if country_str else None)
    if coords:
        lat, lon = coords
        for _, r in unique_products.iterrows():
            rows.append({
                "lat": lat, "lon": lon,
                "Plant": r.get(plant_col, ""),
                "Country": r.get(country_col, ""),
                "Manufacturer": r.get('A__Manufacturer', ""),
                "Product": r.get(product_col, ""),
                "Product_Base": r.get('A__ProductName_Base', ""),
            })
    return pd.DataFrame(rows)


def fn120_aggregate_value_by_base_product(
    df: pd.DataFrame,
    value_col: str,
    product_col: str = 'A__ProductName',
    carry_cols=None,
) -> pd.DataFrame:
    """Mean-aggregate value_col by base product name; carry first values of carry_cols."""
    if product_col not in df.columns or value_col not in df.columns:
        return df
    work = fn114_add_base_product_column(df, product_col=product_col)
    group_keys = ['A__ProductName_Base']
    agg_dict: dict = {value_col: 'mean'}
    carry_cols = carry_cols or []
    valid_carry = [c for c in carry_cols if c in work.columns]
    for c in valid_carry:
        agg_dict[c] = 'first'
    grouped = work.groupby(group_keys, as_index=False).agg(agg_dict)
    grouped[product_col] = grouped['A__ProductName_Base']
    ordered_cols = [product_col] + [c for c in grouped.columns if c not in [product_col, 'A__ProductName_Base']]
    grouped = grouped[ordered_cols]
    return grouped


# ════════════════════════════════════════════════════════════════════════════
# Manufacturer sustainability (aux_companies_sust_credentials.json)
# ════════════════════════════════════════════════════════════════════════════

_SUST_CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "aux_companies_sust_credentials.json"


def _file_mtime_ns(path: Path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


# Keyed on the file's mtime so an edit made outside the app (or by another
# process) is picked up; previously the cache had no key at all and only the
# in-app save path's .clear() ever refreshed it. Still cache_data (a copy per
# call), not cache_resource: the bundle is small and has many callers, and a
# shared mutable dict is not worth the risk.
@st.cache_data(max_entries=2)
def _fn135_cached(mtime_ns: int) -> dict:
    with open(_SUST_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fn135_sustainability_credentials() -> dict:
    """Load manufacturer sustainability bundle from JSON (sectors, credentials, profiles, …)."""
    return _fn135_cached(_file_mtime_ns(_SUST_CREDENTIALS_PATH))


fn135_sustainability_credentials.clear = _fn135_cached.clear  # type: ignore[attr-defined]


def fn136_sustainability_sector_list() -> list:
    """Return list of sector names."""
    return list(fn135_sustainability_credentials()["sectors"].keys())


def fn137_get_credentials_matrix(
    manufacturers: list | None = None, sector: str | None = None,
) -> pd.DataFrame:
    """
    Return a filtered credentials DataFrame (manufacturers as index).

    Args:
        manufacturers: include only these names; ignored if ``sector`` is set
        sector: filter by sector (overrides ``manufacturers``)
    """
    _data = fn135_sustainability_credentials()
    SECTORS = _data["sectors"]
    CREDENTIAL_LABELS = _data["credential_labels"]
    CREDENTIALS = _data["credentials"]
    if sector is not None and sector in SECTORS:
        manufacturers = SECTORS[sector]
    elif manufacturers is None:
        manufacturers = list(CREDENTIALS.keys())
    rows = []
    for mfr in manufacturers:
        if mfr in CREDENTIALS:
            row = {"Manufacturer": mfr}
            row.update(CREDENTIALS[mfr])
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("Manufacturer")
    return df.rename(columns=CREDENTIAL_LABELS)


def fn138_get_maturity_ranking() -> pd.DataFrame:
    """All manufacturers sorted by maturity tier (Advanced → Minimal)."""
    _data = fn135_sustainability_credentials()
    SECTORS = _data["sectors"]
    CREDENTIALS = _data["credentials"]
    tier_order = ["Advanced", "Good", "Progressing", "Developing", "Early Stage", "Minimal"]
    mfr_to_sector: dict[str, str] = {}
    for sec, mfrs in SECTORS.items():
        for mfr in mfrs:
            mfr_to_sector[mfr] = sec
    rows = []
    for mfr, creds in CREDENTIALS.items():
        rows.append({
            "Manufacturer": mfr,
            "Sector": mfr_to_sector.get(mfr, "Unknown"),
            "Maturity Tier": creds["maturity"],
            "SBTi Status": creds["sbti"],
            "CDP Rating": creds["cdp"],
            "ISO 14001": creds["iso14001"],
            "Sustainability Report": creds["sustainability_report"],
        })
    df = pd.DataFrame(rows)
    df["tier_rank"] = df["Maturity Tier"].map({t: i for i, t in enumerate(tier_order)})
    df = df.sort_values(["tier_rank", "Sector", "Manufacturer"]).drop(columns=["tier_rank"])
    return df.reset_index(drop=True)


def fn139_get_company_profile_df() -> pd.DataFrame:
    """One row per manufacturer that has a narrative profile block."""
    _data = fn135_sustainability_credentials()
    COMPANY_PROFILES = _data["company_profiles"]
    CREDENTIALS = _data["credentials"]
    rows = []
    for mfr, profile in COMPANY_PROFILES.items():
        row = {"Manufacturer": mfr}
        row.update({k: v for k, v in profile.items() if k not in ("lat", "lon", "report", "report_url")})
        if mfr in CREDENTIALS:
            row["Maturity"] = CREDENTIALS[mfr]["maturity"]
        rows.append(row)
    return pd.DataFrame(rows)


def fn140_get_sustainability_maturity_counts() -> dict:
    """Count of manufacturers per maturity tier."""
    counts: dict[str, int] = {}
    for creds in fn135_sustainability_credentials()["credentials"].values():
        tier = creds["maturity"]
        counts[tier] = counts.get(tier, 0) + 1
    return counts


# ════════════════════════════════════════════════════════════════════════════
# Impact Framework manufacturers (aux_companies_impact_framework.json)
# Compact summaries for the catalogue detail panel → Manufacturer's Sustainability
# ════════════════════════════════════════════════════════════════════════════

_IMPACT_FRAMEWORK_PATH = Path(__file__).resolve().parent.parent / "aux_companies_impact_framework.json"

_SBTI_LABELS = {0: "No SBTi", 1: "SBTi Committed", 2: "SBTi Near-Term", 3: "SBTi Net-Zero"}
_SBTI_SHORT = {0: "None", 1: "Committed", 2: "Near-Term", 3: "Net-Zero"}


@st.cache_data(show_spinner=False, max_entries=2)
def _fn140a_cached(mtime_ns: int) -> dict:
    with open(_IMPACT_FRAMEWORK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fn140a_load_impact_framework() -> dict:
    """Load the Impact Framework JSON (entities, matrix, maturity tiers).

    Keyed on the file's mtime (see fn135 for why it stays cache_data).
    """
    return _fn140a_cached(_file_mtime_ns(_IMPACT_FRAMEWORK_PATH))


fn140a_load_impact_framework.clear = _fn140a_cached.clear  # type: ignore[attr-defined]


def _ifw_norm_mfr(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    for tok in (
        " group", " spa", " srl", " ltd", " europe", " materials",
        " italy", " italia", " ceramiche", " ceramica",
    ):
        s = s.replace(tok, " ")
    return re.sub(r"\s+", " ", s).strip()


def _ifw_score_manufacturer(e: dict, weights: dict | None = None) -> dict:
    """Mirror pages/8_ImpactFramework.py manufacturer scoring (A–D axes)."""
    A = e.get("A_climate_commitments", {}) or {}
    B = e.get("B_reporting_transparency", {}) or {}
    C = e.get("C_product_credentials", {}) or {}
    D = e.get("D_supply_chain", {}) or {}

    def _bool_s(v) -> float:
        if v is True:
            return 100.0
        if v is False or v is None:
            return 0.0
        return 100.0 if str(v).lower() not in ("false", "none", "0", "") else 0.0

    sbti_map = {0: 0, 1: 25, 2: 75, 3: 100}
    try:
        sbti_s = sbti_map.get(int(A.get("sbti_status", 0) or 0), 0)
    except (TypeError, ValueError):
        sbti_s = 0
    cdp_s = {"A": 100, "A-": 90, "B+": 75, "B": 60, "B-": 45, "C": 30, "D": 10}.get(
        str(A.get("cdp_rating", "")), 0
    )
    scope3_s = {"full": 100, "partial": 50, "none": 0}.get(
        str(A.get("ghg_scope3_disclosed", "none")), 0
    )
    axis_a = (sbti_s + cdp_s + scope3_s) / 3

    try:
        sr_s = (int(B.get("sustainability_report", 0) or 0) / 4) * 100
    except (TypeError, ValueError):
        sr_s = 0.0
    try:
        csrd_s = (int(B.get("csrd_esrs_status", 0) or 0) / 4) * 100
    except (TypeError, ValueError):
        csrd_s = 0.0
    axis_b = (sr_s + csrd_s + _bool_s(B.get("iso14001"))) / 3

    epd_raw = C.get("epd_count_active")
    if epd_raw is None:
        epd_s = 0.0
    elif str(epd_raw).lower() == "multiple":
        epd_s = 80.0
    else:
        try:
            n = int(epd_raw)
            epd_s = 100.0 if n > 10 else (60.0 if n > 0 else 0.0)
        except (TypeError, ValueError):
            epd_s = 0.0
    cam_raw = C.get("cam_portfolio_coverage_pct")
    try:
        cam_s = 0.0 if cam_raw is None else float(cam_raw)
    except (TypeError, ValueError):
        cam_s = 0.0
    # B Corp may sit under B or C depending on entity vintage
    bcorp = B.get("bcorp_certified")
    if bcorp is None:
        bcorp = C.get("bcorp_certified")
    axis_c = (epd_s + cam_s + _bool_s(bcorp)) / 3

    axis_d = (
        _bool_s(D.get("supplier_code_of_conduct"))
        + _bool_s(D.get("supplier_ecovadis_required"))
        + _bool_s(D.get("raw_material_origin_disclosed"))
    ) / 3

    w = weights or {
        "climate_commitments": 0.30,
        "reporting_transparency": 0.25,
        "product_credentials": 0.25,
        "supply_chain": 0.20,
    }
    total = (
        axis_a * float(w.get("climate_commitments", 0.30))
        + axis_b * float(w.get("reporting_transparency", 0.25))
        + axis_c * float(w.get("product_credentials", 0.25))
        + axis_d * float(w.get("supply_chain", 0.20))
    )
    return {"A": axis_a, "B": axis_b, "C": axis_c, "D": axis_d, "total": round(total, 1)}


@st.cache_data(show_spinner=False, max_entries=2)
def _ifw_manufacturer_lookup_cached(mtime_ns: int) -> dict[str, tuple[str, dict]]:
    """``{normalized_name: (canonical_name, entity)}`` for IFW manufacturers."""
    data = fn140a_load_impact_framework()
    out: dict[str, tuple[str, dict]] = {}
    for name, ent in (data.get("entities") or {}).get("manufacturers", {}).items():
        key = _ifw_norm_mfr(name)
        if key:
            out[key] = (name, ent)
    return out


def _ifw_manufacturer_lookup() -> dict[str, tuple[str, dict]]:
    """Same mtime key as fn140a, so the lookup follows external edits too."""
    return _ifw_manufacturer_lookup_cached(_file_mtime_ns(_IMPACT_FRAMEWORK_PATH))


_ifw_manufacturer_lookup.clear = _ifw_manufacturer_lookup_cached.clear  # type: ignore[attr-defined]


def _ifw_resolve_manufacturer(name: str) -> tuple[str, dict] | None:
    raw = str(name or "").strip()
    if not raw or raw.lower() in ("nan", "none", "-", "n/a"):
        return None
    lookup = _ifw_manufacturer_lookup()
    key = _ifw_norm_mfr(raw)
    if key in lookup:
        return lookup[key]
    # Substring match (e.g. "Florim Ceramiche S.p.A. SB" → Florim)
    if key:
        for k, pair in lookup.items():
            if k and (key in k or k in key):
                return pair
    return None


def fn140b_manufacturer_impact_summary(manufacturer: str) -> dict | None:
    """Catalogue-facing Impact Framework card for a manufacturer, or ``None``.

    Shape matches what ``catalogue_component_js2.html`` renders under
    Manufacturer's Sustainability (pills + label/value rows from axes A–D).
    """
    hit = _ifw_resolve_manufacturer(manufacturer)
    if not hit:
        return None
    canon, e = hit
    data = fn140a_load_impact_framework()
    weights = ((data.get("_meta") or {}).get("scoring_weights") or {}).get("company_score")
    score = _ifw_score_manufacturer(e, weights)

    A = e.get("A_climate_commitments", {}) or {}
    B = e.get("B_reporting_transparency", {}) or {}
    C = e.get("C_product_credentials", {}) or {}
    D = e.get("D_supply_chain", {}) or {}

    try:
        sbti_i = int(A.get("sbti_status", 0) or 0)
    except (TypeError, ValueError):
        sbti_i = 0
    cdp_raw = str(A.get("cdp_rating") or "—").strip() or "—"
    cdp_on = cdp_raw not in ("—", "not_participating", "None", "none")
    cdp = cdp_raw if cdp_on else "—"
    iso14 = bool(B.get("iso14001"))
    epd_op = str(C.get("epd_programme_operator_primary") or "—").strip() or "—"
    bcorp = B.get("bcorp_certified")
    if bcorp is None:
        bcorp = C.get("bcorp_certified")
    bcorp = bool(bcorp)
    eco = str(B.get("ecovadis") or "none").strip() or "none"
    tier = str(e.get("maturity_tier") or "—").strip() or "—"

    def _yn(v: bool) -> str:
        return "Yes" if v else "No"

    def _disp(v, empty="—") -> str:
        if v is None or v is False:
            return empty if v is False else "—"
        if v is True:
            return "Yes"
        s = str(v).strip()
        if not s or s.lower() in ("none", "nan", "null", "not_participating", "not-assessed"):
            return "—"
        return s

    pills = [
        {"label": _SBTI_LABELS.get(sbti_i, "No SBTi"), "on": sbti_i > 0},
        {"label": f"CDP {cdp}", "on": cdp_on},
        {"label": "ISO 14001", "on": iso14},
        {"label": f"EPD: {epd_op}", "on": epd_op not in ("—", "none", "None")},
    ]
    if bcorp:
        pills.append({"label": "B Corp", "on": True})
    if eco.lower() not in ("none", "—", ""):
        pills.append({"label": f"EcoVadis: {eco}", "on": True})

    rows = [
        ["Maturity tier", tier],
        ["Impact score", f"{score['total']:.1f} / 100"],
        ["SBTi", _SBTI_SHORT.get(sbti_i, "—")],
        ["CDP rating", cdp if cdp != "not_participating" else "—"],
        ["ISO 14001", _yn(iso14)],
        ["B Corp", _yn(bcorp)],
        ["EcoVadis", _disp(eco if eco.lower() != "none" else None)],
        ["EPD programme", _disp(epd_op if epd_op.lower() not in ("none",) else None)],
        ["Sustainability report", _disp(B.get("sustainability_report"))],
        ["CSRD / ESRS", _disp(B.get("csrd_esrs_status"))],
        ["Supplier code of conduct", _yn(bool(D.get("supplier_code_of_conduct")))],
        ["Material origin disclosed", _yn(bool(D.get("raw_material_origin_disclosed")))],
    ]
    # Drop empty / dash-only rows except the headline score + tier
    keep_always = {"Maturity tier", "Impact score"}
    rows = [
        [lab, val] for lab, val in rows
        if lab in keep_always or (val and val not in ("—", "No", "None", "0"))
    ]

    hq = str(e.get("hq") or "").strip()
    sector = str(e.get("sector") or "").strip()
    return {
        "name": canon,
        "tier": tier,
        "score": score["total"],
        "hq": hq,
        "sector": sector,
        "pills": pills,
        "rows": rows,
    }


def fn140c_manufacturer_impact_summaries_by_name(
    names: list | tuple | set | None,
) -> dict[str, dict]:
    """``{catalogue_manufacturer_name: summary}`` for names that match IFW."""
    out: dict[str, dict] = {}
    for raw in names or []:
        key = str(raw or "").strip()
        if not key or key in out:
            continue
        summary = fn140b_manufacturer_impact_summary(key)
        if summary:
            out[key] = summary
    return out


def _clear_manufacturer_caches() -> None:
    """Bust Impact Framework + sust-credentials caches after a write."""
    for fn in (
        fn140a_load_impact_framework,
        fn135_sustainability_credentials,
        _ifw_manufacturer_lookup,
    ):
        try:
            fn.clear()
        except Exception:
            pass
    try:
        fn140b_manufacturer_impact_summary.clear()
    except Exception:
        pass
    try:
        fn140c_manufacturer_impact_summaries_by_name.clear()
    except Exception:
        pass


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def fn140d_list_manufacturer_names() -> list[str]:
    """Sorted manufacturer names from IFW ∪ sustainability credentials."""
    names: set[str] = set()
    try:
        ifw = fn140a_load_impact_framework()
        names.update((ifw.get("entities") or {}).get("manufacturers", {}).keys())
    except Exception:
        pass
    try:
        sust = fn135_sustainability_credentials()
        names.update((sust.get("credentials") or {}).keys())
        names.update((sust.get("company_profiles") or {}).keys())
    except Exception:
        pass
    return sorted(n for n in names if str(n).strip())


def fn140e_load_manufacturer_for_edit(name: str) -> dict:
    """Flat form values for *name* (IFW entity + optional sust overlay)."""
    from libs.lib_manufacturer_map import flatten_manufacturer

    raw = str(name or "").strip()
    entity: dict | None = None
    canon = raw
    try:
        ifw = fn140a_load_impact_framework()
        mfrs = (ifw.get("entities") or {}).get("manufacturers", {}) or {}
        if raw in mfrs:
            entity = mfrs[raw]
            canon = raw
        else:
            hit = _ifw_resolve_manufacturer(raw)
            if hit:
                canon, entity = hit
    except Exception:
        entity = None

    sust_creds = None
    sust_profile = None
    try:
        sust = fn135_sustainability_credentials()
        creds = sust.get("credentials") or {}
        profiles = sust.get("company_profiles") or {}
        for key in (canon, raw):
            if key in creds:
                sust_creds = creds[key]
                break
        for key in (canon, raw):
            if key in profiles:
                sust_profile = profiles[key]
                break
    except Exception:
        pass

    return flatten_manufacturer(
        canon, entity, sust_creds=sust_creds, sust_profile=sust_profile,
    )


def fn140f_save_manufacturer_edit(
    values: dict,
    *,
    previous_name: str | None = None,
) -> str:
    """Persist manufacturer form values to IFW (+ sust overlay when applicable).

    Returns the canonical name written. Renames move the IFW key when
    ``M__Name`` differs from *previous_name*.
    """
    from libs.lib_manufacturer_map import (
        unflatten_to_entity,
        unflatten_sust_creds,
        unflatten_sust_profile,
    )

    name = str((values or {}).get("M__Name") or "").strip()
    if not name:
        raise ValueError("Manufacturer name is required.")

    prev = str(previous_name or name).strip() or name

    # ── Impact Framework ──────────────────────────────────────────────────
    with open(_IMPACT_FRAMEWORK_PATH, "r", encoding="utf-8") as f:
        ifw = json.load(f)
    ents = ifw.setdefault("entities", {})
    mfrs = ents.setdefault("manufacturers", {})
    base = mfrs.get(prev) or mfrs.get(name) or {}
    entity = unflatten_to_entity(values, base=base)
    if prev != name and prev in mfrs:
        del mfrs[prev]
    mfrs[name] = entity
    meta = ifw.setdefault("_meta", {})
    meta["last_updated"] = time.strftime("%Y-%m-%d")
    _atomic_write_json(_IMPACT_FRAMEWORK_PATH, ifw)

    # ── Sustainability credentials overlay (create/update if any S__/P__ set) ─
    sust_creds = unflatten_sust_creds(values)
    sust_profile = unflatten_sust_profile(values)
    has_sust = any(v is not None and str(v).strip() != "" for v in sust_creds.values())
    has_prof = any(
        v is not None and str(v).strip() != ""
        for k, v in sust_profile.items()
        if k in ("report", "report_url")
    )
    if has_sust or has_prof or prev in (fn135_sustainability_credentials().get("credentials") or {}):
        with open(_SUST_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            sust = json.load(f)
        creds = sust.setdefault("credentials", {})
        profiles = sust.setdefault("company_profiles", {})
        if has_sust:
            existing = dict(creds.get(prev) or creds.get(name) or {})
            existing.update({k: v for k, v in sust_creds.items() if v is not None})
            if "maturity" not in existing or existing.get("maturity") is None:
                existing["maturity"] = entity.get("maturity_tier") or "Minimal"
            if prev != name and prev in creds:
                del creds[prev]
            creds[name] = existing
        elif prev != name and prev in creds:
            creds[name] = creds.pop(prev)
        if has_prof or name in profiles or prev in profiles:
            existing_p = dict(profiles.get(prev) or profiles.get(name) or {})
            existing_p.update({k: v for k, v in sust_profile.items() if v is not None})
            if prev != name and prev in profiles:
                del profiles[prev]
            profiles[name] = existing_p
        # Keep sector index loosely in sync
        sectors = sust.setdefault("sectors", {})
        sector = str(entity.get("sector") or "").strip()
        if sector:
            bucket = list(sectors.get(sector) or [])
            if prev in bucket and prev != name:
                bucket = [name if x == prev else x for x in bucket]
            if name not in bucket:
                bucket.append(name)
            sectors[sector] = sorted(set(bucket))
        _atomic_write_json(_SUST_CREDENTIALS_PATH, sust)

    _clear_manufacturer_caches()
    return name


def fn140g_delete_manufacturer_edit(
    name: str,
    *,
    wipe_sust: bool = False,
) -> None:
    """Remove a manufacturer from the Impact Framework (optional sust wipe)."""
    raw = str(name or "").strip()
    if not raw:
        raise ValueError("Manufacturer name is required.")

    with open(_IMPACT_FRAMEWORK_PATH, "r", encoding="utf-8") as f:
        ifw = json.load(f)
    mfrs = (ifw.get("entities") or {}).get("manufacturers", {}) or {}
    if raw in mfrs:
        del mfrs[raw]
        meta = ifw.setdefault("_meta", {})
        meta["last_updated"] = time.strftime("%Y-%m-%d")
        _atomic_write_json(_IMPACT_FRAMEWORK_PATH, ifw)

    if wipe_sust:
        with open(_SUST_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            sust = json.load(f)
        changed = False
        for bucket_key in ("credentials", "company_profiles"):
            bucket = sust.get(bucket_key) or {}
            if raw in bucket:
                del bucket[raw]
                sust[bucket_key] = bucket
                changed = True
        sectors = sust.get("sectors") or {}
        for sec, names in list(sectors.items()):
            if raw in (names or []):
                sectors[sec] = [n for n in names if n != raw]
                changed = True
        if changed:
            _atomic_write_json(_SUST_CREDENTIALS_PATH, sust)

    _clear_manufacturer_caches()


_EVF_LEVEL_ORDER = ("Core", "Core-se-applicabile", "Advanced")
_EVF_NATURE_ORDER = ("Compliance", "Compliance condizionata", "Merito")


def _evf_norm_followup(raw) -> dict:
    """Normalize a follow-up to ``{question, input, ...}``.

    ``input`` is ``text`` | ``year`` | ``multi`` | ``table``.
    Multi may carry ``options`` and ``other`` (bool → free-text "Altro").
    Table may carry ``rows``, ``value_label``, ``other_row``, ``other_placeholder``.
    """
    if isinstance(raw, dict):
        q = str(raw.get("question") or raw.get("q") or "").strip()
        kind = str(raw.get("input") or "text").strip().lower() or "text"
        if kind not in ("text", "year", "multi", "table"):
            kind = "text"
        out: dict = {"question": q, "input": kind}
        placeholder = str(raw.get("placeholder") or "").strip()
        if placeholder:
            out["placeholder"] = placeholder
        if kind == "multi":
            opts = raw.get("options") or []
            out["options"] = [str(o).strip() for o in opts if str(o).strip()]
            out["other"] = bool(raw.get("other"))
        if kind == "table":
            out["rows"] = [
                str(r).strip() for r in (raw.get("rows") or []) if str(r).strip()
            ]
            out["value_label"] = str(raw.get("value_label") or "Valore").strip() or "Valore"
            other_row = str(raw.get("other_row") or "").strip()
            if other_row:
                out["other_row"] = other_row
            other_ph = str(raw.get("other_placeholder") or "").strip()
            if other_ph:
                out["other_placeholder"] = other_ph
        return out
    return {"question": str(raw or "").strip(), "input": "text"}


def fn140h_evaluation_framework() -> tuple[pd.DataFrame, dict]:
    """Evidence-level evaluation framework for manufacturers (``evaluation_framework``).

    Returns ``(df, meta)`` where *df* is one row per evidence item with the
    columns Macroarea / Evidenza / Livello / Natura / Dipendenza condizionale /
    Criterio / Nota, plus the sort helpers ``_area_order``/``_level_order``.
    *meta* carries the level and nature glossaries and the scoring rule.

    Lives inside aux_companies_impact_framework.json — no separate file, so the
    framework travels with the entities it is meant to score.
    """
    ifw = fn140a_load_impact_framework()
    block = (ifw.get("evaluation_framework") or {})
    meta = dict(block.get("_meta") or {})
    rows: list[dict] = []
    for area in block.get("macroareas") or []:
        label = str(area.get("label") or area.get("key") or "—")
        order = int(area.get("order") or 0)
        for item in area.get("evidence") or []:
            level = str(item.get("level") or "")
            rows.append({
                "Macroarea": label,
                "Evidenza": str(item.get("evidence") or ""),
                "Livello": level,
                "Livello fonte": str(item.get("source_level") or ""),
                "Natura": str(item.get("nature") or ""),
                "Dipendenza condizionale": str(item.get("condition") or ""),
                "Criterio": str(item.get("criterion") or ""),
                "Nota": str(item.get("note") or ""),
                "_area_key": str(area.get("key") or ""),
                "_area_order": order,
                "_level_order": (
                    _EVF_LEVEL_ORDER.index(level) if level in _EVF_LEVEL_ORDER else 99
                ),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["_area_order", "_level_order", "Evidenza"], kind="stable"
        ).reset_index(drop=True)
    return df, meta


def fn140i_evaluation_questionnaire() -> tuple[list[dict], dict]:
    """Supplier questionnaire derived from the same ``evaluation_framework`` block.

    Returns ``(areas, meta)``: one entry per macroarea, each with its ``label``,
    ``key`` and a list of question blocks (screening question, main question,
    follow-ups, expected response type and the document to attach), carrying the
    evidence's level, nature and applicability condition.
    """
    ifw = fn140a_load_impact_framework()
    block = (ifw.get("evaluation_framework") or {})
    meta = dict(block.get("_meta") or {})
    areas: list[dict] = []
    for area in sorted(
        block.get("macroareas") or [], key=lambda a: int(a.get("order") or 0)
    ):
        questions = [
            {
                "evidence": str(it.get("evidence") or ""),
                "level": str(it.get("level") or ""),
                "nature": str(it.get("nature") or ""),
                "condition": str(it.get("condition") or ""),
                "screening": str(it.get("screening") or ""),
                "question": str(it.get("question") or ""),
                "followups": [
                    _evf_norm_followup(f) for f in (it.get("followups") or [])
                    if (
                        str(f.get("question") or f.get("q") or "").strip()
                        if isinstance(f, dict)
                        else str(f or "").strip()
                    )
                ],
                "response_type": str(it.get("response_type") or ""),
                "document": str(it.get("document") or ""),
                # B Lab FTE band from which this evidence enters the questionnaire
                # (micro / piccola / media / grande). Missing → micro (always on).
                "size_min": str(it.get("size_min") or "micro").strip().lower()
                or "micro",
            }
            for it in (area.get("evidence") or [])
            if str(it.get("question") or "").strip()
        ]
        questions.sort(
            key=lambda q: (
                _EVF_LEVEL_ORDER.index(q["level"])
                if q["level"] in _EVF_LEVEL_ORDER else 99,
                q["evidence"],
            )
        )
        if questions:
            areas.append({
                "key": str(area.get("key") or ""),
                "label": str(area.get("label") or area.get("key") or "—"),
                "questions": questions,
            })
    return areas, meta


# ════════════════════════════════════════════════════════════════════════════
# EPD NUMBER UTILITIES  (fn141–fn143)
# Shared across 9_ECOportal.py, 6_RevaluMatching.py, lib_epd_extractor.py
# ════════════════════════════════════════════════════════════════════════════

# Regex patterns for extracting EPD numbers from free-text (technology field,
# PDF text, etc.).  Ordered cheapest-to-match first.
EPD_NUMBER_PATTERNS: list[re.Pattern] = [
    re.compile(r'\b(NEPD[-\s]\d{4,}[-\w]*)',                                re.I),
    re.compile(r'\b(EPD-IES-\d+(?::\d+)?)',                                 re.I),
    re.compile(r'\b(S-P-\d{4,})',                                           re.I),
    re.compile(r'\b(IBU[-\s]\d{3}[-\d\-]+)',                                re.I),
    re.compile(r'\b(HUB-\d{3,})',                                           re.I),
    re.compile(r'\b(EPDITALY\d{3,})',                                       re.I),
    re.compile(r'\b(EPD-[A-Z]{2,8}-\d{6,}-[A-Z0-9]{3,}-[A-Z]{2})\b',      re.I),
    re.compile(
        r'(?:registration|declaration)\s*(?:number|no\.?)\s*[:\s]*'
        r'([A-Z0-9][A-Z0-9\-/]{3,30})',
        re.I,
    ),
]

# Regex to pull <common:registrationNumber> from raw ILCD XML text — avoids
# a full ET parse when only this single field is needed.
EPD_XML_REG_RE: re.Pattern = re.compile(
    r'<[^>]*:?registrationNumber[^>]*>\s*([^<]+?)\s*</',
    re.I,
)


def fn141_norm_epd_num(s: str) -> str | None:
    """Normalise an EPD number string for consistent cross-source comparison.

    Rules:
      - Strip leading/trailing whitespace
      - Upper-case
      - Collapse any run of whitespace, colons, or dots into a single '-'
      - Strip trailing '-'
      - Return None when the result is shorter than 4 characters

    Examples:
      "EPD-IES-0023962:001" → "EPD-IES-0023962-001"
      "S-P-00935"           → "S-P-00935"
      "hub 1416"            → "HUB-1416"
      "*"                   → None
    """
    s = str(s).strip()
    if len(s) < 4:
        return None
    return re.sub(r'[\s:\.]+', '-', s.upper()).rstrip('-')


def fn142_is_valid_epd_num(s: str) -> bool:
    """Return True only for strings that look like real EPD numbers.

    Rejects wildcards, placeholder text, pure product names, and anything
    without at least one digit (all real EPD numbers contain digits).
    """
    if not s:
        return False
    s = s.strip()
    if s in ('*', '-', '—', 'n/a', 'na', 'none', ''):
        return False
    if not re.search(r'\d', s):          # must contain at least one digit
        return False
    if len(s) > 50:                       # product names are longer than this
        return False
    return True


def fn142a_is_usable_document_url(value) -> bool:
    """True when *value* is a non-placeholder URL/path suitable for hyperlinks."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s:
        return False
    if s.lower() in ("-", "–", "—", "n/a", "na", "n/r", "nr", "nan", "none", "<na>", "*"):
        return False
    return True


def _probe_http_url_candidates(url: str) -> list[str]:
    s = str(url or "").strip()
    if not s:
        return []
    if s.lower().startswith(("http://", "https://")):
        return [s]
    if "://" not in s:
        return ["https://" + s.lstrip("/")]
    return [s]


def _probe_url_request_headers(url: str) -> dict:
    headers = dict(_DEFAULT_IMAGE_REQUEST_HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(str(url or "").strip())
        if parsed.scheme and parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return headers


def _probe_http_url_once(fetch_url: str, *, kind: str) -> dict:
    """Single HTTP probe; returns fn142b-shaped dict (uncached)."""
    kind_l = str(kind or "generic").strip().lower()
    headers = _probe_url_request_headers(fetch_url)
    status_code: int | None = None
    snippet = b""
    content_type = ""
    try:
        try:
            resp = requests.head(
                fetch_url,
                headers=headers,
                timeout=12,
                allow_redirects=True,
                verify=True,
            )
        except requests.exceptions.SSLError:
            resp = requests.head(
                fetch_url,
                headers=headers,
                timeout=12,
                allow_redirects=True,
                verify=False,
            )
        status_code = int(resp.status_code)
        content_type = str(resp.headers.get("content-type", "") or "").lower()

        needs_body = kind_l in ("image", "pdf") and status_code < 400
        if status_code in (403, 405, 501) or status_code >= 500 or needs_body:
            try:
                resp = requests.get(
                    fetch_url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                    verify=True,
                    stream=True,
                )
            except requests.exceptions.SSLError:
                resp = requests.get(
                    fetch_url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                    verify=False,
                    stream=True,
                )
            status_code = int(resp.status_code)
            content_type = str(resp.headers.get("content-type", "") or "").lower()
            try:
                for chunk in resp.iter_content(4096):
                    if chunk:
                        snippet = (snippet + chunk)[:8192]
                    if len(snippet) >= 8192:
                        break
            finally:
                resp.close()
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "level": "error",
            "status_code": None,
            "label": "Timeout",
            "detail": "No response within 15s",
            "url": fetch_url,
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "level": "error",
            "status_code": None,
            "label": "Unreachable",
            "detail": str(exc)[:120],
            "url": fetch_url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "level": "error",
            "status_code": None,
            "label": "Error",
            "detail": str(exc)[:120],
            "url": fetch_url,
        }

    if kind_l == "image":
        looks_ok = _bytes_look_like_image(snippet) or "image/" in content_type
    elif kind_l == "pdf":
        looks_ok = snippet[:4] == b"%PDF" or "pdf" in content_type
    else:
        looks_ok = True

    if status_code == 404:
        return {
            "ok": False,
            "level": "error",
            "status_code": status_code,
            "label": "404",
            "detail": "Not found",
            "url": fetch_url,
        }
    if status_code == 403:
        return {
            "ok": False,
            "level": "warn",
            "status_code": status_code,
            "label": "403",
            "detail": "Blocked to bots — may still open in browser",
            "url": fetch_url,
        }
    if status_code == 401:
        return {
            "ok": False,
            "level": "warn",
            "status_code": status_code,
            "label": "401",
            "detail": "Authentication required",
            "url": fetch_url,
        }
    if 200 <= status_code < 400:
        if kind_l in ("image", "pdf") and snippet and not looks_ok and status_code < 300:
            return {
                "ok": False,
                "level": "warn",
                "status_code": status_code,
                "label": str(status_code),
                "detail": "Reachable but response is not a "
                + ("PDF" if kind_l == "pdf" else "recognised image"),
                "url": fetch_url,
            }
        return {
            "ok": True,
            "level": "ok",
            "status_code": status_code,
            "label": str(status_code),
            "detail": "Reachable",
            "url": fetch_url,
        }
    return {
        "ok": False,
        "level": "error",
        "status_code": status_code,
        "label": str(status_code),
        "detail": f"HTTP {status_code}",
        "url": fetch_url,
    }


# ttl: a probe result is a snapshot of someone else's server — without one, a URL
# that was down once (or fixed since) kept its first answer until restart.
@st.cache_data(show_spinner=False, ttl=600, max_entries=500)
def fn142b_probe_http_url(url: str, kind: str = "generic") -> dict:
    """Cached HTTP reachability probe for Add/Edit URL fields."""
    raw = str(url or "").strip()
    if not fn142a_is_usable_document_url(raw):
        return {
            "ok": False,
            "level": "idle",
            "status_code": None,
            "label": "—",
            "detail": "No URL",
            "url": raw,
        }
    candidates = _probe_http_url_candidates(raw)
    if not candidates:
        return {
            "ok": False,
            "level": "error",
            "status_code": None,
            "label": "Invalid",
            "detail": "Not a valid http(s) URL",
            "url": raw,
        }
    last: dict | None = None
    for fetch_url in candidates:
        last = _probe_http_url_once(fetch_url, kind=kind)
        if last.get("ok") or last.get("level") == "warn":
            return last
    return last or {
        "ok": False,
        "level": "error",
        "status_code": None,
        "label": "Error",
        "detail": "Probe failed",
        "url": raw,
    }


def fn143_build_matlib_epd_sets(
    df: "pd.DataFrame",
) -> tuple[set[str], set[str]]:
    """Build normalised EPD-number and product-name lookup sets from MatLib data.

    Returns
    -------
    epd_nums : set[str]
        Normalised EPD numbers from E__EPD_DecNumber + E__EPD_RegNumber.
        Noise values (wildcards, product names, etc.) are filtered out via
        fn142_is_valid_epd_num before normalisation.
    names_lc : set[str]
        Lower-cased A__ProductName values (used as secondary / name match).
    """
    epd_nums: set[str] = set()
    names_lc: set[str] = set()
    try:
        for col in ('E__EPD_DecNumber', 'E__EPD_RegNumber'):
            if col in df.columns:
                for raw in df[col].dropna():
                    raw_s = str(raw).strip()
                    if not fn142_is_valid_epd_num(raw_s):
                        continue
                    norm = fn141_norm_epd_num(raw_s)
                    if norm:
                        epd_nums.add(norm)
        if 'A__ProductName' in df.columns:
            names_lc = {
                str(v).strip().lower()
                for v in df['A__ProductName'].dropna()
                if str(v).strip()
            }
    except Exception:
        pass
    return epd_nums, names_lc


# ════════════════════════════════════════════════════════════════════════════
# ADD / EDIT ITEM — dataset round-trip (pages/13_Add_Edit_Item.py)
# ════════════════════════════════════════════════════════════════════════════
# fn144_resolve_live_parquet_path / fn145_load_raw_live_dataframe /
# fn146_save_raw_live_dataframe are gone. All three existed to read and rewrite
# live_data.parquet, the materialised base + edits merge — a third copy of rows
# that already lived in two files. The Add/Edit page appends to the edit log
# (fn156) and readers derive the merge (fn159_effective_dataset), so there is
# nothing left to round-trip.


def fn147_next_eetra_id(df: pd.DataFrame, product_type: str) -> str:
    """Generate a new ``TYPE__SUBTYPE__NNNN`` id, reusing the prefix already used
    by other rows of the same product type; falls back to a slug of the product
    type when no such row exists yet."""
    id_re = re.compile(r"^[A-Z]+__[A-Z]+__\d+$")
    if "0__EETRA_ID" not in df.columns:
        return "NEW__ITEM__0001"
    all_ids = df["0__EETRA_ID"].dropna().astype(str)
    valid_ids = all_ids[all_ids.str.match(id_re)]

    prefix = None
    if "D__ProductType_ENG" in df.columns and product_type:
        same_type_ids = df.loc[
            df["D__ProductType_ENG"].astype(str).str.strip() == str(product_type).strip(),
            "0__EETRA_ID",
        ].dropna().astype(str)
        same_type_ids = same_type_ids[same_type_ids.str.match(id_re)]
        if not same_type_ids.empty:
            prefix = same_type_ids.apply(lambda v: v.rsplit("__", 1)[0]).value_counts().index[0]
    if prefix is None:
        code = re.sub(r"[^A-Za-z]", "", str(product_type or "ITEM")).upper()[:3] or "ITM"
        prefix = f"{code}__{code}"

    same_prefix = valid_ids[valid_ids.str.startswith(prefix + "__")]
    max_n = 0
    for v in same_prefix:
        try:
            max_n = max(max_n, int(v.rsplit("__", 1)[1]))
        except Exception:
            pass
    return f"{prefix}__{max_n + 1:04d}"


def fn148_upsert_live_data_row(
    df: pd.DataFrame, eetra_id: str, values: dict, is_new: bool
) -> pd.DataFrame:
    """Insert a new row or update an existing one (matched by ``0__EETRA_ID``) in
    the raw live-data DataFrame. Only columns present in ``values`` are touched
    on update — untouched columns (e.g. ``*_Local`` cache paths) are preserved."""
    out = df.copy()

    def _cast(col, v):
        if col not in out.columns:
            return v
        if pd.api.types.is_float_dtype(out[col]) or pd.api.types.is_integer_dtype(out[col]):
            return pd.to_numeric(v, errors="coerce")
        return None if v in (None, "") else str(v)

    if is_new:
        for col in values:
            if col not in out.columns:
                out[col] = pd.Series([pd.NA] * len(out), dtype="string")
        row = {col: pd.NA for col in out.columns}
        for col, v in values.items():
            row[col] = _cast(col, v)
        row["0__EETRA_ID"] = eetra_id
        if "0__NUM" in out.columns:
            try:
                row["0__NUM"] = float(pd.to_numeric(out["0__NUM"], errors="coerce").max() or 0) + 1
            except Exception:
                row["0__NUM"] = 1.0
        # A__Map_yn isn't on the Add/Edit form, so it arrives as pd.NA — and
        # ``not pd.NA`` raises rather than being falsy. Test for emptiness explicitly.
        if "A__Map_yn" in out.columns:
            _map_yn = row.get("A__Map_yn")
            if pd.isna(_map_yn) or str(_map_yn).strip() == "":
                row["A__Map_yn"] = "Y"
        out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
    else:
        mask = out["0__EETRA_ID"].astype(str) == str(eetra_id)
        if not mask.any():
            raise ValueError(f"EETRA ID not found: {eetra_id}")
        idx = out.index[mask][0]
        for col, v in values.items():
            if col not in out.columns:
                out[col] = pd.Series([pd.NA] * len(out), dtype="string")
            out.at[idx, col] = _cast(col, v)
    return out


DATA_SOURCE_OPTIONS: tuple[str, ...] = ("Neon", "Local Parquet", "EETRA Sharepoint")


def fn149a_data_source_options() -> tuple[str, ...]:
    """Catalogue sources offered in the Welcome picker.

    **Neon** is listed first (and is the session default) whenever
    ``[neon] database_url`` is configured; otherwise the list starts at
    Local Parquet.
    """
    from libs.lib_neon import neon_url

    if neon_url():
        return DATA_SOURCE_OPTIONS
    return tuple(o for o in DATA_SOURCE_OPTIONS if o != "Neon")


def fn149_ensure_data_platform_session(
    default: str | None = None,
) -> None:
    """Ensure ``st.session_state['data_platform']`` is a valid catalogue source.

    Default is **Neon** when a connection string is configured, else Local Parquet.
    """
    opts = fn149a_data_source_options()
    if default is None or default not in opts:
        default = opts[0]
    if "data_platform" not in st.session_state:
        st.session_state["data_platform"] = default
    elif st.session_state.get("data_platform") not in opts:
        st.session_state["data_platform"] = default


def fn150_render_data_source_selector() -> None:
    """Data Source picker (Developer Dashboard); persists in session for ``app.py`` loading.

    The widget has its own key and copies into ``data_platform`` on change:
    a widget-bound key is dropped by Streamlit once its page stops rendering,
    which would reset the source on the first navigation away.
    """
    fn149_ensure_data_platform_session()
    opts = list(fn149a_data_source_options())

    def _sync() -> None:
        st.session_state["data_platform"] = st.session_state["_data_platform_picker"]

    st.selectbox(
        "Data Source",
        opts,
        index=opts.index(st.session_state["data_platform"]),
        key="_data_platform_picker",
        on_change=_sync,
    )


def fn151_sidebar_filters_active() -> bool:
    return any(
        st.session_state.get(f"enable_filter_{i}", False)
        for i in range(1, 4)
    )


def _fn151_apply_sidebar_filters_to_df(df: pd.DataFrame) -> pd.DataFrame:
    """Replay sidebar dataset filters on *df* (same equality rules as fn302)."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    out = df
    for i in range(1, 4):
        if not st.session_state.get(f"enable_filter_{i}", False):
            continue
        col = st.session_state.get(f"filter_col_{i}")
        val = st.session_state.get(f"filter_val_{i}")
        if not col or col not in out.columns or val is None:
            continue
        out = out.loc[out[col] == val]
    return out.copy()


def fn152_edit_picker_dataframe(raw_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rows in **Select item to edit** — matches the Catalogue listing.

    Uses the active app data source (``FILTERED_DATA`` / ``ORIGINAL_DATA`` in session),
    not a separate join to local parquet. Applies the same ``A__Map_yn == Y`` rule as
    ``pages/2_Catalogue.py``. *raw_df* is only a fallback when session data is not ready
    (e.g. standalone Add/Edit page before ``app.py`` has loaded).
    """
    df: pd.DataFrame | None = None
    if st.session_state.get("df_filtered_ready"):
        filtered = st.session_state.get("FILTERED_DATA")
        if isinstance(filtered, pd.DataFrame) and not filtered.empty:
            df = filtered
        else:
            orig = st.session_state.get("ORIGINAL_DATA")
            if isinstance(orig, pd.DataFrame) and not orig.empty:
                df = orig
    if df is None or df.empty:
        if raw_df is not None and not raw_df.empty:
            df = _fn151_apply_sidebar_filters_to_df(raw_df)
        else:
            return pd.DataFrame()
    out = fn128_filter_map_y_products(df)
    return out.copy() if out is not None and not out.empty else pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════
# BASE + EDITS PARQUET MODEL (fn153-fn158)
# ════════════════════════════════════════════════════════════════════════════
#
#   base_data.parquet   Excel conversion. Never written by the app. May live in
#                       Neon (matlib_base) when [neon] database_url is set —
#                       see fn153b_load_base_dataframe / libs/lib_neon.py.
#   edits_data.parquet  Append-only. One full-row snapshot per save, plus the
#                       provenance of that save in its "_edit_*" audit columns.
#                       May live in Neon (matlib_edits) the same way.
#   (no third file)     The merge is derived on read by fn159_effective_dataset,
#                       and so is the correction register (fn155c), which used to
#                       be a third parquet; direct parquet readers elsewhere need
#                       no changes.

# Audit columns on the edit log. The first four identify the save; the last five
# carry its provenance — the batch it belonged to, why the value changed, the
# document that proves it, and which fields that evidence covers. They replace
# the separate correction register: old/new values were always recoverable by
# diffing consecutive snapshots, so only the *why* ever needed storing.
EDIT_AUDIT_COLS: tuple[str, ...] = (
    "_edit_id", "_edit_ts", "_edit_user", "_edit_op",
    "_edit_batch", "_edit_reason", "_edit_evidence", "_edit_evidence_url",
    "_edit_fields",
)

# Provenance keys accepted by fn156/fn156b, stored as the "_edit_*" columns above.
EDIT_PROVENANCE_KEYS: tuple[str, ...] = (
    "batch", "reason", "evidence", "evidence_url", "fields",
)

#
# Both live in 01_data/ alongside the rest of the project's data (tags,
# collections, ice_db, img/, pdf/). They used to sit at the project root, with
# copies under 01_data/ and a third materialised file, live_data.parquet — four
# byte-identical parquets and no single answer to which one was canonical. Now
# there are two files and one answer.
_DEFAULT_BASE_PARQUET  = "01_data/base_data.parquet"
_DEFAULT_EDITS_PARQUET = "01_data/edits_data.parquet"

# Where these files used to live. Only consulted when the 01_data/ copy is
# absent, so an installation that has not been migrated still starts.
_LEGACY_BASE_PARQUET   = "base_data.parquet"
_LEGACY_EDITS_PARQUET  = "edits_data.parquet"


def _fn153_secret_parquet(key: str, default: str, legacy: str | None = None) -> Path:
    """Resolve a parquet path: explicit secret, else 01_data/, else the old root."""
    try:
        override = st.secrets.get("parquet", {}).get(key)
    except Exception:
        override = None
    if override:
        return Path(override)
    primary = _MATLIB_ROOT / default
    if primary.exists() or legacy is None:
        return primary
    fallback = _MATLIB_ROOT / legacy
    return fallback if fallback.exists() else primary


def fn153_resolve_base_parquet_path() -> Path:
    """Path to ``01_data/base_data.parquet`` — the Excel conversion. Override
    with ``[parquet] base_path`` in secrets."""
    return _fn153_secret_parquet("base_path", _DEFAULT_BASE_PARQUET, _LEGACY_BASE_PARQUET)


def fn154_resolve_edits_parquet_path() -> Path:
    """Path to ``01_data/edits_data.parquet`` — the append-only edit log.
    Override with ``[parquet] edits_path`` in secrets."""
    return _fn153_secret_parquet("edits_path", _DEFAULT_EDITS_PARQUET, _LEGACY_EDITS_PARQUET)


def _fn_neon_base_on() -> bool:
    """Base snapshot lives in Neon (libs/lib_neon.py) rather than parquet."""
    from libs.lib_neon import base_use_neon
    return base_use_neon()


def fn153b_load_base_dataframe(path: Path | None = None) -> pd.DataFrame:
    """Excel-conversion snapshot from Neon or ``base_data.parquet``.

    Empty frame when neither has been loaded yet. Prefer this over
    ``pd.read_parquet(fn153_…)`` so callers keep working once base is in Neon.
    """
    if path is None and _fn_neon_base_on():
        from libs.lib_neon import load_base
        return load_base()
    path = Path(path) if path is not None else fn153_resolve_base_parquet_path()
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def fn153c_base_available() -> bool:
    """True when a base snapshot exists (Neon row count > 0, or parquet on disk)."""
    if _fn_neon_base_on():
        from libs.lib_neon import base_row_count
        try:
            return base_row_count() > 0
        except Exception:
            return False
    return fn153_resolve_base_parquet_path().exists()


def fn153d_base_version() -> float:
    """Cache key that changes when base changes (file mtime, or Neon upload)."""
    if _fn_neon_base_on():
        from libs.lib_neon import base_version
        return float(base_version())
    p = fn153_resolve_base_parquet_path()
    return float(p.stat().st_mtime) if p.exists() else 0.0


def fn159_effective_dataset(columns: list[str] | None = None) -> pd.DataFrame:
    """Base ⊕ edits, for the modules that used to read ``live_data.parquet``.

    That file was a materialised copy of this merge, rewritten after every save
    so direct readers would not have to do the merge themselves. It was also a
    third copy of the same rows, and a silent way for a stale file to be served
    if a write ever failed. The merge is cheap and cached on both files' mtimes,
    so those readers now compute it instead.

    ``columns`` narrows the result where the caller wants only a few fields.
    """
    df = fn158a_cached_load_effective_live(*fn158b_effective_live_mtimes())
    if columns:
        keep = [c for c in columns if c in df.columns]
        return df[keep].copy() if keep else pd.DataFrame(columns=columns)
    return df


def _fn_neon_on() -> bool:
    """The edit log lives in Neon (libs/lib_neon.py) rather than in parquet files."""
    from libs.lib_neon import edits_use_neon
    return edits_use_neon()


def _fn_neon_edits_for_path(path: Path | None) -> bool:
    """Use Neon for the edit log unless *path* points at an explicit throwaway copy.

    Add/Edit passes the resolved default path; that must still hit Neon when
    configured. Only a path that differs from the default (tests/tools) forces
    parquet.
    """
    if not _fn_neon_on():
        return False
    if path is None:
        return True
    try:
        return Path(path).resolve() == fn154_resolve_edits_parquet_path().resolve()
    except OSError:
        return False


def fn155_load_edits_dataframe(path: Path | None = None) -> pd.DataFrame:
    """Read the append-only edit log. Returns an empty frame carrying only the
    audit columns when the file does not exist yet — callers can always rely on
    ``EDIT_AUDIT_COLS`` being present."""
    if _fn_neon_edits_for_path(path):
        from libs.lib_neon import load_edits
        return load_edits(EDIT_AUDIT_COLS)
    path = Path(path) if path is not None else fn154_resolve_edits_parquet_path()
    if not path.exists():
        return pd.DataFrame({c: pd.Series(dtype="string") for c in EDIT_AUDIT_COLS})
    try:
        edits = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame({c: pd.Series(dtype="string") for c in EDIT_AUDIT_COLS})
    for col in EDIT_AUDIT_COLS:
        if col not in edits.columns:
            edits[col] = pd.array([None] * len(edits), dtype="string")
    return edits


def _fn156_current_user() -> str:
    try:
        return str(st.session_state.get("auth_user") or "unknown")
    except Exception:
        return "unknown"


def fn156_append_edit_record(
    row: dict,
    eetra_id: str,
    op: str,
    *,
    base_columns: List[str] | None = None,
    path: Path | None = None,
    user: str | None = None,
    provenance: dict | None = None,
) -> Path:
    """Append one edit record to ``edits_data.parquet`` and return its path.

    *row* is a **full row snapshot** (every column of the effective dataset), so
    a merge never has to coalesce column-by-column: the newest record for an id
    simply wins. *op* is ``"insert"``, ``"update"`` or ``"delete"`` — a delete
    still carries the snapshot of the row it removed (see fn157).

    The write is atomic — the existing log is read, the record concatenated, and
    the result swapped in via ``os.replace``.
    """
    return fn156b_append_edit_records(
        [(row, eetra_id)], op, base_columns=base_columns, path=path, user=user,
        provenance=provenance,
    )


def fn156b_append_edit_records(
    rows: List[tuple[dict, str]],
    op: str,
    *,
    base_columns: List[str] | None = None,
    path: Path | None = None,
    user: str | None = None,
    provenance: dict | List[dict | None] | None = None,
) -> Path:
    """Append several ``(row snapshot, eetra_id)`` records in one atomic write.

    Same record shape as fn156; used when one save touches many items (an EPD
    reference product re-deriving its variants — libs/lib_epd_family.py).
    ``_edit_id`` stays strictly increasing within the batch.

    *provenance* records **why** the save happened — one dict applied to every
    record, or a list aligned with *rows*. Recognised keys are
    ``EDIT_PROVENANCE_KEYS``; ``fields`` is the list (or ";"-joined string) of
    column names the evidence covers. A save with no evidence behind it simply
    omits it and the columns stay NA.
    """
    use_neon = _fn_neon_edits_for_path(path)
    path = Path(path) if path is not None else fn154_resolve_edits_parquet_path()
    if not rows:
        return path
    existing = None if use_neon else fn155_load_edits_dataframe(path)

    t0 = time.time_ns()
    ts = pd.Timestamp.utcnow().isoformat()
    who = user or _fn156_current_user()
    if isinstance(provenance, list):
        if len(provenance) != len(rows):
            raise ValueError("provenance list must be aligned with rows")
        prov_for = lambda i: provenance[i] or {}
    else:
        _shared = provenance or {}
        prov_for = lambda i: _shared

    records = []
    for i, (row, eetra_id) in enumerate(rows):
        record = {c: row.get(c) for c in (base_columns or list(row.keys()))}
        record["0__EETRA_ID"] = str(eetra_id)
        record["_edit_id"]   = f"{t0 + i:d}"
        record["_edit_ts"]   = ts
        record["_edit_user"] = who
        record["_edit_op"]   = str(op)
        prov = prov_for(i)
        unknown = set(prov) - set(EDIT_PROVENANCE_KEYS)
        if unknown:
            raise ValueError(f"unknown provenance keys: {sorted(unknown)}")
        for key in EDIT_PROVENANCE_KEYS:
            val = prov.get(key)
            if key == "fields" and isinstance(val, (list, tuple, set)):
                val = ";".join(str(v) for v in val)
            record[f"_edit_{key}"] = None if val is None else str(val)
        records.append(record)

    if use_neon:
        from libs.lib_neon import append_edits
        append_edits(records, EDIT_AUDIT_COLS)
        return path

    new_row = pd.DataFrame(records)
    if existing.empty:
        combined = new_row
    else:
        # Sparsely-filled products leave whole columns all-NA in the log; pandas
        # warns that concat's dtype inference for those will change. Irrelevant
        # here — every object column is pinned to "string" right below.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            combined = pd.concat([existing, new_row], ignore_index=True)
    # Object columns straight out of a dict round-trip badly through pyarrow when
    # a column holds a mix of str/NA — pin them to pandas' nullable string dtype.
    for col in combined.columns:
        if combined[col].dtype == "object":
            combined[col] = combined[col].astype("string")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    combined.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, path)
    return path


# ── Data-correction register (derived from the edit log) ─────────────────────
# A save made against an evidence document records its provenance in the log's
# "_edit_*" audit columns. This register is the per-field *view* of those saves:
# one row per corrected field, with the value that was wrong and the value that
# replaced it. Nothing is stored here — old/new come from diffing a record
# against the state it replaced, which the append-only log already holds.
# Read by Developer → Data Corrections.
CORRECTION_COLS: tuple[str, ...] = (
    "_edit_id", "_corr_ts", "_corr_user", "batch", "0__EETRA_ID", "field",
    "old_value", "new_value", "evidence", "evidence_url", "reason",
)


def _fn155c_as_text(value) -> object:
    """Scalar to the register's text form; NA-ish values become None."""
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _fn155c_as_value(value) -> object:
    """Same, for a corrected field's old/new value.

    A whole number keeps its integer spelling ("0", not "0.0"): the log stores
    every column as text, so a percentage saved through a float round-trip would
    otherwise read differently here than it does on the item page. Only applied
    to the value columns — running it over an id would push a 19-digit
    ``_edit_id`` through float64 and silently corrupt its last digits.
    """
    text = _fn155c_as_text(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if not number.is_integer() or abs(number) >= 2**53:
        return text
    return str(int(number))


def fn155c_load_corrections_dataframe(path: Path | None = None) -> pd.DataFrame:
    """The correction register, rebuilt from the edit log's provenance columns.

    One row per (edit record × corrected field). ``old_value`` is read from the
    state that record replaced — the previous log record for the same id, or the
    base row when there is none — and ``new_value`` from the record itself.
    """
    empty = pd.DataFrame({c: pd.Series(dtype="string") for c in CORRECTION_COLS})
    edits = fn155_load_edits_dataframe(path)
    if edits is None or edits.empty or "_edit_fields" not in edits.columns:
        return empty

    log = edits.copy()
    if "_edit_id" in log.columns:
        log = log.sort_values("_edit_id", kind="stable")
    log = log.reset_index(drop=True)

    flagged = log["_edit_fields"].map(_fn155c_as_text).notna()
    if not flagged.any():
        return empty

    # Previous state per id: the record before this one, else the base row.
    try:
        base = fn153b_load_base_dataframe()
        base_by_id = (
            base.set_index(base["0__EETRA_ID"].astype(str))
            if not base.empty and "0__EETRA_ID" in base.columns else None
        )
    except Exception:
        base_by_id = None

    seen: dict[str, pd.Series] = {}
    out: list[dict] = []
    for pos, rec in log.iterrows():
        eid = str(rec.get("0__EETRA_ID") or "").strip()
        prev = seen.get(eid)
        if prev is None and base_by_id is not None and eid in base_by_id.index:
            row = base_by_id.loc[eid]
            prev = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        if flagged.iat[pos]:
            fields = [f.strip() for f in str(rec["_edit_fields"]).split(";") if f.strip()]
            for field in fields:
                out.append({
                    "_edit_id":     _fn155c_as_text(rec.get("_edit_id")),
                    "_corr_ts":     _fn155c_as_text(rec.get("_edit_ts")),
                    "_corr_user":   _fn155c_as_text(rec.get("_edit_user")),
                    "batch":        _fn155c_as_text(rec.get("_edit_batch")),
                    "0__EETRA_ID":  eid,
                    "field":        field,
                    "old_value":    None if prev is None else _fn155c_as_value(prev.get(field)),
                    "new_value":    _fn155c_as_value(rec.get(field)),
                    "evidence":     _fn155c_as_text(rec.get("_edit_evidence")),
                    "evidence_url": _fn155c_as_text(rec.get("_edit_evidence_url")),
                    "reason":       _fn155c_as_text(rec.get("_edit_reason")),
                })
        seen[eid] = rec

    if not out:
        return empty
    return pd.DataFrame(out, columns=list(CORRECTION_COLS)).astype(
        {c: "string" for c in CORRECTION_COLS}
    )



def _fn157_values_fit(dtype, vals) -> bool:
    """True when every non-NA value can be stored in *dtype* without widening."""
    if dtype == object:
        return True
    present = [v for v in vals if not (v is None or v is pd.NA or (isinstance(v, float) and v != v))]
    if not present:
        return True
    if isinstance(dtype, pd.StringDtype):
        return all(isinstance(v, str) for v in present)
    if pd.api.types.is_bool_dtype(dtype):
        return all(isinstance(v, (bool, np.bool_)) for v in present)
    if pd.api.types.is_numeric_dtype(dtype):
        return all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)
                   for v in present)
    return False


def fn157_merge_base_and_edits(base: pd.DataFrame, edits: pd.DataFrame) -> pd.DataFrame:
    """Overlay the edit log onto the base dataset — latest record per id wins.

    Rows whose ``0__EETRA_ID`` exists in base are replaced in place (keeping base
    row order); ids seen only in the log are appended. Audit columns are dropped
    from the result, so the merged frame is schema-identical to base.

    A record with ``_edit_op == "delete"`` is a **tombstone**: the id is removed
    from the merged view, whether it came from base or from an earlier insert.
    The log itself stays append-only — the record carries a full snapshot of the
    row as it was, so a deletion can be audited and reversed by hand, and a later
    insert/update record for the same id revives it (latest record still wins).
    """
    if base is None or base.empty:
        base = pd.DataFrame()
    if edits is None or edits.empty or "0__EETRA_ID" not in edits.columns:
        return base.copy()

    latest = edits.copy()
    # Stable sort on the monotonic _edit_id keeps the newest record per id last.
    if "_edit_id" in latest.columns:
        latest = latest.sort_values("_edit_id", kind="stable")
    latest = latest.drop_duplicates(subset="0__EETRA_ID", keep="last")

    # Read the op before the audit columns go, then drop the tombstoned ids from
    # the overlay so they can never be re-inserted below.
    deleted_ids: set[str] = set()
    if "_edit_op" in latest.columns:
        _is_delete = latest["_edit_op"].astype(str).str.strip().str.lower() == "delete"
        deleted_ids = set(latest.loc[_is_delete, "0__EETRA_ID"].astype(str))
        latest = latest.loc[~_is_delete]

    latest = latest.drop(columns=[c for c in EDIT_AUDIT_COLS if c in latest.columns])

    if base.empty:
        return latest.reset_index(drop=True)

    # Bring forward any edit-only columns (e.g. Physical-property ``*_CM`` flags)
    # so they survive the overlay instead of being dropped by reindex-to-base.
    base = base.copy()
    for col in latest.columns:
        if col == "0__EETRA_ID" or col in base.columns:
            continue
        base[col] = pd.Series([pd.NA] * len(base), dtype="string")

    # Align the overlay to the (possibly extended) base schema; missing edit
    # columns fall back to whatever base already holds.
    latest = latest.reindex(columns=base.columns)
    out = base.copy()
    out["0__EETRA_ID"] = out["0__EETRA_ID"].astype(str)
    latest["0__EETRA_ID"] = latest["0__EETRA_ID"].astype(str)

    known = set(out["0__EETRA_ID"])
    updates = latest[latest["0__EETRA_ID"].isin(known)]
    inserts = latest[~latest["0__EETRA_ID"].isin(known)]

    if not updates.empty:
        # Column-wise rather than one ``.at`` write per cell (~135 per updated row):
        # every updated row takes the edit record's full snapshot, NA included,
        # exactly as before. A column whose dtype can't hold the incoming values is
        # widened to object first, as the per-cell version did on its first clash.
        rec_by_id = updates.set_index("0__EETRA_ID")
        hit = out["0__EETRA_ID"].isin(rec_by_id.index)
        rows = out.index[hit]
        src = rec_by_id.loc[out.loc[hit, "0__EETRA_ID"].values]
        for col in out.columns:
            if col == "0__EETRA_ID":      # the match key: already equal on these rows
                continue
            vals = src[col].to_numpy(dtype=object)
            # Widen exactly when the per-cell ``.at`` write would have raised: a
            # str into a numeric column, or a non-str into a "string" column. A
            # column-wise .loc would instead coerce silently (e.g. "0.2" -> 0.2
            # into Float64), changing what the merged frame holds.
            if not _fn157_values_fit(out[col].dtype, vals):
                out[col] = out[col].astype("object")
            out.loc[rows, col] = vals
    if not inserts.empty:
        out = pd.concat([out, inserts], ignore_index=True)
    if deleted_ids:
        out = out.loc[~out["0__EETRA_ID"].isin(deleted_ids)]
    return out.reset_index(drop=True)


def fn158_load_effective_live_dataframe(
    *, materialise: bool = False
) -> pd.DataFrame:
    """Base ⊕ edits, uncached.

    ``materialise`` is accepted and ignored. It used to write the merge out to
    ``live_data.parquet`` for the modules that read that file directly; those
    modules now call :func:`fn159_effective_dataset`, so there is no third copy
    to keep in step. The parameter stays so existing call sites keep working.
    """
    base = fn153b_load_base_dataframe()
    return fn157_merge_base_and_edits(base, fn155_load_edits_dataframe())


@st.cache_data(show_spinner=False, max_entries=2)
def fn158a_cached_load_effective_live(
    base_mtime_ns: int, edits_mtime_ns: int
) -> pd.DataFrame:
    """@cache_data wrapper for fn158. The two mtimes are unused inside — they
    exist only so the cache key changes when either file on disk changes."""
    return fn158_load_effective_live_dataframe()


@st.cache_resource(show_spinner=False, max_entries=2)
def fn158c_cached_load_clean_effective_live(
    base_mtime_ns: int, edits_mtime_ns: int, key_column: str = "A__Manufacturer"
) -> pd.DataFrame:
    """Base ⊕ edits, cleaned (fn122) — what app.py renders from, once per file version.

    app.py used to chain fn158a → fn109, two ``@st.cache_data`` hits per rerun of
    every page: each unpickled a fresh copy of the whole frame, and fn109 first had
    to hash its DataFrame argument in full to find its entry (~80–130 ms before
    any page code ran). Keyed on scalars only and held as a resource, a hit is a
    dict lookup.

    **Read-only.** The same object is shared by every session; callers derive new
    frames from it (fn114 / fn507 copy, filters subset) and must never mutate it
    in place.
    """
    df = fn158_load_effective_live_dataframe()
    return fn122_clean_dataframe(df, key_column)


# ── SharePoint source: load ⊕ edits ⊕ clean ⊕ Map_yn, once per version ─────
# app.py used to run the edit-log merge, the clean and the Map_yn filter on every
# rerun of every page when the SharePoint source was selected (only the workbook
# download itself was cached). Same steps, same order, now cached on the workbook
# coordinates + the edit log's mtime, with the workbook download's own 1 h ttl.
_SP_FAIL: dict[tuple, tuple[float, str]] = {}
_SP_FAIL_RETRY_S = 60


@st.cache_resource(show_spinner="🔄 Loading from SharePoint...", ttl=3600, max_entries=2)
def _fn158d_sharepoint_effective(sp_key: tuple, edits_mtime_ns: int,
                                 key_column: str) -> tuple[pd.DataFrame, str]:
    (tenant_id, client_id, client_secret, site_hostname, site_path,
     document_library, file_path, sheet_name) = sp_key
    df = fn104_cached_load_excel(
        tenant_id=tenant_id, client_id=client_id, client_secret=client_secret,
        site_hostname=site_hostname, site_path=site_path,
        document_library=document_library, file_path=file_path, sheet_name=sheet_name,
    )
    merge_error = ""
    try:
        df = fn157_merge_base_and_edits(df, fn155_load_edits_dataframe())
    except Exception as e:          # app.py shows this as a warning, as before
        merge_error = str(e)[:120]
    df = fn122_clean_dataframe(df, key_column)
    return fn128_filter_map_y_products(df), merge_error


def fn158d_load_sharepoint_effective(
    sp_key: tuple, key_column: str = "A__Manufacturer"
) -> tuple[pd.DataFrame, str]:
    """``(frame, merge_error)`` for the SharePoint source. **Read-only** shared frame.

    ``sp_key`` = (tenant_id, client_id, client_secret, site_hostname, site_path,
    document_library, file_path, sheet_name). A failure is remembered for
    ``_SP_FAIL_RETRY_S`` seconds and re-raised straight away, so a SharePoint
    outage doesn't cost a token request plus four HTTP calls on every rerun.
    """
    last = _SP_FAIL.get(sp_key)
    if last and time.time() - last[0] < _SP_FAIL_RETRY_S:
        wait = int(_SP_FAIL_RETRY_S - (time.time() - last[0]))
        raise RuntimeError(f"{last[1]} (next retry in {wait}s)")
    try:
        result = _fn158d_sharepoint_effective(
            sp_key, fn158b_effective_live_mtimes()[1], key_column)
    except Exception as e:
        _SP_FAIL[sp_key] = (time.time(), str(e)[:300])
        raise
    _SP_FAIL.pop(sp_key, None)
    return result


def fn158b_effective_live_mtimes() -> tuple[int, int]:
    """(base_version, edits_version) — file mtime_ns locally, Neon tokens remotely.

    0 when that side has never been loaded. Both halves may mix (Neon edits +
    local base, or the reverse) when only one ``[parquet] *_path`` override is set.
    """
    def _m(p: Path) -> int:
        try:
            return os.stat(p).st_mtime_ns
        except OSError:
            return 0

    if _fn_neon_base_on():
        from libs.lib_neon import base_version
        base_v = base_version()
    else:
        base_v = _m(fn153_resolve_base_parquet_path())

    if _fn_neon_on():
        from libs.lib_neon import edits_version
        edits_v = edits_version()
    else:
        edits_v = _m(fn154_resolve_edits_parquet_path())
    return base_v, edits_v


def fn154d_edits_version() -> float:
    """Cache key that changes when the edit log changes (file mtime, or Neon version)."""
    if _fn_neon_on():
        from libs.lib_neon import edits_version
        return float(edits_version())
    p = fn154_resolve_edits_parquet_path()
    return p.stat().st_mtime if p.exists() else 0.0


def fn154e_corrections_version() -> float:
    """Same for the correction register — which is now a view over the edit log,
    so it changes exactly when the log does."""
    return fn154d_edits_version()
