"""Add / Edit Item form as a browser-side component (Streamlit CCv2).

Why this exists
───────────────
The Python form in pages/13_Add_Edit_Item.py renders ~110 widgets; every
keystroke, dropdown pick or tab switch re-ran the whole Developer page to
refresh status pills, tab counters, the d/ρ/m_A sync and the GWP panel. This
component keeps the whole draft in the browser and computes all of that in
JavaScript, so editing costs no reruns at all. Python is only involved when
something has to touch the server:

    load      — Python sends the schema + the selected record via ``data``
    save      — trigger ``action = {type: "save", values}``
    delete    — trigger ``action = {type: "delete"}`` (confirmed in the UI)
    select    — trigger ``action = {type: "select", eid}`` (Edit picker)
    probe     — trigger ``action = {type: "probe", urls}`` (URL reachability)
    open_voc  — trigger ``action = {type: "open_voc", url}`` (PDF dialog)

The draft survives reruns: the frontend only reloads its values when
``data.record.token`` changes (another item, a save, or a reset).

Frontend lives next to this file: item_editor.html / .css / .js. They are read
as inline strings (CCv2 inline mode); the component is re-registered when one
of them changes on disk, so editing the JS does not need an app restart.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

_DIR = Path(__file__).resolve().parent
_FILES = ("item_editor.html", "item_editor.css", "item_editor.js")
_ASSETS: dict[str, Any] = {"sig": None, "texts": None}


def _renderer():
    """The CCv2 mount callable.

    Registered on every call: the registry belongs to the Streamlit runtime, not
    to this module (a second runtime — AppTest, a server restart in the same
    process — starts empty), and re-registering an identical definition is a
    silent no-op. Only the file reads are cached, keyed on their mtimes.
    """
    sig = tuple((_DIR / f).stat().st_mtime_ns for f in _FILES)
    if _ASSETS["sig"] != sig:
        _ASSETS["texts"] = tuple((_DIR / f).read_text(encoding="utf-8") for f in _FILES)
        _ASSETS["sig"] = sig
    html, css, js = _ASSETS["texts"]
    return st.components.v2.component("matlib_item_editor", html=html, css=css, js=js)


def item_editor(data: dict, *, key: str) -> dict | None:
    """Mount the editor; return this run's action dict (or None)."""
    result = _renderer()(
        key=key,
        data=data,
        on_action_change=lambda: None,
    )
    action = getattr(result, "action", None)
    return action if isinstance(action, dict) else None
