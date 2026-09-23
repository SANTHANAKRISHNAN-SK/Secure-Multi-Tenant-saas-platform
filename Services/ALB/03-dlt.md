# 🏗️ Application Load Balancer

## 📌 Overview

`saas-ALB-12` is the internet-facing Application Load Balancer that sits in front of the ECS Fargate service running the platform's Flask application. It receives requests forwarded from Amazon API Gateway and routes them to healthy ECS tasks on port 8080.

## 🎯 Purpose in THIS Project

**Business purpose:** tenants need reliable, always-available access to the SaaS application; the ALB is the mechanism that keeps traffic flowing to a healthy application instance and detects unhealthy ones automatically.

**Technical purpose:** the ALB terminates HTTP traffic from API Gateway's HTTP Proxy Integration, performs health checks against the ECS task, and forwards traffic to the ECS service's target group.

**Contribution to the overall solution:** it is the bridge between the API/edge layer (CloudFront, API Gateway) and the compute layer (ECS Fargate) — every authenticated API request passes through it on the way to the Flask application.

## ✅ Why This Service Was Selected

An Application Load Balancer (Layer 7) was selected — rather than a Network Load Balancer — because the platform's traffic is HTTP/HTTPS REST API traffic that benefits from ALB's HTTP-aware health checks (`/api/v1/health`) and target-type `IP` routing, which is what ECS Fargate tasks require since Fargate tasks don't have static EC2 instance IDs to register.

## ⚙️ My Implementation

| Attribute | Value |
|---|---|
| Load Balancer Name | `saas-ALB-12` |
| Type | Application |
| Scheme | Internet-facing |
| IP Address Type | IPv4 |
| Region | `us-east-1` |
| VPC | `saas-VPC-12` (`vpc-03c620f18f61ea855`) |
| Subnets / AZs | `saas-public-sub1-ALB-aza` (`subnet-0d24c57f51289130e`, `us-east-1a`); `saas-public-sub2-EC2-azb` (`subnet-0cb2c22c0313bf9b2`, `us-east-1b`) |
| Security Group | `ALB-SG-12` (`sg-0e1b1f023fbb55fad`) |
| Listener | HTTP : 80 |
| Target Group | `saas-TG-12` |
| Target Type | IP |
| Target Protocol/Port | HTTP : 8080 |
| Health Check Path | `/api/v1/health` |
| Health Check Protocol/Port | HTTP, Traffic port |
| Health Check Interval | 30 seconds |
| DNS Name | `saas-ALB-12-654507458.us-east-1.elb.amazonaws.com` |
| Status | Running, Healthy |

## 🔄 Role in End-to-End Request Flow

```
User
  ↓
CloudFront
  ↓
API Gateway (HTTP Proxy Integration)
  ↓
Application Load Balancer (saas-ALB-12, listener HTTP:80)
  ↓
Target Group (saas-TG-12, target type IP, port 8080)
  ↓
ECS Fargate (Flask application)
  ↓
Amazon RDS
```

## 🔗 Communication With Other AWS Services

| Service | Why They Communicate | What Is Exchanged | How |
|---|---|---|---|
| Amazon API Gateway | API Gateway's HTTP Proxy Integration forwards every REST resource request to the ALB | HTTP requests/responses | HTTPS from API Gateway to the ALB's public DNS name |
| Amazon ECS Fargate | The ALB forwards healthy-target traffic to the ECS service's registered IP targets | HTTP requests/responses on port 8080 | Target Group `saas-TG-12`, target type IP |
| Amazon VPC | The ALB is deployed into the two public subnets of `saas-VPC-12` | Network placement / routing | Subnet association across `us-east-1a` and `us-east-1b` |

## 🔒 Security Implementation

- Dedicated security group `ALB-SG-12`, accepting HTTPS (443) and HTTP (80) from `0.0.0.0/0` — the only component in the platform intentionally open to the public internet.
- Only traffic from `ALB-SG-12` is permitted into `ECS-SG-12`, meaning ECS tasks cannot receive traffic that didn't first pass through this load balancer.
- Health checks on `/api/v1/health` ensure traffic is only routed to ECS tasks reporting healthy status.

## 📈 High Availability & Scalability

The ALB is associated with subnets in **two Availability Zones** (`us-east-1a` and `us-east-1b`), which is the platform's primary cross-AZ high-availability mechanism at the network edge. However, the ECS service behind it currently runs with a desired task count of 1 in a single private subnet (`us-east-1a` only), so while the load balancer itself is multi-AZ, the compute it forwards to is not yet distributed across AZs.

## 📊 Monitoring

Tracked on the `tenant-saas-app-monitoring` CloudWatch dashboard with the following metrics:

- `RequestCount`
- `TargetResponseTime`
- `ActiveConnectionCount`

## ✅ Best Practices Implemented

- Target type `IP` used for Fargate compatibility (Fargate tasks have no persistent instance ID)
- HTTP health check on a dedicated `/api/v1/health` endpoint rather than relying on the application's root path
- Deployed across two Availability Zones
- Security group scoped so only the ALB itself accepts open internet traffic — every downstream service is reached only through it

## ⭐ Why This Service Is Important

The ALB is the single point where public/edge traffic transitions into the platform's private network. It enforces that ECS is only reachable through a health-checked, load-balanced path, and it is the mechanism that would allow the platform to scale ECS horizontally in the future without any change to how API Gateway or CloudFront address the application.

## 📝 Summary

`saas-ALB-12` is the Layer 7 entry point into the ECS-hosted Flask application, receiving proxied traffic from API Gateway and load-balancing it across health-checked ECS targets on port 8080. Its two-AZ subnet placement and strict security-group boundary make it both the platform's availability anchor and its network security gate for the compute tier.
