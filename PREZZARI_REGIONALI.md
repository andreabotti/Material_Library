# Prezzari regionali delle opere pubbliche — registro fonti

Aggiornato al 2026-09-16. Generato da `04_tools/14_fetch_prezzari_regionali.py`;
il registro macchina-leggibile e' in `01_data/prezzari_regionali.parquet` / `.csv`,
i file scaricati in `.cache/prezzari/<slug>/`.

Ogni Regione e Provincia autonoma pubblica il proprio prezzario ai sensi dell'art. 41 c. 13
del d.lgs. 36/2023. Oltre alle lavorazioni compiute, contengono le **risorse elementari**
(materiali a pie' d'opera, manodopera, noli, trasporti): e' la sezione che da' un prezzo di
mercato territoriale ai materiali del catalogo. Dati pubblici, gratuiti, senza registrazione.

## Copertura

| Amministrazione | Edizione | Formati dati | File | MB | Pagina ufficiale |
|---|---|---|---|---|---|
| Abruzzo | 2026 | ZIP | 1 | 1.4 | [link](https://www.regione.abruzzo.it/argomenti/lavori-pubblici/prezzario-regionale/prezzario-regionale-vigente) |
| Basilicata | 2025 | solo portale | 0 | 0.0 | [link](https://prezzariooperepubbliche.regione.basilicata.it/prezzarioop/prezzario/prezzari.xhtml) |
| Calabria | 2025 | solo PDF (3 doc.) | 0 | 0.0 | [link](https://www.regione.calabria.it/edilizia-infrastrutture-difesa-del-suolo-e-mobilita/prezzario-regionale-oo-pp/) |
| Campania | 2026 | ZIP | 3 | 24.3 | [link](https://prezzario.regione.campania.it/) |
| Emilia-Romagna | 2026 | XLSX, XML | 2 | 18.2 | [link](https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi) |
| Friuli-Venezia Giulia | 2026 | CSV, XLSX, ZIP | 3 | 4.2 | [link](https://www.regione.fvg.it/rafvg/cms/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/) |
| Lazio | 2023 | ZIP | 1 | 0.6 | [link](https://www.regione.lazio.it/cittadini/lavori-pubblici-infrastrutture/tariffa-prezzi-lavori-pubblici) |
| Liguria | 2026 | solo PDF (1 doc.) | 0 | 0.0 | [link](https://appaltiliguria.regione.liguria.it/) |
| Lombardia | 2026 | ZIP | 2 | 26.1 | [link](https://www.regione.lombardia.it/infrastrutture-trasporti-e-mobilita/opere-pubbliche/prezzario-regionale-dei-lavori-pubblici/ser-prezzario-infr) |
| Marche | 2026 | solo PDF (3 doc.) | 0 | 0.0 | [link](https://www.regione.marche.it/Regione-Utile/Edilizia-e-Lavori-Pubblici/Prezzario-regionale-lavori-pubblici) |
| Molise | 2026 | solo PDF (1 doc.) | 0 | 0.0 | [link](https://www.regione.molise.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/193) |
| P.A. Bolzano | 2026 | CSV, XLSX, ZIP | 5 | 80.1 | [link](https://oeffentliche-vertraege.provinz.bz.it/de/informationssystem-offentliche-vertraege/richtpreisverzeichnis-2026) |
| P.A. Trento | 2026 | solo portale | 0 | 0.0 | [link](https://contrattipubblici.provincia.tn.it/Servizi/Elenco-Prezzi-P.A.T.) |
| Piemonte | 2026 | ZIP | 3 | 21.8 | [link](https://prezzario.regione.piemonte.it/2026) |
| Puglia | 2026 | solo PDF (1 doc.) | 0 | 0.0 | [link](https://www.regione.puglia.it/web/territorio-mobilita-e-infrastrutture/elenco-prezzi-opere-pubbliche) |
| Sardegna | 2026 | ZIP | 3 | 12.9 | [link](https://prezzario.regione.sardegna.it/prezzario/) |
| Sicilia | 2024 | XLS | 1 | 3.9 | [link](https://www.regione.sicilia.it/istituzioni/regione/strutture-regionali/assessorato-infrastrutture-mobilita/dipartimento-regionale-tecnico/commissione-regionale-prezziario/prezziario-unico-regionale-per-lavori-pubblici/prezziario-vigente) |
| Toscana | 2026 | CSV, XLS, XML | 30 | 131.5 | [link](https://prezzariollpp.regione.toscana.it/) |
| Umbria | 2025 | XLSX | 2 | 1.5 | [link](https://www.regione.umbria.it/opere-pubbliche/edizione-in-vigore) |
| Valle d'Aosta | 2026 | solo PDF (5 doc.) | 0 | 0.0 | [link](https://www.regione.vda.it/operepubbliche/prezziario/elenco_prezzi_2026_i.aspx) |
| Veneto | 2026 | ODS, XML | 3 | 11.4 | [link](https://www.regione.veneto.it/web/lavori-pubblici/prezzario-regionale) |

**Totale: 21 amministrazioni, 59 file, 338 MB.**

## Note per amministrazione

- **Toscana** — prezzario differenziato per le 10 province; scaricate tutte in CSV, XLS e XML.
  Il CSV articoli riporta il flag **CAM** per ogni voce.
- **Lombardia, Piemonte, Campania, Sardegna, P.A. Bolzano** — stessa piattaforma; export
  completo in ZIP (XLS + CSV + XML). Bolzano pubblica anche un file dedicato alle voci CAM.
- **Lombardia** — la Parte 3 (risorse elementari: umane, materiali, strumentali) e il file
  per settore merceologico sono solo PDF: si scaricano con `--all`.
- **Emilia-Romagna, Friuli-Venezia Giulia, Umbria, Sicilia** — XLSX/CSV/XML diretti.
- **Veneto** — ODS + XML via il servizio di sharing regionale.
- **Abruzzo** — ZIP 'editabile'; il resto e' PDF.
- **Valle d'Aosta, Marche, Calabria, Liguria, Molise, Puglia** — pubblicano solo PDF
  (o, per la Puglia, una cartella Drive): vanno estratti con pdfplumber come i listini URSA.
- **Basilicata** e **P.A. Trento** — consultazione solo via portale online, nessun export
  pubblico diretto; da valutare lo scraping dell'API del portale.

## Edizioni non 2026

| Amministrazione | Edizione vigente |
|---|---|
| Basilicata | 2025 |
| Calabria | 2025 |
| Lazio | 2023 |
| Sicilia | 2024 |
| Umbria | 2025 |

## Prossimo passo

Un parser (`15_parse_prezzari.py`) che normalizzi i formati tabellari in una tabella unica
`prezzari_voci.parquet` — codice, descrizione, u.m., prezzo, quota manodopera, capitolo,
flag CAM, amministrazione, edizione — e isoli le voci 'materiali / risorse elementari' da
agganciare al catalogo.
