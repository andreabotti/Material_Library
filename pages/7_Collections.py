"""
pages/7_Collections.py — Tag-based collections manager
"""

from __future__ import annotations

from io import BytesIO

import html as _html

from libs.page_imports import *  # noqa: F401,F403
from libs.lib_header import fn003a_page_header


def _render_duplicate_id_table(dup_df: pd.DataFrame) -> None:
    """Compact borderless table for duplicate EETRA ID diagnostics."""
    if dup_df.empty:
        return
    summary_rows = []
    for eid, grp in dup_df.groupby("0__EETRA_ID", sort=True):
        products = [
            f"{r['A__Manufacturer']} — {r['A__ProductName']}"
            for _, r in grp.iterrows()
        ]
        summary_rows.append({
            "EETRA ID": str(eid),
            "Products": len(grp),
            "Catalogue entries": "; ".join(products),
        })
    summary_df = pd.DataFrame(summary_rows)
    st.caption(
        "Tags are stored by EETRA ID. When several catalogue products share the same ID, "
        "tagging one product tags all of them."
    )
    cols = list(summary_df.columns)
    th_cells = "".join(f'<th scope="col">{_html.escape(str(c))}</th>' for c in cols)
    body_rows = []
    for _, row in summary_df.iterrows():
        cells = "".join(f"<td>{_html.escape(str(row[c]))}</td>" for c in cols)
        body_rows.append(f"<tr>{cells}</tr>")
    table_html = (
        "<style>"
        ".chart-trace-summary { border-collapse: collapse; width: 100%; "
        "border: none; background: transparent; font-size: 0.875rem; }"
        ".chart-trace-summary th, .chart-trace-summary td { "
        "border: none !important; background: transparent !important; "
        "box-shadow: none !important; "
        "padding: 0.2rem 1.5rem 0.2rem 0; text-align: left; vertical-align: top; }"
        ".chart-trace-summary th { font-weight: 600; }"
        ".chart-trace-summary tr { border: none !important; background: transparent !important; }"
        "</style>"
        f'<table class="chart-trace-summary"><thead><tr>{th_cells}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )
    st.markdown(table_html, unsafe_allow_html=True)


def _slug_name(text: str) -> str:
    from libs.lib_tags import fn402_slugify

    return fn402_slugify(text) or "collection"


def _collection_products_df(collection_id: str) -> pd.DataFrame:
    from libs.lib_tags import fn409_get_products_for_collection

    src = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
    cols = [
        "0__EETRA_ID",
        "A__Manufacturer",
        "A__ProductName",
        "D__ProductType_ENG",
        "G__GWP_A1A3",
        "E__ManuCountry",
    ]
    if src is None or src.empty or "0__EETRA_ID" not in src.columns:
        return pd.DataFrame(columns=cols)
    ids = fn409_get_products_for_collection(collection_id)
    if not ids:
        return pd.DataFrame(columns=cols)
    out = src[src["0__EETRA_ID"].astype(str).isin(set(map(str, ids)))].copy()
    keep = [c for c in cols if c in out.columns]
    return out[keep]


def _export_collection_pdf(collection_row: dict, products_df: pd.DataFrame) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from libs.lib_data import image_path_to_data_uri, resolve_local_product_image_path

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4
    y = h - 20 * mm
    today = pd.Timestamp.now().strftime("%Y-%m-%d")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(15 * mm, y, f"EETRA MatLib — {collection_row.get('name', 'Collection')}")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, y, f"Date: {today} · Products: {len(products_df)}")
    y -= 8 * mm
    c.setStrokeColor(colors.HexColor("#e5e7eb"))
    c.line(15 * mm, y, w - 15 * mm, y)
    y -= 6 * mm

    for _, r in products_df.iterrows():
        if y < 30 * mm:
            c.showPage()
            y = h - 20 * mm
        eid = str(r.get("0__EETRA_ID", ""))
        name = str(r.get("A__ProductName", ""))
        mfr = str(r.get("A__Manufacturer", ""))
        ptype = str(r.get("D__ProductType_ENG", ""))
        gwp = str(r.get("G__GWP_A1A3", ""))
        country = str(r.get("E__ManuCountry", ""))

        img_drawn = False
        try:
            src_df = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
            if not src_df.empty and "U__Img_URL" in src_df.columns and "0__EETRA_ID" in src_df.columns:
                row_src = src_df[src_df["0__EETRA_ID"].astype(str) == eid]
                if not row_src.empty:
                    url = str(row_src.iloc[0].get("U__Img_URL", ""))
                    lp = resolve_local_product_image_path(url, eid, name)
                    if lp is not None:
                        c.drawImage(str(lp), 15 * mm, y - 16 * mm, width=18 * mm, height=14 * mm, preserveAspectRatio=True, anchor='sw')
                        img_drawn = True
        except Exception:
            img_drawn = False

        x0 = 36 * mm if img_drawn else 15 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0, y, f"{mfr} — {name}")
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        c.drawString(x0, y, f"Type: {ptype} · GWP A1-A3: {gwp} · Country: {country} · ID: {eid}")
        y -= 7 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(15 * mm, 12 * mm, f"Generated by EETRA MatLib · {today}")
    c.save()
    return buffer.getvalue()


# When embedded as a Catalogue tab the page title is provided by the host tab,
# so suppress this page's own header to avoid a double title.
if not fn352_is_embedded_page():
    fn003a_page_header("Collections", "Save and share reusable tag sets.")

from libs.lib_tags import (  # lazy import at page level keeps module boundaries explicit
    fn402_slugify,
    fn404_load_collections,
    fn414_list_all_tags,
    fn415_create_collection,
    fn416_update_collection,
    fn417_delete_collection,
    fn418_duplicate_collection,
    fn419_resolve_collection_by_share_token,
    fn420_audit_duplicate_product_ids,
)

_dup = fn420_audit_duplicate_product_ids()
if not _dup.empty:
    _n_dup_ids = int(_dup["0__EETRA_ID"].astype(str).nunique())
    st.warning(f"Tag ambiguity: {_n_dup_ids} EETRA IDs are shared by multiple catalogue products.")
    with st.expander("View duplicate EETRA IDs", expanded=True):
        _render_duplicate_id_table(_dup)

_share = st.query_params.get("collection_share")
if _share:
    _row = fn419_resolve_collection_by_share_token(_share)
    if _row:
        st.session_state["selected_collection_id"] = _row["collection_id"]

collections = fn404_load_collections()
all_tags = fn414_list_all_tags()
tag_options = all_tags["tag_slug"].astype(str).tolist() if not all_tags.empty else []
tag_label_map = (
    {str(r["tag_slug"]): str(r["tag_label"]) for _, r in all_tags[["tag_slug", "tag_label"]].iterrows()}
    if not all_tags.empty
    else {}
)

left, right = st.columns([1, 2], gap="large")

with left:
    st.subheader("Collections")
    if st.button("+ New collection", key="collections_new"):
        new_id = fn415_create_collection("New collection", "")
        st.session_state["selected_collection_id"] = new_id
        st.rerun()

    if collections.empty:
        st.caption("No collections yet — create one above.")
    else:
        for _, row in collections.iterrows():
            cid = str(row["collection_id"])
            products_n = len(_collection_products_df(cid))
            tags_n = len(row.get("tag_slugs") or [])
            label = f"{row['name']}   {products_n} products · {tags_n} tags"
            if st.button(label, key=f"col_sel_{cid}", width='stretch'):
                st.session_state["selected_collection_id"] = cid
                st.rerun()

    selected_id = st.session_state.get("selected_collection_id")
    if selected_id:
        selected_row = collections.loc[collections["collection_id"] == selected_id]
        if not selected_row.empty:
            share = str(selected_row.iloc[0].get("share_token", ""))
            if share:
                st.markdown("#### Share link")
                _base = st.query_params.to_dict()
                _base["collection_share"] = share
                _pairs = [f"{k}={v}" for k, v in _base.items() if v]
                st.code(f"?{'&'.join(_pairs)}", language=None)

with right:
    selected_id = st.session_state.get("selected_collection_id")
    row_df = collections.loc[collections["collection_id"] == selected_id] if selected_id else pd.DataFrame()
    if selected_id and not row_df.empty:
        row = row_df.iloc[0]
        name_key = f"col_name_{selected_id}"
        desc_key = f"col_desc_{selected_id}"
        tags_key = f"col_tags_{selected_id}"

        cur_name = str(row.get("name", ""))
        cur_desc = str(row.get("description", ""))
        cur_tags = list(row.get("tag_slugs") or [])

        name_val = st.text_input("Name", value=cur_name, key=name_key)
        desc_val = st.text_area("Description", value=cur_desc, key=desc_key)
        tags_val = st.multiselect(
            "Tags in this collection",
            options=tag_options,
            default=[t for t in cur_tags if t in tag_options],
            format_func=lambda s: tag_label_map.get(s, s),
            key=tags_key,
        )

        if name_val != cur_name:
            fn416_update_collection(selected_id, name=name_val)
            st.rerun()
        if desc_val != cur_desc:
            fn416_update_collection(selected_id, description=desc_val)
            st.rerun()
        if set(tags_val) != set(cur_tags):
            fn416_update_collection(selected_id, tag_slugs=tags_val)
            st.rerun()

        products_df = _collection_products_df(selected_id)
        st.markdown("#### Products in this collection")
        st.dataframe(products_df, width="stretch", height=420)

        action_cols = st.columns(5)
        with action_cols[0]:
            if st.button("Duplicate", key=f"dup_{selected_id}"):
                new_id = fn418_duplicate_collection(selected_id)
                st.session_state["selected_collection_id"] = new_id
                st.rerun()
        with action_cols[1]:
            _confirm = st.checkbox("Confirm delete", key=f"del_chk_{selected_id}")
            if st.button("Delete", key=f"del_{selected_id}", disabled=not _confirm):
                fn417_delete_collection(selected_id)
                st.session_state["selected_collection_id"] = None
                st.rerun()
        with action_cols[2]:
            csv_name = f"eetra_collection_{_slug_name(cur_name)}_{pd.Timestamp.now().strftime('%Y-%m-%d')}.csv"
            st.download_button(
                "Export CSV",
                data=products_df.to_csv(index=False).encode("utf-8"),
                file_name=csv_name,
                mime="text/csv",
                key=f"csv_{selected_id}",
            )
        with action_cols[3]:
            # Two-step on purpose: building the PDF walks every product and
            # opens its image, so it must not run on every rerun just because a
            # collection happens to be selected.
            pdf_name = f"eetra_collection_{_slug_name(cur_name)}_{pd.Timestamp.now().strftime('%Y-%m-%d')}.pdf"
            _pdf_state_key = f"_pdf_ready_{selected_id}"
            if st.button("Build PDF", key=f"pdf_build_{selected_id}"):
                with fn357_loading("Building PDF…"):
                    st.session_state[_pdf_state_key] = _export_collection_pdf(
                        row.to_dict(), products_df
                    )
            if st.session_state.get(_pdf_state_key):
                st.download_button(
                    "Download PDF",
                    data=st.session_state[_pdf_state_key],
                    file_name=pdf_name,
                    mime="application/pdf",
                    key=f"pdf_{selected_id}",
                )
    else:
        fn356_empty_state(
            "Select a collection on the left, or create a new one.",
            kind="empty",
        )
