"""
pages/1_Welcome.py — Overview, persona chooser (demo), page guide, quick stats
Native Streamlit layout, st.page_link navigation. No emoji glyphs. No
in-page title (the full masthead is shown on Welcome). Application status lives in the sidebar
(app.py); the stats sit at the bottom as a low-key caption.
"""
import streamlit as st

from libs.page_imports import *  # noqa: F401,F403
from libs.lib_i18n import fn704_t as _t, fn711_t_page as _t_page
from libs.lib_ui import DEMO_USERNAME

# ── Pull shared data ─────────────────────────────────────────────────────
df_original = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
_is_demo = str(st.session_state.get("auth_user", "")).strip().lower() == DEMO_USERNAME

# No in-page title: the full masthead above already names the app.

if _is_demo:
    # ── Persona choice (demo account only) ────────────────────────────────
    # Each role carries its own index of top-nav pages; the choice is kept as
    # ``demo_persona`` (designer / contractor / manufacturer).
    from libs.lib_persona import fn820_render_persona_chooser
    fn820_render_persona_chooser()
else:
    # ── Navigation guide (native links, no emojis) ───────────────────────
    st.markdown(f"#### {_t('explore', 'Explore')}")
    st.page_link("pages/2_Catalogue.py",
                 label=_t_page("Catalogue"))
    st.caption(_t("welcome_catalogue_caption",
                  "Product cards with specifications, GWP data and imagery."))
    st.page_link("pages/15_Manufacturers.py",
                 label=_t_page("Manufacturers"))
    st.caption(_t("welcome_manufacturers_caption",
                  "Company profiles, sustainability credentials and Impact Framework scoring."))
    # Collections page hidden for now — uncomment to restore (also in app.py).
    # st.page_link("pages/7_Collections.py",
    #              label="Collections")
    # st.caption("Save and share reusable tag sets.")
    st.page_link("pages/3_Charts.py",
                 label=_t_page("Charts"))
    st.caption(_t("welcome_charts_caption",
                  "Box plots and bar charts comparing GWP across manufacturers and product types."))
    st.page_link("pages/14_FurtherDataSources.py",
                 label=_t_page("Further Data Sources"))
    st.caption(_t("welcome_sources_caption",
                  "Impact Framework matrix, ICE DB, CAM 2025, ECOportal and BDI-LCA browsers."))

# ── Quick stats (bottom, low emphasis) ───────────────────────────────────
_total = int(len(df_original)) if not df_original.empty else 0
_manu = (
    int(df_original["A__Manufacturer"].nunique())
    if "A__Manufacturer" in df_original.columns else 0
)
_locs = (
    int(df_original["E__ManuPlant"].nunique())
    if "E__ManuPlant" in df_original.columns else 0
)

fn303_custom_hr()
st.caption(" · ".join((
    f"{_t('products_in_database', 'Products in database')}: **{_total:,}**",
    f"{_t('manufacturers_count', 'Manufacturers')}: **{_manu:,}**",
    f"{_t('manufacturing_locations', 'Manufacturing locations')}: **{_locs:,}**",
)))
