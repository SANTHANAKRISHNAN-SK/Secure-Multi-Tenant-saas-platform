"""
decorators.py
-------------
Reusable route decorators for authentication, role-based access
control (RBAC), and tenant isolation.
"""

import hmac
import time
from functools import wraps

from flask import session, redirect, url_for, flash, g, request

from config import config
from logging_config import app_logger
from auth import validate_jwt, resolve_tenant_and_role, InvalidTokenError

_TOKEN_REFRESH_SKEW_SECONDS = 60


class _TrustedHeaderAuthError(Exception):
    """Raised internally for any failure to establish identity from
    API-Gateway-forwarded headers."""


def _resolve_trusted_header_identity() -> dict:
    shared_secret_header = request.headers.get(config.API_GW_SECRET_HEADER_NAME, "")
    if not config.API_GW_SHARED_SECRET or not hmac.compare_digest(
        shared_secret_header, config.API_GW_SHARED_SECRET
    ):
        raise _TrustedHeaderAuthError("Missing/incorrect API Gateway shared-secret header")

    sub = request.headers.get(config.API_GW_SUB_HEADER_NAME, "").strip()
    username = request.headers.get(config.API_GW_USERNAME_HEADER_NAME, "").strip()
    email = request.headers.get(config.API_GW_EMAIL_HEADER_NAME, "").strip()
    groups_raw = request.headers.get(config.API_GW_GROUPS_HEADER_NAME, "").strip()

    if not sub or not groups_raw:
        raise _TrustedHeaderAuthError("Missing required identity headers (sub/groups)")

    groups = [g_.strip() for g_ in groups_raw.strip("[]").replace('"', "").split(",") if g_.strip()]
    if not groups:
        raise _TrustedHeaderAuthError("Groups header present but contained no usable group names")

    resolved = None
    for group in groups:
        mapping = config.COGNITO_GROUP_MAP.get(group)
        if not mapping:
            continue
        if resolved is None:
            resolved = {"tenant": mapping["tenant"], "role": mapping["role"], "group": group}
        elif resolved["tenant"] != mapping["tenant"]:
            raise _TrustedHeaderAuthError(
                f"Inconsistent tenant claims across groups: {resolved['group']!r} vs {group!r}"
            )

    if resolved is None:
        raise _TrustedHeaderAuthError("No recognized tenant/role group in forwarded claims")

    return {
        "tenant": resolved["tenant"],
        "role": resolved["role"],
        "group": resolved["group"],
        "username": username or sub,
        "email": email or None,
        "sub": sub,
        "user_id": sub,
        "profile_complete": True,
    }


def _resolve_bearer_jwt_identity() -> dict:
    """Extracts and validates JWT from Authorization header or cognito_access_token cookie."""
    auth_header = request.headers.get("Authorization", "")
    token = None

    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = request.cookies.get("cognito_access_token")

    if not token:
        return None

    try:
        claims = validate_jwt(token)
        identity = resolve_tenant_and_role(claims)
        identity["user_id"] = identity.get("sub") or identity.get("username")
        identity["profile_complete"] = True
        return identity
    except InvalidTokenError as exc:
        app_logger.warning("Invalid Bearer/Cookie JWT presented: %s", exc)
        return None


def _resolve_identity():
    """Resolves identity in order: 
    1. Browser Session
    2. Bearer Authorization header or cognito_access_token cookie
    3. Trusted API Gateway headers (if enabled)
    """
    identity = session.get("identity")
    if identity:
        return identity

    bearer_identity = _resolve_bearer_jwt_identity()
    if bearer_identity:
        return bearer_identity

    if not config.API_GATEWAY_TRUSTED_HEADERS_ENABLED:
        return None

    try:
        return _resolve_trusted_header_identity()
    except _TrustedHeaderAuthError as exc:
        app_logger.warning("Rejected request with untrusted/invalid API Gateway headers: %s", exc)
        return None


def _refresh_session_tokens_if_needed() -> bool:
    expires_at = session.get("token_expires_at")
    if not expires_at:
        return True

    if time.time() < (expires_at - _TOKEN_REFRESH_SKEW_SECONDS):
        return True

    refresh_token = session.get("refresh_token")
    if not refresh_token:
        app_logger.warning("Session token expired with no refresh_token available")
        session.clear()
        return False

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


def _is_json_route() -> bool:
    if config.API_GW_SECRET_HEADER_NAME in request.headers or request.headers.get("Authorization"):
        return True
    return any(request.path.startswith(prefix) for prefix in config.JSON_API_ROUTE_PREFIXES)


def _unauthenticated_response():
    if _is_json_route():
        return {"error": "unauthenticated"}, 401
    flash("Please sign in to continue.", "warning")
    return redirect(url_for("auth_pages.login"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = _resolve_identity()
        if not identity:
            return _unauthenticated_response()

        if session.get("identity") and not config.DEMO_MODE and not _refresh_session_tokens_if_needed():
            flash("Your session has expired. Please sign in again.", "warning")
            return redirect(url_for("auth_pages.login"))

        g.identity = identity
        g.tenant = identity["tenant"]
        g.role = identity["role"]
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = _resolve_identity()
        if not identity:
            return _unauthenticated_response()
        if identity["role"] != "admin":
            app_logger.warning(
                "Blocked non-admin access attempt",
                extra={"user_id": identity.get("sub"), "tenant": identity.get("tenant"), "role": identity.get("role")},
            )
            if _is_json_route():
                return {"error": "forbidden"}, 403
            flash("You do not have permission to view that page.", "danger")
            return redirect(url_for("users.dashboard"))
        g.identity = identity
        g.tenant = identity["tenant"]
        g.role = identity["role"]
        return view(*args, **kwargs)

    return wrapped


def profile_setup_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        identity = session.get("identity") or g.get("identity")
        if identity and not identity.get("profile_complete"):
            flash("Please complete your profile before continuing.", "info")
            return redirect(url_for("users.user_details_page"))
        return view(*args, **kwargs)

    return wrapped