# Remote asset storage — EPD documents and product images

Updated 2026-10-28. Covers the Cloudflare R2 bucket that backs `01_data/pdf`
(EPD / technical-sheet documents) and `01_data/img` (product-image originals).
Read path: `libs/lib_doc_storage.py`. Upload path:
`04_tools/07_upload_pdfs_to_buckets.py`. Credentials: `.streamlit/secrets.toml`.

**Current state: built, not switched on.** The code is in place and inert;
`[doc_storage] enabled` is `false` and the `[cloudflare_r2]` credentials are
still placeholders. Nothing has been uploaded. Follow *Setup* below to finish.

## Why

The app carries 1.28 GB of assets that are not code and not data:

| Folder | Files | Size | What it is |
|---|---:|---:|---|
| `01_data/pdf` | 905 | 1,232 MB | EPDs, VOC certificates, technical sheets. 888 `.pdf`, 16 `.htm`/`.html`/`.php` saved from manufacturer pages, 1 `.jpg` |
| `01_data/img` | 552 | 51.5 MB | Pipeline-downloaded product-image originals, `sha256(source_url)[:16].<ext>` |

Three consequences, all of which the bucket removes:

1. **A full copy of the PDFs exists twice on disk.** `static/docs` holds 650 of
   them (704 MB) so the catalogue's `srcdoc` iframe can fetch them over plain
   HTTP. The module docstring in `lib_doc_storage.py` says these are hard links
   and "cost no extra disk" — on the OneDrive volume this project lives on, the
   hard-link call falls back to copying, so they are real duplicate bytes.
   Verified with `fsutil hardlink list`, which returns a single path per file.
2. **Streamlit's static folder has a hard 1 GiB cap**, checked once at server
   startup. Go over it and static serving is silently disabled app-wide for the
   life of the process. `MAX_STATIC_DOCS_BYTES` (700 MiB) exists only to stay
   under that ceiling, which is why `static/docs` holds 650 files and not 905 —
   the remaining 255 fall back to a slower server-side fetch.
3. **Product images depend on manufacturer URLs staying put.** When a local
   original is missing the app re-fetches from the source site, so a
   manufacturer reorganising its CDN costs us the picture permanently.

## Provider

Cloudflare R2, alone. `provider_order = ["cloudflare_r2"]`.

| | Free storage | Egress | Cost for 1.28 GB |
|---|---|---|---|
| **Cloudflare R2** | 10 GB, then $0.015/GB-mo | **$0, always** | **$0/mo** |
| Backblaze B2 | 10 GB, then $0.006/GB-mo | free to 3× stored | $0/mo |
| Supabase Storage | 1 GB | 5 GB free | does not fit free → $25/mo Pro |
| AWS S3 | — ($0.023/GB-mo) | $0.09/GB | storage trivial, egress scales badly |

Egress decides it. These are 1.4 MB documents served to browsers, so a
per-GB egress charge is the dominant term everywhere except R2, and Supabase's
free tier cannot hold the PDFs at all. At ten times the current volume R2 is
still about $0.04/month.

The `[supabase]` block stays in `secrets.toml` and the code path still works —
`provider_order` accepts a list and tries each in turn — so a second provider
can be added later without code changes.

## Bucket layout

One bucket (`eetra-mat-lib`, Western Europe/WEUR) holds both asset classes:

| Key | Source | Notes |
|---|---|---|
| `<filename>` | `01_data/pdf/<filename>` | Flat, same name as on disk |
| `img/<filename>` | `01_data/img/<filename>` | `img/` prefix |
| `img/_index.json` | generated | `{sha256(url)[:16]: filename}` for every image |

Keys keep their local filenames so the bucket mirrors the folders 1:1 and one
lookup key works for both.

### Why `img/_index.json` exists

The app knows an image by `sha256(source_url)[:16]`. That hash carries no file
extension, and the folder holds `.jpg`, `.jpeg`, `.png`, `.webp` and `.gif`.
Resolving a key by probing would be up to five HTTP round trips per miss, and
on a checkout with no `01_data/img` *every* image misses. The index turns all
of that into one cached fetch. A key the index does not list still falls back
to probing, so an object uploaded by hand is still found, just more slowly.

The index is rewritten from the local folder on every run that touches images.
It is uploaded with `max-age=3600`, unlike the assets themselves, so a newly
added image becomes resolvable within the hour.

## Setup

Four steps in the Cloudflare dashboard, then two commands.

1. **R2 → Create bucket**. The live bucket is `eetra-mat-lib` in Western Europe
   (WEUR); `bucket` in `secrets.toml` must match the name exactly, or every
   `head_object` fails against a bucket that does not exist. The account id in
   the S3 endpoint (`https://<account_id>.r2.cloudflarestorage.com/<bucket>`)
   is `38f77d02a49dc885ae5510e665692c31`.
2. **Bucket → Settings → Public access**: enable the `r2.dev` subdomain, or
   bind a custom domain such as `assets.eetra.it`. The app reads over plain
   public HTTPS with no signing, so the bucket must be public-read.
3. **R2 → Manage API Tokens → Create**, with *Object Read & Write* on that
   bucket. Copy the Access Key ID and Secret Access Key — the secret is shown
   once.
4. Fill in `[cloudflare_r2]` in `.streamlit/secrets.toml`: `account_id`,
   `bucket`, `access_key_id`, `secret_access_key`, `public_base_url`.

Then, from the app root:

```
python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --what both --dry-run
python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --what both
```

Run it from the working copy that actually holds the assets. A git checkout
carries neither `01_data/pdf` nor `.streamlit/secrets.toml`, so the committed
copy of the script cannot upload on its own — it exits with a hint rather than
a bare `No such directory`. Redirect it with `--root`, or set
`MATLIB_ASSET_ROOT` once:

```
python 04_tools/07_upload_pdfs_to_buckets.py --root "E:/path/to/EETRA_MatLib_2026.11" --target r2 --dry-run
```

Finally set `[doc_storage] enabled = true`.

The upload is ~1.28 GB across 1,456 objects. R2 does not charge for ingress.
The run is idempotent and safe to interrupt and resume.

### Re-running: what counts as "already uploaded"

`head_object` returns `ContentLength` and `ETag` alongside existence, so change
detection costs no extra request over a bare existence check.

| Mode | Test | Use |
|---|---|---|
| *(default)* | remote size == local size | routine runs after a pipeline run |
| `--checksum` | also MD5 vs remote ETag | catches a same-size edit; reads every local file that exists remotely, so slower |
| `--force` | no comparison, re-send all 1.28 GB | last resort |

**Existence alone is deliberately not the test.** These keys are not content
hashes — a document key is its registration number, an image key is `sha256` of
its *source URL* — so re-issuing an EPD under the same registration, or a
manufacturer swapping the picture behind a stable URL, leaves the key unchanged
while the bytes change. Skipping on existence pins that stale copy in the
bucket forever, with no error to notice: it is simply counted as skipped.

Two limits remain, both by design:

- **A replaced object can serve stale from the CDN edge** for up to
  `--cache-seconds` (7 days by default). Purge it in the Cloudflare dashboard
  when a correction is urgent, or re-upload that one object with a short TTL.
- **Deletions never propagate.** Removing a local file leaves its object in
  place as an orphan, to be removed by hand.

A multipart ETag is `<md5>-<parts>` rather than a whole-file digest, so
`--checksum` ignores those and lets the size test decide — otherwise every
large object would re-upload on every run.

Covered by `05_tests/test_upload_sync_detection.py` (10 tests), which stubs the


### Run logs

Every run writes a timestamped file under `logs/` (gitignored):
`r2_dryrun_<date>_<time>.log` or `r2_upload_<date>_<time>.log`. The console is
unchanged; the file adds a line per object, so a transfer can be audited after
the fact rather than trusted from a total.

```
2026-11-10 14:22:59  DEBUG    r2 bucket   : eetra-mat-lib
2026-11-10 14:22:59  DEBUG    r2 account  : 38f77d...2c31
2026-11-10 14:23:01  DEBUG    DRY-RUN   18fd37eba58fc35e.pdf (130701 bytes, application/pdf) would upload
2026-11-10 14:25:13  INFO     [cloudflare_r2] done: uploaded=1456 replaced=0 skipped(unchanged)=0 failed=0
```

Each object is logged as `UPLOAD`, `REPLACE`, `SKIP`, `DRY-RUN` or `FAIL` with
its size and content type, and the run ends with duration, bytes actually sent,
and an explicit list of failures. Credentials are never written: the account id
is masked and the access keys are not referenced, so a log can be shared.

`--log-file` puts it elsewhere; `--no-log` turns it off. A log destination that
cannot be opened prints a warning and the run continues -- a missing log must
never cost a 1.28 GB transfer.

**Credentials are checked once, up front.** `head_bucket` runs before the loop
and exits with a named cause (`InvalidAccessKeyId`, `SignatureDoesNotMatch`,
`AccessDenied`, `NoSuchBucket`) instead of failing 1,456 times. Per object,
only `404`/`NoSuchKey`/`NotFound` count as "absent"; an auth or bucket error
aborts. This matters because a bare `except Exception` made a wrong key
indistinguishable from an empty bucket -- every object reported as
"would upload", which looks exactly like a first run.R2 client rather than reaching the network.

The credentials above are used **only** by this offline script. The app never
reads them — it only ever builds a public URL from `public_base_url`.

## How the app reads it

Documents and images use deliberately different tier orders.

**Documents — remote first** (`fn_fetch_document_bytes`):

> bucket (each provider in `provider_order`) → `01_data/pdf` on disk

A document is fetched once, on demand, when the user opens the document panel.
Remote-first costs nothing there and is what makes the local folder optional.

**Images — remote second** (`fn110_cached_fetch_image` in `libs/lib_data.py`):

> `01_data/img` → product-name local file → `img_manifest.csv` →
> `static/img_cache` → **bucket** → live fetch from the manufacturer

An image is read on every catalogue render and the originals are already on
disk, so the local tiers win and the bucket sits between them and the live
fetch. That ordering is what makes the bucket a link-rot backstop: a hit means
the picture survived either a checkout with no image folder or a source URL
that has since rotted, and nothing gets slower while the local folder is intact.

Both paths are inert while `[doc_storage] enabled` is `false`:
`fn_fetch_image_bytes` returns `(None, None)` and `fetch_remote_image_original`
returns `None`, so the app behaves exactly as it did before.

`fetch_remote_image_original` imports `lib_doc_storage` *inside the function*.
That is deliberate — `lib_doc_storage` imports `_dir_has_file` from `lib_data`,
so a module-level import would close the cycle.

## Cache-Control

Assets upload with `public, max-age=604800` (7 days). Override with
`--cache-seconds`.

Not the year-long `immutable` that content-addressed assets usually get,
because **these keys are not content hashes**. An image key is the hash of its
*source URL*; a document key is its registration number. Re-issue an EPD under
the same registration, or let a manufacturer swap the picture behind a stable
URL, and the key is unchanged while the bytes are not. A year of `immutable`
would pin the stale copy at every edge with no way to flush it. Seven days
still serves almost every view from cache at no cost.

## Content types

Every object gets the type its extension implies, via `mimetypes` plus an
explicit table for the cases `mimetypes` gets wrong or does not know
(`.php` → `text/html`, `.webp` → `image/webp`).

This matters because `01_data/pdf` is not all PDFs: 16 of the 905 files are
technical sheets that the manufacturer served as HTML, or `.php` endpoints that
returned a document. Serving those as `application/pdf` makes the browser
download a file it cannot open.

Observed across both folders: 888 `application/pdf`, 393 `image/jpeg`,
86 `image/webp`, 73 `image/png`, 16 `text/html`.

## Operational notes

- **New assets.** Re-run the uploader after a pipeline run. Existing objects
  are skipped, so a routine run only transfers what is new. Re-run with
  `--what images` after adding images so `img/_index.json` is rewritten.
- **One file is excluded on purpose.** `01_data/img/7ed83ddbe52fe2ab.aspx`
  begins `<!DOCTYP` — it is a saved HTML error page from a failed fetch, not an
  image. The uploader's extension allowlist filters it out.
- **`static/docs` can be retired once this is live.** With documents served
  from R2, `fn_sync_static_doc_links()` and its hourly re-link job
  (`libs/lib_ui.py`) become dead code, and the 704 MB duplicate plus the whole
  Streamlit 1 GiB-cap workaround go with them. Decide first whether
  `01_data/pdf` stays the local master or R2 becomes the master — that choice
  is what makes the local copy droppable.
- **The bucket is public.** Appropriate for published EPD certificates, which
  are already public documents on registry sites such as epditaly.it. Anything
  that should not be public needs presigned URLs instead, which this read path
  does not implement.

## Metadata

The bucket stores bytes only. `01_data/pdf_manifest.csv` (902 rows) remains the
index — filename, declared/detected type, confidence, `eetra_ids`,
`product_names`, `manufacturers`, `origin_urls`.

If that index ever needs to be queryable or writable by more than one user, it
belongs in the Neon Postgres instance the app already uses for the edit log
(`libs/lib_neon.py`, `psycopg` in `requirements.txt`) — not in the bucket, and
not as blobs in Postgres, where storage costs far more than R2 and CDN caching
is lost entirely.
