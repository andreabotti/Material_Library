"""
libs/lib_epd_family.py — EPD families: one reference product, many scaled variants
=================================================================================
Many EPDs declare one **reference product** and a table of multiplication
factors for the other products they cover (other thicknesses, facings, …).
The library models that with two EPD columns:

  • ``E__EPD_ConvFactor`` — ``Y`` on the reference product, ``N`` on every
    product whose figures are the reference's × a factor.
  • ``E__EPD_MultFactor`` — that factor (the reference implicitly has 1).

Products belong to the same family when their ``E__EPD_RegNumber`` matches
after whitespace/case normalisation (the workbook has both ``S-P-01137`` and
``S-P- 01137``).

Variant GWP data is never typed by hand: every GWP module (A1–A3, A1 … D) is
the reference value × factor, Metric and FU are copied, and the four
normalised bases (_kg / _m3 / _m2 / _m2R1) are re-derived from the scaled
A1–A3 and the variant's own ρ / d / λ — the same rules as GWP_CONVERSIONS.md
and the GWP conversion panel on the Add/Edit page.

Pure pandas — no Streamlit — so it is testable and reusable.
"""
from __future__ import annotations

import math
import re
from typing import Mapping

import pandas as pd

REG_COL = "E__EPD_RegNumber"
REF_FLAG_COL = "E__EPD_ConvFactor"
FACTOR_COL = "E__EPD_MultFactor"
ID_COL = "0__EETRA_ID"

# Every per-declared-unit GWP figure: scaled by the factor.
GWP_MODULE_COLS: tuple[str, ...] = (
    "G__GWP_A1A3",
    "G__GWP_A1", "G__GWP_A2", "G__GWP_A3", "G__GWP_A4", "G__GWP_A5",
    "G__GWP_B1", "G__GWP_B2", "G__GWP_B3", "G__GWP_B4", "G__GWP_B5",
    "G__GWP_B6", "G__GWP_B7",
    "G__GWP_C1", "G__GWP_C2", "G__GWP_C3", "G__GWP_C4", "G__GWP_D",
)
# Same EPD ⇒ same metric and declared unit: copied verbatim.
GWP_COPY_COLS: tuple[str, ...] = ("G__GWP_Metric", "G__GWP_FU")
# Normalised bases: re-derived per variant from its own physical properties.
GWP_BASIS_COLS: tuple[str, ...] = (
    "G__GWP_A1A3_kg", "G__GWP_A1A3_m3", "G__GWP_A1A3_m2", "G__GWP_A1A3_m2R1",
)
DERIVED_COLS: tuple[str, ...] = GWP_COPY_COLS + GWP_MODULE_COLS + GWP_BASIS_COLS

# Physical inputs for the bases: primary column, EPD fallback column.
_PHYS_INPUTS: dict[str, tuple[str, str]] = {
    "rho": ("P__Mass_kgm3", "E__EPD_Density"),
    "d_mm": ("P__Thick_mm", "E__EPD_Thick_mm"),
    "lam": ("P__L_WmK", "E__L_WmK"),
    "m_a": ("P__Mass_kgm2", ""),
    "r": ("E__Rvalue", ""),
}

# Declared unit (G__GWP_FU) → (anchored basis column, factor on G__GWP_A1A3).
FU_ANCHORS: dict[str, tuple[str, float]] = {
    "m3": ("G__GWP_A1A3_m3", 1.0),
    "m2": ("G__GWP_A1A3_m2", 1.0),
    "kg": ("G__GWP_A1A3_kg", 1.0),
    "ton": ("G__GWP_A1A3_kg", 0.001),
    "tonne": ("G__GWP_A1A3_kg", 0.001),
    "t": ("G__GWP_A1A3_kg", 0.001),
    "m2_r1": ("G__GWP_A1A3_m2R1", 1.0),
}

_NULL_TOKENS = {"", "nan", "none", "<na>", "-", "n/a", "n/r", "na", "nr", "*"}


def fn620_normalise_reg(value) -> str:
    """EPD registration number as a family key: no whitespace, upper case."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA:
        return ""
    s = re.sub(r"\s+", "", str(value)).upper()
    return "" if s.lower() in _NULL_TOKENS else s


def fn621_num(value) -> float | None:
    """Float from a cell, or None for blank / n/a / n/r / text."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if math.isnan(float(value)) else float(value)
    s = str(value).strip().replace(",", ".")
    if s.lower() in _NULL_TOKENS:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return None if math.isnan(f) else f


def _flag(value) -> str:
    s = "" if value is None or value is pd.NA else str(value).strip().upper()
    return {"YES": "Y", "NO": "N", "SI": "Y", "SÌ": "Y"}.get(s, s)


def fn622_is_reference(row: Mapping) -> bool:
    """True when the row is flagged as its EPD's reference product."""
    return _flag(row.get(REF_FLAG_COL)) == "Y"


def fn623_is_variant(row: Mapping) -> bool:
    """True when the row is flagged as a factor-scaled product of its EPD."""
    return _flag(row.get(REF_FLAG_COL)) == "N"


def fn624_family(df: pd.DataFrame, reg_number) -> pd.DataFrame:
    """All rows whose normalised EPD registration number equals *reg_number*'s."""
    key = fn620_normalise_reg(reg_number)
    if not key or df is None or df.empty or REG_COL not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    return df.loc[df[REG_COL].map(fn620_normalise_reg) == key]


def fn625_family_reference(
    df: pd.DataFrame, reg_number, *, exclude_id: str | None = None
) -> tuple[dict | None, str]:
    """The reference row of an EPD family.

    Returns ``(row, status)`` with status ``"ok"``, ``"none"`` (no row flagged
    Y) or ``"ambiguous"`` (more than one — the workbook needs fixing, so nothing
    is derived rather than guessing). *exclude_id* drops the row being edited.
    """
    fam = fn624_family(df, reg_number)
    if exclude_id is not None and ID_COL in fam.columns:
        fam = fam.loc[fam[ID_COL].astype(str) != str(exclude_id)]
    refs = [r for r in fam.to_dict("records") if fn622_is_reference(r)]
    if not refs:
        return None, "none"
    if len(refs) > 1:
        return None, "ambiguous"
    return refs[0], "ok"


def fn626_family_variants(
    df: pd.DataFrame, reg_number, *, exclude_id: str | None = None
) -> list[dict]:
    """Rows of the family flagged N with a numeric multiplication factor."""
    fam = fn624_family(df, reg_number)
    if exclude_id is not None and ID_COL in fam.columns:
        fam = fam.loc[fam[ID_COL].astype(str) != str(exclude_id)]
    return [
        r for r in fam.to_dict("records")
        if fn623_is_variant(r) and fn621_num(r.get(FACTOR_COL)) is not None
    ]


def _norm_fu(value) -> str:
    s = "" if value is None or value is pd.NA else str(value)
    s = s.strip().lower().replace("³", "3").replace("²", "2")
    return s.replace("m^3", "m3").replace("m^2", "m2").replace(" ", "")


def fn627_derive_gwp_bases(
    decl: float | None,
    fu,
    *,
    rho: float | None = None,
    d_mm: float | None = None,
    lam: float | None = None,
    m_a: float | None = None,
    r: float | None = None,
) -> dict[str, float | None]:
    """The four normalised GWP bases from one declared A1–A3 figure.

    Anchor on the declared unit, pivot through GWP/m³, fan out — identical to
    GWP_CONVERSIONS.md §2–§3. A basis that cannot be reached is None.
    """
    out: dict[str, float | None] = {c: None for c in GWP_BASIS_COLS}
    anchor_col, anchor_factor = FU_ANCHORS.get(_norm_fu(fu), ("", 0.0))
    if decl is None or not anchor_col:
        return out
    anchor = decl * anchor_factor
    d = None if d_mm is None else d_mm / 1000.0
    if m_a is None and rho is not None and d is not None:
        m_a = rho * d
    if r is None and d is not None and lam:
        r = d / lam

    g3 = None
    if anchor_col == "G__GWP_A1A3_m3":
        g3 = anchor
    elif anchor_col == "G__GWP_A1A3_kg" and rho is not None:
        g3 = anchor * rho
    elif anchor_col == "G__GWP_A1A3_m2" and d:
        g3 = anchor / d
    elif anchor_col == "G__GWP_A1A3_m2R1" and lam:
        g3 = anchor / lam

    g_kg = g3 / rho if (g3 is not None and rho) else (
        anchor if anchor_col == "G__GWP_A1A3_kg" else None
    )
    if g3 is not None and d is not None:
        g_m2 = g3 * d
    elif g_kg is not None and m_a is not None:
        g_m2 = g_kg * m_a
    else:
        g_m2 = None
    if g3 is not None and lam is not None:
        g_m2r1 = g3 * lam
    elif g_m2 is not None and r:
        g_m2r1 = g_m2 / r
    else:
        g_m2r1 = None

    out.update({
        "G__GWP_A1A3_kg": g_kg, "G__GWP_A1A3_m3": g3,
        "G__GWP_A1A3_m2": g_m2, "G__GWP_A1A3_m2R1": g_m2r1,
    })
    out[anchor_col] = anchor
    return out


def _round(x: float) -> float:
    """Drop float noise (2.7 × 0.87 = 2.3490000000000002) — 10 significant digits."""
    return float(f"{x:.10g}")


def _phys(row: Mapping, key: str) -> float | None:
    primary, fallback = _PHYS_INPUTS[key]
    v = fn621_num(row.get(primary))
    if v is None and fallback:
        v = fn621_num(row.get(fallback))
    return v


def fn628_variant_gwp_values(
    reference: Mapping, factor: float, variant: Mapping
) -> dict:
    """GWP columns for one variant: reference × *factor*, bases re-derived.

    *variant* supplies the variant's own physical properties and, for a basis
    its ρ / d / λ cannot reach, its previously stored value — rescaled by the
    change in A1–A3 so it stays consistent instead of going stale.
    """
    out: dict = {}
    for col in GWP_COPY_COLS:
        v = reference.get(col)
        out[col] = None if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)) else v
    for col in GWP_MODULE_COLS:
        ref_v = reference.get(col)
        n = fn621_num(ref_v)
        if n is not None:
            out[col] = _round(n * factor)
        elif ref_v is None or ref_v is pd.NA or (isinstance(ref_v, float) and math.isnan(ref_v)):
            out[col] = None
        else:
            out[col] = ref_v  # mnd / n/r / text: same declaration status as the reference

    decl = fn621_num(out.get("G__GWP_A1A3"))
    bases = fn627_derive_gwp_bases(
        decl, out.get("G__GWP_FU"),
        **{k: _phys(variant, k) for k in _PHYS_INPUTS},
    )
    old_decl = fn621_num(variant.get("G__GWP_A1A3"))
    for col, v in bases.items():
        if v is None and decl is not None and old_decl:
            old_v = fn621_num(variant.get(col))
            v = None if old_v is None else old_v * decl / old_decl
        out[col] = None if v is None else _round(v)
    return out


def _same(a, b) -> bool:
    na, nb = fn621_num(a), fn621_num(b)
    if na is not None or nb is not None:
        if na is None or nb is None:
            return False
        return math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-12)
    blank = lambda v: v is None or v is pd.NA or str(v).strip() in ("", "nan", "<NA>")  # noqa: E731
    if blank(a) and blank(b):
        return True
    return str(a).strip() == str(b).strip()


def fn629_propagation_plan(df: pd.DataFrame, reference: Mapping) -> list[dict]:
    """What saving *reference* does to the rest of its EPD family.

    Returns one entry per variant whose GWP data would change::

        {"id", "name", "factor", "values": {col: new}, "before": {col: old}}

    Nothing is returned when *reference* is not flagged Y, has no registration
    number, or its family has another product also flagged Y (ambiguous).
    """
    if not fn622_is_reference(reference):
        return []
    reg = reference.get(REG_COL)
    ref_id = reference.get(ID_COL)
    _, status = fn625_family_reference(df, reg, exclude_id=ref_id)
    if status != "none":  # another Y in the family: don't fight over the variants
        return []
    plan: list[dict] = []
    for var in fn626_family_variants(df, reg, exclude_id=ref_id):
        factor = fn621_num(var.get(FACTOR_COL))
        new = fn628_variant_gwp_values(reference, factor, var)
        changed = {c: v for c, v in new.items() if not _same(var.get(c), v)}
        if changed:
            plan.append({
                "id": str(var.get(ID_COL)),
                "name": str(var.get("A__ProductName") or ""),
                "factor": factor,
                "values": changed,
                "before": {c: var.get(c) for c in changed},
            })
    return plan
