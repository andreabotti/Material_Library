"""
pages/8_ImpactFramework.py — EETRA Impact Framework: framework × indicator matrix

Hosted under Further Data Sources. The entity browser (manufacturers, specifiers,
contractors — cards, scoring, detail panel) moved to pages/15_Manufacturers.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from libs.page_imports import *  # noqa: F401,F403

# ── Load data ────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_framework() -> dict:
    p = Path(__file__).parent.parent / "aux_13__companies_impact_framework.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)


DATA = _load_framework()
_fw_matrix = DATA["framework_matrix"]["frameworks"]

_FONTS = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+Pro:ital,wght@0,600;1,600&family=IBM+Plex+Mono&display=swap');"

def _framework_matrix_html() -> str:
    entity_types = ["manufacturers", "specifiers", "contractors"]
    labels = {"manufacturers": "Produttori", "specifiers": "Progettisti", "contractors": "Imprese"}
    ind_keys = {
        "manufacturers": "company_indicators",
        "specifiers": "specifier_indicators",
        "contractors": "contractor_indicators",
    }
    fw_list = list(_fw_matrix.items())

    # compute coverage counts
    data = {}
    for fw_key, fw_data in fw_list:
        data[fw_key] = {}
        for et in entity_types:
            inds = fw_data.get(ind_keys[et], [])
            data[fw_key][et] = len(inds)

    max_count = max(
        (data[fw][et] for fw in data for et in entity_types), default=1
    ) or 1

    header_cells = "".join(f'<th>{labels[et]}</th>' for et in entity_types)
    rows_html = ""
    for fw_key, fw_data in fw_list:
        label = fw_data.get("label", fw_key)
        scope = fw_data.get("scope", "")
        row = f'<td style="font-size:12px;padding:8px 12px;max-width:240px;"><strong>{label}</strong><br><span style="color:#64748b;font-size:10px;">{scope}</span></td>'
        for et in entity_types:
            cnt = data[fw_key][et]
            inds = fw_data.get(ind_keys[et], [])
            tooltip = "&#10;".join(inds) if inds else "—"
            intensity = cnt / max_count
            r = int(255 - intensity * (255 - 42))
            g = int(255 - intensity * (255 - 125))
            b = int(255 - intensity * (255 - 46))
            bg = f"rgb({r},{g},{b})" if cnt > 0 else "#f8fafc"
            fg = "#fff" if intensity > 0.5 else "#1a1a1a"
            row += f'<td title="{tooltip}" style="text-align:center;padding:8px;background:{bg};color:{fg};font-size:12px;font-weight:600;cursor:help;">{cnt}</td>'
        rows_html += f"<tr>{row}</tr>"

    legend_html = ""
    for fw_key, fw_data in fw_list:
        label = fw_data.get("label", fw_key)
        scope = fw_data.get("scope", "")
        legend_html += f'<div style="margin-bottom:6px;font-size:11px;"><strong>{label}</strong>: {scope}</div>'

    return f"""
<style>
{_FONTS}
body{{font-family:'IBM Plex Sans',system-ui,sans-serif;padding:4px;}}
table{{border-collapse:collapse;width:100%;}}
th{{background:#2a7d2e;color:#fff;padding:8px 12px;font-size:11px;font-weight:600;text-align:center;}}
th:first-child{{text-align:left;}}
tr:nth-child(even) td:first-child{{background:#f8fafc;}}
.legend{{margin-top:16px;padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;}}
.legend h4{{font-size:12px;font-weight:600;color:#2a7d2e;margin-bottom:8px;}}
</style>
<table>
  <thead><tr><th>Framework</th>{header_cells}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<div class="legend">
  <h4>Legenda framework</h4>
  {legend_html}
</div>
"""


# ── Page ──────────────────────────────────────────────────────────────────────

# When embedded inside another page's tab the title is provided by the host,
# so suppress this page's own header to avoid a double title.
if not fn352_is_embedded_page():
    fn003a_page_header(
        "Impact Framework",
        "Copertura degli indicatori per framework regolatorio e volontario.",
    )

st.caption(
    "Schede e punteggi di produttori, progettisti e imprese: pagina **Manufacturers**."
)
st.iframe(_framework_matrix_html(), height=800)
