"""
libs/lib_tokens.py — theme.json bridge
======================================
Loads ``theme.json`` (single source of truth for all visual settings) so Python
CSS builders and iframe components share the same tokens.

Usage:
    from libs.lib_tokens import token, theme_section, font_links_html
    green = token("colors", "green")
    charts = theme_section("catalogue", "charts")
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
_THEME_PATH = _APP_ROOT / "theme.json"
_TOKENS_CSS_PATH = _APP_ROOT / "02_html" / "_tokens.css"
_STREAMLIT_CONFIG_PATH = _APP_ROOT / ".streamlit" / "config.toml"
_MEMO: dict = {"mtime": None, "theme": {}}

# ── Legacy alias names ───────────────────────────────────────────────────────
# ``02_html/base.html`` and the iframe components were written against a second,
# hand-maintained token set (--green, --surface, --radius, …) that had already
# drifted from theme.json (e.g. --info was #0284c7 vs colors.info #185FA5).
# Rather than rewrite every consumer, ``sync_tokens_css`` now emits these names
# as aliases of the theme.json values, so there is exactly one source of truth.
# (group, name) → list of legacy CSS custom-property names.
_ALIAS_MAP: list[tuple[tuple[str, str], tuple[str, ...]]] = [
    (("colors", "surface"),       ("--bg",)),
    (("colors", "surface_alt"),   ("--surface",)),
    (("colors", "surface_alt2"),  ("--surface2", "--chip-bg")),
    (("colors", "green_light"),   ("--surface3", "--green-light")),
    (("colors", "border"),        ("--border",)),
    (("colors", "border_strong"), ("--border2",)),
    (("colors", "text"),          ("--text",)),
    (("colors", "text_muted"),    ("--text2",)),
    (("colors", "text_faint"),    ("--text3",)),
    (("colors", "green"),         ("--green",)),
    (("colors", "green_mid"),     ("--green-mid",)),
    (("colors", "ok"),            ("--ok",)),
    (("colors", "warn"),          ("--warn",)),
    (("colors", "error"),         ("--error",)),
    (("colors", "info"),          ("--info",)),
    (("colors", "chip_text"),     ("--chip-text",)),
    (("shadows", "sm"),           ("--shadow-sm",)),
    (("shadows", "md"),           ("--shadow",)),
    (("shadows", "lg"),           ("--shadow-lg",)),
    (("borders", "radius_sm"),    ("--radius-sm",)),
    (("borders", "radius_md"),    ("--radius",)),
    (("borders", "radius_card"),  ("--radius-lg",)),
    (("typography", "font_sans"), ("--font",)),
    (("typography", "font_mono"), ("--font-mono",)),
    (("typography", "font_serif"),("--font-serif",)),
    (("typography", "base_size"), ("--base-size",)),
    # Revalu Matching page + status pills (previously a third inline :root block
    # inside lib_header.fn005).
    (("colors", "surface_alt"),    ("--neutral-50",)),
    (("colors", "border"),         ("--neutral-200",)),
    (("colors", "text_muted"),     ("--neutral-500",)),
    (("colors", "text"),           ("--neutral-800",)),
    (("colors", "ok"),             ("--status-ok",)),
    (("colors", "warn"),           ("--status-warn",)),
    (("colors", "error"),          ("--status-miss",)),
    (("palette", "status_expired"), ("--status-expd",)),
    (("palette", "revalu_navy"),   ("--revalu-navy",)),
    (("palette", "revalu_teal"),   ("--revalu-teal",)),
    (("palette", "revalu_violet"), ("--revalu-violet", "--eetra-p-revalu-violet")),
]

_FALLBACKS = {
    ("colors", "green"): "#2a7d2e",
    ("colors", "border_card"): "#d1d9e6",
    ("colors", "hover_border"): "#b8c5d8",
    ("borders", "radius_card"): "12px",
    ("spacing", "grid_gap"): "12px",
    ("shadows", "hover"): "0 6px 18px rgba(15, 23, 42, 0.08)",
    ("typography", "font_sans"): "'Miranda Sans', 'Source Sans Pro', sans-serif",
    ("typography", "font_serif"): "'Source Serif Pro', Georgia, serif",
}


def load_theme() -> dict:
    """Read theme.json, memoized on file mtime (live edits apply on rerun)."""
    try:
        mtime = _THEME_PATH.stat().st_mtime_ns
        if _MEMO["mtime"] != mtime:
            _MEMO["theme"] = json.loads(_THEME_PATH.read_text(encoding="utf-8"))
            _MEMO["mtime"] = mtime
            _MEMO["hex_vars"] = None
            sync_tokens_css()
            sync_streamlit_config()
    except Exception:
        pass
    return _MEMO["theme"]


def load_design_tokens() -> dict:
    """Back-compat alias: top-level token groups from theme.json."""
    t = load_theme()
    return {k: v for k, v in t.items() if not k.startswith("_") and isinstance(v, dict) and k != "catalogue"}


def theme_section(*keys: str, default=None):
    """Nested lookup, e.g. theme_section('catalogue', 'charts')."""
    node = load_theme()
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def token(group: str, name: str, default: str | None = None) -> str:
    """Return a token value, e.g. token('colors', 'green') -> '#2a7d2e'."""
    val = load_theme().get(group, {}).get(name) if isinstance(load_theme().get(group), dict) else None
    if val is not None and val != "":
        return str(val)
    return default if default is not None else _FALLBACKS.get((group, name), "")


def css_color_with_opacity(color: str, opacity: float | int | str = 1) -> str:
    """Turn ``#rgb`` / ``#rrggbb`` + opacity into ``rgba(...)``; pass other values through.

    Used by compact masthead + top nav so ``background_opacity`` in theme.json is
    a single knob when the green fill feels too strong.
    """
    try:
        op = float(opacity)
    except (TypeError, ValueError):
        op = 1.0
    op = max(0.0, min(1.0, op))
    raw = str(color or "").strip()
    if op >= 0.999:
        return raw or "#2a7d2e"
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", raw)
    if not m:
        return raw or f"rgba(42,125,46,{op:g})"
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{op:g})"


def _css_var_name(group: str, name: str) -> str:
    return f"--eetra-{group.replace('_', '-')}-{name.replace('_', '-')}"


def sync_tokens_css() -> None:
    """Regenerate ``02_html/_tokens.css`` from theme.json when theme changes."""
    theme = _MEMO.get("theme") or {}
    if not theme:
        return
    lines = [
        "/* EETRA MatLib design tokens — auto-generated from theme.json.",
        "   Do not edit by hand; change theme.json and rerun the app. */",
        ":root{",
    ]
    colors = theme.get("colors") or {}
    if isinstance(colors, dict):
        for name, val in colors.items():
            if not name.startswith("_"):
                lines.append(f"  --eetra-{name.replace('_', '-')}:{val};")
    palette = theme.get("palette") or {}
    if isinstance(palette, dict):
        for name, val in palette.items():
            if not name.startswith("_"):
                lines.append(f"  --eetra-p-{name.replace('_', '-')}:{val};")
    typo = theme.get("typography") or {}
    if isinstance(typo, dict):
        for name, val in typo.items():
            if name.startswith("_") or name in ("google_font_links", "local_fonts"):
                continue
            if name.startswith("font_"):
                lines.append(f"  --eetra-ff-{name[5:].replace('_', '-')}:{val};")
    borders = theme.get("borders") or {}
    if isinstance(borders, dict):
        for name, val in borders.items():
            if not name.startswith("_"):
                lines.append(f"  --eetra-{name.replace('_', '-')}:{val};")
    spacing = theme.get("spacing") or {}
    if isinstance(spacing, dict):
        for name, val in spacing.items():
            if not name.startswith("_"):
                lines.append(f"  --eetra-{name.replace('_', '-')}:{val};")
    shadows = theme.get("shadows") or {}
    if isinstance(shadows, dict):
        for name, val in shadows.items():
            if not name.startswith("_"):
                key = name if name == "hover" else name.replace("_", "-")
                lines.append(f"  --eetra-{key}-shadow:{val};" if name != "hover" else f"  --eetra-hover-shadow:{val};")
    lines.append("")
    lines.append("  /* Legacy aliases (02_html/base.html + iframe components). */")
    for (group, name), aliases in _ALIAS_MAP:
        val = (theme.get(group) or {}).get(name) if isinstance(theme.get(group), dict) else None
        if val is None or val == "":
            val = _FALLBACKS.get((group, name))
        if val is None or val == "":
            continue
        for alias in aliases:
            lines.append(f"  {alias}:{val};")
    lines.append("}")
    css_text = "\n".join(lines) + "\n"
    try:
        if not _TOKENS_CSS_PATH.exists() or _TOKENS_CSS_PATH.read_text(encoding="utf-8") != css_text:
            _TOKENS_CSS_PATH.write_text(css_text, encoding="utf-8")
    except Exception:
        pass


def _hex_var_lookup() -> dict[str, str]:
    """``{"#2a7d2e": "var(--eetra-green)", …}`` for every colour token in theme.json.

    Includes 3-digit shorthand for values like ``#ffffff`` / ``#cccccc`` so legacy
    CSS written as ``#fff`` is picked up too. Memoized alongside the theme.
    """
    cached = _MEMO.get("hex_vars")
    if cached is not None:
        return cached
    theme = load_theme()
    out: dict[str, str] = {}

    def _add(value, var_name: str) -> None:
        v = str(value or "").strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", v):
            return
        out.setdefault(v, f"var({var_name})")
        # #aabbcc -> #abc when the pairs repeat
        if v[1] == v[2] and v[3] == v[4] and v[5] == v[6]:
            out.setdefault(f"#{v[1]}{v[3]}{v[5]}", f"var({var_name})")

    for name, val in (theme.get("colors") or {}).items():
        if not str(name).startswith("_"):
            _add(val, f"--eetra-{str(name).replace('_', '-')}")
    for name, val in (theme.get("palette") or {}).items():
        if not str(name).startswith("_"):
            _add(val, f"--eetra-p-{str(name).replace('_', '-')}")
    _MEMO["hex_vars"] = out
    return out


def css_hex_to_var(css: str) -> str:
    """Rewrite hex literals in *css* to their ``var(--eetra-…)`` equivalents.

    This is what keeps theme.json authoritative for CSS that is assembled in
    Python (lib_header.fn005 and the page-level ``<style>`` blocks): any colour
    defined in theme.json stops being a frozen literal and follows the theme on
    the next rerun. Hexes with no token are left untouched.
    """
    lookup = _hex_var_lookup()
    if not css or not lookup:
        return css
    # Longest first so #666666 is matched before #666.
    pattern = re.compile(
        "(?:" + "|".join(re.escape(h) for h in sorted(lookup, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    out = pattern.sub(lambda m: lookup[m.group(0).lower()], css)
    # Safety net: if the CSS itself *declares* one of these custom properties with
    # a literal value, substitution would turn it into `--x: var(--x)`, which CSS
    # treats as invalid at computed-value time — the property silently resolves to
    # nothing. Undo any self-reference we just created.
    return re.sub(
        r"(--[\w-]+)(\s*:\s*)var\(\s*\1\s*\)",
        lambda m: f"{m.group(1)}{m.group(2)}{_var_literal(m.group(1))}",
        out,
    )


def _var_literal(var_name: str) -> str:
    """Literal value behind a ``--eetra-*`` custom property (reverse lookup)."""
    for literal, expr in _hex_var_lookup().items():
        if expr == f"var({var_name})":
            return literal
    return "inherit"


def tokens_css_text() -> str:
    """``_tokens.css`` contents (regenerated on demand), for the main document."""
    load_theme()
    try:
        return _TOKENS_CSS_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def sync_streamlit_config() -> None:
    """Rewrite the ``[theme]`` block of ``.streamlit/config.toml`` from theme.json.

    Only that block is touched — ``[server]``, ``[mapbox]`` and any other section
    are preserved verbatim, so this stays safe to run on every theme change.
    Streamlit reads config.toml at process start, so a change here needs a
    restart to take effect; the file is kept in sync regardless.
    """
    values = (_MEMO.get("theme") or {}).get("streamlit_theme") or {}
    if not isinstance(values, dict) or not values:
        return
    block = ["[theme]", "# Auto-generated from theme.json → streamlit_theme. Do not edit by hand."]
    for key, val in values.items():
        if str(key).startswith("_"):
            continue
        block.append(f'{key} = "{val}"' if isinstance(val, str) else f"{key} = {val}")
    block_text = "\n".join(block)
    try:
        if not _STREAMLIT_CONFIG_PATH.exists():
            return
        current = _STREAMLIT_CONFIG_PATH.read_text(encoding="utf-8")
        # Replace an existing [theme] section (up to the next top-level [section]).
        pattern = re.compile(r"(?ms)^\[theme\][^\[]*")
        updated = (
            pattern.sub(block_text + "\n\n", current, count=1)
            if pattern.search(current)
            else current.rstrip("\n") + "\n\n" + block_text + "\n"
        )
        if updated != current:
            _STREAMLIT_CONFIG_PATH.write_text(updated, encoding="utf-8")
    except Exception:
        pass


def iframe_height(name: str = "") -> int:
    """Shared iframe height from ``theme.json → layout``, with a global default."""
    layout = theme_section("layout") or {}
    try:
        default = int(layout.get("iframe_height_default", 860))
    except (TypeError, ValueError):
        default = 860
    heights = layout.get("iframe_heights") or {}
    if name and isinstance(heights, dict) and name in heights:
        try:
            return int(heights[name])
        except (TypeError, ValueError):
            return default
    return default


def font_links_html() -> str:
    """Google / icon font ``<link>`` tags from theme typography."""
    links = theme_section("typography", "google_font_links") or []
    parts: list[str] = []
    for href in links:
        href = str(href).strip()
        if href:
            parts.append(f'<link href="{href}" rel="stylesheet">')
    return "".join(parts)


def _font_data_uri(rel_path: str) -> str | None:
    path = _APP_ROOT / rel_path.replace("/", "\\") if "\\" not in rel_path else _APP_ROOT / rel_path
    if not path.is_file():
        path = _APP_ROOT / rel_path
    if not path.is_file():
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"url(data:font/woff2;base64,{b64}) format('woff2')"


def local_font_face_css() -> str:
    """``@font-face`` rules for bundled fonts (Ronzino) from theme.json."""
    faces = theme_section("typography", "local_fonts") or []
    blocks: list[str] = []
    for face in faces:
        if not isinstance(face, dict):
            continue
        family = str(face.get("family", "")).strip()
        if not family:
            continue
        url = str(face.get("url", "")).strip()
        if not url:
            rel = str(face.get("file", "")).strip()
            src = _font_data_uri(rel) if rel else None
        else:
            src = f"url('{url}') format('woff2')"
        if not src:
            continue
        weight = face.get("weight", 400)
        style = face.get("style", "normal")
        blocks.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
            f"font-display:swap;src:{src};}}"
        )
    return "".join(blocks)


def _css_escape_font_family(stack: str) -> str:
    """Unquoted CSS font-family list with spaces escaped (Source Serif Pro style)."""
    parts = [p.strip().strip("'\"") for p in re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", stack)]
    return ", ".join(p.replace(" ", "\\ ") if " " in p and not p.startswith("'") else p for p in parts if p)


def serif_heading_css() -> str:
    """CSS block for serif h1–h4 and page titles (unchanged serif stack).

    Font-WEIGHT for the page title is deliberately NOT set here: it used to be a
    second, separate knob (``page_title_font_weight``) fighting with
    ``chrome.page_title.font_weight`` for the same ``.eetra-page-title``
    element — both at 600, which is why titles read as heavier than intended.
    ``chrome.page_title.font_weight`` (applied by ``page_title_css()``, which
    runs after this in fn005) is now the only place that controls it.
    """
    chrome = theme_section("chrome", "serif_headings") or {}
    selectors = chrome.get("selectors") or []
    if not selectors:
        return ""
    serif = _css_escape_font_family(token("typography", "font_serif"))
    fstyle = chrome.get("font_style", "italic")
    fweight = chrome.get("font_weight", "400")
    sel = ", ".join(selectors)
    return f"{sel} {{ font-family: {serif} !important; font-style: {fstyle}; font-weight: {fweight}; }}"


def sans_ui_css() -> str:
    """CSS block forcing app sans (Miranda Sans) on nav, menus, and widgets."""
    chrome = theme_section("chrome", "sans_ui") or {}
    selectors = chrome.get("selectors") or []
    if not selectors:
        return ""
    sans = token("typography", "font_sans")
    sel = ", ".join(selectors)
    return (
        f"{sel} {{ font-family: {sans} !important; font-style: normal !important; }}"
    )


def page_title_css() -> str:
    """Per-page title style (``chrome.page_title``) — title/subtitle only.

    App-global masthead chrome (full Welcome / compact elsewhere) is styled
    separately via ``masthead_chrome_css`` / ``fn001b_render_app_masthead``.
    """
    pt = theme_section("chrome", "page_title") or {}
    fs = pt.get("font_size", "1.5rem")
    fw = pt.get("font_weight", "600")
    lh = pt.get("line_height", "1.15")
    mt = pt.get("margin_top", "0px")
    mb = pt.get("margin_bottom", "6px")
    scroll_mt = pt.get("scroll_margin_top", "4.5rem")
    sub_fs = pt.get("subtitle_font_size", "13px")
    sub_lh = pt.get("subtitle_line_height", "1.25")
    sub_mt = pt.get("subtitle_margin_top", "10px")
    emb_fs = pt.get("embedded_font_size", "1.1rem")
    emb_mb = pt.get("embedded_margin_bottom", "8px")
    gap = pt.get("first_block_gap", "0.15rem")
    tip_gap = pt.get("subtitle_tooltip_gap_em", "0.35em")
    tip_fs = pt.get("subtitle_tooltip_icon_size_em", "0.72em")
    tip_icon_fs = pt.get("subtitle_tooltip_icon_size", "0.72rem")
    tip_color = pt.get("subtitle_tooltip_icon_color", "var(--eetra-text-muted, #64748b)")
    tip_border = pt.get("subtitle_tooltip_icon_border", "1px solid rgba(100,116,139,0.45)")
    tip_bubble_max = pt.get("subtitle_tooltip_bubble_max_width", "22rem")
    tip_bubble_fs = pt.get("subtitle_tooltip_bubble_font_size", "12px")
    tip_bubble_lh = pt.get("subtitle_tooltip_bubble_line_height", "1.4")
    return (
        f".eetra-page-title-wrap {{ margin: {mt} 0 {mb} 0; padding: 0; "
        f"scroll-margin-top: {scroll_mt}; }} "
        # Absolute px sizes (from theme.json) beat rem/root scaling differences
        # across Windows PCs; pin both the h3 and the inner text span.
        f"h3.eetra-page-title, .eetra-page-title {{ margin: 0 !important; padding: 0 !important; "
        f"font-size: {fs} !important; font-weight: {fw} !important; "
        f"line-height: {lh} !important; color: var(--eetra-text, #1e293b); "
        f"display: inline-flex; align-items: center; flex-wrap: wrap; gap: 0; "
        f"scroll-margin-top: {scroll_mt}; }} "
        f".eetra-page-title .eetra-page-title-text {{ font-size: inherit !important; "
        f"font-weight: inherit !important; line-height: inherit !important; }} "
        f".eetra-page-subtitle {{ margin: {sub_mt} 0 0 0; padding: 0; "
        f"font-size: {sub_fs}; line-height: {sub_lh}; "
        f"color: var(--eetra-text-muted, #64748b); }} "
        f".eetra-page-subtitle-tip {{ position: relative; display: inline-flex; "
        f"align-items: center; justify-content: center; vertical-align: middle; cursor: help; outline: none; "
        f"margin-left: {tip_gap}; }} "
        f".eetra-page-subtitle-tip-icon {{ display: inline-flex; align-items: center; justify-content: center; "
        f"width: 1.15em; height: 1.15em; font-size: {tip_fs}; font-weight: 600; font-style: italic; "
        f"font-family: Georgia, 'Times New Roman', serif; line-height: 1; color: {tip_color}; "
        f"border: {tip_border}; border-radius: 50%%; user-select: none; }} "
        f".eetra-page-subtitle-tip-bubble {{ visibility: hidden; opacity: 0; pointer-events: none; "
        f"position: absolute; left: 50%%; top: calc(100%% + 6px); transform: translateX(-50%%); "
        f"z-index: 9999; max-width: {tip_bubble_max}; width: max-content; padding: 0.45rem 0.55rem; "
        f"font-size: {tip_bubble_fs}; font-weight: 400; font-style: normal; line-height: {tip_bubble_lh}; "
        f"text-align: left; color: var(--eetra-text, #1e293b); background: var(--eetra-surface, #fff); "
        f"border: 1px solid var(--eetra-border, rgba(128,128,128,0.25)); border-radius: 0.4rem; "
        f"box-shadow: 0 4px 14px rgba(15,23,42,0.12); transition: opacity 0.12s ease, visibility 0.12s ease; }} "
        f".eetra-page-subtitle-tip:hover .eetra-page-subtitle-tip-bubble, "
        f".eetra-page-subtitle-tip:focus-visible .eetra-page-subtitle-tip-bubble {{ "
        f"visibility: visible; opacity: 1; }} "
        f".eetra-page-title-wrap--embedded {{ margin-bottom: {emb_mb}; }} "
        f".eetra-page-title-wrap--embedded h3.eetra-page-title, "
        f".eetra-page-title-wrap--embedded .eetra-page-title {{ font-size: {emb_fs} !important; }} "
        f".eetra-page-title-wrap--embedded .eetra-page-subtitle-tip-icon {{ font-size: {tip_icon_fs}; }} "
        # Compress Streamlit's default 1rem VerticalBlock gap under the title so
        # chrome.page_title.margin_bottom owns title→content whitespace on every page.
        f"div[data-testid='stVerticalBlock']:has("
        f"> div[data-testid='stElementContainer'] .eetra-page-title-wrap), "
        f"div[data-testid='stVerticalBlock']:has("
        f"> div[data-testid='stVerticalBlockBorderWrapper'] .eetra-page-title-wrap) {{ "
        f"gap: {gap} !important; }}"
    )


def masthead_chrome_css() -> str:
    """Welcome masthead spacing, parked compact styles, Revalu-style top nav + sidebar tighten.

    Any literal ``%`` in CSS must be written as ``%%`` because fn005 still
    %-formats the combined stylesheet for catalogue font tokens.
    """
    hd = theme_section("chrome", "header_divider") or {}
    ct = theme_section("chrome", "custom_title") or {}
    mc = theme_section("chrome", "masthead_compact") or {}
    shell = theme_section("chrome", "shell") or {}
    sidebar = theme_section("chrome", "sidebar") or {}
    layout = theme_section("chrome", "layout") or {}
    mt = hd.get("margin_top", "20px")
    space_below = hd.get("space_below", "50px")

    shell_hex = shell.get("background", "#ffffff")
    shell_bg = css_color_with_opacity(shell_hex, shell.get("background_opacity", 1))
    nav_text = shell.get("nav_text_color", token("colors", "text") or "#1e293b")
    border_show = bool(shell.get("border_bottom_show", True))
    border_color = shell.get("border_bottom_color", "#e5e7eb")
    border_thickness = shell.get("border_bottom_thickness", "1px")
    border_space_above = shell.get("border_space_above", "0px")
    border_space_below = shell.get("border_space_below", "0px")
    sticky_clearance = shell.get("sticky_clearance", "4.25rem")
    header_border = (
        f"{border_thickness} solid {border_color}" if border_show else "none"
    )

    # Parked compact masthead tokens (kept for a later revive).
    bg_hex = mc.get("background", ct.get("color", token("colors", "green")))
    bg = css_color_with_opacity(bg_hex, mc.get("background_opacity", 1))
    title_color = mc.get("title_color", "#ffffff")
    compact_title_fs = str(mc.get("title_font_size") or "1.25rem")
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
    logo_filter = mc.get("logo_filter", "brightness(0) invert(1)")
    side_pad_top = sidebar.get("user_content_padding_top", "0.35rem")
    collapse_header = bool(sidebar.get("collapse_header", True))

    css = (
        f".eetra-masthead-chrome {{ margin: {mt} 0 0 0; padding: 0; height: 0; overflow: hidden; }} "
        f".eetra-masthead-below {{ margin: 0 0 {space_below} 0; padding: 0; height: 0; overflow: hidden; }} "
        f".eetra-masthead-clearance {{ margin: {sticky_clearance} 0 0 0; padding: 0; "
        f"height: 0; overflow: hidden; }} "
        f"div[data-testid='stVerticalBlock']:has("
        f"> div[data-testid='stElementContainer'] .eetra-masthead-chrome) {{ gap: 0.15rem !important; }} "
        f".eetra-masthead-compact {{ "
        f"background: {bg}; color: {title_color}; "
        f"margin: {compact_mt} -{bleed_l} {compact_mb} -{bleed_r}; "
        f"padding: {pad_y} {pad_x}; "
        f"box-sizing: border-box; width: calc(100%% + {bleed_l} + {bleed_r}); }} "
        f".eetra-masthead-compact-row {{ "
        f"display: flex; align-items: center; gap: {gap}; "
        f"min-height: {content_h}; }} "
        f".eetra-masthead-compact-logo {{ "
        f"height: {logo_h}; width: auto; display: block; flex-shrink: 0; "
        f"filter: {logo_filter}; }} "
        f".eetra-masthead-compact-title {{ "
        f"margin: 0 !important; padding: 0 !important; "
        f"font-size: {compact_title_fs} !important; "
        f"line-height: {content_h} !important; height: {content_h}; "
        f"display: flex; align-items: center; "
        f"color: {title_color} !important; }} "
        # Revalu-style top nav: white + bottom rule with tunable space above/below.
        f"[data-testid='stHeader'] {{ "
        f"background: {shell_bg} !important; "
        f"border-bottom: {header_border} !important; "
        f"padding-bottom: {border_space_above} !important; "
        f"margin-bottom: {border_space_below} !important; "
        f"box-shadow: none !important; }} "
        f"[data-testid='stHeader'] [data-testid='stToolbar'], "
        f"[data-testid='stHeader'] [data-testid='stToolbar'] > div {{ "
        f"background: transparent !important; }} "
        f"[data-testid='stHeader'] [data-testid='stTopNavLink'], "
        f"[data-testid='stHeader'] [data-testid='stTopNavLink'] span, "
        f"[data-testid='stHeader'] [data-testid='stTopNavLink'] p, "
        f"[data-testid='stHeader'] [data-testid='stTopNavLink'] a, "
        f"[data-testid='stHeader'] [data-testid='stTopNavLinkContainer'] span, "
        f"[data-testid='stHeader'] [data-testid='stTopNavLinkContainer'] p {{ "
        f"color: {nav_text} !important; }} "
        f"[data-testid='stHeader'] [data-testid='stTopNavLink'] svg, "
        f"[data-testid='stHeader'] [data-testid='stIconMaterial'], "
        f"[data-testid='stHeader'] [data-testid='stBaseButton-header'] svg, "
        f"[data-testid='stHeader'] button svg {{ "
        f"fill: {nav_text} !important; color: {nav_text} !important; }} "
        f"[data-testid='stHeader'] [data-testid='stBaseButton-header'], "
        f"[data-testid='stHeader'] [data-testid='stBaseButton-headerNoPadding'] {{ "
        f"color: {nav_text} !important; }} "
    )
    if shell.get("paint_sidebar", False):
        css += (
            f"section[data-testid='stSidebar'], "
            f"section[data-testid='stSidebar'] > div, "
            f"[data-testid='stSidebarContent'] {{ "
            f"background-color: {shell_bg} !important; "
            f"background-image: none !important; }} "
        )
    if collapse_header:
        css += (
            f"section[data-testid='stSidebar'] [data-testid='stSidebarHeader'] {{ "
            f"height: 0 !important; min-height: 0 !important; "
            f"padding: 0 !important; margin: 0 !important; "
            f"overflow: visible !important; position: relative !important; }} "
            f"section[data-testid='stSidebar'] [data-testid='stLogoSpacer'] {{ "
            f"display: none !important; }} "
            f"section[data-testid='stSidebar'] [data-testid='stSidebarCollapseButton'] {{ "
            f"position: absolute !important; top: 0.35rem !important; "
            f"right: 0.35rem !important; z-index: 2 !important; }} "
            f"section[data-testid='stSidebar'] [data-testid='stSidebarUserContent'] {{ "
            f"padding-top: {side_pad_top} !important; margin-top: 0 !important; }} "
        )
    return css


def add_edit_form_css() -> str:
    """Add/Edit Item form spacing + one shared font (``developer_dashboard.add_edit_form``)."""
    ae = theme_section("developer_dashboard", "add_edit_form") or {}
    fg = theme_section("developer_dashboard", "field_group_section") or {}
    sans = token("typography", "font_sans")
    row_gap = int(ae.get("widget_row_gap_px", 30))
    picker_gap = int(ae.get("edit_picker_to_tabs_gap_px", 20))
    # Single typeface + size for every control, label, caption, and meta line in Add/Edit.
    widget_fs = ae.get("widget_label_font_size", ae.get("widget_input_font_size", "12px"))
    widget_fw = ae.get("widget_label_font_weight", "400")
    fg_mb = fg.get("page_title_margin_bottom", "0.35rem")
    fg_default_mt = fg.get("margin_top", "0.65rem")
    fg_default_mb = fg.get("margin_bottom", "0.35rem")
    fg_color = fg.get("color", "var(--text-color, inherit)")
    # Single prefix only — never comma-join scopes like
    # ``column, verticalBlock descendant`` or the first scope absorbs rules meant
    # for descendants (e.g. ``display:none`` on ``.add-edit-cm-slot`` hid the
    # whole Developer content column).
    # Exclude VerticalBlocks that also contain the page title so Add/Edit cannot
    # shrink the Developer Dashboard title / left rail.
    form = (
        "div[data-testid='stVerticalBlock']:has(.add-edit-form-root)"
        ":not(:has(.eetra-page-title-wrap))"
    )
    return (
        f"{form} "
        f"div[data-testid='stTabPanel'] > div[data-testid='stVerticalBlock'] {{ "
        f"gap: {row_gap}px !important; }} "
        # One font family + size inside Add/Edit (overrides inline meta sizes).
        # Skip Material icon glyphs so tab / button icons keep their symbol font.
        # Skip Revalu R-badge so the circle letter can stay optically smaller.
        # Skip divider section labels (own size / colour / uppercase).
        f"{form} *:not([class*='material']):not([class*='Material'])"
        f":not(.revalu-r-badge):not(.add-edit-section-serif-title)"
        f":not(.eetra-page-title-wrap):not(.eetra-page-title)"
        f":not(.eetra-page-title-text):not(.eetra-page-subtitle)"
        f":not(.eetra-page-subtitle-tip):not(.eetra-page-subtitle-tip-icon)"
        f":not(.eetra-page-subtitle-tip-bubble)"
        f":not(svg):not(path):not(circle):not(rect) {{ "
        f"font-family: {sans} !important; "
        f"font-size: {widget_fs} !important; }} "
        f"{form} .revalu-r-badge {{ "
        f"display: inline-flex !important; align-items: center !important; "
        f"justify-content: center !important; "
        f"width: 16px !important; height: 16px !important; min-width: 16px !important; "
        f"border-radius: 50% !important; "
        f"font-family: {sans} !important; "
        f"font-size: 10px !important; font-weight: 700 !important; line-height: 1 !important; "
        f"background: var(--revalu-violet, {token('palette', 'revalu_violet', '#8c66e0')}) !important; "
        f"color: #fff !important; }} "
        f"{form} .revalu-caption, "
        f"{form} .revalu-caption code, "
        f"{form} .revalu-field-name {{ "
        f"color: var(--revalu-violet, {token('palette', 'revalu_violet', '#8c66e0')}) !important; }} "
        # Divider section labels (Product Info URLs, Physical properties, …):
        # same grey as the rule above, all-caps, tight to the divider.
        f"{form} .add-edit-section-serif-title, "
        f".add-edit-section-serif-title {{ "
        f"font-family: {sans} !important; "
        f"font-style: normal !important; "
        f"font-weight: 600 !important; "
        f"font-size: 0.85rem !important; "
        f"line-height: 1.2 !important; "
        f"letter-spacing: 0.06em !important; "
        f"text-transform: uppercase !important; "
        f"margin: 0 0 0.35rem 0 !important; "
        f"padding: 0 !important; "
        f"color: #d1d5db !important; "
        f"opacity: 1 !important; }} "
        f".add-edit-field-group-title, "
        f".add-edit-field-group-title--page {{ "
        f"font-family: {sans} !important; font-size: {widget_fs} !important; "
        f"font-weight: {widget_fw} !important; line-height: 1.25; "
        f"margin-top: {fg_default_mt}; margin-bottom: {fg_default_mb}; "
        f"color: {fg_color}; opacity: 1; }} "
        f".add-edit-field-group-title--page {{ "
        f"margin-bottom: {fg_mb} !important; "
        f"color: var(--eetra-text, #1e293b) !important; }} "
        f".add-edit-picker-tabs-gap {{ height: {picker_gap}px; min-height: {picker_gap}px; "
        f"margin: 0; padding: 0; display: block; pointer-events: none; }} "
        f".add-edit-summary-matrix {{ margin-top: 0.5rem; padding: 10px 8px 12px; "
        f"background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; }} "
        f".add-edit-summary-legend {{ display: flex; flex-wrap: wrap; gap: 12px; "
        f"color: #64748b; margin-bottom: 10px; }} "
        f".add-edit-summary-legend-item {{ display: inline-flex; align-items: center; gap: 5px; }} "
        f".add-edit-summary-legend-swatch {{ width: 14px; height: 14px; border-radius: 2px; "
        f"box-sizing: border-box; flex-shrink: 0; }} "
        f".add-edit-summary-row {{ display: flex; align-items: center; gap: 10px; "
        f"margin: 5px 0; min-height: 22px; }} "
        f".add-edit-summary-y {{ flex: 0 0 auto; line-height: 1.25; "
        f"text-align: right; color: #334155; padding-right: 4px; }} "
        f".add-edit-summary-y-count {{ color: #64748b; font-weight: 500; }} "
        f".add-edit-summary-cells {{ display: flex; flex-wrap: wrap; gap: 2px; align-items: center; "
        f"flex: 1 1 auto; min-width: 0; }} "
        f".add-edit-summary-cell {{ display: inline-block; width: 18px; height: 18px; "
        f"border-radius: 2px; box-sizing: border-box; flex-shrink: 0; cursor: default; }} "
        f"{form} .add-edit-side-label-block {{ "
        f"display: flex; flex-direction: column; align-items: flex-start; "
        f"gap: 0.2rem; padding-top: 0.15rem; max-width: 100%; }} "
        f"{form} .add-edit-side-label {{ "
        f"font-weight: {widget_fw} !important; line-height: 1.25; "
        f"color: var(--text-color, inherit); "
        f"word-break: break-word; }} "
        f"{form} .add-edit-side-meta {{ "
        f"line-height: 1.25; max-width: 100%; overflow-wrap: anywhere; }} "
        f"{form} div[data-testid='stMarkdownContainer']:has(.add-edit-cm-slot) {{ "
        f"display: none !important; height: 0 !important; margin: 0 !important; "
        f"padding: 0 !important; overflow: hidden !important; }} "
        f"{form} div[data-testid='stColumn']:has(.add-edit-cm-slot) [data-testid='stWidgetLabel'] p {{ "
        f"white-space: nowrap; }} "
        f"{form} div[data-testid='stColumn']:has(.add-edit-cm-slot) [data-baseweb='select'] {{ "
        f"min-width: 0 !important; }} "
        f"{form} .add-edit-phys-meta {{ "
        f"white-space: nowrap; overflow: hidden; text-overflow: ellipsis; "
        f"line-height: 1.25; margin-top: 0.15rem; max-width: 100%; }} "
        f"{form} [data-testid='stWidgetLabel'] p, "
        f"{form} [data-testid='stWidgetLabel'] label {{ "
        f"font-weight: {widget_fw} !important; }} "
    )


def auth_gate_typography_css() -> str:
    """Login masthead text: same stacks as header custom-title / custom-caption, on photo backdrop."""
    from libs.lib_tokens import _css_escape_font_family

    ct = theme_section("chrome", "custom_title") or {}
    cc = theme_section("chrome", "custom_caption") or {}
    sh = theme_section("chrome", "serif_headings") or {}
    ag = theme_section("chrome", "auth_gate") or {}
    sans = token("typography", "font_sans")
    serif = _css_escape_font_family(token("typography", "font_serif"))
    title_color = ag.get("title_color", "#111111")
    tagline_color = ag.get("tagline_color", title_color)
    wordmark_color = ag.get("wordmark_color", title_color)
    title_fs = ag.get("title_font_size", "1.75rem")
    wordmark_fs = ag.get("wordmark_font_size", "0.95rem")
    title_margin = ag.get("title_margin", "0.12rem 0 0.08rem 0")
    try:
        logo_h = int(ag.get("logo_height_px", 40))
    except (TypeError, ValueError):
        logo_h = 40
    try:
        brand_pad_top = int(ag.get("brand_padding_top_px", 200))
    except (TypeError, ValueError):
        brand_pad_top = 200
    try:
        brand_margin_bottom = int(ag.get("brand_margin_bottom_px", 20))
    except (TypeError, ValueError):
        brand_margin_bottom = 20
    text_shadow = ag.get(
        "text_shadow",
        "0 0 10px rgba(255,255,255,0.95), 0 0 22px rgba(255,255,255,0.75), 0 1px 0 rgba(255,255,255,0.9)",
    )
    title_lh = ct.get("line_height", "1.15")
    tag_fs = cc.get("font_size", "0.8rem")
    tag_lh = cc.get("line_height", "1.35")
    serif_style = sh.get("font_style", "italic")
    serif_weight = sh.get("font_weight", "400")
    return (
        local_font_face_css()
        + " "
        + f"div.st-key-login_card, div.st-key-login_card * {{ "
        f"font-family: {sans} !important; font-style: normal !important; }} "
        f"div[data-testid='stMarkdown']:has(.login-gate-brand) {{ width: 100% !important; }} "
        f".login-gate-brand {{ "
        f"display: flex !important; flex-direction: column !important; align-items: center !important; "
        f"width: 100% !important; text-align: center !important; "
        f"padding-top: {brand_pad_top}px !important; margin: 0 0 {brand_margin_bottom}px 0 !important; }} "
        f".login-gate-wordmark {{ "
        f"width: 100% !important; text-align: center !important; "
        f"font-family: {serif} !important; font-style: {serif_style} !important; "
        f"font-weight: {serif_weight} !important; font-size: {wordmark_fs} !important; "
        f"line-height: 1.2 !important; color: {wordmark_color} !important; "
        f"text-shadow: {text_shadow} !important; "
        f"margin: 0 0 0.15rem 0 !important; padding: 0 !important; }} "
        f".login-gate-logo {{ height: {logo_h}px; width: auto; max-width: min(100%, 520px); "
        f"display: block !important; margin: 0 auto !important; }} "
        f".login-gate-title {{ "
        f"width: 100% !important; text-align: center !important; "
        f"font-family: {serif} !important; font-style: {serif_style} !important; "
        f"font-weight: {serif_weight} !important; font-size: {title_fs} !important; "
        f"line-height: {title_lh} !important; color: {title_color} !important; "
        f"text-shadow: {text_shadow} !important; "
        f"margin: {title_margin} !important; "
        f"padding: 0 !important; }} "
        f".login-gate-tagline {{ "
        f"width: 100% !important; text-align: center !important; "
        f"font-family: {sans} !important; font-style: normal !important; font-weight: 400 !important; "
        f"font-size: {tag_fs} !important; line-height: {tag_lh} !important; "
        f"color: {tagline_color} !important; text-shadow: {text_shadow} !important; "
        f"margin: {cc.get('margin', '0')} !important; padding: 0 !important; }} "
        f".login-gate-demo {{ text-align: center; color: var(--eetra-text-faint, #94a3b8); "
        f"font-size: {tag_fs}; margin: 0.75rem 0 0 0; font-weight: 400 !important; "
        f"line-height: {tag_lh}; }} "
    )


def chrome_layout_css() -> str:
    """Main block-container / sidebar padding from theme chrome.layout."""
    lay = theme_section("chrome", "layout") or {}
    return (
        f".block-container {{ padding-top: {lay.get('block_container_padding_top', '0.5rem')}; "
        f"padding-bottom: {lay.get('block_container_padding_bottom', '0.5rem')}; "
        f"padding-left: {lay.get('block_container_padding_left', '2rem')}; "
        f"padding-right: {lay.get('block_container_padding_right', '2rem')}; }} "
        f"section[data-testid=stSidebar] .block-container {{ padding-top: {lay.get('sidebar_block_container_padding_top', '0.5rem')}; }} "
        f"div[data-testid=stAppViewContainer] [data-testid=stMain] .block-container {{ padding-top: {lay.get('main_block_container_padding_top', '0.75rem')}; }} "
        f"[data-testid=stMain] {{ padding-left: {lay.get('main_padding_left', '1rem')}; padding-right: {lay.get('main_padding_right', '1rem')}; }}"
    )


def sidebar_collapsed_control_css() -> str:
    """Hide or fix Streamlit collapsed-sidebar chevron (literal icon-name text leak).

    Streamlit >=1.59 uses ``stExpandSidebarButton`` / ``stSidebarCollapseButton``;
    older builds used ``collapsedControl``. Icon fix must beat ``sans_ui`` on
    ``stHeader``/``stToolbar`` descendants (higher-specificity selectors in theme).
    """
    cfg = theme_section("chrome", "sidebar_collapsed_control") or {}
    mode = str(cfg.get("mode", "icon_fix")).strip().lower()
    hide_selectors = cfg.get("hide_selectors") or [
        "[data-testid='stExpandSidebarButton']",
        "[data-testid='stSidebarCollapseButton']",
        "[data-testid='collapsedControl']",
    ]
    hide_block = (
        "display: none !important; visibility: hidden !important; "
        "width: 0 !important; min-width: 0 !important; max-width: 0 !important; "
        "height: 0 !important; overflow: hidden !important; "
        "padding: 0 !important; margin: 0 !important; border: none !important; "
        "opacity: 0 !important; pointer-events: none !important;"
    )
    if mode == "hide":
        return " ".join(f"{sel} {{ {hide_block} }}" for sel in hide_selectors)

    selectors = cfg.get("selectors") or [
        "[data-testid='stExpandSidebarButton'] [data-testid='stIconMaterial']",
        "[data-testid='stSidebarCollapseButton'] [data-testid='stIconMaterial']",
        "[data-testid='stHeader'] [data-testid='stExpandSidebarButton']",
        "[data-testid='stHeader'] [data-testid='stExpandSidebarButton'] *",
        "[data-testid='stHeader'] [data-testid='stSidebarCollapseButton']",
        "[data-testid='stHeader'] [data-testid='stSidebarCollapseButton'] *",
        "[data-testid='stExpandSidebarButton']",
        "[data-testid='stExpandSidebarButton'] *",
        "[data-testid='stSidebarCollapseButton']",
        "[data-testid='stSidebarCollapseButton'] *",
        "[data-testid='stIconMaterial']",
        "[data-testid='collapsedControl']",
        "[data-testid='collapsedControl'] *",
    ]
    if not selectors:
        return ""
    ff = cfg.get("icon_font_family", "'Material Symbols Rounded', 'Material Icons'")
    fs = cfg.get("icon_font_size", "1.35rem")
    sel = ", ".join(selectors)
    btn_sel = ", ".join(
        s for s in hide_selectors
        if s.endswith("Button']") or s.endswith("Control']")
    )
    return (
        f"{sel} {{ "
        f"font-family: {ff} !important; "
        f"font-style: normal !important; "
        f"font-weight: normal !important; "
        f"font-size: {fs} !important; "
        f"letter-spacing: normal !important; "
        f"text-transform: none !important; "
        f"font-feature-settings: 'liga' !important; "
        f"-webkit-font-feature-settings: 'liga' !important; "
        f"font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24 !important; "
        f"line-height: 1 !important; "
        f"white-space: nowrap !important; "
        f"overflow: hidden !important; "
        f"text-indent: 0 !important; "
        f"}} "
        f"{btn_sel} {{ max-width: 2.75rem !important; }}"
    )


def sidebar_width_px() -> int:
    """Sidebar width for ``st.set_page_config(initial_sidebar_state=…)`` (200–600 px)."""
    cfg = theme_section("chrome", "sidebar") or {}
    try:
        w = int(cfg.get("width_px", 320))
    except (TypeError, ValueError):
        w = 320
    return max(200, min(600, w))


def sidebar_keyboard_shortcut_script() -> str:
    """Return a ``<script>`` that binds the theme-configured key to sidebar toggle.

    Must be injected with ``st.html(..., unsafe_allow_javascript=True)`` —
    Streamlit strips ``<script>`` tags when that flag is omitted.
    """
    cfg = theme_section("chrome", "sidebar") or {}
    sc = cfg.get("keyboard_shortcut") or {}
    if not sc.get("enabled", True):
        return ""
    key = str(sc.get("key", "h")).strip().lower() or "h"
    key_js = json.dumps(key)
    return (
        "<script>(function(){"
        "if(window.__eetraSidebarShortcutBound)return;"
        "window.__eetraSidebarShortcutBound=true;"
        f"var KEY={key_js};"
        "function typingTarget(el){"
        "if(!el)return false;"
        "var t=(el.tagName||'').toUpperCase();"
        "if(t==='INPUT'||t==='TEXTAREA'||t==='SELECT')return true;"
        "if(el.isContentEditable)return true;"
        "return false;"
        "}"
        "function visible(el){"
        "if(!el)return false;"
        "var s=window.getComputedStyle(el);"
        "return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0';"
        "}"
        "function toggleSidebar(){"
        "var collapse=document.querySelector('[data-testid=\"stSidebarCollapseButton\"]');"
        "if(collapse&&visible(collapse)){collapse.click();return;}"
        "var expand=document.querySelector('[data-testid=\"stExpandSidebarButton\"]');"
        "if(expand&&visible(expand)){expand.click();return;}"
        "var legacy=document.querySelector('[data-testid=\"collapsedControl\"]');"
        "if(legacy&&visible(legacy))legacy.click();"
        "}"
        "document.addEventListener('keydown',function(e){"
        "if((e.key||'').toLowerCase()!==KEY)return;"
        "if(e.ctrlKey||e.metaKey||e.altKey)return;"
        "if(typingTarget(document.activeElement))return;"
        "e.preventDefault();"
        # On Developer Dashboard, H may be the first half of HH (nav toggle).
        # Defer so a quick second H cancels the sidebar toggle.
        "var onDev=!!(document.querySelector('.dev-left-nav')||document.querySelector('.dev-content-pane'));"
        "if(onDev&&KEY==='h'){"
        "if(window.__eetraSidebarHTimer){clearTimeout(window.__eetraSidebarHTimer);window.__eetraSidebarHTimer=null;return;}"
        "window.__eetraSidebarHTimer=setTimeout(function(){window.__eetraSidebarHTimer=null;toggleSidebar();},400);"
        "return;"
        "}"
        "toggleSidebar();"
        "},true);"
        "})();</script>"
    )


def developer_left_nav_css() -> str:
    """CSS for the Developer Dashboard left-rail ``st.radio`` (tab-rail look).

    Inject with ``st.html`` (not ``st.markdown``): some Streamlit / browser
    combinations strip ``<style>`` from markdown HTML, which drops the section
    dividers and leaves the native radio circles visible. Dividers use a 2px
    ``::after`` rule so they survive Windows display scaling that eats 1px
    borders.
    """
    ln = theme_section("developer_dashboard", "left_nav") or {}
    gap = ln.get("section_gap_after", "0.85rem")
    div_color = ln.get("section_divider_color", "#94a3b8")
    div_thick = ln.get("section_divider_thickness", "2px")
    return (
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] {{'
        f" gap: {ln.get('option_gap', '0.15rem')};"
        f" border: {ln.get('rail_border', '1px solid rgba(128,128,128,0.20)')};"
        f" border-radius: {ln.get('rail_radius', '0.75rem')};"
        f" padding: {ln.get('rail_padding', '0.4rem')};"
        f" position: sticky;"
        f" top: {ln.get('sticky_top', '3.5rem')};"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label {{'
        f" display: flex; width: 100%; margin: 0;"
        f" padding: {ln.get('option_padding_y', '0.5rem')} {ln.get('option_padding_x', '0.7rem')};"
        f" border-radius: {ln.get('option_radius', '0.5rem')};"
        f" border-left: {ln.get('active_bar_width', '3px')} solid transparent;"
        f" cursor: pointer; line-height: {ln.get('option_line_height', '1.25')};"
        f" transition: background-color 0.12s ease;"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:hover {{'
        f" background: {ln.get('hover_bg', 'rgba(128,128,128,0.10)')};"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label > div:first-child {{'
        f" display: none;"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label div[data-testid="stMarkdownContainer"] p {{'
        f" font-size: {ln.get('option_font_size', '0.9rem')} !important;"
        f" margin: 0 !important;"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:has(input:checked) {{'
        f" background: {ln.get('active_bg', 'rgba(42,125,46,0.12)')};"
        f" border-left-color: {ln.get('active_bar_color', 'var(--eetra-green, #2a7d2e)')};"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:has(input:checked) div[data-testid="stMarkdownContainer"] p {{'
        f" color: {ln.get('active_color', 'var(--eetra-green, #2a7d2e)')} !important;"
        f" font-weight: 600 !important;"
        f" }}"
        # Section dividers after Edit Item (2) and Edit Manufacturer (4).
        # ::after + 2px survives DPI scaling better than border-bottom: 1px.
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:nth-of-type(2),'
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:nth-of-type(4) {{'
        f" position: relative;"
        f" margin-bottom: {gap} !important;"
        f" padding-bottom: {gap} !important;"
        f" border-radius: 0 !important;"
        f" }}"
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:nth-of-type(2)::after,'
        f'div[data-testid="stVerticalBlock"]:has(.dev-left-nav) div[role="radiogroup"] > label:nth-of-type(4)::after {{'
        f' content: "";'
        f" display: block;"
        f" position: absolute;"
        f" left: {ln.get('option_padding_x', '0.7rem')};"
        f" right: {ln.get('option_padding_x', '0.7rem')};"
        f" bottom: 0;"
        f" height: 0;"
        f" border-bottom: {div_thick} solid {div_color};"
        f" pointer-events: none;"
        f" }}"
        f".dev-nav-shortcut-hint {{"
        f" font-size: 0.8rem; color: #64748b; margin: 0.45rem 0 0; line-height: 1.4;"
        f" }}"
        f".dev-nav-shortcut-key {{"
        f" display: inline-block; min-width: 1.35em; padding: 0.05em 0.4em;"
        f" margin: 0 0.15em; border: 1px solid #94a3b8; border-radius: 4px;"
        f" font-family: inherit; font-size: 0.92em; font-weight: 600;"
        f" line-height: 1.35; text-align: center; color: #334155;"
        f" background: #f8fafc; box-shadow: 0 1px 0 #cbd5e1;"
        f" }}"
    )


def developer_left_nav_keyboard_shortcut_script() -> str:
    """Return a ``<script>`` that toggles the Developer left-rail radio column.

    Hides/shows the ``stColumn`` that contains ``.dev-left-nav`` and expands the
    content pane. Preference is kept in ``sessionStorage`` so Streamlit reruns
    re-apply the same state. Inject with ``unsafe_allow_javascript=True``.
    """
    cfg = theme_section("developer_dashboard", "left_nav") or {}
    sc = cfg.get("keyboard_shortcut") or {}
    if not sc.get("enabled", True):
        return ""
    key = str(sc.get("key", "hh")).strip().lower() or "hh"
    # Menu is visible unless the user has explicitly hidden it (STORE === '1').
    default_visible = bool(sc.get("default_visible", True))
    # Repeated letters (e.g. "hh") → double-tap of that letter; otherwise single key.
    chord_char = key[0]
    chord_count = len(key) if key == chord_char * len(key) else 1
    match_key = chord_char if chord_count > 1 else key
    key_js = json.dumps(match_key)
    count_js = json.dumps(chord_count)
    default_hidden_js = "false" if default_visible else "true"
    return (
        '<div style="display:none" aria-hidden="true"></div>'
        "<script>(function(){"
        "var KEY=" + key_js + ";"
        "var NEED=" + count_js + ";"
        "var GAP=400;"
        # v2 resets any previous hide preference so the rail starts visible again.
        "var STORE='eetraDevLeftNavHidden_v2';"
        "var DEFAULT_HIDDEN=" + default_hidden_js + ";"
        "function typingTarget(el){"
        "if(!el)return false;"
        "var t=(el.tagName||'').toUpperCase();"
        "if(t==='INPUT'||t==='TEXTAREA'||t==='SELECT')return true;"
        "if(el.isContentEditable)return true;"
        "return false;"
        "}"
        "function navCol(){"
        "var m=document.querySelector('.dev-left-nav');"
        "return m?m.closest('[data-testid=\"stColumn\"]'):null;"
        "}"
        "function contentCol(){"
        "var m=document.querySelector('.dev-content-pane');"
        "return m?m.closest('[data-testid=\"stColumn\"]'):null;"
        "}"
        "function isHidden(){"
        "try{"
        "var v=sessionStorage.getItem(STORE);"
        "if(v===null)return DEFAULT_HIDDEN;"
        "return v==='1';"
        "}catch(e){return DEFAULT_HIDDEN;}"
        "}"
        "function setHidden(v){try{sessionStorage.setItem(STORE,v?'1':'0');}catch(e){}}"
        "function apply(){"
        "var nav=navCol(),content=contentCol();"
        "if(!nav)return;"
        "var hidden=isHidden();"
        "nav.style.display=hidden?'none':'';"
        "if(content){"
        "if(hidden){"
        "content.style.flex='1 1 100%';"
        "content.style.maxWidth='100%';"
        "content.style.width='100%';"
        "}else{"
        "content.style.flex='';"
        "content.style.maxWidth='';"
        "content.style.width='';"
        "}"
        "}"
        "}"
        "function toggle(){setHidden(!isHidden());apply();}"
        "apply();"
        "if(window.__eetraDevLeftNavOnKey){"
        "document.removeEventListener('keydown',window.__eetraDevLeftNavOnKey,true);"
        "}"
        "window.__eetraDevLeftNavChord={n:0,at:0};"
        "window.__eetraDevLeftNavOnKey=function(e){"
        "if((e.key||'').toLowerCase()!==KEY)return;"
        "if(e.ctrlKey||e.metaKey||e.altKey)return;"
        "if(typingTarget(document.activeElement))return;"
        "if(!document.querySelector('.dev-left-nav')&&!document.querySelector('.dev-content-pane'))return;"
        "if(NEED<=1){e.preventDefault();toggle();return;}"
        "var now=Date.now(),c=window.__eetraDevLeftNavChord;"
        "if(now-c.at>GAP)c.n=0;"
        "c.n+=1;c.at=now;"
        "if(c.n>=NEED){c.n=0;c.at=0;e.preventDefault();toggle();}"
        "};"
        "document.addEventListener('keydown',window.__eetraDevLeftNavOnKey,true);"
        "if(!window.__eetraDevLeftNavObserver){"
        "var t=null;"
        "window.__eetraDevLeftNavObserver=new MutationObserver(function(){"
        "if(t)cancelAnimationFrame(t);"
        "t=requestAnimationFrame(apply);"
        "});"
        "window.__eetraDevLeftNavObserver.observe(document.body,{childList:true,subtree:true});"
        "}"
        "})();</script>"
    )


def app_documentation_css(container_key: str = "eetra_app_docs") -> str:
    """Smaller markdown heading sizes inside Developer → App Documentation tab.

    Scoped to the ``st.container(key=container_key)`` wrapper via Streamlit's
    ``.st-key-<key>`` class — a real ancestor/descendant relationship. Do NOT
    switch this back to a ``:has()`` lookup on an empty marker div: ``:has()``
    matches every ancestor stVerticalBlock (not just the immediate one), so it
    leaks the shrunk h1–h4 sizes onto unrelated page titles elsewhere on the page
    (this previously shrank both the "Material Library" masthead and this
    page's own title whenever the App Documentation tab was visited).
    """
    doc = theme_section("developer_dashboard", "app_documentation") or {}
    lh = doc.get("heading_line_height", "1.2")
    scope = f".st-key-{container_key}"
    return (
        f"{scope} .stMarkdown h1, {scope} h1 {{ "
        f"font-size: {doc.get('h1_font_size', '1.25rem')} !important; "
        f"line-height: {lh} !important; "
        f"margin-top: {doc.get('h1_margin_top', '0.5rem')} !important; "
        f"margin-bottom: {doc.get('h1_margin_bottom', '0.4rem')} !important; "
        f"}} "
        f"{scope} .stMarkdown h2, {scope} h2 {{ "
        f"font-size: {doc.get('h2_font_size', '1.05rem')} !important; "
        f"line-height: {lh} !important; "
        f"margin-top: {doc.get('h2_margin_top', '0.85rem')} !important; "
        f"margin-bottom: {doc.get('h2_margin_bottom', '0.3rem')} !important; "
        f"}} "
        f"{scope} .stMarkdown h3, {scope} h3 {{ "
        f"font-size: {doc.get('h3_font_size', '0.95rem')} !important; "
        f"line-height: {lh} !important; "
        f"margin-top: {doc.get('h3_margin_top', '0.65rem')} !important; "
        f"margin-bottom: {doc.get('h3_margin_bottom', '0.25rem')} !important; "
        f"font-style: normal !important; "
        f"}} "
        f"{scope} .stMarkdown h4, {scope} h4 {{ "
        f"font-size: {doc.get('h4_font_size', '0.9rem')} !important; "
        f"line-height: {lh} !important; "
        f"font-style: normal !important; "
        f"}}"
    )


def database_schema_css() -> str:
    """Compact markdown tables inside Developer → Database Schema tab."""
    schema = theme_section("developer_dashboard", "database_schema") or {}
    scope = ".st-key-eetra_database_schema"
    pad_y = schema.get("table_cell_padding_y", "0.2rem")
    pad_x = schema.get("table_cell_padding_x", "0.45rem")
    fs = schema.get("table_font_size", "0.85rem")
    lh = schema.get("table_line_height", "1.25")
    mt = schema.get("table_margin_top", "0.25rem")
    mb = schema.get("table_margin_bottom", "0.35rem")
    return (
        f"{scope} .stMarkdown table {{ "
        f"margin-top: {mt} !important; margin-bottom: {mb} !important; "
        f"font-size: {fs} !important; line-height: {lh} !important; "
        f"}} "
        f"{scope} .stMarkdown th, {scope} .stMarkdown td {{ "
        f"padding: {pad_y} {pad_x} !important; "
        f"line-height: {lh} !important; "
        f"vertical-align: top !important; "
        f"}} "
        f"{scope} .stMarkdown thead th {{ "
        f"padding-top: {pad_y} !important; padding-bottom: {pad_y} !important; "
        f"}}"
    )
