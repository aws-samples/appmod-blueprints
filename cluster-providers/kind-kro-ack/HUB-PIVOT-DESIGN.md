# Hub Self-Adoption Pivot — Design (issue #775)

> Status: **design / proposal** on branch `feat/hub-self-adoption-pivot`.
> Prereq groundwork landed in **#855** (Class-1 `adopt-or-create` on every
> name/attribute-keyed ACK resource in `rg-eks.yaml`, plus the per-cluster
> `spec.deletionPolicy` retain enabler threaded `clusters.yaml → EksclusterWithVpc
> → EksCluster`). This doc covers the remaining core work: the `hub:pivot` task.

## Goal

Move management of `peeks-hub` from the ephemeral **kind** bootstrap cluster to the
**hub EKS cluster itself**, then `kind delete cluster`. Removes the permanent
kind/EC2 dependency and the ~1h STS-token credential-refresh treadmill (the hub's
in-cluster ACK/KRO run on EKS Pod Identity, never temporary tokens).

## Two findings that shrink the problem vs the issue's generic framing

The issue (and the CAPI-pivot analogy) assume the bootstrap cluster manages
*everything*. In this provider it does not:

1. **kind only ever manages the hub's own `EksCluster` CR.** Spokes are **already
   hub-managed**: `spokes:enable*` just pushes a fleet-config entry; the hub's
   `clusters-kro` ApplicationSet reconciles it and the hub's ACK EKS capability
   creates the spoke. The only `spokes:*` task in this Taskfile is
   `spokes:seed-provider-identity`. So **there is no spoke management to pivot** —
   step 5 of the issue is a no-op here.

2. **On the PEEKS/CDK path the hub VPC is pre-created** (`.hub.network.vpcId` set →
   `hub:claim` applies `kind: EksCluster`, *not* `EksclusterWithVpc`). ACK therefore
   does **not** manage the hub VPC/subnets/NAT/EIP. Every kind-managed hub resource
   is then **Class 1** (name/attribute-keyed), and `adopt-or-create` already landed
   on all of them in #855. The hard **Class 2** ec2 adoption (`adoption-fields` with
   live `vpc-…`/`subnet-…` IDs) is **only** needed on the `EksclusterWithVpc`
   fallback (self-paced without a pre-created VPC).

Net: the primary PEEKS path is a **Class-1-only pivot of a single CR**.

## Inventory of kind-managed hub resources (from `rg-eks.yaml`)

All already annotated `adoption-policy: adopt-or-create` (✅ = #855):

| ACK resource | key | adopt |
|---|---|---|
| `Cluster` (peeks-hub) | name | ✅ |
| `Role` ×N (cluster, node, argocd, external-secrets, adot, kyverno, cni, cw-obs, ack-capability, kro-capability, argocd-capability, crossplane-provider) | name | ✅ |
| `Policy` (cni-metrics-helper) | ARN | ✅ (adoption-fields ARN) |
| `OpenIDConnectProvider` | ARN | ✅ best-effort |
| `AccessEntry` ×N | cluster+principalARN | ✅ |
| `PodIdentityAssociation` ×N | cluster+ns+sa | ✅ |
| `Capability` (ack, kro, argocd) | cluster+name | n/a (`deletePropagationPolicy: RETAIN`) |
| `SecurityGroup` (ingress http/https) | AWS ID | ⚠️ Class 2 (see below) |

> **Caveat — ingress SecurityGroups are Class 2.** `ingressHttpSecurityGroup` /
> `ingressHttpsSecurityGroup` are ec2 (AWS-ID-keyed) and today carry **no**
> `adoption-policy`. They are cheap/stateless (HTTP/HTTPS-from-anywhere on the
> hub VPC) so the pragmatic options are: (a) let the hub-side graph **recreate**
> them (new SG IDs; the ingress annotation `ingress_security_groups` is derived
> from `.status.id`, so KubeVela/ALB re-resolves them) and let kind's retained
> copies be swept, or (b) adopt them with `adoption-fields` like the VPC case.
> Default plan: **(a) recreate** — simplest, and nothing durable keys off the SG ID.

## Pivot algorithm (`task hub:pivot`)

Preconditions (assert, fail-closed): hub EKS `ACTIVE`; hub ACK **and** KRO
capabilities `ACTIVE`; `rg-eks.yaml` + `rg-vpc.yaml` RGDs present & `Active` on the
hub (installed by the normal addons sync); kind reachable.

```
0. hub:kubeconfig                      # private/hub-kubeconfig via aws eks update-kubeconfig
1. Serialize kind's EksCluster/peeks-hub spec (kubectl get -o yaml, strip
   status/metadata.managedFields/uid/resourceVersion/ownerReferences).
2. (EksclusterWithVpc fallback only) read live ec2 IDs from the kind Vpc CR
   .status and generate adoption-fields for VPC/subnets/IGW/NAT/EIP/routetables.
   Skip entirely on the EksCluster (pre-created-VPC) path.
3. Apply the EksCluster manifest on the HUB context. Because every child carries
   adopt-or-create, the hub's ACK adopts the existing AWS resources in place —
   no recreate, no 409. KRO rebuilds the instance graph; readyWhen gates on the
   live cluster being ACTIVE (already true) so it converges fast.
4. Wait: hub-side EksCluster instance Active && all child ACK CRs
   ACK.ResourceSynced=True (reuse the hub:wait-for-* pattern).
5. DETACH from kind (order matters):
     a. patch kind CRs: services.k8s.aws/deletion-policy: retain  (schema field
        spec.deletionPolicy already exists; set it to "retain" and let it
        propagate, OR kubectl annotate the child CRs directly for the transient).
     b. kubectl delete the kind EksCluster CR  → ACK removes the K8s CRs but
        RETAINS the AWS resources (now solely owned by the hub-side CRs).
     c. VERIFY no AWS deletion: re-describe the EKS cluster + roles still exist.
6. kind delete cluster.
7. Idempotency: a re-run is a no-op (adopt-or-create reconciles; delete of an
   absent kind cluster is tolerated).
```

### Why detach is safe — and the gap that makes it NOT safe yet

`deletion-policy: retain` on the kind side is the #855 enabler: deleting a CR with
`retain` orphans the AWS resource instead of calling the AWS Delete API. The hub-side
CR already **adopted** the same AWS resource in step 3, so after detach it is owned by
exactly one manager (the hub).

> **⚠️ Coverage gap (found reading `rg-eks.yaml`).** `deletion-policy:
> "${schema.spec.deletionPolicy}"` is wired on the **Roles, PodIdentityAssociations,
> OIDCProvider and Capabilities**, but **NOT** on the `Cluster`, the ingress
> `SecurityGroup`s, or the `AccessEntry`s (those carry `adopt-or-create` only).
> With `deletionPolicy=retain` set on the instance, those three node types would
> still default to **delete** — so deleting the kind `EksCluster` CR would **delete
> the real EKS cluster**. This is the single most dangerous step.
>
> Therefore the detach must guarantee retain on **every** live child ACK CR. Two ways:
> 1. **RGD change (preferred):** add `services.k8s.aws/deletion-policy:
>    "${schema.spec.deletionPolicy}"` to the `ekscluster`, `ingressHttp/Https
>    SecurityGroup`, and all `AccessEntry` nodes, then `kubectl patch` the instance
>    `spec.deletionPolicy: retain` and let KRO re-propagate before delete.
> 2. **Task-level authoritative annotate:** `kubectl annotate` every live child ACK
>    CR with `deletion-policy: retain` directly before delete (bypasses the RGD).
>
> **Fail-closed rule for `hub:pivot`:** before any delete, enumerate every live ACK CR
> owned by the kind `EksCluster` and assert each carries `deletion-policy: retain`.
> If any is missing → **abort**. The dry-run reports this go/no-go and mutates nothing.

### Crossplane re-point (issue step 6)

The hub already runs its own Crossplane providers (bootstrapped by
`hub:bootstrap-crossplane-identity` on EKS Pod Identity). Nothing in the Crossplane
chain targets the kind cluster — kind only ever held the EksCluster CR. So "re-point
Crossplane to the hub" is **already true**; the only requirement is that the hub's
provider PIAs are healthy before kind is deleted (they are, post-install).

## Risks / open questions (to validate on a live kind+hub)

- **KRO applyset ownership on re-apply.** Re-applying the same `EksCluster` instance
  on the hub creates a *fresh* KRO instance (new uid) owning child CRs via
  ownerReferences. Must confirm KRO's applyset GC on the hub does not fight the
  adopted children, and that the hub-side instance reaches `Active` without
  recreating the cluster. **Primary thing to test.**
- **OIDC provider adoption** needs a CEL scheme-strip of the issuer URL (noted
  "best-effort" in #855). Verify it adopts rather than 409s on the hub.
- **ingress SecurityGroups**: confirm recreate (plan A) leaves no dangling ALB
  listener references; otherwise implement adoption-fields (plan B).
- **Bootstrap window.** kind must survive until the hub ACK/KRO capabilities are
  healthy (already sequenced in `install`). `hub:pivot` is a **separate, explicit**
  task — not wired into `install` — until proven.
- **Teardown interaction.** `task destroy` currently assumes kind manages the hub.
  After a pivot the hub self-manages; `destroy` must delete the hub-side EksCluster
  CR (on the hub) rather than the kind one. Needs a follow-up to the destroy path.

## Deliverables (incremental)

1. `HUB-PIVOT-DESIGN.md` (this doc).
2. `task hub:pivot` in `cluster-providers/kind-kro-ack/Taskfile.yaml`, **dry-run
   first** (`PIVOT_DRY_RUN=true` prints the hub-side manifest + the detach plan +
   the retain go/no-go, mutates nothing).
3. `rg-eks.yaml` retain-coverage fix: add `deletion-policy:
   "${schema.spec.deletionPolicy}"` to the `ekscluster`, ingress `SecurityGroup`,
   and `AccessEntry` nodes (closes the gap above so a `retain` detach is safe).
4. (fallback path) ec2 `adoption-fields` generation helper for `EksclusterWithVpc`
   (`scripts/pivot-adopt-ec2.sh`).
5. destroy-path follow-up (post-pivot teardown targets the hub-side CR).
6. Validation on a live kind+hub (the only way to de-risk the KRO applyset question).
