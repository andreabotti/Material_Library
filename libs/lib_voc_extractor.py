"""
lib_voc_extractor.py  –  EETRA Material Library VOC certificate extractor
────────────────────────────────────────────────────────────────────────────
Much simpler cousin of lib_epd_extractor.py: VOC certificates are short
(1-2 pages), single-product, and the pipeline only needs a handful of
fields off them — certificate number, validity/expiry date, and a little
identifying context.

Extraction strategy (cheapest first):
  1. PyMuPDF text extraction + text-quality check (catches garbled/
     custom-encoded fonts that produce readable-looking but meaningless text)
  2. Deterministic regex parse (certificate-number / date patterns)
  3. Claude TEXT API — fills whatever regex couldn't find (~1-2 pages, cheap)
  4. Claude VISION API — fallback for scanned or garbled-font certificates

Validated against real Indoor Air Comfort Gold (Eurofins) certificates —
the scheme this pipeline sees most often. Other schemes (M1, EMICODE,
ICMQ, generic "Certificate No.") share the same regex-first + Claude
fallback path but haven't been broadly validated yet.

Output fields
─────────────
  cert_number, expiry_date, issue_date   (dates as ISO YYYY-MM-DD)
  scheme            certification scheme name, e.g. "Indoor Air Comfort Gold"
  product_name, manufacturer
  confidence        "high" | "medium" | "low"
  notes
  _mode             "deterministic" | "deterministic+text" | "text" | "vision" | "none"
  _pages_sent, _input_tokens, _output_tokens, _error
"""

from __future__ import annotations
import base64, json, re, traceback
from datetime import datetime
from pathlib import Path

import anthropic
import fitz  # PyMuPDF


MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 512

# Max pages read/sent — VOC certs are almost always 1-2 pages.
_MAX_PAGES = 3

_OUTPUT_KEYS = [
    "cert_number", "expiry_date", "issue_date", "scheme",
    "product_name", "manufacturer", "confidence", "notes",
]


# ═══════════════════════════════════════════════════════════════════════════
# Deterministic regex parse
# ═══════════════════════════════════════════════════════════════════════════

# Ordered from most-specific to most-generic; first match wins.
_CERT_NUM_PATTERNS: list[re.Pattern] = [
    # M1 (Finnish RT classification): "RT-12345 / 2024" or "RTS 12345"
    re.compile(r"\bRT[S]?\s*[-–]?\s*(\d{3,6}(?:\s*/\s*\d{2,4})?)\b", re.I),
    # Eurofins / Indoor Air Comfort Gold — Italian label
    re.compile(r"N[o°]\.?\s+del\s+certificato[:\s]+([A-Z0-9][A-Z0-9\-\/\.]{3,35})", re.I),
    # Full IACG cert number including prefix (e.g. IACG-400-15-01-2021B)
    re.compile(r"\b(IACG[-][0-9]{2,6}(?:[-][0-9A-Z]{1,8}){1,6})\b", re.I),
    # Eurofins legacy short pattern: "IAC 123456" or "IACG 12345"
    re.compile(r"\bIAC?G?[-_\s]?(\d{4,10})\b", re.I),
    # Eurofins standalone registration IDs (long numeric)
    re.compile(r"(?:eurofins|indoor\s+air\s+comfort)[^\n]{0,30}?(\d{6,12})", re.I),
    # EMICODE: "EC1 R 12345" or "GEV-EMICODE 12345"
    re.compile(r"\bEC1\s*[Rr]?\s*(\d{3,8})\b"),
    re.compile(r"GEV[-\s]EMICODE\s*[:\s]([A-Z0-9\-]{3,20})", re.I),
    # ICMQ / Italian certification body: "ICMQ-12345" or "ICMQ Nr. 12345"
    re.compile(r"\bICMQ[-\s]?(?:nr\.?|n\.?)?\s*([A-Z0-9][A-Z0-9\-\/]{2,20})", re.I),
    # French VOC A+: "n° de certif." or "numéro de certificat"
    re.compile(r"num[eé]ro\s+de\s+certif[^\s]*[.:\s]*([A-Z0-9][A-Z0-9\-\/\.]{2,25})", re.I),
    # Generic: "Certificate No. ABC-12345" / "Cert. Nr. 12345" / "N° 12345"
    re.compile(
        r"(?:certif(?:icate|ication)?|cert\.?)\s*(?:no|nr|n°|number|num\.?|#)[.:\s]*([A-Z0-9][A-Z0-9\-\/\.]{2,25})",
        re.I,
    ),
    re.compile(r"\bN[o°r]\b[.:\s]*([A-Z0-9][A-Z0-9\-\/\.]{2,20})", re.I),
    # Registration number
    re.compile(
        r"(?:registration|reg\.?)\s*(?:no|nr|number|num\.?|#)[.:\s]*([A-Z0-9][A-Z0-9\-\/\.]{2,25})",
        re.I,
    ),
]

_SCHEME_HINT_PATTERNS: dict[str, list[re.Pattern]] = {
    "m1":         [_CERT_NUM_PATTERNS[0]],
    "indoor air": [_CERT_NUM_PATTERNS[1], _CERT_NUM_PATTERNS[2], _CERT_NUM_PATTERNS[3]],
    "iacg":       [_CERT_NUM_PATTERNS[1], _CERT_NUM_PATTERNS[2]],
    "emicode":    [_CERT_NUM_PATTERNS[5], _CERT_NUM_PATTERNS[6]],
    "icmq":       [_CERT_NUM_PATTERNS[7]],
}

_DATE_ANCHOR_RE = re.compile(
    r"(?:valid\s+(?:until|through|to|till)|"
    r"expir(?:y|es?)\s*(?:date)?|"
    r"validity(?:\s+(?:until|to|date))?|"
    r"g[üu]ltig\s*bis|"                          # German
    r"valido\s+fino\s+al|"                        # Italian phrase
    r"data\s+di\s+validit[aà]|"                   # Italian label (Eurofins: "Data di validità")
    r"scaden(?:za|te)\s*(?:al|:)?|"               # Italian: scadenza/scadente
    r"valable\s+jusqu'?au)"                        # French (jusqu'au / jusquau)
    r"\s*[:\-–]?\s*",
    re.I,
)

_ISSUE_ANCHOR_RE = re.compile(
    r"(?:issue\s*date|date\s*of\s*issue|"
    r"data\s*(?:di\s*)?emissione|"                # Italian
    r"ausgestellt|"                                 # German
    r"date\s*d'?[ée]mission)"                       # French
    r"\s*[:\-–]?\s*",
    re.I,
)

_DATE_NUM_RE = re.compile(
    r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})"
    r"|(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})"
)

_MONTHS = {
    "jan": 1, "january": 1, "gennaio": 1, "januar": 1, "janvier": 1,
    "feb": 2, "february": 2, "febbraio": 2, "februar": 2, "février": 2, "fevrier": 2,
    "mar": 3, "march": 3, "marzo": 3, "märz": 3, "marz": 3, "mars": 3,
    "apr": 4, "april": 4, "aprile": 4, "avril": 4,
    "may": 5, "maggio": 5, "mai": 5,
    "jun": 6, "june": 6, "giugno": 6, "juni": 6, "juin": 6,
    "jul": 7, "july": 7, "luglio": 7, "juli": 7, "juillet": 7,
    "aug": 8, "august": 8, "agosto": 8, "août": 8, "aout": 8,
    "sep": 9, "september": 9, "settembre": 9, "septembre": 9,
    "oct": 10, "october": 10, "ottobre": 10, "oktober": 10, "octobre": 10,
    "nov": 11, "november": 11, "novembre": 11,
    "dec": 12, "december": 12, "dicembre": 12, "dezember": 12, "décembre": 12, "decembre": 12,
}
_DATE_TEXT_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})"
    r"|(" + "|".join(_MONTHS) + r")\s+(\d{1,2})[,\s]+(\d{4})",
    re.I,
)


def _parse_date_str(text: str) -> str | None:
    """Try to parse a date string into ISO YYYY-MM-DD. Returns None on failure."""
    text = text.strip()
    m = _DATE_NUM_RE.match(text)
    if m:
        if m.group(1):  # DD/MM/YYYY (or YYYY/MM/DD if first token has 4 digits)
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = 2000 + y if y < 100 else y
            if len(m.group(1)) == 4:
                y, mo, d = d, mo, int(m.group(3))
        else:           # YYYY-MM-DD
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _find_date_near_anchor(text: str, anchor_re: re.Pattern) -> str | None:
    for m_anchor in anchor_re.finditer(text):
        snippet = text[m_anchor.end(): m_anchor.end() + 40].strip()
        m = _DATE_NUM_RE.search(snippet)
        if m:
            iso = _parse_date_str(m.group(0))
            if iso:
                return iso
        m = _DATE_TEXT_RE.search(snippet)
        if m:
            if m.group(1):
                d, mon_str, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
            else:
                mon_str, d, y = m.group(4).lower(), int(m.group(5)), int(m.group(6))
            mo = _MONTHS.get(mon_str)
            if mo:
                try:
                    return datetime(y, mo, d).strftime("%Y-%m-%d")
                except ValueError:
                    pass
    return None


def _find_expiry_date(text: str) -> str | None:
    iso = _find_date_near_anchor(text, _DATE_ANCHOR_RE)
    if iso:
        return iso
    # Fallback: scan entire text for textual dates near expiry vocabulary
    for m in _DATE_TEXT_RE.finditer(text):
        context = text[max(0, m.start() - 60): m.start()].lower()
        if any(w in context for w in ("valid", "expir", "until", "scad", "gültig", "bis")):
            if m.group(1):
                d, mon_str, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
            else:
                mon_str, d, y = m.group(4).lower(), int(m.group(5)), int(m.group(6))
            mo = _MONTHS.get(mon_str)
            if mo:
                try:
                    return datetime(y, mo, d).strftime("%Y-%m-%d")
                except ValueError:
                    pass
    return None


def _find_issue_date(text: str) -> str | None:
    return _find_date_near_anchor(text, _ISSUE_ANCHOR_RE)


def _find_cert_number(text: str, scheme_hint: str = "") -> str | None:
    """Return the first certificate/registration number found in text, or None.

    scheme_hint: lowercased scheme label (e.g. "m1", "indoor air comfort gold").
    Scheme-specific patterns are tried first when the hint matches.
    """
    ordered: list[re.Pattern] = []
    if scheme_hint:
        for key, pats in _SCHEME_HINT_PATTERNS.items():
            if key in scheme_hint:
                ordered.extend(pats)
    for pat in _CERT_NUM_PATTERNS:
        if pat not in ordered:
            ordered.append(pat)
    for pat in ordered:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip().rstrip(".")
            if len(candidate) >= 3:
                return candidate
    return None


_SCHEME_LABEL_RE = re.compile(
    r"\b(Indoor Air Comfort Gold|EMICODE\s*EC1\s*Plus|EMICODE\s*EC1|M1|"
    r"GREENGUARD\s*Gold|GREENGUARD|Blue Angel|ICMQ|Nordic Swan|"
    r"Cradle to Cradle|Declare\s*2\.0)\b",
    re.I,
)


def _find_scheme(text: str, scheme_hint: str = "") -> str | None:
    m = _SCHEME_LABEL_RE.search(text)
    if m:
        return m.group(1).strip()
    return scheme_hint.strip() or None


def _det_parse(text: str, scheme_hint: str = "") -> dict:
    return {
        "cert_number":  _find_cert_number(text, scheme_hint),
        "expiry_date":  _find_expiry_date(text),
        "issue_date":   _find_issue_date(text),
        "scheme":       _find_scheme(text, scheme_hint),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Text-quality check — catches garbled/custom-encoded fonts
# ═══════════════════════════════════════════════════════════════════════════
#
# Some VOC certs embed fonts without a proper ToUnicode CMap; PyMuPDF then
# extracts plausible-looking but meaningless text (each glyph mapped to the
# wrong codepoint). A plain length check doesn't catch this — the fix is to
# check that a reasonable fraction of the extracted characters look like
# ordinary printable ASCII (letters/digits/spaces/punctuation).

def _is_readable_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 40:
        return False
    ascii_ish = sum(1 for c in stripped if c.isascii() and (c.isalnum() or c.isspace() or c in ".,:;-/()°"))
    return (ascii_ish / len(stripped)) >= 0.85


# ═══════════════════════════════════════════════════════════════════════════
# Claude API calls
# ═══════════════════════════════════════════════════════════════════════════

_SYS_PROMPT = """\
You are an expert extractor of VOC/indoor-air emission certificate data \
(e.g. Indoor Air Comfort Gold, M1, EMICODE, ICMQ, GREENGUARD, Blue Angel).
You receive plain text (or images) of a short certificate (1-2 pages).
Return ONLY a valid JSON object — no markdown fences, no prose, no comments.

JSON schema (null for any field not found):
{
  "product_name": string|null,
  "manufacturer": string|null,
  "scheme": string|null,
  "cert_number": string|null,
  "issue_date": string|null,
  "expiry_date": string|null,
  "confidence": "high"|"medium"|"low",
  "notes": string
}

Rules:
- scheme: the certification scheme name as printed, e.g. "Indoor Air Comfort Gold", "M1", "EMICODE EC1 Plus".
- cert_number: the certificate/registration number as printed (keep original formatting, e.g. "IACG-456-01-02-2024B").
- issue_date / expiry_date: convert to ISO YYYY-MM-DD. expiry_date is the "valid until" / "validity date" / "scadenza" date,
  NOT the issue date.
- manufacturer is the certificate holder / applicant company; product_name is the certified product/product line.
- Return ONLY the JSON object.\
"""


def _message_text(resp) -> str:
    parts = [getattr(b, "text", "") or "" for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(parts).strip()
    if not text:
        raise ValueError("Model returned no text blocks")
    return text


def _call_text(text: str, n_pages: int, client: anthropic.Anthropic) -> tuple[dict, int, int]:
    body = f"Certificate has {n_pages} page(s).\n\n{text}"
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYS_PROMPT,
        messages=[{"role": "user", "content": body}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", _message_text(resp))
    return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


def _page_png_b64(page, dpi=150) -> str:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    return base64.standard_b64encode(pix.tobytes("png")).decode()


def _call_vision(doc, n_pages: int, client: anthropic.Anthropic) -> tuple[dict, int, int]:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _page_png_b64(doc[i])}}
        for i in range(n_pages)
    ]
    content.append({"type": "text", "text": f"Certificate has {n_pages} page(s). Extract all requested fields."})
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYS_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", _message_text(resp))
    return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def extract_voc(
    pdf_path: str | Path,
    client: anthropic.Anthropic | None = None,
    scheme_hint: str = "",
) -> dict:
    """
    Extract VOC certificate data from a PDF file.

    Parameters
    ----------
    pdf_path    : path to the VOC certificate PDF
    client      : Anthropic client; pass None to skip all Claude calls
                  (deterministic-only extraction)
    scheme_hint : lowercased hint about the expected scheme (e.g. the
                  Excel "V__VOC_Cert" label), used to prioritise regex
                  patterns and pre-fill `scheme` if nothing is found

    Returns
    -------
    dict with cert_number, expiry_date, issue_date, scheme, product_name,
    manufacturer, confidence, notes, plus internal meta keys:
    _mode, _pages_sent, _input_tokens, _output_tokens, _error
    """
    pdf_path = Path(pdf_path)
    res: dict = {k: None for k in _OUTPUT_KEYS}
    res.update({
        "confidence": "low", "notes": "",
        "_mode": "none", "_pages_sent": 0,
        "_input_tokens": 0, "_output_tokens": 0, "_error": None,
    })

    if not pdf_path.exists():
        res["_error"] = f"File not found: {pdf_path.name}"
        return res

    try:
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as exc:
            msg = str(exc).lower()
            if "password" in msg:
                res["_error"] = "PDF is password-protected — cannot open without the password."
            elif "not a pdf" in msg or "no objects" in msg:
                res["_error"] = "File does not appear to be a valid PDF."
            else:
                res["_error"] = f"PDF could not be opened: {exc}"
            return res

        n_pages = min(len(doc), _MAX_PAGES)
        page_texts = [doc[i].get_text("text") for i in range(n_pages)]
        full_text = "\n".join(page_texts)
        readable = _is_readable_text(full_text)

        # ── 1. Deterministic regex parse ────────────────────────────────
        if readable:
            det = _det_parse(full_text, scheme_hint)
            res.update(det)
            res["_pages_sent"] = n_pages
            res["_mode"] = "deterministic"
            if res["cert_number"] and res["expiry_date"]:
                res["confidence"] = "high"
                doc.close()
                return res

        # ── 2. Claude text (fills gaps, or full extraction if unreadable) ──
        if client is not None:
            if readable:
                parsed, it, ot = _call_text(full_text, n_pages, client)
                for k in _OUTPUT_KEYS:
                    if parsed.get(k) is not None and res.get(k) is None:
                        res[k] = parsed[k]
                res["confidence"] = parsed.get("confidence", res["confidence"])
                res["notes"] = parsed.get("notes") or res["notes"]
                res["_input_tokens"] += it
                res["_output_tokens"] += ot
                res["_mode"] = "deterministic+text" if (res["cert_number"] or res["expiry_date"]) else "text"
            else:
                # ── 3. Claude vision — scanned or garbled-font certificate ──
                parsed, it, ot = _call_vision(doc, n_pages, client)
                for k in _OUTPUT_KEYS:
                    if parsed.get(k) is not None:
                        res[k] = parsed[k]
                res["confidence"] = parsed.get("confidence", "low")
                res["notes"] = (parsed.get("notes") or "") + " [vision: scanned/garbled-font PDF]"
                res["_input_tokens"] += it
                res["_output_tokens"] += ot
                res["_pages_sent"] = n_pages
                res["_mode"] = "vision"

        doc.close()

    except json.JSONDecodeError as e:
        res["_error"] = f"JSON parse error: {e}"
    except Exception:
        res["_error"] = traceback.format_exc()

    return res


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Rough USD cost for claude-sonnet-4 ($3/M in · $15/M out)."""
    return (input_tokens * 3 + output_tokens * 15) / 1_000_000


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python lib_voc_extractor.py <voc_cert.pdf> [scheme_hint]")
        sys.exit(1)

    hint = sys.argv[2] if len(sys.argv) > 2 else ""
    data = extract_voc(sys.argv[1], client=anthropic.Anthropic(), scheme_hint=hint.lower())
    cost = estimate_cost(data["_input_tokens"], data["_output_tokens"])
    print(json.dumps({k: v for k, v in data.items() if not k.startswith("_")}, indent=2, ensure_ascii=False))
    print(f"\nmode={data['_mode']}  pages={data['_pages_sent']}  ~${cost:.4f} USD")
    if data["_error"]:
        print(f"ERROR: {data['_error'][:400]}")
