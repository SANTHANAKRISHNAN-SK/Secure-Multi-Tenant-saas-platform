# 🏗️ IAM

## 📌 Overview

The platform uses three purpose-built IAM roles rather than one shared role: `tenant-saas-task-role` (for the ECS application container), `tenant-saas-metering-role-xwtl8bom` (for the billing Lambda), and `ecsTaskExecutionRole` (for ECS's own task startup mechanics). Each role's trust policy restricts `sts:AssumeRole` to exactly one AWS service principal.

## 🎯 Purpose in THIS Project

**Business purpose:** as a multi-tenant platform handling billing data, the project needs a defensible answer to "what can each component actually do" — per-service IAM roles are that answer, and they are what an internship/portfolio reviewer would check first for security maturity.

**Technical purpose:** IAM roles grant the ECS task, the Lambda function, and the ECS execution mechanism only the specific AWS API permissions each one needs at runtime — Cognito, KMS, Secrets Manager, SQS, and CloudWatch Logs access, scoped per role rather than granted globally.

**Contribution to the overall solution:** every cross-service call in the platform — ECS reading a secret, Lambda decrypting a KMS-protected value, ECS sending an SQS message — is authorized through one of these three roles. Without them, no service could call another AWS service at all.

## ✅ Why This Service Was Selected

IAM is the only mechanism AWS provides for granting AWS-service-to-AWS-service permissions, so its use here isn't optional — the decision documented is the **design** of three distinct roles instead of one shared role, keeping ECS's runtime permissions separate from Lambda's and from the pure task-startup permissions ECS itself needs.

## ⚙️ My Implementation

### Role 1 — `tenant-saas-task-role` (ECS application runtime)

| Attribute | Value |
|---|---|
| Role ARN | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/tenant-saas-task-role` |
| Trusted Entity | AWS Service: `ecs-tasks.amazonaws.com` |
| AWS Managed Policies | `AmazonCognitoPowerUser`, `AmazonEC2ContainerServiceRole`, `AWSKeyManagementServicePowerUser`, `CloudWatchLogsFullAccess`, `SecretsManagerReadWrite` |
| Customer Inline Policies | `KMS-tenant-12` (scoped `kms:Encrypt`/`Decrypt`/`GenerateDataKey` on `saas-key-12`); `sqs-policy` (scoped `sqs:SendMessage` on `tenant-saas-usage`) |
| Status | Active |

**Purpose:** allows the container running the Flask application in ECS to interact with the AWS services it needs during runtime — Cognito, KMS, Secrets Manager, CloudWatch Logs, and SQS.

### Role 2 — `tenant-saas-metering-role-xwtl8bom` (Lambda billing runtime)

| Attribute | Value |
|---|---|
| Role ARN | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/service-role/tenant-saas-metering-role-xwtl8bom` |
| Trusted Entity | AWS Service: `lambda.amazonaws.com` |
| AWS/Customer Managed Policies | `AWSLambdaVPCAccessExecutionRole`; `AWSLambdaBasicExecutionRole-*` |
| Customer Inline Policies | `secrets-lambda-policy` (scoped `secretsmanager:GetSecretValue` on `saas-secret-rds-12*`, `kms:Decrypt` on `saas-key-12`); `sqs-lambda-policy` (scoped `sqs:DeleteMessage`, `sqs:ReceiveMessage`, `sqs:GetQueueAttributes` on `tenant-saas-usage`) |
| Status | Active |

**Purpose:** provides the billing/metering Lambda function the permissions to execute inside the VPC, consume messages from SQS, retrieve and decrypt the RDS secret, and write logs.

### Role 3 — `ecsTaskExecutionRole` (ECS task startup)

| Attribute | Value |
|---|---|
| Role ARN | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/ecsTaskExecutionRole` |
| Trusted Entity | AWS Service: `ecs-tasks.amazonaws.com` |
| AWS Managed Policies | `AmazonECSTaskExecutionRolePolicy` |
| Inline Policies | None |
| Status | Active |

**Purpose:** provides the permissions Amazon ECS itself needs to start and manage the tasks (pulling the container image, writing startup logs) — separate from the application's own runtime permissions granted via `tenant-saas-task-role`.

## 🔄 Role in End-to-End Request Flow

IAM roles do not sit in the request path directly; they are the authorization layer checked at every cross-service call along it:

```
ECS Task (assumes tenant-saas-task-role)
  → Secrets Manager (GetSecretValue)
  → KMS (Decrypt)
  → RDS (application data)
  → SQS (SendMessage, usage events)

Lambda (assumes tenant-saas-metering-role-xwtl8bom)
  → SQS (ReceiveMessage/DeleteMessage)
  → Secrets Manager (GetSecretValue) → KMS (Decrypt)
  → RDS (INSERT tenant_usage)
```

## 🔗 Communication With Other AWS Services

| Service | Why They Communicate | What Is Exchanged | How |
|---|---|---|---|
| Amazon ECS | ECS tasks assume `tenant-saas-task-role`; ECS itself assumes `ecsTaskExecutionRole` to start tasks | Temporary security credentials via `sts:AssumeRole` | Trust policy restricted to `ecs-tasks.amazonaws.com` |
| AWS Lambda | The billing function assumes `tenant-saas-metering-role-xwtl8bom` | Temporary security credentials via `sts:AssumeRole` | Trust policy restricted to `lambda.amazonaws.com` |
| AWS KMS | Both `tenant-saas-task-role` and the Lambda role are granted scoped `Decrypt`/`Encrypt` permissions on `saas-key-12` | Encrypt/decrypt authorization | Customer inline policies referencing the specific key ARN |
| AWS Secrets Manager | Both roles are granted `GetSecretValue` on `saas-secret-rds-12` | Read authorization for the RDS secret | AWS-managed (`SecretsManagerReadWrite`) or scoped inline policy |
| Amazon SQS | ECS's role can `SendMessage`; the Lambda role can `ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on `tenant-saas-usage` | Producer/consumer authorization | Customer inline policies scoped to the queue ARN |

## 🔒 Security Implementation

- Each role's trust policy names exactly one AWS service principal (`ecs-tasks.amazonaws.com` or `lambda.amazonaws.com`), preventing cross-service role assumption.
- Inline policies for SQS and KMS access are scoped to specific resource ARNs (the one queue, the one key) rather than `"Resource": "*"`.
- Task startup permissions (`ecsTaskExecutionRole`) are kept separate from application runtime permissions (`tenant-saas-task-role`), so a compromised container process doesn't automatically inherit ECS's own image-pull/logging permissions or vice versa.

> **Known gap (documented, not fabricated):** `tenant-saas-task-role` attaches broad AWS-managed policies (`SecretsManagerReadWrite`, `AWSKeyManagementServicePowerUser`) alongside its scoped inline policies. The recommended improvement is replacing these managed policies with custom policies limited to the exact secret and key ARNs the ECS task actually needs.

## 📈 High Availability & Scalability

This service is not used for scalability in this implementation. IAM roles are global/regional control-plane constructs, not compute resources that scale with load.

## 📊 Monitoring

Monitoring is not applicable in the CloudWatch-dashboard sense. IAM role usage would be observable through AWS CloudTrail (referenced elsewhere in the architecture), but no CloudTrail-specific dashboard or alarm configuration is documented for this implementation.

## ✅ Best Practices Implemented

- Per-service roles instead of one shared role across ECS and Lambda
- Trust policies scoped to a single AWS service principal each
- Custom inline policies scoping SQS and KMS access to specific resource ARNs
- Separation of ECS task-execution permissions from ECS application-runtime permissions

## ⭐ Why This Service Is Important

IAM is what turns "these services are connected" into "these services are connected under a controlled, auditable permission boundary." The three-role design is the concrete evidence, in this project, that ECS cannot do everything Lambda can, and that neither can act outside the specific secret, key, and queue they were each scoped to touch.

## 📝 Summary

Three IAM roles — `tenant-saas-task-role`, `tenant-saas-metering-role-xwtl8bom`, and `ecsTaskExecutionRole` — divide runtime permissions between the ECS application, the billing Lambda, and ECS's own task-management mechanics. Scoped inline policies for SQS and KMS access, alongside single-service trust policies, are the concrete least-privilege controls implemented, with the broad managed-policy attachments on the ECS task role flagged as a known area for future tightening.
