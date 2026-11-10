"""
libs/lib_auth_m365.py — Microsoft 365 sign-in (Entra ID, authorization code flow)
==================================================================================
Second sign-in option on the startup auth gate, next to the username/password
form in ``lib_data`` (fn111/fn112/fn112a). Delegated permissions: each user signs
in with their own Microsoft 365 account and the app never holds their password.

Ported from the EETRA Cantieri app
(``05_Ricerca e Sviluppo/RES50__Cantieri/StreamlitApp/eetra_cantieri_app/app.py``):
same MSAL ``ConfidentialClientApplication``, same per-session ``SerializableTokenCache``,
same ``_pending_flows`` cache keyed on the OAuth ``state``.

Configure (``.streamlit/secrets.toml``)::

    [m365]
    tenant_id     = "<directory (tenant) id>"
    client_id     = "<application (client) id>"
    client_secret = "<client secret value>"
    redirect_uri  = "http://localhost:8502/"      # must match Entra exactly
    # optional
    scopes           = ["User.Read"]
    allowed_domains  = ["eetra.it"]               # empty → any account in the tenant
    admin_users      = ["a.botti@eetra.it"]
    developer_users  = []
    default_role     = "user"

``tenant_id`` / ``client_id`` / ``client_secret`` fall back to the existing
``[sharepoint]`` section, so a single Entra app registration can serve both —
add the redirect URI to that registration (Authentication → Web) to use it.
``redirect_uri`` has no fallback: without it the Microsoft button stays hidden
and the password form is the only way in.

Functions
  fn800  m365_config              merged [m365] (+ [sharepoint]) settings
  fn801  m365_enabled             True when tenant/client/secret/redirect are all set
  fn802  m365_msal_app            ConfidentialClientApplication on the session token cache
  fn803  m365_login_url           start the flow, return the Microsoft sign-in URL
  fn804  m365_handle_redirect     exchange ?code=&state= for a token, set auth_* state
  fn805  m365_access_token        silent access token for Microsoft Graph
  fn806  m365_role_for            map a signed-in account to an app role
  fn807  m365_sign_out            drop the M365 half of the session
  fn808  m365_render_login_button the gate's "Sign in with Microsoft" control

Session state written on success: ``auth_user`` (UPN / e-mail), ``auth_role``,
``auth_method`` = ``"m365"``, ``auth_display_name``, ``auth_email``.
"""
from __future__ import annotations

import html as _html
import os

import streamlit as st

_SESSION_KEYS = (
    "auth_user", "auth_role", "auth_method", "auth_display_name", "auth_email",
    "m365_token_cache", "m365_login_url", "m365_login_error",
)


def fn800_m365_config() -> dict:
    """Merged M365 settings: ``[m365]`` first, ``[sharepoint]`` / env for the app registration."""
    def _secret(section: str, key: str):
        try:
            return st.secrets.get(section, {}).get(key)
        except Exception:
            return None

    def _listish(value) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = value.replace(";", ",").split(",")
        return [str(v).strip().lower() for v in value if str(v).strip()]

    tenant = _secret("m365", "tenant_id") or _secret("sharepoint", "tenant_id") or os.environ.get("M365_TENANT_ID")
    client = _secret("m365", "client_id") or _secret("sharepoint", "client_id") or os.environ.get("M365_CLIENT_ID")
    secret = (_secret("m365", "client_secret") or _secret("sharepoint", "client_secret")
              or os.environ.get("M365_CLIENT_SECRET"))
    redirect = _secret("m365", "redirect_uri") or os.environ.get("M365_REDIRECT_URI")
    scopes = _secret("m365", "scopes")
    if isinstance(scopes, str):
        scopes = [s.strip() for s in scopes.replace(";", ",").split(",") if s.strip()]
    return {
        "tenant_id": str(tenant).strip() if tenant else "",
        "client_id": str(client).strip() if client else "",
        "client_secret": str(secret).strip() if secret else "",
        "redirect_uri": str(redirect).strip() if redirect else "",
        # MSAL adds openid/profile/offline_access itself — never list them here.
        "scopes": list(scopes) if scopes else ["User.Read"],
        "allowed_domains": _listish(_secret("m365", "allowed_domains")),
        "admin_users": _listish(_secret("m365", "admin_users")),
        "developer_users": _listish(_secret("m365", "developer_users")),
        "default_role": str(_secret("m365", "default_role") or "user").strip() or "user",
    }


def fn801_m365_enabled() -> bool:
    """True when the Entra app registration is complete enough to run the flow."""
    cfg = fn800_m365_config()
    return all(cfg[k] for k in ("tenant_id", "client_id", "client_secret", "redirect_uri"))


@st.cache_resource
def _pending_flows() -> dict:
    """OAuth flows awaiting their redirect, keyed by ``state`` (process-wide, as in Cantieri)."""
    return {}


def fn802_m365_msal_app():
    """``ConfidentialClientApplication`` bound to this browser session's token cache."""
    import msal

    if "m365_token_cache" not in st.session_state:
        st.session_state["m365_token_cache"] = msal.SerializableTokenCache()
    cfg = fn800_m365_config()
    return msal.ConfidentialClientApplication(
        cfg["client_id"],
        client_credential=cfg["client_secret"],
        authority=f"https://login.microsoftonline.com/{cfg['tenant_id']}",
        token_cache=st.session_state["m365_token_cache"],
    )


def fn803_m365_login_url() -> str:
    """Sign-in URL for the authorization code flow (one flow per session, cached)."""
    if "m365_login_url" not in st.session_state:
        cfg = fn800_m365_config()
        flow = fn802_m365_msal_app().initiate_auth_code_flow(
            cfg["scopes"], redirect_uri=cfg["redirect_uri"])
        _pending_flows()[flow["state"]] = flow
        st.session_state["m365_login_url"] = flow["auth_uri"]
    return st.session_state["m365_login_url"]


def fn806_m365_role_for(upn: str, email: str = "") -> str | None:
    """App role for a signed-in account, or ``None`` when the domain is not allowed."""
    cfg = fn800_m365_config()
    identities = {str(x).strip().lower() for x in (upn, email) if str(x or "").strip()}
    if cfg["allowed_domains"]:
        domains = {i.rsplit("@", 1)[-1] for i in identities if "@" in i}
        if not domains & set(cfg["allowed_domains"]):
            return None
    if identities & set(cfg["admin_users"]):
        return "admin"
    if identities & set(cfg["developer_users"]):
        return "developer"
    return cfg["default_role"]


def fn804_m365_handle_redirect() -> bool:
    """Complete the flow when Microsoft redirects back with ``?code=&state=``.

    Returns True once ``auth_user`` is set (the caller should ``st.rerun()``).
    Failures leave ``m365_login_error`` in session state for the gate to show.
    """
    qp = st.query_params
    if "code" not in qp or "state" not in qp or not fn801_m365_enabled():
        return False

    flow = _pending_flows().pop(qp["state"], None)
    if flow is None:
        # Stale or replayed redirect (app restarted, or the link was opened twice).
        st.session_state["m365_login_error"] = "Sign-in expired or already used — please try again."
        st.session_state.pop("m365_login_url", None)
        st.query_params.clear()
        return False

    try:
        result = fn802_m365_msal_app().acquire_token_by_auth_code_flow(
            flow, {k: qp[k] for k in qp})
    except Exception as exc:                                   # msal raises on a tampered response
        st.session_state["m365_login_error"] = f"Microsoft sign-in failed: {str(exc)[:200]}"
        st.session_state.pop("m365_login_url", None)
        st.query_params.clear()
        return False

    if "access_token" not in result:
        st.session_state["m365_login_error"] = (
            f"Microsoft sign-in failed: {result.get('error_description') or result.get('error') or result}"[:260])
        st.session_state.pop("m365_login_url", None)
        st.query_params.clear()
        return False

    claims = result.get("id_token_claims") or {}
    upn = str(claims.get("preferred_username") or claims.get("upn") or "").strip()
    email = str(claims.get("email") or upn).strip()
    role = fn806_m365_role_for(upn, email)
    if role is None:
        cfg = fn800_m365_config()
        st.session_state["m365_login_error"] = (
            f"{upn or 'This account'} is not allowed here "
            f"(accepted domains: {', '.join(cfg['allowed_domains'])}).")
        fn807_m365_sign_out()
        st.query_params.clear()
        return False

    st.session_state["auth_user"] = upn or str(claims.get("name") or "microsoft-user")
    st.session_state["auth_role"] = role
    st.session_state["auth_method"] = "m365"
    st.session_state["auth_display_name"] = str(claims.get("name") or upn)
    st.session_state["auth_email"] = email
    st.session_state.pop("m365_login_error", None)
    st.session_state.pop("m365_login_url", None)
    st.query_params.clear()
    return True


def fn805_m365_access_token() -> str | None:
    """Silent Microsoft Graph access token for the signed-in account, or ``None``."""
    if st.session_state.get("auth_method") != "m365" or not fn801_m365_enabled():
        return None
    app = fn802_m365_msal_app()
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(fn800_m365_config()["scopes"], account=accounts[0])
    return (result or {}).get("access_token")


def fn807_m365_sign_out() -> None:
    """Forget the Microsoft half of the session (the password login clears the rest)."""
    for key in ("m365_token_cache", "m365_login_url", "auth_method",
                "auth_display_name", "auth_email"):
        st.session_state.pop(key, None)


def fn808_m365_render_login_button(container=None) -> None:
    """Render the gate's Microsoft sign-in control. No-op when M365 is not configured."""
    target = container if container is not None else st
    if not fn801_m365_enabled():
        return
    error = st.session_state.pop("m365_login_error", None)
    if error:
        target.error(error)
    try:
        url = fn803_m365_login_url()
    except Exception as exc:
        target.error(f"Microsoft sign-in unavailable: {str(exc)[:200]}")
        return
    # A plain anchor, not ``st.link_button``: Streamlit renders link buttons with
    # target="_blank" for any external URL, so Microsoft would send the redirect
    # to a second tab and leave this one on the sign-in screen for ever. No
    # ``icon`` either — the gate hides app chrome before the Material Symbols
    # font is ready, so a ligature icon paints as its literal name.
    target.markdown(
        "<p class='login-gate-or'>or</p>"
        f"<a class='login-gate-m365' href=\"{_html.escape(url, quote=True)}\" target=\"_self\">"
        "Sign in with Microsoft</a>",
        unsafe_allow_html=True,
    )
