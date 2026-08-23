# 📄 Business Requirement Document (BRD)

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Business Requirement Document |
| Project Name | Secure Multi-Tenant SaaS Platform on AWS |
| Document Type | Business Requirements |
| Prepared For | AWS Cloud Internship Portfolio |
| Classification | Internal / Portfolio |
| Status | Final |

## Version History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | Initial Release | Cloud Engineering Author | First published version derived from implemented AWS configuration |

## Document Control

| Control Item | Detail |
|---|---|
| Owner | Project Author |
| Review Cycle | On major architecture change |
| Distribution | Public (GitHub Portfolio) |
| Source of Truth | AWS Configuration Document (implemented infrastructure) |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Objectives](#2-business-objectives)
3. [Project Scope](#3-project-scope)
4. [Stakeholders](#4-stakeholders)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Assumptions](#7-assumptions)
8. [Constraints](#8-constraints)
9. [Success Criteria](#9-success-criteria)
10. [Risks](#10-risks)
11. [Conclusion](#11-conclusion)
12. [Appendix](#12-appendix)

---

## 1. Executive Summary

This document defines the business requirements for a **Secure Multi-Tenant SaaS Platform** built entirely on AWS-native services. The platform allows multiple tenants (organizations) to share a single application deployment while keeping each tenant's users, data access, and billing/usage tracking logically isolated. It was designed and deployed as a hands-on AWS internship project to demonstrate production-style architecture across networking, compute, identity, security, messaging, and observability.

## 2. Business Objectives

| # | Objective | Description |
|---|---|---|
| 1 | Multi-Tenant Access | Support multiple tenant organizations (e.g. Tenant A, Tenant B) with isolated user groups and admin roles inside a single application. |
| 2 | Secure Authentication | Provide centralized, standards-based identity and access control (OAuth2/JWT) for all tenant users. |
| 3 | Usage-Based Billing | Track per-tenant API usage events and persist them for billing/metering purposes. |
| 4 | High Availability Foundations | Run the application on managed, container-based compute with load balancing across Availability Zones. |
| 5 | Operational Visibility | Provide centralized logging, dashboards, and cost tracking so the platform's health and spend are observable. |
| 6 | Cost Control | Operate within a fixed monthly budget appropriate for a portfolio/internship-scale workload. |

## 3. Project Scope

### 3.1 In Scope

- Design and deployment of a segmented VPC (public/private subnets) hosting the platform.
- Containerized Flask application deployed on Amazon ECS Fargate, fronted by an Application Load Balancer and Amazon API Gateway.
- Centralized authentication via Amazon Cognito (Hosted UI, JWT tokens, tenant-based user groups).
- Asynchronous usage-metering pipeline (SQS → Lambda → RDS) for tenant billing data.
- Encryption of secrets and data using AWS KMS and Secrets Manager.
- Global content delivery via Amazon CloudFront.
- Centralized monitoring via Amazon CloudWatch (dashboards, logs, Container Insights).
- Cost governance via AWS Budgets.

### 3.2 Out of Scope

- Multi-region / disaster-recovery failover (single-region deployment only — see [09-Backup-and-Disaster-Recovery.md](09-Backup-and-Disaster-Recovery.md)).
- Auto Scaling policies for ECS (not configured in current implementation).
- Web Application Firewall (WAF) protection (currently disabled — see [07-Security-Architecture.md](07-Security-Architecture.md)).
- Custom domain name and TLS certificate on CloudFront (currently using the default CloudFront domain).

## 4. Stakeholders

| Role | Responsibility |
|---|---|
| Cloud/Platform Engineer (Author) | Designs, provisions, and documents the AWS infrastructure |
| Tenant Administrators | Manage users within their own tenant group (`TenantA_admin`, `TenantB_admin`) |
| Tenant Users | Consume the SaaS application (`TenantA_user`, `TenantB_user`) |
| Technical Reviewer | Evaluates architecture and implementation for correctness and best practice alignment |

## 5. Functional Requirements

| ID | Requirement | Implemented Via |
|---|---|---|
| FR-01 | Users must authenticate before accessing protected resources | Amazon Cognito Hosted UI + JWT |
| FR-02 | The system must support distinct tenant admin and tenant user roles | Cognito User Groups (`TenantA_admin`, `TenantA_user`, `TenantB_admin`, `TenantB_user`) |
| FR-03 | The application must expose a versioned REST API | Amazon API Gateway (`/api/v1/...`) |
| FR-04 | The system must record every billable API interaction per tenant | ECS App → SQS → Lambda → RDS |
| FR-05 | Users must be able to view and update their profile details | `/api/v1/users/userdetails` (GET, PUT) |
| FR-06 | Admins must be able to create, disable, and delete users | `/api/v1/admin/users` endpoints |
| FR-07 | Users/tenants must be able to view billing and usage dashboards | `/api/v1/billing/dashboard`, `/api/v1/billing/usage` |
| FR-08 | The platform must expose a health-check endpoint | `/api/v1/health` |
| FR-09 | Database credentials must never be hard-coded in application code | AWS Secrets Manager |

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Security | All inter-service credentials encrypted at rest (KMS); private subnets for data/compute tier; least-privilege IAM roles per service |
| Availability | Compute and networking span two Availability Zones for ALB/EC2/RDS subnet placement |
| Performance | API Gateway + CloudFront used to reduce latency and centralize routing |
| Observability | CloudWatch dashboards and log groups for ECS, Lambda, RDS, ALB, API Gateway, CloudFront |
| Cost | Monthly spend governed by an AWS Budget with alert thresholds at 50%, 80%, and 100% |
| Maintainability | Infrastructure organized by clearly named, purpose-scoped AWS resources (e.g. `saas-VPC-12`, `saas-cluster-13`) |

## 7. Assumptions

- The platform is operated as a single-region, portfolio/internship-scale deployment rather than a commercial production system.
- Traffic volume is low enough that a single ECS task and `db.t4g.micro` RDS instance are sufficient.
- Tenants shown (`TenantA`, `TenantB`) are illustrative of the multi-tenant model rather than real customer organizations.

## 8. Constraints

- **Budget constraint:** Monthly AWS spend is capped by a `$50.00` budget (see [10-Cost-Estimation.md](10-Cost-Estimation.md)).
- **Single-region constraint:** All resources are deployed in `<AWS_REGION>` only.
- **No custom domain:** The application is currently reachable only via the default CloudFront and API Gateway domains.

## 9. Success Criteria

| Criteria | Definition of Done |
|---|---|
| Functional platform | End users can log in via Cognito, reach protected APIs through CloudFront → API Gateway → ALB → ECS, and read/write data in RDS |
| Isolated tenancy | Users are scoped to tenant-specific Cognito groups |
| Working billing pipeline | Usage events published to SQS are reliably consumed by Lambda and persisted to RDS |
| Secure secret handling | No plaintext credentials present in application code or container image |
| Observable operations | CloudWatch dashboard shows live metrics across all core services |
| Documented and defensible | Every design decision can be explained by the author during a technical review |

## 10. Risks

| Risk | Impact | Mitigation Recommendation |
|---|---|---|
| No Multi-Factor Authentication on Cognito | Medium | Enable MFA for admin-tier user groups |
| No WAF on CloudFront | Medium | Attach AWS WAF Web ACL to the distribution |
| No automated alarms on CloudWatch | Medium | Configure CloudWatch Alarms + SNS notifications on key metrics |
| Secrets Manager rotation disabled | Medium | Enable automatic rotation for the RDS secret |
| Single AZ effective compute footprint | Low–Medium | Extend ECS service and RDS to Multi-AZ for production use |

## 11. Conclusion

The Secure Multi-Tenant SaaS Platform satisfies the core business objective of demonstrating a realistic, security-conscious, multi-tenant SaaS architecture on AWS within a constrained budget. The requirements captured here map directly to the implemented services described in the companion Solution Architecture, High-Level Design, and Low-Level Design documents.

## 12. Appendix

### 12.1 Related Documents

- 02-Solution-Architecture.md
- 03-High-Level-Design.md
- 04-Low-Level-Design.md
- 07-Security-Architecture.md
- 10-Cost-Estimation.md

### 12.2 Glossary

| Term | Definition |
|---|---|
| Tenant | A distinct customer organization sharing the platform |
| JWT | JSON Web Token, used for stateless authentication |
| ALB | Application Load Balancer |
| SaaS | Software as a Service |
