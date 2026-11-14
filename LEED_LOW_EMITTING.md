# LEED v4.1 — EQ Credit Low-Emitting Materials

Fonte: workbook EETRA *Material Library — Low Emitting Materials (LEED)*
(`Approfondimento VOC`). Le categorie di materiale e i codici di applicabilità
sono ereditati dal **LEED Low-Emitting Materials calculator**. I requisiti del
credito sono riassunti, non riprodotti.

Source: the EETRA *Material Library — Low Emitting Materials (LEED)* workbook.
The material groups and applicability codes are inherited from the **LEED
Low-Emitting Materials calculator**. Credit requirements are summarised, not
reproduced.

> **Attenzione / Caveat** — Riassunto operativo, non testo normativo: prima di
> una submission verificare sempre il documento del prodotto e i requisiti del
> credito. La lista USGBC delle certificazioni accettate cambia nel tempo.
> *A working summary, not the credit text: before a submission always check the
> product's own document and the credit requirements. The USGBC list of accepted
> certifications changes over time.*

---

## Dove vive nell'app / Where this lives in the app

| File | Ruolo / Role |
| --- | --- |
| `aux_17__leed_low_emitting.json` | Categorie, requisiti, documenti ammessi, soglie VOC content. Ogni testo ha `it` e `en`. |
| `aux_11__voc_certifications.json` | Le certificazioni; il blocco `leed` porta `listed` e i codici `applicability`. |
| `libs/lib_leed_voc.py` | Caricamento, gerarchia di conformità, testo nella lingua attiva. |
| `pages/13_Add_Edit_Item.py` | Tab *Health*: dropdown categoria, documenti, verdetto, scheda di riferimento. |
| `04_tools/22_leed_group_backfill.py` | Backfill conservativo di `VO__LEED_Group` sui dati esistenti. |

Campi del dataset / dataset fields:

- `VO__LEED_Group` — la categoria LEED, salvata con il nome LEED
  (`Paints and coatings`, …).
- `VO__LEED_Documents` — gli id dei documenti a supporto, separati da `;`.
- `VO__LEED_Pathway` — **derivato** dalla categoria, sola lettura nel form.

---

## La gerarchia / The hierarchy

1. **Categoria** — si indica la categoria LEED del prodotto.
   *State the product's LEED group.*
2. **Requisiti** — la categoria decide se servono VOC content, VOC emissions
   e/o formaldeide, e con quale codice di applicabilità.
   *The group decides which requirements apply, and with which applicability code.*
3. **Documentazione** — si indica che cosa il prodotto ha davvero.
   *State what the product actually holds.*
4. **Certificazione listata** — copre un requisito solo se la sua applicabilità
   include il codice richiesto dalla categoria.
   *A listed certification covers a requirement only if its codes include the
   one the group requires.*
5. **Coperto → conforme** per quel requisito.
6. **Non coperto → altri documenti** ammessi per quella categoria; quel che
   resta aperto è il gap da colmare.
   *Whatever stays open is reported as the gap to fill.*

Codici di applicabilità / applicability codes:

| Codice | Significato |
| --- | --- |
| `GE` | General Emissions Evaluation |
| `VC` | VOC Content for Wet-Applied products |
| `CW` | Composite Wood Evaluation |
| `FF` | Furniture Evaluation |

---

## Le otto categorie / The eight groups

| Categoria (IT) | Group (EN) | Requisiti / Requirements | Codici | Non emissivo | Recupero | Soglia di progetto |
| --- | --- | --- | --- | --- | --- | --- |
| Pitture e rivestimenti | Paints and coatings | VOC content + VOC emissions | VC, GE | No | No | ≥75% emissions **e** 100% content |
| Adesivi e sigillanti | Adhesives and sealants | VOC content + VOC emissions | VC, GE | No | No | ≥75% emissions **e** 100% content |
| Pavimentazioni | Flooring | VOC emissions | GE | Sì | Sì | ≥90% (costo o superficie) |
| Pannelli e finiture a parete | Wall panels | VOC emissions | GE | Sì | Sì | ≥75% (costo o superficie) |
| Soffitti e controsoffitti | Ceilings | VOC emissions | GE | Sì | Sì | ≥90% (costo o superficie) |
| Isolanti | Insulation | VOC emissions | GE | No | No | ≥75% |
| Arredi | Furniture | VOC emissions + formaldeide | FF, FF | Sì | Sì | ≥75% (costo); BIFMA e3 §7.6.1 = metà costo, §7.6.2 = costo pieno |
| Legno composito | Composite wood | VOC emissions + formaldeide | GE, CW | No | Sì | ≥75% (costo o superficie) |

**Note / Notes**

- *Furniture*: in LEED v4.1 la valutazione ANSI/BIFMA comprende VOC e
  formaldeide in un unico report.
- *Composite wood*: LEED v4.1 richiede per questa categoria solo la valutazione
  formaldeide; il requisito VOC emissions è **adottato da EETRA**, non dal
  credito. *The VOC emissions requirement on this group is an EETRA addition.*

---

## Documenti ammessi / Accepted documents

Oltre alle certificazioni listate. La copertura dipende dalla categoria.
*Besides the listed certifications; coverage depends on the group.*

| Documento / Document | Copre / Covers | Categorie / Groups |
| --- | --- | --- |
| Dichiarazione del produttore sul VOC content (scheda tecnica, SDS o lettera) | VOC content | Paints, Adhesives |
| Test report sul VOC content | VOC content | Paints, Adhesives |
| Test report emissioni VOC, laboratorio ISO/IEC 17025 | VOC emissions (+ formaldeide per Furniture) | tutte / all |
| Autodichiarazione del produttore sulle emissioni, basata su test ISO/IEC 17025 | VOC emissions (+ formaldeide per Furniture) | tutte / all |
| Dichiarazione ULEF o NAF (CARB ATCM / EPA TSCA Title VI) | Formaldeide | Composite wood |
| Test report EN 717-1:2014 — classe E1 | Formaldeide | Composite wood |
| Legno composito strutturale, adesivi ASTM D2559 + certificazione di prodotto | Formaldeide | Composite wood |
| Prodotto intrinsecamente non emissivo | tutti i requisiti della categoria | Flooring, Wall panels, Ceilings, Furniture |
| Materiale di recupero (>1 anno al momento dell'uso) | tutti i requisiti della categoria | Flooring, Wall panels, Ceilings, Furniture, Composite wood |

### Documenti NON sufficienti / NOT sufficient

Dichiarazioni generiche ("low VOC", "a basse emissioni") · marcatura CE / DoP ·
SDS senza dati di emissione · EPD · test di laboratorio non accreditato
ISO/IEC 17025 · report di emissione senza dichiarazione di conformità ai limiti
LEED · certificato scaduto o riferito a un prodotto diverso.

---

## Regole generali / General rules

- Il certificato deve essere **valido alla data di acquisto** e riferito al
  prodotto specifico (nome o codice).
- **VOC content**: basta la dichiarazione del produttore, senza laboratorio
  ISO/IEC 17025.
- **VOC emissions**: in alternativa alla certificazione, test report o
  autodichiarazione basata su test di laboratorio accreditato ISO/IEC 17025 che
  dimostri il rispetto dei limiti LEED. Il test deve avere **meno di 3 anni** e
  non può essere successivo alla data di acquisto.
- Una copertura parziale va **integrata** con un altro documento (es.
  certificazione `GE` + dichiarazione VOC content del produttore).

Metodi accettati per le emissioni / accepted emission methods:

- **CDPH Standard Method v1.2-2017** — limiti Tab. 4-1, range TVOC a 14 giorni; oppure
- **EN 16516:2017** con LCI AgBB 2015, formaldeide ≤ 10 µg/m³, range TVOC a 28 giorni.

Scenario: *private office* (*classroom* per le aule scolastiche); per gli arredi
**ANSI/BIFMA M7.1-2011 (R2016)** con conformità a ANSI/BIFMA e3-2014e.

---

## Rapporto con gli altri schemi / Relationship to the other schemes

Il blocco LEED del tab *Health* non è più letto da
`aux_12__voc_rating_alignment.json`: quella lettura guardava la sola
certificazione, mentre il credito guarda **categoria + documentazione**. Le
colonne **WELL v2 X06** e **CAM 2025 criterio 2.4.1** restano in
`aux_12` e continuano a comparire accanto alla certificazione.

*The LEED reading no longer comes from the claim alone: it now takes the
material group and the supporting documents into account. The WELL and CAM
readings are unchanged.*

---

## Backfill dei dati esistenti / Backfilling existing rows

`04_tools/22_leed_group_backfill.py` assegna `VO__LEED_Group` solo dove la
risposta è univoca:

1. `VO__Product_Category` che mappa 1:1 su una categoria LEED;
2. per le righe `Ceilings/Walls/Insulation` (tre categorie LEED in un valore
   solo), `D__ProductType_ENG`, ma solo per le tipologie che stanno
   interamente dentro una categoria.

Restano **volutamente vuote** le righe di muratura, massetti, malte e ripristini:
l'ambito *Wall panels* di LEED esclude gli elementi strutturali verticali, e una
categoria sbagliata produrrebbe un verdetto di conformità sbagliato ma
convincente. Lo script le elenca a fine esecuzione perché siano assegnate a mano.

```bash
python 04_tools/22_leed_group_backfill.py
```

```bash
python 04_tools/22_leed_group_backfill.py --apply
```

Lo script scrive dove l'app legge: **Neon** (`matlib_edits`) quando il log degli
edit vive lì, altrimenti `01_data/edits_data.parquet` (forzabile con
`--parquet`).
