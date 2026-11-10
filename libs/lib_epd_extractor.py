"""
lib_epd_extractor.py  –  EETRA Material Library EPD extractor
────────────────────────────────────────────────────────────────────────────
Extraction strategy (cheapest first):

  1. PyMuPDF text extraction + programme operator detection
  2a. IBU EPD  → column-aware table parser (all modules, all indicators)
  2b. Environdec (modern) → deterministic regex parse
  3.  Claude TEXT API — essential fields (metadata + GWP + SM)
  4.  Claude TEXT API — detail fields (product content, production, flow)
      [optional, separate call, only when detail=True]
  5.  Claude VISION API — fallback for scanned/image-only PDFs

Token cost reference per EPD:
  IBU/Environdec deterministic (no API)   $0.000
  Claude text essential  (3–5 pages)      ~$0.002–0.006
  Claude text detail     (3–5 pages)      ~$0.002–0.006  (additional, optional)
  Claude vision          (3–8 pages)      ~$0.05–0.15    (scanned PDF only)

Output fields
─────────────
Every numeric field is accompanied by a parallel  <field>_source  key whose
value is one of:
  "parsed"      — value read directly from a table cell or unambiguous text
  "calculated"  — value derived by summing per-stage columns (e.g. A1+A2+A3)
  None          — field not found

Essential output fields
───────────────────────
  product_name, manufacturer, declared_unit, reference_standard
  gwp_total        A1-A3 GWP-total / GWP-GHG        (kg CO2eq)
  gwp_fossil       A1-A3 GWP fossil                  (EN 15804+A2 only)
  gwp_biogenic     A1-A3 GWP biogenic                (EN 15804+A2 only)
  gwp_luluc        A1-A3 GWP LULUC                   (EN 15804+A2 only)
  gwp_a1/a2/a3     per-stage values when available
  sm               Use of secondary material, A1-A3 (kg)
  recycled_content_pct   declared % post-consumer recycled by mass
  epd_number, programme_operator, validity_date
  confidence, notes

Extended per-module fields (populated by IBU table parser & Claude)
────────────────────────────────────────────────────────────────────
  gwp_total_{module}   for module in a1a3, a4, a5, b1_b7, c1, c2, c3, c4, d
  gwp_fossil_{module}  for module in a1a3, c1, c2, c3, c4, d
  gwp_biogenic_{module}
  gwp_luluc_{module}
  odp_{module}, ap_{module}, ep_freshwater_{module}, ep_marine_{module},
  ep_terrestrial_{module}, pocp_{module}, adpe_{module}, adpf_{module},
  wdp_{module}
  penre_{module}, pere_{module}, fw_{module}

Optional detail fields (detail=True)
──────────────────────────────────────
  product_description, product_composition, production_method,
  system_boundary, modules_declared, flow_description,
  functional_unit, geographic_scope, third_party_verifier,
  pcr_reference, lca_software, lca_database,
  detail_confidence, detail_notes
"""

from __future__ import annotations
import base64, json, re, traceback
from pathlib import Path

import anthropic
import fitz  # PyMuPDF


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

MODEL = "claude-sonnet-4-6"
MAX_TOKENS_ESSENTIAL = 1536   # slightly larger to accommodate extended fields
MAX_TOKENS_DETAIL     = 2048

LCA_KW_RE = re.compile(
    r"\bGWP\b|kg\s*CO.?eq|A1[\-\u2013]A3|A1\s*/\s*A3|"
    r"global\s*warming|biogenic|fossil|luluc|land\s*use|"
    r"secondary\s*material|Sekund\u00e4r|indicatori\s*ambientali|"
    r"Treibhausgas|r\u00e9sultats\s*environnementaux|"
    r"GWP.total|GWP.fossil|GWP.biogen|climate\s*change|"
    r"LCA.*[Rr]esult|PENRE|PERE|ADPF|ADPE|POCP",
    re.IGNORECASE,
)

DETAIL_KW_RE = re.compile(
    r"product\s*description|composition|manufacturing|production\s*process|"
    r"raw\s*material|costituenti|descrizione|fabbricazione|processo\s*produttivo|"
    r"system\s*boundary|confine\s*del\s*sistema|scope|flow\s*diagram|"
    r"functional\s*unit|unit\u00e0\s*funzionale|declared\s*unit|"
    r"geographic",
    re.IGNORECASE,
)

PROG_RE = re.compile(
    r"\b(IBU|Institut Bauen und Umwelt|"
    r"EPD[\s\-]*IES|EPD\s*International\s*AB|The International EPD|Environdec|"
    r"EPD\s*Nor(?:ge|way)|Norwegian EPD [Ff]oundation|NEPD|"
    r"EPDItaly|EPD\s*Italy|"
    r"EPD\s*Hub|"
    r"RINA|BRE|INIES)\b",
    re.IGNORECASE,
)

EPD_NUM_RE = re.compile(
    r"\b(EPD-[A-Z0-9]{2,8}-\d{8}-[A-Z0-9]{3,6}-[A-Z]{2}|"   # IBU
    r"EPD-IES-\d{7,}|S-P-\d{5,}|"                              # Environdec
    r"NEPD-\d{4}-\d{4}-[A-Z]{2}|"                              # EPD Norway
    r"EPDITAL[YY]\d{4,}|EPD_\d+_\d+|"                          # EPDItaly
    r"HUB-\d{4,})\b",                                           # EPD Hub
    re.IGNORECASE,
)

SM_RE = re.compile(
    r"Use of secondary material|Einsatz von Sekund\u00e4rstoffen|"
    r"Utilizzo di materie prime recuperate|Secondary materials|"
    r"secondary material\b",
    re.IGNORECASE,
)

_NUM_RE = re.compile(r"[-\u2013]?\d{1,6}(?:[,\.]\d{1,6})*(?:[Ee][+\-]?\d+)?")

# IBU GWP row label patterns (for regex-based fallback)
IBU_GWP_ROWS = [
    ("gwp_total",    [r"GWP.{0,15}GHG", r"GWP[\s\-]*total", r"Treibhausgaspotenzial\s*\(GWP\)"]),
    ("gwp_fossil",   [r"GWP.{0,15}fossil"]),
    ("gwp_biogenic", [r"GWP.{0,15}biogen"]),
    ("gwp_luluc",    [r"GWP.{0,15}luluc", r"GWP.{0,15}land"]),
]

# Environdec GWP row label patterns
ENV_GWP_ROWS = [
    ("gwp_total",    [r"GWP[\s\-]+total", r"Climate change\s*\(GWP[\s\-]*total\)", r"Climate change$"]),
    ("gwp_fossil",   [r"GWP[\s\-]+fossil", r"Climate change\s*[-–]\s*Fossil", r"Fossil\s*-\s*kg CO"]),
    ("gwp_biogenic", [r"GWP[\s\-]+biogen", r"Climate change\s*[-–]\s*Biogenic", r"biogenic\s*-\s*kg"]),
    ("gwp_luluc",    [r"GWP[\s\-]+luluc", r"GWP[\s\-]+land", r"\(GWP[\s\-]*luluc\)"]),
]


# ═══════════════════════════════════════════════════════════════════════════
# IBU column-aware table parser
# ═══════════════════════════════════════════════════════════════════════════
#
# IBU EPDs render their LCA results tables as one token per cell in the PDF
# text stream — each column value on its own line.  The column header order
# is declared in the table header row immediately before the data rows and
# maps to a fixed sequence of lifecycle modules.
#
# This parser:
#   1. Detects the column header sequence (A1, A2, A3, A4, ..., D)
#   2. Identifies each indicator row by its label token (GWP-total, ODP, etc.)
#   3. Reads exactly N values (one per column) after the label+unit tokens
#   4. Maps each value to its lifecycle module
#   5. Sets _source = "parsed" for all directly-read values
#   6. Derives A1-A3 sums only when no combined column exists; marks as "calculated"
#
# ───────────────────────────────────────────────────────────────────────────

# Canonical module key suffixes used in output field names
# Order matches typical IBU table column order
_IBU_MODULE_SEQUENCE = ["a1", "a2", "a3", "a4", "a5", "b1", "b2", "b6", "b7", "c1", "c2", "c3", "c4", "d"]

# Regex to recognise a module header token
_MODULE_HDR_RE = re.compile(
    r"^(Tot\.?A1[\-\u2013]A3|A1[\-\u2013]A3|A[1-5]|B1[\-\u2013]B7|B[1-7]|C[1-4]|D)$",
    re.IGNORECASE,
)

# Map raw column header text → canonical suffix
def _canonical_module(tok: str) -> str | None:
    tok = tok.strip().replace("\u2013", "-").replace("\xa0", " ").upper()
    mapping = {
        "A1": "a1", "A2": "a2", "A3": "a3",
        "A4": "a4", "A5": "a5",
        "B1": "b1", "B2": "b2", "B3": "b3", "B4": "b4", "B5": "b5",
        "B6": "b6", "B7": "b7",
        "B1-B7": "b1_b7",
        "C1": "c1", "C2": "c2", "C3": "c3", "C4": "c4",
        "D": "d",
        "A1-A3":    "a1a3",
        "TOT.A1-A3": "a1a3",   # Environdec Italian format
        "TOT.A1A3":  "a1a3",
        "TOTA1-A3":  "a1a3",
        "A1-A3TOTAL": "a1a3",
    }
    return mapping.get(tok)


# Indicator row label → output field prefix
_IBU_INDICATOR_MAP: list[tuple[str, list[str]]] = [
    # GWP family
    ("gwp_total",       [r"^GWP[\s\-]*total$",      r"^GWP[\s\-]*GHG$",
                          r"^Treibhausgaspotenzial"]),
    ("gwp_fossil",      [r"^GWP[\s\-]*fossil$"]),
    ("gwp_biogenic",    [r"^GWP[\s\-]*biogen(ic)?$", r"^GWP[\s\-]*biogen$"]),
    ("gwp_luluc",       [r"^GWP[\s\-]*luluc$",       r"^GWP[\s\-]*land"]),
    # Other env indicators
    ("odp",             [r"^ODP$"]),
    ("ap",              [r"^AP$"]),
    ("ep_freshwater",   [r"^EP[\s\-]*freshwater$",   r"^EP[\s\-]*fw$"]),
    ("ep_marine",       [r"^EP[\s\-]*marine$"]),
    ("ep_terrestrial",  [r"^EP[\s\-]*terrestrial$"]),
    ("pocp",            [r"^POCP$"]),
    ("adpe",            [r"^ADPE$"]),
    ("adpf",            [r"^ADPF$"]),
    ("wdp",             [r"^WDP$"]),
    # Resource use
    ("pere",            [r"^PERE$"]),
    ("perm",            [r"^PERM$"]),
    ("pert",            [r"^PERT$"]),
    ("penre",           [r"^PENRE$"]),
    ("penrm",           [r"^PENRM$"]),
    ("penrt",           [r"^PENRT$"]),
    ("sm",              [r"^SM$"]),
    ("rsf",             [r"^RSF$"]),
    ("nrsf",            [r"^NRSF$"]),
    ("fw",              [r"^FW$"]),
    # Italian / Environdec synonyms for GWP family
    ("gwp_total",       [r"^GWP[\s\-]*totale$",    r"^GWP[\s\-]*GHG$",
                          r"^Treibhausgaspotenzial", r"^Climate\s+change$"]),
    ("gwp_fossil",      [r"^GWP[\s\-]*fossile?$",  r"^GWP[\s\-]*fossil$",
                          r"^Climate\s+change[\s\-]+fossil"]),
    ("gwp_biogenic",    [r"^GWP[\s\-]*biogenic[oa]?$",
                          r"^GWP[\s\-]*biogen$",
                          r"^Climate\s+change[\s\-]+biogenic"]),
    ("gwp_luluc",       [r"^GWP[\s\-]*luluc$",     r"^GWP[\s\-]*land",
                          r"^Climate\s+change[\s\-]+land"]),
    # Italian env indicators
    ("odp",             [r"^ODP$"]),
    ("ap",              [r"^AP$"]),
    ("ep_freshwater",   [r"^EP[\s\-]*(?:freshwater|acqua\s*dolce|fw)$"]),
    ("ep_marine",       [r"^EP[\s\-]*(?:marine[oa]?|marino)$"]),
    ("ep_terrestrial",  [r"^EP[\s\-]*(?:terrestrial[ea]?|terrestre)$"]),
    ("pocp",            [r"^POCP$"]),
    ("adpe",            [r"^ADPE$", r"^ADP[\s\-]*minerali", r"^ADP[\s\-]*mineral"]),
    ("adpf",            [r"^ADPF$", r"^ADP[\s\-]*fossile?$", r"^ADP[\s\-]*fossil\s*\*?$"]),
    ("wdp",             [r"^WDP\s*\*?$"]),
    # Waste
    ("hwd",             [r"^HWD$", r"^Rifiuti\s+pericolosi"]),
    ("nhwd",            [r"^NHWD$"]),
    ("rwd",             [r"^RWD$"]),
    ("cru",             [r"^CRU$"]),
    ("mfr",             [r"^MFR$"]),
    ("mer",             [r"^MER$"]),
    ("eee",             [r"^EEE$"]),
    ("eet",             [r"^EET$"]),
]

# Unit tokens that should be skipped when reading values after a row label
_UNIT_TOKENS = re.compile(
    r"^(kg\s*CO2\s*eq|kg\s*CFC11\s*eq|mol\s*H\+\s*eq|kg\s*P\s*eq|"
    r"kg\s*N\s*eq|mol\s*N\s*eq|kg\s*NMVOC\s*eq|kg\s*Sb\s*eq|MJ|"
    r"m3|m3\s*world\s*eq\s*deprived|kg|Disease\s*incidence|"
    r"kBq\s*U235\s*eq|CTUe|CTUh|SQP|eq|-|\.|/|biogenic)$",
    re.IGNORECASE,
)


def _is_numeric_token(tok: str) -> bool:
    """True if tok looks like a numeric value (possibly scientific notation)."""
    tok = tok.strip().replace("\xa0", "").replace(",", ".")
    if not tok:
        return False
    return bool(re.match(r"^[-+]?\d+\.?\d*([Ee][+\-]?\d+)?$", tok))


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    s = str(s).strip().replace("\u2013", "-").replace("\xa0", "").replace(" ", "")
    # European thousands-separator format: 1.234 or 1.234.567 or 1.234,56
    # Requirements to avoid false-positives (e.g. 0.145 must NOT match):
    #   • integer part must be ≥ 1 digit AND the leading group must be ≥ 1 digit
    #     followed by a dot then exactly 3 digits, AND there must be either a
    #     comma decimal part OR multiple dot-groups (i.e. > 1 thousand group).
    #   • A plain N.DDD with no comma and only one group is ambiguous — treat
    #     as standard decimal unless the integer part is ≥ 2 digits (e.g. 12.345).
    if re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?([Ee][+\-]?\d+)?$", s):
        # Additional guard: if only one dot-group and no comma, only strip dot
        # when integer part has ≥ 2 digits (real thousands: 12.345 → 12345,
        # not 0.145 → 145).
        dot_groups = len(re.findall(r"\.\d{3}", s))
        has_comma  = "," in s
        int_part   = re.match(r"^-?(\d+)", s)
        int_digits = len(int_part.group(1)) if int_part else 0
        if dot_groups > 1 or has_comma or int_digits >= 2:
            s = s.replace(".", "").replace(",", ".")
        else:
            # Single dot-group, no comma, single-digit integer: plain decimal
            s = s.replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _nums(line: str) -> list[float]:
    return [f for f in (_to_float(m) for m in _NUM_RE.findall(line)) if f is not None]


def _match_indicator(tok: str) -> str | None:
    """Return the field prefix if tok matches a known indicator label."""
    tok_clean = tok.strip().replace("\xa0", " ").replace("\u2013", "-")
    for prefix, patterns in _IBU_INDICATOR_MAP:
        for pat in patterns:
            if re.match(pat, tok_clean, re.IGNORECASE):
                return prefix
    return None


def _ibu_parse_tables(page_texts: list[str]) -> dict:
    """
    Parse IBU LCA results tables from PDF page texts.

    Returns a flat dict of  {field_name: value}  plus  {field_name + "_source": "parsed"|"calculated"}
    for every extracted numeric value.

    Field naming convention:
      <indicator>_<module>   e.g.  gwp_total_a1a3,  gwp_total_a1,  penre_a4
    """
    result: dict = {}

    # Concatenate all tokens from all pages into one stream, stripping NBSP.
    # Lines like "kg CO2 eq 1.34E-02" mix a unit label and a numeric value —
    # we split each line into segments, keeping label words together and
    # emitting each numeric value as a separate token.
    all_tokens: list[str] = []
    _val_re = re.compile(r"^[-+]?\d[\d,\.]*([Ee][+\-]?\d+)?$")
    for text in page_texts:
        for line in text.splitlines():
            tok = line.strip().replace("\xa0", " ").strip()
            if not tok:
                continue
            raw_parts = tok.split()
            i_rp = 0
            while i_rp < len(raw_parts):
                part = raw_parts[i_rp]
                if _val_re.match(part):
                    # Numeric: emit as its own token
                    all_tokens.append(part)
                    i_rp += 1
                else:
                    # Non-numeric: accumulate words until next numeric
                    assembled = part
                    j = i_rp + 1
                    while j < len(raw_parts) and not _val_re.match(raw_parts[j]):
                        assembled += " " + raw_parts[j]
                        j += 1
                    all_tokens.append(assembled.strip())
                    i_rp = j

    n = len(all_tokens)
    i = 0

    # ── Step 1 & 2: find data-table column headers and data boundaries ──────────
    #
    # A PDF may contain multiple header runs:
    #   • System boundary matrix (A1 A2 A3 … D  followed by X / ND / MNR)
    #   • Actual data table (columns followed by indicator labels + numbers)
    #   • Repeated data table headers in multi-product EPDs
    #
    # Strategy: scan for header runs (≥4 consecutive module tokens).
    # For each, peek at the token immediately after — if it is an indicator
    # label (matches _match_indicator) or a numeric value, this is a REAL
    # data-table header.  Record:
    #   • active_cols  — column order of the first real data header
    #   • data_start   — token index just after the first real data header
    #   • data_end     — token index where the second real data header begins
    #                    (or n for single-table EPDs)

    active_cols: list[str] = []
    data_start  = 0
    data_end    = n
    _real_hdrs  = 0   # count of real (data-table) header runs found

    _j = 0
    while _j < n:
        if _canonical_module(all_tokens[_j]) is not None:
            _run_start = _j
            _run_cols: list[str] = []
            while _j < n and _canonical_module(all_tokens[_j]) is not None:
                cm = _canonical_module(all_tokens[_j])
                if cm:
                    _run_cols.append(cm)
                _j += 1
            _run_end = _j   # first token after the header run

            if len(_run_cols) < 4:
                continue   # too short, not a table header

            # Scan forward up to 30 tokens to find an indicator label — the
            # real data header may be followed by a footnote line before GWP-total.
            # A "system boundary" header is followed by X / ND / MNR cells.
            _is_data_hdr = False
            for _la in range(_run_end, min(_run_end + 30, n)):
                _la_tok = all_tokens[_la]
                if _match_indicator(_la_tok) is not None:
                    _is_data_hdr = True; break
                if _canonical_module(_la_tok) is not None:
                    break   # hit next header run — stop
                if len(_la_tok) > 80:
                    continue   # long footnote line — skip

            if _is_data_hdr:
                _real_hdrs += 1
                if _real_hdrs == 1:
                    active_cols = _run_cols
                    data_start  = _run_end
                # For multi-product EPDs: update active_cols for each sub-table
                # but data_end stays at n — we read ALL sub-tables.
                # First-value-wins semantics in the data reader prevent overwriting.
                elif _real_hdrs >= 2:
                    # Update the active column order for this sub-table's header
                    # (column order may differ between indicator sections, e.g. A1-A3 vs Tot.A1-A3)
                    # We mark a "column reset" position for the data reader.
                    pass   # data_end stays at n; first-value-wins handles deduplication
        else:
            _j += 1

    if not active_cols:
        return result   # no real data-table header found — fall back to Claude

    i = data_start
    while i < data_end:
        tok = all_tokens[i]

        # ── Check for a new column header run mid-stream (new sub-table) ──────
        # When found, update active_cols so subsequent rows use the right order.
        if _canonical_module(tok) is not None:
            _new_run: list[str] = []
            _k_hdr = i
            while _k_hdr < n and _canonical_module(all_tokens[_k_hdr]) is not None:
                cm = _canonical_module(all_tokens[_k_hdr])
                if cm:
                    _new_run.append(cm)
                _k_hdr += 1
            if len(_new_run) >= 4:
                active_cols = _new_run
                i = _k_hdr
                continue
            else:
                i += 1
                continue

        # Is this an indicator label?
        # Handle two-token labels like "GWP-" / "biogenic" or "EP-" / "freshwater"
        indicator = _match_indicator(tok)
        if indicator is None and i + 1 < n:
            merged = tok.rstrip("-") + all_tokens[i + 1]
            indicator = _match_indicator(merged)
            if indicator is not None:
                i += 1  # consume the second label token

        if indicator is None:
            i += 1
            continue

        # Skip unit tokens immediately following the label.
        # Also skip small standalone integers that appear mid-unit-string
        # (e.g. the "11" in "kg CFC 11 eq." which gets split by the tokeniser).
        i += 1
        _prev_was_unit = True   # the label itself counts as the first unit context
        while i < n:
            _u_tok = all_tokens[i].strip()
            _is_unit = bool(_UNIT_TOKENS.match(_u_tok))
            # Small non-zero integer appearing right after a unit fragment
            # (e.g. "11" in "kg CFC 11 eq."). Must be ≥1 and ≤ 3 digits.
            _is_unit_int = (
                _prev_was_unit
                and re.match(r"^[1-9]\d{0,2}$", _u_tok)   # 1–999, no zero
            )
            _is_non_numeric_filler = (
                not _is_numeric_token(_u_tok)
                and not _u_tok.lstrip("-").replace(".", "").replace("E", "").replace("+", "").isdigit()
            )
            if not (_is_unit or _is_unit_int or _is_non_numeric_filler):
                break
            # Stop at next indicator label or column header
            if _match_indicator(_u_tok) or _canonical_module(_u_tok) is not None:
                break
            # Stop if the token is clearly a section header keyword
            if len(_u_tok) > 25:
                break
            _prev_was_unit = _is_unit or _is_unit_int or _is_non_numeric_filler
            i += 1

        # Read exactly len(active_cols) numeric values
        values: list[float | None] = []
        while i < n and len(values) < len(active_cols):
            tok_v = all_tokens[i].strip()
            # A token can contain two numbers joined by space (PDF artefact)
            sub_nums = re.findall(r"[-+]?\d+\.?\d*[Ee]?[+\-]?\d*", tok_v)
            parsed_nums = [_to_float(s) for s in sub_nums if _to_float(s) is not None]
            if parsed_nums:
                for pn in parsed_nums:
                    if len(values) < len(active_cols):
                        values.append(pn)
                i += 1
            elif tok_v in ("0", "0.0"):
                values.append(0.0)
                i += 1
            elif _match_indicator(tok_v) or _canonical_module(tok_v) or len(tok_v) > 40:
                # Ran into next row — pad remainder with None
                while len(values) < len(active_cols):
                    values.append(None)
                break
            else:
                i += 1  # skip non-numeric filler

        # Pad if short
        while len(values) < len(active_cols):
            values.append(None)

        # Map values to module suffixes
        col_map: dict[str, float | None] = dict(zip(active_cols, values))

        # Detect if this table has an explicit combined A1-A3 column
        has_combined = "a1a3" in col_map
        has_individual = all(m in col_map for m in ["a1", "a2", "a3"])

        for suffix, val in col_map.items():
            if val is None:
                continue
            field = f"{indicator}_{suffix}"
            # First-value-wins: don't overwrite data already parsed from an
            # earlier sub-table (handles multi-product EPDs — we keep the first
            # product's values, which appear first in the token stream).
            if field not in result:
                result[field] = val
                result[f"{field}_source"] = "parsed"

        # Derive combined A1-A3 if individual stages present but no combined column
        if not has_combined and has_individual:
            v1 = col_map.get("a1")
            v2 = col_map.get("a2")
            v3 = col_map.get("a3")
            if v1 is not None and v2 is not None and v3 is not None:
                total = v1 + v2 + v3
                field_combined = f"{indicator}_a1a3"
                if field_combined not in result:
                    result[field_combined] = total
                    result[f"{field_combined}_source"] = "calculated"

        # If there's an explicit combined column but no individual, mark as parsed
        if has_combined and not has_individual:
            field_combined = f"{indicator}_a1a3"
            if field_combined not in result and col_map.get("a1a3") is not None:
                result[field_combined] = col_map["a1a3"]
                result[f"{field_combined}_source"] = "parsed"

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Environdec / legacy regex GWP parse (unchanged from original)
# ═══════════════════════════════════════════════════════════════════════════

def _a1a3_ibu(nums):
    """IBU: A1 | A2 | A3 | A1-A3 | ... → index 3 (combined column)"""
    if not nums: return None
    if len(nums) == 1: return nums[0]
    if len(nums) >= 4: return nums[3]
    return None


def _a1a3_environdec(nums):
    if not nums: return None
    if len(nums) == 1: return nums[0]
    if len(nums) >= 8:
        return nums[0] + nums[1] + nums[2]
    if len(nums) >= 4:
        return nums[0]
    return None


def _a123_environdec(nums):
    if len(nums) >= 8:
        return nums[0], nums[1], nums[2]
    return None, None, None


def _det_parse_gwp(lca_text, gwp_rows, a1a3_fn):
    res = {k: None for k in [
        "gwp_total","gwp_fossil","gwp_biogenic","gwp_luluc",
        "gwp_a1","gwp_a2","gwp_a3","sm","recycled_content_pct",
    ]}
    lines = lca_text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        for field, pats in gwp_rows:
            if res[field] is not None:
                continue
            for pat in pats:
                if re.search(pat, s, re.I):
                    n = _nums(s)
                    if not n and i + 1 < len(lines):
                        n = _nums(lines[i + 1])
                    val = a1a3_fn(n)
                    if val is not None:
                        res[field] = val
                        if field == "gwp_total":
                            a1, a2, a3 = (None, None, None)
                            if a1a3_fn == _a1a3_ibu and len(n) >= 4:
                                a1, a2, a3 = n[0], n[1], n[2]
                            elif a1a3_fn == _a1a3_environdec:
                                a1, a2, a3 = _a123_environdec(n)
                            res["gwp_a1"] = a1
                            res["gwp_a2"] = a2
                            res["gwp_a3"] = a3
                    break
        if res["sm"] is None and SM_RE.search(s):
            n = _nums(s)
            if not n and i + 1 < len(lines):
                n = _nums(lines[i + 1])
            val = a1a3_fn(n)
            if val is not None:
                res["sm"] = val
        if res["recycled_content_pct"] is None:
            if re.search(r"recycled|Rezyklat|post.consumer|riciclato", s, re.I):
                pm = re.search(r"(\d{1,3}(?:[,\.]\d+)?)\s*%", s)
                if pm:
                    res["recycled_content_pct"] = _to_float(pm.group(1))
    return res


# ═══════════════════════════════════════════════════════════════════════════
# PDF helpers
# ═══════════════════════════════════════════════════════════════════════════

def _ptexts(doc):
    return [p.get_text("text") for p in doc]


def _readable(doc):
    pts = _ptexts(doc)
    return sum(1 for t in pts[:5] if len(t.strip()) > 100) >= min(2, len(pts))


def _programme(full_text):
    m = PROG_RE.search(full_text)
    if not m:
        return None
    n = m.group()
    if re.search(r"IBU|Institut Bauen", n, re.I):         return "IBU"
    if re.search(r"EPD[\s\-]*IES|International EPD|Environdec", n, re.I): return "Environdec"
    if re.search(r"Norwegian EPD|NEPD", n, re.I):          return "EPD Norway"
    if re.search(r"EPDItaly|EPD\s*Italy", n, re.I):        return "EPDItaly"
    if re.search(r"EPD\s*Hub", n, re.I):                   return "EPD Hub"
    if re.search(r"EPD.*Nor|Norge", n, re.I):              return "EPD Norway"
    return n.strip()


def _lca_idx(ptexts):
    sel = set(range(min(2, len(ptexts))))
    for i, t in enumerate(ptexts):
        if LCA_KW_RE.search(t):
            sel.add(i)
    return sorted(sel)


def _detail_idx(ptexts):
    sel = set(range(min(3, len(ptexts))))
    for i, t in enumerate(ptexts):
        if DETAIL_KW_RE.search(t):
            sel.add(i)
    return sorted(sel)


def _det_meta(full_text):
    meta = {k: None for k in [
        "product_name","manufacturer","declared_unit","reference_standard",
        "epd_number","validity_date",
    ]}
    m = EPD_NUM_RE.search(full_text)
    if m:
        meta["epd_number"] = m.group(1)

    # ── Date fields — multilingual (EN / DE / IT / FR / ES) ──────────────────
    _DATE_PAT = (
        r"(\d{4}-\d{2}-\d{2}"           # ISO 2022-07-25
        r"|\d{2}[\./\-]\d{2}[\./\-]\d{4}"   # DD.MM.YYYY or DD/MM/YYYY
        r"|\d{2}[\.\/]\d{4})"            # MM.YYYY
    )

    # Validity / expiry date
    m_valid = re.search(
        r"(?:valid(?:ity)?|expires?|expiry|g.ltig|valid\s*until|valid\s*to|"
        r"data\s*validit|fecha\s*de\s*validez|date\s*de\s*validit)"
        r"\D{0,30}" + _DATE_PAT,
        full_text, re.I,
    )
    if m_valid:
        meta["validity_date"] = m_valid.group(1)

    # Issue / publication date
    m_issue = re.search(
        r"(?:issue\s*date|date\s*of\s*issue|published|publication\s*date|"
        r"ausgestellt|ver.ffentlicht|datum\s*der\s*ausgabe|"
        r"data\s*(?:di\s*)?pubblicazione|data\s*publicaci|date\s*de\s*publication)"
        r"\D{0,30}" + _DATE_PAT,
        full_text, re.I,
    )
    if m_issue:
        meta["issue_date"] = m_issue.group(1)

    # Revision date
    m_rev = re.search(
        r"(?:revision\s*date|date\s*of\s*revision|revis(?:ed|ion)|"
        r"aktualisiert|"
        r"data\s*(?:di\s*)?revisione|fecha\s*de\s*revisi|date\s*de\s*r.vision)"
        r"\D{0,30}" + _DATE_PAT,
        full_text, re.I,
    )
    if m_rev:
        meta["revision_date"] = m_rev.group(1)

    # Positional fallback: some EPDs list labels first then values on separate lines.
    # e.g. Environdec: "Numero registrazione EPD:\n ... S-P-06429\n 2022-07-25\n 2023-10-24\n 2027-07-25"
    # Find the EPD number in the text and look for a cluster of ISO dates nearby.
    _epd_str = meta.get("epd_number", "")
    if _epd_str:
        _epd_pos = full_text.find(_epd_str)
        if _epd_pos >= 0:
            _nearby = full_text[max(0, _epd_pos - 20): _epd_pos + 400]
            _nearby_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})\b", _nearby)
            # Expect order: [issue, revision, validity]
            if not m_valid and len(_nearby_dates) >= 1:
                meta["validity_date"] = _nearby_dates[-1]
            if not m_issue and len(_nearby_dates) >= 2:
                meta["issue_date"] = _nearby_dates[-3] if len(_nearby_dates) >= 3 else _nearby_dates[-2]
            if not m_rev and len(_nearby_dates) >= 3:
                meta["revision_date"] = _nearby_dates[-2]

    m = re.search(
        r"(?:valid(?:ity)?|expires?|expiry|bis|g\u00fcltig|valid\s*until|valid\s*to)\D{0,20}"
        r"(\d{2}[\./\-]\d{2}[\./\-]\d{4}|\d{4}[\-/]\d{2}[\-/]\d{2}|\d{2}[\.\/]\d{4})",
        full_text, re.I,
    )
    if m and not meta.get("validity_date"):
        meta["validity_date"] = m.group(1)
    m = re.search(
        r"EN\s*15804"
        r"(?:\s*:\s*\d{4})?"          # optional :2012
        r"(?:\s*[+]\s*A[12])?"        # optional +A2
        r"(?:\s*:\s*\d{4})?"          # optional :2019
        r"(?:/AC:\d{4})?",            # optional /AC:2012
        full_text, re.I
    )
    if m and len(m.group().strip()) >= 7:   # avoid matching bare "EN 15804"
        meta["reference_standard"] = re.sub(r"\s+", "", m.group())
    m = re.search(
        r"(?:declared unit|Bezugsgr\u00f6\u00dfe|unit\u00e9 d\u00e9clar\u00e9e|"
        r"unit\u00e0 dichiarata)[^\n]{0,100}?"
        r"(1\s*(?:kg\b|t\b|m\u00b2|m2|m\u00b3|m3|m\b|piece|St\u00fcck|pcs|lm|m2K/W))",
        full_text, re.I,
    )
    if m:
        meta["declared_unit"] = m.group(1).strip()
    return meta


def _det_conf(res):
    filled = sum(1 for k in [
        "gwp_total","gwp_fossil","epd_number","declared_unit","reference_standard"
    ] if res.get(k) is not None)
    # Also treat as high if GWP data is present even without reference_standard
    has_gwp = res.get("gwp_total") is not None and res.get("gwp_fossil") is not None
    has_id  = res.get("epd_number") is not None
    if has_gwp and has_id:
        return "high"
    return "high" if filled >= 4 else "medium" if filled >= 2 else "low"


# ═══════════════════════════════════════════════════════════════════════════
# Claude system prompts
# ═══════════════════════════════════════════════════════════════════════════

_SYS_ESSENTIAL = """\
You are an expert LCA/EPD data extractor for construction products.
You receive plain text (or images) from selected pages of an EPD PDF.
Return ONLY a valid JSON object — no markdown fences, no prose, no comments.

JSON schema (null for any field not found):
{
  "product_name": string,
  "manufacturer": string,
  "declared_unit": string,
  "reference_standard": string,
  "epd_number": string,
  "programme_operator": string,
  "validity_date": string,
  "issue_date": string,
  "revision_date": string,
  "gwp_total": number|null,
  "gwp_fossil": number|null,
  "gwp_biogenic": number|null,
  "gwp_luluc": number|null,
  "gwp_a1": number|null,
  "gwp_a2": number|null,
  "gwp_a3": number|null,
  "gwp_total_a4": number|null,
  "gwp_total_a5": number|null,
  "gwp_total_c1": number|null,
  "gwp_total_c2": number|null,
  "gwp_total_c3": number|null,
  "gwp_total_c4": number|null,
  "gwp_total_d": number|null,
  "sm": number|null,
  "penre_a1a3": number|null,
  "pere_a1a3": number|null,
  "fw_a1a3": number|null,
  "odp_a1a3": number|null,
  "ap_a1a3": number|null,
  "ep_freshwater_a1a3": number|null,
  "ep_marine_a1a3": number|null,
  "ep_terrestrial_a1a3": number|null,
  "pocp_a1a3": number|null,
  "adpe_a1a3": number|null,
  "adpf_a1a3": number|null,
  "wdp_a1a3": number|null,
  "recycled_content_pct": number|null,
  "confidence": "high"|"medium"|"low",
  "notes": string
}

Rules:
- gwp_total = A1-A3 GWP-total or GWP-GHG (kg CO2eq). If A1-A3 is a combined column, read directly.
  If only individual A1, A2, A3 columns exist, sum them — in that case set notes to include "gwp_total calculated as A1+A2+A3".
- gwp_fossil/biogenic/luluc: EN 15804+A2 only; null for A1.
- gwp_a1/a2/a3: populate when individual A1, A2, A3 stage columns exist.
- gwp_total_a4..d: values from other lifecycle stage columns of GWP-total row.
- sm: "Use of secondary material" A1-A3 column (kg).
- penre_a1a3, pere_a1a3, fw_a1a3: resource use indicators for A1-A3.
- odp, ap, ep_freshwater, ep_marine, ep_terrestrial, pocp, adpe, adpf, wdp: A1-A3 values.
- European decimals (1,23E-02 → 0.0123). Scientific notation → float.
- Multi-product EPDs: extract the FIRST product listed.
- Return ONLY the JSON object.\
"""

_SYS_DETAIL = """\
You are an expert LCA/EPD data extractor for construction products.
Return ONLY a valid JSON object — no markdown fences, no prose, no comments.

JSON schema (null for any field not found):
{
  "product_description": string,
  "product_composition": [
    {"material": string, "pct_by_mass": number|null, "notes": string|null}
  ],
  "production_method": string,
  "system_boundary": string,
  "modules_declared": string,
  "flow_description": string,
  "functional_unit": string,
  "geographic_scope": string,
  "third_party_verifier": string,
  "pcr_reference": string,
  "lca_software": string,
  "lca_database": string,
  "detail_confidence": "high"|"medium"|"low",
  "detail_notes": string
}

Rules:
- product_description: 2–5 sentences summarising the product and its use.
- product_composition: list every declared material with % by mass where stated.
- production_method: describe manufacturing process. 1–3 sentences.
- system_boundary: e.g. "Cradle to gate (A1-A3)" or "Cradle to grave (A1-A3, A4, C1-C4, D)".
- modules_declared: comma-separated list e.g. "A1, A2, A3, C1, C2, C3, C4, D".
- Return ONLY the JSON object.\
"""


# ═══════════════════════════════════════════════════════════════════════════
# Claude API calls
# ═══════════════════════════════════════════════════════════════════════════

def _build_text_body(ptexts, idx, n_pages):
    body = f"EPD has {n_pages} pages. Sending pages {[i+1 for i in idx]}.\n\n"
    for i, t in zip(idx, ptexts):
        body += f"--- PAGE {i+1} ---\n{t}\n\n"
    return body


def _message_assistant_text(resp) -> str:
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    text = "".join(parts).strip()
    if not text:
        types = [getattr(b, "type", type(b).__name__) for b in resp.content]
        raise ValueError(f"Model returned no text blocks (got types: {types})")
    return text


def _call_api(body_or_content, system, max_tokens, client, is_vision=False):
    messages = [{"role": "user", "content": body_or_content}]
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=messages,
    )
    raw = _message_assistant_text(resp)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


def _page_png_b64(page, dpi=150):
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    return base64.standard_b64encode(pix.tobytes("png")).decode()


def _call_vision(doc, idx, system, max_tokens, client):
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": "image/png",
                    "data": _page_png_b64(doc[i])}}
        for i in idx
    ]
    content.append({"type": "text", "text":
        f"EPD has {len(doc)} pages. Sending pages {[i+1 for i in idx]}. "
        "Extract all requested fields."})
    return _call_api(content, system, max_tokens, client, is_vision=True)


# ═══════════════════════════════════════════════════════════════════════════
# Result key lists
# ═══════════════════════════════════════════════════════════════════════════

_ESSENTIAL_KEYS = [
    "product_name","manufacturer","declared_unit","reference_standard",
    "epd_number","programme_operator","validity_date","issue_date","revision_date",
    # Core GWP (A1-A3 only, plus per-stage)
    "gwp_total","gwp_fossil","gwp_biogenic","gwp_luluc",
    "gwp_a1","gwp_a2","gwp_a3",
    # Other indicators A1-A3
    "odp_a1a3","ap_a1a3","ep_freshwater_a1a3","ep_marine_a1a3",
    "ep_terrestrial_a1a3","pocp_a1a3","adpe_a1a3","adpf_a1a3","wdp_a1a3",
    # Resource use A1-A3
    "penre_a1a3","pere_a1a3","fw_a1a3",
    "sm","recycled_content_pct",
    "confidence","notes",
]

_DETAIL_KEYS = [
    "product_description","product_composition","production_method",
    "system_boundary","modules_declared","flow_description",
    "functional_unit","geographic_scope","third_party_verifier",
    "pcr_reference","lca_software","lca_database",
    "detail_confidence","detail_notes",
]

# Extended per-module keys written by the IBU table parser
# These are in addition to _ESSENTIAL_KEYS and surfaced to the review form
_EXTENDED_MODULE_PREFIXES = [
    "gwp_total","gwp_fossil","gwp_biogenic","gwp_luluc",
    "odp","ap","ep_freshwater","ep_marine","ep_terrestrial",
    "pocp","adpe","adpf","wdp",
    "penre","perm","pert","pere","penrt","sm","rsf","nrsf","fw",
    "hwd","nhwd","rwd","cru","mfr","mer","eee","eet",
]


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def extract_epd(
    pdf_path: str | Path,
    client: anthropic.Anthropic | None = None,
    detail: bool = False,
) -> dict:
    """
    Extract EPD data from a PDF file.

    Parameters
    ----------
    pdf_path : path to EPD PDF
    client   : Anthropic client (uses ANTHROPIC_API_KEY env var if None)
    detail   : if True, run a second Claude call to extract product composition,
               production method, system boundary, flow description, etc.

    Returns
    -------
    dict with:
      • all essential keys (see _ESSENTIAL_KEYS)
      • extended per-module keys for GWP/LCA indicators
        (e.g. gwp_total_a1, gwp_total_a2, ..., penre_a4, etc.)
      • for every numeric field: a parallel  <field>_source  key
        with value "parsed" or "calculated"
      • detail keys if detail=True
      • internal meta keys: _pages_sent_essential, _pages_sent_detail,
        _input_tokens, _output_tokens, _detail_input_tokens,
        _detail_output_tokens, _mode, _programme, _error
    """
    if client is None:
        client = anthropic.Anthropic()

    pdf_path = Path(pdf_path)
    res: dict = {k: None for k in _ESSENTIAL_KEYS}
    if detail:
        for k in _DETAIL_KEYS:
            res[k] = None

    res.update({
        "confidence": "low", "notes": "",
        "_pages_sent_essential": 0, "_pages_sent_detail": 0,
        "_input_tokens": 0, "_output_tokens": 0,
        "_detail_input_tokens": 0, "_detail_output_tokens": 0,
        "_mode": "none", "_programme": None, "_error": None,
    })

    try:
        # ── Open PDF — catch file-level errors immediately ─────────────────
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as _fitz_exc:
            _msg = str(_fitz_exc)
            if "password" in _msg.lower():
                _reason = "PDF is password-protected — cannot open without the password."
            elif "not a pdf" in _msg.lower() or "no objects" in _msg.lower():
                _reason = "File does not appear to be a valid PDF."
            elif "no such file" in _msg.lower() or "cannot open" in _msg.lower():
                _reason = f"File not found or unreadable: {pdf_path.name}"
            else:
                _reason = f"PDF could not be opened (PyMuPDF error): {_msg[:200]}"
            res["_error"] = _reason
            res["confidence"] = "low"
            return res
        ptexts = _ptexts(doc)
        full = "\n".join(ptexts)
        n_pages = len(doc)
        readable = _readable(doc)

        prog = _programme(full)
        res["_programme"] = prog
        res["programme_operator"] = prog

        # ── 1. Deterministic parse ─────────────────────────────────────────
        det_done = False
        if readable:
            lca_idx = _lca_idx(ptexts)
            lca_texts = [ptexts[i] for i in lca_idx]
            lca_text_joined = "\n".join(lca_texts)

            # ── Column-aware table parser (all programmes) ────────────────
            # Runs for every readable EPD — works for IBU, Environdec, EPDItaly,
            # EPD Norway, and any other programme using one-token-per-cell layout.
            table_data = _ibu_parse_tables(lca_texts)
            det_done = bool(table_data)

            if det_done:
                res.update(table_data)

                # Populate canonical essential keys from table data
                for prefix in ["gwp_total", "gwp_fossil", "gwp_biogenic", "gwp_luluc"]:
                    a1a3_key = f"{prefix}_a1a3"
                    legacy   = prefix
                    if res.get(legacy) is None and res.get(a1a3_key) is not None:
                        res[legacy] = res[a1a3_key]
                        res[f"{legacy}_source"] = res.get(f"{a1a3_key}_source")

                # Per-stage A1/A2/A3 for gwp_total
                for stage, key in [("a1","gwp_a1"), ("a2","gwp_a2"), ("a3","gwp_a3")]:
                    if res.get(key) is None:
                        v = res.get(f"gwp_total_{stage}")
                        if v is not None:
                            res[key] = v
                            res[f"{key}_source"] = res.get(f"gwp_total_{stage}_source")

                # SM from table
                if res.get("sm") is None and res.get("sm_a1a3") is not None:
                    res["sm"] = res["sm_a1a3"]
                    res["sm_source"] = res.get("sm_a1a3_source")

                # Map table keys → essential keys
                indicator_map = {
                    "odp_a1a3": "odp_a1a3", "ap_a1a3": "ap_a1a3",
                    "ep_freshwater_a1a3": "ep_freshwater_a1a3",
                    "ep_marine_a1a3": "ep_marine_a1a3",
                    "ep_terrestrial_a1a3": "ep_terrestrial_a1a3",
                    "pocp_a1a3": "pocp_a1a3", "adpe_a1a3": "adpe_a1a3",
                    "adpf_a1a3": "adpf_a1a3", "wdp_a1a3": "wdp_a1a3",
                    "penre_a1a3": "penre_a1a3", "pere_a1a3": "pere_a1a3",
                    "fw_a1a3": "fw_a1a3",
                }
                for tbl_key, ess_key in indicator_map.items():
                    if res.get(ess_key) is None and res.get(tbl_key) is not None:
                        res[ess_key] = res[tbl_key]
                        res[f"{ess_key}_source"] = res.get(f"{tbl_key}_source")

                meta = _det_meta(full)
                for k, v in meta.items():
                    if res.get(k) is None:
                        res[k] = v

                res["_pages_sent_essential"] = len(lca_idx)
                res["_mode"] = "deterministic"
                conf = _det_conf(res)
                res["confidence"] = conf

                if conf == "high" and not detail:
                    doc.close()
                    return res

            elif not det_done and prog in ("Environdec", "EPD Norway"):
                # Fallback: old regex parser (for Environdec EPDs where
                # the table parser found no column headers)
                det = _det_parse_gwp(lca_text_joined, ENV_GWP_ROWS, _a1a3_environdec)
                meta = _det_meta(full)
                for k, v in {**meta, **det}.items():
                    res[k] = v
                res["_pages_sent_essential"] = len(lca_idx)
                res["_mode"] = "deterministic"
                conf = _det_conf(res)
                res["confidence"] = conf
                det_done = True
                if conf == "high" and not detail:
                    doc.close()
                    return res

        # ── 2. Claude essential (text) ─────────────────────────────────────
        # Only call Claude if:
        #   a) deterministic parse got no GWP data at all, OR
        #   b) we need to fill gaps and a client is available
        # Never call Claude if client is None — that would raise or return empty.
        if readable and client is not None and res.get("gwp_total") is None:
            lca_idx = _lca_idx(ptexts)
            body = _build_text_body([ptexts[i] for i in lca_idx], lca_idx, n_pages)
            parsed, it, ot = _call_api(body, _SYS_ESSENTIAL, MAX_TOKENS_ESSENTIAL, client)

            # Merge Claude output — only fill gaps not already populated
            for k in _ESSENTIAL_KEYS:
                if k in parsed and parsed[k] is not None and res.get(k) is None:
                    res[k] = parsed[k]
                    res[f"{k}_source"] = "parsed"

            # Handle calculated note from Claude
            notes_raw = parsed.get("notes", "") or ""
            if "calculated" in notes_raw.lower() and "gwp_total" in notes_raw.lower():
                res["gwp_total_source"] = "calculated"

            res["confidence"] = parsed.get("confidence", "medium")
            res["notes"] = notes_raw
            res["_input_tokens"] += it
            res["_output_tokens"] += ot
            res["_pages_sent_essential"] = len(lca_idx)
            res["_mode"] = "deterministic+text" if det_done else "text"

        # ── 3. Claude essential (vision fallback) ──────────────────────────
        elif not readable and client is not None:
            lca_idx = _lca_idx(ptexts)
            if len(lca_idx) <= 2:
                lca_idx = list(range(min(8, n_pages)))
            parsed, it, ot = _call_vision(doc, lca_idx, _SYS_ESSENTIAL, MAX_TOKENS_ESSENTIAL, client)
            for k in _ESSENTIAL_KEYS:
                if k in parsed and parsed[k] is not None:
                    res[k] = parsed[k]
                    res[f"{k}_source"] = "parsed"
            res["confidence"] = parsed.get("confidence", "low")
            res["notes"] = (parsed.get("notes") or "") + " [vision: scanned PDF]"
            res["_input_tokens"] += it
            res["_output_tokens"] += ot
            res["_pages_sent_essential"] = len(lca_idx)
            res["_mode"] = "vision"

        # ── 4. Claude detail (optional, text only) ─────────────────────────
        if detail and readable and client is not None:
            d_idx = _detail_idx(ptexts)
            body = _build_text_body([ptexts[i] for i in d_idx], d_idx, n_pages)
            parsed_d, dit, dot = _call_api(body, _SYS_DETAIL, MAX_TOKENS_DETAIL, client)
            for k in _DETAIL_KEYS:
                if k in parsed_d:
                    res[k] = parsed_d[k]
            res["_detail_input_tokens"] = dit
            res["_detail_output_tokens"] = dot
            res["_pages_sent_detail"] = len(d_idx)

        doc.close()

    except json.JSONDecodeError as e:
        res["_error"] = f"JSON parse error: {e}"
        res["confidence"] = "low"
    except Exception:
        res["_error"] = traceback.format_exc()
        res["confidence"] = "low"

    return res


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    detail_input: int = 0,
    detail_output: int = 0,
) -> float:
    """Rough USD cost for claude-sonnet-4 ($3/M in · $15/M out)."""
    total_in  = input_tokens  + detail_input
    total_out = output_tokens + detail_output
    return (total_in * 3 + total_out * 15) / 1_000_000


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    detail_flag = "--detail" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Usage: python lib_epd_extractor.py <epd.pdf> [--detail]")
        sys.exit(1)

    data = extract_epd(args[0], detail=detail_flag)
    cost = estimate_cost(
        data["_input_tokens"], data["_output_tokens"],
        data["_detail_input_tokens"], data["_detail_output_tokens"],
    )
    sep = "─" * 62
    print(f"\n{sep}")
    print(f"  File        : {Path(args[0]).name}")
    print(f"  Programme   : {data['_programme']}")
    print(f"  Mode        : {data['_mode']}")
    print(f"  Pages sent  : {data['_pages_sent_essential']} essential")
    if detail_flag:
        print(f"  Detail      : {data['_pages_sent_detail']} pages  "
              f"{data['_detail_input_tokens']:,} in / {data['_detail_output_tokens']:,} out")
    print(f"  Est. cost   : ~${cost:.4f} USD")
    print(f"  Confidence  : {data['confidence']}")
    if data["_error"]:
        print(f"  ERROR       : {data['_error'][:400]}")
    print(f"{sep}\n")

    # Print all non-internal keys, grouped
    out = {k: v for k, v in data.items() if not k.startswith("_")}
    print(json.dumps(out, indent=2, ensure_ascii=False))