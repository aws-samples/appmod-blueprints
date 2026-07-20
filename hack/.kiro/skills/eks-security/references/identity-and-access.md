# Layer 2 — Identity & Access on EKS

Two distinct concerns: **pod-level IAM** (how a pod gets AWS credentials) and **cluster-level access** (how an IAM principal maps to Kubernetes RBAC).

## Pod-level IAM — EKS Pod Identity vs IRSA

**The 2026 AWS recommendation: EKS Pod Identity is the recommended approach for new workloads; IRSA remains a fully supported alternative.** Reference: [EKS Pod Identity simplifies IAM permissions](https://aws.amazon.com/blogs/aws/amazon-eks-pod-identity-simplifies-iam-permissions-for-applications-on-amazon-eks-clusters).

| Mechanism | Recommendation | Why / when |
|---|---|---|
| **EKS Pod Identity** | **Recommended for new workloads** | Reuse one IAM role across clusters without per-cluster trust-policy edits; role session tags for ABAC; centralized management via the EKS API (no OIDC provider per cluster); the **only** mechanism on EKS Auto Mode; preferred for new add-ons (e.g., ASCP integration). |
| **IRSA (IAM Roles for Service Accounts)** | **Fully supported alternative** — the right choice in specific cases | OIDC federation; required on **AWS Fargate** and **Windows nodes**, with **SDKs that don't yet support Pod Identity**, for **direct OIDC federation to roles in workload accounts**, and on **EKS Anywhere / ROSA / self-managed Kubernetes** (Pod Identity is EKS-only). Keep existing IRSA; migrate at the next major refactor if desired. |

> **Wording discipline (verified against AWS docs):** Do **not** call IRSA "legacy." The [EKS Best Practices: Multi-Account Strategy](https://docs.aws.amazon.com/eks/latest/best-practices/multi-account-strategy.html) states: *"EKS Pod Identities are the recommended approach for new workloads on supported node types, while IRSA remains a fully supported alternative."* The word "legacy" in AWS docs refers to the `aws-auth` ConfigMap, not IRSA.

> **Hard limit (verified):** EKS Pod Identity supports **up to 5,000 associations per cluster**, and this is a **hard limit not raiseable via Service Quotas**. For workloads exceeding it: consolidate roles, use IRSA for the overflow, or split across clusters. IRSA has no equivalent association limit. Reference: [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html).

Fine-grained scoping and at-scale management: [Session policies for EKS Pod Identity](https://aws.amazon.com/blogs/containers/session-policies-for-amazon-eks-pod-identity) · [Managing Pod Identities at scale with Argo CD and ACK](https://aws.amazon.com/blogs/containers/how-to-manage-eks-pod-identities-at-scale-using-argo-cd-and-aws-ack).

## Cluster-level access — EKS Access Entries (replaces `aws-auth` ConfigMap)

The `aws-auth` ConfigMap is **deprecated** and fragile (single point of failure; manual edits cause lockouts; no API auditability). **EKS Access Entries (the Cluster Access Management / CAM API) is the canonical replacement:**
- Maps an IAM principal → Kubernetes RBAC via the EKS API, **auditable in CloudTrail**.
- Supports AWS-managed access policies — the four you manually associate with human/CI principals are `AmazonEKSClusterAdminPolicy`, `AmazonEKSAdminPolicy`, `AmazonEKSEditPolicy`, `AmazonEKSViewPolicy`. AWS now publishes **26+** access policies in total (including `AmazonEKSAdminViewPolicy`, secret-scoped policies, and purpose-specific/auto-attached ones for Auto Mode, Hybrid Nodes, Insights, Backup, and EKS Capabilities like ACK/ArgoCD/kro) — see the full list in [access-policy-permissions](https://docs.aws.amazon.com/eks/latest/userguide/access-policy-permissions.html).
- Requires a supported EKS platform version — confirm against the [Platform version requirements](https://docs.aws.amazon.com/eks/latest/userguide/platform-versions.html) table for the customer's Kubernetes version before quoting a specific minimum.
- **New clusters should use Access Entries exclusively — do not configure the `aws-auth` ConfigMap.**

Per the [EKS Best Practices: Cluster Access Management](https://docs.aws.amazon.com/eks/latest/best-practices/cluster-access-management.html): *"ConfigMap-based access management (aws-auth ConfigMap) is deprecated and replaced by the Cluster Access Management (CAM) API. For new EKS clusters, implement the CAM API to manage cluster access."*

> **Migration gotcha:** the `aws-auth` → Access Entries migration has a brief lockout-risk window. Execute it in a planned change window with `kubectl` access pre-validated and a break-glass admin principal confirmed. The cluster supports both mechanisms during transition (`API_AND_CONFIG_MAP` authentication mode).

## Preventive governance — EKS IAM condition keys (enforce config via SCPs)

For multi-account orgs, enforce cluster-configuration guardrails **proactively** with EKS IAM condition keys in IAM policies / **AWS Organizations SCPs** — so a non-compliant cluster can't be created in the first place, rather than being caught by a post-deployment audit (all commercial Regions, no charge).

> **Map each key to the exact action(s) it applies to — this matters for correctness.** A condition key placed on an action it does **not** apply to is **vacuously true** (not evaluated), so the SCP silently fails to restrict and you get a false sense of enforcement. Per the [EKS Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonelastickubernetesservice.html#amazonelastickubernetesservice-policy-keys):

| Condition key | Enforces | Applies to action(s) |
|---|---|---|
| `eks:encryptionConfigProviderKeyArns` | Customer-managed KMS key for envelope encryption | `CreateCluster`, `AssociateEncryptionConfig` |
| `eks:kubernetesVersion` | Only approved (supported, non-EOL) versions | `CreateCluster`, `UpdateClusterVersion` |
| `eks:endpointPublicAccess` / `eks:endpointPrivateAccess` | Private-only API endpoint posture | `CreateCluster`, `UpdateClusterConfig` |
| `eks:deletionProtection` | Deletion protection on production clusters | `CreateCluster`, `UpdateClusterConfig` |
| `eks:controlPlaneScalingTier` | Control-plane scaling tier | `CreateCluster`, `UpdateClusterConfig` |
| `eks:zonalShiftEnabled` | Zonal shift for HA | `CreateCluster`, `UpdateClusterConfig` |

To fully enforce a guardrail you must scope the SCP `Condition` to **every** action that can set the attribute (e.g. cover both `CreateCluster` *and* `UpdateClusterConfig` for endpoint privacy, else a later `UpdateClusterConfig` can flip a compliant cluster to public). This makes the security baseline (private endpoint, CMK encryption, supported version) an org-wide *guardrail* instead of a per-cluster checklist item. Reference: [EKS cluster governance with IAM condition keys (Apr 2026)](https://aws.amazon.com/about-aws/whats-new/2026/04/amazon-eks-iam-condition-keys/).

## Cross-account access (Pod Identity role chaining)

Both mechanisms do cross-account access, with different trade-offs — pick by dimension, not "Pod Identity is better":
- **EKS Pod Identity** uses **IAM role chaining** (a Pod Identity role in the cluster account assumes a target role in the resource account): **no OIDC provider to manage in each remote account** (simpler at multi-account scale), but two hops and a ~59-min session TTL. Reference: [EKS Pod Identity cross-account access](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-eks-pod-identity-cross-account-access/).
- **IRSA** can **directly federate** into a role in another account (single hop, configurable longer TTL), but requires the cluster's **OIDC provider to be registered in each remote account**.

Per [EKS Best Practices: Multi-Account](https://docs.aws.amazon.com/eks/latest/best-practices/multi-account-strategy.html) and [cross-account-access](https://docs.aws.amazon.com/eks/latest/userguide/cross-account-access.html): Pod Identity simplifies management at scale; IRSA offers direct single-hop federation. Choose Pod Identity when you want to avoid per-account OIDC setup; IRSA when you need direct federation / longer sessions.

## Shared responsibility (Layer 2)

| AWS manages | Customer manages |
|---|---|
| The Pod Identity agent + EKS API auth plane; CloudTrail recording of Access Entry changes | IAM role least-privilege; service-account → role associations; RBAC bindings via access policies; the aws-auth → Access Entries migration; break-glass access |

## Sources
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html) · [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity simplifies IAM permissions (blog)](https://aws.amazon.com/blogs/aws/amazon-eks-pod-identity-simplifies-iam-permissions-for-applications-on-amazon-eks-clusters) · [Session policies for Pod Identity](https://aws.amazon.com/blogs/containers/session-policies-for-amazon-eks-pod-identity)
- [EKS Cluster Access Management / Access Entries](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html) · [Best Practices: Cluster Access Management](https://docs.aws.amazon.com/eks/latest/best-practices/cluster-access-management.html) · [Platform versions](https://docs.aws.amazon.com/eks/latest/userguide/platform-versions.html)
- [EKS Best Practices: Multi-Account Strategy](https://docs.aws.amazon.com/eks/latest/best-practices/multi-account-strategy.html) (Pod Identity vs IRSA framing)
