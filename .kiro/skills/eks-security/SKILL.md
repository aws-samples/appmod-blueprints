---
name: eks-security
description: Use whenever someone needs security or compliance guidance for Amazon EKS — phrased as "CIS Benchmark for EKS", "HIPAA / PCI-DSS / FedRAMP / SOC 2 / GDPR on EKS", "harden my EKS cluster", "Bottlerocket vs AL2023 vs RHEL/Ubuntu AMI", "EKS Pod Identity vs IRSA", "Access Entries vs aws-auth", "GuardDuty for EKS", "Pod Security Admission / Kyverno / OPA", "NetworkPolicy / Security Groups for Pods", "ECR scanning / image signing (Cosign / Notation)", "EKS audit logging", "etcd / secrets encryption", or regulated-workload / audit-prep guidance. Walks the discovery-driven 7-layer security stack (OS/AMI → identity → workload → image → runtime → audit → compliance accelerators), the compliance-regime scope view, the AWS-canonical baseline, and a 30/60/90 hardening roadmap. Trigger even if "compliance" is never said — any EKS hardening, audit-prep, or regulated-workload decision qualifies. Skip for non-EKS (ECS/ROSA), account-level security with no EKS angle, or GenAI-workload security (use eks-genai).
---

# EKS Security & Compliance

End-to-end, opinionated security and compliance guidance for Amazon EKS, structured as a **7-layer stack** plus a **compliance-regime cross-cutting view**. This skill is **discovery-driven** — the right hardening stack is a function of *(compliance regime × OS-standardization mandate × team skill × audit timeline × workload sensitivity × air-gap requirement × scale × operational-overhead tolerance)*. Skipping the discovery questions makes the recommendation wrong about half the time.

Two AWS-published guides are the canonical foundation and every recommendation must align with one or both: the [EKS Best Practices: Compliance](https://docs.aws.amazon.com/eks/latest/best-practices/compliance.html) guide and the [EKS Best Practices: Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html) guide. For "how do I run a single cluster well" (non-security) use `eks-best-practices`; for designing/building the cluster use `eks-design` / `eks-build`.

> **The accuracy bar (non-negotiable for this skill).** Compliance is the one domain where customers validate *every* claim against an auditor. **Compliance status changes over time — always defer to the live [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) page before quoting program coverage** in any customer-facing document. Never state a cryptographic-module status, FedRAMP boundary, or certification you cannot cite to an AWS-published source. When you can't ground a claim, say so — do not synthesize.

## When to Use This Skill

**Activate when the user wants to:**
- Harden an EKS cluster or prepare for a first-time compliance audit (HIPAA, PCI-DSS, FedRAMP, SOC 2, ISO 27001, GDPR, HITRUST, NIST 800-53/171)
- Choose an OS / AMI strategy for security (Bottlerocket vs AL2023-with-CIS vs Ubuntu Pro vs RHEL vs Auto Mode)
- Decide identity & access (EKS Pod Identity vs IRSA; Access Entries vs `aws-auth`)
- Apply workload security (Pod Security Admission, Kyverno/OPA, NetworkPolicy, Security Groups for Pods)
- Secure the image supply chain (ECR Enhanced Scanning, Cosign/Notation signing, admission verification)
- Add runtime security (GuardDuty for EKS, Falco) and audit logging (control-plane logs, CloudTrail, SIEM)
- Wire compliance accelerators (Audit Manager, Config, Security Hub, Artifact)

**Don't use this skill for:**
- Non-EKS container platforms — **ECS/Fargate-without-EKS** (defer to ECS security guidance) or **ROSA** (Red Hat manages the stack differently)
- **AWS account-level / org-wide security** with no EKS-specific angle (IAM org policy, SCPs, SSO, multi-service GuardDuty) → Security guidance, not this skill
- **GenAI/GPU workload security** specifically (model-artifact provenance, training-data confidentiality, GPU-node compliance) → `eks-genai`
- Generic EKS architecture/cost/upgrade decisions with no security driver → `eks-best-practices` / `eks-design`
- Generating Terraform/Helm (→ `eks-build`) or auditing a live cluster's operational posture (→ `eks-operation-review`)

## Discovery First — the Required Questions

**Do NOT recommend a hardening stack before answering these.** The single most common mistake is reflexively saying "use Bottlerocket" or "use AL2023 with CIS hardening" without confirming the customer's context. The first four answers alone determine ~80% of the recommendation.

1. **Compliance regime(s)?** None / SOC 2 / HIPAA / PCI-DSS / FedRAMP Moderate / FedRAMP High / GDPR / ISO 27001 / HITRUST / NIST 800-53/171 / CJIS / DISA IL5 — rank primary/secondary if multiple.
2. **Workload sensitivity?** Public / internal / PII / PHI (HIPAA) / cardholder data (PCI) / federal.
3. **OS / AMI strategy?** Open to AWS defaults / Bottlerocket-first / AL2023+CIS custom AMI / Ubuntu mandate / RHEL mandate / custom hardened / EKS Auto Mode.
4. **Audit timeline?** None / <3 mo (urgent) / 3-6 mo / 6-12 mo / continuous.
5. **Cluster topology?** Single vs multi-cluster, single vs multi-account, multi-region, EKS Anywhere, Hybrid Nodes, GovCloud.
6. **Team K8s/security skill?** Low / moderate / high / mixed.
7. **Operational-overhead tolerance?** Zero (managed-only) / low / moderate / high.
8. **Current security tooling baseline?** None / AWS-native / third-party CNAPP / OSS / hybrid.

Full required + recommended question set, the 5 adoption-challenge archetypes, and the 8-step response framework: [references/engagement-and-response.md](references/engagement-and-response.md).

## The 7-Layer Security & Compliance Stack

Walk the layers bottom-up on a first engagement; each layer's controls compound on the previous.

| Layer | Focus | AWS-canonical default | Reference |
|-------|-------|----------------------|-----------|
| **1 — Compute / OS / AMI** | Node hardening | **Bottlerocket** (immutable, SELinux-enforcing, minimal); else CIS-hardened AL2023 via Image Builder; respect vendor-OS mandates (Ubuntu Pro / RHEL) | [os-ami-hardening.md](references/os-ami-hardening.md) |
| **2 — Identity & Access** | Who can do what | **EKS Pod Identity** (workloads) + **EKS Access Entries** (cluster access) | [identity-and-access.md](references/identity-and-access.md) |
| **3 — Workload Security** | Pod + network posture | **PSA `restricted`** + **Kyverno** (or OPA) + **VPC CNI NetworkPolicy** (default-deny) + **Security Groups for Pods** | [workload-security.md](references/workload-security.md) |
| **4 — Image Supply Chain** | Trust what you run | **ECR Enhanced Scanning** (Inspector) + **Cosign/Notation signing** + Kyverno `verifyImages` admission | [image-supply-chain.md](references/image-supply-chain.md) |
| **5 — Runtime Security** | Detect at runtime | **GuardDuty for EKS** (EKS Protection + Runtime Monitoring); Falco for OSS/custom rules; findings → Security Hub | [runtime-security.md](references/runtime-security.md) |
| **6 — Audit Logging & Forensics** | Prove what happened | EKS control-plane logs (**`audit` + `authenticator` minimum**) + CloudTrail + VPC Flow Logs + SIEM forwarding | [audit-logging.md](references/audit-logging.md) |
| **7 — Compliance Accelerators** | Continuous evidence | **Audit Manager** + **Config** + **Security Hub** + **Artifact** (download attestations) | [compliance-accelerators.md](references/compliance-accelerators.md) |

> **The AWS-canonical reference stack for a new commercial cluster:** Bottlerocket (L1) + Pod Identity + Access Entries (L2) + PSA `restricted` + Kyverno + VPC CNI NetworkPolicy + Security Groups for Pods (L3) + ECR Enhanced Scanning + Cosign signing (L4) + GuardDuty for EKS (L5) + control-plane `audit`+`authenticator` logging + CloudTrail (L6) + Audit Manager + Config + Security Hub (L7). The **vendor-OS path** applies the same stack with a Layer-1 substitution only.

**Cross-cutting concerns** (span every layer, aligned to the AWS Best Practices security areas): **data encryption & secrets management** (default envelope encryption on K8s 1.28+, CMK, Secrets Manager/CSI/ESO) → [encryption-and-secrets.md](references/encryption-and-secrets.md); **multi-tenancy & multi-account isolation** (soft vs hard, namespaces→cluster-/account-per-tenant) → [multi-tenancy.md](references/multi-tenancy.md); **incident response & forensics** (the runbook when a detection fires) → [incident-response-and-forensics.md](references/incident-response-and-forensics.md); and the **shared-responsibility model** — AWS secures the control plane (control-plane nodes + etcd) and assumes more as you move self-managed → MNG → Fargate; you secure the data plane, node OS, workloads, and the controls in this skill. Each reference includes its per-layer shared-responsibility split.

## Compliance-Regime Scope (cross-cutting)

EKS is **natively in scope** for PCI-DSS L1, HIPAA-eligible (BAA required), SOC 1/2/3, ISO 27001/27017/27018/9001, FedRAMP Moderate (commercial) and High (GovCloud only), HITRUST CSF, IRAP, C5, K-ISMS, ENS High, OSPAR, DISA IL4/IL5 (GovCloud only — commercial reaches IL2). AWS provides **alignment / framework support** (not independent attestation) for GDPR, NIST SP 800-53/800-171, and CJIS — the customer owns workload-level controls. Per-regime nuance, the scope table, and the worked HIPAA/PCI/FedRAMP/GDPR/Auto-Mode scenarios: [references/compliance-regimes.md](references/compliance-regimes.md).

> **Always include the disclaimer in customer-facing output:** "Compliance status changes over time — verify on the live [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) page before quoting program coverage." And precision matters: EKS is **HIPAA-*eligible*** (with a signed BAA), not "HIPAA-compliant"; FedRAMP **High = GovCloud only**, Moderate = commercial regions.

## Security Baseline (non-negotiable — every recommendation includes this)

Regardless of regime, every hardening recommendation MUST include:
- **EKS Pod Identity** (recommended for new workloads; IRSA is a fully supported alternative — see note) — never static AWS keys
- **EKS Access Entries** for cluster access — never the `aws-auth` ConfigMap on new clusters
- **EKS control-plane logging** — `audit` + `authenticator` at minimum
- **GuardDuty for EKS** — EKS Protection (audit-log) + Runtime Monitoring (agent)
- **ECR Enhanced Scanning** on all production repositories
- **Pod Security Admission `restricted`** on production namespaces
- **NetworkPolicy default-deny** on production namespaces (VPC CNI native, or Calico/Cilium on self-managed)
- **Encryption at rest** — EKS provides **default envelope encryption of all Kubernetes API data** (KMS provider v2, AWS-owned key) on **K8s 1.28+ with no action required**; bring a **customer-managed KMS key (CMK)** for control over rotation/audit, and use CMKs for EBS/S3/EFS under compliance regimes (etcd EBS volumes are also EBS-encrypted independently)
- **Encryption in transit** — TLS in-cluster; mTLS via service mesh for high-sensitivity workloads
- **Secrets via Secrets Manager + Secrets Store CSI Driver + ASCP** (or External Secrets Operator) — never plain Kubernetes Secrets in production; never baked into images
- **CloudTrail** for EKS API audit; **private API endpoint** (or restricted public CIDR allowlist) for production
- **Preventive governance (multi-account):** enforce the above with **EKS IAM condition keys** in SCPs/IAM (private endpoint, CMK encryption, approved K8s version, deletion protection) so non-compliant clusters can't be created — see [identity-and-access.md](references/identity-and-access.md)

## Hardening Roadmap (30 / 60 / 90)

- **Days 1-30 (baseline, non-disruptive):** enable control-plane `audit`+`authenticator` logging; enable GuardDuty for EKS; enable Security Hub (CIS AWS Foundations + AWS FSBP); enable ECR Enhanced Scanning; run `kube-bench` for the current CIS posture. *Change nothing yet — establish the baseline.*
- **Days 31-60 (identity + workload):** migrate `aws-auth` → Access Entries (planned change window, `kubectl` access pre-validated); migrate/justify IRSA → Pod Identity; enable PSA `restricted` (start `audit` mode → `enforce`); deploy Kyverno/OPA; enforce NetworkPolicy default-deny.
- **Days 61-90 (OS + image + accelerators):** migrate to Bottlerocket (or build CIS-hardened AL2023 via Image Builder); enable ECR image signing; deploy Audit Manager with the applicable framework; validate Security Hub against the compliance pack; download attestations from AWS Artifact.
- **Greenfield:** deploy the full 7-layer stack at cluster creation, not retrofitted.

## Top Guardrails (the high-cost mistakes)

- **Don't recommend a stack before the discovery questions** — the #1 mistake.
- **Don't call IRSA "legacy"** — AWS docs say Pod Identity is *recommended for new workloads* while **IRSA remains a fully supported alternative** (and is the right choice on Fargate, Windows nodes, unsupported SDKs, or cross-account OIDC federation). "Legacy" applies to the `aws-auth` ConfigMap, not IRSA.
- **Don't use `aws-auth` ConfigMap on new clusters** — it's deprecated; use Access Entries (auditable in CloudTrail).
- **Don't recommend PodSecurityPolicy (PSP)** — removed in Kubernetes 1.25+; use PSA + Kyverno/OPA.
- **Don't recommend AWS App Mesh for new work** — end of support **Sept 30, 2026**; use Istio/Linkerd/Cilium mesh or VPC Lattice.
- **Don't recommend EKS Auto Mode when a hard CIS-hardened-*custom*-AMI requirement exists** — Auto Mode doesn't support custom AMIs (as of June 2026); use Bottlerocket on self-managed Karpenter NodePools. Cilium CNI is also not supported on Auto Mode.
- **Don't promise "HIPAA-compliant"** — EKS is HIPAA-*eligible*; a signed BAA is required and the customer owns workload-level controls.
- **Don't conflate** FedRAMP Moderate (commercial) with High (GovCloud); FIPS 140-3 (Bottlerocket FIPS AMIs) with 140-2; or CIS AL2 with CIS AL2023 benchmarks (distinct documents).
- **Don't treat a CMK as free of operational risk** — once a CMK is the envelope-encryption key, **disabling it degrades the cluster** (the API server can't boot on restart; ~30-day window to re-enable before forced auto-upgrade) and **deleting it makes the cluster unrecoverable**. Guard the CMK with least-privilege IAM + a CloudWatch alarm.
- **Don't synthesize compliance claims** — cite an AWS-published source or recommend escalation.

## Escalation

Create a SpecReq / escalate for: first-time certification on a mission-critical regulated workload; XXL+ segment; FedRAMP High / GovCloud; Top Secret/Secret (out of scope here); EKS Anywhere or Hybrid Nodes inside a FedRAMP boundary; multi-tenant SaaS with cross-tenant PHI/cardholder/federal isolation; customer-vs-auditor disagreement on AWS-managed-control acceptability; or any claim you cannot ground. Full criteria: [references/engagement-and-response.md](references/engagement-and-response.md).

## How to Use the References

Progressive disclosure — the essentials are above; load a reference only when the task needs that depth:

| Reference | Load when the task is about… |
|-----------|------------------------------|
| [engagement-and-response.md](references/engagement-and-response.md) | Full discovery question set, adoption-challenge archetypes, the 8-step response framework, escalation criteria |
| [os-ami-hardening.md](references/os-ami-hardening.md) | Layer 1 — Bottlerocket vs AL2023 vs Ubuntu/RHEL, CIS benchmark hierarchy, Image Builder hardened-AMI pipeline, FIPS |
| [identity-and-access.md](references/identity-and-access.md) | Layer 2 — Pod Identity vs IRSA, Access Entries vs aws-auth, access policies |
| [workload-security.md](references/workload-security.md) | Layer 3 — PSA, Kyverno/OPA, NetworkPolicy, Security Groups for Pods, service-mesh mTLS |
| [image-supply-chain.md](references/image-supply-chain.md) | Layer 4 — ECR Enhanced Scanning, Cosign/Notation signing, admission control, third-party scanners |
| [runtime-security.md](references/runtime-security.md) | Layer 5 — GuardDuty for EKS, Falco, Security Hub aggregation |
| [audit-logging.md](references/audit-logging.md) | Layer 6 — control-plane log types, CloudTrail, VPC Flow Logs, SIEM forwarding, retention |
| [compliance-accelerators.md](references/compliance-accelerators.md) | Layer 7 — Audit Manager, Config, Security Hub, Artifact, kube-bench |
| [encryption-and-secrets.md](references/encryption-and-secrets.md) | Default envelope encryption (KMS v2), CMK + its operational risk, EBS/EFS/FSx encryption, Secrets Manager/CSI/ESO/Sealed Secrets, secret hygiene |
| [multi-tenancy.md](references/multi-tenancy.md) | Soft vs hard multi-tenancy, in-cluster isolation (namespaces/RBAC/NetworkPolicy/quotas/node isolation), cluster-/account-per-tenant |
| [incident-response-and-forensics.md](references/incident-response-and-forensics.md) | IR runbook for a compromised pod/node, isolation/eradication, credential revocation, forensic capture |
| [compliance-regimes.md](references/compliance-regimes.md) | Per-regime scope (HIPAA/PCI/FedRAMP/GDPR/ISO/…), the scope table, worked scenarios, regime-specific controls |

## Sources

- [EKS Best Practices: Compliance](https://docs.aws.amazon.com/eks/latest/best-practices/compliance.html) · [EKS Best Practices: Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html) · [EKS Best Practices: Cluster Access Management](https://docs.aws.amazon.com/eks/latest/best-practices/cluster-access-management.html)
- [Meet compliance requirements with Bottlerocket](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-compliance-support.html) · [Bottlerocket FIPS AMIs](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-fips-amis.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html) · [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) · [Access Entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html)
- [GuardDuty EKS integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-guardduty.html) · [Control-plane logs](https://docs.aws.amazon.com/eks/latest/userguide/control-plane-logs.html) · [VPC CNI NetworkPolicy](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html)
- [AWS Compliance Programs](https://aws.amazon.com/compliance/programs/) · [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) · [AWS Artifact](https://aws.amazon.com/artifact/)
- [aws/aws-eks-best-practices](https://github.com/aws/aws-eks-best-practices) · [EKS Security Immersion Workshop](https://catalog.us-east-1.prod.workshops.aws/workshops/165b0729-2791-4452-8920-53b734419050) · [kube-bench](https://github.com/aquasecurity/kube-bench)
