"""
pages/16_Add_Edit_Manufacturer.py — Add / Edit a manufacturer
=============================================================
Structured like ``13_Add_Edit_Item.py`` (category tabs, filled/missing status,
Save / Delete) but targeting Impact Framework manufacturer entities plus the
optional sustainability-credentials overlay.

Persistence (``libs/lib_data.py`` fn140d–fn140g):
  • reads  aux_13__companies_impact_framework.json ⊕ aux_14__companies_sust_credentials.json
  • writes atomically back to those JSON files and clears related caches

Hosted from the Developer Dashboard via ``_add_mfr_section`` = add | edit
(same embedding pattern as the product Add/Edit page).
"""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from libs.lib_header import fn003a_page_header
from libs.lib_data import (
    fn140d_list_manufacturer_names,
    fn140e_load_manufacturer_for_edit,
    fn140f_save_manufacturer_edit,
    fn140g_delete_manufacturer_edit,
    _ifw_score_manufacturer,
)
from libs.lib_manufacturer_map import (
    CATEGORIES,
    BOOL_FIELDS,
    INT_FIELDS,
    SELECT_OPTIONS,
    TEXTAREA_FIELDS,
    URL_FIELDS,
    FLOAT_OK,
    all_form_fields,
    empty_entity,
    field_status,
    flatten_manufacturer,
    help_for,
    label_for,
    status_badge_html,
    status_counts,
    unflatten_to_entity,
)
from libs.lib_tokens import theme_section, add_edit_form_css
from libs.lib_i18n import fn714_tu as _tu
from libs.lib_ui import fn352_is_embedded_page, render_add_edit_section_title_with_divider


def _col_gap() -> int:
    return int(
        (theme_section("developer_dashboard", "add_edit_form") or {}).get(
            "widget_columns_gap_px", 15
        )
    )


def _widget_help(col: str) -> dict:
    h = help_for(col)
    return {"help": h} if h else {}


def _widget_for_field(col: str, current: Any, key: str, *, disabled: bool = False):
    label = label_for(col)
    if col in BOOL_FIELDS:
        options = ["", "True", "False"]
        if current is True:
            cur = "True"
        elif current is False:
            cur = "False"
        else:
            cur = ""
        idx = options.index(cur) if cur in options else 0
        chosen = st.selectbox(
            label, options, index=idx, key=key, disabled=disabled,
            format_func=lambda v: v or "(blank)", **_widget_help(col),
        )
        if chosen == "True":
            return True
        if chosen == "False":
            return False
        return None
    if col in SELECT_OPTIONS:
        opts = list(SELECT_OPTIONS[col])
        cur = "" if current is None or (isinstance(current, float) and pd.isna(current)) else str(current)
        if cur and cur not in opts:
            opts = opts + [cur]
        idx = opts.index(cur) if cur in opts else 0
        return st.selectbox(
            label, opts, index=idx, key=key, disabled=disabled,
            format_func=lambda v: v or "(blank)", **_widget_help(col),
        )
    if col in TEXTAREA_FIELDS:
        val = "" if current in (None, "-") or (isinstance(current, float) and pd.isna(current)) else str(current)
        return st.text_area(label, value=val, key=key, height=104, disabled=disabled, **_widget_help(col))
    if col in INT_FIELDS:
        try:
            if current in (None, "", "-") or (isinstance(current, float) and pd.isna(current)):
                num = None
            else:
                num = float(current)
                if col not in FLOAT_OK:
                    num = float(int(num))
        except Exception:
            # Keep free-text tokens (e.g. epd_count_active = "multiple")
            val = "" if current is None else str(current)
            return st.text_input(label, value=val, key=key, disabled=disabled, **_widget_help(col))
        return st.number_input(
            label, value=num, key=key, disabled=disabled,
            format="%.4f" if col in FLOAT_OK else "%.0f",
            step=0.1 if col in FLOAT_OK else 1.0,
            **_widget_help(col),
        )
    val = "" if current in (None, "-") or (isinstance(current, float) and pd.isna(current)) else str(current)
    return st.text_input(label, value=val, key=key, disabled=disabled, **_widget_help(col))


def _render_field_row(
    fields: list[str],
    values: dict,
    key_prefix: str,
    *,
    columns_per_row: int = 2,
) -> None:
    n = max(1, int(columns_per_row or 2))
    for start in range(0, len(fields), n):
        chunk = fields[start : start + n]
        cols = st.columns(len(chunk), gap=_col_gap())
        for col_name, slot in zip(chunk, cols):
            with slot:
                # Same order as Edit Existing Item: widget first, status under it.
                values[col_name] = _widget_for_field(
                    col_name,
                    values.get(col_name),
                    f"{key_prefix}__{col_name}",
                )
                status = field_status(col_name, values.get(col_name))
                st.markdown(
                    f'<div class="add-edit-phys-meta">{status_badge_html(status)}</div>',
                    unsafe_allow_html=True,
                )


def _render_category_tab(cat: dict, values: dict, key_prefix: str) -> None:
    for group in cat.get("field_groups") or [{"fields": cat["fields"], "columns_per_row": 2}]:
        title = group.get("section_title")
        if title:
            if group.get("section_divider"):
                render_add_edit_section_title_with_divider(str(title))
            else:
                st.markdown(
                    f'<div class="add-edit-field-group-title">'
                    f"{html.escape(str(title))}</div>",
                    unsafe_allow_html=True,
                )
        fields = [f for f in group.get("fields", []) if f]
        if fields:
            _render_field_row(
                fields, values, key_prefix,
                columns_per_row=int(group.get("columns_per_row") or 2),
            )


def _summary_tab(values: dict) -> None:
    all_fields = all_form_fields()
    overall = status_counts(all_fields, values)
    try:
        score = _ifw_score_manufacturer(unflatten_to_entity(values))
    except Exception:
        score = None
    if score:
        m0, m1, m2 = st.columns(3)
        with m0:
            st.metric(_tu("Impact score"), f"{score['total']:.1f} / 100")
        with m1:
            st.metric(_tu("Filled"), overall["filled"])
        with m2:
            st.metric(_tu("Missing"), overall["missing"])
        st.caption(
            f"Axes — A climate {score['A']:.0f} · B reporting {score['B']:.0f} · "
            f"C products {score['C']:.0f} · D supply {score['D']:.0f}"
        )
    else:
        m1, m2 = st.columns(2)
        with m1:
            st.metric(_tu("Filled"), overall["filled"])
        with m2:
            st.metric(_tu("Missing"), overall["missing"])

    for cat in CATEGORIES:
        counts = status_counts(cat["fields"], values)
        n = len(cat["fields"])
        st.markdown(
            f"**{cat['label']}** "
            f"({counts['filled']}/{n}) — "
            f"{counts['filled']} filled · {counts['missing']} missing"
        )
        rows = "".join(
            f'<div class="add-edit-summary-row">'
            f"{status_badge_html(field_status(col, values.get(col)))} "
            f"<span>{html.escape(label_for(col))}</span></div>"
            for col in cat["fields"]
        )
        st.markdown(rows, unsafe_allow_html=True)


def _render_form(mode: str, values: dict, *, previous_name: str | None) -> None:
    st.markdown(
        f"<style>{add_edit_form_css()}</style><div class='add-edit-form-root'></div>",
        unsafe_allow_html=True,
    )
    all_fields = all_form_fields()
    overall = status_counts(all_fields, values)
    labels = [
        f"Summary ({overall['filled']}/{len(all_fields)})",
        *[
            f"{cat['label']} ({status_counts(cat['fields'], values)['filled']}/{len(cat['fields'])})"
            for cat in CATEGORIES
        ],
    ]
    tabs = st.tabs(labels)
    with tabs[0]:
        _summary_tab(values)
    key_prefix = f"mfr_{mode}_{previous_name or 'new'}"
    for cat, tab in zip(CATEGORIES, tabs[1:]):
        with tab:
            _render_category_tab(cat, values, key_prefix)

    st.markdown("---")
    if mode == "add":
        if st.button(_tu("💾 Save new manufacturer"), type="primary", key="mfr_add_save"):
            name = str(values.get("M__Name") or "").strip()
            if not name:
                st.error(_tu("Manufacturer name is required."))
            elif name in fn140d_list_manufacturer_names():
                st.error(f"**{name}** already exists — use Edit instead.")
            else:
                try:
                    saved = fn140f_save_manufacturer_edit(values, previous_name=None)
                    st.success(f"Saved **{saved}**.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
    else:
        c_save, c_del, _ = st.columns([2, 2, 6], gap=_col_gap())
        with c_save:
            do_save = st.button(
                _tu("💾 Save changes"), type="primary",
                key=f"mfr_edit_save_{previous_name}",
            )
        with c_del:
            do_del = st.button(
                _tu("🗑️ Delete manufacturer"),
                key=f"mfr_edit_del_{previous_name}",
            )
        wipe = st.checkbox(
            _tu("Also remove sustainability credentials / profile on delete"),
            value=False,
            key=f"mfr_wipe_sust_{previous_name}",
        )
        if do_save:
            try:
                saved = fn140f_save_manufacturer_edit(
                    values, previous_name=previous_name,
                )
                st.session_state["mfr_edit_pick"] = saved
                st.session_state.pop("mfr_edit_loaded_for", None)
                st.success(f"Saved **{saved}**.")
                st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")
        if do_del:
            confirm_key = f"mfr_del_confirm_{previous_name}"
            if not st.session_state.get(confirm_key):
                st.session_state[confirm_key] = True
                st.warning(
                    f"Click **Delete manufacturer** again to permanently remove "
                    f"**{previous_name}** from the Impact Framework"
                    + (" and credentials files." if wipe else ".")
                )
            else:
                try:
                    fn140g_delete_manufacturer_edit(
                        previous_name or "", wipe_sust=wipe,
                    )
                    st.session_state.pop("mfr_edit_pick", None)
                    st.session_state.pop("mfr_edit_loaded_for", None)
                    st.session_state.pop(confirm_key, None)
                    st.success(f"Deleted **{previous_name}**.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


def _render_add_section() -> None:
    st.caption(
        _tu("Creates a new Impact Framework manufacturer. Fill Credentials Matrix "
        "to also seed the Manufacturers directory credentials / profile.")
    )
    values = flatten_manufacturer("", empty_entity())
    # Seed widgets from session once per add session
    seed_key = "mfr_add_values"
    if seed_key not in st.session_state:
        st.session_state[seed_key] = values
    form_vals = dict(st.session_state[seed_key])
    _render_form("add", form_vals, previous_name=None)
    st.session_state[seed_key] = form_vals


def _render_edit_section() -> None:
    names = fn140d_list_manufacturer_names()
    if not names:
        st.info(_tu("No manufacturers found in the Impact Framework or credentials files."))
        return
    pick = st.selectbox(
        _tu("Select manufacturer to edit"),
        options=names,
        key="mfr_edit_pick",
    )
    if not pick:
        st.info(_tu("Pick a manufacturer above to load and edit its data."))
        return
    st.caption(f"Editing **{pick}** — Impact Framework + credentials overlay.")
    cache_key = f"mfr_edit_values::{pick}"
    if st.session_state.get("mfr_edit_loaded_for") != pick:
        st.session_state[cache_key] = fn140e_load_manufacturer_for_edit(pick)
        st.session_state["mfr_edit_loaded_for"] = pick
    form_vals = dict(st.session_state.get(cache_key) or {})
    _render_form("edit", form_vals, previous_name=pick)
    st.session_state[cache_key] = form_vals


# ── page chrome ──────────────────────────────────────────────────────────────
if not fn352_is_embedded_page():
    fn003a_page_header(
        "Add / Edit Manufacturer",
        "Impact Framework company profile and sustainability credentials — "
        "same tabbed structure as the product editor.",
    )

_section = st.session_state.get("_add_mfr_section")
if _section == "add":
    _render_add_section()
elif _section == "edit":
    _render_edit_section()
else:
    tab_add, tab_edit = st.tabs(["Add manufacturer", "Edit manufacturer"])
    with tab_add:
        _render_add_section()
    with tab_edit:
        _render_edit_section()
