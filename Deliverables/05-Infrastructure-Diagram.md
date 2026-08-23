# 🗺️ Infrastructure Diagram

## Secure Multi-Tenant SaaS Platform on AWS

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Infrastructure Diagram |
| Project Name | Secure Multi-Tenant SaaS Platform on AWS |
| Status | Final |
| Author | Santhanakrishnan S |
| Document Date | 23 August 2026 |
| Version | 1.0 |

## Version History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 23 August 2026 | Santhanakrishnan S | Initial published version, generated from AWS Configuration Document |

---

## Table of Contents

1. [Network Topology Diagram](#1-network-topology-diagram)
2. [Subnet & Security Group Map](#2-subnet--security-group-map)
3. [CI/CD Build & Deploy Pipeline](#3-cicd-build--deploy-pipeline)
4. [Data Flow Diagram](#4-data-flow-diagram)
5. [Notes](#5-notes)
6. [Conclusion](#6-conclusion)
7. [Appendix](#7-appendix)

---

## 1. Network Topology Diagram

```mermaid
graph TB
    Internet((Internet))

    subgraph VPC["VPC saas-VPC-12 — <VPC_ID> — 10.0.0.0/24"]
        IGW["Internet Gateway\nsaas-IGW-12"]

        subgraph AZ_A["Availability Zone A"]
            subgraph PubA["Public Subnet\n10.0.0.0/26"]
                ALB["ALB\nsaas-ALB-12"]
            end
            subgraph PrivA["Private Subnet\n10.0.0.128/26"]
                RDS[("RDS MySQL\nsaas-database")]
            end
            subgraph PrivA2["Private Subnet\n10.0.0.192/26"]
                ECS["ECS Fargate\nsaas-cluster-13"]
                LAMBDA["Lambda\ntenant-saas-metering"]
            end
        end

        subgraph AZ_B["Availability Zone B"]
            subgraph PubB["Public Subnet\n10.0.0.64/26"]
                EC2["EC2\nec2-rds-14"]
                NAT["NAT Gateway\nsaas-NAT-18"]
            end
        end
    end

    Internet --> IGW --> ALB
    IGW --> EC2
    ALB --> ECS
    ECS --> RDS
    LAMBDA --> RDS
    EC2 --> RDS
    ECS -.egress via.-> NAT --> IGW
    LAMBDA -.egress via.-> NAT
```

## 2. Subnet & Security Group Map

```mermaid
graph LR
    subgraph SG_ALB["ALB-SG-12"]
        direction TB
        R1["443 from 0.0.0.0/0"]
        R2["80 from 0.0.0.0/0"]
    end
    subgraph SG_ECS["ECS-SG-12"]
        R3["8080 from ALB-SG-12"]
    end
    subgraph SG_RDS["RDS-SG-12"]
        R4["3306 from ECS-SG-12"]
        R5["3306 from EC2-SG-12"]
        R6["3306 from LAMBDA-SG"]
    end
    subgraph SG_LAMBDA["saas-LAMBDA-billing-SG"]
        R7["no inbound"]
    end
    subgraph SG_EC2["EC2-SG-12"]
        R8["22 from 0.0.0.0/0"]
        R9["3306 from 0.0.0.0/0"]
    end

    SG_ALB --> SG_ECS --> SG_RDS
    SG_EC2 --> SG_RDS
    SG_LAMBDA --> SG_RDS
```

## 3. CI/CD Build & Deploy Pipeline

```mermaid
flowchart LR
    A["Developer ZIP upload"] --> B["AWS CloudShell\nunzip / build"]
    B --> C["docker build\ntenant-saas-app"]
    C --> D["aws ecr get-login-password"]
    D --> E["docker tag → ECR URI"]
    E --> F["docker push"]
    F --> G[("Amazon ECR\nsaas repository")]
    G --> H["ECS Service Update /\nNew Task Deployment"]
    H --> I["ECS Fargate Task\nsaas-task-family-13"]
```

*Note: this reflects a manual CloudShell-driven build/push process; no automated CI/CD pipeline (e.g. CodePipeline) is currently configured — see recommendation in [06-Deployment-Guide-SOP.md](06-Deployment-Guide-SOP.md).*

## 4. Data Flow Diagram

```mermaid
flowchart TD
    U([Tenant User]) -->|HTTPS| CF[CloudFront]
    CF --> AG[API Gateway]
    AG <-->|JWT validation| COG[Cognito]
    AG --> ALB
    ALB --> ECS[ECS Flask App]
    ECS <--> RDS[(RDS MySQL)]
    ECS -->|usage event| SQS[SQS Queue]
    SQS --> LAM[Lambda Metering]
    LAM --> RDS
    ECS -.secret lookup.-> SM[Secrets Manager]
    LAM -.secret lookup.-> SM
    SM -.encrypt/decrypt.-> KMS[KMS Key]
    ECS --> CW[CloudWatch]
    LAM --> CW
    ALB --> CW
    RDS --> CW
    CF --> CW
```

## 5. Notes

- All diagrams reflect the **implemented** state of the AWS Configuration Document, not an idealized target architecture.
- Dashed arrows represent control-plane / credential-retrieval interactions; solid arrows represent primary data-plane traffic.
- The single `RDS MySQL` node shown throughout represents one physical Amazon RDS instance (`saas-database`) that hosts both the application's own tables (accessed directly by ECS) and the `tenant_usage` table (written only by Lambda). This documentation set does not claim a second, separate "Usage Metering" RDS instance — see [02-Solution-Architecture.md §4](02-Solution-Architecture.md#4-architecture-diagram) for the same clarification.
- Amazon KMS is reached only through AWS Secrets Manager in the credential-retrieval flow shown in Section 4 — ECS and Lambda do not call KMS directly for secret decryption in these diagrams.

## 6. Conclusion

These diagrams provide a visual reference that should be read alongside the Low-Level Design for exact configuration values.

## 7. Appendix

Diagrams are authored in [Mermaid](https://mermaid.js.org/) syntax and render natively in GitHub Markdown previews.
