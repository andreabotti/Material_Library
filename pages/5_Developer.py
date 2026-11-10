"""
pages/5_Developer.py  —  Add/Edit Item, Database Exploration diagnostics
Hybrid pattern: HTML component for the stats panel; a vertical left-column nav
(one st.radio styled as a tab rail) drives the content pane on its right.

Left-rail sections (top → bottom), dispatched in the content column:
  ➕ Add New Item     — embeds add flow from pages/13_Add_Edit_Item.py
  ✏️ Edit Item
  ── divider ──
  ➕ Add New Manufacturer — embeds pages/16_Add_Edit_Manufacturer.py
  ✏️ Edit Manufacturer
  ── divider ──
  🔬 Database Exploration — diagnostics + Available options + Classification Crosswalk
  📥 EPD Parse
  📖 App Documentation
  🕑 Change Log
  🧾 Data Corrections — library values contradicted by their evidence document
"""
# ── Shared imports ──────────────────────────────────────────────────────────
from libs.page_imports import *  # noqa: F401,F403
from libs.lib_tokens import (
    theme_section,
    app_documentation_css,
    database_schema_css,
    developer_left_nav_css,
    developer_left_nav_keyboard_shortcut_script,
)
import html as _html
from libs.lib_i18n import fn714_tu as _tu
from pathlib import Path

_DEV_GWP_COLUMN_LABELS: dict[str, tuple[str, str]] = {
    "GWP_FU": (
        "GWP FU/DU",
        "FU: Functional Unit · DU: Declared unit.",
    ),
    "GWP_A1A3": (
        "GWP A1-A3 (FU/DU)",
        "GWP A1–A3 per functional / declared unit (see GWP FU/DU).",
    ),
}


def _dev_gwp_tabular_html(df_display: pd.DataFrame) -> str:
    """HTML table for Developer → GWP Data with renamed headers and ⓘ tooltips."""
    rename = {
        k: v[0] for k, v in _DEV_GWP_COLUMN_LABELS.items() if k in df_display.columns
    }
    html_df = df_display.rename(columns=rename)
    html_str = html_df.to_html(escape=False, index=False, classes="tabular-data-table")
    html_str = html_str.replace(">mnd<", '><span style="color: #999999;">mnd</span><')
    html_str = html_str.replace("<table", '<table style="font-size: 0.85em;"')
    for _key, (label, tip) in _DEV_GWP_COLUMN_LABELS.items():
        if label not in rename.values():
            continue
        tip_esc = _html.escape(tip, quote=True)
        html_str = html_str.replace(
            f"<th>{label}</th>",
            f'<th>{label} <span title="{tip_esc}" style="cursor:help;opacity:0.72;">ⓘ</span></th>',
        )
    return html_str


# ── GWP conversion-factor reference (App Documentation → sub-tab) ────────────
_DEV_GWP_BASES: tuple[tuple[str, str, str, str], ...] = (
    (
        "G__GWP_A1A3",
        "kg CO₂e / declared unit",
        "The EPD figure exactly as declared, in whatever unit `G__GWP_FU` names.",
        "Card headline, audit trail back to the EPD.",
    ),
    (
        "G__GWP_A1A3_kg",
        "kg CO₂e / kg",
        "Impact of one kilogram of product — a pure material-intensity basis.",
        "Cross-material comparison, Revalu `gwp.a1a3` mapping.",
    ),
    (
        "G__GWP_A1A3_m3",
        "kg CO₂e / m³",
        "Impact of one cubic metre of product in place.",
        "Bulk / volumetric products: concrete, blocks, screeds, timber, insulants.",
    ),
    (
        "G__GWP_A1A3_m2",
        "kg CO₂e / m²",
        "Impact of one square metre **at the product's own declared thickness**.",
        "Layered products: boards, tiles, membranes, finishes.",
    ),
    (
        "G__GWP_A1A3_m2R1",
        "kg CO₂e / m²·(m²K/W)",
        "Impact of the m² of material that delivers a thermal resistance R = 1 m²K/W.",
        "The only functionally fair basis for comparing insulants.",
    ),
)

# Declared unit (`G__GWP_FU`) → the normalised column it anchors, and the factor.
_DEV_GWP_FU_ANCHORS: tuple[tuple[str, str, str, str], ...] = (
    ("m3",    "G__GWP_A1A3_m3",   "× 1",     "Declared per m³ — copied straight across."),
    ("m2",    "G__GWP_A1A3_m2",   "× 1",     "Declared per m² at the stated thickness."),
    ("kg",    "G__GWP_A1A3_kg",   "× 1",     "Declared per kg — copied straight across."),
    ("ton",   "G__GWP_A1A3_kg",   "× 0.001", "Declared per tonne → divide by 1000."),
    ("m2_R1", "G__GWP_A1A3_m2R1", "× 1",     "EPD already declares the R = 1 reference unit."),
    ("m",     "—",                "—",       "Linear declaration (profiles, edgings). No area/volume anchor without a cross-section."),
    ("unit",  "—",                "—",       "Piece-based declaration. Needs pieces per m² or per m³ to normalise."),
)

# Physical inputs used to bridge between bases.
_DEV_GWP_INPUTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ρ (rho)", "Vol. Density",         "P__Mass_kgm3", "`E__EPD_Density`",  "kg/m³"),
    ("d",       "Thickness",            "P__Thick_mm",  "`E__EPD_Thick_mm`", "mm → m (÷ 1000)"),
    ("λ",       "Thermal conductivity", "P__L_WmK",     "`E__L_WmK`",        "W/(m·K)"),
    ("m_A",     "Sup. Density",         "P__Mass_kgm2", "ρ · d",             "kg/m²"),
    ("R",       "Thermal resistance",   "E__Rvalue",    "d / λ",             "m²K/W"),
)


def _dev_gwp_conversion_reference(df_src: pd.DataFrame) -> None:
    """Render **GWP conversion factors** — the kg / m³ / m² / m²·R=1 reference.

    Documents how a single declared A1–A3 figure is normalised onto the four
    comparison bases used across the catalogue, charts and the Revalu export:
    which declared unit anchors which column, which physical property bridges
    each pair of bases, and which database columns supply those properties.
    """
    st.caption(
        "How one declared A1–A3 figure becomes four comparable bases. "
        "The relationships below were validated against `01_data/base_data.parquet`."
    )
    fn303_custom_hr()

    # ── Live coverage, so the reference ages with the data ───────────────────
    _cov: dict[str, int] = {}
    _n_rows = 0
    try:
        if df_src is not None and not df_src.empty:
            _n_rows = int(len(df_src))
            for _c in ("G__GWP_A1A3", "G__GWP_A1A3_kg", "G__GWP_A1A3_m3",
                       "G__GWP_A1A3_m2", "G__GWP_A1A3_m2R1"):
                if _c in df_src.columns:
                    _cov[_c] = int(pd.to_numeric(df_src[_c], errors="coerce").notna().sum())
    except Exception:
        _cov, _n_rows = {}, 0

    def _cov_cell(col: str) -> str:
        if not _cov or col not in _cov:
            return "—"
        return f"{_cov[col]:,} / {_n_rows:,}"

    # ── 1. The bases ────────────────────────────────────────────────────────
    st.markdown("### 1 · The five GWP bases")
    st.markdown(
        "Every product carries **one** figure from its EPD — `G__GWP_A1A3`, expressed in the unit "
        "named by `G__GWP_FU`. The `_kg` / `_m3` / `_m2` / `_m2R1` columns are *derived views* of "
        "that same figure, never independent measurements."
    )
    _rows_bases = "\n".join(
        f"| `{c}` | {u} | {meaning} | {use} | {_cov_cell(c)} |"
        for c, u, meaning, use in _DEV_GWP_BASES
    )
    st.markdown(
        "| Column | Unit | One unit means | Primary use | Rows populated |\n"
        "|---|---|---|---|---|\n" + _rows_bases
    )

    # ── 2. Anchoring on the declared unit ───────────────────────────────────
    st.markdown("### 2 · Step one — anchor on the declared unit")
    st.markdown(
        "`G__GWP_FU` states the EPD's declared unit. It decides which normalised column receives "
        "the declared value **unchanged** (or with a pure unit factor). That column is the anchor; "
        "every other basis is then derived from it in step 3."
    )
    _rows_fu = "\n".join(
        f"| `{fu}` | {dest if dest == '—' else '`' + dest + '`'} | {fac} | {note} |"
        for fu, dest, fac, note in _DEV_GWP_FU_ANCHORS
    )
    st.markdown(
        "| `G__GWP_FU` | Anchored column | Factor | Note |\n"
        "|---|---|---|---|\n" + _rows_fu
    )
    st.info(
        "Only `ton` carries a non-unity factor: **GWP/kg = GWP/tonne ÷ 1000**. The catalogue card "
        "applies the same rule at display time when no `_kg` value exists (`libs/lib_ui.py`).",
        icon="⚖️",
    )

    # ── 3. The bridges ──────────────────────────────────────────────────────
    st.markdown("### 3 · Step two — the three physical bridges")
    st.markdown(
        "Moving between bases needs exactly three material properties: **density** (mass ↔ volume), "
        "**thickness** (volume ↔ area) and **conductivity** (area ↔ thermal performance)."
    )

    st.markdown("**Mass ↔ volume — density ρ**")
    st.latex(
        r"\text{GWP}_{kg} = \frac{\text{GWP}_{m^3}}{\rho}"
        r"\qquad\Longleftrightarrow\qquad"
        r"\text{GWP}_{m^3} = \text{GWP}_{kg} \cdot \rho"
    )

    st.markdown("**Volume ↔ area — thickness d** (stored in mm, used in m)")
    st.latex(
        r"d\,[\mathrm{m}] = \frac{d\,[\mathrm{mm}]}{1000} \qquad"
        r"\text{GWP}_{m^2} = \text{GWP}_{m^3} \cdot d"
        r"\qquad\Longleftrightarrow\qquad"
        r"\text{GWP}_{m^3} = \frac{\text{GWP}_{m^2}}{d}"
    )

    st.markdown("**Area ↔ mass — mass per area m_A**")
    st.latex(
        r"m_A = \rho \cdot d \qquad"
        r"\text{GWP}_{kg} = \frac{\text{GWP}_{m^2}}{m_A}"
    )

    st.markdown("**Area ↔ thermal performance — conductivity λ**")
    st.latex(
        r"R = \frac{d}{\lambda} \quad\Rightarrow\quad"
        r"\text{GWP}_{m^2R=1} = \frac{\text{GWP}_{m^2}}{R}"
        r"= \text{GWP}_{m^2} \cdot \frac{\lambda}{d}"
        r"= \text{GWP}_{m^3} \cdot \lambda"
    )

    st.markdown("#### Conversion matrix")
    st.markdown(
        "Read as **row → column**: multiply the row basis by the cell to obtain the column basis.\n\n"
        "| from ↓ / to → | per kg | per m³ | per m² | per m² R=1 |\n"
        "|---|---|---|---|---|\n"
        "| **per kg** | 1 | × ρ | × ρ·d | × ρ·λ |\n"
        "| **per m³** | ÷ ρ | 1 | × d | × λ |\n"
        "| **per m²** | ÷ (ρ·d) | ÷ d | 1 | × λ/d  (= ÷ R) |\n"
        "| **per m² R=1** | ÷ (ρ·λ) | ÷ λ | × d/λ  (= × R) | 1 |\n"
    )

    # ── 4. Why R = 1 ────────────────────────────────────────────────────────
    st.markdown("### 4 · Why the R = 1 basis exists")
    st.markdown(
        "Comparing insulants per m² or per m³ compares *quantities of material*, not *what the "
        "material does*. 100 mm of mineral wool and 100 mm of PIR occupy the same m², but do not "
        "deliver the same thermal resistance."
    )
    st.markdown(
        "The R = 1 basis removes thickness from the comparison. Since **R = d / λ**, the thickness "
        "that delivers R = 1 m²K/W is:"
    )
    st.latex(r"d_{R=1} = \lambda \cdot 1 = \lambda \quad [\mathrm{m}]")
    st.markdown(
        "so the material volume behind 1 m² at R = 1 is numerically **λ m³**, and therefore:"
    )
    st.latex(r"\text{GWP}_{m^2R=1} = \text{GWP}_{m^3} \cdot \lambda")
    st.markdown(
        "A lower λ means less material is needed for the same performance, and the R = 1 figure "
        "rewards that automatically. This is the basis the insulation charts default to."
    )

    # ── 5. Input data ───────────────────────────────────────────────────────
    st.markdown("### 5 · Input data and fallback chains")
    _rows_in = "\n".join(
        f"| {sym} | {name} | `{prim}` | {fb} | {unit} |"
        for sym, name, prim, fb, unit in _DEV_GWP_INPUTS
    )
    st.markdown(
        "| Symbol | Property | Primary column | Fallback / derivation | Unit |\n"
        "|---|---|---|---|---|\n" + _rows_in
    )
    st.markdown(
        "The `P__` columns hold the curated library value; the `E__` columns hold what the EPD "
        "itself declared. `P__` wins when both are present, so a conversion always uses the figure "
        "the library has vetted. ρ, d and m_A are over-determined (`m_A = ρ · d`) — a row where the "
        "three disagree signals a data error, not a conversion error."
    )

    # ── 6. Worked example ───────────────────────────────────────────────────
    st.markdown("### 6 · Worked example")
    st.markdown(
        "**Blocco THERMO 450 – 240 mm** — a real catalogue row, declared per m³:\n\n"
        "| Input | Value |\n|---|---|\n"
        "| `G__GWP_FU` | `m3` |\n"
        "| `G__GWP_A1A3` | 39.8 kg CO₂e |\n"
        "| `P__Mass_kgm3` (ρ) | 450 kg/m³ |\n"
        "| `P__Thick_mm` (d) | 240 mm → 0.240 m |\n"
        "| `P__L_WmK` (λ) | 0.108 W/(m·K) |\n"
    )
    st.latex(r"\text{GWP}_{m^3} = 39.8 \quad \text{(declared unit is } m^3,\ \text{anchored 1:1)}")
    st.latex(r"\text{GWP}_{kg} = \frac{39.8}{450} = 0.08844 \;\; \mathrm{kgCO_2e/kg}")
    st.latex(r"\text{GWP}_{m^2} = 39.8 \times 0.240 = 9.552 \;\; \mathrm{kgCO_2e/m^2}")
    st.latex(
        r"\text{GWP}_{m^2R=1} = 39.8 \times 0.108 = 4.2984 \;\;"
        r"\mathrm{kgCO_2e/m^2\!\cdot\!(m^2K/W)}"
    )
    st.markdown(
        "Cross-check: R = 0.240 / 0.108 = 2.222 m²K/W, and 9.552 / 2.222 = 4.298 — the same figure "
        "reached from the m² basis."
    )

    # ── 7. Validity ─────────────────────────────────────────────────────────
    st.markdown("### 7 · Validity and caveats")
    st.markdown(
        "- **`_m2R1` is meaningful for insulants only.** It is populated for a few non-insulation "
        "rows, but λ-normalisation has no functional meaning there. `aux_02__chart_value_defaults.json` "
        "restricts the column to the *Insulation* product type for exactly this reason.\n"
        "- **`_m2` is thickness-specific.** Two rows of the same product at different thicknesses "
        "are not comparable on this basis — use `_m3` or `_m2R1`.\n"
        "- **`_kg` ignores performance and geometry.** It answers \"how carbon-intensive is this "
        "material?\", never \"how much carbon does this build-up cost?\".\n"
        "- **Linear (`m`) and piece (`unit`) declarations cannot be normalised** without a "
        "cross-section or a pieces-per-m² figure; those rows stay blank by design.\n"
        "- **A conversion is only as good as its input.** A missing or wrong ρ, d or λ propagates "
        "silently into every derived basis.\n"
        "- **Module scope is A1–A3 throughout.** A4–A5, B, C and D are never folded into these "
        "columns."
    )

    # ── 8. Where the numbers are produced ───────────────────────────────────
    st.markdown("### 8 · Where the conversions happen")
    st.markdown(
        "| Stage | Location | What it does |\n|---|---|---|\n"
        "| Source of truth | `EETRA_MaterialLibrary.xlsx` (sheet `_live_data`) | The `_kg` / `_m3` "
        "/ `_m2` / `_m2R1` columns are computed upstream and stored. The app **reads** them. |\n"
        "| Ingestion | `04_tools/03_excel_to_parquet.py` | Writes `01_data/base_data.parquet`, "
        "preserving the stored conversions unchanged. |\n"
        "| Display fallbacks | `libs/lib_ui.py` (product card) | Fills gaps at render time only: "
        "tonne → kg (÷ 1000), and `_m2 ÷ P__Mass_kgm2` → per kg. Not written back. |\n"
        "| Charts | `libs/lib_charts.py`, `aux_02__chart_value_defaults.json` | Picks the correct basis "
        "per product type and hides bases that would mislead. |\n"
        "| Export | `libs/lib_revalu_send.py`, `libs/lib_revalu_map.py` | `G__GWP_A1A3_kg` maps to "
        "Revalu `gwp.a1a3`; ρ, d and λ travel with it so the receiver can re-derive the rest. |\n"
    )
    st.caption(
        "To change a conversion, edit the source workbook and re-ingest — editing the app will not "
        "alter a stored value."
    )


def _dev_voc_url_from_row(row) -> str:
    from libs.lib_data import fn142a_is_usable_document_url

    for col in ("VO__VOC_URL", "U__VOC_URL"):
        if hasattr(row, "index") and col not in row.index:
            continue
        try:
            val = row.get(col) if hasattr(row, "get") else row[col]
        except (KeyError, TypeError):
            continue
        if fn142a_is_usable_document_url(val):
            return str(val).strip()
    return ""


def _dev_voc_pdf_preview_section(df_dev: pd.DataFrame, df_visible: pd.DataFrame) -> None:
    """Product picker + in-app VOC PDF dialog (Developer → Tabular → VOC Info tab)."""
    from libs.lib_ui import fn346_fetch_document_pdf_bytes, fn348_voc_document_pdf_dialog

    if df_visible is None or df_visible.empty:
        return

    id_col = "0__EETRA_ID"
    if id_col in df_visible.columns:
        eids = {
            str(v).strip()
            for v in df_visible[id_col].dropna()
            if str(v).strip()
        }
        pool = df_dev[df_dev[id_col].astype(str).str.strip().isin(eids)] if eids else df_dev
    else:
        pool = df_visible

    choices: list[str] = []
    row_by_label: dict[str, pd.Series] = {}
    for _, row in pool.iterrows():
        url = _dev_voc_url_from_row(row)
        if not url:
            continue
        mfr = str(row.get("A__Manufacturer", "") or "").strip()
        name = str(row.get("A__ProductName", "") or "").strip()
        eid = str(row.get(id_col, "") or "").strip()
        if mfr or name:
            label = f"{mfr} — {name}" + (f" ({eid})" if eid else "")
        else:
            label = eid or f"Row {len(choices) + 1}"
        if label in row_by_label:
            label = f"{label} #{len(choices) + 1}"
        choices.append(label)
        row_by_label[label] = row

    st.markdown(_tu("#### VOC document preview"))
    if not choices:
        st.caption(
            _tu("No VOC document URLs in the current table rows "
            "(check **VO__VOC_URL** / **U__VOC_URL**).")
        )
        return

    pick_col, btn_col = st.columns([4, 1.35], gap="small", vertical_alignment="bottom")
    with pick_col:
        pick = st.selectbox(
            _tu("Preview VOC PDF for product"),
            choices,
            key="dev_voc_pdf_product",
            label_visibility="visible",
        )
    with btn_col:
        row = row_by_label[pick]
        url = _dev_voc_url_from_row(row)
        if st.button(_tu("Open VOC document"), key="dev_voc_open_pdf", width="stretch"):
            if not url:
                st.warning(_tu("No VOC URL for this product."))
            else:
                bdata, _, _ = fn346_fetch_document_pdf_bytes(
                    url,
                    str(row.get(id_col, "") or ""),
                    str(row.get("A__ProductName", "") or ""),
                    "voc",
                    row=row,
                )
                if bdata:
                    fn348_voc_document_pdf_dialog(bdata)
                else:
                    st.warning(_tu("Could not load the VOC PDF for preview."))


# Embedded-page hosting is shared app-wide (lib_ui.fn354_run_embedded_page):
# this page, the Catalogue and Further Data Sources all use the same helper and
# the same EMBEDDED_PAGE_KEY flag, so embedded pages suppress their own headers
# consistently and errors are reported in one style.


def _run_add_edit_section(section: str, label: str) -> None:
    """Embed one Add/Edit Item section (add, edit, or options) without nested tabs."""
    if not _is_dev:
        fn356_empty_state(
            _tu("Sign in as **developer** or **admin** to {action}.",
                action=_tu(label.lower())),
            kind="locked",
        )
        return
    fn354_run_embedded_page(
        Path(__file__).resolve().parent / "13_Add_Edit_Item.py",
        label,
        _add_edit_section=section,
    )


def _run_add_mfr_section(section: str, label: str) -> None:
    """Embed Add/Edit Manufacturer (add or edit) without nested tabs."""
    if not _is_dev:
        fn356_empty_state(
            _tu("Sign in as **developer** or **admin** to {action}.",
                action=_tu(label.lower())),
            kind="locked",
        )
        return
    fn354_run_embedded_page(
        Path(__file__).resolve().parent / "16_Add_Edit_Manufacturer.py",
        label,
        _add_mfr_section=section,
    )


def _dev_lazy_section(section_key: str, label: str) -> bool:
    """Return True when a heavy Developer tab should run; otherwise show a load button."""
    loaded = st.session_state.setdefault("dev_lazy_loaded", set())
    if section_key in loaded:
        return True
    # The section keeps its English label as identity; only the wording shown
    # here is translated, section name included.
    shown = _tu(label)
    st.caption(
        _tu("**{label}** is not loaded yet — this page stays fast until you ask for it.",
            label=shown)
    )
    if st.button(_tu("Load {label}", label=shown),
                 key=f"dev_lazy_btn_{section_key}", type="primary"):
        loaded.add(section_key)
        st.rerun()
    return False


_REVALU_PICKER_COLUMNS: list[tuple[str, str]] = [
    ("0__EETRA_ID", "EETRA ID"),
    ("A__Manufacturer", "Manufacturer"),
    ("A__ProductName", "Product"),
    ("D__ProductType_ENG", "Product type"),
    ("E__EPD_RegNumber", "EPD reg. no."),
    ("G__GWP_FU", "Declared unit"),
    ("G__GWP_A1A3", "GWP A1-A3"),
]

# Curated columns for the Database Exploration → Value-count treemap picker
# (identity / classification / physical / EPD / recycling / VOC / CAM — not free-text URLs or GWP bases).
_TREEMAP_COLUMNS: tuple[str, ...] = (
    "A__Manufacturer",
    "A__Map_yn",
    "D__EN197-1",
    "D__EN206",
    "D__MaterialType_ENG",
    "D__ProductType_ENG",
    "D__TechDetails",
    "E__EPD_ConvFactor",
    "E__EPD_Density",
    "E__EPD_ExpDate",
    "E__EPD_kg-FU",
    "E__EPD_MultFactor",
    "E__EPD_Programme",
    "E__EPD_Thick_mm",
    "E__EPD_Y/N",
    "E__ManuCountry",
    "E__ManuPlant",
    "E__ServiceLife",
    "G__GWP_FU",
    "G__GWP_Metric",
    "P__FireRating",
    "P__L_WmK",
    "P__Mass_kg",
    "P__Mass_kgm2",
    "P__Mass_kgm3",
    "P__Thick_mm",
    "P__U_Wm2K",
    "R__ByProd_Tot_%",
    "R__Rec_Post_%",
    "R__Rec_Pre_%",
    "R__Rec_Reco_ByProd_%",
    "R__Rec_Reco_ByProd_URL",
    "R__Rec_Tot_%",
    "R__Reco_Tot_%",
    "S__Comments",
    "S__Status",
    "VO__Exp_Date",
    "VO__ReportType",
    "VO__TestStandard",
    "VO__VOC_Cert",
    "VO__VOC_Cert_No",
    "VV__CAM__Evidence",
    "VV__CAM__Status",
    "VV__CAM_Compliance",
    "VV__DOP",
    "VV__LEED_MR_RawMat",
)


def _dev_revalu_picker_frame(df_source: pd.DataFrame, query: str) -> pd.DataFrame:
    """Compact, searchable view of the filtered dataset for the Revalu picker."""
    cols = [c for c, _ in _REVALU_PICKER_COLUMNS if c in df_source.columns]
    view = df_source[cols].copy() if cols else df_source.copy()
    if query.strip():
        needle = query.strip().lower()
        mask = pd.Series(False, index=view.index)
        for col in view.columns:
            mask |= view[col].astype(str).str.lower().str.contains(needle, na=False, regex=False)
        view = view[mask]
    return view


def _dev_revalu_send_section(df_source: pd.DataFrame) -> None:
    """Database Exploration tab: hand selected materials to Revalu (Get EPD Extended).

    Picks individual or multiple materials out of the *sidebar-filtered* dataset
    and hands them to Revalu shaped like the **Get EPD Extended** body documented
    at https://docs.revalu.io/#5ebbf9cf-ecde-4519-9e0f-305966d49cb7 (see
    ``libs/lib_revalu_send.py`` for the field-by-field mapping).
    """
    from libs import lib_revalu_send as rvs

    st.caption(
        "Select materials from the current **sidebar-filtered** dataset and hand them to "
        f"Revalu as [Get EPD Extended]({rvs.REVALU_DOCS_URL})-shaped JSON. "
        "Authentication uses the documented `x-api-key` header."
    )

    if df_source is None or df_source.empty:
        fn356_empty_state(
            "No materials in the current selection.",
            kind="empty",
            hint="Relax the sidebar filters, then come back to this tab.",
        )
        return

    selected_keys: set = st.session_state.setdefault("dev_revalu_selected", set())
    nonce = st.session_state.setdefault("dev_revalu_nonce", 0)

    # ── picker ──────────────────────────────────────────────────────────────
    search_col, all_col, clear_col = st.columns([6, 1.6, 1.6], vertical_alignment="bottom")
    with search_col:
        query = st.text_input(
            _tu("Search within the filtered materials"),
            key="dev_revalu_search",
            placeholder=_tu("Manufacturer, product name, EPD number …"),
        )
    view = _dev_revalu_picker_frame(df_source, query)
    with all_col:
        if st.button(_tu("Select all shown"), key="dev_revalu_select_all", width="stretch"):
            selected_keys.update(view.index.tolist())
            st.session_state["dev_revalu_nonce"] = nonce + 1
            st.rerun()
    with clear_col:
        if st.button(_tu("Clear selection"), key="dev_revalu_clear", width="stretch"):
            selected_keys.clear()
            st.session_state["dev_revalu_nonce"] = nonce + 1
            st.rerun()

    if view.empty:
        st.info(_tu("No materials match that search."))
        return

    editor_df = view.rename(columns=dict(_REVALU_PICKER_COLUMNS))
    editor_df.insert(0, "Send", [idx in selected_keys for idx in view.index])
    edited = st.data_editor(
        editor_df,
        key=f"dev_revalu_editor_{nonce}",
        width="stretch",
        height=340,
        hide_index=True,
        disabled=[c for c in editor_df.columns if c != "Send"],
        column_config={
            "Send": st.column_config.CheckboxColumn(
                "Send", help=_tu("Tick the materials to hand over to Revalu."), width="small"
            )
        },
    )
    # Reconcile the tick boxes with the persistent selection (rows outside the
    # current search keep whatever state they already had).
    for idx, ticked in zip(view.index, edited["Send"].tolist()):
        if ticked:
            selected_keys.add(idx)
        else:
            selected_keys.discard(idx)

    picked_index = [idx for idx in df_source.index if idx in selected_keys]
    if not picked_index:
        st.info(_tu("Tick at least one material above to build the Revalu payload."))
        return
    df_picked = df_source.loc[picked_index]

    # ── payload + readiness ─────────────────────────────────────────────────
    payloads = rvs.build_revalu_payloads(df_picked)
    checks = rvs.validation_frame(payloads)
    ready = [p for p in payloads if not rvs.validate_payload(p)[0]]
    blocked = len(payloads) - len(ready)

    fn303_custom_hr()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(_tu("Selected"), len(payloads))
    m2.metric(_tu("Ready to send"), len(ready))
    m3.metric(_tu("Incomplete"), blocked)
    m4.metric(_tu("With GWP A1-A3"), sum(1 for p in payloads if (p.get("gwp") or {}).get("a1a3") is not None))

    st.markdown(_tu("##### Record readiness"))
    st.dataframe(checks, width="stretch", hide_index=True)
    if blocked:
        st.warning(
            f"**{blocked}** record(s) miss a field Revalu requires "
            f"(`{'`, `'.join(rvs.REQUIRED_FIELDS)}` or any GWP value) and are excluded from the hand-off."
        )

    with st.expander(f"Preview payload ({len(ready)} record(s), Get EPD Extended shape)", expanded=False):
        if ready:
            st.json(ready[0] if len(ready) == 1 else ready[:3], expanded=2)
            if len(ready) > 3:
                st.caption(f"Showing the first 3 of {len(ready)} records — download below for the full document.")
        else:
            st.caption(_tu("Nothing ready to preview yet."))

    # ── hand-off ────────────────────────────────────────────────────────────
    fn303_custom_hr()
    st.markdown(_tu("##### Hand-off"))
    if not ready:
        st.info(_tu("No complete records in the selection — nothing to hand over."))
        return

    dl_json, dl_ndjson, _spacer = st.columns([1.6, 1.6, 5])
    with dl_json:
        st.download_button(
            _tu("Download JSON"),
            data=rvs.payloads_to_json(ready).encode("utf-8"),
            file_name=f"eetra_to_revalu_{len(ready)}_epds.json",
            mime="application/json",
            key="dev_revalu_dl_json",
            width="stretch",
        )
    with dl_ndjson:
        st.download_button(
            _tu("Download NDJSON"),
            data=rvs.payloads_to_ndjson(ready).encode("utf-8"),
            file_name=f"eetra_to_revalu_{len(ready)}_epds.ndjson",
            mime="application/x-ndjson",
            key="dev_revalu_dl_ndjson",
            width="stretch",
        )

    api_key = rvs.revalu_api_key()
    ingest_url = rvs.revalu_ingest_url()

    st.markdown(_tu("##### Revalu API"))
    key_col, verify_col = st.columns([6, 1.8], vertical_alignment="bottom")
    with key_col:
        if api_key:
            st.caption(f"API key loaded from secrets/environment (`…{api_key[-4:]}`).")
        else:
            st.caption(
                _tu("No API key configured. Add `[revalu] api_key` to `.streamlit/secrets.toml` "
                "or set `REVALU_API_KEY`.")
            )
    with verify_col:
        if st.button(_tu("Verify key"), key="dev_revalu_verify", width="stretch", disabled=not api_key):
            ok, msg = rvs.verify_api_key(api_key)
            (st.success if ok else st.error)(msg)

    if not ingest_url:
        st.info(
            _tu("Revalu's public API is **read-only** (`GET /epds/{uuid}`, `GET /epds/{uuid}/extended`, "
            "`GET /epds/search`, `POST /epds/multiple` — all reads), so the records are handed over as "
            "a file. Once Revalu provisions a partner ingestion endpoint, set `[revalu] ingest_url` "
            "(or `REVALU_INGEST_URL`) and a direct POST becomes available here."),
            icon="ℹ️",
        )
        return

    st.caption(f"Ingestion endpoint: `{ingest_url}`")
    confirm = st.checkbox(
        f"I want to send these {len(ready)} record(s) to Revalu.",
        key="dev_revalu_confirm",
    )
    if st.button(
        f"Send {len(ready)} record(s) to Revalu",
        key="dev_revalu_send",
        type="primary",
        disabled=not (confirm and api_key),
    ):
        with st.spinner("Sending to Revalu …"):
            ok, msg = rvs.send_payloads(ready, api_key=api_key, ingest_url=ingest_url)
        (st.success if ok else st.error)(msg)


# ── Change log (built from the append-only edits_data.parquet) ───────────────
_LOG_OP_LABELS: dict[str, str] = {
    "insert": "🟢 Added",
    "update": "🔵 Modified",
    "delete": "🔴 Deleted",
}
_LOG_TZ = "Europe/Rome"


def _log_norm(val) -> str:
    """Comparable text for one cell — NA, '', 'nan' all collapse to ''."""
    if val is None or val is pd.NA:
        return ""
    if isinstance(val, float) and val != val:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "<na>", "nat"):
        return ""
    try:
        f = float(s)
        if f == f:
            return f"{f:.10g}"  # 0.1 / "0.10" / 1.0 / "1" compare equal
    except (TypeError, ValueError):
        pass
    return s


@st.cache_data(show_spinner=False)
def _dev_change_log(edits_mtime: float, base_mtime: float) -> tuple[pd.DataFrame, dict]:
    """One row per edit record (newest first) + field-level diffs per ``_edit_id``.

    Each record in the log is a full-row snapshot, so the fields a save touched
    are found by comparing it with the previous snapshot of the same item — the
    previous log record, or the base row for the item's first edit.
    """
    edits = fn155_load_edits_dataframe()
    if edits.empty or "0__EETRA_ID" not in edits.columns:
        return pd.DataFrame(), {}

    edits = edits.copy()
    edits["0__EETRA_ID"] = edits["0__EETRA_ID"].astype(str)
    edits["_sort"] = pd.to_numeric(edits["_edit_id"], errors="coerce")
    edits = edits.sort_values("_sort", kind="stable")

    base_by_id: dict[str, dict] = {}
    try:
        _base = fn153b_load_base_dataframe()
        if not _base.empty and "0__EETRA_ID" in _base.columns:
            _base = _base.copy()
            _base["0__EETRA_ID"] = _base["0__EETRA_ID"].astype(str)
            _base = _base[_base["0__EETRA_ID"].isin(set(edits["0__EETRA_ID"]))]
            _base = _base.drop_duplicates("0__EETRA_ID", keep="last")
            base_by_id = {r["0__EETRA_ID"]: r for r in _base.to_dict("records")}
    except Exception:
        base_by_id = {}

    data_cols = [c for c in edits.columns if c not in EDIT_AUDIT_COLS and c not in ("_sort", "0__EETRA_ID")]
    prev_by_id: dict[str, dict] = {}
    rows: list[dict] = []
    diffs: dict[str, list[tuple[str, str, str]]] = {}

    for rec in edits.to_dict("records"):
        eid = rec["0__EETRA_ID"]
        op = str(rec.get("_edit_op") or "").strip().lower()
        prev = prev_by_id.get(eid, base_by_id.get(eid))
        changes: list[tuple[str, str, str]] = []
        if op == "delete":
            pass
        elif prev is None:
            changes = [(c, "", _log_norm(rec.get(c))) for c in data_cols if _log_norm(rec.get(c))]
        else:
            for c in data_cols:
                before, after = _log_norm(prev.get(c)), _log_norm(rec.get(c))
                if before != after:
                    changes.append((c, before, after))
        prev_by_id[eid] = rec
        edit_id = str(rec.get("_edit_id") or "")
        diffs[edit_id] = changes

        if op == "delete":
            summary = "item removed"
        elif op == "insert" or prev is None:
            summary = f"{len(changes)} fields filled"
        elif not changes:
            summary = "no field changed"
        else:
            names = [c for c, _, _ in changes]
            summary = ", ".join(names[:4]) + (f" (+{len(names) - 4})" if len(names) > 4 else "")

        rows.append({
            "_edit_id": edit_id,
            "When": rec.get("_edit_ts"),
            "Action": _LOG_OP_LABELS.get(op, op or "?"),
            "EETRA ID": eid,
            "Manufacturer": _log_norm(rec.get("A__Manufacturer")),
            "Product": _log_norm(rec.get("A__ProductName")),
            "Product type": _log_norm(rec.get("D__ProductType_ENG")),
            "User": _log_norm(rec.get("_edit_user")) or "unknown",
            "Fields": len(changes),
            "Changed fields": summary,
        })

    log = pd.DataFrame(rows)
    ts = pd.to_datetime(log["When"], errors="coerce", utc=True)
    log["When"] = ts.dt.tz_convert(_LOG_TZ).dt.tz_localize(None)
    log = log.iloc[::-1].reset_index(drop=True)  # newest first
    return log, diffs


def _dev_change_log_section() -> None:
    """Developer → Change Log: items added / modified / deleted, newest first."""
    log, diffs = _dev_change_log(fn154d_edits_version(), fn153d_base_version())

    st.caption(
        _tu("Every save made from **Add New Item** / **Edit Item** (and EPD family "
        "re-derivations), newest first. Source: the edit log (Neon or "
        "`01_data/edits_data.parquet`) — the base Excel import is not listed.")
    )
    if log.empty:
        fn356_empty_state("No items have been added or modified yet.", kind="empty")
        return

    # ── filters ─────────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2.4, 3.2, 1.6, 1.6], vertical_alignment="bottom")
    with f1:
        ops = st.multiselect(
            _tu("Action"),
            list(_LOG_OP_LABELS.values()),
            default=list(_LOG_OP_LABELS.values()),
            key="dev_log_ops",
        )
    with f2:
        query = st.text_input(
            _tu("Search"), key="dev_log_search",
            placeholder=_tu("EETRA ID, manufacturer, product, field …"),
        )
    with f3:
        users = sorted(log["User"].unique())
        user_pick = st.selectbox(_tu("User"), ["All"] + users, key="dev_log_user")
    with f4:
        one_per_item = st.toggle(
            _tu("Latest per item"), key="dev_log_latest",
            help=_tu("Show only the most recent change of each item."),
        )

    view = log[log["Action"].isin(ops)]
    if user_pick != "All":
        view = view[view["User"] == user_pick]
    if query.strip():
        needle = query.strip().lower()
        hay = view[["EETRA ID", "Manufacturer", "Product", "Product type", "Changed fields"]]
        mask = hay.apply(lambda s: s.astype(str).str.lower().str.contains(needle, regex=False)).any(axis=1)
        view = view[mask]
    if one_per_item:
        counts = view.groupby("EETRA ID").size()
        view = view.drop_duplicates("EETRA ID", keep="first").copy()
        view.insert(view.columns.get_loc("User") + 1, "Edits", view["EETRA ID"].map(counts))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(_tu("Log entries"), f"{len(view):,}")
    m2.metric(_tu("Items"), f"{view['EETRA ID'].nunique():,}")
    m3.metric(_tu("Added"), f"{int((view['Action'] == _LOG_OP_LABELS['insert']).sum()):,}")
    _last = view["When"].max()
    m4.metric(_tu("Last change"), _last.strftime("%d/%m/%Y %H:%M") if pd.notna(_last) else "—")

    if view.empty:
        st.info(_tu("No log entries match these filters."))
        return

    event = st.dataframe(
        view.drop(columns=["_edit_id"]),
        key="dev_log_table",
        width="stretch",
        height=min(560, 40 + 35 * len(view)),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "When": st.column_config.DatetimeColumn("When", format="DD/MM/YYYY HH:mm:ss"),
            "Fields": st.column_config.NumberColumn("Fields", help=_tu("Number of fields this save changed.")),
        },
    )

    dl, _sp = st.columns([1.6, 6])
    with dl:
        st.download_button(
            _tu("Download CSV"),
            data=view.drop(columns=["_edit_id"]).to_csv(index=False).encode("utf-8"),
            file_name="matlib_change_log.csv",
            mime="text/csv",
            key="dev_log_download",
            width="stretch",
        )

    # ── field-level diff of the selected entry ──────────────────────────────
    try:
        sel_rows = event.selection.rows if event is not None else []
    except Exception:
        sel_rows = []
    fn303_custom_hr()
    if not sel_rows:
        st.caption(_tu("Select a row to see exactly which fields changed."))
        return
    entry = view.iloc[sel_rows[0]]
    changes = diffs.get(entry["_edit_id"], [])
    st.markdown(
        f"##### {entry['Action']} · {entry['Manufacturer']} — {entry['Product']} "
        f"(`{entry['EETRA ID']}`)"
    )
    st.caption(f"{entry['When']:%d/%m/%Y %H:%M:%S} · by **{entry['User']}**")
    if not changes:
        st.info(
            "The item was deleted from the library." if entry["Action"] == _LOG_OP_LABELS["delete"]
            else "This save did not change any field value."
        )
        return
    diff = pd.DataFrame(changes, columns=["Field", "Before", "After"])
    # Saves logged as evidence-based corrections carry their source and reason.
    corr = _dev_corrections(fn154e_corrections_version())
    corr = corr[corr["_edit_id"] == entry["_edit_id"]]
    if not corr.empty:
        diff = diff.merge(
            corr[["field", "evidence", "reason"]].rename(
                columns={"field": "Field", "evidence": "Evidence", "reason": "Reason"}),
            on="Field", how="left",
        )
        st.caption(_tu("🧾 This save corrected values contradicted by their evidence document "
                   "— see **Data Corrections** for the full register."))
    st.dataframe(
        diff,
        width="stretch",
        hide_index=True,
        height=min(480, 40 + 35 * len(changes)),
    )


# ── Data corrections (derived from the edit log) ─────────────────────────────
_CORR_FIELD_LABELS: dict[str, str] = {
    "R__Rec_Pre_%": "Recycled pre-consumer %",
    "R__Rec_Post_%": "Recycled post-consumer %",
    "R__Rec_Tot_%": "Recycled total %",
    "R__Reco_Tot_%": "Recovered %",
    "R__ByProd_Tot_%": "By-product %",
    "R__Rec_Reco_ByProd_%": "Recycled + recovered + by-product %",
}


@st.cache_data(show_spinner=False)
def _dev_corrections(corr_mtime: float) -> pd.DataFrame:
    """The correction register, newest first (cache keyed on the edit log's mtime)."""
    corr = fn155c_load_corrections_dataframe()
    if corr.empty:
        return corr
    corr = corr.copy()
    ts = pd.to_datetime(corr["_corr_ts"], errors="coerce", utc=True)
    corr["When"] = ts.dt.tz_convert(_LOG_TZ).dt.tz_localize(None)
    return corr.iloc[::-1].reset_index(drop=True)


def _dev_corrections_section() -> None:
    """Developer → Data Corrections: library values contradicted by their evidence."""
    corr = _dev_corrections(fn154e_corrections_version())

    st.caption(
        _tu("Values that were in the library but are **contradicted by their evidence "
        "document** (certificate / EPD), with the value that replaced them, the source "
        "and the reason. One row per corrected field, derived from the provenance "
        "recorded on each save in `01_data/edits_data.parquet` — the same log behind "
        "the Change Log, which holds the corrected rows themselves.")
    )
    if corr.empty:
        fn356_empty_state("No evidence-based corrections have been recorded yet.", kind="empty")
        return

    names = fn159_effective_dataset(["0__EETRA_ID", "A__Manufacturer", "A__ProductName"])
    names = names.drop_duplicates("0__EETRA_ID").astype({"0__EETRA_ID": str})
    view = corr.merge(names, on="0__EETRA_ID", how="left")
    view["Field label"] = view["field"].map(_CORR_FIELD_LABELS).fillna(view["field"])
    blank = lambda s: s.fillna("").replace("", "—")  # noqa: E731
    view["old_value"], view["new_value"] = blank(view["old_value"]), blank(view["new_value"])

    f1, f2, f3 = st.columns([2.6, 2.2, 3.2], vertical_alignment="bottom")
    with f1:
        batches = list(dict.fromkeys(view["batch"].dropna()))
        batch = st.selectbox(_tu("Batch"), ["All"] + batches, key="dev_corr_batch")
    with f2:
        mfrs = sorted(view["A__Manufacturer"].dropna().unique())
        mfr_pick = st.multiselect(_tu("Manufacturer"), mfrs, key="dev_corr_mfr")
    with f3:
        query = st.text_input(_tu("Search"), key="dev_corr_search",
                              placeholder=_tu("EETRA ID, product, evidence, reason …"))
    if batch != "All":
        view = view[view["batch"] == batch]
    if mfr_pick:
        view = view[view["A__Manufacturer"].isin(mfr_pick)]
    if query.strip():
        needle = query.strip().lower()
        hay = view[["0__EETRA_ID", "A__ProductName", "evidence", "reason", "field"]]
        view = view[hay.apply(lambda s: s.astype(str).str.lower().str.contains(needle, regex=False)).any(axis=1)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(_tu("Corrected fields"), f"{len(view):,}")
    m2.metric(_tu("Items"), f"{view['0__EETRA_ID'].nunique():,}")
    m3.metric(_tu("Manufacturers"), f"{view['A__Manufacturer'].nunique():,}")
    m4.metric(_tu("Values removed"), f"{int((view['new_value'] == '—').sum()):,}",
              help=_tu("Corrections where the evidence declares no value, so the field was emptied."))
    if view.empty:
        st.info(_tu("No corrections match these filters."))
        return

    table = view[[
        "When", "A__Manufacturer", "A__ProductName", "0__EETRA_ID", "Field label",
        "old_value", "new_value", "evidence", "evidence_url", "reason", "_corr_user",
    ]].rename(columns={
        "A__Manufacturer": "Manufacturer", "A__ProductName": "Product", "0__EETRA_ID": "EETRA ID",
        "Field label": "Field", "old_value": "Old value (contradicted)", "new_value": "New value (from evidence)",
        "evidence": "Evidence", "evidence_url": "Source", "reason": "Reason", "_corr_user": "User",
    })
    st.dataframe(
        table,
        key="dev_corr_table",
        width="stretch",
        hide_index=True,
        height=min(620, 40 + 35 * len(table)),
        column_config={
            "When": st.column_config.DatetimeColumn("When", format="DD/MM/YYYY HH:mm"),
            "Old value (contradicted)": st.column_config.TextColumn(
                help=_tu("Value the library held before the correction; '—' = empty.")),
            "New value (from evidence)": st.column_config.TextColumn(
                help=_tu("Value read from the evidence document; '—' = not declared, field emptied.")),
            "Source": st.column_config.LinkColumn("Source", display_text="open ↗"),
            "Reason": st.column_config.TextColumn(width="large"),
        },
    )
    dl, _sp = st.columns([1.6, 6])
    with dl:
        st.download_button(
            _tu("Download CSV"),
            data=table.to_csv(index=False, sep=";").encode("utf-8-sig"),
            file_name="matlib_data_corrections.csv",
            mime="text/csv",
            key="dev_corr_download",
            width="stretch",
        )


_DEV_COL_PREFIX_RE = re.compile(r"^([A-Z]__)")


# ── Pull shared data from session state (written by app.py every run) ────
df_filtered  = st.session_state.get("FILTERED_DATA",  pd.DataFrame())
df_original  = st.session_state.get("ORIGINAL_DATA",  pd.DataFrame())

_is_dev = st.session_state.get("auth_role") in ("developer", "admin")
_data_ok = st.session_state.get("df_filtered_ready", False)
_ch_dims = fn341_get_charts_dimensions()

try:
    if _data_ok and df_original is not None and not df_original.empty:
        _dup_sig = (len(df_original), len(df_original.columns))
        if st.session_state.get("_dev_dup_sig") != _dup_sig:
            st.session_state["_dev_dup_sig"] = _dup_sig
            st.session_state["_dev_dup_ids"] = fn420_audit_duplicate_product_ids(df_original)
except Exception:
    pass

_dev_only_msg = _tu("Please sign in as **developer** or **admin**.")

# ── Left rail (title, stats, nav) + right content pane (one column split) ───
# Section labels double as the radio options and the dispatch keys below.
# Order: items → manufacturers → explore / EPD / docs / log.
# Horizontal rules after Edit Item (2) and Edit Manufacturer (4) via CSS.
_NAV_ADD       = "➕ Add New Item"
_NAV_EDIT      = "✏️ Edit Item"
_NAV_ADD_MFR   = "➕ Add New Manufacturer"
_NAV_EDIT_MFR  = "✏️ Edit Manufacturer"
_NAV_EXPLORE   = "🔬 Database Exploration"
_NAV_EPD       = "📥 EPD Parse"
_NAV_DOCS      = "📖 App Documentation"
_NAV_LOG       = "🕑 Change Log"
_NAV_CORR      = "🧾 Data Corrections"
_NAV_LABELS = [
    _NAV_ADD, _NAV_EDIT,
    _NAV_ADD_MFR, _NAV_EDIT_MFR,
    _NAV_EXPLORE, _NAV_EPD, _NAV_DOCS, _NAV_LOG, _NAV_CORR,
]

_ln = theme_section("developer_dashboard", "left_nav") or {}
_pc = theme_section("developer_dashboard", "picker_caption") or {}
_col_gap = str(_ln.get("columns_gap", "small"))
_content_pad_top = _ln.get("content_column_padding_top", "0")

# Page title above the two-column layout — same helper / spacing as Charts.
fn003a_page_header(
    "Developer Dashboard",
    "Database management, exploration and diagnostics.",
)

_nav_col, _content_col = st.columns(
    [float(_ln.get("col_ratio_nav", 1.1)), float(_ln.get("col_ratio_content", 4.5))],
    gap=_col_gap,
    vertical_alignment="top",
)

st.markdown(
    f"""
    <style>
    div[data-testid="stVerticalBlock"]:has(.dev-dash-layout) > div[data-testid="stHorizontalBlock"] {{
        gap: {_ln.get('columns_gap_css', '0.65rem')} !important;
    }}
    div[data-testid="stColumn"]:has(.dev-content-pane) [data-testid="stVerticalBlock"] {{
        padding-top: {_content_pad_top} !important;
        gap: 0.35rem !important;
    }}
    div[data-testid="stColumn"]:has(.dev-left-nav) .dev-picker-caption {{
        margin: {_pc.get('margin_top', '10px')} 0 0 0;
        padding: 0;
        font-size: {_pc.get('font_size', '0.8rem')};
        line-height: {_pc.get('line_height', '1.25')};
        color: {_pc.get('color', 'inherit')};
        opacity: {_pc.get('opacity', '0.75')};
    }}
    div[data-testid="stColumn"]:has(.dev-left-nav) .dev-picker-caption p {{
        margin: 0;
        padding: 0;
    }}
    div[data-testid="stColumn"]:has(.dev-left-nav) .dev-picker-caption p + p {{
        margin-top: {_pc.get('paragraph_gap', '0.15rem')};
    }}
    div[data-testid="stHorizontalBlock"]:has(.dev-dash-layout) [data-testid="stColumn"] {{
        align-self: start !important;
    }}
    div[data-testid="stColumn"]:has(.dev-content-pane) > div[data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stColumn"]:has(.dev-left-nav) > div[data-testid="stVerticalBlockBorderWrapper"] {{
        padding-top: 0 !important;
    }}
    </style>
    <div class="dev-dash-layout"></div>
    """,
    unsafe_allow_html=True,
)

# Client-side keyboard shortcut: toggle the left radio rail (JS; sessionStorage).
# Must use unsafe_allow_javascript — st.html strips <script> otherwise.
_dev_nav_js = developer_left_nav_keyboard_shortcut_script()
if _dev_nav_js:
    try:
        st.html(_dev_nav_js, unsafe_allow_javascript=True)
    except TypeError:
        st.html(_dev_nav_js)

with _nav_col:
    if _is_dev and _data_ok:
        _total_n = int(len(df_original)) if df_original is not None and not df_original.empty else 0
        _filt_n = int(len(df_filtered)) if df_filtered is not None and not df_filtered.empty else 0
        st.markdown(
            f'<div class="dev-picker-caption">'
            f"<p>{_tu('Viewing {n} / {m} items', n=f'{_filt_n:,}', m=f'{_total_n:,}')}</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        fn355_render_active_filters(key_prefix="dev", show_clear=False)
    elif _is_dev:
        fn356_empty_state("Load data to enable the full diagnostics.")
    elif not _data_ok:
        st.caption(_tu("Data is still loading or unavailable."))

    # Style one st.radio as a vertical tab rail. Inject via st.html so <style>
    # is not stripped (st.markdown HTML sanitisation drops it on some setups,
    # which hid the section dividers and left native radio circles visible).
    # Scoped via :has(.dev-left-nav) so it never leaks to other radios.
    _dev_nav_css = developer_left_nav_css()
    try:
        st.html(
            f"<style>{_dev_nav_css}</style><div class='dev-left-nav'></div>"
        )
    except Exception:
        st.markdown(
            f"<style>{_dev_nav_css}</style><div class='dev-left-nav'></div>",
            unsafe_allow_html=True,
        )
    _nav_cur = st.session_state.get("dev_nav_section")
    _nav_legacy = {
        "✏️ Edit Existing Item": _NAV_EDIT,
        "➕ Add Manufacturer": _NAV_ADD_MFR,
        "📋 Available options": _NAV_EXPLORE,
        "🧭 Classification Crosswalk": _NAV_EXPLORE,
    }
    if _nav_cur in _nav_legacy:
        st.session_state["dev_nav_section"] = _nav_legacy[_nav_cur]
    elif _nav_cur not in _NAV_LABELS:
        st.session_state["dev_nav_section"] = _NAV_ADD
    st.radio(
        _tu("Developer sections"),
        _NAV_LABELS,
        key="dev_nav_section",
        label_visibility="collapsed",
        format_func=_tu,
    )
    _nav_sc = (_ln.get("keyboard_shortcut") or {})
    _nav_key = str(_nav_sc.get("key", "hh")).strip().upper() or "HH"
    if _nav_sc.get("enabled", True):
        st.markdown(
            f'<p class="dev-nav-shortcut-hint">'
            + _tu(
                "Press {key} to show / hide Nav Menu",
                key=f'<kbd class="dev-nav-shortcut-key">{_html.escape(_nav_key)}</kbd>',
            )
            + "</p>",
            unsafe_allow_html=True,
        )

    # Catalogue Data Source (moved here from the Welcome page; read by app.py).
    if _is_dev:
        from libs.lib_data import fn150_render_data_source_selector
        fn150_render_data_source_selector()

_active = st.session_state.get("dev_nav_section", _NAV_ADD)

with _content_col:
    st.markdown('<div class="dev-content-pane"></div>', unsafe_allow_html=True)
    if _active == _NAV_ADD:
        _run_add_edit_section("add", "Add New Item")

    elif _active == _NAV_EDIT:
        _run_add_edit_section("edit", "Edit Item")

    elif _active == _NAV_ADD_MFR:
        _run_add_mfr_section("add", "Add New Manufacturer")

    elif _active == _NAV_EDIT_MFR:
        _run_add_mfr_section("edit", "Edit Manufacturer")

    elif _active == _NAV_EXPLORE:
        if _is_dev:
            with st.sidebar:
                fn303_custom_hr()
                st.markdown(_tu("#### Dataset"))
                if "dev_dataset_choice" not in st.session_state:
                    # Default to sidebar-filtered data so explore charts match
                    # the catalogue filters the user already set.
                    st.session_state["dev_dataset_choice"] = "Filtered (current filters)"
                st.radio(
                    _tu("Dataset"),
                    ["Original (all rows)", "Filtered (current filters)"],
                    key="dev_dataset_choice",
                    label_visibility="collapsed",
                    format_func=_tu,
                )
            _dataset_choice = st.session_state.get("dev_dataset_choice", "Original (all rows)")
            df_dev = df_original if str(_dataset_choice).startswith("Original") else df_filtered
        else:
            df_dev = pd.DataFrame()

        # Lazy tabs: only the selected sub-tab runs. The Load gates inside stay as a
        # first-visit opt-in; on their own they never switched a section off again,
        # so every loaded section re-ran on every click. fn353a keeps the hidden
        # tabs' settings (embedded Maps included) alive while they are not rendered.
        fn353a_keep_widget_state(
            "dev_treemap_col", "dev_treemap_include_", "dev_missmatrix_",
            "dev_revalu_search", "dev_revalu_confirm",
            "charts_map_", "product_map2_selected_base", "product_map2_max_to_show",
            "maps_basemap_choice",
        )
        (
            sub_dup_ids, sub_treemap, sub_completeness, sub_tabular, sub_maps,
            sub_revalu, sub_revalu_send, sub_options, sub_crosswalk, sub_voc_bodies,
        ) = st.tabs(
            [_tu(t) for t in (
                "Duplicate IDs",
                "Value-count treemap",
                "Column completeness",
                "Tabular Data",
                "Maps",
                "Revalu Matching",
                "Send data to Revalu",
                "Available options",
                "Classification Crosswalk",
                "VOC Bodies & Certifications",
            )],
            on_change="rerun",
            key="dev_explore_active_tab",
        )

        if sub_dup_ids.open:
            with sub_dup_ids:
                if not _is_dev:
                    st.info(_dev_only_msg)
                else:
                    try:
                        _dup_ids = st.session_state.get("_dev_dup_ids")
                        if _dup_ids is not None and not _dup_ids.empty:
                            _n_dup = int(_dup_ids["0__EETRA_ID"].astype(str).nunique())
                            st.warning(
                                f"Duplicate catalogue product IDs detected (**{_n_dup}** IDs). "
                                "Tagging one of these IDs will affect every product sharing the same EETRA ID."
                            )
                            st.dataframe(_dup_ids, width="stretch", hide_index=True)
                        else:
                            st.success(_tu("No duplicate catalogue product IDs detected."))
                    except Exception as _e:
                        st.error(f"Could not load duplicate ID audit: {_e}")

        if sub_treemap.open:
            with sub_treemap:
                if not _is_dev:
                    st.info(_dev_only_msg)
                elif not _dev_lazy_section("treemap", "Value-count treemap"):
                    pass
                else:
                    # Always honour sidebar dataset filters for this chart (ignore the
                    # Explore "Original / Filtered" radio, which still drives other tabs).
                    _df_tm = df_filtered if isinstance(df_filtered, pd.DataFrame) else pd.DataFrame()
                    if _df_tm is None or _df_tm.empty:
                        st.info(
                            _tu("No rows after sidebar filters. Clear or widen the sidebar "
                            "dataset filters to populate this chart.")
                        )
                    else:
                        st.caption(
                            f"**{len(_df_tm):,}** rows after sidebar dataset filters "
                            f"(of {len(df_original):,} in the full dataset)."
                        )
                        fn355_render_active_filters()
                        _cols = [c for c in _TREEMAP_COLUMNS if c in _df_tm.columns]
                        if not _cols:
                            st.info(
                                _tu("None of the curated treemap columns are present in the "
                                "current dataset.")
                            )
                        else:
                            _prev = st.session_state.get("dev_treemap_col")
                            if _prev not in _cols:
                                st.session_state["dev_treemap_col"] = _cols[0]
                            col_sel = st.selectbox(
                                _tu("Column"), _cols, key="dev_treemap_col"
                            )
                            _t1, _t2, _t3, _t4 = st.columns(4)
                            with _t1:
                                include_empty = st.toggle(_tu("Include empty values"), value=True, key="dev_treemap_include_empty")
                            with _t2:
                                include_na = st.toggle(_tu("Include n/a (not available)"), value=True, key="dev_treemap_include_na")
                            with _t3:
                                include_nr = st.toggle(_tu("Include n/r (not relevant)"), value=True, key="dev_treemap_include_nr")
                            with _t4:
                                include_symbols = st.toggle(_tu("Include ? and other symbols"), value=True, key="dev_treemap_include_symbols")

                            vc_df = fn322_get_value_counts_for_treemap(
                                _df_tm,
                                col_sel,
                                top_n=None,
                                include_empty=include_empty,
                                include_na=include_na,
                                include_nr=include_nr,
                                include_symbols=include_symbols,
                            )
                            if vc_df.empty:
                                st.info(_tu("No values to display."))
                            else:
                                fig_tm = px.treemap(
                                    vc_df,
                                    path=["value"],
                                    values="count",
                                    custom_data=["value"],
                                )
                                fig_tm.update_traces(
                                    textinfo="label+value",
                                    hovertemplate="<b>%{label}</b><br>count=%{value}<extra></extra>",
                                )
                                fig_tm.update_layout(
                                    margin=dict(l=10, r=10, t=30, b=10),
                                    font=dict(
                                        family=_ch_dims["chart_font_family"],
                                        size=_ch_dims["chart_font_size"],
                                    ),
                                )
                                _tm_event = st.plotly_chart(
                                    fig_tm,
                                    width="stretch",
                                    key="dev_treemap_chart",
                                    on_select="rerun",
                                    selection_mode="points",
                                    config={"displayModeBar": False},
                                )

                                _selected_value = None
                                try:
                                    _pts = (
                                        _tm_event.selection.points
                                        if _tm_event is not None
                                        else None
                                    ) or []
                                except Exception:
                                    _pts = []
                                _known = set(vc_df["value"].astype(str))
                                for _pt in _pts:
                                    if not isinstance(_pt, dict):
                                        continue
                                    _cd = _pt.get("customdata")
                                    if isinstance(_cd, (list, tuple)) and _cd:
                                        _candidate = _cd[0]
                                    else:
                                        _candidate = _pt.get("label") or _pt.get("id")
                                    if _candidate in (None, ""):
                                        continue
                                    _candidate = str(_candidate).strip()
                                    if _candidate.lower() in ("", "root", "(?)", "/"):
                                        continue
                                    if _candidate in _known:
                                        _selected_value = _candidate
                                        break

                                st.markdown(_tu("#### Matching rows"))
                                if not _selected_value:
                                    st.caption(
                                        _tu("Click a treemap sector to list the products in that group.")
                                    )
                                else:
                                    _match_df = fn322a_rows_matching_treemap_value(
                                        _df_tm,
                                        col_sel,
                                        _selected_value,
                                        include_empty=include_empty,
                                        include_na=include_na,
                                        include_nr=include_nr,
                                        include_symbols=include_symbols,
                                    )
                                    st.caption(
                                        f"**{len(_match_df):,}** rows for `{col_sel}` = "
                                        f"**{_selected_value}**"
                                    )
                                    _pref_cols = list(dict.fromkeys(
                                        c
                                        for c in (
                                            "0__EETRA_ID",
                                            "A__Manufacturer",
                                            "A__ProductName",
                                            "D__ProductType_ENG",
                                            "D__MaterialType_ENG",
                                            col_sel,
                                        )
                                        if c in _match_df.columns
                                    ))
                                    _extra = [c for c in _match_df.columns if c not in _pref_cols]
                                    st.dataframe(
                                        _match_df.loc[:, _pref_cols + _extra],
                                        width="stretch",
                                        hide_index=True,
                                        height=min(480, 80 + 28 * min(len(_match_df), 14)),
                                    )
                                    try:
                                        _safe = re.sub(
                                            r"[^\w.\-]+", "_", str(_selected_value)
                                        ).strip("_")[:60] or "value"
                                        st.download_button(
                                            _tu("Download matching rows CSV"),
                                            data=_match_df.to_csv(index=False).encode("utf-8"),
                                            file_name=f"treemap_{col_sel}_{_safe}.csv",
                                            mime="text/csv",
                                            key="dev_treemap_download",
                                        )
                                    except Exception:
                                        pass

        if sub_completeness.open:
            with sub_completeness:
                if not _is_dev:
                    st.info(_dev_only_msg)
                elif not _dev_lazy_section("completeness", "Column completeness"):
                    pass
                else:
                    stats_df = fn321_get_column_completeness_stats(df_dev)
                    st.dataframe(stats_df, height=520, width='stretch')
                    try:
                        st.download_button(
                            _tu("Download completeness CSV"),
                            data=stats_df.to_csv(index=False).encode("utf-8"),
                            file_name="column_completeness.csv",
                            mime="text/csv",
                        )
                    except Exception:
                        pass

                    st.markdown("---")
                    st.markdown(_tu("#### Available vs. missing data, by Product Type"))
                    if "D__ProductType_ENG" not in df_dev.columns:
                        st.info(_tu("D__ProductType_ENG column not found in this dataset."))
                    else:
                        _pt_series = df_dev["D__ProductType_ENG"].dropna().astype(str).str.strip()
                        _pt_values = sorted(v for v in _pt_series.unique() if v)
                        if not _pt_values:
                            st.info(_tu("No Product Type values found."))
                        else:
                            _pt_choice = st.selectbox(_tu("Product Type"), _pt_values, key="dev_missmatrix_pt")
                            _df_pt = df_dev[df_dev["D__ProductType_ENG"].astype(str).str.strip() == _pt_choice]

                            _mat_cols = sorted(
                                c for c in _df_pt.columns if _DEV_COL_PREFIX_RE.match(c)
                            )

                            if _df_pt.empty or not _mat_cols:
                                st.info(_tu("No rows or no eligible columns for this Product Type."))
                            else:
                                _id_col = "A__EETRA_ID" if "A__EETRA_ID" in _df_pt.columns else None
                                _payload = fn344_build_dev_missmatrix_payload(
                                    _df_pt, _mat_cols, id_col=_id_col, batch_size=30,
                                )
                                if not _payload:
                                    st.info(_tu("No data to display."))
                                else:
                                    _n_prod = _payload["totalProducts"]
                                    st.caption(
                                        f"**{_n_prod:,}** products · **30** per batch "
                                        f"(use ◀ ▶ in the chart) · column groups as JS tabs"
                                    )
                                    _iframe_h = min(920, max(520, 220 + 30 * 20))
                                    _mm_html = fn240_build_dev_missmatrix_html(
                                        _payload, height=_iframe_h,
                                    )
                                    st.iframe(_mm_html, height=_iframe_h)

        if sub_tabular.open:
            with sub_tabular:
                if not _is_dev:
                    st.info(_dev_only_msg)
                elif not _dev_lazy_section("tabular", "Tabular Data"):
                    pass
                else:
                    # Add CSS to make font smaller in tabular data
                    st.markdown("""
                        <style>
                        /* Target all dataframes in tabular data tab */
                        div[data-testid="stDataFrame"] {
                            font-size: 0.85em !important;
                        }
                        div[data-testid="stDataFrame"] table {
                            font-size: 0.85em !important;
                        }
                        div[data-testid="stDataFrame"] th,
                        div[data-testid="stDataFrame"] td {
                            font-size: 0.85em !important;
                        }
                        /* Also target HTML tables */
                        .tabular-data-table {
                            font-size: 0.85em !important;
                        }
                        .tabular-data-table table {
                            font-size: 0.85em !important;
                        }
                        .tabular-data-table th,
                        .tabular-data-table td {
                            font-size: 0.85em !important;
                        }
                        </style>
                    """, unsafe_allow_html=True)

                    if df_dev is None or df_dev.empty:
                        st.info(_tu("No rows in selected dataset."))
                    else:
                        # Determine current product type from dataset
                        current_product_type_table = "default"
                        if 'D__ProductType_ENG' in df_dev.columns:
                            unique_types = df_dev['D__ProductType_ENG'].dropna().unique()
                            if len(unique_types) == 1:
                                current_product_type_table = unique_types[0]
                            elif len(unique_types) > 1:
                                current_product_type_table = "Mixed"

                        # Still need to set to default if Mixed for column filtering logic
                        if current_product_type_table == "Mixed":
                            current_product_type_table = "default"

                        # Build column groups by prefix (A__, D__, P__, etc.)
                        grouped_columns = {}
                        for col in df_dev.columns:
                            if "__" in col:
                                prefix = col.split("__")[0]
                                grouped_columns.setdefault(prefix, []).append(col)
                        a_cols = grouped_columns.get("A", [])

                        _DEV_TAB_ORDER = ("D", "P", "C", "G", "R", "VO", "VV")
                        prefix_to_tabname = {
                            "D": "Details",
                            "P": "Properties",
                            "C": "EPD Info",
                            "G": "GWP Data",
                            "R": "Recycling Info",
                            "VO": "VOC Info",
                            "VV": "Various",
                        }
                        valid_prefixes = [p for p in _DEV_TAB_ORDER if p in grouped_columns]

                        tabs = st.tabs(
                            [prefix_to_tabname[p] for p in valid_prefixes],
                            on_change="rerun", key="dev_tabular_active_tab",
                        )
                        for i, prefix in enumerate(valid_prefixes):
                            if not tabs[i].open:
                                continue
                            with tabs[i]:
                                group_cols = grouped_columns[prefix]

                                # Apply column filtering based on product type
                                filtered_group_cols = fn319_filter_columns_by_visibility(group_cols, prefix, current_product_type_table)

                                # For Details tab, exclude specific columns
                                if prefix == 'D':
                                    excluded_cols = ['D__Int/Ext', 'D__Application', 'D__DataComments']
                                    filtered_group_cols = [c for c in filtered_group_cols if c not in excluded_cols]

                                # Show filtering info
                                if len(filtered_group_cols) < len(group_cols):
                                    st.caption(f"ℹ️ Showing {len(filtered_group_cols)} of {len(group_cols)} available columns for this product type")

                                combined_cols = a_cols + filtered_group_cols

                                # Exclude A__Map_yn from column list if present
                                if "A__Map_yn" in combined_cols:
                                    combined_cols = [c for c in combined_cols if c != "A__Map_yn"]

                                # Filter rows: only show rows where A__Map_yn == "Y"
                                # Check A__Map_yn in original df_dev before selecting columns
                                if "A__Map_yn" in df_dev.columns:
                                    mask = df_dev["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"
                                    df_table_data = df_dev[mask][combined_cols].copy()
                                else:
                                    df_table_data = df_dev[combined_cols].copy()

                                # Clean DataFrame for PyArrow compatibility before displaying
                                df_display = fn211_clean_dataframe_for_streamlit(df_table_data)

                                # Strip column name prefixes for cleaner display
                                if prefix == 'G':
                                    # Strip "G__" from GWP Data columns
                                    df_display.columns = [col.replace("G__", "", 1) if col.startswith("G__") else col for col in df_display.columns]

                                    # Custom formatting for GWP Data: round < 10 to 3 decimals, >= 10 to 2 decimals, format "mnd"
                                    def format_gwp_value(val):
                                        """Format GWP values with custom rounding and mnd display"""
                                        if pd.isna(val):
                                            return "mnd"
                                        val_str = str(val).strip()
                                        val_lower = val_str.lower()
                                        # Check if it's "mnd" or similar missing/not defined values
                                        if val_lower in ["mnd", "n/a", "n/r", "-", "", "nan", "none"]:
                                            return "mnd"
                                        try:
                                            num_val = float(val)
                                            if num_val < 10:
                                                return f"{num_val:.3f}"
                                            else:
                                                return f"{num_val:.2f}"
                                        except (ValueError, TypeError):
                                            return str(val)

                                    # Apply formatting to GWP columns (excluding A__ identifier columns)
                                    for col in df_display.columns:
                                        if not col.startswith("A__"):
                                            df_display[col] = df_display[col].apply(format_gwp_value)

                                    st.markdown(_dev_gwp_tabular_html(df_display), unsafe_allow_html=True)
                                elif prefix == 'R':
                                    # Strip "R__" from Recycling Info columns
                                    df_display.columns = [col.replace("R__", "", 1) if col.startswith("R__") else col for col in df_display.columns]
                                    # Round numeric columns to 2 decimal places for Recycling Info
                                    df_display = fn320_round_numeric_columns(df_display, decimal_places=2)
                                    st.dataframe(df_display)
                                elif prefix == "VO":
                                    df_display.columns = [
                                        col.replace("VO__", "", 1)
                                        if col.startswith("VO__")
                                        else col
                                        for col in df_display.columns
                                    ]
                                    df_display = fn320_round_numeric_columns(df_display, decimal_places=2)
                                    st.dataframe(df_display)
                                    st.markdown("---")
                                    _dev_voc_pdf_preview_section(df_dev, df_table_data)
                                elif prefix == "VV":
                                    df_display.columns = [
                                        col.replace("VV__", "", 1)
                                        if col.startswith("VV__")
                                        else col
                                        for col in df_display.columns
                                    ]
                                    df_display = fn320_round_numeric_columns(df_display, decimal_places=2)
                                    st.dataframe(df_display)
                                else:
                                    # Round numeric columns to 2 decimal places for other tabs
                                    df_display = fn320_round_numeric_columns(df_display, decimal_places=2)
                                    st.dataframe(df_display)

        if sub_maps.open:
            with sub_maps:
                if not _is_dev:
                    st.info(_dev_only_msg)
                elif not _dev_lazy_section("maps", "Maps"):
                    pass
                else:
                    fn354_run_embedded_page(Path(__file__).resolve().parent / "4_Maps.py", "Maps")

        if sub_revalu.open:
            with sub_revalu:
                if not _is_dev:
                    st.info(_dev_only_msg)
                elif not _dev_lazy_section("revalu", "Revalu Matching"):
                    pass
                else:
                    fn354_run_embedded_page(
                        Path(__file__).resolve().parent / "6_RevaluMatching.py",
                        "Revalu Matching",
                        _revalu_embedded_in_developer=True,
                    )

        if sub_revalu_send.open:
            with sub_revalu_send:
                if not _is_dev:
                    st.info(_dev_only_msg)
                else:
                    _dev_revalu_send_section(df_filtered)

        if sub_options.open:
            with sub_options:
                if not _is_dev:
                    st.info(_dev_only_msg)
                else:
                    _run_add_edit_section("options", "Available options")

        if sub_crosswalk.open:
            with sub_crosswalk:
                if not _is_dev:
                    st.info(_dev_only_msg)
                else:
                    _cw_counts: dict[str, int] = {}
                    if _data_ok and "D__ProductType_ENG" in df_original.columns:
                        _cw_types = df_original["D__ProductType_ENG"].map(canonical_product_type)
                        _cw_counts = _cw_types[_cw_types != ""].value_counts().to_dict()
                    st.caption(
                        _tu("Product Types matched to Italian, European and international classification "
                        "systems. Mapping reference: `PRODUCT_TYPE_CLASSIFICATIONS.md`; row counts are live.")
                    )
                    st.iframe(fn630_build_classification_crosswalk_html(_cw_counts), height="content")

        if sub_voc_bodies.open:
            with sub_voc_bodies:
                if not _is_dev:
                    st.info(_dev_only_msg)
                else:
                    st.caption(
                        _tu("Every organisation behind a VOC claim in the vocabulary, the claims it "
                        "stands for and how many products carry each one. Bodies and tiers come "
                        "from `aux_11__voc_certifications.json`; counts, report types and spellings "
                        "are live. This page always reads the **whole library** — it describes "
                        "the vocabulary, so the sidebar filters and the Dataset choice above do "
                        "not apply to it.")
                    )
                    st.iframe(
                        fn631_build_voc_bodies_certs_html(
                            fn631_voc_bodies_payload(df_original if _data_ok else None)
                        ),
                        height="content",
                    )

    elif _active == _NAV_EPD:
        if not _is_dev:
            st.info(
                _tu("Please sign in as **developer** or **admin** to use **EPD Parse**.")
            )
        elif not _dev_lazy_section("epd_parse", "EPD Parse"):
            pass
        else:
            fn354_run_embedded_page(
                Path(__file__).resolve().parent / "6_EPD_Parse.py",
                "EPD Parse",
                _epd_parse_embedded_in_developer=True,
            )

    elif _active == _NAV_LOG:
        if not _is_dev:
            st.info(_dev_only_msg)
        else:
            _dev_change_log_section()

    elif _active == _NAV_CORR:
        if not _is_dev:
            st.info(_dev_only_msg)
        else:
            _dev_corrections_section()

    elif _active == _NAV_DOCS:
        if not _is_dev:
            st.info(_dev_only_msg)
        else:
            st.markdown(
                "<style>"
                f"{app_documentation_css()}"
                f"{app_documentation_css('eetra_app_docs_gwp')}"
                f"{database_schema_css()}"
                "</style>",
                unsafe_allow_html=True,
            )
            sub_docs_app, sub_docs_gwp, sub_docs_schema = st.tabs(
                ["App & data reference", "GWP conversion factors", "Database Schema"]
            )

            with sub_docs_app:
                _doc_path = Path(__file__).resolve().parent.parent / "APP_DOCUMENTATION.md"
                if not _doc_path.exists():
                    st.warning(
                        _tu("`APP_DOCUMENTATION.md` not found. Regenerate it by running "
                        "`document_app.cmd` from the app root.")
                    )
                else:
                    _doc_md = _doc_path.read_text(encoding="utf-8")
                    _c1, _c2 = st.columns([4, 1], vertical_alignment="center")
                    with _c1:
                        st.caption(
                            _tu("Auto-generated app & data reference. Regenerate with "
                            "`document_app.cmd` after code changes.")
                        )
                    with _c2:
                        st.download_button(
                            _tu("Download .md"),
                            data=_doc_md.encode("utf-8"),
                            file_name="APP_DOCUMENTATION.md",
                            mime="text/markdown",
                            key="dev_docs_download",
                            width="stretch",
                        )
                    fn303_custom_hr()
                    with st.container(height=720, border=False, key="eetra_app_docs"):
                        st.markdown(_doc_md, unsafe_allow_html=False)

            with sub_docs_gwp:
                with st.container(height=720, border=False, key="eetra_app_docs_gwp"):
                    _dev_gwp_conversion_reference(df_original)

            with sub_docs_schema:
                _schema_md_path = Path(__file__).resolve().parent.parent / "DATABASE_COLUMNS.md"
                if _schema_md_path.exists():
                    _schema_md = _schema_md_path.read_text(encoding="utf-8")
                    with st.container(border=False, key="eetra_database_schema"):
                        st.markdown(_schema_md)
                else:
                    st.info(
                        _tu("DATABASE_COLUMNS.md not found. Create it in the app root with "
                        "column documentation.")
                    )
