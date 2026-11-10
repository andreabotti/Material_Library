"""
libs/lib_prices.py — EETRA MatLib list-price data layer
=======================================================
fn500–fn520  Manufacturer list prices (listini) and their match to the catalogue

  fn500  prices_data_dir            resolve the parquet data directory
  fn501  load_price_lists           read price_lists.parquet (cached, mtime-keyed)
  fn502  load_price_supplements     read price_supplements.parquet (cached)
  fn503  normalise_product_key      product name -> comparable key
  fn504  product_keys               every key a catalogue name can match on
  fn505  price_rows_for_product     listino rows for one manufacturer + product
  fn506  price_for_product          single price indication for a catalogue row
  fn507  attach_prices              add price columns to a catalogue DataFrame
  fn508  format_price               "€ 8,05 /m²" for display
  fn509  price_coverage             which catalogue rows are priced, and which not
  fn510  supplements_for_family     accessories / coatings / surcharges of a family
  fn511  price_table_for_product    the product's full listino table, ready to render
  fn512  price_tables_payload       {EETRA id: table} for the catalogue component

Prices are **list prices** (listino, VAT excluded, before discount), read from
the manufacturer's published PDF by ``04_tools/13_parse_price_lists.py``. They
are an order-of-magnitude indication for design comparisons, never a quotation:
anything shown in the UI should say so and carry ``listino_edition``.

Matching rules
--------------
The catalogue names a product and its thickness separately from the listino
("Tectonic FP Basic - 100 mm" vs "URSA TECTONIC FP Basic" + 100 mm), so the
match is (manufacturer, normalised product key, thickness):

* the key drops the brand, punctuation, the trailing "- NN mm" and the marketing
  word "ECO", which the catalogue and the listino use inconsistently for XPS;
* a name holding alternatives ("XPS ECO | XPS NR") matches on either side;
* a catalogue row with a thickness *range* ("50-240") is a product family rather
  than a SKU, and gets the family's price span instead of a single price.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

_PRICES_FILE = "price_lists.parquet"
_SUPPLEMENTS_FILE = "price_supplements.parquet"

_PRICE_COLUMNS = ["manufacturer", "family", "product", "article", "packaging",
                  "product_code", "thickness_mm", "dimensions_m",
                  "lambda_declared_WmK", "lambda_WmK",
                  "R_m2KW", "price_eur_m2", "price_eur_m3", "price_eur_kg",
                  "weight_kg", "availability", "min_order_pallets", "units_per_pack",
                  "pack_m2", "packs_per_pallet", "pallet_m2", "pallet_kg", "currency",
                  "price_basis", "listino_edition", "listino_date", "source_doc",
                  "source_page", "source_url", "retrieved_on"]

# columns fn507 adds to a catalogue frame — the app's price surface
PRICE_UI_COLUMNS = ["PR__Price_EUR", "PR__Price_EUR_m2", "PR__Cost_per_R",
                    "PR__R_m2KW", "PR__Price_Min_EUR", "PR__Price_Max_EUR",
                    "PR__Price_Unit", "PR__Price_Exact", "PR__Price_Display",
                    "PR__Listino_Edition", "PR__Listino_URL"]

# words that carry no discriminating meaning between a catalogue name and a listino,
# per manufacturer: URSA writes "ECO" on some XPS names and not others, whereas for
# Gyproc "DuraGyp ECO" is a different board from "DuraGyp" and must stay distinct
_NOISE_WORDS = {"ursa": {"URSA", "ECO"}}
_DEFAULT_NOISE = _NOISE_WORDS["ursa"]   # a key built without saying whose name it is

# two sheet sizes of one board give €/m² a cent or two apart (rounding): that is one
# price, not a span
_SAME_PRICE_TOLERANCE = 0.05

# The availability flag ("Dis.") is the manufacturer's own code, and the same letter
# means different things: URSA's S is "a stock", Knauf's S is "on request".
AVAILABILITY_LEGENDS = {
    "ursa": "S = a stock · O = in produzione contro ordine · R = quantità minima da concordare",
    "knauf": ("A = consegna fino a 5 giorni lavorativi · B = fino a 10 giorni lavorativi · "
              "S = prodotto su singola richiesta, con minimi quantitativi"),
    "ediltec": ("S = MTS, materiale standard normalmente disponibile a magazzino · "
                "O = MTO, materiale fuori standard prodotto su ordinativo "
                "(minimo 20 m³ per codice) · R = prezzo su richiesta"),
}


def fn500_prices_data_dir() -> Path:
    """Directory holding the price parquets (01_data/ next to the other data)."""
    return Path(__file__).resolve().parents[1] / "01_data"


def _mtime_or_zero(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(ttl=3600, max_entries=8)
def _cached_read(path_str: str, mtime_key: float, columns: tuple) -> pd.DataFrame:
    """``mtime_key`` only exists to invalidate the cache when the file changes.

    It must not start with an underscore: Streamlit leaves ``_``-prefixed
    parameters out of the cache key, which is how this once served a stale price
    list for up to an hour after the parquet was rewritten (and _prices_by_key
    then stamped that stale frame with the new mtime, keeping it until restart).
    """
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame(columns=list(columns))
    return pd.read_parquet(path)


def fn501_load_price_lists() -> pd.DataFrame:
    """All priced SKUs. Empty frame (right columns) when the parquet is absent."""
    path = fn500_prices_data_dir() / _PRICES_FILE
    return _cached_read(str(path), _mtime_or_zero(path), tuple(_PRICE_COLUMNS)).copy()


def fn502_load_price_supplements() -> pd.DataFrame:
    """Accessories, coatings and surcharges published alongside the listini."""
    path = fn500_prices_data_dir() / _SUPPLEMENTS_FILE
    return _cached_read(str(path), _mtime_or_zero(path), ()).copy()


def fn503_normalise_product_key(name: str, manufacturer: str | None = None) -> str:
    """'Tectonic FP Basic - 100 mm' -> 'TECTONICFPBASIC'.

    The noise words dropped depend on *manufacturer* (see ``_NOISE_WORDS``); without
    one, the URSA set applies, as it always did.
    """
    if not name or pd.isna(name):
        return ""
    noise = (_DEFAULT_NOISE if manufacturer is None
             else _NOISE_WORDS.get(str(manufacturer).strip().casefold(), set()))
    txt = unicodedata.normalize("NFKD", str(name))
    txt = "".join(c for c in txt if not unicodedata.combining(c)).upper()
    # the span a catalogue row covering a whole family carries: "(30-160 mm)" or
    # "- 20,30,40 mm". Only a parenthesised range or a comma list counts, because a
    # bare hyphen also separates a name from its thickness ("Pureone zero 31- 45 mm",
    # where the 31 names the roll) — and the parentheses keep the 500 of
    # "X-FOAM HBT 500 - (50-200 mm)" out of the span
    txt = re.sub(r"[-–]?\s*\(\s*\d+(?:[.,]\d+)?(?:\s*[-–,;/]\s*\d+(?:[.,]\d+)?)*"
                 r"\s*MM\s*\)", " ", txt)
    txt = re.sub(r"[-–]?\s*\d+(?:[.,]\d+)?(?:\s*[,;]\s*\d+(?:[.,]\d+)?)+\s*MM\b",
                 " ", txt)
    txt = re.sub(r"[-–]?\s*\d+(?:[.,]\d+)?\s*MM\b", " ", txt)   # trailing "- 100 mm"
    words = [w for w in re.split(r"[^A-Z0-9]+", txt) if w and w not in noise]
    return "".join(words)


def fn504_product_keys(name: str, manufacturer: str | None = None) -> list[str]:
    """Keys a catalogue name may match on — '|' separates equivalent namings."""
    if not name or pd.isna(name):
        return []
    parts = [p for p in str(name).split("|") if p.strip()]
    keys = [fn503_normalise_product_key(name, manufacturer)]
    keys += [fn503_normalise_product_key(p, manufacturer) for p in parts]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


# {(manufacturer, product key): listino rows}, with the mtime it was built from.
# Memoised in the module rather than with @st.cache_data: fn507 hits this index
# once per catalogue row, and a cache_data round-trip per row (hash + copy of the
# whole dict) costs more than the lookup it protects.
_INDEX_CACHE: tuple[float, dict] | None = None


def _prices_by_key() -> dict:
    global _INDEX_CACHE
    mtime = _mtime_or_zero(fn500_prices_data_dir() / _PRICES_FILE)
    if _INDEX_CACHE is not None and _INDEX_CACHE[0] == mtime:
        return _INDEX_CACHE[1]
    df = fn501_load_price_lists()
    index: dict = {}
    if not df.empty:
        keys = [fn503_normalise_product_key(n, m)
                for n, m in zip(df["product"], df["manufacturer"])]
        manus = df["manufacturer"].astype(str).str.strip().str.casefold()
        index = {group: rows.drop(columns=["_key", "_manu"])
                 for group, rows in df.assign(_key=keys, _manu=manus)
                                      .groupby(["_manu", "_key"], sort=False)}
    _INDEX_CACHE = (mtime, index)
    return index


def _thickness_bounds(value) -> tuple[float | None, float | None]:
    """'100' -> (100, 100); '50-240' -> (50, 240); anything else -> (None, None)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return (None, None)
    txt = str(value).strip().replace(",", ".")
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", txt)]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def _thermal_resistance(row) -> float | None:
    """R (m²K/W) for a listino row — as printed if the family prints it, else d/λ."""
    printed = row.get("R_m2KW")
    if printed is not None and not pd.isna(printed):
        return float(printed)
    thickness = row.get("thickness_mm")
    lam = row.get("lambda_WmK")
    if lam is None or pd.isna(lam):
        lam = row.get("lambda_declared_WmK")
    if thickness is None or pd.isna(thickness) or lam is None or pd.isna(lam) or not lam:
        return None
    return round((float(thickness) / 1000.0) / float(lam), 2)


def fn505_price_rows_for_product(manufacturer: str, product_name: str,
                                 thickness=None) -> pd.DataFrame:
    """Listino rows for one catalogue product, optionally narrowed to a thickness."""
    index = _prices_by_key()
    manu = str(manufacturer or "").strip().casefold()
    found = [index[(manu, key)] for key in fn504_product_keys(product_name, manufacturer)
             if (manu, key) in index]
    if not found:
        return pd.DataFrame(columns=_PRICE_COLUMNS)
    hit = pd.concat(found) if len(found) > 1 else found[0]
    low, high = _thickness_bounds(thickness)
    if low is not None and not hit.empty:
        within = hit[hit["thickness_mm"].between(low, high)]
        hit = within if not within.empty else hit
    return hit


def fn506_price_for_product(manufacturer: str, product_name: str,
                            thickness=None) -> dict:
    """One price indication for a catalogue row.

    Returns ``{}`` when the product is not in any listino. ``exact`` is True when
    a single SKU matched the thickness, False when the figure is the span of a
    product family (a catalogue row covering several thicknesses).
    """
    index = _prices_by_key()
    manu = str(manufacturer or "").strip().casefold()
    if not any((manu, key) in index for key in fn504_product_keys(product_name, manufacturer)):
        return {}                       # most of the catalogue: no listino at all
    rows = fn505_price_rows_for_product(manufacturer, product_name, thickness)
    if rows.empty:
        return {}
    unit = next((c for c in ("price_eur_m2", "price_eur_m3", "price_eur_kg")
                 if rows[c].notna().any()), None)
    if unit is None:
        return {}
    values = rows[unit].dropna()
    low, high = _thickness_bounds(thickness)
    # one price for that thickness — several rows only because the same SKU is
    # listed in more than one packaging (pacchi / lastre su pallet)
    exact = bool(low is not None and low == high
                 and values.max() - values.min() <= _SAME_PRICE_TOLERANCE)
    first = rows.iloc[0]
    price = round(float(values.mean()), 2) if exact else None
    resistance = _thermal_resistance(first)
    return {
        "unit": unit.replace("price_eur_", ""),
        "price": price,
        "R_m2KW": resistance,
        # what a m² of this product costs per unit of thermal resistance — the
        # comparison that matters when the design fixes U, not thickness
        "price_per_R": (round(price / resistance, 2)
                        if price is not None and resistance else None),
        "price_min": float(values.min()),
        "price_max": float(values.max()),
        "exact": exact,
        "currency": first.get("currency", "EUR"),
        "price_basis": first.get("price_basis"),
        "availability": first.get("availability") if exact else None,
        "product": first.get("product"),
        "listino_edition": first.get("listino_edition"),
        "source_url": first.get("source_url"),
        "n_sku": int(len(values)),
    }


def fn507_attach_prices(df: pd.DataFrame,
                        manufacturer_col: str = "A__Manufacturer",
                        product_col: str = "A__ProductName",
                        thickness_col: str = "P__Thick_mm") -> pd.DataFrame:
    """Add ``PR__*`` columns (price, span, unit, display text, edition, link).

    Safe on any frame: rows whose manufacturer publishes no listino simply get
    empty values, so the caller can attach prices once for the whole dataset.
    """
    out = df.copy()
    if out.empty or not _prices_by_key():
        for col in PRICE_UI_COLUMNS:
            if col not in out.columns:
                out[col] = None
        return out
    for col in (manufacturer_col, product_col, thickness_col):
        if col not in out.columns:
            out[col] = None
    quotes = [fn506_price_for_product(manu, product, thick)
              for manu, product, thick in zip(out[manufacturer_col],
                                              out[product_col],
                                              out[thickness_col])]
    out["PR__Price_EUR"] = [q.get("price") for q in quotes]
    # chart axes: only the SKU-exact figures, so a family span never plots as if
    # it were one product's price
    out["PR__Price_EUR_m2"] = [q.get("price") if q.get("unit") == "m2" else None
                               for q in quotes]
    out["PR__Cost_per_R"] = [q.get("price_per_R") if q.get("unit") == "m2" else None
                             for q in quotes]
    out["PR__R_m2KW"] = [q.get("R_m2KW") for q in quotes]
    out["PR__Price_Min_EUR"] = [q.get("price_min") for q in quotes]
    out["PR__Price_Max_EUR"] = [q.get("price_max") for q in quotes]
    out["PR__Price_Unit"] = [q.get("unit") for q in quotes]
    out["PR__Price_Exact"] = [q.get("exact") for q in quotes]
    out["PR__Price_Display"] = [fn508_format_price(q) for q in quotes]
    out["PR__Listino_Edition"] = [q.get("listino_edition") for q in quotes]
    out["PR__Listino_URL"] = [q.get("source_url") for q in quotes]
    return out


def fn508_format_price(quote: dict, with_edition: bool = False) -> str:
    """'€ 8,05 /m²' — or '€ 4,45 – 17,54 /m²' for a family span. '' if unpriced."""
    if not quote:
        return ""
    unit = {"m2": "m²", "m3": "m³", "kg": "kg"}.get(quote.get("unit"), quote.get("unit"))

    def money(value: float) -> str:
        return f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")

    if quote.get("exact") and quote.get("price") is not None:
        text = f"€ {money(quote['price'])} /{unit}"
    else:
        text = f"€ {money(quote['price_min'])} – {money(quote['price_max'])} /{unit}"
    if with_edition and quote.get("listino_edition"):
        text += f" (listino {quote['listino_edition']})"
    return text


def fn509_price_coverage(df: pd.DataFrame,
                         manufacturer_col: str = "A__Manufacturer",
                         product_col: str = "A__ProductName",
                         thickness_col: str = "P__Thick_mm") -> pd.DataFrame:
    """Per catalogue row: whether a listino price was found, and on what basis."""
    priced = fn507_attach_prices(df, manufacturer_col, product_col, thickness_col)
    cols = [c for c in ("0__EETRA_ID", manufacturer_col, product_col, thickness_col)
            if c in priced.columns]
    report = priced[cols + ["PR__Price_EUR", "PR__Price_Min_EUR", "PR__Price_Max_EUR",
                            "PR__Price_Unit", "PR__Price_Exact"]].copy()
    report["matched"] = report["PR__Price_Min_EUR"].notna()
    return report


def fn510_supplements_for_family(manufacturer: str, family: str) -> pd.DataFrame:
    """Accessories / coatings / surcharges published with a family's listino."""
    df = fn502_load_price_supplements()
    if df.empty:
        return df
    manu = str(manufacturer or "").strip().casefold()
    fam = str(family or "").strip().casefold()
    return df[(df["manufacturer"].astype(str).str.casefold() == manu)
              & (df["family"].astype(str).str.casefold() == fam)]


# Columns of a rendered listino table, in the order the manufacturer prints them.
# A column is only shown when the product's rows actually carry it, so a roll
# listino stays as narrow as it is on paper and the XPS one keeps λ / R / €/m³.
_TABLE_COLUMNS = [
    # a reseller's own article name, where one product of the catalogue is sold
    # as a range of named articles (GAIVI's Iris tiles); empty for every listino
    # whose rows are the product itself, and then left out of the table
    ("article", "Articolo", "text"),
    ("product_code", "Codice prodotto", "text"),
    ("thickness_mm", "Spessore mm", "int"),
    ("dimensions_m", "Dimensioni m", "text"),
    ("lambda_WmK", "λ W/mK", "lambda"),
    ("R_m2KW", "R m²K/W", "num2"),
    ("weight_kg", "Peso kg", "num2"),
    ("price_eur_m2", "Prezzo €/m²", "money"),
    ("price_eur_m3", "Prezzo €/m³", "money"),
    ("price_eur_kg", "Prezzo €/kg", "money"),
    ("availability", "Dis.", "text"),
    ("min_order_pallets", "Q.tà min. n° pallet", "int"),
    ("units_per_pack", "Confezione n° pz", "int"),
    ("pack_m2", "Confezione m²", "num2"),
    ("packs_per_pallet", "Pallet n° conf.", "int"),
    ("pallet_m2", "Pallet m²", "num2"),
    ("pallet_kg", "Pallet kg", "num2"),
    ("packaging", "Confezionamento", "text"),
]


def _fmt_cell(value, kind: str) -> str:
    """Italian number formatting, matching how the listino itself prints it."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return "–"
    if kind == "text":
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "int":
        if number != int(number):             # a 12,5 mm board is not a 12 mm one
            return f"{number:.1f}".replace(".", ",")
        return f"{number:,.0f}".replace(",", ".")
    if kind == "lambda":
        return f"{number:.3f}".replace(".", ",")
    digits = 2
    return f"{number:,.{digits}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def fn511_price_table_for_product(manufacturer: str, product_name: str,
                                  thickness=None) -> dict:
    """The product's whole listino table, formatted for display.

    Every SKU of the matched product is returned — not only the one matching the
    catalogue row's thickness — because that is the point of the table: a MatLib
    entry covering 50–240 mm opens onto the twelve thicknesses the manufacturer
    actually sells, with code, size, price, availability and packaging. The rows
    matching the catalogue entry's own thickness are flagged ``highlight``.
    """
    rows = fn505_price_rows_for_product(manufacturer, product_name)  # no narrowing
    if rows.empty:
        return {}
    rows = rows.sort_values(["packaging", "thickness_mm"], na_position="first")
    columns = [(key, label, kind) for key, label, kind in _TABLE_COLUMNS
               if key in rows.columns and rows[key].notna().any()]
    low, high = _thickness_bounds(thickness)
    # Highlighting is only informative when the catalogue entry names one
    # thickness. For an entry covering a range, every row would match and the
    # highlight would say nothing — the range itself is stated in the header.
    single = low is not None and low == high
    out_rows = []
    for _, row in rows.iterrows():
        thick = row.get("thickness_mm")
        highlight = bool(single and thick is not None and not pd.isna(thick)
                         and float(thick) == low)
        out_rows.append({"highlight": highlight,
                         "cells": [_fmt_cell(row.get(key), kind)
                                   for key, _, kind in columns]})
    first = rows.iloc[0]
    return {
        "product": str(first.get("product") or ""),
        "family": str(first.get("family") or ""),
        "manufacturer": str(first.get("manufacturer") or ""),
        "edition": str(first.get("listino_edition") or ""),
        "basis": str(first.get("price_basis") or ""),
        "source_url": str(first.get("source_url") or ""),
        "source_page": int(first.get("source_page")) if pd.notna(first.get("source_page")) else None,
        "columns": [label for _, label, _ in columns],
        "rows": out_rows,
        "n_sku": len(out_rows),
        # a reseller's web price is not the manufacturer's listino, and the UI says so
        "is_reseller": "rivenditore" in str(first.get("price_basis") or "").lower(),
        "availability_legend": AVAILABILITY_LEGENDS.get(
            str(first.get("manufacturer") or "").strip().casefold(), ""),
        # what the catalogue entry itself covers, so the popup can say why it is
        # showing twelve rows for one card
        "entry_thickness": str(thickness) if thickness is not None
        and not (isinstance(thickness, float) and pd.isna(thickness)) else "",
        "entry_is_range": bool(low is not None and low != high),
    }


_TABLE_MEMO: dict = {"mtime": None, "tables": {}}


def fn512_price_tables_payload(df: pd.DataFrame,
                               id_col: str = "0__EETRA_ID",
                               manufacturer_col: str = "A__Manufacturer",
                               product_col: str = "A__ProductName",
                               thickness_col: str = "P__Thick_mm") -> dict:
    """``{EETRA id: fn511 table}`` for the rows of *df* that have a listino.

    One table per product, shared by every catalogue row of that product, so the
    payload stays small (a few tens of rows even for the full catalogue).
    """
    if df.empty or not _prices_by_key() or id_col not in df.columns:
        return {}
    # Tables memoised across calls (not just within one), per price-list version:
    # the Catalogue rebuilt every table on every rerun. Treat them as read-only.
    mtime = _mtime_or_zero(fn500_prices_data_dir() / _PRICES_FILE)
    if _TABLE_MEMO["mtime"] != mtime:
        _TABLE_MEMO.update(mtime=mtime, tables={})
    by_product: dict = _TABLE_MEMO["tables"]
    tables: dict = {}
    for eid, manu, product, thick in zip(df[id_col], df.get(manufacturer_col, ""),
                                         df.get(product_col, ""),
                                         df.get(thickness_col, None)):
        cache_key = (str(manu), str(product), str(thick))
        if cache_key not in by_product:
            by_product[cache_key] = fn511_price_table_for_product(manu, product, thick)
        table = by_product[cache_key]
        if table:
            tables[str(eid)] = table
    return tables
