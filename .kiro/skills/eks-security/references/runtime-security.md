# Layer 5 — Runtime Security

Detect threats *while workloads run* — container breakouts, reverse shells, privilege escalation, crypto-mining, connections to malicious IPs, and anomalous control-plane API calls.

## Amazon GuardDuty for EKS — two complementary features

AWS uses two product-level features; note the current naming (older docs say "Audit Log Monitoring"):

| Feature (current name) | What it does | Setup |
|---|---|---|
| **EKS Protection** (audit-log based) | Analyzes EKS **control-plane audit logs** for anomalous/ malicious API activity (privilege escalation attempts, suspicious RBAC changes, anonymous access). Internally uses the `EKS_AUDIT_LOGS` data source. | Enable in GuardDuty; **no separate agent** — GuardDuty consumes the audit logs directly (you don't even have to send them to CloudWatch). |
| **Runtime Monitoring** (agent-based) | A kernel-level eBPF agent (deployed as a DaemonSet add-on) detecting on-host behavior — container breakouts, reverse shells, malicious process execution, suspicious network connections. Broader plan covering **EKS (on EC2 / Auto Mode) + ECS (incl. Fargate) + EC2**. **Not supported** for EKS on AWS Fargate or EKS Hybrid Nodes. | Deploy the GuardDuty agent via the EKS add-on (or let GuardDuty manage it). |

> **Naming precision:** the current product-level features are **"EKS Protection"** and **"Runtime Monitoring"** (EKS Runtime Monitoring is managed *as part of* Runtime Monitoring). The older label "EKS Audit Log Monitoring" survives in some API surfaces (the `EKS_AUDIT_LOGS` feature flag) but the console/product name is **EKS Protection**. Reference: [GuardDuty EKS integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-guardduty.html) · [EKS Protection in GuardDuty](https://docs.aws.amazon.com/guardduty/latest/ug/kubernetes-protection.html).

**AWS strongly recommends GuardDuty for EKS runtime monitoring.** Reference: [EKS Best Practices: Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html).

> **GuardDuty Extended Threat Detection for EKS (enabled automatically, no extra cost).** GuardDuty now **correlates signals across EKS audit logs, runtime behavior, malware execution, and AWS API activity** to surface a multi-stage attack (e.g. anomalous privileged-container deploy → persistence → crypto-mining → reverse shell) as a **single critical-severity "attack sequence" finding** with an incident summary, event timeline, **MITRE ATT&CK mapping**, and remediation steps — instead of scattered low-signal alerts. Requires **at least one of EKS Protection or Runtime Monitoring (with the EKS add-on)** enabled — the authoritative [Extended Threat Detection docs](https://docs.aws.amazon.com/guardduty/latest/ug/guardduty-extended-threat-detection.html) say either suffices, though both are recommended for full coverage (the June 2025 announcement leads with "EKS Protection"). This is the highest-value detection lever to call out for compliance/SOC customers. Reference: [GuardDuty Extended Threat Detection for EKS](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-guardduty-threat-detection-eks/).

## Falco — open-source alternative / complement

CNCF project; deploy via Helm. Use for **OSS-first organizations** or for **custom detection rules** not covered by GuardDuty. AWS has no managed Falco offering. Falco and GuardDuty are complementary — some customers run GuardDuty for managed coverage + Falco for bespoke rules.

## AWS Security Hub — unified findings aggregation

GuardDuty, Inspector, and Config findings all flow into **Security Hub**, which also evaluates compliance-pack standards: **CIS AWS Foundations Benchmark**, **AWS Foundational Security Best Practices (FSBP)**, **NIST SP 800-53**, and **PCI-DSS**. This is the single pane for posture across the security layers.

## Third-party CNAPP runtime

Wiz, Prisma Cloud, Aqua, Sysdig, CrowdStrike, and SentinelOne offer runtime detection via AWS Marketplace. On EKS Auto Mode, validate any runtime agent works with Auto Mode before committing (not all do).

## Shared responsibility (Layer 5)

| AWS manages | Customer manages |
|---|---|
| GuardDuty detection engine + threat-intel feeds; managed agent lifecycle; Security Hub aggregation | Enabling GuardDuty EKS Protection + Runtime Monitoring; agent rollout/validation (esp. on Auto Mode); triage + response runbooks; custom Falco rules if used |

## Sources
- [GuardDuty EKS integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-guardduty.html) · [EKS Protection in GuardDuty](https://docs.aws.amazon.com/guardduty/latest/ug/kubernetes-protection.html) · [EKS Best Practices: Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html)
- [AWS Security Hub](https://aws.amazon.com/security-hub/) · [Falco (CNCF)](https://falco.org/) · [AWS Marketplace for Containers](https://aws.amazon.com/marketplace/)
