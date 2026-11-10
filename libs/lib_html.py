"""
libs/lib_html.py — HTML assets for iframe components and page chrome
====================================================================
All app HTML lives under ``02_html/``:

  base.html                 — design-system tokens (Welcome, static HTML helpers)
  catalogue_component.html      — MatLib catalogue flip-card grid/list (JS tab)
  catalogue_component_js2.html  — ECOportal-style catalogue (JavaScript tab)
  ecoportal_component.html  — ECOportal EPD browser (ECOportal JS + Browse tab)
  _iframe_shared.css        — reset prepended into iframe components on load

Legacy / unused snapshots: ``html/_ss/``
"""
from __future__ import annotations

from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = _APP_ROOT / "02_html"
HTML_SS_DIR = HTML_DIR / "_ss"

BASE_HTML = HTML_DIR / "base.html"
CATALOGUE_COMPONENT_HTML = HTML_DIR / "catalogue_component.html"
ECOPORTAL_COMPONENT_HTML = HTML_DIR / "ecoportal_component.html"
IFRAME_SHARED_CSS = HTML_DIR / "_iframe_shared.css"
DESIGN_TOKENS_CSS = HTML_DIR / "_tokens.css"

# Back-compat names used across the codebase
CATALOGUE_COMPONENT_PATH = CATALOGUE_COMPONENT_HTML
CATALOGUE_JS2_COMPONENT_PATH = HTML_DIR / "catalogue_component_js2.html"
CHARTS_SCATTER_EC_POPUP_HTML = HTML_DIR / "charts_scatter_ec_popup.html"
DEV_MISSMATRIX_HTML = HTML_DIR / "developer_missmatrix.html"
CLASSIFICATION_CROSSWALK_HTML = HTML_DIR / "classification_crosswalk.html"
VOC_BODIES_CERTS_HTML = HTML_DIR / "voc_bodies_certs.html"
ECO_BROWSER_TPL = ECOPORTAL_COMPONENT_HTML


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_base_css() -> str:
    """Design tokens for fn337+ HTML renderers."""
    if BASE_HTML.exists():
        return read_text(BASE_HTML)
    return ""


def read_iframe_component(
    path: Path,
    *,
    missing_message: str = "",
) -> str:
    """Load an iframe HTML file and prepend shared CSS after the first ``<style>`` tag."""
    if not path.exists():
        return missing_message or f"<p>HTML component not found: {path.name}</p>"
    # Memoised on the three files' mtimes: the catalogue template alone is ~150 KB
    # read from OneDrive on every Catalogue rerun. Edits still apply on the next run.
    key = (str(path), *(_mtime_ns(p) for p in (path, DESIGN_TOKENS_CSS, IFRAME_SHARED_CSS)))
    hit = _COMPONENT_MEMO.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    html = read_text(path)
    for _css_path in (DESIGN_TOKENS_CSS, IFRAME_SHARED_CSS):
        if _css_path.exists() and "<style>" in html:
            shared = read_text(_css_path).strip()
            if shared and shared not in html:
                html = html.replace("<style>", f"<style>\n{shared}\n", 1)
    _COMPONENT_MEMO[str(path)] = (key, html)
    return html


_COMPONENT_MEMO: dict[str, tuple[tuple, str]] = {}


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
