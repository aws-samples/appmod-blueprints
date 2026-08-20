# Identity and Multi-Tenancy

How the platform gives one identity across all tools, credential-free AWS access to workloads, and isolation between teams sharing the platform.

## Keycloak — unified SSO

Keycloak is the identity backbone. Every platform tool — Backstage, ArgoCD, Argo Workflows, Kargo, Grafana, GitLab, JupyterHub, Ray Dashboard — federates authentication through Keycloak via OIDC/SAML.

- **One login, access everything.** A user authenticates once; the session propagates across the toolchain ("Log in via Keycloak").
- **Decoupled identity.** Identity management is separated from the portal and the CI/CD tools, so auth policy changes in one place.
- **Why it matters for adoption.** Per-tool credentials are friction; SSO removes it and centralizes access control.

## Workload identity — EKS Pod Identity / IRSA

Workloads (and platform controllers like ACK) get AWS permissions without stored credentials. Per the EKS Best Practices Guide, **EKS Pod Identity is the recommended approach for new workloads**, while **IRSA remains a fully supported alternative** (not deprecated, no end-of-support) — and is the correct choice in specific scenarios:

| Approach | Use when |
|----------|----------|
| **EKS Pod Identity** (recommended for new workloads) | New workloads on supported node types — simpler association (no per-cluster IAM OIDC provider to manage), session tags, role chaining, native cross-account access, scales past OIDC-provider quotas; it's also the default credential mechanism on EKS Auto Mode |
| **IRSA** (fully supported alternative) | Running on AWS Fargate or Windows nodes, or with SDKs that don't yet support Pod Identity; you already have OIDC/IRSA in place and there's no compelling reason to migrate working deployments; you need direct OIDC federation to roles in workload accounts |

In the platform's application abstraction, the `dp-service-account` component (a kro composition, or an OAM component on KubeVela) creates a service account bound to a scoped IAM role and wires the Pod Identity association — so a developer requesting "access to my DynamoDB table" gets a least-privilege role automatically, never an access key. Controllers (ACK) likewise use Pod Identity / IRSA, so no AWS keys live in the cluster.

## Multi-tenancy

The platform is shared; tenants are isolated by construction:

- **Per-team namespaces** (e.g. `team-rust`, `team-java`) with RBAC.
- **One repo per component/app**, so GitOps boundaries match ownership.
- **Scoped IAM** — each workload's role grants only the resources it declared (via `component-iam-policy` + `dp-service-account`).
- **Spoke clusters** separate dev and prod entirely (own VPC + cluster); the hub never runs tenant workloads.
- **Configuration tiers / PSA / policy** — templates and OAM definitions enforce pod-security and resource standards so tenants can't drift below the baseline.

## Putting it together

A tenant team logs into Backstage (Keycloak), orders a pipeline and resources via templates (landing in their namespace + repos), and their workloads run with scoped Pod Identity roles on a spoke cluster — all without the platform team issuing a single credential or running a single manual provisioning step.
