"""
pages/8_CAM_2025.py — CAM 2025 recycled-content reference (renders CAM.md)

Embedded as a tab of "Further Data Sources"; standalone it renders its own
header through the shared helper like every other page.
"""
from pathlib import Path

import streamlit as st

from libs.lib_header import fn003a_page_header
from libs.lib_ui import fn352_is_embedded_page, fn356_empty_state

if not fn352_is_embedded_page():
    fn003a_page_header(
        "CAM 2025",
        "Target minimi di contenuto riciclato / recuperato / sottoprodotti per materiali da costruzione.",
        icon="📘",
    )

_doc_path = Path(__file__).resolve().parent.parent / "CAM.md"
if _doc_path.is_file():
    st.markdown(_doc_path.read_text(encoding="utf-8"))
else:
    fn356_empty_state(
        "Reference document `CAM.md` not found in the project root.",
        kind="error",
    )
