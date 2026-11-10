"""Manufacturers → Monograph renders headlessly and keeps its selection across tabs.

The edit log is redirected to a throwaway copy via the ``[parquet] edits_path``
secret, so ``01_data/edits_data.parquet`` is never written to. AppTest's
session_state has no ``.get()`` in Streamlit 1.60: use ``in`` and ``[]``.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from libs.lib_data import fn153_resolve_base_parquet_path, fn154_resolve_edits_parquet_path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"

pytestmark = pytest.mark.skipif(
    not (APP.exists() and fn153_resolve_base_parquet_path().exists()),
    reason="app.py / base_data.parquet not available",
)


@pytest.fixture()
def page(tmp_path: Path) -> AppTest:
    dest = tmp_path / "edits_data.parquet"
    src = fn154_resolve_edits_parquet_path()
    if src.exists():
        shutil.copy2(src, dest)
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.secrets["parquet"] = {"edits_path": str(dest)}
    at.session_state["auth_user"] = "perf_test"
    at.session_state["auth_role"] = "admin"
    at.session_state["data_platform"] = "Local Parquet"
    at.run()
    at.switch_page("pages/15_Manufacturers.py")
    at.run()
    assert not at.exception
    return at


def _single_product_manufacturer(at: AppTest) -> str:
    df = at.session_state["ORIGINAL_DATA"]
    vc = df["A__Manufacturer"].astype(str).str.strip().value_counts()
    return str(vc[vc == 1].index[0])


def test_monograph_selection_survives_tab_switch(page: AppTest):
    page.selectbox(key="mono_manufacturer").set_value("Knauf").run()
    assert not page.exception and not page.error
    page.session_state["mfr_active_tab"] = "Directory"
    page.run()
    assert not page.exception
    page.session_state["mfr_active_tab"] = "Monograph"
    page.run()
    assert not page.exception
    assert page.selectbox(key="mono_manufacturer").value == "Knauf"


def _mono_payload(at: AppTest) -> dict | None:
    """``window.__MONO__`` from the Interactive view's iframe, or None."""
    import json
    import re
    for el in at.get("iframe"):
        srcdoc = getattr(el.proto, "srcdoc", "") or ""
        m = re.search(r"window\.__MONO__=(.*?);</script>", srcdoc, re.S)
        if m:
            return json.loads(m.group(1).replace("<\\/", "</"))
    return None


@pytest.mark.parametrize("view", ["Interactive", "Standard"])
@pytest.mark.parametrize("which", ["Unical", "single"])
def test_monograph_no_profile_and_single_product(page: AppTest, which: str, view: str):
    name = _single_product_manufacturer(page) if which == "single" else which
    page.session_state["mono_view"] = view
    page.selectbox(key="mono_manufacturer").set_value(name).run()
    assert not page.exception and not page.error
    if view == "Interactive":
        payload = _mono_payload(page)
        assert payload is not None, "Interactive view rendered no monograph component"
        assert payload["name"] == name
        if which == "Unical":
            assert payload["profileFound"] is False   # component shows "No company profile yet"
    elif which == "Unical":
        # The caption is translated (lib_i18n), so match the active language's text.
        from libs.lib_i18n import fn714_tu

        expected = fn714_tu("No company profile yet for this manufacturer.")
        assert any(expected in c.value for c in page.caption)
