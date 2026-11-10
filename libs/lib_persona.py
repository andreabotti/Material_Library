"""
libs/lib_persona.py — "Chi sei?" persona chooser for the Welcome page (demo account)

  fn820  render_persona_chooser   three role columns, each with an index of top-nav pages

Inline CCv2 component (no iframe): app primary colour, Source Serif Pro (the
title font, loaded globally by fn005_inject_global_css) on a clear background.
Clicking a role title stores it in ``st.session_state['demo_persona']``;
clicking an index entry also switches to that page.
"""
from __future__ import annotations

import streamlit as st

from libs.lib_i18n import fn704_t as _t, fn711_t_page as _t_page

# Role → (title, tagline, [(page path, nav title, caption), ...]). English
# strings are fallbacks; translations live under persona_* in aux_16.
PERSONAS: dict[str, tuple[str, str, tuple[tuple[str, str, str], ...]]] = {
    "designer": ("Designer", "choose and justify", (
        ("pages/2_Catalogue.py", "Catalogue",
         "Compare products by GWP, recycled content and CAM 2025 compliance."),
        ("pages/3_Charts.py", "Charts",
         "Justify the choice: GWP compared across manufacturers and product types."),
        ("pages/14_FurtherDataSources.py", "Further Data Sources",
         "Reference values from ICE DB and the Italian LCA database (BDI-LCA)."),
    )),
    "contractor": ("Contractor / GC", "procure and document", (
        ("pages/2_Catalogue.py", "Catalogue",
         "List prices and the EPDs to attach to your project documentation."),
        ("pages/15_Manufacturers.py", "Manufacturers",
         "Supplier plants and sustainability credentials."),
        ("pages/14_FurtherDataSources.py", "Further Data Sources",
         "CAM 2025 criteria and EPD registries for verification."),
    )),
    "manufacturer": ("Manufacturer", "get found and improve", (
        ("pages/15_Manufacturers.py", "Manufacturers",
         "Your company profile and Impact Framework score."),
        ("pages/3_Charts.py", "Charts",
         "See where your products sit against competitors on GWP."),
        ("pages/2_Catalogue.py", "Catalogue",
         "How your product cards appear to designers and contractors."),
    )),
}

_HTML = """
<section class="pc">
  <div class="pc-bar"></div>
  <div class="pc-kicker"></div>
  <h2 class="pc-headline"></h2>
  <div class="pc-cols"></div>
</section>
"""

_CSS = """
:host { display: block; }
.pc {
  --pc-green: var(--st-primary-color, #2a7d2e);
  --pc-serif: 'Source Serif Pro', Georgia, serif;
  max-width: 1180px;
  margin: 0;
  padding: 7vh 0 6vh 0;
  color: var(--pc-green);
  font-family: var(--pc-serif);
}
.pc-bar { width: 68px; height: 7px; background: var(--pc-green); }
.pc-kicker {
  margin-top: 20px;
  font-family: var(--st-font, sans-serif);
  font-size: 0.82rem; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase;
}
.pc-headline {
  margin: 6px 0 48px 0;
  font-family: var(--pc-serif);
  /* Same style as the masthead "Material Library" title. */
  font-size: clamp(2rem, 4.2vw, 3.3rem); font-style: italic; font-weight: 400;
  letter-spacing: -0.005em; line-height: 1.15;
  color: var(--pc-green);
}
.pc-cols {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 34px;
}
@media (max-width: 760px) { .pc-cols { grid-template-columns: 1fr; } }
.pc-col { transition: opacity .2s ease; }
.pc-cols.has-sel .pc-col:not(.sel) { opacity: .55; }
.pc-cols.has-sel .pc-col:not(.sel):hover { opacity: 1; }
.pc-role {
  all: unset; box-sizing: border-box; display: block; width: 100%;
  cursor: pointer; padding-top: 16px;
  border-top: 2px solid var(--pc-green);
  transition: border-width .15s ease, padding .15s ease;
}
.pc-role:hover, .pc-role:focus-visible { border-top-width: 5px; padding-top: 13px; }
.pc-col.sel .pc-role { border-top-width: 5px; padding-top: 13px; }
.pc-role:focus-visible { outline: 2px dashed var(--pc-green); outline-offset: 4px; }
.pc-title { font-size: 1.65rem; font-weight: 700; line-height: 1.2; }
.pc-tag { margin-top: 6px; font-size: 1.15rem; font-style: italic; }
.pc-index { list-style: none; margin: 26px 0 0 0; padding: 0; }
.pc-item {
  all: unset; box-sizing: border-box; display: grid;
  grid-template-columns: 2.1rem 1fr; column-gap: 4px;
  width: 100%; padding: 10px 6px; cursor: pointer;
  border-bottom: 1px solid color-mix(in srgb, var(--pc-green) 22%, transparent);
  border-radius: 2px;
}
.pc-item:hover, .pc-item:focus-visible {
  background: color-mix(in srgb, var(--pc-green) 7%, transparent);
}
.pc-num { font-size: 0.95rem; font-weight: 600; opacity: .7; padding-top: 2px; }
.pc-page { font-size: 1.08rem; font-weight: 600; }
.pc-desc {
  grid-column: 2; margin-top: 3px;
  font-family: var(--st-font, sans-serif);
  font-size: 0.86rem; line-height: 1.4;
  color: var(--st-text-color, #1e293b); opacity: .78;
}
"""

_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector(".pc")
  if (!root || !data) return

  root.querySelector(".pc-kicker").textContent = data.kicker || ""
  root.querySelector(".pc-headline").textContent = data.headline || ""

  const cols = root.querySelector(".pc-cols")
  cols.replaceChildren()
  cols.classList.toggle("has-sel", !!data.selected)

  for (const p of data.personas || []) {
    const col = document.createElement("div")
    col.className = "pc-col" + (p.id === data.selected ? " sel" : "")

    const role = document.createElement("button")
    role.type = "button"
    role.className = "pc-role"
    role.setAttribute("aria-pressed", String(p.id === data.selected))
    const title = document.createElement("div")
    title.className = "pc-title"
    title.textContent = p.title
    const tag = document.createElement("div")
    tag.className = "pc-tag"
    tag.textContent = p.tagline
    role.append(title, tag)
    role.onclick = () => setTriggerValue("select", p.id)
    col.append(role)

    const list = document.createElement("ul")
    list.className = "pc-index"
    p.pages.forEach((pg, i) => {
      const li = document.createElement("li")
      const item = document.createElement("button")
      item.type = "button"
      item.className = "pc-item"
      const num = document.createElement("span")
      num.className = "pc-num"
      num.textContent = String(i + 1).padStart(2, "0")
      const name = document.createElement("span")
      name.className = "pc-page"
      name.textContent = pg.title
      const desc = document.createElement("span")
      desc.className = "pc-desc"
      desc.textContent = pg.caption
      item.append(num, name, desc)
      item.onclick = () => setTriggerValue("navigate", { persona: p.id, page: pg.path })
      li.append(item)
      list.append(li)
    })
    col.append(list)
    cols.append(col)
  }
}
"""

_PERSONA_COMPONENT = st.components.v2.component(
    "eetra_persona_chooser",
    html=_HTML,
    css=_CSS,
    js=_JS,
)

_KEY = "persona_chooser"


def _on_select() -> None:
    picked = (st.session_state.get(_KEY) or {}).get("select")
    if picked in PERSONAS:
        st.session_state["demo_persona"] = picked


def fn820_render_persona_chooser() -> None:
    """Render the chooser; switches page when an index entry is clicked."""
    personas = [
        {
            "id": pid,
            "title": _t(f"persona_{pid}", title),
            "tagline": _t(f"persona_{pid}_tagline", tagline),
            "pages": [
                {"path": path, "title": _t_page(nav_title),
                 "caption": _t(f"persona_{pid}_{n}", caption)}
                for n, (path, nav_title, caption) in enumerate(pages, 1)
            ],
        }
        for pid, (title, tagline, pages) in PERSONAS.items()
    ]
    result = _PERSONA_COMPONENT(
        key=_KEY,
        data={
            "kicker": _t("persona_question", "Who are you?"),
            "headline": _t("persona_headline", "One library, three ways to use it"),
            "selected": st.session_state.get("demo_persona"),
            "personas": personas,
        },
        width="stretch",
        on_select_change=_on_select,
        on_navigate_change=lambda: None,
    )
    nav = getattr(result, "navigate", None)
    if isinstance(nav, dict) and nav.get("persona") in PERSONAS:
        st.session_state["demo_persona"] = nav["persona"]
        st.switch_page(nav["page"])
