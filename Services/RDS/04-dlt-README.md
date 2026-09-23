# 🏗️ Amazon RDS

## 📌 Overview

`saas-database` is the single MySQL RDS instance that serves as the backend database for the entire platform. It stores both the application's operational data (accessed via ECS) and the tenant usage/billing records written by the billing Lambda function — one database serving both purposes, not two separate instances.

## 🎯 Purpose in THIS Project

**Business purpose:** tenant data (users, roles, usage, billing) needs a durable, structured store. RDS is what persists everything the platform's tenants and administrators rely on across sessions.

**Technical purpose:** RDS provides the MySQL engine the Flask application connects to for reads/writes, and the same instance/database is where the billing Lambda inserts `tenant_usage` records after consuming events from SQS.

**Contribution to the overall solution:** RDS is the terminal point of both major flows in the platform — the direct application flow (`ALB → ECS → RDS`) and the asynchronous billing flow (`ECS → SQS → Lambda → RDS`).

## ✅ Why This Service Was Selected

MySQL Community on RDS was selected as a managed relational database that removes patching/backup operational overhead while supporting the structured, relational access patterns the Flask application and billing Lambda both need (user records, tenant usage rows, standard SQL). A single instance was used rather than separate application/billing databases, since the documented implementation is one `saas_database` shared by both.

## ⚙️ My Implementation

| Attribute | Value |
|---|---|
| DB Identifier | `saas-database` |
| Database Engine | MySQL Community |
| Engine Version | 8.4.9 |
| Instance Class | `db.t4g.micro` |
| Storage Type | General Purpose SSD (gp2) |
| Allocated Storage | 400 GiB |
| Region / AZ | `us-east-1` / `us-east-1a` |
| VPC | `saas-VPC-12` (`vpc-03c620f18f61ea855`) |
| DB Subnet Group | `default-vpc-03c620f18f61ea855` |
| Security Group | `RDS-SG-12` (`sg-04b2fe2cf0099879e`) |
| Database Name | `mysql` (application database created inside it: `saas_database`) |
| Master Username | `admin` |
| Port | 3306 |
| Storage Encryption | Enabled |
| KMS Key | `saas-key-12` (`6c0c7b96-7824-4024-b118-04955f2339ed`) |
| Public Access | No |
| Endpoint | `saas-database.cspc2k48alh9.us-east-1.rds.amazonaws.com` |
| Status | Available |

The database `saas_database` and its tables were created via a bootstrap EC2 instance (`ec2-rds-14`) connecting over MySQL.

## 🔄 Role in End-to-End Request Flow

**Application flow:**
```
User → CloudFront → API Gateway → ALB → ECS Fargate → Amazon RDS
```

**Billing/usage flow:**
```
ECS Fargate → Amazon SQS → AWS Lambda (billing) → Amazon RDS
```

**Bootstrap flow (one-time, administrative):**
```
Amazon EC2 (ec2-rds-14) → Amazon RDS
```

## 🔗 Communication With Other AWS Services

| Service | Why They Communicate | What Is Exchanged | How |
|---|---|---|---|
| Amazon ECS Fargate | The Flask application reads/writes application data during request handling | SQL queries and result sets | MySQL protocol on port 3306, permitted via `RDS-SG-12` accepting `ECS-SG-12` |
| AWS Lambda (Billing) | The metering function inserts tenant usage records after consuming SQS messages | `INSERT INTO tenant_usage (...)` statements | MySQL protocol on port 3306, permitted via `RDS-SG-12` accepting the Lambda security group |
| Amazon EC2 | Used to create the `saas_database` schema and tables | DDL/administrative SQL | MySQL protocol on port 3306, permitted via `RDS-SG-12` accepting `EC2-SG-12` |
| AWS Secrets Manager | ECS and Lambda retrieve RDS credentials (`db_username`, `db_password`, `host`, `port`) from Secrets Manager rather than storing them independently | Database connection credentials | IAM-permissioned `GetSecretValue` calls made by ECS's and Lambda's roles |
| AWS KMS | The customer-managed key `saas-key-12` protects RDS storage encryption | Encryption/decryption of storage volumes | RDS-native integration with the assigned KMS key |

## 🔒 Security Implementation

- **No public access** — RDS is only reachable from within the VPC's private subnets.
- **Security-group-scoped access**: `RDS-SG-12` only accepts MySQL/Aurora traffic from three named security groups — ECS, EC2, and Lambda — never from an open CIDR.
- **Storage encryption at rest** enabled, using customer-managed KMS key `saas-key-12`.
- **Credentials centralized** in AWS Secrets Manager (`saas-secret-rds-12`) rather than hardcoded in application source.

## 📈 High Availability & Scalability

The instance runs Single-AZ (`us-east-1a`) on a `db.t4g.micro` class with no documented Multi-AZ standby. This service is not used for horizontal scalability in this implementation — there is one RDS instance, and no read replicas are configured.

## 📊 Monitoring

Tracked on the `tenant-saas-app-monitoring` CloudWatch dashboard with the following metrics:

- `FreeStorageSpace`
- `CPUUtilization`
- `DatabaseConnections`

## ✅ Best Practices Implemented

- Storage encryption at rest with a customer-managed KMS key
- No public accessibility
- Credentials retrieved from Secrets Manager rather than embedded permanently in code
- Access restricted to specific security groups rather than broad network ranges

## ⭐ Why This Service Is Important

RDS is where every piece of durable state in the platform ultimately lands — tenant user data through the application path and tenant billing/usage data through the asynchronous metering path. Its private-subnet, security-group-scoped design is what makes the platform's "secure multi-tenant" claim technically real rather than just architectural intent.

## 📝 Summary

`saas-database` is a Single-AZ, encrypted, privately-networked MySQL instance that serves both the application's operational data needs (via ECS) and the platform's usage-metering pipeline (via the billing Lambda), reached exclusively through security-group-scoped connections from ECS, EC2, and Lambda.
