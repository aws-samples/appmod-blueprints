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
3. STOP kind FIRST (before adopting), to avoid both kind's and the hub's kro/ACK
   controllers reconciling the same AWS resources at once:
     docker stop $(kind node containers for this cluster)
   This halts kind's kube-apiserver + kro/ACK controller pods but PRESERVES etcd in
   the container filesystem — fully recoverable with `docker start`. The live AWS
   resources (EKS cluster, roles, PIAs, OIDC, SGs) need no controller to keep
   running, so the brief no-manager window between stop and hub-adopt is harmless.
4. Apply the EksCluster manifest on the HUB context. With kind stopped, ONLY the hub
   reconciles. Because every child carries adopt-or-create, the hub's ACK adopts the
   existing AWS resources in place — no recreate, no 409, no dual-manager conflict.
   KRO rebuilds the instance graph; readyWhen gates on the live cluster being ACTIVE
   (already true) so it converges fast.
5. Wait (THE safety gate): hub-side EksCluster instance Active && EVERY kro-owned
   child CR synced (ACK.ResourceSynced/Ready/Synced = True). This is the single
   go/no-go — the hub must demonstrably own every resource before kind is discarded.
6. DETACH outcome — PIVOT_DETACH_MODE:
     stop   (DEFAULT): leave kind STOPPED. Fully recoverable (`docker start`) while
            the procedure is still being validated. kind's CRs still exist in its
            (stopped) etcd but no controller is running them, so no AWS delete fires.
     delete: `kind delete cluster` — removes the node containers (docker rm -f),
            taking etcd + controllers atomically. No deletionTimestamp is ever set on
            the CR, so NO finalizer runs and ACK never issues an AWS Delete. Permanent.
   On gate FAILURE: `docker start` the kind nodes to resume kind management (abort);
   nothing on the hub or kind is deleted.
7. Idempotency: a re-run is a no-op (adopt-or-create reconciles; a stopped/absent kind
   is tolerated).
```

### Why this ordering is safe — stop kind first, never `kubectl delete` the CR

Stopping kind **before** adopting removes the only real hazard of a dual-manager
window: with kind's apiserver + kro/ACK controllers down, only the hub reconciles the
adopted resources, so the two controller sets never fight over the same AWS objects.
The AWS resources are stable without any controller, so the stop→adopt gap is benign.

The pivot also deliberately **avoids** the graceful-delete path. `deletion-policy` (the
#855 `retain` enabler) only takes effect when a CR is gracefully deleted (`kubectl
delete` sets a deletion timestamp → ACK's finalizer calls the AWS Delete API). Neither
`stop` (leave kind halted) nor `delete` (`kind delete cluster`, which destroys the
container outright) ever sets a deletion timestamp on the CR — so there is **no
deletion event, no finalizer, no AWS Delete call**. The AWS resources survive, and the
hub already adopted them in steps 4–5, so the hub is their sole manager.

> **This is why the `retain` coverage gap does NOT block the pivot.** `deletion-policy:
> "${schema.spec.deletionPolicy}"` is wired on the Roles/PIAs/OIDC/Capabilities but
> NOT on the `Cluster`, ingress `SecurityGroup`s, or `AccessEntry`s. That gap would
> only bite a **graceful** `kubectl delete` of the CR — which the pivot never does.
> Stopping or discarding kind sidesteps `deletion-policy` entirely.
>
> **Absolute rules during the pivot window** (this is where the missing `retain`
> WOULD be dangerous):
> 1. NEVER `kubectl delete` the kind `EksCluster` CR (or its namespace) — fires
>    finalizers → with the gap, the real cluster would be deleted.
> 2. NEVER run `task destroy` mid-pivot — same graceful-delete hazard.
> 3. To ABORT, `docker start` kind — do NOT `kubectl delete` the hub-side instance to
>    "undo" an adopt (same finalizer hazard, now on the hub side).
>
> **Fail-closed rule for `hub:pivot`:** the go/no-go is the *adoption-complete* check in
> step 5 (hub instance Active + all kro-owned children synced), NOT a retain audit.
> If the hub has not fully adopted → **abort** (leave/restart kind), never detach.
> The dry-run reports this and mutates nothing.
>
> The `retain`-coverage fix (deliverable #3) is still worth landing, but for the
> **`task destroy` graceful-teardown path**, not for the pivot.

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
   first** (`PIVOT_DRY_RUN=true` prints the hub-side manifest + the adoption-complete
   go/no-go, mutates nothing). Detach = `kind delete cluster` (not a graceful CR
   delete), so no retain audit is needed on the pivot path.
3. `rg-eks.yaml` retain-coverage fix: add `deletion-policy:
   "${schema.spec.deletionPolicy}"` to the `ekscluster`, ingress `SecurityGroup`,
   and `AccessEntry` nodes. **Decoupled from the pivot** — this hardens the
   `task destroy` graceful-teardown path (so an intentional `retain` destroy does
   not delete those three node types); the pivot itself does not depend on it.
4. (fallback path) ec2 `adoption-fields` generation helper for `EksclusterWithVpc`
   (`scripts/pivot-adopt-ec2.sh`).
5. destroy-path follow-up (post-pivot teardown targets the hub-side CR).
6. Validation on a live kind+hub (the only way to de-risk the KRO applyset question).
