"""
lib_doc_classifier.py  –  EETRA Material Library document-type classifier
────────────────────────────────────────────────────────────────────────────
Classifies an already-downloaded file in 01_data/pdf into a document-type
bucket — independent of which Excel column/URL it came from. Built to
answer one question: "what IS this file, really?" — useful for indexing
the media folder and for catching mismatches (a VOC URL that actually
downloaded a marketing webpage, a self-declaration letter mislabeled as a
formal certificate, etc — see libs/lib_voc_extractor.py's parse_failed
investigation for real examples of this happening).

Document types
──────────────
  epd               Environmental Product Declaration
  voc_certificate   Formal VOC/indoor-air emissions certificate with a
                    scheme name + certificate number (Indoor Air Comfort
                    Gold, EMICODE, M1, GREENGUARD, Blue Angel, ICMQ, ...)
  voc_declaration   Manufacturer self-declaration about VOC/emissions with
                    no formal scheme/certificate number (e.g. "our tiles
                    are fired at 1200°C and release no VOCs")
  technical_sheet   Product technical/performance data sheet
  webpage           HTML page saved with a .pdf/.htm extension — nav menus,
                    cookie banners, product-listing pages; not a real document
  other             Doesn't fit any of the above with any confidence

Two tiers (cheapest first):
  1. Heuristic keyword/structure scoring on extracted text — free, instant
  2. Optional Claude text/vision fallback for low-confidence or unreadable
     (scanned/garbled-font) cases
"""

from __future__ import annotations
import base64, json, re, traceback
from pathlib import Path

import fitz  # PyMuPDF

# Reuse the EPD/VOC identifier regexes already validated in the other
# extractors instead of re-deriving them.
from libs.lib_epd_extractor import PROG_RE as _EPD_PROG_RE, LCA_KW_RE as _EPD_LCA_KW_RE
from libs.lib_voc_extractor import _SCHEME_LABEL_RE as _VOC_SCHEME_RE, _CERT_NUM_PATTERNS as _VOC_CERT_NUM_PATTERNS


DOC_TYPES = ["epd", "voc_certificate", "voc_declaration", "technical_sheet", "webpage", "other"]

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 256
_MAX_PAGES = 2


# ═══════════════════════════════════════════════════════════════════════════
# Heuristic scoring
# ═══════════════════════════════════════════════════════════════════════════

_WEBPAGE_CHROME_RE = re.compile(
    r"\b(HOME|PRODUCTS|MENU|CONTACT US|COOKIE POLICY|PRIVACY POLICY|"
    r"Cookie Policy|Privacy Policy|Termini e condizioni|Tutti i Prodotti|"
    r"Tutti i Sistemi|GiT BADGE)\b"
)

_TECH_SHEET_RE = re.compile(
    r"\b(scheda\s+tecnica|technical\s+data\s+sheet|technical\s+sheet|"
    r"product\s+data\s+sheet|datasheet|dati\s+tecnici|caratteristiche\s+tecniche|"
    r"fiche\s+technique|technisches\s+datenblatt|thermal\s+conductivity|"
    r"conducibilit[aà]\s+termica|resistenza\s+a\s+compressione|"
    r"compressive\s+strength|densit[aà]|reaction\s+to\s+fire|"
    r"euroclass|EN\s*13501)\b",
    re.I,
)

_EPD_STRONG_RE = re.compile(
    r"\b(EN\s*15804|ISO\s*14025|"
    r"Environmental\s+Product\s+Declaration|"
    r"Dichiarazione\s+Ambientale\s+di\s+Prodotto|"
    r"Umwelt[\-\s]?Produktdeklaration|"
    r"D[ée]claration\s+Environnementale\s+de\s+Produit)\b",
    re.I,
)

_VOC_DECLARATION_RE = re.compile(
    r"\b(self[\s\-]?declaration|autodichiarazione|autocertificazione|"
    r"dichiariamo\s+che|declares?\s+that|we\s+hereby\s+declare|"
    r"attesta\s+che|hereby\s+certif(?:y|ies)\s+that\s+the\s+above)\b",
    re.I,
)


def _readable_ratio(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    ascii_ish = sum(1 for c in stripped if c.isascii() and (c.isalnum() or c.isspace() or c in ".,:;-/()°%"))
    return ascii_ish / len(stripped)


def _bullet_line_ratio(text: str) -> float:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    bullets = sum(1 for l in lines if l.strip().startswith(("•", "○", "■", "-")) and len(l.strip()) < 60)
    return bullets / len(lines)


def _heuristic_classify(text: str) -> tuple[str, str, str]:
    """Returns (doc_type, confidence, notes). confidence is 'high'|'medium'|'low'."""
    stripped = text.strip()
    if len(stripped) < 20:
        return "other", "low", "No usable text extracted (scanned image or empty page)."

    readable = _readable_ratio(stripped)
    if readable < 0.85:
        return "other", "low", "Extracted text looks garbled (likely a custom-encoded/embedded font)."

    scores = {t: 0 for t in DOC_TYPES if t != "other"}

    # Webpage chrome — nav menus, cookie banners, etc.
    chrome_hits = len(_WEBPAGE_CHROME_RE.findall(stripped))
    bullet_ratio = _bullet_line_ratio(stripped)
    if chrome_hits >= 2 or bullet_ratio > 0.4:
        scores["webpage"] += 3 + chrome_hits

    # EPD signals. A recognised programme-operator name (IBU, Environdec,
    # EPDItaly, ...) is decisive on its own. The bare "Environmental Product
    # Declaration" phrase is NOT decisive by itself though — a LEED credit
    # sheet can *mention* EPDs as a credit category without being one — so it
    # only counts as strong evidence when corroborated by a programme
    # operator or actual LCA-result keywords (GWP, kg CO2eq...).
    prog_hit = bool(_EPD_PROG_RE.search(stripped))
    lca_kw_count = min(len(_EPD_LCA_KW_RE.findall(stripped)), 5)
    strong_hits = min(len(_EPD_STRONG_RE.findall(stripped)), 2)
    if prog_hit:
        scores["epd"] += 3
    scores["epd"] += lca_kw_count
    if strong_hits and (prog_hit or lca_kw_count >= 1):
        scores["epd"] += 4 * strong_hits
    elif strong_hits:
        scores["epd"] += 1

    # VOC certificate signals — scheme name + a plausible cert number pattern.
    # ICMQ double-duties as both a VOC certifier AND a common PCR-writing body
    # cited inside EPDItaly EPDs ("PCR ICMQ-001/15") — don't let that citation
    # register as VOC-certificate evidence once we already have a confirmed
    # EPD programme operator.
    scheme_m = _VOC_SCHEME_RE.search(stripped)
    if scheme_m and not (prog_hit and scheme_m.group().upper() == "ICMQ"):
        scores["voc_certificate"] += 2
    if not prog_hit:
        for pat in _VOC_CERT_NUM_PATTERNS:
            if pat.search(stripped):
                scores["voc_certificate"] += 1
                break

    # VOC self-declaration signals (letter-style, no formal scheme/number)
    if _VOC_DECLARATION_RE.search(stripped):
        scores["voc_declaration"] += 3

    # Technical sheet signals
    scores["technical_sheet"] += min(len(_TECH_SHEET_RE.findall(stripped)), 4)

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]
    second_best = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0

    if best_score == 0:
        return "other", "low", "No document-type signal matched any known pattern."
    if best_score - second_best <= 1 and best_score < 3:
        return best_type, "low", f"Ambiguous — scores: {scores}"
    confidence = "high" if best_score >= 3 and (best_score - second_best) >= 2 else "medium"
    return best_type, confidence, f"scores: {scores}"


# ═══════════════════════════════════════════════════════════════════════════
# Claude fallback
# ═══════════════════════════════════════════════════════════════════════════

_SYS_PROMPT = """\
You classify construction-product documents into exactly one category.
Return ONLY a valid JSON object — no markdown fences, no prose, no comments.

Categories:
- "epd": Environmental Product Declaration (LCA results, GWP, EN 15804, declared unit).
- "voc_certificate": a formal VOC/indoor-air emissions certificate naming a scheme
  (Indoor Air Comfort Gold, EMICODE, M1, GREENGUARD, Blue Angel, ICMQ, etc.) with a
  certificate/registration number and usually a validity/expiry date.
- "voc_declaration": a manufacturer's own letter/statement about VOC content or emissions,
  with NO formal third-party scheme or certificate number.
- "technical_sheet": a product technical/performance data sheet (dimensions, mechanical/
  thermal properties, standards references) — not about emissions or LCA at all.
- "webpage": this is clearly a website page (navigation menu, cookie banner, product
  listing) that was saved as a PDF/image by mistake, not a real document.
- "other": doesn't fit any of the above.

JSON schema:
{
  "doc_type": "epd"|"voc_certificate"|"voc_declaration"|"technical_sheet"|"webpage"|"other",
  "confidence": "high"|"medium"|"low",
  "notes": string
}
Return ONLY the JSON object.\
"""


def _message_text(resp) -> str:
    parts = [getattr(b, "text", "") or "" for b in resp.content if getattr(b, "type", None) == "text"]
    text = "".join(parts).strip()
    if not text:
        raise ValueError("Model returned no text blocks")
    return text


def _call_claude_text(text: str, client) -> tuple[dict, int, int]:
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYS_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", _message_text(resp))
    return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


def _page_png_b64(page, dpi=150) -> str:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    return base64.standard_b64encode(pix.tobytes("png")).decode()


def _call_claude_vision(doc, n_pages: int, client) -> tuple[dict, int, int]:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _page_png_b64(doc[i])}}
        for i in range(n_pages)
    ]
    content.append({"type": "text", "text": "Classify this document."})
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYS_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", _message_text(resp))
    return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def classify_document(
    pdf_path: str | Path,
    client=None,
    escalate_low_confidence: bool = True,
    force_claude: bool = False,
) -> dict:
    """
    Classify a file's actual document type.

    Parameters
    ----------
    pdf_path                : path to the file (PDF or image opened via fitz)
    client                  : anthropic.Anthropic instance, or None to run
                               heuristic-only classification (free, no API calls)
    escalate_low_confidence : if True and a client is given, low-confidence
                               heuristic results get a Claude pass (text or
                               vision, depending on text readability)
    force_claude            : if True and a client is given, always run the
                               Claude pass regardless of heuristic confidence
                               (bypasses the heuristic entirely — costs more)

    Returns
    -------
    dict: doc_type, confidence, method ("heuristic"|"claude_text"|"claude_vision"),
    notes, _input_tokens, _output_tokens, _error
    """
    pdf_path = Path(pdf_path)
    res = {
        "doc_type": "other", "confidence": "low", "method": "heuristic", "notes": "",
        "_input_tokens": 0, "_output_tokens": 0, "_error": None,
    }

    if not pdf_path.exists():
        res["_error"] = f"File not found: {pdf_path.name}"
        return res

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        res["_error"] = f"Could not open file: {exc}"
        return res

    try:
        n_pages = min(len(doc), _MAX_PAGES)
        text = "\n".join(doc[i].get_text("text") for i in range(n_pages))

        if not force_claude:
            doc_type, confidence, notes = _heuristic_classify(text)
            res.update({"doc_type": doc_type, "confidence": confidence, "notes": notes})

        needs_claude = client is not None and (
            force_claude or (escalate_low_confidence and res["confidence"] == "low")
        )
        if needs_claude:
            readable = _readable_ratio(text.strip()) >= 0.85 and len(text.strip()) >= 20
            try:
                if readable:
                    parsed, it, ot = _call_claude_text(text, client)
                    method = "claude_text"
                else:
                    parsed, it, ot = _call_claude_vision(doc, n_pages, client)
                    method = "claude_vision"
                if parsed.get("doc_type") in DOC_TYPES:
                    res["doc_type"] = parsed["doc_type"]
                    res["confidence"] = parsed.get("confidence", "medium")
                    res["notes"] = parsed.get("notes", "")
                    res["method"] = method
                res["_input_tokens"] += it
                res["_output_tokens"] += ot
            except Exception as exc:
                res["_error"] = f"Claude classification failed: {exc}"

        doc.close()
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
        print("Usage: python lib_doc_classifier.py <file.pdf> [--claude]")
        sys.exit(1)

    client = None
    if "--claude" in sys.argv:
        import anthropic
        client = anthropic.Anthropic()

    data = classify_document(sys.argv[1], client=client)
    print(json.dumps(data, indent=2, ensure_ascii=False))
