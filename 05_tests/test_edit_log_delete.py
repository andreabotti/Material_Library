"""Tombstone semantics of the append-only edit log (lib_data fn157).

A ``delete`` record removes the id from the effective dataset without erasing
anything: the log keeps the snapshot and ``base_data.parquet`` is untouched, so
the merge is what makes the row disappear.
"""
from __future__ import annotations

import pandas as pd

from libs.lib_data import EDIT_AUDIT_COLS, fn157_merge_base_and_edits

BASE_COLS = ["0__EETRA_ID", "A__ProductName", "A__Map_yn"]


def _base() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"0__EETRA_ID": "AAA__1", "A__ProductName": "One", "A__Map_yn": "Y"},
            {"0__EETRA_ID": "AAA__2", "A__ProductName": "Two", "A__Map_yn": "Y"},
        ]
    )


def _rec(eid: str, op: str, edit_id: str, name: str = "") -> dict:
    rec = {c: None for c in BASE_COLS + list(EDIT_AUDIT_COLS)}
    rec.update({
        "0__EETRA_ID": eid,
        "A__ProductName": name or eid,
        "A__Map_yn": "Y",
        "_edit_id": edit_id,
        "_edit_op": op,
        "_edit_ts": f"2026-01-01T00:00:{edit_id.zfill(2)}",
        "_edit_user": "test",
    })
    return rec


def _merge(*records: dict) -> pd.DataFrame:
    return fn157_merge_base_and_edits(_base(), pd.DataFrame(list(records)))


def _ids(df: pd.DataFrame) -> list[str]:
    return df["0__EETRA_ID"].astype(str).tolist()


def test_delete_removes_a_base_row():
    out = _merge(_rec("AAA__1", "delete", "10"))
    assert _ids(out) == ["AAA__2"]


def test_delete_removes_a_row_that_only_ever_existed_in_the_log():
    out = _merge(_rec("NEW__9", "insert", "10"), _rec("NEW__9", "delete", "20"))
    assert _ids(out) == ["AAA__1", "AAA__2"]


def test_a_later_insert_revives_a_deleted_id():
    out = _merge(
        _rec("AAA__1", "delete", "10"),
        _rec("AAA__1", "insert", "20", name="Reborn"),
    )
    assert "AAA__1" in _ids(out)
    assert out.loc[out["0__EETRA_ID"] == "AAA__1", "A__ProductName"].iloc[0] == "Reborn"


def test_delete_wins_over_an_earlier_update():
    out = _merge(
        _rec("AAA__2", "update", "10", name="Edited"),
        _rec("AAA__2", "delete", "20"),
    )
    assert _ids(out) == ["AAA__1"]


def test_audit_columns_never_leak_into_the_merged_frame():
    out = _merge(_rec("AAA__1", "delete", "10"), _rec("AAA__2", "update", "20"))
    assert not set(EDIT_AUDIT_COLS) & set(out.columns)


def test_deleting_every_row_yields_an_empty_frame_not_an_error():
    out = _merge(_rec("AAA__1", "delete", "10"), _rec("AAA__2", "delete", "20"))
    assert out.empty
    assert list(out.columns) == BASE_COLS


def test_log_without_deletes_is_unaffected():
    out = _merge(_rec("AAA__1", "update", "10", name="Edited"))
    assert _ids(out) == ["AAA__1", "AAA__2"]
    assert out.loc[out["0__EETRA_ID"] == "AAA__1", "A__ProductName"].iloc[0] == "Edited"
