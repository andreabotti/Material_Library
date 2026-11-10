"""
libs/lib_manufacturer_map.py — field taxonomy for the Manufacturer Add/Edit form
================================================================================
Mirrors ``lib_revalu_map.py`` for products: categories, labels, widget kinds,
and flatten / unflatten between the Impact Framework entity dict and a flat
form-values map.

Primary store: ``aux_13__companies_impact_framework.json`` → ``entities.manufacturers``.
Optional overlay: ``aux_14__companies_sust_credentials.json`` credentials + profile
(when the manufacturer name exists there).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# ── Identity (top-level IFW entity keys) ─────────────────────────────────────
IDENTITY_FIELDS: list[str] = [
    "M__Name",
    "M__hq",
    "M__sector",
    "M__parent",
    "M__website",
    "M__ownership",
    "M__listed_exchange",
    "M__revenue_eur",
    "M__employees",
    "M__countries",
    "M__lat",
    "M__lon",
    "M__maturity_tier",
    "M__notes",
]

# Axis A–D field keys → nested IFW path under the axis object
AXIS_FIELDS: dict[str, list[str]] = {
    "A_climate_commitments": [
        "A__sbti_status",
        "A__sbti_target_year",
        "A__net_zero_target_year",
        "A__net_zero_pathway",
        "A__cdp_rating",
        "A__cdp_year",
        "A__ghg_scope1_2_disclosed",
        "A__ghg_scope3_disclosed",
        "A__ghg_intensity_reduction_target_pct",
        "A__renewable_energy_pct_current",
        "A__crrem_pathway_aligned",
    ],
    "B_reporting_transparency": [
        "B__sustainability_report",
        "B__gri_standard",
        "B__tcfd_aligned",
        "B__csrd_esrs_status",
        "B__iso14001",
        "B__iso50001",
        "B__emas",
        "B__ecovadis",
        "B__bcorp_certified",
        "B__benefit_corporation_it",
    ],
    "C_product_credentials": [
        "C__epd_count_active",
        "C__epd_programme_operator_primary",
        "C__cam_portfolio_coverage_pct",
        "C__gwp_portfolio_avg_percentile",
        "C__material_health_strategy",
    ],
    "D_supply_chain": [
        "D__supplier_code_of_conduct",
        "D__supplier_ecovadis_required",
        "D__raw_material_origin_disclosed",
        "D__conflict_minerals_declaration",
        "D__fsc_pefc_certified",
    ],
}

# Sustainability-credentials overlay (aux_14__companies_sust_credentials.json)
SUST_CRED_FIELDS: list[str] = [
    "S__sbti",
    "S__cdp",
    "S__ecovadis",
    "S__iso14001",
    "S__sustainability_report",
    "S__scope1_2",
    "S__scope3",
    "S__net_zero_target",
    "S__csrd_esrs",
    "S__maturity",
]

SUST_PROFILE_FIELDS: list[str] = [
    "P__report",
    "P__report_url",
]

FIELD_LABELS: dict[str, str] = {
    "M__Name": "Manufacturer name",
    "M__hq": "Headquarters",
    "M__sector": "Sector",
    "M__parent": "Parent company",
    "M__website": "Website",
    "M__ownership": "Ownership",
    "M__listed_exchange": "Listed exchange",
    "M__revenue_eur": "Revenue",
    "M__employees": "Employees",
    "M__countries": "Countries of operation",
    "M__lat": "Latitude",
    "M__lon": "Longitude",
    "M__maturity_tier": "Maturity tier (IFW)",
    "M__notes": "Notes",
    "A__sbti_status": "SBTi status",
    "A__sbti_target_year": "SBTi target year",
    "A__net_zero_target_year": "Net-zero target year",
    "A__net_zero_pathway": "Net-zero pathway",
    "A__cdp_rating": "CDP rating",
    "A__cdp_year": "CDP year",
    "A__ghg_scope1_2_disclosed": "GHG Scope 1+2 disclosed",
    "A__ghg_scope3_disclosed": "GHG Scope 3 disclosed",
    "A__ghg_intensity_reduction_target_pct": "GHG intensity reduction target (%)",
    "A__renewable_energy_pct_current": "Renewable energy current (%)",
    "A__crrem_pathway_aligned": "CRREM pathway aligned",
    "B__sustainability_report": "Sustainability report level",
    "B__gri_standard": "GRI standard",
    "B__tcfd_aligned": "TCFD aligned",
    "B__csrd_esrs_status": "CSRD / ESRS status",
    "B__iso14001": "ISO 14001",
    "B__iso50001": "ISO 50001",
    "B__emas": "EMAS",
    "B__ecovadis": "EcoVadis (IFW)",
    "B__bcorp_certified": "B Corp certified",
    "B__benefit_corporation_it": "Società Benefit (IT)",
    "C__epd_count_active": "Active EPD count",
    "C__epd_programme_operator_primary": "Primary EPD programme",
    "C__cam_portfolio_coverage_pct": "CAM portfolio coverage (%)",
    "C__gwp_portfolio_avg_percentile": "GWP portfolio avg percentile",
    "C__material_health_strategy": "Material health strategy",
    "D__supplier_code_of_conduct": "Supplier code of conduct",
    "D__supplier_ecovadis_required": "Supplier EcoVadis required",
    "D__raw_material_origin_disclosed": "Raw material origin disclosed",
    "D__conflict_minerals_declaration": "Conflict minerals declaration",
    "D__fsc_pefc_certified": "FSC / PEFC certified",
    "S__sbti": "SBTi Status",
    "S__cdp": "CDP Rating",
    "S__ecovadis": "EcoVadis",
    "S__iso14001": "ISO 14001",
    "S__sustainability_report": "Sustainability Report",
    "S__scope1_2": "GHG Scope 1+2",
    "S__scope3": "GHG Scope 3",
    "S__net_zero_target": "Net Zero Target",
    "S__csrd_esrs": "CSRD / ESRS",
    "S__maturity": "Maturity tier (credentials)",
    "P__report": "Narrative profile",
    "P__report_url": "Sustainability report URL",
}

FIELD_HELP: dict[str, str] = {
    "A__sbti_status": "0 = none · 1 = committed · 2 = near-term validated · 3 = net-zero validated",
    "B__sustainability_report": "0 = none · 1 = periodic · 2 = annual · 3 = annual GRI · 4 = integrated GRI/TCFD",
    "B__csrd_esrs_status": "0 = n/a · 1 = not started · 2 = preparing · 3 = first year · 4 = compliant",
    "A__ghg_scope3_disclosed": "none / partial / full",
    "A__crrem_pathway_aligned": "true / false / not-assessed",
    "C__epd_count_active": "Integer count, or the token “multiple”",
    "M__Name": "Canonical name — the Impact Framework dictionary key. Renaming moves the record.",
}

# Widget kind hints
BOOL_FIELDS = frozenset({
    "A__ghg_scope1_2_disclosed",
    "B__gri_standard", "B__tcfd_aligned", "B__iso14001", "B__iso50001", "B__emas",
    "B__bcorp_certified", "B__benefit_corporation_it",
    "C__material_health_strategy",
    "D__supplier_code_of_conduct", "D__supplier_ecovadis_required",
    "D__raw_material_origin_disclosed", "D__conflict_minerals_declaration",
    "D__fsc_pefc_certified",
})
INT_FIELDS = frozenset({
    "A__sbti_status", "A__sbti_target_year", "A__net_zero_target_year", "A__cdp_year",
    "A__ghg_intensity_reduction_target_pct", "A__renewable_energy_pct_current",
    "B__sustainability_report", "B__csrd_esrs_status",
    "C__cam_portfolio_coverage_pct", "C__gwp_portfolio_avg_percentile",
    "M__lat", "M__lon",
})
FLOAT_OK = frozenset({"M__lat", "M__lon", "C__cam_portfolio_coverage_pct", "C__gwp_portfolio_avg_percentile"})
SELECT_OPTIONS: dict[str, list[str]] = {
    "A__sbti_status": ["", "0", "1", "2", "3"],
    "A__net_zero_pathway": ["", "SBTi_net_zero", "GCCA", "SteelZero", "proprietary", "none"],
    "A__cdp_rating": ["", "A", "A-", "B+", "B", "B-", "C", "D", "not_participating"],
    "A__ghg_scope3_disclosed": ["", "none", "partial", "full"],
    "A__crrem_pathway_aligned": ["", "true", "false", "not-assessed"],
    "B__sustainability_report": ["", "0", "1", "2", "3", "4"],
    "B__csrd_esrs_status": ["", "0", "1", "2", "3", "4"],
    "B__ecovadis": ["", "none", "Bronze", "Silver", "Gold", "Platinum"],
    "C__epd_programme_operator_primary": [
        "", "IBU", "EPDItaly", "Environdec", "EPD_Norway", "EPD_Hub", "multiple", "none",
    ],
    "M__maturity_tier": [
        "", "Advanced", "Good", "Progressing", "Developing", "Early Stage", "Minimal",
    ],
    "M__ownership": ["", "listed", "private", "cooperative", "public", "family", "other"],
    "S__maturity": [
        "", "Advanced", "Good", "Progressing", "Developing", "Early Stage", "Minimal",
    ],
}
TEXTAREA_FIELDS = frozenset({"M__notes", "P__report"})
URL_FIELDS = frozenset({"M__website", "P__report_url"})
READONLY_ON_EDIT = frozenset()  # name is editable (rename supported)

CATEGORIES: list[dict] = [
    {
        "key": "identity",
        "label": "Identity",
        "fields": IDENTITY_FIELDS,
        "field_groups": [
            {
                "fields": ["M__Name", "M__sector", "M__hq", "M__parent"],
                "columns_per_row": 2,
            },
            {
                "fields": ["M__website", "M__ownership", "M__listed_exchange", "M__maturity_tier"],
                "columns_per_row": 2,
            },
            {
                "fields": ["M__revenue_eur", "M__employees", "M__countries", "M__lat", "M__lon"],
                "columns_per_row": 3,
            },
            {
                "fields": ["M__notes"],
                "columns_per_row": 1,
            },
        ],
    },
    {
        "key": "climate",
        "label": "Climate commitments",
        "fields": AXIS_FIELDS["A_climate_commitments"],
        "field_groups": [
            {
                "fields": [
                    "A__sbti_status", "A__sbti_target_year",
                    "A__net_zero_target_year", "A__net_zero_pathway",
                ],
                "columns_per_row": 2,
            },
            {
                "fields": [
                    "A__cdp_rating", "A__cdp_year",
                    "A__ghg_scope1_2_disclosed", "A__ghg_scope3_disclosed",
                ],
                "columns_per_row": 2,
            },
            {
                "fields": [
                    "A__ghg_intensity_reduction_target_pct",
                    "A__renewable_energy_pct_current",
                    "A__crrem_pathway_aligned",
                ],
                "columns_per_row": 3,
            },
        ],
    },
    {
        "key": "reporting",
        "label": "Reporting & transparency",
        "fields": AXIS_FIELDS["B_reporting_transparency"],
        "field_groups": [
            {
                "fields": [
                    "B__sustainability_report", "B__csrd_esrs_status",
                    "B__gri_standard", "B__tcfd_aligned",
                ],
                "columns_per_row": 2,
            },
            {
                "fields": [
                    "B__iso14001", "B__iso50001", "B__emas", "B__ecovadis",
                ],
                "columns_per_row": 2,
            },
            {
                "fields": ["B__bcorp_certified", "B__benefit_corporation_it"],
                "columns_per_row": 2,
            },
        ],
    },
    {
        "key": "products",
        "label": "Product credentials",
        "fields": AXIS_FIELDS["C_product_credentials"],
        "field_groups": [
            {
                "fields": [
                    "C__epd_count_active", "C__epd_programme_operator_primary",
                    "C__cam_portfolio_coverage_pct", "C__gwp_portfolio_avg_percentile",
                ],
                "columns_per_row": 2,
            },
            {
                "fields": ["C__material_health_strategy"],
                "columns_per_row": 2,
            },
        ],
    },
    {
        "key": "supply",
        "label": "Supply chain",
        "fields": AXIS_FIELDS["D_supply_chain"],
        "field_groups": [
            {
                "fields": list(AXIS_FIELDS["D_supply_chain"]),
                "columns_per_row": 2,
            },
        ],
    },
    {
        "key": "sust",
        "label": "Credentials matrix",
        "fields": SUST_CRED_FIELDS + SUST_PROFILE_FIELDS,
        "field_groups": [
            {
                "section_title": "Nine-check credentials (Manufacturers directory)",
                "section_divider": True,
                "fields": SUST_CRED_FIELDS,
                "columns_per_row": 2,
            },
            {
                "section_title": "Narrative profile",
                "section_divider": True,
                "fields": SUST_PROFILE_FIELDS,
                "columns_per_row": 1,
            },
        ],
    },
]


def label_for(col: str) -> str:
    return FIELD_LABELS.get(col, col)


def help_for(col: str) -> str | None:
    return FIELD_HELP.get(col)


def normalize_maturity_tier(value: Any, *, style: str = "sust") -> Any:
    """Align IFW ``Early-Stage`` with credentials ``Early Stage``.

    ``style="sust"`` → spaced form; ``style="ifw"`` → hyphenated Early-Stage.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    key = s.lower().replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    canonical = {
        "advanced": "Advanced",
        "good": "Good",
        "progressing": "Progressing",
        "developing": "Developing",
        "early stage": "Early Stage",
        "minimal": "Minimal",
    }.get(key)
    if not canonical:
        return s
    if style == "ifw" and canonical == "Early Stage":
        return "Early-Stage"
    return canonical


def all_form_fields() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for cat in CATEGORIES:
        for col in cat["fields"]:
            if col not in seen:
                seen.add(col)
                out.append(col)
    return out


def _axis_leaf(col: str) -> str:
    """``A__sbti_status`` → ``sbti_status``."""
    return col.split("__", 1)[1] if "__" in col else col


def empty_entity() -> dict[str, Any]:
    """Minimal IFW manufacturer stub for Add."""
    return {
        "entity_type": "manufacturer",
        "hq": "",
        "sector": "",
        "parent": None,
        "revenue_eur": None,
        "employees": None,
        "ownership": None,
        "listed_exchange": None,
        "countries": None,
        "lat": None,
        "lon": None,
        "website": None,
        "A_climate_commitments": {},
        "B_reporting_transparency": {},
        "C_product_credentials": {},
        "D_supply_chain": {},
        "maturity_tier": None,
        "notes": None,
    }


def flatten_manufacturer(
    name: str,
    entity: dict | None,
    *,
    sust_creds: dict | None = None,
    sust_profile: dict | None = None,
) -> dict[str, Any]:
    """Entity (+ optional sust overlay) → flat form values."""
    e = entity or {}
    vals: dict[str, Any] = {"M__Name": name}
    for col in IDENTITY_FIELDS:
        if col == "M__Name":
            continue
        leaf = _axis_leaf(col)
        vals[col] = e.get(leaf)
    vals["M__maturity_tier"] = normalize_maturity_tier(
        vals.get("M__maturity_tier"), style="sust",
    )
    for axis, cols in AXIS_FIELDS.items():
        block = e.get(axis) or {}
        for col in cols:
            vals[col] = block.get(_axis_leaf(col))
    creds = sust_creds or {}
    for col in SUST_CRED_FIELDS:
        vals[col] = creds.get(_axis_leaf(col))
    vals["S__maturity"] = normalize_maturity_tier(
        vals.get("S__maturity"), style="sust",
    )
    prof = sust_profile or {}
    for col in SUST_PROFILE_FIELDS:
        vals[col] = prof.get(_axis_leaf(col))
    return vals


def unflatten_to_entity(values: dict[str, Any], base: dict | None = None) -> dict[str, Any]:
    """Flat form values → IFW manufacturer entity (no name key)."""
    e = deepcopy(base) if base else empty_entity()
    e["entity_type"] = "manufacturer"
    for col in IDENTITY_FIELDS:
        if col == "M__Name":
            continue
        leaf = _axis_leaf(col)
        e[leaf] = _coerce_stored(col, values.get(col))
    e["maturity_tier"] = normalize_maturity_tier(
        e.get("maturity_tier"), style="ifw",
    )
    for axis, cols in AXIS_FIELDS.items():
        block = dict(e.get(axis) or {})
        for col in cols:
            block[_axis_leaf(col)] = _coerce_stored(col, values.get(col))
        e[axis] = block
    return e


def unflatten_sust_creds(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in SUST_CRED_FIELDS:
        out[_axis_leaf(col)] = _coerce_stored(col, values.get(col))
    if "maturity" in out:
        out["maturity"] = normalize_maturity_tier(out.get("maturity"), style="sust")
    return out


def unflatten_sust_profile(values: dict[str, Any], identity: dict | None = None) -> dict[str, Any]:
    """Build / update a company_profiles entry; copy identity basics when present."""
    out: dict[str, Any] = dict(identity or {})
    for col in SUST_PROFILE_FIELDS:
        out[_axis_leaf(col)] = _coerce_stored(col, values.get(col))
    # Keep profile identity in sync with IFW identity when saving.
    for src, dst in (
        ("M__hq", "hq"),
        ("M__sector", "sector"),
        ("M__parent", "parent"),
        ("M__website", "website"),
        ("M__ownership", "ownership"),
        ("M__revenue_eur", "revenue"),
        ("M__employees", "employees"),
        ("M__countries", "countries"),
        ("M__lat", "lat"),
        ("M__lon", "lon"),
    ):
        if src in (values or {}):
            out[dst] = _coerce_stored(src, values.get(src))
    return out


def _coerce_stored(col: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if col in BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "y"):
            return True
        if s in ("false", "0", "no", "n"):
            return False
        return None
    if col in SELECT_OPTIONS and col in INT_FIELDS:
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return value
    if col in INT_FIELDS:
        try:
            f = float(str(value).replace(",", ".").strip())
            return f if col in FLOAT_OK else int(f)
        except (TypeError, ValueError):
            return value  # keep tokens like "multiple"
    return value


def field_status(col: str, value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "filled"
    s = str(value).strip()
    if s in ("", "-", "nan", "None", "<NA>"):
        return "missing"
    return "filled"


_STATUS_STYLE = {
    "filled": ("#16a34a", "● Filled"),
    "missing": ("#d97706", "● Missing"),
}


def status_badge_html(status: str) -> str:
    color, text = _STATUS_STYLE.get(status, _STATUS_STYLE["missing"])
    return f'<span style="color:{color};font-weight:600;">{text}</span>'


def status_counts(fields: list[str], values: dict[str, Any]) -> dict[str, int]:
    counts = {"filled": 0, "missing": 0}
    for col in fields:
        counts[field_status(col, values.get(col))] += 1
    return counts
