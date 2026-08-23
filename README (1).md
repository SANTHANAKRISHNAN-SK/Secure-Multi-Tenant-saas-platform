# 🔐 Secure Multi-Tenant SaaS Platform on AWS

> A production-style, multi-tenant SaaS platform built entirely on managed AWS services — containerized application tier, centralized identity, asynchronous usage metering, and full supporting documentation.

---

## 📖 Project Overview

This project is an AWS Cloud Computing internship build demonstrating a realistic, security-conscious **multi-tenant SaaS architecture**. Multiple tenant organizations (e.g. Tenant A, Tenant B) share a single containerized Flask application while remaining logically isolated at the identity layer through Amazon Cognito user groups.

The platform is fronted by Amazon CloudFront and Amazon API Gateway, runs on Amazon ECS Fargate, persists data in Amazon RDS, and tracks per-tenant billing usage through a decoupled Amazon SQS → AWS Lambda pipeline. Secrets and encryption are centralized through AWS Secrets Manager and AWS KMS, and the entire environment is observed through Amazon CloudWatch and governed by an AWS Budget.

This repository contains the complete technical documentation set for the project — from business requirements through cost estimation — written to be defensible in a technical review and ready for a public portfolio.

---

## ✨ Features

- 🏢 Multi-Tenant SaaS Architecture
- 🔑 Amazon Cognito Authentication (Hosted UI, OAuth 2.0)
- 🪪 JWT-Based Authorization (API Gateway)
- 📦 Amazon ECS Fargate Deployment (Containerized Flask App)
- 🗄️ Amazon RDS Database (MySQL)
- 📊 Asynchronous Usage Metering (SQS + Lambda)
- 🔒 Centralized Secrets Management (Secrets Manager + KMS)
- 📈 Centralized Monitoring (CloudWatch Dashboards & Logs)
- 🛡️ Security Best Practices (Least-Privilege IAM, Private Subnets)
- 💰 Cost Governance (AWS Budgets)

---

## ☁️ AWS Services Used

| AWS Service | Purpose |
|---|---|
| Amazon VPC | Isolated network with public/private subnets, IGW, NAT Gateway |
| Amazon CloudFront | Global CDN / HTTPS public entry point |
| Amazon Cognito | Centralized authentication, Hosted UI, JWT issuance, tenant user groups |
| Amazon API Gateway | Versioned REST API with Cognito JWT authorization |
| Application Load Balancer | Routes HTTP traffic to ECS tasks |
| Amazon ECS (Fargate) | Runs the containerized Flask application |
| Amazon EC2 | Administrative host for RDS schema bootstrap |
| Amazon RDS (MySQL) | Primary relational data store (application data + usage metering) |
| Amazon SQS | Decouples usage-event publishing from billing processing |
| AWS Lambda | Processes usage events and writes billing records to RDS |
| AWS Secrets Manager | Secure storage of database credentials and app secret key |
| AWS KMS | Encryption key management for Secrets Manager |
| AWS IAM | Least-privilege, per-service execution roles |
| Amazon ECR | Stores the application's Docker container image |
| AWS CloudShell | Browser-based build and image-push environment |
| Amazon CloudWatch | Dashboards, logs, and Container Insights |
| AWS Budgets | Monthly cost tracking and alert thresholds |

---

## 🏗️ Architecture Diagram

```
                                   Users
                                     │
                       Amazon CloudFront (HTTPS / CDN)
                                     │
                    Amazon Cognito Hosted UI (SPA Client)
                                     │
                    OAuth 2.0 Authorization Code Flow
                                     │
                          JWT Access / ID / Refresh Tokens
                                     │
                            Amazon API Gateway
                                     │
                          Application Load Balancer
                                     │
                     Amazon ECS Fargate (Flask Application)
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                    │
                 ▼                   ▼                    ▼
          Amazon RDS            Amazon SQS         AWS Secrets Manager
        (Application DB)             │                    │
                 ▲                   ▼                    ▼
                 │              AWS Lambda            AWS KMS
                 │           (Usage Metering)             │
                 │                   │                    │
                 │                   ▼                    │
                 └──────────  Amazon RDS  ◄────────────────┘
                            (Usage Metering Table)
                          Secure Credential Access
```

> **Note:** Amazon RDS above represents a **single** deployed MySQL instance that serves both the application's own tables (read/written directly by ECS) and the usage-metering table (written by Lambda) — not two separate database instances. AWS KMS is reached only through Secrets Manager, not directly from ECS. See [`02-Solution-Architecture.md`](02-Solution-Architecture.md) for the full explanation.

---

## 📁 Repository Structure

```
├── 01-Business-Requirement-Document.md
├── 02-Solution-Architecture.md
├── 03-High-Level-Design.md
├── 04-Low-Level-Design.md
├── 05-Infrastructure-Diagram.md
├── 06-Deployment-Guide-SOP.md
├── 07-Security-Architecture.md
├── 08-Monitoring-and-Logging.md
├── 09-Backup-and-Disaster-Recovery.md
├── 10-Cost-Estimation.md
├── 11-Final-Quality-Review.md
└── README.md
```

---

## 🔄 Project Workflow

**User-facing request path:**

```
Users → CloudFront → Cognito → API Gateway → ALB → ECS → RDS
```

**Asynchronous billing / usage-metering path:**

```
ECS → SQS → Lambda → Usage Metering Table (RDS)
```

**Credential retrieval path:**

```
ECS / Lambda → Secrets Manager → AWS KMS
```

---

## 📚 Documentation

| Document | Description |
|---|---|
| [01-Business-Requirement-Document.md](01-Business-Requirement-Document.md) | Business objectives, scope, stakeholders, functional & non-functional requirements |
| [02-Solution-Architecture.md](02-Solution-Architecture.md) | AWS services used, architecture diagram, multi-tenancy strategy, technology stack |
| [03-High-Level-Design.md](03-High-Level-Design.md) | Component breakdown and request/auth/billing flow diagrams |
| [04-Low-Level-Design.md](04-Low-Level-Design.md) | Exact resource-level configuration for every deployed AWS service |
| [05-Infrastructure-Diagram.md](05-Infrastructure-Diagram.md) | Network topology, security-group map, CI/CD pipeline, and data-flow diagrams |
| [06-Deployment-Guide-SOP.md](06-Deployment-Guide-SOP.md) | Step-by-step (Step 1–17) AWS Console deployment manual |
| [07-Security-Architecture.md](07-Security-Architecture.md) | IAM, network, data-protection, and edge security review with findings |
| [08-Monitoring-and-Logging.md](08-Monitoring-and-Logging.md) | CloudWatch dashboards, metrics, log groups, and observability gaps |
| [09-Backup-and-Disaster-Recovery.md](09-Backup-and-Disaster-Recovery.md) | Current resilience posture and recommended backup/DR strategy |
| [10-Cost-Estimation.md](10-Cost-Estimation.md) | Estimated monthly cost by service, compared against the configured AWS Budget |
| [11-Final-Quality-Review.md](11-Final-Quality-Review.md) | Documentation review, corrections applied, and per-document quality scores |

---

## 🛡️ Security Features

- Private-subnet isolation for RDS, ECS, and Lambda — no direct internet exposure
- Least-privilege, per-service IAM roles (ECS task role, Lambda execution role, ECS execution role)
- Centralized secrets in AWS Secrets Manager, encrypted with a customer-managed KMS key
- JWT validation enforced at API Gateway before traffic reaches the application tier
- Security-group-to-security-group referencing instead of broad CIDR rules for internal traffic
- HTTPS enforced end-to-end via CloudFront (Redirect HTTP → HTTPS)

---

## 📈 Monitoring

- Centralized CloudWatch dashboard covering ALB, RDS, API Gateway, ECS, Lambda, and CloudFront
- Container Insights enabled on the ECS Fargate cluster
- Dedicated log groups for the application (`/ecs/saas-task-family-13`) and the billing Lambda (`/aws/lambda/tenant-saas-metering`)
- AWS Budget with alert thresholds at 50%, 80%, and 100% of the monthly spend cap

---

## 🧰 Technologies Used

| Layer | Technology |
|---|---|
| Application Framework | Python / Flask |
| Container Runtime | Docker |
| Database | MySQL 8.4 (Amazon RDS) |
| Async Processing | Python, `boto3`, `pymysql` (AWS Lambda) |
| Authentication | OAuth 2.0 / OpenID Connect (Amazon Cognito) |
| Infrastructure | AWS Console-driven provisioning |
| Documentation | Markdown + Mermaid diagrams |

---

## 🎓 Learning Outcomes

- Designed and deployed a multi-tier AWS architecture spanning networking, compute, data, and identity
- Implemented centralized authentication and JWT-based API authorization with Amazon Cognito
- Built a decoupled, asynchronous billing pipeline using SQS and Lambda
- Applied least-privilege IAM design across multiple service roles
- Centralized secret storage and encryption using Secrets Manager and KMS
- Configured multi-service observability using CloudWatch dashboards and log groups
- Practiced cost governance using AWS Budgets and independent cost estimation
- Produced enterprise-style technical documentation defensible in a technical review

---

## 🚧 Future Enhancements

> The following are **not implemented** in the current deployment and are listed only as realistic next steps.

- ⚙️ ECS Service Auto Scaling
- 🔁 Automated CI/CD Pipeline (CodePipeline / GitHub Actions)
- 🧱 Infrastructure as Code (Terraform / CloudFormation / CDK)
- 🌍 Multi-Region Disaster Recovery
- 🛡️ AWS WAF on CloudFront

---

## 👤 Author

**Santhanakrishnan S**

---

## 📄 License

This project is licensed under the **MIT License**.
