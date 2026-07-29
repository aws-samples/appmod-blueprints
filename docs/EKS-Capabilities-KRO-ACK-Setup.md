# EKS Capabilities: Managed KRO + Managed ACK Setup

This document describes how to enable the **Managed KRO** and **Managed ACK** EKS
Capabilities on this platform, alongside the existing **Managed ArgoCD** capability
(see [`EKS-Capabilities-ArgoCD-Setup.md`](./EKS-Capabilities-ArgoCD-Setup.md)).

## Overview

**EKS Capabilities** are AWS-managed platform controllers that run *outside* the
cluster — AWS handles installing, patching, and scaling them. Three types exist:

| Type | What it provides |
|---|---|
| `ARGOCD` | Managed Argo CD for GitOps (already enabled on the hub) |
| `KRO` | Kube Resource Orchestrator — serves `ResourceGraphDefinition`s that compose many resources behind one custom CRD |
| `ACK` | AWS Controllers for Kubernetes — manage AWS resources (IAM, S3, RDS, …) as Kubernetes custom resources |

> **This platform already wires all three declaratively.** The `platform-cluster`
> Crossplane Composition contains `Capability` managed resources (provider-aws-eks
> v2.6.1) for `KRO`, `ACK`, and `ARGOCD`, each gated by
> `spec.capabilities.<type>.enabled` via a `function-cel-filter` step, plus the IAM
> roles they assume (`capabilities.eks.amazonaws.com` trust). Enabling a capability is
> therefore a **config toggle**, not new infrastructure.

## Enable KRO + ACK

Set the capability flags on the cluster in your platform config. For the hub:

```yaml
# config.yaml  (hub cluster block)
hub:
  clusterName: "<unique-cluster-name>"
  # ...
  capabilities:
    kro:
      enabled: true
    ack:
      enabled: true
    # argocd is enabled separately (needs IDC config — see the ArgoCD capability doc)
```

This flows into the `PlatformCluster` claim
(`gitops/abstractions/crossplane/platform-cluster/templates/claim.yaml` →
`spec.capabilities`), which un-gates the KRO/ACK `Capability` MRs in the Composition.
`hub:seed` waits for the `Capability` MRs to become `Ready`.

### What ACK provides (and what it does *not*)

Managed ACK bundles the ACK service controllers whose upstream service is **Generally
Available** — this includes `iam`, `s3`, `rds`, `dynamodb`, `lambda`, `eks`, and
[50+ others](https://aws-controllers-k8s.github.io/community/docs/community/services/).

> **Pre-GA controllers are NOT in Managed ACK.** A controller must be GA upstream to be
> bundled. Newer, `v1alpha1` controllers (for example the **Lambda MicroVM** controller,
> `lambdamicrovms.services.k8s.aws`) are **not** included and must be **self-managed**
> (installed as their own Helm chart / GitOps addon) until they graduate. Managed ACK and
> a self-managed controller **coexist** cleanly because they reconcile different CRD
> groups — there is no conflict as long as two controllers never own the same service.

## Consumer: Flow D — Lambda MicroVM Agent Sandbox (downstream repo)

The first consumer of Managed KRO + Managed ACK on this platform is **Flow D** in the
**`sample-open-agentic-platform`** repo (where the Dark Factory / Agent Sandbox lives).
Flow D adds a second Agent-Sandbox substrate — an **AWS Lambda MicroVM** — using:

- **Managed KRO** — a single `MicrovmSandbox` `ResourceGraphDefinition` that composes all
  the primitives behind one CRD.
- **Managed ACK** — the **GA** `iam` (Role) + `s3` (Bucket) controllers the MicroVM image
  and instance depend on.
- **Self-managed ACK** — the **pre-GA** `lambdamicrovms` controller (`MicrovmImage` +
  `Microvm`), installed as its own addon in that repo because Managed ACK can't bundle it
  yet. When it goes GA, the self-managed addon is removed and Managed ACK adopts it — the
  RGD is unchanged.

So this repo owns the **platform capabilities** (Managed KRO + Managed ACK); the downstream
repo owns the **pre-GA controller + the RGD + the sandbox shim**. See that repo's
`docs/dark-factory/README.md` §4.5 (Flow D).

## Verification

1. Confirm the Capability MRs are Ready:
```bash
kubectl get capability.eks.aws.upbound.io -A
```

2. Confirm the capabilities exist at the AWS level:
```bash
aws eks list-capabilities --cluster-name <cluster-name> --region <region>
# expect type ARGOCD (existing) + KRO + ACK once enabled
```

3. Confirm the KRO + ACK CRDs are served on the cluster:
```bash
kubectl get crd | grep -E "kro\.run|services\.k8s\.aws"
# kro.run/ResourceGraphDefinition + the enabled ACK service groups (iam/s3/…)
```

## Troubleshooting

### Capability MR stuck (not Ready)
- Check the capability IAM role trust is `capabilities.eks.amazonaws.com` and the role
  ARN selector matches (`matchLabels.capability: kro|ack`).
- `aws eks describe-capability --cluster-name <c> --capability-name kro|ack` for the
  AWS-side status/health.

### ACK custom resource not reconciling
- Confirm the ACK capability is `ACTIVE` and the specific service controller (e.g. `s3`)
  is part of the managed set (GA services only).
- For a **pre-GA** service (e.g. `lambdamicrovms`), it will *never* appear under Managed
  ACK — it must be self-managed downstream (see Flow D above).

## References

- [EKS ACK Capability](https://docs.aws.amazon.com/eks/latest/userguide/ack.html)
- [ACK community services (GA list)](https://aws-controllers-k8s.github.io/community/docs/community/services/)
- [EKS Capabilities ArgoCD Setup](./EKS-Capabilities-ArgoCD-Setup.md)
