# 🔧 Low-Level Design (LLD)

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Low-Level Design |
| Project Name | Secure Multi-Tenant SaaS Platform on AWS |
| Status | Final |
| Author | Santhanakrishnan S |
| Document Date | 23 August 2026 |
| Version | 1.0 |

## Version History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 23 August 2026 | Santhanakrishnan S | Initial published version, generated from AWS Configuration Document |

## Document Control

> ⚠️ All account IDs, endpoints, credentials, and identifiers in this document are replaced with placeholders (`<PLACEHOLDER>`). No real secrets are recorded here.

---

## Table of Contents

1. [Networking](#1-networking)
2. [Compute — EC2](#2-compute--ec2)
3. [Load Balancing](#3-load-balancing)
4. [Database — RDS](#4-database--rds)
5. [IAM Roles and Policies](#5-iam-roles-and-policies)
6. [KMS](#6-kms)
7. [Secrets Manager](#7-secrets-manager)
8. [SQS](#8-sqs)
9. [CloudFront](#9-cloudfront)
10. [API Gateway](#10-api-gateway)
11. [Lambda](#11-lambda)
12. [ECR](#12-ecr)
13. [ECS](#13-ecs)
14. [Cognito](#14-cognito)
15. [Conclusion](#15-conclusion)
16. [Appendix](#16-appendix)

---

## 1. Networking

| Attribute | Value |
|---|---|
| VPC Name | `saas-VPC-12` |
| VPC ID | `<VPC_ID>` |
| CIDR Block | `10.0.0.0/24` |
| Region | `<AWS_REGION>` |

### 1.1 Subnets

| Subnet | Type | CIDR | AZ | Purpose |
|---|---|---|---|---|
| `saas-public-sub1-ALB-aza` | Public | `10.0.0.0/26` | AZ-a | ALB |
| `saas-public-sub2-EC2-azb` | Public | `10.0.0.64/26` | AZ-b | EC2 |
| `saas-private-sub1-RDS-aza` | Private | `10.0.0.128/26` | AZ-a | RDS |
| `saas-private-sub2-ECS-aza` | Private | `10.0.0.192/26` | AZ-a | ECS / Lambda |

All subnet IDs are represented as `<SUBNET_ID>` outside internal cross-referencing.

### 1.2 Internet Gateway & NAT Gateway

| Resource | Name | ID |
|---|---|---|
| Internet Gateway | `saas-IGW-12` | `<IGW_ID>` |
| NAT Gateway | `saas-NAT-18` (Regional) | `<NAT_GATEWAY_ID>` |

### 1.3 Route Tables

| Route Table | Associated Subnets | Route |
|---|---|---|
| Public RT | 2 public subnets | `0.0.0.0/0 → IGW` |
| Private RT | 2 private subnets | `0.0.0.0/0 → NAT Gateway` |

### 1.4 Security Groups

| SG Name | ID | Inbound Rules | Purpose |
|---|---|---|---|
| `ALB-SG-12` | `<SG_ID>` | HTTPS 443 from `0.0.0.0/0`; HTTP 80 from `0.0.0.0/0` | Application Load Balancer |
| `ECS-SG-12` | `<SG_ID>` | TCP 8080 from ALB SG | ECS tasks |
| `RDS-SG-12` | `<SG_ID>` | MySQL 3306 from ECS SG, EC2 SG, Lambda SG | RDS database |
| `saas-LAMBDA-billing-SG` | `<SG_ID>` | none (outbound-only) | Lambda billing function |
| `EC2-SG-12` | `<SG_ID>` | SSH 22 from `0.0.0.0/0`; MySQL 3306 from `0.0.0.0/0` | EC2 DB-admin instance |

**Connectivity (by security group reference):** `ALB → ECS → RDS`, `EC2 → RDS`, `Lambda → RDS`.

> ⚠️ **Finding:** `EC2-SG-12` permits SSH (22) and MySQL (3306) from `0.0.0.0/0`. Recommend restricting to a specific administrator IP range.

---

## 2. Compute — EC2

| Attribute | Value |
|---|---|
| Instance Name | `ec2-rds-14` |
| Instance ID | `<EC2_INSTANCE_ID>` |
| AMI | Amazon Linux 2023 (`<AMI_ID>`) |
| Instance Type | `t3.micro` |
| Subnet | `saas-public-sub2-EC2-azb` (`<SUBNET_ID>`) |
| Private IP | `<EC2_PRIVATE_IP>` |
| Public IP | `<EC2_PUBLIC_IP>` |
| Security Group | `EC2-SG-12` |
| Key Pair | `<KEY_PAIR_NAME>` |
| Purpose | Bootstraps and administers the `saas_database` schema/tables inside RDS via MySQL client |

---

## 3. Load Balancing

| Attribute | Value |
|---|---|
| Name | `saas-ALB-12` |
| ARN | `arn:aws:elasticloadbalancing:<AWS_REGION>:<ACCOUNT_ID>:loadbalancer/app/saas-ALB-12/<HASH>` |
| Type / Scheme | Application / Internet-facing |
| Subnets | Both public subnets (AZ-a, AZ-b) |
| Security Group | `ALB-SG-12` |
| Listener | HTTP : 80 |
| Target Group | `saas-TG-12` (Target Type: IP, Protocol/Port: HTTP:8080) |
| Health Check | `/api/v1/health`, HTTP, traffic port, 30s interval |
| DNS Name | `<ALB_DNS_NAME>` |
| Status | Running, Healthy |

---

## 4. Database — RDS

| Attribute | Value |
|---|---|
| DB Identifier | `saas-database` |
| Engine | MySQL Community `8.4.9` |
| Instance Class | `db.t4g.micro` |
| Storage | 400 GiB, General Purpose SSD (gp2) |
| Multi-AZ | No (single-AZ) |
| VPC / Subnet Group | `saas-VPC-12` / default subnet group |
| Security Group | `RDS-SG-12` |
| Master Username | `<DB_USERNAME>` |
| Port | `3306` |
| Storage Encryption | Enabled — KMS key `saas-key-12` |
| Public Access | No |
| Endpoint | `<RDS_ENDPOINT>` |
| Application Database | `saas_database` (created manually via EC2 MySQL client) |
| Status | Available |

---

## 5. IAM Roles and Policies

### 5.1 `tenant-saas-task-role` (ECS Task Role)

| Attribute | Value |
|---|---|
| ARN | `arn:aws:iam::<ACCOUNT_ID>:role/tenant-saas-task-role` |
| Trusted Entity | `ecs-tasks.amazonaws.com` |
| AWS Managed Policies | `AmazonCognitoPowerUser`, `AmazonEC2ContainerServiceRole`, `AWSKeyManagementServicePowerUser`, `CloudWatchLogsFullAccess`, `SecretsManagerReadWrite` |
| Inline Policies | `KMS-tenant-12` (Encrypt/Decrypt/GenerateDataKey on `<KMS_KEY_ARN>`), `sqs-policy` (`sqs:SendMessage` on `<SQS_QUEUE_ARN>`) |
| Purpose | Allows the running Flask container to use KMS, Secrets Manager, Cognito, and SQS |

> ⚠️ **Finding:** `SecretsManagerReadWrite` and `AWSKeyManagementServicePowerUser` are broad AWS-managed policies that exceed the role's actual need (retrieve one secret, decrypt one key). Recommend scoping to a custom least-privilege policy restricted to the specific secret and key ARNs.

### 5.2 `tenant-saas-metering-role-<IAM_ROLE_SUFFIX>` (Lambda Execution Role)

| Attribute | Value |
|---|---|
| ARN | `arn:aws:iam::<ACCOUNT_ID>:role/service-role/tenant-saas-metering-role-<IAM_ROLE_SUFFIX>` |
| Trusted Entity | `lambda.amazonaws.com` |
| Policies | `AWSLambdaVPCAccessExecutionRole` (managed), `AWSLambdaBasicExecutionRole-<IAM_ROLE_SUFFIX>` (customer managed) |
| Inline Policies | `secrets-lambda-policy` (`secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:<AWS_REGION>:<ACCOUNT_ID>:secret:<RDS_SECRET_NAME>`; `kms:Decrypt` on `<KMS_KEY_ARN>`), `sqs-lambda-policy` (`DeleteMessage`, `ReceiveMessage`, `GetQueueAttributes` on `<SQS_QUEUE_ARN>`) |
| Purpose | Lets the metering Lambda consume from SQS and write billing records to RDS via Secrets Manager credentials |

### 5.3 `ecsTaskExecutionRole`

| Attribute | Value |
|---|---|
| ARN | `arn:aws:iam::<ACCOUNT_ID>:role/ecsTaskExecutionRole` |
| Trusted Entity | `ecs-tasks.amazonaws.com` |
| Policy | `AmazonECSTaskExecutionRolePolicy` (managed) |
| Purpose | Standard role allowing ECS to pull the container image and write task logs |

---

## 6. KMS

| Attribute | Value |
|---|---|
| Key Alias | `saas-key-12` |
| Key ID / ARN | `<KMS_KEY_ID>` / `<KMS_KEY_ARN>` |
| Type | Symmetric, Customer-managed |
| Rotation | Disabled |
| Used By | Secrets Manager, RDS (if configured with this key), ECS, Lambda |
| Key Policy | Grants full key access to account root; grants `kms:Decrypt` / `kms:DescribeKey` to `tenant-saas-task-role` |

> ⚠️ **Finding:** Automatic key rotation is disabled. Recommend enabling annual rotation for customer-managed KMS keys protecting credentials.

---

## 7. Secrets Manager

| Attribute | Value |
|---|---|
| Secret Name | `<RDS_SECRET_NAME>` |
| Secret ARN | `arn:aws:secretsmanager:<AWS_REGION>:<ACCOUNT_ID>:secret:<RDS_SECRET_NAME>` |
| Encryption Key | `saas-key-12` |
| Stored Fields | `db_username`, `db_password`, `engine`, `host`, `port`, `dbInstanceIdentifier`, `FLASK_SECRET_KEY` (all redacted here) |
| Rotation | Disabled |
| Consumers | `tenant-saas-task-role` (ECS), `tenant-saas-metering-role-*` (Lambda) |

> ⚠️ **Finding:** Rotation is disabled and the same secret bundles both DB credentials and the unrelated Flask application secret key. Recommend separating concerns into two secrets and enabling rotation for the database credential secret.

---

## 8. SQS

| Attribute | Value |
|---|---|
| Queue Name | `tenant-saas-usage` |
| Type | Standard |
| Encryption | SSE-SQS (Amazon SQS managed key) |
| Visibility Timeout | 1 minute |
| Message Retention | 4 days |
| Max Message Size | 1024 KiB |
| Dead Letter Queue | Disabled |
| Producer / Consumer | ECS (Flask app) / Lambda (`tenant-saas-metering`) |

> ⚠️ **Finding:** No Dead Letter Queue is configured. Failed usage events beyond Lambda retry limits will be dropped. Recommend adding a DLQ with a redrive policy.

---

## 9. CloudFront

| Attribute | Value |
|---|---|
| Distribution ID | `<CLOUDFRONT_DISTRIBUTION_ID>` |
| Domain | `<CLOUDFRONT_DOMAIN>` |
| Origin | API Gateway (`<API_GATEWAY_URL>`), origin path `/saas` |
| Origin Protocol | HTTPS only |
| Viewer Protocol Policy | Redirect HTTP → HTTPS |
| Allowed Methods | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| Cache Policy | CachingDisabled |
| Compression | Enabled |
| Price Class | All edge locations |
| WAF | Disabled |
| Logging | Disabled |

> ⚠️ **Finding:** WAF and access logging are both disabled on the distribution. See [07-Security-Architecture.md](07-Security-Architecture.md) for recommendations.

---

## 10. API Gateway

| Attribute | Value |
|---|---|
| API Name | `rest-api-new-17` |
| API ID | `<API_GATEWAY_ID>` |
| Type / Endpoint | REST API / Regional |
| Stage | `saas` |
| Invoke URL | `<API_GATEWAY_URL>` |
| Authorization | Amazon Cognito User Pool (JWT) |
| Integration | HTTP Proxy → Application Load Balancer |
| Throttling | Default stage throttling |
| Logging | Amazon CloudWatch Logs |

### 10.1 Resource Tree

```
/
├── login                         [GET]
├── login/cognito                 [GET]
├── auth/callback                 [GET]
├── logout                        [GET]
└── api/v1
    ├── health                    [GET]
    ├── users
    │   ├── dashboard              [GET]
    │   ├── userdetails            [GET, PUT]
    │   └── password/reset         [GET, POST]
    ├── admin
    │   ├── dashboard              [GET]
    │   └── users                  [POST]
    │       └── {user_id}          [DELETE]
    │           └── toggle         [PATCH]
    └── billing
        ├── dashboard              [GET]
        └── usage                  [GET, POST]
```

---

## 11. Lambda

| Attribute | Value |
|---|---|
| Function Name | `tenant-saas-metering` |
| Runtime | Python 3.14 |
| Handler | `lambda_function.lambda_handler` |
| Memory / Timeout | 128 MB / 15 sec |
| Ephemeral Storage | 512 MB |
| Architecture | x86_64 |
| Layer | `tenant-saas-pymysql` (v1) — provides `PyMySQL` |
| Execution Role | `tenant-saas-metering-role-<IAM_ROLE_SUFFIX>` |
| VPC Placement | Both private subnets (RDS + ECS) |
| Security Group | `saas-LAMBDA-billing-SG` |
| Trigger | SQS (`tenant-saas-usage`), enabled |

### 11.1 Function Logic Summary

1. Reads `DB_SECRET_NAME` from environment variables; retrieves and caches DB credentials from Secrets Manager (`get_db_credentials`).
2. Opens a `pymysql` connection to RDS using the retrieved credentials (`get_db_connection`).
3. For each SQS record, parses the JSON body and validates required fields (`event_id`, `tenant_id`, `user_id`, `action`, `api_path`, `http_method`, `status_code`, `usage_units`).
4. Inserts the record into the `tenant_usage` table with an idempotent `ON DUPLICATE KEY UPDATE` clause keyed on `event_id`.
5. Returns `batchItemFailures` for any message that failed processing, enabling SQS partial-batch retry.

---

## 12. ECR

| Attribute | Value |
|---|---|
| Repository Name | `saas` |
| Repository URI | `<ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/saas` |
| Type | Private |
| Image Tag Mutability | Mutable |
| Encryption | KMS |
| Scan on Push | Disabled |
| Current Tag | `latest` (~144 MB) |

> ⚠️ **Finding:** Scan-on-push is disabled and there is no lifecycle policy. Recommend enabling image scanning and a lifecycle policy to expire untagged/old images.

---

## 13. ECS

| Attribute | Value |
|---|---|
| Cluster Name | `saas-cluster-13` |
| Launch Type | AWS Fargate |
| Task Definition | `saas-task-family-13` (revision 17) |
| Task Role / Execution Role | `tenant-saas-task-role` / `ecsTaskExecutionRole` |
| Task Size | 1 vCPU / 3 GB memory |
| Service Name | `saas-task-family-20-service` |
| Desired / Running Tasks | 1 / 1 |
| Container Name | `saas-container-13` |
| Container Image | ECR `saas:latest` |
| Container Port | 8080 (TCP, HTTP) |
| Subnet | `saas-private-sub2-ECS-aza` |
| Security Group | `ECS-SG-12` |
| Logging | CloudWatch Logs, group `/ecs/saas-task-family-13` |
| Auto Scaling | Not configured |

### 13.1 Environment Variables (names only — values redacted)

`AWS_REGION`, `COGNITO_APP_CLIENT_ID`, `COGNITO_DOMAIN`, `COGNITO_LOGOUT_REDIRECT_URI`, `COGNITO_REDIRECT_URI`, `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `DB_PASSWORD`, `DB_USERNAME`, `DEMO_MODE`, `FLASK_DEBUG`, `FLASK_ENV`, `FLASK_SECRET_KEY`, `KMS_KEY_ID`, `LOG_GROUP_NAME`, `LOG_LEVEL`, `RDS_DB_NAME`, `RDS_HOST`, `RDS_PORT`, `SECRETS_MANAGER_SECRET_NAME`, `SESSION_COOKIE_SECURE`, `SESSION_TTL_MINUTES`, `USAGE_EVENTS_QUEUE_URL`, `USAGE_METERING_ENABLED`, `USAGE_PUBLISH_TIMEOUT_SECONDS`.

> ⚠️ **Finding:** `DB_PASSWORD` and `FLASK_SECRET_KEY` are injected as plain ECS task environment variables in addition to being stored in Secrets Manager. Recommend switching the task definition to native **ECS `secrets` injection** (referencing Secrets Manager ARNs directly) instead of plaintext environment variables, so the values never appear in the task definition JSON.

---

## 14. Cognito

| Attribute | Value |
|---|---|
| User Pool Name | `<COGNITO_USER_POOL_NAME>` |
| User Pool ID | `<COGNITO_USER_POOL_ID>` |
| App Client Name | `saas-SPA-cognito-12` |
| App Client ID | `<COGNITO_APP_CLIENT_ID>` |
| Cognito Domain | `<COGNITO_DOMAIN>` |
| Sign-in Options | Email, Username |
| MFA | Not enabled |
| Password Policy | Min 8 chars; requires number, special character, uppercase, lowercase; temp passwords expire in 7 days |
| Callback / Redirect / Sign-out URLs | `<CLOUDFRONT_DOMAIN>/auth/callback`, `<CLOUDFRONT_DOMAIN>/auth/callback`, `<CLOUDFRONT_DOMAIN>/` |
| OAuth Flow | Authorization Code Grant |
| OAuth Scopes | `aws.cognito.signin.user.admin`, `email`, `openid`, `profile` |
| User Groups | `TenantA_admin`, `TenantA_user`, `TenantB_admin`, `TenantB_user` |
| Token Signing | RS256, JWKS published at `<COGNITO_JWKS_URL>` |

> ⚠️ **Finding:** MFA is not enabled. Recommend requiring MFA at minimum for the `*_admin` groups.

---

## 15. Conclusion

This Low-Level Design captures every implemented AWS resource at configuration granularity, providing enough detail to reproduce, audit, or defend the deployment in a technical review, while keeping all credential and identifier values out of the document.

## 16. Appendix

### 16.1 Placeholder Reference

| Placeholder | Field(s) Represented |
|---|---|
| `<ACCOUNT_ID>` | AWS account number in all ARNs |
| `<AWS_REGION>` | Deployment region |
| `<VPC_ID>`, `<SUBNET_ID>`, `<SG_ID>`, `<IGW_ID>`, `<NAT_GATEWAY_ID>` | Network identifiers |
| `<RDS_ENDPOINT>`, `<DB_USERNAME>`, `<DB_PASSWORD>` | Database connection details |
| `<RDS_SECRET_NAME>`, `arn:aws:secretsmanager:<AWS_REGION>:<ACCOUNT_ID>:secret:<RDS_SECRET_NAME>` | Secrets Manager identifiers |
| `<KMS_KEY_ID>` / `<KMS_KEY_ARN>` | KMS key identifiers |
| `<IAM_ROLE_SUFFIX>` | AWS-generated random suffix on the Lambda execution role name |
| `<API_GATEWAY_URL>`, `<API_GATEWAY_ID>` | API Gateway identifiers |
| `<CLOUDFRONT_DOMAIN>`, `<CLOUDFRONT_DISTRIBUTION_ID>` | CloudFront identifiers |
| `<COGNITO_USER_POOL_ID>`, `<COGNITO_APP_CLIENT_ID>`, `<COGNITO_DOMAIN>` | Cognito identifiers |
