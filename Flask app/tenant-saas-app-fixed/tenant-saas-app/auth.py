"""
auth.py
-------
JWT validation helper.

Architecture note: this Flask app owns the full OAuth2 Authorization
Code Flow against Cognito's Hosted UI itself (see
routes/auth_pages.py -> callback()). After exchanging the
authorization code for tokens at Cognito's /oauth2/token endpoint,
Flask independently validates the returned ID token's signature and
claims (issuer, audience, expiry, token_use) against Cognito's public
JWKS here -- it never trusts the token exchange response blindly,
and it never accepts a token supplied directly by the browser/client
(e.g. a hidden form field). This is also where "cognito:groups" is
extracted to resolve tenant + role in one place (see
resolve_tenant_and_role() below, used by decorators.py).

Once validated, the identity is stored server-side in a secure
session cookie (see decorators.py / routes/*.py) -- validate_jwt() is
only ever called once, at the callback, not on every request.
"""

import time

import jwt
from jwt import PyJWKClient

from config import config
from logging_config import app_logger

_jwks_client = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(config.COGNITO_JWKS_URL)
    return _jwks_client


class InvalidTokenError(Exception):
    """Raised for any token that fails signature/claims validation."""


def validate_jwt(token: str) -> dict:
    """
    Validates a Cognito-issued JWT's signature against the User Pool's
    JWKS, and checks standard claims (exp, iss, token_use, audience).
    Returns the decoded claims dict on success.

    Raises InvalidTokenError on any failure -- callers must treat that
    as an authentication failure and redirect to login, never as a
    default/anonymous session.
    """
    if config.DEMO_MODE:
        # In demo mode there is no live Cognito User Pool to verify
        # against; we still parse basic claims from a locally-issued
        # demo token so the rest of the app's logic (group -> tenant
        # resolution) can be exercised end-to-end.
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
            return claims
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.COGNITO_APP_CLIENT_ID,
            issuer=f"https://cognito-idp.{config.COGNITO_REGION}.amazonaws.com/{config.COGNITO_USER_POOL_ID}",
        )
        if claims.get("token_use") not in ("id", "access"):
            raise InvalidTokenError("Unexpected token_use claim")
        if claims.get("exp", 0) < time.time():
            raise InvalidTokenError("Token expired")
        return claims
    except jwt.PyJWTError as exc:
        app_logger.warning("JWT validation failed: %s", exc)
        raise InvalidTokenError(str(exc)) from exc


def resolve_tenant_and_role(claims: dict) -> dict:
    """
    Resolves tenant + role SOLELY from the validated token's
    "cognito:groups" claim, using the fixed COGNITO_GROUP_MAP
    whitelist. This is the only sanctioned source of tenant/role in
    the entire application -- it is never read from a form field,
    query string, or JSON body.
    """
    groups = claims.get("cognito:groups", [])
    for group in groups:
        mapping = config.COGNITO_GROUP_MAP.get(group)
        if mapping:
            return {
                "tenant": mapping["tenant"],
                "role": mapping["role"],
                "group": group,
                "username": claims.get("cognito:username") or claims.get("username"),
                "email": claims.get("email"),
                "sub": claims.get("sub"),
            }
    raise InvalidTokenError("Token does not contain a recognized tenant/role group")
