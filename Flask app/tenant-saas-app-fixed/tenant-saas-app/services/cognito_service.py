"""
services/cognito_service.py
-----------------------------
Wraps the boto3 `cognito-idp` client and handles OAuth2 endpoints.
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

_demo_cognito_users: dict = {}


def _get_cognito_client():
    return boto3.client("cognito-idp", region_name=config.COGNITO_REGION)


class OAuthExchangeError(Exception):
    """Raised when OAuth exchange with Cognito fails."""


def generate_pkce_pair() -> tuple:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_login_url(state: str, code_challenge: str, scope: str = None) -> str:
    if not scope:
        scope = getattr(config, "COGNITO_SCOPES", None) or "openid email profile aws.cognito.signin.user.admin saas-api/read saas-api/write"
    
    if "saas-api/read" not in scope:
        scope = f"{scope} saas-api/read".strip()

    params = {
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": config.COGNITO_REDIRECT_URI,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    return f"{config.COGNITO_AUTHORIZE_URL}?{urlencode(params)}"


def build_logout_url() -> str:
    params = {
        "client_id": config.COGNITO_APP_CLIENT_ID,
        "logout_uri": config.COGNITO_LOGOUT_REDIRECT_URI or config.COGNITO_REDIRECT_URI,
    }
    return f"{config.COGNITO_LOGOUT_URL}?{urlencode(params)}"


def _token_request(payload: dict) -> dict:
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
        app_logger.warning("Cognito token endpoint returned %s: %s", response.status_code, response.text[:300])
        raise OAuthExchangeError(f"Cognito token endpoint returned HTTP {response.status_code}")

    return response.json()


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
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
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "!@#$%^&*" for c in pw)):
            return pw


def create_cognito_user(username: str, email: str, tenant: str, role: str) -> dict:
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