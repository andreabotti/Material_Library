"""Tests for libs/lib_prices.py — the listino price layer and its catalogue match.

These run against the real ``01_data/price_lists.parquet`` (written by
``04_tools/13_parse_price_lists.py``): the point is that the shipped price data
still joins to the shipped catalogue, which is what breaks when either side is
regenerated. They skip themselves when the parquet is absent.
"""
from __future__ import annotations

import pandas as pd
import pytest

from libs import lib_prices as lp

pytestmark = pytest.mark.skipif(
    not (lp.fn500_prices_data_dir() / "price_lists.parquet").exists(),
    reason="price_lists.parquet not built — run 04_tools/13_parse_price_lists.py",
)


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    return lp.fn501_load_price_lists()


def test_every_row_has_a_price_in_some_unit(prices):
    units = ["price_eur_m2", "price_eur_m3", "price_eur_kg"]
    assert prices[units].notna().any(axis=1).all()


def test_prices_are_positive_and_sane(prices):
    m2 = prices["price_eur_m2"].dropna()
    assert (m2 > 0).all()
    assert m2.max() < 1000          # a listino €/m² in the hundreds, never more


def test_every_row_carries_its_source(prices):
    for col in ("listino_edition", "source_url", "product"):
        assert prices[col].notna().all(), col
    # a printed page number only exists for PDF listini, not for a reseller's web page
    pdf = prices[prices["source_doc"].str.endswith(".pdf")]
    assert pdf["source_page"].notna().all()


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Tectonic FP Basic - 100 mm", "TECTONICFPBASIC"),
        ("Pureone zero 31- 45 mm", "PUREONEZERO31"),
        ("URSA XPS ECO NIII L", "XPSNIIIL"),        # "ECO" is not discriminating
        ("XPS ECO NV L - 50 mm", "XPSNVL"),
    ],
)
def test_normalise_product_key(name, expected):
    assert lp.fn503_normalise_product_key(name) == expected


def test_alternative_namings_both_match():
    # the catalogue writes "XPS ECO | XPS NR", the listino "URSA XPS ECO NR"
    keys = lp.fn504_product_keys("XPS ECO | XPS NR - 20 mm")
    assert "XPSNR" in keys


def test_exact_thickness_gives_one_price():
    quote = lp.fn506_price_for_product("Ursa", "Tectonic FP Basic - 100 mm", "100")
    assert quote["exact"] is True
    assert quote["price"] == pytest.approx(52.96)
    assert quote["unit"] == "m2"
    assert lp.fn508_format_price(quote) == "€ 52,96 /m²"


def test_thickness_range_gives_a_span_not_a_price():
    quote = lp.fn506_price_for_product("Ursa", "Glasswool DF 39", "50-240")
    assert quote["exact"] is False
    assert quote["price"] is None
    assert quote["price_min"] < quote["price_max"]
    assert "–" in lp.fn508_format_price(quote)


def test_unknown_product_returns_empty_quote():
    assert lp.fn506_price_for_product("Ursa", "Glasswool AKP 5/Nb", "50-120") == {}
    assert lp.fn506_price_for_product("Nonexistent Co", "Whatever - 50 mm", "50") == {}
    assert lp.fn508_format_price({}) == ""


def test_cost_per_R_is_price_over_resistance():
    quote = lp.fn506_price_for_product("Ursa", "XPS ECO | XPS NIII L - 100 mm", "100")
    assert quote["R_m2KW"] > 0
    assert quote["price_per_R"] == pytest.approx(quote["price"] / quote["R_m2KW"], abs=0.02)


def test_attach_prices_adds_every_ui_column_even_without_a_match():
    df = pd.DataFrame({"A__Manufacturer": ["Nonexistent Co"],
                       "A__ProductName": ["Whatever"],
                       "P__Thick_mm": ["50"]})
    out = lp.fn507_attach_prices(df)
    for col in lp.PRICE_UI_COLUMNS:
        assert col in out.columns
    assert out["PR__Price_Display"].iloc[0] == ""


def test_attach_prices_leaves_the_catalogue_columns_untouched():
    df = pd.DataFrame({"A__Manufacturer": ["Ursa"],
                       "A__ProductName": ["Tectonic FP Basic - 100 mm"],
                       "P__Thick_mm": ["100"]})
    out = lp.fn507_attach_prices(df)
    pd.testing.assert_frame_equal(out[df.columns], df)
    assert out["PR__Price_EUR_m2"].iloc[0] == pytest.approx(52.96)


def test_full_table_matches_the_printed_listino():
    """URSA GLASSWOOL DF 39, page 9 of the Giugno 2026 listino, all 12 rows."""
    table = lp.fn511_price_table_for_product("Ursa", "Glasswool DF 39", "50-240")
    assert table["product"] == "URSA GLASSWOOL DF 39"
    assert table["n_sku"] == 12
    assert table["columns"][:4] == ["Codice prodotto", "Spessore mm",
                                    "Dimensioni m", "Prezzo €/m²"]
    assert table["rows"][0]["cells"][:4] == ["2082192", "50", "7,50 x 1,20", "5,09"]
    assert table["rows"][-1]["cells"][:4] == ["2081942", "240", "3,10 x 1,20", "22,30"]
    assert table["source_page"] == 9
    assert "IVA esclusa" in table["basis"]


def test_range_entry_opens_the_whole_family_without_highlighting_everything():
    table = lp.fn511_price_table_for_product("Ursa", "Glasswool DF 39", "50-240")
    assert table["entry_is_range"] is True
    assert not any(r["highlight"] for r in table["rows"])


def test_single_thickness_entry_highlights_its_own_sku():
    table = lp.fn511_price_table_for_product("Ursa", "Tectonic FP Basic - 100 mm", "100")
    assert table["entry_is_range"] is False
    flagged = [r for r in table["rows"] if r["highlight"]]
    assert len(flagged) == 1
    assert flagged[0]["cells"][1] == "100"
    # the table still lists the whole product, not only the matching thickness
    assert table["n_sku"] > 1


def test_table_columns_follow_what_the_family_prints():
    xps = lp.fn511_price_table_for_product("Ursa", "XPS ECO | XPS NIII L - 100 mm", "100")
    assert "Prezzo €/m³" in xps["columns"] and "λ W/mK" in xps["columns"]
    rolls = lp.fn511_price_table_for_product("Ursa", "Glasswool DF 39", "50-240")
    assert "Prezzo €/m³" not in rolls["columns"] and "λ W/mK" not in rolls["columns"]


def test_tables_payload_is_keyed_by_eetra_id():
    df = pd.DataFrame({"0__EETRA_ID": ["INS__FIB__0001", "INS__FIB__0002"],
                       "A__Manufacturer": ["Ursa", "Nonexistent Co"],
                       "A__ProductName": ["Glasswool DF 39", "Whatever"],
                       "P__Thick_mm": ["50-240", "50"]})
    payload = lp.fn512_price_tables_payload(df)
    assert set(payload) == {"INS__FIB__0001"}          # unpriced rows carry no table
    assert payload["INS__FIB__0001"]["n_sku"] == 12


# ---- Knauf Insulation (listino prezzi edilizia, Maggio 2026) ----------------

def test_knauf_table_matches_the_printed_listino():
    """Mineral Wool 35, printed page 10: seven rows, 40 → 120 mm."""
    table = lp.fn511_price_table_for_product("Knauf", "Mineral Wool 35", "40-120")
    assert table["product"] == "Mineral Wool 35"
    assert table["n_sku"] == 7
    assert table["edition"] == "Maggio 2026"
    assert table["source_page"] == 10
    first, last = table["rows"][0]["cells"], table["rows"][-1]["cells"]
    cols = table["columns"]
    assert first[cols.index("Codice prodotto")] == "784144"
    assert first[cols.index("Prezzo €/m²")] == "6,27"
    assert first[cols.index("R m²K/W")] == "1,10"
    assert last[cols.index("Spessore mm")] == "120"
    assert last[cols.index("Prezzo €/m²")] == "18,97"


def test_knauf_lambda_is_filled_for_every_row_of_a_table(prices):
    # the Knauf Insulation listino (the Knauf boards priced at ATA carry no lambda)
    knauf = prices[prices["source_doc"] == "knauf_insulation.pdf"]
    assert len(knauf) > 300
    assert knauf["lambda_declared_WmK"].notna().all()
    # R printed in the listino agrees with thickness / lambda on every row
    m2 = knauf[knauf["R_m2KW"].notna()]
    calc = m2["thickness_mm"] / 1000 / m2["lambda_declared_WmK"]
    assert ((calc - m2["R_m2KW"]).abs() <= 0.06).all()


def test_knauf_product_printed_with_two_tables_keeps_both():
    """SmartRoof TOP XL is sold as 'lastre su pallet' and 'pacchi su pallet'."""
    rows = lp.fn505_price_rows_for_product("Knauf", "SmartRoof TOP XL")
    assert set(rows["packaging"].dropna()) == {"Lastre su pallet", "Pacchi su pallet"}
    assert "549302" in set(rows["product_code"])


def test_knauf_bagged_wool_is_priced_per_kg():
    quote = lp.fn506_price_for_product("Knauf", "SUPAFIL MULTI")
    assert quote["unit"] == "kg"
    assert quote["price_min"] == pytest.approx(5.04)


def test_knauf_catalogue_name_differing_from_listino_still_matches():
    # the listino prints a bare "TPT"; the catalogue says "NaturBoard TPT"
    assert lp.fn506_price_for_product("Knauf", "NaturBoard TPT", "20")["price"] == pytest.approx(8.22)


def test_availability_legend_depends_on_the_manufacturer():
    knauf = lp.fn511_price_table_for_product("Knauf", "Mineral Wool 35", "40-120")
    ursa = lp.fn511_price_table_for_product("Ursa", "Glasswool DF 39", "50-240")
    assert "A = consegna fino a 5 giorni" in knauf["availability_legend"]
    assert "S = a stock" in ursa["availability_legend"]


# ---- Siniat via ATA Torino (reseller web prices, not a manufacturer listino) -

def test_siniat_prices_are_flagged_as_reseller_prices():
    table = lp.fn511_price_table_for_product("Siniat", "PregyPlac A1 BA13", "12.5")
    assert table["is_reseller"] is True
    assert "rivenditore" in table["basis"] and "IVA" in table["basis"]
    assert lp.fn511_price_table_for_product("Knauf", "Mineral Wool 35", "40-120")["is_reseller"] is False


def test_siniat_board_is_priced_per_m2_with_a_sane_value():
    quote = lp.fn506_price_for_product("Siniat", "PregyPlac A1 BA13", "12.5")
    assert quote["unit"] == "m2" and quote["exact"] is True
    assert 1 < quote["price"] < 40            # a plasterboard €/m², never per sheet
    table = lp.fn511_price_table_for_product("Siniat", "LaDura plus BA13", "12.5")
    col = table["columns"].index("Spessore mm")
    assert table["rows"][0]["cells"][col] == "12,5"     # 12,5 mm is not shown as 12


def test_siniat_catalogue_names_match_the_shop_names():
    for name in ("Pregydro BA13", "Pregyplac plus BA13", "LaDura plus BA13",
                 "Solidtex indoor BA13", "Aquaboard BA13"):
        assert lp.fn506_price_for_product("Siniat", name, "12.5"), name


def test_siniat_sacks_are_priced_per_kg(prices):
    sacks = prices[(prices["manufacturer"] == "Siniat") & prices["price_eur_kg"].notna()]
    assert len(sacks) == 3 and (sacks["price_eur_kg"].between(0.3, 5)).all()


# ---- ATA reseller, other brands ---------------------------------------------

def test_gyproc_eco_board_is_not_priced_as_the_plain_one():
    # "ECO" is noise only in URSA names; DuraGyp ECO is a different Gyproc board
    assert lp.fn503_normalise_product_key("DuraGyp ECO 13 Activ'Air", "Gyproc") \
        != lp.fn503_normalise_product_key("DuraGyp 13 Activ'Air", "Gyproc")
    assert lp.fn506_price_for_product("Gyproc", "DuraGyp ECO 13 Activ'Air", "12.5") == {}


def test_two_sheet_sizes_of_one_board_give_one_price():
    quote = lp.fn506_price_for_product("Gyproc", "Lisaflam 13", "12.5")
    assert quote["exact"] is True and quote["price"] is not None


def test_ata_brands_are_reseller_priced_and_matched():
    for manu, name, thick in (("Gyproc", "Fireline 13", "12.5"),
                              ("Knauf", "Lastra GKB (A) - 12.5", "12.5"),
                              ("Fassa Bortolo", "Gypsotech STD TIPO A - 13", "12.5"),
                              ("Isover (Saint Gobain)", "PAR 4+", "45-90")):
        quote = lp.fn506_price_for_product(manu, name, thick)
        assert quote, name
        assert 1 < quote["price_min"] < 60, name
        assert lp.fn511_price_table_for_product(manu, name, thick)["is_reseller"] is True, name


# ---- Iris Ceramiche via GAIVI (a retail listino, IVA included) ---------------

def test_gaivi_wall_tiles_are_one_catalogue_family_of_named_articles():
    """The listino's 63 wall tiles answer for the catalogue's wall-covering EPD."""
    name = "Ceramics for internal wall coverings"
    quote = lp.fn506_price_for_product("Iris Ceramica Group", name, "7-10.5")
    assert quote["unit"] == "m2" and quote["exact"] is False
    assert 1 < quote["price_min"] < quote["price_max"] < 100
    table = lp.fn511_price_table_for_product("Iris Ceramica Group", name, "7-10.5")
    assert table["n_sku"] == 63
    assert table["is_reseller"] is True and "IVA 22% scorporata" in table["basis"]
    # the commercial article is what the reseller sells; the product is the family
    assert table["columns"][:2] == ["Articolo", "Codice prodotto"]
    assert table["rows"][0]["cells"][0] == "ALBA 20X20 PIASTRELLA S.E."
    assert table["source_url"].startswith("http://www.gaivi.it/listini/iris-ceramiche-spa/")


def test_gaivi_floor_tiles_are_priced_but_not_matched_to_a_thickness(prices):
    """No thickness is printed, so the porcelain-stoneware families stay unpriced."""
    gaivi = prices[prices["source_doc"] == "gaivi_iris.pdf"]
    assert len(gaivi) == 159 and gaivi["price_eur_m2"].notna().all()
    assert gaivi["thickness_mm"].isna().all()
    for name in ("Porcelain stoneware ceramic (6, 8 mm)",
                 "Full body porcelain stoneware ceramic (10 mm)"):
        assert lp.fn506_price_for_product("Iris Ceramica Group", name, "10") == {}


def test_gaivi_pezzi_speciali_are_supplements_not_square_metre_prices():
    """A rosone at € 605 is one piece, and has no business in a €/m² column."""
    sup = lp.fn502_load_price_supplements()
    iris = sup[sup["manufacturer"] == "Iris Ceramica Group"]
    assert len(iris) == 125
    assert set(iris["unit"]) == {"pezzo"} and set(iris["kind"]) == {"pezzo speciale"}
    rosone = iris[iris["description"].str.contains("ROSONE")]
    assert rosone["price_eur"].iloc[0] == pytest.approx(605.00, abs=0.01)
    assert iris["price_eur"].notna().all()
