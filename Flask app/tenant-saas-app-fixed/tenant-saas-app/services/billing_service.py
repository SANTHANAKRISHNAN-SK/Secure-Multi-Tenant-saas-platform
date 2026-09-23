"""
services/billing_service.py
----------------------------
Tenant-scoped billing calculation for the Billing Dashboard.

This module is read-only with respect to AWS: it never writes to
DynamoDB. All writes to the usage ledger / monthly aggregate happen
exclusively in metering_lambda/handler.py, which is the only thing
that ever increments usage. This module just reads the already-
computed monthly aggregate and applies plan pricing to it.

SECURITY: every function here takes `tenant` as an explicit,
caller-supplied parameter -- exactly like services/rds_service.py.
The only sanctioned caller is routes/billing.py, which resolves
`tenant` from `g.tenant` (itself resolved from the validated Cognito
JWT at login -- see auth.py / decorators.py). This module never reads
request.args/form/json, so there is no code path by which a client
can ask for another tenant's billing data.

DynamoDB access pattern: every read is a Query scoped to a single
tenant's partition key (`PK = TENANT#<tenant>`), matching the key
design documented in metering_lambda/handler.py. A tenant can
structurally never read another tenant's usage rows because the
partition key itself is derived from the authenticated tenant, never
from client input.

PLAN ASSIGNMENT (placeholder): there is no per-tenant subscription
table anywhere in the existing project (RDS only has the TenantA /
TenantB user tables). Until a real subscription store exists,
tenant -> plan is resolved from config.BILLING_PLAN_MAP, mirroring
how config.COGNITO_GROUP_MAP already maps tenant/role from Cognito
groups. This is intentionally isolated to one dict lookup
(_plan_for_tenant) so swapping it for a real RDS/DynamoDB-backed
subscription table later is a one-function change.
"""

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from datetime import datetime, timezone

from config import config
from logging_config import app_logger

_dynamodb_resource = None

# ---------------------------------------------------------------
# Billing plan catalog (Phase 8 pricing model). No Stripe / payment
# processing -- this only produces a calculated amount for display
# and reporting.
# ---------------------------------------------------------------
PLAN_CATALOG = {
    "Basic": {"display_name": "Basic", "base_amount": 10.00, "included_requests": 5000, "overage_rate": 0.0035},
    "Pro": {"display_name": "Pro", "base_amount": 30.00, "included_requests": 20000, "overage_rate": 0.0025},
    "Enterprise": {"display_name": "Enterprise", "base_amount": 100.00, "included_requests": 100000, "overage_rate": 0.0015},
}

_DEFAULT_PLAN = "Basic"

# Deterministic, in-memory mock usage used only when DEMO_MODE=true
# or DynamoDB is unreachable, so the dashboard is demoable without a
# live AWS account -- mirrors the _demo_db pattern in rds_service.py.
_demo_usage_by_tenant = {
    "TenantA": 24850,
    "TenantB": 3120,
}


def _plan_for_tenant(tenant: str) -> dict:
    """Resolves a tenant's billing plan. See module docstring for why
    this is presently a static config-driven mapping rather than a
    database lookup."""
    plan_name = config.BILLING_PLAN_MAP.get(tenant, _DEFAULT_PLAN)
    plan = PLAN_CATALOG.get(plan_name, PLAN_CATALOG[_DEFAULT_PLAN])
    return {"plan_name": plan_name, **plan}


def current_billing_period() -> str:
    """Returns the current UTC billing period as 'YYYY-MM', matching
    the month key format metering_lambda/handler.py already writes
    (`_billing_month`)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_dynamodb_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource(
            "dynamodb",
            region_name=config.AWS_REGION,
            config=BotoConfig(
                connect_timeout=config.USAGE_PUBLISH_TIMEOUT_SECONDS,
                read_timeout=config.USAGE_PUBLISH_TIMEOUT_SECONDS,
                retries={"max_attempts": 2},
            ),
        )
    return _dynamodb_resource


def _query_tenant_aggregates(tenant: str) -> list:
    """Queries every USAGE_AGGREGATE_TABLE item for one tenant's
    partition (PK = TENANT#<tenant> only -- never touches another
    tenant's partition). Returns a list of {billing_month,
    request_count, usage_units} dicts, most recent first."""
    if config.DEMO_MODE:
        month = current_billing_period()
        units = _demo_usage_by_tenant.get(tenant, 500)
        return [{"billing_month": month, "request_count": units, "usage_units": units}]

    if not config.USAGE_AGGREGATE_TABLE:
        app_logger.warning("BILLING: USAGE_AGGREGATE_TABLE not configured; returning zero usage for tenant=%s", tenant)
        return []

    try:
        table = _get_dynamodb_resource().Table(config.USAGE_AGGREGATE_TABLE)
        response = table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"TENANT#{tenant}"},
        )
        items = response.get("Items", [])
        results = [
            {
                "billing_month": item.get("billing_month", item.get("SK", "").replace("MONTH#", "")),
                "request_count": int(item.get("request_count", 0)),
                "usage_units": int(item.get("usage_units", 0)),
            }
            for item in items
        ]
        results.sort(key=lambda r: r["billing_month"], reverse=True)
        return results
    except (BotoCoreError, ClientError):
        app_logger.exception("BILLING: failed to query usage aggregate for tenant=%s", tenant)
        return []


def get_tenant_usage(tenant: str, period: str = None) -> dict:
    """Returns usage for one tenant/period. Falls back to zero usage
    (not an error) if no aggregate row exists yet for that period --
    that's the normal, expected state for a tenant with no billable
    activity yet this month."""
    period = period or current_billing_period()
    for row in _query_tenant_aggregates(tenant):
        if row["billing_month"] == period:
            return row
    return {"billing_month": period, "request_count": 0, "usage_units": 0}


def calculate_invoice(tenant: str, period: str = None) -> dict:
    """Applies plan pricing (Phase 8 model) to a tenant's usage for
    one billing period. Pure calculation -- no side effects, no
    persisted invoice record (none was requested for this pass; see
    conversation). Safe to call repeatedly / idempotently for display."""
    period = period or current_billing_period()
    plan = _plan_for_tenant(tenant)
    usage = get_tenant_usage(tenant, period)

    used_units = usage["usage_units"]
    included = plan["included_requests"]
    overage_units = max(0, used_units - included)
    usage_amount = round(overage_units * plan["overage_rate"], 2)
    base_amount = plan["base_amount"]
    total_amount = round(base_amount + usage_amount, 2)

    return {
        "tenant_id": tenant,
        "billing_period": period,
        "plan_name": plan["plan_name"],
        "plan_display_name": plan["display_name"],
        "included_requests": included,
        "usage_units": used_units,
        "overage_units": overage_units,
        "base_amount": base_amount,
        "usage_amount": usage_amount,
        "total_amount": total_amount,
        "overage_rate": plan["overage_rate"],
    }


def get_invoices(tenant: str, limit: int = 12) -> list:
    """Returns a calculated invoice for every billing period that has
    a usage aggregate row for this tenant, most recent first. There is
    deliberately no separate persisted 'Invoice' table yet -- each
    invoice is derived on demand from the (already durable) usage
    aggregate, which keeps this additive feature free of new
    write paths / new sources of truth to keep consistent."""
    periods = _query_tenant_aggregates(tenant)
    if not periods:
        # No usage recorded yet for this tenant at all -- still show
        # the current (zero-usage) period so the dashboard/invoice
        # list isn't empty for a brand-new tenant.
        return [calculate_invoice(tenant, current_billing_period())]
    return [calculate_invoice(tenant, row["billing_month"]) for row in periods[:limit]]
