# Deploying MatLib to Streamlit Community Cloud

Updated 2026-11-10. Entry point `app.py`, repository
[andreabotti/Material_Library](https://github.com/andreabotti/Material_Library).

**The repository is public.** Nothing in it may contain a credential. Secrets
live in the Streamlit Cloud dashboard; see *Secrets* below.

## Where each thing lives

The app no longer carries its own bulk. Three stores back it:

| Store | Holds | Backed by | In the repo? |
|---|---|---|---|
| Neon (Postgres) | `base_data`, the edit log | `[neon] database_url` | no |
| Cloudflare R2 | 905 documents, 551 image originals | `[cloudflare_r2]` | no |
| Repository | code, `aux_*.json`, `theme.json`, working parquet | git | yes |

That leaves ~78 MB of repository against ~2.6 GB of working copy. The excluded
folders are listed in `.gitignore` and explained in `REMOTE_ASSET_STORAGE.md`.

## Prerequisites

1. **R2 populated.** `python 04_tools/07_upload_pdfs_to_buckets.py --target r2
   --what both` has run clean. Verify by listing the bucket: 905 documents,
   551 images, plus `img/_index.json`.
2. **Public access on the bucket.** R2 > bucket > Settings > Public access
   (r2.dev subdomain or a custom domain). The read path builds plain public
   HTTPS URLs and does no signing, so a private bucket yields 401s.
3. **Neon reachable** from outside your network.

## Deploy

1. Push `main` to GitHub.
2. share.streamlit.io > **New app** > repo `andreabotti/Material_Library`,
   branch `main`, main file **`app.py`**.
3. **Advanced settings > Python version: 3.12** (matches local; there is no
   `runtime.txt`, so the default may differ).
4. **Advanced settings > Secrets** — paste the whole of your local
   `.streamlit/secrets.toml`. Same TOML, read through `st.secrets` exactly as
   on your machine. See below.
5. Deploy. First build installs 25 pinned requirements.

## Secrets

Paste the file's contents into the Secrets box. Do not commit it: `.gitignore`
blocks `secrets*`, `*.bak`, `*.pem`, `*.key` and similar near-misses, because
an exact-path rule once let `secrets.toml.bak_pre_r2_2026-11-09` through.

Sections the app reads: `doc_storage`, `cloudflare_r2`, `neon`, `anthropic`,
`mapbox`, `sharepoint`, `m365`, `google_oauth`, `gcp_service_account`,
`motherduck`, `soda4lca`, `auth.users`. `.streamlit/secrets.toml.example`
is the value-stripped structure.

Three values must differ from or be set beyond your local file:

- `[doc_storage] enabled = true` — otherwise every remote path is inert and the
  app looks for documents on a disk that does not have them.
- `[cloudflare_r2] public_base_url` — the **r2.dev** URL, not the
  `*.r2.cloudflarestorage.com` S3 endpoint, which requires signing.
- `[m365] redirect_uri` — must be the deployed URL, registered in Entra ID
  (App registrations > Authentication > Web). The localhost value will not work
  in the cloud, and without a registered URI the Microsoft button stays hidden.

Some settings also read from the environment, which Streamlit Cloud does not
expose directly — use the Secrets box instead: `NEON_DATABASE_URL`,
`EETRA_MATLIB_ROOT`, `MAPBOX_ACCESS_TOKEN`, `REVALU_API_KEY`.

## Known limitation: writes do not survive a restart

Streamlit Cloud's filesystem is **ephemeral**. It resets on reboot, redeploy
and after inactivity. Neon covers `base_data` and the edit log, but two stores
still write to local parquet:

| Written at | File | On restart |
|---|---|---|
| `libs/lib_tags.py:190` | `01_data/tags.parquet` | **lost** |
| `libs/lib_data.py:4230` | `01_data/collections.parquet` | **lost** |

`libs/lib_neon.py` has no `collections` or `tags` path. Nothing errors — a user
creates a collection, it works, and it is gone after the next restart. Decide
before launch whether these are read-mostly (acceptable) or user-facing
(needs Neon tables first, modelled on `matlib_base` in `lib_neon.py`).

## Config worth overriding

`.streamlit/config.toml` carries local development settings:

- `runOnSave = true` — meaningless in the cloud.
- `fileWatcherType = "poll"` — a OneDrive workaround. In the cloud it polls the
  filesystem continuously for no benefit, on a small shared instance.
- `enableStaticServing = true` — **keep this**. It serves `./static`, which the
  catalogue still uses for fonts and pdf.js.

`fn_sync_static_doc_links()` returns immediately when `01_data/pdf` is absent,
and its caller swallows exceptions, so the `static/docs` mirror is simply a
no-op in the cloud. Documents come from R2 instead.

## After the first deploy, check

1. A product card renders its image (R2 `img/` tier, or a live manufacturer
   fetch if that fails).
2. Opening a document panel serves a PDF from the r2.dev URL — the strongest
   single signal that `enabled = true` and `public_base_url` are both right.
3. A `.htm`/`.php` technical sheet opens in the browser rather than
   downloading, which confirms content types survived the upload.
4. The sidebar lists each page **once**. Duplicates mean a sync-conflict copy
   reached `pages/`; `.gitignore` blocks `*-DESKTOP-*` and `*-LAPTOP-*`.
5. The edit log writes and reads back, confirming Neon.

## Updating later

New documents or images after a pipeline run:

```
python 04_tools/07_upload_pdfs_to_buckets.py --target r2 --what both
```

Unchanged objects are skipped on a size comparison, so a routine run transfers
only what is new; `--checksum` also compares MD5 against the remote ETag, and
`--force` re-sends everything. Every run writes a timestamped log under
`logs/` (gitignored) with a line per object. Run it from the working copy that
holds the assets, or pass `--root`; a git checkout has neither the assets nor
the secrets. Details in `REMOTE_ASSET_STORAGE.md`.

A replaced object can serve stale from the CDN edge for up to seven days
(`--cache-seconds`); purge in the Cloudflare dashboard when urgent. Deletions
never propagate.

Code changes redeploy on push to `main`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Documents never load, no error | `[doc_storage] enabled` is false, or `public_base_url` still holds the `XXXXXXXX` placeholder — the URL builder returns `None` and the app falls back to a disk with no PDFs |
| 401 on every document | the bucket is not public-read |
| PDFs download instead of opening | `public_base_url` points at the S3 endpoint rather than r2.dev |
| `InvalidAccessKeyId` / `SignatureDoesNotMatch` on upload | the uploader's preflight names the cause; re-check the API token |
| A page appears twice | a sync-conflict copy in `pages/` |
| Collections vanish | ephemeral disk; see above |
