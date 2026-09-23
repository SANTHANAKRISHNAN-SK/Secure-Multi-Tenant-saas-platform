"""
config.py
---------
Centralized configuration for the multi-tenant SaaS application.
All values are sourced from environment variables so the same image
can be promoted across dev / staging / prod on ECS Fargate without
rebuilding. Secrets (DB credentials, Cognito app secret, etc.) are
NEVER stored here directly -- they are fetched at runtime from AWS
Secrets Manager by services/secret_service.py.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration shared by all environments."""

    # ---------------------------------------------------------------
    # Flask core
    # ---------------------------------------------------------------
    # SECRET_KEY is bootstrapped from an env var for local/dev use, but
    # in production it is overwritten at startup with the value pulled
    # from Secrets Manager (see app.py -> load_runtime_secrets()).
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
    ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # ---------------------------------------------------------------
    # Session / Cookie security
    # ---------------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_TTL_MINUTES", "30")))
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    # ---------------------------------------------------------------
    # AWS region / general
    # ---------------------------------------------------------------
    # NOTE: os.environ.get(key, default) only falls back to `default`
    # when the key is completely ABSENT. If the ECS task definition
    # sets AWS_REGION to an empty string (or just whitespace), this
    # call still returns "" and the default is never used. That empty
    # region is what produced the malformed endpoint
    # "https://secretsmanager..amazonaws.com". Guard against that by
    # explicitly falling back to "us-east-1" whenever the resolved
    # value is blank, while still letting a real ECS-provided value
    # take precedence.
    AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"

    # ---------------------------------------------------------------
    # Amazon Cognito
    # ---------------------------------------------------------------
    COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
    COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
    COGNITO_REGION = os.environ.get("COGNITO_REGION", AWS_REGION)
    COGNITO_JWKS_URL = (
        f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
        f"{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )

    # --- OAuth2 Authorization Code Flow (Cognito Hosted UI) ---------
    # COGNITO_DOMAIN is the Hosted UI domain prefix configured on the
    # User Pool App Client, e.g. "tenant-saas.auth.us-east-1.amazoncognito.com"
    # (no scheme, no trailing slash). Used to build the /oauth2/authorize,
    # /oauth2/token, and /logout Hosted UI endpoints below.
    COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "").strip().rstrip("/")

    # Must be registered EXACTLY (scheme + host + path) as a "callback
    # URL" on the App Client, and must point at the ALB-fronted
    # /auth/callback route implemented in routes/auth_pages.py.
    COGNITO_REDIRECT_URI = os.environ.get("COGNITO_REDIRECT_URI", "").strip()

    # Must be registered EXACTLY as a "sign-out URL" on the App Client.
    # Defaults to the login page on the same host as the redirect URI
    # if not explicitly set.
    COGNITO_LOGOUT_REDIRECT_URI = os.environ.get("COGNITO_LOGOUT_REDIRECT_URI", "").strip()

    # NOTE: "aws.cognito.signin.user.admin" is required in addition to
    # openid/email/profile because it is the scope that authorizes the
    # resulting ACCESS TOKEN to call Cognito User Pool "self-service"
    # APIs (ChangePassword, GetUser, UpdateUserAttributes, etc.) via
    # boto3's cognito-idp client. Without it, Cognito issues an access
    # token that authenticates the user but is not authorized to call
    # those APIs, which is exactly the
    # "Access Token does not have required scopes" NotAuthorizedException
    # seen from client.change_password() in services/cognito_service.py.
    COGNITO_SCOPES = os.environ.get(
        "COGNITO_SCOPES", "openid email profile aws.cognito.signin.user.admin"
    ).strip()

    # Set by app.py -> load_runtime_secrets() from Secrets Manager at
    # startup for confidential App Clients. Left blank for App Clients
    # created WITHOUT a secret (public clients using PKCE only), which
    # is the recommended setting for a server-rendered app like this
    # one since it avoids storing a long-lived shared secret at all.
    COGNITO_APP_CLIENT_SECRET = os.environ.get("COGNITO_APP_CLIENT_SECRET", "").strip()

    @property
    def COGNITO_AUTHORIZE_URL(self) -> str:
        return f"https://{self.COGNITO_DOMAIN}/oauth2/authorize"

    @property
    def COGNITO_TOKEN_URL(self) -> str:
        return f"https://{self.COGNITO_DOMAIN}/oauth2/token"

    @property
    def COGNITO_LOGOUT_URL(self) -> str:
        return f"https://{self.COGNITO_DOMAIN}/logout"

    # Cognito Group -> (tenant, role) mapping. This is the ONLY place
    # tenant/role resolution happens; it is derived from the validated
    # JWT's "cognito:groups" claim and is never accepted from the UI.
    COGNITO_GROUP_MAP = {
        "TenantA_admin": {"tenant": "TenantA", "role": "admin"},
        "TenantA_user": {"tenant": "TenantA", "role": "user"},
        "TenantB_admin": {"tenant": "TenantB", "role": "admin"},
        "TenantB_user": {"tenant": "TenantB", "role": "user"},
    }

    # ---------------------------------------------------------------
    # Boundary between "browser session cookie" and "bearer-token API
    # client" responses on an auth failure (Option A, confirmed against
    # the actual API Gateway resource map: only these paths are ever
    # true JSON responses in this app -- everything else under /api/v1/
    # still renders HTML or redirects, and must keep the original
    # redirect-to-login UX on an auth failure, not a raw 401 JSON body).
    # /api/v1/health is intentionally excluded -- it has no decorator
    # at all and is always public.
    # ---------------------------------------------------------------
    JSON_API_ROUTE_PREFIXES = tuple(
        p.strip() for p in os.environ.get("JSON_API_ROUTE_PREFIXES", "/api/v1/billing/").split(",") if p.strip()
    )

    # ---------------------------------------------------------------
    # API Gateway + Cognito Authorizer trusted-header identity path
    # (migration addition -- see MIGRATION_REVIEW.md section 3)
    #
    # This is entirely OPT-IN and defaults to disabled. It exists for
    # programmatic/API clients that call the JSON endpoints directly
    # with a bearer JWT validated upstream by an API Gateway Cognito
    # Authorizer; the browser OAuth/session-cookie flow is completely
    # unaffected by these settings.
    #
    # The header names below are placeholders matching a common REST
    # API mapping-template shape -- they are NOT guaranteed to match
    # your actual API Gateway integration and MUST be set to the real
    # values (via env vars) before API_GATEWAY_TRUSTED_HEADERS_ENABLED
    # is turned on. See decorators.py::_resolve_trusted_header_identity.
    # ---------------------------------------------------------------
    API_GATEWAY_TRUSTED_HEADERS_ENABLED = (
        os.environ.get("API_GATEWAY_TRUSTED_HEADERS_ENABLED", "false").lower() == "true"
    )

    # Shared secret that API Gateway's mapping template must inject on
    # every request it forwards, and that the ALB/ECS listener path
    # cannot produce on its own. This is the ONLY thing standing
    # between "request came through the Cognito Authorizer" and "request
    # hit the ALB directly" for this path (the ALB cannot itself verify
    # a JWT). In production this MUST come from Secrets Manager, not a
    # plaintext env var -- wire it through services/secret_service.py
    # once the real value exists; the env var fallback here is for
    # local/dev exercising of the code path only.
    API_GW_SHARED_SECRET = os.environ.get("API_GW_SHARED_SECRET", "").strip()
    API_GW_SECRET_HEADER_NAME = os.environ.get("API_GW_SECRET_HEADER_NAME", "X-Api-Gateway-Secret").strip()

    # Claim-forwarding header names -- confirm/replace against your
    # actual API Gateway mapping template before enabling.
    API_GW_SUB_HEADER_NAME = os.environ.get("API_GW_SUB_HEADER_NAME", "X-Amzn-Cognito-Sub").strip()
    API_GW_USERNAME_HEADER_NAME = os.environ.get("API_GW_USERNAME_HEADER_NAME", "X-Amzn-Cognito-Username").strip()
    API_GW_EMAIL_HEADER_NAME = os.environ.get("API_GW_EMAIL_HEADER_NAME", "X-Amzn-Cognito-Email").strip()
    API_GW_GROUPS_HEADER_NAME = os.environ.get("API_GW_GROUPS_HEADER_NAME", "X-Amzn-Cognito-Groups").strip()

    # ---------------------------------------------------------------
    # AWS Secrets Manager
    # ---------------------------------------------------------------
    SECRETS_MANAGER_SECRET_NAME = os.environ.get(
        "SECRETS_MANAGER_SECRET_NAME", "saas/secrets/rds/31"
    ).strip() or "saas/secrets/rds/31"

    # ---------------------------------------------------------------
    # AWS KMS
    # ---------------------------------------------------------------
    KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "")

    # ---------------------------------------------------------------
    # Amazon RDS (host/port/db name are non-secret; user/password come
    # from Secrets Manager at runtime)
    # ---------------------------------------------------------------
    RDS_HOST = os.environ.get("RDS_HOST", "localhost")
    RDS_PORT = int(os.environ.get("RDS_PORT", "3306"))
    RDS_DB_NAME = os.environ.get("RDS_DB_NAME", "tenant_saas")
    RDS_CONNECT_TIMEOUT = int(os.environ.get("RDS_CONNECT_TIMEOUT", "5"))

    # ---------------------------------------------------------------
    # CloudWatch / logging
    # ---------------------------------------------------------------
    LOG_GROUP_NAME = os.environ.get("LOG_GROUP_NAME", "/ecs/tenant-saas-app")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # ---------------------------------------------------------------
    # Demo / local-dev mode. When true, services/*.py fall back to
    # in-memory mock data instead of calling real AWS APIs, so the
    # app is runnable and demoable without live AWS credentials.
    # This MUST be false in any real deployment.
    # ---------------------------------------------------------------
    DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"

    # ---------------------------------------------------------------
    # Tenant usage metering / billing (additive feature -- see
    # services/usage_service.py). Disabled entirely by default so
    # this can be turned on per-environment without a code change,
    # and turned off instantly (e.g. incident response) by flipping
    # one env var, with zero impact on the existing request path.
    # ---------------------------------------------------------------
    USAGE_METERING_ENABLED = os.environ.get("USAGE_METERING_ENABLED", "false").lower() == "true"
    USAGE_EVENTS_QUEUE_URL = os.environ.get("USAGE_EVENTS_QUEUE_URL", "").strip()
    # Hard cap so a slow/unreachable SQS endpoint can never noticeably
    # delay a response to the browser; this is best-effort telemetry,
    # not part of the user-facing transaction.
    USAGE_PUBLISH_TIMEOUT_SECONDS = float(os.environ.get("USAGE_PUBLISH_TIMEOUT_SECONDS", "1.5"))

    # ---------------------------------------------------------------
    # Billing Dashboard (reads the metering pipeline's output; never
    # writes to it -- see services/billing_service.py). Table name
    # matches the "UsageMonthlyAggregate" table already documented in
    # metering_lambda/DEPLOY.md; the Flask app only ever issues
    # Query (never Scan) against a single tenant's partition.
    # ---------------------------------------------------------------
    USAGE_AGGREGATE_TABLE = os.environ.get("USAGE_AGGREGATE_TABLE", "UsageMonthlyAggregate").strip()

    # Tenant -> billing plan. Placeholder mapping until a real
    # subscription/plan record exists (see services/billing_service.py
    # module docstring for why). Override per-environment via
    # BILLING_PLAN_MAP_JSON, e.g. '{"TenantA": "Enterprise"}'.
    BILLING_PLAN_MAP = {"TenantA": "Pro", "TenantB": "Basic"}
    _plan_map_override = os.environ.get("BILLING_PLAN_MAP_JSON", "").strip()
    if _plan_map_override:
        import json as _json
        try:
            BILLING_PLAN_MAP.update(_json.loads(_plan_map_override))
        except (ValueError, TypeError):
            pass  # invalid override -- keep the safe static default


config = Config()
