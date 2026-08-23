# 🚀 Deployment Guide / Standard Operating Procedure (SOP)

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Deployment Guide / SOP |
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

> This SOP follows the **actual deployment sequence** used to build the platform, in AWS Console order, and is written as a step-by-step deployment manual. Every value shown is a placeholder — substitute your own account-specific values when executing these steps.

---

## Table of Contents

1. [Step 1: VPC Setup](#step-1-vpc-setup)
2. [Step 2: EC2 Setup](#step-2-ec2-setup)
3. [Step 3: Application Load Balancer Setup](#step-3-application-load-balancer-setup)
4. [Step 4: RDS Database Setup](#step-4-rds-database-setup)
5. [Step 5: IAM Setup](#step-5-iam-setup)
6. [Step 6: KMS Setup](#step-6-kms-setup)
7. [Step 7: Secrets Manager Setup](#step-7-secrets-manager-setup)
8. [Step 8: SQS Setup](#step-8-sqs-setup)
9. [Step 9: CloudFront Setup](#step-9-cloudfront-setup)
10. [Step 10: API Gateway Setup](#step-10-api-gateway-setup)
11. [Step 11: Lambda Setup](#step-11-lambda-setup)
12. [Step 12: ECR Setup](#step-12-ecr-setup)
13. [Step 13: ECS Setup](#step-13-ecs-setup)
14. [Step 14: CloudShell Build & Push](#step-14-cloudshell-build--push)
15. [Step 15: CloudWatch Setup](#step-15-cloudwatch-setup)
16. [Step 16: Billing and Cost Management Setup](#step-16-billing-and-cost-management-setup)
17. [Step 17: Cognito Setup](#step-17-cognito-setup)
18. [Conclusion](#18-conclusion)
19. [Appendix](#19-appendix)

---

## Step 1: VPC Setup

**Purpose**
Provide an isolated network foundation with public and private subnets for the SaaS platform, so every downstream service has a controlled place to live.

**AWS Console Navigation**
VPC Console → Your VPCs → Create VPC.

**Configuration**
1. Create a VPC with CIDR block `10.0.0.0/24`.
2. Create 2 public subnets and 2 private subnets, spread across 2 Availability Zones.
3. Create an Internet Gateway and attach it to the VPC.
4. Create a NAT Gateway in a public subnet with an Elastic IP attached.
5. Create a public route table (route `0.0.0.0/0 → IGW`) and associate it with both public subnets.
6. Create a private route table (route `0.0.0.0/0 → NAT Gateway`) and associate it with both private subnets.
7. Create 5 security groups — ALB, ECS, RDS, Lambda, and EC2 — with the rules documented in [04-Low-Level-Design.md §1.4](04-Low-Level-Design.md#14-security-groups).

**Validation**
- Subnets show the correct AZ and CIDR block.
- Route tables show the expected target (IGW for public, NAT for private).
- All 5 security groups exist with the correct inbound rules.

**Expected Result**
A VPC with 4 subnets, 1 Internet Gateway, 1 NAT Gateway, 2 route tables, and 5 security groups, all in an `Available` state.

**Best Practice**
Keep data-tier and compute-tier resources in private subnets; never assign a public IP to RDS.

**Troubleshooting**
If resources in a private subnet cannot reach the internet, confirm the NAT Gateway sits in a *public* subnet and that the private route table points to the NAT Gateway, not the Internet Gateway.

**Warnings**
⚠️ The current `EC2-SG-12` security group allows SSH (22) and MySQL (3306) inbound from `0.0.0.0/0`. This should be restricted to a known administrator IP range before this is treated as production-ready — see [07-Security-Architecture.md §7](07-Security-Architecture.md#7-security-findings-and-recommendations).

---

## Step 2: EC2 Setup

**Purpose**
Provide an administrative host used to bootstrap and manage the RDS database schema.

**AWS Console Navigation**
EC2 Console → Instances → Launch Instance.

**Configuration**
1. Choose the Amazon Linux 2023 AMI.
2. Select instance type `t3.micro`.
3. Place the instance in the public EC2 subnet (`saas-public-sub2-EC2-azb`).
4. Attach the `EC2-SG-12` security group.
5. Create or select the key pair `<KEY_PAIR_NAME>`.
6. Launch the instance.

**Validation**
- Instance state shows `running`.
- SSH connection succeeds using the key pair.
- The instance can reach RDS on port 3306 once RDS is available (Step 4).

**Expected Result**
A running EC2 instance capable of connecting to the RDS database for schema bootstrap.

**Best Practice**
Use this instance only for administrative database tasks — it is not part of the live application request path.

**Troubleshooting**
Connection timeouts typically point to a missing inbound SSH rule or an incorrect route table association.

**Warnings**
⚠️ Restrict SSH/MySQL inbound access to a specific administrator IP instead of `0.0.0.0/0` for any environment beyond a personal learning project.

---

## Step 3: Application Load Balancer Setup

**Purpose**
Serve as the internal HTTP entry point that routes traffic from API Gateway to the ECS-hosted Flask application.

**AWS Console Navigation**
EC2 Console → Load Balancers → Create Load Balancer → Application Load Balancer.

**Configuration**
1. Name the load balancer `saas-ALB-12`; scheme Internet-facing; IP address type IPv4.
2. Select both public subnets (`saas-public-sub1-ALB-aza`, `saas-public-sub2-EC2-azb`).
3. Attach the `ALB-SG-12` security group.
4. Create target group `saas-TG-12` (Target type: IP, Protocol/Port: HTTP:8080, health check path `/api/v1/health`).
5. Add an HTTP:80 listener forwarding to `saas-TG-12`.

**Validation**
- Load balancer state is `Active`.
- Target group shows healthy targets once ECS tasks register in Step 13.

**Expected Result**
An `Active` ALB reachable at `<ALB_DNS_NAME>`, with an empty (not yet healthy) target group ready for ECS registration.

**Best Practice**
Keep the health-check path lightweight and independent of downstream dependencies — it should not require a database call to succeed.

**Troubleshooting**
`Unhealthy` targets usually mean the health-check path is wrong, the container port doesn't match, or `ECS-SG-12` doesn't allow inbound traffic from `ALB-SG-12` on the target port.

---

## Step 4: RDS Database Setup

**Purpose**
Provide the relational data store for both application data and tenant usage records.

**AWS Console Navigation**
RDS Console → Databases → Create Database.

**Configuration**
1. Engine: MySQL Community 8.4.
2. Instance class: `db.t4g.micro`.
3. Storage: General Purpose SSD (gp2), 400 GiB allocated.
4. VPC: `saas-VPC-12`; DB subnet group covering the two private subnets.
5. Security group: `RDS-SG-12`.
6. Set the master username/password, then store them immediately in Secrets Manager (Step 7).
7. Enable storage encryption using KMS key `saas-key-12` (created in Step 6).
8. Disable public access.

**Validation**
- DB instance status reaches `Available`.
- A successful MySQL connection can be made from the EC2 bootstrap host on port 3306.

**Expected Result**
An `Available` RDS instance reachable only privately at `<RDS_ENDPOINT>`.

**Best Practice**
Never expose RDS publicly; always enable encryption at rest; store credentials only in Secrets Manager, never in application code.

**Troubleshooting**
If the EC2 host cannot connect, confirm `RDS-SG-12` allows inbound port 3306 from `EC2-SG-12`, and that both resources sit in the same VPC.

**Warnings**
⚠️ 400 GiB of allocated storage is significantly larger than this workload currently needs and is the single largest driver of estimated monthly cost — see [10-Cost-Estimation.md §4](10-Cost-Estimation.md#4-primary-cost-drivers). Consider a smaller allocation with storage autoscaling enabled instead.

**Next sub-step:** From the EC2 host, connect via a MySQL client and create the `saas_database` schema along with the required application tables and the `tenant_usage` table used by the billing pipeline (Step 11).

---

## Step 5: IAM Setup

**Purpose**
Grant each compute service only the permissions it needs to operate — no more, no less.

**AWS Console Navigation**
IAM Console → Roles → Create Role.

**Configuration**
Create three roles:
1. **`tenant-saas-task-role`** — trusted entity `ecs-tasks.amazonaws.com`. Attach `AmazonCognitoPowerUser`, `AmazonEC2ContainerServiceRole`, `AWSKeyManagementServicePowerUser`, `CloudWatchLogsFullAccess`, `SecretsManagerReadWrite`, plus inline policies scoping KMS actions to `<KMS_KEY_ARN>` and `sqs:SendMessage` to `<SQS_QUEUE_ARN>`.
2. **`tenant-saas-metering-role-<IAM_ROLE_SUFFIX>`** — trusted entity `lambda.amazonaws.com`. Attach `AWSLambdaVPCAccessExecutionRole` and a customer-managed basic execution policy, plus inline policies scoping `secretsmanager:GetSecretValue` to the RDS secret, `kms:Decrypt` to `<KMS_KEY_ARN>`, and SQS consume actions to `<SQS_QUEUE_ARN>`.
3. **`ecsTaskExecutionRole`** — trusted entity `ecs-tasks.amazonaws.com`. Attach `AmazonECSTaskExecutionRolePolicy`.

**Validation**
- Each role's trust policy shows the correct service principal.
- Each role's attached permissions match [04-Low-Level-Design.md §5](04-Low-Level-Design.md#5-iam-roles-and-policies).

**Expected Result**
Three IAM roles ready to be attached to the ECS task definition (Step 13) and the Lambda function (Step 11).

**Best Practice**
Prefer narrowly scoped custom policies over broad AWS-managed policies wherever feasible.

**Troubleshooting**
`AccessDenied` errors at runtime almost always trace back to an inline policy's resource ARN not exactly matching the target resource.

**Warnings**
⚠️ `tenant-saas-task-role` currently attaches broad AWS-managed policies (`SecretsManagerReadWrite`, `AWSKeyManagementServicePowerUser`) that exceed its actual need. Recommend replacing these with custom least-privilege policies scoped to the specific secret and key ARNs.

---

## Step 6: KMS Setup

**Purpose**
Provide a customer-managed encryption key to protect secrets and, where configured, data at rest.

**AWS Console Navigation**
KMS Console → Customer managed keys → Create key.

**Configuration**
1. Key type: Symmetric.
2. Alias: `saas-key-12`.
3. Key administrators: account root/admin.
4. Key usage permissions: grant `kms:Decrypt` and `kms:DescribeKey` to `tenant-saas-task-role` (add the Lambda role's equivalent permission after Step 5's Lambda role exists).

**Validation**
- Key status shows `Enabled`.
- The key policy lists the expected IAM role principals.

**Expected Result**
An enabled customer-managed KMS key at `<KMS_KEY_ARN>`.

**Best Practice**
Enable automatic annual key rotation.

**Troubleshooting**
If a service cannot decrypt data it should be able to, confirm the caller's IAM role appears directly in the **key policy**, not only in an IAM policy — KMS key policies are the final authority on key access.

**Warnings**
⚠️ Automatic key rotation is currently **disabled** on `saas-key-12`. Recommend enabling rotation.

---

## Step 7: Secrets Manager Setup

**Purpose**
Securely store database credentials and the application secret key so they never appear in source code or plaintext configuration.

**AWS Console Navigation**
Secrets Manager Console → Store a new secret.

**Configuration**
1. Secret type: Other type of secret.
2. Key/value pairs: `db_username`, `db_password`, `engine`, `host`, `port`, `dbInstanceIdentifier`, `FLASK_SECRET_KEY`.
3. Encryption key: `saas-key-12` (from Step 6).
4. Name the secret `<RDS_SECRET_NAME>`.
5. Skip automatic rotation for now (or enable it — recommended).

**Validation**
- The secret is retrievable via `secretsmanager:GetSecretValue` from an authorized role (`tenant-saas-task-role`, the Lambda metering role).
- Retrieval is denied for any unauthorized principal.

**Expected Result**
A stored, KMS-encrypted secret at `arn:aws:secretsmanager:<AWS_REGION>:<ACCOUNT_ID>:secret:<RDS_SECRET_NAME>`.

**Best Practice**
Separate unrelated secrets — the database credential and the unrelated `FLASK_SECRET_KEY` — into distinct Secrets Manager entries.

**Troubleshooting**
An `AccessDeniedException` on retrieval usually means the caller's role is missing from the IAM policy and/or a resource policy attached to the secret.

**Warnings**
⚠️ Rotation is currently disabled. Recommend enabling automatic rotation for the database credential portion of this secret.

---

## Step 8: SQS Setup

**Purpose**
Decouple usage-event publishing (ECS) from usage-event processing (Lambda), so billing never blocks the user-facing request path.

**AWS Console Navigation**
SQS Console → Create Queue.

**Configuration**
1. Type: Standard.
2. Name: `tenant-saas-usage`.
3. Visibility timeout: 1 minute.
4. Message retention: 4 days.
5. Encryption: SSE-SQS (Amazon SQS managed key).
6. Access policy: allow the relevant IAM roles to send/receive as scoped in Step 5.

**Validation**
- The queue is visible in the console and reachable.
- A test message can be sent and received using the console's "Send and receive messages" tool.

**Expected Result**
An active queue at `<SQS_QUEUE_URL>`.

**Best Practice**
Configure a Dead Letter Queue (DLQ) with a redrive policy so a message that repeatedly fails processing doesn't loop forever.

**Troubleshooting**
If the same message is processed and fails indefinitely, check whether a DLQ is configured — it currently is not.

**Warnings**
⚠️ No Dead Letter Queue is configured for `tenant-saas-usage`. Failed usage events beyond Lambda's retry limit will currently be dropped silently.

---

## Step 9: CloudFront Setup

**Purpose**
Serve as the global, HTTPS public entry point for the application.

**AWS Console Navigation**
CloudFront Console → Distributions → Create Distribution.

**Configuration**
1. Origin domain: the API Gateway invoke URL created in Step 10 (`<API_GATEWAY_URL>`), origin path `/saas`, protocol HTTPS only.
2. Viewer protocol policy: Redirect HTTP to HTTPS.
3. Allowed methods: GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE.
4. Cache policy: CachingDisabled (the origin is a dynamic API).
5. Compression: enabled.
6. Price class: Use all edge locations.

**Validation**
- Distribution status shows `Enabled`.
- Requests to `<CLOUDFRONT_DOMAIN>` are correctly proxied through to the API Gateway origin.

**Expected Result**
An enabled CloudFront distribution at `<CLOUDFRONT_DOMAIN>`.

**Best Practice**
Attach an AWS WAF Web ACL and enable access logging to an S3 bucket.

**Troubleshooting**
502/503 errors typically mean the origin (API Gateway) is unreachable, or the origin protocol policy doesn't match what API Gateway expects (HTTPS only).

**Warnings**
⚠️ AWS WAF is currently **disabled** on this distribution, and access logging is currently **disabled**. Both are recommended before wider exposure — see [07-Security-Architecture.md §6](07-Security-Architecture.md#6-edge-security).

---

## Step 10: API Gateway Setup

**Purpose**
Provide a versioned, JWT-authorized REST API surface in front of the Application Load Balancer.

**AWS Console Navigation**
API Gateway Console → Create API → REST API.

**Configuration**
1. Name: `rest-api-new-17`; Endpoint type: Regional.
2. Build the resource tree matching [04-Low-Level-Design.md §10.1](04-Low-Level-Design.md#101-resource-tree).
3. For each method, set the integration type to HTTP Proxy pointing to `<ALB_DNS_NAME>`.
4. Create a Cognito User Pool authorizer (using the pool from Step 17) and attach it to every protected method.
5. Deploy the API to a stage named `saas`.

**Validation**
- The invoke URL `<API_GATEWAY_URL>` responds successfully.
- Protected routes reject requests without a valid Cognito token and accept requests carrying a valid token.

**Expected Result**
A deployed REST API at `<API_GATEWAY_URL>` proxying authorized requests through to the ALB.

**Best Practice**
Keep the API versioned under `/api/v1` so future changes can be introduced without breaking existing clients.

**Troubleshooting**
`401 Unauthorized` responses indicate a missing, expired, or invalid JWT, or an authorizer configured against the wrong User Pool / App Client.

---

## Step 11: Lambda Setup

**Purpose**
Asynchronously process usage events pulled from SQS and persist billing records into the RDS `tenant_usage` table.

**AWS Console Navigation**
Lambda Console → Create Function.

**Configuration**
1. Runtime: Python 3.14; Handler: `lambda_function.lambda_handler`.
2. Memory: 128 MB; Timeout: 15 seconds.
3. VPC: both private subnets; Security group: `saas-LAMBDA-billing-SG`.
4. Execution role: `tenant-saas-metering-role-<IAM_ROLE_SUFFIX>` (from Step 5).
5. Attach a Lambda Layer named `tenant-saas-pymysql`, built as follows on a local machine:
   - `mkdir tenant-saas-pymysql && cd tenant-saas-pymysql`
   - `mkdir python`
   - `python -m pip install PyMySQL -t python`
   - `powershell Compress-Archive -Path python -DestinationPath tenant-saas-pymysql.zip`
   - Upload the resulting ZIP as a new Lambda Layer version.
6. Set the environment variable `DB_SECRET_NAME` to `<RDS_SECRET_NAME>`.
7. Add an SQS trigger on the `tenant-saas-usage` queue (from Step 8), enabled.

**Validation**
- Sending a test message to the SQS queue results in a new row in the `tenant_usage` table in RDS.
- CloudWatch Logs for `/aws/lambda/tenant-saas-metering` show `Usage event processed`.

**Expected Result**
An active Lambda function that reliably drains the SQS queue into RDS.

**Best Practice**
Cache the Secrets Manager response across warm invocations (already implemented in the function code) to reduce API calls and cold-start latency.

**Troubleshooting**
Timeouts usually mean the function is not deployed in the correct private subnets, or the security group doesn't allow egress to RDS on port 3306. Import errors for `pymysql` mean the layer wasn't attached or was built for the wrong architecture.

---

## Step 12: ECR Setup

**Purpose**
Store the Docker image for the Flask application so ECS can pull it during deployment.

**AWS Console Navigation**
ECR Console → Repositories → Create Repository.

**Configuration**
1. Name: `saas`.
2. Visibility: Private.
3. Tag mutability: Mutable.
4. Encryption type: KMS.

**Validation**
- The repository is visible in the console.
- `docker push` succeeds after ECR authentication.

**Expected Result**
An empty, active ECR repository ready to receive an image.

**Best Practice**
Enable scan-on-push and configure a lifecycle policy to remove stale, untagged images.

**Troubleshooting**
`no basic auth credentials` errors mean `aws ecr get-login-password` was not correctly piped into `docker login`.

**Warnings**
⚠️ Scan-on-push is currently disabled and no lifecycle policy is configured. Recommend enabling both.

---

## Step 13: ECS Setup

**Purpose**
Run the containerized Flask application as a managed, load-balanced service.

**AWS Console Navigation**
ECS Console → Clusters → Create Cluster (Fargate).

**Configuration**
1. Cluster: `saas-cluster-13`, launch type AWS Fargate.
2. Task definition `saas-task-family-13`: 1 vCPU / 3 GB memory; container `saas-container-13` on port 8080; image from the ECR repository built in Step 14; task role `tenant-saas-task-role` and execution role `ecsTaskExecutionRole` attached; environment variables set per [04-Low-Level-Design.md §13.1](04-Low-Level-Design.md#131-environment-variables-names-only--values-redacted); CloudWatch log configuration pointed at `/ecs/saas-task-family-13`.
3. Service `saas-task-family-20-service`: desired count 1; private subnet `saas-private-sub2-ECS-aza`; security group `ECS-SG-12`; attached to ALB target group `saas-TG-12` (from Step 3).

**Validation**
- The task reaches `RUNNING` state.
- The ALB target group reports the task as `healthy`.
- `/api/v1/health` returns a successful response through the full CloudFront → API Gateway → ALB → ECS path.

**Expected Result**
1/1 desired tasks running and registered healthy behind the ALB.

**Best Practice**
Configure ECS Service Auto Scaling based on CPU/memory or ALB request count once traffic patterns are understood.

**Troubleshooting**
Tasks stuck in `PENDING` usually mean the container can't pull the image (check execution role / ECR permissions) or the container is crashing on startup (check CloudWatch Logs for a missing environment variable).

**Warnings**
⚠️ `DB_PASSWORD` and `FLASK_SECRET_KEY` are currently injected as plaintext ECS task environment variables in addition to being stored in Secrets Manager. Recommend switching to native ECS `secrets` injection (referencing the Secrets Manager ARN directly) so these values never appear in the task definition JSON.
⚠️ ECS Service Auto Scaling is not currently configured.

---

## Step 14: CloudShell Build & Push

**Purpose**
Build the application's Docker image and push it to ECR using a browser-based CLI environment, ahead of Step 13's ECS deployment.

**AWS Console Navigation**
AWS Console → CloudShell icon (top navigation bar).

**Configuration**
1. Actions → Upload file → upload the application source ZIP.
2. `unzip <archive>.zip && cd <project-folder>`
3. `docker build -t tenant-saas-app .`
4. `aws ecr get-login-password --region <AWS_REGION> | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com`
5. `docker tag tenant-saas-app:latest <ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/saas:latest`
6. `docker push <ACCOUNT_ID>.dkr.ecr.<AWS_REGION>.amazonaws.com/saas:latest`

**Validation**
The pushed image appears in the ECR repository (Step 12) with the expected tag and digest.

**Expected Result**
An image available in ECR, ready for ECS to deploy or redeploy.

**Best Practice**
Consider replacing this manual process with an automated pipeline (CodeBuild/CodePipeline or a GitHub Actions workflow) for repeatable deployments.

**Troubleshooting**
Build failures usually trace back to a missing `Dockerfile` or a dependency issue in the uploaded ZIP — check the `docker build` output.

---

## Step 15: CloudWatch Setup

**Purpose**
Provide centralized dashboards and logs across every service in the platform.

**AWS Console Navigation**
CloudWatch Console → Dashboards → Create Dashboard.

**Configuration**
1. Create dashboard `tenant-saas-app-monitoring`.
2. Add widgets for ALB (`RequestCount`, `TargetResponseTime`, `ActiveConnectionCount`), RDS (`FreeStorageSpace`, `CPUUtilization`, `DatabaseConnections`), API Gateway (`Count`, `Latency`, `4XXError`, `5XXError`), ECS (`CPUUtilization`, `MemoryUtilization`), Lambda (`Duration`, `Invocations`, `Errors`), and CloudFront (`Requests`, `4XXErrorRate`, `5XXErrorRate`, `BytesDownloaded`).
3. Enable Container Insights on the `saas-cluster-13` ECS cluster.
4. Confirm the log groups `/ecs/saas-task-family-13` and `/aws/lambda/tenant-saas-metering` are receiving log streams with 30-day retention.

**Validation**
- The dashboard renders live data for every widget.
- Both log groups show recent log streams.

**Expected Result**
A populated monitoring dashboard and two active log groups.

**Best Practice**
Add CloudWatch Alarms with SNS notifications on key thresholds (error rates, RDS free storage, ECS CPU/memory).

**Troubleshooting**
Missing metrics usually mean the service hasn't generated traffic yet, or Container Insights was enabled after tasks had already launched.

**Warnings**
⚠️ No CloudWatch Alarms are currently configured — issues are only visible when someone actively views the dashboard. See [08-Monitoring-and-Logging.md §7](08-Monitoring-and-Logging.md#7-gaps-and-recommendations).

---

## Step 16: Billing and Cost Management Setup

**Purpose**
Control and monitor AWS spend for the project.

**AWS Console Navigation**
Billing and Cost Management Console → Budgets → Create Budget.

**Configuration**
1. Type: Cost budget; Name: `tenant-saas-monthly-budget`.
2. Amount: $50.00, Monthly.
3. Alerts: Actual cost > 50%, Forecasted cost > 80%, Actual cost > 80%, Actual cost > 100%.
4. Enable email notifications.

**Validation**
The budget appears in the Budgets list with the correct amount and thresholds.

**Expected Result**
An active budget tracking monthly spend with alerting configured.

**Best Practice**
Review AWS Cost Explorer regularly and tag resources consistently (e.g. `Project=SaaS-Platform`) for clearer cost attribution.

**Troubleshooting**
If alerts don't fire as expected, confirm the notification email/subscription was confirmed and the thresholds were saved correctly.

**Warnings**
⚠️ Based on the resource sizes actually configured in Steps 1–15, estimated real spend is likely to exceed this $50 budget significantly — see [10-Cost-Estimation.md §3](10-Cost-Estimation.md#3-budget-vs-estimated-spend). Review that document before assuming this budget reflects real usage.

---

## Step 17: Cognito Setup

**Purpose**
Provide centralized authentication and tenant-based authorization for the platform.

**AWS Console Navigation**
Cognito Console → User Pools → Create User Pool.

**Configuration**
1. Sign-in options: Email, Username.
2. Password policy: minimum 8 characters, requires a number, a special character, an uppercase letter, and a lowercase letter; temporary passwords expire after 7 days.
3. App client: `saas-SPA-cognito-12`, type Single-Page Application (SPA); OAuth flow: Authorization Code Grant; scopes: `openid`, `email`, `profile`, `aws.cognito.signin.user.admin`.
4. Configure a Hosted UI domain.
5. Set callback URL `<CLOUDFRONT_DOMAIN>/auth/callback`, redirect URL `<CLOUDFRONT_DOMAIN>/auth/callback`, sign-out URL `<CLOUDFRONT_DOMAIN>/`.
6. Create user groups: `TenantA_admin`, `TenantA_user`, `TenantB_admin`, `TenantB_user`.

**Validation**
- The Hosted UI login page loads correctly.
- A successful login redirects to `/auth/callback` with an authorization code.
- Token exchange returns a valid JWT that verifies against the published JWKS endpoint.

**Expected Result**
A running Cognito User Pool issuing valid JWTs for authenticated tenant users, usable by API Gateway's authorizer (configured in Step 10).

**Best Practice**
Require MFA, at minimum for the `*_admin` groups.

**Troubleshooting**
`redirect_mismatch` errors mean the callback URL configured in Cognito doesn't exactly match the one the application requested.

**Warnings**
⚠️ MFA is not currently enabled for any user group. Recommend enabling it for `TenantA_admin` and `TenantB_admin` at minimum.

**Final validation (all steps):** Log in via Cognito, confirm access through the full CloudFront → API Gateway → ALB → ECS path, and confirm a usage event flows end-to-end through SQS → Lambda → RDS.

---

## 18. Conclusion

Following Steps 1 through 17 in sequence reproduces the full platform from an empty AWS account to a running, authenticated, monitored, cost-governed multi-tenant SaaS deployment. Every step lists the warnings and best-practice gaps identified during the documentation review, so they can be tracked and addressed without changing the core architecture.

## 19. Appendix

### 19.1 Recommended Improvements Summary

| Step | Area | Recommendation |
|---|---|---|
| 1 | EC2 security group | Restrict SSH/MySQL to a known admin IP |
| 4 | RDS storage | Reduce 400 GiB allocation to match actual data volume |
| 5 | IAM | Replace broad managed policies with narrowly scoped custom policies |
| 6 | KMS | Enable automatic key rotation |
| 7 | Secrets Manager | Enable rotation; split unrelated secrets |
| 8 | SQS | Add a Dead Letter Queue |
| 9 | CloudFront | Enable WAF and access logging |
| 12 | ECR | Enable scan-on-push and a lifecycle policy |
| 13 | ECS | Use native `secrets` injection instead of plaintext env vars; add Auto Scaling |
| 15 | CloudWatch | Add Alarms + SNS notifications |
| 16 | Billing | Re-validate the $50 budget against real Cost Explorer data |
| 17 | Cognito | Enable MFA for admin groups |
| 14 | CI/CD | Automate the CloudShell build/push steps with a pipeline |
