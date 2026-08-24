# 🏗️ Amazon EC2

## 📌 Overview

A single EC2 instance, `ec2-rds-14`, runs in the platform's public subnet and serves one specific role: it is the bootstrap host used to connect to the RDS database and create the application database and tables. It is not part of the application's runtime request path.

## 🎯 Purpose in THIS Project

**Business purpose:** before the SaaS application can serve tenants, the underlying `saas_database` schema and tables have to exist. The business needed a controlled way to reach the private RDS instance during initial setup without exposing RDS directly to the internet.

**Technical purpose:** EC2 provides a host inside the same VPC that can be given security-group access to RDS on port 3306, so a database administrator can connect via a MySQL client and provision the schema.

**Contribution to the overall solution:** `ec2-rds-14` is a one-time/administrative component — it is how `saas_database` and its tables were created inside `saas-database`, which the ECS application and the billing Lambda then use at runtime.

## ✅ Why This Service Was Selected

EC2 was selected specifically because RDS in this implementation has no public access — a direct MySQL client on a local machine cannot reach it. An EC2 instance placed inside `saas-VPC-12` gives an administrator a network path to RDS while keeping the database itself unreachable from the internet. No other database-bootstrap approach (e.g. a bastion, Session Manager on RDS, or a Lambda-based migration) is documented as implemented for this task.

## ⚙️ My Implementation

| Attribute | Value |
|---|---|
| Instance Name | `ec2-rds-14` |
| Instance ID | `i-01c9ab04df4fc89e3` |
| AMI | `al2023-ami-2023.12.20260803.3-kernel-6.18-x86_64` (`ami-0bdc7d025135d7b49`) |
| Operating System | Amazon Linux (Linux/UNIX) |
| Instance Type | `t3.micro` |
| Region / AZ | `us-east-1` / `us-east-1b` |
| VPC | `saas-VPC-12` (`vpc-03c620f18f61ea855`) |
| Subnet | `saas-public-sub2-EC2-aza` (`subnet-0cb2c22c0313bf9b2`) |
| Private IPv4 | `10.0.0.101` |
| Public IPv4 | `54.158.177.175` |
| Security Group | `EC2-SG-12` (`sg-054345fb16cc84289`) |
| Key Pair | `rds-ec2-12` |
| Status | Running |

**Purpose (as documented):** connect to the RDS database, and create a database and tables in the RDS database using MySQL. The database `saas_database` was created via this instance and is the database the platform uses.

## 🔄 Role in End-to-End Request Flow

EC2 is **not** part of the live user request flow (`CloudFront → API Gateway → ALB → ECS → RDS`). Its role is administrative and precedes that flow:

```
Administrator
  ↓
EC2 (ec2-rds-14, public subnet)
  ↓
RDS (saas-database, private subnet) — schema/table creation
```

## 🔗 Communication With Other AWS Services

| Service | Why They Communicate | What Is Exchanged | How |
|---|---|---|---|
| Amazon RDS | EC2 connects to RDS to create `saas_database` and its tables | MySQL connection (schema DDL, administrative queries) | Port 3306, permitted by `RDS-SG-12` accepting traffic from `EC2-SG-12` |
| Amazon VPC | EC2 is deployed inside `saas-public-sub2-EC2-azb`, giving it network access to reach RDS in a private subnet of the same VPC | Network routing | Subnet/security-group placement |

No other AWS services (Secrets Manager, KMS, ECS, Lambda) are documented as connected to this EC2 instance.

## 🔒 Security Implementation

- Placed inside `saas-VPC-12`, using a dedicated security group (`EC2-SG-12`) rather than the VPC default.
- Access to RDS is scoped through the security-group chain: `RDS-SG-12` accepts MySQL/Aurora traffic from `EC2-SG-12` as a named source, not an open CIDR.
- Access to the instance itself uses a named key pair (`rds-ec2-12`) rather than a password.

> **Known gap (documented, not fabricated):** `EC2-SG-12` allows inbound SSH (22) and MySQL (3306) from `0.0.0.0/0`. Because this instance has a public IP and broad inbound access, it is the highest documented network-security risk in the platform. The recommended fix is to restrict both rules to a specific administrator CIDR, or replace SSH access entirely with AWS Systems Manager Session Manager.

## 📈 High Availability & Scalability

This service is not used for scalability in this implementation. It is a single `t3.micro` instance used for one-time/administrative database setup, not a component that scales with application load.

## 📊 Monitoring

Monitoring is not applicable. EC2 is not listed among the services tracked on the `tenant-saas-app-monitoring` CloudWatch dashboard or the platform's log groups.

## ✅ Best Practices Implemented

- Deployed inside the project VPC rather than accessed over the public internet directly to RDS
- Uses a dedicated, named security group and key pair rather than shared/default credentials

## ⭐ Why This Service Is Important

Without `ec2-rds-14`, there would be no documented path to initialize `saas_database` inside a private-subnet, no-public-access RDS instance. It is a small but necessary piece of the deployment story: it is how the schema the ECS application and billing Lambda depend on actually came to exist.

## 📝 Summary

`ec2-rds-14` is a `t3.micro` administrative bootstrap host used exclusively to connect to and provision the `saas_database` schema inside the private RDS instance. It plays no role in live traffic handling and is the one component in this implementation with the broadest network exposure, which is documented here as an accepted, known risk rather than omitted.
