# 📐 High-Level Design (HLD)

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | High-Level Design |
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

| Control Item | Detail |
|---|---|
| Related Documents | 02-Solution-Architecture.md, 04-Low-Level-Design.md |

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Component Breakdown](#2-component-breakdown)
3. [Request Flow](#3-request-flow)
4. [Authentication Flow](#4-authentication-flow)
5. [Billing / Usage-Metering Flow](#5-billing--usage-metering-flow)
6. [Component Interaction Table](#6-component-interaction-table)
7. [Notes and Best Practices](#7-notes-and-best-practices)
8. [Conclusion](#8-conclusion)
9. [Appendix](#9-appendix)

---

## 1. Purpose

This document decomposes the platform into its major functional components and describes how they interact, without going into resource-level configuration (covered in the Low-Level Design).

## 2. Component Breakdown

| Component | Responsibility |
|---|---|
| **Network Layer** | VPC, public/private subnets, IGW, NAT Gateway, route tables, security groups |
| **Edge Layer** | CloudFront (CDN/HTTPS), API Gateway (REST API + JWT authorization) |
| **Compute Layer** | ECS Fargate (application), EC2 (DB bootstrap), Lambda (billing) |
| **Data Layer** | RDS MySQL |
| **Identity Layer** | Amazon Cognito (User Pool, Hosted UI, User Groups) |
| **Messaging Layer** | Amazon SQS |
| **Security Layer** | IAM, KMS, Secrets Manager |
| **Delivery Layer** | Amazon ECR, AWS CloudShell |
| **Observability Layer** | Amazon CloudWatch |
| **Cost Layer** | AWS Budgets |

## 3. Request Flow

```mermaid
sequenceDiagram
    participant U as Tenant User
    participant CF as CloudFront
    participant AG as API Gateway
    participant ALB as ALB
    participant ECS as ECS (Flask App)
    participant RDS as RDS MySQL

    U->>CF: HTTPS request
    CF->>AG: Forward to origin (API Gateway)
    AG->>AG: Validate Cognito JWT
    AG->>ALB: HTTP Proxy integration
    ALB->>ECS: Route to healthy task (port 8080)
    ECS->>RDS: Query / update tenant data
    RDS-->>ECS: Result set
    ECS-->>ALB: Response
    ALB-->>AG: Response
    AG-->>CF: Response
    CF-->>U: HTTPS response
```

## 4. Authentication Flow

```mermaid
sequenceDiagram
    participant U as Tenant User
    participant COG as Cognito Hosted UI
    participant APP as Flask App (ECS)
    participant AG as API Gateway

    U->>COG: Navigate to /login/cognito
    COG->>U: Present Hosted UI login form
    U->>COG: Submit credentials
    COG-->>U: Redirect with authorization code
    U->>APP: /auth/callback?code=...
    APP->>COG: Exchange code for tokens (Authorization Code Grant)
    COG-->>APP: ID Token + Access Token (JWT, RS256)
    APP-->>U: Authenticated session established
    U->>AG: Subsequent API calls with Access Token
    AG->>AG: Validate signature, issuer, expiry against JWKS
```

## 5. Billing / Usage-Metering Flow

```mermaid
sequenceDiagram
    participant ECS as ECS (Flask App)
    participant SQS as SQS Queue (tenant-saas-usage)
    participant LAM as Lambda (tenant-saas-metering)
    participant SM as Secrets Manager
    participant RDS as RDS (tenant_usage table)

    ECS->>SQS: Publish usage event (tenant_id, action, api_path, status_code...)
    SQS->>LAM: Trigger with message batch
    LAM->>SM: Retrieve DB credentials
    SM-->>LAM: Encrypted credentials (via KMS)
    LAM->>RDS: INSERT usage record
    RDS-->>LAM: Acknowledge write
    LAM-->>SQS: Delete processed message / report batch failures
```

## 6. Component Interaction Table

| From | To | Protocol / Mechanism | Purpose |
|---|---|---|---|
| CloudFront | API Gateway | HTTPS (origin) | Deliver app to end users |
| API Gateway | Cognito | JWT / JWKS validation | Authorize API requests |
| API Gateway | ALB | HTTP Proxy Integration | Forward to application |
| ALB | ECS | HTTP (port 8080) | Route to container task |
| ECS | RDS | MySQL (port 3306) | Application data access |
| ECS | Secrets Manager | AWS SDK (`GetSecretValue`) | Retrieve DB credentials |
| ECS | SQS | AWS SDK (`SendMessage`) | Publish usage events |
| SQS | Lambda | Event source mapping | Trigger billing processing |
| Lambda | RDS | MySQL (`pymysql`) | Persist usage records |
| Lambda | Secrets Manager | AWS SDK | Retrieve DB credentials |
| EC2 | RDS | MySQL (port 3306) | Schema bootstrap / admin queries |
| ECS / Lambda / ALB / RDS | CloudWatch | Logs & Metrics API | Observability |

## 7. Notes and Best Practices

> **Best Practice:** Keeping JWT validation at the API Gateway layer (rather than inside the Flask app) centralizes authorization and reduces the attack surface reaching the application tier.

- The billing pipeline is intentionally **asynchronous** (SQS + Lambda) so that usage-tracking never blocks or slows the user-facing request path.
- The EC2 instance is used purely as an administrative bootstrap host for the database and is not part of the live request path.

## 8. Conclusion

The high-level design confirms a clean separation between the synchronous user-facing request path and the asynchronous billing path, with identity validation enforced at the edge before traffic reaches internal compute.

## 9. Appendix

See [04-Low-Level-Design.md](04-Low-Level-Design.md) for exact resource configuration values referenced by each component above.
