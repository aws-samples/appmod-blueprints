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

The capability flags are set on the cluster in your platform config. **This platform now
enables KRO + ACK on the hub by default** (`config.yaml` hub block):

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

> To **disable** a capability on a cluster, set its `enabled: false` (or omit the block —
> the XRD default is `false`). Spokes do not get KRO/ACK unless their per-cluster entry
> opts in.

### What Managed ACK provides

Managed ACK bundles the ACK service controllers whose upstream service is **Generally
Available** — `iam`, `s3`, `rds`, `dynamodb`, `lambda`, `eks`, and many more — so those
AWS resources can be managed as Kubernetes custom resources without operating the
controllers yourself.

> **Scope note:** non-GA ACK controllers are not part of the managed set. A consumer that
> needs one installs it as its own GitOps addon (self-managed); it coexists with Managed
> ACK because they reconcile different CRD groups. That is a **consumer** concern,
> documented by whichever workload needs it — not by this capability-enablement guide.

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

## References

- [EKS ACK Capability](https://docs.aws.amazon.com/eks/latest/userguide/ack.html)
- [EKS Capabilities ArgoCD Setup](./EKS-Capabilities-ArgoCD-Setup.md)
