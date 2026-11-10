"""
21_ediltec_product_links.py — repoint Ediltec links at the new site.

Why this exists
---------------
Ediltec moved its site from ``italy.ediltec.com`` to ``ediltec.com`` (WordPress).
Every product page and every file under ``italy.ediltec.com/upload/`` now
returns 404.

Product pages (``U__ProductInfo_URL``)

    https://italy.ediltec.com/it/prodotto/<category>/<slug>
 -> https://ediltec.com/prodotti/isolamento-termico/<category>/<slug>/

(source: https://ediltec.com/product-sitemap.xml). Slugs are unchanged; only the
"prodotti-speciali-pannelli-fresati-e-ventilati" category was renamed.

Files were renamed, so they are read off each row's new product page instead:

    U__TechDetails_URL      the page's "Scheda tecnica" link
    VV__DOP                 the page's "DoP" link
    U__Img_URL              the page's og:image

and the two ICMQ recycled-content certificates (``R__Rec_Reco_ByProd_URL``) are
mapped by name from https://ediltec.com/documentazione/.

Left alone, because the new site has no file for them (the documentation pages
exist but carry no PDF): ``VV__MSDS__URL`` (Poliiso / X-Foam safety data
sheets) and ``VV__Other`` (2023 LEED mapping). Also left alone: rows linking the
bare homepage (TECNOFOAM range) and the Poliiso Air ducts site.

The ``*_Local`` cache columns are carried over unchanged, so the app keeps
showing the copies it already downloaded.

``base_data.parquet`` is never written by the app, so the fix goes into the edit
log (Neon when configured, else ``edits_data.parquet``) through fn156b, as one
full-row snapshot per changed row — newest record per id wins on merge.
Re-running is a no-op.

Usage
-----
    python 04_tools/21_ediltec_product_links.py            # dry run
    python 04_tools/21_ediltec_product_links.py --apply    # write
"""

from __future__ import annotations

import argparse
import html
import pathlib
import re
import sys
import urllib.request

import pandas as pd

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from libs.lib_data import (  # noqa: E402
    fn153b_load_base_dataframe,
    fn155_load_edits_dataframe,
    fn156b_append_edit_records,
    fn157_merge_base_and_edits,
)

URL_COL   = "U__ProductInfo_URL"
EDIT_USER = "ediltec_link_update"
OLD_HOST  = "italy.ediltec.com"

OLD_RE   = re.compile(r"^https?://italy\.ediltec\.com/it/prodotto/([^/]+)/([^/?#]+)/?$")
NEW_ROOT = "https://ediltec.com/prodotti/isolamento-termico"
CATEGORY_RENAMES = {
    "prodotti-speciali-pannelli-fresati-e-ventilati": "pannelli-fresati-e-ventilati",
}

# Column -> pattern pulling that document's link out of the new product page.
PAGE_FIELDS = {
    "U__TechDetails_URL": re.compile(r'id="scheda_prodotto_Tecnica" href="([^"]+)"'),
    "VV__DOP":            re.compile(r'id="Certificazione_prodotto" href="([^"]+)"'),
    "U__Img_URL":         re.compile(r'property="og:image" content="([^"]+)"'),
}

_DOWNLOAD_IT = "https://ediltec.com/wp-content/uploads/download/it"
FILE_RENAMES = {
    "https://italy.ediltec.com/upload/pdf/CP-DOC-262-POLIISO.pdf":
        f"{_DOWNLOAD_IT}/CP%20DOC%20262%20POLIISO.pdf",
    "https://italy.ediltec.com/upload/pdf/CP-DOC-262-XFOAM.pdf":
        f"{_DOWNLOAD_IT}/CP%20DOC%20262%20X_FOAM.pdf",
}

PROVENANCE = {
    "batch":        "2026-10-29 ediltec site migration",
    "reason":       "italy.ediltec.com pages and files return 404; moved to ediltec.com",
    "evidence":     "Ediltec product sitemap and product pages",
    "evidence_url": "https://ediltec.com/product-sitemap.xml",
}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def new_url(old) -> str | None:
    """New ediltec.com page for an old italy.ediltec.com one, else None."""
    if not isinstance(old, str):
        return None
    m = OLD_RE.match(old.strip())
    if not m:
        return None
    category, slug = m.groups()
    return f"{NEW_ROOT}/{CATEGORY_RENAMES.get(category, category)}/{slug}/"


_page_cache: dict[str, dict[str, str]] = {}


def _fetch(url: str, method: str = "GET") -> bytes | None:
    """Body of *url*, or None when it does not answer 200."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read() if resp.status == 200 else None
    except OSError:
        return None


def _live(url: str) -> bool:
    return _fetch(url, "HEAD") is not None


def _image_fallback(url: str) -> str | None:
    """Ediltec's og:image is sometimes missing while its resized copies exist
    (e.g. POLIISO-VV); fall back to the largest of those."""
    if _live(url):
        return url
    alt = re.sub(r"(\.\w+)$", r"-768x768\1", url)
    return alt if _live(alt) else None


def page_links(page_url) -> dict[str, str]:
    """{column: live link} read off a new ediltec.com product page (cached)."""
    if not isinstance(page_url, str) or not page_url.startswith(NEW_ROOT):
        return {}
    if page_url not in _page_cache:
        body = (_fetch(page_url) or b"").decode("utf-8", errors="replace")
        links = {}
        for col, rx in PAGE_FIELDS.items():
            if not (m := rx.search(body)):
                continue
            url = html.unescape(m.group(1))
            url = _image_fallback(url) if col == "U__Img_URL" else (url if _live(url) else None)
            if url:
                links[col] = url
        _page_cache[page_url] = links
    return _page_cache[page_url]


def _is_old(value) -> bool:
    return isinstance(value, str) and OLD_HOST in value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the records (default is a dry run)")
    args = ap.parse_args()

    df = fn157_merge_base_and_edits(fn153b_load_base_dataframe(),
                                    fn155_load_edits_dataframe())

    changes: dict[int, dict[str, str]] = {}
    for idx, row in df.iterrows():
        page = new_url(row.get(URL_COL))
        fix = {URL_COL: page} if page else {}
        page = page or row.get(URL_COL)
        for col in PAGE_FIELDS:
            if _is_old(row.get(col)) and col in page_links(page):
                fix[col] = page_links(page)[col]
        col = "R__Rec_Reco_ByProd_URL"
        if row.get(col) in FILE_RENAMES:
            fix[col] = FILE_RENAMES[row[col]]
        if fix:
            changes[idx] = fix

    summary = pd.DataFrame(
        [(col, df.at[i, col], new) for i, fix in changes.items() for col, new in fix.items()],
        columns=["column", "old", "new"],
    )
    print(f"Rows to update: {len(changes)}\n")
    if not summary.empty:
        print(summary.groupby("column").size().to_string(), "\n")
        print(summary.drop_duplicates().sort_values(["column", "new"]).to_string(index=False))

    if not changes:
        print("Nothing to do.")
        return 0
    if not args.apply:
        print("\nDry run. Re-run with --apply to write to the edit log.")
        return 0

    rows, provenance = [], []
    for idx, fix in changes.items():
        row = df.loc[idx].to_dict()
        row.update(fix)
        rows.append((row, row["0__EETRA_ID"]))
        provenance.append({**PROVENANCE, "fields": ";".join(fix)})
    dest = fn156b_append_edit_records(rows, "update", user=EDIT_USER,
                                      provenance=provenance)
    print(f"\n✅ Wrote {len(rows)} records → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
