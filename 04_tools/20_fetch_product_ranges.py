"""Build aux_09__product_ranges.json — commercial ranges behind an EPD entry.

Why this exists
───────────────
A single library row is one EPD (e.g. TIL__POR__1535 = S-P-12921, 12 mm
Castellarano). Behind it sits a whole commercial range: 48 SapienStone slabs,
each with its own name, image, size and finish. Those belong in the catalogue
as a *gallery* the user can open from the row, not as 48 more library rows —
48 rows would distort the GWP statistics and the two-file data model keeps
product rows in edits_data.parquet only.

So the range lives here, as auxiliary reference data, keyed by range id. The
row links to a range through its existing ``D__IncludedProducts`` field; the
catalogue component looks each name up in the flat index this file also writes
and shows the image when it finds one.

Run:  python -I 04_tools/20_fetch_product_ranges.py
Writes: aux_09__product_ranges.json (project root)

Iris Ceramica Group publishes everything this needs server-side, so plain
urllib is enough — no browser, no JS. Pages are fetched once and parsed with
regexes against the rendered markup; if the sites are restructured the
assertions at the end of each fetcher will fail loudly rather than write a
half-empty file.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = PROJECT_ROOT / "aux_09__product_ranges.json"

UA = "Mozilla/5.0 (compatible; EETRA-MatLib/1.0; +https://eetra.it)"
SLEEP = 0.3


def fetch(url: str, *, tries: int = 3) -> str:
    """GET *url* and return the body as text, retrying transient failures.

    A 404 comes back as "" rather than an exception: the site links colours that
    are not published yet (and some pages answer 404 only intermittently), and
    one missing colour should not lose the whole run.
    """
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return ""
            last = exc
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def strip_tags(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


# ── SapienStone (sapienstone.com) ────────────────────────────────────────────
# Countertop / furniture slabs. One page per product, size + thickness + finish
# rendered server-side. The sitemap is the authoritative product list.
SS_BASE = "https://www.sapienstone.com"


def fetch_sapienstone() -> list[dict]:
    sitemap = fetch(f"{SS_BASE}/sitemap.xml")
    slugs = sorted({m for m in re.findall(r"/products/([a-z0-9-]+)", sitemap)})
    members = []
    for slug in slugs:
        html = fetch(f"{SS_BASE}/products/{slug}")
        text = strip_tags(html)
        name = slug.replace("-", " ").title()
        if m := re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, flags=re.I):
            name = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() or name
        img = ""
        if m := re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, flags=re.I):
            img = m.group(1)
        if not img and (m := re.search(r'src="(/resources/material-design-images/[^"]+)"', html)):
            img = m.group(1)
        if img.startswith("/"):
            img = SS_BASE + img
        members.append({
            "name": name,
            "url": f"{SS_BASE}/products/{slug}",
            "img": img,
            # "12 mm" / "20 mm" — the EPD that applies depends on this.
            "thickness_mm": sorted({t.replace(" mm", "") for t in re.findall(r"\d{1,2} mm", text)}, key=float),
            "sizes": sorted({s for s in re.findall(r"\b\d{3}x\d{2,3}\b", text)}),
            "finishes": sorted({f.title() for f in re.findall(
                r"\b(Polished|Silky|Natural|Soft|Structured|Matte)\b", text)}),
            "full_body": slug.endswith("-4d") or "4d" in name.lower(),
        })
        time.sleep(SLEEP)
    assert len(members) >= 40, f"SapienStone: only {len(members)} products found"
    return members


# ── Iris Ceramica (irisceramica.com) ─────────────────────────────────────────
# Floor / wall collections. A collection page links to one page per colour;
# each colour page carries a "SIZES Code THICKNESS Finish" table, and a single
# colour can span several thicknesses (so several EPDs).
IR_BASE = "https://www.irisceramica.com"

# The table runs straight into the per-size cards that repeat it ("… Size
# 100X100 cm Code …"), so the finish group has to stop before the next row's
# size, before that repeat, and before whatever section follows the table.
# Sizes can carry a decimal comma ("7,5X30 cm") and a row can be followed by a
# footnote marker ("Stuctured * Available at Cersaie 2025"), so both the size
# and the run-off after the finish have to allow more than digits and ticks.
# The size separator is inconsistently cased on the site ("10X60" / "10x60").
IR_SIZE = r"[\d,]{1,6}[Xx][\d,]{1,6}"
IR_ROW_RE = re.compile(
    rf"({IR_SIZE})\s*cm\s*([A-Z0-9]{{4,14}})\s*([\d.,]+)\s*mm\s*"
    r"([A-Za-z][A-Za-z +]*?)[\s√✓*]*"
    rf"(?={IR_SIZE}\s*cm|\bSize\b|\bCertification|\bRequest\b|\bDecorations\b|\bAvailable\b|$)"
)


def iris_collection_slugs() -> list[str]:
    """Every collection linked from the site's own collections listing.

    Hard-coding the list went stale immediately — the Théké ranges, Uni Active
    and Urban Active were all missing. The listing pages all carry the same 34
    links (/collections/wall-coverings shows a subset), so one fetch is enough;
    the others are taken as well so a reshuffle of the nav cannot silently
    shrink the crawl.
    """
    slugs: set[str] = set()
    for path in ("/collections/floors", "/collections/wall-coverings", "/collections"):
        html = fetch(IR_BASE + path)
        slugs.update(re.findall(r'href="/products/([a-z0-9._-]+)"', html))
        time.sleep(SLEEP)
    return sorted(slugs)


# A collection page renders its colour range as a grid of swatches — the
# rectangular texture shot, the name under it, and a red NEW flag — under an
# <h2> per section ("Floors", "Wall coverings"). Reading the grid itself gets
# the picture a person actually sees on the page, and the section each colour
# belongs to, which the individual colour pages do not say.
IR_ITEM_MARK = re.compile(r"model-41__item")
IR_SECTION_RE = re.compile(r"<h2[^>]*model-41__title[^>]*>(.*?)</h2>", re.S)
IR_NAME_RE = re.compile(r"model-41__color[^>]*>(.*?)</h3>", re.S)


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def _iris_grid_once(slug: str) -> list[dict]:
    """One read of a collection page's swatch grid."""
    html = fetch(f"{IR_BASE}/products/{slug}")
    if not html or re.search(r"Page 404|does not exist", html, flags=re.I):
        return []
    sections = [(m.start(), _text(m.group(1))) for m in IR_SECTION_RE.finditer(html)]
    marks = [m.start() for m in IR_ITEM_MARK.finditer(html)]
    out = []
    for n, pos in enumerate(marks):
        # One block per grid item, so attribute order inside it never matters.
        block = html[pos: marks[n + 1] if n + 1 < len(marks) else pos + 2500]
        img = re.search(r'<img[^>]*src="([^"]+)"', block)
        name = IR_NAME_RE.search(block)
        if not (img and name):
            continue
        href = re.search(r'href="(/products/[^"#?]+)"', block)
        before = [t for p, t in sections if p < pos]
        out.append({
            "section": before[-1] if before else "",
            "name": _text(name.group(1)),
            "img": IR_BASE + img.group(1) if img.group(1).startswith("/") else img.group(1),
            "url": IR_BASE + href.group(1) if href else "",
            "new": bool(re.search(r'class="[^"]*\bnew\b', block)),
        })
    return out


def iris_collection_grid(slug: str, passes: int = 3) -> list[dict]:
    """Swatches on a collection page, merged over several reads.

    irisceramica.com serves more than one version of the same collection page:
    Victorian Stone comes back either with Full White under "Floors" and a NEW
    badge on all 23 swatches, or with Full White under "Wall coverings" and no
    badges at all. Which one you get varies request to request, so a single
    fetch silently decides both the section split and every NEW flag.

    Reading it a few times and merging keeps every swatch that any version
    showed, records each section it was seen in, and treats NEW as true if any
    version flagged it — the optimistic reading, since the badge disappearing
    is the variant that looks like data loss. Treat ``new`` as best-effort even
    so: three passes can still land on the unbadged version every time. The
    swatch list itself is stable once merged.

    Keyed on the colour's own URL, not its name: a collection routinely sells
    the same colour as both a floor and a wall tile
    (``/floors-baycliff-black`` and ``/wall-coverings-baycliff-black``), and
    those are two products with two SKU tables.
    """
    merged: dict[str, dict] = {}
    for _ in range(max(1, passes)):
        for item in _iris_grid_once(slug):
            key = item["url"] or f"{item['section']}|{item['name']}".lower()
            if key in merged:
                merged[key]["new"] = merged[key]["new"] or item["new"]
                merged[key]["section"] = merged[key]["section"] or item["section"]
            else:
                merged[key] = dict(item)
        time.sleep(SLEEP)
    return list(merged.values())


def _iris_skus(url: str) -> dict:
    """The "SIZES Code THICKNESS Finish" table on one colour page."""
    html = fetch(url) if url else ""
    if not html or re.search(r"Page 404|does not exist", html, flags=re.I):
        return {"thickness_mm": [], "sizes": [], "finishes": [], "skus": []}
    text = strip_tags(html)
    i = text.upper().find("SIZES CODE THICKNESS")
    rows = []
    if i > -1:
        for size, code, mm, fin in IR_ROW_RE.findall(text[i:i + 1600]):
            fin = fin.strip()
            # Decor pieces leave the Finish cell empty, so the match runs on
            # into the "Size …" card that repeats the row.
            row = {"size": size, "code": code,
                   "mm": mm.replace(",", "."),
                   "finish": "" if fin == "Size" else fin}
            # The page prints the table and then repeats it as per-size cards,
            # so the same SKU can match twice.
            if row not in rows:
                rows.append(row)
    return {
        "thickness_mm": sorted({r["mm"] for r in rows}, key=float),
        "sizes": sorted({r["size"] for r in rows}),
        "finishes": sorted({r["finish"] for r in rows if r["finish"]}),
        "skus": rows,
    }


def fetch_iris_collection(slug: str) -> list[dict]:
    members = []
    for item in iris_collection_grid(slug):
        member = dict(item)
        member.update(_iris_skus(item["url"]))
        members.append(member)
        time.sleep(SLEEP)
    return members


# What each 2024 Iris Ceramica Group declaration covers, transcribed from its
# PRODUCT IDENTIFICATION paragraph and production-sites page. This is what
# decides which EPD a collection may cite: brand first, then thickness. Note
# that brand + thickness does not always give one answer — the Iris Ceramica
# brand at 6 mm is in both 12918 and 12925, at 8 mm in both 12923 and 12925 —
# because the split that remains is Italy vs the German plant.
IRIS_EPD_SCOPE = {
    "S-P-12918": {
        "plants": ["Castellarano (RE), Via Radici Nord 112 / Via Cimabue 20 / Via Manganella 2"],
        "thickness_mm": ["6"],
        "brands": ["Ariostea", "Fiandre Architectural Surfaces",
                   "FMG Fabbrica Marmi e Graniti", "Iris Ceramica", "Porcelaingres",
                   "SapienStone", "Stonepeak Ceramics", "Active Surfaces"],
        "note": "Slabs, countertops and furniture.",
    },
    "S-P-12921": {
        "plants": ["Castellarano (RE), Via Radici Nord 112 / Via Cimabue 20 / Via Manganella 2"],
        "thickness_mm": ["12"],
        "brands": ["SapienStone", "Active Surfaces"],
        "note": "Furniture and countertops only; includes 4D Ceramics full body.",
    },
    "S-P-12922": {
        "plants": ["Castellarano (RE), Via Radici Nord 112 / Via Cimabue 20 / Via Manganella 2"],
        "thickness_mm": ["20"],
        "brands": ["SapienStone", "Active Surfaces"],
        "note": "Furniture and countertops only; includes 4D Ceramics full body.",
    },
    "S-P-12923": {
        "plants": ["Fiorano Modenese (MO), Via Ghiarola Nuova 128",
                   "Sassuolo (MO), Via Valle d'Aosta 37"],
        "thickness_mm": ["8", "9"],
        "brands": ["Ariostea", "Fiandre Architectural Surfaces",
                   "FMG Fabbrica Marmi e Graniti", "Iris Ceramica",
                   "Stonepeak Ceramics", "Active Surfaces"],
        "note": "The EPD titles itself 'Sassuolo Plant' but declares both sites.",
    },
    "S-P-12924": {
        "plants": ["Fiorano Modenese (MO), Via Ghiarola Nuova 128",
                   "Sassuolo (MO), Via Valle d'Aosta 37"],
        "thickness_mm": ["10"],
        "brands": ["Ariostea", "Fiandre Architectural Surfaces",
                   "FMG Fabbrica Marmi e Graniti", "Iris Ceramica", "SapienStone",
                   "Stonepeak Ceramics", "Active Surfaces"],
        "note": "Full-body slabs. At 10 mm, check this against S-P-12928 — that "
                "one is semi-gres wall tile at the same thickness.",
    },
    "S-P-12925": {
        "plants": ["Irisstrasse 1, 03226 Vetschau, Germany"],
        "thickness_mm": ["6", "8"],
        "brands": ["Ariostea", "Fiandre Architectural Surfaces",
                   "FMG Fabbrica Marmi e Graniti", "Iris Ceramica", "Porcelaingres",
                   "Active Surfaces"],
        "note": "German plant. Overlaps 12918 at 6 mm and 12923 at 8 mm.",
    },
    "S-P-12927": {
        "plants": ["Irisstrasse 1, 03226 Vetschau, Germany"],
        "thickness_mm": ["9", "11", "13", "20"],
        "brands": ["Ariostea", "Fiandre Architectural Surfaces",
                   "FMG Fabbrica Marmi e Graniti", "Iris Ceramica", "Porcelaingres",
                   "Stonepeak Ceramics", "Active Surfaces"],
        "note": "The only declaration covering the Iris Ceramica brand at 11, 13 "
                "and 20 mm, so those thicknesses resolve to it outright.",
    },
    "S-P-12928": {
        "plants": ["Fiorano Modenese (MO), Via Ghiarola Nuova 119"],
        "thickness_mm": ["7", "7.5", "8.5", "8.8", "10", "10.5"],
        "brands": ["FMG Fabbrica Marmi e Graniti", "Iris Ceramica",
                   "Stonepeak Ceramics", "Active Surfaces"],
        "note": "Semi-gres for internal wall coverings. The only declaration at "
                "7, 7.5, 8.5, 8.8 and 10.5 mm.",
    },
}



# ── Emilceramica (emilgroup.it) ──────────────────────────────────────────────
# Emilceramica S.r.l. sells through five brands — Emilceramica, Ergon, Provenza,
# Viva and Level — all on one Next.js site. The rendered HTML carries almost
# nothing, but the pages router exposes the same props as JSON under
# /_next/data/<buildId>/…, and that payload is far better structured than the
# Iris markup: every collection lists its colour families, each tonalità with
# its own photo and URL, plus the thicknesses and the formats sold at each.
EM_BASE = "https://www.emilgroup.it"

EM_BRANDS = (("emilceramica", "Emilceramica"), ("ergon", "Ergon"),
             ("provenza", "Provenza"), ("viva", "Viva"), ("level", "Level"))


def emil_build_id() -> str:
    """The deploy hash that /_next/data URLs are keyed on.

    It changes on every deploy, so it is read from a live page rather than
    pinned. Failing loudly here is right: a stale id answers 404 for every
    collection and would otherwise write an empty Emilceramica section.
    """
    html = fetch(f"{EM_BASE}/collezioni/")
    m = re.search(r"/_next/static/([A-Za-z0-9_-]{12,})/_buildManifest", html)
    if not m:
        raise RuntimeError("could not read the emilgroup.it build id")
    return m.group(1)


def emil_json(build: str, path: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    raw = fetch(f"{EM_BASE}/_next/data/{build}/{path}.json?{query}")
    return json.loads(raw).get("pageProps", {}) if raw else {}


def emil_brand_collections(build: str, brand: str) -> list[tuple[str, str]]:
    """(slug, title) for every collection the brand's own page lists."""
    pp = emil_json(build, f"collezioni/brand/{brand}", slug_brand=brand)
    out = []
    for c in (pp.get("brand") or {}).get("collezioni") or []:
        slug = (c.get("url") or "").strip("/").split("/")[-1]
        if slug and slug != brand:
            out.append((slug, c.get("title") or slug.replace("-", " ").title()))
    return out


def _emil_thickness(raw: str) -> str:
    """'9,5 mm' → '9.5'. Empty for anything that is not a plain number."""
    m = re.search(r"(\d+(?:[.,]\d+)?)", raw or "")
    return m.group(1).replace(",", ".") if m else ""


def _emil_max_side(formats: list[str]) -> float:
    """Longest side in cm across *formats*, which is what tells a slab from a tile.

    EPDITALY0178 covers the Fiorano large-slab line and explicitly excludes the
    pressed-tile line, so format is what separates a collection the declaration
    could reach from one it cannot: 120x278 is a slab, 60x120 is a tile.
    """
    best = 0.0
    for f in formats:
        for side in re.findall(r"(\d+(?:[.,]\d+)?)", f or ""):
            best = max(best, float(side.replace(",", ".")))
    return best


def _emil_img(url: str) -> str:
    """Percent-encode an image URL.

    Emilgroup names its photo files after the product — "Level Concrete
    White 1.jpg" — so the URLs it publishes carry raw spaces and urllib refuses
    them. Only the path is quoted, and '/' and '%' are left alone so an already
    encoded URL survives a second pass unchanged.
    """
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        parts._replace(path=urllib.parse.quote(parts.path, safe="/%")))


def fetch_emil_collection(build: str, brand: str, slug: str) -> tuple[list[dict], dict]:
    """Colours of one collection, plus the collection-level facts behind them."""
    pp = emil_json(build, f"collezioni/brand/{brand}/{slug}",
                   slug_brand=brand, slug_collezione=slug)
    col = pp.get("collezione") or {}
    if not col:
        return [], {}

    thicknesses, sizes = [], []
    for sf in col.get("spessoriFormati") or []:
        if (t := _emil_thickness(sf.get("spessore") or "")) and t not in thicknesses:
            thicknesses.append(t)
        for f in sf.get("formati") or []:
            name = (f.get("nome") or "").strip()
            if name and name not in sizes:
                sizes.append(name)
    finishes = [n for s in col.get("superfici") or []
                if (n := (s.get("nome") or s.get("title") or "").strip())]

    families = col.get("colori") or []
    # A colour name repeats across families — Grain Stone sells Sand in both
    # Fine Grain and Rough Grain — so the family has to be part of the name, or
    # the two collapse into one entry in the index.
    qualify = len(families) > 1
    members, seen = [], set()
    for fam in families:
        fam_name = (fam.get("nome") or "").strip()
        for ton in fam.get("tonalita") or []:
            colour = (ton.get("nome") or "").strip()
            url = ton.get("url") or ""
            if not colour or url in seen:
                continue
            seen.add(url)
            members.append({
                "name": f"{fam_name} {colour}".strip() if qualify else colour,
                "colour": colour,
                "family": fam_name,
                "url": EM_BASE + url if url.startswith("/") else url,
                "img": _emil_img((ton.get("image") or {}).get("url") or ""),
                "thickness_mm": thicknesses,
                "sizes": sizes,
                "finishes": finishes,
                "section": "",
                "new": bool(col.get("novita")),
            })

    meta = {
        "thickness_mm": thicknesses,
        "sizes": sizes,
        "finishes": finishes,
        "max_side_cm": _emil_max_side(sizes),
        "effect": (col.get("categoriaEffetto") or {}).get("slug") or "",
    }
    return members, meta


# Which plant makes which series, from the annex to Certiquality certificate
# 73438 (recycled content, issued 08/01/2026, expiring 07/01/2029), read with
# ``pdftotext -table``. This is the only public document that ties an
# Emilceramica series to a production site, and the site is what decides
# whether EPDITALY0178 — Fiorano, large-slab line — can apply at all.
#
# It covers 12 series out of the 73 on the website; the rest have no published
# plant. Note also that the certificate's own header names only the Fiorano
# unit while the annex lists four sites, so the library's R__Rec_Cert_Plant
# ("Via Ghiarola Nuova, 29 … Fiorano") understates it for most of these series.
EMIL_SERIES_PLANTS = {
    ("ergon", "cornerstone"): ["Casiglie"],
    ("ergon", "cornerstone-alpen"): ["Casiglie"],
    ("ergon", "elegance-pro"): ["Sassuolo"],
    ("ergon", "grain-stone"): ["Fiorano"],
    ("ergon", "lombarda"): ["Fiorano", "Casiglie"],
    ("ergon", "matera-stone"): ["Casiglie", "Sassuolo", "Finale Emilia"],
    ("ergon", "tr3nd"): ["Fiorano", "Casiglie", "Finale Emilia"],
    ("provenza", "ego"): ["Fiorano"],
    ("provenza", "eureka"): ["Fiorano"],
    ("provenza", "unique-bourg"): ["Fiorano"],
    ("provenza", "unique-travertine"): ["Casiglie"],
    ("provenza", "w-circles"): ["Fiorano"],
    ("emilceramica", "mapierre"): ["Casiglie", "Sassuolo"],
}

# Cornerstone Alpen is a separate collection on the site, but the annex names
# only "Cornerstone". Treat the plant as inherited and say so, rather than
# leaving it blank or asserting it silently.
EMIL_PLANT_CAVEAT = {
    ("ergon", "cornerstone-alpen"):
        "Inherited from Cornerstone — the certificate annex does not list "
        "Cornerstone Alpen separately.",
}

# The two Emilceramica declarations the library holds. Neither works like the
# Iris ones: neither names a brand, a series or a thickness, so no collection
# can be resolved to one by brand-plus-thickness the way an Iris collection is.
#
#   EPDITALY0178  is Emilceramica's own, but scoped to a single production
#                 line — Fiorano, Grandi Lastre — and it explicitly excludes
#                 series made on the pressed-tile line. Plant AND line must
#                 both match. It expired on 08/04/2026.
#   EPD-COI-…     is Confindustria Ceramica's sector average for Italian
#                 ceramic tiles: it covers any Italian tile as an average and
#                 no particular product as a declaration.
EMIL_EPD_SCOPE = {
    "EPDITALY0178": {
        "declaration": "EMI_SLABS_19_0001",
        "programme": "EPDItaly",
        "owner": "Emilceramica S.r.l. a socio unico",
        "plants": ["Fiorano Modenese (MO), Via Ghiarola Nuova 29 — "
                   "linea Grandi Lastre"],
        "thickness_mm": [],
        "brands": [],
        "product": "Porcelain stoneware slabs (large format)",
        "declared_unit": "1 m2, average 18.8 kg/m2",
        "issued": "2021-04-08",
        "valid_to": "2026-04-08",
        "excludes": "Series produced on the 'piastrelle in ceramica' "
                    "(pressed tile) line.",
        "note": "Scope, verbatim: 'lastra in gres porcellanato media tra i "
                "diversi prodotti di Emilceramica S.r.l. realizzati nel sito di "
                "Fiorano, ad esclusione delle serie realizzate con la tecnologia "
                "della linea produttiva \"piastrelle in ceramica\"'. A collection "
                "therefore qualifies only if it is made at Fiorano AND on the "
                "slab line; tile formats are out by definition. Declares no "
                "brand and no series. EXPIRED 08/04/2026.",
    },
    "EPD-COI-20220297-ICG1-EN": {
        "declaration": "EPD-COI-20220297-ICG1-EN",
        "programme": "IBU (Institut Bauen und Umwelt)",
        "owner": "Confindustria Ceramica",
        "plants": ["74 member companies, 87 plants — 82.6 % of Italian "
                   "ceramic tile production"],
        "thickness_mm": [],
        "brands": [],
        "product": "Italian ceramic tiles, sector average",
        "declared_unit": "1 m2 of installed ceramic tile (average), 21.38 kg/m2",
        "issued": "2023-01-04",
        "valid_to": "2028-01-03",
        "note": "Industry-wide average, not a manufacturer declaration: it "
                "names no company, plant, brand or series. It applies to an "
                "Emilceramica tile only in the sense that it applies to every "
                "Italian ceramic tile, and must not be presented as "
                "product-specific data.",
    },
}


def emil_range_note(plants: list[str], meta: dict, brand: str, slug: str) -> str:
    """One line on what the two declarations can and cannot say about this range."""
    is_slab = meta.get("max_side_cm", 0) >= 200
    parts = []
    if plants:
        parts.append("Plant: " + " / ".join(plants) + " (Certiquality 73438 annex).")
        if caveat := EMIL_PLANT_CAVEAT.get((brand, slug)):
            parts.append(caveat)
    else:
        parts.append("Plant not published.")
    if is_slab and "Fiorano" in plants:
        parts.append("Large formats and made at Fiorano, so EPDITALY0178 is the "
                     "candidate — but confirm the series runs on the slab line.")
    elif is_slab:
        parts.append("Large formats, but the certificate does not place it at "
                     "Fiorano, so EPDITALY0178 does not reach it.")
    else:
        parts.append("Tile formats only, so outside EPDITALY0178, which excludes "
                     "the pressed-tile line.")
    parts.append("EPD-COI-20220297-ICG1-EN applies only as the Italian sector average.")
    return " ".join(parts)


def fetch_emilceramica() -> dict:
    """Every collection of the five Emilceramica brands, keyed emil-<brand>-<slug>."""
    build = emil_build_id()
    print(f"  build id {build}", flush=True)
    out: dict[str, dict] = {}
    for brand, label in EM_BRANDS:
        collections = emil_brand_collections(build, brand)
        print(f"Emilceramica / {label}: {len(collections)} collections", flush=True)
        time.sleep(SLEEP)
        for slug, title in collections:
            members, meta = fetch_emil_collection(build, brand, slug)
            time.sleep(SLEEP)
            if not members:
                print(f"  {slug}: no colours — skipped", flush=True)
                continue
            plants = EMIL_SERIES_PLANTS.get((brand, slug), [])
            out[f"emil-{brand}-{slug}"] = {
                "manufacturer": "Emilceramica",
                "brand": label,
                "label": f"{label} {title}",
                "source": f"{EM_BASE}/collezioni/brand/{brand}/{slug}/",
                # No EPD id per collection, for the same reason as Iris but a
                # different cause: these two declarations name no brand, series
                # or thickness, so nothing in the product data selects one.
                "plants": plants,
                "note": emil_range_note(plants, meta, brand, slug),
                "members": members,
                **meta,
            }
            print(f"  {slug}: {len(members)} colours, "
                  f"{'/'.join(meta['thickness_mm']) or '?'} mm", flush=True)
    return out


def cache_images(ranges: dict) -> int:
    """Pull every member thumbnail into ``static/img_cache``; return how many.

    The catalogue component runs in a sandboxed Streamlit iframe that will not
    load a remote image, so hotlinking the manufacturer's own URL renders a row
    of empty tiles even though the URL is perfectly good. Product card images
    already solve this by going through ``lib_data.ensure_static_img_cache``
    (downscaled, keyed on the source URL, served from ``/app/static/…``); the
    range gallery reuses exactly that, and each member keeps the remote URL in
    ``img_src`` so a rebuild can re-fetch it.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from io import BytesIO

    from PIL import Image

    from libs import lib_data

    done = 0
    for rng in ranges.values():
        for m in rng["members"]:
            src = m.get("img", "")
            if not src:
                continue
            if existing := lib_data.static_img_cache_url(src):
                m["img_cached"] = existing
                done += 1
                continue
            try:
                req = urllib.request.Request(src, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                img = Image.open(BytesIO(raw))
                img.load()
                written = lib_data.ensure_static_img_cache(src, img)
                if url := written.get("card"):
                    m["img_cached"] = url
                    done += 1
            except Exception as exc:  # pragma: no cover — one bad image is not fatal
                print(f"  ! {m['name']}: {exc}", flush=True)
            time.sleep(SLEEP)
    return done


def main() -> int:
    ranges: dict[str, dict] = {}

    print("SapienStone …", flush=True)
    ranges["sapienstone"] = {
        "brand": "SapienStone",
        "label": "SapienStone",
        "source": SS_BASE,
        "note": "Countertop / furniture slabs, Castellarano (RE). 12 mm → EPD "
                "S-P-12921; 20 mm → S-P-12922.",
        "members": fetch_sapienstone(),
    }
    print(f"  {len(ranges['sapienstone']['members'])} products", flush=True)

    slugs = iris_collection_slugs()
    print(f"\nIris Ceramica: {len(slugs)} collections listed", flush=True)
    for slug in slugs:
        print(f"Iris Ceramica / {slug} …", flush=True)
        members = fetch_iris_collection(slug)
        if not members:
            print("  (no live product pages — skipped)", flush=True)
            continue
        ranges[f"iris-{slug}"] = {
            "brand": "Iris Ceramica",
            "label": slug.replace("-", " ").title(),
            "source": f"{IR_BASE}/products/{slug}",
            # Deliberately no EPD id per collection. Each declaration names the
            # brands and thicknesses it covers, which narrows it but does not
            # always close it: the Iris Ceramica brand appears at 6 mm in both
            # S-P-12918 (Castellarano) and S-P-12925 (Vetschau), and at 8 mm in
            # both S-P-12923 (Fiorano/Sassuolo) and S-P-12925. Only the plant
            # separates those, and the brand site does not publish it.
            "note": "Pick the EPD by thickness against the brand scope in "
                    "IRIS_EPD_SCOPE. 6 mm and 8/9 mm stay ambiguous between the "
                    "Italian and German plants — confirm with Iris Ceramica Group.",
            "members": members,
        }
        print(f"  {len(members)} colours", flush=True)

    print("\ncaching thumbnails …", flush=True)
    print("\nEmilceramica (emilgroup.it)", flush=True)
    ranges.update(fetch_emilceramica())

    cached = cache_images(ranges)
    print(f"  {cached} of {sum(len(r['members']) for r in ranges.values())} cached", flush=True)

    # Flat name → member index, so the catalogue popup can resolve an
    # D__IncludedProducts entry to an image without walking every range.
    #
    # Colour names are not unique across collections — "White" is sold by
    # E-Wood, Fence, Pluriball and Slide, "Grey" by Blaze, Fence and Slide —
    # and those differ in thickness and in which EPD covers them. So every
    # member is also indexed under "<Collection> <Name>", and a row listing a
    # shared name must use that qualified form or it will resolve to whichever
    # collection happens to come first.
    index: dict[str, dict] = {}
    owners: dict[str, set[str]] = {}
    for rid, rng in ranges.items():
        for m in rng["members"]:
            owners.setdefault(m["name"].strip().lower(), set()).add(rid)

    for rid, rng in ranges.items():
        for m in rng["members"]:
            bare = m["name"].strip().lower()
            keys = [f"{rng['label']} {m['name']}".strip().lower()]
            if len(owners[bare]) == 1:
                keys.append(bare)
            entry = {
                "range": rid,
                "label": rng["label"],
                "name": m["name"],
                # Same-origin path; the component iframe cannot load the
                # manufacturer's own URL (see cache_images).
                "img": m.get("img_cached", ""),
                "img_src": m.get("img", ""),
                "url": m.get("url", ""),
                "thickness_mm": m.get("thickness_mm", []),
                "sizes": m.get("sizes", []),
                "finishes": m.get("finishes", []),
                # Iris Ceramica only: which grid the swatch sits in, and
                # whether the page flags it as a new product.
                "brand": rng.get("brand", ""),
                # Emilceramica only: the production site from the
                # Certiquality annex, which is what decides whether
                # EPDITALY0178 can apply at all.
                "plants": rng.get("plants", []),
                "section": m.get("section", ""),
                "new": bool(m.get("new", False)),
                # True when the bare colour name is sold by more than one
                # collection, so only the qualified key is trustworthy.
                "name_shared": len(owners[bare]) > 1,
            }
            for key in keys:
                index.setdefault(key, entry)

    payload = {
        "_comment": (
            "Commercial ranges behind a library row. A row links to its range "
            "through D__IncludedProducts (names must match 'index' keys, "
            "case-insensitively). Rebuild with 04_tools/20_fetch_product_ranges.py. "
            "'epd_scope' is what each 2024 declaration covers (brands, thicknesses, "
            "plants), read from the EPDs themselves; match a collection to it by "
            "brand and then thickness. No range asserts an EPD id, because brand "
            "plus thickness does not always give a single answer."
        ),
        "_version": 3,
        "_fetched": date.today().isoformat(),
        "epd_scope": {**IRIS_EPD_SCOPE, **EMIL_EPD_SCOPE},
        "ranges": ranges,
        "index": index,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT_PATH} — {len(ranges)} ranges, {len(index)} named products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
