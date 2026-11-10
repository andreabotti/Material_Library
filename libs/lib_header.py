"""
libs/lib_header.py — EETRA MatLib header module
=================================================
fn001–fn099  Page chrome: headers, CSS injection, Mapbox

  fn001  create_page_header    st.set_page_config (+ optional full masthead)
  fn001b render_app_masthead   Full (Welcome) or compact (all other pages) masthead
  fn003  render_page_header    Title HTML only (prefer fn003a)
  fn003a page_header           Per-page title only (masthead chrome is fn001b)
  fn005  inject_global_css     Inject all global CSS once per run
  fn006  resolve_mapbox        @cache_data Mapbox token + style URL resolver

All visual values come from ``theme.json`` (see libs/lib_tokens.py). Product
naming comes from ``theme.json → brand``. ``fn002_render_welcome`` and
``fn004_render_dev_header`` were removed: nothing called them, and the Welcome
copy inside fn002 still advertised pages that had been folded into other tabs.
"""

from __future__ import annotations
import streamlit as st
import json
import os
import re
from io import BytesIO
import base64
from pathlib import Path
from PIL import Image

from .lib_tokens import (
    token as _design_token,
    font_links_html,
    local_font_face_css,
    serif_heading_css,
    sans_ui_css,
    sidebar_collapsed_control_css,
    sidebar_width_px,
    sidebar_keyboard_shortcut_script,
    chrome_layout_css,
    page_title_css,
    masthead_chrome_css,
    css_hex_to_var,
    tokens_css_text,
    theme_section,
)

_APP_ROOT = Path(__file__).resolve().parent.parent
_BRAND_IMG_DIR = _APP_ROOT / "03_img"

# ── Import constants from lib_ui (no circular dep: lib_header → lib_ui → lib_data) ──
from .lib_ui import (
    CATALOGUE_FONT_SIZE_PX,
    CATALOGUE_LINE_HEIGHT,
    CATALOGUE_TITLE_LINE_HEIGHT,
    CATALOGUE_GWP_LINE_HEIGHT,
    CATALOGUE_CARD_BORDER_WIDTH,
    CATALOGUE_CARD_BORDER_STYLE,
    CATALOGUE_CARD_BORDER_COLOR,
    CATALOGUE_CARD_BORDER_RADIUS,
    CATALOGUE_CARD_BACKGROUND,
    CATALOGUE_CARD_BODY_PADDING_X,
    CATALOGUE_CARD_BODY_PADDING_BOTTOM,
    CATALOGUE_CARD_IMAGE_OBJECT_FIT,
    CATALOGUE_CARD_IMAGE_OBJECT_POSITION,
    CATALOGUE_CARD_IMAGE_ZOOM_ORIGIN,
    CATALOGUE_CARD_HOVER_BOX_SHADOW,
    CATALOGUE_CARD_HOVER_BORDER_COLOR,
    CATALOGUE_STREAMLIT_CARD_MIN_HEIGHT_PX,
    CATALOGUE_STREAMLIT_CARD_MAX_HEIGHT_PX,
    _CATALOGUE_CARD_BLOCK,
    _CATALOGUE_CARD_COLUMN,
    _CATALOGUE_CARD_SURFACE_CLASS,
    _CATALOGUE_OBJECT_FIT_ALLOWED,
    _catalogue_css_sanitize_position,
    _catalogue_image_zoom_scale,
    catalogue_material_band_css_var_declarations,
    catalogue_material_band_important_suffix,
    _VOC_CERT_FOOTER_RASTER_MAX_H,
)


# ════════════════════════════════════════════════════════════════════════════
# fn001  create_page_header
# ════════════════════════════════════════════════════════════════════════════

def _render_header_divider(position: str) -> None:
    """The app's one horizontal rule, rendered above and/or below the masthead.

    Single implementation, called only from here (fn001) — no page renders its
    own copy. Everything is read from ``theme.json → chrome.header_divider``:
    color · thickness · width · alignment · independent on/off and spacing for
    the "above" and "below" positions. ``show`` is a master switch (off hides
    both); ``show_above`` / ``show_below`` control each position independently.
    """
    cfg = theme_section("chrome", "header_divider") or {}
    if not cfg.get("show", True):
        return
    if not cfg.get(f"show_{position}", True):
        return
    color     = cfg.get("color", "var(--border)")
    thickness = cfg.get("thickness", "1px")
    width     = cfg.get("width", "100%")
    align     = str(cfg.get("align", "center")).lower()
    if position == "above":
        mt = cfg.get("margin_above_top", "0px")
        mb = cfg.get("margin_above_bottom", "6px")
    else:
        mt = cfg.get("margin_below_top", "6px")
        mb = cfg.get("margin_below_bottom", "10px")
    ml, mr = {
        "left":  ("0", "auto"),
        "right": ("auto", "0"),
    }.get(align, ("auto", "auto"))  # default: centre
    st.markdown(
        f"<div class='eetra-header-divider' style='height:{thickness};width:{width};"
        f"background:{color};border:none;margin-top:{mt};margin-bottom:{mb};"
        f"margin-left:{ml};margin-right:{mr};'></div>",
        unsafe_allow_html=True,
    )


def brand(key: str, default: str = "") -> str:
    """Read one value from ``theme.json → brand`` (single product-naming source)."""
    cfg = theme_section("brand") or {}
    val = cfg.get(key) if isinstance(cfg, dict) else None
    return str(val) if val not in (None, "") else default


def fn001_create_page_header(show_branding: bool = True):
    """``st.set_page_config`` plus optional full masthead.

    Prefer calling with ``show_branding=False`` early in ``app.py``, then
    ``fn001b_render_app_masthead`` after ``st.navigation`` so Welcome can keep
    the full header while other pages get the compact bar.
    """
    st.set_page_config(
        page_title=brand("browser_tab_title", brand("app_name", "EETRA Material Library")),
        page_icon=str(_BRAND_IMG_DIR / "EETRA_favicon.png"),
        layout="wide",
        initial_sidebar_state=sidebar_width_px(),
    )
    if show_branding:
        fn001b_render_app_masthead(compact=False)


_LOGO_URI_MEMO: dict = {"key": None, "uri": None}


def _logo_data_uri() -> str | None:
    """Base64 PNG data-URI for the EETRA rect logo, or None on failure.

    Memoised on the file's mtime: decoding and re-encoding the PNG cost ~10 ms on
    every run that drew the masthead.
    """
    path = _BRAND_IMG_DIR / "EETRA_logo_rect.png"
    try:
        key = os.stat(path).st_mtime_ns
    except OSError:
        return None
    if _LOGO_URI_MEMO["key"] == key:
        return _LOGO_URI_MEMO["uri"]
    try:
        from .lib_data import _pil_open_safe
        image = _pil_open_safe(str(path))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:
        return None
    _LOGO_URI_MEMO.update(key=key, uri=uri)
    return uri


def _render_masthead_full() -> None:
    """Original Welcome masthead: logo + title + tagline/credit + dividers."""
    st.markdown(
        '<div class="eetra-masthead-chrome" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    _render_header_divider("above")

    top_col1, spacing, top_col2 = st.columns([18, 1, 200])

    with top_col2:
        st.write("")
        _credit_url = brand("credit_url")
        _credit_label = brand("credit_label")
        _credit = (
            f' [ Developed by <a href="{_esc(_credit_url)}" target="_blank">{_esc(_credit_label)}</a> ]'
            if _credit_url and _credit_label else ""
        )
        st.markdown(
            f"""
            <div class="eetra-header-branding">
                <h2 class="custom-title">{_esc(brand("masthead_title", "Material Library"))}</h2>
                <p class="custom-caption">{_esc(brand("tagline"))}{_credit}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_col1:
        img_uri = _logo_data_uri()
        if img_uri:
            st.markdown(
                f'<div class="eetra-header-logo">'
                f'<img src="{img_uri}" style="width:100%; height:auto;" alt="EETRA" />'
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.warning("Logo could not be loaded.")

    _render_header_divider("below")
    st.markdown(
        '<div class="eetra-masthead-below" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )


def _render_masthead_compact() -> None:
    """Compact bar for non-Welcome pages: logo + title only, primary fill, white title.

    Critical look (green fill, white title, logo size) is applied inline so the
    bar stays visible even if the global %-formatted stylesheet mis-parses.
    """
    from .lib_tokens import css_color_with_opacity, theme_section, token

    title = brand("masthead_title", "Material Library")
    mc = theme_section("chrome", "masthead_compact") or {}
    ct = theme_section("chrome", "custom_title") or {}
    layout = theme_section("chrome", "layout") or {}
    bg = css_color_with_opacity(
        mc.get("background", ct.get("color", token("colors", "green"))),
        mc.get("background_opacity", 1),
    )
    title_color = mc.get("title_color", "#ffffff")
    content_h = mc.get("content_height", mc.get("logo_height", "22px"))
    logo_h = mc.get("logo_height", content_h)
    pad_y = mc.get("padding_y", "0.4rem")
    pad_x = mc.get(
        "padding_x",
        layout.get("content_inset_x", layout.get("main_padding_left", "1rem")),
    )
    gap = mc.get("gap", "0.65rem")
    compact_mt = mc.get("margin_top", "3.25rem")
    compact_mb = mc.get("margin_bottom", "0.75rem")
    bleed_l = layout.get("main_padding_left", "1rem")
    bleed_r = layout.get("main_padding_right", "1rem")
    title_fs = mc.get("title_font_size")
    if not title_fs:
        scale = float(mc.get("scale", 0.6))
        base_title_fs = mc.get("base_title_font_size", "1.75rem")
        try:
            if str(base_title_fs).endswith("rem"):
                title_fs = f"{float(str(base_title_fs).replace('rem', '').strip()) * scale:.3f}rem"
            else:
                title_fs = "1.25rem"
        except (TypeError, ValueError):
            title_fs = "1.25rem"
    logo_filter = mc.get("logo_filter", "brightness(0) invert(1)")

    img_uri = _logo_data_uri()
    logo_html = (
        f'<img class="eetra-masthead-compact-logo" src="{img_uri}" alt="EETRA" '
        f'style="height:{logo_h};width:auto;display:block;flex-shrink:0;filter:{logo_filter};" />'
        if img_uri
        else ""
    )
    html = (
        f'<div class="eetra-masthead-compact" style="'
        f"background:{bg};color:{title_color};"
        f"margin:{compact_mt} -{bleed_l} {compact_mb} -{bleed_r};"
        f"padding:{pad_y} {pad_x};box-sizing:border-box;"
        f"width:calc(100% + {bleed_l} + {bleed_r});"
        f'">'
        f'<div class="eetra-masthead-compact-row" style="'
        f"display:flex;align-items:center;gap:{gap};min-height:{content_h};"
        f'">'
        f"{logo_html}"
        f'<h2 class="eetra-masthead-compact-title" style="'
        f"margin:0;padding:0;font-size:{title_fs};line-height:{content_h};"
        f"height:{content_h};display:flex;align-items:center;color:{title_color};"
        f'">{_esc(title)}</h2>'
        f"</div></div>"
    )
    try:
        st.html(html)
    except Exception:
        st.markdown(html, unsafe_allow_html=True)


def fn001b_render_app_masthead(*, compact: bool = False) -> None:
    """Render the app masthead — full on Welcome; compact parked (not shown).

    Compact is kept in code/theme (``chrome.masthead_compact``) but gated off via
    ``enabled: false`` so we can revive it later without re-implementing.
    """
    from .lib_tokens import theme_section

    if compact:
        mc = theme_section("chrome", "masthead_compact") or {}
        if mc.get("enabled", False):
            _render_masthead_compact()
        else:
            # Still clear the sticky top nav so page titles are not hidden under it.
            st.markdown(
                '<div class="eetra-masthead-clearance" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
        return
    _render_masthead_full()


# ════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ════════════════════════════════════════════════════════════════════════════

def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ════════════════════════════════════════════════════════════════════════════
# fn003  render_page_header
# ════════════════════════════════════════════════════════════════════════════

def _subtitle_tooltip_html(subtitle: str) -> str:
    """Inline (i) control with hover/focus tooltip — replaces visible subtitle line."""
    return (
        f'<span class="eetra-page-subtitle-tip" tabindex="0" aria-label="{_esc(subtitle)}">'
        f'<span class="eetra-page-subtitle-tip-icon" aria-hidden="true">i</span>'
        f'<span class="eetra-page-subtitle-tip-bubble" role="tooltip">{_esc(subtitle)}</span>'
        f"</span>"
    )


def fn003_render_page_header(
    title: str,
    subtitle: str = "",
    *,
    icon: str = "",
    embedded: bool | None = None,
    subtitle_tooltip: bool = True,
) -> str:
    """HTML for the per-page title only (no masthead divider).

    Style lives in ``theme.json → chrome.page_title``. Prefer ``fn003a_page_header``.
    """
    if embedded is None:
        try:
            from .lib_ui import fn352_is_embedded_page

            embedded = fn352_is_embedded_page()
        except Exception:
            embedded = False
    # Translated here rather than at the ~15 call sites, so pages keep passing
    # the English string and only aux_16 knows about the other language.
    try:
        from .lib_i18n import fn711_t_page, fn712_t_subtitle

        title = fn711_t_page(title)
        subtitle = fn712_t_subtitle(subtitle)
    except Exception:
        pass
    cls = "eetra-page-title-wrap eetra-page-title-wrap--embedded" if embedded else "eetra-page-title-wrap"
    label = f"{icon} {title}".strip() if icon else title
    if subtitle and subtitle_tooltip:
        title_html = (
            f'<span class="eetra-page-title-text">{_esc(label)}</span>'
            f"{_subtitle_tooltip_html(subtitle)}"
        )
        sub_html = ""
    else:
        title_html = _esc(label)
        sub_html = (
            f'<p class="eetra-page-subtitle">{_esc(subtitle)}</p>' if subtitle else ""
        )
    return (
        f'<div class="{cls}">'
        f'<h3 class="eetra-page-title">{title_html}</h3>'
        f"{sub_html}"
        f"</div>"
    )


def fn003a_page_header(
    title: str,
    subtitle: str = "",
    *,
    icon: str = "",
    embedded: bool | None = None,
    subtitle_tooltip: bool = True,
) -> None:
    """Render the per-page title (Catalogue, Charts, …) — not the app masthead.

    Masthead chrome (full Welcome / compact elsewhere) is owned by
    ``fn001b_render_app_masthead``.
    """
    st.markdown(
        fn003_render_page_header(
            title, subtitle, icon=icon, embedded=embedded, subtitle_tooltip=subtitle_tooltip,
        ),
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# fn005  inject_global_css
# ════════════════════════════════════════════════════════════════════════════

_GLOBAL_CSS_SOURCES = (
    _APP_ROOT / "theme.json",
    _APP_ROOT / "aux_01__catalogue_layout.json",
    _APP_ROOT / "aux_03__design_tokens.json",
)
_GLOBAL_CSS_MEMO: dict = {"key": None, "html": ""}


def _mtime_ns_or_zero(path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def _css_source_key(path) -> tuple[int, int]:
    """mtime + size so OneDrive-stale mtimes still rebuild the stylesheet."""
    try:
        info = os.stat(path)
        return (int(info.st_mtime_ns), int(info.st_size))
    except OSError:
        return (0, 0)


def _fn005_build_global_css() -> str:
    """The global ``<style>`` block (see fn005_inject_global_css)."""
    _ct = theme_section("chrome", "custom_title") or {}
    _cc = theme_section("chrome", "custom_caption") or {}
    _co2 = theme_section("chrome", "co2_value") or {}
    _hb = theme_section("chrome", "header_branding") or {}
    _hl = theme_section("chrome", "header_logo") or {}
    _green = _design_token("colors", "green")

    css = (
        local_font_face_css()
        + " "
        + chrome_layout_css()
        + " "
        + serif_heading_css()
        + " "
        + sans_ui_css()
        + " "
        + sidebar_collapsed_control_css()
        + " "
        + page_title_css()
        + " "
        + masthead_chrome_css()
        + " "
        f"h2.custom-title, .custom-title {{ color: {_ct.get('color', _green)}; }} "
        f"h2.custom-title {{ margin: {_ct.get('margin', '0 0 -20px 0')} !important; "
        f"padding: {_ct.get('padding', '0')} !important; line-height: {_ct.get('line_height', '1.15')} !important; }} "
        f".custom-caption {{ font-size: {_cc.get('font_size', '0.8rem')}; color: {_cc.get('color', 'gray')}; "
        f"margin: {_cc.get('margin', '0')} !important; padding: {_cc.get('padding', '15px 0 2px 0')} !important; "
        f"line-height: {_cc.get('line_height', '1.35')} !important; }} "
        f".eetra-header-branding {{ margin: 0 !important; margin-bottom: {_hb.get('margin_bottom', '0')} !important; "
        f"padding-bottom: {_hb.get('padding_bottom', '5px')} !important; padding-top: {_hb.get('padding_top', '38px')} !important; }} "
        f".eetra-header-logo {{ margin: {_hl.get('margin', '60px 0 4px 0')} !important; padding: {_hl.get('padding', '0')} !important; }} "
        f".co2-value {{ font-weight: {_co2.get('font_weight', '600')}; font-size: {_co2.get('font_size', '16px')}; "
        f"color: {_co2.get('color', _green)}; margin: {_co2.get('margin', '0 0 8px 0')}; padding: {_co2.get('padding', '0')}; }} "
        f".co2-value span {{ font-weight: {_co2.get('font_weight', '600')}; font-size: {_co2.get('font_size', '16px')}; "
        f"margin: 0; padding: {_co2.get('span_padding', '1px 3px')}; }} "
        ".material-symbols-rounded, .material-symbols-outlined, [class*=material-symbols] { "
        "font-family: Material\\ Symbols\\ Rounded !important; font-weight: normal !important; "
        "font-style: normal !important; letter-spacing: normal !important; "
        "text-transform: none !important; display: inline-block; white-space: nowrap; "
        "word-wrap: normal; direction: ltr; -webkit-font-feature-settings: liga; "
        "-webkit-font-smoothing: antialiased; } "
        ".material-icons, [class*=material-icons] { "
        "font-family: Material\\ Icons !important; font-weight: normal !important; "
        "font-style: normal !important; letter-spacing: normal !important; "
        "text-transform: none !important; display: inline-block; white-space: nowrap; "
        "word-wrap: normal; direction: ltr; -webkit-font-feature-settings: liga; "
        "-webkit-font-smoothing: antialiased; } "
        ".product-title { font-size: 16px; font-weight: 600; line-height: %(cat_title_line_height)s; } "
        ".product-details { font-size: %(cat_font_px)spx; line-height: %(cat_line_height)s; } "
        ".brand { font-size: %(cat_font_px)spx; line-height: %(cat_line_height)s; color: #666; } "
        "div[data-testid=stMarkdownContainer] img.eetra-voc-cert-badge { "
        f"height: {_VOC_CERT_FOOTER_RASTER_MAX_H}px !important; width: auto !important; "
        f"max-width: {_VOC_CERT_FOOTER_RASTER_MAX_H * 6}px !important; "
        "min-height: 24px !important; object-fit: contain !important; "
        "display: inline-block !important; vertical-align: middle !important; "
        "margin: 0 4px 0 0 !important; "
        "} "
        "[data-testid=stImage], .stImage { width: 100%% !important; max-width: 100%% !important; } "
        # Do not use height:auto for fn329 cards (same column block has .product-title); fixed height is in catalogue_card_css.
        "div[data-testid=stAppViewContainer] [data-testid=stMain] div[data-testid=stVerticalBlock]:not(:has(.product-title)) .stImage img { "
        "width: 100%% !important; height: auto !important; border: none !important; border-radius: 0 !important; } "
        ".hr-line { margin-top: -5px; margin-bottom: -10px; padding: 0; height: 1px; border: none; background-color: #ccc; } "
        # ── Active-filters strip (fn355_render_active_filters) ────────────────
        ".eetra-filterbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; "
        "padding: 2px 0 4px; min-height: 1.9rem; } "
        ".eetra-filterbar-label { font-size: 10px; font-weight: 600; letter-spacing: .06em; "
        "text-transform: uppercase; color: #94a3b8; margin-right: 2px; } "
        ".eetra-filterbar-none { font-size: 12px; color: #94a3b8; } "
        ".eetra-filter-chip { display: inline-flex; align-items: center; gap: 5px; "
        "padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; "
        "background: #e8f5e9; color: #2a7d2e; border: 1px solid #86efac; } "
        ".eetra-filter-chip-key { font-weight: 500; color: #64748b; text-transform: uppercase; "
        "font-size: 9px; letter-spacing: .05em; } "
        ".hr-line-compact { margin-top: -5px; margin-bottom: -5px; } "
        # ── Catalogue CSS-tab system ──────────────────────────────────────────
        ".cat-panel-grid { display: grid; } "
        # Hidden radio inputs used as no-JS tab state
        "input[id^='ctc'],input[id^='cte'] { display:none !important; } "
        # Default state: compact panel visible, extended hidden
        ".cat-cpanel { visibility:visible; pointer-events:auto; } "
        ".cat-epanel { visibility:hidden;  pointer-events:none; } "
        # Tab bar layout
        ".cat-tab-bar { display:flex; border-top:1px solid #e5e7eb; flex-shrink:0; margin-top:auto; } "
        ".cat-tab-c, .cat-tab-e { "
        "flex:1; text-align:center; padding:4px 2px; font-size:10px; font-weight:600; "
        "letter-spacing:0.03em; cursor:pointer; line-height:1.3; "
        "border-top:1px solid #e5e7eb; transition:background .12s,color .12s; } "
        # Default active state = Compact tab highlighted
        ".cat-tab-c { background:#fff; color:#111; border-top:2px solid #2a7d2e; } "
        ".cat-tab-e { background:#f9fafb; color:#6b7280; } "
        ".cat-tab-c:hover, .cat-tab-e:hover { background:#f3f4f6; color:#374151; } "
        # ── ECOportal page ────────────────────────────────────────────────────
        ".eco-metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;text-align:center;} "
        ".eco-metric .val{font-size:1.6rem;font-weight:700;color:#1e293b;line-height:1.1;} "
        ".eco-metric .lbl{font-size:0.72rem;color:#64748b;margin-top:3px;text-transform:uppercase;letter-spacing:0.05em;} "
        ".log-box{background:#0d1117;border:1px solid #21262d;border-radius:6px;"
        "font-family:'JetBrains Mono','Fira Code',monospace;font-size:0.72rem;color:#8b949e;"
        "padding:12px 16px;height:300px;overflow-y:auto;white-space:pre-wrap;line-height:1.55;} "
        ".eco-badge{display:inline-block;border-radius:10px;padding:2px 9px;font-size:0.7rem;font-weight:600;margin-right:4px;} "
        ".eco-badge-green{background:#dcfce7;color:#16a34a;border:1px solid #86efac;} "
        ".eco-badge-orange{background:#fff7ed;color:#ea580c;border:1px solid #fdba74;} "
        ".eco-badge-red{background:#fef2f2;color:#dc2626;border:1px solid #fca5a5;} "
        ".eco-badge-grey{background:#f1f5f9;color:#64748b;border:1px solid #cbd5e1;} "
        ".eco-badge-blue{background:#eff6ff;color:#2563eb;border:1px solid #93c5fd;} "
        ".type-row{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:0.82rem;} "
        ".type-label{width:110px;color:#64748b;font-family:monospace;} "
        ".type-bar-wrap{flex:1;background:#e2e8f0;border-radius:3px;height:6px;} "
        ".type-bar{background:#16a34a;border-radius:3px;height:6px;} "
        ".type-count{color:#1e293b;width:70px;text-align:right;font-size:0.75rem;} "
        # ── Revalu Matching page ──────────────────────────────────────────────
        # (This block used to redeclare --eetra-green, --revalu-*, --neutral-* and
        #  --status-* as literals — a third parallel token set. They are now
        #  emitted from theme.json as aliases; see lib_tokens._ALIAS_MAP.)
        ".revalu-banner{background:linear-gradient(135deg,var(--revalu-navy) 0%%,#1a3a6b 50%%,var(--eetra-green) 100%%);"
        "border-radius:12px;padding:20px 28px;margin-bottom:18px;"
        "display:flex;align-items:center;justify-content:space-between;gap:20px;} "
        ".revalu-banner h2{color:white;font-size:1.3rem;font-weight:700;margin:0 0 4px 0;letter-spacing:-0.02em;} "
        ".revalu-banner p{color:rgba(255,255,255,0.75);font-size:0.82rem;margin:0;line-height:1.5;} "
        ".revalu-badge{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);"
        "border-radius:8px;padding:8px 16px;color:white;font-size:0.78rem;font-weight:600;"
        "letter-spacing:0.05em;text-transform:uppercase;white-space:nowrap;} "
        ".status-pill{display:inline-block;padding:2px 10px;border-radius:999px;"
        "font-size:0.72rem;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;} "
        ".status-linked{background:#dcfce7;color:var(--status-ok);} "
        ".status-number{background:#fef9c3;color:#854d0e;} "
        ".status-missing{background:#fee2e2;color:var(--status-miss);} "
        ".status-expired{background:#f3e8ff;color:var(--status-expd);} "
        ".reg-links{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;} "
        ".reg-link{display:inline-block;padding:4px 11px;border-radius:6px;font-size:0.75rem;"
        "font-weight:600;text-decoration:none;border:1px solid;transition:background 0.15s;} "
        ".reg-epdi{background:#e0f2fe;color:#0369a1;border-color:#bae6fd;} "
        ".reg-italy{background:#dcfce7;color:#166534;border-color:#bbf7d0;} "
        ".reg-ibu{background:#f0fdf4;color:#15803d;border-color:#d1fae5;} "
        ".reg-inies{background:#fff7ed;color:#c2410c;border-color:#fed7aa;} "
        ".reg-revalu{background:#f5f3ff;color:#5b21b6;border-color:#ddd6fe;} "
        ".reg-open{background:#f0f9ff;color:#0c4a6e;border-color:#bae6fd;} "
        ".metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px;} "
        ".metric-box{background:var(--neutral-50);border:1px solid var(--neutral-200);"
        "border-radius:10px;padding:14px 18px;text-align:center;} "
        ".metric-box .num{font-size:2rem;font-weight:800;line-height:1;color:var(--neutral-800);} "
        ".metric-box .lbl{font-size:0.72rem;color:var(--neutral-500);text-transform:uppercase;"
        "letter-spacing:0.05em;margin-top:4px;} "
        ".metric-box.ok .num{color:var(--status-ok);} "
        ".metric-box.warn .num{color:var(--status-warn);} "
        ".metric-box.miss .num{color:var(--status-miss);} "
        ".metric-box.expd .num{color:var(--status-expd);} "
        ".epd-row{border:1px solid var(--neutral-200);border-radius:10px;padding:14px 18px;"
        "margin-bottom:8px;background:white;} "
        ".epd-row:hover{border-color:var(--revalu-teal);box-shadow:0 2px 12px rgba(0,180,216,0.08);} "
        ".epd-row-header{display:flex;align-items:flex-start;justify-content:space-between;"
        "gap:12px;margin-bottom:8px;} "
        ".epd-product-name{font-weight:700;font-size:0.9rem;color:var(--neutral-800);line-height:1.3;} "
        ".epd-manufacturer{font-size:0.78rem;color:var(--neutral-500);margin-top:2px;} "
        ".epd-reg-number{font-family:'SF Mono','Cascadia Code',monospace;font-size:0.8rem;"
        "color:var(--revalu-navy);background:#f1f5f9;padding:3px 8px;border-radius:5px;white-space:nowrap;} "
    )

    _hover_block = ""
    if str(CATALOGUE_CARD_HOVER_BOX_SHADOW or "").strip():
        _hover_block = (
            f"{_CATALOGUE_CARD_BLOCK}:hover {{ "
            f"box-shadow: {CATALOGUE_CARD_HOVER_BOX_SHADOW}; border-color: {CATALOGUE_CARD_HOVER_BORDER_COLOR}; "
            "} "
        )

    try:
        _card_min = max(0, int(CATALOGUE_STREAMLIT_CARD_MIN_HEIGHT_PX))
    except (TypeError, ValueError):
        _card_min = 0
    try:
        _card_max = max(0, int(CATALOGUE_STREAMLIT_CARD_MAX_HEIGHT_PX))
    except (TypeError, ValueError):
        _card_max = 0
    if _card_min > 0:
        _vb_fill_rule = f"height: auto !important; min-height: {_card_min}px !important; "
    else:
        _vb_fill_rule = "height: 100%% !important; min-height: 0 !important; "
    if _card_max > 0:
        _vb_fill_rule += f"max-height: {_card_max}px !important; "

    _mb_imp = catalogue_material_band_important_suffix()
    _mat_root = ":root{" + catalogue_material_band_css_var_declarations() + "}"
    catalogue_card_css = (
        _mat_root
        + f"{_CATALOGUE_CARD_BLOCK} {{ "
        # Longhands, not the `border` / `background` shorthands: once a shorthand
        # contains var() the whole declaration becomes pending-substitution, and
        # the colour component was resolving to currentColor (dark text blue)
        # instead of the card border token. Longhands substitute reliably.
        f"border-width: {CATALOGUE_CARD_BORDER_WIDTH}; "
        f"border-style: {CATALOGUE_CARD_BORDER_STYLE}; "
        f"border-color: {CATALOGUE_CARD_BORDER_COLOR}; "
        f"border-radius: {CATALOGUE_CARD_BORDER_RADIUS}; "
        f"background-color: {CATALOGUE_CARD_BACKGROUND}; "
        "display: flex !important; flex-direction: column !important; "
        "box-sizing: border-box !important; flex: 1 1 auto !important; "
        f"{_vb_fill_rule}"
        "overflow: hidden !important; "
        "transition: box-shadow 0.15s ease, border-color 0.15s ease; "
        "} "
        + _hover_block
    )
    catalogue_card_css += (
        f"{_CATALOGUE_CARD_BLOCK} .brand, {_CATALOGUE_CARD_BLOCK} .product-title {{ "
        f"padding-left: {CATALOGUE_CARD_BODY_PADDING_X}; padding-right: {CATALOGUE_CARD_BODY_PADDING_X}; "
        "display: block; box-sizing: border-box !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .product-details {{ "
        f"padding-left: {CATALOGUE_CARD_BODY_PADDING_X}; padding-right: {CATALOGUE_CARD_BODY_PADDING_X}; "
        f"padding-bottom: {CATALOGUE_CARD_BODY_PADDING_BOTTOM}; "
        "box-sizing: border-box !important; flex: 1 1 auto !important; min-height: 0 !important; overflow-y: auto !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .product-details img.eetra-voc-cert-badge, "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-voc-cert-badge {{ "
        f"height: {_VOC_CERT_FOOTER_RASTER_MAX_H}px !important; width: auto !important; "
        f"max-width: {_VOC_CERT_FOOTER_RASTER_MAX_H * 6}px !important; "
        "min-height: 24px !important; max-height: 56px !important; object-fit: contain !important; "
        "display: inline-block !important; vertical-align: middle !important; "
        "margin: 0 4px 0 0 !important; flex: 0 0 auto !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-voc-cert-footer {{ "
        "display: flex !important; flex-wrap: wrap !important; align-items: center !important; "
        "justify-content: center !important; gap: 6px !important; "
        "padding: 2px 8px !important; margin: 0 !important; flex-shrink: 0 !important; "
        "width: 100% !important; box-sizing: border-box !important; "
        "border: none !important; background: transparent !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-voc-cert-footer img.eetra-voc-cert-badge, "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-voc-cert-footer .eetra-voc-cert-badge--footer {{ "
        f"height: {_VOC_CERT_FOOTER_RASTER_MAX_H}px !important; width: auto !important; "
        f"max-width: {_VOC_CERT_FOOTER_RASTER_MAX_H * 6}px !important; "
        "min-height: 24px !important; max-height: 56px !important; object-fit: contain !important; "
        "display: inline-block !important; vertical-align: middle !important; margin: 0 !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-cat-img-band {{ "
        "position: relative !important; box-sizing: border-box !important; flex-shrink: 0 !important; "
        "} "
        f"{_CATALOGUE_CARD_BLOCK} .eetra-cat-material-band, "
        f"{_CATALOGUE_CARD_COLUMN} .eetra-cat-material-band, "
        f"div[data-testid=stMarkdownContainer] .eetra-cat-material-band {{ "
        f"position: var(--cat-mat-position){_mb_imp};"
        f"top: var(--cat-mat-top){_mb_imp};"
        f"bottom: var(--cat-mat-bottom){_mb_imp};"
        f"left: var(--cat-mat-left){_mb_imp};"
        f"z-index: var(--cat-mat-z){_mb_imp};"
        f"max-width: var(--cat-mat-maxw){_mb_imp};"
        f"background-color: var(--cat-mat-bg){_mb_imp};"
        f"color: var(--cat-mat-color){_mb_imp};"
        f"font-size: var(--cat-mat-fs){_mb_imp};"
        f"font-style: var(--cat-mat-style){_mb_imp};"
        f"font-weight: var(--cat-mat-weight){_mb_imp};"
        f"line-height: var(--cat-mat-lh){_mb_imp};"
        f"padding: var(--cat-mat-pad){_mb_imp};"
        f"margin: var(--cat-mat-margin){_mb_imp};"
        f"border-radius: var(--cat-mat-radius){_mb_imp};"
        f"pointer-events: var(--cat-mat-pe){_mb_imp};"
        f"white-space: var(--cat-mat-ws){_mb_imp};"
        f"overflow: var(--cat-mat-ov){_mb_imp};"
        f"text-overflow: var(--cat-mat-to){_mb_imp};"
        f"box-sizing: var(--cat-mat-box){_mb_imp};"
        f"font-family: var(--cat-mat-ff){_mb_imp};"
        "} "
    )
    _rad_b = str(CATALOGUE_CARD_BORDER_RADIUS).strip()
    # When CATALOGUE_CARD_IMAGE_HEIGHT_PX==0, fn329 uses st.image; rules below target that widget only.
    _fit = str(CATALOGUE_CARD_IMAGE_OBJECT_FIT or "contain").strip().lower()
    if _fit not in _CATALOGUE_OBJECT_FIT_ALLOWED:
        _fit = "contain"
    _obj_pos = _catalogue_css_sanitize_position(str(CATALOGUE_CARD_IMAGE_OBJECT_POSITION or "center"))
    _z_origin = _catalogue_css_sanitize_position(str(CATALOGUE_CARD_IMAGE_ZOOM_ORIGIN or "center center"))
    _z_scale = _catalogue_image_zoom_scale()
    catalogue_card_css += (
        f"{_CATALOGUE_CARD_COLUMN} .stImage img, "
        f"{_CATALOGUE_CARD_COLUMN} [data-testid=stImage] img {{ "
        "width: 100%% !important; height: 100%% !important; max-width: none !important; max-height: none !important; "
        "border: none !important; border-radius: 0 !important; display: block !important; "
        "margin: 0 auto !important; object-fit: %s !important; object-position: %s !important; "
        "transform: scale(%s) !important; transform-origin: %s !important; "
        "} "
    ) % (_fit, _obj_pos, _z_scale, _z_origin)
    _cat_actions = f"{_CATALOGUE_CARD_COLUMN} div[data-testid=stHorizontalBlock]:has(button)"
    catalogue_card_css += (
        f"{_cat_actions} {{ "
        "flex-shrink: 0 !important; gap: 0 !important; margin: 0 !important; margin-top: auto !important; "
        "padding: 0 !important; width: 100%% !important; box-sizing: border-box !important; "
        "}} "
        f"{_cat_actions} > div[data-testid=stColumn] {{ "
        "padding: 0 !important; margin: 0 !important; min-height: 0 !important; "
        "}} "
        f"{_cat_actions} .stButton {{ margin: 0 !important; width: 100%% !important; }} "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(1) .stButton > button {{ "
        "font-size: 10px !important; font-weight: 600 !important; letter-spacing: 0.02em !important; "
        "padding: 5px 8px !important; min-height: 0 !important; height: auto !important; line-height: 1.2 !important; "
        "border: none !important; border-top: 1px solid #d1d5db !important; "
        "border-right: 1px solid #d1d5db !important; border-radius: 0 0 0 {_rad_b} !important; "
        "background: #f3f4f6 !important; color: #374151 !important; "
        "box-shadow: none !important; background-image: none !important; "
        "}} "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(1) .stButton > button:hover {{ "
        "background: #e5e7eb !important; border-color: #9ca3af !important; color: #1f2937 !important; "
        "}} "
        f"{_cat_actions} > div[data-testid=stColumn]:only-child .stButton > button {{ "
        f"border-right: none !important; border-radius: 0 0 {_rad_b} {_rad_b} !important; "
        "}} "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) .stButton > button, "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) .stButton > a, "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) a[href] {{ "
        "font-size: 10px !important; font-weight: 600 !important; letter-spacing: 0.02em !important; "
        "padding: 5px 8px !important; min-height: 0 !important; height: auto !important; line-height: 1.2 !important; "
        "border: none !important; border-top: 1px solid #e0b878 !important; "
        f"border-radius: 0 0 {_rad_b} 0 !important; "
        "background: linear-gradient(180deg,#fff6e8 0%,#ffe8cc 100%) !important; color: #6a3d00 !important; "
        "box-shadow: none !important; "
        "text-decoration: none !important; display: inline-flex !important; align-items: center !important; "
        "justify-content: center !important; width: 100% !important; box-sizing: border-box !important; "
        "}} "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) .stButton > a:hover, "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) .stButton > button:hover, "
        f"{_cat_actions} > div[data-testid=stColumn]:nth-child(2) a[href]:hover {{ "
        "filter: brightness(0.97); border-color: #cc9a3c !important; color: #4a2800 !important; "
        "}} "
    )

    css_filled  = css % {
        "cat_font_px":          CATALOGUE_FONT_SIZE_PX,
        "cat_line_height":      CATALOGUE_LINE_HEIGHT,
        "cat_title_line_height": CATALOGUE_TITLE_LINE_HEIGHT,
    }
    css_filled  = css_filled + catalogue_card_css
    # Re-point EVERY hex literal that theme.json defines at its CSS variable, so
    # Streamlit chrome, page CSS and iframe components share one palette and a
    # colour change in theme.json needs no code edit. Colours with no token
    # (one-off gradients etc.) are left as they are.
    css_filled  = css_hex_to_var(css_filled)
    return "<style>" + css_filled + "</style>"


def fn005_inject_global_css(force: bool = False):
    """Inject all global CSS. Called in app.py BEFORE ``pg.run()``.

    Guarded so it runs **once per script run**: pages used to re-inject the same
    ~20 KB stylesheet defensively (Catalogue did), which duplicated every rule in
    the document. Pass ``force=True`` only if a page genuinely changed a value
    that feeds this CSS mid-run.
    """
    try:
        from .lib_ui import fn351_once_per_run

        if not force and not fn351_once_per_run("global_css"):
            return
    except Exception:
        pass

    st.markdown(font_links_html(), unsafe_allow_html=True)
    # Design tokens (theme.json → _tokens.css) must exist in the MAIN document,
    # not only inside iframes, so page-level CSS can use var(--eetra-*).
    _tokens = tokens_css_text().strip()
    if _tokens:
        st.html(f"<style>{_tokens}</style>")

    # The stylesheet is a pure function of the JSON files below (module constants
    # such as CATALOGUE_* are themselves loaded from them), so the ~30 KB string
    # is built once per file version instead of on every run.
    _key = tuple(_css_source_key(p) for p in _GLOBAL_CSS_SOURCES)
    if _GLOBAL_CSS_MEMO["key"] != _key:
        _GLOBAL_CSS_MEMO["html"] = _fn005_build_global_css()
        _GLOBAL_CSS_MEMO["key"] = _key
    full_html = _GLOBAL_CSS_MEMO["html"]
    try:
        st.html(full_html)
    except Exception:
        st.markdown(full_html, unsafe_allow_html=True)

    _shortcut = sidebar_keyboard_shortcut_script()
    if _shortcut:
        try:
            from .lib_ui import fn351_once_per_run

            if fn351_once_per_run("sidebar_keyboard_shortcut"):
                st.html(_shortcut, unsafe_allow_javascript=True)
        except TypeError:
            # Older Streamlit without unsafe_allow_javascript.
            try:
                st.html(_shortcut)
            except Exception:
                pass
        except Exception:
            try:
                st.html(_shortcut, unsafe_allow_javascript=True)
            except TypeError:
                st.html(_shortcut)


# ════════════════════════════════════════════════════════════════════════════
# fn006  resolve_mapbox
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fn006_resolve_mapbox() -> tuple:
    """Return (token, style_url). Falls back gracefully when token is absent."""
    token = None
    try:
        token = st.secrets.get("mapbox", {}).get("token")
    except Exception:
        pass
    if not token:
        token = os.environ.get("MAPBOX_API_KEY") or os.environ.get("MAPBOX_ACCESS_TOKEN")
    return token, "mapbox://styles/mapbox/light-v11"
