# PlatformCluster Deletion Ordering

## Known Issue: EIP Stuck on Deletion (NAT Gateway Dependency)

When a PlatformCluster composite is deleted, Crossplane fires delete on all composed resources **in parallel**. This causes a race condition between the NAT Gateway and its associated EIP:

1. Crossplane deletes NATGateway and EIP simultaneously
2. EIP deletion calls `DisassociateAddress` → fails because NAT Gateway still holds the association
3. AWS returns `AuthFailure` (misleading — actually means "operation not valid while NAT Gateway exists")
4. NAT Gateway MR may disappear from the cluster (upjet async delete removes finalizer after initiating delete) while the AWS resource is still being deleted
5. EIP retries indefinitely until the NAT Gateway is fully gone in AWS

### Root Cause

Crossplane compositions do not support delete ordering. Unlike Terraform's dependency graph, all composed resources are deleted concurrently via Kubernetes garbage collection (`foregroundDeletion`). The upjet-based providers use async deletion — they remove the managed resource finalizer after **initiating** the cloud delete, not after **confirming** the resource is gone.

### Impact

- EIP gets stuck in `CannotDeleteExternalResource` state for 2-5 minutes (until NAT Gateway finishes deleting in AWS)
- If the provider loses credentials during this window (e.g., PodIdentityAssociation deleted), the EIP becomes permanently stuck
- In worst case, the NATGateway MR is removed from the cluster while the AWS NAT Gateway persists → orphaned cloud resource

### Fix: Usage Resource for Deletion Ordering

Add a `Usage` resource to the composition that declares "NATGateway uses EIP", blocking EIP deletion until the NAT Gateway is gone:

```yaml
- name: natgw-uses-eip
  base:
    apiVersion: protection.crossplane.io/v1beta1
    kind: Usage
    spec:
      replayDeletion: true
      of:
        apiVersion: ec2.aws.upbound.io/v1beta1
        kind: EIP
        resourceSelector:
          matchControllerRef: true
      by:
        apiVersion: ec2.aws.upbound.io/v1beta1
        kind: NATGateway
        resourceSelector:
          matchControllerRef: true
```

With `replayDeletion: true`, once the NATGateway is deleted, the Usage is removed and Crossplane replays the EIP deletion — avoiding the garbage collector backoff delay.

### Implemented Usage Resources

All added to `templates/composition.yaml`:

| Name | Protected (of) | Used By (by) | Reason |
|---|---|---|---|
| `natgw-uses-eip` | EIP | NATGateway | Cannot disassociate EIP while NAT GW exists |
| `route-uses-igw` | InternetGateway | Route | Cannot detach IGW while routes reference it |
| `route-uses-natgw` | NATGateway | Route | Cannot delete NAT GW while private route references it |
| `rta-uses-rt` | RouteTable | RouteTableAssociation | Cannot delete RT with active associations |
| `cluster-uses-subnets` | Subnet | EKS Cluster | Cluster ENIs hold subnet references |
| `cluster-uses-vpc` | VPC | EKS Cluster | Cannot delete VPC with attached cluster |

### Deletion Order (enforced by Usages)

```
RouteTableAssociations → RouteTables
Routes → InternetGateway
Routes → NATGateway → EIP
EKS Cluster → Subnets → VPC
EKS Cluster → VPC
```

### Workaround (Without Usage)

If Usage resources are not available (requires Crossplane 1.14+), the EIP will eventually self-heal once the NAT Gateway finishes deleting in AWS (~2-5 minutes). Ensure the Crossplane EC2 provider retains its credentials (PodIdentityAssociation) throughout the entire deletion process.

## References

- [Crossplane Deletion Pitfalls](https://www.cecg.io/blog/crossplane-deletion-management) — Comprehensive guide on deletion policies and Usage resources
- [Composition Dependency and Ordered Creation (Issue #2072)](https://github.com/crossplane/crossplane/issues/2072) — Original issue requesting dependency ordering
- [Dependencies handling on composite deletion (Issue #2212)](https://github.com/crossplane/crossplane/issues/2212) — Multi-provider deletion ordering
- [Introduce Usage type for ordered deletion (Issue #3393)](https://github.com/crossplane/crossplane/issues/3393) — Usage resource design
- [Crossplane Usage Docs](https://docs.crossplane.io/latest/managed-resources/usages/) — Official Usage API reference
- [Crossplane Deletion Policies](https://oneuptime.com/blog/post/2026-02-09-crossplane-deletion-policies/view) — Configuring deletion behavior
