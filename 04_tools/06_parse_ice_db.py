"""
Parse ICE DB Advanced V4.1 (Oct 2025) Excel file into JSON.
Extracts all material data from the ICE Summary sheet.
"""

import json
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
import openpyxl

ROOT = Path(__file__).parent.parent
EXCEL_PATH = ROOT / "01_data" / "ICE DB Advanced V4.1 - Oct 2025" / "ICE DB Advanced V4.1 - Oct 2025.xlsx"
OUTPUT_PATH = ROOT / "01_data" / "ice_db.json"

MAIN_CATEGORIES = {
    "Aggregates and Sand",
    "Aluminium",
    "Asphalt",
    "Bitumen",
    "Brass",
    "Bricks",
    "Bronze",
    "Carpet",
    "Cement and Mortar",
    "Ceramics",
    "Clay",
    "Concrete",
    "Copper",
    "Glass",
    "Insulation",
    "Iron",
    "Lead",
    "Lime",
    "Linoleum",
    "Miscellaneous",
    "Paint",
    "Paper",
    "Plastics",
    "Plaster",
    "Rubber",
    "Sealants and Adhesives",
    "Soil",
    "Steel",
    "Stone",
    "Timber",
    "Tin",
    "Titanium",
    "Vinyl",
    "Zinc",
}

METADATA_PREFIXES = (
    "ICE DB Version",
    "Is this version",
    "Check if this copy",
    "INVENTORY OF CARBON",
    "Lookup Name In ICE DB",
    "Introduction",
    "Materials covered",
    "<<< End",
    "<<<",
)

SKIP_COL_T = {
    "Name Exactly as in ICE DB",
    "Lookup Name In ICE DB [Hide these]",
}

NO_VALUE_PHRASES = (
    "data has been removed",
    "no gwp data",
    "these gwp references from the ice v2.0 dataset have",
    "gwp data not available",
    "no data",
)


def is_metadata_row(text: str) -> bool:
    return any(text.startswith(p) for p in METADATA_PREFIXES)


def extract_section_unit(col_g) -> str:
    """
    Infer the EC unit from a table header's col_g text.
    Returns one of: 'kg', 'tonne', 'm2', 'm3', 'unit'.
    """
    if not col_g or not isinstance(col_g, str):
        return "kg"
    s = col_g.lower().strip()
    if "per tonne" in s or "/tonne" in s:
        return "tonne"
    if "/m2" in s or "per m2" in s or "m²" in s:
        return "m2"
    if "/m3" in s or "per m3" in s or "m³" in s:
        return "m3"
    if "per unit" in s:
        return "unit"  # unit will come from col_i of each data row
    return "kg"


def is_table_header(col_f, col_g) -> bool:
    """True for rows like 'Materials | Embodied Carbon...' that are column headers."""
    if not col_f:
        return False
    f = str(col_f).strip()
    if f in {"Materials", "worldsteel Data", "Calculated steel data"}:
        return True
    # Header row where col_f = "In-Situ Concrete" used as section label alongside unit col_g
    if col_g and isinstance(col_g, str) and "kgCO2e" in col_g:
        return True
    return False


def is_unit_string(val) -> bool:
    """True when col_g holds a unit label (multi-unit brick/precast style rows)."""
    if val is None or isinstance(val, (int, float)):
        return False
    s = str(val).strip().lower()
    return s in {"m", "kg", "m2", "m3", "each", "m²", "m³", "1"}


def parse_ec_value(val) -> tuple[float | None, str | None]:
    """
    Returns (numeric_float, raw_string_note).
    raw_string_note is set when the cell contains text (legacy or removed data).
    """
    if val is None:
        return None, None
    if isinstance(val, (int, float)):
        return float(val), None
    s = str(val).strip()
    if any(p in s.lower() for p in NO_VALUE_PHRASES):
        return None, s
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)", s)
    if m:
        return float(m.group(1)), s
    return None, s


def extract_col8_unit(col_i) -> str | None:
    """Try to extract a simple unit string from col_i (e.g. 'm2' from a longer description)."""
    if col_i is None:
        return None
    s = str(col_i).strip().lower()
    if s in {"m", "kg", "m2", "m3", "each", "m²", "m³", "#n/a", " "}:
        return s if s not in {"#n/a", " "} else None
    # Longer description like "1 m2, per 100mm depth..."
    for unit in ("m2", "m3", "m", "each"):
        if unit in s:
            return unit
    return None


def parse_summary_sheet(ws) -> list[dict]:
    materials = []
    current_category = "Unknown"
    current_subcategory: str | None = None
    ice_version_note: str | None = None
    current_section_unit: str = "kg"   # tracks unit declared by table header
    last_col8_unit: str | None = None  # for 'unit' sections, carries forward from first data row
    row_num = 0
    done = False

    for raw_row in ws.iter_rows(values_only=True):
        row_num += 1
        if done:
            break

        row = tuple(raw_row) + (None,) * max(0, 25 - len(raw_row))

        col_e = row[4]   # extra label column (sometimes holds "kgCO2e per tonne" etc.)
        col_f = row[5]   # material name or category header
        col_g = row[6]   # EC value (per section unit) OR declared-unit string OR header text
        col_h = row[7]   # EC per declared-unit (multi-unit rows)
        col_i = row[8]   # mass per unit OR unit string (multi-unit rows)
        col_j = row[9]   # comments
        col_k = row[10]  # DQI score
        col_l = row[11]  # DQI version
        col_t = row[19]  # lookup name

        # End sentinel
        if col_f and isinstance(col_f, str) and col_f.strip().startswith("<<< End"):
            done = True
            continue

        # Empty row
        if col_f is None and col_g is None and col_t is None:
            continue

        # ------------------------------------------------------------------ #
        # Category / sub-category header rows (col_g is None, col_t is None)
        if col_f and col_g is None and col_t is None:
            text = str(col_f).strip()
            if is_metadata_row(text):
                continue
            if len(text) > 80:
                continue
            if text.startswith("Version:"):
                ice_version_note = text.replace("Version:", "").strip()
                continue
            if text in MAIN_CATEGORIES:
                current_category = text
                current_subcategory = None
                ice_version_note = None
                current_section_unit = "kg"
            else:
                current_subcategory = text
            continue

        # ------------------------------------------------------------------ #
        # Table header rows: detect and extract section unit
        # IMPORTANT: check this BEFORE the SKIP_COL_T check, because table
        # header rows often have col_t = "Name Exactly as in ICE DB".
        if col_f and isinstance(col_f, str) and is_table_header(col_f, col_g):
            # Try col_g first, then col_e for unit declaration
            unit_from_g = extract_section_unit(col_g)
            unit_from_e = extract_section_unit(col_e) if col_e else "kg"
            # Non-kg unit in either column wins
            if unit_from_g != "kg":
                current_section_unit = unit_from_g
            elif unit_from_e != "kg":
                current_section_unit = unit_from_e
            else:
                current_section_unit = "kg"
            last_col8_unit = None
            continue

        # ------------------------------------------------------------------ #
        # Skip col_t sub-headers (only after table header check above)
        if col_t is not None and str(col_t).strip() in SKIP_COL_T:
            continue

        # ------------------------------------------------------------------ #
        # Data rows
        if col_f is None:
            continue
        if col_g is None and col_t is None:
            continue

        material_name = str(col_f).strip()
        if is_metadata_row(material_name):
            continue

        lookup_name = (
            str(col_t).strip()
            if (col_t and str(col_t).strip() not in SKIP_COL_T)
            else material_name
        )

        # ------------------------------------------------------------------ #
        # Determine row type
        multi_unit = is_unit_string(col_g)
        # "Declared Units" table style (brick walls): col_g is NUMERIC 1
        # (quantity), col_h = EC per unit, col_i = unit string. is_unit_string
        # rejects numerics, so detect it here.
        if (
            not multi_unit
            and isinstance(col_g, (int, float))
            and float(col_g) == 1.0
            and isinstance(col_h, (int, float))
            and extract_col8_unit(col_i)
        ):
            multi_unit = True

        if multi_unit:
            # Brick-wall / precast style: col_g = unit or "1", col_h = EC, col_i = unit/mass
            unit_in_g = str(col_g).strip().lower()
            if unit_in_g in ("1", "1.0"):
                ec_per_unit_val = col_h
                declared_unit = str(col_i).strip() if col_i is not None else "unit"
                mass_per_unit = None
            else:
                declared_unit = unit_in_g
                ec_per_unit_val = col_h
                if isinstance(col_i, (int, float)):
                    mass_per_unit = float(col_i)
                elif col_i and re.match(r"^[0-9]+(?:\.[0-9]+)?$", str(col_i).strip()):
                    mass_per_unit = float(str(col_i).strip())
                else:
                    mass_per_unit = None

            ec_per_unit, ec_text = parse_ec_value(ec_per_unit_val)

            if declared_unit.lower() == "kg" and ec_per_unit is not None:
                ec_per_kg = ec_per_unit
            elif mass_per_unit and ec_per_unit:
                ec_per_kg = ec_per_unit / mass_per_unit
            else:
                ec_per_kg = None

        else:
            # Standard or section-unit row: col_g holds numeric EC value
            ec_raw, ec_text = parse_ec_value(col_g)

            if current_section_unit == "tonne":
                ec_per_unit = ec_raw
                ec_per_kg = ec_raw / 1000.0 if ec_raw is not None else None
                declared_unit = "tonne"
                mass_per_unit = None

            elif current_section_unit in ("m2", "m3"):
                ec_per_unit = ec_raw
                ec_per_kg = None
                declared_unit = current_section_unit
                mass_per_unit = None

            elif current_section_unit == "unit":
                # Unit comes from col_i of each data row (or inherited from first row)
                col8_unit = extract_col8_unit(col_i)
                if col8_unit:
                    last_col8_unit = col8_unit
                declared_unit = last_col8_unit or "unit"
                ec_per_unit = ec_raw
                ec_per_kg = None
                mass_per_unit = None

            else:  # "kg"
                ec_per_kg = ec_raw
                ec_per_unit = ec_raw
                declared_unit = "kg"
                mass_per_unit = None

        # ------------------------------------------------------------------ #
        dqi_score = float(col_k) if isinstance(col_k, (int, float)) else None
        dqi_version = str(col_l).strip() if col_l is not None else None
        comments = str(col_j).strip() if col_j is not None else None

        is_legacy = (
            ice_version_note is not None
            or (ec_per_kg is None and declared_unit == "kg" and ec_text is not None)
            or (ec_text is not None and "?" in ec_text)
        )

        record = {
            "lookup_name": lookup_name,
            "name": material_name,
            "category": current_category,
            "subcategory": current_subcategory,
            "ec_kgco2e_per_kg": round(ec_per_kg, 8) if ec_per_kg is not None else None,
            "ec_kgco2e_per_unit": round(ec_per_unit, 8) if (ec_per_unit is not None and declared_unit != "kg") else None,
            "declared_unit": declared_unit,
            "mass_per_unit_kg": round(mass_per_unit, 4) if mass_per_unit else None,
            "dqi_score": round(dqi_score, 6) if dqi_score else None,
            "dqi_version": dqi_version,
            "comments": comments,
            "ice_version": ice_version_note if is_legacy else "V4.1",
            "is_legacy": is_legacy,
            "ec_value_raw": ec_text if (ec_text and (is_legacy or ec_text != str(ec_per_kg))) else None,
            "source_row": row_num,
        }
        materials.append(record)

    return materials


def build_output(materials: list[dict]) -> dict:
    categories: dict[str, int] = {}
    for m in materials:
        cat = m["category"]
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "metadata": {
            "source": "ICE Database Advanced V4.1 - Oct 2025",
            "source_file": "ICE DB Advanced V4.1 - Oct 2025.xlsx",
            "publisher": "Circular Ecology",
            "url": "https://circularecology.com/embodied-energy-and-carbon-footprint-database.html",
            "parsed_date": "2026-06-12",
            "total_materials": len(materials),
            "categories": dict(sorted(categories.items())),
            "fields": {
                "lookup_name": "Exact material name used as key in ICE DB formulas",
                "name": "Display name from the spreadsheet",
                "category": "Top-level material category",
                "subcategory": "Sub-category or section heading within the category (may be null)",
                "ec_kgco2e_per_kg": "Embodied carbon, kg CO2e per kg (A1-A3 cradle to gate). Null for per-area/per-unit entries.",
                "ec_kgco2e_per_unit": "Embodied carbon per declared_unit (for m2/m3/tonne/each entries). Null for per-kg entries.",
                "declared_unit": "Reference unit: kg (most materials), m2 (glazing, walls), m3 (concrete by volume), tonne (asphalt mixed at plant), each (concrete blocks), unit (other).",
                "mass_per_unit_kg": "Mass per declared unit in kg (provided for some multi-unit entries).",
                "dqi_score": "Data Quality Index score 0-1 (higher = better). Null for legacy ICE V2.0 data.",
                "dqi_version": "DQI methodology version.",
                "comments": "Source notes, assumptions, and applicability guidance.",
                "ice_version": "ICE version this entry originates from (V4.1, ICE V4.0 2024, ICE V3.0 2019, ICE V2.0 2011).",
                "is_legacy": "True if pre-V4.1 data that has not been updated.",
                "ec_value_raw": "Original text for legacy entries where numeric extraction was approximate.",
                "source_row": "Source row in the ICE Summary worksheet (for debugging).",
            },
        },
        "materials": materials,
    }


def main():
    print(f"Loading: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True)

    print("Parsing ICE Summary sheet...")
    ws = wb["ICE Summary"]
    materials = parse_summary_sheet(ws)
    wb.close()

    print(f"  Parsed {len(materials)} material entries")

    output = build_output(materials)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {OUTPUT_PATH}")
    print(f"Total materials: {output['metadata']['total_materials']}")
    print(f"  with ec_kgco2e_per_kg: {sum(1 for m in materials if m['ec_kgco2e_per_kg'] is not None)}")
    print(f"  with ec_kgco2e_per_unit (non-kg): {sum(1 for m in materials if m['ec_kgco2e_per_unit'] is not None)}")
    print(f"  legacy/text-only: {sum(1 for m in materials if m['is_legacy'])}")
    print("\nCategory breakdown:")
    for cat, count in output["metadata"]["categories"].items():
        print(f"  {cat}: {count}")
    print("\nUnit breakdown:")
    from collections import Counter
    units = Counter(m["declared_unit"] for m in materials)
    for unit, count in units.most_common():
        print(f"  {unit}: {count}")


if __name__ == "__main__":
    main()
