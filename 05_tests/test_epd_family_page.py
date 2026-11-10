"""EPD reference → variants on the real Add/Edit page (Streamlit AppTest).

Uses the Ursa Tectonic FP family (EPD-IES-0022920): 100 mm is the reference
(INS__FIB__0478), 80 mm a variant with factor 0.87 (INS__FIB__0477). The edit
log is a throwaway copy — the project's own edits_data.parquet is never written.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from libs import lib_data
from libs.lib_data import fn153_resolve_base_parquet_path, fn154_resolve_edits_parquet_path
from libs.lib_i18n import fn714_tu as _L

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pages" / "13_Add_Edit_Item.py"
REF_ID, VAR_ID = "INS__FIB__0478", "INS__FIB__0477"

pytestmark = pytest.mark.skipif(
    not (PAGE.exists() and fn153_resolve_base_parquet_path().exists()),
    reason="Add/Edit page or base_data.parquet not available",
)


@pytest.fixture(autouse=True)
def no_url_probes(monkeypatch: pytest.MonkeyPatch):
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


def _select(at: AppTest, eetra_id: str) -> None:
    sel = at.selectbox(key="edit_choice")
    target = [o for o in sel.options if f"({eetra_id})" in o]
    if not target:
        pytest.skip(f"{eetra_id} not in the editable set")
    sel.set_value(target[0]).run()
    assert not at.exception


def _derived(at: AppTest, mode: str, col: str):
    hits = [t for t in at.text_input if str(t.key or "").startswith(f"{mode}_{col}__epdref_")]
    return hits[0] if hits else None


def test_variant_gwp_fields_are_derived_and_locked(page: AppTest):
    _select(page, VAR_ID)
    mode = f"edit_{VAR_ID}"
    a1a3 = _derived(page, mode, "G__GWP_A1A3")
    assert a1a3 is not None and a1a3.disabled
    assert float(a1a3.value) == pytest.approx(2.7 * 0.87)
    assert float(_derived(page, mode, "G__GWP_A4").value) == pytest.approx(1.3 * 0.87)
    assert any("Derived from the EPD reference product" in i.value for i in page.info)


def test_saving_the_reference_updates_its_variants(page: AppTest, edits_copy: Path):
    _select(page, REF_ID)
    mode = f"edit_{REF_ID}"
    assert any("EPD reference product" in i.value for i in page.info)
    page.number_input(key=f"{mode}_G__GWP_A1A3").set_value(3.0).run()
    n_before = len(pd.read_parquet(edits_copy))
    [b for b in page.button
     if _L("💾 Save changes") in b.label][0].click().run()
    assert not page.exception

    log = pd.read_parquet(edits_copy)
    new = log.iloc[n_before:]
    assert REF_ID in set(new["0__EETRA_ID"])
    variants = new.loc[new["0__EETRA_ID"] != REF_ID].set_index("0__EETRA_ID")
    assert len(variants) == 10                      # every N product of the EPD
    assert float(variants.loc[VAR_ID, "G__GWP_A1A3"]) == pytest.approx(3.0 * 0.87)
    assert float(variants.loc[VAR_ID, "G__GWP_A1A3_m3"]) == pytest.approx(3.0 * 0.87 / 0.08)
    assert any("recomputed" in s.value for s in page.success)
