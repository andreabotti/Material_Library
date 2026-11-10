"""
13_parse_price_lists.py — encode manufacturer list prices (listini) into
``01_data/price_lists.parquet``.

Why this exists
---------------
The catalogue carries technical and environmental data but no commercial one.
Manufacturers publish their list prices as PDF listini — a page per product,
each with a small price table. This tool downloads those PDFs, reads the tables
and writes them out as two tidy tables the app can join on:

  price_lists.parquet       one row per priced SKU (product + thickness + size)
  price_supplements.parquet accessories, coatings and surcharges (per family)

Prices are *list* prices, VAT excluded, before any commercial discount — the app
must present them as an indication, never as a quotation.

First source: URSA Italia (9 listini, "Listino prezzi" documents at
https://www.ursa.it/it-it/dati-tecnici-e-documentazione/documentazione/).
The parser is written against the layout Etex uses for the whole URSA range, so
adding a new URSA listino is one line in ``SOURCES``. Another manufacturer with
a different layout needs its own ``parse_*`` function feeding the same schema.

Third source: ATA Torino, a reseller (``parse_ata``), read through its public
WooCommerce Store API: Siniat, Gyproc, Isover, Fassa Bortolo, Knauf boards,
Supercel, Promat and Global Building (``ATA_SOURCES``, with an explicit
shop-name -> catalogue-name table per brand). These are web *shop* prices, not the manufacturer's listino:
the shop shows them IVA included and mostly "in offerta", per sheet or sack. They
are converted to EUR/m2 (sheet area from the title) or EUR/kg with the IVA taken
out, and ``price_basis`` says so; the app words them as a reseller price.
In October 2026 ATA rewrote its titles — the pack size, the thickness and the
panel size moved into the short description, the type word is written lower case
and sometimes first, and the boards are named plainly ("Knauf GKB Lastra
standard 1200x3000x12,5 mm", not "Knauf Lastra GKB1330"). The parser reads the
description when the title says nothing, and the ``ATA_NAMES_*`` tables are
keyed on the new names, matched without regard to case.

Second source: Knauf Insulation Italia, "Listino prezzi edilizia" (one 23-sheet
PDF, May 2026, ``parse_knauf``). The PDF is a set of A3 spreads, two printed pages
per sheet and up to two tables per page, so it is read half-sheet by half-sheet.
Its download link sits behind a Cloudflare challenge: the PDF has to be saved by
hand as ``.cache/pricelists/knauf_insulation.pdf`` (it is never fetched). Its
availability flag is a delivery-time band (A <= 5 d, B <= 10 d, S on request),
not the URSA stock flag - see ``AVAILABILITY_LEGENDS`` in libs/lib_prices.py.

Fourth source: Ediltec Insulation, "Listino prezzi" (one PDF, April 2026,
``parse_ediltec``) - the POLIISO polyiso boards and roof system, the X-FOAM XPS
range and the GIBITEC insulated plasterboards, with the roof accessories, the
GIBITEC board options and the service-policy costs as supplements. It downloads
without a challenge. Its flag is the make-to-stock / make-to-order one (S = MTS,
O = MTO). The listino prints no lambda, so those columns stay empty and the app
shows no cost per R for Ediltec.

Fifth source: POLIISO AIR (``parse_poliiso_air``), Ediltec's pre-insulated
ductwork system. It is sold off its own site and is absent from the building
listino above; its catalogue (April 2025, poliisoairducts.com) carries the
prices, 23 panels and 129 accessories. It is a year older than the building
listino, which is why the edition is shown with every price.

Sixth source: GAIVI, a Treviso building-materials cooperative, for Iris
Ceramiche (``parse_gaivi``) - the only price published for the Iris Ceramica
Group range. It is a public retail list of 285 articles (floor tiles, wall tiles
and decori), given as two PDFs with the same content, one with a photo per
article; both are read, the second only to check they agree. Neither can be
downloaded without a session token, so both are saved by hand as
``.cache/pricelists/gaivi_iris.pdf`` and ``gaivi_iris_foto.pdf``.
These are retail prices IVA included (22% taken out, as for ATA) and ``price_basis``
says so. Two things the listino does not print:
  * the unit. Tiles go by the square metre and pezzi speciali (battiscopa,
    listelli, tozzetti, rosoni) by the piece, which is read off the section and
    the description; the per-piece rows become supplements. The rule was audited
    against the ``Unita`` field of all 285 article pages on gaivi.it and agrees
    on 280 of them, the five it does not being listed in ``GAIVI_UNITS``.
  * the thickness. The catalogue splits Iris porcelain stoneware by thickness,
    so only the wall tiles can be named without guessing ("Ceramics for internal
    wall coverings"); the floor tiles keep their commercial names, are priced,
    and stay unmatched. Their ``article`` column carries the commercial name.
Note that gaivi.it shows the same articles 1/11 higher than its own PDF (€ 21,96
against € 20,13), which is a 20% against a 10% IVA rate; neither is the 22% the
site states elsewhere as its ordinary rate. The PDF is what is read.

How the tables are read
-----------------------
Every URSA price table has the same backbone whatever the family:

    Codice prodotto | Spessore | Dimensioni | [Lambda] [R] | Prezzo €/… | Dis* | logistics…

The availability flag (S / O / R, "Dis*") is the anchor: everything to its left
is product data, everything to its right is packaging and logistics. The column
meaning is read off the unit row ("€/m2 n° pallet n° rotoli m2 n° conf. m2"), so
the same code handles rolls, panels, boards and bags without a per-family table.
Rotated sidebar text (the family name printed vertically, "Reazione al fuoco",
…) lands inside the text lines and is ignored by anchoring on that flag.

Usage
-----
    python 04_tools/13_parse_price_lists.py            # download + parse + write
    python 04_tools/13_parse_price_lists.py --no-fetch # reuse the cached PDFs
    python 04_tools/13_parse_price_lists.py --dry-run  # parse, print, write nothing

The PDFs are cached under ``.cache/pricelists/``; re-running is idempotent.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pdfplumber
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "pricelists"
DATA_DIR = ROOT / "01_data"
PRICES_PARQUET = DATA_DIR / "price_lists.parquet"
SUPPLEMENTS_PARQUET = DATA_DIR / "price_supplements.parquet"

DOC_PAGE = ("https://www.ursa.it/it-it/dati-tecnici-e-documentazione/documentazione/"
            "?filter=documentType.eq.PriceList")

# (slug, manufacturer, family, pdf url) — the URSA Italia listino set
SOURCES = [
    ("ursa_glasswool", "Ursa", "URSA GLASSWOOL",
     "https://etex.azureedge.net/doc_1194582_it/original/1667802296/"
     "ursa_glasswool_listino_prezzi.pdf?brand=ursa&market=it"),
    ("ursa_purefloc", "Ursa", "URSA PUREFLOC",
     "https://etex.azureedge.net/doc_1194584_it/original/-262243852/"
     "ursa_purefloc_listino-prezzi.pdf?brand=ursa&market=it"),
    ("ursa_pureone", "Ursa", "URSA PUREONE",
     "https://etex.azureedge.net/doc_1194587_it/original/1762046319/"
     "ursa_pureone_listino_prezzi.pdf?brand=ursa&market=it"),
    ("ursa_tectonic", "Ursa", "URSA TECTONIC",
     "https://etex.azureedge.net/doc_1194591_it/original/-1767583022/"
     "ursa_tectonic_listino_prezzi.pdf?brand=ursa&market=it"),
    ("ursa_woodlith", "Ursa", "URSA WOODLITH",
     "https://etex.azureedge.net/doc_1194596_it/original/-1898051197/"
     "ursa_woodlith_listino_prezzi.pdf?brand=ursa&market=it"),
    ("ursa_terra", "Ursa", "URSA TERRA",
     "https://etex.azureedge.net/doc_1194598_it/original/-1898051197/"
     "ursa_terra_listino_prezzi.pdf?brand=ursa&market=it"),
    ("ursa_air", "Ursa", "URSA AIR",
     "https://etex.azureedge.net/doc_1194849_it/original/-1579352059/"
     "ursa_air_listino-prezzi_2026_repo_e0326_r01_0426.pdf?brand=ursa&market=it"),
    ("ursa_tech", "Ursa", "URSA TECH",
     "https://etex.azureedge.net/doc_1194850_it/original/-1579352059/"
     "ursa-tech-listino-prezzi.pdf?brand=ursa&market=it"),
    ("ursa_xps", "Ursa", "URSA XPS",
     "https://etex.azureedge.net/doc_1195130_it/original/-1295239321/"
     "ursa_xps_listino_prezzi_maggio26.pdf?brand=ursa&market=it"),
]

# Knauf Insulation: a single PDF, saved by hand (see the module docstring)
KNAUF_SOURCE = (
    "knauf_insulation", "Knauf", "Knauf Insulation",
    "https://knauf.com/api/download-center/v1/assets/"
    "694935ca-39fa-402b-8e84-1589b2b304a8?download=true")

# Ediltec Insulation: one PDF, "Listino prezzi" (parse_ediltec)
EDILTEC_SOURCE = (
    "ediltec", "EDILTEC", "EDILTEC",
    "https://ediltec.com/wp-content/uploads/download/it/ListinoEdiltec2026c.pdf")

# "Dis*" — S: a stock, O: in produzione contro ordine, R: da valutare col
# Customer Service. The asterisked variants carry a footnote on the page.
FLAGS = {"S", "O", "R", "S*", "O*", "R*", "S**", "O**", "R**"}

RE_NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$")
RE_DIM = re.compile(r"\d+,\d+\s*x\s*\d+,\d+(?:\s*x\s*\d+,\d+)?", re.I)
RE_DIM_MULT = re.compile(r"\d+\s*x\s*\(\s*\d+,\d+\s*x\s*\d+,\d+\s*\)", re.I)
RE_CODE = re.compile(r"^\d{6,8}$")
RE_LAMBDA = re.compile(r"^0,0\d{2,3}$")
RE_HEAD = re.compile(r"^URSA\s+[A-Z0-9][A-Za-z0-9ÀÈÉÌÒÙ''/\-+. ]*$")
RE_PACK = re.compile(r"^Confezionamento:\s*(.+)$", re.I)
RE_EDITION = re.compile(r"^(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|"
                        r"Agosto|Settembre|Ottobre|Novembre|Dicembre)\s+(\d{4})$")

RE_ACCESSORY = re.compile(
    r"^(?P<code>\d{7})\s+(?P<desc>.*?)\s*(?P<price>\d{1,3}(?:\.\d{3})*,\d{2})\s+"
    r"(?P<flag>[SOR]\*{0,2})\s+(?P<qty>\d+)\s+(?P<unit>[a-zà]+)$")
RE_COATING = re.compile(
    r"^(?P<code>[A-Z][a-z])\s+(?P<desc>[A-Za-zàèéìòù ]+?)\s+(?P<gsm>\d{2,3})\s+"
    r"(?P<price>\d{1,2},\d{2})\b")
RE_SERVICE = re.compile(
    r"^(?P<desc>.+?)\s*(?:\(\d\)\s*)?(?P<code>[A-Z][A-Z0-9]?)\s+(?P<price>\d{1,2},\d{2})\b")
RE_SERVICE_PCT = re.compile(
    r"^(?P<desc>.+?)\s*(?:\(\d\)\s*)?(?P<code>[A-Z][A-Z0-9]?)\s*\+\s*(?P<pct>\d{1,2})\s*%")

MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
          "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
          "novembre": 11, "dicembre": 12}

# the same logistics column under the unit name each family happens to use
PACK_NAMES = {"pallet": "min_order_pallets", "rotol": "units_per_pack",
              "pannell": "units_per_pack", "panell": "units_per_pack",
              "lastr": "units_per_pack", "sacch": "units_per_pack",
              "pacch": "packs_per_pallet", "conf": "packs_per_pallet",
              "scatol": "packs_per_pallet"}

COLUMNS = ["manufacturer", "family", "product", "article", "packaging", "product_code",
           "thickness_mm", "dimensions_m", "lambda_declared_WmK", "lambda_WmK",
           "R_m2KW", "price_eur_m2", "price_eur_m3", "price_eur_kg", "weight_kg",
           "availability", "min_order_pallets", "units_per_pack", "pack_m2",
           "packs_per_pallet", "pallet_m2", "pallet_kg", "currency", "price_basis",
           "listino_edition", "listino_date", "source_doc", "source_page",
           "source_url", "retrieved_on"]


# ---------------------------------------------------------------- helpers ---

def to_num(tok):
    """Italian decimal ('1.122,00') -> float. '-' and non-numbers -> None."""
    if tok is None:
        return None
    tok = str(tok).strip()
    if not RE_NUM.match(tok) or tok in {"-", ""}:
        return None
    return float(tok.replace(".", "").replace(",", "."))


def fetch(slug: str, url: str, refresh: bool) -> Path:
    path = CACHE_DIR / f"{slug}.pdf"
    if path.exists() and not refresh:
        return path
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def value_columns(unit_row: str, context: list[str]) -> list[str]:
    """Columns left of the availability flag, in order, from the unit row."""
    ctx = " ".join(context).lower()
    cols = []
    if "lambda" in ctx or "w/mk" in unit_row.lower():
        cols.append("lambda_WmK")
    if "m2k/w" in unit_row.lower():
        cols.append("R_m2KW")
    if "peso" in ctx and "kg" in ctx:
        cols.append("weight_kg")
    for unit, name in (("€/m2", "price_eur_m2"), ("€/m3", "price_eur_m3"),
                       ("€/kg", "price_eur_kg")):
        if unit in unit_row:
            cols.append(name)
    return cols


def logistics_columns(unit_row: str) -> list[str]:
    """Columns right of the availability flag, in order, from the unit row."""
    tail = unit_row.lower().split("€/")[-1]
    tail = tail[tail.find(" "):] if " " in tail else ""
    cols, areas = [], 0
    for tok in re.findall(r"n°\s*[a-zàè.]+|m2|m3|kg", tail):
        if tok.startswith("n°"):
            word = tok.split("°", 1)[1].strip().strip(".")
            cols.append(next((v for k, v in PACK_NAMES.items() if word.startswith(k)),
                             f"n_{word}"))
        elif tok in {"m2", "m3"}:
            areas += 1
            cols.append("pack_m2" if areas == 1 else "pallet_m2")
        elif tok == "kg":
            cols.append("pallet_kg")
    return cols


def split_on_flag(tokens: list[str]):
    """(product side, availability flag, logistics side) or None for a non-row."""
    for i, tok in enumerate(tokens):
        if tok in FLAGS and i > 0:
            tail = tokens[i + 1:]
            if tail and all(RE_NUM.match(t) or t == "-" for t in tail):
                return tokens[:i], tok, tail
    return None


def cover_edition(text: str) -> tuple[str | None, date | None]:
    """'Giugno 2026' + 'rev. 00/26' from the cover page."""
    month = year = rev = None
    for line in text.split("\n"):
        line = line.strip()
        m = RE_EDITION.match(line)
        if m:
            month, year = m.group(1), int(m.group(2))
        if line.lower().startswith("rev."):
            rev = line
    if not month:
        return (rev, None)
    edition = f"{month} {year}" + (f" ({rev})" if rev else "")
    return edition, date(year, MONTHS[month.lower()], 1)


# ------------------------------------------------------------- the parser ---

def parse_listino(path: Path, manufacturer: str, family: str, url: str) -> tuple[list, list]:
    """Read one URSA listino PDF -> (price rows, supplement rows)."""
    prices, supplements = [], []
    today = date.today().isoformat()
    with pdfplumber.open(path) as pdf:
        edition, edition_date = cover_edition(pdf.pages[0].extract_text() or "")
        for pageno, page in enumerate(pdf.pages, 1):
            lines = [ln.strip() for ln in (page.extract_text() or "").split("\n")]
            product = packaging = lam = None
            value_cols: list[str] = []
            logi_cols: list[str] = []
            has_code = False
            mode = None          # supplement block currently open
            wrapped = ""         # accessory description wrapped onto its own line
            for idx, line in enumerate(lines):
                low = line.lower()

                # --- supplement blocks (accessories, coatings, surcharges) ---
                if low.startswith("accessori"):
                    mode = "accessory"
                elif low.startswith("rivestimenti applicabili"):
                    mode = "coating"
                elif low.startswith("servizi in aggiunta"):
                    mode = "service"
                elif low.startswith("servizi di logistica") or low.startswith("condizioni"):
                    mode = None
                if mode:
                    supplement = read_supplement(line, mode, manufacturer, family,
                                                 pageno, url, wrapped)
                    if supplement:
                        supplements.append(supplement)
                        wrapped = ""
                        continue
                    if mode == "accessory" and not re.match(r"^\d{7}\b", line):
                        wrapped = (wrapped + " " + line).strip() if len(line) > 25 else wrapped

                # --- product heading (sometimes sharing the baseline with the
                #     "Download disponibili" block and the declared lambda) ---
                m = re.match(r"^(URSA\s+[A-Z0-9][^|]*?)\s+Download disponibili", line)
                head = m.group(1) if m else line
                if RE_HEAD.match(head) and len(head) > 6 and head.upper() != family:
                    product = re.sub(r"\s+", " ", head).strip()
                    packaging = None
                    lam = next((to_num(t) for t in line.split() if RE_LAMBDA.match(t)), None)
                    continue
                mp = RE_PACK.match(line)
                if mp:                                   # "Confezionamento: Lastre su pallet"
                    packaging = mp.group(1).strip()
                    continue
                if lam is None:
                    lam = next((to_num(t) for t in line.split() if RE_LAMBDA.match(t)), None)

                # --- table header: learn this table's columns ---
                if "€/" in line:
                    context = lines[max(0, idx - 4):idx]
                    value_cols = value_columns(line, context)
                    logi_cols = logistics_columns(line)
                    has_code = any("codice" in c.lower() for c in context)
                    continue
                if not value_cols:
                    continue

                # --- a price row ---
                split = split_on_flag(line.split())
                if not split:
                    continue
                pre, flag, tail = split
                joined = " ".join(pre)
                dim = RE_DIM_MULT.search(joined) or RE_DIM.search(joined)
                code = next((t for t in pre if RE_CODE.match(t)), None) if has_code else None
                before = joined[:dim.start()] if dim else joined
                after = joined[dim.end():] if dim else joined
                thickness = None
                for tok in before.split():               # last bare integer before the size
                    if re.match(r"^\d{1,3}$", tok) and tok != code:
                        thickness = int(tok)
                row = {
                    "manufacturer": manufacturer, "family": family, "product": product,
                    "packaging": packaging, "product_code": code,
                    "thickness_mm": thickness,
                    "dimensions_m": re.sub(r"\s+", " ", dim.group(0)) if dim else None,
                    "lambda_declared_WmK": lam, "availability": flag,
                    "currency": "EUR", "price_basis": "listino, IVA esclusa",
                    "listino_edition": edition, "listino_date": edition_date,
                    "source_doc": path.name, "source_page": pageno,
                    "source_url": url, "retrieved_on": today,
                }
                values = [t for t in after.split() if RE_NUM.match(t) or t == "-"]
                for name, raw in zip(value_cols, values):
                    row[name] = to_num(raw)
                for name, raw in zip(logi_cols, tail):
                    row.setdefault(name, to_num(raw))
                if any(row.get(c) is not None for c in
                       ("price_eur_m2", "price_eur_m3", "price_eur_kg")):
                    prices.append(row)
    return prices, supplements


def read_supplement(line, mode, manufacturer, family, pageno, url, wrapped):
    """One row of an accessory / coating / surcharge table, or None."""
    base = {"manufacturer": manufacturer, "family": family, "page": pageno,
            "source_url": url, "currency": "EUR"}
    if mode == "accessory":
        m = RE_ACCESSORY.match(line)
        if m:
            return {**base, "kind": "accessorio", "code": m["code"],
                    "description": m["desc"].strip() or wrapped,
                    "price_eur": to_num(m["price"]), "unit": m["unit"],
                    "availability": m["flag"], "min_qty": int(m["qty"])}
    elif mode == "coating":
        m = RE_COATING.match(line)
        if m:
            return {**base, "kind": "rivestimento", "code": m["code"],
                    "description": m["desc"].strip(), "price_eur": to_num(m["price"]),
                    "unit": "m2", "grammage_gm2": int(m["gsm"])}
    elif mode == "service":
        m = RE_SERVICE_PCT.match(line) or RE_SERVICE.match(line)
        if m:
            groups = m.groupdict()
            return {**base, "kind": "servizio", "code": groups["code"],
                    "description": groups["desc"].strip(),
                    "price_eur": to_num(groups.get("price")),
                    "unit": "m2" if groups.get("price") else None,
                    "uplift_pct": float(groups["pct"]) if groups.get("pct") else None}
    return None


# ---------------------------------------------------- Knauf Insulation parser ---

RE_K_ROW = re.compile(
    r"^(?P<code>\d{5,7})\s+(?P<ean>\d{13})\s+"
    r"(?P<dims>\d+\s*x\s*\d+\s*x\s*(?:\d+|\(\d+x\d+\)))\s+"
    r"(?P<mid>[\d.,\s]*?)\s*(?P<flag>[ABS])\s+(?P<tail>[\d,\s]+?)(?:\s+NEW)?$")
RE_K_LAMBDA = re.compile(r"^0,0\d{2,3}$")
RE_K_PAGE = re.compile(r"Pag\.\s*(\d+)\s*$")
RE_K_PACKAGING = re.compile(r"^[A-Z]+ SU PALLET$")
K_NOISE = {"NEW", "Listino prezzi edilizia"}
K_TITLE_SIZE = 15.0       # product names are the only 15 pt lines on a page
K_SECTION_SIZE = 24.0     # chapter / sub-chapter headings are 24 pt and 32 pt
# the listino prints some products bare, the catalogue (and the market) use the full name
K_PRODUCT_NAMES = {"TPT": "NaturBoard TPT"}


def _k_dim_m(dims: str, with_thickness: bool) -> tuple[float | None, str]:
    """'50 x 600 x 1200' (mm) -> (50.0, '1,20 x 0,60'): metres, length x width.

    A roll length may be printed '(2x8000)' - two rolls in the pack; it is kept
    as '(2x8,00) x 0,60'. The thickness is dropped from the text, as for URSA.
    """
    first, width, length = [t.strip() for t in re.split(r"\s*x\s*", dims, maxsplit=2)]

    def metres(mm: str) -> str:
        return f"{int(mm) / 1000:.2f}".replace(".", ",")

    multi = re.match(r"\((\d+)x(\d+)\)", length)
    length_txt = f"({multi.group(1)}x{metres(multi.group(2))})" if multi else metres(length)
    return (float(first) if with_thickness else None), f"{length_txt} x {metres(width)}"


def _k_lambda_for(thickness, resistance, candidates):
    """The block's λ closest to s/R - λ is a merged cell, printed once per block."""
    if not candidates:
        return None
    if thickness is None or not resistance:
        return candidates[0]
    return min(candidates, key=lambda lam: abs(thickness / 1000 / lam - resistance))


def parse_knauf(path: Path, manufacturer: str, family: str, url: str) -> tuple[list, list]:
    """Read the Knauf Insulation 'Listino prezzi edilizia' -> (price rows, [])."""
    today = date.today().isoformat()
    prices: list = []
    with pdfplumber.open(path) as pdf:
        cover = (pdf.pages[0].extract_text() or "").strip().split("\n")[0]
        m = RE_EDITION.match(cover.strip().capitalize())
        edition = f"{m.group(1)} {m.group(2)}" if m else cover
        edition_date = date(int(m.group(2)), MONTHS[m.group(1).lower()], 1) if m else None
        for sheet in pdf.pages[1:]:
            half_w = sheet.width / 2
            for left in (0.0, half_w):
                half = sheet.crop((left, 0, left + half_w, sheet.height))
                lines = [{"text": ln["text"].strip(),
                          "size": round(max(c["size"] for c in ln["chars"]), 1)}
                         for ln in half.extract_text_lines(return_chars=True)
                         if ln["chars"]]
                footer = next((RE_K_PAGE.search(ln["text"]) for ln in lines
                               if RE_K_PAGE.search(ln["text"])), None)
                printed_page = int(footer.group(1)) if footer else None
                block: list = []          # lines since the previous table closed
                rows: list = []
                lambdas: list = []
                product = section = last_product = packaging = None
                kg_table = False
                for ln in lines:
                    text = ln["text"]
                    if text.startswith("Pallet x camion") or text.startswith("Knauf Insulation |"):
                        _k_flush(prices, rows, lambdas)
                        rows, lambdas, product, block = [], [], None, []
                        if text.startswith("Knauf Insulation |"):
                            last_product = None
                        continue
                    if text.startswith("Codice Codice"):
                        titles = [b["text"] for b in block
                                  if b["size"] == K_TITLE_SIZE and b["text"] not in K_NOISE]
                        # a product printed with two tables (lastre / pacchi su
                        # pallet) names itself only above the first
                        product = (K_PRODUCT_NAMES.get(titles[-1], titles[-1])
                                   .replace("W ool", "Wool")
                                   if titles else last_product)
                        last_product = product
                        packaging = next((b["text"].capitalize() for b in reversed(block)
                                          if RE_K_PACKAGING.match(b["text"])), None)
                        macro = [b["text"] for b in block if b["size"] >= K_SECTION_SIZE]
                        section = macro[0] if macro else section
                        kg_table = False
                        continue
                    if product and "prodotto EAN" in text:
                        kg_table = "€/kg" in text
                        continue
                    if not product:
                        block.append(ln)
                        continue
                    if RE_K_LAMBDA.match(text):
                        lambdas.append(to_num(text))
                        continue
                    r = RE_K_ROW.match(text)
                    if r:
                        rows.append((r, kg_table, printed_page, section, product, packaging))
                _k_flush(prices, rows, lambdas)
    # the same SKU can appear in two application chapters (Supafil...): keep the
    # first, it is the same listino line
    seen: set = set()
    unique = []
    for row in prices:
        key = (row["product"], row["product_code"])
        if key in seen:
            continue
        seen.add(key)
        row.update(manufacturer=manufacturer, currency="EUR",
                   price_basis="listino, IVA esclusa", listino_edition=edition,
                   listino_date=edition_date, source_doc=path.name,
                   source_url=url, retrieved_on=today)
        row["family"] = row.pop("section") or family
        unique.append(row)
    return unique, []


def _k_flush(prices: list, rows: list, lambdas: list) -> None:
    """Turn the regex matches of one table into price rows."""
    # lambda is a merged cell: printed once per table, either alone or inside one row
    lambdas = lambdas + [to_num(t) for r, *_ in rows for t in r["tail"].split()
                         if RE_K_LAMBDA.match(t)]
    for r, kg_table, page, section, product, packaging in rows:
        tail = r["tail"].split()
        inline = [t for t in tail if RE_K_LAMBDA.match(t)]
        nums = [to_num(t) for t in tail if not RE_K_LAMBDA.match(t)]
        mid_tokens = r["mid"].split()
        mid = [to_num(t) for t in mid_tokens]
        thickness, dims = _k_dim_m(r["dims"], with_thickness=not kg_table)
        row = {"product": product, "product_code": r["code"], "thickness_mm": thickness,
               "dimensions_m": dims, "availability": r["flag"],
               "source_page": page, "packaging": packaging, "section": section}
        if kg_table:
            # "28 434 15,5": sacchi/pallet, kg/pallet, kg/sacco - then lambda, EUR/kg
            row.update(packs_per_pallet=mid[0], pallet_kg=mid[1], weight_kg=mid[2],
                       price_eur_kg=nums[-1],
                       lambda_declared_WmK=to_num(inline[0]) if inline else None)
        else:
            if len(mid) == 3:
                row.update(pack_m2=mid[0], packs_per_pallet=mid[1], pallet_m2=mid[2])
            elif len(mid) == 2 and "," not in mid_tokens[0]:
                row.update(packs_per_pallet=mid[0], pallet_m2=mid[1])
            elif len(mid) == 2:
                row.update(pack_m2=mid[0], pallet_m2=mid[1])
            elif len(mid) == 1:
                row.update(pallet_m2=mid[0])
            row.update(R_m2KW=nums[-2], price_eur_m2=nums[-1],
                       lambda_declared_WmK=(to_num(inline[0]) if inline else
                                            _k_lambda_for(thickness, nums[-2], lambdas)))
        prices.append(row)


# ------------------------------------------------------------ Ediltec parser ---
#
# Ediltec prints one table per product, always the same backbone:
#
#     spessore  n. lastre  pacchi      m2          m3       <- header 1
#     X-FOAM HBT                        €/m3 €/m2            <- title, with the units
#     mm        per pacco  per bancale per bancale bancale   <- header 2
#     Finitura: battentato  30 14 12 126,00 3,780 300,00 9,00 S
#
# The two header rows say what the numbers between the thickness and the S/O flag
# mean, and they vary by family (m² per pacco vs per bancale, €/m² alone vs €/m³
# and €/m², panels per pack vs per pallet). E_SHAPES maps that pair to the columns;
# a pair that is not in there is a layout change, and the table is reported and
# skipped rather than read into the wrong columns.
#
# The product's own description ("Finitura:", "Superficie:", "Dimensioni:") is
# printed as a left-hand sidebar, so pdfplumber hands those labels back glued to
# the front of whichever price row they happen to sit beside. Each table is
# therefore read twice: once for the sidebar, once for the rows.

E_SHAPES = {
    ("n. pannelli pacchi m2 m2", "per pacco per bancale per pacco bancale"):
        ["units_per_pack", "packs_per_pallet", "pack_m2", "pallet_m2"],
    ("n. pannelli pacchi m2 m3", "per pacco per bancale per pacco per pacco"):
        ["units_per_pack", "packs_per_pallet", "pack_m2", None],      # m³/pacco
    ("n. lastre pacchi m2 m3", "per pacco per bancale per bancale bancale"):
        ["units_per_pack", "packs_per_pallet", "pallet_m2", None],    # m³/bancale
    ("n. lastre pacchi m2 m3", "per pacco per bancale per pacco per pacco"):
        ["units_per_pack", "packs_per_pallet", "pack_m2", None],
    # GIBITEC ships whole pallets, so its panel count is per pallet, and it is
    # printed for two sheet lengths — the second m² column is the 1200x2000 pallet
    ("n. pannelli m2 per bancale m2 per bancale", "per bancale 1200x3000 1200x2000"):
        ["units_per_pack", "pallet_m2", None],
}

E_FLAGS = {"S", "O"}
RE_E_HEAD = re.compile(r"^(?:POLIISO|X-FOAM|GIBITEC)[A-Z0-9 \-]*$")
RE_E_H2_INLINE = re.compile(r"\bmm per (?:pacco|bancale)\b")
RE_E_SIDEBAR = re.compile(r"^(Finitura|Superficie|Dimensioni|Lunghezza|Passo|Profilo):"
                          r"\s*(.+)$")
RE_E_ROW_NAME = re.compile(r"^[A-Z][A-Z ]{3,}$")      # "PANNELLO PARTENZA" before a row
RE_E_THICK = re.compile(r"^\d+(?:\+\d+)?$")           # "100", or GIBITEC's "20+13"
# "600x1200 mm", and the tegola sidebar's "larghezza mm 630x2415"
RE_E_SIZE = re.compile(r"(\d{3,4})\s*x\s*(\d{3,4})")
RE_E_PASSO = re.compile(r"PASSO\s+(\d{3})")
RE_E_COVER = re.compile(r"^([A-Z]+)\s+(\d{4})\s+LISTINO PREZZI$")

RE_E_ACCESSORY = re.compile(r"^(?P<desc>.+?)\s+(?P<unit>pz\.|confezioni|da \d+ pz\.)?"
                            r"\s*(?P<price>\d{1,3},\d{2})$")
RE_E_ACC_NAME = re.compile(r"^[A-Z][A-Z0-9]+ ")       # an accessory names itself in caps
RE_E_UPLIFT = re.compile(r"^(?P<desc>Idro|BV|Classe A1\*?)\s+(?P<price>\d{1,2},\d{2})$")
RE_E_SERVICE = re.compile(r"^(?P<desc>.+?)\s+€\s*(?P<price>\d{1,3}(?:\.\d{3})*,\d{2})$")
RE_E_SERVICE_PCT = re.compile(r"^(?P<desc>.+?)\s+(?P<pct>\d{1,3})%\s+importo ordine$")


def _e_dimensions(sidebar: dict) -> tuple[str | None, float | None]:
    """(size, panel length m) from the sidebar: '600x1200 mm' -> '1,20 x 0,60'.

    A tegola panel has no size of its own — it is cut to the pitch of the tile —
    so those tables print only a length, and the width is worked back out of the
    packing figures (a doppio passo or ardesia panel spans two courses, not one).
    """
    size = RE_E_SIZE.search(sidebar.get("Dimensioni", ""))
    if size:
        a, b = sorted((int(size.group(1)), int(size.group(2))), reverse=True)
        return f"{a / 1000:.2f} x {b / 1000:.2f}".replace(".", ","), a / 1000
    length = re.search(r"(\d{3,4})\s*mm", sidebar.get("Lunghezza", ""))
    return None, int(length.group(1)) / 1000 if length else None


def _e_packaging(sidebar: dict) -> str | None:
    """The finish and the facing Ediltec prints beside the table, as one label."""
    parts = [sidebar[k] for k in ("Finitura", "Superficie") if sidebar.get(k)]
    if not parts:
        return None
    # a facing printed over two lines keeps only its first ("velovetro addizionato +")
    label = " · ".join(p.rstrip(" .+") for p in parts)
    return label[0].upper() + label[1:]


def _e_split_row(line: str, width: int):
    """('Finitura: bordi dritti', ['30', '28', ...]) for a price row, else None.

    *width* is how many numbers the table prints between the thickness and the
    flag, plus the thickness itself; anything in front is the sidebar bleeding in.
    """
    tokens = line.split()
    if len(tokens) < width + 1 or tokens[-1] not in E_FLAGS:
        return None
    cells = tokens[-1 - width:-1]
    if not RE_E_THICK.match(cells[0]) or not all(RE_NUM.match(c) for c in cells[1:]):
        return None
    return " ".join(tokens[:-1 - width]), cells + [tokens[-1]]


def _e_tables(lines: list[str]):
    """Yield (first line, title, price units, columns, body) for each table."""
    i = 0
    while i < len(lines):
        if not lines[i].startswith("spessore"):
            i += 1
            continue
        head1 = lines[i][len("spessore"):].strip()
        title_line = lines[i + 1] if i + 1 < len(lines) else ""
        if "€/" not in title_line:       # "POLIISO CURVO": prezzo su richiesta
            i += 1
            continue
        units = [f"price_eur_{u}" for u in re.findall(r"€/(m2|m3|kg)", title_line)]
        title = title_line[:title_line.index("€/")].strip()
        # one page prints the second header row glued to the title instead
        inline = RE_E_H2_INLINE.search(title)
        if inline:
            head2, title, skip = title[inline.start():], title[:inline.start()].strip(), 2
        else:
            head2, skip = lines[i + 2].strip(), 3
        shape = E_SHAPES.get((head1, head2[len("mm"):].strip()))
        if shape is None:
            print(f"!! Ediltec: unknown table layout for {title!r} "
                  f"({head1!r} / {head2!r}) - skipped")
            i += skip
            continue
        body, j = [], i + skip
        while j < len(lines) and not lines[j].startswith("spessore"):
            body.append(lines[j])
            j += 1
        yield i, title, units, shape, body
        i = j


def parse_ediltec(path: Path, manufacturer: str, family: str,
                  url: str) -> tuple[list, list]:
    """Read the Ediltec 'Listino prezzi' -> (price rows, supplement rows)."""
    today = date.today().isoformat()
    prices: list = []
    with pdfplumber.open(path) as pdf:
        cover = (pdf.pages[0].extract_text() or "").strip().split("\n")
        edition, edition_date = _e_edition(cover)
        heading = None
        for number, page in enumerate(pdf.pages, start=1):
            lines = [ln.strip() for ln in
                     (page.extract_text(x_tolerance=1.5) or "").split("\n") if ln.strip()]
            # a page can carry two products ("POLIISO TEGOLA DOPPIO PASSO" and
            # "... PASSO ARDESIA"), so the heading is read up to each table, not
            # once for the page
            read_to = 0
            for start, title, units, shape, body in _e_tables(lines):
                for line in lines[read_to:start]:
                    if RE_E_HEAD.match(line) and "€" not in line:
                        heading = line
                read_to = start
                width = 1 + len([c for c in shape]) + len(units)
                passo = None
                if title.upper().startswith("PACKING LIST"):
                    passo = int(RE_E_PASSO.search(title).group(1))
                    product = heading
                else:
                    product = heading = title
                sidebar: dict = {}
                for line in body:
                    split = _e_split_row(line, width)
                    label = RE_E_SIDEBAR.match(split[0] if split else line)
                    if label:
                        sidebar.setdefault(label.group(1), label.group(2).strip())
                dims, length = _e_dimensions(sidebar)
                packaging = _e_packaging(sidebar)
                variant = None
                for line in body:
                    split = _e_split_row(line, width)
                    if split is None:
                        continue
                    prefix, cells = split
                    if RE_E_ROW_NAME.match(prefix):   # "PANNELLO PARTENZA 60 21 ..."
                        variant = prefix
                    prices.append(_e_row(product, variant, cells, shape, units,
                                         dims, length, packaging, passo, number))
    for row in prices:
        row.update(manufacturer=manufacturer, currency="EUR",
                   price_basis="listino, IVA esclusa", listino_edition=edition,
                   listino_date=edition_date, source_doc=path.name,
                   source_url=url, retrieved_on=today)
        row["family"] = row["product"].split()[0] if row["product"] else family
    return prices, _e_supplements(path, manufacturer, url)


def _e_edition(cover: list[str]) -> tuple[str, date | None]:
    """'APRILE 2026 LISTINO PREZZI' -> ('Aprile 2026', 2026-04-01)."""
    for line in cover:
        m = RE_E_COVER.match(line.strip())
        if m and m.group(1).lower() in MONTHS:
            month = m.group(1).lower()
            return (f"{month.capitalize()} {m.group(2)}",
                    date(int(m.group(2)), MONTHS[month], 1))
    return "", None


def _e_row(product, variant, cells, shape, units, dims, length,
           packaging, passo, page) -> dict:
    """One price table line -> one priced SKU."""
    thickness = cells[0]
    if "+" in thickness:              # GIBITEC: insulation + its plasterboard skin
        core, board = (int(n) for n in thickness.split("+"))
        thickness = core + board
        packaging = f"{packaging} · {core}+{board} mm"
    row = {"product": f"{product} {variant}".strip() if variant else product,
           "product_code": None, "thickness_mm": float(thickness),
           "dimensions_m": dims, "packaging": packaging,
           "availability": cells[-1], "source_page": page}
    for name, value in zip(shape + units, cells[1:-1]):
        if name:                      # the m³ columns have nowhere to go
            row[name] = to_num(value)
    if passo:
        row["packaging"] = f"{row['packaging']} · passo {passo} mm"
        if dims is None and length and row.get("units_per_pack") and row.get("pack_m2"):
            width = row["pack_m2"] / (row["units_per_pack"] * length)
            row["dimensions_m"] = f"{length:.2f} x {width:.3f}".replace(".", ",")
    return row


def _e_supplements(path: Path, manufacturer: str, url: str) -> list:
    """Accessories, the GIBITEC board options and the service policy costs."""
    out: list = []

    def add(**kw):
        out.append({"manufacturer": manufacturer, "source_url": url,
                    "currency": "EUR", **kw})

    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            lines = [ln.strip() for ln in
                     (page.extract_text(x_tolerance=1.5) or "").split("\n") if ln.strip()]
            section, buffer = None, []
            for line in lines:
                if line in {"ACCESSORI", "SERVIZI AL CLIENTE & SERVICE POLICY"} \
                        or line.startswith("PER IL CARTONGESSO"):
                    section, buffer = line, []
                    continue
                if section == "ACCESSORI":
                    # the price sits on whichever line the description happens to
                    # end on, and the unit column ("rotoli da 10 m", "confezioni
                    # da 50 pz.") wraps under it, so an item is carried by the
                    # last line that opened with its name, in capitals
                    m = RE_E_ACCESSORY.match(line)
                    if not m:
                        if RE_E_ACC_NAME.match(line):
                            buffer = [line]
                        elif buffer:
                            buffer.append(line)
                        continue
                    desc = m.group("desc").strip()
                    if not RE_E_ACC_NAME.match(desc):      # "H 42 mm" -> its profile
                        desc = " ".join(buffer + [desc]).strip()
                    add(family="POLIISO TEGOLA", page=number, kind="accessorio",
                        code=None, description=desc,
                        price_eur=to_num(m.group("price")),
                        unit="pezzo" if "pz." in line else "confezione")
                    buffer = buffer[:1]
                elif section and section.startswith("PER IL CARTONGESSO"):
                    m = RE_E_UPLIFT.match(line)
                    if m:
                        add(family="GIBITEC", page=number, kind="rivestimento",
                            code=m.group("desc").rstrip("*"),
                            description=f"Lastra di cartongesso {m.group('desc')}",
                            price_eur=to_num(m.group("price")), unit="m2")
                elif section == "SERVIZI AL CLIENTE & SERVICE POLICY":
                    m = RE_E_SERVICE.match(line)
                    if m:
                        add(family=None, page=number, kind="servizio", code=None,
                            description=m.group("desc").strip(),
                            price_eur=to_num(m.group("price")), unit="consegna")
                        continue
                    m = RE_E_SERVICE_PCT.match(line)
                    if m:
                        add(family=None, page=number, kind="servizio", code=None,
                            description=m.group("desc").strip(), price_eur=None,
                            unit="ordine", uplift_pct=float(m.group("pct")))
    return out

# -------------------------------------------------------- POLIISO AIR parser ---
#
# POLIISO AIR is Ediltec's pre-insulated ductwork system, sold off its own site
# and absent from the building listino; its catalogue doubles as the price list.
# Every product is a block of bilingual "label value" lines:
#
#     POLIISO AIR INDOOR GG080
#     Codice / Code                 10024
#     Prezzo / Price (€/m²)         31,00
#     Dimensioni / Size (mm)        4000 x 1200
#     Spessore / Thickness (mm)     20,5
#     Confezione / Pack             10 pannelli / 10 panels
#
# An accessory block is the same shape under a "ITALIANO | ENGLISH" heading, and
# carries one or two variants side by side (a 20 and a 30 mm flange joint), which
# the "Codice / Code" line counts. Those go out as supplements, one per variant.
#
# The facing is printed over two or three lines in an order that varies, so the
# aluminium thickness ("80/200") stands in for it as the packaging label — the
# product name already says which face is which (GG = both embossed, GL = one
# smooth, and 080/200/400 the micron pair).

POLIISO_AIR_SOURCE = (
    "poliiso_air", "EDILTEC", "POLIISO AIR",
    "https://www.poliisoairducts.com/upload/download/file/"
    "Catalisto%20PoliisoAIR-zjK5.pdf")

RE_PA_PANEL = re.compile(r"^POLIISO AIR (?:INDOOR|OUTDOOR|CARE) [A-Z0-9]+$")
RE_PA_ACCESSORY = re.compile(r"^(?P<it>[^|]{4,}?)\s*\|\s*.+$")
# "Spessore Alu. / Alu. Thickness (μm) 40 50 50 50": the English half of the label
# runs to wherever the first cell starts, and a cell is a number, a product code
# or the on-demand marker — matching the label lazily up to one of those is the
# only way to keep "Code AC013" from reading as a label of its own
RE_PA_FIELD = re.compile(r"^(?P<label>[A-Za-zÀ-ü.]+(?: [A-Za-zÀ-ü.]+)*?)\s*/\s*.*?"
                         r"(?<![\w,.])(?P<value>(?:\d|AC\d|SU_RICHIESTA).*)$")
RE_PA_ONDEMAND = re.compile(r"su richiesta\s*/\s*on demand", re.I)
RE_PA_NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^\d+(?:,\d+)?$")
RE_PA_MONTH = re.compile(r"^(" + "|".join(MONTHS).upper() + r")\s+(\d{4})$")


def _pa_values(value: str) -> list[str]:
    """The cells of a bilingual field line, with 'su richiesta' kept as one."""
    return RE_PA_ONDEMAND.sub("SU_RICHIESTA", value).split()


def _pa_num(token) -> float | None:
    """Italian decimal -> float, four figures and up included (2405,00)."""
    return to_num(token) if to_num(token) is not None else (
        float(str(token).replace(".", "").replace(",", "."))
        if RE_PA_NUM.match(str(token)) else None)


def _pa_blocks(lines: list[str]):
    """Yield (kind, title, [{label: [cell, ...]}, ...]) for a page's products.

    A block is one product; each "Codice / Code" line opens a group of variants
    printed side by side, and a block can hold more than one (the aluminium
    fitting lists eight diameters as two rows of four).
    """
    kind = title = None
    groups: list = []

    def start(new_kind, new_title):
        nonlocal kind, title, groups
        out = (kind, title, groups) if title else None
        kind, title, groups = new_kind, new_title, []
        return out

    for raw in lines:
        line = RE_PA_ONDEMAND.sub("SU_RICHIESTA", raw)
        if RE_PA_PANEL.match(line):
            done = start("panel", line)
            if done:
                yield done
            continue
        accessory = RE_PA_ACCESSORY.match(line)
        # an accessory heading is set in capitals; the bulleted bilingual lists
        # earlier in the catalogue ("a. Edifici civili | Residential") are not
        if accessory and accessory.group("it").strip().isupper():
            done = start("accessory", accessory.group("it").strip())
            if done:
                yield done
            continue
        field = RE_PA_FIELD.match(line)
        if field and title:
            label, cells = field.group("label"), field.group("value").split()
            if label == "Codice":
                groups.append({})
            if groups:
                groups[-1].setdefault(label, cells)
    if title:
        yield kind, title, groups


def parse_poliiso_air(path: Path, manufacturer: str, family: str,
                      url: str) -> tuple[list, list]:
    """Read the POLIISO AIR catalogue -> (panel price rows, accessory rows)."""
    today = date.today().isoformat()
    prices: list = []
    supplements: list = []
    with pdfplumber.open(path) as pdf:
        cover = (pdf.pages[0].extract_text() or "").split("\n")
        edition, edition_date = "", None
        for line in cover:
            m = RE_PA_MONTH.match(line.strip())
            if m:
                edition = f"{m.group(1).capitalize()} {m.group(2)}"
                edition_date = date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
        for number, page in enumerate(pdf.pages, start=1):
            lines = [ln.strip() for ln in
                     (page.extract_text(x_tolerance=1.5) or "").split("\n") if ln.strip()]
            for kind, title, groups in _pa_blocks(lines):
                for fields in groups:
                    if not fields.get("Codice") or not fields.get("Prezzo"):
                        continue
                    if kind == "panel":
                        panel = _pa_panel(title, fields, number)
                        # three facings are quoted on request; a row with no
                        # price has no place in the priced-SKU table
                        if panel["price_eur_m2"] is not None:
                            prices.append(panel)
                    else:
                        supplements += _pa_accessory(title, fields, number)
    for row in prices:
        row.update(manufacturer=manufacturer, family=family, currency="EUR",
                   price_basis="listino, IVA esclusa", listino_edition=edition,
                   listino_date=edition_date, source_doc=path.name,
                   source_url=url, retrieved_on=today)
    for row in supplements:
        row.update(manufacturer=manufacturer, family=family, currency="EUR",
                   source_url=url)
    return prices, supplements


def _pa_panel(title, fields, page) -> dict:
    """One panel block -> one priced SKU."""
    size = fields.get("Dimensioni", [])
    dims = None
    if len(size) == 3:                       # "4000 x 1200"
        a, b = sorted((int(size[0]), int(size[2])), reverse=True)
        dims = f"{a / 1000:.2f} x {b / 1000:.2f}".replace(".", ",")
    micron = "/".join(fields.get("Spessore Alluminio", []))
    pack = fields.get("Confezione", [])
    price = fields["Prezzo"][0]
    return {"product": title, "product_code": fields["Codice"][0],
            "thickness_mm": _pa_num(fields.get("Spessore", [None])[0]),
            "dimensions_m": dims,
            "price_eur_m2": _pa_num(price),
            "units_per_pack": _pa_num(pack[0]) if pack else None,
            "packaging": f"Alluminio {micron} µm" if micron else None,
            "source_page": page}


def _pa_accessory(title, fields, page) -> list:
    """One variant group -> a supplement row each, named by what sets them apart.

    Variants of one accessory differ in a height, a diameter or a length, and
    which it is varies by accessory — so the label is taken from the first field
    whose cells actually differ, and falls back to the code when none does.
    """
    codes, money = fields["Codice"], fields["Prezzo"]
    telling = next((label for label, cells in fields.items()
                    if label not in {"Codice", "Prezzo"}
                    and len(cells) == len(codes) and len(set(cells)) > 1), None)
    rows = []
    for i, code in enumerate(codes):
        price = money[i] if i < len(money) else None
        if len(codes) == 1:
            label = title
        elif telling:
            label = f"{title} ({telling.lower()} {fields[telling][i]})"
        else:
            label = f"{title} ({code})"
        rows.append({"page": page, "kind": "accessorio", "code": code,
                     "description": label, "price_eur": _pa_num(price),
                     "unit": "pezzo",
                     "availability": "R" if price == "SU_RICHIESTA" else None})
    return rows

# ------------------------------------------------- GAIVI (Iris, reseller) ---
#
# GAIVI is a Treviso building-materials cooperative that publishes a public
# price list per brand, Iris Ceramiche among them, as two PDFs carrying the same
# 285 articles: a plain one and a "figurato" one with a photo per article. Both
# print one line per article,
#
#     202346 ARCOBALENO AZZURRO 20X20 GRESS PORC. 713609 713609 € 20,13
#     \_ GAIVI code                   \_ size     \_ Iris code    \_ price
#
# under a section heading (PAVIMENTI, RIVESTIMENTI, DECORI) and with a web link
# per line, which becomes the row's ``source_url``. The figurato prints the Iris
# code again in a caption under the photo; it is read only to check that the two
# files agree, because GAIVI regenerates both together and a divergence means
# one of the cached copies is stale.
#
# Neither PDF prints the unit, and the range mixes tiles sold by the square
# metre with pezzi speciali (battiscopa, listelli, tozzetti, rosoni) sold by the
# piece. The piece is read off the description - every article in DECORI plus
# any whose name carries a special-piece word - and those rows go out as
# supplements, where a per-piece price has a column. The rule was audited
# against the ``Unita`` field of all 285 article pages on gaivi.it (see the
# module docstring).
#
# The prices are retail, IVA included at a rate the listino does not state;
# GAIVI's ordinary rate is 22% (4% and 10% are a service it applies on request),
# so 22% is what is taken out, and ``price_basis`` says so.
#
# Only one catalogue family can be named from this listino without guessing: the
# wall tiles of RIVESTIMENTI are the "Ceramics for internal wall coverings" EPD.
# The floor tiles are porcelain stoneware, which the catalogue splits by
# thickness (6, 6-8, 8-9, 9-20 mm) - and no thickness is printed anywhere in the
# listino or on the article pages, so they keep their commercial names and stay
# unmatched rather than be assigned a thickness they may not have.

GAIVI_IRIS_SOURCE = ("gaivi_iris", "Iris Ceramica Group", "Iris Ceramiche",
                     "https://listini.gaivi.it/pdf/iris-ceramiche-spa/")
GAIVI_FOTO_SLUG = "gaivi_iris_foto"
GAIVI_VAT = 1.22
GAIVI_BASIS = ("prezzo al pubblico rivenditore GAIVI (non listino del produttore), "
               "IVA 22% scorporata")
GAIVI_WALL_PRODUCT = "Ceramics for internal wall coverings"

RE_GV_ROW = re.compile(r"^(?P<code>\d{6})\s+(?P<desc>.+?)\s+€\s*(?P<price>[\d.]*\d,\d{2})$")
RE_GV_CAPTION = re.compile(r"^IRIS CERAMICHE SPA\s+-\s+(?P<code>.+?)\s+-\s+\d+$")
RE_GV_SKIP = re.compile(r"^(IRIS CERAMICHE SPA|LISTINO PREZZI|pagina \d+|"
                        r"Prezzi al pubblico|COOPERATIVA)")
RE_GV_UPDATED = re.compile(r"Prezzi aggiornati al (\d{2})/(\d{2})/(\d{4})")
RE_GV_ITEM_CODE = re.compile(r"^[A-Z]{0,2}\d{5,6}$")
RE_GV_URL_CODE = re.compile(r"-(\d{6})\.html$")
RE_GV_SIZE = re.compile(r"\b(?P<a>\d{1,3}(?:,\d)?)\s*[Xx]\s*(?P<b>\d{1,3}(?:,\d)?)\b")
# a pezzo speciale: a trim, a border or a single decorated tile, sold one at a time
RE_GV_PIECE = re.compile(
    r"\b(LISTELLO|LIST|LISTONE|TOZZETTO|BATTISCOPA|MATITA|BOMBATO|TORELLO|INSERTO|INS|"
    r"ROSONE|FASCIA|CAPITELLO|ZOCCOLO|SINGOLO|SING|PALIOTTO|GRECA|ANGOLO|SCALINO|"
    r"BORDO|COPRIBORDO|BOISSERIE|RILIEVO|BASSORILIEVO|FIORE|FIORI|FRUTTI|INTAR|MOSAICO|"
    r"RETTANGOLI|FLOREALE|METALLO|METALLLO|BOTTONE|GENERICO|TOP)\b")

# The five articles GAIVI sells against the rule above: a 10x10 floor tozzetto
# and a 20x25 floor tile sold by the piece, and two jolly trims and a listello
# sold by the square metre. Taken from the ``Unita`` field of their article
# pages, which is where the rule itself was audited; anything new GAIVI adds is
# read by the rule until it is checked the same way.
GAIVI_UNITS = {"202683": "pezzo",   # FMG ROSA PORTOGALLO 10X10 ANTICATO
               "202738": "pezzo",   # RINNOVA HOME WHITE MODERN 20X25
               "202497": "m2",      # ARCOBALENO JOLLY BIANCO
               "202498": "m2",      # ARCOBALENO JOLLY BLU
               "220491": "m2"}      # ENERGY 761135 8X20 LISTELLO ROMANTICA 2
# the quotation placeholder GAIVI keeps in every brand list: no product behind it
RE_GV_PLACEHOLDER = re.compile(r"^ARTICOLO GENERICO")


def parse_gaivi(path: Path, manufacturer: str, family: str, url: str,
                check: Path | None = None) -> tuple[list, list]:
    """Read a GAIVI brand listino -> (tiles priced by m2, pezzi speciali)."""
    today = date.today().isoformat()
    rows = _gv_rows(path)
    if check is not None and check.exists():
        _gv_cross_check(rows, _gv_rows(check), check.name)
    edition, edition_date = _gv_edition(path)
    prices, supplements = [], []
    for row in rows:
        if RE_GV_PLACEHOLDER.match(row["name"]):
            continue
        net = round(row["price"] / GAIVI_VAT, 2)
        if row["piece"]:
            supplements.append(
                {"manufacturer": manufacturer, "family": family,
                 "page": row["page"], "source_url": row["url"] or url,
                 "currency": "EUR", "kind": "pezzo speciale", "code": row["item_code"],
                 "description": f"{row['name']} ({row['section'].capitalize()})",
                 "price_eur": net, "unit": "pezzo", "availability": None})
            continue
        wall = row["section"] == "RIVESTIMENTI"
        prices.append(
            {"manufacturer": manufacturer, "family": family,
             "product": GAIVI_WALL_PRODUCT if wall else row["name"],
             # only where the product is the catalogue's family and the article
             # name would otherwise be lost; it is the product itself elsewhere
             "article": row["name"] if wall else None,
             "product_code": row["item_code"],
             "dimensions_m": row["dimensions_m"], "price_eur_m2": net,
             "currency": "EUR", "price_basis": GAIVI_BASIS,
             "listino_edition": edition, "listino_date": edition_date,
             "source_doc": path.name, "source_page": row["page"],
             "source_url": row["url"] or url, "retrieved_on": today})
    return prices, supplements


def _gv_rows(path: Path) -> list[dict]:
    """Every article line of a GAIVI listino, with its section and web link."""
    out: list[dict] = []
    section = ""
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            links = {m.group(1): h["uri"] for h in page.hyperlinks
                     if (m := RE_GV_URL_CODE.search(h["uri"]))}
            lines = [ln.strip() for ln in
                     (page.extract_text(x_tolerance=1.5) or "").split("\n") if ln.strip()]
            for line in lines:
                row = RE_GV_ROW.match(line)
                if row:
                    out.append(_gv_row(row, section, links, number))
                elif (line.isupper() and ">" not in line
                        and not RE_GV_SKIP.match(line)
                        and not RE_GV_CAPTION.match(line)):
                    section = line            # a heading holds until the next one
    return out


def _gv_row(match: re.Match, section: str, links: dict, page: int) -> dict:
    """One article line -> its code, name, size and price."""
    tokens = match["desc"].split()
    # the Iris code is printed at the end of the line, once or twice, and for a
    # handful of articles only inside the description
    item_code = (tokens[-1] if RE_GV_ITEM_CODE.match(tokens[-1])
                 else next((t for t in tokens if RE_GV_ITEM_CODE.match(t)), None))
    while tokens and RE_GV_ITEM_CODE.match(tokens[-1]):
        tokens.pop()
    name = " ".join(tokens)
    return {"page": page, "section": section, "code": match["code"],
            "item_code": item_code, "name": name,
            "price": to_num(match["price"]),
            "dimensions_m": _gv_size(RE_GV_SIZE.search(name)),
            # the section is the surer signal: DECORI is pezzi speciali throughout,
            # including the few whose name says nothing (LIFE BIANCO STAR GIALLO)
            "piece": (GAIVI_UNITS[match["code"]] == "pezzo"
                      if match["code"] in GAIVI_UNITS
                      else section == "DECORI"
                      or bool(RE_GV_PIECE.search(match["desc"].replace(".", " ")))),
            "url": links.get(match["code"])}


def _gv_size(match: re.Match | None) -> str | None:
    """'33,3X33,3' -> '0,33 x 0,33' - the listino prints tile sizes in cm."""
    if not match:
        return None
    a, b = (to_num(match[k]) / 100 for k in ("a", "b"))
    return f"{max(a, b):.2f} x {min(a, b):.2f}".replace(".", ",")


def _gv_edition(path: Path) -> tuple[str, date | None]:
    """The footer's 'Prezzi aggiornati al 25/10/2026'."""
    with pdfplumber.open(path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    stamp = RE_GV_UPDATED.search(text)
    if not stamp:
        return ("GAIVI", None)
    day, month, year = (int(n) for n in stamp.groups())
    return (f"GAIVI, prezzi aggiornati al {day:02d}/{month:02d}/{year}",
            date(year, month, day))


def _gv_cross_check(rows: list[dict], other: list[dict], name: str) -> None:
    """Report any article the two editions of one listino disagree on."""
    mine = {r["code"]: r for r in rows}
    theirs = {r["code"]: r for r in other}
    missing = sorted(set(mine) ^ set(theirs))
    differing = sorted(code for code in set(mine) & set(theirs)
                       if mine[code]["price"] != theirs[code]["price"])
    if missing or differing:
        print(f"!! {name} disagrees with the plain listino: {len(missing)} articles "
              f"only in one, {len(differing)} priced differently "
              f"{(missing + differing)[:5]} - re-download both")
    else:
        print(f"   {name}: the same {len(other)} articles at the same prices")


# ----------------------------------------------------- ATA Torino (reseller) ---
#
# ATA's shop runs WooCommerce; its public Store API returns every product of a
# brand category as JSON (name, SKU, permalink, current and regular price), so
# no HTML is scraped. One category per manufacturer, read 100 products a page.

ATA_API = "https://www.ata.to.it/wp-json/wc/store/v1/products"
ATA_VAT = 1.22     # ATA's shop prices include IVA (its Condizioni Generali di Vendita)
ATA_BASIS = ("prezzo web rivenditore ATA Torino (non listino del produttore), "
             "in offerta, IVA 22% scorporata")

# The shop's product name, shorn of brand and product type, -> the catalogue's name.
# A dict value picks the name by thickness (mm, after the 13 -> 12,5 board rule).
# A product absent here keeps the shop's name: still priced, just not matched.
ATA_NAMES_SINIAT = {
    "Solidtex Indoor": "Solidtex Indoor BA13",
    "AquaBoard": "Aquaboard BA13",
    "PregyFlam A1 BA15": "Pregyflam BA15",
}
ATA_NAMES_GYPROC = {
    "4PRO": "4Pro",
    "X-RAY Protection": "X-Ray Protection - 13",
    "Glasroc X": "Glasroc X 13",
    "LISAFLAM 13": "Lisaflam 13",
    "Fireline 13": "Fireline 13",
    "Fireline 15": "Fireline 15",
    "LISAPLAC": {12.5: "Lisaplac 13", 15.0: "Lisaplac 15"},
    "Habito Forte": "Habito Forte 13",
    "DuraGyp Activ'Air": "DuraGyp 13 Activ'Air",
    "HYDRO 13": "Hydro 13",
    "WALLBOARD FLY": "Wallboard FLY",
    "WALLBOARD 10": "Wallboard 10",
    "VAPOR 13": "Vapor 13",
    "FLEX 6": "Flex 6",
    "SMART Easy2 Activ'Air": "Easy2 13 Activ'Air",
}
ATA_NAMES_ISOVER = {
    "PAR 4+": "PAR 4+",
    "IBR N 4+": "IBR N 4+ | senza riv.",
    "IBR K 4+": "IBR K 4+ | con riv.",
    "ARENA31": "Arena31",
    "ARENA32": "Arena32",
    "ARENA34": "Arena34",
}
ATA_NAMES_FASSA = {
    "STD BA13": "Gypsotech STD TIPO A - 13",
    "STD BA10": "Gypsotech STD TIPO A - 10",
    "STD BA6": "Gypsotech STD TIPO A - 6",
    "STD ZERO": "Gypsotech STD ZERO TIPO A - 13",
    "FOCUS BA13": "Gypsotech FOCUS TIPO DFI- 13",
    "FOCUS BA15": "Gypsotech FOCUS TIPO DFI- 15",
    "LIGNUM": "Gypsotech GYPSOLIGNUM TIPO DEFH1IR - 13",
    "AQUA": "Gypsotech AQUA TIPO EH2 - 13",
    "EXTERNA LIGHT": "Gypsotech EXTERNA LIGHT - 13",
    "FOCUS ULTRA": "Gypsotech FOCUS TIPO DFI - 25",
}
ATA_NAMES_KNAUF = {
    # the shop used to encode the board and its sheet size in one token
    # ("GKB1330" = GKB, 13 mm, 3,00 m); since October 2026 it names the board and
    # prints the size after it, so the thickness tells the variants apart
    "GKB": {9.5: "Lastra GKB (A) - 9.5", 12.5: "Lastra GKB (A) - 12.5",
            15.0: "Lastra GKB (A) - 15"},
    "GKI": "Idrolastra GKI",
    "GKF": {12.5: "Lastra GKF - 12.5", 15.0: "Lastra GKF - 15"},
    "F-Zero": {12.5: "Lastra F-ZERO - 12.5", 15.0: "Lastra F-ZERO - 15"},
    "A-Zero": "Lastra A-ZERO",
    "Diamant HF": "Lastra DIAMANT",
    "Advanced": "Lastra GKB Advanced",
    "AQUAPANEL Outdoor": "Aquapanel Outdoor 12,5 mm",
}
ATA_NAMES_SUPERCEL = {"Vitrum": "VITRUM"}
ATA_NAMES_PROMAT = {"PROMATECT-H": "PROMATECT-H"}
ATA_NAMES_GLOBAL = {"Fireguard 13": "Lastra Fireguard 13"}

# (ATA category id, catalogue manufacturer, brand words the shop prefixes, names)
ATA_SOURCES = [
    (126, "Siniat", "Siniat", ATA_NAMES_SINIAT),
    (101, "Gyproc", "Gyproc", ATA_NAMES_GYPROC),
    (112, "Isover (Saint Gobain)", "Isover", ATA_NAMES_ISOVER),
    (111, "Fassa Bortolo", "Fassa", ATA_NAMES_FASSA),
    (102, "Knauf", "Knauf", ATA_NAMES_KNAUF),
    (286, "SUPERCEL", "Resine Isolanti Supercel|Supercel", ATA_NAMES_SUPERCEL),
    (116, "Promat", "Promat", ATA_NAMES_PROMAT),
    (114, "Global Building", "Global Building", ATA_NAMES_GLOBAL),
]

# The first word after the commercial name says what the item is. Since the
# October 2026 rewrite the shop also writes it lower case and sometimes puts it
# first ("Global Building lastra Fireguard 13"), so the match is case-insensitive
# and a leading type word is stripped before the name is read off.
_ATA_TYPES = (r"Lastra|Ignilastra|Idrolastra|Isolante|Pannello|Stucco|Rasante|Malta|"
              r"Intonaco|Vite|Sigillante|Silicone|Membrana|Rete|Schiuma|Profilo|"
              r"Raccordo|Collare|Cassetta|Mattone|Cuscino|Manicotto|Pittura|Nastro|"
              r"Griglia|Giunto|Sacchetto|Listello|Pistola|"
              # a title can name the material instead of the format
              # ("Isover PAR 4+ Lana di vetro 95 mm")
              r"Lana(?:\s+(?:di\s+vetro|di\s+roccia|minerale))?")
RE_ATA_TYPE = re.compile(rf"\s+(?P<type>{_ATA_TYPES})\b", re.I)
RE_ATA_LEAD_TYPE = re.compile(rf"^(?:{_ATA_TYPES})\s+", re.I)
RE_ATA_DIMS = re.compile(r"(?P<w>\d{3,4})\s*[×x]\s*(?P<l>\d{3,5})(?:\s*[×x]\s*"
                         r"(?P<t>\d+(?:,\d+)?))?\s*mm")
RE_ATA_INS_T = re.compile(r"Isolante\s+(?P<t>\d+(?:,\d+)?)\s*mm")
RE_ATA_AREA = re.compile(r"(?P<a>\d+(?:,\d+)?)\s*m²\s*/\s*(?:rotolo|conf\.?|lastra)"
                         r"|rotolo\s+(?P<b>\d+(?:,\d+)?)\s*m²")
RE_ATA_KG = re.compile(r"(?P<kg>\d+(?:,\d+)?)\s*kg\b")
# ATA shortened its product titles in October 2026: the pack size that used to be
# printed in the name ("2 rot. da 0,60 x 7,50 - 9 mq/conf") now sits only in the
# short description, which words it half a dozen ways
RE_ATA_PACK_SD = re.compile(
    r"superficie totale(?:\s+per\s+confezione)?:?\s*(?P<a>\d+(?:,\d+)?)\s*m[²q]"
    r"|(?:confezione|pacco|conf\.)\s+da\s*(?P<b>\d+(?:,\d+)?)\s*m[²q]"
    r"|(?P<c>\d+(?:,\d+)?)\s*m[²q]\s*/\s*(?:rot|conf)", re.I)
# "Spessore 95 mm, dimensioni 600 × 1450 mm" — likewise moved to the description
RE_ATA_THICK_SD = re.compile(r"spessore\s+(?P<t>\d+(?:,\d+)?)\s*mm", re.I)
RE_ATA_DIMS_SD = re.compile(r"dimensioni\s+(?P<w>\d{3,4})\s*[×x]\s*(?P<l>\d{3,5})\s*mm",
                            re.I)
# a few descriptions give the board in centimetres ("Lastra 120x200x1,25cm")
RE_ATA_DIMS_CM = re.compile(r"(?P<w>\d{2,3})\s*[×x]\s*(?P<l>\d{2,3})\s*[×x]\s*"
                            r"(?P<t>\d+(?:,\d+)?)\s*cm", re.I)
# the thickness a shortened title ends on ("ISOVER PAR 4+ Lana di vetro 95 mm")
RE_ATA_TAIL_T = re.compile(r"(?P<t>\d+(?:,\d+)?)\s*mm\s*\)?\s*$")
SHEET_TYPES = {"Lastra", "Ignilastra", "Idrolastra"}


def fetch_ata_category(cid: int, refresh: bool) -> list:
    """Every product of one ATA category, cached as JSON under .cache/pricelists/ata_api/."""
    folder = CACHE_DIR / "ata_api"
    path = folder / f"cat_{cid}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    products, page = [], 1
    while page <= 10:
        response = requests.get(ATA_API, timeout=60,
                                params={"category": cid, "per_page": 100, "page": page},
                                headers={"User-Agent": "EETRA-MatLib price check"})
        response.raise_for_status()
        batch = response.json()
        products += batch
        time.sleep(1.0)                           # one request a second, no more
        if len(batch) < 100:
            break
        page += 1
    path.write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
    return products


def _ata_catalogue_name(names: dict, short: str, thickness):
    """The catalogue's name for a shop item, or the shop's own when unmapped.

    Matched without regard to case: the shop re-cased half its range in October
    2026 ("ARENA31" -> "Arena31") without changing what the products are.
    """
    folded = {k.casefold(): v for k, v in names.items()}
    hit = folded.get(short.casefold())
    if isinstance(hit, dict):
        return hit.get(thickness, short)
    return hit or short


def parse_ata_product(item: dict, manufacturer: str, brand: str, names: dict,
                      today: date) -> dict | None:
    """One shop product -> a price row in EUR/m2 (boards, insulation) or EUR/kg (sacks).

    Items sold per piece (screws, collars, sealant cartridges) return None: the
    catalogue holds none of them and there is no per-piece price column.
    """
    text = re.sub(r"\s+", " ", html.unescape(item["name"])).replace("’", "'").strip()
    body = re.sub(rf"^(?:{brand})\s+", "", text, flags=re.I)
    lead = RE_ATA_LEAD_TYPE.match(body)      # "lastra Fireguard 13": type first
    if lead:
        body = body[lead.end():]
    kind = RE_ATA_TYPE.search(body)
    short = body[:kind.start()].strip() if kind else body
    item_type = (kind["type"] if kind else
                 lead.group(0).strip() if lead else None)
    prices = item["prices"]
    shown = int(prices["price"]) / 10 ** int(prices["currency_minor_unit"])
    if not shown:
        return None
    net = shown / ATA_VAT
    category = next((c["name"] for c in item.get("categories", [])
                     if "ata-torino" not in c["slug"] and "produttori" not in c["slug"]),
                    manufacturer)
    row = {"manufacturer": manufacturer, "family": category, "packaging": None,
           "product_code": item.get("sku") or None, "availability": None,
           "currency": "EUR", "price_basis": ATA_BASIS,
           "listino_edition": f"ATA Torino, rilevato {today:%d/%m/%Y}",
           "listino_date": today, "source_doc": f"ata_api/cat",
           "source_page": None, "source_url": item.get("permalink"),
           "retrieved_on": today.isoformat()}
    dims, area = RE_ATA_DIMS.search(body), RE_ATA_AREA.search(body)
    ins_t = RE_ATA_INS_T.search(body)
    kg = RE_ATA_KG.search(body)
    named_dims = dims is not None
    is_sheet = bool(item_type and item_type.capitalize() in SHEET_TYPES)
    # the shortened titles leave the pack size, the thickness and the panel size
    # to the short description, so it stands in wherever the name says nothing
    blurb = re.sub(r"\s+", " ",
                   html.unescape(re.sub(r"<[^>]+>", " ",
                                        item.get("short_description") or "")))
    thickness = None
    if ins_t:
        thickness = to_num(ins_t["t"])
    elif dims and dims["t"]:
        thickness = to_num(dims["t"])
    elif not dims:
        tail = RE_ATA_TAIL_T.search(body) or RE_ATA_THICK_SD.search(blurb)
        thickness = to_num(tail["t"]) if tail else None
    if not named_dims:
        dims = (RE_ATA_DIMS_SD.search(blurb) or RE_ATA_DIMS.search(blurb)
                or RE_ATA_DIMS_CM.search(blurb))
        if dims and dims.re is RE_ATA_DIMS_CM:
            dims = {"w": int(dims["w"]) * 10, "l": int(dims["l"]) * 10,
                    "t": to_num(dims["t"]) * 10}
            thickness = dims["t"]
        elif dims and dims.groupdict().get("t"):
            thickness = to_num(dims["t"])
    # a "13 mm" plasterboard is the 12,5 mm one (BA13): the shop rounds it
    if is_sheet and thickness == 13.0:
        thickness = 12.5
    if not area:
        area = RE_ATA_PACK_SD.search(blurb)
    if area:
        m2 = to_num(area["a"] or area["b"] or area.groupdict().get("c"))
    elif is_sheet and dims:
        m2 = int(dims["w"]) * int(dims["l"]) / 1e6
    else:
        m2 = None
    if m2:
        row["price_eur_m2"] = round(net / m2, 2)
        row["pack_m2"] = round(m2, 2) if area else None
    elif kg and not named_dims:
        row.update(weight_kg=to_num(kg["kg"]), price_eur_kg=round(net / to_num(kg["kg"]), 2))
    else:
        return None
    if dims:
        length, width = int(dims["l"]), int(dims["w"])
        row["dimensions_m"] = f"{length / 1000:.2f} x {width / 1000:.2f}".replace(".", ",")
    row["thickness_mm"] = thickness
    row["product"] = _ata_catalogue_name(names, short, thickness)
    return row


def parse_ata(refresh: bool) -> list:
    """All ATA brand categories in ``ATA_SOURCES`` -> price rows."""
    today = date.today()
    rows = []
    for cid, manufacturer, brand, names in ATA_SOURCES:
        items = fetch_ata_category(cid, refresh)
        parsed = [r for r in (parse_ata_product(i, manufacturer, brand, names, today)
                              for i in items) if r]
        for r in parsed:
            r["source_doc"] = f"ata_api/cat_{cid}.json"
        mapped = sum(1 for r in parsed if r["product"] in _ata_mapped_names(names))
        print(f"{manufacturer[:18]:18s} {len(parsed):4d} SKU  ({mapped} matched to the "
              f"catalogue, of {len(items)} shop items)  [ATA]")
        rows += parsed
    return rows


def _ata_mapped_names(names: dict) -> set:
    out = set()
    for v in names.values():
        out |= set(v.values()) if isinstance(v, dict) else {v}
    return out


# ---------------------------------------------------------------- driver ----

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-fetch", action="store_true",
                    help="use the PDFs already cached under .cache/pricelists")
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    args = ap.parse_args()

    all_prices, all_supplements = [], []
    for slug, manufacturer, family, url in SOURCES:
        path = fetch(slug, url, refresh=not args.no_fetch)
        prices, supplements = parse_listino(path, manufacturer, family, url)
        print(f"{family:18s} {len(prices):4d} SKU  +{len(supplements):2d} supplements"
              f"  ({prices[0]['listino_edition'] if prices else '?'})")
        all_prices += prices
        all_supplements += supplements

    slug, manufacturer, family, url = KNAUF_SOURCE
    knauf_pdf = CACHE_DIR / f"{slug}.pdf"
    if knauf_pdf.exists():
        prices, _ = parse_knauf(knauf_pdf, manufacturer, family, url)
        print(f"{family:18s} {len(prices):4d} SKU  ({prices[0]['listino_edition']})")
        all_prices += prices
    else:
        print(f"!! {knauf_pdf.relative_to(ROOT)} missing - Knauf skipped "
              "(save the PDF by hand, see the module docstring)")

    slug, manufacturer, family, url = EDILTEC_SOURCE
    ediltec_pdf = fetch(slug, url, refresh=not args.no_fetch)
    prices, supplements = parse_ediltec(ediltec_pdf, manufacturer, family, url)
    print(f"{family:18s} {len(prices):4d} SKU  +{len(supplements):2d} supplements"
          f"  ({prices[0]['listino_edition'] if prices else '?'})")
    all_prices += prices
    all_supplements += supplements

    slug, manufacturer, family, url = POLIISO_AIR_SOURCE
    air_pdf = fetch(slug, url, refresh=not args.no_fetch)
    prices, supplements = parse_poliiso_air(air_pdf, manufacturer, family, url)
    print(f"{family:18s} {len(prices):4d} SKU  +{len(supplements):2d} supplements"
          f"  ({prices[0]['listino_edition'] if prices else '?'})")
    all_prices += prices
    all_supplements += supplements

    slug, manufacturer, family, url = GAIVI_IRIS_SOURCE
    gaivi_pdf = CACHE_DIR / f"{slug}.pdf"
    if gaivi_pdf.exists():
        prices, supplements = parse_gaivi(gaivi_pdf, manufacturer, family, url,
                                          check=CACHE_DIR / f"{GAIVI_FOTO_SLUG}.pdf")
        print(f"{family:18s} {len(prices):4d} SKU  +{len(supplements):2d} supplements"
              f"  ({prices[0]['listino_edition'] if prices else '?'})")
        all_prices += prices
        all_supplements += supplements
    else:
        print(f"!! {gaivi_pdf.relative_to(ROOT)} missing - GAIVI skipped "
              "(save the PDF by hand, see the module docstring)")

    all_prices += parse_ata(refresh=not args.no_fetch)

    prices_df = pd.DataFrame(all_prices).reindex(columns=COLUMNS)
    prices_df["listino_date"] = pd.to_datetime(prices_df["listino_date"])
    supplements_df = pd.DataFrame(all_supplements).drop_duplicates(
        subset=["manufacturer", "family", "kind", "code", "description"], keep="first")

    print(f"\ntotal {len(prices_df)} priced SKUs across "
          f"{prices_df['product'].nunique()} products, "
          f"{len(supplements_df)} supplements")
    if args.dry_run:
        print(prices_df.head(15).to_string())
        return
    DATA_DIR.mkdir(exist_ok=True)
    prices_df.to_parquet(PRICES_PARQUET, index=False)
    supplements_df.to_parquet(SUPPLEMENTS_PARQUET, index=False)
    print(f"written: {PRICES_PARQUET.relative_to(ROOT)}, "
          f"{SUPPLEMENTS_PARQUET.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
