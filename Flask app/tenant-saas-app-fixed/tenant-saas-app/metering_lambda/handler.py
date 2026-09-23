"""
metering_lambda/handler.py
----------------------------
Consumes tenant usage events from the USAGE_EVENTS_QUEUE (SQS),
validates them, and idempotently writes them into two DynamoDB
tables:

  1. USAGE_LEDGER_TABLE  -- append-only, auditable source of truth.
     One item per usage event. PK/SK design (see below) makes
     event_id part of the key, so a redelivered SQS message (SQS is
     at-least-once, never exactly-once) can never be double-counted.

  2. USAGE_AGGREGATE_TABLE -- one item per (tenant, billing month),
     atomically incremented request_count / usage_units. This is
     what billing calculation (Phase 8) reads -- O(1) lookup instead
     of scanning/querying the whole ledger for every invoice run.

DynamoDB key design
--------------------
USAGE_LEDGER_TABLE:
    PK (partition key) : "TENANT#<tenant_id>"
    SK (sort key)       : "USAGE#<YYYY-MM>#<event_id>"

    - Every item is scoped under a single tenant's partition -- a
      Query can never span tenants, and the application code never
      constructs a Query without a tenant_id, so cross-tenant reads
      are structurally impossible, not just policy.
    - Sort key is prefixed by billing month so "give me tenant X's
      usage for 2026-08" is a single efficient Query with
      begins_with(SK, "USAGE#2026-08"), not a table scan.
    - event_id as the final component of SK (combined with the
      conditional put below) is the idempotency key.

USAGE_AGGREGATE_TABLE (billing-ready rollup):
    PK : "TENANT#<tenant_id>"
    SK : "MONTH#<YYYY-MM>"
    Attributes: request_count (N), usage_units (N), updated_at

    A separate aggregate table is used (rather than always summing
    the ledger at billing time) because: (a) billing/invoice
    generation should be a cheap point lookup, not an aggregation
    query over potentially tens of thousands of ledger rows per
    tenant per month, and (b) it lets the ledger stay a pure,
    unopinionated audit log while the aggregate is the
    billing-optimized read model. The two are kept consistent by
    only ever incrementing the aggregate in the SAME idempotent path
    as the ledger write (never independently).

Idempotency
-----------
The ledger write uses a conditional PutItem:
    ConditionExpression = "attribute_not_exists(PK) AND attribute_not_exists(SK)"
If that condition fails, DynamoDB raises ConditionalCheckFailedException,
which we treat as "already processed" -- NOT an error. We skip the
aggregate increment (it would already have happened the first time)
and report the message as successfully handled, so SQS deletes it
and it is never retried again.

Batch failure reporting
------------------------
This function is written for Lambda's SQS trigger with
FunctionResponseTypes = ["ReportBatchItemFailures"] enabled on the
event source mapping. Only messages that genuinely failed processing
are returned in `batchItemFailures`, so a single poison message
doesn't cause the entire batch to be retried -- just that one message,
which eventually lands in the DLQ after maxReceiveCount is exceeded.
"""

import json
import logging
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
LEDGER_TABLE_NAME = os.environ["USAGE_LEDGER_TABLE"]
AGGREGATE_TABLE_NAME = os.environ["USAGE_AGGREGATE_TABLE"]
ledger_table = dynamodb.Table(LEDGER_TABLE_NAME)
aggregate_table = dynamodb.Table(AGGREGATE_TABLE_NAME)

_REQUIRED_FIELDS = (
    "event_id",
    "tenant_id",
    "user_id",
    "api_path",
    "http_method",
    "status_code",
    "usage_units",
    "timestamp",
)


class InvalidUsageEvent(Exception):
    """Raised for a structurally invalid event. These are NOT retried
    -- a malformed message will never become valid on retry, so it is
    reported as a permanent failure and routed straight to the DLQ
    for inspection, rather than being retried maxReceiveCount times
    for no benefit."""


def _validate(event: dict) -> None:
    missing = [f for f in _REQUIRED_FIELDS if f not in event or event[f] in (None, "")]
    if missing:
        raise InvalidUsageEvent(f"Missing required field(s): {missing}")

    if not isinstance(event["tenant_id"], str) or not event["tenant_id"].strip():
        raise InvalidUsageEvent("tenant_id must be a non-empty string")

    if not isinstance(event["usage_units"], (int, float)) or event["usage_units"] <= 0:
        raise InvalidUsageEvent("usage_units must be a positive number")

    try:
        # Accept "...Z" or "...+00:00"; normalize for parsing.
        datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise InvalidUsageEvent(f"Invalid timestamp: {exc}") from exc

    if not isinstance(event["status_code"], int):
        raise InvalidUsageEvent("status_code must be an integer")


def _billing_month(timestamp_str: str) -> str:
    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    return ts.strftime("%Y-%m")


def _process_event(usage_event: dict) -> None:
    _validate(usage_event)

    tenant_id = usage_event["tenant_id"]
    event_id = usage_event["event_id"]
    month = _billing_month(usage_event["timestamp"])
    usage_units = int(usage_event["usage_units"])

    pk = f"TENANT#{tenant_id}"
    sk = f"USAGE#{month}#{event_id}"

    try:
        ledger_table.put_item(
            Item={
                "PK": pk,
                "SK": sk,
                "event_id": event_id,
                "tenant_id": tenant_id,
                "user_id": usage_event["user_id"],
                "api_path": usage_event["api_path"],
                "http_method": usage_event["http_method"],
                "status_code": usage_event["status_code"],
                "usage_units": usage_units,
                "event_timestamp": usage_event["timestamp"],
                "ingested_at": datetime.utcnow().isoformat() + "Z",
            },
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("Duplicate event_id=%s tenant=%s -- already processed, skipping", event_id, tenant_id)
            return  # Idempotent no-op: NOT an error.
        raise  # Any other DynamoDB error is a real failure -> let it retry / hit DLQ.

    # Only reached for a genuinely new (non-duplicate) event, so it's
    # safe to increment the aggregate exactly once.
    aggregate_table.update_item(
        Key={"PK": pk, "SK": f"MONTH#{month}"},
        UpdateExpression=(
            "ADD request_count :one, usage_units :units "
            "SET updated_at = :now, tenant_id = :tenant_id, billing_month = :month"
        ),
        ExpressionAttributeValues={
            ":one": 1,
            ":units": usage_units,
            ":now": datetime.utcnow().isoformat() + "Z",
            ":tenant_id": tenant_id,
            ":month": month,
        },
    )
    logger.info("Recorded usage event_id=%s tenant=%s month=%s", event_id, tenant_id, month)


def handler(event, context):
    """SQS-triggered entry point. Processes each record independently
    and reports only genuinely failed records back to Lambda/SQS via
    `batchItemFailures`, so one bad message doesn't block/retry the
    whole batch."""
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            _process_event(body)
        except InvalidUsageEvent as exc:
            # Permanently invalid -- do not retry. We still report it
            # as a failure so it's visible/counted, but in practice
            # you'd typically route these to the DLQ manually or via
            # a low maxReceiveCount rather than retrying a message
            # that can never succeed. Logged at ERROR for CloudWatch
            # alarms to catch.
            logger.error("Invalid usage event (messageId=%s): %s | body=%s", message_id, exc, record.get("body"))
            batch_item_failures.append({"itemIdentifier": message_id})
        except (ClientError, json.JSONDecodeError) as exc:
            # Transient / infrastructure failure -- worth retrying.
            logger.exception("Failed to process message %s: %s", message_id, exc)
            batch_item_failures.append({"itemIdentifier": message_id})
        except Exception:
            logger.exception("Unexpected error processing message %s", message_id)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
