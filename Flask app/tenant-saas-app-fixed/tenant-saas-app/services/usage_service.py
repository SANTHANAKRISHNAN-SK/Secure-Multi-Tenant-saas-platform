"""
services/usage_service.py
--------------------------
Tenant-aware API usage metering.

This module is intentionally the ONLY place that builds and publishes
a billing usage event. It is called from a single site -- the
`after_request` hook registered in app.py (register_usage_metering)
-- and nowhere else, so it can be disabled by flipping
USAGE_METERING_ENABLED=false (config.py) or by removing that one
registration call, without touching any route/business logic.

SECURITY: tenant_id / user_id are read ONLY from `flask.g.identity`,
which is set by decorators.py's @login_required / @admin_required
from the server-side session, which was itself populated once at
/auth/callback from a cryptographically validated Cognito JWT (see
auth.py). This module never reads request.form / request.args /
request.json for tenant identity, and never accepts a tenant_id
parameter from a caller -- there is deliberately no code path that
allows the client to influence which tenant a usage event is
attributed to.

RELIABILITY: publishing a usage event is a best-effort, fire-and-
forget side effect of an already-completed request. Any failure here
(SQS unreachable, IAM misconfigured, throttled, etc.) is caught,
logged, and swallowed -- it must NEVER turn a successful user-facing
response into an error, and it must never add meaningful latency to
the response (a short boto3 connect/read timeout is enforced).
"""

import json
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from config import config
from logging_config import app_logger

_sqs_client = None

# In DEMO_MODE (or if metering is simply disabled) we never touch a
# real SQS queue -- events are just logged, mirroring the DEMO_MODE
# pattern used throughout services/*.py.
_demo_published_events: list = []


def _get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client(
            "sqs",
            region_name=config.AWS_REGION,
            config=BotoConfig(
                connect_timeout=config.USAGE_PUBLISH_TIMEOUT_SECONDS,
                read_timeout=config.USAGE_PUBLISH_TIMEOUT_SECONDS,
                retries={"max_attempts": 1},  # fail fast; DLQ handles real retry semantics
            ),
        )
    return _sqs_client


def _is_billable_status(status_code: int) -> bool:
    """
    Only successfully processed requests are counted as billable
    usage. 2xx and 3xx (most mutating routes in this app redirect on
    success rather than returning 200 -- see routes/users.py,
    routes/admin.py) count; 4xx/5xx (auth failures, CSRF rejection,
    validation errors returned directly as an error status, server
    errors) do not.

    Known limitation (flagged, not hidden): a handful of routes also
    redirect (302) on a *failed* form validation (e.g. missing
    required field), which is indistinguishable from a successful
    redirect by status code alone. Treating this as billable is an
    accepted over-count for v1; tightening this later means having
    those routes set a response header/flag on the failure path and
    checking it here -- no change needed elsewhere.
    """
    return 200 <= status_code < 400


def build_usage_event(*, identity: dict, method: str, path: str, status_code: int, usage_units: int = 1) -> dict:
    """Builds the canonical usage-event payload. Pure function (no I/O)
    so it's trivially unit-testable independent of SQS."""
    return {
        "event_id": str(uuid.uuid4()),
        "tenant_id": identity["tenant"],
        "user_id": identity.get("user_id") or identity.get("sub") or identity.get("username"),
        "action": f"{method} {path}",
        "api_path": path,
        "http_method": method,
        "status_code": status_code,
        "usage_units": usage_units,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def _publish(event: dict) -> None:
    if config.DEMO_MODE or not config.USAGE_METERING_ENABLED:
        # Local/dev or explicitly disabled: record in-memory only, so
        # the rest of the pipeline is exercisable without live AWS.
        _demo_published_events.append(event)
        app_logger.info(
            "Usage event recorded (DEMO/disabled, not sent to SQS)",
            extra={"tenant": event["tenant_id"], "user_id": event["user_id"], "path": event["api_path"]},
        )
        return

    if not config.USAGE_EVENTS_QUEUE_URL:
        app_logger.warning("USAGE_METERING_ENABLED=true but USAGE_EVENTS_QUEUE_URL is not set; dropping event")
        return

    _get_sqs_client().send_message(
        QueueUrl=config.USAGE_EVENTS_QUEUE_URL,
        MessageBody=json.dumps(event),
        MessageAttributes={
            "tenant_id": {"DataType": "String", "StringValue": event["tenant_id"]},
        },
    )


def record_api_usage(identity: dict, method: str, path: str, status_code: int, usage_units: int = 1) -> None:
    """
    Public entry point. Builds and publishes one usage event for an
    authenticated, successfully processed request. Never raises --
    all failures are caught and logged so the caller (the
    after_request hook in app.py) can call this unconditionally
    without any try/except of its own.
    """
    if not config.USAGE_METERING_ENABLED and not config.DEMO_MODE:
        return  # metering off outside demo: don't even build the event

    if identity is None:
        return  # anonymous request (e.g. /login, /auth/callback, health check): never billed

    if not _is_billable_status(status_code):
        return

    try:
        event = build_usage_event(
            identity=identity, method=method, path=path, status_code=status_code, usage_units=usage_units
        )
        started = time.monotonic()
        _publish(event)
        app_logger.info(
            "Usage event published",
            extra={
                "tenant": event["tenant_id"],
                "user_id": event["user_id"],
                "path": event["api_path"],
            },
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms > 500:
            app_logger.warning("Usage event publish took %.0fms (event_id=%s)", elapsed_ms, event["event_id"])
    except (BotoCoreError, ClientError) as exc:
        # Expected failure mode (throttling, network blip, bad IAM
        # perms, queue deleted, etc.) -- log and move on. The DLQ /
        # CloudWatch alarms (Phase 13) are the real safety net for
        # this, not blocking the user's request.
        app_logger.warning("Failed to publish usage event to SQS: %s", exc)
    except Exception:
        # Defense in depth: literally nothing in this module should
        # ever be allowed to propagate into the response path.
        app_logger.exception("Unexpected error recording API usage")
