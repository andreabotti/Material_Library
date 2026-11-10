"""
libs/lib_tags.py — EETRA MatLib tags and collections data layer
===============================================================
fn400–fn420  Tag and collection persistence helpers

  fn400  is_valid_product_id                 strict TYPE__SUBTYPE__NNNN guard
  fn401  tags_data_dir                       resolve parquet data directory
  fn402  slugify                             normalize human labels to slugs
  fn403  load_tags                           read tags parquet (cached)
  fn404  load_collections                    read collections parquet (cached)
  fn405  save_tags                           atomic write tags parquet
  fn406  save_collections                    atomic write collections parquet
  fn407  get_tags_for_product                list tag dicts for one product
  fn408  get_products_for_tag                list product ids for one tag
  fn409  get_products_for_collection         union products from collection tags
  fn410  add_tag_to_product                  idempotent add tag
  fn411  remove_tag_from_product             remove one product-tag pair
  fn412  rename_tag                          rename slug + update collections
  fn413  delete_tag                          delete slug from tags and collections
  fn414  list_all_tags                       aggregate tag usage table
  fn415  create_collection                   create collection row
  fn416  update_collection                   partial update collection row
  fn417  delete_collection                   delete collection row
  fn418  duplicate_collection                copy collection with new ids
  fn419  resolve_collection_by_share_token   resolve collection by share token
  fn420  audit_duplicate_product_ids         diagnostic duplicate EETRA IDs
"""

from __future__ import annotations

import contextlib
import ast
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st


_RE_PRODUCT_ID = re.compile(r"^[A-Z]+__[A-Z]+__\d+$")
_TAGS_COLUMNS = ["eetra_id", "tag_slug", "tag_label", "created_at", "created_by"]
_COLLECTIONS_COLUMNS = [
    "collection_id",
    "name",
    "description",
    "tag_slugs",
    "share_token",
    "owner",
    "created_at",
    "updated_at",
]


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _auth_user() -> str:
    return str(st.session_state.get("auth_user", "anonymous"))


# Filenames that mark the data directory. live_data.parquet is retired as a
# stored file (the app derives base ⊕ edits instead), but it is still recognised
# here so an un-migrated checkout — and the test fixture, which drops an empty
# one in a tmp dir purely as a marker — still resolves to the right folder.
_DATASET_MARKERS = ("base_data.parquet", "live_data.parquet")


def _live_data_path_from_session() -> Path | None:
    src = st.session_state.get("DATA_SOURCE_PATH")
    if not src:
        return None
    try:
        p = Path(str(src))
        if p.name.lower() in _DATASET_MARKERS and p.exists():
            return p
        if p.is_dir():
            for marker in _DATASET_MARKERS:
                candidate = p / marker
                if candidate.exists():
                    return candidate
    except Exception:
        return None
    return None


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "01_data"


def _ensure_df_schema(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = None
    return out[columns]


def _normalize_tag_slugs(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v).strip()]
    if value is None:
        return []
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return []
    except Exception:
        pass
    if hasattr(value, "tolist"):
        try:
            arr = value.tolist()
            if isinstance(arr, list):
                return [str(v) for v in arr if str(v).strip()]
        except Exception:
            pass
    s = str(value).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if str(v).strip()]
        except Exception:
            return [s]
    return [s]


def _tags_file() -> Path:
    return fn401_tags_data_dir() / "tags.parquet"


def _collections_file() -> Path:
    return fn401_tags_data_dir() / "collections.parquet"


def _mtime_or_zero(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(lock_path, "a+", encoding="utf-8")
    locked = False
    try:
        try:
            import portalocker  # type: ignore

            portalocker.lock(lock_fh, portalocker.LOCK_EX, timeout=5)
            locked = True
        except ImportError:
            if os.name == "posix":
                try:
                    import fcntl

                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                    locked = True
                except Exception:
                    print("Warning: lock unavailable, proceeding without file lock.")
            else:
                print("Warning: lock backend unavailable on Windows, proceeding unlocked.")
        yield
    finally:
        if locked:
            try:
                try:
                    import portalocker  # type: ignore

                    portalocker.unlock(lock_fh)
                except Exception:
                    if os.name == "posix":
                        import fcntl

                        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        lock_fh.close()


def _atomic_write_parquet(df: pd.DataFrame, target_path: Path) -> None:
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, target_path)


def fn400_is_valid_product_id(eetra_id) -> bool:
    """Return True only for strict product keys like TYPE__SUBTYPE__0001."""
    if eetra_id is None:
        return False
    try:
        if pd.isna(eetra_id):  # type: ignore[arg-type]
            return False
    except Exception:
        pass
    value = str(eetra_id).strip()
    if not value or value in {"-", "*", "__"}:
        return False
    return bool(_RE_PRODUCT_ID.fullmatch(value))


def fn401_tags_data_dir() -> Path:
    """Resolve the data directory holding the dataset and tag files (01_data/)."""
    live_data_path = _live_data_path_from_session()
    data_dir = live_data_path.parent if live_data_path else _default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def fn402_slugify(label: str) -> str:
    """Normalize a human label into a lowercase dash slug."""
    if label is None:
        return ""
    txt = str(label).strip().lower().replace("_", "-")
    txt = re.sub(r"\s+", "-", txt)
    txt = re.sub(r"[^a-z0-9-]", "", txt)
    txt = re.sub(r"-{2,}", "-", txt).strip("-")
    return txt


# Keyed on path + mtime. Neither may start with an underscore — Streamlit leaves
# ``_``-prefixed parameters out of the cache key, so the old ``_mtime_key`` never
# invalidated anything and only the 60 s ttl (and the .clear() on save) kept
# these fresh. The path is part of the key because it can differ per session.
@st.cache_data(ttl=60, max_entries=8)
def _cached_load_tags(path_str: str, mtime_key: float) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame(columns=_TAGS_COLUMNS)
    df = pd.read_parquet(path)
    return _ensure_df_schema(df, _TAGS_COLUMNS)


@st.cache_data(ttl=60, max_entries=8)
def _cached_load_collections(path_str: str, mtime_key: float) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame(columns=_COLLECTIONS_COLUMNS)
    df = pd.read_parquet(path)
    df = _ensure_df_schema(df, _COLLECTIONS_COLUMNS)
    if "tag_slugs" in df.columns:
        df["tag_slugs"] = df["tag_slugs"].apply(_normalize_tag_slugs)
    return df


def fn403_load_tags() -> pd.DataFrame:
    """Load tags.parquet with cache keyed by mtime."""
    path = _tags_file()
    return _cached_load_tags(str(path), _mtime_or_zero(path)).copy()


def fn404_load_collections() -> pd.DataFrame:
    """Load collections.parquet with cache keyed by mtime."""
    path = _collections_file()
    return _cached_load_collections(str(path), _mtime_or_zero(path)).copy()


def fn405_save_tags(df: pd.DataFrame) -> None:
    """Atomically write tags parquet."""
    path = _tags_file()
    payload = _ensure_df_schema(df, _TAGS_COLUMNS)
    with _file_lock(path.with_suffix(path.suffix + ".lock")):
        _atomic_write_parquet(payload, path)
    _cached_load_tags.clear()


def fn406_save_collections(df: pd.DataFrame) -> None:
    """Atomically write collections parquet."""
    path = _collections_file()
    payload = _ensure_df_schema(df, _COLLECTIONS_COLUMNS).copy()
    payload["tag_slugs"] = payload["tag_slugs"].apply(_normalize_tag_slugs)
    with _file_lock(path.with_suffix(path.suffix + ".lock")):
        _atomic_write_parquet(payload, path)
    _cached_load_collections.clear()


def fn407_get_tags_for_product(eetra_id: str) -> list[dict]:
    if not fn400_is_valid_product_id(eetra_id):
        return []
    df = fn403_load_tags()
    if df.empty:
        return []
    rows = df.loc[df["eetra_id"] == str(eetra_id), ["tag_slug", "tag_label"]].drop_duplicates()
    rows = rows.sort_values("tag_label", key=lambda s: s.fillna("").str.lower())
    return [{"slug": str(r["tag_slug"]), "label": str(r["tag_label"])} for _, r in rows.iterrows()]


def fn408_get_products_for_tag(tag_slug: str) -> list[str]:
    slug = fn402_slugify(tag_slug)
    if not slug:
        return []
    df = fn403_load_tags()
    if df.empty:
        return []
    values = df.loc[df["tag_slug"] == slug, "eetra_id"].dropna().astype(str).tolist()
    return list(dict.fromkeys(values))


def fn409_get_products_for_collection(collection_id: str) -> list[str]:
    cols = fn404_load_collections()
    if cols.empty:
        return []
    row = cols.loc[cols["collection_id"] == str(collection_id)]
    if row.empty:
        return []
    slugs = row.iloc[0]["tag_slugs"] or []
    ordered: dict[str, bool] = {}
    for slug in slugs:
        for pid in fn408_get_products_for_tag(str(slug)):
            if pid not in ordered:
                ordered[pid] = True
    return list(ordered.keys())


def fn410_add_tag_to_product(eetra_id: str, label: str) -> dict:
    if not fn400_is_valid_product_id(eetra_id):
        return {"slug": "", "label": str(label or ""), "added": False}
    clean_label = str(label or "").strip()
    slug = fn402_slugify(clean_label)
    if not slug:
        return {"slug": "", "label": clean_label, "added": False}
    df = fn403_load_tags()
    if not df.empty:
        exists = ((df["eetra_id"] == str(eetra_id)) & (df["tag_slug"] == slug)).any()
        if bool(exists):
            return {"slug": slug, "label": clean_label, "added": False}
    new_row = pd.DataFrame(
        [
            {
                "eetra_id": str(eetra_id),
                "tag_slug": slug,
                "tag_label": clean_label,
                "created_at": _utc_now(),
                "created_by": _auth_user(),
            }
        ]
    )
    out = pd.concat([df, new_row], ignore_index=True)
    fn405_save_tags(out)
    return {"slug": slug, "label": clean_label, "added": True}


def fn411_remove_tag_from_product(eetra_id: str, tag_slug: str) -> bool:
    if not fn400_is_valid_product_id(eetra_id):
        return False
    slug = fn402_slugify(tag_slug)
    if not slug:
        return False
    df = fn403_load_tags()
    if df.empty:
        return False
    mask = (df["eetra_id"] == str(eetra_id)) & (df["tag_slug"] == slug)
    if not bool(mask.any()):
        return False
    fn405_save_tags(df.loc[~mask].reset_index(drop=True))
    return True


def fn412_rename_tag(old_slug: str, new_label: str) -> str:
    old_slug = fn402_slugify(old_slug)
    new_label = str(new_label or "").strip()
    new_slug = fn402_slugify(new_label)
    if not old_slug or not new_slug:
        return old_slug

    tags = fn403_load_tags()
    cols = fn404_load_collections()
    if not tags.empty:
        mask = tags["tag_slug"] == old_slug
        if bool(mask.any()):
            tags.loc[mask, "tag_label"] = new_label
            if new_slug != old_slug:
                tags.loc[mask, "tag_slug"] = new_slug
            fn405_save_tags(tags)
    if not cols.empty and new_slug != old_slug:
        cols["tag_slugs"] = cols["tag_slugs"].apply(
            lambda arr: [new_slug if fn402_slugify(x) == old_slug else fn402_slugify(x) for x in (arr or [])]
        )
        fn406_save_collections(cols)
    return new_slug


def fn413_delete_tag(tag_slug: str) -> int:
    slug = fn402_slugify(tag_slug)
    if not slug:
        return 0
    tags = fn403_load_tags()
    cols = fn404_load_collections()
    removed = 0
    if not tags.empty:
        mask = tags["tag_slug"] == slug
        removed = int(mask.sum())
        if removed > 0:
            fn405_save_tags(tags.loc[~mask].reset_index(drop=True))
    if not cols.empty:
        cols["tag_slugs"] = cols["tag_slugs"].apply(lambda arr: [s for s in (arr or []) if fn402_slugify(s) != slug])
        fn406_save_collections(cols)
    return removed


def fn414_list_all_tags() -> pd.DataFrame:
    tags = fn403_load_tags()
    if tags.empty:
        return pd.DataFrame(columns=["tag_slug", "tag_label", "product_count", "last_used_at"])
    tmp = tags.copy()
    tmp["created_at"] = pd.to_datetime(tmp["created_at"], errors="coerce", utc=True)
    agg = (
        tmp.groupby("tag_slug", dropna=False)
        .agg(
            tag_label=("tag_label", lambda s: s.mode().iloc[0] if not s.mode().empty else s.dropna().astype(str).iloc[0]),
            product_count=("eetra_id", "nunique"),
            last_used_at=("created_at", "max"),
        )
        .reset_index()
    )
    return agg.sort_values("last_used_at", ascending=False, na_position="last").reset_index(drop=True)


def fn415_create_collection(name: str, description: str = "", tag_slugs: list[str] | None = None) -> str:
    cols = fn404_load_collections()
    cid = uuid4().hex
    now = _utc_now()
    row = pd.DataFrame(
        [
            {
                "collection_id": cid,
                "name": str(name or "").strip(),
                "description": str(description or "").strip(),
                "tag_slugs": [fn402_slugify(x) for x in (tag_slugs or []) if fn402_slugify(x)],
                "share_token": uuid4().hex,
                "owner": _auth_user(),
                "created_at": now,
                "updated_at": now,
            }
        ]
    )
    fn406_save_collections(pd.concat([cols, row], ignore_index=True))
    return cid


def fn416_update_collection(
    collection_id: str,
    *,
    name: Any = None,
    description: Any = None,
    tag_slugs: list[str] | None = None,
) -> bool:
    cols = fn404_load_collections()
    if cols.empty:
        return False
    idx = cols.index[cols["collection_id"] == str(collection_id)]
    if len(idx) == 0:
        return False
    i = idx[0]
    if name is not None:
        cols.at[i, "name"] = str(name)
    if description is not None:
        cols.at[i, "description"] = str(description)
    if tag_slugs is not None:
        cols.at[i, "tag_slugs"] = [fn402_slugify(x) for x in tag_slugs if fn402_slugify(x)]
    cols.at[i, "updated_at"] = _utc_now()
    fn406_save_collections(cols)
    return True


def fn417_delete_collection(collection_id: str) -> bool:
    cols = fn404_load_collections()
    if cols.empty:
        return False
    mask = cols["collection_id"] == str(collection_id)
    if not bool(mask.any()):
        return False
    fn406_save_collections(cols.loc[~mask].reset_index(drop=True))
    return True


def fn418_duplicate_collection(collection_id: str, new_name: str | None = None) -> str:
    cols = fn404_load_collections()
    row = cols.loc[cols["collection_id"] == str(collection_id)]
    if row.empty:
        return ""
    base = row.iloc[0].to_dict()
    now = _utc_now()
    new_id = uuid4().hex
    base["collection_id"] = new_id
    base["share_token"] = uuid4().hex
    base["name"] = str(new_name).strip() if new_name is not None else f"{base.get('name', '')} (copy)"
    base["created_at"] = now
    base["updated_at"] = now
    base["owner"] = _auth_user()
    base["tag_slugs"] = list(base.get("tag_slugs") or [])
    fn406_save_collections(pd.concat([cols, pd.DataFrame([base])], ignore_index=True))
    return new_id


def fn419_resolve_collection_by_share_token(token: str) -> dict | None:
    cols = fn404_load_collections()
    if cols.empty:
        return None
    row = cols.loc[cols["share_token"] == str(token)]
    if row.empty:
        return None
    out = row.iloc[0].to_dict()
    out["tag_slugs"] = list(out.get("tag_slugs") or [])
    return out


def fn420_audit_duplicate_product_ids(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Diagnostic helper for duplicate mapped product IDs in source data."""
    if df is None:
        try:
            _sess = st.session_state.get("ORIGINAL_DATA")
            if isinstance(_sess, pd.DataFrame) and not _sess.empty:
                df = _sess
            else:
                import libs.lib_data as _ld

                df = _ld.fn159_effective_dataset()
                if df.empty:
                    df = _ld.fn106_cached_load_live_data()
        except Exception:
            return pd.DataFrame(columns=["0__EETRA_ID", "A__Manufacturer", "A__ProductName"])

    required = {"A__Map_yn", "0__EETRA_ID", "A__Manufacturer", "A__ProductName"}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame(columns=["0__EETRA_ID", "A__Manufacturer", "A__ProductName"])

    cat = df.loc[df["A__Map_yn"].astype(str).str.upper() == "Y"].copy()
    counts = cat["0__EETRA_ID"].astype(str).value_counts()
    dup_ids = counts[counts > 1].index.tolist()
    if not dup_ids:
        return pd.DataFrame(columns=["0__EETRA_ID", "A__Manufacturer", "A__ProductName"])
    out = cat.loc[cat["0__EETRA_ID"].astype(str).isin(dup_ids), ["0__EETRA_ID", "A__Manufacturer", "A__ProductName"]]
    return out.reset_index(drop=True)
