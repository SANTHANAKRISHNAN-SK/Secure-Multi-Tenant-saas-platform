# 🏗️ Amazon VPC

## 📌 Overview

The **Secure Multi-Tenant SaaS Platform** runs entirely inside a single custom VPC, `saas-VPC-12` (`10.0.0.0/24`, region `us-east-1`). This VPC is the network foundation that every other service in the platform — the Application Load Balancer, ECS Fargate, RDS, and the billing Lambda — is deployed into. It is split into four `/26` subnets across two Availability Zones, separating internet-facing resources from the application and data tier.

## 🎯 Purpose in THIS Project

**Business purpose:** the platform serves multiple tenant organizations from one shared deployment, so the network layer has to guarantee that tenant data (in RDS) and application logic (in ECS) can never be reached directly from the public internet — isolation is a baseline trust requirement for a multi-tenant SaaS product, not an optional hardening step.

**Technical purpose:** `saas-VPC-12` provides the address space, subnet segmentation, routing, and gateway infrastructure that lets public-facing components (ALB, the EC2 bootstrap host) sit in public subnets while RDS, ECS Fargate, and the Lambda billing function sit in private subnets with no direct internet exposure.

**Contribution to the overall solution:** every request that reaches the application — `CloudFront → API Gateway → ALB → ECS → RDS` — crosses this VPC's subnets and route tables. Without it, none of the compute or data services in this project would have a place to run.

## ✅ Why This Service Was Selected

A custom VPC (rather than the AWS default VPC) was selected because the project requires explicit control over which subnets are public vs. private and which security groups can talk to which. The implementation uses a `/24` CIDR block split into four `/26` subnets — two public, two private — which is deliberately sized for this project's actual resource count (ALB, one EC2 bootstrap instance, ECS Fargate tasks, one RDS instance) rather than over-provisioned for growth that isn't part of this implementation.

## ⚙️ My Implementation

### Core VPC

| Attribute | Value |
|---|---|
| VPC Name | `saas-VPC-12` |
| VPC ID | `vpc-03c620f18f61ea855` |
| CIDR Block | `10.0.0.0/24` |
| Region | `us-east-1` |

### Subnets (4)

| # | Name | Subnet ID | Type | CIDR | Availability Zone |
|---|---|---|---|---|---|
| 1 | `saas-public-sub1-ALB-aza` | `subnet-0d24c57f51289130e` | Public | `10.0.0.0/26` | `us-east-1a` |
| 2 | `saas-public-sub2-EC2-azb` | `subnet-0cb2c22c0313bf9b2` | Public | `10.0.0.64/26` | `us-east-1b` |
| 3 | `saas-private-sub1-RDS-aza` | `subnet-061aa5db0fd7392d2` | Private | `10.0.0.128/26` | `us-east-1a` |
| 4 | `saas-private-sub2-ECS-aza` | `subnet-0dc094fbd105a3f97` | Private | `10.0.0.192/26` | `us-east-1a` |

The ALB, ECS, and RDS resources all sit in Availability Zone `us-east-1a`, but in three different subnets (public, private-RDS, private-ECS respectively). The billing Lambda function is attached to the same two private subnets used by ECS and RDS.

### Gateways

| Resource | Name | ID |
|---|---|---|
| Internet Gateway | `saas-IGW-12` | `igw-0e14fa4dfd22a2659` |
| NAT Gateway | `saas-NAT-18` | `nat-19f35b394c3ab7636` (Regional) |

### Route Tables

| Route Table | ID | Associated Subnets | Route |
|---|---|---|---|
| Public | `rtb-0d5e9bc2e1711ab0c` | 2 public subnets | → Internet Gateway |
| Private | `rtb-0523b9a34d724232e` | 2 private subnets | → NAT Gateway |

The private route table gives ECS, RDS, and Lambda outbound-only internet access (for tasks like pulling the ECR image, calling AWS APIs, or downloading OS updates) through the NAT Gateway, without allowing any inbound connection to originate from the internet.

### Security Groups (5)

| # | Name | ID | Inbound Rule(s) | Purpose |
|---|---|---|---|---|
| 1 | `ALB-SG-12` | `sg-0e1b1f023fbb55fad` | HTTPS 443 from `0.0.0.0/0`; HTTP 80 from `0.0.0.0/0` | Application Load Balancer |
| 2 | `ECS-SG-12` | `sg-0a895aeb74947a534` | Custom TCP 8080 from `ALB-SG-12` | ECS Fargate tasks |
| 3 | `RDS-SG-12` | `sg-04b2fe2cf0099879e` | MySQL/Aurora 3306 from `ECS-SG-12`, `EC2-SG-12`, and the Lambda security group | RDS database |
| 4 | `saas-LAMBDA-billing-SG` | `sg-080f0b92c37b76dca` | None (no inbound rules) | Billing Lambda function |
| 5 | `EC2-SG-12` | `sg-054345fb16cc84289` | SSH 22 from `0.0.0.0/0`; MySQL/Aurora 3306 from `0.0.0.0/0` | EC2 bootstrap instance (database creation) |

The security groups form a **chained trust model**: `ALB-SG-12 → ECS-SG-12 → RDS-SG-12`. Each group only accepts traffic from the specific security group in front of it — not from arbitrary CIDR ranges — except for `ALB-SG-12` (which must accept public traffic by design) and `EC2-SG-12` (used only for one-time database bootstrapping).

### Connectivity Paths (by Security Group)

- `ALB → ECS → RDS`
- `EC2 → RDS`
- `Lambda → RDS`

## 🔄 Role in End-to-End Request Flow

```
User
  ↓
CloudFront
  ↓
API Gateway
  ↓
ALB (public subnet, saas-VPC-12)
  ↓
ECS Fargate (private subnet, saas-VPC-12)
  ↓
RDS (private subnet, saas-VPC-12)
```

The VPC itself does not process requests — it defines the boundary and paths every request travels through once it reaches the ALB. Everything from the ALB onward (ECS, RDS, the Lambda billing path via SQS) operates inside this VPC's subnets.

## 🔗 Communication With Other AWS Services

| Service | Why They Communicate | What Is Exchanged | How |
|---|---|---|---|
| Application Load Balancer | ALB is deployed into the two public subnets to receive internet traffic | HTTP/HTTPS requests and responses | Public subnet routing via Internet Gateway |
| Amazon ECS Fargate | ECS tasks run in a private subnet and receive traffic only from the ALB | Application requests/responses | Security-group-scoped traffic (`ECS-SG-12` accepts only from `ALB-SG-12`) |
| Amazon RDS | RDS runs in a private subnet, reachable only from ECS, EC2, and Lambda | Database queries and MySQL protocol traffic | Security-group-scoped traffic on port 3306 |
| AWS Lambda (Billing) | Lambda is VPC-attached to the same private subnets as ECS/RDS to reach RDS securely | Billing/usage records written to RDS | Private subnet + NAT Gateway (for AWS API calls) + `RDS-SG-12` |
| Amazon EC2 | EC2 instance sits in a public subnet and connects to RDS for one-time database/table creation | MySQL connection to `saas_database` | Security-group-scoped traffic on port 3306 |
| NAT Gateway | Private-subnet resources (ECS, RDS, Lambda) route outbound internet traffic through it | Outbound-only connections (e.g. pulling ECR images, calling AWS service endpoints) | Private route table default route |

## 🔒 Security Implementation

- **Public/private subnet separation:** only the ALB and the EC2 bootstrap instance sit in public subnets; ECS, RDS, and the Lambda function all sit in private subnets with no direct route to the Internet Gateway.
- **Security-group chaining:** `ECS-SG-12` and `RDS-SG-12` reference other security groups as their traffic source instead of open CIDR ranges, so only the intended AWS resources — not arbitrary IP ranges — can reach ECS or RDS.
- **No inbound rules on the Lambda security group:** `saas-LAMBDA-billing-SG` has zero inbound rules, since the billing function only ever initiates outbound connections (to Secrets Manager, SQS, and RDS).
- **NAT Gateway for private egress:** private-subnet resources get outbound internet access without being directly reachable from the internet.

> **Known gap (documented, not fabricated):** `EC2-SG-12` allows SSH (22) and MySQL (3306) from `0.0.0.0/0`. This is an accepted risk in the current implementation, used only for one-time database setup from the EC2 bootstrap host; it should be restricted to a specific administrator CIDR or replaced with AWS Systems Manager Session Manager.

## 📈 High Availability & Scalability

The VPC itself spans two Availability Zones (`us-east-1a` and `us-east-1b`) via its four subnets, and the ALB is associated with subnets in both AZs. However, the application stack (ECS, RDS, Lambda's chosen subnets) is currently concentrated in `us-east-1a` only — the second AZ's subnet capacity (`saas-public-sub2-EC2-azb`) is used for the EC2 bootstrap host, not for a redundant application deployment. There is no Multi-AZ RDS standby and no cross-AZ ECS task spread configured in this implementation.

## 📊 Monitoring

Monitoring is not applicable to the VPC itself as a standalone resource in this implementation — VPC-level traffic (VPC Flow Logs) is not configured. Monitoring of the services that run inside the VPC (ECS, RDS, ALB, Lambda) is covered in their respective READMEs and in the shared CloudWatch dashboard `tenant-saas-app-monitoring`.

## ✅ Best Practices Implemented

- Segmented public/private subnet design instead of a flat/default VPC
- Security-group-to-security-group referencing for internal traffic instead of broad CIDR rules
- NAT Gateway used for private-subnet egress rather than granting private resources public IPs
- Route tables scoped separately per subnet tier (public vs. private)

## ⭐ Why This Service Is Important

The VPC is the structural foundation the entire "Secure" part of "Secure Multi-Tenant SaaS Platform" depends on. Every isolation guarantee made to tenants — that their data in RDS can't be reached directly from the internet, that only the ALB can talk to ECS — is enforced at this layer through subnet placement and security groups. If the VPC design were flat or default, none of the other services' security postures documented in this project would hold.

## 📝 Summary

`saas-VPC-12` provides a two-AZ, four-subnet network foundation that separates the platform's public entry point (ALB) from its private application and data tier (ECS, RDS, Lambda). Its security-group chain (`ALB-SG-12 → ECS-SG-12 → RDS-SG-12`) and NAT-Gateway-based private egress are the concrete mechanisms behind every other service's network security claims in this project.
