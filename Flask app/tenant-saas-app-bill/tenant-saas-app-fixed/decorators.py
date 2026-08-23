"""
decorators.py
-------------
Reusable route decorators for authentication, role-based access
control (RBAC), and tenant isolation. Every protected route in
routes/*.py should be wrapped with @login_required at minimum, and
@admin_required for admin-only endpoints.

Session contract: after a successful login, session["identity"] holds
a small dict: {tenant, role, group, username, email, sub, user_id,
profile_complete}. This is the ONLY place tenant/role are read from
for authorization decisions inside route handlers -- never from
request.form/args/json. For real (non-DEMO_MODE) logins, the session
also holds access_token / refresh_token / token_expires_at, set by
routes/auth_pages.py after the OAuth2 token exchange.
"""

import time
from functools import wraps

from flask import session, redirect, url_for, flash, g

from config import config
from logging_config import app_logger

# Refresh the Cognito access/ID token this many seconds before its
# actual expiry, so a request never races an about-to-expire token.
_TOKEN_REFRESH_SKEW_SECONDS = 60


def _refresh_session_tokens_if_needed() -> bool:
    """
    If the session holds a Cognito token nearing expiry, transparently
    exchanges the stored refresh token for a new access/ID token
    instead of forcing the user to log in again every
    PERMANENT_SESSION_LIFETIME. Returns False (and clears the
    session) if a refresh was needed but failed, so the caller can
    redirect to login; returns True otherwise.

    No-op for DEMO_MODE sessions (they never have a token_expires_at).
    """
    expires_at = session.get("token_expires_at")
    if not expires_at:
        return True  # nothing to refresh (DEMO_MODE, or no tokens stored)

    if time.time() < (expires_at - _TOKEN_REFRESH_SKEW_SECONDS):
        return True  # still fresh

    refresh_token = session.get("refresh_token")
    if not refresh_token:
        app_logger.warning("Session token expired with no refresh_token available")
        session.clear()
        return False

    # Imported lazily to avoid a circular import (cognito_service ->
    # config/logging_config only; this keeps decorators.py import-safe
    # for every route module).
    from services.cognito_service import refresh_tokens, OAuthExchangeError

    try:
        new_tokens = refresh_tokens(refresh_token)
        session["access_token"] = new_tokens.get("access_token")
        session["token_expires_at"] = time.time() + int(new_tokens.get("expires_in", 3600))
        app_logger.info("Refreshed Cognito access token for user_id=%s",
                         (session.get("identity") or {}).get("sub"))
        return True
    except OAuthExchangeError:
        app_logger.warning("Token refresh failed; forcing re-login for user_id=%s",
                            (session.get("identity") or {}).get("sub"))
        session.clear()
        return False


def login_required(view):
    """Ensures a validated identity exists in the session before
    allowing access; otherwise redirects to the login page. Also
    transparently refreshes an expiring access token (see above)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = session.get("identity")
        if not identity:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth_pages.login"))

        if not config.DEMO_MODE and not _refresh_session_tokens_if_needed():
            flash("Your session has expired. Please sign in again.", "warning")
            return redirect(url_for("auth_pages.login"))

        # Make the identity conveniently available on flask.g for the
        # duration of the request without re-reading the session.
        g.identity = identity
        g.tenant = identity["tenant"]
        g.role = identity["role"]
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Restricts a route to users whose resolved role is 'admin'.
    Must be combined with @login_required (or used after it) so
    g.identity is already populated."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = session.get("identity")
        if not identity:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth_pages.login"))
        if identity["role"] != "admin":
            app_logger.warning(
                "Blocked non-admin access attempt",
                extra={"user_id": identity.get("sub"), "tenant": identity.get("tenant"), "role": identity.get("role")},
            )
            flash("You do not have permission to view that page.", "danger")
            return redirect(url_for("users.dashboard"))
        g.identity = identity
        g.tenant = identity["tenant"]
        g.role = identity["role"]
        return view(*args, **kwargs)

    return wrapped


def profile_setup_required(view):
    """
    Forces users through the profile-setup page before they can reach
    any other authenticated page, until their RDS profile record has
    the required fields filled in.

    Note: this deliberately does NOT gate on password state. Cognito's
    Hosted UI itself forces a "New Password Required" change on first
    login (FORCE_CHANGE_PASSWORD) *before* the browser is ever
    redirected back to /auth/callback -- Flask never sees a session
    for a user who hasn't completed that step, so there is nothing
    left for Flask to enforce there. What Flask does still need to
    enforce is the app-specific profile (phone/department) that only
    exists in RDS, which is what this checks.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = session.get("identity")
        if identity and not identity.get("profile_complete"):
            flash("Please complete your profile before continuing.", "info")
            return redirect(url_for("users.user_details_page"))
        return view(*args, **kwargs)

    return wrapped
