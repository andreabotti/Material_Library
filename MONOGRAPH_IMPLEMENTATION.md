# Manufacturer Monograph tab — implementation spec

**Target:** EETRA MatLib, Streamlit 1.60 · **Written:** 2026-10-03 · **For:** an implementing agent (Cursor)

Read this whole document before writing code. Every function name, file path, column
name and line reference below was checked against the codebase on the date above. If
something doesn't match what you find, trust the code, and note the difference in your
summary.

---

## 1. Goal

Add a **Monograph** tab as the *first* tab of the Manufacturers page
(`pages/15_Manufacturers.py`). The user picks one manufacturer and gets a single
scrolling page about it, in this order:

1. **Picker.** Choose the manufacturer.
2. **Profile header.** The same company information the Directory tab's detail panel shows, plus 4 KPI tiles.
3. **Composition.** Two treemaps: product types and material types for this manufacturer.
4. **Data quality.** Completeness by field group, compared with the library average, and richness per product, with document counts.
5. **Catalogue.** The existing JS2 product-card component, filtered to this manufacturer and optionally narrowed further by a treemap selection.

Existing tabs keep working unchanged and keep their order after Monograph:
Directory, Credentials Matrix, Maturity Ranking.

### Decisions already made (do not re-litigate; flagged so the owner can change them)

| # | Decision | Default to implement |
|---|---|---|
| D1 | Sidebar dataset filters | **Ignored.** The monograph describes the whole manufacturer. Show a one-line caption saying so. |
| D2 | Name mismatches between dataset and profile JSONs | **Alias map** in a new `aux__manufacturer_aliases.json` (seed in §6). |
| D3 | Impact Framework specifiers / contractors (no products) | **Excluded** from the picker. Only manufacturers that have products appear. |
| D4 | Chart library | Plotly for the treemaps (to match the existing Developer treemap and its click selection); **Altair** for the bar and histogram charts. |
| D5 | Layout | One scrolling page, no sub-tabs. Heavy sections go in `@st.fragment`. |

---

## 2. Codebase conventions you must follow

These are hard-won rules in this repo. Breaking them causes real bugs.

1. **Page imports.** Every page starts with `from libs.page_imports import *`. That
   re-exports `st`, `pd`, `px`, `go`, `json`, `re`, `Path` and everything public from
   `libs.lib_data`, `libs.lib_charts`, `libs.lib_ui`, `libs.lib_header`, `libs.lib_tags`.
   No module defines `__all__`, so any public name (no leading underscore) is
   importable that way.
2. **Function naming.** Library helpers are numbered `fnNNN_snake_name`. New shared
   helpers go in a **new module** `libs/lib_monograph.py`, numbered `fn600`–`fn619`
   (that range is free). Page-private helpers start with `_`.
3. **Data source.** `app.py` loads the data on every run and puts it in session state:
   - `st.session_state["ORIGINAL_DATA"]`: the full effective dataset (base ⊕ edits,
     cleaned, with `A__ProductName_Base` and `PR__*` price columns). **Use this one** (D1).
   - `st.session_state["FILTERED_DATA"]`: the sidebar-filtered view. **Don't use it** here.
   - `st.session_state["df_filtered_ready"]`: False until data has loaded. If it's False,
     show `fn356_empty_state(...)` and `st.stop()`, exactly like `pages/2_Catalogue.py:49-54`.
   - Treat these frames as **read-only**. Never mutate them in place; work on `.copy()`
     or a boolean-mask subset.
   - The catalogue-visible rows are `A__Map_yn == "Y"`. Today all 1,609 rows are "Y",
     but apply the mask anyway, the same way `pages/2_Catalogue.py:57-62` does.
4. **Caching rules.**
   - `@st.cache_data` for anything derived from data. Set `max_entries` (or `ttl`) on
     every parameterised cache.
   - **Never name a cache-key parameter with a leading underscore.** Streamlit leaves
     `_`-prefixed parameters *out of the cache key*. This trap already bit this repo
     (`lib_prices._cached_read(_mtime_key)`, `lib_tags._cached_load_tags(_mtime_key)`, and
     `15_Manufacturers._build_payload(_mtimes, …)`). Use `mtime_key`, `data_sig`, and so on.
   - Don't pass large DataFrames as cache arguments when a scalar key will do: hashing
     the 1,609×135 frame costs ~44 ms. Key on `(manufacturer_name, data_sig)`, where
     `data_sig` is the tuple `st.session_state["_data_fingerprint"]` that `app.py`
     already builds (it changes whenever the parquet files or the row set change). Read
     the frame from session state *inside* the page, and pass it to the cached function
     as a parameter named `_df` (excluded from hashing on purpose; the signature carries
     the identity).
   - A cached function must not call `st.*` elements; they get replayed on cache hits
     and crash (`CacheReplayClosureError`).
5. **UI rules** (from `.claude/skills/developing-with-streamlit`):
   - **Never** use `use_container_width`. Use `width="stretch"` or `width="content"`.
   - Sentence case for every label and heading.
   - Page header: `fn003a_page_header("Manufacturers")` is already called once at the
     top of the page. Don't add another. Use `st.markdown("#### …")` or
     `st.subheader` for section titles.
   - Empty or error states: `fn356_empty_state(message, hint=..., kind="info"|"empty"|"warn"|"error")`.
   - Spinners: `with fn357_loading("…"):`.
6. **Lazy tabs and widget state.** Since 2026-10-03 this app uses lazy tabs
   (`st.tabs(..., on_change="rerun")` plus `if tab.open:`). Widgets inside a hidden tab are not
   rendered, so **Streamlit discards their state** and they reset when the user comes
   back. The helper `fn353a_keep_widget_state(*prefixes)` (in `libs/lib_ui.py`) re-saves
   plain widget values. Call it before `st.tabs(...)`. **Never pass a prefix that covers
   `st.button`, `st.download_button`, `st.file_uploader` or `st.data_editor` keys**:
   Streamlit raises on Session State writes to those. That's why every Monograph widget
   key below starts with `mono_`, and no button uses that prefix.
7. **Theme.** Visual values live in `theme.json` and `aux__*.json`. Don't hardcode new
   colours in Python. For chart fonts use `fn341_get_charts_dimensions()` (returns
   a dict with `chart_font_family` and `chart_font_size`, as used in
   `pages/5_Developer.py` around the treemap).

---

## 3. Files

| Action | Path | Purpose |
|---|---|---|
| **Create** | `libs/lib_monograph.py` | Pure data helpers (fn600–fn612). No page code. |
| **Create** | `aux__manufacturer_aliases.json` | Dataset name → profile/IFW name map (seed in §6). |
| **Modify** | `pages/15_Manufacturers.py` | Add the Monograph tab, make tabs lazy, extract the profile builder, fix the `_mtimes` cache-key bug. |
| **Create** | `pages/_monograph_section.py` *(optional, see §7.0)* | The Monograph UI, if you prefer to keep `15_Manufacturers.py` short. |
| **Create** | `05_tests/test_lib_monograph.py` | Unit tests for the pure helpers (§10). |
| **Modify** | `APP_DOCUMENTATION.md` | Short section describing the tab (§11). |

Don't touch `app.py`, `libs/lib_data.py` or `02_html/*` unless a step below says so.

---

## 4. Data model reference

### 4.1 Dataset columns (verified on `01_data/base_data.parquet`: 1,609 rows × 135 columns)

Columns are named `PREFIX__Name`. Prefix counts: G 24, E 18, VO 13, D 11, P 7, R 7,
VV 7, U 6, A 4, `0` 2, S 2.

Key columns:

| Column | Meaning |
|---|---|
| `0__EETRA_ID` | Product id (string). |
| `A__Manufacturer` | Manufacturer name: the join key. 84 distinct values. |
| `A__ProductName`, `A__ProductDescription`, `A__Map_yn` | Identity and catalogue flag. |
| `D__ProductType_ENG` | Product type (treemap 1). |
| `D__MaterialType_ENG` | Material type (treemap 2). |
| `D__*` | Other descriptors (`D__EN197-1`, `D__EN206`, `D__TechDetails`, …). |
| `G__GWP_A1A3` | GWP A1–A3 (numeric-like string). `G__GWP_FU` is the declared unit. |
| `E__*` | EPD metadata (`E__EPD_Y/N`, `E__EPD_Programme`, `E__EPD_RegNumber`, `E__EPD_URL`, `E__ManuCountry`, `E__ManuPlant`, …). |
| `P__*` | Physical properties (`P__Thick_mm`, `P__Mass_kgm3`, `P__L_WmK`, …). |
| `R__*` | Recycled content. |
| `VO__*` | VOC emissions (`VO__VOC_Cert`, …). |
| `VV__*` | CAM, DoP, LEED (`VV__CAM_Compliance`, `VV__DOP`, …). |
| `U__*` | URLs (`U__Img_URL`, …). |
| `S__*` | Status and comments (internal). |

Value conventions (same rules as `fn321`/`fn322` in `libs/lib_ui.py`):

- **Empty:** NaN, `""`, or `"-"`.
- **n/a (not available):** `n/a`, `n\a`, `na` (case-insensitive). Counts as **missing**.
- **n/r (not relevant):** `n/r`, `n\r`, `nr`. Counts as **not applicable** (exclude it from the
  denominator).

### 4.2 Profile sources

- `fn135_sustainability_credentials()` (in `libs/lib_data.py`) returns a dict with keys
  `sectors` (sector → list of names), `credential_labels`, `maturity_tiers`,
  `company_profiles` (name → `{hq, revenue, employees, ownership, countries, sector,
  parent, lat, lon, website, report_url, report}`), `credentials` (name →
  `{sbti, cdp, iso14001, ecovadis, sustainability_report, …, maturity}`), and `geocoding`.
- `fn140a_load_impact_framework()` returns the Impact Framework (IFW) JSON. Manufacturers are under
  `["entities"]["manufacturers"]`, keyed by name.
- `fn140b_manufacturer_impact_summary(name)` returns `{"pills": [{"label", "on"}...], ...}` or None.
- `_ifw_score_manufacturer(entity, weights)` (imported in `15_Manufacturers.py`) returns the score
  dict, with `["total"]`.
- Logos: `fn312_get_manufacturer_logo_mapping(str(_APP_ROOT / "aux__ui_config.json"))`
  maps a normalised (lowercase, single-spaced) name to `{"logo_path": ...}`.
  `_logo_data_uri(rel)` in `15_Manufacturers.py` turns that into a data URI.

**Name mismatch problem (D2).** 40 of the 84 dataset manufacturers don't match any
profile or IFW key exactly, for example `"Florim Ceramiche S.p.A. SB"` in the data vs `"Florim"`
in the profiles. §6 fixes this.

---

## 5. Step 1: extract the per-manufacturer profile builder (refactor, no behaviour change)

Today, `_build_payload` in `pages/15_Manufacturers.py` (around lines 419–595) builds each
manufacturer's record inside a loop (`for name in sorted(set(creds) | set(ifw_mfr)...)`).
The Monograph must show **exactly the same** profile, so pull the loop body out into a
function both callers use.

1. In `pages/15_Manufacturers.py`, create
   `_manufacturer_record(name, *, creds, profiles, labels, mfr_sector, ifw_mfr, weights, tier_rank, fw_matrix, logo_fn, n_products) -> dict`.
   It returns exactly the dict currently appended to `out["manufacturers"]`. Move the loop
   body into it verbatim. The loop then becomes `out["manufacturers"].append(_manufacturer_record(...))`.
2. Keep it in `15_Manufacturers.py`. It depends on page-private helpers (`_Sources`,
   `_profile_rows`, `_cred_status`, `_norm_tier`, `_framework_hits`, `_ifw_groups`).
   Moving all of those into a lib is a bigger refactor that isn't needed here.
3. **Fix the cache-key bug while you're there.** `_build_payload(_mtimes, product_counts)`
   leaves `_mtimes` out of the key, so editing the JSONs never invalidates it. Rename the
   parameter to `mtimes` and update the one call site in `_render_directory()`.
4. Also fix `_product_counts()` (around line 597). It's `@st.cache_data` with no key, so
   product counts never refresh after an edit. Give it a parameter
   `data_sig: tuple` and call it with `st.session_state.get("_data_fingerprint")`.
5. **Verify:** the Directory iframe renders identically before and after. Compare
   `json.dumps(_build_payload(...), sort_keys=True)` before and after the refactor. It
   must be byte-identical.

---

## 6. Step 2: alias map

Create `aux__manufacturer_aliases.json` in the project root:

```json
{
  "_note": "Dataset A__Manufacturer -> key used in aux_companies_sust_credentials.json / aux_companies_impact_framework.json. Entries marked VERIFY were fuzzy-matched; confirm each one.",
  "aliases": {
    "Agglo Baghin S.r.l": "Agglo Baghin",
    "Ceramica Fondovalle S.p.A (Italcer Group)": "CERAMICA FONDOVALLE (ITALCER)",
    "Ceramica del Conca S.p.A.": "Ceramica del Conca",
    "Ceramica d’Imola s.c.": "Ceramica Imola",
    "Ceramiche CCV Castelvetro": "CCV Castelvetro",
    "Ceramiche La Fenice S.r.l.": "La Fenice S.r.l.",
    "Ceramiche Piemme": "Ceramica Piemme",
    "Florim Ceramiche S.p.A. SB": "Florim",
    "Giussani Enrico & figli S.r.l.": "Giussani Enrico & figli srl",
    "Gold Art Ceramica S.p.A.": "Gold Art",
    "Heidelberg Materials Italia Cementi": "Heidelberg Materials",
    "Industrie Riunite Odolesi I,R,O": "Acciaierie Riunite Odolesi I.R.O.",
    "Laminam S.p.A.": "Laminam",
    "Marazzi Group": "Marazzi",
    "Marmi Scala S.r.l.": "Marmi Scala",
    "Newfloor S.r.l.": "Newfloor",
    "Panaria Group": "Panaria",
    "SIL GROUP": "SIL Group",
    "CIPA GRES S.p.A.": "IPA GRES",
    "Gruppo Romani S.p.A.": "Gruppo Roma",
    "Mirage Granito Ceramico S.p.A.": "Rage Granito",
    "Tecnocanapa": "nocanapa"
  },
  "verify": ["CIPA GRES S.p.A.", "Gruppo Romani S.p.A.", "Mirage Granito Ceramico S.p.A.", "Tecnocanapa"]
}
```

These dataset names had **no plausible match** and must render "no profile yet"
(don't invent aliases for them): ALU-PRO, Atena S.p.A., BWR, Beton Lana, BetonRossi,
Cementirossi, Colacem, Confindustria Ceramica, DIMA, Fornaci Calce Grigolin S.p.A.,
Hunterdouglas, IPM ITALIA SRL, Iris Ceramica Group, Isolpack, Mapei, Swisspacer,
Technoform, Unical.

> Note: `"Ceramica d’Imola s.c."` contains a typographic apostrophe (U+2019) in the
> data. Keep it as `’` in the JSON.

The resolver goes in `lib_monograph.py` (§8, `fn601`).

---

## 7. Step 3: the page

### 7.0 Where the code lives

`15_Manufacturers.py` is about 700 lines. Put the Monograph UI in a function
`_render_monograph()` in **`pages/15_Manufacturers.py`**, because it needs
`_manufacturer_record`, `_logo_data_uri` and the other page-private helpers. If it grows past
about 250 lines, move the pure-UI parts into `pages/_monograph_section.py` and import from
there, but keep `_manufacturer_record` where it is.

### 7.1 Tab bar (replace the current `st.tabs` call around line 647)

```python
fn353a_keep_widget_state("mono_", "mfr_matrix_", "mfr_rank_")
tab_mono, tab_dir, tab_matrix, tab_rank = st.tabs(
    ["Monograph", "Directory", "Credentials matrix", "Maturity ranking"],
    on_change="rerun",
    key="mfr_active_tab",
)
if tab_mono.open:
    with tab_mono:
        _render_monograph()
if tab_dir.open:
    with tab_dir:
        ...existing body...
```

- Wrap each existing `with tab_x:` block in `if tab_x.open:` and indent its body. Move
  `_sust = fn135_sustainability_credentials()` *above* the tabs, because the matrix and
  ranking tabs both use it.
- **Check before indenting:** none of the three existing tab bodies uses a variable
  assigned only in another tab's body. Today they don't, but check again after your
  refactor.
- The labels change to sentence case ("Credentials matrix", "Maturity ranking"). That is
  intentional.
- `mfr_matrix_` and `mfr_rank_` cover only selectbox and text_input keys (`*_sector`,
  `*_tier`, `*_q` in `_table_filters`), so the prefix is safe.

### 7.2 `_render_monograph()`: skeleton

```python
def _render_monograph() -> None:
    if not st.session_state.get("df_filtered_ready"):
        fn356_empty_state("Loading data…", hint="Give it a moment, or check the data source on Welcome.")
        return
    df_all = st.session_state.get("ORIGINAL_DATA", pd.DataFrame())
    if df_all.empty or "A__Manufacturer" not in df_all.columns:
        fn356_empty_state("No product data available.", kind="warn")
        return
    if "A__Map_yn" in df_all.columns:
        df_all = df_all[df_all["A__Map_yn"].astype(str).str.strip().str.upper() == "Y"]
    data_sig = st.session_state.get("_data_fingerprint") or (len(df_all),)

    name = _monograph_picker(df_all, data_sig)          # 7.3
    if not name:
        return
    df_m = fn602_manufacturer_rows(df_all, name)         # boolean subset, no copy needed
    st.caption("Showing every product from this manufacturer. Sidebar filters don't apply on this tab.")

    _monograph_header(name, df_m, df_all, data_sig)      # 7.4
    selection = _monograph_composition(df_m, name, data_sig)   # 7.5 → (column, value) | None
    _monograph_quality(df_m, df_all, name, data_sig)     # 7.6
    _monograph_catalogue(df_m, selection)                # 7.7
```

### 7.3 Picker

- Options are the manufacturers that have products: `fn600_manufacturer_options(_df, data_sig)`
  returns `[(name, n_products), ...]`, sorted by `n_products` descending, then name.
- Use `st.selectbox("Manufacturer", options=[n for n, _ in opts], format_func=lambda n: f"{n}  ·  {counts[n]} products", key="mono_manufacturer", index=None, placeholder="Choose a manufacturer")`.
  Streamlit's selectbox has type-to-search built in.
- **Deep link.** Read `st.query_params.get("mfr")` on first render. If it's a valid
  name and `mono_manufacturer` isn't in session state yet, set
  `st.session_state["mono_manufacturer"] = qp` **before** creating the widget. When the
  selection changes, write it back with `st.query_params["mfr"] = name`. Only touch the
  `mfr` key, so other params such as `open_product` survive. (Note: the app's `st.navigation`
  pages have default URL paths, so `/Manufacturers?mfr=Knauf` works.)
- With nothing selected, show `fn356_empty_state("Choose a manufacturer to see its monograph.", kind="empty")`
  and return None.

### 7.4 Profile header and KPIs

**Profile.** Resolve the profile name with `fn601_resolve_profile_name(name)` (alias, then
an exact match, then a case-insensitive match). Then build the record:

- Reuse `_manufacturer_record(...)`. Get its inputs the same way `_build_payload` does
  (`fn135_sustainability_credentials()`, `fn140a_load_impact_framework()`, and so on). Wrap
  the call in a cached function `_mono_profile(profile_name, mtimes)` with
  `@st.cache_data(max_entries=64)`, where `mtimes` is the same JSON-mtime tuple
  `_render_directory()` computes from `_DATA_FILES`.
- If no profile matches: still render the header (name, logo if one exists, product count)
  plus a muted note: "No company profile yet for this manufacturer."

**Render** with native elements (no new iframe):

```
[logo 56px]  ### {name}
             {sector} · HQ {hq} · [website](url)
             :green-badge[SBTi] :green-badge[ISO 14001] :gray-badge[CDP]  :blue-badge[Tier: Advanced]
```

- Layout: `st.container(horizontal=True, vertical_alignment="center")`, with the logo as
  `st.image(data_uri, width=56)` (skip it if there's no logo) and a text column.
- Badges: `st.badge(label, color=...)` or the markdown `:color-badge[...]` syntax. Use
  green for `state == "ok"`, orange for `"partial"`, gray for `"off"`/`"no"` (use the
  record's `pills` list as-is), and blue for the tier.
- Below that, a two-column `st.container(border=True)` lists the record's `profile` rows
  (`[label, value, …]`). Values may hold HTML anchors for websites (see `_profile_rows`).
  Render those through `st.markdown(..., unsafe_allow_html=True)`, escaping every
  non-link value with `html.escape`.
- If the record has a non-empty `narrative`, show it in
  `st.expander("Sustainability summary")`.
- If `reportUrl` is set, add `st.link_button("Sustainability report", url, icon=":material/description:")`.

**KPI tiles:** 4 `st.metric` in `st.container(horizontal=True)`:

| Tile | Value | Delta / help |
|---|---|---|
| Products | `len(df_m)` | help: "Catalogue-listed products (A__Map_yn = Y)" |
| With EPD | % of rows where `E__EPD_Y/N` is truthy (`y`, `yes`, `si`, `sì`, `1`, `true`, case-insensitive), **or** where `E__EPD_RegNumber` / `E__EPD_URL` is non-empty | delta vs library: `f"{pct - lib_pct:+.0f} pp vs library"` |
| Median GWP A1–A3 | median of `pd.to_numeric(G__GWP_A1A3, errors="coerce")` | **No library delta**: GWP is only comparable within a product type and declared unit. Show the unit if `G__GWP_FU` has one dominant value (≥80%), otherwise "mixed units". |
| Data completeness | `fn604` overall % (§8) | delta vs library average, in pp |

### 7.5 Composition: treemaps

Two columns (`st.columns(2)`, gap "medium"), each with:

- A title: `#### Product types` or `#### Material types`.
- Data: `fn603_value_counts(_df_m, column, mfr, data_sig)`. It wraps
  `fn322_get_value_counts_for_treemap(df_m, column, top_n=12, include_empty=True, include_na=False, include_nr=False, include_symbols=False)`
  in a cache with `max_entries=128`. Relabel the `(empty)` bucket as "Not specified".
- Chart: `px.treemap(vc_df, path=["value"], values="count", custom_data=["value"])`,
  with `update_traces(textinfo="label+value", hovertemplate="<b>%{label}</b><br>%{value} products<extra></extra>")`,
  `update_layout(margin=dict(l=0, r=0, t=0, b=0), height=260, font=dict(family=dims["chart_font_family"], size=dims["chart_font_size"]))`.
- Render with `st.plotly_chart(fig, width="stretch", key=f"mono_tm_{slug}", on_select="rerun", selection_mode="points", config={"displayModeBar": False})`.
  The plotly selection value is a dict, which `fn353a` skips, so the key prefix is safe.
- **Reading the selection:** copy the parsing loop from `pages/5_Developer.py` around lines
  1080–1100 (`_tm_event.selection.points` → `customdata[0]`, ignoring
  `"root"`/`""`/`"(?)"`/`"/"`, and only accepting values in `vc_df["value"]`).
- **Only one active filter.** Store it in `st.session_state["mono_tm_filter"] = (column, value)`.
  A click on the other treemap replaces it. Show it as a chip above the catalogue with a
  "Clear" `st.button(key="monoclear_tm_filter")`. Note the key is **not** `mono_` prefixed,
  so `fn353a` never re-saves a button. Clicking Clear pops `mono_tm_filter`.
- **Reset the filter when the manufacturer changes.** Keep
  `st.session_state["mono_tm_filter_for"] = name` and drop the filter if it differs.
- With a single value (100% one type), still render the treemap. It's informative.
  With an empty `vc_df`, show `st.caption("No values recorded.")`.
- Return the active `(column, value)` tuple or None.

### 7.6 Data quality

Two columns.

**Left: completeness by field group** (`fn604_completeness_by_group`, §8).

- An Altair horizontal bar chart: y = group label (fixed order, §8), x = completeness %
  (0–100), bars in the theme accent colour. Add a `tick` mark layer (or a `rule` with
  `strokeDash=[3,3]`) at the **library average** for the same group, computed with the same
  function over `df_all`.
- Tooltip: group, % for this manufacturer, % for the library, filled / applicable cells.
- Caption: "Dashed tick = library average. Fields marked not relevant (n/r) or hidden for
  a product type are excluded."
- `st.altair_chart(chart, width="stretch")`, height around 220.

**Right: richness per product** (`fn605_richness_per_product`, §8).

- An Altair histogram of each product's completeness score, in 5 bins
  (0–20 … 80–100%). Use `alt.X("bin_label:O", sort=[...])`, not automatic binning, so the
  labels are stable.
- Under it, the document coverage line from `fn606_document_counts`:
  `EPD 110 · TDS 96 · VOC 41 · DoP 22 · SDS 9 · CAM 30 · RC 12` (counts of products
  having each document). Render as `st.caption`, or as small `st.metric`s in a horizontal
  container if it fits.

**Optional, off by default:** `st.toggle("Show product × field heatmap", key="mono_show_heatmap")`.
When on, render the existing missing-data heatmap for `df_m`:

- Reuse the Developer code path at `pages/5_Developer.py:1181-1207`:
  ```python
  payload = fn344_build_dev_missmatrix_payload(df_m, cols, id_col=None, batch_size=30)
  h = min(920, max(520, 220 + 30 * 20))
  st.iframe(fn240_build_dev_missmatrix_html(payload, height=h), height=h)
  ```
  `fn240_build_dev_missmatrix_html` is in `libs/lib_charts.py`.
- **Column selection gotcha:** the Developer page filters with
  `_DEV_COL_PREFIX_RE = re.compile(r"^([A-Z]__)")`, which only matches **single-letter**
  prefixes, so it silently drops `VO__*` and `VV__*`. For the monograph, select the columns
  from `FIELD_GROUPS` (§8) instead, so the heatmap and the completeness bars cover the same fields.
- Put it inside `@st.fragment` so toggling doesn't rerun the whole page.

### 7.7 Catalogue

```python
@st.fragment
def _monograph_catalogue(df_m: pd.DataFrame, selection) -> None:
    df_cards = df_m
    if selection:
        col, val = selection
        df_cards = fn322a_rows_matching_treemap_value(df_m, col, val)
    st.markdown(f"#### Products · {len(df_cards)}")
    if df_cards.empty:
        fn356_empty_state("No products match this selection.", kind="empty"); return
    df_cards = df_cards.sort_values("A__ProductName", kind="mergesort") if "A__ProductName" in df_cards else df_cards
    try:
        from libs.lib_prices import fn512_price_tables_payload
        price_tables = fn512_price_tables_payload(df_cards)
    except Exception:
        price_tables = {}
    from libs.lib_html import CATALOGUE_JS2_COMPONENT_PATH
    fn336_render_catalogue_flipcard(
        df_cards,
        cols=6,
        height=max(int(_lib_ui.CATALOGUE_STREAMLIT_GRID_HEIGHT_PX), fn359_iframe_height("catalogue_js")),
        _component_path=CATALOGUE_JS2_COMPONENT_PATH,
        price_tables=price_tables,
    )
```

Notes:

- `fn336_render_catalogue_flipcard` (`libs/lib_ui.py`, search for `def fn336_render_catalogue_flipcard`)
  caches its payload keyed on the frame. Since 2026-10-03 it writes the product rows to
  `static/cat_cache/<md5>.json` and the iframe fetches them, so a per-manufacturer subset
  is cheap (a few KB to a few hundred KB).
- `CATALOGUE_STREAMLIT_GRID_HEIGHT_PX` is injected into `libs.lib_ui_catalogues` at import
  time (`lib_ui_catalogues.py:508`, from `aux__catalogue_layout.json`) and re-imported by
  `libs/lib_ui.py:162`. `2_Catalogue.py` reads it as `_lib_ui.CATALOGUE_STREAMLIT_GRID_HEIGHT_PX`;
  do the same (`import libs.lib_ui as _lib_ui`) so you get the live value.
- **Document panel and "Edit item":** the catalogue card posts bridge messages
  (`eetra:viewDocuments`, `eetra:editItem`). On this page they're optional. Locally
  mirrored PDFs open client-side with no bridge at all. **Don't** copy the Catalogue
  page's bridge handling in v1. Mention it under "Follow-ups" in your summary instead.
- **Don't** pass `open_product` / `doc_preview` in v1.

---

## 8. Step 4: `libs/lib_monograph.py`

Module docstring: the purpose plus the list of functions, in the style of the other libs. Imports:
`from __future__ import annotations`, `json`, `re`, `unicodedata`, `Path`, `pandas as pd`,
`streamlit as st`, and from `.lib_ui` import `fn319_filter_columns_by_visibility`,
`fn322_get_value_counts_for_treemap`.

```python
_APP_ROOT = Path(__file__).resolve().parent.parent
_ALIASES_PATH = _APP_ROOT / "aux__manufacturer_aliases.json"
```

### fn600_manufacturer_options(_df, data_sig) -> list[tuple[str, int]]
`@st.cache_data(max_entries=4, show_spinner=False)`. `value_counts()` of
`A__Manufacturer.astype(str).str.strip()`, dropping `""`, `"-"`, `"nan"`. Sort by count
descending, then `str.lower` ascending.

### fn601_resolve_profile_name(name, known_names: frozenset[str]) -> str | None
- Load the aliases with a module-level memo keyed on the file's mtime (same pattern as
  `_UI_CONFIG_MEMO` in lib_data; plain `os.stat` is fine).
- Order: alias hit (if the target is in `known_names`), then exact match, then a match on a
  normalised key (casefold, NFKC, collapse whitespace, map `’`→`'`), then None.
- Pure function, no Streamlit. `known_names` is the union of `credentials`, `company_profiles`
  and IFW manufacturer keys, which the caller computes.

### fn602_manufacturer_rows(df, name) -> pd.DataFrame
Boolean subset `df[df["A__Manufacturer"].astype(str).str.strip() == name]`. Don't copy.

### fn603_value_counts(_df_m, column, manufacturer, data_sig) -> pd.DataFrame
`@st.cache_data(max_entries=128, show_spinner=False)`. Calls `fn322` as specified in
§7.5 and renames `(empty)` to "Not specified".

### Field groups (module constant)

```python
FIELD_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Identity",        ("A__", "D__")),
    ("Physical",        ("P__",)),
    ("EPD and GWP",     ("E__", "G__")),
    ("Recycled content", ("R__",)),
    ("VOC emissions",   ("VO__",)),
    ("CAM and documents", ("VV__",)),
]
EXCLUDED_COLUMNS = {"0__EETRA_ID", "A__Map_yn", "A__ProductName_Base", "D__DataComments"}
# Also exclude: every "S__*" column (internal status), "U__*" (URLs counted under documents),
# "PR__*" (derived list prices) and any "*_CM" provenance flag column.
```

**Watch the prefix-match trap:** `"VO__"` must not be swallowed by a `"V"` check, and
`"VV__"` must not match `"VO__"`. Match on the full `PREFIX__` string with
`col.startswith(prefix)`, where every prefix ends in `__`.

### fn604_completeness_by_group(_df, scope_key, data_sig) -> pd.DataFrame
`@st.cache_data(max_entries=128)`. `scope_key` is the manufacturer name or `"__library__"`.

For each row, find its product type (`D__ProductType_ENG`). For each group and each column
in the group:

1. **Applicable?** The column is applicable for that row's product type when it survives
   `fn319_filter_columns_by_visibility([col], prefix_letter, product_type)`, where
   `prefix_letter` is the part before `__` (`"P"`, `"VO"`, …). That is the same
   per-product-type visibility the Developer "Tabular data" view uses, configured in
   `aux__ui_config.json`. Cache the visibility lookup per `(product_type, prefix)`, because
   `fn318` reads config.
2. **Not relevant?** Cell value `n/r` means not applicable, so exclude it from the denominator.
3. **Filled?** Not empty, not `-`, not `n/a`.

Vectorise it. Compute three boolean masks per column (`empty_or_na`, `nr`, `applicable`)
with `str.strip().str.lower()` on `astype(str)`, once per column. Don't loop over rows
in Python.

Return columns `group, filled, applicable, pct` (pct = 100 × filled / applicable,
or NaN when applicable == 0), plus a final row `("Overall", Σfilled, Σapplicable, pct)`.
Keep `FIELD_GROUPS` order.

### fn605_richness_per_product(_df, scope_key, data_sig) -> pd.DataFrame
`@st.cache_data(max_entries=64)`. Uses the same masks as fn604, but sums **per row**
across all groups: `filled_n`, `applicable_n`, `pct`. Adds `bin_label` with labels
`["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]`; a pct of exactly 100 goes in the
last bin. Factor the shared mask building into a private `_cell_masks(df)` so fn604 and
fn605 can't drift apart.

### fn606_document_counts(df) -> dict[str, int]
Counts products that have a non-empty `http…` URL in each document column. **Verify these
names against the dataset before relying on them.** Check
`libs/lib_ui.py` around lines 4820–4870, where the catalogue payload maps raw columns to
`epdUrl`, `techDetailsUrl`, `dopUrl`, `recyclingUrl`, `vocUrl…`, and use the same source
columns.

| Label | Source column(s) |
|---|---|
| EPD | the column mapped to `epdUrl` (expected `E__EPD_URL`) |
| TDS | the column mapped to `techDetailsUrl` |
| VOC | the columns mapped to `vocUrlPrimary` / `vocUrlAlt` (count once if either exists) |
| DoP | the column mapped to `dopUrl` |
| SDS | the column mapped to `msdsUrl` |
| CAM | `VV__CAM_Compliance` when it holds a URL |
| RC | the column mapped to `recyclingUrl` |

Return them in the table's order. Missing columns are simply skipped.

### fn607_kpis(df_m, df_all) -> dict
Returns `{"n": int, "epd_pct": float, "epd_pct_lib": float, "gwp_median": float|None,
"gwp_unit": str|None}` as specified in §7.4. Pure, no cache needed (it's cheap), or
`max_entries=64` keyed like the others.

---

## 9. Performance budget

- Switching manufacturers: **≤ 1.0 s server time** on a warm cache, measured with
  `AppTest` (see §10). Cold first visit: ≤ 3 s.
- A treemap click reruns everything except the cached computations. The catalogue fragment
  re-renders with the filtered subset.
- No cached function receives an un-underscored DataFrame parameter.
- No `iterrows` / `apply(axis=1)` over the dataset.

---

## 10. Tests

### 10.1 Unit tests: `05_tests/test_lib_monograph.py` (pytest)

Build small synthetic frames. Don't read the real parquet.

1. `fn601`: alias hit; exact match; normalised match (`"Ceramica d’Imola s.c."` vs the ASCII-apostrophe variant); no match returns None; an alias pointing at an unknown target returns None.
2. `fn604`: one product type, three columns: one filled, one `n/a`, one `n/r` → `filled=1, applicable=2, pct=50`. Empty and `"-"` count as missing. A group with zero applicable cells → pct NaN, and it is still present in the output.
3. Prefix trap: columns `VO__X` and `VV__Y` land in different groups.
4. `fn605`: per-row pct, and the bin edges (0, 20, 100 → first, second, last bin).
5. `fn606`: non-URL text (`"yes"`, `"-"`) isn't counted; an `http` URL is.
6. `fn600`: sorted by count, then name; blank names dropped.

`fn319` reads app config. In tests, monkeypatch
`libs.lib_monograph.fn319_filter_columns_by_visibility` to `lambda cols, p, t: cols`.

### 10.2 Page smoke test (AppTest)

Note: Streamlit 1.60's `AppTest.session_state` has **no `.get()`**. Use
`key in at.session_state` and `at.session_state[key]`.

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=300)
at.session_state["auth_user"] = "perf_test"; at.session_state["auth_role"] = "admin"
at.run(); at.switch_page("pages/15_Manufacturers.py"); at.run()
assert not at.exception
at.selectbox(key="mono_manufacturer").set_value("Knauf").run()
assert not at.exception and not at.error
# switch tabs and back: the selection must survive (fn353a)
at.session_state["mfr_active_tab"] = "Directory"; at.run()
at.session_state["mfr_active_tab"] = "Monograph"; at.run()
assert at.selectbox(key="mono_manufacturer").value == "Knauf"
```

Run it with the project root on `PYTHONPATH`, from the project root. Also select a
manufacturer that has **no profile** (for example `"Unical"`, which has 588 products and no profile)
and one with a single product. Neither may raise an exception.

> The existing suite has 10 **pre-existing** failures (stale `session_state.get`, a
> portalocker API mismatch, and `test_delete_item_flow` assuming 0 tombstones in the real
> edit log). Don't "fix" them as part of this task. Just make sure the count doesn't go up.

### 10.3 Manual browser check

`streamlit run app.py --server.port 8502`, sign in with the demo account (demo/demo, a
built-in test account), then go to Manufacturers → Monograph and check:

- [ ] The picker searches as you type; the counts are right.
- [ ] `?mfr=Knauf` in the URL opens straight to Knauf.
- [ ] The header matches the Directory panel for the same company (sector, HQ, pills, tier).
- [ ] A no-profile manufacturer shows the "No company profile yet" note, with no errors.
- [ ] Treemap click → the catalogue narrows; the chip shows the filter; Clear resets it.
- [ ] Changing manufacturer clears the treemap filter.
- [ ] The completeness bars show dashed library ticks; hovering shows both percentages.
- [ ] The catalogue cards open the detail panel; local PDFs open in the Documents tab.
- [ ] Monograph → Directory → Monograph keeps the selected manufacturer.
- [ ] Dark mode (Settings → Theme) stays readable.

---

## 11. Documentation

Add a short "Manufacturers → Monograph" subsection to `APP_DOCUMENTATION.md`: what each
section shows, the D1 note (sidebar filters ignored), how completeness is defined (n/r
excluded, product-type visibility respected), and the alias file plus how to add an entry.

Update the module docstring at the top of `pages/15_Manufacturers.py` (the "Tabs:" list).

---

## 12. Definition of done

- [ ] Monograph is the first tab; the three existing tabs render as before.
- [ ] Directory payload is byte-identical before and after the §5 refactor.
- [ ] The `_build_payload` and `_product_counts` cache-key bugs are fixed (§5.3–5.4).
- [ ] `aux__manufacturer_aliases.json` exists; VERIFY entries are listed in the summary for the owner.
- [ ] All the §10.1 unit tests pass; the §10.2 smoke test passes; the pre-existing failure count is unchanged.
- [ ] No `use_container_width`, no underscore-named cache keys, no `iterrows` on the dataset.
- [ ] Switching manufacturers is ≤ 1 s warm (state the measured number in your summary).
- [ ] `APP_DOCUMENTATION.md` and the page docstring are updated.

## 13. Out of scope (list as follow-ups, don't build)

- Document-panel bridge (`eetra:viewDocuments` / `eetra:editItem`) on this tab.
- Comparing two manufacturers side by side.
- Exporting the monograph as PDF.
- Linking Directory cards to the monograph (`?mfr=`). It's easy once this exists, but
  it touches `02_html/manufacturers_component.html`.
