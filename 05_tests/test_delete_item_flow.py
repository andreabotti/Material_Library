"""Developer → Edit Existing Item: the delete flow and its confirmation.

Drives the real page through Streamlit's AppTest: the toolbar button must only
arm a confirmation, Cancel must leave everything alone, and only the explicit
second click may write the tombstone. The edit log is redirected to a throwaway
copy, so ``01_data/edits_data.parquet`` is never written to.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from libs import lib_data
from libs.lib_i18n import fn714_tu as _L
from libs.lib_data import fn153_resolve_base_parquet_path, fn154_resolve_edits_parquet_path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pages" / "13_Add_Edit_Item.py"

pytestmark = pytest.mark.skipif(
    not (PAGE.exists() and fn153_resolve_base_parquet_path().exists()),
    reason="Add/Edit page or base_data.parquet not available",
)


@pytest.fixture(autouse=True)
def no_url_probes(monkeypatch: pytest.MonkeyPatch):
    """The form probes its URL fields over HTTP — stub it, keep the test offline."""
    monkeypatch.setattr(
        lib_data, "fn142b_probe_http_url",
        lambda url, kind="generic": {"ok": False, "level": "idle", "status_code": None,
                                     "label": "—", "detail": "stubbed", "url": url},
    )


@pytest.fixture()
def edits_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "edits_data.parquet"
    src = fn154_resolve_edits_parquet_path()
    if src.exists():
        shutil.copy2(src, dest)
    return dest


@pytest.fixture()
def deletes_before(edits_copy: Path) -> int:
    """Tombstones already in the copied log.

    ``edits_copy`` is a copy of the real ``01_data/edits_data.parquet``, which
    accumulates genuine deletions as the library is curated — 19 of them by
    the time this fixture was added. Asserting an absolute count here silently
    coupled the suite to production data: the tests passed while the log
    happened to hold none, then broke the first time someone deleted an item
    in the app. What the flow owes us is a delta — nothing written when the
    button is merely armed or cancelled, exactly one tombstone on confirm.
    """
    return _n_deletes(edits_copy)


@pytest.fixture()
def page(edits_copy: Path) -> AppTest:
    at = AppTest.from_file(str(PAGE), default_timeout=300)
    at.secrets["parquet"] = {"edits_path": str(edits_copy)}
    at.session_state["auth_user"] = "test"
    at.session_state["auth_role"] = "admin"
    at.session_state["_add_edit_section"] = "edit"
    # The widget form; the default browser editor (libs/item_editor) is JS-only.
    at.session_state["add_edit_classic_form"] = True
    at.run()
    assert not at.exception
    return at


def _labels(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


def _click(at: AppTest, text: str) -> AppTest:
    return [b for b in at.button if text in b.label][0].click().run()


def _n_deletes(path: Path) -> int:
    if not path.exists():
        return 0
    df = pd.read_parquet(path)
    return int((df["_edit_op"].astype(str) == "delete").sum())


def _select_first_item(at: AppTest) -> str:
    sel = at.selectbox(key="edit_choice")
    target = [o for o in sel.options if o != "— select —"][0]
    sel.set_value(target).run()
    assert not at.exception
    return target


def test_delete_button_does_not_delete_on_its_own(page: AppTest, edits_copy: Path, deletes_before: int):
    _select_first_item(page)
    assert any(_L("🗑️ Delete item") in lbl for lbl in _labels(page))
    assert not any(_L("Yes, delete this item") in lbl for lbl in _labels(page))

    _click(page, _L("🗑️ Delete item"))
    assert any(_L("Yes, delete this item") in lbl for lbl in _labels(page))
    assert any(lbl == _L("Cancel") for lbl in _labels(page))
    assert page.warning, "confirmation must warn before deleting"
    assert _n_deletes(edits_copy) == deletes_before, "arming the button already deleted"


def test_cancel_leaves_the_item_alone(page: AppTest, edits_copy: Path, deletes_before: int):
    target = _select_first_item(page)
    _click(page, _L("🗑️ Delete item"))
    _click(page, _L("Cancel"))

    assert not any(_L("Yes, delete this item") in lbl for lbl in _labels(page))
    assert _n_deletes(edits_copy) == deletes_before
    assert page.session_state["edit_choice"] == target, "cancel changed the selection"


def test_confirming_writes_one_tombstone_and_clears_the_picker(
    page: AppTest, edits_copy: Path, deletes_before: int,
):
    target = _select_first_item(page)
    _click(page, _L("🗑️ Delete item"))
    _click(page, _L("Yes, delete this item"))
    assert not page.exception

    assert _n_deletes(edits_copy) == deletes_before + 1
    log = pd.read_parquet(edits_copy)
    rec = log[log["_edit_op"].astype(str) == "delete"].iloc[-1]
    assert str(rec["0__EETRA_ID"]) in target
    # The record keeps a snapshot, which is what makes the delete reversible.
    assert str(rec["A__ProductName"]).strip() not in ("", "None", "<NA>")

    # The deleted item leaves the picker, and the form falls back to its prompt
    # rather than indexing a row that is no longer there.
    sel = page.selectbox(key="edit_choice")
    assert target not in sel.options
    assert sel.value == "— select —"
    assert any(_L("Pick a product above to load and edit its data.") in i.value
               for i in page.info)
    assert any("Deleted" in s.value for s in page.success)
