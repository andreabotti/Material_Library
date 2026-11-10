from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st

from libs import lib_tags as lt


@pytest.fixture
def tmp_tags_env(tmp_path: Path):
    st.session_state["DATA_SOURCE_PATH"] = str(tmp_path / "live_data.parquet")
    (tmp_path / "live_data.parquet").write_bytes(b"")
    try:
        lt._cached_load_tags.clear()
        lt._cached_load_collections.clear()
    except Exception:
        pass
    yield tmp_path
    try:
        lt._cached_load_tags.clear()
        lt._cached_load_collections.clear()
    except Exception:
        pass


def test_slugify_edge_cases(tmp_tags_env):
    assert lt.fn402_slugify("Villa Toscana — Bagno!") == "villa-toscana-bagno"
    assert lt.fn402_slugify("  ") == ""
    assert lt.fn402_slugify("") == ""
    assert lt.fn402_slugify("A_B C") == "a-b-c"


def test_add_tag_idempotency(tmp_tags_env):
    pid = "INS__MIW__0001"
    first = lt.fn410_add_tag_to_product(pid, "Villa Toscana")
    second = lt.fn410_add_tag_to_product(pid, "Villa Toscana")
    assert first["added"] is True
    assert second["added"] is False
    tags = lt.fn403_load_tags()
    assert len(tags) == 1


def test_remove_tag_missing_returns_false(tmp_tags_env):
    assert lt.fn411_remove_tag_from_product("INS__MIW__0001", "nope") is False


def test_rename_updates_tags_and_collections(tmp_tags_env):
    pid = "INS__MIW__0001"
    lt.fn410_add_tag_to_product(pid, "Old Label")
    cid = lt.fn415_create_collection("C1", tag_slugs=["old-label"])

    new_slug = lt.fn412_rename_tag("old-label", "New Label")
    assert new_slug == "new-label"

    tags = lt.fn403_load_tags()
    assert set(tags["tag_slug"].astype(str)) == {"new-label"}
    cols = lt.fn404_load_collections()
    row = cols.loc[cols["collection_id"] == cid].iloc[0]
    assert "new-label" in row["tag_slugs"]
    assert "old-label" not in row["tag_slugs"]


def test_delete_tag_removes_from_collections(tmp_tags_env):
    pid = "INS__MIW__0001"
    lt.fn410_add_tag_to_product(pid, "Delete Me")
    cid = lt.fn415_create_collection("C1", tag_slugs=["delete-me", "other"])
    removed = lt.fn413_delete_tag("delete-me")
    assert removed == 1
    row = lt.fn404_load_collections().loc[lambda d: d["collection_id"] == cid].iloc[0]
    assert "delete-me" not in row["tag_slugs"]


def test_duplicate_collection_new_ids(tmp_tags_env):
    cid = lt.fn415_create_collection("Base", tag_slugs=["alpha"])
    dup = lt.fn418_duplicate_collection(cid)
    assert dup
    cols = lt.fn404_load_collections()
    orig = cols.loc[cols["collection_id"] == cid].iloc[0]
    copy = cols.loc[cols["collection_id"] == dup].iloc[0]
    assert orig["share_token"] != copy["share_token"]
    assert orig["tag_slugs"] == copy["tag_slugs"]


def test_resolve_unknown_share_token(tmp_tags_env):
    assert lt.fn419_resolve_collection_by_share_token("missing") is None


def test_atomic_write_preserves_existing_on_replace_failure(tmp_tags_env, monkeypatch):
    tags_path = lt.fn401_tags_data_dir() / "tags.parquet"
    base = pd.DataFrame(
        [
            {
                "eetra_id": "INS__MIW__0001",
                "tag_slug": "alpha",
                "tag_label": "Alpha",
                "created_at": pd.Timestamp.utcnow(),
                "created_by": "tester",
            }
        ]
    )
    lt.fn405_save_tags(base)
    before = pd.read_parquet(tags_path)

    original_replace = os.replace

    def _boom(src, dst):
        if str(dst).endswith("tags.parquet"):
            raise RuntimeError("replace failed")
        return original_replace(src, dst)

    monkeypatch.setattr(lt.os, "replace", _boom)
    with pytest.raises(RuntimeError):
        lt.fn405_save_tags(
            pd.concat(
                [
                    base,
                    pd.DataFrame(
                        [
                            {
                                "eetra_id": "INS__MIW__0002",
                                "tag_slug": "beta",
                                "tag_label": "Beta",
                                "created_at": pd.Timestamp.utcnow(),
                                "created_by": "tester",
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
        )
    after = pd.read_parquet(tags_path)
    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True), check_dtype=False)
