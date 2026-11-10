"""
libs/lib_revalu_send.py — build & transmit Revalu-shaped EPD payloads
=====================================================================
Companion to ``libs/lib_revalu_map.py``. Where that module documents which
EETRA column corresponds to which Revalu field, this one actually *produces*
the JSON: it turns one (or many) rows of the Material Library into objects
shaped exactly like the body of Revalu's **Get EPD Extended** response
(https://docs.revalu.io/ — collection item 5ebbf9cf-ecde-4519-9e0f-305966d49cb7).

Schema implemented (Get EPD Extended -> ``body``)
-------------------------------------------------
``id``, ``location``, ``version``, ``registration_number``, ``name``,
``manufacturer``, ``valid_from``, ``valid_until``, ``declared_unit``,
``declared_unit_amount``, ``thickness`` (m), ``grammage``, ``gross_density``,
``bulk_density``, ``linear_density``, ``standard``, ``subtype``, ``lambda``,
``u_value``, ``r_value``, ``source {name,url}``, ``gwp``, ``gwp_fossil``,
``gwp_biogenic``, ``gwp_luluc``, ``fw``, ``pert``, ``penrt``,
``energy_mix_percentage``, ``custom_attribute``, ``additional_data``,
``all_documents``, ``certificates``, ``rsl``, ``tags``.

Module keys inside every ``gwp*`` object follow the documented sample:
a1a3, a4, a5, b1…b7, c1…c4, d.

Transport
---------
Revalu's *public* API (api.revalu.io) is read-only — it publishes GET
``/epds/{uuid}``, GET ``/epds/{uuid}/extended``, GET ``/epds/search`` and POST
``/epds/multiple`` (a read that takes a list of UUIDs). There is no public
endpoint that accepts third-party EPD records, so "sending" is done in one of
two ways, both provided here:

  1. **File hand-off** (always available) — a JSON / NDJSON document in the
     Get-EPD-Extended shape, downloaded from the UI and passed to Revalu.
  2. **HTTP POST** (only when a partner ingestion URL is configured) — the same
     payload posted to ``[revalu] ingest_url`` with the documented
     ``x-api-key`` header.

Configuration (``.streamlit/secrets.toml`` or environment)::

    [revalu]
    api_key    = "…"                     # or env REVALU_API_KEY
    ingest_url = "https://…"             # or env REVALU_INGEST_URL (optional)

``verify_api_key()`` calls the documented GET ``/epds/{uuid}/extended`` so the
key can be checked against the real API before any hand-off.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Iterable

import pandas as pd

# ── API constants (from the published Revalu collection) ────────────────────
REVALU_API_BASE = "https://api.revalu.io"
REVALU_API_KEY_HEADER = "x-api-key"
REVALU_EPD_EXTENDED_PATH = "/epds/{uuid}/extended"
REVALU_EPD_MULTIPLE_PATH = "/epds/multiple"
REVALU_DOCS_URL = "https://docs.revalu.io/#5ebbf9cf-ecde-4519-9e0f-305966d49cb7"
# Public sample EPD used by the docs — handy as a key-validity probe.
REVALU_SAMPLE_UUID = "c37c442b-b6ac-4bf8-9b24-08dbdfa8f0c9"

GWP_MODULES = (
    "a1a3", "a4", "a5",
    "b1", "b2", "b3", "b4", "b5", "b6", "b7",
    "c1", "c2", "c3", "c4", "d",
)

# EETRA GWP column per Revalu module key (a1a3 handled separately: it may have
# to be summed from the split A1/A2/A3 columns).
_GWP_COLUMN_BY_MODULE = {
    "a4": "G__GWP_A4", "a5": "G__GWP_A5",
    "b1": "G__GWP_B1", "b2": "G__GWP_B2", "b3": "G__GWP_B3", "b4": "G__GWP_B4",
    "b5": "G__GWP_B5", "b6": "G__GWP_B6", "b7": "G__GWP_B7",
    "c1": "G__GWP_C1", "c2": "G__GWP_C2", "c3": "G__GWP_C3", "c4": "G__GWP_C4",
    "d": "G__GWP_D",
}

# EETRA-only columns worth carrying across as ``custom_attribute`` — Revalu's
# EPD schema has no recycled-content, VOC or CAM attributes of its own.
_CUSTOM_ATTRIBUTE_COLUMNS = {
    "D__ProductType_ENG": "eetra_product_type",
    "D__MaterialType_ENG": "eetra_material_type",
    "D__MaterialType_ITA": "eetra_material_type_ita",
    "D__Int/Ext": "eetra_int_ext",
    "D__Application": "eetra_application",
    "D__Size": "eetra_size",
    "D__Content": "eetra_composition",
    "D__EN197-1": "cement_type",
    "D__EN206": "concrete_exposure_class",
    "P__Mass_kg": "mass_kg",
    "P__FireRating": "fire_rating",
    "E__ManuPlant": "manufacturing_plant",
    "E__ManuCountry": "manufacturing_country",
    "R__Rec_Pre_%": "recycled_content_pre_consumer_pct",
    "R__Rec_Post_%": "recycled_content_post_consumer_pct",
    "R__Rec_Tot_%": "recycled_content_total_pct",
    "R__Reco_Tot_%": "recovered_content_total_pct",
    "R__ByProd_Tot_%": "by_product_total_pct",
    "R__Rec_Reco_ByProd_%": "recycled_recovered_by_product_pct",
    "VO__VOC_Cert": "voc_certification",
    "VO__TestStandard": "voc_test_standard",
    "VO__ReportType": "voc_report_type",
    "VO__Product_Category": "voc_product_category",
    "VO__Application_Scope": "voc_application_scope",
    "VV__LEED_MR_RawMat": "leed_mr_raw_materials",
    "VV__CAM__Status": "cam_status",
    "VV__CAM_Compliance": "cam_compliance",
    "VV__Other": "eetra_other",
}

# Document URL columns → ``all_documents`` entries / ``additional_data`` keys.
_DOCUMENT_COLUMNS = {
    "E__EPD_URL": ("epd", "EPD document"),
    "U__TechDetails_URL": ("technical_datasheet", "Technical details"),
    "U__ProductInfo_URL": ("product_information", "Product information"),
    "VO__VOC_URL": ("voc_certificate", "VOC certificate"),
    "VV__MSDS__URL": ("msds", "Safety data sheet"),
    "VV__DOP": ("dop", "Declaration of performance"),
    "R__Rec_Reco_ByProd_URL": ("recycled_content", "Recycled content evidence"),
}

# ``*`` is the Excel section-marker token that survives into some cells; "see
# above" is a hand-typed placeholder in ``E__EPD_URL``. Both mean "no value".
_MISSING_TOKENS = {
    "", "nan", "none", "null", "n/a", "na", "n/r", "nr", "n/d", "nd", "mnd",
    "-", "–", "—", "*", "see above",
}
_YEAR_RE = re.compile(r"(19|20)\d{2}")


# ── scalar coercion ─────────────────────────────────────────────────────────
def _is_missing(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return str(val).strip().lower() in _MISSING_TOKENS


def _text(row: Any, col: str) -> str | None:
    """Trimmed string for ``col``, or None when absent / a missing-data token."""
    try:
        val = row.get(col)
    except (AttributeError, KeyError):
        return None
    if _is_missing(val):
        return None
    return str(val).strip()


def _num(row: Any, col: str) -> float | None:
    """Float for ``col``, tolerating comma decimals and unit suffixes."""
    raw = _text(row, col)
    if raw is None:
        return None
    cleaned = raw.replace(",", ".").replace("%", "").strip()
    cleaned = re.sub(r"[^0-9eE+\-.]", "", cleaned)
    try:
        num = float(cleaned)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(num) or math.isinf(num) else num


def _year(row: Any, col: str) -> int | None:
    """Four-digit year out of a date-ish cell (Revalu wants a bare number)."""
    raw = _text(row, col)
    if raw is None:
        return None
    match = _YEAR_RE.search(raw)
    if match:
        return int(match.group(0))
    num = _num(row, col)
    if num is not None and 1900 <= num <= 2100:
        return int(num)
    return None


def _url(row: Any, col: str) -> str | None:
    """Only genuine http(s) URLs — several columns hold prose placeholders."""
    val = _text(row, col)
    if val and val.lower().startswith(("http://", "https://")):
        return val
    return None


def _first_num(row: Any, *cols: str) -> float | None:
    for col in cols:
        val = _num(row, col)
        if val is not None:
            return val
    return None


def _first_text(row: Any, *cols: str) -> str | None:
    for col in cols:
        val = _text(row, col)
        if val is not None:
            return val
    return None


# ── field builders ──────────────────────────────────────────────────────────
def _gwp_object(row: Any) -> dict[str, float | None]:
    """``gwp`` per the documented module keys (a1a3, a4, a5, b1…b7, c1…c4, d)."""
    out: dict[str, float | None] = {}
    a1a3 = _first_num(row, "G__GWP_A1A3", "G__GWP_A1A3_kg")
    if a1a3 is None:
        split = [_num(row, c) for c in ("G__GWP_A1", "G__GWP_A2", "G__GWP_A3")]
        if any(v is not None for v in split):
            a1a3 = sum(v for v in split if v is not None)
    out["a1a3"] = a1a3
    for module in GWP_MODULES:
        if module == "a1a3":
            continue
        out[module] = _num(row, _GWP_COLUMN_BY_MODULE[module])
    return out


def _source_object(row: Any) -> dict[str, str] | None:
    name = _text(row, "E__EPD_Programme")
    url = _url(row, "E__EPD_URL")
    if not name and not url:
        return None
    obj: dict[str, str] = {}
    if name:
        obj["name"] = name
    if url:
        obj["url"] = url
    return obj


def _documents(row: Any) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for col, (doc_type, label) in _DOCUMENT_COLUMNS.items():
        url = _url(row, col)
        if url:
            docs.append({"type": doc_type, "name": label, "url": url})
    return docs


def _certificates(row: Any) -> list[dict[str, str]]:
    """VOC / emission certificates — Revalu's ``certificates`` array."""
    name = _text(row, "VO__VOC_Cert")
    number = _text(row, "VO__VOC_Cert_No")
    if not name and not number:
        return []
    cert: dict[str, str] = {}
    if name:
        cert["name"] = name
    if number:
        cert["number"] = number
    for key, col in (
        ("issuer", "VO__VOC_Body"),
        ("standard", "VO__TestStandard"),
        ("valid_until", "VO__Exp_Date"),
    ):
        val = _text(row, col)
        if val:
            cert[key] = val
    cert_url = _url(row, "VO__VOC_URL")
    if cert_url:
        cert["url"] = cert_url
    return [cert]


def _custom_attribute(row: Any) -> dict[str, str]:
    """EETRA-only data, carried in Revalu's free-form ``custom_attribute``."""
    out: dict[str, str] = {}
    eetra_id = _text(row, "0__EETRA_ID")
    if eetra_id:
        out["eetra_id"] = eetra_id
    for col, key in _CUSTOM_ATTRIBUTE_COLUMNS.items():
        val = _text(row, col)
        if val:
            out[key] = val
    return out


def _additional_data(row: Any) -> dict[str, Any]:
    """``additional_data`` — the docs sample carries ``epd_pdf_url`` here."""
    out: dict[str, Any] = {}
    epd_url = _url(row, "E__EPD_URL")
    if epd_url:
        out["epd_pdf_url"] = epd_url
    for key, col in (
        ("image_url", "U__Img_URL"),
        ("technical_details_url", "U__TechDetails_URL"),
        ("product_information_url", "U__ProductInfo_URL"),
    ):
        val = _url(row, col)
        if val:
            out[key] = val
    for key, col in (
        ("product_description", "A__ProductDescription"),
        ("technical_details", "D__TechDetails"),
        ("data_comments", "D__DataComments"),
        ("gwp_metric", "G__GWP_Metric"),
    ):
        val = _text(row, col)
        if val:
            out[key] = val
    return out


def _tags(row: Any) -> list[str]:
    """Revalu tag vocabulary (Bio-based, Recycled, …) inferred from EETRA data."""
    tags: list[str] = []
    recycled = _first_num(row, "R__Rec_Tot_%", "R__Rec_Reco_ByProd_%")
    if recycled is not None and recycled > 0:
        tags.append("Recycled")
    content = (_text(row, "D__Content") or "").lower()
    material = (_text(row, "D__MaterialType_ENG") or "").lower()
    if any(word in f"{content} {material}" for word in ("bio-based", "biobased", "bio based")):
        tags.append("Bio-based")
    return tags


def _thickness_m(row: Any) -> float | None:
    """Revalu reports thickness in metres; EETRA stores millimetres."""
    mm = _first_num(row, "P__Thick_mm", "E__EPD_Thick_mm")
    return None if mm is None else round(mm / 1000.0, 6)


def _standard(row: Any) -> str | None:
    """Normalise to Revalu's enum: ``EN 15804+A1`` / ``EN 15804+A2``."""
    raw = _first_text(row, "G__GWP_Metric", "D__DataComments")
    if not raw:
        return None
    compact = raw.upper().replace(" ", "")
    if "15804" not in compact:
        return None  # "GWP-T" and free-text comments say nothing about the standard
    if "15804+A2" in compact:
        return "EN 15804+A2"
    if "15804+A1" in compact:
        return "EN 15804+A1"
    return None


# ── payload assembly ────────────────────────────────────────────────────────
def build_revalu_payload(row: Any, *, drop_empty: bool = True) -> dict[str, Any]:
    """One EETRA row → one Get-EPD-Extended-shaped object.

    ``drop_empty`` removes keys with no value, which keeps hand-off files small;
    pass False to emit the full schema with explicit nulls.
    """
    gwp = _gwp_object(row)
    payload: dict[str, Any] = {
        "id": _text(row, "0__EETRA_ID"),
        "location": _first_text(row, "E__ManuCountry", "E__ManuPlant"),
        "version": None,
        "registration_number": _first_text(row, "E__EPD_RegNumber", "E__EPD_DecNumber"),
        "name": _first_text(row, "A__ProductName", "E__EPD_Product Name"),
        "manufacturer": _text(row, "A__Manufacturer"),
        "valid_from": None,
        "valid_until": _year(row, "E__EPD_ExpDate"),
        "declared_unit": _text(row, "G__GWP_FU"),
        "declared_unit_amount": _first_num(row, "E__EPD_kg-FU", "E__EPD_MultFactor"),
        "thickness": _thickness_m(row),
        "grammage": _num(row, "P__Mass_kgm2"),
        "gross_density": _first_num(row, "P__Mass_kgm3", "E__EPD_Density"),
        "bulk_density": None,
        "linear_density": None,
        "standard": _standard(row),
        "subtype": "specific dataset",
        "lambda": _first_num(row, "P__L_WmK", "E__L_WmK"),
        "u_value": _num(row, "P__U_Wm2K"),
        "r_value": _num(row, "E__Rvalue"),
        "source": _source_object(row),
        "gwp": gwp,
        "gwp_fossil": None,
        "gwp_biogenic": None,
        "gwp_luluc": None,
        "fw": None,
        "pert": None,
        "penrt": None,
        "energy_mix_percentage": None,
        "custom_attribute": _custom_attribute(row) or None,
        "additional_data": _additional_data(row) or None,
        "all_documents": _documents(row) or None,
        "certificates": _certificates(row) or None,
        "rsl": _text(row, "E__ServiceLife"),
        "tags": _tags(row) or None,
    }
    if not drop_empty:
        return payload
    gwp_clean = {k: v for k, v in gwp.items() if v is not None}
    payload["gwp"] = gwp_clean or None
    return {k: v for k, v in payload.items() if v is not None}


def build_revalu_payloads(
    df: pd.DataFrame,
    *,
    drop_empty: bool = True,
) -> list[dict[str, Any]]:
    """Every row of ``df`` as a Revalu EPD object (selection order preserved)."""
    if df is None or df.empty:
        return []
    return [build_revalu_payload(row, drop_empty=drop_empty) for _, row in df.iterrows()]


# ── validation ──────────────────────────────────────────────────────────────
#: Fields Revalu needs to make an EPD record usable on their side.
REQUIRED_FIELDS = ("id", "name", "manufacturer", "declared_unit")
#: Strongly recommended, but a record without them is still accepted.
RECOMMENDED_FIELDS = ("registration_number", "location", "valid_until", "source")


def validate_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for one payload.

    Errors block the hand-off; warnings only flag thin records.
    """
    errors = [f"missing `{f}`" for f in REQUIRED_FIELDS if not payload.get(f)]
    warnings = [f"no `{f}`" for f in RECOMMENDED_FIELDS if not payload.get(f)]
    gwp = payload.get("gwp") or {}
    if not gwp:
        errors.append("no GWP values")
    elif gwp.get("a1a3") is None:
        warnings.append("no `gwp.a1a3`")
    return errors, warnings


def validation_frame(payloads: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Per-record readiness table shown above the send button."""
    rows = []
    for payload in payloads:
        errors, warnings = validate_payload(payload)
        rows.append(
            {
                "EETRA ID": payload.get("id", ""),
                "Manufacturer": payload.get("manufacturer", ""),
                "Product": payload.get("name", ""),
                "Ready": "✅" if not errors else "❌",
                "Blocking": ", ".join(errors),
                "Warnings": ", ".join(warnings),
                "GWP modules": len(payload.get("gwp") or {}),
                "Fields": len(payload),
            }
        )
    return pd.DataFrame(rows)


# ── serialisation ───────────────────────────────────────────────────────────
def payloads_to_json(payloads: list[dict[str, Any]], *, indent: int = 2) -> str:
    """Hand-off document: ``{"epds": [...]}`` — mirrors POST /epds/multiple."""
    return json.dumps(
        {"epds": payloads, "count": len(payloads)}, indent=indent, ensure_ascii=False
    )


def payloads_to_ndjson(payloads: list[dict[str, Any]]) -> str:
    """One JSON object per line — the format bulk importers usually prefer."""
    return "\n".join(json.dumps(p, ensure_ascii=False) for p in payloads)


# ── credentials & transport ─────────────────────────────────────────────────
def _secret(section: str, key: str) -> str | None:
    try:
        import streamlit as st

        val = st.secrets.get(section, {}).get(key)
        if val:
            return str(val).strip()
    except Exception:
        pass
    return None


def revalu_api_key() -> str | None:
    """API key from ``[revalu] api_key`` or ``REVALU_API_KEY``."""
    return (
        _secret("revalu", "api_key")
        or (os.environ.get("REVALU_API_KEY") or "").strip()
        or None
    )


def revalu_ingest_url() -> str | None:
    """Partner ingestion endpoint from ``[revalu] ingest_url`` / ``REVALU_INGEST_URL``.

    Empty by default: the public API is read-only, so a POST target only exists
    once Revalu provisions one for the partnership.
    """
    return (
        _secret("revalu", "ingest_url")
        or (os.environ.get("REVALU_INGEST_URL") or "").strip()
        or None
    )


def verify_api_key(
    api_key: str, *, uuid: str = REVALU_SAMPLE_UUID, timeout: int = 20
) -> tuple[bool, str]:
    """Probe GET /epds/{uuid}/extended so the key is checked against the real API."""
    import requests

    url = REVALU_API_BASE + REVALU_EPD_EXTENDED_PATH.format(uuid=uuid)
    try:
        resp = requests.get(url, headers={REVALU_API_KEY_HEADER: api_key}, timeout=timeout)
    except Exception as exc:  # network, DNS, TLS …
        return False, f"Request failed: {exc}"
    if resp.status_code == 200:
        return True, "API key accepted — GET /epds/{uuid}/extended returned 200."
    if resp.status_code == 403:
        return False, "403 Forbidden — key missing, invalid, or a tier without access to this endpoint."
    if resp.status_code == 429:
        return False, "429 Limit Exceeded — the key is valid but rate-limited."
    return False, f"HTTP {resp.status_code}: {resp.text[:300]}"


def send_payloads(
    payloads: list[dict[str, Any]],
    *,
    api_key: str,
    ingest_url: str,
    timeout: int = 60,
) -> tuple[bool, str]:
    """POST the hand-off document to the configured partner ingestion URL."""
    import requests

    body = {"epds": payloads, "count": len(payloads), "source": "EETRA MatLib"}
    try:
        resp = requests.post(
            ingest_url,
            headers={REVALU_API_KEY_HEADER: api_key, "Content-Type": "application/json"},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"Request failed: {exc}"
    ok = 200 <= resp.status_code < 300
    return ok, f"HTTP {resp.status_code}: {resp.text[:600]}"
