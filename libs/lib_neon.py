"""
libs/lib_neon.py — Neon (Postgres) backend for base_data + the edit log
========================================================================
Replaces ``01_data/base_data.parquet`` and ``01_data/edits_data.parquet`` when a
connection string is configured, so two PCs no longer fight over OneDrive copies
of those files.

Configure (either one):
  .streamlit/secrets.toml     [neon]  database_url = "postgresql://…neon.tech/…?sslmode=require"
  environment variable        NEON_DATABASE_URL

Not used when the matching ``[parquet] base_path`` / ``edits_path`` secret is set
(tests and tools that point the app at a throwaway copy stay on parquet), or when
no URL is configured.

Storage model
  matlib_base         eetra_id (text PK), row (jsonb: every data column except the
                      id). Replaced wholesale by ``04_tools/15_parquet_to_neon.py``
                      after each Excel → parquet refresh.
  matlib_base_meta    single row: upload timestamp, row count, column dtypes so
                      load restores Float64 / string the way the parquet did.
  matlib_edits        edit_id (bigint PK, the time-based ``_edit_id``), edit_ts,
                      edit_user, edit_op, eetra_id, row (jsonb: every column of
                      the full-row snapshot as text; NA → JSON null), plus the
                      provenance columns edit_batch / edit_reason / edit_evidence
                      / edit_evidence_url / edit_fields

The correction register is a *view* over these provenance columns (lib_data
fn155c), not a table of its own — the old ``matlib_corrections`` is dropped on
connect once its contents have been migrated by 04_tools/15_parquet_to_neon.py.

Edit-log values are stored as text, exactly what the parquet log held (its
columns are pandas "string"); ``0__NUM`` is the one numeric column and is cast
back on load. Base rows keep JSON-native numbers/strings and restore dtypes from
``matlib_base_meta``.
"""
from __future__ import annotations

import os
import threading
import time

import pandas as pd
import streamlit as st

_NUMERIC_COLS = ("0__NUM",)
_VERSION_TTL_S = 2.0

_SCHEMA = """
create table if not exists matlib_edits (
    edit_id    bigint primary key,
    edit_ts    text   not null,
    edit_user  text,
    edit_op    text   not null,
    eetra_id   text   not null,
    row        jsonb  not null
);
create index if not exists matlib_edits_eetra_idx on matlib_edits (eetra_id, edit_id);

alter table matlib_edits add column if not exists edit_batch        text;
alter table matlib_edits add column if not exists edit_reason       text;
alter table matlib_edits add column if not exists edit_evidence     text;
alter table matlib_edits add column if not exists edit_evidence_url text;
alter table matlib_edits add column if not exists edit_fields       text;

create table if not exists matlib_base (
    eetra_id   text primary key,
    row        jsonb not null
);

create table if not exists matlib_base_meta (
    id           int primary key default 1 check (id = 1),
    uploaded_at  timestamptz not null,
    n_rows       int not null,
    dtypes       jsonb not null
);
"""


def neon_url() -> str | None:
    """Connection string from the environment or ``[neon] database_url``."""
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("neon", {}).get("database_url")
        except Exception:
            url = None
    return str(url).strip() or None if url else None


def _parquet_override(key: str) -> bool:
    try:
        return bool(st.secrets.get("parquet", {}).get(key))
    except Exception:
        return False


def _session_platform() -> str | None:
    """Welcome-page Data Source selection, if a Streamlit session is active."""
    try:
        return st.session_state.get("data_platform")
    except Exception:
        return None


def edits_use_neon() -> bool:
    """True when the edit log lives in Neon.

    Off when there is no URL, when ``[parquet] edits_path`` forces a file, or when
    the UI Data Source is **Local Parquet**. **Neon** and **EETRA Sharepoint**
    (and offline tools with no session) use Neon whenever a URL is configured.
    """
    if neon_url() is None or _parquet_override("edits_path"):
        return False
    if _session_platform() == "Local Parquet":
        return False
    return True


def base_use_neon() -> bool:
    """True when base_data lives in Neon.

    Off for **Local Parquet** / **EETRA Sharepoint** (those use the file or the
    workbook). On for **Neon**, and for tools with no session when a URL is set.
    """
    if neon_url() is None or _parquet_override("base_path"):
        return False
    platform = _session_platform()
    if platform in ("Local Parquet", "EETRA Sharepoint"):
        return False
    return True


def neon_enabled() -> bool:
    """Back-compat alias: True when the edit log uses Neon."""
    return edits_use_neon()


def _normalize_url(url: str) -> str:
    """Drop ``channel_binding=require`` — it breaks some Windows/psycopg setups
    and is unnecessary when ``sslmode=require`` is already set."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k.lower() != "channel_binding"]
    return urlunparse(p._replace(query=urlencode(q)))


@st.cache_resource(show_spinner=False)
def _pool(url: str):
    """One small pool per process. ``check`` re-validates connections Neon closed
    while the compute was idle (scale-to-zero)."""
    from psycopg import OperationalError
    from psycopg_pool import ConnectionPool, PoolTimeout

    pool = ConnectionPool(
        url, min_size=0, max_size=4, open=True, timeout=60,
        check=ConnectionPool.check_connection,
        # Neon free-tier cold start can take ~10–30s after idle suspend.
        kwargs={"connect_timeout": 60, "autocommit": False},
    )
    try:
        with pool.connection() as conn:
            conn.execute(_SCHEMA)
    except (PoolTimeout, OperationalError) as e:
        try:
            pool.close()
        except Exception:
            pass
        _pool.clear()  # type: ignore[attr-defined]
        hint = (
            "Neon connection failed. Re-copy the connection string from Neon → "
            "Connect → Postgres database (click Show password first — a masked "
            "******** paste will fail auth). Prefer the non-pooled host if the "
            "pooler keeps timing out. Special characters in the password must be "
            "URL-encoded (@ → %40, # → %23, % → %25)."
        )
        raise RuntimeError(f"{hint}\nUnderlying error: {e}") from e
    return pool


def _conn():
    url = neon_url()
    if not url:
        raise RuntimeError("Neon is not configured (secrets [neon] database_url).")
    return _pool(_normalize_url(url)).connection()


# ── version token (replaces file mtimes as the cache key) ────────────────────
_ver_lock = threading.Lock()
_ver_cache: dict[str, tuple[float, int]] = {}


def _version(table: str, col: str) -> int:
    now = time.monotonic()
    with _ver_lock:
        hit = _ver_cache.get(table)
        if hit and now - hit[0] < _VERSION_TTL_S:
            return hit[1]
    with _conn() as conn:
        n, last = conn.execute(f"select count(*), coalesce(max({col}), 0) from {table}").fetchone()
    val = int(n) * 1_000_003 + int(last) % 1_000_003 if n else 0
    with _ver_lock:
        _ver_cache[table] = (now, val)
    return val


def _bump() -> None:
    with _ver_lock:
        _ver_cache.clear()


def edits_version() -> int:
    """Changes whenever a record is added to the edit log (0 when empty)."""
    return _version("matlib_edits", "edit_id")


def base_version() -> int:
    """Changes whenever base is replaced (0 when never uploaded)."""
    now = time.monotonic()
    with _ver_lock:
        hit = _ver_cache.get("matlib_base")
        if hit and now - hit[0] < _VERSION_TTL_S:
            return hit[1]
    with _conn() as conn:
        row = conn.execute(
            "select coalesce(extract(epoch from uploaded_at) * 1000, 0)::bigint, "
            "coalesce(n_rows, 0) from matlib_base_meta where id = 1"
        ).fetchone()
    val = int(row[0]) * 1_000_003 + int(row[1]) if row else 0
    with _ver_lock:
        _ver_cache["matlib_base"] = (now, val)
    return val


def base_row_count() -> int:
    with _conn() as conn:
        n = conn.execute("select count(*) from matlib_base").fetchone()[0]
    return int(n)


# ── helpers ──────────────────────────────────────────────────────────────────
def _text(v):
    """Same coercion the parquet log applied (``astype("string")``): NA → None."""
    if v is None or v is pd.NA:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


def _json_safe(v):
    """NA → None; numpy/pandas scalars → plain Python for jsonb."""
    if v is None or v is pd.NA:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def _restore_dtypes(df: pd.DataFrame, dtypes: dict) -> pd.DataFrame:
    if not dtypes:
        return df
    order = [c for c in dtypes if c in df.columns]
    order += [c for c in df.columns if c not in order]
    df = df.reindex(columns=order)
    for col, dt in dtypes.items():
        if col not in df.columns:
            continue
        name = str(dt)
        try:
            if "Float" in name or name in ("float64", "float32", "float"):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
            elif "Int" in name or name in ("int64", "int32", "int"):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
            elif "bool" in name.lower():
                df[col] = df[col].astype("boolean")
            elif "string" in name or name == "object":
                df[col] = df[col].astype("string")
            elif "datetime" in name.lower():
                df[col] = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            pass
    return df


# ── base_data ────────────────────────────────────────────────────────────────
def load_base() -> pd.DataFrame:
    """Full Excel-conversion snapshot, dtypes restored from ``matlib_base_meta``."""
    with _conn() as conn:
        meta = conn.execute("select dtypes from matlib_base_meta where id = 1").fetchone()
        recs = conn.execute("select eetra_id, row from matlib_base").fetchall()
    if not recs:
        return pd.DataFrame()
    data = []
    for eid, row in recs:
        payload = dict(row) if row is not None else {}
        payload["0__EETRA_ID"] = eid
        data.append(payload)
    df = pd.DataFrame(data)
    dtypes = dict(meta[0]) if meta and meta[0] else {}
    return _restore_dtypes(df, dtypes)


def replace_base(df: pd.DataFrame) -> int:
    """Replace ``matlib_base`` with *df* (full snapshot). Returns row count."""
    from psycopg.types.json import Jsonb

    if df is None or df.empty:
        raise ValueError("base DataFrame is empty")
    if "0__EETRA_ID" not in df.columns:
        raise ValueError("base DataFrame needs a 0__EETRA_ID column")

    dtypes = {c: str(df[c].dtype) for c in df.columns}
    params = []
    for rec in df.to_dict("records"):
        eid = str(rec["0__EETRA_ID"])
        row = {k: _json_safe(v) for k, v in rec.items() if k != "0__EETRA_ID"}
        params.append((eid, Jsonb(row)))

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from matlib_base")
            cur.executemany(
                "insert into matlib_base (eetra_id, row) values (%s, %s)", params,
            )
            cur.execute(
                "insert into matlib_base_meta (id, uploaded_at, n_rows, dtypes) "
                "values (1, now(), %s, %s) "
                "on conflict (id) do update set "
                "uploaded_at = excluded.uploaded_at, "
                "n_rows = excluded.n_rows, "
                "dtypes = excluded.dtypes",
                (len(params), Jsonb(dtypes)),
            )
    _bump()
    return len(params)


# ── edit log ─────────────────────────────────────────────────────────────────
def load_edits(audit_cols: tuple[str, ...]) -> pd.DataFrame:
    """The whole log as a frame shaped like the parquet one (all "string",
    ``0__NUM`` Float64, audit columns present)."""
    with _conn() as conn:
        recs = conn.execute(
            "select edit_id, edit_ts, edit_user, edit_op, eetra_id, row, "
            "edit_batch, edit_reason, edit_evidence, edit_evidence_url, edit_fields "
            "from matlib_edits order by edit_id"
        ).fetchall()
    if not recs:
        return pd.DataFrame({c: pd.Series(dtype="string") for c in audit_cols})
    data = pd.DataFrame([r[5] for r in recs]).astype("string")
    data["0__EETRA_ID"] = pd.Series([r[4] for r in recs], dtype="string")
    data["_edit_id"] = pd.Series([str(r[0]) for r in recs], dtype="string")
    data["_edit_ts"] = pd.Series([r[1] for r in recs], dtype="string")
    data["_edit_user"] = pd.Series([r[2] for r in recs], dtype="string")
    data["_edit_op"] = pd.Series([r[3] for r in recs], dtype="string")
    for pos, name in enumerate(
        ("_edit_batch", "_edit_reason", "_edit_evidence", "_edit_evidence_url", "_edit_fields"),
        start=6,
    ):
        data[name] = pd.Series([r[pos] for r in recs], dtype="string")
    for c in _NUMERIC_COLS:
        if c in data.columns:
            data[c] = pd.to_numeric(data[c], errors="coerce").astype("Float64")
    return data


def append_edits(records: list[dict], audit_cols: tuple[str, ...]) -> None:
    """INSERT full-row snapshots (dicts holding the data columns plus
    ``0__EETRA_ID`` and the audit columns) in one transaction. A duplicate
    ``_edit_id`` raises instead of overwriting."""
    from psycopg.types.json import Jsonb

    params = []
    for rec in records:
        row = {k: _text(v) for k, v in rec.items() if k not in audit_cols and k != "0__EETRA_ID"}
        params.append((
            int(rec["_edit_id"]), rec["_edit_ts"], rec.get("_edit_user"), rec["_edit_op"],
            str(rec["0__EETRA_ID"]), Jsonb(row),
            rec.get("_edit_batch"), rec.get("_edit_reason"), rec.get("_edit_evidence"),
            rec.get("_edit_evidence_url"), rec.get("_edit_fields"),
        ))
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "insert into matlib_edits (edit_id, edit_ts, edit_user, edit_op, eetra_id, row, "
                "edit_batch, edit_reason, edit_evidence, edit_evidence_url, edit_fields) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", params,
            )
    _bump()


# ── correction register ──────────────────────────────────────────────────────
# Derived on read from the provenance columns above (lib_data fn155c); there is
# no longer a table behind it.
