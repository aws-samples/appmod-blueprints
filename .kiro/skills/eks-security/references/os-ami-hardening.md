# Layer 1 — Compute / OS / AMI Hardening

The single biggest decision in EKS security. It depends on whether the customer accepts AWS-canonical defaults or has an organizational vendor-OS standardization mandate. The decision rule is a function of *(compliance regime × OS-standardization mandate × team skill × audit timeline × air-gap requirement)*.

## OS / AMI decision matrix

| Customer profile | AWS-canonical recommendation | Vendor-OS path | Notes |
|---|---|---|---|
| Open to AWS defaults + container-first | **Bottlerocket** — purpose-built, immutable root filesystem, SELinux enforcing, minimal attack surface | — | AWS-preferred for containers; CIS-hardening guidance published; FIPS 140-3 variant; HIPAA-eligible |
| Open to AWS defaults + general-purpose OS | **Amazon Linux 2023 (AL2023)** EKS-optimized AMI | — | Default EKS AMI; CIS Level 2 achievable via Image Builder pipeline |
| Open to AWS defaults + lowest ops burden | **EKS Auto Mode AMI** (AWS-managed) | — | **Custom AMIs NOT supported**; AWS-managed patching; see Auto Mode trade-off below |
| Vendor mandate — Ubuntu | — | **Canonical Ubuntu Pro for EC2** (Marketplace AMI; FIPS variant available); custom EKS AMI from Ubuntu base | Vendor-supported security patches |
| Vendor mandate — RHEL | — | **RHEL custom AMI** on self-managed nodes; OR **ROSA** for fully Red Hat-managed OpenShift | Customer owns RHEL-specific hardening; ROSA is a separate product (defer to ROSA + Red Hat partner) |
| Air-gapped / FedRAMP High / classified | **EKS Anywhere** on bare metal (or Bottlerocket on Outposts) | EKS Anywhere with vendor OS | Customer owns ALL physical + OS security; AWS manages no control plane in air-gapped mode |
| FIPS 140-3 cryptography required | **Bottlerocket FIPS AMIs** (FIPS 140-3 validated modules — the [FIPS AMI page](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-fips-amis.html) names the AL2023 Kernel Crypto API + Go Cryptographic Module; the [compliance page](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-compliance-support.html) also lists the AWS-LC Cryptographic Module) | Ubuntu Pro FIPS; RHEL FIPS profile | Verify current module names + CMVP certificate numbers at NIST CMVP before quoting in customer-facing docs |

## The AWS opinionated default for new clusters

1. **First choice — Bottlerocket** for container-first workloads with no vendor-OS mandate: immutable root filesystem, SELinux enforcing, minimal attack surface, AWS-published CIS hardening, FIPS 140-3 variant, HIPAA-eligible. Reference: [Meet compliance requirements with Bottlerocket](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-compliance-support.html).
2. **Second choice — AL2023 with a CIS-hardened Image Builder pipeline** for customers needing a general-purpose OS. Reference: [Automating AL2023 custom hardened AMI updates for EKS managed nodes](https://aws.amazon.com/blogs/containers/automating-al2023-custom-hardened-ami-updates-for-amazon-eks-managed-nodes) (Containers TFC, 2026).
3. **Third choice — EKS Auto Mode** for zero data-plane management (no custom AMI possible).

> **Bottlerocket CIS posture (use the precise, current numbers).** The **CIS Bottlerocket Benchmark v1.0.0** defines **15 Level-1 checks and 13 Level-2 checks (28 total)**. Out of the box, the EKS-optimized Bottlerocket AMI passes **11 of the 15 Level-1 checks, with 4 skipped** (manual checks — e.g. update-repo, host-firewall — that require environment-specific configuration); the current [Bottlerocket compliance support page](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-compliance-support.html) summarizes this as "most of the controls required by the CIS Level 1 configuration profile," and you can reproduce the exact `Passed: 11, Skipped: 4, Total: 15` report on a node (`apiclient report cis --level 1`, see [Generate CIS compliance reports](https://docs.aws.amazon.com/eks/latest/userguide/auto-cis.html)). **Do not cite "18 of 28" as a Level-1 figure** — 18 is the count of passing checks across **both Level 1 + Level 2 combined** (per the [validation blog](https://aws.amazon.com/blogs/containers/validating-amazon-eks-optimized-bottlerocket-ami-against-the-cis-benchmark/)), and "18 of 22" was wrong on both numbers.

## When the vendor-OS path is the right answer

- Enterprise contract with Canonical (Ubuntu) or Red Hat (RHEL) including security patches + 24×7 support.
- Compliance regime requires vendor-supported security errata (some FedRAMP / DoD profiles).
- Application uses vendor-specific kernel modules or compiled binaries that don't run on AL2023 / Bottlerocket.
- Organization already standardized hardening tooling on a specific vendor OS (existing CIS-hardened base images, config management).

Recommend Bottlerocket as the AWS-canonical default, but **respect a genuine vendor-OS mandate** — surface Bottlerocket as an alternative ("if the mandate is a support contract rather than specific OS features…") without pushing past the customer's organizational requirement.

## CIS Benchmark hierarchy (AWS opinionated position)

```text
CIS Amazon EKS Benchmark        ← CANONICAL — AWS co-authored; EKS-specific controls
        +
CIS <OS> Benchmark              ← Choose ONE — node-level OS controls
   - CIS Bottlerocket Benchmark
   - CIS Amazon Linux 2023 Benchmark
   - CIS Ubuntu Benchmark (Canonical-published)
   - CIS RHEL Benchmark (Red Hat-published)
```

The upstream **CIS Kubernetes Benchmark** applies to the data plane and is what `kube-bench` scans, but the **CIS Amazon EKS Benchmark is the canonical AWS recommendation** for EKS-specific controls (the managed control plane and EKS API auth aren't fully captured by the upstream Kubernetes benchmark).

> **Gotcha:** the **CIS Amazon Linux 2 Benchmark and the CIS AL2023 Benchmark are distinct documents with different controls.** Do not apply AL2 guidance to AL2023 nodes.

## Image Builder pipeline pattern for CIS-hardened AMIs at scale

[EC2 Image Builder](https://aws.amazon.com/imagebuilder/) is the AWS-native solution and is FedRAMP in scope. Two TFC-endorsed approaches:
1. **EKS-optimized AL2023 AMI as base + add hardening components** — preserves EKS components (kubelet, containerd, CNI binaries); layer CIS hardening on top.
2. **Marketplace hardened AMI as base + add EKS components** — preserves the vendor's CIS hardening; install EKS components in a build phase.

Both produce a custom AMI flowing through Image Builder pipelines with automated patch testing and managed AMI rotation. Reference: [Automating AL2023 custom hardened AMI updates](https://aws.amazon.com/blogs/containers/automating-al2023-custom-hardened-ami-updates-for-amazon-eks-managed-nodes).

## EKS Auto Mode trade-off (custom-AMI constraint)

EKS Auto Mode is the lowest-operational-burden option but **does not support custom AMIs** (as of June 2026), and **Cilium CNI is not supported** on it. The compliance question is whether a CIS-hardened *custom* AMI is a **hard regulatory requirement** (auditor mandates specific CIS Level-2 controls baked into the AMI) or an **organizational preference** (auditor accepts AWS-managed AMI with a documented patch cadence):
- **Hard requirement → Auto Mode is not viable.** Use **Bottlerocket on self-managed Karpenter NodePools** (immutable container-OS + custom-AMI control + Karpenter consolidation).
- **Preference → Auto Mode is viable**, and its reduced-permission node IAM (`AmazonEKSWorkerNodeMinimalPolicy`, granting only `eks-auth:AssumeRoleForPodIdentity`) is a genuine security differentiator worth leading with.

> **AL2 currency note (as of June 2026):** EKS **stopped publishing EKS-optimized AL2 AMIs on Nov 26, 2025**; the **AL2 operating system reaches end-of-life on June 30, 2026.** Migrate AL2 nodes to AL2023 or Bottlerocket. Don't conflate the two dates.

## Shared responsibility (Layer 1)

| AWS manages | Customer manages |
|---|---|
| Control-plane OS + patching; EKS-optimized AMI builds; Auto Mode node patching | Node OS hardening on self-managed/custom AMIs; CIS benchmark validation; AMI rotation cadence; bootstrap-container gap closure on Bottlerocket |

## Sources
- [Meet compliance requirements with Bottlerocket](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-compliance-support.html) · [Bottlerocket FIPS AMIs](https://docs.aws.amazon.com/eks/latest/userguide/bottlerocket-fips-amis.html)
- [Validating the EKS-optimized Bottlerocket AMI against the CIS Benchmark](https://aws.amazon.com/blogs/containers/validating-amazon-eks-optimized-bottlerocket-ami-against-the-cis-benchmark)
- [Automating AL2023 custom hardened AMI updates for EKS managed nodes](https://aws.amazon.com/blogs/containers/automating-al2023-custom-hardened-ami-updates-for-amazon-eks-managed-nodes)
- [EC2 Image Builder](https://aws.amazon.com/imagebuilder/) · [EKS-Optimized Accelerated AMIs](https://docs.aws.amazon.com/eks/latest/userguide/eks-optimized-amis.html) · [EKS AL2 AMI deprecation FAQ](https://docs.aws.amazon.com/eks/latest/userguide/eks-ami-deprecation-faqs.html)
- [NIST CMVP](https://csrc.nist.gov/projects/cryptographic-module-validation-program) (verify FIPS module status before quoting)
