"""
pages/15_Manufacturers.py — Manufacturers directory
====================================================

One place for everything the app knows about the companies behind the products.
Merges two datasets, keyed by manufacturer name (the names are identical in both):

  aux_companies_sust_credentials.json   — company profiles + 9 credential checks
                                          (was Developer → Data Exploration → Manufacturers)
  aux_companies_impact_framework.json   — Impact Framework entities, A–D axes and score
                                          (was Further Data Sources → Impact Framework → Entità)

Tabs (lazy: only the open tab runs):
  Monograph          — one manufacturer on one scrolling page: profile header + KPIs,
                       product / material treemaps (click to filter), data completeness
                       vs the library, and its JS2 product cards. Reads ORIGINAL_DATA, so
                       sidebar filters don't apply. Dataset names are matched to profile
                       keys through aux__manufacturer_aliases.json (libs/lib_monograph.py).
                       Deep link: ?mfr=<dataset manufacturer name>.
                       Two views: Interactive (02_html/monograph_component.html, ECharts;
                       treemap clicks filter the catalogue iframe client-side) and
                       Standard (native Streamlit elements). Same numbers in both.
  Directory          — card grid + right detail panel (02_html/manufacturers_component.html),
                       styled after the Catalogue's JS2 component. Specifiers and
                       contractors from the Impact Framework sit behind the same toolbar toggle.
  Credentials matrix — the 9-credential table for manufacturers
  Maturity ranking   — manufacturers by credentials maturity tier + distribution
  Evaluation framework — the evidence asked of a manufacturer, by macroarea, with its
                       level (Core / Core-se-applicabile / Advanced), its conditional
                       dependency and whether it is Compliance (a legal obligation, so a
                       gate) or Merito (voluntary, the only nature that scores).
                       Read-only view over aux_companies_impact_framework.json →
                       evaluation_framework (lib_data.fn140h). ``Livello fonte`` keeps the
                       source document's two-level call, flagged where it was reclassified.
  Questionnaire      — interactive supplier survey over the same evaluation_framework block;
                       SASB SICS classification + company-size filter first (B Lab FTE bands),
                       then live branching (lib_data.fn140i). One Microsoft-Forms-like section
                       per macroarea: applicability filters skip an evidence, and follow-ups
                       open only on a Sì. Answers stay in session_state for this session.

The Impact Framework's Framework Matrix stays under Further Data Sources.
"""

from __future__ import annotations

import base64
import html as _html
import json
import unicodedata
from functools import partial
from io import BytesIO
from pathlib import Path

import altair as alt

from libs.page_imports import *  # noqa: F401,F403
import libs.lib_ui as _lib_ui
from libs.lib_monograph import (
    FIELD_GROUPS,
    RICHNESS_BINS,
    fn600_manufacturer_options,
    fn601_resolve_profile_name,
    fn602_manufacturer_rows,
    fn603_value_counts,
    fn604_completeness_by_group,
    fn605_richness_per_product,
    fn606_document_counts,
    fn607_kpis,
    fn608_field_group_columns,
)
from libs.lib_tokens import token as _token
from libs.lib_data import (
    fn135_sustainability_credentials,
    fn137_get_credentials_matrix,
    fn138_get_maturity_ranking,
    fn140a_load_impact_framework,
    fn140b_manufacturer_impact_summary,
    fn140h_evaluation_framework,
    fn140i_evaluation_questionnaire,
    _ifw_score_manufacturer,
)
from libs.lib_html import HTML_DIR, read_iframe_component
from libs.lib_tokens import font_links_html
from libs.lib_ui import (
    card_name_divider_root_css,
    fn312_get_manufacturer_logo_mapping,
    fn359_iframe_height,
    js2_typography_root_css,
)

_APP_ROOT = Path(__file__).resolve().parent.parent
_COMPONENT = HTML_DIR / "manufacturers_component.html"
_MONO_JS_COMPONENT = HTML_DIR / "monograph_component.html"
_DATA_FILES = (
    _APP_ROOT / "aux_companies_sust_credentials.json",
    _APP_ROOT / "aux_companies_impact_framework.json",
    _APP_ROOT / "aux__ui_config.json",
    Path(__file__).resolve(),  # payload helpers live here; editing them must invalidate the cache
)

_ETYPES = [
    {"key": "manufacturers", "label": "Manufacturers", "noun": "manufacturers"},
    {"key": "specifiers", "label": "Specifiers", "noun": "specifiers"},
    {"key": "contractors", "label": "Contractors", "noun": "contractors"},
]
_ETYPE_FALLBACK_SECTOR = {"specifiers": "Design studio", "contractors": "Contractor"}


# ── Impact Framework scoring (specifiers / contractors) ──────────────────────
# Manufacturers use lib_data._ifw_score_manufacturer, the same function behind
# the Catalogue's Manufacturer's Sustainability card, so both show one score.

def _b(v) -> float:
    if v is True:
        return 100.0
    if v is False or v is None:
        return 0.0
    return 100.0 if str(v).lower() not in ("false", "none", "0", "") else 0.0


def _leed_count_score(v) -> float:
    if v is None:
        return 0.0
    s = str(v).strip()
    try:
        n = int(s.lstrip("<>"))
    except ValueError:
        return 50.0 if s.startswith(">") else (25.0 if s.startswith("<") else 0.0)
    if s.startswith("<"):
        return 25.0 if n > 0 else 0.0
    return 100.0 if n >= 10 else (50.0 if n >= 5 else (25.0 if n > 0 else 0.0))


def _score_specifier(e: dict, w: dict) -> dict:
    E = e.get("E_framework_adoption", {}) or {}
    F = e.get("F_material_specification", {}) or {}
    G = e.get("G_reporting_capability", {}) or {}
    H = e.get("H_team_capacity", {}) or {}
    cam = E.get("cam_projects_count")
    axis_e = (
        _leed_count_score(E.get("leed_certified_projects_count"))
        + (0.0 if cam in (None, "none", 0) else (100.0 if str(cam) == "multiple" else 50.0))
        + (0.0 if E.get("well_certified_projects_count") in (None, 0) else 100.0)
    ) / 3
    axis_f = (
        _b(F.get("epd_required_in_specs")) + _b(F.get("gwp_threshold_in_specs"))
        + (0.0 if F.get("lca_tool_used") in (None, "none") else 100.0)
    ) / 3
    axis_g = (
        _b(G.get("embodied_carbon_reporting")) + _b(G.get("dnsh_assessment_capability"))
        + _b(G.get("bim_lca_integration"))
    ) / 3
    axis_h = (_b(H.get("sustainability_lead")) + _b(H.get("lca_specialist_inhouse"))) / 2
    total = (
        axis_e * w["framework_adoption"] + axis_f * w["material_specification"]
        + axis_g * w["reporting_capability"] + axis_h * w["team_capacity"]
    )
    return {"E": axis_e, "F": axis_f, "G": axis_g, "H": axis_h, "total": round(total, 1)}


def _score_contractor(e: dict, w: dict) -> dict:
    I = e.get("I_site_operations", {}) or {}
    J = e.get("J_material_procurement", {}) or {}
    K = e.get("K_reporting_compliance", {}) or {}
    L = e.get("L_certifications", {}) or {}
    axis_i = (_b(I.get("iso14001_construction_sites")) + _b(I.get("iso45001"))
              + _b(I.get("site_waste_management_plan"))) / 3
    axis_j = (_b(J.get("epd_required_from_suppliers")) + _b(J.get("cam_procurement_policy"))
              + _b(J.get("voc_requirement_procurement"))) / 3
    axis_k = (_b(K.get("ghg_scope1_2_disclosed")) + _b(K.get("pnrr_dnsh_compliance"))
              + _b(K.get("leed_breeam_site_credits"))) / 3
    eco = {"none": 0, "Bronze": 33, "Silver": 66, "Gold": 90, "Platinum": 100}.get(
        str(L.get("ecovadis", "none")), 0)
    axis_l = (eco + _b(L.get("rating_legalita"))) / 2
    total = (
        axis_i * w["site_operations"] + axis_j * w["material_procurement"]
        + axis_k * w["reporting_compliance"] + axis_l * w["certifications"]
    )
    return {"I": axis_i, "J": axis_j, "K": axis_k, "L": axis_l, "total": round(total, 1)}


# ── Value formatting ─────────────────────────────────────────────────────────

_AXES = {
    "manufacturers": [
        ("A", "A_climate_commitments", "🌐", "Climate commitments"),
        ("B", "B_reporting_transparency", "📄", "Reporting & transparency"),
        ("C", "C_product_credentials", "🏷", "Product credentials"),
        ("D", "D_supply_chain", "🔗", "Supply chain"),
    ],
    "specifiers": [
        ("E", "E_framework_adoption", "🧭", "Framework adoption"),
        ("F", "F_material_specification", "📐", "Material specification"),
        ("G", "G_reporting_capability", "📄", "Reporting capability"),
        ("H", "H_team_capacity", "👥", "Team capacity"),
    ],
    "contractors": [
        ("I", "I_site_operations", "🏗", "Site operations"),
        ("J", "J_material_procurement", "📦", "Material procurement"),
        ("K", "K_reporting_compliance", "📄", "Reporting & compliance"),
        ("L", "L_certifications", "🏅", "Certifications"),
    ],
}
_ALL_AXIS_KEYS = [ax for axes in _AXES.values() for _, ax, _, _ in axes]

_LABELS = {
    "sbti_status": "SBTi status", "sbti_target_year": "SBTi target year",
    "sbti_scopes_covered": "SBTi scopes", "net_zero_target_year": "Net-zero target year",
    "net_zero_pathway": "Net-zero pathway", "cdp_rating": "CDP rating", "cdp_year": "CDP year",
    "ghg_scope1_2_disclosed": "GHG Scope 1+2 disclosed", "ghg_scope3_disclosed": "GHG Scope 3 disclosed",
    "ghg_intensity_reduction_target_pct": "GHG reduction target (%)",
    "renewable_energy_pct_current": "Renewable energy (%)", "crrem_pathway_aligned": "CRREM aligned",
    "sustainability_report": "Sustainability report", "report_url": "Report",
    "gri_standard": "GRI standard", "tcfd_aligned": "TCFD aligned", "csrd_esrs_status": "CSRD / ESRS",
    "iso14001": "ISO 14001", "iso50001": "ISO 50001", "emas": "EMAS", "ecovadis": "EcoVadis",
    "ecovadis_score": "EcoVadis score", "bcorp_certified": "B Corp", "bcorp_score": "B Corp score",
    "bcorp_year": "B Corp year", "benefit_corporation_it": "Società Benefit",
    "epd_count_active": "Active EPDs", "epd_programme_operator_primary": "EPD programme",
    "cam_portfolio_coverage_pct": "CAM portfolio coverage (%)",
    "gwp_portfolio_avg_percentile": "GWP portfolio percentile",
    "material_health_strategy": "Material health strategy",
    "supplier_code_of_conduct": "Supplier code of conduct",
    "supplier_ecovadis_required": "Supplier EcoVadis required",
    "raw_material_origin_disclosed": "Material origin disclosed",
    "conflict_minerals_declaration": "Conflict minerals declaration",
    "fsc_pefc_certified": "FSC / PEFC certified",
    # added by the 2026-09 research pass
    "bcorp_recertified": "B Corp recertified", "c2c_certified_products": "Cradle to Cradle products",
    "cogeneration_mwh": "Cogeneration (MWh)", "csrd_first_reporting_year": "CSRD first reporting year",
    "eaf_scrap_content_pct": "EAF scrap content (%)", "epd_detail": "EPD notes",
    "epd_portfolio_coverage_pct": "EPD portfolio coverage (%)", "ghg_scope1_2_basis": "Scope 1+2 basis",
    "ghg_scope1_2_tco2eq": "Scope 1+2 (tCO2e)", "gwp_reduction_intensity_pct": "GWP intensity reduction (%)",
    "iso14064_1": "ISO 14064-1", "iso20400": "ISO 20400",
    "iso20400_sustainable_procurement": "ISO 20400 (procurement)", "iso45001": "ISO 45001",
    "leed_products_count": "LEED-contributing products", "material_health_detail": "Material health notes",
    "production_waste_recovered_pct": "Production waste recovered (%)",
    "recycled_content_avg_pct": "Recycled content, average (%)",
    "recycled_content_premium_range_pct": "Recycled content, premium range (%)",
    "recycled_content_range_pct": "Recycled content range (%)", "recycled_gypsum_pct": "Recycled gypsum (%)",
    "renewable_energy_basis": "Renewable energy basis",
    "renewable_energy_target_pct_2030": "Renewable energy target 2030 (%)",
    "reporting_framework": "Reporting framework", "supplier_code_signed_pct": "Supplier code signed (%)",
    "supplier_iso14001_required": "Supplier ISO 14001 required",
    "wastewater_recycled_m3": "Wastewater recycled (m³)", "wastewater_recycled_pct": "Wastewater recycled (%)",
}
_ENUMS = {
    "sbti_status": {0: "None", 1: "Committed", 2: "Validated near-term", 3: "Validated net-zero"},
    "sustainability_report": {0: "None", 1: "Periodic", 2: "Annual", 3: "Annual (GRI)",
                              4: "Integrated (GRI + TCFD)"},
    "csrd_esrs_status": {0: "Not applicable", 1: "Not started", 2: "Preparing", 3: "First year",
                         4: "Compliant"},
}
_WORDS = {"none": "None", "not_participating": "Not participating", "not-assessed": "Not assessed",
          "not_applicable": "Not applicable", "multiple": "Multiple", "full": "Full",
          "partial": "Partial", "proprietary": "Proprietary"}


def _label(key: str) -> str:
    return _LABELS.get(key) or key.replace("_", " ").strip().capitalize()


def _fmt(key: str, v):
    """``(text, status, is_html)`` for one Impact Framework indicator, or None to skip."""
    if v is None:
        return None
    if isinstance(v, bool):
        return ("Yes" if v else "No", "ok" if v else "no", False)
    if key in _ENUMS:
        try:
            i = int(v)
            return (_ENUMS[key].get(i, str(v)), "ok" if i > 0 else "no", False)
        except (TypeError, ValueError):
            pass
    if isinstance(v, list):
        return (", ".join(str(x) for x in v) or None, None, False) if v else None
    s = str(v).strip()
    if not s:
        return None
    if s.startswith("http"):
        return (f'<a href="{_html.escape(s)}" target="_blank" rel="noopener">Open ↗</a>', None, True)
    if s in _WORDS:
        return (_WORDS[s], "no" if s in ("none", "not_participating", "not_applicable") else None, False)
    if "_" in s and " " not in s:
        s = s.replace("_", " ").capitalize()
    return (s, None, False)


def _cred_status(raw: str) -> tuple[str, str]:
    """Split a credentials cell like '✅ Annual (GRI)' into ('Annual (GRI)', 'ok')."""
    s = str(raw or "").strip()
    for mark, st_ in (("✅", "ok"), ("⚠️", "warn"), ("⚠", "warn"), ("❌", "no")):
        if s.startswith(mark):
            rest = s[len(mark):].strip()
            return (rest or {"ok": "Yes", "warn": "Partial", "no": "No"}[st_], st_)
    return (s or "—", "no")


def _norm_tier(t: str) -> str:
    t = str(t or "").strip()
    return "Early-Stage" if t.lower().replace("-", " ") == "early stage" else t


# ── Logos ────────────────────────────────────────────────────────────────────

def _logo_data_uri(rel: str) -> str:
    rel = str(rel or "").strip()
    if not rel:
        return ""
    cands = [_APP_ROOT / rel, _APP_ROOT / "03_img" / Path(rel).name]
    path = next((p for p in cands if p.is_file()), None)
    if path is None:
        return ""
    try:
        if path.suffix.lower() == ".svg":
            return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()
        img = Image.open(path)
        img.thumbnail((200, 90))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ── Payload ──────────────────────────────────────────────────────────────────

def _framework_hits(e: dict, fw_matrix: dict, ind_key: str) -> list[str]:
    hits = []
    for fw_key, fw in fw_matrix.items():
        for ind in fw.get(ind_key, []) or []:
            if any((e.get(ax, {}) or {}).get(ind) not in
                   (None, False, 0, "none", "not_participating", "not_applicable")
                   for ax in _ALL_AXIS_KEYS if ind in (e.get(ax, {}) or {})):
                hits.append(_fw_short(fw_key))
                break
    return hits


def _fw_short(k: str) -> str:
    for a, b in (("_Edilizia_IT", ""), ("_EU_Taxonomy", ""), ("_Int", ""), ("_v41", ""), ("_v2", ""),
                 ("_Gensler", ""), ("_ESRS", ""), ("_Composite", ""), ("_s", "")):
        k = k.replace(a, b)
    return k.replace("Level", "Level(s)") if k == "Level" else k


# ── Sources ──────────────────────────────────────────────────────────────────
# Each Impact Framework entity may carry ``sources: {indicator_key | alias: [url]}``
# (aliases: _profile, epd, ghg, cam, notes). Rows get the matching URLs as 🔗
# links, as in the Catalogue; the Sources tab lists every URL once.

# Credentials-file keys → Impact Framework indicator keys
_CRED_TO_IFW = {
    "sbti": "sbti_status", "cdp": "cdp_rating", "ecovadis": "ecovadis", "iso14001": "iso14001",
    "sustainability_report": "sustainability_report", "scope1_2": "ghg_scope1_2_disclosed",
    "scope3": "ghg_scope3_disclosed", "net_zero_target": "net_zero_target_year",
    "csrd_esrs": "csrd_esrs_status",
}
# Rows the company's own sustainability/report page substantiates when no
# indicator-specific source was recorded.
_REPORT_FALLBACK_KEYS = {
    "sustainability_report", "csrd_esrs_status", "gri_standard", "tcfd_aligned", "sbti_status",
    "net_zero_target_year", "ghg_scope1_2_disclosed", "ghg_scope3_disclosed",
}
_ALIAS_PREFIX = (("epd_", "epd"), ("ghg_", "ghg"), ("cam_", "cam"))
_ALIAS_LABELS = {"_profile": "Company profile", "epd": "EPDs", "ghg": "GHG disclosure",
                 "cam": "CAM / recycled-content declarations", "notes": "Analyst notes"}


class _Sources:
    def __init__(self, src, report_url: str = ""):
        self.src = src if isinstance(src, dict) else {}
        self.report_url = str(report_url or "").strip()
        self.used: dict[str, list[str]] = {}

    def _note(self, urls: list, label: str) -> list:
        for u in urls:
            lst = self.used.setdefault(u, [])
            # Credentials and Impact Framework rows name the same check with
            # different casing ("SBTi Status" / "SBTi status") — list it once.
            if label and label.lower() not in (x.lower() for x in lst):
                lst.append(label)
        return urls

    def for_key(self, key: str, label: str) -> list:
        urls = list(self.src.get(key) or [])
        if not urls:
            for pre, alias in _ALIAS_PREFIX:
                if key.startswith(pre):
                    urls = list(self.src.get(alias) or [])
                    break
        if not urls and key in _REPORT_FALLBACK_KEYS and self.report_url.startswith("http"):
            urls = [self.report_url]
        return self._note([u for u in urls if str(u).startswith("http")], label)

    def alias(self, alias: str, label: str) -> list:
        return self._note([u for u in (self.src.get(alias) or []) if str(u).startswith("http")], label)

    def listing(self) -> list:
        # Recorded sources that no displayed row picked up still get listed.
        for k, urls in self.src.items():
            for u in urls or []:
                if str(u).startswith("http") and u not in self.used:
                    self.used[u] = [_ALIAS_LABELS.get(k) or _label(k.lstrip("_"))]
        # One entry per document; page-anchored links into the same PDF
        # (``…pdf#page=34``) become that document's page chips.
        docs: dict[str, dict] = {}
        for u, labels in self.used.items():
            base, _, frag = u.partition("#")
            host, _, path = base.split("//", 1)[-1].partition("/")
            d = docs.setdefault(base, {"url": base, "host": host.removeprefix("www."),
                                       "path": ("/" + path) if path else "", "used": [], "pages": []})
            page = frag[5:] if frag.startswith("page=") else ""
            if page:
                d["pages"].append({"url": u, "page": page, "used": labels})
            for lab in labels:
                if lab.lower() not in (x.lower() for x in d["used"]):
                    d["used"].append(lab)
        out = list(docs.values())
        for d in out:
            d["pages"].sort(key=lambda p: int(p["page"]) if p["page"].isdigit() else 10**6)
        return out


def _ifw_groups(etype: str, e: dict, score: dict, srcs: "_Sources") -> list[dict]:
    groups = []
    for letter, ax, icon, title in _AXES[etype]:
        rows = []
        for k, v in (e.get(ax) or {}).items():
            f = _fmt(k, v)
            if f and f[0] not in (None, ""):
                urls = [] if k == "report_url" else srcs.for_key(k, _label(k))
                rows.append([_label(k), f[0], f[1], f[2], urls])
        if rows:
            groups.append({"icon": icon, "title": f"{letter} · {title}",
                           "sub": f"{score.get(letter, 0):.0f}/100", "rows": rows})
    return groups


def _profile_rows(pairs, srcs=None,
                  sourced=("Headquarters", "Parent", "Ownership", "Revenue", "Employees")) -> list[list]:
    rows = []
    for label, val in pairs:
        if val is None or (isinstance(val, (list, tuple)) and not val):
            continue
        if isinstance(val, (list, tuple)):
            val = ", ".join(str(x) for x in val)
        s = str(val).strip()
        if not s or s.lower() in ("none", "nan", "—"):
            continue
        if s.startswith("http"):
            rows.append([label, f'<a href="{_html.escape(s)}" target="_blank" rel="noopener">'
                                f'{_html.escape(s.split("//", 1)[-1].rstrip("/"))}</a>', None, True, []])
        else:
            urls = srcs.alias("_profile", label)[:1] if (srcs and label in sourced) else []
            rows.append([label, s, None, False, urls])
    return rows


# Credential groups for the panel (keys from credential_labels)
_CRED_GROUPS = [
    ("🌐", "Climate", ["sbti", "net_zero_target", "cdp", "scope1_2", "scope3"]),
    ("📄", "Reporting & ratings", ["sustainability_report", "csrd_esrs", "iso14001", "ecovadis"]),
]


def _logo_resolver(logo_map: dict):
    """``name -> data URI`` (or "") from the aux__ui_config logo mapping, memoised per path."""
    logo_cache: dict[str, str] = {}

    def _logo(name: str) -> str:
        m = logo_map.get(" ".join(str(name).split()).lower())
        rel = m.get("logo_path") if isinstance(m, dict) else None
        if not rel:
            return ""
        if rel not in logo_cache:
            logo_cache[rel] = _logo_data_uri(rel)
        return logo_cache[rel]

    return _logo


def _manufacturer_record(name: str, *, creds: dict, profiles: dict, labels: dict, mfr_sector: dict,
                         ifw_mfr: dict, weights: dict, tier_rank: dict, fw_matrix: dict,
                         logo_fn, n_products: int) -> dict:
    """One manufacturer as the Directory panel (and the Monograph header) shows it."""
    c = creds.get(name) or {}
    p = profiles.get(name) or {}
    e = ifw_mfr.get(name) or {}
    has_ifw = bool(e)
    score = _ifw_score_manufacturer(e, weights.get("company_score")) if has_ifw else None
    cred_tier = _norm_tier(c.get("maturity", ""))
    tier = _norm_tier(e.get("maturity_tier")) if has_ifw else cred_tier
    sector = p.get("sector") or e.get("sector") or mfr_sector.get(name, "")
    hq = p.get("hq") or e.get("hq") or ""

    if has_ifw:
        summ = fn140b_manufacturer_impact_summary(name) or {}
        pills = [{"label": x["label"], "state": "ok" if x.get("on") else "off"}
                 for x in summ.get("pills", [])]
    else:
        pills = []
        for key, short in (("sbti", "SBTi"), ("cdp", "CDP"), ("iso14001", "ISO 14001"),
                           ("ecovadis", "EcoVadis"), ("sustainability_report", "Report")):
            if key in c:
                txt, st_ = _cred_status(c[key])
                pills.append({"label": short, "state": {"no": "off"}.get(st_, st_),
                              "title": f"{labels.get(key, short)}: {txt}"})

    srcs = _Sources(
        e.get("sources"),
        (e.get("B_reporting_transparency") or {}).get("report_url") or p.get("report_url") or "",
    )
    credentials = []
    if c:
        for icon, title, keys in _CRED_GROUPS:
            rows = []
            for k in keys:
                if k in c:
                    txt, st_ = _cred_status(c[k])
                    lab = labels.get(k, k)
                    rows.append([lab, txt, st_, False, srcs.for_key(_CRED_TO_IFW.get(k, k), lab)])
            if rows:
                credentials.append({"icon": icon, "title": title, "rows": rows})

    n_products = int(n_products or 0)
    profile = _profile_rows([
        ("Headquarters", hq),
        ("Parent", p.get("parent") or e.get("parent")),
        ("Ownership", p.get("ownership") or e.get("ownership")),
        ("Revenue", p.get("revenue") or e.get("revenue_eur")),
        ("Employees", p.get("employees") or e.get("employees")),
        ("Countries", p.get("countries") or e.get("countries")),
        ("Listed on", e.get("listed_exchange")),
        ("Website", p.get("website") or e.get("website")),
        ("Products in library", n_products),          # 0 shows as 0 — "no coverage yet" is a fact
    ], srcs)
    fw = _framework_hits(e, fw_matrix, "company_indicators") if has_ifw else []
    narrative = p.get("report") or ""
    if narrative.startswith("(see "):
        narrative = ""
    if narrative and str(p.get("report_url") or "").startswith("http"):
        srcs._note([p["report_url"]], "Sustainability summary")
    search = " ".join([name, hq, sector, (e.get("notes") or ""), narrative]).lower()
    rec = {
        "id": f"m::{name}", "name": name, "sector": sector, "hq": hq,
        "tier": tier, "tierRank": tier_rank.get(tier, 99), "credTier": cred_tier,
        "score": score["total"] if score else None, "hasIfw": has_ifw,
        "logo": logo_fn(name), "products": n_products, "pills": pills, "fw": fw,
        "profile": profile, "narrative": narrative, "reportUrl": p.get("report_url") or "",
        "notes": (e.get("notes") or ""), "notesUrls": srcs.alias("notes", "Analyst notes"),
        "credentials": credentials,
        "ifwGroups": _ifw_groups("manufacturers", e, score, srcs) if has_ifw else [],
        "search": search,
    }
    rec["sources"] = srcs.listing()
    return rec


def _record_inputs() -> dict:
    """Shared inputs for :func:`_manufacturer_record`, read from the two company JSONs."""
    sust = fn135_sustainability_credentials()
    ifw = fn140a_load_impact_framework()
    meta = ifw.get("_meta", {}) or {}
    tiers = [_norm_tier(t) for t in (ifw.get("maturity_tiers") or {}).keys()]
    logo_map = fn312_get_manufacturer_logo_mapping(str(_APP_ROOT / "aux__ui_config.json"))
    return {
        "creds": sust.get("credentials", {}) or {},
        "profiles": sust.get("company_profiles", {}) or {},
        "labels": sust.get("credential_labels", {}) or {},
        "mfr_sector": {m: sec for sec, ms in (sust.get("sectors") or {}).items() for m in ms},
        "ifw_mfr": (ifw.get("entities", {}) or {}).get("manufacturers", {}) or {},
        "weights": meta.get("scoring_weights", {}) or {},
        "tier_rank": {t: i for i, t in enumerate(tiers)},
        "fw_matrix": (ifw.get("framework_matrix", {}) or {}).get("frameworks", {}) or {},
        "logo_fn": _logo_resolver(logo_map),
    }


@st.cache_data(show_spinner="Building manufacturers directory…", max_entries=4)
def _build_payload(mtimes: tuple, product_counts: dict) -> dict:
    ifw = fn140a_load_impact_framework()
    meta = ifw.get("_meta", {}) or {}
    weights = meta.get("scoring_weights", {}) or {}
    fw_matrix = (ifw.get("framework_matrix", {}) or {}).get("frameworks", {}) or {}
    tiers = [_norm_tier(t) for t in (ifw.get("maturity_tiers") or {}).keys()]
    tier_rank = {t: i for i, t in enumerate(tiers)}
    ents_ifw = ifw.get("entities", {}) or {}

    inputs = _record_inputs()
    creds, ifw_mfr = inputs["creds"], inputs["ifw_mfr"]

    out: dict[str, list] = {t["key"]: [] for t in _ETYPES}

    # Manufacturers: union of both files
    for name in sorted(set(creds) | set(ifw_mfr), key=str.lower):
        out["manufacturers"].append(
            _manufacturer_record(name, n_products=product_counts.get(name, 0), **inputs)
        )

    # Specifiers / contractors: Impact Framework only
    for etype, scorer, wkey, ind_key in (
        ("specifiers", _score_specifier, "specifier_score", "specifier_indicators"),
        ("contractors", _score_contractor, "contractor_score", "contractor_indicators"),
    ):
        for name, e in (ents_ifw.get(etype) or {}).items():
            if not e.get("hq"):
                continue  # stubs such as "Salini Impregilo (ora Webuild)"
            score = scorer(e, weights[wkey])
            tier = _norm_tier(e.get("maturity_tier"))
            tags = e.get("focus") or e.get("specializations") or []
            sector = e.get("sector") or e.get("subtype") or _ETYPE_FALLBACK_SECTOR[etype]
            if etype == "specifiers":
                F = e.get("F_material_specification", {}) or {}
                Eax = e.get("E_framework_adoption", {}) or {}
                lca = str(F.get("lca_tool_used") or "none")
                pills = [
                    {"label": "EPD in specs", "state": "ok" if F.get("epd_required_in_specs") else "off"},
                    {"label": "GWP threshold", "state": "ok" if F.get("gwp_threshold_in_specs") else "off"},
                    {"label": f"LCA: {lca}", "state": "off" if lca in ("none", "None", "") else "ok"},
                    {"label": f"LEED {Eax.get('leed_certified_projects_count') or 0}",
                     "state": "ok" if Eax.get("leed_certified_projects_count") not in (None, 0) else "off"},
                ]
            else:
                J = e.get("J_material_procurement", {}) or {}
                K = e.get("K_reporting_compliance", {}) or {}
                L = e.get("L_certifications", {}) or {}
                eco = str(L.get("ecovadis") or "none")
                pills = [
                    {"label": "EPD from suppliers", "state": "ok" if J.get("epd_required_from_suppliers") else "off"},
                    {"label": "CAM policy", "state": "ok" if J.get("cam_procurement_policy") else "off"},
                    {"label": f"EcoVadis: {eco}", "state": "off" if eco in ("none", "None") else "ok"},
                    {"label": "LEED/BREEAM exp.", "state": "ok" if K.get("leed_breeam_site_credits") else "off"},
                ]
            srcs = _Sources(e.get("sources"), (e.get("K_reporting_compliance") or {}).get("report_url") or "")
            profile = _profile_rows([
                ("Headquarters", e.get("hq")),
                ("Offices", e.get("offices")),
                ("Ownership", e.get("ownership")),
                ("Revenue", e.get("revenue_eur")),
                ("Employees", e.get("employees")),
                ("Countries", e.get("countries")),
                ("Listed on", e.get("listed_exchange")),
                ("Focus" if etype == "specifiers" else "Specializations", tags),
                ("Website", e.get("website")),
            ], srcs)
            ifw_groups = _ifw_groups(etype, e, score, srcs)
            notes_urls = srcs.alias("notes", "Analyst notes")
            out[etype].append({
                "id": f"{etype[0]}::{name}", "name": name, "sector": sector, "hq": (e.get("hq") or ""),
                "tier": tier, "tierRank": tier_rank.get(tier, 99), "credTier": "",
                "score": score["total"], "hasIfw": True, "logo": "", "products": 0,
                "pills": pills, "fw": _framework_hits(e, fw_matrix, ind_key),
                "profile": profile, "narrative": "", "reportUrl": "", "notes": (e.get("notes") or ""),
                "notesUrls": notes_urls,
                "credentials": [], "ifwGroups": ifw_groups, "sources": srcs.listing(),
                "search": " ".join([name, (e.get("hq") or ""), sector, (e.get("notes") or ""),
                                    " ".join(map(str, tags))]).lower(),
            })

    frameworks = []
    for k in fw_matrix:
        s = _fw_short(k)
        if s not in frameworks:
            frameworks.append(s)
    return {"entities": out, "etypes": _ETYPES, "tiers": tiers, "frameworks": frameworks}


@st.cache_data(show_spinner=False, max_entries=4)
def _product_counts(data_sig: tuple) -> dict:
    """Products per manufacturer in the effective dataset (base ⊕ edits).

    ``data_sig`` is app.py's ``_data_fingerprint``; it only keys the cache.
    """
    try:
        df = fn159_effective_dataset(["A__Manufacturer"])
        if "A__Manufacturer" in df.columns:
            return {str(k): int(v) for k, v in df["A__Manufacturer"].value_counts().items()}
    except Exception:
        pass
    return {}


def _json_mtimes() -> tuple:
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in _DATA_FILES)


def _render_directory() -> None:
    payload = _build_payload(_json_mtimes(), _product_counts(st.session_state.get("_data_fingerprint")))
    height = fn359_iframe_height("manufacturers")
    html_tpl = read_iframe_component(_COMPONENT)
    links = font_links_html()
    if links:
        html_tpl = html_tpl.replace("<head>", f"<head>{links}", 1)
    injection = (
        f"<style>:root{{{js2_typography_root_css()}{card_name_divider_root_css()}}}</style>\n"
        f"<script>window.__MFR_DATA__={json.dumps(payload, ensure_ascii=False)};"
        f"window.__MFR_HEIGHT__={int(height)};</script>\n"
    )
    st.iframe(html_tpl.replace("</head>", injection + "</head>", 1), height=height)


def _table_filters(key: str, sust: dict) -> list[str]:
    """Sector / tier / search row for the table tabs; returns the matching manufacturers."""
    creds = sust["credentials"]
    sectors = sust["sectors"]
    c1, c2, c3 = st.columns([2, 2, 3])
    sector = c1.selectbox("Sector", ["All sectors"] + sorted(sectors), key=f"{key}_sector")
    tier = c2.selectbox("Maturity tier", ["All tiers"] + list(sust["maturity_tiers"]), key=f"{key}_tier")
    q = c3.text_input("Search manufacturer", placeholder="e.g. Holcim, Florim…", key=f"{key}_q")
    mfrs = list(creds)
    if sector != "All sectors":
        mfrs = [m for m in mfrs if m in set(sectors.get(sector, []))]
    if tier != "All tiers":
        mfrs = [m for m in mfrs if creds[m].get("maturity") == tier]
    if q.strip():
        mfrs = [m for m in mfrs if q.strip().lower() in m.lower()]
    st.caption(f"Showing **{len(mfrs)}** of {len(creds)} manufacturers")
    return mfrs


# ── Monograph ────────────────────────────────────────────────────────────────
# Widget keys start with ``mono_`` so fn353a_keep_widget_state keeps them across
# lazy-tab switches; button keys must not (Streamlit refuses state writes to them).

_MONO_TREEMAPS = (
    ("D__ProductType_ENG", "Product types", "type"),
    ("D__MaterialType_ENG", "Material types", "material"),
)
_MONO_TREEMAP_LABELS = {col: title[:-1].lower() for col, title, _ in _MONO_TREEMAPS}
_MONO_BADGE_COLORS = {"ok": "green", "partial": "orange", "warn": "orange"}


@st.cache_data(max_entries=4, show_spinner=False)
def _mono_known_names(mtimes: tuple) -> frozenset:
    inputs = _record_inputs()
    return frozenset(set(inputs["creds"]) | set(inputs["profiles"]) | set(inputs["ifw_mfr"]))


@st.cache_data(max_entries=64, show_spinner=False)
def _mono_profile(profile_name: str, n_products: int, mtimes: tuple) -> dict:
    """The Directory record for one profile key, plus its website for the header line."""
    inputs = _record_inputs()
    rec = _manufacturer_record(profile_name, n_products=n_products, **inputs)
    p = inputs["profiles"].get(profile_name) or {}
    e = inputs["ifw_mfr"].get(profile_name) or {}
    rec["website"] = str(p.get("website") or e.get("website") or "")
    return rec


@st.cache_data(max_entries=64, show_spinner=False)
def _mono_logo(name: str, mtimes: tuple) -> str:
    logo_map = fn312_get_manufacturer_logo_mapping(str(_APP_ROOT / "aux__ui_config.json"))
    return _logo_resolver(logo_map)(name)


def _uri_image(uri: str):
    """``st.image`` input from a data URI: SVG markup or raw PNG bytes."""
    head, _, b64 = uri.partition(",")
    raw = base64.b64decode(b64)
    return raw.decode("utf-8") if "svg" in head else raw


def _md_badge(label: str, color: str) -> str:
    clean = str(label).replace("[", "(").replace("]", ")")
    return f":{color}-badge[{clean}]"


def _mono_bump_treemaps() -> None:
    """Fresh treemap keys, so a stale click highlight doesn't outlive its filter."""
    for _, _, slug in _MONO_TREEMAPS:
        k = f"mono_tm_nonce_{slug}"
        st.session_state[k] = int(st.session_state.get(k, 0)) + 1


def _mono_clear_filter() -> None:
    st.session_state.pop("mono_tm_filter", None)
    _mono_bump_treemaps()


def _mono_on_treemap_select(chart_key: str, column: str, known: tuple, other_slug: str) -> None:
    """Treemap click → the single active filter (a click on the other treemap replaces it)."""
    try:
        pts = st.session_state[chart_key].selection.points or []
    except Exception:
        pts = []
    selected = None
    for pt in pts:
        if not isinstance(pt, dict):
            continue
        cd = pt.get("customdata")
        cand = cd[0] if isinstance(cd, (list, tuple)) and cd else (pt.get("label") or pt.get("id"))
        if cand in (None, ""):
            continue
        cand = str(cand).strip()
        if cand.lower() in ("", "root", "(?)", "/"):
            continue
        if cand in known:
            selected = cand
            break
    if selected:
        st.session_state["mono_tm_filter"] = (column, selected)
        k = f"mono_tm_nonce_{other_slug}"
        st.session_state[k] = int(st.session_state.get(k, 0)) + 1
    elif (st.session_state.get("mono_tm_filter") or (None,))[0] == column:
        st.session_state.pop("mono_tm_filter", None)


def _monograph_picker(df_all: pd.DataFrame, data_sig) -> str | None:
    opts = fn600_manufacturer_options(df_all, data_sig)
    counts = dict(opts)
    qp = st.query_params.get("mfr")
    if qp and qp in counts and "mono_manufacturer" not in st.session_state:
        st.session_state["mono_manufacturer"] = qp
    name = st.selectbox(
        "Manufacturer",
        options=[n for n, _ in opts],
        format_func=lambda n: f"{n}  ·  {counts.get(n, 0)} products",
        key="mono_manufacturer",
        index=None,
        placeholder="Choose a manufacturer",
        help="Showing every product from this manufacturer. Sidebar filters don't apply on this tab.",
    )
    if not name:
        return None
    if st.query_params.get("mfr") != name:
        st.query_params["mfr"] = name
    return name


def _fmt_pp(v: float, ref: float) -> str | None:
    if pd.isna(v) or pd.isna(ref):
        return None
    return f"{v - ref:+.0f} pp vs library"


def _monograph_profile_rec(name: str, df_m: pd.DataFrame):
    """Resolved company profile record + logo URI for *name*."""
    mtimes = _json_mtimes()
    profile_name = fn601_resolve_profile_name(name, _mono_known_names(mtimes))
    rec = _mono_profile(profile_name, len(df_m), mtimes) if profile_name else None
    logo = (rec or {}).get("logo") or _mono_logo(name, mtimes)
    return rec, logo


def _monograph_title_block(name: str, rec: dict | None, logo) -> None:
    """Logo + company name, sector / HQ / badges (left column)."""
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        if logo:
            try:
                st.image(_uri_image(logo), width=56)
            except Exception:
                pass
        with st.container(gap="small"):
            st.markdown(f"### {name}")
            if rec:
                bits = [
                    str(x)
                    for x in (
                        rec.get("sector"),
                        f"HQ {rec['hq']}" if rec.get("hq") else "",
                    )
                    if x
                ]
                if rec.get("website", "").startswith("http"):
                    bits.append(f"[website]({rec['website']})")
                if bits:
                    st.markdown(" · ".join(bits))
                badges = [
                    _md_badge(
                        p["label"],
                        _MONO_BADGE_COLORS.get(p.get("state"), "gray"),
                    )
                    for p in rec.get("pills", [])
                ]
                if rec.get("tier"):
                    badges.append(_md_badge(f"Tier: {rec['tier']}", "blue"))
                if rec.get("score") is not None:
                    badges.append(
                        _md_badge(f"Impact score {rec['score']:.0f}/100", "violet")
                    )
                if badges:
                    st.markdown(" ".join(badges))
            else:
                st.caption("No company profile yet for this manufacturer.")


def _monograph_kpi_row(name: str, df_m: pd.DataFrame, df_all: pd.DataFrame, data_sig) -> None:
    """Three compact KPI metrics (Products / EPD / completeness)."""
    k = fn607_kpis(df_m, df_all, name, data_sig)
    comp_m = fn604_completeness_by_group(df_m, name, data_sig)
    comp_lib = fn604_completeness_by_group(df_all, "__library__", data_sig)
    overall_m = float(comp_m["pct"].iloc[-1])
    overall_lib = float(comp_lib["pct"].iloc[-1])
    st.markdown(
        "<style>"
        ".st-key-mono_kpi_header [data-testid='stMetric'] "
        "{ padding: 0.35rem 0.55rem !important; }"
        ".st-key-mono_kpi_header [data-testid='stMetricLabel'] p "
        "{ font-size: 0.72rem !important; line-height: 1.15 !important; "
        "white-space: normal !important; }"
        ".st-key-mono_kpi_header [data-testid='stMetricValue'] "
        "{ font-size: 1.15rem !important; }"
        ".st-key-mono_kpi_header [data-testid='stMetricDelta'] "
        "{ font-size: 0.7rem !important; }"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="mono_kpi_header"):
        c_prod, c_epd, c_comp = st.columns(
            [1.5, 1.5, 1.5], gap="small", vertical_alignment="center"
        )
        with c_prod:
            st.metric(
                "Products", k["n"],
                help="Catalogue-listed products (A__Map_yn = Y)", border=True,
            )
        with c_epd:
            st.metric(
                "With EPD",
                "—" if pd.isna(k["epd_pct"]) else f"{k['epd_pct']:.0f}%",
                delta=_fmt_pp(k["epd_pct"], k["epd_pct_lib"]), border=True,
                help="EPD flag set, or an EPD registration number / URL recorded.",
            )
        with c_comp:
            st.metric(
                "Data completeness",
                "—" if pd.isna(overall_m) else f"{overall_m:.0f}%",
                delta=_fmt_pp(overall_m, overall_lib), border=True,
                help="Filled cells over applicable cells, across the field groups below.",
            )


_MONO_PROFILE_ORDER = ("Headquarters", "Parent", "Ownership", "Revenue", "Employees",
                       "Countries", "Listed on", "Website", "Products in library")
_MONO_PROFILE_OPTIONAL = {"Parent", "Listed on"}


def _monograph_profile_extras(rec: dict | None, n_products: int = 0) -> None:
    """Company profile card — same visual language as the Interactive monograph JS.

    The core rows always show (— when unknown), so every manufacturer reads alike.
    """
    rec = rec or {}
    have = {str(r[0]): r for r in rec.get("profile", []) if r and len(r) >= 2}
    rows = []
    for label in _MONO_PROFILE_ORDER:
        if label in have:
            rows.append(have[label])
        elif label == "Products in library":
            rows.append([label, str(int(n_products or 0))])
        elif label not in _MONO_PROFILE_OPTIONAL:
            rows.append([label, "—"])
    rows += [r for k, r in have.items() if k not in _MONO_PROFILE_ORDER]
    narrative = str(rec.get("narrative") or "").strip()
    report = str(rec.get("reportUrl") or "").strip()

    # Match 02_html/monograph_component.html (.prof / details / .btn).
    parts: list[str] = []
    if rows:
        row_html = []
        for r in rows:
            label = _html.escape(str(r[0]))
            # Linked values already carry an <a> from _profile_rows; plain text is escaped.
            if len(r) > 3 and r[3]:
                val = str(r[1])
            else:
                val = _html.escape(str(r[1]))
            row_html.append(
                f'<div><span class="mono-prof-k">{label}</span>'
                f'<span class="mono-prof-v">{val}</span></div>'
            )
        parts.append(f'<div class="mono-prof">{"".join(row_html)}</div>')
    if narrative:
        parts.append(
            "<details class='mono-narr'>"
            "<summary>Sustainability summary</summary>"
            f"<p>{_html.escape(narrative)}</p>"
            "</details>"
        )
    if report.startswith("http"):
        parts.append(
            f'<div class="mono-prof-actions">'
            f'<a class="mono-btn" href="{_html.escape(report, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Sustainability report ↗</a>'
            f"</div>"
        )

    st.markdown(
        "<style>"
        ".mono-profile-card{"
        "margin:0.15rem 0 0.75rem;padding:0;"
        "font-family:var(--eetra-ff-sans,'Miranda Sans',system-ui,sans-serif);"
        "font-size:13px;line-height:1.45;color:var(--eetra-text,#1e293b);}"
        ".mono-prof{display:grid;grid-template-columns:minmax(0,1fr);gap:4px;"
        "margin-top:4px;padding-top:12px;border-top:1px solid var(--eetra-border,#e2e8f0);}"
        ".mono-prof>div{display:flex;gap:8px;font-size:12px;min-width:0;}"
        ".mono-prof-k{color:var(--eetra-text-muted,#64748b);flex:0 0 118px;}"
        ".mono-prof-v{min-width:0;overflow-wrap:anywhere;}"
        ".mono-prof-v a{color:var(--eetra-green,#2a7d2e);text-decoration:none;}"
        ".mono-prof-v a:hover{text-decoration:underline;}"
        ".mono-narr{margin-top:10px;}"
        ".mono-narr summary{cursor:pointer;color:var(--eetra-text-muted,#64748b);font-size:12px;}"
        ".mono-narr p{margin-top:6px;font-size:12px;white-space:pre-line;}"
        ".mono-prof-actions{margin-top:10px;}"
        ".mono-btn{display:inline-flex;align-items:center;gap:6px;font-size:12px;"
        "padding:5px 11px;border-radius:8px;border:1px solid var(--eetra-border-card,#d1d9e6);"
        "background:var(--eetra-surface,#fff);color:var(--eetra-text,#1e293b);"
        "text-decoration:none;}"
        ".mono-btn:hover{border-color:var(--eetra-hover-border,#b8c5d8);text-decoration:none;}"
        "</style>"
        f"<div class='mono-profile-card'>{''.join(parts)}</div>",
        unsafe_allow_html=True,
    )


def _monograph_composition(df_m: pd.DataFrame, name: str, data_sig):
    if st.session_state.get("mono_tm_filter_for") != name:
        st.session_state.pop("mono_tm_filter", None)
        st.session_state["mono_tm_filter_for"] = name
        _mono_bump_treemaps()

    dims = fn341_get_charts_dimensions()
    cols = st.columns(2, gap="medium")
    for i, (col, title, slug) in enumerate(_MONO_TREEMAPS):
        other_slug = _MONO_TREEMAPS[1 - i][2]
        with cols[i]:
            st.markdown(f"#### {title}")
            vc_df = fn603_value_counts(df_m, col, name, data_sig)
            if vc_df.empty:
                st.caption("No values recorded.")
                continue
            fig = px.treemap(vc_df, path=["value"], values="count", custom_data=["value"])
            fig.update_traces(
                textinfo="label+value",
                hovertemplate="<b>%{label}</b><br>%{value} products<extra></extra>",
            )
            fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0), height=260,
                font=dict(family=dims["chart_font_family"], size=dims["chart_font_size"]),
            )
            chart_key = f"mono_tm_{slug}_{int(st.session_state.get(f'mono_tm_nonce_{slug}', 0))}"
            st.plotly_chart(
                fig, width="stretch", key=chart_key,
                on_select=partial(_mono_on_treemap_select, chart_key, col,
                                  tuple(vc_df["value"].astype(str)), other_slug),
                selection_mode="points",
                config={"displayModeBar": False},
            )
    sel = st.session_state.get("mono_tm_filter")
    return tuple(sel) if sel else None


@st.fragment
def _monograph_heatmap(df_m: pd.DataFrame) -> None:
    if not st.toggle("Show product × field heatmap", key="mono_show_heatmap"):
        return
    cols = fn608_field_group_columns(df_m.columns)
    payload = fn344_build_dev_missmatrix_payload(df_m, cols, id_col=None, batch_size=30)
    if not payload:
        st.caption("No fields to show.")
        return
    h = min(920, max(520, 220 + 30 * 20))
    st.iframe(fn240_build_dev_missmatrix_html(payload, height=h), height=h)


def _monograph_quality(df_m: pd.DataFrame, df_all: pd.DataFrame, name: str, data_sig) -> None:
    st.markdown("#### Data quality")
    accent = _token("colors", "green")
    tick_color = _token("colors", "text")
    dims = fn341_get_charts_dimensions()
    order = [g for g, _ in FIELD_GROUPS]

    comp_m = fn604_completeness_by_group(df_m, name, data_sig)
    comp_lib = fn604_completeness_by_group(df_all, "__library__", data_sig)
    dq = comp_m[comp_m["group"] != "Overall"].merge(
        comp_lib[["group", "pct"]].rename(columns={"pct": "lib_pct"}), on="group", how="left",
    )

    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown("**Completeness by field group**")
        tooltip = [
            alt.Tooltip("group:N", title="Group"),
            alt.Tooltip("pct:Q", title="This manufacturer (%)", format=".0f"),
            alt.Tooltip("lib_pct:Q", title="Library (%)", format=".0f"),
            alt.Tooltip("filled:Q", title="Filled cells"),
            alt.Tooltip("applicable:Q", title="Applicable cells"),
        ]
        base = alt.Chart(dq).encode(y=alt.Y("group:N", sort=order, title=None))
        bars = base.mark_bar(color=accent).encode(
            x=alt.X("pct:Q", scale=alt.Scale(domain=[0, 100]), title="Completeness (%)"),
            tooltip=tooltip,
        )
        ticks = base.mark_tick(color=tick_color, thickness=2, size=20, strokeDash=[3, 3]).encode(
            x="lib_pct:Q", tooltip=tooltip,
        )
        chart = (bars + ticks).properties(height=220).configure_axis(
            labelFont=dims["chart_font_family"], titleFont=dims["chart_font_family"],
        )
        st.altair_chart(chart, width="stretch")
        st.caption(
            "Dashed tick = library average. Fields marked not relevant (n/r) or hidden for "
            "a product type are excluded."
        )
    with right:
        st.markdown("**Richness per product**")
        rich = fn605_richness_per_product(df_m, name, data_sig)
        hist = (rich["bin_label"].value_counts().reindex(RICHNESS_BINS, fill_value=0)
                .rename_axis("bin_label").reset_index(name="products"))
        chart = alt.Chart(hist).mark_bar(color=accent).encode(
            x=alt.X("bin_label:O", sort=RICHNESS_BINS, title="Product completeness",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("products:Q", title="Products"),
            tooltip=[alt.Tooltip("bin_label:O", title="Completeness"),
                     alt.Tooltip("products:Q", title="Products")],
        ).properties(height=220).configure_axis(
            labelFont=dims["chart_font_family"], titleFont=dims["chart_font_family"],
        )
        st.altair_chart(chart, width="stretch")
        docs = fn606_document_counts(df_m)
        if docs:
            st.caption("Products with a document link: " + " · ".join(f"{k} {v}" for k, v in docs.items()))

    _monograph_heatmap(df_m)


def _prices_sig() -> tuple:
    try:
        from libs.lib_prices import fn500_prices_data_dir
        return tuple(sorted((p.name, p.stat().st_mtime) for p in fn500_prices_data_dir().glob("price_*.parquet")))
    except Exception:
        return ()


@st.cache_data(max_entries=32, show_spinner=False)
def _mono_price_tables(_df_m: pd.DataFrame, manufacturer: str, data_sig, prices_sig: tuple) -> dict:
    """fn512 for the whole manufacturer (~1 s for the largest one); filtered per view by id."""
    try:
        from libs.lib_prices import fn512_price_tables_payload
        return fn512_price_tables_payload(_df_m)
    except Exception:
        return {}


@st.fragment
def _monograph_catalogue(df_m: pd.DataFrame, selection, name: str, data_sig,
                         show_heading: bool = True) -> None:
    df_cards = df_m
    if selection:
        col, val = selection
        df_cards = fn322a_rows_matching_treemap_value(df_m, col, val)
    if show_heading:
        st.markdown(f"#### Products · {len(df_cards)}")
    if df_cards.empty:
        fn356_empty_state("No products match this selection.", kind="empty")
        return
    if "A__ProductName" in df_cards.columns:
        df_cards = df_cards.sort_values("A__ProductName", kind="mergesort")
    price_tables = _mono_price_tables(df_m, name, data_sig, _prices_sig())
    if selection and price_tables and "0__EETRA_ID" in df_cards.columns:
        ids = set(df_cards["0__EETRA_ID"].astype(str))
        price_tables = {k: v for k, v in price_tables.items() if k in ids}
    from libs.lib_html import CATALOGUE_JS2_COMPONENT_PATH
    fn336_render_catalogue_flipcard(
        df_cards,
        cols=6,
        height=max(int(_lib_ui.CATALOGUE_STREAMLIT_GRID_HEIGHT_PX), fn359_iframe_height("catalogue_js")),
        _component_path=CATALOGUE_JS2_COMPONENT_PATH,
        price_tables=price_tables,
    )


# ── Monograph · Interactive view (02_html/monograph_component.html) ────────
# Same numbers as the Standard view — every figure comes from the same cached
# helpers — drawn by one HTML/ECharts component. Treemap clicks filter the
# catalogue iframe below client-side (see the component's header comment), so the
# Streamlit-side treemap filter (mono_tm_filter) is not used in this view.

_MONO_VIEWS = ("Interactive", "Standard")
_MONO_TREEMAP_FIELDS = {"D__ProductType_ENG": ("prod", "Product type"),
                        "D__MaterialType_ENG": ("mat", "Material type")}


def _nan_to_none(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def _mono_js_payload(name: str, df_m: pd.DataFrame, df_all: pd.DataFrame, data_sig) -> dict:
    """``window.__MONO__`` for the Interactive view, assembled from the cached helpers."""
    mtimes = _json_mtimes()
    profile_name = fn601_resolve_profile_name(name, _mono_known_names(mtimes))
    rec = _mono_profile(profile_name, len(df_m), mtimes) if profile_name else None
    rec = rec or {}

    k = fn607_kpis(df_m, df_all, name, data_sig)
    comp_m = fn604_completeness_by_group(df_m, name, data_sig)
    comp_lib = fn604_completeness_by_group(df_all, "__library__", data_sig)
    lib_pct = dict(zip(comp_lib["group"], comp_lib["pct"]))
    completeness = [
        {"group": r.group, "pct": _nan_to_none(r.pct), "libPct": _nan_to_none(lib_pct.get(r.group)),
         "filled": int(r.filled), "applicable": int(r.applicable)}
        for r in comp_m.itertuples(index=False) if r.group != "Overall"
    ]
    rich = fn605_richness_per_product(df_m, name, data_sig)
    hist = rich["bin_label"].value_counts().reindex(RICHNESS_BINS, fill_value=0)

    treemaps = []
    for col, title, _slug in _MONO_TREEMAPS:
        vc = fn603_value_counts(df_m, col, name, data_sig)
        field, chip = _MONO_TREEMAP_FIELDS[col]
        treemaps.append({
            "title": title, "field": field, "chipLabel": chip,
            "data": [{"name": str(v), "value": int(c)} for v, c in zip(vc.get("value", []), vc.get("count", []))],
        })

    website = str(rec.get("website") or "")
    return {
        "name": name,
        "profileFound": bool(profile_name),
        "logo": rec.get("logo") or _mono_logo(name, mtimes) or "",
        "sector": rec.get("sector") or "",
        "hq": rec.get("hq") or "",
        "website": website if website.startswith("http") else "",
        "pills": [{"label": p.get("label", ""), "state": p.get("state") or "off", "title": p.get("title", "")}
                  for p in rec.get("pills", [])],
        "tier": rec.get("tier") or "",
        "score": _nan_to_none(rec.get("score")),
        # [label, value, is_link] — link values are the anchors _profile_rows built
        # (URL already escaped); everything else is escaped by the component.
        "profile": [[str(r[0]), str(r[1]), bool(len(r) > 3 and r[3])]
                    for r in rec.get("profile", []) if r and len(r) >= 2],
        "narrative": rec.get("narrative") or "",
        "reportUrl": rec.get("reportUrl") if str(rec.get("reportUrl") or "").startswith("http") else "",
        "kpis": {
            "n": k["n"], "epdPct": _nan_to_none(k["epd_pct"]), "epdPctLib": _nan_to_none(k["epd_pct_lib"]),
            "gwpMedian": _nan_to_none(k["gwp_median"]), "gwpUnit": k["gwp_unit"] or "",
            "completeness": _nan_to_none(comp_m["pct"].iloc[-1]),
            "completenessLib": _nan_to_none(comp_lib["pct"].iloc[-1]),
        },
        "treemaps": treemaps,
        "completeness": completeness,
        "richness": [{"bin": b, "products": int(n)} for b, n in hist.items()],
        "docs": fn606_document_counts(df_m),
        # Interactive iframe renders the fancy title + KPI strip + profile.
        "chartsOnly": False,
    }


def _mono_js_iframe(payload: dict) -> None:
    html_tpl = read_iframe_component(_MONO_JS_COMPONENT)
    links = font_links_html()
    if links:
        html_tpl = html_tpl.replace("<head>", f"<head>{links}", 1)
    # "</" escaped so a value can never close the <script> element early.
    data = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    injection = (
        f"<style>:root{{{js2_typography_root_css()}}}</style>\n"
        f"<script>window.__MONO__={data};</script>\n"
    )
    st.iframe(html_tpl.replace("</head>", injection + "</head>", 1), height="content")


def _render_monograph_js(name: str, df_m: pd.DataFrame, df_all: pd.DataFrame, data_sig,
                         head_slot, treemap_slot) -> None:
    payload = _mono_js_payload(name, df_m, df_all, data_sig)
    # Company panel (title + profile + stacked KPIs) left, Product / Material type
    # treemaps as tabs right; the main iframe below carries the data-quality charts.
    with head_slot:
        _mono_js_iframe({**payload, "part": "head"})
    with treemap_slot:
        _mono_js_iframe({**payload, "part": "treemaps"})
    _mono_js_iframe({**payload, "chartsOnly": True})
    _monograph_heatmap(df_m)
    _monograph_catalogue(df_m, None, name, data_sig, show_heading=False)


def _render_monograph() -> None:
    if not st.session_state.get("df_filtered_ready"):
        fn356_empty_state("Loading data…", hint="Give it a moment, or check the data source on Welcome.")
        return
    df_all = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
    if df_all.empty or "A__Manufacturer" not in df_all.columns:
        fn356_empty_state("No product data available.", kind="warn")
        return
    if "A__Map_yn" in df_all.columns:
        df_all = df_all[df_all["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"]
    data_sig = st.session_state.get("_data_fingerprint") or (len(df_all),)

    # Manufacturer + View live at the bottom of the sidebar. This only runs while the
    # Monograph tab is open (lazy tabs), so the controls show on this tab alone;
    # fn353a keeps their mono_ values across tab switches.
    with st.sidebar:
        st.divider()
        st.caption("Monograph")
        name = _monograph_picker(df_all, data_sig)
        # Seeded rather than default=: fn353a re-saves mono_view through Session
        # State, and default= plus a state write logs a duplicate-value warning.
        st.session_state.setdefault("mono_view", _MONO_VIEWS[0])
        view = st.segmented_control(
            "View", _MONO_VIEWS, key="mono_view",
            help="Interactive: designed charts, and treemap clicks filter the products "
                 "without reloading. Standard: native Streamlit elements.",
        ) or _MONO_VIEWS[0]
    if not name:
        fn356_empty_state("Choose a manufacturer in the sidebar to see its monograph.", kind="empty")
        return

    c_left, c_right = st.columns([6, 6], gap="medium", vertical_alignment="top")

    df_m = fn602_manufacturer_rows(df_all, name)
    interactive = view == "Interactive" and _MONO_JS_COMPONENT.exists()

    if interactive:
        # Company panel (left) + tabbed treemaps (right), then the remaining charts.
        _render_monograph_js(name, df_m, df_all, data_sig, c_left, c_right)
        return

    # Standard: Streamlit title (left) + KPIs (right), then profile + charts.
    rec, logo = _monograph_profile_rec(name, df_m)
    with c_left:
        _monograph_title_block(name, rec, logo)
    with c_right:
        _monograph_kpi_row(name, df_m, df_all, data_sig)

    _monograph_profile_extras(rec, len(df_m))

    selection = _monograph_composition(df_m, name, data_sig)
    _monograph_quality(df_m, df_all, name, data_sig)
    if selection:
        col, val = selection
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(_md_badge(f"{_MONO_TREEMAP_LABELS.get(col, col).capitalize()}: {val}", "green"))
            st.button("Clear", key="monoclear_tm_filter", icon=":material/close:",
                      on_click=_mono_clear_filter, type="tertiary")
    _monograph_catalogue(df_m, selection, name, data_sig)


# ── Evaluation framework ─────────────────────────────────────────────────────
# Reference view over aux_companies_impact_framework.json → evaluation_framework.
# Read-only: it documents *what* is asked of a manufacturer and *why* it counts,
# so that Compliance (obligation, a gate) is never silently scored as Merito.

_EVF_LEVEL_CSS = {
    "Core": ("#e0f2fe", "#075985"),
    "Core-se-applicabile": ("#ede9fe", "#5b21b6"),
    "Advanced": ("#ccfbf1", "#115e59"),
}
_EVF_NATURE_CSS = {
    "Compliance": ("#eef2f7", "#475569"),
    "Compliance condizionata": ("#fef3c7", "#78350f"),
    "Merito": ("#dcfce7", "#14532d"),
}

_EVF_CSS = (
    "<style>"
    ".evf-wrap{font-family:var(--eetra-ff-sans,'Miranda Sans',system-ui,sans-serif);"
    "color:var(--eetra-text,#1e293b);}"
    ".evf-tbl{width:100%;table-layout:fixed;border-collapse:collapse;font-size:12.5px;"
    "line-height:1.45;margin:2px 0 18px;}"
    ".evf-tbl th{text-align:left;font-size:11px;letter-spacing:.04em;text-transform:uppercase;"
    "color:var(--eetra-text-muted,#64748b);font-weight:600;padding:6px 10px;"
    "border-bottom:1px solid var(--eetra-border,#e2e8f0);}"
    ".evf-tbl td{padding:9px 10px;vertical-align:top;"
    "border-bottom:1px solid var(--eetra-border,#eef2f7);overflow-wrap:anywhere;}"
    ".evf-tbl tr:hover td{background:var(--eetra-surface-hover,#f8fafc);}"
    ".evf-ev{font-weight:600;width:15%;}"
    ".evf-lv{width:13%;} .evf-nt{width:15%;} .evf-cond{width:25%;}"
    ".evf-cond-empty{color:var(--eetra-text-muted,#94a3b8);}"
    ".evf-note{display:block;margin-top:5px;font-size:11.5px;font-style:italic;"
    "color:var(--eetra-text-muted,#64748b);}"
    ".evf-badge{display:inline-block;padding:3px 8px;border-radius:6px;"
    "font-size:10.5px;font-weight:600;line-height:1.35;white-space:normal;"
    "max-width:100%;}"
    ".evf-src{display:block;margin-top:5px;font-size:10.5px;"
    "color:var(--eetra-text-muted,#94a3b8);}"
    "</style>"
)


def _evf_badge(label: str, palette: dict) -> str:
    bg, fg = palette.get(label, ("#f1f5f9", "#475569"))
    return (
        f"<span class='evf-badge' style='background:{bg};color:{fg}'>"
        f"{_html.escape(label)}</span>"
    )


def _evf_source_marker(row: dict) -> str:
    """Flag rows whose level was reclassified away from the source document's."""
    src = str(row.get("Livello fonte") or "").strip()
    if not src or src == str(row.get("Livello") or "").strip():
        return ""
    return f"<span class='evf-src'>documento: {_html.escape(src)}</span>"


def _evf_table_html(rows: pd.DataFrame) -> str:
    head = (
        "<tr><th class='evf-ev'>Evidenza</th><th class='evf-lv'>Livello</th>"
        "<th class='evf-nt'>Natura</th><th class='evf-cond'>Dipendenza condizionale</th>"
        "<th>Criterio</th></tr>"
    )
    body = []
    for r in rows.to_dict("records"):
        cond = str(r.get("Dipendenza condizionale") or "").strip()
        cond_html = (
            _html.escape(cond) if cond
            else "<span class='evf-cond-empty'>— sempre applicabile</span>"
        )
        note = str(r.get("Nota") or "").strip()
        note_html = f"<span class='evf-note'>{_html.escape(note)}</span>" if note else ""
        body.append(
            "<tr>"
            f"<td class='evf-ev'>{_html.escape(str(r.get('Evidenza', '')))}</td>"
            f"<td class='evf-lv'>{_evf_badge(str(r.get('Livello', '')), _EVF_LEVEL_CSS)}"
            f"{_evf_source_marker(r)}</td>"
            f"<td class='evf-nt'>{_evf_badge(str(r.get('Natura', '')), _EVF_NATURE_CSS)}</td>"
            f"<td class='evf-cond'>{cond_html}</td>"
            f"<td>{_html.escape(str(r.get('Criterio', '')))}{note_html}</td>"
            "</tr>"
        )
    return f"<table class='evf-tbl'>{head}{''.join(body)}</table>"


def _render_evaluation_framework() -> None:
    df, meta = fn140h_evaluation_framework()
    if df.empty:
        st.info(
            "No `evaluation_framework` block found in aux_companies_impact_framework.json."
        )
        return

    st.markdown(
        "Le evidenze richieste a un produttore, organizzate in "
        f"**{df['Macroarea'].nunique()} macroaree**. Ogni voce porta il **livello** "
        "(soglia attesa) e la **natura** del requisito: *Compliance* è un obbligo di "
        "legge e va trattato come gate di ammissibilità, non come punteggio; solo il "
        "*Merito* misura la maturità."
    )

    with st.expander("Legenda e regola di punteggio", expanded=False):
        lv, nt = st.columns(2)
        with lv:
            st.markdown("**Livelli**")
            for k, v in (meta.get("levels") or {}).items():
                st.markdown(f"- {_md_badge(k, 'blue')} {v}")
        with nt:
            st.markdown("**Natura del requisito**")
            _nat_colors = {
                "Compliance": "gray",
                "Compliance condizionata": "orange",
                "Merito": "green",
            }
            for k, v in (meta.get("natures") or {}).items():
                st.markdown(f"- {_md_badge(k, _nat_colors.get(k, 'blue'))} {v}")
        if meta.get("scoring_rule"):
            st.markdown(f"**Regola di punteggio** — {meta['scoring_rule']}")
        if meta.get("source_level_note"):
            st.markdown(f"**Livello del documento sorgente** — {meta['source_level_note']}")
        if meta.get("track"):
            st.caption(meta["track"])

    c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
    area = c1.selectbox(
        "Macroarea", ["Tutte le macroaree"] + list(dict.fromkeys(df["Macroarea"])),
        key="mfr_evf_area",
    )
    level = c2.selectbox(
        "Livello", ["Tutti i livelli"] + list(_EVF_LEVEL_CSS), key="mfr_evf_level",
    )
    nature = c3.selectbox(
        "Natura", ["Tutte le nature"] + list(_EVF_NATURE_CSS), key="mfr_evf_nature",
    )
    q = c4.text_input(
        "Cerca evidenza", placeholder="es. EPD, CAM, ISO…", key="mfr_evf_q",
    )

    view = df
    if area != "Tutte le macroaree":
        view = view[view["Macroarea"] == area]
    if level != "Tutti i livelli":
        view = view[view["Livello"] == level]
    if nature != "Tutte le nature":
        view = view[view["Natura"] == nature]
    if q.strip():
        needle = q.strip().lower()
        view = view[
            view["Evidenza"].str.lower().str.contains(needle, regex=False)
            | view["Criterio"].str.lower().str.contains(needle, regex=False)
            | view["Dipendenza condizionale"].str.lower().str.contains(needle, regex=False)
        ]

    if view.empty:
        st.info("Nessuna evidenza corrisponde ai filtri correnti.")
        return

    cols = st.columns(6)
    for col, (label, series, value) in zip(
        cols,
        [(k, "Livello", k) for k in _EVF_LEVEL_CSS]
        + [(k, "Natura", k) for k in _EVF_NATURE_CSS],
    ):
        col.metric(label, int((view[series] == value).sum()))
    st.caption(
        f"**{len(view)}** evidenze su {len(df)} · "
        f"{int((view['Natura'] == 'Merito').sum())} valutabili a punteggio, "
        f"{int((view['Natura'] != 'Merito').sum())} da trattare come gate di compliance."
    )

    st.markdown(_EVF_CSS, unsafe_allow_html=True)
    for _, area_label in sorted(
        {(int(r), a) for r, a in zip(view["_area_order"], view["Macroarea"])}
    ):
        rows = view[view["Macroarea"] == area_label]
        st.markdown(f"#### {area_label}")
        st.markdown(
            f"<div class='evf-wrap'>{_evf_table_html(rows)}</div>",
            unsafe_allow_html=True,
        )

    st.download_button(
        "Download CSV",
        view[[c for c in view.columns if not c.startswith("_")]]
        .to_csv(index=False).encode("utf-8-sig"),
        file_name="eetra_manufacturer_evaluation_framework.csv",
        mime="text/csv",
        icon=":material/download:",
    )
    st.caption(
        "Fonte: `aux_companies_impact_framework.json` → `evaluation_framework` "
        f"(v{meta.get('version', '—')}, {meta.get('created', '—')})."
    )


# ── Questionnaire ────────────────────────────────────────────────────────────
# Interactive supplier survey over the same evaluation_framework block.
# One Microsoft-Forms-like section per macroarea, with live branching:
#   screening No → evidence marked not applicable, details hidden
#   Sì/No main   → follow-ups and the document field open only on Sì
# Identical screening questions share an answer (Società Benefit, dipendenti).
# Company-size filter (B Lab FTE bands) runs first and drops evidence whose
# size_min is above the chosen band.
# Answers live in session_state for this session; they are not written to disk.

_EVQ_YNA = ("Sì", "No", "Non applicabile")
_EVQ_YN = ("Sì", "No")
_EVQ_LEVEL_BADGE = {
    "Core": "blue",
    "Core-se-applicabile": "violet",
    "Advanced": "green",
}
_EVQ_NATURE_BADGE = {
    "Compliance": "gray",
    "Compliance condizionata": "orange",
    "Merito": "green",
}
# B Lab Standards V2.1 worker (FTE) bands — first four sizes (revenue ignored).
_EVQ_SIZE_ORDER = ("micro", "piccola", "media", "grande")
_EVQ_SIZE_BANDS = {
    "micro": {
        "label": "Micro",
        "fte": "1–9 dipendenti",
        "help": "B Lab Micro (1–9 FTE). Allineato alla microimpresa UE.",
    },
    "piccola": {
        "label": "Piccola",
        "fte": "10–49 dipendenti",
        "help": "B Lab Small (10–49 FTE).",
    },
    "media": {
        "label": "Media",
        "fte": "50–249 dipendenti",
        "help": "B Lab Medium (50–249 FTE). Soglia whistleblowing (≥50).",
    },
    "grande": {
        "label": "Grande",
        "fte": "250+ dipendenti",
        "help": "B Lab Large e oltre (≥250 FTE).",
    },
}
_EVQ_SCREEN_ALIASES = {
    "la societa e costituita o qualificata come societa benefit?": "societa_benefit",
    "la societa ha adottato la qualifica di societa benefit?": "societa_benefit",
    "l'azienda ha lavoratori dipendenti o equiparati?": "ha_dipendenti",
}
_EVQ_INITIAL_SKIP = frozenset({
    "&", "and", "e", "of", "di", "del", "della", "delle", "the",
})
_EVQ_YEAR_OPTIONS = ("2020", "2021", "2022", "2023", "2024", "2025", "2026")
_EVQ_SASB_PATH = _APP_ROOT / "aux_sasb_sics.json"


@st.cache_data(show_spinner=False)
def _evq_load_sasb_sics() -> dict:
    """SASB SICS taxonomy (11 sectors / 77 industries)."""
    try:
        return json.loads(_EVQ_SASB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"_meta": {}, "sectors": []}


def _evq_fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return " ".join(
        "".join(c for c in nfkd if not unicodedata.combining(c)).lower().split()
    )


def _evq_screen_id(screening: str) -> str:
    folded = _evq_fold(screening)
    return _EVQ_SCREEN_ALIASES.get(folded, folded) if folded else ""


def _evq_initials(label: str) -> str:
    """Significant-word initials: Governance & Strategy → GS."""
    letters: list[str] = []
    for raw in (label or "").replace("/", " ").split():
        word = raw.strip(".,;:()")
        if not word or word.lower() in _EVQ_INITIAL_SKIP:
            continue
        letters.append(word[0].upper())
    if letters:
        return "".join(letters)
    compact = "".join(c for c in (label or "") if c.isalnum())
    return compact[:2].upper() or "XX"


def _evq_code(initials: str, n: int) -> str:
    return f"{initials}{n:02d}"


def _evq_kind(response_type: str) -> str:
    head = (response_type or "").split("+", 1)[0].strip().lower()
    if head.startswith("sì") or head.startswith("si"):
        # "Sì / No / Non applicabile" → yna; "Sì / No" alone → yn
        if "non applicabile" in head:
            return "yna"
        return "yn"
    if "quantitativ" in head:
        return "qty"
    return "text"


def _evq_is_choice(kind: str) -> bool:
    return kind in ("yn", "yna")


def _evq_choice_options(kind: str) -> tuple[str, ...]:
    return _EVQ_YNA if kind == "yna" else _EVQ_YN


def _evq_slug(qid: str) -> str:
    return "_".join(
        "".join(c.lower() if c.isalnum() else "_" for c in qid).split("_")
    )


def _evq_wkey(qid: str, field: str) -> str:
    gen = int(st.session_state.get("mfr_q_gen", 0))
    return f"mfr_q_{gen}_{_evq_slug(qid)}_{field}"


def _evq_size_rank(key: str) -> int:
    try:
        return _EVQ_SIZE_ORDER.index(key)
    except ValueError:
        return 0


def _evq_size_key() -> str:
    key = str(st.session_state.get("mfr_q_size") or "").strip().lower()
    return key if key in _EVQ_SIZE_BANDS else ""


def _evq_size_label(key: str | None = None) -> str:
    k = key or _evq_size_key()
    band = _EVQ_SIZE_BANDS.get(k) or {}
    if not band:
        return ""
    return f"{band['label']} ({band['fte']})"


def _evq_size_applies(item_or_q: dict, size_key: str) -> bool:
    """True if evidence size_min is at or below the chosen company-size band."""
    if not size_key:
        return True
    return _evq_size_rank(item_or_q.get("size_min") or "micro") <= _evq_size_rank(
        size_key
    )


def _evq_filter_areas(areas: list[dict], size_key: str | None = None) -> list[dict]:
    size = size_key if size_key is not None else _evq_size_key()
    if not size:
        return areas
    out: list[dict] = []
    for a in areas:
        qs = [q for q in a["questions"] if _evq_size_applies(q, size)]
        if qs:
            out.append({**a, "questions": qs})
    return out


def _evq_items(areas: list[dict]) -> list[dict]:
    items: list[dict] = []
    for a in areas:
        initials = _evq_initials(a["label"])
        for i, q in enumerate(a["questions"], 1):
            items.append({
                "qid": f"{a['key']}::{q['evidence']}",
                "area_key": a["key"],
                "area_label": a["label"],
                "initials": initials,
                "code": _evq_code(initials, i),
                **q,
            })
    return items


def _evq_sasb_sectors() -> list[dict]:
    return list((_evq_load_sasb_sics().get("sectors") or []))


def _evq_sasb_meta() -> dict:
    return dict((_evq_load_sasb_sics().get("_meta") or {}))


def _evq_sasb_sector_label(key: str | None = None) -> str:
    k = key if key is not None else st.session_state.get("mfr_q_sasb_sector")
    for sec in _evq_sasb_sectors():
        if sec.get("key") == k:
            return str(sec.get("label") or k or "")
    return str(k or "")


def _evq_sasb_industry() -> str:
    return str(st.session_state.get("mfr_q_sasb_industry") or "").strip()


def _evq_sasb_label() -> str:
    industry = _evq_sasb_industry()
    sector = _evq_sasb_sector_label()
    if industry and sector:
        return f"{sector} · {industry}"
    return industry or sector


def _evq_init() -> None:
    ss = st.session_state
    ss.setdefault("mfr_q_gen", 0)
    ss.setdefault("mfr_q_phase", "intro")
    ss.setdefault("mfr_q_step", 0)
    ss.setdefault("mfr_q_screens", {})
    ss.setdefault("mfr_q_submitted", False)
    ss.setdefault("mfr_q_err", "")
    ss.setdefault("mfr_q_size", None)
    ss.setdefault("mfr_q_sasb_sector", None)
    ss.setdefault("mfr_q_sasb_industry", None)


def _evq_reset() -> None:
    ss = st.session_state
    old = int(ss.get("mfr_q_gen", 0))
    prefix = f"mfr_q_{old}_"
    for k in list(ss.keys()):
        if isinstance(k, str) and k.startswith(prefix):
            del ss[k]
    ss["mfr_q_gen"] = old + 1
    ss["mfr_q_phase"] = "intro"
    ss["mfr_q_step"] = 0
    ss["mfr_q_screens"] = {}
    ss["mfr_q_submitted"] = False
    ss["mfr_q_err"] = ""
    ss["mfr_q_size"] = None
    ss["mfr_q_sasb_sector"] = None
    ss["mfr_q_sasb_industry"] = None
    for wk in (
        "mfr_q_size_widget",
        "mfr_q_sasb_sector_widget",
        "mfr_q_sasb_industry_widget",
    ):
        if wk in ss:
            del ss[wk]


def _evq_apply_size_side_effects(size_key: str) -> None:
    """Seed shared screening answers implied by the chosen headcount band."""
    if size_key in _EVQ_SIZE_BANDS:
        # All four bands start at ≥1 FTE → dipendenti = Sì.
        st.session_state.setdefault("mfr_q_screens", {})["ha_dipendenti"] = "Sì"


def _evq_get(qid: str, field: str, default=None):
    return st.session_state.get(_evq_wkey(qid, field), default)


def _evq_applicable(item: dict) -> bool:
    if not item.get("screening"):
        return True
    return _evq_get(item["qid"], "screen") != "No"


def _evq_show_details(item: dict) -> bool:
    if not _evq_applicable(item):
        return False
    if _evq_is_choice(_evq_kind(item["response_type"])):
        return _evq_get(item["qid"], "answer") == "Sì"
    return True


def _evq_answered(item: dict) -> bool:
    if item.get("screening") and _evq_get(item["qid"], "screen") not in _EVQ_YN:
        return False
    if not _evq_applicable(item):
        return True
    ans = _evq_get(item["qid"], "answer")
    kind = _evq_kind(item["response_type"])
    if _evq_is_choice(kind):
        return ans in _evq_choice_options(kind)
    return bool(str(ans or "").strip())


def _evq_status(item: dict) -> str:
    if item.get("screening") and _evq_get(item["qid"], "screen") not in _EVQ_YN:
        return "missing"
    if not _evq_applicable(item):
        return "na"
    if _evq_answered(item):
        return "done"
    if item.get("level") in ("Core", "Core-se-applicabile"):
        return "missing"
    return "optional"


def _evq_seed_screening(item: dict) -> None:
    """Share identical gates; infer whistleblowing from Modello 231 = Sì."""
    screening = item.get("screening") or ""
    if not screening:
        return
    wkey = _evq_wkey(item["qid"], "screen")
    if st.session_state.get(wkey) in _EVQ_YN:
        return
    sid = _evq_screen_id(screening)
    shared = (st.session_state.get("mfr_q_screens") or {}).get(sid)
    if shared in _EVQ_YN:
        st.session_state[wkey] = shared
        return
    if item["evidence"] == "Procedura e canale whistleblowing":
        if _evq_get("governance::Modello 231", "answer") == "Sì":
            st.session_state[wkey] = "Sì"


def _evq_on_screen(sid: str, wkey: str) -> None:
    val = st.session_state.get(wkey)
    if sid and val in _EVQ_YN:
        st.session_state.setdefault("mfr_q_screens", {})[sid] = val


def _evq_fu_label(fu) -> str:
    if isinstance(fu, dict):
        return str(fu.get("question") or "")
    return str(fu or "")


def _evq_fu_input(fu) -> str:
    if isinstance(fu, dict):
        kind = str(fu.get("input") or "text").lower()
        return kind if kind in ("text", "year", "multi", "table") else "text"
    return "text"


_EVQ_OTHER_LABEL = "Altro"


def _evq_fu_table_default(fu: dict) -> pd.DataFrame:
    rows = list(fu.get("rows") or [])
    value_label = str(fu.get("value_label") or "Numero")
    return pd.DataFrame({
        "Tipologia": rows,
        value_label: [pd.NA] * len(rows),
        "Specifica": [""] * len(rows),
    })


def _evq_fu_value(item: dict, index: int, fu) -> str:
    """Serialize a follow-up answer for export / review."""
    raw = _evq_get(item["qid"], f"fu{index}", None)
    kind = _evq_fu_input(fu)
    if kind == "table":
        if not isinstance(raw, pd.DataFrame) or raw.empty:
            return ""
        value_label = str((fu or {}).get("value_label") or "Numero")
        other_row = str((fu or {}).get("other_row") or "")
        parts: list[str] = []
        for _, row in raw.iterrows():
            tip = str(row.get("Tipologia") or "").strip()
            num = row.get(value_label)
            spec = str(row.get("Specifica") or "").strip()
            if pd.isna(num) and not spec:
                continue
            num_s = "" if pd.isna(num) else str(int(num) if float(num) == int(num) else num)
            if tip == other_row or (spec and tip == _EVQ_OTHER_LABEL):
                bit = f"{tip}: {num_s}".strip(": ")
                if spec:
                    bit = f"{bit} ({spec})" if num_s else f"{tip}: {spec}"
                parts.append(bit)
            elif num_s:
                parts.append(f"{tip}: {num_s}")
        return " | ".join(parts)
    if kind != "multi":
        return "" if raw is None else str(raw)
    if isinstance(raw, (list, tuple)):
        selected = [str(s) for s in raw if s]
    elif raw:
        selected = [str(raw)]
    else:
        selected = []
    parts = [s for s in selected if s != _EVQ_OTHER_LABEL]
    if _EVQ_OTHER_LABEL in selected:
        other = str(_evq_get(item["qid"], f"fu{index}_other", "") or "").strip()
        parts.append(f"{_EVQ_OTHER_LABEL}: {other}" if other else _EVQ_OTHER_LABEL)
    return " | ".join(parts)


def _evq_collect(item: dict) -> dict:
    fus = item.get("followups") or []
    return {
        "codice": item.get("code") or "",
        "iniziali": item.get("initials") or "",
        "macroarea": item["area_label"],
        "evidenza": item["evidence"],
        "livello": item["level"],
        "natura": item["nature"],
        "size_min": item.get("size_min") or "micro",
        "screening": _evq_get(item["qid"], "screen"),
        "risposta": _evq_get(item["qid"], "answer"),
        "dettagli": [
            {
                "domanda": _evq_fu_label(fu),
                "risposta": _evq_fu_value(item, i, fu),
            }
            for i, fu in enumerate(fus)
        ],
        "documento": _evq_get(item["qid"], "doc", "") or "",
        "note": _evq_get(item["qid"], "notes", "") or "",
        "stato": _evq_status(item),
    }


def _evq_answers_rows(items: list[dict]) -> pd.DataFrame:
    rows = []
    size_label = _evq_size_label()
    sasb_sector = _evq_sasb_sector_label()
    sasb_industry = _evq_sasb_industry()
    for it in items:
        rec = _evq_collect(it)
        rows.append({
            "Dimensione": size_label,
            "SASB settore": sasb_sector,
            "SASB industry": sasb_industry,
            "Codice": rec["codice"],
            "Macroarea": rec["macroarea"],
            "Evidenza": rec["evidenza"],
            "Livello": rec["livello"],
            "Natura": rec["natura"],
            "Size min": rec["size_min"],
            "Filtro": rec["screening"] or "",
            "Risposta": rec["risposta"] or "",
            "Dettagli": " | ".join(
                f"{d['domanda']} → {d['risposta']}".strip()
                for d in rec["dettagli"]
                if str(d.get("risposta") or "").strip()
            ),
            "Documento": rec["documento"],
            "Note": rec["note"],
            "Stato": rec["stato"],
        })
    return pd.DataFrame(rows)


def _evq_go(phase: str, step: int | None = None) -> None:
    st.session_state["mfr_q_phase"] = phase
    st.session_state["mfr_q_err"] = ""
    if step is not None:
        st.session_state["mfr_q_step"] = step


def _evq_try_next(step: int, n_areas: int) -> None:
    # Navigation is never blocked: incomplete Core items are flagged on review.
    if step + 1 >= n_areas:
        _evq_go("review")
    else:
        _evq_go("survey", step + 1)


def _evq_back(step: int) -> None:
    if step <= 0:
        _evq_go("intro", 0)
    else:
        _evq_go("survey", step - 1)


def _evq_submit() -> None:
    st.session_state["mfr_q_submitted"] = True
    st.session_state["mfr_q_err"] = ""


def _evq_start_survey() -> None:
    sector = st.session_state.get("mfr_q_sasb_sector_widget")
    industry = st.session_state.get("mfr_q_sasb_industry_widget")
    size = st.session_state.get("mfr_q_size_widget")
    sector_ok = any(s.get("key") == sector for s in _evq_sasb_sectors())
    if not sector_ok or not industry:
        st.session_state["mfr_q_err"] = (
            "Seleziona il settore e l'industry SASB (SICS) prima di iniziare."
        )
        return
    if size not in _EVQ_SIZE_BANDS:
        st.session_state["mfr_q_err"] = (
            "Seleziona la dimensione aziendale prima di iniziare."
        )
        return
    st.session_state["mfr_q_sasb_sector"] = sector
    st.session_state["mfr_q_sasb_industry"] = industry
    st.session_state["mfr_q_size"] = size
    _evq_apply_size_side_effects(size)
    _evq_go("survey", int(st.session_state.get("mfr_q_step", 0)))


def _evq_render_intro(areas: list[dict], meta: dict) -> None:
    total_all = sum(len(a["questions"]) for a in areas)
    sasb_meta = _evq_sasb_meta()
    st.subheader("Questionario fornitore")
    st.markdown(
        "Prima di tutto classifica l'azienda con **SASB SICS** (settore e industry) "
        "e indica la **dimensione aziendale** (fasce FTE B Lab). "
        "La dimensione filtra le evidenze del questionario; la classificazione SASB "
        "resta nell'intestazione e nell'export. "
        "Puoi avanzare anche con risposte incomplete: in revisione restano "
        "segnalate le evidenze e le sezioni da completare."
    )

    # ── SASB SICS classification ──────────────────────────────────────────
    sectors = _evq_sasb_sectors()
    sector_keys = [s["key"] for s in sectors]
    sector_labels = {s["key"]: s["label"] for s in sectors}
    industries_by_sector = {
        s["key"]: list(s.get("industries") or []) for s in sectors
    }
    if (
        "mfr_q_sasb_sector_widget" not in st.session_state
        and st.session_state.get("mfr_q_sasb_sector") in sector_keys
    ):
        st.session_state["mfr_q_sasb_sector_widget"] = st.session_state[
            "mfr_q_sasb_sector"
        ]
    sector_kwargs: dict = {
        "options": sector_keys,
        "format_func": lambda k: sector_labels.get(k, k),
        "key": "mfr_q_sasb_sector_widget",
        "help": (
            "Sustainable Industry Classification System (SICS®): "
            f"{sasb_meta.get('sectors', 11)} settori, "
            f"{sasb_meta.get('industries', 77)} industry. "
            "Fonte IFRS / SASB."
        ),
        "placeholder": "Scegli il settore SASB",
    }
    if "mfr_q_sasb_sector_widget" not in st.session_state:
        sector_kwargs["index"] = None
    sector_pick = st.selectbox("Settore SASB (SICS)", **sector_kwargs)

    industry_opts = industries_by_sector.get(sector_pick, []) if sector_pick else []
    # Reset industry widget when sector changes and current industry is invalid.
    cur_ind = st.session_state.get("mfr_q_sasb_industry_widget")
    if cur_ind and cur_ind not in industry_opts:
        del st.session_state["mfr_q_sasb_industry_widget"]
    if (
        "mfr_q_sasb_industry_widget" not in st.session_state
        and st.session_state.get("mfr_q_sasb_industry") in industry_opts
    ):
        st.session_state["mfr_q_sasb_industry_widget"] = st.session_state[
            "mfr_q_sasb_industry"
        ]
    industry_kwargs: dict = {
        "options": industry_opts,
        "key": "mfr_q_sasb_industry_widget",
        "placeholder": "Scegli l'industry SASB",
        "disabled": not bool(industry_opts),
        "help": "Industry SICS all'interno del settore selezionato.",
    }
    if "mfr_q_sasb_industry_widget" not in st.session_state:
        industry_kwargs["index"] = None
    industry_pick = st.selectbox("Industry SASB (SICS)", **industry_kwargs)
    src = sasb_meta.get("source") or ""
    src_label = sasb_meta.get("source_label") or "Elenco industry SICS"
    if src:
        st.caption(f"Riferimento: [{src_label}]({src})")

    # ── Company size ──────────────────────────────────────────────────────
    size_options = list(_EVQ_SIZE_ORDER)
    # Keep the radio in sync when returning to intro with a chosen size.
    if (
        "mfr_q_size_widget" not in st.session_state
        and _evq_size_key() in _EVQ_SIZE_BANDS
    ):
        st.session_state["mfr_q_size_widget"] = _evq_size_key()
    size_kwargs: dict = {
        "options": size_options,
        "format_func": lambda k: _EVQ_SIZE_BANDS[k]["label"],
        "captions": [_EVQ_SIZE_BANDS[k]["fte"] for k in size_options],
        "key": "mfr_q_size_widget",
        "horizontal": True,
        "help": (
            "Soglie B Lab Standards V2.1 (lavoratori FTE): "
            "Micro 1–9 · Small 10–49 · Medium 50–249 · Large 250+. "
            "Qui usiamo solo il criterio headcount (non il fatturato)."
        ),
        "width": "stretch",
    }
    if "mfr_q_size_widget" not in st.session_state:
        size_kwargs["index"] = None
    size_pick = st.radio(
        "Dimensione aziendale (dipendenti / FTE)",
        **size_kwargs,
    )
    if size_pick in _EVQ_SIZE_BANDS:
        st.caption(_EVQ_SIZE_BANDS[size_pick]["help"])
        filtered = _evq_filter_areas(areas, size_pick)
        n_show = sum(len(a["questions"]) for a in filtered)
        n_hide = total_all - n_show
        screens = sum(
            1 for a in filtered for q in a["questions"] if q["screening"]
        )
        st.info(
            f"Con fascia **{_evq_size_label(size_pick)}**: "
            f"**{n_show}** evidenze in **{len(filtered)}** sezioni "
            f"({n_hide} escluse perché riservate a fasce superiori). "
            f"{screens} domande filtro di applicabilità restano attive."
        )
        st.caption(
            "Sezioni: "
            + ", ".join(
                f"**{_evq_initials(a['label'])}** {a['label']} "
                f"({len(a['questions'])})"
                for a in filtered
            )
        )
    else:
        st.caption(
            f"Catalogo completo: **{total_all}** evidenze in **{len(areas)}** "
            "sezioni — la selezione restringe il perimetro."
        )

    names = sorted(fn135_sustainability_credentials().get("credentials") or {})
    sb_kwargs: dict = {
        "placeholder": "Scegli o scrivi il nome del produttore",
        "accept_new_options": True,
        "key": "mfr_q_company",
        "help": "Facoltativo: serve a intestare le risposte di questa sessione.",
    }
    if "mfr_q_company" not in st.session_state:
        sb_kwargs["index"] = None
    company = st.selectbox("Produttore", names, **sb_kwargs)

    err = st.session_state.get("mfr_q_err") or ""
    if err:
        st.warning(err)

    gen = int(st.session_state.get("mfr_q_gen", 0))
    resumed = (
        bool(_evq_size_key())
        and bool(_evq_sasb_industry())
        and any(
            isinstance(k, str) and k.startswith(f"mfr_q_{gen}_")
            for k in st.session_state
        )
    )
    can_start = (
        sector_pick in sector_keys
        and bool(industry_pick)
        and size_pick in _EVQ_SIZE_BANDS
    )
    with st.container(horizontal=True):
        st.button(
            "Riprendi" if resumed else "Inizia",
            type="primary",
            icon=":material/play_arrow:",
            on_click=_evq_start_survey,
            disabled=not can_start,
            key="mfrqb_start",
        )
        if resumed:
            st.button(
                "Ricomincia",
                icon=":material/replay:",
                on_click=_evq_reset,
                key="mfrqb_reset_intro",
            )
    st.caption(
        f"Framework evidenze v{meta.get('version', '—')} · "
        "le risposte restano in questa sessione, non vengono salvate su file."
    )
    if company:
        st.caption(f"Intestato a **{company}**.")


def _evq_render_fu_year(item: dict, index: int, fu) -> None:
    label = f"{item['code']}.{index + 1}  {_evq_fu_label(fu)}"
    st.pills(
        label,
        _EVQ_YEAR_OPTIONS,
        selection_mode="single",
        key=_evq_wkey(item["qid"], f"fu{index}"),
        width="stretch",
    )


def _evq_render_fu_text(item: dict, index: int, fu) -> None:
    placeholder = ""
    if isinstance(fu, dict):
        placeholder = str(fu.get("placeholder") or "").strip()
    st.text_input(
        f"{item['code']}.{index + 1}  {_evq_fu_label(fu)}",
        key=_evq_wkey(item["qid"], f"fu{index}"),
        placeholder=placeholder or None,
    )


def _evq_render_fu_multi(item: dict, index: int, fu) -> None:
    """Multi-select channels (pills) with optional free-text Altro."""
    options = list((fu or {}).get("options") or [])
    allow_other = bool((fu or {}).get("other"))
    if allow_other and _EVQ_OTHER_LABEL not in options:
        options = [*options, _EVQ_OTHER_LABEL]
    label = f"{item['code']}.{index + 1}  {_evq_fu_label(fu)}"
    wkey = _evq_wkey(item["qid"], f"fu{index}")
    # Drop stale scalar values if this slot used to be a free-text field.
    prev = st.session_state.get(wkey)
    if prev is not None and not isinstance(prev, (list, tuple)):
        del st.session_state[wkey]
    selected = st.pills(
        label,
        options,
        selection_mode="multi",
        key=wkey,
        help="Puoi selezionare più canali.",
        width="stretch",
    )
    if allow_other and selected and _EVQ_OTHER_LABEL in list(selected or []):
        st.text_input(
            "Altro — specificare",
            key=_evq_wkey(item["qid"], f"fu{index}_other"),
            placeholder="Specifica il canale",
        )


def _evq_render_fu_table(item: dict, index: int, fu) -> None:
    """Editable typology × value table (e.g. headcount by contract type)."""
    fu = fu if isinstance(fu, dict) else {}
    value_label = str(fu.get("value_label") or "Numero")
    other_ph = str(fu.get("other_placeholder") or "Specificare")
    label = f"{item['code']}.{index + 1}  {_evq_fu_label(fu)}"
    st.markdown(f"**{label}**")
    wkey = _evq_wkey(item["qid"], f"fu{index}")
    # Drop stale scalar values if this slot used to be a free-text field.
    prev = st.session_state.get(wkey)
    if prev is not None and not isinstance(prev, pd.DataFrame):
        del st.session_state[wkey]
    st.data_editor(
        _evq_fu_table_default(fu),
        column_config={
            "Tipologia": st.column_config.TextColumn(
                "Tipologia",
                disabled=True,
                width="medium",
            ),
            value_label: st.column_config.NumberColumn(
                value_label,
                min_value=0,
                step=1,
                format="%d",
                width="small",
            ),
            "Specifica": st.column_config.TextColumn(
                f"Specifica ({other_ph})",
                help="Compilare soprattutto sulla riga Altro.",
                width="medium",
            ),
        },
        column_order=["Tipologia", value_label, "Specifica"],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=wkey,
    )


def _evq_render_followups(item: dict, followups: list) -> None:
    """Render follow-ups; consecutive year inputs sit side-by-side in 2 cols."""
    i = 0
    n = len(followups)
    while i < n:
        fu = followups[i]
        kind = _evq_fu_input(fu)
        if (
            kind == "year"
            and i + 1 < n
            and _evq_fu_input(followups[i + 1]) == "year"
        ):
            c1, c2 = st.columns(2)
            with c1:
                _evq_render_fu_year(item, i, fu)
            with c2:
                _evq_render_fu_year(item, i + 1, followups[i + 1])
            i += 2
            continue
        if kind == "year":
            _evq_render_fu_year(item, i, fu)
        elif kind == "multi":
            _evq_render_fu_multi(item, i, fu)
        elif kind == "table":
            _evq_render_fu_table(item, i, fu)
        else:
            _evq_render_fu_text(item, i, fu)
        i += 1


def _evq_render_item(item: dict) -> None:
    qid = item["qid"]
    kind = _evq_kind(item["response_type"])
    required = item.get("level") in ("Core", "Core-se-applicabile")
    _evq_seed_screening(item)

    with st.container(border=True):
        with st.container(
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{item['code']} · {item['evidence']}**")
                st.markdown(
                    _md_badge(item["level"], _EVQ_LEVEL_BADGE.get(item["level"], "gray"))
                    + " "
                    + _md_badge(
                        item["nature"], _EVQ_NATURE_BADGE.get(item["nature"], "gray")
                    )
                )
            st.caption("Obbligatoria se applicabile" if required else "Facoltativa")

        if item.get("screening"):
            sid = _evq_screen_id(item["screening"])
            wkey = _evq_wkey(qid, "screen")
            screen = st.segmented_control(
                f"Filtro di applicabilità — {item['screening']}",
                _EVQ_YN,
                key=wkey,
                width="content",
                required=True,
                help="Se No, questa evidenza esce dal questionario e non penalizza.",
                on_change=_evq_on_screen,
                args=(sid, wkey),
            )
            if screen != "Sì":
                if screen == "No":
                    st.info(
                        "Evidenza non richiesta. Il branching salta i dettagli."
                    )
                    st.text_area(
                        "Nota sul filtro (facoltativa)",
                        key=_evq_wkey(qid, "notes"),
                        height=68,
                    )
                return

        if item.get("condition"):
            st.caption(item["condition"])

        if _evq_is_choice(kind):
            answer = st.segmented_control(
                item["question"],
                _evq_choice_options(kind),
                key=_evq_wkey(qid, "answer"),
                width="content",
                required=True,
            )
        else:
            answer = st.text_area(
                item["question"],
                key=_evq_wkey(qid, "answer"),
                height=100,
                placeholder=(
                    "Inserisci i dati richiesti"
                    if kind == "qty"
                    else "Descrivi la pratica o l'evidenza"
                ),
            )

        if _evq_is_choice(kind) and answer in ("No", "Non applicabile"):
            st.caption(
                "I punti di dettaglio e il documento si aprono solo se la "
                "risposta è Sì."
            )
            st.text_area(
                "Motivazione (facoltativa)",
                key=_evq_wkey(qid, "notes"),
                height=68,
            )
            return

        if not _evq_show_details(item):
            return

        followups = item.get("followups") or []
        if followups:
            st.markdown("**Dettagli**")
            _evq_render_followups(item, followups)

        doc_hint = str(item.get("document") or "").strip()
        if doc_hint:
            st.text_input(
                "Documento da allegare",
                key=_evq_wkey(qid, "doc"),
                placeholder=doc_hint,
                help=doc_hint,
            )
        st.text_area(
            "Note (facoltative)",
            key=_evq_wkey(qid, "notes"),
            height=68,
        )


def _evq_render_survey(areas: list[dict], items: list[dict], step: int) -> None:
    n_areas = len(areas)
    area = areas[step]
    section_items = [it for it in items if it["area_key"] == area["key"]]
    company = st.session_state.get("mfr_q_company") or ""
    size_lbl = _evq_size_label()
    sasb_ind = _evq_sasb_industry()
    done = sum(1 for it in section_items if _evq_status(it) in ("done", "na"))
    st.progress(
        (step + 1) / n_areas,
        text=(
            f"Sezione {step + 1} di {n_areas} · "
            f"{_evq_initials(area['label'])} · {area['label']}"
            + (f" · {sasb_ind}" if sasb_ind else "")
            + (f" · {size_lbl}" if size_lbl else "")
            + (f" · {company}" if company else "")
        ),
    )
    missing_here = [it for it in section_items if _evq_status(it) == "missing"]
    st.caption(
        f"**{len(section_items)}** evidenze in questa sezione · "
        f"{done} compilate o non applicabili · "
        f"{len(missing_here)} da completare · "
        f"{sum(1 for q in area['questions'] if q['level'] == 'Core')} Core · "
        f"{sum(1 for q in area['questions'] if q['level'] == 'Core-se-applicabile')} "
        "Core-se-applicabile · "
        f"{sum(1 for q in area['questions'] if q['level'] == 'Advanced')} Advanced"
    )
    if missing_here:
        st.info(
            "Puoi andare avanti anche senza completare tutto. "
            "In revisione resteranno segnalate: "
            + ", ".join(f"{it['code']} {it['evidence']}" for it in missing_here)
        )

    for it in section_items:
        _evq_render_item(it)

    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.button(
            "Indietro",
            icon=":material/arrow_back:",
            on_click=_evq_back,
            args=(step,),
            key="mfrqb_back",
        )
        st.button(
            "Revisione" if step + 1 >= n_areas else "Avanti",
            type="primary",
            icon=":material/arrow_forward:",
            on_click=_evq_try_next,
            args=(step, n_areas),
            key="mfrqb_next",
        )


def _evq_render_review(areas: list[dict], items: list[dict], meta: dict) -> None:
    company = st.session_state.get("mfr_q_company") or ""
    size_lbl = _evq_size_label()
    sasb_lbl = _evq_sasb_label()
    st.progress(1.0, text="Revisione delle risposte")
    st.subheader("Revisione")
    caps = []
    if company:
        caps.append(f"Produttore: **{company}**")
    if sasb_lbl:
        caps.append(f"SASB: **{sasb_lbl}**")
    if size_lbl:
        caps.append(f"Dimensione: **{size_lbl}**")
    if caps:
        st.caption(" · ".join(caps))
    counts = {"done": 0, "na": 0, "missing": 0, "optional": 0}
    for it in items:
        counts[_evq_status(it)] = counts.get(_evq_status(it), 0) + 1
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compilate", counts["done"])
    c2.metric("Non applicabili", counts["na"])
    c3.metric("Da completare", counts["missing"])
    c4.metric("Facoltative vuote", counts["optional"])

    incomplete_by_area: list[tuple[str, list[dict]]] = []
    for a in areas:
        section_missing = [
            it for it in items
            if it["area_key"] == a["key"] and _evq_status(it) == "missing"
        ]
        if section_missing:
            incomplete_by_area.append((a["label"], section_missing))

    if incomplete_by_area:
        st.warning(
            f"**{counts['missing']} evidenze obbligatorie da completare** in "
            f"{len(incomplete_by_area)} sezioni. Puoi tornare indietro, "
            "oppure inviare dopo averle completate."
        )
        with st.container(border=True):
            st.markdown("#### Da completare")
            for label, section_missing in incomplete_by_area:
                st.markdown(
                    f"**{_evq_initials(label)} · {label}** "
                    f"({len(section_missing)})"
                )
                for it in section_missing:
                    st.markdown(
                        f"- :red-badge[da completare] "
                        f"**{it['code']}** · {it['evidence']}"
                    )
    elif counts["optional"]:
        st.info(
            "Tutte le evidenze obbligatorie sono compilate. "
            f"Restano {counts['optional']} facoltative vuote."
        )
    else:
        st.success("Tutte le evidenze sono compilate o non applicabili.")

    if st.session_state.get("mfr_q_submitted"):
        st.success(
            "Questionario inviato in questa sessione. "
            "Le risposte non sono state scritte su file: scaricale se ti servono."
        )

    for a in areas:
        section = [it for it in items if it["area_key"] == a["key"]]
        n_done = sum(1 for it in section if _evq_status(it) in ("done", "na"))
        n_miss = sum(1 for it in section if _evq_status(it) == "missing")
        flag = f" · {n_miss} da completare" if n_miss else ""
        with st.expander(
            f"{_evq_initials(a['label'])} · {a['label']} · "
            f"{n_done}/{len(section)}{flag}",
            expanded=bool(n_miss),
        ):
            for it in section:
                rec = _evq_collect(it)
                status = rec["stato"]
                mark = {
                    "done": ":green-badge[compilata]",
                    "na": ":gray-badge[non applicabile]",
                    "missing": ":red-badge[da completare]",
                    "optional": ":orange-badge[facoltativa]",
                }.get(status, "")
                st.markdown(f"**{it['code']} · {it['evidence']}** {mark}")
                if rec["screening"]:
                    st.caption(f"Filtro: {rec['screening']}")
                if rec["risposta"]:
                    st.markdown(str(rec["risposta"]))
                details = [
                    d for d in rec["dettagli"] if str(d.get("risposta") or "").strip()
                ]
                for d in details:
                    st.caption(f"{d['domanda']} — {d['risposta']}")
                if rec["documento"]:
                    st.caption(f"Documento: {rec['documento']}")
                if rec["note"]:
                    st.caption(f"Note: {rec['note']}")
                st.divider()

    df = _evq_answers_rows(items)
    payload = {
        "producer": company,
        "sasb_sector": st.session_state.get("mfr_q_sasb_sector"),
        "sasb_sector_label": _evq_sasb_sector_label(),
        "sasb_industry": _evq_sasb_industry(),
        "company_size": _evq_size_key(),
        "company_size_label": size_lbl,
        "framework_version": meta.get("version"),
        "answers": [_evq_collect(it) for it in items],
    }
    with st.container(horizontal=True):
        st.download_button(
            "Risposte CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name="eetra_questionario_risposte.csv",
            mime="text/csv",
            icon=":material/download:",
            key="mfrqb_dl_csv",
        )
        st.download_button(
            "Risposte JSON",
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="eetra_questionario_risposte.json",
            mime="application/json",
            icon=":material/download:",
            key="mfrqb_dl_json",
        )

    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.button(
            "Indietro",
            icon=":material/arrow_back:",
            on_click=_evq_go,
            args=("survey", len(areas) - 1),
            key="mfrqb_review_back",
        )
        st.button(
            "Invia",
            type="primary",
            icon=":material/send:",
            on_click=_evq_submit,
            disabled=bool(counts["missing"]) or bool(
                st.session_state.get("mfr_q_submitted")
            ),
            key="mfrqb_submit",
        )
        st.button(
            "Ricomincia",
            icon=":material/replay:",
            on_click=_evq_reset,
            key="mfrqb_reset_review",
        )


def _render_questionnaire() -> None:
    areas_all, meta = fn140i_evaluation_questionnaire()
    if not areas_all:
        st.info("No questions found in the `evaluation_framework` block.")
        return

    _evq_init()
    phase = st.session_state.get("mfr_q_phase") or "intro"
    if phase == "intro":
        _evq_render_intro(areas_all, meta)
        return

    if not _evq_size_key() or not _evq_sasb_industry():
        # Size + SASB are mandatory before survey/review.
        st.session_state["mfr_q_phase"] = "intro"
        _evq_render_intro(areas_all, meta)
        return

    areas = _evq_filter_areas(areas_all)
    if not areas:
        st.warning(
            "Nessuna evidenza applicabile a questa dimensione. "
            "Torna indietro e scegli un'altra fascia."
        )
        st.button(
            "Torna all'inizio",
            icon=":material/arrow_back:",
            on_click=_evq_go,
            args=("intro", 0),
            key="mfrqb_empty_back",
        )
        return

    items = _evq_items(areas)
    if phase == "review":
        _evq_render_review(areas, items, meta)
        return

    step = int(st.session_state.get("mfr_q_step", 0))
    step = max(0, min(step, len(areas) - 1))
    st.session_state["mfr_q_step"] = step
    _evq_render_survey(areas, items, step)


# ── Page ─────────────────────────────────────────────────────────────────────

fn003a_page_header("Manufacturers")

_sust = fn135_sustainability_credentials()

fn353a_keep_widget_state("mono_", "mfr_matrix_", "mfr_rank_", "mfr_evf_", "mfr_q_")
tab_mono, tab_dir, tab_matrix, tab_rank, tab_evf, tab_quest = st.tabs(
    ["Monograph", "Directory", "Credentials matrix", "Maturity ranking",
     "Evaluation framework", "Questionnaire"],
    on_change="rerun",
    key="mfr_active_tab",
)

if tab_mono.open:
    with tab_mono:
        _render_monograph()

if tab_dir.open:
    with tab_dir:
        if not _COMPONENT.exists():
            st.error(f"Component not found: `{_COMPONENT.name}`")
        else:
            _render_directory()
        st.caption(
            "Impact score and tier come from the EETRA Impact Framework where the company is assessed; "
            "otherwise the tier is the credentials maturity tier. Sources: SBTi Target Dashboard, CDP, "
            "EcoVadis, company sustainability reports, ISO registries."
        )

if tab_matrix.open:
    with tab_matrix:
        _m = _table_filters("mfr_matrix", _sust)
        if not _m:
            st.info("No manufacturers match the current filters.")
        else:
            _df = fn137_get_credentials_matrix(manufacturers=_m)
            if not _df.empty:
                _df = _df.drop(columns=["maturity"], errors="ignore")
                st.dataframe(_df, width="stretch", height=min(600, 40 + 35 * len(_df)))
        st.caption(
            "✅ = confirmed / validated · ⚠️ = partial or unconfirmed · ❌ = no evidence found. "
            "Based on public disclosures (February 2026; insulation manufacturers reviewed September 2026)."
        )

if tab_rank.open:
    with tab_rank:
        _m = _table_filters("mfr_rank", _sust)
        _rank = fn138_get_maturity_ranking()
        _rank = _rank[_rank["Manufacturer"].isin(_m)]
        if _rank.empty:
            st.info("No manufacturers match the current filters.")
        else:
            _tiers = list(_sust["maturity_tiers"])
            _counts = _rank["Maturity Tier"].value_counts()
            for _col, _t in zip(st.columns(len(_tiers)), _tiers):
                _col.metric(_t, int(_counts.get(_t, 0)))
            _tier_css = {
                "Advanced": "color: #0f5f58; font-weight: 600",
                "Good": "color: #1f5e23; font-weight: 600",
                "Progressing": "color: #b45309; font-weight: 600",
                "Developing": "color: #a16207; font-weight: 600",
                "Early Stage": "color: #1565c0; font-weight: 600",
                "Minimal": "color: #64748b",
            }
            st.dataframe(
                _rank.style.map(lambda v: _tier_css.get(v, ""), subset=["Maturity Tier"]),
                width="stretch", hide_index=True, height=min(700, 50 + 35 * len(_rank)),
            )
            st.markdown("#### Maturity distribution")
            _dist = _rank["Maturity Tier"].value_counts().reindex(_tiers, fill_value=0)
            st.bar_chart(pd.DataFrame({"Tier": _dist.index, "Count": _dist.values}).set_index("Tier"))

if tab_evf.open:
    with tab_evf:
        _render_evaluation_framework()

if tab_quest.open:
    with tab_quest:
        _render_questionnaire()
