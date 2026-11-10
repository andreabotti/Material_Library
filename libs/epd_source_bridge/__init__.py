"""Streamlit bridge: EPD iframe postMessage ↔ setComponentValue + deliver back."""
from __future__ import annotations

import os

import streamlit.components.v1 as components

_DIR = os.path.dirname(os.path.abspath(__file__))
_component = components.declare_component(
    "epd_source_bridge",
    path=os.path.join(_DIR, "frontend"),
)


def epd_source_bridge(*, deliver: str = "", key: str | None = None):
    """deliver: JSON string of epd:sourceBundle message to forward to browser iframes."""
    return _component(deliver=deliver, key=key, default=None)
