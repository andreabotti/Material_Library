### EETRA Material Library — Database Column Reference

This document describes the **content and purpose of each column** in the Material Library database. The data is sourced from the Excel file **EETRA_MaterialLibrary.xlsx** (sheet: `_live_data`), and may also be loaded from SharePoint, local Parquet, or MotherDuck. Column names use a **prefix** (e.g. `A__`, `D__`, `P__`) to group fields by category.

---

#### Column naming convention

- **Format:** `PREFIX__FieldName` (e.g. `A__ProductName`, `G__GWP_A1A3`).
- **Prefixes** group columns for display (e.g. Details, Properties, EPD Info, GWP Data, Recycling, VOC).
- In the app, prefixes can be stripped for cleaner labels (e.g. `G__GWP_A1A3` → `GWP_A1A3`).
- The `0__` prefix marks record identifiers; single-underscore variants (`V_Test_Standard`, `V_Report_Type`, `V_CAM_Compliance`) also exist for a few VOC/CAM fields.

---

#### 0 — Record identifiers

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **0__EETRA_ID** | Product key | Strict `TYPE__SUBTYPE__NNNN` identifier (e.g. `INS__FIB__0494`). Primary key for tags, collections, media file naming, and the Add/Edit Item page. |
| **0__NUM** | Sequence number | Numeric row sequence used for ordering; auto-incremented when new items are added. |

---

#### A — Product identity & attributes

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **A__Manufacturer** | Manufacturer or brand name | Company name (e.g. Knauf, Gyproc). Used for filters, catalogue, charts, maps, and manufacturer logos. |
| **A__ProductName** | Commercial product name | Full product name as in catalogues. Used for sorting, cards, and as primary label in charts/maps. |
| **A__ProductDescription** | Product description | Free-text description / marketing summary of the product. |
| **A__ProductName_Base** | Base product (derived) | Normalized product name used for grouping variants (e.g. thickness). Populated by app logic from `A__ProductName`. |
| **A__Map_yn** | Include in map view | `Y` = show on maps; other/missing = exclude. Used to filter rows in MAPS tab and Developer "Tabular Data". |
| **A__Thickness_mm** | Thickness (attribute) | Thickness in mm when stored at product level (alternative to property thickness). |

---

#### B — Board / block attributes

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **B__Thickness_mm** | Board/block thickness | Thickness in mm for board/block products. Used in fallback chains for display (with `P__Thick_mm`, `E__EPD_Thick_mm`, etc.). |

---

#### D — Details (product type, material, technical)

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **D__ProductType_ENG** | Product type (English) | High-level type (e.g. Insulation, Building boards, Binder, In situ Concrete). Drives filter options and field visibility per product type. |
| **D__MaterialType_ENG** | Material type (English) | More specific material classification. Used in sidebar filters and tabular visibility. |
| **D__MaterialType_ITA** | Material type (Italian) | Italian-language material classification (localisation of `D__MaterialType_ENG`). |
| **D__Size** | Size / dimensions | Product size or dimensional description (free text). |
| **D__EN197-1** | Cement designation (EN 197-1) | Cement type/marking for binders (e.g. CEM I, CEM II). Shown in catalogue and tabular "Details"; visibility varies by product type. |
| **D__EN206** | Concrete class (EN 206) | Concrete exposure / strength class per EN 206 (e.g. `C25/30`, `XC1`) for in-situ concrete and related products. |
| **D__Content** | Content / composition | Text description of composition or content. Visibility varies by product type. |
| **D__TechDetails** | Technical details (text) | Free-text technical information. Can be paired with `U__TechDetails_URL`. Visibility varies by product type. |
| **D__Int/Ext** | Interior / exterior | Interior vs exterior use. Excluded from Developer "Tabular Data" Details tab by default. |
| **D__Application** | Application | Use/application (e.g. wall, floor). Excluded from Developer "Tabular Data" Details tab by default. |
| **D__DataComments** | Data comments | Internal or data-quality comments. Excluded from Developer "Tabular Data" Details tab by default. |

---

#### E — EPD & manufacturing (declarations, plant, country)

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **E__EPD_Y/N** | Has EPD | `Y` when the product has an Environmental Product Declaration; blank/other otherwise. |
| **E__EPD_Programme** | EPD programme | Programme operator / registry that published the EPD (e.g. EPD International, EPD Italy, IBU, INIES). |
| **E__EPD_RegNumber** | EPD registration number | Official EPD identifier. Used for sorting and as "EPD Num." in catalogue. |
| **E__EPD_DecNumber** | EPD declaration number | Alternative declaration number (some registries issue this alongside the registration number). Used with `E__EPD_RegNumber` for cross-matching. |
| **E__EPD_URL** | EPD document URL | Link to the EPD document. Used with `E__EPD_RegNumber` for "EPD Num." in catalogue. |
| **E__EPD_Publisher** | EPD publisher | Organisation that published the EPD. |
| **E__EPD_Type** | EPD type | Type of declaration (e.g. product-specific, generic). |
| **E__EPD_Product Name** | EPD product name | Product name exactly as it appears in the EPD (may differ from `A__ProductName`). |
| **E__EPD_IssueDate** | EPD issue date | Date the EPD was issued. |
| **E__EPD_ValidUntil** | EPD valid until | Expiry or validity end date of the EPD. |
| **E__EPD_ExpDate** | EPD expiry date | Expiry date of the EPD (used by Revalu matching to flag expired declarations). |
| **E__ServiceLife** | Service life (RSL) | Reference service life declared in the EPD. Maps to Revalu `rsl`. |
| **E__EPD_Thick_mm** | Thickness from EPD | Thickness in mm as declared in the EPD. Used in catalogue "Thickness" when combined with `P__Thick_mm`. |
| **E__EPD_Density** | Density from EPD | Density as declared in the EPD (kg/m³). |
| **E__L_WmK** | Conductivity from EPD | Thermal conductivity (λ) in W/(m·K) from EPD. Used in catalogue "Conductivity (ʎ)" with `P__L_WmK`. |
| **E__Rvalue** | Thermal resistance (R) | R-value declared in the EPD (m²·K/W). Maps to Revalu `r_value`. |
| **E__EPD_MultFactor** | Multiplication factor | Factor the EPD gives to scale its reference product's results to this product (1 on the reference). |
| **E__EPD_ConvFactor** | EPD reference product (Y/N) | `Y` = the EPD's reference product; `N` = GWP data are the reference's × `E__EPD_MultFactor`, derived automatically by the Add/Edit page (family = same `E__EPD_RegNumber`). See GWP_CONVERSIONS.md §9. |
| **E__EPD_kg-FU** | kg per functional unit | Mass (kg) corresponding to one declared functional unit; used to normalise per-kg GWP. |
| **E__Certifications** | Product certifications | Product-level certification or rating that is **not** a VOC scheme (e.g. `Green Tag Level A`); comma-separated if several. Shown in the Sustainability tab under *Responsible Sourcing* → *Product certification*. Lives in the edit log (`edits_data.parquet`), which is the working source of truth. |
| **E__Certifications_URL** | Certifications page | Page documenting `E__Certifications`; the 🔗 next to the row. Also held in the edit log. |
| **E__ManuCountry** | Manufacturing country | Country of production. Used in filters, maps (with plant), and "Manufacturing Plant" in catalogue. |
| **E__ManuPlant** | Manufacturing plant | Plant or site name. Used for maps, location cache, and "Manufacturing Plant" in catalogue. |

---

#### G — GWP (Global Warming Potential)

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **G__GWP_Metric** | GWP metric | Accounting metric / method label for the GWP figures (e.g. GWP-total per EN 15804+A2, or GWP100). |
| **G__GWP_A1A3** | GWP A1–A3 (declared unit) | Total GWP for modules A1–A3 in the EPD's declared unit (e.g. kg CO₂eq per tonne). Main GWP value for charts and catalogue. |
| **G__GWP_A1A3_kg** | GWP A1–A3 per kg | GWP for A1–A3 normalised to 1 kg of material. Maps to Revalu `gwp.a1a3`. |
| **G__GWP_FU** | Declared unit (functional unit) | Text or code for the functional unit (e.g. "1 m²", "1 tonne"). Shown with `G__GWP_A1A3` in catalogue. |
| **G__GWP_A1A3_m2** | GWP A1–A3 per m² | GWP normalised per square metre. Used in charts and comparisons. |
| **G__GWP_A1A3_m3** | GWP A1–A3 per m³ | GWP normalised per cubic metre. Used in charts and catalogue for some product types. |
| **G__GWP_A1A3_m2R1** | GWP A1–A3 per m² (reference) | GWP per m² under a reference scenario (e.g. R1). Used in charts. |
| **G__GWP_A1** | GWP module A1 | GWP for raw materials and supply. Optional in charts. |
| **G__GWP_A2** | GWP module A2 | GWP for transport to factory. Optional in charts. |
| **G__GWP_A3** | GWP module A3 | GWP for manufacturing. Optional in charts. |
| **G__GWP_A4** | GWP module A4 | Transport to the construction site (EN 15804). |
| **G__GWP_A5** | GWP module A5 | Installation / construction process. |
| **G__GWP_B1** | GWP module B1 | Use. |
| **G__GWP_B2** | GWP module B2 | Maintenance. |
| **G__GWP_B3** | GWP module B3 | Repair. |
| **G__GWP_B4** | GWP module B4 | Replacement. |
| **G__GWP_B5** | GWP module B5 | Refurbishment. |
| **G__GWP_B6** | GWP module B6 | Operational energy use. |
| **G__GWP_B7** | GWP module B7 | Operational water use. |
| **G__GWP_C1** | GWP module C1 | Deconstruction / demolition. |
| **G__GWP_C2** | GWP module C2 | Transport of waste. |
| **G__GWP_C3** | GWP module C3 | Waste processing. |
| **G__GWP_C4** | GWP module C4 | Disposal. |
| **G__GWP_D** | GWP module D | Benefits and loads beyond the system boundary (reuse / recovery / recycling potential). |

*Life-cycle modules A1–A3 (product), A4–A5 (construction), B1–B7 (use), C1–C4 (end-of-life) and D (beyond system boundary) follow EN 15804.*

---

#### P — Physical & technical properties

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **P__Mass_kgm3** | Density | Bulk density in kg/m³. Catalogue "Density"; visibility varies by product type. |
| **P__Thick_mm** | Thickness | Thickness in mm. Used in filters, catalogue "Thickness", charts, and sorting. |
| **P__Lambda_WmK** / **P__L_WmK** | Thermal conductivity (λ) | Conductivity in W/(m·K). Catalogue "Conductivity (ʎ)"; key for insulation. |
| **P__U_Wm2K** | Thermal transmittance (U) | U-value in W/(m²·K). Used in charts. |
| **P__FireRating** | Fire rating | Fire classification (e.g. Euroclass). Catalogue "Fire rating". |
| **P__ServiceLife** | Service life | Expected or declared service life. Catalogue "Service Life". |
| **P__Mass_kgm2** | Mass per area | Mass in kg/m². Used in charts. |
| **P__Mass_kg** | Mass per unit | Mass in kg per declared unit. Used in charts. |

---

#### R — Recycling & end-of-life

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **R__Rec_Pre_%** | Pre-consumer recycled content (%) | Percentage of recycled content (pre-consumer). Used in charts. |
| **R__Rec_Post_%** | Post-consumer recycled content (%) | Percentage of recycled content (post-consumer). Used in charts. |
| **R__Rec_Tot_%** | Total recycled content (%) | Total recycled content. Used in charts. |
| **R__Reco_Tot_%** | Total recyclability (%) | End-of-life recyclability. Used in catalogue "Recycling Rate" and tabular view. |
| **R__ByProd_Tot_%** | By-products / recovery (%) | Share of by-products or recovery. Used in charts. |
| **R__Rec_Reco_ByProd_%** | Recycled + recovered (combined) (%) | Combined recycled and recovered content. Used for catalogue "Recycling Rate" and tabular view. |
| **R__Rec_Reco_ByProd_URL** | Recycling evidence URL | Link to certification / evidence backing the recycled-content claim (e.g. ReMade in Italy, PSV). |
| **R__Rec_Cert_No** | Recycled-content certificate number | Number of the document in `R__Rec_Reco_ByProd_URL` (e.g. ICMQ `P01036`, Remade `RE0634`, EPD registration number). `; `-separated when several certificates cover the product. Held in the edit log. |
| **R__Rec_Cert_Scheme** | Certification system | Scheme behind the claim, e.g. `ICMQ – Sistema di Certificazione 3 - ISO/IEC 17067 (CP DOC 262)`, `Remade in Italy® – Disciplinare tecnico`, `EPD ISO 14025 / EN 15804 – EPD International`, `Autodichiarazione del produttore`. Held in the edit log. |
| **R__Rec_Cert_Expiry** | Certificate expiry | Expiry date of the certificate (`YYYY-MM-DD 00:00:00`, same format as `E__EPD_ExpDate`); the catalogue shows it as dd/mm/yyyy and flags it once past. Held in the edit log. |
| **R__Rec_Cert_Plant** | Certified production unit | Production unit(s) named on the certificate, full address when given; `; `-separated for several plants. Held in the edit log. |

---

#### S — Comments

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **S__Comments** | General comments | Free-text comments. Mapped to catalogue "Comments" in `field_meta`. |
| **S__Status** | Record status | Data / workflow status flag for the record (e.g. draft, verified). Internal use. |

---

#### U — URLs & external links

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **U__ProductInfo_URL** | Product info link | URL to a product landing / info page. |
| **U__TechDetails_URL** | Technical details link | URL to technical datasheet or details. Used with "Technical Details" in catalogue. |
| **U__Img_URL** | Product image URL | URL of product image. Used for image caching and display. |

---

#### V — VOC, emissions & CAM compliance

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **V__LEED_MR_RawMat** | LEED MR — raw materials | LEED Materials & Resources credit note for raw-material sourcing. |
| **V__VOC_Body** | VOC scheme / description | VOC certification scheme label or descriptive text (e.g. Indoor Air Comfort Gold, EMICODE, M1). Shown in catalogue/tabular "VOC Info". |
| **V__VOC_Cert** | VOC certification | Programme or label the product is certified under. Rendered with inline certification badges in the catalogue. |
| **V_Test_Standard** | VOC test standard | Emission-test standard used (e.g. ISO 16000, CDPH). |
| **V_Report_Type** | VOC report type | Type of emissions report / classification. |
| **V__VOC_URL** | VOC document URL | Link to the VOC certificate / emissions report. Primary URL downloaded by the pipeline. |
| **V__VOC_Cert_No** | VOC certificate number | Certificate / registration number (as entered). |
| **V__Exp_Date** | VOC certificate expiry | Expiry date of the VOC certificate (as entered). |
| **V__Application_Scope** | VOC application scope | Scope of the certificate (products / use conditions it covers). |
| **V__Product_Category** | VOC product category | Product category as classified by the VOC scheme. |
| **V__Other** | VOC — other notes | Additional free-text VOC notes. |
| **V__SDS__URL** | Safety Data Sheet URL | Link to the product Safety Data Sheet (SDS). |
| **V__CAM__Status** | CAM 2025 status | Compliance status against CAM 2025 criteria. |
| **V__CAM__Evidence** | CAM 2025 evidence | Evidence / method of verification for CAM compliance. |
| **V_CAM_Compliance** | CAM 2025 compliance | Overall CAM compliance flag / summary. |
| **V__DOP** | Declaration of Performance | DoP reference; last expected column in the Excel (used as the data-region cutoff during cleaning). |

---

#### Pipeline-generated helper columns

These columns are **not** in the source Excel — they are appended by
`04_tools/03_excel_to_parquet.py` when it downloads media and parses VOC-cert
PDFs, and are consumed by the app to prefer locally-cached files.

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **U__Img_Local** | Local image path | Relative path to the downloaded product image under `01_data/img/`. |
| **E__EPD_Local** | Local EPD path | Relative path to the downloaded EPD PDF under `01_data/pdf/`. |
| **U__TechDetails_Local** | Local tech-sheet path | Relative path to the downloaded technical-sheet PDF. |
| **V__VOC_Local** | Local VOC-cert path | Relative path to the downloaded VOC certificate (primary URL). |
| **U__VOC_Local_alt** | Local VOC-cert path (alt) | Relative path to the VOC certificate downloaded from the alternate URL. |
| **V__VOC_Cert_Number** | Parsed VOC cert number | Certificate / registration number extracted from the VOC-cert PDF. |
| **V__VOC_Cert_Expiry** | Parsed VOC cert expiry | Expiry / valid-until date extracted from the VOC-cert PDF (ISO `YYYY-MM-DD`). |
| **V__VOC_Cert_Parse_Status** | VOC parse status | Outcome of the PDF parse (e.g. parsed, no_url, not_applicable, failed). |

---

#### PR — List prices (runtime-derived)

These columns are **not** in the source Excel and are **not** stored in any
dataset parquet. `app.py` attaches them to `ORIGINAL_DATA` on load via
`libs/lib_prices.py` `fn507_attach_prices`, joining the catalogue to
`01_data/price_lists.parquet` on manufacturer + normalised product name +
thickness. Because they are derived, they never enter `edits_data.parquet` and
are excluded from the Developer missing-data matrix (its prefix rule is a single
letter).

The prices themselves are **list prices** (listino, VAT excluded, before any
discount), read from the manufacturers' published PDF listini by
`04_tools/13_parse_price_lists.py` (first source: URSA Italia, 9 listini,
331 priced SKUs + 15 accessories/surcharges in `01_data/price_supplements.parquet`).
They are an indication for design comparison, never a quotation — the UI always
shows the listino edition next to the figure.

Clicking the price on a card opens the manufacturer's **full listino table** for
that product (`fn511_price_table_for_product` / `fn512_price_tables_payload`,
injected as `window.__PRICE_TABLES__`): every SKU with code, size, price,
availability and packaging, exactly as printed. That is what a catalogue entry
covering a thickness *range* (e.g. `Glasswool DF 39`, 50–240 mm) expands into —
the twelve thicknesses actually sold. For an entry naming a single thickness the
matching row is highlighted instead.

| Column | Purpose | Content / notes |
|--------|---------|------------------|
| **PR__Price_EUR** | List price (SKU) | Price of the matched SKU in its own unit; empty when the catalogue row covers a thickness range rather than one SKU. |
| **PR__Price_EUR_m2** | List price €/m² | Chart axis: only SKU-exact €/m² prices, so a family span never plots as a single product's price. |
| **PR__Cost_per_R** | €/m² per unit R | `PR__Price_EUR_m2 ÷ R`, the cost of a m² per unit of thermal resistance. Offered for Insulation only. |
| **PR__R_m2KW** | Thermal resistance | R (m²K/W) as printed in the listino, else thickness ÷ λ from the listino row. |
| **PR__Price_Min_EUR** / **PR__Price_Max_EUR** | Price span | Cheapest / dearest SKU of the matched product — the range shown for a catalogue row covering several thicknesses. |
| **PR__Price_Unit** | Price basis | `m2`, `m3` or `kg`, per how the manufacturer prices that family. |
| **PR__Price_Exact** | Match quality | `True` when one SKU matched the thickness; `False` when the figure is a family span. |
| **PR__Price_Display** | Display text | Formatted for the UI: `€ 8,05 /m²` or `€ 5,09 – 22,30 /m²`. Feeds the catalogue card row and detail panel. |
| **PR__Listino_Edition** | Listino edition | E.g. `Giugno 2026 (rev. 00/26)` — shown with every price. |
| **PR__Listino_URL** | Listino source | Link to the manufacturer's price-list PDF the figure was read from. |

---

#### Summary by prefix

| Prefix | Category (UI) | Main use |
|--------|----------------|----------|
| **0** | Identifiers | EETRA product key and sequence number |
| **A** | Product identity | Manufacturer, product name, description, map flag, base product |
| **B** | Board/block | Thickness and board-specific attributes |
| **D** | Details | Product type, material type, size, EN197-1, EN206, content, technical details, application |
| **E** | EPD & manufacturing | EPD metadata (programme, numbers, dates, factors), conductivity/R-value, manufacturing country and plant |
| **G** | GWP Data | GWP indicators, functional unit, and full EN 15804 life-cycle modules (A1–D) |
| **P** | Properties | Density, thickness, conductivity, U-value, fire, service life, mass |
| **R** | Recycling Info | Recycled content, recyclability percentages, and evidence URL |
| **S** | Comments | General comments and record status |
| **U** | URLs | Product info, technical details, and image URLs (+ local cache paths) |
| **V** | VOC / emissions / CAM | VOC scheme, test standard, certificate metadata, SDS, and CAM 2025 compliance |
| **PR** | List prices (derived) | Manufacturer listino price, price span, cost per unit R, listino edition and source link |

---

#### Data source and cleaning

- **Source:** Excel `EETRA_MaterialLibrary.xlsx`, sheet `_live_data` (or equivalent from SharePoint / Parquet / MotherDuck).
- **Cleaning:** Unnamed/empty columns and marker rows (e.g. starting with `*`) are dropped. Data from the Excel is cut at the last expected column (`V__DOP`); the pipeline then appends the helper columns above. Rows with empty product name and manufacturer may be dropped when `A__Map_yn` is used.
- **Visibility:** Which columns appear in catalogue and tabular view depends on **product type** and on `aux__ui_config.json` (`field_visibility`, `field_meta`, `tabular_column_visibility`).
- **Conversion pipeline:** `04_tools/03_excel_to_parquet.py` converts the Excel DB to `live_data.parquet`, downloads images / EPD / tech-sheet / VOC-cert documents into `01_data/`, and parses VOC-cert PDFs. See the file manifest in `APP_DOCUMENTATION.md`.
