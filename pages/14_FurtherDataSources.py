"""
pages/14_FurtherDataSources.py — Further Data Sources
=======================================================
Consolidates the supplementary data-source browsers under one page with sub-tabs:

  Impact Framework  — framework × indicator matrix (all users; entity cards moved to Manufacturers)
  ICE DB Browser    — Inventory of Carbon & Energy V4.1 (all users)
  CAM 2025          — recycled-content targets reference (all users)
  ECOportal         — soda4LCA EPD browser + ingest pipeline (admin only)
  BDI-LCA Browser   — ENEA Italian LCA database (admin only)

Each sub-page is rendered inline by the shared host helper
``lib_ui.fn354_run_embedded_page`` (one implementation for the whole app; the
Developer page and the Catalogue use the same one). Heavy tabs are lazy-loaded —
a sub-page only runs once its Load button is pressed — so opening this page never
pays the cost of every browser at once.

Admin-only sources are omitted from the tab bar entirely rather than shown as a
locked tab: a tab that cannot do anything is worse than no tab.
"""

from __future__ import annotations

from pathlib import Path

from libs.page_imports import *  # noqa: F401,F403
from libs.lib_ui import fn353_is_admin, fn354_run_embedded_page
from libs.lib_i18n import fn711_t_page as _t_page, fn714_tu as _tu

_PAGES_DIR = Path(__file__).resolve().parent
_is_admin = fn353_is_admin()


def _lazy_gate(section_key: str, label: str, cost_hint: str = "") -> bool:
    """Return True when a heavy sub-page should run; else show a Load button.

    The button says what loading will do and roughly what it costs, so the gate
    reads as a deliberate choice rather than a dead end.
    """
    loaded = st.session_state.setdefault("_further_data_loaded", set())
    if section_key in loaded:
        return True
    # The section keeps its English label as identity; only the wording shown
    # here is translated, section name included.
    shown = _t_page(label)
    st.caption(
        _tu("**{label}** is not loaded yet — this page stays fast until you ask for it.",
            label=shown)
        + (f" {_tu(cost_hint)}" if cost_hint else "")
    )
    if st.button(_tu("Load {label}", label=shown),
                 key=f"further_load_{section_key}", type="primary"):
        loaded.add(section_key)
        st.rerun()
    return False


fn003a_page_header(
    "Further Data Sources",
    "Supplementary sustainability datasets — corporate impact scoring, embodied-carbon inventories, and EPD registries.",
)

# Tab labels are plain text; icons belong to the top-level st.Page entries.
_SECTIONS: list[tuple[str, str, str, str, bool]] = [
    # (key, tab label, page file, cost hint, admin_only)
    ("impact", "Impact Framework", "8_ImpactFramework.py",
     "Loads the framework coverage matrix.", False),
    ("ice", "ICE DB Browser", "12_ICE_DB_Browser.py",
     "Loads ~1,700 embodied-carbon records and four charts.", False),
    ("cam", "CAM 2025", "8_CAM_2025.py", "", False),
    ("ecoportal", "ECOportal", "9_ECOportal.py",
     "Indexes the full soda4LCA EPD dataset — a few seconds on a cold cache.", True),
    ("bdilca", "BDI-LCA Browser", "11_BDILCA_Browser.py",
     "Parses the ARCADIA ILCD XML files.", True),
]

_visible = [s for s in _SECTIONS if _is_admin or not s[4]]
# Lazy tabs: only the selected section runs. The Load gate below is a first-visit
# opt-in only — on its own it never switched a section off again, so once all of
# them had been loaded, every click on this page re-ran every sub-page, visible
# or not.
# _SECTIONS keeps the English label as its identity; only the tab strip translates.
_tabs = st.tabs([_t_page(s[1]) for s in _visible], on_change="rerun", key="further_data_active_tab")

for _tab, (_key, _label, _file, _hint, _admin_only) in zip(_tabs, _visible):
    if not _tab.open:
        continue
    with _tab:
        # CAM 2025 is a static markdown reference — no gate needed.
        if _key == "cam":
            fn354_run_embedded_page(_PAGES_DIR / _file, _label)
        elif _lazy_gate(_key, _label, _hint):
            fn354_run_embedded_page(_PAGES_DIR / _file, _label)

if not _is_admin:
    st.caption(
        _tu("ECOportal and the BDI-LCA browser are administrator tools and are not shown here.")
    )
