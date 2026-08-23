# 🚀 Deployment Guide / Standard Operating Procedure (SOP)

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Deployment Guide / SOP |
| Project Name | Secure Multi-Tenant SaaS Platform on AWS |
| Status | Final |

## Version History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | Initial Release | Cloud Engineering Author | First published version |

## Document Control

> This SOP follows the **actual deployment sequence** used to build the platform, in AWS Console order. Every value shown is a placeholder — substitute your own account-specific values when executing these steps.

---

## Table of Contents

1. VPC Setup
2. EC2 Setup
3. Application Load Balancer Setup
4. RDS Database Setup
5. IAM Setup
6. KMS Setup
7. Secrets Manager Setup
8. SQS Setup
9. CloudFront Setup
10. API Gateway Setup
11. Lambda Setup
12. ECR Setup
13. ECS Setup
14. CloudShell Build & Push
15. CloudWatch Setup
16. Billing and Cost Management Setup
17. Cognito Setup
18. Conclusion
19. Appendix

---

## 1. VPC Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide an isolated network foundation with public and private subnets for the SaaS platform. |
| **Prerequisites** | AWS account with VPC creation permissions; region selected (`<AWS_REGION>`). |
| **Console Navigation** | VPC Console → Your VPCs → Create VPC (with settings for subnets, route tables, NAT). |
| **Configuration Steps** | 1) Create VPC with CIDR `10.0.0.0/24`. 2) Create 2 public + 2 private subnets across 2 AZs. 3) Create and attach an Internet Gateway. 4) Create a NAT Gateway in a public subnet with an Elastic IP. 5) Create public and private route tables; associate subnets; add `0.0.0.0/0` routes to IGW (public) and NAT (private). 6) Create 5 security groups (ALB, ECS, RDS, Lambda, EC2) with the rules in [04-Low-Level-Design.md](04-Low-Level-Design.md). |
| **Dependencies** | None — this is the foundation layer. |
| **Validation** | Confirm subnets show correct AZ/CIDR; confirm route tables show expected targets; confirm security groups exist with correct inbound rules. |
| **Troubleshooting** | If private-subnet resources cannot reach the internet, verify the NAT Gateway is in a *public* subnet and the private route table points to it, not to the IGW. |
| **Best Practices** | Keep data-tier and compute-tier resources in private subnets; never assign public IPs to RDS. |
| **Expected Output** | A VPC with 4 subnets, 1 IGW, 1 NAT Gateway, 2 route tables, and 5 security groups, all in `Available` state. |
| **Next Step** | Proceed to EC2 Setup. |

## 2. EC2 Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide an administrative host to initialize the RDS database schema. |
| **Prerequisites** | VPC and public subnet available; key pair created. |
| **Console Navigation** | EC2 Console → Instances → Launch Instance. |
| **Configuration Steps** | 1) Choose Amazon Linux 2023 AMI. 2) Select `t3.micro`. 3) Place in the public EC2 subnet. 4) Attach `EC2-SG-12`. 5) Assign/create key pair `<KEY_PAIR_NAME>`. 6) Launch. |
| **Dependencies** | VPC, public subnet, EC2 security group. |
| **Validation** | Instance state is `running`; can connect via SSH; can reach RDS on port 3306. |
| **Troubleshooting** | Connection timeouts usually indicate a missing inbound SSH rule or a route table misconfiguration. |
| **Best Practices** | Restrict SSH/MySQL inbound rules to a known administrator IP rather than `0.0.0.0/0` in production. |
| **Expected Output** | A running EC2 instance capable of connecting to RDS. |
| **Next Step** | Proceed to Application Load Balancer Setup (can be parallelized with RDS). |

## 3. Application Load Balancer Setup

| Field | Detail |
|---|---|
| **Purpose** | Serve as the internal HTTP entry point that routes traffic to ECS tasks. |
| **Prerequisites** | VPC with 2 public subnets across different AZs; ALB security group. |
| **Console Navigation** | EC2 Console → Load Balancers → Create Load Balancer → Application Load Balancer. |
| **Configuration Steps** | 1) Name `saas-ALB-12`, Internet-facing, IPv4. 2) Select both public subnets. 3) Attach `ALB-SG-12`. 4) Create target group `saas-TG-12` (Target type: IP, Protocol/Port HTTP:8080, health check path `/api/v1/health`). 5) Add HTTP:80 listener forwarding to the target group. |
| **Dependencies** | VPC, public subnets, ALB security group. |
| **Validation** | Load balancer state `Active`; target group shows healthy targets once ECS tasks register. |
| **Troubleshooting** | `Unhealthy` targets typically indicate the health-check path is wrong, the container port doesn't match, or the ECS security group doesn't allow the ALB security group on the target port. |
| **Best Practices** | Keep the health-check path lightweight and independent of downstream dependencies (e.g. don't require a DB call to succeed). |
| **Expected Output** | An `Active` ALB with DNS name `<ALB_DNS_NAME>` and an empty (not yet healthy) target group, ready for ECS registration. |
| **Next Step** | Proceed to RDS Database Setup. |

## 4. RDS Database Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide the relational data store for application and billing data. |
| **Prerequisites** | Private subnets across 2 AZs; RDS security group; KMS key (recommended before creation if using a custom key). |
| **Console Navigation** | RDS Console → Databases → Create Database. |
| **Configuration Steps** | 1) Engine: MySQL Community 8.4. 2) Instance class `db.t4g.micro`. 3) Storage: 400 GiB gp2. 4) VPC: `saas-VPC-12`; DB subnet group covering private subnets. 5) Security group: `RDS-SG-12`. 6) Set master username/password (store immediately in Secrets Manager). 7) Enable storage encryption with `saas-key-12`. 8) Disable public access. |
| **Dependencies** | VPC, private subnets, RDS security group, KMS key. |
| **Validation** | DB instance status `Available`; connect successfully from the EC2 bootstrap host on port 3306. |
| **Troubleshooting** | If connection fails from EC2, verify `RDS-SG-12` allows inbound 3306 from `EC2-SG-12`, and that both resources are in the same VPC. |
| **Best Practices** | Never expose RDS publicly; always enable encryption at rest; store credentials only in Secrets Manager. |
| **Expected Output** | An `Available` RDS instance with private endpoint `<RDS_ENDPOINT>`. |
| **Next Step** | From the EC2 host, connect via MySQL client and create the `saas_database` schema and required tables (including `tenant_usage`). Then proceed to IAM Setup. |

## 5. IAM Setup

| Field | Detail |
|---|---|
| **Purpose** | Grant each compute service only the permissions it needs to operate. |
| **Prerequisites** | Target resource ARNs known (RDS, KMS key, secret, SQS queue) or created iteratively alongside those services. |
| **Console Navigation** | IAM Console → Roles → Create Role. |
| **Configuration Steps** | Create three roles: 1) `tenant-saas-task-role` (trusted entity `ecs-tasks.amazonaws.com`) with Cognito, ECS, KMS, CloudWatch Logs, and Secrets Manager access plus inline policies for the specific KMS key and SQS queue. 2) `tenant-saas-metering-role-*` (trusted entity `lambda.amazonaws.com`) with Lambda VPC access, basic execution, and inline policies for the specific secret, KMS key, and SQS queue. 3) `ecsTaskExecutionRole` (trusted entity `ecs-tasks.amazonaws.com`) with `AmazonECSTaskExecutionRolePolicy`. |
| **Dependencies** | None to start (roles can be created before dependent resources exist by using placeholder ARNs, then tightened afterward). |
| **Validation** | Each role's trust policy shows the correct service principal; each role's permissions list matches [04-Low-Level-Design.md](04-Low-Level-Design.md). |
| **Troubleshooting** | `AccessDenied` errors at runtime usually mean an inline policy resource ARN doesn't exactly match the target resource. |
| **Best Practices** | Prefer narrow inline/customer-managed policies over broad AWS-managed policies where feasible (see Finding in LLD §5.1). |
| **Expected Output** | Three IAM roles ready to be attached to ECS task definitions and the Lambda function. |
| **Next Step** | Proceed to KMS Setup. |

## 6. KMS Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide a customer-managed encryption key for secrets and data. |
| **Prerequisites** | IAM roles that will need key access identified. |
| **Console Navigation** | KMS Console → Customer managed keys → Create key. |
| **Configuration Steps** | 1) Key type: Symmetric. 2) Alias: `saas-key-12`. 3) Key administrators: account root/admin. 4) Key usage permissions: grant `kms:Decrypt`, `kms:DescribeKey` to `tenant-saas-task-role` (and later the Lambda role). |
| **Dependencies** | IAM roles (can be added to the key policy after role creation). |
| **Validation** | Key status `Enabled`; key policy includes the expected principals. |
| **Troubleshooting** | If a service cannot decrypt, confirm the caller's IAM role appears in the key policy statement, not only in an IAM policy — KMS key policies are the final authority. |
| **Best Practices** | Enable automatic key rotation (currently disabled in this deployment — recommended improvement). |
| **Expected Output** | An enabled customer-managed KMS key, `<KMS_KEY_ARN>`. |
| **Next Step** | Proceed to Secrets Manager Setup. |

## 7. Secrets Manager Setup

| Field | Detail |
|---|---|
| **Purpose** | Securely store database credentials and the application secret key, retrievable only by authorized roles. |
| **Prerequisites** | RDS endpoint and credentials available; KMS key created. |
| **Console Navigation** | Secrets Manager Console → Store a new secret. |
| **Configuration Steps** | 1) Secret type: Other type of secret. 2) Key/value pairs: `db_username`, `db_password`, `engine`, `host`, `port`, `dbInstanceIdentifier`, `FLASK_SECRET_KEY`. 3) Encryption key: `saas-key-12`. 4) Name: `<SECRET_NAME>`. 5) Skip automatic rotation (or enable it — recommended). |
| **Dependencies** | RDS instance, KMS key. |
| **Validation** | Secret retrievable via `secretsmanager:GetSecretValue` from an authorized role; denied from unauthorized principals. |
| **Troubleshooting** | `AccessDeniedException` on retrieval usually indicates the caller's role is missing from both the IAM policy and, if a resource policy exists, the secret's resource policy. |
| **Best Practices** | Separate unrelated secrets (DB credentials vs. application signing key) into distinct Secrets Manager entries; enable rotation for database credentials. |
| **Expected Output** | A stored, encrypted secret at `<SECRET_ARN>`. |
| **Next Step** | Proceed to SQS Setup. |

## 8. SQS Setup

| Field | Detail |
|---|---|
| **Purpose** | Decouple usage-event publishing (ECS) from usage-event processing (Lambda). |
| **Prerequisites** | None beyond VPC/region selection. |
| **Console Navigation** | SQS Console → Create Queue. |
| **Configuration Steps** | 1) Type: Standard. 2) Name: `tenant-saas-usage`. 3) Visibility timeout: 1 minute. 4) Message retention: 4 days. 5) Encryption: SSE-SQS. 6) Access policy: allow the account root / relevant roles `SQS:*` or scoped actions as needed. |
| **Dependencies** | None. |
| **Validation** | Queue is visible and reachable; test message can be sent and received via the console "Send and receive messages" tool. |
| **Troubleshooting** | If messages are consumed but errors recur indefinitely, check whether a Dead Letter Queue is configured (currently it is not — recommended improvement). |
| **Best Practices** | Configure a DLQ with a redrive policy so poison messages don't loop forever. |
| **Expected Output** | An active queue at `<SQS_QUEUE_URL>`. |
| **Next Step** | Proceed to CloudFront Setup. |

## 9. CloudFront Setup

| Field | Detail |
|---|---|
| **Purpose** | Serve as the global, HTTPS public entry point for the application. |
| **Prerequisites** | API Gateway origin domain available (can be created after, then attached). |
| **Console Navigation** | CloudFront Console → Distributions → Create Distribution. |
| **Configuration Steps** | 1) Origin domain: API Gateway custom domain (`<API_GATEWAY_URL>`), origin path `/saas`, protocol HTTPS only. 2) Viewer protocol policy: Redirect HTTP to HTTPS. 3) Allowed methods: GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE. 4) Cache policy: CachingDisabled (dynamic API). 5) Compression: enabled. 6) Price class: all edge locations. |
| **Dependencies** | API Gateway (origin). |
| **Validation** | Distribution status `Enabled`; requests to `<CLOUDFRONT_DOMAIN>` are proxied through to the API Gateway origin. |
| **Troubleshooting** | 502/503 errors typically indicate the origin (API Gateway) is unreachable or the origin protocol policy doesn't match what API Gateway expects (HTTPS only). |
| **Best Practices** | Attach a WAF Web ACL and enable access logging (both currently disabled — recommended improvements). |
| **Expected Output** | An enabled CloudFront distribution at `<CLOUDFRONT_DOMAIN>`. |
| **Next Step** | Proceed to API Gateway Setup (if not already created as the CloudFront origin). |

## 10. API Gateway Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide a versioned, authorized REST API surface in front of the ALB. |
| **Prerequisites** | Cognito User Pool created (for authorizer); ALB DNS name available. |
| **Console Navigation** | API Gateway Console → Create API → REST API. |
| **Configuration Steps** | 1) Name: `rest-api-new-17`, Regional endpoint. 2) Create resource tree matching [04-Low-Level-Design.md §10.1](04-Low-Level-Design.md#101-resource-tree). 3) For each method, set integration type HTTP Proxy pointing to the ALB DNS name. 4) Create a Cognito User Pool authorizer and attach it to protected methods. 5) Deploy to stage `saas`. |
| **Dependencies** | Cognito User Pool, ALB. |
| **Troubleshooting** | `401 Unauthorized` responses indicate a missing/expired/invalid JWT, or an authorizer misconfigured with the wrong User Pool/App Client. |
| **Validation** | Invoke URL `<API_GATEWAY_URL>` responds; protected routes reject requests without a valid Cognito token and accept ones with a valid token. |
| **Best Practices** | Keep the API versioned under `/api/v1` to allow non-breaking evolution. |
| **Expected Output** | A deployed REST API at `<API_GATEWAY_URL>` proxying to the ALB. |
| **Next Step** | Attach this API as the CloudFront origin (§9), then proceed to Lambda Setup. |

## 11. Lambda Setup

| Field | Detail |
|---|---|
| **Purpose** | Asynchronously process usage events from SQS and persist billing records to RDS. |
| **Prerequisites** | Execution role, VPC private subnets, `saas-LAMBDA-billing-SG`, SQS queue, Secrets Manager secret. |
| **Console Navigation** | Lambda Console → Create Function. |
| **Configuration Steps** | 1) Runtime: Python 3.14. 2) Handler: `lambda_function.lambda_handler`. 3) Memory 128 MB, timeout 15 sec. 4) VPC: private subnets, `saas-LAMBDA-billing-SG`. 5) Execution role: `tenant-saas-metering-role-*`. 6) Add a Lambda Layer (`tenant-saas-pymysql`) built via the CMD packaging steps below. 7) Set environment variable `DB_SECRET_NAME`. 8) Add SQS trigger on `tenant-saas-usage`. |
| **CMD Layer Packaging (Prerequisite Sub-step)** | On a local Windows machine: `mkdir tenant-saas-pymysql` → `cd tenant-saas-pymysql` → `mkdir python` → `python -m pip install PyMySQL -t python` → `powershell Compress-Archive -Path python -DestinationPath tenant-saas-pymysql.zip`. Upload the resulting ZIP as a Lambda Layer. |
| **Dependencies** | IAM role, VPC/subnets/security group, SQS queue, Secrets Manager secret, Lambda layer. |
| **Validation** | Sending a test message to the SQS queue results in a new row in the `tenant_usage` RDS table; CloudWatch Logs show `Usage event processed`. |
| **Troubleshooting** | Timeouts often mean the Lambda is not in the correct private subnets or the security group doesn't allow egress to RDS on 3306. Import errors for `pymysql` mean the layer wasn't attached or built for the wrong architecture. |
| **Best Practices** | Cache the Secrets Manager response across invocations (already implemented) to reduce API calls and cold-start latency. |
| **Expected Output** | An active Lambda function successfully draining the SQS queue into RDS. |
| **Next Step** | Proceed to ECR Setup. |

## 12. ECR Setup

| Field | Detail |
|---|---|
| **Purpose** | Store the Docker image for the Flask application. |
| **Prerequisites** | None beyond account/region. |
| **Console Navigation** | ECR Console → Repositories → Create Repository. |
| **Configuration Steps** | 1) Name: `saas`. 2) Visibility: Private. 3) Tag mutability: Mutable. 4) Encryption: KMS. |
| **Dependencies** | None. |
| **Validation** | Repository visible in console; `docker push` succeeds after authentication. |
| **Troubleshooting** | `no basic auth credentials` errors mean `aws ecr get-login-password` wasn't piped into `docker login` correctly. |
| **Best Practices** | Enable scan-on-push and a lifecycle policy to remove stale images (currently not configured — recommended improvement). |
| **Expected Output** | An empty, active ECR repository ready to receive an image. |
| **Next Step** | Proceed to ECS Setup (task definition can be created before the image is pushed, then updated). |

## 13. ECS Setup

| Field | Detail |
|---|---|
| **Purpose** | Run the containerized Flask application. |
| **Prerequisites** | ECR repository, private subnet, `ECS-SG-12`, `tenant-saas-task-role`, `ecsTaskExecutionRole`, ALB target group. |
| **Console Navigation** | ECS Console → Clusters → Create Cluster (Fargate). |
| **Configuration Steps** | 1) Cluster: `saas-cluster-13`. 2) Task definition `saas-task-family-13`: Fargate, 1 vCPU / 3 GB, container `saas-container-13` on port 8080, image from ECR, task role + execution role attached, environment variables set (see LLD §13.1), CloudWatch log configuration to `/ecs/saas-task-family-13`. 3) Service `saas-task-family-20-service`: desired count 1, private subnet, `ECS-SG-12`, attached to ALB target group `saas-TG-12`. |
| **Dependencies** | ECR image, IAM roles, VPC/subnet/security group, ALB target group, Secrets Manager (for credential values). |
| **Validation** | Task reaches `RUNNING`; ALB target group shows the task as `healthy`; `/api/v1/health` returns success through the full CloudFront → API Gateway → ALB → ECS path. |
| **Troubleshooting** | Tasks stuck in `PENDING` often indicate the container can't pull the image (execution role or ECR permissions) or can't start (missing env var causing app crash — check CloudWatch Logs). |
| **Best Practices** | Configure Service Auto Scaling based on CPU/memory or ALB request count for production readiness (not currently configured). |
| **Expected Output** | 1/1 tasks running and registered healthy behind the ALB. |
| **Next Step** | Proceed to CloudShell build & push (if the image has not yet been built), then CloudWatch Setup. |

## 14. CloudShell Build & Push

| Field | Detail |
|---|---|
| **Purpose** | Build the Docker image and push it to ECR using a browser-based CLI environment. |
| **Prerequisites** | Application source packaged as a ZIP file; ECR repository created. |
| **Console Navigation** | AWS Console → CloudShell icon (top navigation bar). |
| **Configuration Steps** | 1) Actions → Upload file → upload the application ZIP. 2) `unzip <archive>.zip && cd <project-folder>`. 3) `docker build -t tenant-saas-app .`. 4) `aws ecr get-login-password --region <AWS_REGION> \| docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com`. 5) `docker tag tenant-saas-app:latest <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/saas:latest`. 6) `docker push <AWS_ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/saas:latest`. |
| **Dependencies** | ECR repository, Docker support in CloudShell. |
| **Validation** | Image appears in the ECR repository with the expected tag and digest. |
| **Troubleshooting** | Build failures usually trace back to a missing `Dockerfile` or dependency issue in the uploaded ZIP; re-check `docker build` output. |
| **Best Practices** | Consider replacing this manual process with an automated pipeline (CodeBuild/CodePipeline or GitHub Actions) for repeatable deployments. |
| **Expected Output** | A pushed image ready for ECS to deploy. |
| **Next Step** | Update/redeploy the ECS service to pick up the new image, then proceed to CloudWatch Setup. |

## 15. CloudWatch Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide centralized dashboards and logs across all platform services. |
| **Prerequisites** | Services already deployed (ECS, Lambda, RDS, ALB, API Gateway, CloudFront). |
| **Console Navigation** | CloudWatch Console → Dashboards → Create Dashboard. |
| **Configuration Steps** | 1) Create dashboard `tenant-saas-app-monitoring`. 2) Add widgets for ALB (RequestCount, TargetResponseTime, ActiveConnectionCount), RDS (FreeStorageSpace, CPUUtilization, DatabaseConnections), API Gateway (Count, Latency, 4XXError, 5XXError), ECS (CPUUtilization, MemoryUtilization), Lambda (Duration, Invocations, Errors), CloudFront (Requests, 4XXErrorRate, 5XXErrorRate, BytesDownloaded). 3) Enable Container Insights on the ECS cluster. 4) Confirm log groups `/ecs/saas-task-family-13` and `/aws/lambda/tenant-saas-metering` are receiving logs, with 30-day retention. |
| **Dependencies** | All monitored services must already be deployed and emitting metrics. |
| **Validation** | Dashboard renders live data; log groups show recent log streams. |
| **Troubleshooting** | Missing metrics usually mean the service hasn't generated traffic yet, or Container Insights wasn't enabled before task launch. |
| **Best Practices** | Add CloudWatch Alarms with SNS notifications for key thresholds (currently no alarms configured — recommended improvement). |
| **Expected Output** | A populated monitoring dashboard and active log groups. |
| **Next Step** | Proceed to Billing and Cost Management Setup. |

## 16. Billing and Cost Management Setup

| Field | Detail |
|---|---|
| **Purpose** | Control and monitor AWS spend for the project. |
| **Prerequisites** | Billing console access enabled for the account. |
| **Console Navigation** | Billing and Cost Management Console → Budgets → Create Budget. |
| **Configuration Steps** | 1) Type: Cost budget. 2) Name: `tenant-saas-monthly-budget`. 3) Amount: $50.00, Monthly. 4) Alerts: Actual cost > 50%, Forecasted cost > 80%, Actual cost > 80%, Actual cost > 100%. 5) Enable email notifications. |
| **Dependencies** | None. |
| **Validation** | Budget appears in the Budgets list with correct thresholds; test notification email received (optional). |
| **Troubleshooting** | If alerts don't fire, confirm the notification email/subscription was confirmed and thresholds are saved correctly. |
| **Best Practices** | Review AWS Cost Explorer regularly and tag resources consistently (e.g. `Project=SaaS-Platform`) for clearer cost attribution. |
| **Expected Output** | An active budget tracking monthly spend with alerting configured. |
| **Next Step** | Proceed to Cognito Setup. |

## 17. Cognito Setup

| Field | Detail |
|---|---|
| **Purpose** | Provide centralized authentication and tenant-based authorization. |
| **Prerequisites** | CloudFront domain known (for callback/redirect URLs). |
| **Console Navigation** | Cognito Console → User Pools → Create User Pool. |
| **Configuration Steps** | 1) Sign-in options: Email, Username. 2) Password policy: min 8 chars, requires number/special/upper/lower, temp password expiry 7 days. 3) App client: `saas-SPA-cognito-12`, type SPA, OAuth Authorization Code Grant, scopes `openid`, `email`, `profile`, `aws.cognito.signin.user.admin`. 4) Configure Hosted UI domain. 5) Set callback URL `<CLOUDFRONT_DOMAIN>/auth/callback`, redirect URL `<CLOUDFRONT_DOMAIN>/auth/callback`, sign-out URL `<CLOUDFRONT_DOMAIN>/`. 6) Create user groups: `TenantA_admin`, `TenantA_user`, `TenantB_admin`, `TenantB_user`. |
| **Dependencies** | CloudFront distribution domain. |
| **Validation** | Hosted UI login page loads; successful login redirects to `/auth/callback` with an authorization code; token exchange returns a valid JWT verifiable against the published JWKS. |
| **Troubleshooting** | `redirect_mismatch` errors mean the callback URL configured in Cognito doesn't exactly match the one requested by the app. |
| **Best Practices** | Enable MFA, particularly for `*_admin` groups (currently not enabled — recommended improvement). |
| **Expected Output** | A running Cognito User Pool issuing valid JWTs for authenticated tenant users. |
| **Next Step** | End-to-end validation: log in via Cognito, confirm access through CloudFront → API Gateway → ALB → ECS, and confirm a usage event flows through SQS → Lambda → RDS. |

## 18. Conclusion

Following these seventeen procedures in sequence reproduces the full platform from an empty AWS account to a running, authenticated, monitored, cost-governed multi-tenant SaaS deployment.

## 19. Appendix

### 19.1 Recommended Improvements Summary

| Area | Recommendation |
|---|---|
| EC2 security group | Restrict SSH/MySQL to a known admin IP |
| IAM | Replace broad managed policies with narrowly scoped custom policies |
| KMS | Enable automatic key rotation |
| Secrets Manager | Enable rotation; split unrelated secrets |
| SQS | Add a Dead Letter Queue |
| CloudFront | Enable WAF and access logging |
| ECR | Enable scan-on-push and a lifecycle policy |
| ECS | Use native `secrets` injection instead of plaintext env vars; add Auto Scaling |
| CloudWatch | Add Alarms + SNS notifications |
| Cognito | Enable MFA for admin groups |
| CI/CD | Automate the CloudShell build/push steps with a pipeline |
