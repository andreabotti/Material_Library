"""
libs/lib_en520.py — EN 520 board-type designations for Building boards
======================================================================
Builds the ``en520`` payload shown in the JS2 catalogue detail panel
(Tech. Details tab → "EN 520:2004+A1:2009" section).

Designations are read from ``S__Comments`` ("Type D E F H1 I R"); products
without one, or that are not EN 520 boards, are covered by the ``overrides``
in ``aux_04__en520_designations.json``, which also holds the type definitions.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_REF_PATH = Path(__file__).resolve().parent.parent / "aux_04__en520_designations.json"
BUILDING_BOARDS = "Building boards"

_TYPE_RE = re.compile(r"\bType\s+([A-Z0-9 \-]+?)\s*(?:$|[\n\r(,;]|Product)", re.I)
_TOKEN_RE = re.compile(r"H[123]|[ADEFIPR]")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


@lru_cache(maxsize=1)
def _reference() -> dict:
    try:
        return json.loads(_REF_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _thickness_mm(v) -> float | None:
    m = _NUM_RE.search(str(v or ""))
    if not m:
        return None
    try:
        t = float(m.group(0).replace(",", "."))
    except ValueError:
        return None
    return t if t > 0 else None


def _fmt_n(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def _type_rows(codes: list[str], types: dict, thickness: float | None, with_req: bool) -> list[dict]:
    rows = []
    for code in codes:
        spec = types.get(code)
        if not spec:
            continue
        req = spec.get("req", "") if with_req else ""
        if with_req and code == "R" and thickness:
            req = (
                f"Flexural breaking load ≥ {_fmt_n(58 * thickness)} N longitudinal, "
                f"≥ {_fmt_n(24 * thickness)} N transverse (at {thickness:g} mm)"
            )
        rows.append({"code": code, "name": spec.get("name", ""), "req": req})
    return rows


def fn_en520_payload(eetra_id, product_type, comments, thickness) -> dict | None:
    """``{standard, designation, types:[{code,name,req}], note, source}`` or None."""
    if str(product_type or "").strip() != BUILDING_BOARDS:
        return None
    ref = _reference()
    if not ref:
        return None
    std = ref.get("standard", "EN 520")
    types = ref.get("types", {})

    ov = (ref.get("overrides") or {}).get(str(eetra_id or "").strip())
    if ov:
        return {
            "standard": ov.get("standard", ""),
            "designation": ov.get("designation", ""),
            "types": [],
            "note": ov.get("note", ""),
            "source": ov.get("source", ""),
            "inScope": False,
        }

    m = _TYPE_RE.search(str(comments or ""))
    if not m:
        return {
            "standard": std, "designation": "", "types": [], "source": "", "inScope": True,
            "note": "EN 520 type designation not recorded — check the DoP.",
        }
    raw = m.group(1).upper()
    t = _thickness_mm(thickness)

    # "G M - F H1 I R" → glass-mat board under EN 15283-1 (GM-FH1IR).
    gm = re.match(r"\s*G\s*M\b\s*-?\s*(.*)", raw)
    if gm:
        codes = _TOKEN_RE.findall(gm.group(1))
        gm_ref = ref.get("glass_mat", {})
        return {
            "standard": gm_ref.get("standard", "EN 15283-1"),
            "designation": "GM-" + "".join(codes),
            "types": _type_rows(codes, types, t, with_req=False),
            "note": gm_ref.get("note", ""),
            "source": "",
            "inScope": False,
        }

    codes = list(dict.fromkeys(_TOKEN_RE.findall(raw)))
    return {
        "standard": std,
        "designation": "Type " + "".join(codes),
        "types": _type_rows(codes, types, t, with_req=True),
        "note": "",
        "source": "",
        "inScope": True,
    }
