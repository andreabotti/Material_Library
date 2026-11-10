#!/usr/bin/env python3
"""
BDI-LCA ARCADIA — Step 2: Parse XML files → Excel
Legge tutti i file ILCD XML da  01_data/xml_processes/  e produce un Excel con:
  - Foglio "Metadata"   (1 riga per processo, tutti i campi ILCD)
  - Foglio "Exchanges"  (1 riga per flusso Input/Output)
  - Foglio "Summary"

Prerequisito:
    01_data/xml_processes/*.xml   (prodotto da bdilca_xml_download.py)

Uso:
    python bdilca_xml_parse.py
"""

import warnings; warnings.filterwarnings("ignore")
import sys, io
from pathlib import Path
from datetime import date
import xml.etree.ElementTree as ET

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── namespace map ILCD ─────────────────────────────────────────────────────────
NS = {
    "p":  "http://lca.jrc.it/ILCD/Process",
    "c":  "http://lca.jrc.it/ILCD/Common",
}


def tx(el):
    """Testo di un elemento, strippato; '' se None."""
    return (el.text or "").strip() if el is not None else ""


def find(root, path):
    """Cerca con namespaces; ritorna testo o ''."""
    el = root.find(path, NS)
    return tx(el)


def findall(root, path):
    """Lista di elementi."""
    return root.findall(path, NS)


# ── parser XML ─────────────────────────────────────────────────────────────────

def parse_xml(path: Path):
    """
    Ritorna (meta dict, exchanges list).
    """
    tree = ET.parse(path)
    root = tree.getroot()

    pInfo = root.find("p:processInformation", NS)
    dsi   = pInfo.find("p:dataSetInformation", NS) if pInfo else None
    time_ = pInfo.find("p:time", NS)               if pInfo else None
    geo   = pInfo.find("p:geography", NS)           if pInfo else None
    tech  = pInfo.find("p:technology", NS)          if pInfo else None
    qref  = pInfo.find("p:quantitativeReference", NS) if pInfo else None

    mv    = root.find("p:modellingAndValidation", NS)
    lci   = mv.find("p:LCIMethodAndAllocation", NS)   if mv else None
    dstr  = mv.find("p:dataSourcesTreatmentAndRepresentativeness", NS) if mv else None
    comp  = mv.find("p:completeness", NS)              if mv else None
    val   = mv.find("p:validation", NS)                if mv else None

    adm   = root.find("p:administrativeInformation", NS)
    cg    = adm.find("p:common:commissionerAndGoal", NS) if adm else None
    dgen  = adm.find("p:dataGenerator", NS)            if adm else None
    deb   = adm.find("p:dataEntryBy", NS)              if adm else None
    pub   = adm.find("p:publicationAndOwnership", NS)  if adm else None

    # ── Metadata ───────────────────────────────────────────────────────────────
    # Classificationi
    classes = []
    if dsi is not None:
        for cls_el in dsi.findall(".//c:class", NS):
            classes.append(f"L{cls_el.get('level','?')}:{tx(cls_el)}")

    # Compliance
    compliance_systems = []
    if mv is not None:
        for comp_el in mv.findall(".//p:compliance", NS):
            ref = comp_el.find("c:referenceToComplianceSystem", NS)
            if ref is not None:
                short = ref.find("c:shortDescription", NS)
                compliance_systems.append(tx(short))

    # Data quality indicators
    dq_indicators = {}
    if val is not None:
        for dq in val.findall(".//c:dataQualityIndicator", NS):
            dq_indicators[dq.get("name", "")] = dq.get("value", "")

    # Data sources
    data_sources = []
    if dstr is not None:
        for ref in dstr.findall(".//p:referenceToDataSource", NS):
            short = ref.find("c:shortDescription", NS)
            data_sources.append(tx(short))

    # External docs
    ext_docs = []
    if dsi is not None:
        for ref in dsi.findall(".//p:referenceToExternalDocumentation", NS):
            short = ref.find("c:shortDescription", NS)
            ext_docs.append(tx(short))

    # Reference flow name
    ref_flow_ids = set()
    if qref is not None:
        for rf in qref.findall("p:referenceToReferenceFlow", NS):
            ref_flow_ids.add(rf.text.strip() if rf.text else "")

    # Commissioner
    commissioner = ""
    project = ""
    if adm is not None:
        cg2 = adm.find("c:commissionerAndGoal", NS)
        if cg2 is not None:
            ref_c = cg2.find("c:referenceToCommissioner", NS)
            if ref_c is not None:
                short = ref_c.find("c:shortDescription", NS)
                commissioner = tx(short)
            project = find(cg2, "c:project")

    # Data generator
    data_generator = ""
    if dgen is not None:
        ref_g = dgen.find("c:referenceToPersonOrEntityGeneratingTheDataSet", NS)
        if ref_g is not None:
            short = ref_g.find("c:shortDescription", NS)
            data_generator = tx(short)

    # Owner
    owner = ""
    if pub is not None:
        ref_o = pub.find("c:referenceToOwnershipOfDataSet", NS)
        if ref_o is not None:
            short = ref_o.find("c:shortDescription", NS)
            owner = tx(short)

    # Reviewer
    reviewer = ""
    if val is not None:
        rev = val.find(".//p:review", NS)
        if rev is not None:
            ref_r = rev.find("c:referenceToNameOfReviewerAndInstitution", NS)
            if ref_r is not None:
                short = ref_r.find("c:shortDescription", NS)
                reviewer = tx(short)

    meta = {
        # Identificazione
        "uuid":              find(root, ".//c:UUID"),
        "name":              find(root, ".//p:name/p:baseName[@{http://www.w3.org/XML/1998/namespace}lang='en']")
                             or find(root, ".//p:name/p:baseName"),
        "synonyms":          find(root, ".//c:synonyms"),
        "classification":    " > ".join(classes),
        "general_comment":   find(root, ".//c:generalComment"),
        # Tempo / Geo
        "reference_year":    find(root, ".//c:referenceYear"),
        "valid_until":       find(root, ".//c:dataSetValidUntil"),
        "location":          geo.find("p:locationOfOperationSupplyOrProduction", NS).get("location", "")
                             if geo is not None and geo.find("p:locationOfOperationSupplyOrProduction", NS) is not None
                             else "",
        "geo_description":   find(root, ".//p:descriptionOfRestrictions"),
        # Tecnologia
        "technology_description": find(root, ".//p:technologyDescriptionAndIncludedProcesses"),
        "technical_applicability": find(root, ".//p:technologicalApplicability"),
        # Modelling
        "type_of_dataset":        find(root, ".//p:typeOfDataSet"),
        "lci_method_principle":   find(root, ".//p:LCIMethodPrinciple"),
        "lci_method_approaches":  find(root, ".//p:LCIMethodApproaches"),
        "data_cutoff":            find(root, ".//p:dataCutOffAndCompletenessPrinciples"),
        "sampling_procedure":     find(root, ".//p:samplingProcedure"),
        "data_collection_period": find(root, ".//p:dataCollectionPeriod"),
        "completeness":           find(root, ".//p:completenessProductModel"),
        "data_sources":           " | ".join(data_sources),
        "external_docs":          " | ".join(ext_docs),
        # Review / Qualità
        "review_type":            val.find(".//p:review", NS).get("type", "") if val is not None and val.find(".//p:review", NS) is not None else "",
        "review_details":         find(root, ".//c:reviewDetails"),
        "reviewer":               reviewer,
        "dq_technological":       dq_indicators.get("Technological representativeness", ""),
        "dq_time":                dq_indicators.get("Time representativeness", ""),
        "dq_geographical":        dq_indicators.get("Geographical representativeness", ""),
        "dq_completeness":        dq_indicators.get("Completeness", ""),
        # Compliance
        "compliance":             " | ".join(compliance_systems),
        # Amministrativo
        "commissioner":           commissioner,
        "project":                project,
        "data_generator":         data_generator,
        "timestamp":              find(root, ".//c:timeStamp"),
        "format":                 find(root, ".//c:referenceToDataSetFormat/c:shortDescription"),
        "version":                find(root, ".//c:dataSetVersion"),
        "date_last_revision":     find(root, ".//c:dateOfLastRevision"),
        "permanent_uri":          find(root, ".//c:permanentDataSetURI"),
        "copyright":              find(root, ".//c:copyright"),
        "license_type":           find(root, ".//c:licenseType"),
        "access_restrictions":    find(root, ".//c:accessRestrictions"),
        "owner":                  owner,
    }

    # ── Exchanges ──────────────────────────────────────────────────────────────
    exchanges = []
    ref_uuid = meta["uuid"]

    for exc in findall(root, "p:exchanges/p:exchange"):
        int_id = exc.get("dataSetInternalID", "")

        ref_flow = exc.find("p:referenceToFlowDataSet", NS)
        flow_uuid = ref_flow.get("refObjectId", "") if ref_flow is not None else ""
        flow_name = ""
        if ref_flow is not None:
            for sd in ref_flow.findall("c:shortDescription", NS):
                lang = sd.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                if lang == "en" or not flow_name:
                    flow_name = tx(sd)

        flow_type_cat = tx(exc.find("p:referenceToFlowDataSet", NS)) if exc.find("p:referenceToFlowDataSet", NS) is not None else ""

        # Flow classification (se presente)
        flow_class = ""
        for fc in exc.findall(".//p:flowCategorization/p:class", NS):
            flow_class += tx(fc) + " / "
        flow_class = flow_class.rstrip(" / ")

        direction    = tx(exc.find("p:exchangeDirection", NS))
        location     = tx(exc.find("p:location", NS))
        mean_amt     = tx(exc.find("p:meanAmount", NS))
        result_amt   = tx(exc.find("p:resultingAmount", NS))
        min_amt      = tx(exc.find("p:minimumAmount", NS))
        max_amt      = tx(exc.find("p:maximumAmount", NS))
        unit_uuid    = ""
        unit_el      = exc.find("p:referenceToUnit", NS)
        if unit_el is not None:
            unit_uuid = unit_el.get("refObjectId", "")
            unit_short = unit_el.find("c:shortDescription", NS)
            unit_uuid  = tx(unit_short) or unit_uuid
        comment      = tx(exc.find("p:generalComment", NS))
        is_reference = "true" if int_id in ref_flow_ids else ""

        exchanges.append({
            "process_uuid":    ref_uuid,
            "exchange_id":     int_id,
            "direction":       direction,
            "flow_uuid":       flow_uuid,
            "flow_name":       flow_name,
            "flow_class":      flow_class,
            "location":        location,
            "mean_amount":     mean_amt,
            "resulting_amount":result_amt,
            "min_amount":      min_amt,
            "max_amount":      max_amt,
            "unit":            unit_uuid,
            "is_reference_flow": is_reference,
            "comment":         comment,
        })

    return meta, exchanges


# ── export Excel ───────────────────────────────────────────────────────────────

def export_excel(all_meta, all_exchanges, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    thin  = Side(border_style="thin", color="CCCCCC")
    bdr   = Border(left=thin, right=thin, top=thin, bottom=thin)
    cntr  = Alignment(horizontal="center", vertical="center")
    left  = Alignment(vertical="center")
    leftww = Alignment(vertical="center", wrap_text=True)

    def hdr(cell, fg="1F4E79"):
        cell.font      = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
        cell.fill      = PatternFill("solid", fgColor=fg)
        cell.alignment = cntr
        cell.border    = bdr

    def cell_style(cell, wrap=False, color=None):
        cell.font      = Font(name="Calibri", size=9)
        cell.alignment = leftww if wrap else left
        cell.border    = bdr
        if color:
            cell.fill  = PatternFill("solid", fgColor=color)

    wb = Workbook()

    # ── Metadata ───────────────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Metadata"

    meta_cols = list(all_meta[0].keys()) if all_meta else []
    meta_widths = {
        "uuid": 38, "name": 65, "synonyms": 45, "classification": 30,
        "general_comment": 55, "reference_year": 11, "valid_until": 11,
        "location": 8, "geo_description": 35, "technology_description": 55,
        "technical_applicability": 45, "type_of_dataset": 24,
        "lci_method_principle": 20, "lci_method_approaches": 28,
        "data_cutoff": 35, "sampling_procedure": 30, "data_collection_period": 16,
        "completeness": 16, "data_sources": 40, "external_docs": 40,
        "review_type": 30, "review_details": 50, "reviewer": 30,
        "dq_technological": 14, "dq_time": 14, "dq_geographical": 14, "dq_completeness": 14,
        "compliance": 30, "commissioner": 30, "project": 45,
        "data_generator": 45, "timestamp": 24, "format": 16,
        "version": 12, "date_last_revision": 24, "permanent_uri": 40,
        "copyright": 10, "license_type": 30, "access_restrictions": 35, "owner": 25,
    }
    wrap_cols = {"general_comment", "technology_description", "technical_applicability",
                 "data_cutoff", "review_details", "data_sources", "external_docs",
                 "access_restrictions", "synonyms"}

    for ci, col in enumerate(meta_cols, 1):
        c = ws1.cell(1, ci, col.replace("_", " ").title())
        hdr(c)
        ws1.column_dimensions[get_column_letter(ci)].width = meta_widths.get(col, 16)
    ws1.row_dimensions[1].height = 28
    ws1.freeze_panes = "A2"

    fills = ["FFFFFF", "EBF3FB"]
    for ri, row in enumerate(all_meta, 2):
        fill = fills[ri % 2]
        for ci, col in enumerate(meta_cols, 1):
            c = ws1.cell(ri, ci, row.get(col, ""))
            cell_style(c, wrap=(col in wrap_cols), color=fill)
        ws1.row_dimensions[ri].height = 16

    # ── Exchanges ──────────────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Exchanges")

    exc_cols = list(all_exchanges[0].keys()) if all_exchanges else []
    exc_widths = {
        "process_uuid": 38, "exchange_id": 10, "direction": 10,
        "flow_uuid": 38, "flow_name": 70, "flow_class": 35,
        "location": 8, "mean_amount": 16, "resulting_amount": 16,
        "min_amount": 14, "max_amount": 14, "unit": 12,
        "is_reference_flow": 12, "comment": 45,
    }
    dir_colors = {"Input": "E2EFDA", "Output": "FCE4D6"}

    for ci, col in enumerate(exc_cols, 1):
        c = ws2.cell(1, ci, col.replace("_", " ").title())
        hdr(c, fg="375623")
        ws2.column_dimensions[get_column_letter(ci)].width = exc_widths.get(col, 14)
    ws2.row_dimensions[1].height = 28
    ws2.freeze_panes = "A2"

    for ri, row in enumerate(all_exchanges, 2):
        fill = dir_colors.get(row.get("direction", ""), "FFFFFF")
        for ci, col in enumerate(exc_cols, 1):
            c = ws2.cell(ri, ci, row.get(col, ""))
            cell_style(c, wrap=(col in ("flow_name", "comment", "flow_class")), color=fill)
        ws2.row_dimensions[ri].height = 16

    # ── Summary ────────────────────────────────────────────────────────────────
    ws3 = wb.create_sheet("Summary")
    ws3.column_dimensions["A"].width = 32
    ws3.column_dimensions["B"].width = 16

    n_in  = sum(1 for e in all_exchanges if e.get("direction") == "Input")
    n_out = sum(1 for e in all_exchanges if e.get("direction") == "Output")
    rows_s = [
        ("Processi parsati",      len(all_meta)),
        ("Exchanges totali",      len(all_exchanges)),
        ("  di cui Input",        n_in),
        ("  di cui Output",       n_out),
        ("Data parsata",          date.today().isoformat()),
        ("Fonte",                 "ILCD XML — BDI-LCA ARCADIA / ENEA"),
    ]
    for ri, (k, v) in enumerate(rows_s, 1):
        c1 = ws3.cell(ri, 1, k)
        c2 = ws3.cell(ri, 2, v)
        for c in (c1, c2):
            c.font   = Font(name="Calibri", size=10,
                            bold=(ri <= 2))
            c.border = bdr
            c.alignment = left

    wb.save(path)
    return len(all_meta), len(all_exchanges), n_in, n_out


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    xml_dir = Path("01_data/xml_processes")
    out_path = f"BDILCA_from_xml_{date.today().isoformat()}.xlsx"

    print("=" * 65)
    print("  BDI-LCA ARCADIA - Parser XML -> Excel")
    print(f"  Input:  {xml_dir}/")
    print(f"  Output: {out_path}")
    print("=" * 65)

    xml_files = sorted(xml_dir.glob("*.xml"))
    print(f"\n  {len(xml_files)} file XML trovati\n")

    all_meta      = []
    all_exchanges = []
    errors        = []

    for i, fp in enumerate(xml_files, 1):
        try:
            meta, exchanges = parse_xml(fp)
            name = meta.get("name", fp.stem)[:50]
            n_in  = sum(1 for e in exchanges if e["direction"] == "Input")
            n_out = sum(1 for e in exchanges if e["direction"] == "Output")
            all_meta.append(meta)
            all_exchanges.extend(exchanges)
            print(f"  [{i:3}/{len(xml_files)}] {name} | in={n_in} out={n_out}")
        except Exception as e:
            print(f"  [{i:3}/{len(xml_files)}] ERR {fp.name}: {e}")
            errors.append((fp.name, str(e)))

    print(f"\n  Parsing completato: {len(all_meta)} processi, {len(all_exchanges)} exchanges")

    print("\n  Export Excel...")
    n_p, n_e, n_in, n_out = export_excel(all_meta, all_exchanges, out_path)
    print(f"  [OK] {out_path}")
    print(f"       {n_p} processi | {n_e} exchanges ({n_in} input, {n_out} output)")

    if errors:
        print(f"\n  [!!] {len(errors)} errori:")
        for fn, err in errors:
            print(f"       {fn}: {err}")

    print(f"\n{'='*65}")
    print(f"  Completato -> {out_path}")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
