# 🚀 Secure Multi-Tenant SaaS Platform on AWS

<p align="center">

![AWS](https://img.shields.io/badge/AWS-Cloud-orange?logo=amazonaws)
![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-black?logo=flask)
![Docker](https://img.shields.io/badge/Docker-Container-blue?logo=docker)
![Amazon ECS](https://img.shields.io/badge/Amazon-ECS-orange)
![Amazon RDS](https://img.shields.io/badge/Amazon-RDS-blue)
![Amazon Cognito](https://img.shields.io/badge/Amazon-Cognito-yellow)
![License](https://img.shields.io/badge/License-MIT-green)

</p>

---

# 📌 Project Overview

The **Secure Multi-Tenant SaaS Platform on AWS** is a cloud-native application designed to provide secure, scalable, and isolated access for multiple tenants within a single platform. The solution leverages AWS managed services to deliver authentication, networking, application hosting, secure database access, monitoring, logging, and tenant usage processing.

This project was developed as part of an internship to demonstrate cloud architecture design, secure deployment practices, multi-tenant application management, and AWS service integration.

---

# 🎯 Project Objectives

- Build a secure multi-tenant SaaS platform.
- Implement tenant authentication and authorization.
- Deploy a containerized Flask application.
- Secure database connectivity.
- Monitor application health and activity.
- Implement tenant usage processing.
- Demonstrate AWS best practices.
- Produce professional technical documentation.

---

# ✨ Key Features

- 👥 Multi-Tenant Architecture
- 🔐 Amazon Cognito Authentication with a Resource Server and custom OAuth scopes
- 🌐 Amazon API Gateway as the primary JWT authentication and API-scope authorization boundary
- ⚖️ Application Load Balancer
- 🐳 Amazon ECS Fargate Deployment
- 🗄️ Amazon RDS MySQL Database
- 🔑 AWS Secrets Manager Integration
- 🔒 AWS KMS Encryption
- 📊 Amazon CloudWatch Monitoring
- 📝 AWS CloudTrail Auditing
- 📦 Amazon ECR Container Registry
- ☁️ Amazon CloudFront Distribution with a CloudFront Function for token forwarding
- 📨 Amazon SQS Queue
- ⚡ AWS Lambda Usage Processing
- 💰 AWS Billing & Budgets Monitoring

---

# 🏗️ High-Level Architecture

The platform separates the **user login flow** from the **protected API request flow** — Cognito's Hosted UI is only involved when a user authenticates, not on every subsequent API call.

### Login Flow

```text
Browser
   │
   ▼
Amazon CloudFront
   │
   ▼
Cognito Hosted UI
   │
   ▼
Authorization Code
   │
   ▼
/auth/callback (Flask, token exchange)
```

### Protected API Request Flow

```text
Browser
   │
   ▼
Amazon CloudFront
   │
   ▼
CloudFront Function (token forwarding only)
   │
   ▼
Authorization: Bearer <Cognito Access Token>
   │
   ▼
Amazon API Gateway REST API
   │
   ▼
Cognito User Pool Authorizer (JWT + scope validation)
   │
   ▼
Application Load Balancer
   │
   ▼
Amazon ECS Fargate — Flask Application
   │
   ▼
Amazon RDS MySQL
```

### Usage Metering Flow

```text
Amazon ECS
     │
     ▼
 Amazon SQS
     │
     ▼
 AWS Lambda
     │
     ▼
 Amazon RDS
```

### Credential Flow

```text
Amazon ECS / Lambda
     │
     ▼
AWS Secrets Manager
     │
     ▼
AWS KMS
```

---

# 🔑 Authentication & Authorization

Authentication and authorization are split across four layers, each with a distinct, non-overlapping responsibility:

| Layer | Responsibility |
|---|---|
| **Amazon Cognito** | User authentication via the Hosted UI, OAuth 2.0 Authorization Code Grant, and issuance of the JWT Access Token and ID Token |
| **CloudFront Function** | Reads the Cognito access token from the browser cookie and adds it as `Authorization: Bearer <access_token>`. **Does not** validate the JWT and **does not** authenticate users — token forwarding only |
| **Amazon API Gateway (Cognito User Pool Authorizer)** | The **primary authentication and API authorization boundary**. Validates the JWT (signature, issuer, expiry) and enforces the required OAuth scope (`saas-api/read` or `saas-api/write`) per method before any request reaches the ALB or ECS |
| **Flask Application** | **Not** the primary authentication layer. Performs only application-level tenant authorization, role authorization, business logic, and resource authorization after the request has already passed the API Gateway authorization boundary |

This separation keeps unauthenticated, tampered, or under-scoped requests from ever reaching the application tier, while leaving fine-grained, tenant-aware authorization to the Flask application itself.

---

# 🏗️ Cognito Configuration

| Attribute | Value |
|---|---|
| User Pool | `kmfplo` |
| Region | `us-east-1` |
| App Client | `saas-SPA-cognito-12` |
| OAuth Flow | Authorization Code Grant |
| Resource Server | `saas-api` |
| Custom Scopes | `saas-api/read`, `saas-api/write` |
| Tenant Groups | `TenantA_admin`, `TenantA_user`, `TenantB_admin`, `TenantB_user` |

The `saas-api` Resource Server defines the custom scopes consumed by the API Gateway Cognito User Pool Authorizer to enforce per-method authorization — the Resource Server itself does not validate JWTs; that validation is performed by API Gateway.

---

# 🚪 API Gateway

| Attribute | Value |
|---|---|
| API Type | REST API |
| Integration | HTTP Proxy Integration |
| Backend | Application Load Balancer |
| Protected `GET` routes | Cognito User Pool Authorizer, scope `saas-api/read` |
| Protected `POST` routes | Cognito User Pool Authorizer, scope `saas-api/write` |
| Public routes | `Authorization = NONE` |

Every protected method requires a valid Cognito-issued JWT carrying the matching scope; public routes (health checks, login redirects, static assets) bypass the authorizer entirely.

---

# ☁️ AWS Services Used

| Service | Purpose |
|----------|---------|
| Amazon VPC | Network isolation |
| Amazon EC2 | Supporting compute resources |
| Application Load Balancer | Traffic distribution |
| Amazon ECS Fargate | Application hosting |
| Amazon ECR | Docker image repository |
| Amazon API Gateway | Primary JWT authentication and API-scope authorization boundary |
| Amazon Cognito | User authentication, JWT issuance, Resource Server & custom OAuth scopes |
| Amazon RDS | Relational database |
| AWS Lambda | Background processing |
| Amazon SQS | Message queue |
| AWS Secrets Manager | Secure credential management |
| AWS KMS | Encryption |
| Amazon CloudFront | Content delivery + CloudFront Function for token forwarding |
| Amazon CloudWatch | Monitoring & Logging |
| AWS CloudTrail | Audit logging |
| AWS Billing & Budgets | Cost monitoring |
| AWS CloudShell | Cloud management |
| Windows CMD | Lambda package preparation |

---

# 📂 Repository Structure

```text
Secure-Multi-Tenant-SaaS-Platform/
│
├── Billing Function/
│   ├── Lambda function/
│   └── .gitkeep
│
├── DEMO VIDEO/
│   └── DEMO_VIDEO.md
│
├── Deliverables/
│   ├── 01-Business-Requirement-Document.md
│   ├── 02-Solution-Architecture.md
│   ├── 03-High-Level-Design.md
│   ├── 04-Low-Level-Design.md
│   ├── 05-Infrastructure-Diagram.md
│   ├── 06-Deployment-Guide-SOP.md
│   ├── 07-Security-Architecture.md
│   ├── 08-Monitoring-and-Logging.md
│   ├── 09-Backup-and-Disaster-Recovery.md
│   └── 10-Cost-Estimation.md
│
├── Diagram/
│   ├── HLD/
│   ├── INFRASTRUCTURE/
│   ├── LLD/
│   ├── SECURITY ARCHITECTURE/
│   ├── SOLUTION ARCHITECTURE/
│   └── .gitkeep
│
├── Flask app/
│   ├── tenant-saas-app-fixed/
│   └── .gitkeep
│
├── Services/
│   ├── ALB/
│   ├── API GATEWAY/
│   ├── BILLING AND COST MANAGEMENT/
│   ├── CLOUDFRONT/
│   ├── CLOUDSHELL/
│   ├── CLOUDWATCH/
│   ├── COGNITO/
│   ├── EC2/
│   ├── ECR/
│   ├── ECS/
│   ├── IAM/
│   ├── KMS/
│   ├── LAMBDA/
│   ├── RDS/
│   ├── SECRETS MANAGER/
│   ├── SQS/
│   ├── VPC/
│   ├── WINDOWS CMD/
│   └── .gitkeep
│
├── images/
│   ├── ALB/
│   ├── API GATEWAY/
│   ├── BILLING AND COST MANAGEMENT/
│   ├── CLOUDFRONT/
│   ├── CLOUDSHELL/
│   ├── CLOUDWATCH/
│   ├── COGNITO/
│   ├── EC2/
│   ├── ECR/
│   ├── ECS/
│   ├── IAM/
│   ├── IMPLEMENTATION/
│   ├── KMS/
│   ├── LAMBDA/
│   ├── RDS/
│   ├── RDS DATABASE TABLES/
│   ├── SECRET MANAGER/
│   ├── SQS/
│   ├── VPC/
│   └── .gitkeep
│
├── .gitignore
└── README.md
```

---

# 📚 Project Documentation

| #  | Document                                | Status |
| -- | --------------------------------------- | ------ |
| 01 | Business Requirement Document (BRD)     | ✅      |
| 02 | Solution Architecture                   | ✅      |
| 03 | High-Level Design (HLD)                 | ✅      |
| 04 | Low-Level Design (LLD)                  | ✅      |
| 05 | Infrastructure Diagram                  | ✅      |
| 06 | Deployment Guide / SOP                  | ✅      |
| 07 | Security Architecture                   | ✅      |
| 08 | Monitoring and Logging                  | ✅      |
| 09 | Backup and Disaster Recovery            | ✅      |
| 10 | Cost Estimation                         | ✅      |
| —  | AWS Service Documentation (18 Services) | ✅      |
| —  | Architecture Diagrams                   | ✅      |
| —  | Flask Application                       | ✅      |
| —  | Billing Function                        | ✅      |
| —  | Demo Video                              | ✅      |

---

# 🔐 Security Features

- **Primary JWT authentication and API-scope authorization at Amazon API Gateway**, via the Cognito User Pool Authorizer, enforcing the `saas-api/read` and `saas-api/write` scopes per method
- **Token forwarding only at the CloudFront Function** — it never validates or authenticates the JWT
- **Application-level tenant and role authorization in Flask**, performed after the request has already cleared the API Gateway authorization boundary
- Tenant isolation via Cognito User Groups (`TenantA_admin`/`TenantA_user`, `TenantB_admin`/`TenantB_user`)
- IAM-based, least-privilege access control across ECS, Lambda, and supporting services
- Encrypted secrets management via AWS Secrets Manager
- Encryption at rest and in transit using AWS KMS
- Private, non-public database connectivity for Amazon RDS
- Audit logging via AWS CloudTrail

---

# 📊 Monitoring & Logging

- Amazon CloudWatch
- CloudWatch Logs
- CloudWatch Dashboards
- Application monitoring
- Infrastructure monitoring

---

# 💰 Cost Management

- AWS Budgets
- Cost monitoring
- Usage tracking
- Billing notifications

---

# 📸 Project Screenshots

- Architecture Diagram
- AWS Console
- Cognito Authentication
- API Gateway
- Application Load Balancer
- Amazon ECS
- Amazon RDS
- CloudWatch Dashboard
- Tenant Admin Dashboard
- Tenant User Dashboard

---

# 🎥 Demo Video

> https://drive.google.com/file/d/16-41T3O55b1s3EaHDrAjah93Qe3kUZ2T/view?usp=drivesdk

---

# 🚀 Deployment Summary

The application is deployed using AWS managed services with a secure multi-tier architecture. Browser requests pass through CloudFront and a CloudFront Function that forwards the Cognito access token, are authenticated and scope-checked at API Gateway's Cognito User Pool Authorizer, then proxied through the Application Load Balancer to the containerized Flask application running on Amazon ECS Fargate. The Flask application performs tenant-, role-, and resource-level authorization before reading from or writing to Amazon RDS MySQL. Tenant usage events are published to Amazon SQS and processed asynchronously by AWS Lambda, while credentials for ECS and Lambda are retrieved from AWS Secrets Manager and decrypted via AWS KMS. The full stack is monitored through Amazon CloudWatch and audited through AWS CloudTrail.

---

# 📈 Future Enhancements

- Kubernetes deployment
- CI/CD pipeline
- Infrastructure as Code
- Auto Scaling improvements
- Multi-region deployment
- Advanced analytics dashboard

---

# 👨‍💻 Author

**Santhanakrishnan S**

**Project:** Secure Multi-Tenant SaaS Platform on AWS

**GitHub:** https://github.com/SANTHANAKRISHNAN-SK

---

# 📄 License

This project is developed for educational and internship purposes.

---

# ⭐ Acknowledgements

Special thanks to my internship mentor and the AWS community for providing the knowledge and resources that supported the successful completion of this project.
