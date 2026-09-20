# Multi-tenancy & Multi-Account Isolation

A first-class security area in the AWS EKS Best Practices guide. The question is how strongly tenants (teams, customers, environments) must be isolated — which drives whether you isolate *within* a cluster or *across* clusters/accounts.

## Soft vs hard multi-tenancy

- **Soft multi-tenancy** — trusted tenants (e.g. internal teams) share a cluster, isolated by Kubernetes constructs. Acceptable when a tenant escaping its boundary is a low-likelihood, low-impact risk.
- **Hard multi-tenancy** — untrusted/adversarial tenants, or strict regulatory isolation (cross-tenant PHI / cardholder / federal data). Kubernetes alone does **not** provide a hard security boundary between tenants sharing a control plane — escalate to **cluster-per-tenant** and/or **account-per-tenant**.

> **Rule of thumb:** if a cross-tenant breach would be a reportable compliance event (PHI/cardholder/federal data leaking across tenants), treat it as hard multi-tenancy → separate clusters/accounts, not just namespaces. This is an escalation trigger (see `engagement-and-response.md`).

## In-cluster isolation controls (soft multi-tenancy)

Layer these; each compounds:
- **Namespaces per tenant** — the basic unit of scoping.
- **RBAC** — least-privilege Roles/RoleBindings scoped to the tenant namespace; no cluster-wide grants. Map IAM principals via **EKS Access Entries** (Layer 2).
- **Network policy default-deny** — per-namespace, allowlisting only required flows (VPC CNI native); **Security Groups for Pods** for network-layer isolation between sensitive and non-sensitive pods (Layer 3).
- **Pod Security Admission `restricted`** per namespace (Layer 3).
- **Resource quotas + LimitRanges** — prevent a noisy/hostile tenant from starving others (a availability-isolation control).
- **Node isolation** — dedicate node pools to sensitive tenants (taints/tolerations + `nodeSelector`, or separate Karpenter NodePools) so workloads of different trust levels don't share a kernel. Recall: containers share the host kernel, so co-tenancy on a node is a shared-fate boundary.
- **Separate namespaces for secrets** (see `encryption-and-secrets.md`).

## Cross-cluster / multi-account isolation (hard multi-tenancy)

- **Cluster-per-tenant** — strongest in-AWS-account isolation; separate control planes remove the shared-control-plane risk.
- **Account-per-tenant (multi-account)** — the strongest isolation AWS offers: separate IAM blast radius, separate quotas, separate billing, account-level SCP guardrails. AWS's recommended pattern for strict regulatory tenant isolation. Use AWS Organizations + a landing-zone pattern; manage fleet access centrally.
- Trade-off: operational overhead and cost rise with isolation strength — match the isolation model to the actual threat/compliance requirement, not the maximum.

## Shared responsibility (multi-tenancy)

| AWS manages | Customer manages |
|---|---|
| Control-plane isolation per cluster; account-level isolation primitives (Organizations, SCPs, IAM) | Tenancy model choice (soft/hard, in-cluster vs multi-account); namespace/RBAC/NetworkPolicy/quota design; node isolation; mapping the model to the compliance requirement |

## Sources
- [EKS Best Practices: Multi-tenancy](https://docs.aws.amazon.com/eks/latest/best-practices/multitenancy.html) · [EKS Best Practices: Multi-Account strategy](https://docs.aws.amazon.com/eks/latest/best-practices/multi-account-strategy.html)
- [EKS Best Practices: Security](https://docs.aws.amazon.com/eks/latest/best-practices/security.html) (multi-tenancy + multi-account areas)
