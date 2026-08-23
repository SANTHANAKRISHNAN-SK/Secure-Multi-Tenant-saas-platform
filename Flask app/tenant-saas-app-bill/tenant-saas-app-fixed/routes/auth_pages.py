"""
routes/auth_pages.py
---------------------
Implements the full Cognito Hosted UI OAuth2 Authorization Code Flow
and turns the resulting validated identity into a server-side Flask
session.

    GET  /login             render the sign-in page
    GET  /login/cognito     starts the flow: redirects to Cognito's
                             Hosted UI /oauth2/authorize (never the
                             implicit flow -- there is no
                             response_type=token anywhere here)
    GET  /auth/callback     OAuth2 callback: exchanges the returned
                             `code` for tokens, validates the ID
                             token, creates the session
    GET/POST /logout        clears the local session AND ends the
                             Hosted UI session via Cognito's /logout

Previously, login.html posted a permanently-empty hidden `id_token`
field straight to this blueprint, so the Cognito ID token never
reached Flask and every login failed with HTTP 400. That dead code
path has been removed; this module now performs the token exchange
itself against Cognito's /oauth2/token endpoint (see
services/cognito_service.py) and never accepts a token supplied
directly by the browser.

DEMO_MODE keeps its own separate, clearly-labeled path (a dropdown
that simulates a validated JWT's claims) so the app remains fully
clickable without a live Cognito User Pool -- it is never reachable
when DEMO_MODE is false.

DEBUG LOGGING (temporary, for diagnosing "missing/mismatched state or
code" on /auth/callback): /login/cognito logs the state it stores and
a truncated prefix of the PKCE code_verifier (never the full verifier
-- it's a secret used to bind the token exchange); /auth/callback logs
the state it finds in the session vs. the state Cognito sent back, and
whether a code was present, immediately on entry and before any
validation runs. Remove or lower these to DEBUG level once the root
cause is confirmed.
"""

import time

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from auth import validate_jwt, resolve_tenant_and_role, InvalidTokenError
from config import config
from logging_config import app_logger
from services.rds_service import get_user_by_username
from services.cognito_service import (
    generate_pkce_pair,
    generate_state,
    build_login_url,
    build_logout_url,
    exchange_code_for_tokens,
    OAuthExchangeError,
)

auth_pages_bp = Blueprint("auth_pages", __name__)

# Profile fields that must be filled in before a user is considered
# "set up" -- mirrors _profile_completion() in routes/users.py. Kept
# here too (rather than importing across blueprints) to avoid a
# circular import; both read from the same RDS record shape.
_REQUIRED_PROFILE_FIELDS = ("phone", "department")


def _profile_is_complete(record: dict) -> bool:
    if not record:
        return False
    return all(record.get(field) for field in _REQUIRED_PROFILE_FIELDS)


def _build_identity(claims: dict) -> dict:
    """Resolves tenant/role from validated claims, then enriches the
    identity with the RDS-side profile state so downstream routes
    know whether to send the user to profile setup or the dashboard."""
    identity = resolve_tenant_and_role(claims)

    # Determine profile-completeness (and the tenant-table userId) by
    # joining on username -- the Cognito `sub` is not the RDS primary
    # key in this schema; `userId` is the admin-assigned identifier
    # created alongside the Cognito user in routes/admin.py.
    record = get_user_by_username(identity["tenant"], identity["username"])
    identity["user_id"] = record["userId"] if record else None
    identity["profile_complete"] = _profile_is_complete(record)
    # Retained for display/logging/back-compat; no longer used to gate
    # access -- Cognito's Hosted UI itself forces a password change on
    # first login (FORCE_CHANGE_PASSWORD) before the browser is ever
    # redirected back to /auth/callback, so by the time Flask sees the
    # user, that step is already done.
    identity["first_login"] = bool(record["first_login"]) if record else True
    return identity


def _start_session(identity: dict, tokens: dict = None) -> None:
    session.clear()
    session.permanent = True
    session["identity"] = identity
    if tokens:
        session["access_token"] = tokens.get("access_token")
        session["refresh_token"] = tokens.get("refresh_token")
        session["token_expires_at"] = time.time() + int(tokens.get("expires_in", 3600))


def _post_login_redirect(identity: dict):
    if not identity.get("profile_complete"):
        return redirect(url_for("users.user_details_page"))
    if identity["role"] == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("users.dashboard"))


@auth_pages_bp.route("/", methods=["GET"])
def index():
    if session.get("identity"):
        return redirect(url_for("users.dashboard"))
    return redirect(url_for("auth_pages.login"))


@auth_pages_bp.route("/login", methods=["GET"])
def login():
    if session.get("identity"):
        return redirect(url_for("users.dashboard"))
    return render_template("login.html", demo_mode=config.DEMO_MODE)


@auth_pages_bp.route("/login/cognito", methods=["GET"])
def login_redirect():
    """Starts the real OAuth2 Authorization Code Flow by redirecting
    to Cognito's Hosted UI. Not available in DEMO_MODE, since there is
    no live User Pool / App Client to redirect to."""
    if config.DEMO_MODE:
        flash("DEMO_MODE is enabled -- use the tenant/role picker below to sign in.", "info")
        return redirect(url_for("auth_pages.login"))

    if not (config.COGNITO_DOMAIN and config.COGNITO_APP_CLIENT_ID and config.COGNITO_REDIRECT_URI):
        app_logger.error("Cognito Hosted UI is not fully configured (COGNITO_DOMAIN/APP_CLIENT_ID/REDIRECT_URI)")
        flash("Sign-in is temporarily unavailable. Please contact your administrator.", "danger")
        return redirect(url_for("auth_pages.login"))

    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()

    # Stashed in the session (not permanent -- this must not outlive
    # the redirect round-trip) so /auth/callback can verify both the
    # anti-CSRF state and complete the PKCE handshake.
    session["oauth_state"] = state
    session["oauth_code_verifier"] = code_verifier

    # DEBUG: confirm what was actually written to the session before
    # the redirect to Cognito. Compare these values against the
    # "Callback saved state" log line on /auth/callback for the same
    # request -- if they differ, the session cookie itself isn't
    # surviving the round trip (cookie config / shared SECRET_KEY
    # across ECS tasks / SameSite), not the OAuth logic.
    app_logger.info(f"OAuth state stored: {state}")
    app_logger.info(f"Code verifier stored: {code_verifier[:20]}...")

    return redirect(build_login_url(state=state, code_challenge=code_challenge))


@auth_pages_bp.route("/login", methods=["POST"])
def login_demo_submit():
    """DEMO_MODE-only form handler that simulates a validated JWT's
    claims via a tenant/role dropdown, so the full app can be
    exercised without a live Cognito User Pool. Real deployments never
    hit this branch -- the Hosted UI flow above (GET /login/cognito)
    is the only path that can create a session when DEMO_MODE=false."""
    if not config.DEMO_MODE:
        flash("Please sign in with Cognito.", "warning")
        return redirect(url_for("auth_pages.login"))

    demo_group = request.form.get("demo_group", "").strip()
    if not demo_group:
        flash("Please choose a group to simulate.", "danger")
        return redirect(url_for("auth_pages.login"))

    try:
        claims = {
            "cognito:groups": [demo_group],
            "cognito:username": request.form.get("username", "demo.user"),
            "email": request.form.get("email", "demo.user@example.com"),
            "sub": "demo-sub",
        }
        identity = _build_identity(claims)
        _start_session(identity)

        app_logger.info(
            "User authenticated (DEMO_MODE)",
            extra={"tenant": identity["tenant"], "role": identity["role"], "user_id": identity.get("sub")},
        )
        return _post_login_redirect(identity)

    except InvalidTokenError as exc:
        app_logger.warning("Demo login rejected: %s", exc)
        flash("We couldn't verify your credentials. Please try signing in again.", "danger")
        return redirect(url_for("auth_pages.login"))


@auth_pages_bp.route("/auth/callback", methods=["GET"])
def callback():
    """
    OAuth2 Authorization Code Flow callback. This route's full URL
    must be registered EXACTLY as a "callback URL" on the Cognito App
    Client (COGNITO_REDIRECT_URI).

    Flow: validate `state` -> exchange `code` for tokens -> validate
    the ID token against Cognito's JWKS -> resolve tenant/role ->
    create the Flask session -> route to profile setup or dashboard.
    """
    error = request.args.get("error")
    if error:
        app_logger.warning("Cognito returned an OAuth error: %s (%s)", error, request.args.get("error_description"))
        flash("Sign-in was cancelled or failed. Please try again.", "warning")
        return redirect(url_for("auth_pages.login"))

    # DEBUG: capture the raw inputs to state validation *before*
    # popping anything off the session, so these values are exactly
    # what was available at the top of the request.
    saved_state = session.get("oauth_state")
    received_state = request.args.get("state")
    code = request.args.get("code")

    app_logger.info(f"Callback saved state: {saved_state}")
    app_logger.info(f"Callback received state: {received_state}")
    app_logger.info(f"Callback received code exists: {bool(code)}")

    returned_state = received_state
    expected_state = session.pop("oauth_state", None)
    code_verifier = session.pop("oauth_code_verifier", None)

    if not code or not returned_state or not expected_state or returned_state != expected_state:
        app_logger.warning("OAuth callback rejected: missing/mismatched state or code")
        flash("Your sign-in request could not be verified. Please try signing in again.", "danger")
        return redirect(url_for("auth_pages.login"))

    try:
        tokens = exchange_code_for_tokens(code=code, code_verifier=code_verifier)
        if not tokens.get("id_token"):
            raise OAuthExchangeError("Token endpoint response did not include an id_token")

        claims = validate_jwt(tokens["id_token"])
        identity = _build_identity(claims)

        _start_session(identity, tokens=tokens)

        app_logger.info(
            "User authenticated",
            extra={"tenant": identity["tenant"], "role": identity["role"], "user_id": identity.get("sub")},
        )
        return _post_login_redirect(identity)

    except (OAuthExchangeError, InvalidTokenError) as exc:
        app_logger.warning("Login rejected: %s", exc)
        flash("We couldn't verify your credentials. Please try signing in again.", "danger")
        return redirect(url_for("auth_pages.login"))
    except Exception:
        app_logger.exception("Unexpected error during OAuth callback handling")
        flash("Something went wrong while signing you in. Please try again.", "danger")
        return redirect(url_for("auth_pages.login"))


@auth_pages_bp.route("/logout", methods=["POST", "GET"])
def logout():
    was_demo = config.DEMO_MODE
    session.clear()

    if was_demo or not config.COGNITO_DOMAIN:
        flash("You have been signed out.", "info")
        return redirect(url_for("auth_pages.login"))

    # End the Hosted UI session too, not just the local Flask cookie,
    # so a subsequent "Sign in" click can't silently re-authenticate
    # the user without re-entering credentials.
    return redirect(build_logout_url())
