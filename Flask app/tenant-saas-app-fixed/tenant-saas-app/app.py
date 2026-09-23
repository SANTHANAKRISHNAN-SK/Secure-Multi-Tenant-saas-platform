"""
app.py
------
Application entry point for the multi-tenant SaaS platform.

Request flow in production:

    Browser
      -> Amazon Cognito Hosted UI (authentication, incl. forced
         "New Password Required" on first login)
      -> Application Load Balancer
      -> ECS Fargate task running THIS Flask app (gunicorn), which
         owns the OAuth2 Authorization Code exchange itself at
         GET /auth/callback (see routes/auth_pages.py)
      -> Amazon RDS (tenant-scoped data), guarded by Secrets Manager + KMS

Flask performs the full OAuth2 Authorization Code Flow against
Cognito's Hosted UI (authorize -> callback -> token exchange), then
independently validates the returned ID token's signature/claims
against Cognito's JWKS (see auth.py) before ever creating a session --
it never trusts a client-supplied token. Tenant + role are resolved
strictly from the validated token's Cognito Groups claim, and the app
renders server-side HTML (Jinja2 + Bootstrap 5) for every page -- the
only JSON endpoint in the whole app is GET /api/v1/health.

SESSION / OAUTH STATE RELIABILITY
----------------------------------
This app stores the PKCE `state` (and `code_verifier`) in the Flask
session between GET /login/cognito and GET /auth/callback. Flask's
default session is a client-side, cryptographically SIGNED cookie --
there is no server-side session store, so there's no sticky-session
requirement at the ALB. However, that also means EVERY ECS Fargate
task must sign/verify with the exact same SECRET_KEY, or a cookie set
by the task that served /login/cognito will fail signature
verification on whichever task the ALB happens to route
/auth/callback to -- which looks exactly like "missing/mismatched
state" and is the most common cause of this class of bug in a
multi-task Fargate deployment. See load_runtime_secrets() below.
"""

import os
import secrets
from datetime import timedelta

from flask import Flask, render_template, request, g
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config
from logging_config import app_logger
from services.secret_service import get_secret
from services.usage_service import record_api_usage

from routes.health import health_bp
from routes.auth_pages import auth_pages_bp
from routes.password import password_bp
from routes.users import users_bp
from routes.admin import admin_bp
from routes.billing import billing_bp


def load_runtime_secrets(app: Flask) -> None:
    """
    Pulls sensitive runtime configuration (DB credentials, Flask
    session signing key, etc.) from AWS Secrets Manager and overlays
    it onto app.config. This means the SECRET_KEY used to sign
    session cookies is never hardcoded in source control.

    FLASK_SECRET_KEY resolution order: Secrets Manager -> environment
    variable -> (DEMO_MODE only) a generated in-memory value.

    IMPORTANT: outside DEMO_MODE we do NOT fall back to a generated
    in-memory key. This app runs as multiple ECS Fargate tasks behind
    an ALB with no server-side session store -- every task signs and
    verifies the session cookie with SECRET_KEY. If each task
    generated its own random key, a session cookie set by the task
    that handled /login/cognito would fail to verify on whichever
    task handles /auth/callback, which manifests as "missing/
    mismatched state or code" on the OAuth callback -- silently, and
    only some of the time, depending on ALB routing. We fail startup
    loudly instead, so this is caught in deployment, not in
    production traffic.

    A hard failure to reach Secrets Manager at all (bad region,
    network, IAM permissions, etc.) is still treated as fatal outside
    DEMO_MODE, because the same fetch also supplies DB credentials
    that the app cannot run without.
    """
    try:
        secret_bundle = get_secret()
    except Exception:
        # Fail safe rather than fail open: if we can't load secrets in
        # a real (non-demo) deployment, refuse to start with a dev key.
        if not config.DEMO_MODE:
            app_logger.exception("Could not load runtime secrets; aborting startup")
            raise
        app_logger.warning("Secrets Manager unavailable; continuing in DEMO_MODE with defaults")
        secret_bundle = {}

    # Secrets Manager JSON in this environment uses "FLASK_SECRET_KEY";
    # older/demo bundles use lowercase "flask_secret_key" -- accept both.
    flask_secret_key = secret_bundle.get("FLASK_SECRET_KEY") or secret_bundle.get("flask_secret_key")
    source = "AWS Secrets Manager"

    if not flask_secret_key:
        flask_secret_key = os.environ.get("FLASK_SECRET_KEY")
        source = "FLASK_SECRET_KEY environment variable"

    if not flask_secret_key:
        if not config.DEMO_MODE:
            # DO NOT fall back to a per-process random key outside demo
            # mode -- see the module/function docstring above for why
            # this breaks OAuth state across multiple Fargate tasks.
            app_logger.error(
                "FLASK_SECRET_KEY not found in Secrets Manager or environment; "
                "refusing to start with an ephemeral per-task key outside DEMO_MODE."
            )
            raise RuntimeError(
                "FLASK_SECRET_KEY is required outside DEMO_MODE (must be identical across "
                "every ECS task so OAuth session state survives the Cognito redirect)."
            )
        flask_secret_key = secrets.token_urlsafe(48)
        source = "securely generated in-memory value (DEMO_MODE only, local/dev)"

    app.config["SECRET_KEY"] = flask_secret_key
    # Log which source was used, never the value itself.
    app_logger.info("Flask SECRET_KEY configured from: %s", source)

    # The Cognito App Client secret (only present for confidential App
    # Clients) is OPTIONAL: an App Client created without a secret is
    # a valid, arguably preferable, setup for a server-rendered app
    # using PKCE. Same fallback order as FLASK_SECRET_KEY, except the
    # final fallback is simply "" (no secret sent on token exchange)
    # rather than a generated value, since there's nothing to invent.
    cognito_client_secret = (
        secret_bundle.get("COGNITO_APP_CLIENT_SECRET")
        or secret_bundle.get("cognito_app_client_secret")
        or os.environ.get("COGNITO_APP_CLIENT_SECRET", "")
    )
    app.config["COGNITO_APP_CLIENT_SECRET"] = cognito_client_secret
    app_logger.info(
        "Cognito App Client secret configured: %s",
        "yes (confidential client)" if cognito_client_secret else "no (public client / PKCE only)",
    )

    app_logger.info("Runtime secrets loaded successfully")


def configure_session(app: Flask) -> None:
    """Configures Flask's session cookie so OAuth `state`/PKCE
    `code_verifier` reliably survive the round trip to Cognito's
    Hosted UI and back, and so the cookie behaves correctly when the
    app is reached through CloudFront -> ALB rather than directly.

    - SESSION_COOKIE_NAME: explicit, stable name (avoids relying on
      Flask's default and makes cookie behavior easy to inspect/debug
      in browser devtools or ALB access logs).
    - SESSION_COOKIE_HTTPONLY: True. JS never needs to read the
      session cookie; blocks it from XSS-based theft.
    - SESSION_COOKIE_SECURE: True outside local dev. The browser only
      ever talks to CloudFront/ALB over HTTPS in real deployments, so
      the cookie must be marked Secure. Only relaxed for local
      `flask run` (config.DEBUG) where there is no TLS at all.
    - SESSION_COOKIE_SAMESITE: "Lax". This is required for the OAuth
      redirect flow: when Cognito's Hosted UI redirects the browser
      back to /auth/callback, that's a top-level GET navigation
      initiated cross-site (from the Cognito domain). SameSite=Lax
      still sends the cookie for top-level GET navigations, so the
      state we stored before leaving for Cognito is available when we
      come back. SameSite=Strict would silently drop the cookie on
      that exact redirect and produce precisely a "missing state"
      error -- if this was ever set to Strict (or a proxy/CDN
      stripped it), that alone would reproduce your symptom.
    - SESSION_COOKIE_DOMAIN: intentionally left unset (None), so the
      cookie is scoped to the exact host the browser used. Do not set
      this to a wildcard/parent domain unless you specifically need
      cross-subdomain SSO -- a mismatched Domain attribute is another
      classic way to "lose" a cookie between two routes on what looks
      like the same site.
    - SESSION_PERMANENT / PERMANENT_SESSION_LIFETIME: short-lived,
      non-permanent by default; explicitly bounded when a session
      does opt into "permanent" (e.g. after successful login) so a
      stale OAuth `state` can't linger indefinitely in the cookie jar.
    - PREFERRED_URL_SCHEME: "https". Ensures any url_for(...,
      _external=True) call (building the Cognito redirect_uri) always
      generates an https:// URL, matching what's registered as the
      allowed callback URL in the Cognito App Client -- even though
      Flask itself is only ever spoken to over plain HTTP inside the
      VPC by the ALB.
    """
    is_local_dev = bool(config.DEBUG)

    app.config["SESSION_COOKIE_NAME"] = "app_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not is_local_dev
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_DOMAIN"] = None
    app.config["SESSION_COOKIE_PATH"] = "/"
    app.config["SESSION_PERMANENT"] = False
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
    app.config["PREFERRED_URL_SCHEME"] = "https"

    app_logger.info(
        "Session cookie configured: name=%s secure=%s samesite=%s httponly=%s",
        app.config["SESSION_COOKIE_NAME"],
        app.config["SESSION_COOKIE_SECURE"],
        app.config["SESSION_COOKIE_SAMESITE"],
        app.config["SESSION_COOKIE_HTTPONLY"],
    )


def configure_proxy_fix(app: Flask) -> None:
    """Installs ProxyFix so Flask/Werkzeug trust the X-Forwarded-*
    headers set by the Application Load Balancer, instead of looking
    at the raw (internal, plain-HTTP) connection from the ALB to this
    Fargate task.

    Without this, request.is_secure is False for every request (the
    ALB terminates TLS and speaks plain HTTP to the task), which in
    turn makes url_for(..., _external=True) build http:// URLs. That
    produces a redirect_uri sent to Cognito that doesn't match the
    https:// callback URL registered on the App Client, and/or a
    mismatch between the scheme used when `state` was stored and the
    scheme Flask thinks the callback request arrived on -- both of
    which surface as OAuth callback failures.

    Topology here is Browser -> CloudFront -> ALB -> Fargate task,
    i.e. exactly ONE proxy hop that Flask itself needs to trust (the
    ALB). CloudFront's edge is a CDN/reverse-proxy in front of the
    ALB, not an additional hop the ALB forwards through untouched --
    the ALB is the proxy immediately in front of Flask and is the
    one adding/normalizing X-Forwarded-For / X-Forwarded-Proto /
    X-Forwarded-Port for this task to trust. Hence x_for=1, x_proto=1,
    x_host=1, x_port=1. If you later add another real proxy hop
    between the ALB and this task (e.g. a service mesh sidecar that
    itself appends to X-Forwarded-*), increase these counts to match
    -- an undercount silently keeps trusting the wrong (spoofable)
    header value, and an overcount lets a client-supplied header
    override the real value, so this must track your actual topology.
    """
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
        x_prefix=1,
    )
    app_logger.info("ProxyFix installed (x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)")


def register_error_handlers(app: Flask) -> None:
    """Renders the branded error page for common HTTP error codes
    instead of Flask's default plain-text errors, and makes sure we
    never leak a JSON stack trace to the browser."""

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message="Bad request."), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You don't have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="That page could not be found."), 404

    @app.errorhandler(500)
    def server_error(e):
        app_logger.exception("Unhandled server error")
        return render_template("error.html", code=500, message="Something went wrong on our end."), 500


def register_security_headers(app: Flask) -> None:
    """Adds standard defensive HTTP response headers on every response."""

    @app.after_request
    def set_secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com fonts.googleapis.com; "
            "font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            "img-src 'self' data:;"
        )
        return response


def register_request_logging(app: Flask) -> None:
    """Logs every request at INFO level with tenant/user context when
    available, for CloudWatch Logs Insights queries and auditing."""

    @app.before_request
    def log_request():
        from flask import session
        identity = session.get("identity") if session else None
        app_logger.info(
            "Incoming request",
            extra={
                "path": request.path,
                "tenant": identity.get("tenant") if identity else None,
                "user_id": identity.get("user_id") if identity else None,
                "role": identity.get("role") if identity else None,
            },
        )


def register_usage_metering(app: Flask) -> None:
    """
    Publishes one tenant usage event per successfully processed,
    authenticated request -- see services/usage_service.py for the
    full design rationale.

    Deliberately implemented as its own `after_request` hook (rather
    than folded into register_request_logging above, or called from
    inside individual routes) so that:
      1. It runs strictly AFTER the view has produced a response --
         it can never block, delay, or fail the actual request.
      2. It requires ZERO changes to routes/users.py, routes/admin.py,
         etc. -- tenant identity is read from flask.g, which
         decorators.py already populates for every authenticated
         route.
      3. Disabling billing entirely is a one-line change: remove the
         call to this function below (or set
         USAGE_METERING_ENABLED=false).
    """

    @app.after_request
    def meter_usage(response):
        identity = getattr(g, "identity", None)
        record_api_usage(
            identity=identity,
            method=request.method,
            path=request.path,
            status_code=response.status_code,
        )
        return response


def create_app() -> Flask:
    """Application factory. Using a factory (rather than a bare
    module-level `app = Flask(__name__)`) makes the app testable and
    keeps configuration/bootstrapping explicit and ordered."""
    app = Flask(__name__)
    app.config.from_object(config)

    load_runtime_secrets(app)
    configure_session(app)

    # Must be installed before anything (including CSRFProtect, which
    # also inspects request.is_secure/scheme for its own cookie/token
    # handling) relies on request.is_secure / request.url / request.host
    # reflecting the real client-facing scheme and host rather than the
    # ALB's internal plain-HTTP connection to this task.
    configure_proxy_fix(app)

    csrf = CSRFProtect()
    csrf.init_app(app)

    # The health check is intentionally exempt from CSRF (it's a GET
    # with no side effects, hit by the ALB with no cookie/session).
    csrf.exempt(health_bp)

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_pages_bp)
    app.register_blueprint(password_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(billing_bp)

    register_error_handlers(app)
    register_security_headers(app)
    register_request_logging(app)
    register_usage_metering(app)

    @app.context_processor
    def inject_globals():
        # Makes DEMO_MODE and the current year available to every
        # template without passing them explicitly each render_template call.
        import datetime
        return {"demo_mode": config.DEMO_MODE, "current_year": datetime.datetime.utcnow().year}

    app_logger.info("Flask application created (env=%s, demo_mode=%s)", config.ENV, config.DEMO_MODE)
    return app


app = create_app()


if __name__ == "__main__":
    # Local/dev entry point only. In production this app is served by
    # gunicorn inside the ECS Fargate task (see Dockerfile / CMD),
    # fronted by the Application Load Balancer.
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=config.DEBUG)
