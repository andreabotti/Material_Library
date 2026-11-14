# MatLib — performance on Streamlit Community Cloud

| | |
|---|---|
| **Scope** | `app.py` · `libs/` · `pages/` · `requirements.txt` · repo contents |
| **Deployment** | Streamlit Community Cloud (1 shared vCPU, ~2.7 GB RAM per app, container sleeps when idle) |
| **Dated** | 14 November 2026 |
| **Status** | Findings 1, 3, 6 and 7 implemented — see *What was done* below. 2, 4, 5 and 8 open. |

This follows on from `20260915__Optimisation_Register.md`, which measured the app
on a local workstation. Community Cloud changes which costs matter: CPU is one
shared core, RAM is a hard ceiling shared by **all concurrent sessions**, the
container is wiped and rebuilt on every wake, and anything not in git does not
exist at boot. Several things that were fine locally are the dominant cost there.

Everything below was measured on this checkout, not estimated from reading.

---

## What was done

Findings 1, 3, 6 and 7 are implemented in `libs/lib_ui.py` and `libs/lib_data.py`.
Measured after, on this checkout:

| | Before | After |
|---|---|---|
| Catalogue gzip, per rerun (6.5 MB test payload) | 87 ms | **0.012 ms** on a memo hit |
| Effective dataset, resident | 13.9 MB | **7.2 MB** |
| `edits_data.parquet` at load | 35.7 MB | **11.6 MB** |
| `import libs.lib_data` | 579 ms | **26 ms** |
| `import libs.page_imports` (what every page pays) | 3.15 s | **2.61 s** |
| `aux_09` range index, per rerun | ~10 ms + 1 MB garbage | cached |

Verification: the gz blob round-trips through gzip+base64 to the identical row
list, and the effective frame is **value-identical** to the one the old code
produced (`DataFrame.equals` on the stringified frames, 1,688 × 131).

Test suite: **3 failed / 122 passed** with these changes, against **9 failed /
116 passed** on the same checkout with them stashed. The 3 remaining failures
are a strict subset of the baseline 9, pass in isolation, and are pre-existing
order-dependent flakiness in `test_monograph_page.py` and
`test_new_item_visibility.py` — not regressions, and not touched by this work.

One correction to the original estimate below: §3 projected the saving against
the *raw* parquet sizes (~48 MB), but `fn122_clean_dataframe` cuts the frame to
1,688 × 131 before any session sees it, so the resident saving is 13.9 → 7.2 MB
per copy rather than the larger figure implied. The peak-memory saving during
merge is the bigger half of the win, and that one is as described.

---

## Headline

| Finding | Cost on Community Cloud | Fix effort |
|---|---|---|
| 1. Catalogue payload gzipped on every rerun | ~0.3 s local → **~0.7–1 s per Catalogue rerun** on 1 vCPU | Small |
| 2. 1,228 webp image tiers are gitignored, 53 MB of originals are not | **Minutes of PIL work after every wake**, repeated | Medium |
| 3. `string[python]` dtypes across the dataset | **3.3× more RAM** than needed, per session | Small |
| 4. Two full DataFrame copies per session in `session_state` | RAM scales linearly with concurrent users | Medium |
| 5. `fn110_cached_fetch_image` caches PIL objects, `max_entries=1024` | Up to **~490 MB** of one 2.7 GB budget | Small |
| 6. `office365` + `msal` imported at module scope | **~0.55 s** of every cold boot, for a non-default data source | Small |
| 7. `aux_09` range index re-serialised per rerun | ~10 ms + 1 MB garbage per Catalogue rerun | Trivial |
| 8. Dead out-of-band payload path (`_fn336_static_products_url`) | — | Decide |

---

## 1. The catalogue payload is gzipped on every rerun — the biggest single CPU cost

`libs/lib_ui.py:5694` `_fn336_inline_products_js()` gzips the ~11 MB products
JSON at `compresslevel=6` and base64-encodes it into the iframe srcdoc. It is
**not cached** — `_fn336_cached_catalogue_payload` caches the JSON *string*, but
the compression runs fresh on every single rerun of the Catalogue page: every
search keystroke, tag toggle, filter change, document-rail open.

Measured on this machine against an 11 MB blob:

| compresslevel | time | output |
|---|---|---|
| 9 | 273 ms | 0.71 MB |
| **6 (current)** | **133 ms** | 0.73 MB |
| 1 | 65 ms | 0.96 MB |

Community Cloud's shared vCPU is roughly 3–5× slower than this under load, so
budget **0.4–0.7 s of pure compression per rerun**, before anything renders.

**Fix.** Move the gzip+base64 inside `_fn336_cached_catalogue_payload` (or wrap
`_fn336_inline_products_js` in its own `@st.cache_data(max_entries=4)` keyed on
the JSON). It is a pure function of `products_json` — the cache key already
exists. That takes the per-rerun cost to zero on a hit.

Secondary: `compresslevel=1` costs 0.23 MB more over the wire and saves half the
CPU. Worth it on Cloud if, for any reason, the call cannot be cached.

### Related: the cached payload is copied on every hit

`_fn336_cached_catalogue_payload` is `@st.cache_data`, which pickles the return
value and **unpickles a fresh copy on every hit** — ~11 MB of string churn per
rerun, plus `max_entries=4` × 11 MB held. The payload is read-only (it is
immediately serialised into the srcdoc), so `@st.cache_resource` would hand back
the same object with no copy. The same argument already justified
`fn158c_cached_load_clean_effective_live` being a `cache_resource` (see its
docstring) — this is the same case.

---

## 2. The image tiers are not deployed, so Cloud rebuilds them every wake

```
01_data/img/       53 MB   552 originals   TRACKED in git
static/img_cache/  12 MB   1,228 webp tiers   GITIGNORED (.gitignore:50)
```

This is exactly backwards for Cloud. The September work established that the
grid loads the 200 px tier and the detail panel the 400 px tier, and that
`01_data/img` originals are "never written — only ever read". But on Community
Cloud:

- the clone pulls **53 MB of originals the app never shows directly**;
- `static/img_cache` arrives empty, so `fn110_cached_fetch_image` falls through
  its local tiers and PIL-decodes + downscales **552 originals into 1,228 webp
  files at runtime**, on one shared core;
- the container is ephemeral — that work is thrown away and redone on **every**
  reboot, every wake from sleep, every redeploy.

There is a further trap in the comment at `libs/lib_ui.py:6006`: `/app/static`
returns SPA HTML on Community Cloud, so even once the tiers exist they may not
serve. Worth re-testing — `enableStaticServing` is on in `config.toml`, and if
it does work the inline payload gets much smaller.

**Fix, in order of payoff.**

1. Commit `static/img_cache/*.webp` (12 MB) and gitignore `01_data/img`
   instead. The originals are a tooling input for
   `04_tools/11_rebuild_image_tiers.py`, not a runtime dependency — they belong
   in the bucket, not the deploy.
2. If the tiers must stay out of git, point the Cloud deployment at the R2
   bucket for the *tiers* and not just as a link-rot backstop. Today
   `REMOTE_ASSET_STORAGE.md` puts the bucket **below** `static/img_cache` in the
   image tier order, which is the right order locally and the wrong one on
   Cloud, where that directory is always empty on a cold container.
3. Either way, make the ordering conditional on `fn_on_streamlit_cloud()`, which
   already exists at `libs/lib_data.py:1291` and is currently used in only one
   place.

---

## 3. `string[python]` dtypes cost 3.3× the RAM they need

Every column in both parquet files loads as `string[python]` (172 of 173 columns
in the edits file). Measured, this checkout:

| File | rows × cols | current | `string[pyarrow]` | `dtype_backend="pyarrow"` |
|---|---|---|---|---|
| `base_data.parquet` | 1,609 × 135 | 12.7 MB | **3.9 MB** | — |
| `edits_data.parquet` | 3,296 × 173 | 35.7 MB | **10.2 MB** | 7.9 MB |

A one-line conversion after load — `df[c] = df[c].astype("string[pyarrow]")` for
every `string` column, or `pd.read_parquet(..., dtype_backend="pyarrow")` —
cuts the resident dataset from ~48 MB to ~14 MB. `pyarrow` is already a declared
dependency. Spot-checked `.astype(str).str.strip()` against the converted frame:
unchanged.

Do it once inside `fn153b_load_base_dataframe` / `fn155_load_edits_dataframe` so
the shared cached frame *and* every per-session copy derived from it shrink
together.

Full `dtype_backend="pyarrow"` is another 2.3 MB cheaper but changes NA
semantics across 5,000 lines of downstream code — not worth the risk for the
delta. Stick to the string columns.

---

## 4. Each session holds two more copies of the dataset

`app.py:355` and `app.py:395`:

```python
st.session_state["ORIGINAL_DATA"] = _df_base     # full frame + PR__ + _Base + ITA cols
st.session_state["FILTERED_DATA"] = df_filtered  # row subset, all columns
```

`fn158c_cached_load_clean_effective_live` is correctly a shared `cache_resource`
(one copy for the whole process). But each *session* then derives and retains a
full annotated copy plus a filtered copy. Unfiltered, that is roughly 2× the
dataset per connected browser tab — and Community Cloud's RAM ceiling is shared
across all of them.

With finding 3 applied this is ~28 MB per session instead of ~96 MB, which is
probably enough on its own. If more headroom is wanted:

- `FILTERED_DATA` is a row subset — hold the **index** and slice from
  `ORIGINAL_DATA` at point of use, rather than a second frame;
- the three derived columns (`A__ProductName_Base`, `PR__*`, Italian product
  type) are deterministic functions of the shared frame and the same for every
  session. They could be computed once inside the cached loader instead of
  per session, leaving `ORIGINAL_DATA` as a reference to the shared object.

Note `fn_046_add_base_product_column` also runs **uncached on `df_filtered` on
every rerun** (`app.py:390`), after already having run on the full frame.

---

## 5. The image cache holds decoded PIL objects

`libs/lib_data.py:1777`:

```python
@st.cache_data(max_entries=1024)
def fn110_cached_fetch_image(url, profile="default", *, eetra_id=None, product_name=None):
```

It returns **PIL `Image` objects** at up to 400×400 (`libs/lib_ui_catalogues.py:560`).
Pickled, that is raw pixel data: ~480 KB per RGB image. At the documented ~560
distinct catalogue images that is **~270 MB**; at the `max_entries=1024` ceiling,
**~490 MB** — roughly a fifth of the app's entire RAM budget, for data that
exists on disk as 10–30 KB webp files.

The `max_entries=1024` comment correctly identifies the growth risk but the unit
is wrong. Cache the **encoded bytes** (`BytesIO` of the webp) and decode at point
of use, or drop `max_entries` to ~128. Encoded, 560 images is ~15 MB.

---

## 6. Cold-boot imports

`-X importtime` on `import libs.page_imports`, this machine, warm filesystem:

| Module | cumulative |
|---|---|
| **total** | **3.15 s** |
| `streamlit` | 1.21 s |
| `pandas` | 0.73 s |
| `office365.sharepoint.client_context` | **0.51 s** |
| `plotly.express` | 0.36 s |
| `requests` | 0.17 s |
| `pydeck` | 0.07 s |
| `msal` | 0.03 s |

Streamlit and pandas are unavoidable. **`office365` + `msal` (0.55 s, 18% of
import time) are not** — `libs/lib_data.py:108-110` imports them at module scope,
but the default data source is Neon (`fn149`), and SharePoint is one of three
options selected on the Developer Dashboard. Every user on every cold boot pays
for a code path most of them never take.

Move those three imports inside `fn104_cached_load_excel` / the SharePoint
branch. The file already does exactly this for `duckdb` (`lib_data.py:1732`) and
`lib_ui.py` does it for `fitz` — the pattern is established.

`libs/page_imports.py` is a `import *` shim pulled in by all 11 pages; it also
imports `plotly.io`, `plotly.graph_objects`, `plotly.express`, `pydeck` and `PIL`
for every page, including Welcome. Pages that plot already import plotly
themselves (`pages/12`, `pages/15`, `pages/9`). Dropping `pydeck` and plotly from
the shim and leaving them to the pages that use them saves another ~0.43 s.

On Cloud this sits on top of `pip install` for 24 declared packages — several of
them heavy (`PyMuPDF`, `reportlab`, `pdfplumber`, `duckdb`, `boto3`,
`Office365-REST-Python-Client`, `anthropic`, `openai`) and several used only by
admin pages or `04_tools/` scripts that never run on the deployment. Splitting
`requirements.txt` into runtime vs tooling would measurably shorten every
redeploy; `pytest` in particular has no business in the deployed environment.

---

## 7. Small, cheap

- **`aux_09` range index re-serialised per rerun.** `libs/lib_ui.py:6001-6004`
  calls `json.dumps(_fn_product_range_index())` and
  `json.dumps(_fn_product_range_collections())` on every Catalogue rerun. The
  *dicts* are cached (`max_entries=1`); the serialisation is not. Measured 10 ms
  and ~1 MB of garbage per rerun for the index alone. Cache the strings.
- **Eleven caches have neither `ttl` nor `max_entries`** (`lib_auth_m365.py:103`,
  `lib_charts.py:307`, `lib_data.py:1717`, `lib_eco_data.py:143`, `:603`,
  `lib_i18n.py:109`, `pages/12:33`, `pages/15:1597`, `pages/5:761`, `:981`,
  `pages/8:16`). Most take no arguments, so they hold one entry and are fine —
  but any that take a parameter grows without bound for the life of the
  container. Worth a pass with that distinction in mind.
- **`_expand_tabular_cv` on every run** (`app.py:132` → `fn132`): measured
  0.21 ms. Harmless. Noted only so it is not mistaken for a problem later.

---

## 8. One decision to make

`_fn336_static_products_url` (`libs/lib_ui.py:5745`) implements exactly the fix
finding 1 and 2 want — serve the products JSON out-of-band through Streamlit's
`MediaFileManager` so the srcdoc stays small — and **nothing calls it**. The
render path at `:6010` goes straight to `_fn336_inline_products_js`.

Either it was abandoned because `MediaFileManager` failed on Cloud, in which
case the function and its docstring should go so the next reader does not
rediscover it; or it works and is the single biggest available win, since it
removes both the gzip and the ~1 MB-per-rerun websocket payload at once.

Worth 20 minutes on the deployed app to settle.

---

## Suggested order

1. Cache the gzip (§1) — smallest change, largest per-interaction win.
2. `string[pyarrow]` on load (§3) — one function, 3.3× less RAM everywhere.
3. Lazy `office365`/`msal` (§6) — three lines, 18% off cold boot.
4. Cache the two `json.dumps` calls (§7) — trivial.
5. Encoded bytes in the image cache (§5) — frees ~250 MB.
6. Settle §8, then decide §2 — these two are the same question.
7. Session-state copies (§4) — most invasive, do last, and only if §3 is not
   enough.

Steps 1–4 are roughly an afternoon and need no architectural decisions.
