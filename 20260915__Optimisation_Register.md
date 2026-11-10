# MatLib Optimisation Register

**EETRA Material Library** · Performance Audit · 2026.07 build

Nine findings across speed, storage and usability in the MatLib Streamlit app.
Six implemented and measured; two open, one that could not be reproduced — plus
two follow-on questions answered since.

| | |
|---|---|
| **Scope** | `app.py` · `libs/` · `pages/` · `02_html/` |
| **Dataset** | 1,609 products × 135 columns |
| **Streamlit** | 1.60.0 |
| **Dated** | 15–16 September 2026 |

---

## Headline

All figures measured against `01_data/base_data.parquet` on the real catalogue, not
estimated. Ratios this extreme don't plot honestly on a linear axis, so they're
given as a ledger.

| Metric | Before | After | Change |
|---|---:|---:|---|
| Image bytes in the catalogue payload | 315.8 MB | 0.128 MB | **2,400× less** |
| Catalogue payload build, per rerun | 14.01 s | 0.06 s | **233× faster** |
| Filesystem calls, cold render | 11,711 | 133 | **88× fewer** |
| Image caches on disk | 3 · 115 MB | 2 · 59 MB | **55.3 MB freed** |
| Copies of the dataset on disk | 4 files | 2 files | **one canonical** |
| Declared dependencies | 10 of 23 | 23 of 23 | **deploys clean** |
| Thumbnail bytes for a full grid | 5.19 MB | 3.21 MB | **38% lighter** |

### Where the build time went

Finding 2 came apart in five stages. Each was verified byte-identical against
the previous payload before moving on.

| Stage | Build time |
|---|---:|
| Baseline | 14.01 s |
| + badge memo, tag map, field-visibility memo | 4.59 s |
| + object-dtype rows, doc-URL columns | 1.81 s |
| + bulk `rawFields` | 1.20 s |
| + payload cache (rerun) | **0.06 s** |

Median of three runs, 1,609 products.

---

## Findings 1–3, 5, 6, 9 · implemented

### 1. The catalogue shipped ~300 MB of base64 images — FIXED

Only the last-resort live-fetch branch wrote to `static/img_cache`. Every
local-disk branch called `image_path_to_data_uri()`, which read the
*full-resolution original* and base64-inlined it into the iframe srcdoc — for a
100 px image band. Two bugs compounded it: no downscaling (median source 51 KB,
largest 1 MB), and a memo keyed on `(url, eetra_id, name)`, so 552 distinct
files were re-encoded once per each of the 1,580 rows referencing them.

**What changed.** All branches now route through `static/img_cache`: downscaled
once to the existing `theme.json → image_band.fetch_max_*` budget (300×300),
written as WebP with a per-thread temp file and `os.replace`, and referenced as
a short URL. The memo keys on the image URL alone. No JavaScript changed —
`productImageSrc → appStaticUrl` already resolved `/app/…` paths and the tags
already carried `loading="lazy"`.

| Payload | Rows served locally | Thumbnails on disk | Conversion, one-off |
|---|---|---|---|
| 315.8 → 0.128 MB | 21 → 1,587 | 6.4 MB | 16.1 s |

### 2. The payload build ran on every rerun — FIXED

`fn336_render_catalogue_flipcard` rebuilt ~600 lines of payload on every
Catalogue rerun — each search keystroke, tag toggle and document click.
Profiling found four distinct causes, not one.

**What changed.**

- **Badge composite.** `fn346_voc_cert_composite_data_uri` was 7.9 s of the
  profile — 1,198 calls re-opening two PNGs, resizing and encoding, for just
  *three* reachable results. Memoized on the derived kinds tuple, so "M1",
  "M1 class" and "M1 classification" share one entry.
- **Tags.** One `groupby` pass replaced `fn407_get_tags_for_product` per row,
  which was copying the whole tags frame and re-resolving its path 1,609 times.
- **Row extraction.** The frame arrives as 125 `string` columns and 10
  `Float64`, so pandas rebuilt the common dtype across all 135 on *every* row
  access — `find_common_type` alone was 8 s. One `astype(object)` (5 ms)
  removes the search entirely.
- **The cache.** The build moved into `_fn336_cached_catalogue_payload`, keyed
  on the frame plus a config signature covering field visibility, display
  params and the tags mtime. Only theme/session CSS, `cols`, `height`,
  `open_product` and `doc_preview` stay live per rerun.

| Rerun | Full render | Filter change | Payload |
|---|---|---|---|
| 14.01 → 0.06 s | 0.11 s | 0.33 s | byte-identical |

### 3. Filesystem probing on a OneDrive volume — FIXED (estimate corrected)

Three media resolvers shared one shape: build a candidate filename,
`is_file()`, repeat across five or six extensions and up to two directories.
`static_img_cache_url` alone was up to eight probes per call, called up to three
times per image — and Finding 1 had made it the primary lookup, so this was
partly self-inflicted.

**What changed.** `_dir_file_index()` lists a directory once into a dict and
answers every candidate from it, with the freshness check itself rate-limited to
2 s — a first attempt that re-stat'd the directory per lookup only traded eight
syscalls for one. Files this process writes register immediately, so the served
store is never stale for its own writes. `fn_sync_static_doc_links` and
`_static_doc_file_info` moved to `os.scandir`, whose directory enumeration
already carries size and mtime.

| Syscalls | Doc sync | Cold render | Real saving |
|---|---|---|---|
| 11,711 → 133 | ~150 → 8 ms | 4.02 → 3.73 s | ~0.3 s |

### 6. Three parallel image caches — FIXED

`01_data/img` (pipeline originals, `sha256[:16]`), `.cache/images` (fetch cache,
`md5` with a `__catalogue` filename variant) and `static/img_cache` (served
thumbnails, `md5`) held overlapping content under three key schemes. Every
caller of `fn110_cached_fetch_image` passes `profile="catalogue"` — the legacy
300×160 profile had no callers left, so 238 of those files were from a retired
code path.

**What changed.** `fn110`'s fetch tier now reads and writes `static/img_cache`,
the same store the catalogue serves from. That leaves two directories with
clearly separate jobs: pipeline source of truth, and served thumbnails.
`04_tools/10_consolidate_image_caches.py` checks the legacy store for anything
unique before removal — it found 7 candidates, all of which turned out to be
50×50 CDN error graphics that the app's own `catalogue_image_cache_is_valid`
rejects. Nothing was lost; `.cache/images` was deleted.

| Stores | Freed | Unique images lost | Coverage |
|---|---|---|---|
| 3 → 2 | 55.3 MB | 0 | unchanged |

### 5. Four byte-identical copies of the dataset — FIXED

`base_data.parquet`, `live_data.parquet` and copies of both under `01_data/` all
hashed to `5f1736c1…`. `live_data.parquet` was a *materialised* base ⊕ edits
merge, rewritten after every save so that modules reading it directly — the
document-path map, the tags layer, the manufacturers page and four offline tools
— would not have to merge for themselves. A third copy of rows that already
lived in two files, and a way for a failed write to serve stale data silently.

**What changed.** Two files remain, both in `01_data/` beside the rest of the
project's data: `base_data.parquet` (the Excel conversion, written only by the
pipeline) and `edits_data.parquet` (the append-only log of everything done
through the app's form). The merge is no longer stored — `fn159_effective_dataset()`
derives it on read, cached on both files' mtimes, and every former direct reader
now calls it. The Excel pipeline stops emitting the duplicates. Path resolution
prefers `01_data/` and falls back to the old root location, so an un-migrated
checkout still starts.

| Files | Readers repointed | Edit round-trip | Payload |
|---|---|---|---|
| 4 → 2 | 7 | verified | byte-identical |

### 9. `requirements.txt` was missing half its dependencies — FIXED

Ten of the twenty-three packages the code imports were declared. A clean deploy
failed on the first chart. Rebuilt by walking every import across `app.py`,
`libs/`, `pages/`, `04_tools/` and `05_tests/` and mapping each module to its
distribution, rather than by memory.

**What changed.** Added `pillow`, `numpy`, `pyarrow`, `plotly`, `altair`,
`pydeck`, `requests`, `urllib3`, `orjson`, `msal`,
`Office365-REST-Python-Client`, `duckdb`, `openai` and `botocore`. Removed
`pycountry`, listed for a long time and imported nowhere. `soda4lca` is
documented as deliberately optional — it powers the ECOportal Ingest tab only
and is imported inside a try.

Two things surfaced while checking. `pyarrow` was never declared even though
every parquet read depends on it. And `portalocker`, which locks `tags.parquet`
during writes, *was* declared but is **not installed** in the current
environment — so those writes run unlocked today and two concurrent saves can
interleave. Installing it closes a real hazard.

| Declared | Floors verified | Unmet | Dead entries |
|---|---|---|---|
| 10 → 23 | 22 of 23 met | portalocker | 1 removed |

---

## Follow-on work

Two questions asked after the nine findings were closed. Neither was on the
original list; both changed the code.

### A. Can `static/` fold into `01_data/`? — EVALUATED, NO

Read out of Streamlit 1.60's own source rather than assumed. Three findings, any
one of which settles it:

**The name and location are hardcoded.** `file_util.get_app_static_dir()` is
literally `Path(app.py).parent / "static"`. There is no config option pointing it
elsewhere.

**A symlink would work and would be a mistake.** The route calls
`os.path.realpath()` on the root, so `static → 01_data` would resolve and serve.
It would also publish `base_data.parquet`, `edits_data.parquet`, `tags.parquet`
and all 904 PDFs over HTTP with `Access-Control-Allow-Origin: *` — and these are
server routes that never execute the script, so they bypass the login gate
entirely.

**It would break regardless.** `bootstrap.py` walks the folder at startup and,
above `MAX_APP_STATIC_FOLDER_SIZE` (1 GiB), calls
`config.set_option("server.enableStaticServing", False)` — silently, for the
whole process. `01_data` is 1.3 GB, so the merge would disable static serving and
take out both the document panel and every catalogue image.

**Conclusion.** The two directories have genuinely different jobs: `01_data` is
private source of truth, `static/` is the public serving window, and only the
second can be reached by a browser. The split stands. One incidental find:
`static/fonts/ronzino/` (180 KB) is referenced nowhere — `theme.json`'s
`local_fonts` is empty and nothing loads those faces.

| static/ total | of 1 GiB cap | headroom | dead weight |
|---|---|---|---|
| 708.9 MiB | 69% | 315 MiB | fonts, 180 KB |

### B. Originals kept, two served thumbnail tiers — IMPLEMENTED

Finding 1 replaced base64 inlining with a single 300 px served size. Measuring
what the catalogue actually paints showed one size was wrong in both directions
at once:

| Context | Displayed | Was served |
|---|---|---|
| Grid, size M | 78×70 | 300×225 |
| Grid, size L | 98×94 | 300×225 |
| Grid, size XL | 70×62 | 300×225 |
| Detail panel | 98×74 (CSS allows 180×130) | 300×225 |

Three times too large for a grid card, and too small for a HiDPI detail panel.

**What changed.** Two tiers, both produced from a single decode of the untouched
original and sized in `theme.json → image_band`: `<md5>.webp` at 200 px is what
the grid loads 1,600 of, `<md5>__d.webp` at 400 px is what the panel loads one of
per click. The card tier keeps the bare name, so URLs already in a cached payload
keep resolving. `04_tools/11_rebuild_image_tiers.py` performs the migration,
report-only unless `--apply`.

The originals in `01_data/img` are never written — 53 MB, 552 files, only ever
read.

| Grid transfer | Detail tier | Rebuilt | Payload cost |
|---|---|---|---|
| 5.19 → 3.21 MB | 400 px, on click | 543 of 562 | +136 KB |

---

## Corrections to this audit

Two estimates in the original report were wrong, and two bugs were introduced
during the work and caught before delivery. Recorded because the numbers above
are only worth what the method behind them is.

### Finding 3's cost was overstated by roughly 15×

The instrumented profile attributed 4.48 s to stat calls. Measuring actual
syscall latency afterwards put it at **12–17 µs per call** — the rest was the
measurement wrapper. The syscall *count* in the original report (≈11,000) was
right; the cost attributed to it was not. Real saving: ~0.3 s on a cold render,
~0 on warm reruns.

Kept anyway on two grounds: `os.scandir` of the whole 562-file directory costs
~992 µs against ~194 ms of stats, so it still nets positive; and these figures
are for locally-hydrated files. A OneDrive Files On-Demand file dehydrated to
cloud-only blocks on network per stat, and 133 of those is survivable where
11,711 is not.

### "`read_iframe_component` re-reads the template every render" — not a hot spot

Claimed in the original report as per-render overhead worth memoizing.
Measured: three file reads, under a millisecond, absorbed by the OS page cache.
Left alone rather than adding a memo for nothing.

### Introduced: underscore-prefixed cache parameters key nothing

The first version of the payload cache named its parameters `_is_js2` and
`_config_signature`. Streamlit *excludes* underscore-prefixed parameters from
the cache key, so neither keyed anything — a field-visibility edit would have
silently served a stale catalogue. Caught by the invalidation test (0.057 s
where a rebuild was due), renamed, and the trap recorded in the docstring.
`_progress` keeps its underscore deliberately, being a live widget handle.

### Introduced: a cached progress bar took the Catalogue down

The payload cache drove a progress bar belonging to a placeholder created by the
calling page. `@st.cache_data` *records the Streamlit element calls a cached
function makes* so it can replay them on a hit — and on a hit that placeholder no
longer exists, so every cached render raised `CacheReplayClosureError`. It could
only fail on a cache hit, which is exactly what the bare-mode test harness never
exercises; it reached the user before it reached a test.

The bar is gone, replaced by the decorator's own spinner, and the regression is
now covered by an `AppTest` run that drives one miss followed by two hits under a
real script runner.

### Introduced: a legacy PNG silently shadowed the rebuilt thumbnail

`static_img_cache_url` probes `.png` before `.webp`, so that entries written by
older versions keep resolving. When the tier rebuild wrote a new 200 px WebP
beside a leftover 300 px PNG of the same key, the probe kept returning the PNG
and the rebuild appeared to do nothing for those images. Writes now prune
same-key files at other extensions, so one key means one file; verified zero keys
present at more than one extension.

### Introduced: the cache migration shipped CDN placeholders

The first run of `10_consolidate_image_caches.py` rescued 7 "unique" images into
the served store. Inspection showed all were 50×50, 918-byte CDN error graphics
— below the 64 px floor the app's own `catalogue_image_cache_is_valid` enforces.
The migration had laundered rejected placeholders into a store the catalogue
trusts on sight. The tool now applies that same admission test; the six files
were removed and coverage returned to baseline.

---

## Findings 4, 7, 8 · open and unresolved

### 4. OneDrive does not preserve hard links — OPEN

`01_data/pdf` is 1.3 GB and `static/docs` hard-links 702 MB of it — verified
sharing inodes (`nlink = 2`), so locally it costs nothing. In the cloud,
OneDrive uploads both as independent files: ~2 GB of tenant quota and sync
bandwidth for 1.3 GB of PDFs.

**Recommended.** Exclude `static/docs`, `01_data/img`, `__pycache__`,
`.pytest_cache` and `logs/` from sync. OneDrive has no `.gitignore` equivalent,
so this means either moving the repo out of the synced tree or using per-folder
exclusion.

### 7. Collections is missing from the nav bar — COULD NOT REPRODUCE

The original report repeated the diagnosis in `app.py`'s comment — a Streamlit
limit on flat `position="top"` pages — and proposed passing a dict to group
them. Neither holds up.

A faithful reproduction (the same five page files, same titles, same icons, same
order, an expanded sidebar, the admin sixth page, and `st.navigation` called
late in the script) renders **all six links, Collections included**. The app's
global CSS was dumped and searched: nothing hides a nav item. Five flat pages is
nowhere near an overflow threshold.

**Status.** Left unchanged rather than applying a speculative fix. The real nav
only exists past the login gate, so confirming it needs a signed-in session. If
it still happens there, the cause is something the reproduction does not
capture — and the grouped-dict change proposed earlier would likely not have
addressed it.

### 8. No `url_path` on any page — OPEN

Every deep link and hard reload bounces to Welcome, which is why
`?view_docs_for=` needs a whole fallback path in `app.py`. Adding `url_path=` to
each `st.Page` gives real URLs and lets that fallback be deleted.

---

## Found in passing

Not part of the original nine; surfaced while measuring.

### Cold start now waits on failing network fetches — OPEN

With disk and CPU addressed, the ~3.7 s cold render is dominated by
`http.client` waiting on the 13 image URLs that no longer resolve. Those
failures aren't negative-cached, so every process start re-attempts them against
a 20 s timeout. This is now the largest remaining win on the catalogue path.

### `products_json` is 11.2 MB, almost all `rawFields` — product decision

Every one of the 135 columns, as strings, for every product, shipped on every
view to serve the XL grid size. Images are now 0.13 MB of it. Trimming to the
columns XL displays — or fetching on demand when someone switches to XL — is the
next big cut, but it's a decision about that view rather than a mechanical
optimisation.

### One pipeline output is not an image — pipeline

`01_data/img/7ed83ddbe52fe2ab.aspx` (25 KB) fails to decode — almost certainly
an HTML error page saved with an image extension. That card's image was already
broken in the browser; the new code degrades identically.

### Authentication — OPEN

`fn111_get_auth_users` hard-codes a fallback admin credential in source,
compares passwords in plaintext with `==`, and the gate screen pre-fills that
admin password. Fine for an internal tool on a trusted network; not fine if this
is ever reachable beyond it.

---

## Files changed

| File | Change | Findings |
|---|---|---|
| `libs/lib_data.py` | Single thumbnail store (`ensure_static_img_cache`, atomic writes); directory index with TTL; `fn110` fetch tier repointed at `static/img_cache` | 1, 3, 6 |
| `libs/lib_ui.py` | Image chain routed through the static store; badge composite memoized; tag map; field-visibility per type; object-dtype rows; bulk `rawFields`; payload split into `_fn336_cached_catalogue_payload`; `_static_doc_file_info` via scandir | 1, 2, 3 |
| `libs/lib_doc_storage.py` | `fn_static_doc_url` via the directory index; `fn_sync_static_doc_links` rewritten on `os.scandir` | 3 |
| `04_tools/10_consolidate_image_caches.py` | New — audits the legacy cache for unique images, migrates any that pass the app's admission test, reports only unless `--apply` | 6 |
| `libs/lib_tags.py` | Data-directory markers accept `base_data.parquet`; duplicate-ID audit reads the merge | 5 |
| `pages/_manufacturers_ui.py` | Product counts from the merge instead of `live_data.parquet` | 5 |
| `pages/13_Add_Edit_Item.py` | Docs corrected — the form appends to the edit log and nothing is re-materialised | 5 |
| `04_tools/03_excel_to_parquet.py` | Writes one base parquet into `01_data/`; no root copy, no materialised merge | 5 |
| `04_tools/04, 05, 08, 09` | Repointed at `01_data/base_data.parquet`; 09 writes the single canonical file | 5 |
| `requirements.txt` | Rebuilt from a full import walk — 13 added, 1 dead entry removed, optional dependency documented | 9 |
| `02_html/catalogue_component_js2.html` | Detail panel loads the larger tier (`productImageSrcDetail`); GWP pill type aligned with the card | B |
| `theme.json` | `image_band` tier sizes; upright serif faces requested; restart requirement documented | B |
| `04_tools/11_rebuild_image_tiers.py` | New — rewrites both tiers from the originals, report-only unless `--apply` | B |

---

## How this was verified

- Payload compared key-by-key after every stage — all six pre-existing keys
  byte-identical to baseline; the only delta is a newly-returned
  `list_fields_json`, which the Charts consumer reads via `.get()`.
- Cache invalidation exercised for a filter change, a `FIELD_VISIBILITY` edit
  (1.27 s rebuild) and a tag edit — the last by writing a real tag to
  `BBW__GYP__0002`, confirming it appeared, then restoring `tags.parquet`
  md5-identical.
- Dynamic arguments and session CSS confirmed live on cache hits: toggling card
  borders and switching detail level to Extended both take effect in 0.11 s.
- All 1,609 image URLs resolve identically through the directory index and
  direct `is_file()` probing; 200 document names likewise, present and missing.
- `fn_sync_static_doc_links` makes byte-identical decisions to the old
  implementation (649 skipped, 255 budget-skipped), leaves `static/docs`
  unchanged, keeps all 649 hard links, and is idempotent.
- Served over HTTP from the running app: `/app/static/img_cache/` returns 200
  `image/webp`, `/app/static/docs/` returns 200 `application/pdf`, both with
  `access-control-allow-origin: *` — which is what lets the sandboxed srcdoc
  iframe (origin `"null"`) load them.
- `./static` totals 708 MiB, under Streamlit's 1 GiB startup cap, which is
  checked once at boot and silently disables static serving app-wide if
  exceeded.
- Dataset consolidation: all four parquets confirmed byte-identical before the
  move; the two survivors verified md5-identical after it; the catalogue payload
  byte-identical across the change.
- The Add/Edit round-trip re-tested end to end — an update replays over base with
  no audit-column leakage and no row-count change, a new id appends
  (1,609 → 1,610), and `edits_data.parquet` was restored byte-for-byte afterwards.
- Every former `live_data.parquet` reader re-checked: the document-path map still
  returns 1,609 ids, manufacturer counts still cover 84 manufacturers, the tags
  layer still resolves `01_data/`.
- Dependency floors checked against the installed environment: 22 of 23
  satisfied, the exception being `portalocker`, which is genuinely absent.
- Image tiers verified in the live component against real data: the card slot
  loads `<md5>.webp` at 200×150, the panel loads `<md5>__d.webp` at 400×300 into
  a 98×74 box, both served 200 with an ETag so any cached 300 px copy
  revalidates away.
- 8/8 existing tests pass; everything compiles; app boots with no server errors.

```bash
python -m pytest 05_tests -q
python 04_tools/10_consolidate_image_caches.py        # report only
streamlit run app.py --server.port 8502
```
