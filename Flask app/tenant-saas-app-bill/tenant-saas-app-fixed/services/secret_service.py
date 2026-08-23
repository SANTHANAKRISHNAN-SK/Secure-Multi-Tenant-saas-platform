"""
services/secret_service.py
---------------------------
Thin wrapper around AWS Secrets Manager. Centralizing secret retrieval
here means:
  * we cache secrets in-process (with a short TTL) to avoid hammering
    the Secrets Manager API on every request,
  * every other module asks THIS module for credentials instead of
    reading environment variables directly, so rotation only requires
    restarting/refreshing this cache -- not redeploying the service,
  * DEMO_MODE lets the app run locally without real AWS access.
"""

import json
import time

import boto3
from botocore.exceptions import ClientError

from config import config
from logging_config import app_logger

_cache: dict = {}
_CACHE_TTL_SECONDS = 300

_DEMO_SECRETS = {
    "db_username": "demo_app_user",
    "db_password": "demo-password-not-real",
    "flask_secret_key": "demo-flask-secret-key-not-for-prod",
    "cognito_app_client_secret": "",
}


def _get_secrets_client():
    """
    Creates the boto3 Secrets Manager client, always pinned explicitly
    to config.AWS_REGION.

    We never rely on boto3's implicit region resolution here: passing
    an empty/blank region_name results in a malformed endpoint like
    "https://secretsmanager..amazonaws.com" (note the double dot),
    which is exactly what caused the ECS "Worker failed to boot"
    crash. So we validate the region up front and fail loudly with a
    clear message instead of letting boto3 raise an opaque ValueError
    deep inside client construction.
    """
    region = (config.AWS_REGION or "").strip()

    # --- TEMPORARY DEBUG LOGGING (safe: config values only, no secrets) ---
    print(f"AWS_REGION = {region}")
    print(f"SECRET_NAME = {config.SECRETS_MANAGER_SECRET_NAME}")
    # -----------------------------------------------------------------

    if not region:
        app_logger.error(
            "AWS_REGION is empty/unset - cannot create Secrets Manager client"
        )
        raise ValueError(
            "AWS_REGION is empty. Set the AWS_REGION environment variable "
            "on the ECS task definition (e.g. 'us-east-1')."
        )

    return boto3.client("secretsmanager", region_name=region)


def get_secret(secret_name: str = None) -> dict:
    """
    Retrieves and JSON-decodes a secret from Secrets Manager, with a
    short-lived in-process cache. Falls back to demo values when
    DEMO_MODE is enabled so the app can run without live AWS creds.
    """
    secret_name = secret_name or config.SECRETS_MANAGER_SECRET_NAME

    if not secret_name:
        app_logger.error("SECRETS_MANAGER_SECRET_NAME is empty/unset")
        raise ValueError(
            "SECRETS_MANAGER_SECRET_NAME is empty. Set it on the ECS task "
            "definition (e.g. 'saas/secrets/rds/31')."
        )

    cached = _cache.get(secret_name)
    if cached and (time.time() - cached["fetched_at"]) < _CACHE_TTL_SECONDS:
        return cached["value"]

    if config.DEMO_MODE:
        app_logger.info("DEMO_MODE active - returning mock secret bundle")
        _cache[secret_name] = {"value": _DEMO_SECRETS, "fetched_at": time.time()}
        return _DEMO_SECRETS

    try:
        client = _get_secrets_client()
        response = client.get_secret_value(SecretId=secret_name)
        raw = response.get("SecretString")
        value = json.loads(raw) if raw else {}
        _cache[secret_name] = {"value": value, "fetched_at": time.time()}
        return value
    except ClientError:
        app_logger.exception("Failed to retrieve secret '%s' from Secrets Manager", secret_name)
        raise
    except ValueError:
        # Raised by _get_secrets_client() for a blank region, by the
        # secret-name check above, or by json.loads() for a malformed
        # secret payload -- these are startup-fatal configuration
        # errors, not transient AWS API errors.
        app_logger.exception("Invalid configuration while fetching secret '%s'", secret_name)
        raise
