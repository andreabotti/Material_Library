"""
pages/13_Add_Edit_Item.py — Add / Edit a material item in the database
========================================================================
Three tabs (Add New Item / Edit Existing Item / Available options)
rendering the same multi-column form, grouped by category (Summary, Identity, Details,
EPD - Gen. Data, EPD - GWP Data, Recycling & EOL, Health, Various, Comments).

Add and Edit render through the browser-side editor (libs/item_editor, see
"browser-side editor" near the end of this file): the draft and every derived
read-out live in JavaScript, so editing triggers no reruns. The widget form
remains in this file for AppTest suites (they set add_edit_classic_form).

Every field shows, underneath its widget:
  • a colour-coded status pill — 🟢 Filled / 🟠 Missing / ⚪ Not relevant
    (Missing vs. Not-relevant reuses the same per-product-type field
    visibility rules the Catalogue already applies — aux_10__ui_config.json)
  • its Revalu API counterpart (from the "Get EPD Extended" schema at
    docs.revalu.io), so the two taxonomies stay visibly aligned.

Persistence (two-file model — see libs/lib_data.py fn153–fn158):
  • reads  base_data.parquet ⊕ edits_data.parquet — the effective dataset
  • writes ONLY to edits_data.parquet, appending one full-row snapshot per
    save plus _edit_id / _edit_ts / _edit_user / _edit_op. Nothing else is
    written: readers derive base ⊕ edits themselves (fn159_effective_dataset).
  • deleting an item (Edit Existing Item, behind a two-step confirmation)
    appends a `delete` record carrying the snapshot of the removed row. The
    row leaves the effective dataset, base_data.parquet keeps it, and the
    delete is undone by removing that record from the log.
  • EPD families (libs/lib_epd_family.py): a product flagged N in
    E__EPD_ConvFactor gets its GWP data derived from the family's Y product ×
    E__EPD_MultFactor (fields locked); saving the Y product appends one update
    record per changed variant in the same write.
base_data.parquet is the Excel conversion and is never touched here, so
re-running the Excel pipeline never has to reconcile app edits. Writes are
atomic (temp file + os.replace), matching tags.parquet / collections.parquet
in libs/lib_tags.py. Switch the sidebar Data Source to "Local Parquet" to see
changes; SharePoint mode is unaffected (this page never writes to SharePoint).
"""

from __future__ import annotations

import html
import re
from datetime import date

from libs.page_imports import *  # noqa: F401,F403

from libs.lib_data import (
    HIDDEN_APP_COLUMNS,
    fn147_next_eetra_id             as _next_eetra_id,
    fn148_upsert_live_data_row      as _upsert_row,
    fn152_edit_picker_dataframe     as _edit_picker_dataframe,
    fn153c_base_available           as _base_available,
    fn154_resolve_edits_parquet_path as _resolve_edits_path,
    fn156_append_edit_record        as _append_edit,
    fn156b_append_edit_records      as _append_edits,
    fn158a_cached_load_effective_live as _cached_effective_df,
    fn158b_effective_live_mtimes    as _effective_mtimes,
)
from libs.lib_revalu_map import (
    CATEGORIES, NUMBER_FIELDS, TEXTAREA_FIELDS, READONLY_FIELDS, URL_FIELDS,
    YN_SELECT_FIELDS, DATE_FIELDS,
    OPTIONAL_PCT_SENTINEL_FIELDS, OPTIONAL_PCT_SENTINELS, normalize_optional_pct,
    field_status, status_badge_html, revalu_caption_html, label_for, help_for,
    widget_help_kwargs, textarea_height, included_products_display,
    field_disabled_for_product_type, OPTION_SELECT_FIELDS, status_rect_cell_style,
    VOC_FIELDS, VOC_NOT_RELEVANT_VALUE, VOC_CERT_NR_LOCK_FIELDS,
    VOC_DATA_RELEVANT_FIELD, VOC_DATA_RELEVANT_VALUES,
    voc_not_relevant, voc_cert_is_not_relevant, voc_data_is_not_relevant,
    voc_emissions_locked,
    PHYSICAL_PROPERTY_FIELDS, physical_cm_column, infer_physical_cm, PHYSICAL_CM_HELP,
    voc_cert_labels, voc_cert_clarification, voc_cert_tiers, voc_cert_caveat,
    voc_cert_by_label, VOC_LEED_PATHWAYS, VOC_BODIES,
    VOC_CHECKLIST_FIELDS, VOC_CHECKLIST_VALUES, VOC_CHECKLIST_DERIVED,
    voc_checklist_derived, voc_cert_alignment, voc_rating_frameworks,
    voc_alignment_lookup,
)
from libs.lib_tokens import theme_section, add_edit_form_css
from libs.lib_i18n import fn714_tu as _tu
from libs.lib_epd_family import (
    DERIVED_COLS as _EPD_DERIVED_COLS,
    FACTOR_COL as _EPD_FACTOR_COL,
    REF_FLAG_COL as _EPD_REF_FLAG_COL,
    REG_COL as _EPD_REG_COL,
    fn620_normalise_reg as _epd_reg_key,
    fn621_num as _epd_num,
    fn622_is_reference as _epd_is_reference,
    fn623_is_variant as _epd_is_variant,
    fn625_family_reference as _epd_family_reference,
    fn626_family_variants as _epd_family_variants,
    fn628_variant_gwp_values as _epd_variant_values,
    fn629_propagation_plan as _epd_propagation_plan,
)


def _add_edit_col_gap() -> int:
    """Pixel gap for ``st.columns`` (Streamlit >=1.60: ``gap`` as int). Theme: ``widget_columns_gap_px``."""
    return int(
        (theme_section("developer_dashboard", "add_edit_form") or {}).get(
            "widget_columns_gap_px", 15
        )
    )


@st.dialog("VOC certifications & clarifications", width="large")
def _voc_cert_catalog_dialog(selected_label: str = "") -> None:
    """Popup table of every curated VOC claim; highlights the dropdown selection."""
    selected = str(selected_label or "").strip()
    selected_entry = voc_cert_by_label(selected)
    selected_canonical = (
        str(selected_entry.get("label") or "").strip() if selected_entry else selected
    )

    caveat = voc_cert_caveat()
    if caveat:
        st.caption(caveat)
    if selected_canonical:
        if selected_entry:
            st.markdown(f"**Selected:** {selected_canonical}")
        else:
            st.info(
                f"**{selected_canonical}** is not in the curated catalog — "
                "showing the full reference list without a highlight."
            )

    rows_html: list[str] = []
    for tier in voc_cert_tiers():
        tier_label = str(tier.get("label") or "").strip()
        for entry in tier.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            desc = str(entry.get("description") or "").strip()
            hint = str(entry.get("cert_number_hint") or "").strip()
            body = desc + (f" {hint}" if hint else "")
            is_sel = bool(
                selected_canonical
                and label.lower() == selected_canonical.lower()
            )
            bg = "#eaf3ea" if is_sel else "#ffffff"
            weight = "600" if is_sel else "500"
            mark = " ✓" if is_sel else ""
            rows_html.append(
                "<tr style="
                f"'background:{bg};'>"
                f"<td style='padding:8px 10px;vertical-align:top;color:#6b7280;"
                f"white-space:nowrap;'>{html.escape(tier_label)}</td>"
                f"<td style='padding:8px 10px;vertical-align:top;font-weight:{weight};"
                f"color:#111827;white-space:nowrap;'>{html.escape(label)}{mark}</td>"
                f"<td style='padding:8px 10px;vertical-align:top;color:#374151;"
                f"line-height:1.4;'>{html.escape(body)}</td>"
                "</tr>"
            )

    if not rows_html:
        st.warning(_tu("VOC catalog is empty — check `aux_11__voc_certifications.json`."))
        return

    st.markdown(
        "<div style='max-height:min(70vh,640px);overflow:auto;"
        "border:1px solid #e5e7eb;border-radius:8px;'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>"
        "<thead style='position:sticky;top:0;background:#f8fafc;z-index:1;'>"
        "<tr>"
        "<th style='text-align:left;padding:8px 10px;border-bottom:1px solid #e5e7eb;"
        "color:#64748b;font-weight:600;'>Tier</th>"
        "<th style='text-align:left;padding:8px 10px;border-bottom:1px solid #e5e7eb;"
        "color:#64748b;font-weight:600;'>Certification / claim</th>"
        "<th style='text-align:left;padding:8px 10px;border-bottom:1px solid #e5e7eb;"
        "color:#64748b;font-weight:600;'>Clarification</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    if st.button(_tu("Close"), key="voc_cert_dialog_close"):
        st.rerun()

# When embedded inside another page's tab the title is provided by the host,
# so suppress this page's own header to avoid a double title.
if not fn352_is_embedded_page():
    fn003a_page_header(
        "Add / Edit Item",
        "Create new products or edit existing ones — mapped against the Revalu API field taxonomy.",
    )


# ── data access ──────────────────────────────────────────────────────────────
# Cached on both parquets' mtimes, so the page still always sees the latest file:
# a save appends to the edit log, which moves its mtime and misses the cache on the
# very next rerun. It used to re-read and re-merge the parquet uncached — once per
# tab, on every keystroke in a form with hundreds of widgets.
def _load_raw() -> tuple[pd.DataFrame, "Path"]:
    """Effective dataset = base_data.parquet ⊕ edits_data.parquet.

    The returned path is the **edit log** — the only file this page writes to.
    ``base_data.parquet`` is owned by ``04_tools/03_excel_to_parquet.py`` and is
    never modified here, so an Excel refresh never has to reconcile app edits.
    The frame is this caller's own copy (``st.cache_data``), safe to modify.
    """
    if not _base_available():
        st.error(
            _tu("Base dataset not found — run `04_tools/03_excel_to_parquet.py`, then "
            "`04_tools/15_parquet_to_neon.py` if Neon is configured.")
        )
        st.stop()
    return _cached_effective_df(*_effective_mtimes()), _resolve_edits_path()


def _persist(updated_df: pd.DataFrame, eetra_id: str, op: str) -> None:
    """Append the saved row to the append-only edit log.

    Readers pick the change up on the next rerun: the merge is keyed on this
    file's mtime, so appending is all that is needed."""
    row = updated_df.loc[updated_df["0__EETRA_ID"].astype(str) == str(eetra_id)].iloc[0]
    _append_edit(
        row.to_dict(),
        eetra_id=eetra_id,
        op=op,
        base_columns=list(updated_df.columns),
        path=_resolve_edits_path(),
    )


def _persist_delete(raw_df: pd.DataFrame, eetra_id: str) -> None:
    """Tombstone one item in the append-only edit log.

    Nothing is erased: the record carries a full snapshot of the row as it was,
    and ``base_data.parquet`` is untouched. The merge (lib_data fn157) drops the
    id from the effective dataset, so the item leaves the catalogue on the next
    rerun; restoring it means removing that record from the log.
    """
    match = raw_df.loc[raw_df["0__EETRA_ID"].astype(str) == str(eetra_id)]
    snapshot = match.iloc[0].to_dict() if not match.empty else {"0__EETRA_ID": eetra_id}
    _append_edit(
        snapshot,
        eetra_id=eetra_id,
        op="delete",
        base_columns=list(raw_df.columns),
        path=_resolve_edits_path(),
    )


_column_display_labels = st.session_state.get("COLUMN_DISPLAY_LABELS", {})


def _label_for(col: str) -> str:
    return label_for(col, _column_display_labels)


def _product_types(df: pd.DataFrame) -> list[str]:
    if "D__ProductType_ENG" not in df.columns:
        return []
    vals = sorted({str(v).strip() for v in df["D__ProductType_ENG"].dropna() if str(v).strip()})
    return vals


def _manufacturers(df: pd.DataFrame) -> list[str]:
    if "A__Manufacturer" not in df.columns:
        return []
    vals = sorted({str(v).strip() for v in df["A__Manufacturer"].dropna() if str(v).strip()})
    return [v for v in vals if v.lower() not in ("nan", "-")]


_SEMICOLON_SPLIT_OPTION_COLS = frozenset({"E__ManuCountry"})


def _option_tokens_from_cell(value, col_name: str) -> list[str]:
    """Normalise one cell into countable tokens (split multi-country values on ';')."""
    s = str(value).strip()
    if not s or s == "-" or s.lower() in ("nan", "none", "<na>"):
        return []
    if s.startswith("*"):
        return []
    if col_name in _SEMICOLON_SPLIT_OPTION_COLS:
        return [
            part for part in (p.strip() for p in s.split(";"))
            if part and part != "-" and part.lower() not in ("nan", "none", "<na>")
        ]
    return [s]


def _distinct_field_options(df: pd.DataFrame, col: str) -> list[str]:
    """Unique values for option dropdowns (same token rules as Available options)."""
    if col not in df.columns:
        return []
    seen: set[str] = set()
    for value in df[col].dropna():
        for token in _option_tokens_from_cell(value, col):
            seen.add(token)
    return sorted(seen, key=lambda s: s.lower())


@st.cache_data(show_spinner=False, max_entries=2)
def _cached_form_options(
    base_mtime_ns: int, edits_mtime_ns: int
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """(product types, manufacturers, per-field option lists) for one file version.

    Scanning every option column takes noticeable time and the form re-renders on
    each widget change; the answer only moves when a parquet does.
    """
    df = _cached_effective_df(base_mtime_ns, edits_mtime_ns)
    return (
        _product_types(df),
        _manufacturers(df),
        {col: _distinct_field_options(df, col) for col in OPTION_SELECT_FIELDS},
    )


def _field_option_lists(df: pd.DataFrame | None = None) -> dict[str, list[str]]:
    if df is None:
        out = dict(_cached_form_options(*_effective_mtimes())[2])
    else:
        out = {col: _distinct_field_options(df, col) for col in OPTION_SELECT_FIELDS}
    # VOC cert: catalog presets first (stable order), then any extra dataset values.
    preset = voc_cert_labels()
    if preset:
        seen = {s.lower() for s in preset}
        extras = [v for v in out.get("VO__VOC_Cert", []) if v.lower() not in seen]
        out["VO__VOC_Cert"] = preset + extras
    # LEED pathway: same treatment, so the field offers its vocabulary from the
    # first row edited rather than starting empty.
    pathways = list(VOC_LEED_PATHWAYS)
    seen = {s.lower() for s in pathways}
    extras = [v for v in out.get("VO__LEED_Pathway", []) if v.lower() not in seen]
    out["VO__LEED_Pathway"] = pathways + extras
    # Testing / certifying body: the curated list first, then any lab already
    # recorded in the data that the list does not name.
    bodies = list(VOC_BODIES)
    seen = {s.lower() for s in bodies}
    extras = [v for v in out.get("VO__VOC_Body", []) if v.lower() not in seen]
    out["VO__VOC_Body"] = bodies + extras
    return out


_OPTION_SELECT_NEW_LABELS: dict[str, tuple[str, str]] = {
    "D__MaterialType_ENG": ("➕ New material type…", "New material type name"),
    "E__ManuCountry": ("➕ New country…", "New manufacturing country"),
    "E__EPD_Programme": ("➕ New EPD programme…", "New EPD programme name"),
    "VO__VOC_Cert": ("➕ New VOC claim…", "New VOC certification / claim name"),
    "VO__VOC_Body": ("➕ New body…", "New testing laboratory / certifying body"),
}

def _select_or_new(
    label: str,
    options: list[str],
    current,
    key: str,
    *,
    new_label: str,
    new_input_label: str,
    label_visibility: str = "visible",
) -> str:
    """Dropdown from existing values, with optional free-text new entry."""
    cur_str = str(current).strip() if current not in (None, "") else ""
    menu = ["— select —"] + options + [new_label]
    if cur_str and cur_str not in menu:
        menu = ["— select —", cur_str] + options + [new_label]
    default_idx = menu.index(cur_str) if cur_str in menu else 0
    choice = st.selectbox(
        label, menu, index=default_idx, key=key,
        label_visibility=label_visibility,
    )
    if choice == new_label:
        return str(st.text_input(new_input_label, key=key + "_new") or "").strip()
    return "" if choice == "— select —" else choice


def _coerce_date_value(current) -> date | None:
    if current is None or pd.isna(current):
        return None
    s = str(current).strip()
    if not s or s in ("-", "nan", "None", "<NA>"):
        return None
    try:
        # ISO-like strings ("2026-09-17", "2026-09-17 10:30:00") are unambiguous
        # and must not be parsed with dayfirst=True (pandas warns and ignores it).
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            ts = pd.to_datetime(s, errors="coerce")
        else:
            ts = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


_OPTIONAL_PCT_MODES = ("", "value", "n/d", "n/a")
_OPTIONAL_PCT_MODE_LABELS = {
    "": "(blank)",
    "value": "Enter %…",
    "n/d": "n/d — not declared",
    "n/a": "n/a",
}


def _optional_pct_mode_from_current(current) -> tuple[str, float | None]:
    """Infer select mode + numeric seed from a stored Pre/Post value."""
    norm = normalize_optional_pct(current)
    if not norm:
        return "", None
    if norm in OPTIONAL_PCT_SENTINELS:
        return norm, None
    try:
        return "value", float(norm.replace(",", "."))
    except (TypeError, ValueError):
        return "", None


def _widget_optional_pct(
    col: str,
    current,
    key: str,
    *,
    label: str,
    disabled: bool = False,
):
    """Percentage with explicit ``n/d`` / ``n/a`` when only a total is published."""
    mode_key = f"{key}__mode"
    num_key = f"{key}__num"
    init_mode, init_num = _optional_pct_mode_from_current(current)
    if mode_key not in st.session_state:
        st.session_state[mode_key] = init_mode
    mode = st.selectbox(
        label,
        options=list(_OPTIONAL_PCT_MODES),
        key=mode_key,
        format_func=lambda m: _OPTIONAL_PCT_MODE_LABELS.get(m, m),
        disabled=disabled,
        **widget_help_kwargs(col),
    )
    if mode == "n/d":
        return "n/d"
    if mode == "n/a":
        return "n/a"
    if mode != "value":
        return ""
    if num_key not in st.session_state:
        st.session_state[num_key] = init_num
    return st.number_input(
        f"{label} value",
        key=num_key,
        format="%.4f",
        step=0.1,
        disabled=disabled,
        label_visibility="collapsed",
        **widget_help_kwargs(col),
    )


def _widget_for_field(
    col: str,
    current,
    key: str,
    product_types: list[str],
    manufacturers: list[str],
    *,
    disabled: bool = False,
    label_override: str | None = None,
    field_options: dict[str, list[str]] | None = None,
):
    """Render the input widget for one field and return its current value."""
    label = label_override or _label_for(col)
    if col in READONLY_FIELDS:
        st.text_input(label, value="" if current is None else str(current), key=key, disabled=True)
        return current
    if col == "D__ProductType_ENG":
        return _select_or_new(
            label,
            product_types,
            current,
            key,
            new_label="➕ New product type…",
            new_input_label="New product type name",
        )
    if col == "A__Manufacturer":
        return _select_or_new(
            label,
            manufacturers,
            current,
            key,
            new_label="➕ New manufacturer…",
            new_input_label="New manufacturer name",
        )
    if col in OPTION_SELECT_FIELDS:
        opts = (field_options or {}).get(col, [])
        new_label, new_input = _OPTION_SELECT_NEW_LABELS.get(
            col, ("➕ New value…", "New value")
        )
        if col == "VO__VOC_Cert":
            # ⓘ sits beside the field label (no extra button row under the widget).
            _lab, _info = st.columns([12, 1], gap="small", vertical_alignment="center")
            with _lab:
                st.markdown(
                    f'<div style="font-size:0.875rem;font-weight:500;color:inherit;'
                    f'line-height:1.25;padding-top:0.15rem;">{html.escape(label)}</div>',
                    unsafe_allow_html=True,
                )
            with _info:
                _open = st.button(
                    "ⓘ",
                    key=f"{key}_voc_info",
                    help=_tu("Clarifications for all VOC certifications — highlights the selected value."),
                )
            chosen = _select_or_new(
                label, opts, current, key,
                new_label=new_label, new_input_label=new_input,
                label_visibility="collapsed",
            )
            if _open:
                _voc_cert_catalog_dialog(chosen)
            return chosen
        return _select_or_new(
            label, opts, current, key,
            new_label=new_label, new_input_label=new_input,
        )
    if col == _EPD_REF_FLAG_COL:
        cur_str = "" if current in (None, "") or pd.isna(current) else str(current).strip()
        cur_str = {"YES": "Y", "NO": "N"}.get(cur_str.upper(), cur_str)
        options = ["", "Y", "N", "n/r"]
        # Legacy workbook values ("*", stray numbers) stay selectable so a save
        # never silently blanks them.
        if cur_str and cur_str not in options:
            options.append(cur_str)
        _fmt = {
            "": "(blank)",
            "Y": "Y — reference product (factor 1)",
            "N": "N — reference × multiplication factor",
        }
        return st.selectbox(label, options, index=options.index(cur_str), key=key,
                            format_func=lambda v: _fmt.get(v, v), disabled=disabled,
                            **widget_help_kwargs(col))
    if col == VOC_DATA_RELEVANT_FIELD:
        options = list(VOC_DATA_RELEVANT_VALUES)
        cur_str = str(current).strip() if current not in (None, "") else ""
        if cur_str and cur_str not in options:
            options.append(cur_str)
        _fmt = {
            "": "(blank)",
            "Yes": "Yes — VOC data applies",
            "No": "No — lock VOC fields to n/r",
            "Not sure": "Not sure — leave editable",
        }
        return st.selectbox(
            label, options, index=options.index(cur_str) if cur_str in options else 0,
            key=key, format_func=lambda v: _fmt.get(v, v), disabled=disabled,
            **widget_help_kwargs(col),
        )
    if col in VOC_CHECKLIST_FIELDS:
        options = list(VOC_CHECKLIST_VALUES)
        cur_str = str(current).strip() if current not in (None, "") else ""
        # A legacy value stays selectable so a save never silently blanks it.
        if cur_str and cur_str not in options:
            options.append(cur_str)
        return st.selectbox(
            label, options, index=options.index(cur_str) if cur_str in options else 0,
            key=key, format_func=lambda v: v or "(not reviewed)", disabled=disabled,
            **widget_help_kwargs(col),
        )
    if col == "A__Map_yn" or col in YN_SELECT_FIELDS:
        options = ["", "Y", "N"]
        cur_str = str(current).strip().upper() if current not in (None, "") else ""
        default_idx = options.index(cur_str) if cur_str in options else 0
        return st.selectbox(label, options, index=default_idx, key=key,
                             format_func=lambda v: v or "(blank)", disabled=disabled,
                             **widget_help_kwargs(col))
    if col in DATE_FIELDS:
        picked = st.date_input(
            label,
            value=_coerce_date_value(current),
            key=key,
            disabled=disabled,
            **widget_help_kwargs(col),
        )
        return picked.isoformat() if picked else ""
    if col in OPTIONAL_PCT_SENTINEL_FIELDS:
        return _widget_optional_pct(col, current, key, label=label, disabled=disabled)
    if col in NUMBER_FIELDS:
        try:
            num_val = float(current) if current not in (None, "", "-") and pd.notna(current) else None
        except Exception:
            num_val = None
        return st.number_input(label, value=num_val, key=key, format="%.4f", step=0.1,
                               disabled=disabled, **widget_help_kwargs(col))
    if col in TEXTAREA_FIELDS:
        if col == "D__IncludedProducts":
            _ta_val = included_products_display(current)
        else:
            _ta_val = "" if current in (None, "-") or pd.isna(current) else str(current)
        return st.text_area(label, value=_ta_val,
                            key=key, height=textarea_height(col), disabled=disabled, **widget_help_kwargs(col))
    # Once the key lives in session state (e.g. a value derived by
    # _sync_thickness_density), let it drive the widget — passing ``value``
    # too would trigger Streamlit's "set via Session State API" warning.
    value_kwargs = {} if key in st.session_state else {
        "value": "" if current in (None, "-") or pd.isna(current) else str(current)
    }
    return st.text_input(label, key=key, disabled=disabled, **value_kwargs, **widget_help_kwargs(col))


def _external_href(url: str) -> str | None:
    u = str(url or "").strip()
    if not u or u in ("-", "nan", "None", "<NA>"):
        return None
    if u.lower().startswith(("http://", "https://")):
        return u
    if "://" not in u:
        return "https://" + u.lstrip("/")
    return u


def _url_ready_to_probe(url: str) -> bool:
    """Skip partial URLs while the user is still typing."""
    from libs.lib_data import fn142a_is_usable_document_url

    u = _external_href(url)
    if not u or not fn142a_is_usable_document_url(u):
        return False
    try:
        from urllib.parse import urlparse

        host = (urlparse(u).netloc or "").lower()
    except Exception:
        return False
    if not host or "." not in host:
        return False
    return True


def _url_probe_kind(col: str) -> str:
    if col == "U__Img_URL":
        return "image"
    if col in ("VO__VOC_URL", "U__TechDetails_URL", "VV__MSDS__URL", "VV__DOP"):
        return "pdf"
    return "generic"


def _cached_url_probe(url: str, col: str) -> dict | None:
    """Auto-check URL reachability (cached per URL in lib_data.fn142b_probe_http_url)."""
    from libs.lib_data import fn142b_probe_http_url

    u = str(url or "").strip()
    if not _url_ready_to_probe(u):
        return None
    return fn142b_probe_http_url(u, _url_probe_kind(col))


def _url_probe_badge_html(probe: dict | None) -> str:
    if probe is None:
        return (
            '<span style="color:#9ca3af;font-size:0.78rem;margin-left:0.35rem;" '
            'title="Auto-check runs when the URL looks complete">…</span>'
        )
    level = str(probe.get("level") or "error")
    label = html.escape(str(probe.get("label") or "—"))
    detail = html.escape(str(probe.get("detail") or ""))
    if level == "ok":
        color, icon = "#059669", "✓"
    elif level == "warn":
        color, icon = "#d97706", "⚠"
    elif level == "idle":
        return '<span style="color:#9ca3af;font-size:0.78rem;margin-left:0.35rem;">—</span>'
    else:
        color, icon = "#dc2626", "✗"
    return (
        f'<span style="color:{color};font-size:0.78rem;margin-left:0.35rem;white-space:nowrap;" '
        f'title="{detail}">{icon} {label}</span>'
    )


def _url_link_html(url: str, *, probe: dict | None = None) -> str:
    href = _external_href(url)
    badge = _url_probe_badge_html(probe)
    if not href:
        return f'<span style="color:#9ca3af;font-size:0.85rem;">—</span>{badge}'
    return (
        f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'style="font-size:0.85rem;line-height:1.35;">Test Link</a>{badge}'
    )


def _identity_preview_context(
    existing_row: dict | None,
    values: dict,
) -> tuple[str | None, str | None]:
    row_dict = dict(existing_row or {})
    if values:
        row_dict.update(values)
    eid = str(row_dict.get("0__EETRA_ID", "") or "").strip()
    pname = str(row_dict.get("A__ProductName", "") or "").strip()
    return (eid or None, pname or None)


def _image_preview_pil(url: str, *, eetra_id: str | None, product_name: str | None):
    from libs.lib_data import fn110_cached_fetch_image, fn142a_is_usable_document_url

    if not fn142a_is_usable_document_url(url):
        return None
    try:
        img = fn110_cached_fetch_image(
            str(url).strip(),
            "catalogue",
            eetra_id=eetra_id,
            product_name=product_name,
        )
    except Exception:
        return None
    if img is None or not hasattr(img, "size"):
        return None
    return img


# Shared Identity side-label row geometry: label+meta | input | Test Link | preview.
# Same weights for Product Info / Tech Details / Image.
_IDENTITY_URL_ROW_WEIGHTS = [1.15, 5.2, 1.05, 0.75]


def _side_label_block_html(col: str, status: str) -> str:
    """Title + status/Revalu stacked under it (left of the input, inside field height)."""
    label = html.escape(_label_for(col))
    tip = help_for(col)
    tip_attr = f' title="{html.escape(tip, quote=True)}"' if tip else ""
    return (
        f'<div class="add-edit-side-label-block">'
        f'<div class="add-edit-side-label"{tip_attr}>{label}</div>'
        f'<div class="add-edit-side-meta">{status_badge_html(status)}</div>'
        f'<div class="add-edit-side-meta">{revalu_caption_html(col)}</div>'
        f"</div>"
    )


def _identity_url_row_columns(*, vertical_alignment: str = "top"):
    """Four equal-geometry columns for every Identity side-label row."""
    return st.columns(
        list(_IDENTITY_URL_ROW_WEIGHTS),
        gap=_add_edit_col_gap(),
        vertical_alignment=vertical_alignment,
    )


def _render_side_label_textarea_field(
    col: str,
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
    *,
    with_test_link: bool = False,
) -> None:
    """label+meta | textarea | optional Test Link | empty preview — shared Identity layout."""
    current = (existing_row or {}).get(col)
    key = f"{mode}_{col}"
    _val_str = "" if current in (None, "-") or pd.isna(current) else str(current)
    _pre = _resolve_field_value(mode, col, existing_row)
    _status = field_status(
        col, _pre, values.get("D__ProductType_ENG", product_type_current)
    )

    label_col, input_col, link_col, _preview_col = _identity_url_row_columns(
        vertical_alignment="top"
    )
    with label_col:
        st.markdown(_side_label_block_html(col, _status), unsafe_allow_html=True)
    with input_col:
        val = st.text_area(
            _label_for(col),
            value=_val_str,
            key=key,
            height=textarea_height(col),
            label_visibility="collapsed",
            **widget_help_kwargs(col),
        )
    with link_col:
        if with_test_link:
            _probe = _cached_url_probe(str(val or ""), col)
            st.markdown(_url_link_html(str(val or ""), probe=_probe), unsafe_allow_html=True)
    values[col] = val


def _render_img_url_field(
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
) -> None:
    """Image URL row: label+meta | input | Test Link | live preview."""
    col = "U__Img_URL"
    current = (existing_row or {}).get(col)
    key = f"{mode}_{col}"
    eid, pname = _identity_preview_context(existing_row, values)
    # session_state already holds the latest value at the start of the run
    _pre = _resolve_field_value(mode, col, existing_row)
    _status = field_status(
        col, _pre, values.get("D__ProductType_ENG", product_type_current)
    )

    label_col, input_col, link_col, preview_col = _identity_url_row_columns(
        vertical_alignment="top"
    )
    with label_col:
        st.markdown(_side_label_block_html(col, _status), unsafe_allow_html=True)
    with input_col:
        val = st.text_input(
            _label_for(col),
            value="" if current in (None, "-") or pd.isna(current) else str(current),
            key=key,
            label_visibility="collapsed",
            **widget_help_kwargs(col),
        )
    with link_col:
        _probe = _cached_url_probe(str(val or ""), col)
        st.markdown(_url_link_html(str(val or ""), probe=_probe), unsafe_allow_html=True)
    with preview_col:
        preview = _image_preview_pil(str(val or ""), eetra_id=eid, product_name=pname)
        if preview is not None:
            st.image(preview, width=72)
        else:
            st.markdown(
                '<div style="width:72px;max-width:100%;min-height:48px;'
                'border:1px dashed #d1d5db;border-radius:8px;display:flex;'
                'align-items:center;justify-content:center;color:#9ca3af;font-size:0.72rem;">'
                "—</div>",
                unsafe_allow_html=True,
            )
    values[col] = val


def _render_url_field(
    col: str,
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
) -> None:
    # Identity Product Info / Tech Details: side-label grid (label | input | Test Link).
    if col in ("U__ProductInfo_URL", "U__TechDetails_URL"):
        if col == "U__ProductInfo_URL":
            render_add_edit_section_title_with_divider("Product Info URLs")
        _render_side_label_textarea_field(
            col, mode, existing_row, values, product_type_current,
            with_test_link=True,
        )
        return

    current = (existing_row or {}).get(col)
    key = f"{mode}_{col}"
    _val_str = "" if current in (None, "-") or pd.isna(current) else str(current)

    input_col, link_col = st.columns(
        [3, 2], gap=_add_edit_col_gap(), vertical_alignment="bottom"
    )
    with input_col:
        val = st.text_input(
            _label_for(col),
            value=_val_str,
            key=key,
            **widget_help_kwargs(col),
        )
    with link_col:
        _probe = _cached_url_probe(str(val or ""), col)
        st.markdown(_url_link_html(str(val or ""), probe=_probe), unsafe_allow_html=True)

    values[col] = val
    status = field_status(col, val, values.get("D__ProductType_ENG", product_type_current))
    st.markdown(
        f'{status_badge_html(status)} &nbsp; {revalu_caption_html(col)}',
        unsafe_allow_html=True,
    )


def _voc_preview_row(mode: str, existing_row: dict | None, values: dict) -> pd.Series:
    row_dict = dict(existing_row or {})
    if values:
        row_dict.update(values)
    return pd.Series(row_dict)


def _render_voc_url_field(
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
) -> None:
    """Wide URL input, Test Link, and in-app Open VOC document dialog on one row."""
    from libs.lib_data import fn142a_is_usable_document_url
    from libs.lib_ui import fn346_fetch_document_pdf_bytes, fn348_voc_document_pdf_dialog

    col = "VO__VOC_URL"
    current = (existing_row or {}).get(col)
    key = f"{mode}_{col}"
    input_col, link_col, open_col = st.columns(
        [5.5, 1.1, 1.35], gap=_add_edit_col_gap(), vertical_alignment="bottom"
    )
    with input_col:
        val = st.text_input(
            _label_for(col),
            value="" if current in (None, "-") or pd.isna(current) else str(current),
            key=key,
            **widget_help_kwargs(col),
        )
    with link_col:
        _probe = _cached_url_probe(str(val or ""), col)
        st.markdown(_url_link_html(str(val or ""), probe=_probe), unsafe_allow_html=True)
    with open_col:
        _can_open = fn142a_is_usable_document_url(val)
        if st.button(
            _tu("Open VOC document"),
            key=f"{mode}_voc_open_pdf",
            disabled=not _can_open,
            width="stretch",
        ):
            row_series = _voc_preview_row(mode, existing_row, values)
            eid = str(row_series.get("0__EETRA_ID", "") or "")
            pname = str(row_series.get("A__ProductName", "") or "")
            bdata, _, _ = fn346_fetch_document_pdf_bytes(
                str(val).strip(), eid, pname, "voc", row=row_series
            )
            if bdata:
                fn348_voc_document_pdf_dialog(bdata)
            else:
                st.warning(_tu("Could not load the VOC PDF for preview."))
    values[col] = val
    status = field_status(col, val, values.get("D__ProductType_ENG", product_type_current))
    st.markdown(
        f'{status_badge_html(status)} &nbsp; {revalu_caption_html(col)}',
        unsafe_allow_html=True,
    )


def _ensure_physical_cm_session(
    host_col: str,
    mode: str,
    existing_row: dict | None,
    values: dict,
) -> str:
    """Initialise the C/M session key if missing; return the current flag (``C``/``M``/``""``)."""
    cm_col = physical_cm_column(host_col)
    key = f"{mode}_{cm_col}"
    if key not in st.session_state:
        row_for_infer = dict(existing_row or {})
        row_for_infer.update(values)
        stored = str((existing_row or {}).get(cm_col, "") or "").strip().upper()
        if stored not in ("C", "M"):
            stored = infer_physical_cm(host_col, row_for_infer)
        st.session_state[key] = stored if stored in ("C", "M") else ""
    return str(st.session_state.get(key, "") or "").strip().upper()


def _render_physical_cm_select(
    host_col: str,
    mode: str,
    existing_row: dict | None,
    values: dict,
    *,
    disabled: bool = False,
) -> None:
    """Narrow C/M dropdown (Calculated / Manually entered), shown right of its host widget."""
    cm_col = physical_cm_column(host_col)
    key = f"{mode}_{cm_col}"
    _ensure_physical_cm_session(host_col, mode, existing_row, values)
    options = ["", "C", "M"]
    picked = st.selectbox(
        _tu("C/M"),
        options,
        key=key,
        help=PHYSICAL_CM_HELP,
        disabled=disabled,
        format_func=lambda v: {"C": "C", "M": "M", "": "—"}.get(v, v),
    )
    values[cm_col] = picked


def _voc_cert_value(
    mode: str,
    existing_row: dict | None,
    values: dict | None = None,
):
    """Latest VOC Certification choice (this run's widget, session, or row)."""
    return _effective_field_value(mode, "VO__VOC_Cert", existing_row, values)


def _voc_data_relevant_value(
    mode: str,
    existing_row: dict | None,
    values: dict | None = None,
):
    """Latest VOC Data Relevant choice (this run's widget, session, or row)."""
    return _effective_field_value(mode, VOC_DATA_RELEVANT_FIELD, existing_row, values)


def _render_one_field(
    col: str,
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
    product_types: list[str],
    manufacturers: list[str],
    label_override: str | None = None,
    field_options: dict[str, list[str]] | None = None,
) -> None:
    if col == "U__Img_URL":
        _render_img_url_field(mode, existing_row, values, product_type_current)
        return
    if col == "VO__VOC_URL":
        _render_voc_url_field(mode, existing_row, values, product_type_current)
        return
    if col in URL_FIELDS:
        _render_url_field(col, mode, existing_row, values, product_type_current)
        return
    current = (existing_row or {}).get(col)
    key = f"{mode}_{col}"
    product_type = str(values.get("D__ProductType_ENG", product_type_current) or "")
    voc_cert = _voc_cert_value(mode, existing_row, values)
    data_relevant = _voc_data_relevant_value(mode, existing_row, values)
    _derived = _EPD_DERIVED.get(mode, {})
    if col in _derived:
        _render_epd_derived_field(col, key, _derived[col], values, product_type,
                                  label_override=label_override)
        return
    # VOC Certification = n/r → certificate number / expiry are n/r and greyed.
    if col in VOC_CERT_NR_LOCK_FIELDS and voc_cert_is_not_relevant(voc_cert):
        st.session_state[key] = VOC_NOT_RELEVANT_VALUE
        label = label_override or _label_for(col)
        val = st.text_input(
            label,
            key=key,
            disabled=True,
            **widget_help_kwargs(col),
        )
        values[col] = VOC_NOT_RELEVANT_VALUE
        status = field_status(
            col, val, product_type, voc_cert=voc_cert, data_relevant=data_relevant,
        )
        st.markdown(
            f'{status_badge_html(status)} &nbsp; {revalu_caption_html(col)}',
            unsafe_allow_html=True,
        )
        return
    # Leaving a cert-n/r lock: date_input cannot keep a literal "n/r" in session.
    if col == "VO__Exp_Date" and key in st.session_state:
        _prev = str(st.session_state.get(key) or "").strip().lower().replace("\\", "/")
        if _prev in ("n/r", "nr") or _prev.startswith("n/r ") or _prev.startswith("nr "):
            del st.session_state[key]
    # Product-type auto-lock forces Data Relevant to No (read-only).
    if col == VOC_DATA_RELEVANT_FIELD and voc_not_relevant(product_type):
        st.session_state[key] = "No"
        disabled = True
        current = "No"
    else:
        disabled = field_disabled_for_product_type(
            col, product_type, voc_cert=voc_cert, data_relevant=data_relevant,
        )
    val = _widget_for_field(
        col, current, key, product_types, manufacturers, disabled=disabled,
        label_override=label_override, field_options=field_options,
    )
    values[col] = "No" if (col == VOC_DATA_RELEVANT_FIELD and voc_not_relevant(product_type)) else val
    status = field_status(
        col, values[col], values.get("D__ProductType_ENG", product_type_current),
        voc_cert=voc_cert, data_relevant=values.get(VOC_DATA_RELEVANT_FIELD, data_relevant),
    )
    st.markdown(
        f'{status_badge_html(status)} &nbsp; {revalu_caption_html(col)}',
        unsafe_allow_html=True,
    )


def _render_fields_row_major(
    fields: list[str],
    n_cols: int,
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
    product_types: list[str],
    manufacturers: list[str],
    field_options: dict[str, list[str]] | None = None,
) -> None:
    """Lay out fields left-to-right, wrapping every *n_cols* widgets onto a new row."""
    n_cols = max(1, int(n_cols))
    for start in range(0, len(fields), n_cols):
        chunk = fields[start : start + n_cols]
        cols = st.columns(n_cols, gap=_add_edit_col_gap())
        for j, field_col in enumerate(chunk):
            with cols[j]:
                _render_one_field(
                    field_col, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    field_options=field_options,
                )


# Physical-properties row: value | C/M pairs fill the tab width.
# PAIR_GAP_W is an empty column between consecutive (value, C/M) pairs.
_PHYS_CM_VALUE_W = 2.5
_PHYS_CM_CM_W = 1.5
_PHYS_CM_PAIR_GAP_W = 0.6
_PHYS_CM_ROW_SPACER = 0.0


def _render_physical_properties_cm_row(
    group_fields: list[str],
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
    product_types: list[str],
    manufacturers: list[str],
    field_labels: dict | None = None,
    field_options: dict[str, list[str]] | None = None,
    *,
    pad_slots: int | None = None,
) -> None:
    """One pair-column per field: value|C/M on top, status+Revalu on one line below.

    Pair columns keep short rows (e.g. U-value + λ) the same cell width as a
    fuller Physical-properties row above via ``pad_slots``.
    """
    field_labels = field_labels or {}
    n_slots = max(len(group_fields), int(pad_slots or len(group_fields)))
    outer_weights: list[float] = []
    pair_indices: list[int] = []
    for i in range(n_slots):
        pair_indices.append(len(outer_weights))
        outer_weights.append(_PHYS_CM_VALUE_W + _PHYS_CM_CM_W)
        if i < n_slots - 1 and _PHYS_CM_PAIR_GAP_W > 0:
            outer_weights.append(_PHYS_CM_PAIR_GAP_W)
    if _PHYS_CM_ROW_SPACER > 0:
        outer_weights.append(_PHYS_CM_ROW_SPACER)
    pairs = st.columns(outer_weights, gap="small")
    for i, field_col in enumerate(group_fields):
        with pairs[pair_indices[i]]:
            # EN / other non-physical hosts share the row but have no C/M pair.
            if field_col not in PHYSICAL_PROPERTY_FIELDS:
                _render_one_field(
                    field_col, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    label_override=field_labels.get(field_col),
                    field_options=field_options,
                )
                continue
            vcol, ccol = st.columns(
                [_PHYS_CM_VALUE_W, _PHYS_CM_CM_W],
                gap="small",
                vertical_alignment="bottom",
            )
            product_type = str(values.get("D__ProductType_ENG", product_type_current) or "")
            type_disabled = field_disabled_for_product_type(field_col, product_type)
            # C = calculated → value locked/greyed. Switching to M unlocks it.
            cm_flag = _ensure_physical_cm_session(
                field_col, mode, existing_row, values,
            )
            value_disabled = type_disabled or (cm_flag == "C")
            with vcol:
                current = (existing_row or {}).get(field_col)
                key = f"{mode}_{field_col}"
                val = _widget_for_field(
                    field_col, current, key, product_types, manufacturers,
                    disabled=value_disabled,
                    label_override=field_labels.get(field_col),
                    field_options=field_options,
                )
                values[field_col] = val
            with ccol:
                # Marker for C/M-column CSS (collapsed to zero height — see tokens).
                st.markdown(
                    '<div class="add-edit-cm-slot" aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                _render_physical_cm_select(
                    field_col, mode, existing_row, values, disabled=type_disabled,
                )
            status = field_status(
                field_col,
                values.get(field_col),
                values.get("D__ProductType_ENG", product_type_current),
            )
            st.markdown(
                f'<div class="add-edit-phys-meta">'
                f'{status_badge_html(status)}&nbsp;&nbsp;{revalu_caption_html(field_col)}'
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_field_group(
    group: dict,
    group_fields: list[str],
    mode: str,
    existing_row: dict | None,
    values: dict,
    product_type_current: str,
    product_types: list[str],
    manufacturers: list[str],
    field_options: dict[str, list[str]] | None = None,
) -> None:
    section_title = group.get("section_title")
    if section_title:
        _mt = group.get("section_margin_top")
        if group.get("section_divider"):
            render_add_edit_section_title_with_divider(str(section_title), margin_top=_mt)
        else:
            _style = str(group.get("section_title_style", "default")).strip().lower()
            if _mt is None:
                _fg = theme_section("developer_dashboard", "field_group_section") or {}
                _mt = _fg.get("margin_top", "0.65rem")
            _cls = "add-edit-field-group-title"
            if _style == "page_title":
                _cls += " add-edit-field-group-title--page"
            st.markdown(
                f'<div class="{_cls}" style="margin-top:{html.escape(str(_mt))};">'
                f"{html.escape(str(section_title))}</div>",
                unsafe_allow_html=True,
            )
    field_labels = group.get("field_labels") or {}

    # Physical properties: one pair-column per field (value|C/M + status line).
    if group.get("cm_under_fields"):
        _pad = group.get("cm_pad_slots")
        _render_physical_properties_cm_row(
            group_fields, mode, existing_row, values,
            product_type_current, product_types, manufacturers,
            field_labels=field_labels, field_options=field_options,
            pad_slots=int(_pad) if _pad is not None else None,
        )
        return

    # Fixed-width slots (e.g. GWP A1…D): same cell width regardless of field count.
    # ``pad_slots`` = reference grid (B-row = 7). ``slot_width_scale`` shrinks each
    # cell vs that reference (0.75 ⇒ GWP B1 − 25%). Trailing spacer fills the row.
    if group.get("pad_slots") is not None:
        n_slots = max(int(group["pad_slots"]), len(group_fields), 1)
        try:
            slot_scale = float(group.get("slot_width_scale") or 1.0)
        except (TypeError, ValueError):
            slot_scale = 1.0
        slot_scale = max(0.05, slot_scale)
        n_fields = len(group_fields)
        if abs(slot_scale - 1.0) < 1e-9:
            cols = st.columns(n_slots, gap=_add_edit_col_gap())
        else:
            weights: list[float] = [slot_scale] * n_fields
            rem = float(n_slots) - slot_scale * n_fields
            if rem > 1e-6:
                weights.append(rem)
            cols = st.columns(weights, gap=_add_edit_col_gap())
        for j, field_col in enumerate(group_fields):
            with cols[j]:
                _render_one_field(
                    field_col, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    label_override=field_labels.get(field_col),
                    field_options=field_options,
                )
        return

    weights = group.get("column_weights")
    if weights and len(weights) == len(group_fields):
        cols = st.columns([float(w) for w in weights], gap=_add_edit_col_gap())
        for j, field_col in enumerate(group_fields):
            with cols[j]:
                _render_one_field(
                    field_col, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    label_override=field_labels.get(field_col),
                    field_options=field_options,
                )
        return
    n_cols = int(group.get("columns_per_row", max(1, len(group_fields))))
    for start in range(0, len(group_fields), n_cols):
        chunk = group_fields[start : start + n_cols]
        cols = st.columns(n_cols, gap=_add_edit_col_gap())
        for j, field_col in enumerate(chunk):
            with cols[j]:
                _render_one_field(
                    field_col, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    label_override=field_labels.get(field_col),
                    field_options=field_options,
                )
    if group.get("derived_checklist"):
        _render_derived_checklist(mode, existing_row, values)
    if group.get("rating_alignment"):
        _render_rating_alignment(mode, existing_row, values)


_CHECKLIST_COLOURS = {"Yes": "#15803d", "No": "#b91c1c", "Unknown": "#a16207"}

# LEED / WELL / CAM alignment pills — same vocabulary as the Developer page.
_ALIGN_MARK = {"yes": "✓", "partial": "~", "no": "—", "unknown": "?", "na": "·"}
_ALIGN_STYLE = {
    "yes": "background:#dcfce7;color:#15803d;",
    "partial": "background:#fef3c7;color:#a16207;",
    "no": "background:#f1f5f9;color:#64748b;",
    "unknown": "background:#fee2e2;color:#b91c1c;",
    "na": "background:#f1f5f9;color:#94a3b8;",
}


def _render_rating_alignment(mode: str, existing_row: dict | None, values: dict) -> None:
    """How the chosen VOC claim reads against LEED v4.1, WELL v2 and CAM 2025.

    Read from aux_12__voc_rating_alignment.json through the catalog, so an alias
    answers like the canonical label. Nothing is stored: the claim decides.
    """
    cert = _effective_field_value(mode, "VO__VOC_Cert", existing_row, values)
    cert_str = "" if cert is None else str(cert).strip()
    if not cert_str or voc_cert_is_not_relevant(cert_str):
        return
    rows = voc_cert_alignment(cert_str)
    if not rows:
        return
    pills, notes = [], []
    for r in rows:
        style = _ALIGN_STYLE.get(r["status"], _ALIGN_STYLE["no"])
        pills.append(
            f'<span style="{style}font-size:0.7rem;font-weight:600;padding:1px 6px;'
            f'border-radius:3px;white-space:nowrap;" title="{html.escape(r["label"] + " — " + r["credit"])}">'
            f'{html.escape(r["short"])} {_ALIGN_MARK.get(r["status"], "—")}</span>'
        )
        if r["note"]:
            notes.append(
                f'<div><b>{html.escape(r["short"])}</b> · {html.escape(r["note"])}</div>'
            )
    unknown = all(r["status"] == "unknown" for r in rows)
    tail = (
        '<div style="color:#b91c1c;">Not in the VOC catalogue — no reading against the schemes.</div>'
        if unknown else "".join(notes)
    )
    st.markdown(
        '<div style="margin:2px 0 12px;">'
        '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">'
        '<span style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;'
        'letter-spacing:.05em;">Alignment</span>' + "".join(pills) + "</div>"
        '<div style="margin-top:4px;color:#64748b;font-size:0.75rem;line-height:1.45;">'
        + tail + "</div></div>",
        unsafe_allow_html=True,
    )


def _render_derived_checklist(mode: str, existing_row: dict | None, values: dict) -> None:
    """The three controls answered by fields the row already carries.

    They are read live from the form, so changing the body or the test date
    updates the answer on the next rerun — there is nothing to keep in step by
    hand, and nothing stored that could contradict the field it describes.
    """
    row = {
        col: _effective_field_value(mode, col, existing_row, values)
        for _label, col in VOC_CHECKLIST_DERIVED
    }
    items = []
    for label, answer, source in voc_checklist_derived(row):
        colour = _CHECKLIST_COLOURS.get(answer, "#64748b")
        items.append(
            f'<div style="display:flex;gap:6px;align-items:baseline;min-width:0;">'
            f'<b style="color:{colour};font-size:0.82rem;">{html.escape(answer)}</b>'
            f'<span style="font-size:0.82rem;">{html.escape(label)}</span>'
            f'<span style="font-size:0.72rem;color:#94a3b8;white-space:nowrap;">'
            f'← {html.escape(source)}</span></div>'
        )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));'
        'gap:4px 18px;margin:2px 0 10px;color:#475569;">' + "".join(items) + "</div>",
        unsafe_allow_html=True,
    )


# ── locked VOC tab ───────────────────────────────────────────────────────────
# For the product types in VOC_NOT_RELEVANT_PRODUCT_TYPES (cementitious, mineral
# and metallic goods) no product can carry an indoor-air emission certificate,
# so the whole category reads n/r rather than nine empty inputs. The widgets are
# replaced by a static read-out — nothing to type into, and nothing that could
# overwrite the n/r on save, since *values* is filled here instead.
_VOC_LOCKED_GREY = "#9ca3af"


def _voc_locked_field_html(col: str) -> str:
    """One greyed, non-editable VOC field showing its n/r value."""
    return (
        f'<div style="margin-bottom:0.55rem;">'
        f'<div style="font-size:0.8rem;color:{_VOC_LOCKED_GREY};margin-bottom:0.2rem;">'
        f"{html.escape(_label_for(col))}</div>"
        f'<div style="border:1px solid #e5e7eb;border-radius:0.5rem;background:#f8fafc;'
        f'color:{_VOC_LOCKED_GREY};padding:0.45rem 0.7rem;font-size:0.9rem;'
        f'user-select:none;">{html.escape(VOC_NOT_RELEVANT_VALUE)}</div>'
        f"</div>"
    )


def _render_voc_locked_tab(cat: dict, values: dict, product_type: str) -> None:
    """Render the Health tab's VOC fields as locked n/r and record those values.

    Only the VOC_FIELDS are locked; the caller renders the rest of the tab
    (VOC Data Relevant, health declarations, MSDS) as normal editable fields.
    """
    for col in VOC_FIELDS:
        values[col] = VOC_NOT_RELEVANT_VALUE
    if voc_not_relevant(product_type):
        values[VOC_DATA_RELEVANT_FIELD] = "No"
        banner = (
            f"🔒 <b>VOC not relevant</b> for product type "
            f"“{html.escape(str(product_type))}” — no product in this category can "
            f"carry an indoor-air emission certificate, so every VOC field is fixed at "
            f"<code>n/r</code> and locked. Change the <b>Product Type</b> on the "
            f"<b>Product ID</b> tab to edit these fields. Health declarations below "
            f"remain editable."
        )
    else:
        banner = (
            "🔒 <b>VOC Data Relevant</b> is <b>No</b> — inherently non-emitting / no "
            "VOC evidence required, so every VOC field is fixed at <code>n/r</code> "
            "and locked. Choose <b>Yes</b> or <b>Not sure</b> above to edit these "
            "fields. Health declarations below remain editable."
        )

    st.markdown(
        f'<div style="border:1px solid #e5e7eb;border-left:3px solid {_VOC_LOCKED_GREY};'
        f'border-radius:0.5rem;background:#f8fafc;padding:0.6rem 0.85rem;'
        f'margin-bottom:0.9rem;color:#475569;font-size:0.86rem;">'
        f"{banner}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Same column shape as the editable tab, so the layout does not jump when a
    # product type moves in or out of the locked set.
    groups = cat.get("field_groups") or [{"fields": list(cat["fields"]), "columns_per_row": 3}]
    for group in groups:
        group_fields = [f for f in group.get("fields", []) if f in VOC_FIELDS]
        if not group_fields:
            continue
        weights = group.get("column_weights")
        if weights and len(weights) == len(group_fields):
            cols = st.columns([float(w) for w in weights], gap=_add_edit_col_gap())
        else:
            cols = st.columns(
                max(1, int(group.get("columns_per_row", len(group_fields)))),
                gap=_add_edit_col_gap(),
            )
        for j, field_col in enumerate(group_fields):
            with cols[j % len(cols)]:
                st.markdown(_voc_locked_field_html(field_col), unsafe_allow_html=True)


def _resolve_field_value(mode: str, col: str, existing_row: dict | None):
    """Widget value from session state (previous run) or the loaded row."""
    _derived = _EPD_DERIVED.get(mode, {})
    if col in _derived:
        return _derived[col]
    key = f"{mode}_{col}"
    if key in st.session_state:
        return st.session_state[key]
    return (existing_row or {}).get(col)


def _effective_field_value(
    mode: str,
    col: str,
    existing_row: dict | None,
    values: dict | None = None,
):
    """Prefer values collected from widgets this run, else session state / row."""
    if values is not None and col in values:
        return values[col]
    return _resolve_field_value(mode, col, existing_row)


def _resolve_product_type(
    mode: str, existing_row: dict | None, values: dict | None = None
) -> str:
    val = _effective_field_value(mode, "D__ProductType_ENG", existing_row, values)
    return str(val or "").strip()


def _field_status_counts(
    fields: list[str],
    mode: str,
    existing_row: dict | None,
    product_type: str,
    values: dict | None = None,
) -> dict[str, int]:
    counts = {"filled": 0, "missing": 0, "not_relevant": 0}
    voc_cert = _voc_cert_value(mode, existing_row, values)
    data_relevant = _voc_data_relevant_value(mode, existing_row, values)
    for col in fields:
        status = field_status(
            col,
            _effective_field_value(mode, col, existing_row, values),
            product_type,
            voc_cert=voc_cert,
            data_relevant=data_relevant,
        )
        counts[status] = counts.get(status, 0) + 1
    return counts


def _relevant_total(counts: dict[str, int]) -> int:
    """Denominator for completion ratios — grey (not relevant) cells are excluded."""
    return int(counts.get("filled", 0)) + int(counts.get("missing", 0))


def _category_progress(
    cat: dict,
    mode: str,
    existing_row: dict | None,
    product_type: str,
    values: dict | None = None,
) -> tuple[int, int]:
    """Return ``(filled, relevant_total)`` for a category tab label."""
    counts = _field_status_counts(
        cat["fields"], mode, existing_row, product_type, values=values
    )
    return counts["filled"], _relevant_total(counts)


def _all_form_fields() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for cat in CATEGORIES:
        for col in cat["fields"]:
            if col not in seen:
                seen.add(col)
                ordered.append(col)
    return ordered


def _summary_legend_html() -> str:
    items = [
        ("filled", "Filled", status_rect_cell_style("filled")),
        ("missing", "Missing", status_rect_cell_style("missing")),
        ("not_relevant", "Not relevant", status_rect_cell_style("not_relevant")),
    ]
    swatches = "".join(
        f'<span class="add-edit-summary-legend-item">'
        f'<span class="add-edit-summary-legend-swatch" style="{style}"></span>'
        f"{html.escape(label)}</span>"
        for _key, label, style in items
    )
    return f'<div class="add-edit-summary-legend">{swatches}</div>'


def _summary_matrix_html(
    mode: str,
    existing_row: dict | None,
    product_type: str,
    values: dict | None = None,
) -> str:
    label_width = min(
        300,
        max(
            168,
            max((len(str(cat["label"])) for cat in CATEGORIES), default=20) * 6.5,
        ),
    )
    voc_cert = _voc_cert_value(mode, existing_row, values)
    data_relevant = _voc_data_relevant_value(mode, existing_row, values)
    rows: list[str] = []
    for cat in CATEGORIES:
        fields = list(cat["fields"])
        counts = _field_status_counts(fields, mode, existing_row, product_type, values=values)
        n_relevant = _relevant_total(counts)
        y_label = html.escape(str(cat["label"]))
        cells = "".join(
            f'<span class="add-edit-summary-cell" title="{html.escape(_label_for(col))}" '
            f'style="{status_rect_cell_style(field_status(col, _effective_field_value(mode, col, existing_row, values), product_type, voc_cert=voc_cert, data_relevant=data_relevant))}"></span>'
            for col in fields
        )
        # Locked VOC fields count as not relevant, so the Health row's ratio
        # only covers the health declarations / MSDS that still apply.
        y_count = (
            f'<span class="add-edit-summary-y-count">'
            f'({counts["filled"]}/{n_relevant})</span>'
        )
        rows.append(
            f'<div class="add-edit-summary-row">'
            f'<div class="add-edit-summary-y" style="width:{label_width:.0f}px;">'
            f"{y_label} {y_count}"
            f"</div>"
            f'<div class="add-edit-summary-cells">{cells}</div>'
            f"</div>"
        )
    return (
        f'<div class="add-edit-summary-matrix">'
        f"{_summary_legend_html()}"
        f"{''.join(rows)}"
        f"</div>"
    )


def _summary_field_row_html(col: str, status: str) -> str:
    label = html.escape(_label_for(col))
    badge = status_badge_html(status)
    caption = revalu_caption_html(col)
    return (
        f'<div class="add-edit-summary-field" style="display:flex;flex-wrap:wrap;'
        f'align-items:baseline;gap:0.35rem 0.75rem;margin:0.2rem 0;padding:0.15rem 0;">'
        f"{badge} "
        f'<span style="font-size:0.88rem;font-weight:500;">{label}</span> '
        f"{caption}</div>"
    )


def _render_summary_details(
    mode: str,
    existing_row: dict | None,
    product_type: str,
    values: dict | None = None,
) -> None:
    for cat in CATEGORIES:
        fields = list(cat["fields"])
        counts = _field_status_counts(fields, mode, existing_row, product_type, values=values)
        n = len(fields)
        n_relevant = _relevant_total(counts)
        filled = counts["filled"]
        if cat["key"] == "vo" and voc_emissions_locked(
            product_type,
            data_relevant=_voc_data_relevant_value(mode, existing_row, values),
        ):
            head_count = (
                f'<span style="font-weight:500;opacity:0.85;">'
                f'({filled}/{n_relevant})</span>'
            )
            head_style = "margin-top:1rem;"
            if voc_not_relevant(product_type):
                sub_line = (
                    f"VOC does not apply to this product type — {len(VOC_FIELDS)} VOC "
                    f"fields fixed at n/r · {counts['filled']} filled · "
                    f"{counts['missing']} missing"
                )
            else:
                sub_line = (
                    f"VOC Data Relevant = No — {len(VOC_FIELDS)} VOC "
                    f"fields fixed at n/r · {counts['filled']} filled · "
                    f"{counts['missing']} missing"
                )
        else:
            head_count = (
                f'<span style="font-weight:500;opacity:0.85;">'
                f'({filled}/{n_relevant})</span>'
            )
            head_style = "margin-top:1rem;"
            if counts["not_relevant"]:
                sub_line = (
                    f"{counts['filled']} filled · {counts['missing']} missing"
                    f" · {counts['not_relevant']} not relevant (excluded from count)"
                )
            else:
                sub_line = (
                    f"{counts['filled']} filled · {counts['missing']} missing"
                )
        st.markdown(
            f'<div class="add-edit-field-group-title add-edit-summary-cat-title" '
            f'style="{head_style}">'
            f"{html.escape(str(cat['label']))} {head_count}"
            f"</div>"
            f'<div style="font-size:0.78rem;color:#6b7280;margin-bottom:0.35rem;">'
            f"{sub_line}</div>",
            unsafe_allow_html=True,
        )
        voc_cert = _voc_cert_value(mode, existing_row, values)
        data_relevant = _voc_data_relevant_value(mode, existing_row, values)
        rows = "".join(
            _summary_field_row_html(
                col,
                field_status(
                    col,
                    _effective_field_value(mode, col, existing_row, values),
                    product_type,
                    voc_cert=voc_cert,
                    data_relevant=data_relevant,
                ),
            )
            for col in fields
        )
        st.markdown(
            f'<div class="add-edit-summary-fields">{rows}</div>',
            unsafe_allow_html=True,
        )


def _render_summary_tab(
    mode: str,
    existing_row: dict | None,
    values: dict | None = None,
) -> None:
    product_type = _resolve_product_type(mode, existing_row, values)
    if product_type:
        st.caption(
            f"Completion uses **Product Type** “{product_type}” for Missing vs. Not relevant "
            f"(same rules as the Catalogue extended view)."
        )
    else:
        st.caption(
            _tu("Set **Product Type** on the Product ID tab to refine Missing vs. Not relevant.")
        )

    all_fields = _all_form_fields()
    overall = _field_status_counts(
        all_fields, mode, existing_row, product_type, values=values
    )
    # Cluster the three counts on the left — equal full-width columns leave
    # them stranded far apart in the Developer content pane.
    m1, m2, m3, _ = st.columns([1, 1, 1.15, 4], gap="small")
    with m1:
        st.metric(_tu("Filled"), overall["filled"])
    with m2:
        st.metric(_tu("Missing"), overall["missing"])
    with m3:
        st.metric(_tu("Not relevant"), overall["not_relevant"])

    st.markdown(
        _summary_matrix_html(mode, existing_row, product_type, values=values),
        unsafe_allow_html=True,
    )
    st.caption(_tu("One rectangle per field in each tab. Hover a cell for the field name."))

    with st.expander(_tu("Field-by-field details"), expanded=False):
        _render_summary_details(mode, existing_row, product_type, values=values)


# ── EPD families: reference product → scaled variants ──────────────────────
# E__EPD_ConvFactor = Y marks the product whose figures the EPD prints; N marks
# the products covered by the same EPD (same E__EPD_RegNumber) whose figures are
# the reference's × E__EPD_MultFactor. Logic lives in libs/lib_epd_family.py.
#
#   • Editing a variant: its GWP fields are derived from the saved reference and
#     shown locked; the derived values are what gets saved.
#   • Saving a reference: every variant of the family is re-derived and written
#     to the edit log in the same save.
#
# mode → {column: derived value}, rebuilt by _render_form on every run before any
# field renders. Page scripts re-execute top to bottom, so this never leaks
# between runs or sessions.
_EPD_DERIVED: dict[str, dict] = {}


def _epd_fmt(v) -> str:
    if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def _render_epd_derived_field(
    col: str, key: str, value, values: dict, product_type: str,
    *, label_override: str | None = None,
) -> None:
    """Locked read-out of a GWP field derived from the EPD reference product."""
    shown = _epd_fmt(value)
    # The value is part of the key: a keyed widget ignores a changed ``value``,
    # and this one must follow the reference / factor / ρ·d·λ as they change.
    st.text_input(
        label_override or _label_for(col), value=shown,
        key=f"{key}__epdref_{abs(hash(shown)) % 10**8}", disabled=True,
        help=_tu("Derived from the EPD reference product × multiplication factor."),
    )
    values[col] = value
    st.markdown(
        f'{status_badge_html(field_status(col, value, product_type))} &nbsp; '
        f'{revalu_caption_html(col)}',
        unsafe_allow_html=True,
    )


def _epd_form_row(mode: str, existing_row: dict | None) -> dict:
    """The record as currently on the form: loaded row overlaid with widget state."""
    row = dict(existing_row or {})
    ss = st.session_state
    for col in _all_form_fields():
        if col in _EPD_DERIVED_COLS:
            continue
        key = f"{mode}_{col}"
        if key in ss:
            row[col] = ss[key]
    return row


def _epd_context(mode: str, raw_df: pd.DataFrame, existing_row: dict | None) -> dict:
    """Role of the record in its EPD family, and what follows from it.

    ``role`` is ``"variant"`` (derived values in ``_EPD_DERIVED[mode]``),
    ``"reference"`` (save plan in ``plan``) or ``None``; ``note`` explains why
    nothing is derived / propagated when the flags say something should be.
    """
    _EPD_DERIVED[mode] = {}
    row = _epd_form_row(mode, existing_row)
    reg = row.get(_EPD_REG_COL)
    has_reg = bool(_epd_reg_key(reg))
    self_id = (existing_row or {}).get("0__EETRA_ID")
    ctx: dict = {"role": None, "reg": reg}
    if _epd_is_reference(row):
        ctx["role"] = "reference"
        if not has_reg:
            ctx["note"] = ("Enter the **EPD Registration Number** to link the other "
                           "products covered by this EPD.")
            return ctx
        other, status = _epd_family_reference(raw_df, reg, exclude_id=self_id)
        if status != "none":
            ctx["note"] = (
                f"Another product with EPD `{reg}` is also flagged **Y**"
                + (f" (**{other.get('A__ProductName')}**)" if other else "")
                + " — the family has no single reference product, so nothing is "
                "propagated on save. Set the other product(s) to N."
            )
            return ctx
        ctx["family"] = _epd_family_variants(raw_df, reg, exclude_id=self_id)
        ctx["plan"] = _epd_propagation_plan(raw_df, {**row, "0__EETRA_ID": self_id})
        return ctx
    if not _epd_is_variant(row):
        return ctx
    ctx["role"] = "variant"
    factor = _epd_num(row.get(_EPD_FACTOR_COL))
    ref, status = _epd_family_reference(raw_df, reg, exclude_id=self_id) if has_reg else (None, "none")
    if not has_reg:
        ctx["note"] = "Enter the **EPD Registration Number** to find this EPD's reference product."
    elif status == "none":
        ctx["note"] = (
            f"No product with EPD `{reg}` is flagged **Y** (reference) yet — GWP data "
            "stay editable until the reference product is saved."
        )
    elif status == "ambiguous":
        ctx["note"] = (
            f"More than one product with EPD `{reg}` is flagged **Y** — fix the "
            "reference flag before GWP data can be derived."
        )
    elif factor is None:
        ctx["note"] = ("Enter the **EPD Multiplication Factor** (EPD - Gen. Data tab) to "
                       "derive the GWP data from the reference product.")
    if ctx.get("note"):
        return ctx
    ctx.update(reference=ref, factor=factor)
    _EPD_DERIVED[mode] = _epd_variant_values(ref, factor, row)
    return ctx


def _render_epd_family_banner(ctx: dict) -> None:
    """Top of the GWP Data tab: where this record's GWP data come from / go to."""
    role = ctx.get("role")
    if role is None:
        return
    if ctx.get("note"):
        st.warning(ctx["note"], icon="🔗")
        return
    if role == "variant":
        ref = ctx["reference"]
        st.info(
            f"**Derived from the EPD reference product "
            f"{ref.get('A__ProductName')}** (`{ref.get('0__EETRA_ID')}`, EPD "
            f"`{ref.get(_EPD_REG_COL)}`) × multiplication factor **{ctx['factor']:g}**. "
            "GWP modules are scaled, Metric and FU copied, and the per kg / m³ / m² / "
            "R=1 bases re-derived from this product's own ρ, d and λ. To change them, "
            "edit the reference product — or set *EPD Reference Product* to blank to "
            "enter them by hand.",
            icon="🔗",
        )
        return
    family, plan = ctx.get("family") or [], ctx.get("plan") or []
    if not family:
        st.info(
            f"**EPD reference product.** No other product with EPD `{ctx['reg']}` is "
            "flagged N yet — products saved later with N and a multiplication factor "
            "derive their GWP data from this one.",
            icon="🔗",
        )
        return
    if not plan:
        st.info(
            f"**EPD reference product** for {len(family)} other product(s) — their GWP "
            "data already equal these values × their multiplication factors.",
            icon="🔗",
        )
        return
    st.info(
        f"**EPD reference product.** On save, the GWP data of **{len(plan)}** of the "
        f"{len(family)} other product(s) covered by EPD `{ctx['reg']}` are recomputed "
        "as these values × their multiplication factor.",
        icon="🔗",
    )
    with st.expander(f"Preview — {len(plan)} product(s) updated on save", expanded=False):
        st.dataframe(
            pd.DataFrame([
                {
                    "Product": p["name"],
                    "ID": p["id"],
                    "Factor": p["factor"],
                    "GWP A1-A3 now": _epd_fmt(p["before"].get("G__GWP_A1A3", "(unchanged)")),
                    "GWP A1-A3 after save": _epd_fmt(p["values"].get("G__GWP_A1A3", "(unchanged)")),
                    "Fields changed": len(p["values"]),
                }
                for p in plan
            ]),
            hide_index=True,
            width="stretch",
        )


def _propagate_epd_reference(updated_df: pd.DataFrame, eetra_id: str) -> int:
    """After saving *eetra_id*: re-derive its EPD variants, log them in one write.

    Returns how many variants were updated (0 when the item is not a reference).
    """
    match = updated_df.loc[updated_df["0__EETRA_ID"].astype(str) == str(eetra_id)]
    if match.empty:
        return 0
    plan = _epd_propagation_plan(updated_df, match.iloc[0].to_dict())
    if not plan:
        return 0
    df = updated_df
    for p in plan:
        df = _upsert_row(df, p["id"], p["values"], is_new=False)
    by_id = df.set_index(df["0__EETRA_ID"].astype(str))
    _append_edits(
        [(by_id.loc[p["id"]].to_dict(), p["id"]) for p in plan],
        op="update",
        base_columns=list(updated_df.columns),
        path=_resolve_edits_path(),
    )
    return len(plan)


def _epd_propagation_note(n: int) -> str:
    return (
        f"🔗 GWP data of **{n}** product(s) covered by the same EPD were recomputed "
        "from this reference × their multiplication factors."
    )


# ── GWP conversion-factor panel (bottom of the GWP Data tab) ─────────────────
# The four normalised GWP columns (_kg / _m3 / _m2 / _m2R1) are stored values,
# not app-computed ones, so nothing in the form tells the person entering data
# whether they are mutually consistent. This panel re-derives each basis from
# the physical properties already on the form and shows the formula, the inputs
# it used and whether the entered value agrees — read-only, never written back.
_GWP_PANEL_INK      = "#334155"
_GWP_PANEL_MUTED    = "#64748b"
_GWP_PANEL_BORDER   = "#e5e7eb"
_GWP_PANEL_BG       = "#f8fafc"
_GWP_PANEL_OK       = "#15803d"
_GWP_PANEL_WARN     = "#b45309"
_GWP_PANEL_SUGGEST  = "#1d4ed8"

# Tolerance on |derived / entered − 1| before a value is flagged as disagreeing.
_GWP_PANEL_TOL = 0.02

# Physical inputs: symbol, label, primary column, fallback column, unit.
_GWP_PANEL_INPUTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ρ",   "Vol. Density",         "P__Mass_kgm3", "E__EPD_Density",  "kg/m³"),
    ("d",   "Thickness",            "P__Thick_mm",  "E__EPD_Thick_mm", "mm"),
    ("λ",   "Conductivity",         "P__L_WmK",     "E__L_WmK",        "W/(m·K)"),
    ("m_A", "Sup. Density",         "P__Mass_kgm2", "",                "kg/m²"),
    ("R",   "Thermal resistance",   "E__Rvalue",    "",                "m²K/W"),
)

# Declared unit (G__GWP_FU) → (anchored column, factor applied to G__GWP_A1A3).
_GWP_PANEL_ANCHORS: dict[str, tuple[str, float]] = {
    "m3":    ("G__GWP_A1A3_m3",   1.0),
    "m2":    ("G__GWP_A1A3_m2",   1.0),
    "kg":    ("G__GWP_A1A3_kg",   1.0),
    "ton":   ("G__GWP_A1A3_kg",   0.001),
    "tonne": ("G__GWP_A1A3_kg",   0.001),
    "t":     ("G__GWP_A1A3_kg",   0.001),
    "m2_r1": ("G__GWP_A1A3_m2R1", 1.0),
}


def _gwp_panel_num(mode: str, col: str, existing_row: dict | None, values: dict):
    """Current numeric value of one form field, or None when blank / n-a / n-r."""
    raw = _effective_field_value(mode, col, existing_row, values)
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".")
    if s == "" or s.lower() in ("nan", "none", "-", "n/a", "n/r", "na", "nr", "*"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _gwp_panel_fmt(v: float | None, dash: str = "—") -> str:
    """Compact number for the read-out: significant digits without noise."""
    if v is None:
        return dash
    a = abs(v)
    if a and (a < 1e-4 or a >= 1e7):
        return f"{v:.3e}"
    s = f"{v:,.6g}"
    return s


def _gwp_panel_chip(symbol: str, label: str, value: str, unit: str, source: str) -> str:
    """One read-only input-metric chip."""
    _src = (
        f'<div style="font-size:0.68rem;color:{_GWP_PANEL_MUTED};margin-top:0.15rem;">'
        f"{html.escape(source)}</div>"
        if source else ""
    )
    return (
        f'<div style="flex:1 1 9rem;min-width:8.5rem;border:1px solid {_GWP_PANEL_BORDER};'
        f'border-radius:0.5rem;background:{_GWP_PANEL_BG};padding:0.4rem 0.6rem;">'
        f'<div style="font-size:0.72rem;color:{_GWP_PANEL_MUTED};">'
        f"{html.escape(symbol)} · {html.escape(label)}</div>"
        f'<div style="font-size:0.95rem;color:{_GWP_PANEL_INK};font-weight:600;">'
        f"{html.escape(value)} "
        f'<span style="font-weight:400;font-size:0.75rem;color:{_GWP_PANEL_MUTED};">'
        f"{html.escape(unit)}</span></div>"
        f"{_src}</div>"
    )


def _gwp_panel_card(
    title: str, unit: str, entered: float | None, derived: float | None,
    formula: str, substitution: str, missing: list[str],
) -> str:
    """One derived-basis card: entered vs derived, with the formula behind it."""
    if derived is None:
        badge_txt, badge_col = "cannot derive", _GWP_PANEL_MUTED
    elif entered is None:
        badge_txt, badge_col = "not entered — suggested", _GWP_PANEL_SUGGEST
    elif entered == 0 or abs(derived / entered - 1.0) <= _GWP_PANEL_TOL:
        badge_txt, badge_col = "matches entered value", _GWP_PANEL_OK
    else:
        _delta = (derived / entered - 1.0) * 100.0
        badge_txt, badge_col = f"differs from entered by {_delta:+.1f}%", _GWP_PANEL_WARN

    if derived is None:
        detail = (
            f'<div style="font-size:0.75rem;color:{_GWP_PANEL_MUTED};">'
            f"missing input: {html.escape(', '.join(missing) or 'declared A1–A3 value')}</div>"
        )
    else:
        detail = (
            f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
            f'font-size:0.74rem;color:{_GWP_PANEL_MUTED};margin-top:0.1rem;">'
            f"{html.escape(substitution)}</div>"
        )

    return (
        f'<div style="flex:1 1 15rem;min-width:14rem;border:1px solid {_GWP_PANEL_BORDER};'
        f'border-radius:0.5rem;background:{_GWP_PANEL_BG};padding:0.55rem 0.7rem;">'
        f'<div style="font-size:0.78rem;color:{_GWP_PANEL_MUTED};">{html.escape(title)}</div>'
        f'<div style="font-size:1.15rem;font-weight:700;color:{_GWP_PANEL_INK};'
        f'line-height:1.3;">{html.escape(_gwp_panel_fmt(derived))} '
        f'<span style="font-size:0.72rem;font-weight:400;color:{_GWP_PANEL_MUTED};">'
        f"{html.escape(unit)}</span></div>"
        f'<div style="font-size:0.72rem;color:{badge_col};font-weight:600;'
        f'margin-bottom:0.3rem;">{html.escape(badge_txt)}'
        f'<span style="font-weight:400;color:{_GWP_PANEL_MUTED};"> · entered: '
        f"{html.escape(_gwp_panel_fmt(entered, 'blank'))}</span></div>"
        f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
        f'font-size:0.76rem;color:{_GWP_PANEL_INK};">{html.escape(formula)}</div>'
        f"{detail}</div>"
    )


def _render_gwp_conversion_panel(
    mode: str, existing_row: dict | None, values: dict
) -> None:
    """Read-only derivation of the four GWP bases, below the GWP Data fields.

    Pivots everything through GWP per m³: the declared unit (``G__GWP_FU``)
    anchors one basis 1:1, that basis converts to per m³ with ρ, d or λ, and
    the remaining three follow. Nothing here is saved — it exists so a wrong
    density, thickness or conductivity shows up at data-entry time instead of
    in a chart.
    """
    fn303_custom_hr()
    _fg = theme_section("developer_dashboard", "field_group_section") or {}
    st.markdown(
        '<div class="add-edit-field-group-title add-edit-field-group-title--page" '
        f'style="margin-top:{html.escape(str(_fg.get("margin_top_panel", "22px")))};">'
        "GWP A1–A3 conversion factors</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        _tu("Derived live from the fields above — read-only, never saved. The stored "
        "`_kg` / `_m3` / `_m2` / `_m2R1` columns come from the source workbook; this "
        "panel re-computes them so an inconsistent density, thickness or λ is visible here.")
    )

    # ── Input metrics ───────────────────────────────────────────────────────
    _vals: dict[str, float | None] = {}
    _srcs: dict[str, str] = {}
    _chips: list[str] = []
    for sym, label, primary, fallback, unit in _GWP_PANEL_INPUTS:
        v = _gwp_panel_num(mode, primary, existing_row, values)
        src = primary if v is not None else ""
        if v is None and fallback:
            v = _gwp_panel_num(mode, fallback, existing_row, values)
            src = fallback if v is not None else ""
        _vals[sym], _srcs[sym] = v, src
        _chips.append(
            _gwp_panel_chip(sym, label, _gwp_panel_fmt(v), unit, src or "not entered")
        )

    rho, d_mm, lam = _vals["ρ"], _vals["d"], _vals["λ"]
    d = None if d_mm is None else d_mm / 1000.0
    m_a = _vals["m_A"]
    if m_a is None and rho is not None and d is not None:
        m_a, _srcs["m_A"] = rho * d, "derived: ρ · d"
        _chips[3] = _gwp_panel_chip("m_A", "Sup. Density", _gwp_panel_fmt(m_a),
                                    "kg/m²", "derived: ρ · d")
    r_val = _vals["R"]
    if r_val is None and d is not None and lam:
        r_val, _srcs["R"] = d / lam, "derived: d / λ"
        _chips[4] = _gwp_panel_chip("R", "Thermal resistance", _gwp_panel_fmt(r_val),
                                    "m²K/W", "derived: d / λ")

    st.markdown(
        '<div style="font-size:0.78rem;font-weight:600;color:' + _GWP_PANEL_INK +
        ';margin:0.2rem 0 0.35rem 0;">Input metrics used</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.7rem;">'
        + "".join(_chips) + "</div>",
        unsafe_allow_html=True,
    )

    # ── Declared value and its anchor ───────────────────────────────────────
    decl = _gwp_panel_num(mode, "G__GWP_A1A3", existing_row, values)
    fu_raw = _effective_field_value(mode, "G__GWP_FU", existing_row, values)
    fu = str(fu_raw or "").strip().lower().replace("³", "3").replace("²", "2")
    fu = fu.replace("m^3", "m3").replace("m^2", "m2").replace(" ", "")
    anchor_col, anchor_factor = _GWP_PANEL_ANCHORS.get(fu, ("", 0.0))
    anchor_val = None if (decl is None or not anchor_col) else decl * anchor_factor

    if not anchor_col:
        _anchor_msg = (
            f"Declared unit `{fu_raw or '—'}` does not map to a normalised basis "
            "(linear and piece declarations need a cross-section or a pieces-per-m² figure), "
            "so nothing below can be derived from it."
        )
    else:
        _fac = "unchanged" if anchor_factor == 1.0 else f"× {anchor_factor:g}"
        _anchor_msg = (
            f"Declared unit `{fu_raw}` → **{_label_for(anchor_col)}** anchored {_fac}: "
            f"**{_gwp_panel_fmt(anchor_val)}**. Every other basis below is derived from it."
        )
    st.markdown(
        f"**Step 1 — anchor on the declared unit.** {_anchor_msg}"
    )

    # ── Pivot to per m³, then fan out ───────────────────────────────────────
    g3 = None
    pivot_note = ""
    if anchor_val is not None:
        if anchor_col == "G__GWP_A1A3_m3":
            g3, pivot_note = anchor_val, "declared per m³ — already the pivot"
        elif anchor_col == "G__GWP_A1A3_kg" and rho is not None:
            g3, pivot_note = anchor_val * rho, f"per m³ = per kg × ρ = {_gwp_panel_fmt(anchor_val)} × {_gwp_panel_fmt(rho)}"
        elif anchor_col == "G__GWP_A1A3_m2" and d:
            g3, pivot_note = anchor_val / d, f"per m³ = per m² ÷ d = {_gwp_panel_fmt(anchor_val)} ÷ {_gwp_panel_fmt(d)}"
        elif anchor_col == "G__GWP_A1A3_m2R1" and lam:
            g3, pivot_note = anchor_val / lam, f"per m³ = per m²(R=1) ÷ λ = {_gwp_panel_fmt(anchor_val)} ÷ {_gwp_panel_fmt(lam)}"

    if anchor_col and g3 is None and anchor_val is not None:
        _need = {"G__GWP_A1A3_kg": "ρ", "G__GWP_A1A3_m2": "d", "G__GWP_A1A3_m2R1": "λ"}
        st.markdown(
            f"**Step 2 — pivot to per m³.** Not possible: "
            f"`{_need.get(anchor_col, '—')}` is missing."
        )
    elif g3 is not None:
        st.markdown(f"**Step 2 — pivot to per m³.** {pivot_note} = **{_gwp_panel_fmt(g3)}**")

    # Each basis has a primary route through the per-m³ pivot and a documented
    # fallback for when the pivot input is missing but an equivalent one is on
    # the form. The route that actually produced the number is the one shown.
    _F_KG   = "GWP/kg = GWP/m³ ÷ ρ"
    _F_M2   = "GWP/m² = GWP/m³ × d   (d in m = mm ÷ 1000)"
    _F_M2R1 = "GWP/m²(R=1) = GWP/m³ × λ   (since R = d/λ ⇒ d at R=1 is λ)"

    if g3 is not None and rho:
        g_kg = g3 / rho
        f_kg = (_F_KG, f"= {_gwp_panel_fmt(g3)} ÷ {_gwp_panel_fmt(rho)}")
    elif anchor_col == "G__GWP_A1A3_kg" and anchor_val is not None:
        g_kg = anchor_val
        f_kg = ("GWP/kg = declared value", "anchored directly on the declared unit")
    else:
        g_kg, f_kg = None, (_F_KG, "")

    if g3 is not None and d is not None:
        g_m2 = g3 * d
        f_m2 = (_F_M2, f"= {_gwp_panel_fmt(g3)} × {_gwp_panel_fmt(d)}")
    elif g_kg is not None and m_a is not None:
        g_m2 = g_kg * m_a
        f_m2 = ("GWP/m² = GWP/kg × m_A",
                f"= {_gwp_panel_fmt(g_kg)} × {_gwp_panel_fmt(m_a)}")
    else:
        g_m2, f_m2 = None, (_F_M2, "")

    if g3 is not None and lam is not None:
        g_m2r1 = g3 * lam
        f_m2r1 = (_F_M2R1, f"= {_gwp_panel_fmt(g3)} × {_gwp_panel_fmt(lam)}")
    elif g_m2 is not None and r_val:
        g_m2r1 = g_m2 / r_val
        f_m2r1 = ("GWP/m²(R=1) = GWP/m² ÷ R",
                  f"= {_gwp_panel_fmt(g_m2)} ÷ {_gwp_panel_fmt(r_val)}")
    else:
        g_m2r1, f_m2r1 = None, (_F_M2R1, "")

    cards = [
        _gwp_panel_card(
            f"{_label_for('G__GWP_A1A3_kg')} — per kg", "kgCO₂e/kg",
            _gwp_panel_num(mode, "G__GWP_A1A3_kg", existing_row, values), g_kg,
            f_kg[0], f_kg[1],
            [s for s, v in (("GWP/m³", g3), ("ρ (density)", rho)) if not v],
        ),
        _gwp_panel_card(
            f"{_label_for('G__GWP_A1A3_m3')} — per m³", "kgCO₂e/m³",
            _gwp_panel_num(mode, "G__GWP_A1A3_m3", existing_row, values), g3,
            "GWP/m³ = pivot basis",
            pivot_note or "—",
            ["declared A1–A3 or its unit"],
        ),
        _gwp_panel_card(
            f"{_label_for('G__GWP_A1A3_m2')} — per m²", "kgCO₂e/m²",
            _gwp_panel_num(mode, "G__GWP_A1A3_m2", existing_row, values), g_m2,
            f_m2[0], f_m2[1],
            [s for s, v in (("GWP/m³", g3), ("d (thickness)", d)) if not v],
        ),
        _gwp_panel_card(
            f"{_label_for('G__GWP_A1A3_m2R1')} — per m² at R=1", "kgCO₂e/m²·(m²K/W)",
            _gwp_panel_num(mode, "G__GWP_A1A3_m2R1", existing_row, values), g_m2r1,
            f_m2r1[0], f_m2r1[1],
            [s for s, v in (("GWP/m³", g3), ("λ (conductivity)", lam)) if not v],
        ),
    ]
    st.markdown(
        '<div style="font-size:0.78rem;font-weight:600;color:' + _GWP_PANEL_INK +
        ';margin:0.55rem 0 0.35rem 0;">Step 3 — the four bases</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;">'
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )

    with st.expander(_tu("Formulae, input metrics and caveats"), expanded=False):
        st.markdown(
            "**Conversion matrix** — multiply the row basis by the cell to reach the column basis:\n\n"
            "| from ↓ / to → | per kg | per m³ | per m² | per m² R=1 |\n"
            "|---|---|---|---|---|\n"
            "| **per kg** | 1 | × ρ | × ρ·d | × ρ·λ |\n"
            "| **per m³** | ÷ ρ | 1 | × d | × λ |\n"
            "| **per m²** | ÷ (ρ·d) | ÷ d | 1 | × λ/d  (= ÷ R) |\n"
            "| **per m² R=1** | ÷ (ρ·λ) | ÷ λ | × d/λ  (= × R) | 1 |\n\n"
            "**Input metrics**\n\n"
            "| Symbol | Meaning | Field used | Fallback | Unit |\n"
            "|---|---|---|---|---|\n"
            "| ρ | Vol. Density | `P__Mass_kgm3` | `E__EPD_Density` | kg/m³ |\n"
            "| d | Thickness | `P__Thick_mm` | `E__EPD_Thick_mm` | mm → m (÷ 1000) |\n"
            "| λ | Thermal conductivity | `P__L_WmK` | `E__L_WmK` | W/(m·K) |\n"
            "| m_A | Sup. Density | `P__Mass_kgm2` | derived ρ · d | kg/m² |\n"
            "| R | Thermal resistance | `E__Rvalue` | derived d / λ | m²K/W |\n\n"
            "**Declared-unit anchors** — `m3`, `m2`, `kg` and `m2_R1` map 1:1 onto their basis; "
            "`ton` is the only unit factor (÷ 1000 → per kg); `m` and `unit` cannot be normalised.\n\n"
            "**Why R = 1** — comparing insulants per m² compares material, not performance. "
            "With R = d/λ, the thickness giving R = 1 m²K/W is numerically λ metres, so "
            "GWP/m²(R=1) = GWP/m³ × λ. A lower λ is rewarded automatically.\n\n"
            "**Caveats** — per m² is tied to the declared thickness and is not comparable across "
            "thicknesses; per m²(R=1) is only meaningful for insulants; per kg ignores geometry "
            "and performance. All figures are A1–A3 only. A mismatch flagged above usually means "
            "a wrong ρ, d or λ, not a wrong GWP.\n\n"
            f"Values are flagged as disagreeing beyond ±{_GWP_PANEL_TOL:.0%}. "
            "Full reference: **Developer → App Documentation → GWP conversion factors**."
        )


def _sync_thickness_density(mode: str) -> None:
    """Keep the calculated one of d / ρ / m_A in step when the other two are M.

    m_A [kg/m²] = ρ [kg/m³] · d [mm] / 1000.

    * Target flagged **M** — never touch (user override; value cell is unlocked).
    * Target flagged **C** (or empty with no value yet) — write the derived
      figure and set C so the value cell stays locked/greyed.
    * Target has a value but CM is blank — leave alone (mid-entry before the
      user picks M).
    """
    ss = st.session_state
    d_key, r_key, m_key = (f"{mode}_{c}" for c in ("P__Thick_mm", "P__Mass_kgm3", "P__Mass_kgm2"))

    def _num(key: str) -> float | None:
        try:
            f = float(str(ss.get(key, "") or "").strip().replace(",", "."))
        except (TypeError, ValueError):
            return None
        return f if pd.notna(f) else None

    def _is_manual(key: str) -> bool:
        cm = ss.get(f"{mode}_{physical_cm_column(key[len(mode) + 1:])}")
        return cm == "M" and _num(key) is not None

    def _cm_key(host_key: str) -> str:
        return f"{mode}_{physical_cm_column(host_key[len(mode) + 1:])}"

    manual = [k for k in (d_key, r_key, m_key) if _is_manual(k)]
    if len(manual) != 2:
        return
    d, rho, m_a = _num(d_key), _num(r_key), _num(m_key)
    if m_key not in manual:
        if d is None or rho is None:
            return
        target, result = m_key, rho * d / 1000.0
    elif r_key not in manual:
        if not d or m_a is None:
            return
        target, result = r_key, m_a * 1000.0 / d
    else:
        if not rho or m_a is None:
            return
        target, result = d_key, m_a * 1000.0 / rho

    cm = str(ss.get(_cm_key(target), "") or "").strip().upper()
    if cm == "M":
        return
    # Blank CM with an existing number: user may be about to flip to M — don't stomp.
    if cm != "C" and _num(target) is not None:
        return

    ss[target] = f"{result:.6f}".rstrip("0").rstrip(".")
    ss[_cm_key(target)] = "C"


def _render_form(mode: str, raw_df: pd.DataFrame, existing_row: dict | None) -> dict | None:
    """Render the category grid; returns collected field values only on Save."""
    _sync_thickness_density(mode)
    st.markdown(
        f"<style>{add_edit_form_css()}</style><div class='add-edit-form-root'></div>",
        unsafe_allow_html=True,
    )
    product_type_current = str((existing_row or {}).get("D__ProductType_ENG", "") or "")
    # raw_df always comes from _load_raw(), i.e. the current file version — read
    # the option lists from the per-version cache instead of rescanning it.
    product_types, manufacturers, _ = _cached_form_options(*_effective_mtimes())
    field_options = _field_option_lists()

    values: dict = {}
    # Before anything reads a field value: fills _EPD_DERIVED[mode] for a variant.
    _epd_ctx = _epd_context(mode, raw_df, existing_row)
    product_type_for_labels = _resolve_product_type(mode, existing_row)
    data_relevant_for_labels = _voc_data_relevant_value(mode, existing_row)

    all_fields = _all_form_fields()
    summary_counts = _field_status_counts(
        all_fields, mode, existing_row, product_type_for_labels
    )
    summary_filled = summary_counts["filled"]
    summary_relevant = _relevant_total(summary_counts)
    _voc_locked = voc_emissions_locked(
        product_type_for_labels, data_relevant=data_relevant_for_labels
    )

    def _cat_label(cat: dict) -> str:
        # Locked VOC fields are not relevant, so Health counts only what applies.
        filled, relevant = _category_progress(
            cat, mode, existing_row, product_type_for_labels
        )
        return f"{cat['label']} ({filled}/{relevant})"

    cat_labels = [
        f"Summary ({summary_filled}/{summary_relevant})",
        *[_cat_label(cat) for cat in CATEGORIES],
    ]
    cat_tabs = st.tabs(cat_labels)
    for cat, tab in zip(CATEGORIES, cat_tabs[1:]):
        with tab:
            fields = list(cat["fields"])
            if cat["key"] == "vo" and _voc_locked:
                # Keep VOC Data Relevant editable above the locked n/r block.
                field_groups_pre = cat.get("field_groups") or []
                for group in field_groups_pre:
                    group_fields = [
                        f for f in group.get("fields", [])
                        if f in fields and f not in VOC_FIELDS and f.startswith("VO__")
                    ]
                    if group_fields:
                        _render_field_group(
                            group, group_fields, mode, existing_row, values,
                            product_type_current, product_types, manufacturers,
                            field_options=field_options,
                        )
                        for f in group_fields:
                            if f in fields:
                                fields = [x for x in fields if x != f]
                _render_voc_locked_tab(cat, values, product_type_for_labels)
                fields = [f for f in fields if f not in VOC_FIELDS]
            field_groups = cat.get("field_groups")
            if cat["key"] == "gwp":
                _render_epd_family_banner(_epd_ctx)
            if field_groups:
                for group in field_groups:
                    group_fields = [f for f in group.get("fields", []) if f in fields]
                    if group_fields:
                        _render_field_group(
                            group, group_fields, mode, existing_row, values,
                            product_type_current, product_types, manufacturers,
                            field_options=field_options,
                        )
                if cat["key"] == "gwp":
                    _render_gwp_conversion_panel(mode, existing_row, values)
                continue

            n_cols = int(cat.get("columns_per_row", 3))
            first_row = list(cat.get("first_row_fields") or [])
            bottom = list(cat.get("bottom_fields") or [])
            bottom_n_cols = int(cat.get("bottom_columns_per_row", 1))
            bottom_set = set(bottom)

            if first_row:
                head = [f for f in first_row if f in fields]
                tail = [f for f in fields if f not in head and f not in bottom_set]
                bottom_fields = [f for f in bottom if f in fields]
                if head:
                    weights = cat.get("first_row_column_weights")
                    if weights and len(weights) == len(head):
                        top_cols = st.columns([float(w) for w in weights], gap=_add_edit_col_gap())
                    else:
                        top_cols = st.columns(len(head), gap=_add_edit_col_gap())
                    for j, field_col in enumerate(head):
                        with top_cols[j]:
                            _render_one_field(
                                field_col, mode, existing_row, values,
                                product_type_current, product_types, manufacturers,
                                field_options=field_options,
                            )
                if tail:
                    _render_fields_row_major(
                        tail, n_cols, mode, existing_row, values,
                        product_type_current, product_types, manufacturers,
                        field_options=field_options,
                    )
                if bottom_fields:
                    _render_fields_row_major(
                        bottom_fields, bottom_n_cols, mode, existing_row, values,
                        product_type_current, product_types, manufacturers,
                        field_options=field_options,
                    )
            elif bottom:
                main = [f for f in fields if f not in bottom_set]
                bottom_fields = [f for f in bottom if f in fields]
                if main:
                    _render_fields_row_major(
                        main, n_cols, mode, existing_row, values,
                        product_type_current, product_types, manufacturers,
                        field_options=field_options,
                    )
                if bottom_fields:
                    _render_fields_row_major(
                        bottom_fields, bottom_n_cols, mode, existing_row, values,
                        product_type_current, product_types, manufacturers,
                        field_options=field_options,
                    )
            else:
                _render_fields_row_major(
                    fields, n_cols, mode, existing_row, values,
                    product_type_current, product_types, manufacturers,
                    field_options=field_options,
                )
    with cat_tabs[0]:
        _render_summary_tab(mode, existing_row, values=values)
    return values


_DEFAULT_OPTION_COLS = [
    "A__Manufacturer",
    "D__ProductType_ENG",
    "D__MaterialType_ENG",
    "E__ManuCountry",
    "E__EPD_Programme",
    "VO__VOC_Cert",
]

def _option_value_counts(series, col_name: str) -> list[tuple[str, int]]:
    """Return sorted (value, usage_count) pairs for one Available Options column."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for value in series.dropna():
        for token in _option_tokens_from_cell(value, col_name):
            counts[token] += 1
    return sorted(counts.items(), key=lambda item: item[0].lower())


def _option_values_list_html(value_counts: list[tuple[str, int]]) -> str:
    """Scrollable bullet list for one Available Options column."""
    if not value_counts:
        return '<p style="color:#9ca3af;font-size:0.85rem;margin:0;">No values</p>'
    items = "".join(
        f'<li style="margin:0.15rem 0;">{html.escape(str(value))}'
        f' <span style="color:#9ca3af;font-size:0.82rem;">[{count}]</span></li>'
        for value, count in value_counts
    )
    return (
        '<div style="max-height:520px;overflow-y:auto;font-size:0.85rem;line-height:1.35;">'
        f"<ul style='margin:0.35rem 0 0 1.1rem;padding:0;'>{items}</ul></div>"
    )


def _render_available_options(raw_df: pd.DataFrame) -> None:
    """Browse distinct values in categorical columns (dropdown source data)."""
    st.caption(
        _tu("Inspect unique values already in the **dataset** — the same lists used "
        "for Manufacturer and Product Type dropdowns when adding or editing items. "
        "VOC Certification also includes the curated catalog from "
        "`aux_11__voc_certifications.json`.")
    )

    # Curated VOC catalog with clarifications (always visible above the browser).
    _voc_tiers = voc_cert_tiers()
    if _voc_tiers:
        with st.expander(_tu("VOC certifications / claims — catalog & clarifications"), expanded=False):
            _caveat = voc_cert_caveat()
            if _caveat:
                st.caption(_caveat)
            _usage: dict[str, int] = {}
            if "VO__VOC_Cert" in raw_df.columns:
                for value, count in _option_value_counts(raw_df["VO__VOC_Cert"], "VO__VOC_Cert"):
                    _usage[str(value).strip().lower()] = int(count)
            for tier in _voc_tiers:
                st.markdown(f"**{html.escape(str(tier.get('label') or ''))}**")
                for entry in tier.get("entries") or []:
                    if not isinstance(entry, dict):
                        continue
                    label = str(entry.get("label") or "").strip()
                    if not label:
                        continue
                    desc = str(entry.get("description") or "").strip()
                    hint = str(entry.get("cert_number_hint") or "").strip()
                    n = _usage.get(label.lower(), 0)
                    # Also count alias hits in the dataset.
                    for alias in entry.get("aliases") or []:
                        n += _usage.get(str(alias).strip().lower(), 0)
                    count_bit = (
                        f' <span style="color:#9ca3af;font-size:0.82rem;">'
                        f"[{n} in dataset]</span>"
                        if n
                        else ""
                    )
                    st.markdown(
                        f"<div style='margin:0.35rem 0 0.85rem 0;font-size:0.9rem;line-height:1.4;'>"
                        f"<div style='font-weight:600;'>{html.escape(label)}{count_bit}</div>"
                        f"<div style='color:#374151;'>{html.escape(desc)}</div>"
                        + (
                            f"<div style='color:#6b7280;font-size:0.82rem;margin-top:0.2rem;'>"
                            f"{html.escape(hint)}</div>"
                            if hint
                            else ""
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )

    _eligible = [
        c for c in raw_df.columns
        if not str(c).strip().startswith("*") and c not in HIDDEN_APP_COLUMNS
    ]
    _defaults = [c for c in _DEFAULT_OPTION_COLS if c in _eligible]
    if not _defaults and _eligible:
        _defaults = _eligible[:6]

    _picked = st.multiselect(
        _tu("Columns to inspect"),
        options=_eligible,
        default=_defaults,
        format_func=_label_for,
        key="add_edit_option_cols",
    )
    if not _picked:
        st.info(_tu("Select one or more columns to list their available values."))
        return

    _search = st.text_input(
        _tu("Filter values"),
        key="add_edit_option_search",
        placeholder=_tu("Optional text filter…"),
    ).strip().lower()

    _cols = st.columns(len(_picked), gap="medium")
    _any_values = False
    for col_name, col_slot in zip(_picked, _cols):
        value_counts = _option_value_counts(raw_df[col_name], col_name)
        # For VOC cert, also surface catalog labels that are not yet in the dataset.
        if col_name == "VO__VOC_Cert":
            present = {str(v).strip().lower() for v, _ in value_counts}
            for label in voc_cert_labels():
                if label.lower() not in present:
                    value_counts.append((label, 0))
            value_counts = sorted(value_counts, key=lambda item: item[0].lower())
        if _search:
            value_counts = [
                (value, count) for value, count in value_counts
                if _search in str(value).lower()
            ]
        if value_counts:
            _any_values = True
        with col_slot:
            st.markdown(
                f"**{_label_for(col_name)}**  \n"
                f'<span style="color:#6b7280;font-size:0.78rem;">{len(value_counts)} values</span>',
                unsafe_allow_html=True,
            )
            if col_name == "VO__VOC_Cert":
                # Show clarification under each listed value when known.
                lines = []
                for value, count in value_counts:
                    note = voc_cert_clarification(value)
                    tip = (
                        f'<div style="color:#6b7280;font-size:0.78rem;margin:0.1rem 0 0.45rem 0;">'
                        f"{html.escape(note)}</div>"
                        if note
                        else ""
                    )
                    lines.append(
                        f'<li style="margin:0.15rem 0;">{html.escape(str(value))}'
                        f' <span style="color:#9ca3af;font-size:0.82rem;">[{count}]</span>'
                        f"{tip}</li>"
                    )
                html_list = (
                    '<div style="max-height:520px;overflow-y:auto;font-size:0.85rem;line-height:1.35;">'
                    f"<ul style='margin:0.35rem 0 0 1.1rem;padding:0;'>{''.join(lines)}</ul></div>"
                    if lines
                    else '<p style="color:#9ca3af;font-size:0.85rem;margin:0;">No values</p>'
                )
                st.markdown(html_list, unsafe_allow_html=True)
            else:
                st.markdown(_option_values_list_html(value_counts), unsafe_allow_html=True)

    if not _any_values:
        st.warning(_tu("No values match the current filter."))


def _render_add_section() -> None:
    _raw_df, _path = _load_raw()
    _epd_note = st.session_state.pop("_epd_propagated_note_add", None)
    if _epd_note:
        st.success(_epd_note)
    _values = _render_form("add", _raw_df, existing_row=None)
    if _values is not None:
        _ptype_vals = str(_values.get("D__ProductType_ENG", "") or "")
        if voc_not_relevant(_ptype_vals):
            _values[VOC_DATA_RELEVANT_FIELD] = "No"
            for _col in VOC_FIELDS:
                _values[_col] = VOC_NOT_RELEVANT_VALUE
        elif voc_data_is_not_relevant(_values.get(VOC_DATA_RELEVANT_FIELD)):
            for _col in VOC_FIELDS:
                _values[_col] = VOC_NOT_RELEVANT_VALUE
        elif voc_cert_is_not_relevant(_values.get("VO__VOC_Cert")):
            for _col in VOC_CERT_NR_LOCK_FIELDS:
                _values[_col] = VOC_NOT_RELEVANT_VALUE

    if st.button(_tu("💾 Save new item"), key="add_save", type="primary"):
        _manu = str(_values.get("A__Manufacturer", "")).strip()
        _name = str(_values.get("A__ProductName", "")).strip()
        _ptype = str(_values.get("D__ProductType_ENG", "")).strip()
        _missing = [lbl for lbl, v in
                    [("Manufacturer", _manu), ("Product Name", _name), ("Product Type", _ptype)] if not v]
        if _missing:
            st.error(f"Please fill in required fields: {', '.join(_missing)}.")
        else:
            _new_id = _next_eetra_id(_raw_df, _ptype)
            _updated = _upsert_row(_raw_df, _new_id, _values, is_new=True)
            _persist(_updated, _new_id, op="insert")
            _n_family = _propagate_epd_reference(_updated, _new_id)
            if _n_family:
                st.session_state["_epd_propagated_note_add"] = _epd_propagation_note(_n_family)
            st.success(f"✅ Saved new item **{_manu} — {_name}** as `{_new_id}`.")
            st.rerun()


def _delete_armed_key(eetra_id: str) -> str:
    return f"edit_delete_armed_{eetra_id}"


def _render_delete_button(eetra_id: str) -> None:
    """🗑️ Delete item — arms the confirmation panel, never deletes on its own."""
    if st.session_state.get(_delete_armed_key(eetra_id)):
        st.button(
            _tu("🗑️ Delete item"), key=f"edit_delete_{eetra_id}",
            width="stretch", disabled=True,
        )
        return
    if st.button(_tu("🗑️ Delete item"), key=f"edit_delete_{eetra_id}", width="stretch"):
        st.session_state[_delete_armed_key(eetra_id)] = True
        st.rerun()


def _render_delete_confirmation(raw_df: pd.DataFrame, eetra_id: str, row: dict) -> None:
    """The second step: a full-width panel naming the product before it goes.

    Deleting is the one action on this page that removes something from every
    other view, so the destructive call sits behind its own explicitly-labelled
    click — the toolbar button only arms this panel.
    """
    _flag = _delete_armed_key(eetra_id)
    if not st.session_state.get(_flag):
        return

    _name = str(row.get("A__ProductName", "") or "").strip() or "this item"
    _manu = str(row.get("A__Manufacturer", "") or "").strip()
    _title = f"{_manu} — {_name}" if _manu else _name

    with st.container(border=True):
        st.warning(
            f"Delete **{_title}** (`{eetra_id}`)?\n\n"
            "It disappears from the Catalogue, Charts, Maps and every export on the "
            "next rerun.",
            icon="⚠️",
        )
        st.caption(
            _tu("Recorded as a `delete` record in `edits_data.parquet`, keeping a full "
            "snapshot of the row. `base_data.parquet` is not modified, so the item "
            "can be restored by removing that record from the edit log.")
        )
        _c_yes, _c_no, _ = st.columns([2, 1.4, 5], gap=_add_edit_col_gap())
        with _c_yes:
            _confirm = st.button(
                _tu("Yes, delete this item"),
                key=f"edit_delete_confirm_{eetra_id}",
                type="primary",
                width="stretch",
            )
        with _c_no:
            _cancel = st.button(
                _tu("Cancel"), key=f"edit_delete_cancel_{eetra_id}", width="stretch"
            )

    if _cancel:
        st.session_state.pop(_flag, None)
        st.rerun()
    if _confirm:
        try:
            _persist_delete(raw_df, eetra_id)
        except Exception as _e:
            st.session_state.pop(_flag, None)
            st.error(f"Could not delete `{eetra_id}`: {_e}")
            return
        st.session_state.pop(_flag, None)
        # The picker's own key cannot be written here — the selectbox has already
        # been instantiated this run, and assigning to it raises. It does not need
        # to be: the deleted label is gone from the options on the next run, and
        # the caller treats a selection that no longer resolves as "nothing
        # selected".
        st.session_state["_edit_deleted_note"] = f"{_title} (`{eetra_id}`)"
        st.rerun()


def _render_edit_section() -> None:
    _raw_df, _path = _load_raw()
    _deleted_note = st.session_state.pop("_edit_deleted_note", None)
    if _deleted_note:
        st.success(f"🗑️ Deleted **{_deleted_note}** — removed from the catalogue.")
    _epd_note = st.session_state.pop("_epd_propagated_note_edit", None)
    if _epd_note:
        st.success(_epd_note)
    if "0__EETRA_ID" not in _raw_df.columns or _raw_df.empty:
        fn356_empty_state("No products in the database yet.", kind="empty")
        return
    _picker_df = _edit_picker_dataframe(_raw_df)
    if _picker_df.empty:
        fn356_empty_state(
            "No products match what the **Catalogue** would show — check sidebar "
            "**Dataset Filters** and that data has finished loading.",
            kind="empty",
        )
        return
    if not fn352_is_embedded_page():
        _orig = st.session_state.get("ORIGINAL_DATA", _raw_df)
        _orig_n = int(len(_orig)) if isinstance(_orig, pd.DataFrame) and not _orig.empty else len(_raw_df)
        st.caption(
            f"Showing {len(_picker_df)} of {_orig_n} products (same set as Catalogue for the "
            f"current **Data Source** and sidebar filters). Clear filters to widen the list."
        )
    _picker_df["_label"] = (
        _picker_df["A__Manufacturer"].astype(str).fillna("")
        + " — " + _picker_df["A__ProductName"].astype(str).fillna("")
        + "  (" + _picker_df["0__EETRA_ID"].astype(str).fillna("") + ")"
    )
    _picker_df = _picker_df.sort_values("_label")
    # Catalogue detail-panel "Edit item" deep-link: pre-select before the
    # selectbox is created so Streamlit accepts the session-state write.
    _pending_eid = str(st.session_state.pop("_pending_edit_eetra_id", "") or "").strip()
    if _pending_eid:
        _pending_match = _picker_df.loc[
            _picker_df["0__EETRA_ID"].astype(str).str.strip() == _pending_eid
        ]
        if not _pending_match.empty:
            st.session_state["edit_choice"] = str(_pending_match.iloc[0]["_label"])
            # Clear search so a previous filter can't hide the pre-selected row.
            st.session_state.pop("edit_search", None)
        else:
            st.warning(
                f"Product `{_pending_eid}` is not in the editable set for the "
                "current data source / sidebar filters."
            )
    _col_search, _col_pick, _col_editing = st.columns(
        [2, 3, 1.4], gap=_add_edit_col_gap(), vertical_alignment="bottom"
    )
    with _col_search:
        _search = st.text_input(_tu("🔍 Search by manufacturer or product name"), key="edit_search")
    _options = _picker_df["_label"].tolist()
    if _search.strip():
        _s = _search.strip().lower()
        _options = [o for o in _options if _s in o.lower()]
    with _col_pick:
        _choice = st.selectbox(_tu("Select item to edit"), ["— select —"] + _options, key="edit_choice")
    # A selection can stop resolving between runs — the item was just deleted, or
    # a filter narrowed the picker — so never index into the match blindly.
    _match = _picker_df.loc[_picker_df["_label"] == _choice] if _choice != "— select —" else _picker_df.iloc[0:0]
    _has_selection = not _match.empty
    with _col_editing:
        if _has_selection:
            st.caption(f"Editing `{_match.iloc[0]['0__EETRA_ID']}`")

    if _has_selection:
        st.markdown(
            '<div class="add-edit-picker-tabs-gap" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        _row = _match.iloc[0].to_dict()
        _eid = str(_row.get("0__EETRA_ID"))
        _values = _render_form(f"edit_{_eid}", _raw_df, existing_row=_row)
        if _values is not None:
            _ptype_vals = str(_values.get("D__ProductType_ENG", "") or "")
            if voc_not_relevant(_ptype_vals):
                _values[VOC_DATA_RELEVANT_FIELD] = "No"
                for _col in VOC_FIELDS:
                    _values[_col] = VOC_NOT_RELEVANT_VALUE
            elif voc_data_is_not_relevant(_values.get(VOC_DATA_RELEVANT_FIELD)):
                for _col in VOC_FIELDS:
                    _values[_col] = VOC_NOT_RELEVANT_VALUE
            elif voc_cert_is_not_relevant(_values.get("VO__VOC_Cert")):
                for _col in VOC_CERT_NR_LOCK_FIELDS:
                    _values[_col] = VOC_NOT_RELEVANT_VALUE

        _c_save, _c_delete, _ = st.columns([2, 2, 6], gap=_add_edit_col_gap())
        with _c_save:
            _do_save = st.button(
                _tu("💾 Save changes"), key=f"edit_save_{_eid}", type="primary",
                width="stretch",
            )
        with _c_delete:
            _render_delete_button(_eid)
        _render_delete_confirmation(_raw_df, _eid, _row)

        if _do_save:
            _manu = str(_values.get("A__Manufacturer", "")).strip()
            _name = str(_values.get("A__ProductName", "")).strip()
            _ptype = str(_values.get("D__ProductType_ENG", "")).strip()
            _missing = [lbl for lbl, v in
                        [("Manufacturer", _manu), ("Product Name", _name), ("Product Type", _ptype)] if not v]
            if _missing:
                st.error(f"Please fill in required fields: {', '.join(_missing)}.")
            else:
                _updated = _upsert_row(_raw_df, _eid, _values, is_new=False)
                _persist(_updated, _eid, op="update")
                _n_family = _propagate_epd_reference(_updated, _eid)
                if _n_family:
                    st.session_state["_epd_propagated_note_edit"] = _epd_propagation_note(_n_family)
                st.success(f"✅ Saved changes to **{_manu} — {_name}** (`{_eid}`).")
                st.rerun()
    else:
        st.info(_tu("Pick a product above to load and edit its data."))


def _render_options_section() -> None:
    _raw_df, _path = _load_raw()
    _render_available_options(_raw_df)


# ── browser-side editor (libs/item_editor) ───────────────────────────────────
# The Add / Edit form. The draft lives in the browser: status pills, tab
# counters, the Summary matrix, the d/ρ/m_A sync, EPD-variant derivation and the
# GWP panel are recomputed in JavaScript, so editing triggers no reruns. Python
# runs only for the actions below. AppTest suites still drive the widget form
# by setting add_edit_classic_form before run().
from libs.item_editor import item_editor as _item_editor  # noqa: E402
from libs.lib_revalu_map import (  # noqa: E402
    CONCEPT_FIELD_MAP, REVALU_MAP, VOC_NOT_RELEVANT_PRODUCT_TYPES,
    CEMENT_CONCRETE_PRODUCT_TYPES, CEMENT_CONCRETE_ONLY_FIELDS,
    PHYSICAL_PROPERTY_FIELDS as _PHYS_FIELDS, field_relevance, infer_physical_cm as _infer_cm,
)
from libs.lib_epd_family import (  # noqa: E402
    GWP_MODULE_COLS as _GWP_MODULE_COLS, GWP_COPY_COLS as _GWP_COPY_COLS,
)

_CLASSIC_KEY = "add_edit_classic_form"
_IE_PROBES_KEY = "_ie_probes"
_IE_EDIT_EID_KEY = "_ie_edit_eid"
_IE_PHYS_INPUT_COLS = (
    "P__Mass_kgm3", "E__EPD_Density", "P__Thick_mm", "E__EPD_Thick_mm",
    "P__L_WmK", "E__L_WmK", "P__Mass_kgm2", "E__Rvalue",
)


def _ie_blank(v) -> bool:
    if v is None or v is pd.NA:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _ie_json(v):
    """A cell as a JSON-safe scalar (NaN / NA → None, numpy → Python)."""
    if _ie_blank(v):
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _ie_text(v) -> str:
    """Display string for a text widget — same blanks as the classic form."""
    if _ie_blank(v):
        return ""
    s = str(v)
    return "" if s.strip() == "-" else s


def _ie_kind(col: str) -> str:
    """Widget kind — same precedence as _render_one_field / _widget_for_field."""
    if col == "VO__VOC_URL":
        return "voc_url"
    if col in URL_FIELDS:
        return "url"
    if col in READONLY_FIELDS:
        return "readonly"
    if col in ("D__ProductType_ENG", "A__Manufacturer") or col in OPTION_SELECT_FIELDS:
        return "combo"
    if col == _EPD_REF_FLAG_COL:
        return "epdref"
    if col == VOC_DATA_RELEVANT_FIELD:
        return "voc_relevant"
    if col in VOC_CHECKLIST_FIELDS:
        return "checklist"
    if col == "A__Map_yn" or col in YN_SELECT_FIELDS:
        return "yn"
    if col in DATE_FIELDS:
        return "date"
    if col in OPTIONAL_PCT_SENTINEL_FIELDS:
        return "optpct"
    if col in NUMBER_FIELDS:
        return "number"
    if col in TEXTAREA_FIELDS:
        return "textarea"
    return "text"


def _ie_opts_key(col: str) -> str | None:
    if col == "D__ProductType_ENG":
        return "product_types"
    if col == "A__Manufacturer":
        return "manufacturers"
    return col if col in OPTION_SELECT_FIELDS else None


def _ie_initial_values(row: dict | None) -> dict:
    """The record as the editor shows it: one display string per field."""
    row = row or {}
    out: dict[str, str] = {}
    for col in _all_form_fields():
        cur = row.get(col)
        kind = _ie_kind(col)
        if kind == "date":
            d = _coerce_date_value(cur)
            out[col] = d.isoformat() if d else ""
        elif kind == "optpct":
            out[col] = normalize_optional_pct(cur)
        elif kind == "number":
            try:
                n = None if _ie_blank(cur) or cur in ("", "-") else float(cur)
            except (TypeError, ValueError):
                n = None
            # repr: the shortest string that round-trips — saving an untouched
            # field must write back exactly the stored float.
            out[col] = "" if n is None or pd.isna(n) else repr(n)
        elif kind == "epdref":
            s = _ie_text(cur).strip()
            out[col] = {"YES": "Y", "NO": "N"}.get(s.upper(), s)
        elif kind == "yn":
            s = _ie_text(cur).strip().upper()
            out[col] = s if s in ("Y", "N") else ""
        elif col == "D__IncludedProducts":
            # Empty / new → local "n/a"; user overwrites before save when needed.
            out[col] = included_products_display(cur)
        else:
            out[col] = _ie_text(cur)
    for host in _PHYS_FIELDS:
        cm_col = physical_cm_column(host)
        stored = _ie_text(row.get(cm_col)).strip().upper()
        out[cm_col] = stored if stored in ("C", "M") else _infer_cm(host, row)
    return out


def _ie_epd_index(raw_df: pd.DataFrame) -> dict:
    """EPD families by normalised registration number: Y rows and N variants."""
    refs: dict[str, list] = {}
    variants: dict[str, list] = {}
    if raw_df.empty or _EPD_REF_FLAG_COL not in raw_df.columns:
        return {"refs": refs, "variants": variants}
    flags = raw_df[_EPD_REF_FLAG_COL].astype(str).str.strip().str.upper()
    sub = raw_df.loc[flags.isin(["Y", "N", "YES", "NO", "SI", "SÌ"])]
    ref_cols = (*_GWP_COPY_COLS, *_GWP_MODULE_COLS)
    var_cols = (*_EPD_DERIVED_COLS, *_IE_PHYS_INPUT_COLS)
    for r in sub.to_dict("records"):
        key = _epd_reg_key(r.get(_EPD_REG_COL))
        if not key:
            continue
        base = {"id": str(r.get("0__EETRA_ID")), "name": str(r.get("A__ProductName") or "")}
        if _epd_is_reference(r):
            refs.setdefault(key, []).append(
                {**base, "reg": _ie_json(r.get(_EPD_REG_COL)),
                 **{c: _ie_json(r.get(c)) for c in ref_cols}}
            )
        elif _epd_is_variant(r) and _epd_num(r.get(_EPD_FACTOR_COL)) is not None:
            variants.setdefault(key, []).append(
                {**base, _EPD_FACTOR_COL: _ie_json(r.get(_EPD_FACTOR_COL)),
                 **{c: _ie_json(r.get(c)) for c in var_cols}}
            )
    return {"refs": refs, "variants": variants}


def _ie_voc_catalog() -> dict:
    tiers = []
    for t in voc_cert_tiers():
        entries = [
            {"label": str(e.get("label") or "").strip(),
             "description": str(e.get("description") or "").strip(),
             "hint": str(e.get("cert_number_hint") or "").strip()}
            for e in (t.get("entries") or [])
            if isinstance(e, dict) and str(e.get("label") or "").strip()
        ]
        tiers.append({"label": str(t.get("label") or "").strip(), "entries": entries})
    return {"caveat": voc_cert_caveat(), "tiers": tiers}


def _ie_schema(raw_df: pd.DataFrame) -> tuple[dict, str]:
    """Everything static the editor needs, rebuilt only when a parquet changes."""
    # Include textarea heights / form field set so layout or category tweaks
    # (e.g. VOC Data Relevant) refresh without a data change.
    _h_sig = ",".join(f"{c}:{textarea_height(c)}" for c in sorted(TEXTAREA_FIELDS))
    _f_sig = ",".join(_all_form_fields())
    sig = f"{_effective_mtimes()}:{len(_column_display_labels)}:{_h_sig}:{_f_sig}"
    memo = st.session_state.get("_ie_schema_memo")
    if memo and memo[0] == sig:
        return memo[1], sig
    product_types, manufacturers, _ = _cached_form_options(*_effective_mtimes())
    options = {"product_types": product_types, "manufacturers": manufacturers, **_field_option_lists()}
    fields = {}
    for col in _all_form_fields():
        rv_field, tier = REVALU_MAP.get(col, (None, None))
        kind = _ie_kind(col)
        fields[col] = {
            "label": _label_for(col),
            "help": help_for(col),
            "kind": kind,
            "rv": [rv_field, tier] if rv_field else None,
            "h": textarea_height(col),
            "opts": _ie_opts_key(col) if kind == "combo" else None,
        }
    concept_cols = sorted(CONCEPT_FIELD_MAP)
    concept_nr = {
        pt: [c for c in concept_cols if field_relevance(c, pt) == "not_relevant"]
        for pt in ["", *product_types]
    }
    try:
        from libs.lib_tokens import token as _token
        violet = _token("palette", "revalu_violet", "#8c66e0")
    except Exception:
        violet = "#8c66e0"
    schema = {
        "categories": CATEGORIES,
        "fields": fields,
        "options": options,
        "phys": list(_PHYS_FIELDS),
        "phys_cm_help": PHYSICAL_CM_HELP,
        "voc_fields": list(VOC_FIELDS),
        "voc_checklist_values": list(VOC_CHECKLIST_VALUES),
        "voc_checklist_derived": [list(pair) for pair in VOC_CHECKLIST_DERIVED],
        "voc_data_relevant_values": list(VOC_DATA_RELEVANT_VALUES),
        "voc_nr_types": sorted(VOC_NOT_RELEVANT_PRODUCT_TYPES),
        "voc_nr_value": VOC_NOT_RELEVANT_VALUE,
        "cement_types": sorted(CEMENT_CONCRETE_PRODUCT_TYPES),
        "cement_only": sorted(CEMENT_CONCRETE_ONLY_FIELDS),
        "concept_cols": concept_cols,
        "concept_nr": concept_nr,
        "voc_catalog": _ie_voc_catalog(),
        "voc_align": voc_alignment_lookup(),
        "voc_frameworks": voc_rating_frameworks(),
        "epd": _ie_epd_index(raw_df),
        "violet": violet,
    }
    st.session_state["_ie_schema_memo"] = (sig, schema)
    return schema, sig


def _ie_probes(values: dict) -> dict:
    """URL reachability for the record's URL fields plus any the editor asked for."""
    probes = st.session_state.setdefault(_IE_PROBES_KEY, {})
    for col in URL_FIELDS:
        url = str(values.get(col) or "").strip()
        if url and url not in probes:
            p = _cached_url_probe(url, col)
            if p is not None:
                probes[url] = p
    return {u: {k: p.get(k) for k in ("level", "label", "detail")} for u, p in probes.items()}


def _ie_flash(section: str, kind: str, text: str) -> None:
    st.session_state[f"_ie_flash_{section}"] = {"kind": kind, "text": text}


def _ie_take_flash(section: str) -> dict | None:
    f = st.session_state.pop(f"_ie_flash_{section}", None)
    if f:
        f["nonce"] = f"{section}:{id(f)}:{len(str(f))}:{pd.Timestamp.now().value}"
    return f


def _ie_coerce(values: dict, product_type: str) -> dict:
    """Editor strings → the types the classic form hands to _upsert_row."""
    out: dict = {}
    for col, v in (values or {}).items():
        if col in READONLY_FIELDS:
            continue
        kind = _ie_kind(col)
        if col in NUMBER_FIELDS:
            out[col] = _epd_num(v)
        elif col in OPTIONAL_PCT_SENTINEL_FIELDS:
            norm = normalize_optional_pct(v)
            out[col] = norm if norm in ("", "n/d", "n/a") else _epd_num(norm)
        elif kind == "date":
            out[col] = str(v or "")
        else:
            out[col] = "" if v is None else v
    if voc_not_relevant(product_type):
        out[VOC_DATA_RELEVANT_FIELD] = "No"
        for col in VOC_FIELDS:
            out[col] = VOC_NOT_RELEVANT_VALUE
    elif voc_data_is_not_relevant(out.get(VOC_DATA_RELEVANT_FIELD)):
        for col in VOC_FIELDS:
            out[col] = VOC_NOT_RELEVANT_VALUE
    elif voc_cert_is_not_relevant(out.get("VO__VOC_Cert")):
        for col in VOC_CERT_NR_LOCK_FIELDS:
            out[col] = VOC_NOT_RELEVANT_VALUE
    return out


def _ie_apply_epd_variant(values: dict, raw_df: pd.DataFrame, eid: str | None) -> None:
    """Re-derive a variant's GWP data server-side — the browser's copy is a preview."""
    row = dict(values)
    if not _epd_is_variant(row):
        return
    reg = row.get(_EPD_REG_COL)
    factor = _epd_num(row.get(_EPD_FACTOR_COL))
    if not _epd_reg_key(reg) or factor is None:
        return
    ref, status = _epd_family_reference(raw_df, reg, exclude_id=eid)
    if status == "ok" and ref is not None:
        values.update(_epd_variant_values(ref, factor, row))


def _ie_handle_save(section: str, raw_df: pd.DataFrame, action: dict, existing: dict | None) -> None:
    eid = str(existing.get("0__EETRA_ID")) if existing else None
    values = _ie_coerce(action.get("values") or {}, str((action.get("values") or {}).get("D__ProductType_ENG") or ""))
    manu = str(values.get("A__Manufacturer", "")).strip()
    name = str(values.get("A__ProductName", "")).strip()
    ptype = str(values.get("D__ProductType_ENG", "")).strip()
    missing = [lbl for lbl, v in [("Manufacturer", manu), ("Product Name", name), ("Product Type", ptype)] if not v]
    if missing:
        _ie_flash(section, "error", f"Please fill in required fields: {', '.join(missing)}.")
        return
    try:
        _ie_apply_epd_variant(values, raw_df, eid)
        if section == "add":
            new_id = _next_eetra_id(raw_df, ptype)
            updated = _upsert_row(raw_df, new_id, values, is_new=True)
            _persist(updated, new_id, op="insert")
            saved_id, msg = new_id, f"✅ Saved new item **{manu} — {name}** as `{new_id}`."
            st.session_state["_ie_add_reset"] = st.session_state.get("_ie_add_reset", 0) + 1
        else:
            updated = _upsert_row(raw_df, eid, values, is_new=False)
            _persist(updated, eid, op="update")
            saved_id, msg = eid, f"✅ Saved changes to **{manu} — {name}** (`{eid}`)."
        n_family = _propagate_epd_reference(updated, saved_id)
    except Exception as e:  # keep the draft in the browser; say what failed
        _ie_flash(section, "error", f"Could not save: {e}")
        return
    if n_family:
        msg += "\n\n" + _epd_propagation_note(n_family)
    _ie_flash(section, "success", msg)


def _ie_handle_action(section: str, action: dict, raw_df: pd.DataFrame, existing: dict | None) -> None:
    """Act on one editor trigger, then rerun so the editor sees the result."""
    kind = action.get("type")
    if kind == "save":
        _ie_handle_save(section, raw_df, action, existing)
    elif kind == "select":
        st.session_state[_IE_EDIT_EID_KEY] = str(action.get("eid") or "")
    elif kind == "delete" and existing:
        eid = str(existing.get("0__EETRA_ID"))
        name = str(existing.get("A__ProductName", "") or "").strip() or "this item"
        manu = str(existing.get("A__Manufacturer", "") or "").strip()
        try:
            _persist_delete(raw_df, eid)
        except Exception as e:
            _ie_flash(section, "error", f"Could not delete `{eid}`: {e}")
        else:
            st.session_state.pop(_IE_EDIT_EID_KEY, None)
            _ie_flash(section, "success",
                      f"🗑️ Deleted **{manu + ' — ' if manu else ''}{name}** (`{eid}`) — removed from the catalogue.")
    elif kind == "probe":
        probes = st.session_state.setdefault(_IE_PROBES_KEY, {})
        for item in action.get("urls") or []:
            url, col = str(item.get("url") or "").strip(), str(item.get("col") or "")
            p = _cached_url_probe(url, col)
            if p is not None:
                probes[url] = p
        if len(probes) > 300:  # keep the session copy bounded
            for k in list(probes)[: len(probes) - 300]:
                probes.pop(k, None)
    elif kind == "open_voc":
        # Opens a dialog in this run — no rerun, or it would close again.
        from libs.lib_ui import fn346_fetch_document_pdf_bytes, fn348_voc_document_pdf_dialog
        url = str(action.get("url") or "").strip()
        row = pd.Series(dict(existing or {}))
        bdata, _, _ = fn346_fetch_document_pdf_bytes(
            url, str(row.get("0__EETRA_ID", "") or ""), str(row.get("A__ProductName", "") or ""),
            "voc", row=row,
        )
        if bdata:
            fn348_voc_document_pdf_dialog(bdata)
        else:
            st.warning(_tu("Could not load the VOC PDF for preview."))
        return
    st.rerun()


def _ie_picker(raw_df: pd.DataFrame) -> tuple[list, str, pd.DataFrame]:
    picker_df = _edit_picker_dataframe(raw_df)
    if picker_df.empty:
        return [], "", picker_df
    labels = (
        picker_df["A__Manufacturer"].astype(str).fillna("")
        + " — " + picker_df["A__ProductName"].astype(str).fillna("")
        + "  (" + picker_df["0__EETRA_ID"].astype(str).fillna("") + ")"
    )
    items = sorted(zip(picker_df["0__EETRA_ID"].astype(str), labels), key=lambda t: t[1])
    caption = ""
    if not fn352_is_embedded_page():
        orig = st.session_state.get("ORIGINAL_DATA", raw_df)
        orig_n = int(len(orig)) if isinstance(orig, pd.DataFrame) and not orig.empty else len(raw_df)
        caption = (f"Showing {len(picker_df)} of {orig_n} products (same set as Catalogue for the "
                   "current **Data Source** and sidebar filters). Clear filters to widen the list.")
    return [list(t) for t in items], caption, picker_df


def _render_js_section(section: str) -> None:
    """Add or Edit through the browser-side editor."""
    raw_df, _ = _load_raw()
    schema, schema_sig = _ie_schema(raw_df)
    data: dict = {"section": section, "schema": schema, "schema_sig": schema_sig}
    existing: dict | None = None
    flash_extra: dict | None = None

    if section == "edit":
        if "0__EETRA_ID" not in raw_df.columns or raw_df.empty:
            fn356_empty_state("No products in the database yet.", kind="empty")
            return
        items, caption, picker_df = _ie_picker(raw_df)
        if not items:
            fn356_empty_state(
                "No products match what the **Catalogue** would show — check sidebar "
                "**Dataset Filters** and that data has finished loading.",
                kind="empty",
            )
            return
        # Catalogue detail-panel "Edit item" deep-link.
        pending = str(st.session_state.pop("_pending_edit_eetra_id", "") or "").strip()
        if pending:
            if pending in {i for i, _ in items}:
                st.session_state[_IE_EDIT_EID_KEY] = pending
            else:
                flash_extra = {"kind": "warning", "text": (
                    f"Product `{pending}` is not in the editable set for the current data "
                    "source / sidebar filters.")}
        data["picker"] = {"items": items, "caption": caption}
        eid = str(st.session_state.get(_IE_EDIT_EID_KEY) or "")
        match = picker_df.loc[picker_df["0__EETRA_ID"].astype(str) == eid] if eid else picker_df.iloc[0:0]
        if not match.empty:
            # The picker frame can be the session's display copy — read the row
            # from the effective dataset so every form column is there.
            full = raw_df.loc[raw_df["0__EETRA_ID"].astype(str) == eid]
            existing = (full if not full.empty else match).iloc[0].to_dict()
    record_values = _ie_initial_values(existing)
    if section == "add" or existing is not None:
        token_id = (existing or {}).get("0__EETRA_ID", f"new-{st.session_state.get('_ie_add_reset', 0)}")
        data["record"] = {
            "token": f"{section}:{token_id}:{_effective_mtimes()}",
            "eid": str(existing.get("0__EETRA_ID")) if existing else None,
            "title": f"{record_values.get('A__Manufacturer', '')} — {record_values.get('A__ProductName', '')}",
            "values": record_values,
        }
    data["probes"] = _ie_probes(record_values)
    data["flash"] = _ie_take_flash(section) or (
        {**flash_extra, "nonce": f"pending:{pd.Timestamp.now().value}"} if flash_extra else None
    )

    action = _item_editor(data, key=f"item_editor_{section}")
    if action:
        _ie_handle_action(section, action, raw_df, existing)


def _render_section(section: str) -> None:
    """One Add / Edit section: browser editor, or the widget form for AppTest."""
    if st.session_state.get(_CLASSIC_KEY) and os.environ.get("PYTEST_CURRENT_TEST"):
        (_render_add_section if section == "add" else _render_edit_section)()
    else:
        _render_js_section(section)


_add_edit_section = st.session_state.get("_add_edit_section")
if _add_edit_section in ("add", "edit"):
    _render_section(_add_edit_section)
elif _add_edit_section == "options":
    _render_options_section()
else:
    tab_add, tab_edit, tab_options = st.tabs(
        ["Add New Item", "Edit Existing Item", "Available options"]
    )
    with tab_add:
        _render_section("add")
    with tab_edit:
        _render_section("edit")
    with tab_options:
        _render_options_section()
