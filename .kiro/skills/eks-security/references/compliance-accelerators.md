# Layer 7 — Compliance Accelerators

Tools that turn the hardened cluster into **continuous, auditor-ready evidence** — so an audit is a report-pull, not a fire drill.

| Service | Function | Reference |
|---|---|---|
| **AWS Audit Manager** | Continuous evidence collection mapped to framework controls (HIPAA, PCI-DSS, FedRAMP, NIST 800-53). The engine that makes audit prep continuous rather than point-in-time. | [AWS Audit Manager](https://aws.amazon.com/audit-manager/) |
| **AWS Config** | Resource-configuration compliance; rules evaluating EKS cluster settings (logging enabled, endpoint privacy, encryption). | [AWS Config](https://aws.amazon.com/config/) |
| **AWS Security Hub** | CSPM; aggregates GuardDuty + Inspector + Config findings; evaluates compliance-pack standards (CIS AWS Foundations, AWS FSBP, NIST SP 800-53, PCI-DSS). | [Security Hub](https://aws.amazon.com/security-hub/) |
| **AWS Artifact** | Self-service download of SOC 2, ISO 27001, PCI-DSS AOC, FedRAMP packages, HIPAA AOC, and the AWS Data Processing Addendum (DPA) — the documents you hand an auditor. | [AWS Artifact](https://aws.amazon.com/artifact/) |
| **AWS Compliance Programs / Services in Scope** | The authoritative, live source for which programs EKS is in scope for. | [Compliance Programs](https://aws.amazon.com/compliance/programs/) · [Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) |
| **kube-bench** | OSS CIS Kubernetes Benchmark scanner; run it to baseline current CIS posture and re-validate after hardening. | [kube-bench (Aqua)](https://github.com/aquasecurity/kube-bench) |

## How they fit together

1. **Baseline** — run `kube-bench` for current CIS posture; turn on Security Hub standards.
2. **Continuous evidence** — Audit Manager collects evidence against the chosen framework; Config flags drift.
3. **Audit time** — validate Security Hub against the compliance pack, remediate findings, download the attestation (AOC / package) from Artifact for the auditor.

> **Disclaimer (always include in customer-facing output):** "Compliance status changes over time — verify on the live [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) page before quoting program coverage." Audit Manager / Security Hub frameworks accelerate evidence; they do **not** themselves constitute certification.

## Shared responsibility (Layer 7)

| AWS manages | Customer manages |
|---|---|
| Service availability; pre-built framework definitions + compliance packs; attestation packages in Artifact | Selecting the right framework; remediating findings; mapping evidence to the auditor's requirements; downloading + presenting attestations; the workload-level controls AWS attestations don't cover |

## Sources
- [AWS Audit Manager](https://aws.amazon.com/audit-manager/) · [AWS Config](https://aws.amazon.com/config/) · [AWS Security Hub](https://aws.amazon.com/security-hub/) · [AWS Artifact](https://aws.amazon.com/artifact/)
- [AWS Compliance Programs](https://aws.amazon.com/compliance/programs/) · [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) · [kube-bench](https://github.com/aquasecurity/kube-bench)
