"""Tests for libs/lib_auth_m365.py — the Microsoft 365 option on the startup gate.

No network and no Entra app: ``fn800_m365_config`` is swapped for a fixed dict so
the role/domain rules are exercised on their own. The gate test runs the real
``app.py`` through AppTest and only checks which controls the card offers —
without ``redirect_uri`` the password form must be the only way in.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from libs import lib_auth_m365 as m

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"


@pytest.fixture()
def cfg(monkeypatch):
    """Patchable ``fn800_m365_config`` — call the returned setter with overrides."""
    def _set(**over):
        base = dict(tenant_id="t", client_id="c", client_secret="s",
                    redirect_uri="http://localhost:8502/", scopes=["User.Read"],
                    allowed_domains=[], admin_users=[], developer_users=[],
                    default_role="user")
        base.update(over)
        monkeypatch.setattr(m, "fn800_m365_config", lambda: base)
        return base
    return _set


def test_enabled_needs_the_whole_app_registration(cfg):
    cfg()
    assert m.fn801_m365_enabled()
    cfg(redirect_uri="")
    assert not m.fn801_m365_enabled()


def test_role_lists_win_over_the_default(cfg):
    cfg(admin_users=["a.botti@eetra.it"], developer_users=["dev@eetra.it"])
    assert m.fn806_m365_role_for("a.botti@eetra.it") == "admin"
    assert m.fn806_m365_role_for("DEV@EETRA.IT") == "developer"   # case-insensitive
    assert m.fn806_m365_role_for("someone@eetra.it") == "user"


def test_allowed_domains_reject_outsiders(cfg):
    cfg(allowed_domains=["eetra.it"])
    assert m.fn806_m365_role_for("someone@eetra.it") == "user"
    assert m.fn806_m365_role_for("outsider@gmail.com") is None
    cfg(allowed_domains=[])                                        # unset → any tenant account
    assert m.fn806_m365_role_for("outsider@gmail.com") == "user"


def test_role_matches_the_mail_claim_when_the_upn_differs(cfg):
    cfg(allowed_domains=["eetra.it"], admin_users=["a.botti@eetra.it"])
    assert m.fn806_m365_role_for("abotti_eetra.it#EXT#@tenant.onmicrosoft.com",
                                 "a.botti@eetra.it") == "admin"


@pytest.mark.skipif(not APP.exists(), reason="app.py not available")
def test_gate_hides_the_microsoft_button_until_redirect_uri_is_set(monkeypatch):
    monkeypatch.delenv("M365_REDIRECT_URI", raising=False)
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.secrets["m365"] = {"tenant_id": "t", "client_id": "c", "client_secret": "s"}
    at.run()
    assert not at.exception
    assert [w.label for w in at.text_input] == ["Username", "Password"]
    assert [w.label for w in at.button] == ["Log in"]
    assert list(at.link_button) == []
