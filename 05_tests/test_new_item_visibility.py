"""An item saved on the Add/Edit page must show up in the catalogue immediately.

The two-file data model (``base_data.parquet`` ⊕ ``edits_data.parquet``) was
always correct, but ``app.py`` built ``ORIGINAL_DATA`` once per session, so a
newly created product reached the edit log and the reloaded frame yet never the
frame the Catalogue, Charts and Maps render — it stayed invisible until the
session restarted. These tests run the real ``app.py`` headlessly through
Streamlit's AppTest and assert the row appears on the next rerun, which is what
``st.rerun()`` after a save produces.

The edit log is redirected to a throwaway copy via the ``[parquet] edits_path``
secret, so the project's own ``01_data/edits_data.parquet`` is never written to.

A rerun is a *fresh* ``AppTest`` seeded with the previous run's session state,
not a second ``at.run()`` — see :func:`run_app` for why.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from libs.lib_data import (
    fn153_resolve_base_parquet_path,
    fn154_resolve_edits_parquet_path,
    fn156_append_edit_record,
)

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"
NEW_ID = "TST__ZZZ__9999"

pytestmark = pytest.mark.skipif(
    not (APP.exists() and fn153_resolve_base_parquet_path().exists()),
    reason="app.py / base_data.parquet not available",
)


@pytest.fixture()
def edits_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the edit log — the real one is never touched."""
    dest = tmp_path / "edits_data.parquet"
    src = fn154_resolve_edits_parquet_path()
    if src.exists():
        shutil.copy2(src, dest)
    return dest


@pytest.fixture()
def run_app(edits_copy: Path):
    """Run ``app.py`` the way a rerun does: a new script execution that inherits
    the previous run's session state.

    Calling ``at.run()`` twice does NOT do this. ``app.py`` ends in
    ``st.navigation(...)`` / ``pg.run()``, and once AppTest has executed the
    entrypoint it reruns only the page that navigation selected — the
    entrypoint's whole data-reload block never runs again. It is observable:
    the per-run counter ``fn350_begin_run()`` bumps at the top of app.py stays
    at 1 no matter how many times ``at.run()`` is called, and
    ``fn158b_effective_live_mtimes()`` is called exactly once. Streamlit itself
    re-executes the entrypoint on every rerun, so seeding a fresh AppTest with
    the carried-over state is what actually reproduces production behaviour.

    Carrying the state is also what keeps these tests strict: ``ORIGINAL_DATA``
    and ``_data_fingerprint`` come across, so a regression that went back to
    building the frame once per session would reuse the stale frame and fail.
    """
    def _run(state: dict | None = None) -> AppTest:
        at = AppTest.from_file(str(APP), default_timeout=300)
        at.secrets["parquet"] = {"edits_path": str(edits_copy)}
        # app.py stops at its auth gate before any data loads; seed a signed-in
        # session the same way a successful login does.
        at.session_state["auth_user"] = "test"
        at.session_state["auth_role"] = "admin"
        at.session_state["data_platform"] = "Local Parquet"
        for key, value in (state or {}).items():
            at.session_state[key] = value
        at.run()
        assert not at.exception
        return at

    return _run


def _state(at: AppTest) -> dict:
    """Everything the next run should inherit, as Streamlit would keep it."""
    return {key: at.session_state[key] for key in at.session_state}


def _ids(at: AppTest, key: str = "ORIGINAL_DATA") -> set[str]:
    df = at.session_state.get(key)
    if df is None or not len(df):
        return set()
    return set(df["0__EETRA_ID"].astype(str))


def _save_new_item(path: Path) -> None:
    """Append one insert record, as pages/13_Add_Edit_Item.py does on save."""
    base = pd.read_parquet(fn153_resolve_base_parquet_path())
    row = {c: None for c in base.columns}
    row.update({
        "0__EETRA_ID": NEW_ID,
        "A__ProductName": "Regression Test Product",
        "A__Manufacturer": "TEST MFR",
        "D__ProductType_ENG": "Tiles",
        "A__Map_yn": "Y",
    })
    fn156_append_edit_record(row, eetra_id=NEW_ID, op="insert",
                             base_columns=list(base.columns), path=path,
                             user="test")


def test_new_item_reaches_catalogue_on_next_rerun(run_app, edits_copy: Path):
    first = run_app()
    before = _ids(first)
    assert NEW_ID not in before

    _save_new_item(edits_copy)
    second = run_app(_state(first))

    assert NEW_ID in _ids(second), "new item missing from ORIGINAL_DATA"
    assert NEW_ID in _ids(second, "FILTERED_DATA"), "new item missing from the catalogue view"
    assert len(_ids(second)) - len(before) == 1


def test_deleted_item_leaves_the_catalogue_on_next_rerun(run_app, edits_copy: Path):
    """The mirror of the test above: a delete record removes the row everywhere."""
    first = run_app()
    before = _ids(first)

    # Pick a victim that exists in base_data: the delete record carries a
    # snapshot taken from there, so an insert-only row has nothing to snapshot.
    base = pd.read_parquet(fn153_resolve_base_parquet_path())
    base_ids = set(base["0__EETRA_ID"].astype(str))
    victim = sorted(before & base_ids)[0]

    snapshot = base.loc[base["0__EETRA_ID"].astype(str) == victim].iloc[0].to_dict()
    fn156_append_edit_record(snapshot, eetra_id=victim, op="delete",
                             base_columns=list(base.columns), path=edits_copy,
                             user="test")

    second = run_app(_state(first))
    assert victim not in _ids(second), "deleted item still in ORIGINAL_DATA"
    assert victim not in _ids(second, "FILTERED_DATA"), "deleted item still in the catalogue view"
    assert len(before) - len(_ids(second)) == 1


def test_unchanged_rerun_does_not_rebuild_the_frame(run_app):
    """The rebuild is keyed on the data, not on every rerun."""
    first = run_app()
    frame = first.session_state["ORIGINAL_DATA"]

    second = run_app(_state(first))
    assert second.session_state["ORIGINAL_DATA"] is frame
