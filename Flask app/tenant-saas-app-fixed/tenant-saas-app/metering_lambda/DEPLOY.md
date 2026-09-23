# Tenant Usage Metering — Deployment Reference (Phases 5–7)

This covers only the NEW infrastructure for usage metering. Nothing
here changes the existing Cognito/ALB/ECS/RDS setup.

```
ECS Flask (services/usage_service.py)
   -> SQS: usage-events-queue
        -> Lambda: metering_lambda/handler.py
             -> DynamoDB: UsageLedger (source of truth)
             -> DynamoDB: UsageMonthlyAggregate (billing rollup)
   -> SQS: usage-events-dlq (after 5 failed receives)
```

## 1. SQS queues

**Main queue: `usage-events-queue`**
| Setting | Value | Why |
|---|---|---|
| VisibilityTimeout | 60s | ≥ Lambda timeout (recommend Lambda timeout 15–30s); prevents a second concurrent delivery of the same message while it's still being processed. |
| MessageRetentionPeriod | 4 days (345600s) | Usage events are transient telemetry, not long-term storage (the ledger is); a few days is enough buffer for a Lambda outage to be fixed. |
| RedrivePolicy | maxReceiveCount = 5, target = `usage-events-dlq` | Poison/invalid messages get 5 attempts, then move to DLQ instead of retrying forever. |
| SSE (encryption) | Enabled, `alias/aws/sqs` (or a customer-managed KMS key if you need audit-level key control) | Usage events include tenant_id/user_id/paths — treat as sensitive-ish; encrypt at rest by default. |

**Dead-letter queue: `usage-events-dlq`**
| Setting | Value |
|---|---|
| MessageRetentionPeriod | 14 days (max) — gives time to investigate before messages expire |
| SSE | Same as above |
| CloudWatch alarm | `ApproximateNumberOfMessagesVisible > 0` (see Phase 13 monitoring, next step) |

## 2. Lambda event source mapping

- Trigger: `usage-events-queue`
- Batch size: 10 (tune up for throughput once volume is known)
- `FunctionResponseTypes: ["ReportBatchItemFailures"]` — **required**, the handler returns `batchItemFailures` and relies on this to avoid retrying a whole batch for one bad message.
- Function timeout: 15–30s (must be ≤ queue VisibilityTimeout)
- Environment variables:
  - `USAGE_LEDGER_TABLE`
  - `USAGE_AGGREGATE_TABLE`
  - `LOG_LEVEL=INFO`

## 3. DynamoDB tables

**`UsageLedger`**
- PK: `PK` (String) — `TENANT#<tenant_id>`
- SK: `SK` (String) — `USAGE#<YYYY-MM>#<event_id>`
- Billing mode: On-Demand (usage is bursty/unpredictable; avoids capacity planning)
- SSE: Enabled (AWS owned or KMS)
- Point-in-time recovery: Enabled (this is your audit trail)

**`UsageMonthlyAggregate`**
- PK: `PK` (String) — `TENANT#<tenant_id>`
- SK: `SK` (String) — `MONTH#<YYYY-MM>`
- Billing mode: On-Demand
- SSE: Enabled

Neither table needs a GSI for the queries described here: both are
always looked up by an exact or prefixed key within a single tenant's
partition, which is also what structurally prevents one tenant's
query from ever touching another tenant's items.

## 4. IAM — least privilege

**ECS task role — add this statement only (do not attach broader SQS/DynamoDB access):**
```json
{
  "Sid": "PublishUsageEvents",
  "Effect": "Allow",
  "Action": "sqs:SendMessage",
  "Resource": "arn:aws:sqs:<region>:<account_id>:usage-events-queue"
}
```

**Lambda execution role:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConsumeUsageQueue",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:<region>:<account_id>:usage-events-queue"
    },
    {
      "Sid": "WriteUsageTables",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:<region>:<account_id>:table/UsageLedger",
        "arn:aws:dynamodb:<region>:<account_id>:table/UsageMonthlyAggregate"
      ]
    },
    {
      "Sid": "BasicLambdaLogging",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:<region>:<account_id>:log-group:/aws/lambda/metering-lambda:*"
    }
  ]
}
```
No `AdministratorAccess`, no wildcard resources, no `dynamodb:Scan`/`Query` granted to the Lambda (it never needs to read — only write) or to the ECS task (it never reads DynamoDB at all in this phase).

## 5. New environment variables — ECS task definition

| Variable | Example | Notes |
|---|---|---|
| `USAGE_METERING_ENABLED` | `true` | Defaults to `false` — metering is off until explicitly enabled. |
| `USAGE_EVENTS_QUEUE_URL` | `https://sqs.us-east-1.amazonaws.com/123456789012/usage-events-queue` | |
| `USAGE_PUBLISH_TIMEOUT_SECONDS` | `1.5` | Optional; caps worst-case latency added to a response. |

No AWS credentials are set anywhere — `services/usage_service.py` uses `boto3.client("sqs", region_name=config.AWS_REGION)`, which resolves credentials from the ECS task's IAM role via the standard SDK credential chain, exactly like `services/rds_service.py` / `services/cognito_service.py` already do.

## 6. Rollout / rollback

1. Deploy DynamoDB tables + SQS queues first (no app behavior change).
2. Deploy Lambda + event source mapping (idle — no messages yet).
3. Deploy the updated Flask image with `USAGE_METERING_ENABLED=false` (this PR's code, inert).
4. Flip `USAGE_METERING_ENABLED=true` via an ECS task definition env var update (no image rebuild needed).
5. **Rollback**: flip `USAGE_METERING_ENABLED=false` back — zero code deploy required, and no existing functionality was ever touched, so there's nothing else to roll back.
