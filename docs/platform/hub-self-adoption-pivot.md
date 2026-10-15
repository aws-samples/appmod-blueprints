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
> `adoption-policy`. Two options were considered: (a) let the hub-side graph
> **recreate** them, or (b) adopt them with `adoption-fields`.
>
> **⚠️ Live validation (2026-10-11) REFUTES plan (a) recreate.** While kind's copies
> still exist, the hub's ACK tries to **create** fresh SGs and EC2 rejects the
> duplicate group-name within the same VPC → the child goes `ACK.Terminal=True`
> with `Resource already exists` and **never syncs**. The adoption-complete gate
> then (correctly) blocks forever. The same happened to the `OpenIDConnectProvider`
> (`EntityAlreadyExists: Provider with url … already exists`). **Conclusion: the
> ingress SGs AND the OIDC provider MUST carry true adoption (`adopt-or-create` +
> `adoption-fields`), not recreate.** This makes the retain/adoption fix on those
> three nodes a **pivot blocker**, not merely a `task destroy` nicety (see
> Deliverable #3).

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

## Live validation (2026-10-11, Workshop Studio event)

Ran the **LIVE stop-mode pivot** (`task hub:pivot PIVOT_DRY_RUN=false
PIVOT_DETACH_MODE=stop PIVOT_CONFIRM=yes`) on a running PEEKS event (fresh account,
`kind-kro-ack`). Driven on the IDE; hub observed with participant creds.

**What passed (the core of the design — validated):**
- **Confirm gate works.** The first run without `PIVOT_CONFIRM=yes` **refused**
  (`✗ Refusing live pivot without PIVOT_CONFIRM=yes`) and mutated nothing — fail-closed.
- **Stop-first ordering works.** The kind control-plane container was `docker stop`ed
  (ended `Exited (137)`, still registered → recoverable) *before* the hub applied the
  manifest, so only the hub reconciled — no dual-manager window.
- **Clean-projection manifest works.** The serialized spec carried only the
  pre-created VPC/subnets + hub config (no finalizers/applyset/kro labels).
- **Adopt-in-place of the live cluster works — the critical result.** The real EKS
  cluster stayed `ACTIVE` with its original creation timestamp (never recreated), and
  the hub's `clusters.eks` child adopted it `status=ACTIVE, ResourceSynced=True`.
  **21/24 kro-owned children adopted**: cluster 1/1, access entries 4/4, IAM roles
  11/11, pod-identity associations 5/5.
- **Adoption-complete gate is correctly fail-closed.** The hub instance stayed
  `IN_PROGRESS` and the gate never reached GO because 3 children could not sync, so
  kind was **never discarded** — exactly the intended safety behavior.

**What failed — and the decisive finding (3/24 children):**
- The 2 ingress `SecurityGroup`s and the `OpenIDConnectProvider` went
  `ACK.Terminal=True` / `already exists` — ACK tried to **create** them (they lack
  `adopt-or-create`) and collided with kind's still-live copies. This **refutes the
  "recreate" plan** for the SGs (EC2/IAM reject duplicates) and promotes true adoption
  of those three nodes to a **pivot blocker** (Deliverable #3, re-scoped below).

**End state left on the event:** kind **stopped** (recoverable via `docker start`),
hub as sole manager of the adopted resources, real cluster + spokes healthy. No
destructive action taken; the risky retain-delete of the hub-side CR was deliberately
NOT performed (finalizer hazard — requires the Deliverable #3 fix first).

### Re-run attempt after the Deliverable #3 fix (2026-10-11) — why in-place validation is not possible on an already-provisioned event

After implementing the SG/OIDC `adopt-or-create` fix, I attempted to drive the same
event's 3 stuck children to GREEN by applying the fixed `ekscluster.kro.run` RGD to the
live hub. **This cannot be validated in-place on a provisioned event**, for a structural
reason worth recording:

- The event's RGD is reconciled by an **ArgoCD ApplicationSet-managed** app
  (`kro-clusters-rgds-hub-peeks-hub`) with **`selfHeal: true`**, sourced from the
  **event's provisioning branch** (which predates #1033). A `kubectl apply` of the fixed
  RGD is **reverted by selfHeal within the resync window** — faster than kro recreates a
  deleted child, so freshly-rendered children are born from the *reverted* (pre-fix) RGD.
- Two approaches were tried and both lose to selfHeal: (a) apply-and-nudge — ACK terminal
  CRs do **not** auto-requeue on an annotation-only change (known behavior), so the
  children stay terminal; (b) apply-then-delete/recreate — selfHeal restores the pre-fix
  RGD before kro re-renders, so the recreated SG has `adoption-policy=None` and the
  recreated OIDC has `adopt-or-create` **but no `adoption-fields`** (confirming the
  event-branch RGD is missing both halves of the #1033 fix).
- Disabling selfHeal on the child app is **reverted by the parent ApplicationSet**;
  disabling it on the ApplicationSet would stop reconciliation of **all** cluster RGDs on
  a shared workshop hub — too intrusive for a validation.

**All mutations were AWS-safe and left the event no worse than before:** the deleted SG
child CRs had empty `Status.ID` (ACK finalizer no-op) and were `retain`-annotated
defensively; the real ingress SGs, the EKS cluster (original creation time), and both
spokes remained intact. Net state == pre-attempt (21/24, same 3 terminal).

**Faithful validation of 24/24 GREEN = a fresh deploy from this branch** (RGD correct
from t=0 → children born with `adopt-or-create` [+ OIDC `adoption-fields`], no selfHeal
fight), or repointing the event's addons source at #1033. The in-place re-run did,
however, independently **re-confirm the fix is necessary and correctly targeted**: the
live event-branch RGD lacks SG `adopt-or-create` and OIDC `adoption-fields`, which is
exactly why those 3 children are terminal.

### Fresh-deploy re-run (2026-10-12, event built from #1033) — SG/OIDC fix confirmed; new fleet-identity defect found

Provisioned a **fresh** Workshop Studio event whose hub carries #1033 from t=0 (content
branch `test/hub-pivot-event` → appmod fork branch `feat/peeks-agent-instance-hub-pivot`,
= `feat/peeks-agent-instance` + #1033). Ran the LIVE stop-mode pivot on the full
agent-platform (#926) hub (14 kro-owned children on the `peeks-hub` instance, vs the
earlier simpler hub's 24).

**✅ Deliverable #3 confirmed end-to-end.** The two ingress `SecurityGroup`s adopted by
`(group-name, vpc-id)` (`ACK.ResourceSynced=True`), the OIDC provider synced — the old
event's 3 terminal "already exists" children are **gone**. **8/14 adopted** (2 SG + 1
OIDC + 4 access-entries + 1 role). Real `peeks-hub` cluster stayed `ACTIVE` (original
creation time, never recreated).

**❌ Blocker #1 (IAM scoping, separate follow-up).** The remaining 6 are all `eks:`
resources (cluster + 5 pod-identity-associations), each failing identically:
`AccessDeniedException … peeks-hub-ack-capability-role … not authorized to perform
eks:DescribeCluster / eks:DescribePodIdentityAssociation on …/cluster/peeks-hub`. The
hub ACK capability role is provisioned to manage **spokes**, not to **self-manage the
hub cluster**. `adopt-or-create` is necessary but not sufficient — a follow-up must
grant that role `eks:Describe*`/pod-identity reads on the hub cluster ARN
(Deliverable #9).

**🔴 Blocker #2 (THE fleet-identity defect — now fixed).** The instant the pivot adopted
`EksCluster/peeks-hub`, the hub's own ArgoCD cluster secret flipped
`fleet_member: control-plane → spoke`, and seconds later the hub's `clusters-kro-*` apps
deletion-marked the spoke `EksclusterWithVpc` parents (cascading to their `EksCluster`
children). ArgoCD was **exonerated** by live evidence — the `clusters-kro` apps stayed
`Synced` and still *wanted* the spokes (`requiresPruning=None`); the appset's
deletion-safety guards (`create-update`, no `resources-finalizer`, `prune:false`,
`preserveResourcesOnDeletion:true`) all held. The delete came from **kro** after the hub
dropped out of the `clusters-kro` matrix generator, whose first generator selects
`matchLabels{fleet_member: control-plane}` (`gitops/bootstrap/clusters-kro.yaml`). The
real spoke EKS clusters survived only because the kro cascade was itself wedged on the
same `eks:` AccessDenied (Blocker #1).

**Root cause:** `fleet_member` was **hardcoded `spoke`** in the `EksCluster` RGD
(`rg-eks.yaml`) — both the direct `argocdSecret` label (hub path) and the fleet-secret
`addons` blob. On self-adoption the hub reconciled its own `EksCluster` and overwrote the
`control-plane` label that `hub:claim` had set.

**Fixes added to #1033 (both pivot-safety fixes):**
1. **`fleetMember` schema field** (root cause). `rg-eks.yaml` gains
   `fleetMember: string | default="spoke"`; both hardcoded sites become
   `${schema.spec.fleetMember}`. Threaded through the wrapper RGD `rg-eks-vpc.yaml`
   (schema + EksCluster passthrough) and the `clusters-kro` chart
   (`clusters.yaml`, default `spoke`); `hub:claim` now sets `fleetMember: control-plane`.
   Spokes are unchanged (default `spoke`); the hub keeps `control-plane` through
   self-adoption → it stays in the matrix → spokes are never pruned.
2. **Applyset scoping / spoke-integrity guard** (defense-in-depth) in `hub:pivot`. The
   task now snapshots the pre-existing spoke `EksclusterWithVpc`/`EksCluster` instances
   and **fails closed** (aborts + `docker start` kind) the instant any of them acquires
   a `deletionTimestamp` during adoption — both inside the adoption gate loop and as a
   final pre-detach assertion. kind is never discarded while a spoke is being pruned, so
   a future regression cannot silently cascade into spoke deletion.

## Risks / open questions

- **✅ RESOLVED — KRO applyset ownership on re-apply.** Re-applying the instance on the
  hub created a fresh KRO graph that adopted the existing children via
  `adopt-or-create` without recreating the cluster or fighting a foreign applyset. The
  hub instance converged to `IN_PROGRESS→(21/24 synced)` purely gated by the SG/OIDC
  issue, not by any applyset GC conflict. This was the primary unknown — now observed OK.
- **🟢 RESOLVED — ingress SecurityGroups + OIDC provider.** Now carry
  `adopt-or-create` (Deliverable #3): the SGs adopt by `(group-name, vpc-id)` with no
  adoption-fields (ACK `getSecurityGroupID`), the OIDC provider by a derived ARN
  `adoption-fields`. Verified against the ec2/iam controller source. A hub re-apply
  will adopt all three in place instead of hitting EC2/IAM "already exists", so the
  gate can reach GO (24/24). Re-run on a live kind+hub to confirm end-to-end GREEN.
- **Bootstrap window.** kind must survive until the hub ACK/KRO capabilities are
  healthy (already sequenced in `install`). `hub:pivot` is a **separate, explicit**
  task — not wired into `install`.
- **Teardown interaction.** `task destroy` currently assumes kind manages the hub.
  After a completed pivot the hub self-manages; `destroy` must delete the hub-side
  EksCluster CR (on the hub). Needs a follow-up to the destroy path (Deliverable #5).

## Deliverables (incremental)

1. ✅ `docs/platform/hub-self-adoption-pivot.md` (this doc).
2. ✅ `task hub:pivot` in `cluster-providers/kind-kro-ack/Taskfile.yaml`, with
   `PIVOT_DRY_RUN=true` default + a `PIVOT_CONFIRM=yes` live gate + the
   adoption-complete go/no-go. Detach via `PIVOT_DETACH_MODE` (`stop` default,
   recoverable | `delete`), no graceful CR delete → no finalizer / no AWS Delete.
3. 🟢 **`rg-eks.yaml` adoption fix — IMPLEMENTED (the pivot blocker).** True adoption
   added to the two nodes that live-failed to sync, verified against the ACK
   controller source:
   - ingress `SecurityGroup`s (http/https): `adopt-or-create` with **NO
     `adoption-fields`**. ACK's ec2 `SecurityGroup` find (`getSecurityGroupID`)
     resolves the live `sg-id` from a `(group-name, vpc-id)` filter when `Status.ID`
     is unset — both are already in `spec` — so the same manifest CREATES on a fresh
     cluster and ADOPTS on pivot. (This refines the earlier "AWS-ID/filter
     adoption-fields" guess: no runtime id injection is needed; recreate is still
     refuted — EC2 rejects the duplicate group-name.)
   - `OpenIDConnectProvider`: `adopt-or-create` + ARN `adoption-fields`. OIDC find
     uses `GetOpenIDConnectProvider` (ARN-keyed) and cannot match by a spec
     attribute, so the ARN must be supplied. It is derivable with a CEL scheme-strip:
     `arn:<partition>:iam::<accountId>:oidc-provider/<issuer.replace("https://","")>`
     (kro enables `ext.Strings()`), mirroring the existing cni-metrics-helper Policy
     adoption-fields pattern. On a fresh cluster the ARN does not exist →
     `NoSuchEntity` → ACK creates.
   This makes `hub:pivot` able to reach GO (24/24) on a re-run.

   ✅ **Destroy-path hardening — IMPLEMENTED.** `deletion-policy:
   "${schema.spec.deletionPolicy}"` now also on the `ekscluster` (`Cluster`) node and
   all six `AccessEntry` nodes (`access-entry`, `-argocd-capability`, `-admin`,
   `-admin-instance`, `-argocd-capability-access`, `-ack-capability-access`), matching
   every Role/PIA/SG node. This only affects a graceful `task destroy` with
   `deletionPolicy=retain` (so a retained hub is never issued `DeleteCluster` /
   access-entry deletes); it is independent of the pivot, which never graceful-deletes.
4. ✅ (fallback path) ec2 `adoption-fields` generation helper for `EksclusterWithVpc`
   (`scripts/pivot-adopt-ec2.sh`).
5. ⬜ destroy-path follow-up (post-pivot teardown targets the hub-side CR).
6. ✅ Validation on a live kind+hub — **done 2026-10-11** (see "Live validation"
   above): adopt-in-place + stop-first + gate fail-closed all confirmed; surfaced the
   #3 blocker. The remaining re-run to GREEN depends on #3.
7. 🟢 **Fleet-identity fix — IMPLEMENTED (pivot-safety fix #1).** `fleetMember` schema
   field on `rg-eks.yaml` (default `spoke`) replaces the hardcoded `fleet_member: spoke`
   in both the `argocdSecret` label and the fleet-secret `addons` blob; threaded through
   `rg-eks-vpc.yaml` (schema + EksCluster passthrough) and `clusters.yaml` (chart,
   default `spoke`); `hub:claim` sets `control-plane`. Stops the hub self-adoption from
   relabelling the hub `control-plane→spoke` and pruning the spokes (fresh-deploy
   finding, 2026-10-12).
8. 🟢 **Applyset scoping / spoke-integrity guard — IMPLEMENTED (pivot-safety fix #2).**
   `hub:pivot` snapshots pre-existing spoke instances and fails closed (abort + restart
   kind) the instant any acquires a `deletionTimestamp` during adoption — in the gate
   loop and as a final pre-detach assertion. Defense-in-depth behind #7.
9. 🟢 **Hub ACK capability-role self-manage — RE-IMPLEMENTED IN THE RGD, gated to
   control-plane (Blocker #1 fix).** The grant lives as a `SelfManageHub` **inline policy
   on `${schema.spec.name}-ack-capability-role` in `rg-eks.yaml`**, built with a CEL
   **ternary that returns the whole map** (`${ cond ? {3 keys} : {2 keys} }` — space-form
   standalone, plain CEL, no `Maps.merge` extension and no `${{` opener), **gated on
   `schema.spec.fleetMember == "control-plane"`**. Render-validated on a real kro cluster:
   the control-plane instance gets `{AssumeWorkloadRoles, ManageIRSARoles, SelfManageHub}`,
   the spoke instance gets `{AssumeWorkloadRoles, ManageIRSARoles}` (no `SelfManageHub`),
   all policy docs valid JSON with ARNs correctly interpolated. It grants
   `eks:DescribeCluster` /
   `UpdateClusterConfig` / `UpdateClusterVersion` / `ListPodIdentityAssociations` /
   `CreatePodIdentityAssociation` + tag reads on the hub's own cluster ARN, and
   `eks:Describe/Update/DeletePodIdentityAssociation` + tag reads on
   `podidentityassociation/${name}/*`.
   - **Why control-plane-only:** only the hub self-adopts its own `EksCluster` into its
     own kro graph, so only the control-plane capability role needs rights on its OWN
     cluster ARN. A spoke never self-adopts (its control plane is hub-managed), so a spoke
     capability role with `eks:*` on its own cluster would be a pure least-privilege
     over-grant — hence the `fleetMember` gate.
   - **Why the RGD, not the Taskfile (corrects the first attempt):** on event
     `38cd39ef` (2026-10-12) the imperative `aws iam put-role-policy ack-self-manage-hub`
     in `hub:create-mgmt-roles` **silently did not survive** — the role is itself a
     kro/ACK-managed IAM Role (`app.kubernetes.io/managed-by: kro`), so ACK reconciles it
     back to its RGD-defined `inlinePolicies` on every pass, stripping any out-of-band
     policy. Live proof: post-rollback the role carried only `AssumeWorkloadRoles` +
     `ManageIRSARoles`, and the adopted `cluster.eks/peeks-hub` stayed
     `AccessDeniedException … eks:DescribeCluster`. The imperative block is removed; the
     RGD inline policy is durable. `ManageIRSARoles` already grants `iam:PutRolePolicy`
     on `role/${name}-*` (matches this role), so no new IAM surface is required.
   AWS's managed `AmazonEKSACKPolicy` deliberately withholds self-reference on the
   cluster's own ARN, so this explicit, hub-scoped grant is what lets the adopted
   `cluster.eks` + pod-identity children reach `synced` → the gate reaches GREEN.
   Independent of #7/#8.
10. 🟢 **Automatic pivot on install — IMPLEMENTED.** New gated `install:pivot` task runs
    `hub:pivot` (LIVE, `PIVOT_DETACH_MODE=stop`) as the **final** step of
    `kind-kro-ack:install`, so a fresh bootstrap self-adopts the hub and detaches from
    the kind bootstrap cluster automatically. Gated by `HUB_PIVOT_ON_INSTALL` (default
    `true`; set `false` to keep kind-managed and pivot manually later). Placed at the end
    of the generic hub install — **before** the workshop/consumer enables any spoke — so
    the auto-pivot runs with no spokes present (cannot perturb them), and the whole
    workshop tail (cloudfront, overlay wiring, spokes:enable, idc, ray) runs afterward
    against the self-managed hub (none of it needs kind). Fail-closed via #8's
    spoke-integrity guard; depends on #9 for the adoption gate to pass.
11. 🟢 **Hub-instance anti-prune + deleter forensics — IMPLEMENTED (14:07 regression).**
    On event `38cd39ef` the hub's OWN `EksCluster/peeks-hub` instance acquired a
    `deletionTimestamp` ~3 min after adoption, and the gate kept polling the terminating
    CR for the full 27 min because it only watched the spokes + child-sync, never the hub
    instance itself. Two changes:
    - **Prevention:** the adopted `hub-instance.json` now carries
      `argocd.argoproj.io/compare-options: IgnoreExtraneous` +
      `argocd.argoproj.io/sync-options: Prune=false`. The hub instance is created
      imperatively by the pivot (not from git), so an auto-sync/self-heal ArgoCD App with
      pruning enabled is the prime suspect; these annotations neutralise that path.
    - **Detection + forensics:** a `hub_intact` check runs every gate iteration and, the
      instant a `deletionTimestamp` appears, dumps `capture_hub_deleter_forensics`
      (instance managed-fields, events mentioning the hub, every ArgoCD App tracking an
      `EksCluster` with its `autoPrune/selfHeal` flags + per-resource `status`/
      `requiresPruning`, all ApplicationSets, the instance's labels/annotations/ownerRefs,
      and the hub cluster-secret `fleet_member`), then fails closed (abort + restart
      kind). The next run **names the deleter** instead of guessing. If the anti-prune
      annotations prove insufficient, the forensics identify the real actor for a
      follow-up fix.

12. 🟢 **Non-mutating adoption — the hub instance never owns the registration Secret
    (`createArgocdClusterSecret:"false"` on the hub-side manifest).**
    Root cause of the spoke deletion-marking, isolated with @pnz1990 on kro `0.9.4-eks-1`:
    kro adopts a pre-existing Secret **in place** (same UID), so re-asserting the instance is
    not itself the deleter. The real coupling is ownership. On the hub the ArgoCD registration
    Secret (`argocd/<hub>`, carrying the `fleet_member: control-plane` label the `clusters-kro`
    matrix selects on) is created by `hub:seed` (`kubectl apply`) and kept current by the
    fleet-secret `ExternalSecret` — it is **never a kro-owned object there** (verified live:
    `managedFields` = `kubectl-client-side-apply` + `externalsecrets…/fleet-secret-<hub>`, no
    kro labels). `hub:claim` sets `createArgocdClusterSecret:"true"` only for the **kind**
    bootstrap (ESO cannot register the hub to itself yet — chicken-and-egg), which renders the
    `argocdSecret` node into **kind's** `argocd` namespace. If the adopted hub-side instance
    kept `"true"`, its fresh kro applyset would pull `argocd/<hub>` INTO the hub EksCluster
    graph, coupling the fleet-identity label to the very instance being adopted — the churn
    that empties the matrix and deletion-marks the spokes.

    **INVARIANT:** the hub registration Secret and its `fleet_member: control-plane` label are
    invariant across the pivot — never deleted, recreated, re-derived, or momentarily absent.
    Adoption transfers **management**, not fleet identity; kind is only suspended
    (`docker stop`), never mutated.

    **Fix:** the adopt projection forces `.spec.createArgocdClusterSecret = "false"` on the
    hub-side manifest (alongside `fleetMember=control-plane` / `deletionPolicy=retain`). The
    hub instance stays on the fleet-secret path (`clusterConfigK8sSecretFleet` /
    `clusterConfigSecretFleet` → ESO) and never materialises the registration Secret, so the
    matrix never empties. kind keeps `"true"` for its own bootstrap; nothing flips on the hub.
    This is the RGD's documented mainline (`createArgocdClusterSecret default="false"`, the
    Crossplane/Terraform spoke flow), not a workaround — `"true"` on the hub is the exception.

    **Caveat (@pnz1990).** On the fleet path the hub-side instance also renders
    `clusterConfigSecretFleet` (ACK `secretsmanager` Secret `<hub>/config`). ACK does not push a
    changed `secretString` to an existing Secrets Manager secret, so `<hub>/config` keeps the
    content `hub:seed`/kind wrote — ESO keeps building the same registration Secret (good for
    continuity). If the fleet blob (e.g. `fleet_member` derived from `fleetMember`) must land, a
    one-time `aws secretsmanager put-secret-value` is required. Tracked for validation.

    (The earlier snapshot/restore "continuity guard" is superseded by this root-cause fix and
    was shelved — it enforced the invariant behaviourally; `createArgocdClusterSecret:"false"`
    prevents the perturbation at the source.)
