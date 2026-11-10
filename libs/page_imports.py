"""
libs/page_imports.py
====================
Single-import shim for all EETRA page modules.

Each page uses:
    from libs.page_imports import *   # noqa: F401,F403
"""

# ── Standard library & third-party ───────────────────────────────────────────
import streamlit as st
import pandas as pd
import plotly.io as pio
import plotly.graph_objects as go
import plotly.express as px
import pydeck as pdk
import requests
import json, hashlib, re, os
import html as _html
import concurrent.futures as _cf
from pathlib import Path
from PIL import Image

# ── New consolidated lib modules ──────────────────────────────────────────────
from .lib_data import *    # noqa: F401,F403
from .lib_charts import *  # noqa: F401,F403
from .lib_ui import *      # noqa: F401,F403
from .lib_header import *  # noqa: F401,F403
from .lib_tags import *    # noqa: F401,F403
