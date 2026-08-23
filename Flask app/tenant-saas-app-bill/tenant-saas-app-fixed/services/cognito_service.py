"""
services/cognito_service.py
-----------------------------
Wraps the boto3 `cognito-idp` client for all Cognito User Pool admin
operations used by the admin panel: creating users, assigning them to
the correct tenant/role group, generating temporary passwords, and
deleting/disabling users.

NOTE: JWT *validation* (verifying tokens presented by already-logged
in users) lives in auth.py, not here -- this module is only concerned
with the admin/management-plane API calls, which is a distinct IAM
permission set (cognito-idp:Admin* actions) from the read-only JWKS
verification used on every request.
"""

import base64
import hashlib
import secrets
import string
import uuid
from urllib.parse import urlencode

import boto3
import requests
from botocore.exceptions import ClientError

from config import config
from logging_config import app_logger

# In-memory store used only when DEMO_MODE=true, so the admin panel is
# fully clickable without a live Cognito User Pool.
_demo_cognito_users: dict = {}


def _get_cognito_client():
    return boto3.client("cognito-idp", region_name=config.COGNITO_REGION)


class OAuthExchangeError(Exception):
    """Raised when the Hosted UI authorization-code/refresh-token
    exchange with Cognito's /oauth2/token endpoint fails."""


# ---------------------------------------------------------------------
# OAuth2 Authorization Code Flow (Cognito Hosted UI)
# ---------------------------------------------------------------------
# These helpers are the ONLY place that talks to the Hosted UI's
# /oauth2/authorize, /oauth2/token, and /logout endpoints. Callers
# (routes/auth_pages.py) never build these URLs or POST bodies
# themselves, so the client id/secret handling and PKCE mechanics stay
# in one place.

def generate_pkce_pair() -> tuple:
    """Generates an RFC 7636 PKCE code_verifier / code_challenge
    (S256) pair. Used even when the App Client also has a secret, as
    defense in depth against authorization-code interception/replay."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def generate_state() -> str:
    """Generates an unguessable, single-use `state` value to protect
    the redirect against CSRF (the callback rejects any state that
    doesn't match what was stashed in the session before redirecting
    to Cognito)."""
    return secrets.token_urlsafe(32)


def build_login_url(state: str, code_challenge: str) -> str:
    """Builds the Cognito Hosted UI /oauth2/authorize URL that starts
    the Authorization Code Flow (never the implicit flow -- there is
    no response_type=token anywhere in this app)."""
    params = {
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "response_type": "code",
        "scope": config.COGNITO_SCOPES,
        "redirect_uri": config.COGNITO_REDIRECT_URI,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    return f"{config.COGNITO_AUTHORIZE_URL}?{urlencode(params)}"


def build_logout_url() -> str:
    """Builds the Cognito Hosted UI /logout URL. Redirecting the
    browser here (in addition to clearing the local Flask session)
    ends the user's Hosted UI session too, so a subsequent 'Sign in'
    click can't silently re-authenticate them without re-entering
    credentials."""
    params = {
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "logout_uri": config.COGNITO_LOGOUT_REDIRECT_URI or config.COGNITO_REDIRECT_URI,
    }
    return f"{config.COGNITO_LOGOUT_URL}?{urlencode(params)}"


def _token_request(payload: dict) -> dict:
    """POSTs to Cognito's /oauth2/token endpoint (application/x-www-form-urlencoded,
    per the OAuth2 spec) and returns the decoded JSON body. Uses HTTP
    Basic auth with the App Client secret when one is configured
    (confidential client); omits it entirely for a public client
    relying on PKCE alone."""
    auth = None
    if config.COGNITO_APP_CLIENT_SECRET:
        auth = (config.COGNITO_APP_CLIENT_ID, config.COGNITO_APP_CLIENT_SECRET)

    try:
        response = requests.post(
            config.COGNITO_TOKEN_URL,
            data=payload,
            auth=auth,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except requests.RequestException as exc:
        app_logger.exception("Network error calling Cognito /oauth2/token")
        raise OAuthExchangeError(f"Could not reach Cognito token endpoint: {exc}") from exc

    if response.status_code != 200:
        # Cognito's error body is JSON like {"error": "invalid_grant"};
        # never log the request payload (it may contain the code/refresh token).
        app_logger.warning("Cognito token endpoint returned %s: %s", response.status_code, response.text[:300])
        raise OAuthExchangeError(f"Cognito token endpoint returned HTTP {response.status_code}")

    return response.json()


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """
    Exchanges an OAuth2 authorization code (from the /auth/callback
    redirect) for an ID token, access token, and refresh token. This
    is the ONLY sanctioned way tokens enter this application -- the
    app never accepts a token submitted directly by the browser (e.g.
    a form field), which was the root cause of the original bug.
    """
    payload = {
        "grant_type": "authorization_code",
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "code": code,
        "redirect_uri": config.COGNITO_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    body = _token_request(payload)
    return {
        "id_token": body.get("id_token"),
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token"),
        "expires_in": body.get("expires_in", 3600),
        "token_type": body.get("token_type", "Bearer"),
    }


def refresh_tokens(refresh_token: str) -> dict:
    """
    Exchanges a previously issued refresh token for a new ID token and
    access token (Cognito does not rotate the refresh token itself by
    default, so it isn't re-returned here). Used by decorators.py to
    transparently extend a session shortly before the access/ID token
    expires, instead of forcing the user to log in again every 60
    minutes.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    body = _token_request(payload)
    return {
        "id_token": body.get("id_token"),
        "access_token": body.get("access_token"),
        "expires_in": body.get("expires_in", 3600),
        "token_type": body.get("token_type", "Bearer"),
    }


def _generate_temp_password(length: int = 14) -> str:
    """Generates a temporary password that satisfies Cognito's default
    password policy (upper, lower, digit, symbol)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "!@#$%^&*" for c in pw)):
            return pw


def create_cognito_user(username: str, email: str, tenant: str, role: str) -> dict:
    """
    Creates a Cognito user, assigns it to the Cognito group that
    encodes both tenant and role (e.g. "TenantA_admin"), and returns
    a temporary password for the user's first login.
    """
    group_name = f"{tenant}_{role}"
    temp_password = _generate_temp_password()

    if config.DEMO_MODE:
        user_sub = str(uuid.uuid4())
        _demo_cognito_users[username] = {
            "sub": user_sub, "email": email, "group": group_name,
            "status": "FORCE_CHANGE_PASSWORD", "enabled": True,
        }
        app_logger.info("DEMO_MODE: created mock Cognito user '%s' in group '%s'", username, group_name)
        return {"username": username, "temp_password": temp_password, "group": group_name, "sub": user_sub}

    client = _get_cognito_client()
    try:
        client.admin_create_user(
            UserPoolId=config.COGNITO_USER_POOL_ID,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            TemporaryPassword=temp_password,
            DesiredDeliveryMediums=["EMAIL"],
        )
        client.admin_add_user_to_group(
            UserPoolId=config.COGNITO_USER_POOL_ID,
            Username=username,
            GroupName=group_name,
        )
        app_logger.info("Created Cognito user '%s' in group '%s'", username, group_name)
        return {"username": username, "temp_password": temp_password, "group": group_name}
    except ClientError:
        app_logger.exception("Failed to create Cognito user '%s'", username)
        raise


def delete_cognito_user(username: str) -> None:
    """Permanently deletes a Cognito user."""
    if config.DEMO_MODE:
        _demo_cognito_users.pop(username, None)
        app_logger.info("DEMO_MODE: deleted mock Cognito user '%s'", username)
        return

    client = _get_cognito_client()
    try:
        client.admin_delete_user(UserPoolId=config.COGNITO_USER_POOL_ID, Username=username)
        app_logger.info("Deleted Cognito user '%s'", username)
    except ClientError:
        app_logger.exception("Failed to delete Cognito user '%s'", username)
        raise


def set_user_enabled(username: str, enabled: bool) -> None:
    """Enables or disables a Cognito user (used for the Disable/Enable
    User actions in the admin panel, which is preferred over hard
    delete when an account may need to be restored)."""
    if config.DEMO_MODE:
        if username in _demo_cognito_users:
            _demo_cognito_users[username]["enabled"] = enabled
        app_logger.info("DEMO_MODE: set enabled=%s for '%s'", enabled, username)
        return

    client = _get_cognito_client()
    try:
        if enabled:
            client.admin_enable_user(UserPoolId=config.COGNITO_USER_POOL_ID, Username=username)
        else:
            client.admin_disable_user(UserPoolId=config.COGNITO_USER_POOL_ID, Username=username)
        app_logger.info("Set enabled=%s for Cognito user '%s'", enabled, username)
    except ClientError:
        app_logger.exception("Failed to set enabled state for '%s'", username)
        raise


def change_password(access_token: str, previous_password: str, proposed_password: str) -> None:
    """Changes the password for the currently authenticated user
    (used by the forced first-login password reset flow)."""
    if config.DEMO_MODE:
        app_logger.info("DEMO_MODE: password change accepted (not persisted)")
        return

    client = _get_cognito_client()
    try:
        client.change_password(
            AccessToken=access_token,
            PreviousPassword=previous_password,
            ProposedPassword=proposed_password,
        )
    except ClientError:
        app_logger.exception("Cognito change_password failed")
        raise
