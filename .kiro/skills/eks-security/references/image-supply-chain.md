# Layer 4 — Image Supply Chain Security

The end-state is a complete chain: **scan → sign → verify-at-admission.** Each stage is independently valuable; together they ensure only scanned, signed images run.

## ECR Enhanced Scanning (powered by Amazon Inspector)

- CVE detection across **OS packages AND programming-language packages** (Python, Node.js, Java, Ruby, Go, …).
- CVSS severity scoring; **continuous re-scan** on new CVE disclosure.
- Findings flow to **AWS Security Hub** for unified posture.
- References: [Amazon ECR features](https://aws.amazon.com/ecr/features/) · [Amazon Inspector](https://aws.amazon.com/inspector/).

## ECR image signing

ECR stores image signatures as OCI artifacts via:
- **Cosign** (Sigstore project, CNCF) — keyless or keyed signatures.
- **Notation** (CNCF, OCI standard) — ECR is Notation-compatible.

## Image admission control — Kyverno `verifyImages`

Kyverno's `verifyImages` rule blocks unsigned or high-severity images **at admission time**. Combined with ECR Enhanced Scanning + signing, this closes the loop: an image that isn't scanned-clean and signed never schedules. (See Layer 3 — this is policy-engine sub-rule 3c.)

## Third-party scanners (alternatives or complements to ECR Enhanced Scanning)

| Scanner | Strengths | Available via |
|---|---|---|
| **Snyk** | Developer-focused, strong language scanning | AWS Marketplace |
| **Aqua** | Full container security platform | AWS Marketplace |
| **Wiz** | CNAPP, agentless | AWS Marketplace |
| **Prisma Cloud** (Palo Alto) | Comprehensive CSPM + workload protection | AWS Marketplace |
| **Trivy** | Open-source, fast, broad CVE coverage | Self-hosted (CI/CD) |

Position AWS-native (ECR Enhanced Scanning + Inspector + Security Hub) as the default; third-party CNAPP suits customers with an existing enterprise contract or multi-cloud posture. When a customer already runs a CNAPP, the conversation is coexistence-vs-displacement — escalate to Security guidance rather than reflexively recommending replacement.

## Hardening the images themselves

- Prefer **distroless / minimal base images** to shrink the CVE surface.
- Generate an **SBOM** and enforce build provenance where the regime requires it.
- DLC and ML images carry large dependency trees (PyTorch, CUDA) — the CVE surface is far larger than typical microservices; scan on push **and** on a schedule for base-image drift.

## Shared responsibility (Layer 4)

| AWS manages | Customer manages |
|---|---|
| ECR registry; Inspector scanning engine + CVE feed; signature storage | Enabling Enhanced Scanning per repo; signing keys + signing pipeline; admission policies (`verifyImages`); base-image hygiene; SBOM/provenance |

## Sources
- [Amazon ECR features](https://aws.amazon.com/ecr/features/) · [Amazon Inspector](https://aws.amazon.com/inspector/)
- [Sigstore Cosign](https://docs.sigstore.dev/) · [Notation (CNCF Notary Project)](https://notaryproject.dev/) · [Kyverno verifyImages](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/)
- [AWS Marketplace for Containers](https://aws.amazon.com/marketplace/) (Snyk, Aqua, Wiz, Prisma Cloud, Sysdig, …)
