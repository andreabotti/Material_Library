"""Streamlit bridge: catalogue JS2 iframe postMessage → setComponentValue.

Why this exists
───────────────
The JS2 catalogue (02_html/catalogue_component_js2.html) is rendered with
``components.html()``, which is one-way: the iframe can't hand a value back to
Python. The original workaround was for the iframe to set a query param on the
parent window and force ``location.reload()`` — but this app builds its nav with
``st.navigation()``, which has no per-page URL routing, so ANY hard reload lands
on the default page (Welcome). Clicking a button in the catalogue therefore
bounced the user out of the catalogue before the dialog appeared.

This component fixes that. It renders a zero-height declared component (which
Streamlit serves same-origin, so it can attach a listener to the *parent*
window) that catches the catalogue iframe's postMessage and forwards it through
``setComponentValue``. That triggers an ordinary Streamlit rerun — same page,
no reload, no navigation — on which Python can open an ``st.dialog``.

Same trick as libs/epd_source_bridge; kept separate because the message
vocabulary and payload differ.

Messages consumed (posted by the catalogue iframe to ``window.parent``):
    {type: "eetra:viewDocuments",  eetraId: "<EETRA_ID>", kind: "<kind>", nonce: <number>}
    {type: "eetra:closeDocuments", eetraId: "<EETRA_ID>", nonce: <number>}
    {type: "eetra:editItem",       eetraId: "<EETRA_ID>", nonce: <number>}

``kind`` (optional, on ``viewDocuments``) names the document the user asked to
preview: previews are rendered to page images server-side, so opening one costs a
rerun and Python needs to know which file to rasterise.

``eetra:editItem`` is the detail-panel "Edit item" button: Catalogue switches to
Developer Dashboard → Edit Existing Item with that product pre-selected.

The ``nonce`` matters: the component value persists across reruns, so callers
must ignore a payload whose nonce they've already handled (otherwise a dialog
would reopen every rerun after being closed). See
``fn352_catalogue_bridge_action`` in libs/lib_ui.py.
"""
from __future__ import annotations

import os

import streamlit.components.v1 as components

_DIR = os.path.dirname(os.path.abspath(__file__))
_component = components.declare_component(
    "catalogue_bridge",
    path=os.path.join(_DIR, "frontend"),
)


def catalogue_bridge(*, key: str | None = None):
    """Render the (invisible) bridge; return the last action dict, or None.

    Returned dict shape:
    ``{"type": str, "eetraId": str, "kind": str, "nonce": int|float}``
    """
    return _component(key=key, default=None)
