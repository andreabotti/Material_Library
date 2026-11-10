"""
libs/lib_revalu_map.py — EETRA MatLib ↔ Revalu field mapping
================================================================
Static registry used by ``pages/13_Add_Edit_Item.py`` to lay out the
add/edit form in categories and to show, next to every EETRA column,
which Revalu API field (if any) it corresponds to.

Source of the Revalu taxonomy: the "Get EPD Extended" endpoint of the
public Revalu API docs (https://docs.revalu.io/ — collection item
5ebbf9cf-ecde-4519-9e0f-305966d49cb7), which is the richest EPD schema
Revalu exposes (id, location, manufacturer, gwp/gwp_fossil/gwp_biogenic/
gwp_luluc, fw, pert, penrt, thickness, density, lambda, u_value, r_value,
declared_unit(_amount), certificates, rsl, tags, cement/concrete fields, …).

Mapping tiers
-------------
"exact"   — same quantity, same (or trivially convertible) unit/meaning.
"related" — same concept but approximate (unit mismatch, combined vs.
            split modules, or EETRA holds more/less detail than Revalu).
None      — no Revalu counterpart in the Get EPD Extended schema
            (EETRA-only field, e.g. CAM/VOC/recycling content — Revalu's
            EPD schema has no recycled-content or VOC attributes today).

Columns excluded entirely from the registry (auto-managed, not user-edited):
``*``/``*.N`` Excel section markers, ``Unnamed: N``, and the local media
cache columns (``U__Img_Local``, ``E__EPD_Local``, ``U__TechDetails_Local``,
``VO__VOC_Local``, ``U__VOC_Local_alt``, ``VO__VOC_Cert_Number``,
``VO__VOC_Cert_Expiry``, ``VO__VOC_Cert_Parse_Status``).

Column prefixes: ``VO__`` = VOC; ``VV__`` = Various (CAM, LEED, MSDS, DOP, …).
Legacy ``V__`` headers are renamed on load via ``apply_sharepoint_v_column_renames``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# ── concept-field map: raw column → aux_10__ui_config.json field_visibility key ─
# Used to tell "missing" (relevant, empty) apart from "not relevant" (hidden
# for this product type at Extended detail level). Fields with no entry here
# are treated as always-relevant — we only know filled vs. missing for them.
CONCEPT_FIELD_MAP: dict[str, str] = {
    "P__Mass_kgm3": "Density",
    "P__Thick_mm": "Thickness",
    "P__L_WmK": "Conductivity (ʎ)",
    "P__U_Wm2K": "U-value",
    # EPD Physical Parameters — same insulation-only n/r greying as Details.
    "E__L_WmK": "Conductivity (ʎ)",
    "E__Rvalue": "U-value",
    "P__FireRating": "Fire rating",
    "E__ServiceLife": "Service Life",
    "R__Reco_Tot_%": "Recycling Rate",
    "R__Rec_Reco_ByProd_%": "Recycling Rate",
    "E__EPD_RegNumber": "EPD Num.",
    "E__EPD_URL": "EPD Num.",
    "D__TechDetails": "Technical Details",
    # U__TechDetails_URL is deliberately NOT mapped — always relevant in Add/Edit
    # (status never shows "Not relevant"), even when the Technical Details text
    # field is hidden for a product type.
    "VO__VOC_Body": "VOC",
    "VO__VOC_Cert": "VOC",
    "VO__VOC_URL": "VOC",
    "VO__VOC_Cert_No": "VOC",
    "D__EN197-1": "EN197-1",
    "S__Comments": "Comments",
    "E__ManuPlant": "Manufacturing Plant",
    "E__ManuCountry": "Manufacturing Plant",
}

# ── EETRA column → (revalu field expression, tier) ───────────────────────────
REVALU_MAP: dict[str, tuple[str, str] | tuple[None, None]] = {
    "0__EETRA_ID": ("id", "related"),
    "0__NUM": (None, None),
    "A__Manufacturer": ("manufacturer", "exact"),
    "A__ProductName": ("name", "exact"),
    "A__ProductDescription": (None, None),
    "A__Map_yn": (None, None),
    "D__ProductType_ENG": (None, None),
    "D__MaterialType_ENG": (None, None),
    "D__MaterialType_ITA": (None, None),
    "D__Int/Ext": (None, None),
    "D__Application": (None, None),
    "D__Content": ("custom_attribute", "related"),
    "D__Size": (None, None),
    "D__TechDetails": ("additional_data", "related"),
    "D__IncludedProducts": (None, None),
    "D__EN197-1": ("cement_type", "related"),
    "D__EN206": ("exposure_class / compressive_strength_standard", "related"),
    "D__DataComments": ("data_quality_warnings", "related"),
    "S__Comments": (None, None),
    "S__Status": (None, None),
    "U__ProductInfo_URL": ("all_documents", "related"),
    "U__TechDetails_URL": ("all_documents", "related"),
    "U__Img_URL": (None, None),
    "P__U_Wm2K": ("u_value", "exact"),
    "P__L_WmK": ("lambda", "exact"),
    "P__Thick_mm": ("thickness (m)", "related"),
    "P__Mass_kgm3": ("gross_density / bulk_density", "exact"),
    "P__Mass_kgm2": ("grammage", "exact"),
    "P__Mass_kg": (None, None),
    "P__FireRating": (None, None),
    "E__ManuCountry": ("location", "related"),
    "E__ManuPlant": ("location", "related"),
    "E__EPD_Y/N": (None, None),
    "E__EPD_Programme": ("source.name", "exact"),
    "E__EPD_URL": ("source.url", "exact"),
    "E__EPD_DecNumber": ("registration_number", "related"),
    "E__EPD_RegNumber": ("registration_number", "exact"),
    "E__EPD_Product Name": ("name", "related"),
    "E__EPD_ExpDate": ("valid_until", "exact"),
    "E__ServiceLife": ("rsl", "exact"),
    "E__EPD_Density": ("gross_density / bulk_density", "related"),
    "E__L_WmK": ("lambda", "related"),
    "E__EPD_Thick_mm": ("thickness (m)", "related"),
    "E__Rvalue": ("r_value", "exact"),
    "E__EPD_MultFactor": ("declared_unit_amount", "related"),
    "E__EPD_ConvFactor": (None, None),
    "E__EPD_kg-FU": ("declared_unit_amount", "related"),
    "G__GWP_Metric": (None, None),
    "G__GWP_FU": ("declared_unit", "exact"),
    "G__GWP_A1A3": ("gwp.a1a3", "exact"),
    "G__GWP_A1A3_kg": ("gwp.a1a3", "related"),
    "G__GWP_A1A3_m2": (None, None),
    "G__GWP_A1A3_m3": (None, None),
    "G__GWP_A1A3_m2R1": (None, None),
    "G__GWP_A1": ("gwp.a1a3 (combined)", "related"),
    "G__GWP_A2": ("gwp.a1a3 (combined)", "related"),
    "G__GWP_A3": ("gwp.a1a3 (combined)", "related"),
    "G__GWP_A4": ("gwp.a4", "exact"),
    "G__GWP_A5": ("gwp.a5", "exact"),
    "G__GWP_B1": ("gwp.b1", "exact"),
    "G__GWP_B2": ("gwp.b2", "exact"),
    "G__GWP_B3": ("gwp.b3", "exact"),
    "G__GWP_B4": ("gwp.b4", "exact"),
    "G__GWP_B5": ("gwp.b5", "exact"),
    "G__GWP_B6": ("gwp.b6", "exact"),
    "G__GWP_B7": ("gwp.b7", "exact"),
    "G__GWP_C1": ("gwp.c1", "exact"),
    "G__GWP_C2": ("gwp.c2", "exact"),
    "G__GWP_C3": ("gwp.c3", "exact"),
    "G__GWP_C4": ("gwp.c4", "exact"),
    "G__GWP_D": ("gwp.d", "exact"),
    "R__Rec_Reco_ByProd_URL": (None, None),
    "R__Rec_Pre_%": (None, None),
    "R__Rec_Post_%": (None, None),
    "R__Rec_Tot_%": (None, None),
    "R__Reco_Tot_%": (None, None),
    "R__ByProd_Tot_%": (None, None),
    "R__Rec_Reco_ByProd_%": (None, None),
    "R__Rec_Cert_No": (None, None),
    "R__Rec_Cert_Scheme": (None, None),
    "R__Rec_Cert_Expiry": (None, None),
    "R__Rec_Cert_Plant": (None, None),
    "VO__Data_Relevant": (None, None),
    "VO__VOC_Body": (None, None),
    "VO__VOC_Cert": ("certificates", "related"),
    "VO__TestStandard": (None, None),
    "VO__ReportType": (None, None),
    "VO__VOC_URL": (None, None),
    "VO__VOC_Cert_No": ("certificates", "related"),
    "VO__Exp_Date": (None, None),
    "VO__TestDate": (None, None),
    "VO__IssueDate": (None, None),
    "VO__LEED_Pathway": (None, None),
    "VO__Chk_TVOC": (None, None),
    "VO__Chk_ISO17025": (None, None),
    "VO__Chk_Scenario": (None, None),
    "VO__Application_Scope": (None, None),
    "VO__Product_Category": (None, None),
    "VV__Other": (None, None),
    "VV__LEED_MR_RawMat": (None, None),
    "VV__MSDS__URL": (None, None),
    "VV__CAM__Status": (None, None),
    "VV__CAM__Evidence": (None, None),
    "VV__CAM_Compliance": (None, None),
    "VV__DOP": (None, None),
    "VV__HPD": (None, None),
    "VV__HPD_URL": (None, None),
    "VV__Declare": (None, None),
    "VV__Declare_URL": (None, None),
    "VV__C2C_MH": (None, None),
    "VV__C2C_MH_URL": (None, None),
    "VV__HealthDecl_Other": (None, None),
    "VV__HealthDecl_Other_URL": (None, None),
}

# ── field widget hints ───────────────────────────────────────────────────────
NUMBER_FIELDS = {
    "0__NUM", "G__GWP_A1A3", "G__GWP_A1A3_kg", "G__GWP_A1A3_m3",
    "R__Rec_Tot_%", "R__Reco_Tot_%",
    "R__ByProd_Tot_%", "R__Rec_Reco_ByProd_%",
}
# Pre/post consumer split is often absent when only a total is published —
# these accept a number or the sentinels ``n/d`` / ``n/a`` (not via number_input).
OPTIONAL_PCT_SENTINEL_FIELDS = frozenset({
    "R__Rec_Pre_%",
    "R__Rec_Post_%",
})
OPTIONAL_PCT_SENTINELS = frozenset({"n/d", "n/a"})
OPTIONAL_PCT_HELP = (
    "Enter a percentage, or n/d (not declared) / n/a when the source only "
    "states a total recycled content without a pre/post split."
)
TEXTAREA_FIELDS = {
    "A__ProductDescription", "D__Content", "D__TechDetails", "D__IncludedProducts",
    "D__DataComments", "S__Comments",
}
TEXTAREA_HEIGHTS: dict[str, int] = {
    "A__ProductDescription": 104,
    "D__Content": 104,
    "D__TechDetails": 104,
    # Compact: usually "n/a" or a short list; resize still available in the browser editor.
    "D__IncludedProducts": 68,
    "D__DataComments": 104,
    # Two text rows (Streamlit min with label_visibility="collapsed").
    "U__ProductInfo_URL": 68,
    "U__TechDetails_URL": 68,
}
DEFAULT_TEXTAREA_HEIGHT = 90
# Local form default when the parquet cell is empty (user can overwrite before save).
INCLUDED_PRODUCTS_DEFAULT = "n/a"
INCLUDED_PRODUCTS_EMPTY = frozenset({
    "", "-", "–", "—", "nan", "none", "<na>", "n/a", "na", "n/r", "nr", "*",
})
READONLY_FIELDS = {"0__EETRA_ID", "0__NUM"}
YN_SELECT_FIELDS = {"A__Map_yn", "E__EPD_Y/N"}
DATE_FIELDS = {
    "E__EPD_ExpDate", "VO__Exp_Date", "VO__TestDate", "VO__IssueDate",
    "R__Rec_Cert_Expiry",
}
URL_FIELDS = {
    "U__ProductInfo_URL", "U__TechDetails_URL", "U__Img_URL",
    "VO__VOC_URL", "VV__MSDS__URL", "VV__DOP", "R__Rec_Reco_ByProd_URL",
    "VV__HPD_URL", "VV__Declare_URL", "VV__C2C_MH_URL", "VV__HealthDecl_Other_URL",
}
CEMENT_CONCRETE_PRODUCT_TYPES = frozenset({
    "Binder (Cement)",
    "In situ Concrete",
    "Grouting",
})
CEMENT_CONCRETE_ONLY_FIELDS = frozenset({"D__EN197-1", "D__EN206"})
OPTION_SELECT_FIELDS = frozenset({
    "D__MaterialType_ENG",
    "E__ManuCountry",
    "E__EPD_Programme",
    "VO__VOC_Cert",
    "VO__LEED_Pathway",
    "VO__VOC_Body",
})

# Who tested or certified the product. Offered ahead of the values already in
# the data (see _field_option_lists in pages/13_Add_Edit_Item.py); a laboratory
# that is not on the list is still typed in through "➕ New body…".
# Scheme owners (GEV, CRI, RAL) and testing laboratories (Eurofins, Intertek)
# share one list because the data does: what matters here is whose name is on
# the document behind VOC Certification.
VOC_BODIES: tuple[str, ...] = (
    "Berkeley Analytical",
    "Benchmark International",
    "Biosafe",
    "Building Information Foundation RTS",
    "Bureau Veritas Laboratoires",
    "Collaborative for High Performance Schools (CHPS)",
    "CRI (Carpet and Rug Institute)",
    "eco-INSTITUT Germany GmbH",
    "Eurofins",
    "GEV",
    "Intertek",
    "NSF International",
    "RAL gGmbH",
    "SCS Global Services",
    "UL Solutions",
    "Manufacturer (in-house)",
    "Other (ISO 17025 lab)",
    "n/a",
    "n/r",
)

# Which LEED v4.1 EQ Low-Emitting Materials pathway the VOC evidence serves.
# Offered ahead of whatever the data already holds (see _field_option_lists in
# pages/13_Add_Edit_Item.py), so the field starts with a vocabulary rather than
# an empty dropdown. One value per product for now; a product needing both
# takes the combined entry.
VOC_LEED_PATHWAYS: tuple[str, ...] = (
    "VOC Emissions",
    "VOC Content",
    "VOC Emissions + VOC Content",
    "Formaldehyde Emissions",
    "Furniture Emissions",
    "Inherently Non-Emitting",
    "n/a",
    "n/r",
)

# ── VOC documentation review checklist ───────────────────────────────────────
# Six controls over the supporting document. Three cannot be answered from the
# data and are stored; the other three are read off fields the row already has,
# so they cannot drift out of step with what they describe.
VOC_CHECKLIST_FIELDS: tuple[str, ...] = (
    "VO__Chk_TVOC",
    "VO__Chk_ISO17025",
    "VO__Chk_Scenario",
)
VOC_CHECKLIST_VALUES: tuple[str, ...] = ("", "Yes", "No", "Unknown", "n/r")

# Manual gate for the VOC emissions block (ceramic tiles, untreated minerals, …).
# Kept out of VOC_FIELDS so a "No" answer can lock the rest without overwriting itself.
VOC_DATA_RELEVANT_FIELD = "VO__Data_Relevant"
VOC_DATA_RELEVANT_VALUES: tuple[str, ...] = ("", "Yes", "No", "Not sure")

# (control, source column, how to read it) — the derived half of the checklist.
VOC_CHECKLIST_DERIVED: tuple[tuple[str, str], ...] = (
    ("Laboratory identified?", "VO__VOC_Body"),
    ("Test date available?", "VO__TestDate"),
    ("VOC Content documented?", "VO__LEED_Pathway"),
)

_CHECKLIST_EMPTY = frozenset({"", "-", "nan", "none", "<na>", "n/a", "na", "*"})


def _checklist_cell(row, col: str) -> str:
    """One cell as plain text, whether *row* is a Series, a dict or the form values."""
    if row is None:
        return ""
    try:
        value = row.get(col)
    except AttributeError:
        value = None
    if value is None:
        return ""
    try:
        import pandas as _pd

        if _pd.isna(value):
            return ""
    except (TypeError, ValueError, ImportError):
        pass
    return str(value).strip()


def voc_checklist_derived(row) -> list[tuple[str, str, str]]:
    """[(control, answer, which field answered it)] for the derived controls.

    ``n/r`` in the source field is carried through rather than read as "No":
    a product that needs no VOC evidence is not missing any.
    """
    out: list[tuple[str, str, str]] = []
    for label, col in VOC_CHECKLIST_DERIVED:
        raw = _checklist_cell(row, col)
        low = raw.lower()
        if low in ("n/r", "nr"):
            answer = "n/r"
        elif low in _CHECKLIST_EMPTY:
            answer = "No" if col != "VO__LEED_Pathway" else "Unknown"
        elif col == "VO__LEED_Pathway":
            answer = "Yes" if "voc content" in low else "No"
        else:
            answer = "Yes"
        out.append((label, answer, FIELD_LABELS.get(col, col)))
    return out


# Physical-property hosts that carry a companion ``{col}_CM`` flag (C/M).
PHYSICAL_PROPERTY_FIELDS: tuple[str, ...] = (
    "P__U_Wm2K", "P__L_WmK", "P__Thick_mm", "P__Mass_kgm3",
    "P__Mass_kgm2", "P__FireRating",
)
# When the P__ value matches this EPD column (within tolerance) → default C.
PHYSICAL_CM_EPD_SOURCE: dict[str, str] = {
    "P__L_WmK": "E__L_WmK",
    "P__Thick_mm": "E__EPD_Thick_mm",
    "P__Mass_kgm3": "E__EPD_Density",
}
PHYSICAL_CM_HELP = (
    "C Calculated (value locked) · M Manually entered (value editable). "
    "Switch C→M to override a calculated figure."
)


def physical_cm_column(host_col: str) -> str:
    return f"{host_col}_CM"


def _physical_cm_num(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = float(value)
        return None if pd.isna(f) else f
    s = str(value).strip().replace(",", ".")
    if not s or s.lower() in ("-", "–", "—", "nan", "none", "<na>", "n/a", "na", "n/r", "nr"):
        return None
    try:
        f = float(s)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _physical_cm_has_value(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    return bool(s) and s.lower() not in ("-", "–", "—", "nan", "none", "<na>", "n/a", "na")


def _physical_cm_close(a: float, b: float, *, rel: float = 0.02) -> bool:
    return abs(a - b) <= abs(a) * rel + 1e-9


def infer_physical_cm(host_col: str, row: dict | None) -> str:
    """Default C/M for a physical-property field: ``C``, ``M``, or ``\"\"``.

    Prefer a stored ``{col}_CM`` when present. Otherwise infer:
    * match to the paired EPD column → C
    * ``P__Mass_kgm2`` ≈ ρ · d → C
    * ``P__U_Wm2K`` ≈ λ / d → C
    * any other non-empty value → M
    """
    row = row or {}
    stored = str(row.get(physical_cm_column(host_col), "") or "").strip().upper()
    if stored in ("C", "M"):
        return stored

    if not _physical_cm_has_value(row.get(host_col)):
        return ""

    # Text ratings are always manual when present.
    if host_col == "P__FireRating":
        return "M"

    val = _physical_cm_num(row.get(host_col))
    epd_col = PHYSICAL_CM_EPD_SOURCE.get(host_col)
    if epd_col and val is not None:
        epd_val = _physical_cm_num(row.get(epd_col))
        if epd_val is not None and _physical_cm_close(val, epd_val):
            return "C"

    if host_col == "P__Mass_kgm2" and val is not None:
        rho = _physical_cm_num(row.get("P__Mass_kgm3"))
        thick = _physical_cm_num(row.get("P__Thick_mm"))
        if rho is not None and thick is not None:
            derived = rho * (thick / 1000.0)
            if _physical_cm_close(val, derived):
                return "C"

    if host_col == "P__U_Wm2K" and val is not None:
        lam = _physical_cm_num(row.get("P__L_WmK"))
        thick = _physical_cm_num(row.get("P__Thick_mm"))
        if lam is not None and thick is not None and thick > 0:
            derived = lam / (thick / 1000.0)
            if _physical_cm_close(val, derived, rel=0.05):
                return "C"

    return "M"


# ── categories (mirrors DATABASE_COLUMNS.md prefixes) ────────────────────────
CATEGORIES: list[dict] = [
    {
        "key": "identity", "label": "Product ID", "icon": "🏷️",
        "field_groups": [
            {
                "fields": [
                    "0__EETRA_ID", "A__Manufacturer", "A__ProductName",
                    "D__ProductType_ENG", "D__MaterialType_ENG",
                ],
                "column_weights": [2.2, 3.5, 4.0, 3.5, 3.5],
            },
            {
                "fields": [
                    "A__ProductDescription",
                    "D__IncludedProducts",
                ],
                "column_weights": [6, 4],
            },
            {
                "fields": [
                    "U__ProductInfo_URL", "U__TechDetails_URL", "U__Img_URL",
                ],
                "columns_per_row": 1,
            },
        ],
        "fields": [
            "0__EETRA_ID", "A__Manufacturer", "A__ProductName",
            "D__ProductType_ENG", "D__MaterialType_ENG",
            "A__ProductDescription", "D__IncludedProducts",
            "U__ProductInfo_URL", "U__TechDetails_URL", "U__Img_URL",
        ],
    },
    {
        "key": "details", "label": "Technical Details", "icon": "📋",
        "field_groups": [
            {
                # D__Int/Ext and D__Application are hidden app-wide
                # (lib_data.HIDDEN_APP_COLUMNS): off the form, so a save never
                # touches their stored values.
                "fields": ["D__Size"],
                "columns_per_row": 3,
            },
            {
                "fields": ["D__Content", "D__TechDetails", "D__DataComments"],
                "columns_per_row": 3,
            },
            {
                "section_title": "Physical properties",
                "section_title_style": "page_title",
                "section_margin_top": "20px",
                "section_divider": True,
                "fields": [
                    "P__Thick_mm", "P__Mass_kgm3",
                    "P__Mass_kgm2", "P__FireRating",
                ],
                "columns_per_row": 4,
                "cm_under_fields": True,
            },
            {
                "fields": [
                    "P__U_Wm2K", "P__L_WmK", "D__EN197-1", "D__EN206",
                ],
                "cm_under_fields": True,
                "cm_pad_slots": 4,
            },
        ],
        "fields": [
            "D__Size",
            "D__Content", "D__TechDetails", "D__DataComments",
            "P__Thick_mm", "P__Mass_kgm3",
            "P__Mass_kgm2", "P__FireRating",
            "P__U_Wm2K", "P__L_WmK",
            "D__EN197-1", "D__EN206",
        ],
    },
    {
        "key": "epd", "label": "EPD - Gen. Data", "icon": "🏭",
        "field_groups": [
            {
                "fields": ["E__ManuCountry", "E__ManuPlant", "E__EPD_Y/N", "E__EPD_Programme"],
                "column_weights": [6, 10, 3, 6],
            },
            {
                "fields": ["E__EPD_DecNumber", "E__EPD_RegNumber", "E__EPD_Product Name", "E__EPD_ExpDate"],
                "columns_per_row": 4,
            },
            {
                "section_title": "EPD Physical Parameters",
                "section_title_style": "page_title",
                "section_margin_top": "20px",
                "section_divider": True,
                "fields": [
                    "E__L_WmK", "E__Rvalue", "E__EPD_Density", "E__EPD_kg-FU", "E__EPD_Thick_mm",
                ],
                "column_weights": [4, 4, 5, 5, 4],
            },
            {
                "fields": ["E__EPD_MultFactor", "E__EPD_ConvFactor"],
                "columns_per_row": 2,
            },
            {
                "fields": ["E__EPD_URL", "E__ServiceLife"],
                "columns_per_row": 2,
            },
        ],
        "fields": [
            "E__ManuCountry", "E__ManuPlant", "E__EPD_Y/N",
            "E__EPD_Programme", "E__EPD_DecNumber", "E__EPD_RegNumber",
            "E__EPD_Product Name", "E__EPD_ExpDate",
            "E__L_WmK", "E__Rvalue", "E__EPD_Density", "E__EPD_kg-FU", "E__EPD_Thick_mm",
            "E__EPD_MultFactor", "E__EPD_ConvFactor",
            "E__EPD_URL", "E__ServiceLife",
        ],
    },
    {
        "key": "gwp", "label": "EPD - GWP Data", "icon": "🌍",
        "field_groups": [
            {
                "fields": ["G__GWP_Metric", "G__GWP_FU", "G__GWP_A1A3", "G__GWP_A1A3_kg",
                           "G__GWP_A1A3_m2", "G__GWP_A1A3_m3", "G__GWP_A1A3_m2R1"],
                "columns_per_row": 7,
            },
            {
                "fields": ["G__GWP_A1", "G__GWP_A2", "G__GWP_A3", "G__GWP_A4", "G__GWP_A5"],
                "pad_slots": 7,
                "slot_width_scale": 0.75,
            },
            {
                "fields": ["G__GWP_B1", "G__GWP_B2", "G__GWP_B3", "G__GWP_B4", "G__GWP_B5",
                           "G__GWP_B6", "G__GWP_B7"],
                "pad_slots": 7,
                "slot_width_scale": 0.75,
            },
            {
                "fields": ["G__GWP_C1", "G__GWP_C2", "G__GWP_C3", "G__GWP_C4", "G__GWP_D"],
                "pad_slots": 7,
                "slot_width_scale": 0.75,
            },
        ],
        "fields": ["G__GWP_Metric", "G__GWP_FU", "G__GWP_A1A3", "G__GWP_A1A3_kg",
                   "G__GWP_A1A3_m2", "G__GWP_A1A3_m3", "G__GWP_A1A3_m2R1",
                   "G__GWP_A1", "G__GWP_A2", "G__GWP_A3", "G__GWP_A4", "G__GWP_A5",
                   "G__GWP_B1", "G__GWP_B2", "G__GWP_B3", "G__GWP_B4", "G__GWP_B5",
                   "G__GWP_B6", "G__GWP_B7", "G__GWP_C1", "G__GWP_C2", "G__GWP_C3",
                   "G__GWP_C4", "G__GWP_D"],
    },
    {
        "key": "recycling", "label": "Recycling & EOL", "icon": "♻️",
        "field_groups": [
            {
                "fields": ["R__Rec_Pre_%", "R__Rec_Post_%", "R__Rec_Tot_%", "R__Reco_Tot_%",
                           "R__ByProd_Tot_%", "R__Rec_Reco_ByProd_%"],
                "columns_per_row": 6,
            },
            {
                "fields": ["R__Rec_Reco_ByProd_URL"],
                "columns_per_row": 1,
            },
            {
                # Certificate behind the recycled-content claim (ICMQ, Remade, EPD …)
                "fields": ["R__Rec_Cert_No", "R__Rec_Cert_Scheme", "R__Rec_Cert_Expiry"],
                "columns_per_row": 3,
            },
            {
                "fields": ["R__Rec_Cert_Plant"],
                "columns_per_row": 1,
            },
        ],
        "fields": ["R__Rec_Pre_%", "R__Rec_Post_%", "R__Rec_Tot_%", "R__Reco_Tot_%",
                   "R__ByProd_Tot_%", "R__Rec_Reco_ByProd_%", "R__Rec_Reco_ByProd_URL",
                   "R__Rec_Cert_No", "R__Rec_Cert_Scheme", "R__Rec_Cert_Expiry",
                   "R__Rec_Cert_Plant"],
    },
    {
        # Health: VOC emissions plus material-health declarations (HPD, Declare,
        # C2C Material Health, …) and the safety data sheet. Key stays "vo" so
        # session state / summary logic keyed on it keeps working.
        "key": "vo", "label": "Health", "icon": "🌿",
        "field_groups": [
            {
                "section_title": "VOC emissions",
                "section_title_style": "page_title",
                # Manual Yes/No/Not sure gate — own group so it stays editable when
                # the remaining VOC fields swap to the locked n/r panel.
                "fields": ["VO__Data_Relevant"],
                "columns_per_row": 3,
            },
            {
                "fields": ["VO__VOC_Cert", "VO__VOC_Cert_No", "VO__VOC_Body",
                           "VO__ReportType", "VO__TestStandard"],
                "columns_per_row": 5,
                # Under the row: how the chosen claim reads against LEED v4.1,
                # WELL v2 and CAM 2025 (aux_12__voc_rating_alignment.json).
                "rating_alignment": True,
            },
            {
                "section_title": "Documentation review",
                "section_margin_top": "16px",
                "fields": ["VO__Chk_TVOC", "VO__Chk_ISO17025", "VO__Chk_Scenario"],
                "columns_per_row": 3,
                "derived_checklist": True,
            },
            {
                # Traceability: when the lab tested it, when the certificate was
                # issued, when it expires, and which LEED pathway it serves. The
                # three dates sit together so a gap in the chain is visible.
                "fields": ["VO__TestDate", "VO__IssueDate", "VO__Exp_Date", "VO__LEED_Pathway"],
                "columns_per_row": 4,
            },
            {
                "fields": ["VO__VOC_URL"],
                "columns_per_row": 1,
            },
            {
                "section_title": "Health declarations",
                "section_title_style": "page_title",
                "section_margin_top": "20px",
                "section_divider": True,
                "fields": ["VV__HPD", "VV__Declare", "VV__C2C_MH", "VV__HealthDecl_Other"],
                "columns_per_row": 4,
            },
            {
                "fields": ["VV__HPD_URL", "VV__Declare_URL", "VV__C2C_MH_URL", "VV__HealthDecl_Other_URL"],
                "columns_per_row": 4,
            },
            {
                "fields": ["VV__MSDS__URL"],
                "columns_per_row": 1,
            },
        ],
        # VO__Product_Category and VO__Application_Scope stay hidden app-wide as
        # uninformative: off the form, so a save never touches their stored
        # values, and out of the Catalogue VOC line. The columns stay in the
        # data and the Revalu export. VO__VOC_Body was hidden with them while it
        # held free prose; it is now the testing / certifying body, on a
        # vocabulary (VOC_BODIES), and back on the form. It is still off the
        # Catalogue VOC line (aux_10__ui_config.json) — the card shows the claim,
        # not who issued it.
        "fields": [
            "VO__Data_Relevant",
            "VO__VOC_Cert",
            "VO__VOC_Cert_No",
            "VO__VOC_Body",
            "VO__Exp_Date",
            "VO__TestDate",
            "VO__IssueDate",
            "VO__LEED_Pathway",
            "VO__Chk_TVOC",
            "VO__Chk_ISO17025",
            "VO__Chk_Scenario",
            "VO__TestStandard",
            "VO__ReportType",
            "VO__VOC_URL",
            "VV__HPD", "VV__Declare", "VV__C2C_MH", "VV__HealthDecl_Other",
            "VV__HPD_URL", "VV__Declare_URL", "VV__C2C_MH_URL", "VV__HealthDecl_Other_URL",
            "VV__MSDS__URL",
        ],
    },
    {
        "key": "vv", "label": "Various", "icon": "📎",
        "bottom_fields": ["VV__DOP"],
        "bottom_columns_per_row": 1,
        "fields": [
            "VV__Other", "VV__LEED_MR_RawMat", "VV__CAM__Status",
            "VV__CAM__Evidence", "VV__CAM_Compliance",
            "VV__DOP",
        ],
    },
    {
        "key": "comments", "label": "Comments", "icon": "💬",
        "fields": ["S__Comments", "S__Status"],
    },
]


# ── VOC relevance by product type ────────────────────────────────────────────
# Product types with no organic-emission pathway: cementitious, mineral or
# metallic goods that cannot carry an indoor-air / VOC emission certificate.
# For these the whole VOC category is *not relevant* rather than merely empty —
# every ``VO__`` field reads ``n/r``, the VOC fields of the Add/Edit Health tab are locked, and the
# Summary matrix greys the VOC row out instead of counting nine missing fields.
#
# Rule for adding a type here: NO product in the category can ever hold an
# emission certificate. Types where *some* products do must stay out — Metal
# accessories, Building fasteners and Structural components all hold real
# LEED / AgBB / French A+ certificates in the dataset and are deliberately absent.
#
# 04_tools/03_excel_to_parquet.py keeps a separate ``_PRODUCT_TYPES_NO_VOC``.
# That set answers "don't chase a certificate PDF for this row"; this one
# answers "the field does not apply to this product". They overlap but are not
# the same question, so they are not merged.
VOC_NOT_RELEVANT_PRODUCT_TYPES = frozenset({
    # Cementitious / mineral binders and mixes
    "In situ Concrete",
    "Binder (Cement)",
    "Cement",
    "Paving",
    # Structural steel
    "Rebar",
    "Coil",
    # Metal carriers and framing (no exposed organic surface)
    "Cable trays",
    "Framing profiles (Cladding/stud frame)",
    "Structural accessories",
})

# Marker written into every VOC field for the product types above. Matches the
# ``n/r`` already entered by hand in the source Excel for most of these rows.
VOC_NOT_RELEVANT_VALUE = "n/r"

# The VOC fields of the Health category (its VO__ columns), excluding the
# manual relevance gate. Health declarations and the MSDS share the tab but
# stay editable for every product type.
VOC_FIELDS: tuple[str, ...] = tuple(
    f for f in next(cat for cat in CATEGORIES if cat["key"] == "vo")["fields"]
    if f.startswith("VO__") and f != VOC_DATA_RELEVANT_FIELD
)

# When VOC Certification is ``n/r``, these dependent fields are forced to ``n/r``
# and greyed out (certificate number / expiry do not apply without a certificate).
VOC_CERT_NR_LOCK_FIELDS = frozenset({
    "VO__VOC_Cert_No", "VO__Exp_Date", "VO__TestDate", "VO__IssueDate",
    "VO__LEED_Pathway", "VO__VOC_Body",
    "VO__Chk_TVOC", "VO__Chk_ISO17025", "VO__Chk_Scenario",
})


def voc_cert_is_not_relevant(cert_value) -> bool:
    """True when *cert_value* is the catalog ``n/r`` choice (label or short form)."""
    s = str(cert_value or "").strip().lower().replace("\\", "/")
    if not s:
        return False
    return s == "n/r" or s == "nr" or s.startswith("n/r ") or s.startswith("nr ")


def voc_data_is_not_relevant(data_relevant) -> bool:
    """True when VOC Data Relevant is the manual ``No`` choice."""
    return str(data_relevant or "").strip().lower() == "no"


def voc_not_relevant(product_type: str | None) -> bool:
    """True when the VOC category does not apply to *product_type* at all."""
    return str(product_type or "").strip() in VOC_NOT_RELEVANT_PRODUCT_TYPES


def voc_emissions_locked(
    product_type: str | None = None,
    *,
    data_relevant=None,
) -> bool:
    """True when every VOC emissions field (except Data Relevant) is fixed at n/r."""
    return voc_not_relevant(product_type) or voc_data_is_not_relevant(data_relevant)


# ── friendly labels (fn128_clean_column_name mangles camelCase single-word
# columns like "ProductName" → "Productname"; override those here) ──────────
FIELD_LABELS: dict[str, str] = {
    "0__EETRA_ID": "EETRA ID",
    "0__NUM": "Sequence No.",
    "A__Manufacturer": "Manufacturer",
    "A__ProductName": "Product Name",
    "A__ProductDescription": "Product Description",
    "A__Map_yn": "Show on Maps (Y/N)",
    "D__ProductType_ENG": "Product Type",
    "D__MaterialType_ENG": "Material Type (English)",
    "D__MaterialType_ITA": "Material Type (Italian)",
    "D__Int/Ext": "Interior / Exterior",
    "D__Application": "Application",
    "D__Content": "Content / Composition",
    "D__Size": "Size",
    "D__TechDetails": "Technical Details",
    "D__IncludedProducts": "Included products / collections",
    "D__EN197-1": "Cement Designation (EN 197-1)",
    "D__EN206": "Concrete Class (EN 206)",
    "D__DataComments": "Data Comments",
    "S__Comments": "Comments",
    "S__Status": "Status",
    "U__ProductInfo_URL": "Product Info URL",
    "U__TechDetails_URL": "Technical Details URL",
    "U__Img_URL": "Image URL",
    "P__U_Wm2K": "U-value (W/m²K)",
    "P__L_WmK": "Conductivity λ (W/mK)",
    "P__Thick_mm": "Thickness (mm)",
    "P__Mass_kgm3": "Vol. Density (kg/m³)",
    "P__Mass_kgm2": "Sup. Density (kg/m²)",
    "P__FireRating": "Fire Rating",
    "E__ManuCountry": "Manufacturing Country",
    "E__ManuPlant": "Manufacturing Plant",
    "E__EPD_Y/N": "Has EPD (Y/N)",
    "E__EPD_Programme": "EPD Programme",
    "E__EPD_URL": "EPD URL",
    "E__EPD_DecNumber": "EPD Declaration Number",
    "E__EPD_RegNumber": "EPD Registration Number",
    "E__EPD_Product Name": "EPD Product Name",
    "E__EPD_ExpDate": "EPD Expiry Date",
    "E__ServiceLife": "Service Life",
    "E__EPD_Density": "EPD Density",
    "E__L_WmK": "EPD Conductivity λ (W/mK)",
    "E__EPD_Thick_mm": "EPD Thickness (mm)",
    "E__Rvalue": "R-value",
    "E__EPD_MultFactor": "EPD Multiplication Factor",
    "E__EPD_ConvFactor": "EPD Reference Product (Y/N)",
    "E__EPD_kg-FU": "EPD kg per Functional Unit",
    "G__GWP_Metric": "GWP Metric",
    "G__GWP_FU": "GWP FU/DU",
    "G__GWP_A1A3": "GWP A1-A3 (FU/DU)",
    "G__GWP_A1A3_kg": "GWP A1-A3 (per kg)",
    "G__GWP_A1A3_m2": "GWP A1-A3 (per m²)",
    "G__GWP_A1A3_m3": "GWP A1-A3 (per m³)",
    "G__GWP_A1A3_m2R1": "GWP A1-A3 (per m², R=1)",
    "G__GWP_A1": "GWP A1", "G__GWP_A2": "GWP A2", "G__GWP_A3": "GWP A3",
    "G__GWP_A4": "GWP A4", "G__GWP_A5": "GWP A5",
    "G__GWP_B1": "GWP B1", "G__GWP_B2": "GWP B2", "G__GWP_B3": "GWP B3",
    "G__GWP_B4": "GWP B4", "G__GWP_B5": "GWP B5", "G__GWP_B6": "GWP B6", "G__GWP_B7": "GWP B7",
    "G__GWP_C1": "GWP C1", "G__GWP_C2": "GWP C2", "G__GWP_C3": "GWP C3", "G__GWP_C4": "GWP C4",
    "G__GWP_D": "GWP D (benefits/loads)",
    "R__Rec_Reco_ByProd_URL": "Recycling Evidence URL",
    "R__Rec_Pre_%": "Rec. Content - Pre-C. (%)",
    "R__Rec_Post_%": "Rec. Content - Post-C. (%)",
    "R__Rec_Tot_%": "Rec. Content — Total (%)",
    "R__Reco_Tot_%": "Recyclability - Total (%)",
    "R__ByProd_Tot_%": "By-products / Recovery (%)",
    "R__Rec_Reco_ByProd_%": "Rec.+ Recovered (Combined %)",
    "R__Rec_Cert_No": "Rec. Cert. No.",
    "R__Rec_Cert_Scheme": "Rec. Cert. System",
    "R__Rec_Cert_Expiry": "Rec. Cert. Expiry",
    "R__Rec_Cert_Plant": "Rec. Cert. Production Unit",
    "VO__Data_Relevant": "VOC Data Relevant",
    "VO__VOC_Body": "VOC Testing / Certifying Body",
    "VO__VOC_Cert": "VOC Certification",
    "VO__TestStandard": "VOC Test Standard",
    "VO__ReportType": "VOC Report Type",
    "VO__VOC_URL": "VOC Document URL",
    "VO__VOC_Cert_No": "VOC Certificate Number",
    "VO__Exp_Date": "VOC Certificate Expiry Date",
    "VO__TestDate": "VOC Test Date",
    "VO__IssueDate": "VOC Certificate Issue Date",
    "VO__LEED_Pathway": "LEED Low-Emitting Pathway",
    "VO__Chk_TVOC": "TVOC stated?",
    "VO__Chk_ISO17025": "ISO 17025 scope verified?",
    "VO__Chk_Scenario": "Required scenario documented?",
    "VO__Application_Scope": "VOC Application Scope",
    "VO__Product_Category": "VOC Product Category",
    "VV__Other": "Other Notes",
    "VV__LEED_MR_RawMat": "LEED MR — Raw Materials",
    "VV__MSDS__URL": "Safety Data Sheet (MSDS) URL",
    "VV__CAM__Status": "CAM 2025 Status",
    "VV__CAM__Evidence": "CAM 2025 Evidence",
    "VV__CAM_Compliance": "CAM 2025 Compliance",
    "VV__DOP": "Declaration of Performance (DOP)",
    "VV__HPD": "HPD (Health Product Declaration)",
    "VV__HPD_URL": "HPD URL",
    "VV__Declare": "Declare Label",
    "VV__Declare_URL": "Declare URL",
    "VV__C2C_MH": "C2C Material Health",
    "VV__C2C_MH_URL": "C2C Material Health URL",
    "VV__HealthDecl_Other": "Other Health Declaration",
    "VV__HealthDecl_Other_URL": "Other Health Declaration URL",
}

FIELD_HELP: dict[str, str] = {
    "E__EPD_ConvFactor": (
        "Y = the EPD's reference product (multiplication factor 1): its GWP data are the "
        "values printed in the EPD. N = another product covered by the same EPD: its GWP "
        "data are the reference's × EPD Multiplication Factor, filled in automatically. "
        "Products are matched on EPD Registration Number."
    ),
    "E__EPD_MultFactor": (
        "Factor the EPD gives to scale the reference product's results to this product. "
        "1 (or blank) on the reference product."
    ),
    "G__GWP_FU": "FU: Functional Unit · DU: Declared unit.",
    "VO__Data_Relevant": (
        "Does this product need VOC emission / content evidence? Choose No for "
        "inherently non-emitting mineral products (e.g. untreated ceramic tiles) "
        "that LEED treats as non-emissive without further testing — all other VOC "
        "fields then lock to n/r. Yes = fill the claim and documentation; "
        "Not sure = leave fields editable until confirmed."
    ),
    "VO__VOC_Body": (
        "Whose name is on the document behind the VOC claim: the testing "
        "laboratory, or the body that runs the scheme and awarded the "
        "certificate. Use Manufacturer (in-house) for a self-declaration and "
        "Other (ISO 17025 lab) for an accredited lab that is not on the list."
    ),
    "VO__Chk_TVOC": (
        "Does the document state a TVOC result, not only a pass against a "
        "scheme? A certificate that says only “compliant” cannot be "
        "checked against another project's threshold."
    ),
    "VO__Chk_ISO17025": (
        "Has the testing laboratory's ISO 17025 accreditation been checked, and "
        "does its scope actually cover this test method? Accreditation is per "
        "method, so a lab can be accredited and still out of scope."
    ),
    "VO__Chk_Scenario": (
        "Does the report name the exposure scenario behind the result (CDPH "
        "classroom or private office, EN 16516 reference room) and the loading "
        "factor used? Without it the concentrations cannot be compared."
    ),
    "VO__TestDate": (
        "Date the laboratory ran the emission test, as printed on the test report — "
        "not the date the certificate was issued. Chamber results age, so a scheme "
        "certificate can be current while the testing behind it is not."
    ),
    "VO__IssueDate": (
        "Date the certificate or declaration was issued, completing the chain "
        "test date → issue date → expiry date."
    ),
    "VO__LEED_Pathway": (
        "Which LEED v4.1 EQ Low-Emitting Materials pathway this evidence serves. "
        "Emissions = chamber testing (CDPH / EN 16516); Content = VOC g/L limits for "
        "wet-applied products; Inherently Non-Emitting = unfinished inorganic "
        "materials that need no testing."
    ),
    "G__GWP_A1A3": "GWP A1–A3 per functional / declared unit (see GWP FU/DU).",
    "G__GWP_A1A3_m2R1": (
        "GWP A1–A3 per m² normalised to thermal resistance R = 1 m²·K/W. "
        "Use this to compare insulation products on insulating performance rather than "
        "declared thickness alone — equivalent GWP per unit of thermal efficacy."
    ),
    "D__IncludedProducts": (
        "Commercial products or collections whose sustainability data are covered "
        "by this MatLib entry (typical for plant-/family-level EPDs such as Marazzi). "
        "One name per line (semicolon also accepted). Names are searchable in the Catalogue. "
        "Defaults to n/a when empty — overwrite with the list when the EPD covers a family."
    ),
    "R__Rec_Pre_%": OPTIONAL_PCT_HELP,
    "R__Rec_Post_%": OPTIONAL_PCT_HELP,
    "VO__VOC_Cert": (
        "Select a third-party ecolabel, regulatory label, rating-system attestation, "
        "self-declaration, or status (n/a / n/r). Clarifications come from "
        "aux_11__voc_certifications.json."
    ),
    "VV__HPD": (
        "HPD Open Standard version and disclosure threshold, e.g. "
        "'HPD v2.3 — 100 ppm, fully disclosed'. Use n/a if none is published."
    ),
    "VV__Declare": (
        "Declare (ILFI) label status: Red List Free, Red List Approved, LBC Compliant "
        "or Declared — add the label ID if shown. Use n/a if none is published."
    ),
    "VV__C2C_MH": (
        "Cradle to Cradle Certified Material Health level (Bronze/Silver/Gold/Platinum) "
        "or Material Health Certificate. Use n/a if none."
    ),
    "VV__HealthDecl_Other": (
        "Any other material-health disclosure: manufacturer inventory, REACH SVHC "
        "statement, GreenScreen, Pharos, ToxFree, etc."
    ),
}


# ── VOC certification catalog (aux_11__voc_certifications.json) ─────────────────
_VOC_CERT_JSON = Path(__file__).resolve().parent.parent / "aux_11__voc_certifications.json"
_VOC_CERT_MEMO: dict = {"mtime": None, "data": {}}


def fn_load_voc_certifications() -> dict:
    """Read ``aux_11__voc_certifications.json`` (mtime-memoized)."""
    import json
    import os

    try:
        mtime = os.stat(_VOC_CERT_JSON).st_mtime_ns
        if _VOC_CERT_MEMO["mtime"] != mtime:
            with open(_VOC_CERT_JSON, "r", encoding="utf-8") as f:
                _VOC_CERT_MEMO["data"] = json.load(f)
            _VOC_CERT_MEMO["mtime"] = mtime
        return _VOC_CERT_MEMO["data"] or {}
    except Exception:
        return {}


_VOC_ALIGN_JSON = Path(__file__).resolve().parent.parent / "aux_12__voc_rating_alignment.json"
_VOC_ALIGN_MEMO: dict = {"mtime": None, "data": None}


def fn_load_voc_rating_alignment() -> dict:
    """Read ``aux_12__voc_rating_alignment.json`` (mtime-memoized).

    How each VOC claim lines up with LEED v4.1 EQ Low-Emitting Materials,
    WELL v2 X06 and CAM edilizia 2025 criterio 2.4.1.
    """
    import json
    import os

    try:
        mtime = os.stat(_VOC_ALIGN_JSON).st_mtime_ns
        if _VOC_ALIGN_MEMO["mtime"] != mtime:
            with open(_VOC_ALIGN_JSON, "r", encoding="utf-8") as f:
                _VOC_ALIGN_MEMO["data"] = json.load(f)
            _VOC_ALIGN_MEMO["mtime"] = mtime
        return _VOC_ALIGN_MEMO["data"] or {}
    except Exception:
        return {}


def voc_rating_frameworks() -> list[dict]:
    """The schemes the VOC claims are read against, in file order."""
    data = fn_load_voc_rating_alignment()
    return [f for f in (data.get("frameworks") or []) if isinstance(f, dict)]


def voc_cert_alignment(label: str | None) -> list[dict]:
    """[{id, short, label, credit, url, status, note}] for one VOC claim.

    Resolved through the catalog, so an alias ("IAC Gold") answers like the
    canonical label. An unknown claim comes back with status ``unknown``.
    """
    frameworks = voc_rating_frameworks()
    if not frameworks:
        return []
    entry = voc_cert_by_label(label)
    by_cert = (fn_load_voc_rating_alignment().get("alignment") or {})
    hit = by_cert.get(str(entry.get("id") or "")) if entry else None
    out: list[dict] = []
    for fw in frameworks:
        pair = (hit or {}).get(fw.get("id")) or []
        status = str(pair[0]) if pair else ("unknown" if entry is None else "no")
        note = str(pair[1]) if len(pair) > 1 else ""
        out.append({
            "id": str(fw.get("id") or ""),
            "short": str(fw.get("short") or ""),
            "label": str(fw.get("label") or ""),
            "credit": str(fw.get("credit") or ""),
            "url": str(fw.get("url") or ""),
            "status": status,
            "note": note,
        })
    return out


def voc_alignment_lookup() -> dict[str, list[dict]]:
    """{lowercased label or alias: alignment} — for the browser-side editor."""
    out: dict[str, list[dict]] = {}
    for entry in voc_cert_entries():
        align = voc_cert_alignment(entry.get("label"))
        if not align:
            continue
        for phrase in [entry.get("label"), *(entry.get("aliases") or [])]:
            key = str(phrase or "").strip().lower()
            if key:
                out[key] = align
    return out


def voc_cert_tiers() -> list[dict]:
    """Tier blocks from the VOC catalog (each has ``label`` + ``entries``)."""
    data = fn_load_voc_certifications()
    tiers = data.get("tiers") or []
    return [t for t in tiers if isinstance(t, dict)]


def voc_cert_entries() -> list[dict]:
    """Flat list of catalog entries (``id``, ``label``, ``description``, …)."""
    out: list[dict] = []
    for tier in voc_cert_tiers():
        tier_label = str(tier.get("label") or "").strip()
        for entry in tier.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            row = dict(entry)
            row["tier"] = tier_label
            row["tier_id"] = str(tier.get("id") or "").strip()
            out.append(row)
    return out


def voc_cert_labels() -> list[str]:
    """Canonical dropdown labels in catalog order (tiers then entries)."""
    return [str(e["label"]) for e in voc_cert_entries()]


def voc_cert_by_label(label: str | None) -> dict | None:
    """Resolve a catalog entry by canonical label or any alias (case-insensitive)."""
    needle = str(label or "").strip()
    if not needle:
        return None
    low = needle.lower()
    for entry in voc_cert_entries():
        if str(entry.get("label") or "").strip().lower() == low:
            return entry
        for alias in entry.get("aliases") or []:
            if str(alias).strip().lower() == low:
                return entry
    return None


def voc_cert_clarification(label: str | None) -> str:
    """Human-readable clarification for a VOC cert / status value, or empty string."""
    entry = voc_cert_by_label(label)
    if not entry:
        return ""
    bits = [str(entry.get("description") or "").strip()]
    hint = str(entry.get("cert_number_hint") or "").strip()
    if hint:
        bits.append(hint)
    return " ".join(b for b in bits if b)


def voc_cert_caveat() -> str:
    return str(fn_load_voc_certifications().get("caveat") or "").strip()



def label_for(col: str, column_display_labels: dict | None = None) -> str:
    """
    Display label for a raw column name.

    English is resolved first (FIELD_LABELS → ``column_display_labels`` →
    ``fn128_clean_column_name``); ``libs.lib_i18n.fn703`` then substitutes the
    active language's translation when ``aux_16__translations.json`` has one.
    """
    label = ""
    if col in FIELD_LABELS:
        label = FIELD_LABELS[col]
    else:
        column_display_labels = column_display_labels or {}
        if col in column_display_labels:
            label = str(column_display_labels[col]).strip()
    if not label:
        from libs.lib_data import fn128_clean_column_name
        label = fn128_clean_column_name(col)
    try:
        from libs.lib_i18n import fn703_translate_field
        return fn703_translate_field(col, label)
    except Exception:
        return label


def help_for(col: str) -> str | None:
    return FIELD_HELP.get(col)


def widget_help_kwargs(col: str) -> dict:
    h = help_for(col)
    return {"help": h} if h else {}


def textarea_height(col: str) -> int:
    return TEXTAREA_HEIGHTS.get(col, DEFAULT_TEXTAREA_HEIGHT)


def included_products_display(value) -> str:
    """Form display for ``D__IncludedProducts``: empty cells → ``n/a`` (local draft)."""
    if value is None:
        return INCLUDED_PRODUCTS_DEFAULT
    try:
        if pd.isna(value):
            return INCLUDED_PRODUCTS_DEFAULT
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if s.lower() in INCLUDED_PRODUCTS_EMPTY:
        return INCLUDED_PRODUCTS_DEFAULT
    return str(value)


def field_disabled_for_product_type(
    col: str,
    product_type: str,
    *,
    voc_cert=None,
    data_relevant=None,
) -> bool:
    """Grey out fields that do not apply to the current product type / VOC cert."""
    # Whole VOC emissions block is locked for cementitious / metallic product
    # types, or when VOC Data Relevant is manually set to No.
    if col in VOC_FIELDS and voc_emissions_locked(
        product_type, data_relevant=data_relevant
    ):
        return True
    if col in VOC_CERT_NR_LOCK_FIELDS and voc_cert_is_not_relevant(voc_cert):
        return True
    # aux_10__ui_config.json field_visibility (Extended): Conductivity, U-value,
    # EN197-1, etc. — same n/r + grey treatment as Cement Designation.
    if col in CONCEPT_FIELD_MAP and field_relevance(
        col, product_type, voc_cert=voc_cert, data_relevant=data_relevant
    ) == "not_relevant":
        return True
    if col not in CEMENT_CONCRETE_ONLY_FIELDS:
        return False
    pt = str(product_type or "").strip()
    if pt in CEMENT_CONCRETE_PRODUCT_TYPES:
        return False
    low = pt.lower()
    return not any(token in low for token in ("concrete", "grouting", "cement"))


def field_relevance(
    col: str,
    product_type: str,
    *,
    voc_cert=None,
    data_relevant=None,
) -> str:
    """Return "relevant", "not_relevant", or "unknown" (always-relevant / no rule)."""
    # Product-type / Data Relevant rules win over aux_10__ui_config.json, which
    # only carries a single "VOC" concept flag covering four of the VO__ fields.
    if col in VOC_FIELDS and voc_emissions_locked(
        product_type, data_relevant=data_relevant
    ):
        return "not_relevant"
    if col in VOC_CERT_NR_LOCK_FIELDS and voc_cert_is_not_relevant(voc_cert):
        return "not_relevant"
    # Technical Details URL is always editable / countable — never "Not relevant".
    if col == "U__TechDetails_URL":
        return "relevant"
    concept = CONCEPT_FIELD_MAP.get(col)
    if concept is None:
        return "unknown"
    try:
        from libs.lib_ui import fn317_get_field_visibility
        vis = fn317_get_field_visibility(product_type, detail_level="Extended")
    except Exception:
        return "unknown"
    if not isinstance(vis, dict) or concept not in vis:
        return "unknown"
    return "relevant" if vis[concept] else "not_relevant"


_NUMERIC_EMPTY_TOKENS = frozenset({
    "", "-", "–", "—", "nan", "none", "<na>", "n/a", "na", "n/r", "nr",
})


def _numeric_value_for_status(value) -> float | None:
    """Match Add/Edit ``number_input`` empty handling (``n/a`` in parquet → empty)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = float(value)
        return None if pd.isna(f) else f
    s = str(value).strip()
    if s.lower() in _NUMERIC_EMPTY_TOKENS:
        return None
    try:
        f = float(s.replace(",", "."))
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def normalize_optional_pct(value) -> str:
    """Canonical form for optional % fields: number string, ``n/d``, ``n/a``, or ``""``."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "-", "–", "—", "<na>"):
        return ""
    low = s.lower().replace(" ", "")
    if low in ("n/d", "nd", "notdeclared", "not_declared"):
        return "n/d"
    if low in ("n/a", "na", "n/r", "nr"):
        return "n/a"
    try:
        f = float(s.replace(",", "."))
        if pd.isna(f):
            return ""
        # Trim trailing zeros for a clean percentage display.
        out = f"{f:.4f}".rstrip("0").rstrip(".")
        return out
    except (TypeError, ValueError):
        return s


def field_status(
    col: str,
    value,
    product_type: str,
    *,
    voc_cert=None,
    data_relevant=None,
) -> str:
    """Return "filled", "missing", or "not_relevant" for one field's current value."""
    if field_relevance(
        col, product_type, voc_cert=voc_cert, data_relevant=data_relevant
    ) == "not_relevant":
        return "not_relevant"
    if col in OPTIONAL_PCT_SENTINEL_FIELDS:
        norm = normalize_optional_pct(value)
        if not norm:
            return "missing"
        if norm.lower() in OPTIONAL_PCT_SENTINELS:
            return "filled"
        return "filled" if _numeric_value_for_status(norm) is not None else "missing"
    if col in NUMBER_FIELDS:
        return "filled" if _numeric_value_for_status(value) is not None else "missing"
    has_value = value is not None and str(value).strip() not in ("", "-", "nan", "None", "<NA>")
    return "filled" if has_value else "missing"


_STATUS_STYLE = {
    "filled": ("#16a34a", "● Filled"),
    "missing": ("#d97706", "● Missing"),
    "not_relevant": ("#9ca3af", "● Not relevant"),
}

_STATUS_RECT_COLORS = {
    "filled": "#16a34a",
    "missing": "#d97706",
    "not_relevant": "#9ca3af",
}


def status_rect_cell_style(status: str) -> str:
    """Inline CSS for Add/Edit Summary matrix cells (missing = hollow rectangle)."""
    border_gap = "2px solid #fff"
    if status == "filled":
        return f"background:{_STATUS_RECT_COLORS['filled']};border:{border_gap};"
    if status == "missing":
        return (
            f"background:#fff;border:2px solid {_STATUS_RECT_COLORS['missing']};"
            f"box-shadow:inset 0 0 0 1px #fff;"
        )
    return f"background:{_STATUS_RECT_COLORS['not_relevant']};border:{border_gap};"


def status_badge_html(status: str) -> str:
    color, text = _STATUS_STYLE.get(status, _STATUS_STYLE["missing"])
    return f'<span style="color:{color};font-weight:600;">{text}</span>'


def revalu_r_badge_html() -> str:
    """White bold R in Revalu violet circle — colour from ``palette.revalu_violet``."""
    try:
        from libs.lib_tokens import token
        violet = token("palette", "revalu_violet", "#8c66e0")
    except Exception:
        violet = "#8c66e0"
    return (
        f'<span class="revalu-r-badge" title="Revalu" '
        f'style="display:inline-flex;align-items:center;justify-content:center;'
        f'width:16px;height:16px;min-width:16px;border-radius:50%;'
        f'background:{violet};color:#fff;font-weight:700;line-height:1;'
        f'flex-shrink:0;vertical-align:middle;">R</span>'
    )


def revalu_caption_html(col: str) -> str:
    revalu_field, tier = REVALU_MAP.get(col, (None, None))
    if not revalu_field:
        return '<span style="color:#9ca3af;">EETRA-only</span>'
    icon = "↔" if tier == "exact" else "≈"
    try:
        from libs.lib_tokens import token
        violet = token("palette", "revalu_violet", "#8c66e0")
    except Exception:
        violet = "#8c66e0"
    return (
        f'<span class="revalu-caption" style="color:{violet};display:inline-flex;'
        f'align-items:center;gap:0.3em;vertical-align:middle;">'
        f'{icon} {revalu_r_badge_html()} '
        f'<code class="revalu-field-name" style="color:{violet};">{revalu_field}</code></span>'
    )
