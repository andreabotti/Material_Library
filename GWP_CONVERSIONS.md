# GWP A1–A3 Conversion Factors

How one declared A1–A3 figure becomes four comparable bases — per kg, per m³, per m²
and per m² at R = 1 — which physical inputs each conversion needs, and where the
numbers are produced.

Rendered live in the app at **Developer → 📖 App Documentation → GWP conversion
factors** (that tab adds live row-coverage counts and typeset formulae). The
**➕ Add New Item** and **✏️ Edit Existing Item** forms show the same derivation
applied to the record being edited, at the bottom of the **GWP Data** tab.

All relationships below were validated against `01_data/base_data.parquet`
(1,609 rows): each holds at a median ratio of exactly 1.000 across the rows where
both sides are populated.

---

## 1. The five GWP bases

Every product carries **one** figure from its EPD — `G__GWP_A1A3`, expressed in the
unit named by `G__GWP_FU`. The `_kg` / `_m3` / `_m2` / `_m2R1` columns are *derived
views* of that same figure, never independent measurements.

| Column | Unit | One unit means | Primary use | Rows populated |
|---|---|---|---|---|
| `G__GWP_A1A3` | kg CO₂e / declared unit | The EPD figure exactly as declared, in whatever unit `G__GWP_FU` names. | Card headline, audit trail back to the EPD. | 1,533 / 1,609 |
| `G__GWP_A1A3_kg` | kg CO₂e / kg | Impact of one kilogram of product — a pure material-intensity basis. | Cross-material comparison, Revalu `gwp.a1a3` mapping. | 834 / 1,609 |
| `G__GWP_A1A3_m3` | kg CO₂e / m³ | Impact of one cubic metre of product in place. | Bulk / volumetric products: concrete, blocks, screeds, timber, insulants. | 1,293 / 1,609 |
| `G__GWP_A1A3_m2` | kg CO₂e / m² | Impact of one square metre **at the product's own declared thickness**. | Layered products: boards, tiles, membranes, finishes. | 603 / 1,609 |
| `G__GWP_A1A3_m2R1` | kg CO₂e / m²·(m²K/W) | Impact of the m² of material that delivers a thermal resistance R = 1 m²K/W. | The only functionally fair basis for comparing insulants. | 376 / 1,609 |

*Coverage as of the 2026-09 dataset; the in-app tab recomputes these counts live.*

---

## 2. Step one — anchor on the declared unit

`G__GWP_FU` states the EPD's declared unit. It decides which normalised column
receives the declared value **unchanged** (or with a pure unit factor). That column
is the anchor; every other basis is then derived from it in step 3.

| `G__GWP_FU` | Anchored column | Factor | Note |
|---|---|---|---|
| `m3` | `G__GWP_A1A3_m3` | × 1 | Declared per m³ — copied straight across. |
| `m2` | `G__GWP_A1A3_m2` | × 1 | Declared per m² at the stated thickness. |
| `kg` | `G__GWP_A1A3_kg` | × 1 | Declared per kg — copied straight across. |
| `ton` | `G__GWP_A1A3_kg` | × 0.001 | Declared per tonne → divide by 1000. |
| `m2_R1` | `G__GWP_A1A3_m2R1` | × 1 | EPD already declares the R = 1 reference unit. |
| `m` | — | — | Linear declaration (profiles, edgings). No area/volume anchor without a cross-section. |
| `unit` | — | — | Piece-based declaration. Needs pieces per m² or per m³ to normalise. |

Only `ton` carries a non-unity factor: **GWP/kg = GWP/tonne ÷ 1000**. The catalogue
card applies the same rule at display time when no `_kg` value exists
(`libs/lib_ui.py`).

Observed distribution of `G__GWP_FU`: `m3` 768, `m2` 373, `ton` 187, `kg` 115,
`m2_R1` 51, `m` 28, `unit` 7, blank 67.

---

## 3. Step two — the three physical bridges

Moving between bases needs exactly three material properties: **density**
(mass ↔ volume), **thickness** (volume ↔ area) and **conductivity**
(area ↔ thermal performance).

**Mass ↔ volume — density ρ**

$$\text{GWP}_{kg} = \frac{\text{GWP}_{m^3}}{\rho} \qquad\Longleftrightarrow\qquad \text{GWP}_{m^3} = \text{GWP}_{kg} \cdot \rho$$

**Volume ↔ area — thickness d** (stored in mm, used in m)

$$d\,[\mathrm{m}] = \frac{d\,[\mathrm{mm}]}{1000} \qquad \text{GWP}_{m^2} = \text{GWP}_{m^3} \cdot d \qquad\Longleftrightarrow\qquad \text{GWP}_{m^3} = \frac{\text{GWP}_{m^2}}{d}$$

**Area ↔ mass — mass per area m_A**

$$m_A = \rho \cdot d \qquad \text{GWP}_{kg} = \frac{\text{GWP}_{m^2}}{m_A}$$

**Area ↔ thermal performance — conductivity λ**

$$R = \frac{d}{\lambda} \quad\Rightarrow\quad \text{GWP}_{m^2R=1} = \frac{\text{GWP}_{m^2}}{R} = \text{GWP}_{m^2} \cdot \frac{\lambda}{d} = \text{GWP}_{m^3} \cdot \lambda$$

### Conversion matrix

Read as **row → column**: multiply the row basis by the cell to obtain the column basis.

| from ↓ / to → | per kg | per m³ | per m² | per m² R=1 |
|---|---|---|---|---|
| **per kg** | 1 | × ρ | × ρ·d | × ρ·λ |
| **per m³** | ÷ ρ | 1 | × d | × λ |
| **per m²** | ÷ (ρ·d) | ÷ d | 1 | × λ/d  (= ÷ R) |
| **per m² R=1** | ÷ (ρ·λ) | ÷ λ | × d/λ  (= × R) | 1 |

---

## 4. Why the R = 1 basis exists

Comparing insulants per m² or per m³ compares *quantities of material*, not *what
the material does*. 100 mm of mineral wool and 100 mm of PIR occupy the same m², but
do not deliver the same thermal resistance.

The R = 1 basis removes thickness from the comparison. Since **R = d / λ**, the
thickness that delivers R = 1 m²K/W is:

$$d_{R=1} = \lambda \cdot 1 = \lambda \quad [\mathrm{m}]$$

so the material volume behind 1 m² at R = 1 is numerically **λ m³**, and therefore:

$$\text{GWP}_{m^2R=1} = \text{GWP}_{m^3} \cdot \lambda$$

A lower λ means less material is needed for the same performance, and the R = 1
figure rewards that automatically. This is the basis the insulation charts default to.

---

## 5. Input data and fallback chains

| Symbol | Property | Primary column | Fallback / derivation | Unit |
|---|---|---|---|---|
| ρ (rho) | Bulk density | `P__Mass_kgm3` | `E__EPD_Density` | kg/m³ |
| d | Thickness | `P__Thick_mm` | `E__EPD_Thick_mm` | mm → m (÷ 1000) |
| λ | Thermal conductivity | `P__L_WmK` | `E__L_WmK` | W/(m·K) |
| m_A | Mass per area | `P__Mass_kgm2` | ρ · d | kg/m² |
| R | Thermal resistance | `E__Rvalue` | d / λ | m²K/W |

The `P__` columns hold the curated library value; the `E__` columns hold what the EPD
itself declared. `P__` wins when both are present, so a conversion always uses the
figure the library has vetted. ρ, d and m_A are over-determined (`m_A = ρ · d`) — a
row where the three disagree signals a data error, not a conversion error.

---

## 6. Worked example

**Blocco THERMO 450 – 240 mm** — a real catalogue row, declared per m³:

| Input | Value |
|---|---|
| `G__GWP_FU` | `m3` |
| `G__GWP_A1A3` | 39.8 kg CO₂e |
| `P__Mass_kgm3` (ρ) | 450 kg/m³ |
| `P__Thick_mm` (d) | 240 mm → 0.240 m |
| `P__L_WmK` (λ) | 0.108 W/(m·K) |

$$\text{GWP}_{m^3} = 39.8 \quad \text{(declared unit is } m^3,\ \text{anchored 1:1)}$$

$$\text{GWP}_{kg} = \frac{39.8}{450} = 0.08844 \;\; \mathrm{kgCO_2e/kg}$$

$$\text{GWP}_{m^2} = 39.8 \times 0.240 = 9.552 \;\; \mathrm{kgCO_2e/m^2}$$

$$\text{GWP}_{m^2R=1} = 39.8 \times 0.108 = 4.2984 \;\; \mathrm{kgCO_2e/m^2\cdot(m^2K/W)}$$

Cross-check: R = 0.240 / 0.108 = 2.222 m²K/W, and 9.552 / 2.222 = 4.298 — the same
figure reached from the m² basis.

---

## 7. Validity and caveats

- **`_m2R1` is meaningful for insulants only.** It is populated for a few
  non-insulation rows, but λ-normalisation has no functional meaning there.
  `aux__chart_value_defaults.json` restricts the column to the *Insulation* product
  type for exactly this reason.
- **`_m2` is thickness-specific.** Two rows of the same product at different
  thicknesses are not comparable on this basis — use `_m3` or `_m2R1`.
- **`_kg` ignores performance and geometry.** It answers "how carbon-intensive is
  this material?", never "how much carbon does this build-up cost?".
- **Linear (`m`) and piece (`unit`) declarations cannot be normalised** without a
  cross-section or a pieces-per-m² figure; those rows stay blank by design.
- **A conversion is only as good as its input.** A missing or wrong ρ, d or λ
  propagates silently into every derived basis.
- **Module scope is A1–A3 throughout.** A4–A5, B, C and D are never folded into
  these columns.

---

## 8. Where the conversions happen

| Stage | Location | What it does |
|---|---|---|
| Source of truth | `EETRA_MaterialLibrary.xlsx` (sheet `_live_data`) | The `_kg` / `_m3` / `_m2` / `_m2R1` columns are computed upstream and stored. The app **reads** them. |
| Ingestion | `04_tools/03_excel_to_parquet.py` | Writes `01_data/base_data.parquet`, preserving the stored conversions unchanged. |
| Data entry | `pages/13_Add_Edit_Item.py` (GWP Data tab) | Re-derives all four bases from the form's own ρ / d / λ and flags any stored value that disagrees by more than ±2%. Read-only — never written back. |
| EPD variants | `libs/lib_epd_family.py`, `pages/13_Add_Edit_Item.py` | **Written.** Products flagged N in an EPD family get reference × factor, with the four bases re-derived by the same rules — see §9. |
| Display fallbacks | `libs/lib_ui.py` (product card) | Fills gaps at render time only: tonne → kg (÷ 1000), and `_m2 ÷ P__Mass_kgm2` → per kg. Not written back. |
| Charts | `libs/lib_charts.py`, `aux__chart_value_defaults.json` | Picks the correct basis per product type and hides bases that would mislead. |
| Export | `libs/lib_revalu_send.py`, `libs/lib_revalu_map.py` | `G__GWP_A1A3_kg` maps to Revalu `gwp.a1a3`; ρ, d and λ travel with it so the receiver can re-derive the rest. |

To change a conversion of an ordinary product, edit the source workbook and re-ingest —
editing the app will not alter its stored value. EPD variants (§9) are the exception.

---

## 9. EPD families — reference product × multiplication factor

Many EPDs publish results for one **reference product** plus a table of factors for
the other products they cover (other thicknesses, facings). Two columns model this:

| Column | Value | Meaning |
|---|---|---|
| `E__EPD_ConvFactor` | `Y` | Reference product: its GWP data are the figures printed in the EPD (factor 1). |
| `E__EPD_ConvFactor` | `N` | Variant: its GWP data are the reference's × `E__EPD_MultFactor`. |

A family is every product with the same `E__EPD_RegNumber`, compared without
whitespace or case (`S-P- 01137` = `S-P-01137`). For a variant:

- `G__GWP_A1A3` and **every module** A1 … D are multiplied by the factor; non-numeric
  entries (`mnd`, `n/r`) are copied as they are.
- `G__GWP_Metric` and `G__GWP_FU` are copied from the reference.
- The four bases are re-derived (§2–§3) from the scaled A1–A3 and the variant's **own**
  ρ, d and λ. A basis those inputs cannot reach keeps its stored value rescaled by the
  change in A1–A3, so it never goes stale.

In the Add/Edit form a variant's GWP fields are filled in and locked; saving the
reference product rewrites every variant of its family in the same save (the GWP Data
tab previews which ones). Nothing is derived when the family has no product flagged Y,
more than one, or the variant has no numeric factor — the form says which.

The Excel workbook scaled only `G__GWP_A1A3` and copied A4–D unchanged; the app scales
every module, so variants differ from the workbook there after their reference is saved.
