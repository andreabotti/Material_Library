"""
14_fetch_prezzari_regionali.py — registro e download dei prezzari regionali
italiani delle opere pubbliche (fonte per i prezzi dei materiali edili).

Perche' esiste
--------------
``13_parse_price_lists.py`` raccoglie i *listini di produttore* (prezzo di
listino di uno SKU). Questo strumento raccoglie invece i *prezzari pubblici*:
ogni Regione e Provincia autonoma pubblica annualmente, ai sensi dell'art. 41
c. 13 del d.lgs. 36/2023, un prezzario delle opere pubbliche che contiene sia
le lavorazioni compiute sia — ed e' la parte che interessa al catalogo — le
"risorse elementari": materiali a pie' d'opera, manodopera, noli e trasporti.

Sono dati pubblici, scaricabili gratuitamente e senza registrazione, e danno
un prezzo di mercato per territorio con cui confrontare i listini di produttore.

Struttura
---------
``SOURCES`` e' il registro: una voce per amministrazione, con l'edizione
vigente, la pagina ufficiale e i file scaricabili. ``kind`` distingue:

  prezzario   l'elenco prezzi vero e proprio (e' il file da parsare)
  analisi     le analisi prezzo (composizione di ogni voce)
  materiali   sezione dedicata alle sole risorse elementari / materiali
  allegato    note metodologiche, avvertenze, indici
  atto        delibera / decreto di approvazione

``fmt`` e' il formato: piu' e' machine-readable meglio e' (XML > CSV/XLS > PDF).

Uso
---
    python 04_tools/14_fetch_prezzari_regionali.py --list
    python 04_tools/14_fetch_prezzari_regionali.py --check       # solo HEAD
    python 04_tools/14_fetch_prezzari_regionali.py               # scarica i dati
    python 04_tools/14_fetch_prezzari_regionali.py --all         # anche i PDF
    python 04_tools/14_fetch_prezzari_regionali.py --region toscana

I file finiscono in ``.cache/prezzari/<slug>/``; il registro viene riscritto in
``01_data/prezzari_regionali.parquet`` e ``.csv`` con l'esito di ogni download.
"""
from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "prezzari"
DATA_DIR = ROOT / "01_data"
REGISTRY_PARQUET = DATA_DIR / "prezzari_regionali.parquet"
REGISTRY_CSV = DATA_DIR / "prezzari_regionali.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EETRA-MatLib/1.0"
# diverse regioni servono certificati incompleti o scaduti: sono portali
# pubblici e i file sono firmati a valle dalla delibera, quindi si procede.
SSL_CTX = ssl._create_unverified_context()

DATA_FORMATS = {"XML", "CSV", "XLS", "XLSX", "ODS", "ZIP"}

# (slug, amministrazione, edizione, pagina ufficiale, [(kind, fmt, label, url)])
SOURCES = [
 ("abruzzo", "Abruzzo", 2026,
  "https://www.regione.abruzzo.it/argomenti/lavori-pubblici/prezzario-regionale/prezzario-regionale-vigente", [
  ("prezzario", "ZIP", "Prezzario 2026 editabile",
   "https://www.regione.abruzzo.it/sites/default/files/allegati/3524/2026-08-05/prezzario-abruzzo-2026-editabile.zip"),
  ("prezzario", "PDF", "Opere edili",
   "https://www.regione.abruzzo.it/sites/default/files/allegati/3523/2026-08-05/all-prezzarioopereediliregioneabruzzo2026.pdf"),
  ("materiali", "PDF", "Manodopera, noli, prestazioni",
   "https://www.regione.abruzzo.it/sites/default/files/allegati/3523/2026-08-05/all-prezzarioregioneabruzzo2026manodopera-noli-prestazioni.pdf"),
  ("analisi", "PDF", "Analisi prezzi opere edili",
   "https://www.regione.abruzzo.it/sites/default/files/allegati/3527/2026-08-05/all-analisiprezziopereedili2026.pdf"),
  ("allegato", "PDF", "Avvertenze generali",
   "https://www.regione.abruzzo.it/sites/default/files/allegati/3523/2026-08-05/all-avvertenzegenerali2026.pdf"),
 ]),
 ("basilicata", "Basilicata", 2025,
  "https://prezzariooperepubbliche.regione.basilicata.it/prezzarioop/prezzario/prezzari.xhtml", []),
 ("bolzano", "P.A. Bolzano", 2026,
  "https://oeffentliche-vertraege.provinz.bz.it/de/informationssystem-offentliche-vertraege/richtpreisverzeichnis-2026", [
  ("prezzario", "XLSX", "Voci / Positionen 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Prezzario-Voci-Richtpreisverzeichnis-Positionen-2026.xlsx"),
  ("prezzario", "CSV", "Voci 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Prezzario-Voci-2026.csv?v=1"),
  ("prezzario", "ZIP", "Voci 2026 XML",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/2026-ambito-provinciale-xml-it.zip?v=1"),
  ("analisi", "XLSX", "Analisi prezzo 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Prezzario-Analisi-2026.xlsx"),
  ("materiali", "XLSX", "Posizioni CAM 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Prezzario-Voci-Richtpreisverzeichnis-Positionen-2026_CAM.xlsx"),
  ("prezzario", "PDF", "Prezzario provinciale 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Prezzario-Voci-2026.pdf"),
  ("allegato", "PDF", "Disposizioni tecnico-contrattuali 2026",
   "https://gestione-prezzario.provincia.bz.it/data/2026-0/Disposizioni_Tecniche_-_Contrattuali_2026.pdf"),
 ]),
 ("calabria", "Calabria", 2025,
  "https://www.regione.calabria.it/edilizia-infrastrutture-difesa-del-suolo-e-mobilita/prezzario-regionale-oo-pp/", [
  ("prezzario", "PDF", "Articoli",
   "https://www.regione.calabria.it/wp-content/uploads/2025/06/DGR-219_21-05-2025-Allegato-3-Articoli.pdf"),
  ("analisi", "PDF", "Analisi",
   "https://www.regione.calabria.it/wp-content/uploads/2025/06/DGR-219_21-05-2025-Allegato-4-Analisi.pdf"),
  ("allegato", "PDF", "Nota metodologica 2025",
   "https://www.regione.calabria.it/wp-content/uploads/2025/06/DGR-219_21-05-2025-Allegato-1-NOTA-METODOLOGICA-2025.pdf"),
 ]),
 ("campania", "Campania", 2026,
  "https://prezzario.regione.campania.it/", [
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XLS)",
   "https://gestione-prezzario.regione.campania.it/data/2026-0/2026_(XLS).zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (CSV)",
   "https://gestione-prezzario.regione.campania.it/data/2026-0/2026_(CSV).zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XML)",
   "https://gestione-prezzario.regione.campania.it/data/2026-0/2026_(XML).zip"),
  ("allegato", "PDF", "Avvertenze generali 2026",
   "https://gestione-prezzario.regione.campania.it/data/2026-0/AVVERTENZE_GENERALI_PREZZARIO_2026_-_DEF.pdf"),
 ]),
 ("emilia_romagna", "Emilia-Romagna", 2026,
  "https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi", [
  ("prezzario", "XLSX", "Elenco prezzi 2026",
   "https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi/prezzario-2026/prezzario_rer_2026_definitivo_17_12_25.xlsx/@@download/file"),
  ("prezzario", "XML", "Elenco prezzi 2026 (export Alice OO.PP.)",
   "https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi/prezzario-2026/export-prezzario-da-alice-oopp_2026.xml/@@download/file"),
  ("prezzario", "PDF", "Elenco prezzi 2026",
   "https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi/prezzario-2026/prezzario_rer_2026_definitivo_17_12_25_ver2.pdf/@@download/file"),
 ]),
 ("friuli_venezia_giulia", "Friuli-Venezia Giulia", 2026,
  "https://www.regione.fvg.it/rafvg/cms/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/", [
  ("prezzario", "XLSX", "Prezzario 2026.1 descrizioni estese",
   "https://www.regione.fvg.it/rafvg/cms/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/allegati/20260630_Prezzario_FVG_2026.1_descrizioni_estese.xlsx"),
  ("prezzario", "CSV", "Prezzario 2026.1 descrizioni estese",
   "https://www.regione.fvg.it/rafvg/cms/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/allegati/20260630_Prezzario_FVG_2026.1_descrizioni_estese.CSV"),
  ("prezzario", "ZIP", "Prezzario 2026 XML",
   "https://www.regione.fvg.it/rafvg/export/sites/default/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/allegati/20260630_Prezzario_FVG_2026_xml.zip"),
  ("prezzario", "PDF", "Prezzario regionale 2026",
   "https://www.regione.fvg.it/rafvg/export/sites/default/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/allegati/20260806_Prezzario_Regionale_dei_lavori_Pubblici_FVG_2026.pdf"),
 ]),
 ("lazio", "Lazio", 2023,
  "https://www.regione.lazio.it/cittadini/lavori-pubblici-infrastrutture/tariffa-prezzi-lavori-pubblici", [
  ("prezzario", "ZIP", "Tariffa 2023 formato open data",
   "https://www.regione.lazio.it/sites/default/files/2023-05/Tariffa_2023_formato_open_DATA%20%281%29.zip"),
  ("prezzario", "PDF", "Parte A - Opere edili",
   "https://www.regione.lazio.it/sites/default/files/documentazione/INF-DGR-101-14-04-2023-AllegatoA.pdf"),
  ("prezzario", "PDF", "Parte E - Impianti tecnologici",
   "https://www.regione.lazio.it/sites/default/files/documentazione/INF-DGR-101-14-04-2023-AllegatoE.pdf"),
 ]),
 ("liguria", "Liguria", 2026,
  "https://appaltiliguria.regione.liguria.it/", [
  ("prezzario", "PDF", "Prezzario 2026",
   "https://appaltiliguria.regione.liguria.it/upload/prezzarioDTS/docs/2026/Prezzario.pdf"),
 ]),
 ("lombardia", "Lombardia", 2026,
  "https://www.regione.lombardia.it/infrastrutture-trasporti-e-mobilita/opere-pubbliche/prezzario-regionale-dei-lavori-pubblici/ser-prezzario-infr", [
  ("prezzario", "ZIP", "Prezzario 2026 XLS",
   "https://www.regione.lombardia.it/content/dam/rl/canali-tematici-servizi/09-infrastrutture-trasporti-e-mobilit%C3%A0/01-acquisti-e-contratti-pubblici/02-prezzario-regionale-dei-lavori-pubblici/02-prezzario-regionale-dei-lavori-pubblici-infr/allegati/allegato-2026-unico/allegati-27-05/Prezzario_2026_LOM261_XLS.zip"),
  ("prezzario", "ZIP", "Prezzario 2026 XML",
   "https://www.regione.lombardia.it/content/dam/rl/canali-tematici-servizi/09-infrastrutture-trasporti-e-mobilit%C3%A0/01-acquisti-e-contratti-pubblici/02-prezzario-regionale-dei-lavori-pubblici/02-prezzario-regionale-dei-lavori-pubblici-infr/allegati/allegato-2026-unico/allegati-27-05/Prezzario_2026_LOM261_XML.zip"),
  ("materiali", "PDF", "Parte 3 - Risorse elementari (umane, materiali, strumentali)",
   "https://www.regione.lombardia.it/content/dam/rl/canali-tematici-servizi/09-infrastrutture-trasporti-e-mobilit%C3%A0/01-acquisti-e-contratti-pubblici/02-prezzario-regionale-dei-lavori-pubblici/02-prezzario-regionale-dei-lavori-pubblici-infr/allegati/allegato-2026-unico/allegati-corretti/all-parte-3-elenco-prezzi-risorse-elementari-umane-materiali-strumentali-e-produttive-tecnologiche.pdf"),
  ("materiali", "PDF", "Risorse elementari per settore merceologico",
   "https://www.regione.lombardia.it/content/dam/rl/canali-tematici-servizi/09-infrastrutture-trasporti-e-mobilit%C3%A0/01-acquisti-e-contratti-pubblici/02-prezzario-regionale-dei-lavori-pubblici/02-prezzario-regionale-dei-lavori-pubblici-infr/allegati/allegati-2026/2026_Sett%20Merc_Risorse.pdf"),
  ("prezzario", "PDF", "Parte 1 - Civile, urbanizzazione, difesa suolo",
   "https://www.regione.lombardia.it/content/dam/rl/canali-tematici-servizi/09-infrastrutture-trasporti-e-mobilit%C3%A0/01-acquisti-e-contratti-pubblici/02-prezzario-regionale-dei-lavori-pubblici/02-prezzario-regionale-dei-lavori-pubblici-infr/allegati/allegato-2026-unico/allegati-corretti/all-parte-1-elenco-prezzi-civile-urbanizzazione-difesa-suolo-agroforestale.pdf"),
 ]),
 ("marche", "Marche", 2026,
  "https://www.regione.marche.it/Regione-Utile/Edilizia-e-Lavori-Pubblici/Prezzario-regionale-lavori-pubblici", [
  ("prezzario", "PDF", "Prezzario 2026 per sottovoci",
   "https://www.regione.marche.it/portals/0/ITE/PREZZARIO/2026/File%202.pdf"),
  ("analisi", "PDF", "Analisi dei costi 2026",
   "https://www.regione.marche.it/portals/0/ITE/PREZZARIO/2026/File%205.pdf"),
  ("allegato", "PDF", "Avvertenze generali 2026",
   "https://www.regione.marche.it/portals/0/ITE/PREZZARIO/2026/File%201.pdf"),
 ]),
 ("molise", "Molise", 2026,
  "https://www.regione.molise.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/193", [
  ("allegato", "PDF", "Integrazione refusi 20-05-2026",
   "https://www.regione.molise.it/flex/files/1/9/1/D.e13240b0efe54e637c74/Integrazione_refusi_20_05_2026.pdf"),
 ]),
 ("piemonte", "Piemonte", 2026,
  "https://prezzario.regione.piemonte.it/2026", [
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XLS)",
   "https://gestione-prezzario.regione.piemonte.it/data/2026-1/2026_1_XLS.zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (CSV)",
   "https://gestione-prezzario.regione.piemonte.it/data/2026-1/2026_1_CSV.zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XML)",
   "https://gestione-prezzario.regione.piemonte.it/data/2026-1/2026_1_XML.zip"),
  ("prezzario", "PDF", "Allegato B parte 1 - Elenco prezzi unitari",
   "https://gestione-prezzario.regione.piemonte.it/data/2026-1/Allegato_B_-_Parte_1_-_Elenco_Prezzi_Unitari.pdf"),
  ("allegato", "PDF", "Allegato A - Nota metodologica 2026",
   "https://gestione-prezzario.regione.piemonte.it/data/2026-1/Allegato_A_-_Nota_metodologica_edizione_2026.pdf"),
 ]),
 ("puglia", "Puglia", 2026,
  "https://www.regione.puglia.it/web/territorio-mobilita-e-infrastrutture/elenco-prezzi-opere-pubbliche", [
  ("atto", "PDF", "D.G.R. 774 del 16/06/2026",
   "https://www.regione.puglia.it/documents/60013/10192486/DGR_774_2026_06_16_signed_signed.pdf/af9d0075-f549-5af7-1237-184c10d6c134?t=1781772371256"),
 ]),
 ("sardegna", "Sardegna", 2026,
  "https://prezzario.regione.sardegna.it/prezzario/", [
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XLS)",
   "https://prezzariogestione.regione.sardegna.it/data/2026-0/2026_XLS.zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (CSV)",
   "https://prezzariogestione.regione.sardegna.it/data/2026-0/2026_CSV.zip"),
  ("prezzario", "ZIP", "Articoli e analisi 2026 (XML)",
   "https://prezzariogestione.regione.sardegna.it/data/2026-0/2026_XML.zip"),
  ("allegato", "PDF", "Nota metodologica DGR 32/68 del 24.06.2026",
   "https://prezzariogestione.regione.sardegna.it/data/2026-0/DEL32-68_Allegato_Prezzario_2026_-_Nota_metodologica.pdf"),
 ]),
 ("sicilia", "Sicilia", 2024,
  "https://www.regione.sicilia.it/istituzioni/regione/strutture-regionali/assessorato-infrastrutture-mobilita/dipartimento-regionale-tecnico/commissione-regionale-prezziario/prezziario-unico-regionale-per-lavori-pubblici/prezziario-vigente", [
  ("prezzario", "XLS", "Prezzario unico regionale 2024",
   "https://www.regione.sicilia.it/system/files/2026-09/prezzario_2024.xls"),
  ("materiali", "PDF", "Tabella materiali 2024",
   "https://www.regione.sicilia.it/system/files/2024-01/Tabella%20materiali%202024_0.pdf"),
  ("materiali", "PDF", "Tabella manodopera e noli 2024",
   "https://www.regione.sicilia.it/system/files/2024-01/Tabella%20manodopera%20e%20noli%202024_0.pdf"),
  ("prezzario", "PDF", "Prezzario unico regionale 2024",
   "https://www.regione.sicilia.it/system/files/2024-01/Prezzario%202024.pdf"),
 ]),
 ("trento", "P.A. Trento", 2026,
  "https://contrattipubblici.provincia.tn.it/Servizi/Elenco-Prezzi-P.A.T.", []),
 ("umbria", "Umbria", 2025,
  "https://www.regione.umbria.it/opere-pubbliche/edizione-in-vigore", [
  ("prezzario", "XLSX", "Elenco prezzi 2025 capitoli 1-13",
   "https://www.regione.umbria.it/documents/18/2335454/Elenco+regionale+dei+prezzi+2025+-+Capitoli+da+1+a+13+-+Refusi+stampa.xlsx/307f8e29-7387-43c2-87ba-cc60cb1073ce"),
  ("prezzario", "XLSX", "Elenco prezzi 2025 capitoli 14-21",
   "https://www.regione.umbria.it/documents/18/2335454/Elenco+regionale+dei+prezzi+2025+-+Capitoli+da+14+a+21+-+Refusi+stampa.xlsx/fbfa8982-e216-4aba-aa6c-bd4694765851"),
  ("materiali", "PDF", "Prezzi elementari",
   "https://www.regione.umbria.it/documents/18/2335454/Prezzi+elementari.pdf/d7fe8c13-0a54-4ff8-acf5-5274b1a6173e"),
  ("materiali", "PDF", "Noli",
   "https://www.regione.umbria.it/documents/18/2335454/Noli.pdf/373d3e9b-38d1-47b2-994c-42b4d55ab139"),
  ("prezzario", "PDF", "Testo coordinato 2025",
   "https://www.regione.umbria.it/documents/18/2335454/Elenco_Prezzi_2025_Testo_Coordinato.pdf/572ccede-d528-4a35-888b-5e8814b3dba7"),
 ]),
 ("valle_aosta", "Valle d'Aosta", 2026,
  "https://www.regione.vda.it/operepubbliche/prezziario/elenco_prezzi_2026_i.aspx", [
  ("prezzario", "PDF", "Opere edili elementari e compiute 2026 (1/2)",
   "https://www.regione.vda.it/allegato.aspx?pk=126853"),
  ("prezzario", "PDF", "Opere edili elementari e compiute 2026 (2/2)",
   "https://www.regione.vda.it/allegato.aspx?pk=126854"),
  ("prezzario", "PDF", "Impianti meccanici 2026 (1/2)",
   "https://www.regione.vda.it/allegato.aspx?pk=126855"),
  ("prezzario", "PDF", "Impianti elettrici 2026 (1/2)",
   "https://www.regione.vda.it/allegato.aspx?pk=126857"),
  ("atto", "PDF", "D.G.R. 643 del 05/06/2026",
   "https://www.regione.vda.it/allegato.aspx?pk=126852"),
 ]),
 ("veneto", "Veneto", 2026,
  "https://www.regione.veneto.it/web/lavori-pubblici/prezzario-regionale", [
  ("prezzario", "ODS", "Elenco prezzi 2026",
   "https://sharing.regione.veneto.it/index.php/s/GtpzgicsGrM6YtT/download"),
  ("prezzario", "XML", "Elenco prezzi 2026",
   "https://sharing.regione.veneto.it/index.php/s/nYSRpnYTTtNWYos/download"),
  ("analisi", "ODS", "Analisi prezzi 2026",
   "https://sharing.regione.veneto.it/index.php/s/sCnb3dtbZT3k2TD/download"),
  ("prezzario", "PDF", "Elenco prezzi 2026",
   "https://sharing.regione.veneto.it/index.php/s/Ho9oZMqN8xMDcwE/download"),
  ("allegato", "PDF", "Norme di misurazione 2026",
   "https://sharing.regione.veneto.it/index.php/s/EQnZ6k3HG2b9CCg/download"),
 ]),
]

# La Toscana pubblica un prezzario per provincia: si genera dal dataset CKAN
# open data, cosi' le dieci province restano allineate senza dieci righe a mano.
TOSCANA_CKAN = ("https://www.dati.toscana.it/api/3/action/package_show"
                "?id=prezzario-lavori-2026")


def _toscana_sources() -> tuple:
    import json
    with urllib.request.urlopen(
            urllib.request.Request(TOSCANA_CKAN, headers={"User-Agent": UA}),
            timeout=60, context=SSL_CTX) as r:
        res = json.load(r)["result"]["resources"]
    files = []
    for r in res:
        fmt, name, url = (r.get("format") or "").upper(), r.get("name") or "", r.get("url")
        if not url:
            continue
        m = re.match(r"^(\d{4})\s+(.+?)\.\s*\((.+)\)$", name)
        if m and "attributi" not in m.group(3).lower():
            files.append(("prezzario", fmt, f"Prezzario {m.group(2)} {m.group(1)}", url))
        elif "nota metodologica" in name.lower() or "indice" in name.lower():
            files.append(("allegato", fmt, name.rstrip("."), url))
    return ("toscana", "Toscana", 2026, "https://prezzariollpp.regione.toscana.it/", files)


def _filename(url: str, slug: str, label: str, fmt: str) -> str:
    base = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    if not base or "." not in base:      # link opachi (sharing Veneto, vda.it)
        base = f"{re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')}.{fmt.lower()}"
    return re.sub(r"[^A-Za-z0-9._()-]+", "_", base)[:120]


def fetch(url: str, dest: Path, check_only: bool) -> tuple[str, int]:
    """Returns (status, bytes). ``check_only`` stops after the headers."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    if check_only:
        req.get_method = lambda: "HEAD"
    try:
        with urllib.request.urlopen(req, timeout=180, context=SSL_CTX) as r:
            if check_only:
                return f"ok {r.status}", int(r.headers.get("Content-Length") or 0)
            dest.parent.mkdir(parents=True, exist_ok=True)
            n = 0
            with dest.open("wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
                    n += len(chunk)
            return "scaricato", n
    except Exception as exc:                                  # noqa: BLE001
        return f"errore: {type(exc).__name__} {exc}"[:120], 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="stampa il registro e basta")
    ap.add_argument("--check", action="store_true", help="verifica gli URL senza scaricare")
    ap.add_argument("--all", action="store_true", help="scarica anche i PDF")
    ap.add_argument("--region", help="limita a uno slug (es. toscana)")
    args = ap.parse_args(argv)

    sources = list(SOURCES)
    try:
        sources.append(_toscana_sources())
    except Exception as exc:                                  # noqa: BLE001
        print(f"!! Toscana: dataset CKAN non raggiungibile ({exc})", file=sys.stderr)
    sources.sort(key=lambda s: s[1])

    rows = []
    for slug, admin, edizione, pagina, files in sources:
        if args.region and args.region != slug:
            continue
        if not files:
            print(f"-- {admin} {edizione}: solo consultazione online -> {pagina}")
            rows.append(dict(slug=slug, amministrazione=admin, edizione=edizione,
                             pagina_ufficiale=pagina, kind="portale", fmt=None,
                             label="consultazione online", url=pagina,
                             file=None, bytes=0, esito="solo portale",
                             recuperato_il=date.today().isoformat()))
            continue
        print(f"== {admin} {edizione} ({len(files)} file)")
        for kind, fmt, label, url in files:
            skip = not args.list and not args.all and fmt.upper() not in DATA_FORMATS
            name = _filename(url, slug, label, fmt)
            dest = CACHE_DIR / slug / name
            if args.list or skip:
                esito, n = ("elencato" if args.list else "saltato (PDF)"), 0
            elif dest.exists() and not args.check:
                esito, n = "in cache", dest.stat().st_size
            else:
                esito, n = fetch(url, dest, args.check)
            print(f"   [{fmt:5}] {label[:58]:58} {esito:12} {n/1e6:8.2f} MB")
            rows.append(dict(slug=slug, amministrazione=admin, edizione=edizione,
                             pagina_ufficiale=pagina, kind=kind, fmt=fmt, label=label,
                             url=url, file=str(dest.relative_to(ROOT)) if n else None,
                             bytes=n, esito=esito,
                             recuperato_il=date.today().isoformat()))

    df = pd.DataFrame(rows)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(REGISTRY_PARQUET, index=False)
    df.to_csv(REGISTRY_CSV, index=False, encoding="utf-8-sig")
    print(f"\n{len(df)} voci, {df.amministrazione.nunique()} amministrazioni, "
          f"{df.bytes.sum()/1e6:.1f} MB -> {REGISTRY_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
