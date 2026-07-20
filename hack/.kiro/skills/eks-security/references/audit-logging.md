# Layer 6 — Audit Logging & Forensics

Proving *what happened* is the backbone of every compliance audit. Three sources compound: Kubernetes-level (control-plane logs), AWS-API-level (CloudTrail), and network-level (VPC Flow Logs).

## EKS control-plane logging — 5 log types (all to CloudWatch Logs)

| Log type | Purpose | Recommended? |
|---|---|---|
| `audit` | Who did what, when (Kubernetes-level) | **REQUIRED for compliance** |
| `authenticator` | IAM / OIDC authentication events | **REQUIRED for compliance** |
| `controllerManager` | Controller reconciliation loop | Recommended for forensics |
| `scheduler` | Pod placement decisions | Optional (high volume) |
| `api` | Kubernetes API server | Recommended for high-sensitivity workloads |

For compliance regimes, **always enable `audit` and `authenticator` at minimum.** Reference: [Send control plane logs to CloudWatch](https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html).

> **Gotcha:** EKS audit-log **filtering is not supported** — it's all-or-nothing per log type. Large clusters can generate substantial audit-log volume → meaningful CloudWatch Logs cost. Budget for it and set a retention policy that meets the regime (below) without over-retaining.

## CloudTrail — EKS API audit trail

Records all EKS API calls (`CreateCluster`, `UpdateClusterConfig`, `AssociateAccessPolicy`, …). Required for the audit trail of **cluster-level configuration changes** — and the reason Access Entries (which write through the EKS API) are auditable while `aws-auth` ConfigMap edits were not.

## VPC Flow Logs — pod-level network forensics

Especially valuable combined with **Security Groups for Pods** (Layer 3), giving network-flow evidence at pod granularity for incident investigation and segmentation proof.

## SIEM forwarding pattern

CloudWatch Logs subscription → Kinesis Data Streams → Firehose → SIEM destination (Splunk, Elastic, Datadog, Microsoft Sentinel). For federal workloads, Datadog has a [FedRAMP High-certified solution](https://aws.amazon.com/blogs/publicsector/transforming-federal-it-with-datadogs-fedramp-high-solution/).

## Retention requirements by regime (set this deliberately)

| Regime | Minimum audit-log retention |
|---|---|
| Commercial (no regime) | per policy (often 30-90 days) |
| **PCI-DSS** | **1 year minimum** (3 months immediately available) |
| **HIPAA / SOX** | **6 years** |
| FedRAMP | per System Security Plan; continuous-monitoring cadence |

Apply the retention to the CloudWatch Logs groups holding `audit`/`authenticator` (and to CloudTrail/S3) — and encrypt those groups with a customer-managed KMS key for high-sensitivity workloads.

## Shared responsibility (Layer 6)

| AWS manages | Customer manages |
|---|---|
| Control-plane log generation; CloudTrail capture of EKS API calls; durability of CloudWatch Logs/S3 | Enabling the right log types; retention + encryption (CMK); SIEM pipeline; log review / alerting; forensic runbooks |

## Sources
- [Send control plane logs to CloudWatch](https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html) · [AWS CloudTrail](https://aws.amazon.com/cloudtrail/) · [VPC Flow Logs](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html)
- [Datadog FedRAMP High solution](https://aws.amazon.com/blogs/publicsector/transforming-federal-it-with-datadogs-fedramp-high-solution/)
