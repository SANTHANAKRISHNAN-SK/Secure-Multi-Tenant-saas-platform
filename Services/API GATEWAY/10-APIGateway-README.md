# 🚪 Amazon API Gateway

## 📌 Overview

Amazon API Gateway is a fully managed service that lets you create, publish, and secure REST, HTTP, and WebSocket APIs at any scale. It sits at the edge of your architecture, handling request routing, authorization, throttling, and monitoring so that backend compute services don't have to.

In this project, Amazon API Gateway is deployed as a **REST API** named `rest-api-new-17`, acting as the secure, centralized entry point for every client request entering the Secure Multi-Tenant SaaS Platform.

---

## 🎯 Purpose in THIS Project

| Attribute | Value |
|---|---|
| API Name | `rest-api-new-17` |
| API ID | `26qdafcfw9` |
| API Type | REST API |
| Endpoint Type | Regional |
| Stage | `saas` |
| Invoke URL | `https://26qdafcfw9.execute-api.us-east-1.amazonaws.com/saas` |
| Authorization | Amazon Cognito User Pool Authorization (JWT) |
| Integration Type | HTTP Proxy Integration (Application Load Balancer) |
| Logging | Amazon CloudWatch Logs |
| Throttling | Default Stage Throttling (No Custom Throttling Configured) |
| Caching | Disabled |
| Status | Available |

`rest-api-new-17` receives every application request routed through Amazon CloudFront, validates the caller's identity using a Cognito JWT authorizer, and proxies the authenticated request to the Application Load Balancer over HTTP.

---

## ✅ Why This Service Was Selected

- The platform required a **single, versioned, and centrally managed entry point** for all Flask application routes instead of exposing the Application Load Balancer directly to the internet.
- API Gateway's native **Amazon Cognito User Pool Authorizer** integration made it possible to enforce JWT validation at the edge, before any request reaches Amazon ECS.
- **HTTP Proxy Integration** allowed the existing Flask routing logic to be reused without rewriting the application as a set of Lambda-backed API Gateway methods.
- Built-in **Amazon CloudWatch Logs** integration provided request-level visibility without deploying a separate logging layer.
- Regional endpoint type kept latency low for the CloudFront origin while avoiding the added complexity of an edge-optimized deployment.

---

## ⚙️ My Implementation

### REST API Resource Tree

```
/
├── login                              → GET
├── login/cognito                      → GET
├── auth
│   └── callback                       → GET
├── logout                             → GET
└── api
    └── v1
        ├── health                     → GET
        ├── users
        │   ├── dashboard              → GET
        │   ├── userdetails            → GET, PUT
        │   └── password
        │       └── reset              → GET, POST
        ├── admin
        │   ├── dashboard              → GET
        │   └── users                  → POST
        │       └── {user_id}
        │           ├── DELETE
        │           └── PATCH (toggle)
        └── billing
            ├── dashboard              → GET
            └── usage                  → GET, POST
```

### Resource → Method Mapping

| Resource | Method(s) |
|---|---|
| `/login` | GET |
| `/login/cognito` | GET |
| `/auth/callback` | GET |
| `/logout` | GET |
| `/api/v1/health` | GET |
| `/api/v1/users/dashboard` | GET |
| `/api/v1/users/userdetails` | GET, PUT |
| `/api/v1/users/password/reset` | GET, POST |
| `/api/v1/admin/dashboard` | GET |
| `/api/v1/admin/users` | POST |
| `/api/v1/admin/users/{user_id}` | DELETE |
| `/api/v1/admin/users/{user_id}/toggle` | PATCH |
| `/api/v1/billing/dashboard` | GET |
| `/api/v1/billing/usage` | GET, POST |

Every method integrates with the backend through **HTTP Proxy Integration**, forwarding the request path, headers, and body directly to `saas-ALB-12`, which then routes it to the Amazon ECS Fargate task.

---

## 🔄 Role in End-to-End Request Flow

```mermaid
sequenceDiagram
    participant User
    participant CloudFront as Amazon CloudFront
    participant APIGW as API Gateway (rest-api-new-17)
    participant Cognito as Amazon Cognito
    participant ALB as Application Load Balancer
    participant ECS as Amazon ECS (Flask App)

    User->>CloudFront: HTTPS Request
    CloudFront->>APIGW: Forward to Origin (/saas stage)
    APIGW->>Cognito: Validate JWT (Access/ID Token)
    Cognito-->>APIGW: Token Valid / Invalid
    APIGW->>ALB: HTTP Proxy Integration (authorized requests only)
    ALB->>ECS: Forward to Target Group (saas-TG-12)
    ECS-->>APIGW: Response
    APIGW-->>CloudFront: Response
    CloudFront-->>User: Response
```

API Gateway is the **first authorization checkpoint** in the request path — CloudFront forwards all traffic to it, and only requests carrying a valid Cognito-issued JWT are proxied onward to the ALB and Amazon ECS.

---

## 🔗 Communication With Other AWS Services

| Service | Interaction |
|---|---|
| **Amazon CloudFront** | Origin domain for `saas-distribution-13`; CloudFront forwards all viewer requests to `26qdafcfw9.execute-api.us-east-1.amazonaws.com/saas` |
| **Amazon Cognito** | Validates incoming JWT (ID/Access Tokens) issued by User Pool `us-east-1_t5OcevNKj` before allowing requests through |
| **Application Load Balancer** | Downstream target for HTTP Proxy Integration; all authorized requests are forwarded to `saas-ALB-12` |
| **Amazon CloudWatch** | Receives execution logs for API Gateway requests and is used in the `tenant-saas-app-monitoring` dashboard (Count, Latency, 4XXError, 5XXError) |

---

## 🔒 Security Implementation

- **JWT Authorization**: Every protected route is secured with a Cognito User Pool Authorizer, so unauthenticated or tampered requests are rejected at the API Gateway layer and never reach the Application Load Balancer or ECS.
- **Regional Endpoint**: Kept the API within the AWS backbone path from CloudFront, avoiding a public edge-optimized surface.
- **HTTPS Only**: All client traffic reaches API Gateway over HTTPS via the CloudFront origin.
- **No Direct Backend Exposure**: The Application Load Balancer and Amazon ECS tasks are never called directly by clients — API Gateway is the sole authorized entry point.

---

## 📈 High Availability & Scalability

- Amazon API Gateway is a fully managed, serverless service that automatically scales to handle incoming request volume without any provisioning on my part.
- The **regional endpoint** is inherently distributed across multiple Availability Zones within `us-east-1` by AWS.
- Default stage throttling protects the downstream Application Load Balancer and Amazon ECS service from sudden traffic spikes.

---

## 📊 Monitoring

| Metric | Purpose |
|---|---|
| `Count` | Total number of API requests received |
| `Latency` | End-to-end request latency through API Gateway |
| `4XXError` | Client-side errors (e.g., failed JWT authorization) |
| `5XXError` | Server-side errors (backend/integration failures) |

These metrics are surfaced on the **`tenant-saas-app-monitoring`** Amazon CloudWatch dashboard, alongside ALB, RDS, ECS, Lambda, and CloudFront widgets, giving a unified view of API health.

---

## ✅ Best Practices Implemented

- ✅ Centralized, single entry point for all application routes
- ✅ Authorization enforced at the edge using Cognito JWT before reaching compute
- ✅ HTTP Proxy Integration to avoid duplicating routing logic across layers
- ✅ CloudWatch Logs enabled for request-level visibility
- ✅ Stage-based deployment (`saas`) for clean environment separation

---

## ⭐ Why This Service Is Important

API Gateway is the **security and traffic control boundary** of the platform. Without it, every request would need to be authenticated inside the Flask application itself, increasing the attack surface and coupling authentication logic to application code. By validating JWTs before requests ever reach Amazon ECS, API Gateway ensures that only legitimate, authenticated tenant traffic consumes backend compute and database resources.

---

## 📝 Summary

Amazon API Gateway (`rest-api-new-17`) provides the Secure Multi-Tenant SaaS Platform with a single, versioned REST API surface that enforces Cognito JWT authorization, proxies authenticated requests to the Application Load Balancer, and streams request metrics and logs to Amazon CloudWatch — forming the authenticated gateway between Amazon CloudFront and the application tier.
