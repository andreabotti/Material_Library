"""
lib_leed_voc.py — LEED v4.1 EQ Low-Emitting Materials: groups, requirements, verdict
====================================================================================
The structure and the guidance come from ``aux_17__leed_low_emitting.json`` (built
from the EETRA "Low Emitting Materials — LEED" workbook). Every text in that file
carries an ``it`` and an ``en`` string, so the module answers in the language the
app is speaking; nothing is hard-coded here except the control flow.

The hierarchy this module implements (the workbook's "Indicazioni per Material
Library"):

    1. the product is placed in one of the eight LEED material groups
    2. the group decides which requirements apply (VOC content / VOC emissions /
       formaldehyde) and, for each, which applicability code a certification must
       carry (GE, VC, CW, FF)
    3. the product's documentation is declared: a VOC claim (``VO__VOC_Cert``)
       and/or one or more accepted documents (``VO__LEED_Documents``)
    4. a listed certification covers a requirement only when its codes include
       the code the group asks for — see ``leed`` in aux_11__voc_certifications.json
    5. covered by the certification → compliant for that requirement
    6. not covered → the other accepted documents for that group are checked, and
       whatever is still open is reported as the gap to fill

Public API
----------
fn_load_leed_voc()                 the catalogue dict, memoized on file mtime
leed_lang(lang=None)               "it" / "en" for the active app language
leed_text(value, lang=None)        one bilingual value as a string
leed_groups()                      the eight groups, in workbook order
leed_group(ref)                    one group by id, LEED name or translated label
leed_group_ids()                   their ids
leed_group_label(ref, lang=None)   the display label of a group
leed_group_requirements(ref)       [{kind, cert_code, label, summary}, …]
leed_documents(ref=None)           accepted documents (all, or valid for a group)
leed_document_label(doc_id, …)     the display label of one document
leed_pathway_for_group(ref)        the VO__LEED_Pathway value a group implies
leed_thresholds(ref)               VOC content thresholds for the group, or []
leed_evaluate(group, certs, docs)  the verdict (see below)
leed_guidance(lang=None)           steps, general rules, "not sufficient" list

``leed_evaluate`` returns::

    {
      "group": {...} | None,
      "status": "compliant" | "partial" | "not_compliant" | "unknown",
      "requirements": [
          {"kind", "label", "cert_code", "summary",
           "covered": bool, "sources": [str, …]}, …],
      "covered": [kind, …],
      "missing": [kind, …],
      "unlisted_certs": [str, …],   # claims not on the LEED list for this group
      "headline": str,              # one line, in the active language
      "detail": str,                # what is still missing, in the active language
    }

Nothing is stored: the verdict is recomputed from the group, the claim and the
documents each time, so it cannot drift away from the fields it describes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_LEED_JSON = Path(__file__).resolve().parent.parent / "aux_17__leed_low_emitting.json"
_LEED_MEMO: dict = {"mtime": None, "data": None}

# Requirement kinds, in the order they are shown.
REQUIREMENT_ORDER: tuple[str, ...] = ("voc_content", "voc_emissions", "formaldehyde")

# Verdict vocabulary, with the one-line headline per language.
_HEADLINES = {
    "compliant": {
        "it": "Conforme — la documentazione copre tutti i requisiti della categoria",
        "en": "Compliant — the documentation covers every requirement of the group",
    },
    "partial": {
        "it": "Parziale — copre {covered}; da integrare: {missing}",
        "en": "Partial — covers {covered}; still to cover: {missing}",
    },
    "not_compliant": {
        "it": "Non sufficiente — nessun requisito della categoria risulta coperto",
        "en": "Not sufficient — none of the group's requirements is covered",
    },
    "unknown": {
        "it": "Selezionare la categoria LEED del materiale per valutare la conformità",
        "en": "Select the material's LEED group to assess compliance",
    },
}


# ── catalogue ────────────────────────────────────────────────────────────────
def fn_load_leed_voc() -> dict:
    """Read ``aux_17__leed_low_emitting.json`` (mtime-memoized, never raises)."""
    try:
        mtime = os.stat(_LEED_JSON).st_mtime_ns
        if _LEED_MEMO["mtime"] != mtime:
            with open(_LEED_JSON, "r", encoding="utf-8") as f:
                _LEED_MEMO["data"] = json.load(f)
            _LEED_MEMO["mtime"] = mtime
        return _LEED_MEMO["data"] or {}
    except Exception:
        return {}


def leed_lang(lang: str | None = None) -> str:
    """``it`` / ``en`` for *lang*, or for the language the app is speaking."""
    code = str(lang or "").strip().lower()
    if code in ("it", "ita", "italiano"):
        return "it"
    if code in ("en", "eng", "english"):
        return "en"
    if code:
        return "en"
    try:
        from .lib_i18n import fn702_current_language

        return "it" if str(fn702_current_language()).upper().startswith("IT") else "en"
    except Exception:
        return "en"


def leed_text(value, lang: str | None = None) -> str:
    """One bilingual value (``{"it":…, "en":…}``) as plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        code = leed_lang(lang)
        other = "en" if code == "it" else "it"
        return str(value.get(code) or value.get(other) or "")
    return str(value)


def leed_list(value, lang: str | None = None) -> list[str]:
    """A bilingual list (``{"it":[…], "en":[…]}``) as a list of strings."""
    if isinstance(value, dict):
        code = leed_lang(lang)
        other = "en" if code == "it" else "it"
        value = value.get(code) or value.get(other) or []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def leed_caveat(lang: str | None = None) -> str:
    """The standing warning that this is a working summary, not the credit text."""
    return leed_text(fn_load_leed_voc().get("_caveat"), lang)


def leed_credit(lang: str | None = None) -> dict:
    """``{"label", "url"}`` for the credit these groups belong to."""
    credit = fn_load_leed_voc().get("credit") or {}
    return {"label": leed_text(credit.get("label"), lang), "url": str(credit.get("url") or "")}


# ── groups ───────────────────────────────────────────────────────────────────
def leed_groups() -> list[dict]:
    """The eight LEED material groups, in workbook order."""
    return [g for g in (fn_load_leed_voc().get("groups") or []) if isinstance(g, dict)]


def leed_group_ids() -> list[str]:
    return [str(g.get("id") or "") for g in leed_groups()]


def leed_group(ref) -> dict | None:
    """One group by id, LEED name, or either translated label (case-insensitive).

    *ref* may already be a group dict, which is returned unchanged — callers can
    pass whatever they have without checking first.
    """
    if isinstance(ref, dict):
        return ref
    needle = str(ref or "").strip().lower()
    if not needle:
        return None
    for g in leed_groups():
        if str(g.get("id") or "").lower() == needle:
            return g
        if str(g.get("leed_name") or "").strip().lower() == needle:
            return g
        label = g.get("label") or {}
        if any(str(label.get(k) or "").strip().lower() == needle for k in ("it", "en")):
            return g
    return None


def leed_group_label(ref, lang: str | None = None) -> str:
    """Display label of a group; falls back to the raw value when unknown."""
    g = leed_group(ref)
    if not g:
        return "" if ref is None else str(ref)
    return leed_text(g.get("label"), lang) or str(g.get("leed_name") or "")


def leed_group_option_labels(lang: str | None = None) -> dict[str, str]:
    """``{group id: display label}`` for a dropdown, in workbook order.

    The LEED name is kept beside a translated label, because the group names are
    the calculator's own and submissions are written in English.
    """
    code = leed_lang(lang)
    out: dict[str, str] = {}
    for g in leed_groups():
        gid = str(g.get("id") or "")
        name = str(g.get("leed_name") or "")
        label = leed_text(g.get("label"), code)
        out[gid] = name if (code == "en" or not label or label == name) else f"{label} ({name})"
    return out


def leed_group_requirements(ref, lang: str | None = None) -> list[dict]:
    """``[{kind, cert_code, label, short, summary}, …]`` for one group."""
    g = leed_group(ref)
    if not g:
        return []
    defs = fn_load_leed_voc().get("requirements") or {}
    out = []
    for req in g.get("requirements") or []:
        kind = str(req.get("kind") or "")
        spec = defs.get(kind) or {}
        out.append({
            "kind": kind,
            "cert_code": str(req.get("cert_code") or spec.get("cert_code") or ""),
            "label": leed_text(spec.get("label"), lang) or kind,
            "short": leed_text(spec.get("short"), lang) or kind,
            "summary": leed_text(spec.get("summary"), lang),
        })
    return out


def leed_requirement_kinds(ref) -> list[str]:
    g = leed_group(ref)
    if not g:
        return []
    return [str(r.get("kind") or "") for r in (g.get("requirements") or [])]


def leed_applicability_codes(lang: str | None = None) -> dict[str, str]:
    """``{"GE": "General Emissions Evaluation", …}`` in the active language."""
    codes = fn_load_leed_voc().get("applicability_codes") or {}
    return {k: leed_text(v, lang) for k, v in codes.items()}


def leed_thresholds(ref) -> list[dict]:
    """VOC content thresholds (``subcategory`` / ``limit_g_l``) for one group."""
    g = leed_group(ref)
    if not g:
        return []
    key = str(g.get("voc_content_thresholds") or "")
    if not key:
        return []
    table = (fn_load_leed_voc().get("voc_content_thresholds") or {}).get(key) or []
    return [t for t in table if isinstance(t, dict)]


# ── documents ────────────────────────────────────────────────────────────────
def leed_documents(ref=None) -> list[dict]:
    """Accepted documents — all of them, or only those valid for one group."""
    docs = [d for d in (fn_load_leed_voc().get("documents") or []) if isinstance(d, dict)]
    g = leed_group(ref) if ref is not None else None
    if ref is None:
        return docs
    if not g:
        return []
    gid = str(g.get("id") or "")
    return [d for d in docs if (d.get("coverage") or {}).get(gid)]


def leed_document(doc_id: str | None) -> dict | None:
    needle = str(doc_id or "").strip().lower()
    if not needle:
        return None
    for d in leed_documents():
        if str(d.get("id") or "").lower() == needle:
            return d
        label = d.get("label") or {}
        if any(str(label.get(k) or "").strip().lower() == needle for k in ("it", "en")):
            return d
    return None


def leed_document_label(doc_id, lang: str | None = None) -> str:
    d = leed_document(doc_id)
    if not d:
        return "" if doc_id is None else str(doc_id)
    return leed_text(d.get("label"), lang)


def leed_document_conditions(doc_id, ref=None, lang: str | None = None) -> str:
    """What to verify in that document — the group-specific text when there is one."""
    d = leed_document(doc_id)
    if not d:
        return ""
    g = leed_group(ref) if ref is not None else None
    gid = str((g or {}).get("id") or "")
    by_group = d.get("conditions_by_group") or {}
    if gid and gid in by_group:
        return leed_text(by_group[gid], lang)
    return leed_text(d.get("conditions"), lang)


def leed_document_covers(doc_id, ref) -> list[str]:
    """Requirement kinds that *doc_id* covers in group *ref*."""
    d = leed_document(doc_id)
    g = leed_group(ref)
    if not d or not g:
        return []
    return list((d.get("coverage") or {}).get(str(g.get("id") or "")) or [])


def leed_document_option_labels(ref=None, lang: str | None = None) -> dict[str, str]:
    """``{document id: display label}`` for the multiselect, in catalogue order."""
    return {str(d.get("id") or ""): leed_text(d.get("label"), lang) for d in leed_documents(ref)}


# ── certifications ───────────────────────────────────────────────────────────
def _cert_applicability(label: str | None) -> tuple[dict | None, list[str]]:
    """``(catalogue entry, applicability codes)`` for one VOC claim."""
    try:
        from .lib_revalu_map import voc_cert_by_label
    except Exception:
        return None, []
    entry = voc_cert_by_label(label)
    if not entry:
        return None, []
    leed = entry.get("leed") or {}
    codes = [str(c).upper() for c in (leed.get("applicability") or [])]
    return entry, codes


def leed_cert_codes(label: str | None) -> list[str]:
    """The GE / VC / CW / FF codes one VOC claim carries (empty when not listed)."""
    return _cert_applicability(label)[1]


def leed_cert_is_listed(label: str | None) -> bool:
    entry, _ = _cert_applicability(label)
    return bool((entry or {}).get("leed", {}).get("listed"))


def leed_certs_for_group(ref, lang: str | None = None) -> list[dict]:
    """Every listed certification, with what it covers in group *ref*.

    ``[{label, body, codes, covers: [kind, …], outcome}]`` — outcome is
    ``full`` / ``partial`` / ``none``, matching the workbook's three bands.
    """
    g = leed_group(ref)
    if not g:
        return []
    try:
        from .lib_revalu_map import voc_cert_entries
    except Exception:
        return []
    needed = [(r["kind"], r["cert_code"]) for r in leed_group_requirements(g, lang)]
    rows = []
    for entry in voc_cert_entries():
        leed = entry.get("leed") or {}
        if not leed.get("listed"):
            continue
        codes = [str(c).upper() for c in (leed.get("applicability") or [])]
        covers = [kind for kind, code in needed if code and code in codes]
        outcome = "full" if len(covers) == len(needed) and needed else (
            "partial" if covers else "none")
        rows.append({
            "label": str(entry.get("label") or ""),
            "body": str(entry.get("body") or ""),
            "codes": codes,
            "covers": covers,
            "outcome": outcome,
        })
    order = {"full": 0, "partial": 1, "none": 2}
    rows.sort(key=lambda r: (order[r["outcome"]], r["label"].lower()))
    return rows


# ── the verdict ──────────────────────────────────────────────────────────────
def _as_list(value) -> list[str]:
    """Accept a list, a ``;``-joined string or a single value."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        text = str(value).strip()
        if not text:
            return []
        items = text.split(";") if ";" in text else [text]
    out = []
    for item in items:
        s = str(item).strip()
        if s and s.lower() not in ("nan", "none", "<na>", "-", "*"):
            out.append(s)
    return out


def leed_evaluate(group, certs=None, documents=None, lang: str | None = None) -> dict:
    """The compliance verdict for one product — step 4 to 6 of the hierarchy.

    *group* is anything ``leed_group`` accepts, *certs* one or more VOC claims
    (``VO__VOC_Cert``) and *documents* the accepted-document ids
    (``VO__LEED_Documents``), as a list or a ``;``-joined string.
    """
    code = leed_lang(lang)
    g = leed_group(group)
    if not g:
        return {
            "group": None, "status": "unknown", "requirements": [],
            "covered": [], "missing": [], "unlisted_certs": [],
            "headline": _HEADLINES["unknown"][code], "detail": "",
        }

    reqs = leed_group_requirements(g, code)
    rows = [dict(r, covered=False, sources=[]) for r in reqs]
    by_kind = {r["kind"]: r for r in rows}
    unlisted: list[str] = []

    # Step 4/5 — a listed certification covers a requirement when its codes
    # include the code this group asks for.
    for label in _as_list(certs):
        try:
            from .lib_revalu_map import voc_cert_is_not_relevant

            if voc_cert_is_not_relevant(label):
                continue
        except Exception:
            pass
        entry, codes = _cert_applicability(label)
        hit = False
        for row in rows:
            if row["cert_code"] and row["cert_code"] in codes:
                row["covered"] = True
                row["sources"].append(label)
                hit = True
        if not hit and not leed_cert_is_listed(label):
            unlisted.append(label)

    # Step 6 — whatever the certification leaves open, the other accepted
    # documents for this group may close.
    gid = str(g.get("id") or "")
    for doc_id in _as_list(documents):
        doc = leed_document(doc_id)
        if not doc:
            continue
        for kind in (doc.get("coverage") or {}).get(gid) or []:
            row = by_kind.get(kind)
            if row is not None:
                row["covered"] = True
                row["sources"].append(leed_text(doc.get("label"), code))

    covered = [r["kind"] for r in rows if r["covered"]]
    missing = [r["kind"] for r in rows if not r["covered"]]
    status = "compliant" if rows and not missing else ("partial" if covered else "not_compliant")

    if status == "partial":
        headline = _HEADLINES["partial"][code].format(
            covered=", ".join(by_kind[k]["label"] for k in covered),
            missing=", ".join(by_kind[k]["label"] for k in missing),
        )
    else:
        headline = _HEADLINES[status][code]

    detail = ""
    if missing:
        hints = []
        for kind in missing:
            options = [
                leed_text(d.get("label"), code)
                for d in leed_documents(g)
                if kind in ((d.get("coverage") or {}).get(gid) or [])
            ]
            if options:
                lead = ("Per {req} serve uno fra: {opts}." if code == "it"
                        else "For {req}, one of: {opts}.")
                hints.append(lead.format(req=by_kind[kind]["label"], opts="; ".join(options)))
        detail = " ".join(hints)
    elif status == "compliant":
        detail = leed_text(g.get("project_threshold"), code)

    return {
        "group": g, "status": status, "requirements": rows,
        "covered": covered, "missing": missing, "unlisted_certs": unlisted,
        "headline": headline, "detail": detail,
    }


# ── derived field ────────────────────────────────────────────────────────────
# The LEED pathway a group implies, in the vocabulary VO__LEED_Pathway already
# uses (lib_revalu_map.VOC_LEED_PATHWAYS). Derived, never typed: the group is
# the single answer to "which pathway does this product's evidence serve?".
# Keys are the group's requirement kinds, sorted — the group states them in
# reading order, which is not the order they compare in.
_PATHWAY_BY_KINDS: dict[tuple[str, ...], str] = {
    ("voc_content",): "VOC Content",
    ("voc_emissions",): "VOC Emissions",
    ("voc_content", "voc_emissions"): "VOC Emissions + VOC Content",
    ("formaldehyde",): "Formaldehyde Emissions",
    ("formaldehyde", "voc_emissions"): "VOC Emissions + Formaldehyde Emissions",
}


def leed_pathway_for_group(ref) -> str:
    """The ``VO__LEED_Pathway`` value group *ref* implies ("" when unknown)."""
    g = leed_group(ref)
    if not g:
        return ""
    kinds = tuple(sorted(leed_requirement_kinds(g)))
    if str(g.get("id") or "") == "furniture":
        return "Furniture Emissions"
    return _PATHWAY_BY_KINDS.get(kinds, "")


# ── payload for the browser-side editor ──────────────────────────────────────
def leed_editor_payload(lang: str | None = None) -> dict:
    """Everything the browser-side editor needs, with the rule already applied.

    The Add/Edit form runs in the browser (libs/item_editor), so it cannot call
    ``leed_evaluate``. Rather than restate the hierarchy in JavaScript, this
    resolves it here into two lookups per group — what each certification covers
    and what each document covers — leaving the frontend with a set union. The
    rule stays in this module; only the arithmetic crosses.
    """
    code = leed_lang(lang)
    try:
        from .lib_revalu_map import voc_cert_entries
    except Exception:
        voc_cert_entries = lambda: []  # noqa: E731

    certs = list(voc_cert_entries())
    groups = []
    for g in leed_groups():
        gid = str(g.get("id") or "")
        reqs = leed_group_requirements(g, code)
        needed = {r["kind"]: r["cert_code"] for r in reqs}

        cert_covers: dict[str, list[str]] = {}
        listed: list[str] = []
        for entry in certs:
            leed = entry.get("leed") or {}
            phrases = [entry.get("label"), *(entry.get("aliases") or [])]
            keys = [str(p).strip().lower() for p in phrases if str(p or "").strip()]
            if leed.get("listed"):
                listed.extend(keys)
            codes = [str(c).upper() for c in (leed.get("applicability") or [])]
            covers = [k for k, c in needed.items() if c and c in codes]
            if covers:
                for key in keys:
                    cert_covers[key] = covers

        docs = []
        doc_covers: dict[str, list[str]] = {}
        for d in leed_documents(g):
            did = str(d.get("id") or "")
            covers = list((d.get("coverage") or {}).get(gid) or [])
            doc_covers[did] = covers
            docs.append({
                "id": did,
                "label": leed_text(d.get("label"), code),
                "covers": covers,
                "conditions": leed_document_conditions(did, g, code),
            })

        hints = {}
        for kind in needed:
            options = [d["label"] for d in docs if kind in d["covers"]]
            if options:
                lead = ("Per {req} serve uno fra: {opts}." if code == "it"
                        else "For {req}, one of: {opts}.")
                hints[kind] = lead.format(
                    req=next(r["label"] for r in reqs if r["kind"] == kind),
                    opts="; ".join(options),
                )

        groups.append({
            "id": gid,
            "name": str(g.get("leed_name") or ""),
            "label": leed_group_label(g, code),
            "option_label": leed_group_option_labels(code).get(gid, gid),
            "requirements": reqs,
            "scope": leed_text(g.get("scope"), code),
            "threshold": leed_text(g.get("project_threshold"), code),
            "note": leed_text(g.get("note"), code),
            "allow_non_emitting": bool(g.get("allow_inherently_non_emitting")),
            "allow_salvaged": bool(g.get("allow_salvaged")),
            "pathway": leed_pathway_for_group(g),
            "cert_covers": cert_covers,
            "listed": sorted(set(listed)),
            "documents": docs,
            "doc_covers": doc_covers,
            "hints": hints,
            "thresholds": leed_thresholds(g),
        })

    it = code == "it"
    return {
        "lang": code,
        "groups": groups,
        "text": {
            "requirements": "Requisiti" if it else "Requirements",
            "alternatives": "Alternative ammesse" if it else "Alternatives allowed",
            "non_emitting": "Intrinsecamente non emissivo" if it else "Inherently non-emitting",
            "salvaged": "Materiale di recupero" if it else "Salvaged material",
            "threshold": "Soglia di progetto" if it else "Project threshold",
            "pick_group": ("Scegliere la categoria LEED: decide quali requisiti il prodotto deve "
                           "dimostrare." if it else
                           "Choose the LEED group: it decides which requirements the product must "
                           "demonstrate."),
            "pick_group_first": ("Selezionare prima la categoria LEED" if it
                                 else "Select a LEED material group first"),
            "not_set": "(non indicata)" if it else "(not set)",
            "unlisted": ("non è fra le certificazioni accettate da LEED per questa categoria" if it
                         else "is not among the certifications LEED accepts for this group"),
            "guidance": "Guida LEED" if it else "LEED guidance",
            "conditions": "Da verificare nel documento" if it else "What to verify in the document",
            "covers": "copre" if it else "covers",
            "not_sufficient": ("Documenti NON sufficienti" if it
                               else "Documents that are NOT sufficient"),
            "general_rules": "Regole generali" if it else "General rules",
            "thresholds": ("Soglie VOC content per sottocategoria (g/l)" if it
                           else "VOC content thresholds by sub-category (g/l)"),
            "compliant": _HEADLINES["compliant"][code],
            "not_compliant": _HEADLINES["not_compliant"][code],
            "partial_covers": "Parziale — copre" if it else "Partial — covers",
            "partial_missing": "da integrare" if it else "still to cover",
        },
        "guidance": leed_guidance(code),
        "caveat": leed_caveat(code),
        "credit": leed_credit(code),
    }


# ── guidance ─────────────────────────────────────────────────────────────────
def leed_guidance(lang: str | None = None) -> dict:
    """``{steps, general_rules, not_sufficient}`` in the active language."""
    data = fn_load_leed_voc()
    return {
        "steps": leed_list(data.get("steps"), lang),
        "general_rules": leed_list(data.get("general_rules"), lang),
        "not_sufficient": leed_list(data.get("not_sufficient"), lang),
    }
