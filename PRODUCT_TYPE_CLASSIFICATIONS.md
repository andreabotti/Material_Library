# Product Types — crosswalk to national and international classifications

Generated 2026-10-13 from `01_data/base_data.parquet` + `01_data/edits_data.parquet`
(edits override base by `0__EETRA_ID`; 1,780 rows). Column: `D__ProductType_ENG`.
Canonicalisation from `libs/lib_data.py::PRODUCT_TYPE_ALIASES` is already applied.

## 1. Values in the dropdown (34)

| # | Product type | Rows | What is actually in it |
|---|---|---:|---|
| 1 | In situ Concrete | 635 | ready-mixed / site concrete |
| 2 | Insulation | 337 | mineral wool, foams, etc. |
| 3 | Building boards | 199 | gypsum (173), mineral boards (22), fibre cement (4) |
| 4 | Tiles | 125 | ceramic tiles |
| 5 | Binder (Cement) | 119 | cements |
| 6 | Masonry (Block) | 52 | masonry units |
| 7 | Screed | 29 | screed mortars |
| 8 | Suspended ceiling | 28 | ceiling tiles / systems |
| 9 | Windows & Doors - Whole system | 27 | complete windows and doors |
| 10 | Metal accessories | 23 | Hilti screw anchors, helical bars (mechanical anchors) |
| 11 | Cable trays | 23 | cable support systems |
| 12 | Flooring | 17 | Tarkett homogeneous vinyl (PVC) |
| 13 | Framing profiles (Cladding/stud frame) | 17 | metal studs / tracks |
| 14 | Windows - Other | 15 | warm-edge spacers, Georgian bars (IGU parts) |
| 15 | Rebar | 15 | reinforcing steel |
| 16 | Coatings | 14 | Mapei repair / protection systems, resins |
| 17 | Rendering | 13 | renders |
| 18 | Coil | 12 | galvanised / organic-coated steel coil **and** rebar in coil (Pittini, Feralpi) |
| 19 | Cladding | 12 | sandwich panels (PU/PIR), stone composite |
| 20 | Structural components | 11 | Porotherm lintels and slab beams, mortars |
| 21 | Building fasteners | 10 | Hilti bonded (chemical) anchors |
| 22 | Masonry (Bricklaying) | 9 | **masonry mortars** (Grigolin), not bricks |
| 23 | Levelling compound | 8 | self-levelling underlayments |
| 24 | Skim plaster | 7 | finishing plasters |
| 25 | Adhesives | 5 | tile/board adhesives |
| 26 | Waterproofing materials | 4 | membranes / liquid waterproofing |
| 27 | Firestopping accessories | 4 | Hilti firestop blocks, plugs, foams, sprays |
| 28 | Paving | 3 | concrete block pavers (masselli autobloccanti) |
| 29 | Grouting | 2 | tile grouts |
| 30 | Finish (Walls) | 1 | lime finish (FG 56 B) |
| 31 | Raised access floor | 1 | — |
| 32 | Paints | 1 | — |
| 33 | Structural accessories | 1 | Hilti base plate |
| 34 | Various assorted floors | 1 | Interface PVC floor |

In `base_data` alone there are 32 values; `Flooring` and `Various assorted floors` come only from edits.

## 2. Reference systems used

**Italy**
- **UNI 8290-1:1981** (*Sistema tecnologico — classificazione e terminologia*): classes of technological
  units and elements (Struttura portante, Chiusura, Partizione interna/esterna, Impianti…). The Italian
  reference for "where it goes in the building".
- **CAM Edilizia 2025** (MASE, nov. 2025), §2.4 *Specifiche tecniche per i prodotti da costruzione*,
  criteria 2.4.1–2.4.18. Mandatory in public procurement (art. 57 d.lgs. 36/2023), so the most
  operational Italian product grouping.
- **NTC 2018, cap. 11** (*Materiali e prodotti per uso strutturale*): 11.2 calcestruzzo, 11.3 acciaio,
  11.7 legno, 11.8 prefabbricati, 11.10 murature. Only structural products.
- **Prezzari regionali** (art. 41 c. 13 d.lgs. 36/2023): chapter structure differs by region, so no
  single code. The *risorse elementari / materiali* sections group roughly like CAM. See
  `PREZZARI_REGIONALI.md`.

**International / European**
- **CPR (Reg. 305/2011, being replaced by Reg. 2024/3110)**: harmonised standards (hEN) and EADs,
  i.e. product families defined by the standard that gives the CE marking. Binding in Italy too.
- **EN 15804+A2 complementary PCRs (c-PCR)**: EN 16757 concrete, EN 16783 thermal insulation,
  EN 16908 cement/lime, EN 17160 ceramic tiles, EN 17213 windows/doors, EN 16810 floor coverings,
  EN 16485 timber; EN 50693 / PEP ecopassport for electrical products. Most relevant for an EPD
  catalogue like this one.
- **MasterFormat 2020 (CSI/CSC)**: spec sections, North America, widely used in international
  projects.
- **ÖKOBAUDAT** (DE, BBSR): top categories 1 Mineral building products, 2 Insulation, 3 Wood,
  4 Metals, 5 Coatings, 6 Plastics, 7 Windows & curtain wall components, 8 Building services, 9 Other.
  Organised by material, like the EC3 / ICE databases.
- Also relevant, not mapped row by row: **Uniclass 2015 table Pr** (UK, ISO 12006-2), **OmniClass
  Table 23** (US), **CoClass** (SE), **CCS** (DK), **IFC** entity types. Uniclass Pr is the closest
  in concept to this dropdown (function-based products). It is worth mapping with a verified copy
  of the table rather than from memory.

## 3. Crosswalk

| Product type | UNI 8290 / NTC (IT) | CAM 2025 (IT) | CPR hEN / EAD | EN 15804 c-PCR | MasterFormat 2020 | ÖKOBAUDAT |
|---|---|---|---|---|---|---|
| In situ Concrete | Struttura portante; NTC 11.2 | 2.4.2 | EN 206 (not harmonised; NTC 11.2 governs) | EN 16757 | 03 30 00 Cast-in-place concrete | 1 Mineral |
| Insulation | Chiusure / partizioni (strato isolante) | 2.4.7 | EN 13162–13171; EADs for others | EN 16783 | 07 21 00 Thermal insulation | 2 Insulation |
| Building boards | Partizione interna verticale; controsoffitti | 2.4.8; 2.4.1 (f) | EN 520; EN 15283; EN 12467 (fibre cement) | — (IBU / EPDItaly PCR) | 09 21 16 Gypsum board assemblies | 1 Mineral |
| Tiles | Pavimentazioni / rivestimenti | 2.4.11 | EN 14411 | EN 17160 | 09 30 00 Tiling | 1 Mineral |
| Binder (Cement) | — (constituent material); NTC 11.2 | via 2.4.2 | EN 197-1 | EN 16908 | — (in 03 30 00) | 1 Mineral |
| Masonry (Block) | Chiusura verticale / partizione; NTC 11.10 | 2.4.5 (clay) or 2.4.3 (concrete, AAC) | EN 771-1…-6 | EN 16757 (concrete units) | 04 21 00 Clay / 04 22 00 Concrete unit masonry | 1 Mineral |
| Screed | Partizione orizzontale (strato di ripartizione) | — | EN 13813 | — | 03 53 00 Concrete topping | 1 Mineral |
| Suspended ceiling | Partizione orizzontale – controsoffitto | 2.4.8; 2.4.1 (g) | EN 13964 | — | 09 51 00 Acoustical ceilings | 1 Mineral / 4 Metals |
| Windows & Doors - Whole system | Chiusura verticale – infissi esterni | 2.4.12; 2.4.18 | EN 14351-1 | EN 17213 | 08 10 00 Doors & frames; 08 50 00 Windows | 7 Windows |
| Windows - Other | Infissi (componenti vetrocamera) | 2.4.18 | EN 1279-5 (IGU) | EN 17213 | 08 80 00 Glazing | 7 Windows |
| Metal accessories | — (fixings) | 2.4.4 | EAD 330232 (mechanical fasteners in concrete) | — | 05 05 19 Post-installed concrete anchors | 4 Metals |
| Building fasteners | — (fixings) | — | EAD 330499 (bonded fasteners in concrete) | — | 05 05 19 Post-installed concrete anchors | 6 Plastics / 9 Other |
| Structural accessories | — | 2.4.4 | EN 1090-1 | — | 05 50 00 Metal fabrications | 4 Metals |
| Cable trays | Impianto di fornitura servizi (elettrico) | — (2.4.17 covers HVAC installation only) | EN 61537 (LVD, not CPR) | EN 50693 / PEP PSR | 26 05 36 Cable trays | 8 Building services |
| Flooring / Various assorted floors | Pavimentazioni | 2.4.10; 2.4.1 (d) | EN 14041 | EN 16810 | 09 65 00 Resilient flooring | 6 Plastics |
| Framing profiles | Partizione interna (sistemi a secco) | 2.4.8; 2.4.4 | EN 14195 | — | 09 22 16 Non-structural metal framing | 4 Metals |
| Rebar | Struttura portante; NTC 11.3.2 (B450C) | 2.4.4 | EN 10080 (not harmonised; NTC qualification) | — | 03 21 00 Reinforcement bars | 4 Metals |
| Coil | Semilavorato (lamiera) or rebar in coil | 2.4.4 | EN 10346 / EN 10169 (sheet); EN 10080 (rebar coil) | — | 05 xx / 03 21 00 | 4 Metals |
| Coatings | Rivestimenti / protezione cls | 2.4.15; 2.4.1 (a) | EN 1504-2 / -7 | — | 03 01 30 Concrete repair; 09 96 00 | 5 Coatings |
| Paints | Rivestimenti (finiture) | 2.4.15; 2.4.1 (a) | — (EN 13300 classification) | — | 09 91 00 Painting | 5 Coatings |
| Rendering | Chiusura verticale – rivestimento esterno | 2.4.1 (b) if indoor | EN 998-1; EN 15824 | — | 09 24 00 Cement plastering | 1 Mineral |
| Skim plaster / Finish (Walls) | Rivestimenti interni | 2.4.1 (b) | EN 13279-1; EN 998-1 | — | 09 23 00 Gypsum plastering | 1 Mineral |
| Masonry (Bricklaying) | Murature (malta); NTC 11.10.2 | — | EN 998-2 | — | 04 05 13 Masonry mortaring | 1 Mineral |
| Cladding | Chiusura verticale – rivestimento / facciata | 2.4.7 (core); 2.4.4 | EN 14509 (sandwich panels) | — | 07 42 13 Metal wall panels | 4 Metals / 2 Insulation |
| Structural components | Struttura portante; NTC 11.8 / 11.10 | 2.4.5 / 2.4.3 | EN 845-2 (lintels); EN 15037-1 (beam-and-block) | — | 04 05 23 Masonry accessories; 03 40 00 Precast | 1 Mineral |
| Levelling compound | Partizione orizzontale | 2.4.1 (b) | EN 13813 | — | 03 54 00 Cast underlayment | 1 Mineral |
| Adhesives | — | 2.4.1 (c) | EN 12004 | — | 09 30 00 (setting materials) | 9 Other |
| Grouting | — | 2.4.1 (c) | EN 13888 | — | 09 30 00 / 03 60 00 Grouting | 1 Mineral |
| Waterproofing materials | Chiusure (strato impermeabile) | 2.4.1 (h) for vapour layers only | EN 13956 / EN 13967 / EN 14891 | — | 07 10 00 Dampproofing & waterproofing | 6 Plastics |
| Firestopping accessories | Impianto di sicurezza / compartimentazione | — | EAD 350454 (fire-stopping and sealing) | — | 07 84 00 Firestopping | 9 Other |
| Paving | Attrezzatura esterna – pavimentazioni | 2.4.3 (vibrocompressed concrete) | EN 1338 | EN 16757 | 32 14 13 Precast concrete unit paving | 1 Mineral |
| Raised access floor | Partizione orizzontale | — | EN 12825 (not harmonised) | — | 09 69 00 Access flooring | 4 Metals |

"—" means no dedicated item. CAM 2.4.1 (a–h) is the indoor-emissions criterion and only applies to
products used indoors.

## 4. Observations on the current list

1. **Function and material are mixed.** Most values describe function (Insulation, Tiles), but
   `Coil` is a form of supply and `Binder (Cement)` is an ingredient. International systems keep
   these on separate axes (Uniclass Pr vs Ma, or CPR family vs ÖKOBAUDAT material).
   `D__MaterialType_ENG` already covers material.
2. **Labels that don't match their content:** `Masonry (Bricklaying)` is all mortar, so
   "Masonry mortar" (EN 998-2) would be accurate. `Windows - Other` is all IGU spacers and bars, so
   "Glazing components". `Coil` mixes sheet steel with rebar in coil, and the rebar rows belong
   under `Rebar`.
3. **Overlaps:** `Metal accessories`, `Building fasteners` and `Structural accessories` are all
   Hilti anchors and fixings, split by material. Every reference system groups them as
   "post-installed anchors / fixings" (MasterFormat 05 05 19, EAD 330232 / 330499).
   `Flooring` and `Various assorted floors` are both PVC floors. `Paints` (1 row) sits next to
   `Coatings`. `Finish (Walls)` (1 row) sits next to `Skim plaster`.
4. **Naming style:** `Windows & Doors - Whole system` vs `Windows - Other`, and
   `Framing profiles (Cladding/stud frame)`, use different patterns. A "Family - Subtype"
   convention modelled on CPR families would make the dropdown sort sensibly.

Caveat: MasterFormat numbers, EAD numbers and c-PCR references come from working knowledge and
were not checked against the current editions. CAM numbers were checked against the CAM 2025
text. Verify before citing any code in a deliverable.
