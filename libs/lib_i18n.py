"""
lib_i18n.py — app language (ITA / ENG) and field-name translation
==================================================================
Single source of truth for which language the UI speaks and for the
translated label of every dataset field.

Catalogue lives in ``aux_16__translations.json`` (repo root):

    fields.<LANG>.<raw column name>  → translated field label
    ui.<LANG>.<string id>            → translated app-chrome string

Resolution order for a field label (fn703):
    1. ``fields.<active lang>`` in the catalogue
    2. the English label the app already computes (caller's ``fallback``:
       ``lib_revalu_map.FIELD_LABELS`` → ``aux_10__ui_config.json ->
       column_display_labels`` → ``lib_data.fn128_clean_column_name``)
So an untranslated key degrades to English rather than to a raw column name,
and ``fields.ENG`` only needs entries that differ from those defaults.

Public API
----------
fn700_load_translations()      catalogue dict, memoized on file mtime
fn701_languages()              {"ITA": {...}, "ENG": {...}}
fn702_current_language()       active code, default from the catalogue (ITA)
fn703_translate_field(col, fallback=None)   translated field label
fn704_t(key, fallback="", **fmt)            translated UI string
fn705_set_language(lang)       write the active language into session state
fn706_render_language_selector(container=None)   the sidebar toggle
fn707_translate_card_fields(config_json)    catalogue card labels, in the payload
fn708_translate_value(column, value)        a dataset value (Product/Material Type)
fn709_value_maps_for_component()            those maps, keyed by JS field name
fn710_add_italian_product_type(df)          derive the D__ProductType_ITA column
fn711_t_page(title)                         a page / tab-menu title
fn712_t_subtitle(subtitle)                  an in-page sub-heading
fn713_chrome_strings()                      catalogue-component chrome map
fn714_tu(text, **fmt)                       an in-page control label / caption

Everything degrades quietly: a missing/unreadable catalogue leaves the app in
English, exactly as it behaved before this module existed.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import streamlit as st

# Session-state key holding the active language code.
LANG_STATE_KEY = "app_language"
# The picker widget's own state key (see fn702 / fn706).
_LANG_WIDGET_KEY = "_app_language_picker"

_TRANSLATIONS_PATH = Path(__file__).resolve().parent.parent / "aux_16__translations.json"
_FALLBACK_LANG = "ENG"

# Used when the catalogue cannot be read at all, so the selector still renders.
_DEFAULT_LANGUAGES: dict[str, dict] = {
    "ITA": {"label": "ITA", "name": "Italiano", "flag": "\U0001F1EE\U0001F1F9"},
    "ENG": {"label": "ENG", "name": "English", "flag": "\U0001F1EC\U0001F1E7"},
}

# Windows/Chromium ships no glyphs for regional-indicator pairs, so the flag
# emoji in the catalogue renders as two letter boxes ("IT", "GB"). Streamlit
# puts that leading emoji in the option's own icon slot
# (``[data-testid="stIconEmoji"]``), which fn706 then paints over with these
# SVGs — the emoji stays as the accessible text underneath. A language may
# override this with ``languages.<code>.flag_svg`` in the catalogue.
_FLAG_SVG: dict[str, str] = {
    "ITA": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2">'
        '<rect width="3" height="2" fill="#fff"/>'
        '<rect width="1" height="2" fill="#008C45"/>'
        '<rect x="2" width="1" height="2" fill="#CD212A"/></svg>'
    ),
    "ENG": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30">'
        '<clipPath id="uj"><path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z"/></clipPath>'
        '<rect width="60" height="30" fill="#012169"/>'
        '<path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/>'
        '<path d="M0,0 L60,30 M60,0 L0,30" clip-path="url(#uj)" stroke="#C8102E" stroke-width="4"/>'
        '<path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/>'
        '<path d="M30,0 v30 M0,15 h60" stroke="#C8102E" stroke-width="6"/></svg>'
    ),
}


# Flanks the toggle. Only the flags and the two labels are styled here; the
# switch itself is left entirely to Streamlit's own theme.
_FN706_TOGGLE_CSS = (
    ".app-language-side {"
    " display: inline-flex; align-items: center; gap: 0.3rem;"
    " font-size: 0.80rem; line-height: 1.1; opacity: 0.55; white-space: nowrap; }"
    ".app-language-side.is-active { opacity: 1; font-weight: 600; }"
    ".app-language-flag {"
    " width: 1.05rem; height: 0.72rem; border-radius: 2px;"
    " box-shadow: 0 0 0 1px rgba(0,0,0,0.18); display: block; }"
)


def _fn706_flag_data_uri(code: str, meta: dict) -> str:
    """``url(...)`` value for a language's flag, or "" when there is none."""
    svg = str((meta or {}).get("flag_svg") or "").strip() or _FLAG_SVG.get(code, "")
    if not svg:
        return ""
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")


@st.cache_data(show_spinner=False)
def _fn700_read_translations(mtime: float) -> dict:
    """
    Read the catalogue from disk. Keyed on mtime so edits apply on rerun.

    ``mtime`` must NOT be underscore-prefixed: Streamlit silently drops such
    parameters from the cache key, and the catalogue would then be read once
    per process and never again — edits to the JSON would not show up until a
    restart. (Same trap as ``config_signature`` in libs/lib_ui.py.)
    """
    try:
        with open(_TRANSLATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def fn700_load_translations() -> dict:
    """Translation catalogue, re-read whenever ``aux_16__translations.json`` changes."""
    try:
        mtime = _TRANSLATIONS_PATH.stat().st_mtime
    except Exception:
        mtime = 0.0
    return _fn700_read_translations(mtime)


def fn701_languages() -> dict[str, dict]:
    """Available languages, ``{code: {label, name, flag}}``."""
    langs = (fn700_load_translations() or {}).get("languages")
    if isinstance(langs, dict) and langs:
        return langs
    return dict(_DEFAULT_LANGUAGES)


def _fn702_default_language() -> str:
    cat = fn700_load_translations() or {}
    code = str(cat.get("default_language") or "").strip().upper()
    langs = fn701_languages()
    if code in langs:
        return code
    return "ITA" if "ITA" in langs else (next(iter(langs), _FALLBACK_LANG))


def fn702_current_language() -> str:
    """
    Active language code. Defaults to the catalogue's ``default_language`` (ITA).

    The picker's own widget state is read first: on the rerun that follows a
    language change it already holds the new code, while ``LANG_STATE_KEY`` is
    only written when fn706 runs — which is *after* the sidebar strings above
    it. Without this, those strings lagged one run behind the toggle.
    """
    langs = fn701_languages()
    widget_code = str(st.session_state.get(_LANG_WIDGET_KEY) or "").strip().upper()
    if widget_code and widget_code in langs:
        return widget_code
    code = str(st.session_state.get(LANG_STATE_KEY) or "").strip().upper()
    if code and code in langs:
        return code
    code = _fn702_default_language()
    st.session_state[LANG_STATE_KEY] = code
    return code


def fn705_set_language(lang: str) -> None:
    """Set the active language (no-op for an unknown code)."""
    code = str(lang or "").strip().upper()
    if code in fn701_languages():
        st.session_state[LANG_STATE_KEY] = code


def _fn703_field_map(lang: str | None = None) -> dict:
    fields = (fn700_load_translations() or {}).get("fields") or {}
    table = fields.get(lang or fn702_current_language())
    return table if isinstance(table, dict) else {}


def fn703_translate_field(col: str, fallback: str | None = None) -> str:
    """
    Translated label for raw column ``col``.

    ``fallback`` is the English label the caller already resolved; it is
    returned unchanged when the active language has no entry for ``col``
    (which is the whole of ENG, by design).
    """
    key = str(col or "").strip()
    if not key:
        return fallback if fallback is not None else ""
    label = _fn703_field_map().get(key)
    if isinstance(label, str) and label.strip():
        return label.strip()
    return fallback if fallback is not None else key


def fn704_t(key: str, fallback: str = "", **fmt) -> str:
    """
    Translated app-chrome string for ``key``, with ``{placeholder}`` formatting.

    Falls back to the active language's ENG entry, then to ``fallback``.
    """
    ui = (fn700_load_translations() or {}).get("ui") or {}
    text = ""
    for lang in (fn702_current_language(), _FALLBACK_LANG):
        table = ui.get(lang)
        if isinstance(table, dict):
            candidate = table.get(key)
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
                break
    if not text:
        text = fallback or key
    if fmt:
        try:
            text = text.format(**fmt)
        except Exception:
            pass
    return text


def _fn708_value_map(column: str, lang: str | None = None) -> dict:
    table = (fn700_load_translations() or {}).get("values") or {}
    table = table.get(lang or fn702_current_language())
    if not isinstance(table, dict):
        return {}
    col_map = table.get(column)
    return col_map if isinstance(col_map, dict) else {}


def fn708_translate_value(column: str, value) -> str:
    """
    Translated display text for a dataset *value* (Product Type, Material Type).

    Display-only: the English value stays the key everything else runs on —
    filtering, grouping and the per-product-type rules in the catalogue config.
    Lookup is exact, then case-insensitive (the data holds both ``Steel`` and
    ``steel``), then the value unchanged.
    """
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return raw
    col_map = _fn708_value_map(column)
    if not col_map:
        return raw
    hit = col_map.get(raw)
    if isinstance(hit, str) and hit.strip():
        return hit
    lowered = raw.lower()
    for key, label in col_map.items():
        if str(key).strip().lower() == lowered and isinstance(label, str) and label.strip():
            return label
    return raw


def fn709_value_maps_for_component(columns: dict[str, str] | None = None) -> dict:
    """
    Value maps for the catalogue component, keyed by its own JS field names.

    The cards live in an iframe, so they cannot call fn708 — ``lib_ui`` injects
    this as ``window.__VALUE_I18N__`` and the component's ``tv()`` helper reads
    it at the display sites only.
    """
    columns = columns or {
        "D__ProductType_ENG": "productType",
        "D__MaterialType_ENG": "materialType",
    }
    out: dict[str, dict] = {}
    for column, js_field in columns.items():
        col_map = _fn708_value_map(column)
        if col_map:
            out[js_field] = dict(col_map)
    return out


def fn710_add_italian_product_type(df, source_col: str = "D__ProductType_ENG",
                                   target_col: str = "D__ProductType_ITA"):
    """
    Derive ``D__ProductType_ITA`` from ``D__ProductType_ENG`` and the catalogue.

    The dataset ships ``D__MaterialType_ITA`` but has no Product Type
    counterpart; this adds one, the same way ``A__ProductName_Base`` and the
    ``PR__`` prices are derived at load time (see ``app.py``) rather than
    written back to Neon/parquet. Untranslated values carry through in English,
    so the column is never empty where the English one is populated.

    Returns ``df`` unchanged when the source column is missing or there is no
    Italian map to apply.
    """
    try:
        if source_col not in getattr(df, "columns", []):
            return df
        col_map = _fn708_value_map(source_col, "ITA")
        if not col_map:
            return df
        lowered = {str(k).strip().lower(): v for k, v in col_map.items()}

        def _translate(value) -> str:
            raw = "" if value is None else str(value).strip()
            if not raw:
                return raw
            return col_map.get(raw) or lowered.get(raw.lower()) or raw

        df = df.copy()
        df[target_col] = df[source_col].map(_translate)
        return df
    except Exception:
        return df


def fn711_t_page(title: str) -> str:
    """Translated page / tab-menu title, falling back to the English one."""
    raw = str(title or "").strip()
    if not raw:
        return raw
    pages = (fn700_load_translations() or {}).get("pages") or {}
    table = pages.get(fn702_current_language())
    if isinstance(table, dict):
        hit = table.get(raw)
        if isinstance(hit, str) and hit.strip():
            return hit
    return raw


def fn712_t_subtitle(subtitle: str) -> str:
    """Translated in-page sub-heading, falling back to the English one.

    Keyed by the exact English sentence written in the page, so pages keep
    reading as plain prose and only ``aux_16`` knows about the other language.
    """
    raw = str(subtitle or "").strip()
    if not raw:
        return raw
    subs = (fn700_load_translations() or {}).get("page_subtitles") or {}
    table = subs.get(fn702_current_language())
    if isinstance(table, dict):
        hit = table.get(raw)
        if isinstance(hit, str) and hit.strip():
            return hit
    return raw


def fn713_chrome_strings() -> dict:
    """
    Chrome strings for the catalogue component, English string → translation.

    The toolbar and filter bar live in an iframe, so ``lib_ui`` injects this as
    ``window.__CHROME_I18N__`` and the component translates its own markup once
    at boot. Empty in English, which leaves the component untouched.
    """
    chrome = (fn700_load_translations() or {}).get("chrome") or {}
    table = chrome.get(fn702_current_language())
    return dict(table) if isinstance(table, dict) else {}


def fn714_tu(text: str, **fmt) -> str:
    """
    Translated in-page control label, help string, caption or empty state.

    Keyed by the exact English string (``controls`` in the catalogue) rather
    than by an invented id, so a page keeps reading as plain English and
    wrapping a new string is a one-token change. ``**fmt`` fills ``{name}``
    placeholders, on the translation or on the English fallback alike.

    Selectbox OPTIONS go through this as a ``format_func``: the label shown
    translates while the value the code compares against stays English.
    """
    raw = str(text or "")
    if not raw.strip():
        return raw
    controls = (fn700_load_translations() or {}).get("controls") or {}
    table = controls.get(fn702_current_language())
    out = raw
    if isinstance(table, dict):
        hit = table.get(raw.strip())
        if isinstance(hit, str) and hit.strip():
            out = hit
    if fmt:
        try:
            out = out.format(**fmt)
        except (KeyError, IndexError, ValueError):
            pass
    return out


def fn707_translate_card_fields(config_json: str) -> str:
    """
    Translate the catalogue card's detail-row labels in a JS2 field config.

    ``config_json`` is the raw text of ``aux_07__js2_card_fields.json``, which
    libs/lib_ui injects as ``window.__JS2_FIELDS__``. The cards live inside an
    HTML component, so their labels never pass through fn703 — they are
    rewritten here, against ``card_labels.<lang>``, keyed on the English label.

    Returns the input unchanged on any problem, and whenever the active
    language has no card-label table (which is all of ENG, by design).
    """
    table = (fn700_load_translations() or {}).get("card_labels") or {}
    table = table.get(fn702_current_language())
    if not isinstance(table, dict) or not table:
        return config_json
    try:
        cfg = json.loads(config_json)
    except Exception:
        return config_json
    if not isinstance(cfg, dict):
        return config_json

    def _tr(label):
        if isinstance(label, str):
            swapped = table.get(label)
            if isinstance(swapped, str) and swapped.strip():
                return swapped
        return label

    try:
        for row in cfg.get("detail_rows") or []:
            if not isinstance(row, dict):
                continue
            if "label" in row:
                row["label"] = _tr(row["label"])
            by_size = row.get("labels_by_size")
            if isinstance(by_size, dict):
                row["labels_by_size"] = {k: _tr(v) for k, v in by_size.items()}
        return json.dumps(cfg, ensure_ascii=False)
    except Exception:
        return config_json


def fn706_render_language_selector(container=None) -> str:
    """
    Language switch — a native ``st.toggle``, flanked by the two flags.

    Rendered in the sidebar above the Filters block (see ``app.py``). It is a
    real Streamlit toggle rather than a hand-rolled control, so it carries the
    platform's own switch look, theming and keyboard behaviour; the flags and
    the active-side emphasis are markdown either side of it.

    The toggle is boolean, so it supports exactly two languages: ``codes[0]``
    when off, ``codes[1]`` when on. A catalogue with more than two would need a
    different widget — the first two win, and the rest are ignored.

    Returns the active language code.
    """
    target = container if container is not None else st.sidebar
    langs = fn701_languages()
    codes = list(langs.keys())
    if not codes:
        return _FALLBACK_LANG
    if len(codes) == 1:
        st.session_state[LANG_STATE_KEY] = codes[0]
        return codes[0]
    codes = codes[:2]

    current = fn702_current_language()
    if current not in codes:
        current = codes[0]

    widget_key = _LANG_WIDGET_KEY
    # Keep the toggle's own state in step with the resolved language — covers
    # the first run (no widget state yet) and a language set programmatically.
    # Only legal *before* the widget is instantiated below.
    st.session_state[widget_key] = (current == codes[1])

    def _on_language_change() -> None:
        # Callbacks run before the next run instantiates the widget, which is
        # the only place the widget's key may be written once it exists.
        st.session_state[LANG_STATE_KEY] = (
            codes[1] if st.session_state.get(widget_key) else codes[0]
        )

    def _side(code: str, active: bool) -> str:
        meta = langs.get(code) or {}
        label = str(meta.get("label") or code).strip()
        uri = _fn706_flag_data_uri(code, meta)
        flag = f"<img class='app-language-flag' src=\"{uri}\" alt=''>" if uri else ""
        cls = "app-language-side is-active" if active else "app-language-side"
        return f"<span class='{cls}'>{flag}<span>{label}</span></span>"

    target.markdown(
        f"<div class='app-language-label'>{fn704_t('app_language', 'App Language')}</div>"
        f"<style>{_FN706_TOGGLE_CSS}</style>",
        unsafe_allow_html=True,
    )
    left, mid, right = target.columns([5, 4, 5], vertical_alignment="center")
    left.markdown(_side(codes[0], current == codes[0]), unsafe_allow_html=True)
    mid.toggle(
        fn704_t("app_language", "App Language"),
        key=widget_key,
        label_visibility="collapsed",
        help=fn704_t("app_language_help", "") or None,
        on_change=_on_language_change,
    )
    right.markdown(_side(codes[1], current == codes[1]), unsafe_allow_html=True)

    # The toggle's return value is this run's state, which equals ``current``:
    # a flip reruns the script, and _on_language_change has already written the
    # new code to LANG_STATE_KEY by the time that run reaches here.
    st.session_state[LANG_STATE_KEY] = current
    return current
