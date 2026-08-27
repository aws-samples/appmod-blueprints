# Design: `ack-pod-identity` addon (Option 4)

Status: **DEPLOYED AND VALIDATED ON THE HUB** (2026-08-25). Spokes NOT done.

Hub outcome: app `ack-pod-identities-peeks-hub` Synced/Healthy, all 6 ACK resources
`ACK.ResourceSynced=True`, `/keycloak` and `/backstage` both return 200, LBC reconciling
normally, and **external-dns fixed** (was failing `no EC2 IMDS role found`, now reports
"All records are already up to date").

Note on the rollout: a staged rollout (external-dns only, via a fleet-config cluster
overlay) was pushed but did NOT take effect — ArgoCD synced the app from its cached copy of
the overlay repo before re-reading it, so lbc + external-dns + keycloak deployed at once and
the IAM role swap happened immediately. The correct order is to push the overlay AND confirm
ArgoCD has picked it up BEFORE flipping `addonsRepoRevision`. The outcome was safe only
because the policies had been compared beforehand (lbc byte-identical, keycloak a strict
superset) — preparation, not sequencing, is what saved it.

Related issues: **#775** (hub self-adoption / CAPI pivot — the adoption semantics
established here answer its step 3), **#813** (duplicate IAMRoleSelector scope → infinite
ACK reconcile loop; why multi-acct is now the SOLE owner of IAMRoleSelectors),
**#647** (GitOps diff preview on PRs — natural home for the drift test).

Scope was REDUCED as a result: only **4** identities migrate (eso, lbc, external-dns,
keycloak), not 8. The other 4 RGD blocks (adotCollector, cloudwatchObservability,
cniMetricsHelper, kyvernoPolicyReporter) are dead code — delete, do not migrate.

## NEW REQUIREMENT found during implementation: IAMRoleSelector / CARM

Not in the original design. ACK resolves which IAM role to assume **per namespace + API
group** via `IAMRoleSelector`. Live selectors exist only for `peeks-spoke-dev`,
`peeks-spoke-prod`, `ray-system` and `default` — there is **no** selector for a hub
namespace covering `iam.services.k8s.aws` / `eks.services.k8s.aws`. Without one the CRs
are created and then **silently never reconciled** (no error, no events).

This is why the adoption probe had to run in the `peeks-spoke-dev` namespace to work.

Consequences, both implemented:
- CRs go into a namespace named after the **target cluster** (not `crossplane-system` as
  the crossplane entry uses), matching the RGD convention that the existing selectors are
  keyed on.
- The chart ships its own `IAMRoleSelector`s (wave -5) for the iam+eks groups, pointing at
  `<prefix>-cluster-mgmt-{iam,eks}` — the same roles `multi-acct` uses (both verified to
  exist). SUPERSEDED: the chart no longer ships selectors at all -- see "Selector
  ownership" below.

## Files added / changed

| File | Status |
|---|---|
| `gitops/addons/charts/ack-pod-identity/` (Chart, values, 5 templates, README) | NEW |
| `gitops/addons/registry/core.yaml` → `ack_pod_identities` entry | CHANGED |
| `platform/validation/pod-identity/test_chart_drift.py` | NEW |
| `Taskfile.yaml` → `test-pod-identity-drift` | CHANGED |

Verification performed (no cluster mutation):
- `helm template` of the chart renders 18 resources; all policy/assume-role documents parse
  as JSON; external-dns correctly targets `kube-system/external-dns-sa`; PIAs carry no
  `adoption-fields`.
- `helm template` of `platform-charts/appset-chart` against the registry produces the
  `ack-pod-identities` ApplicationSet with the correct hub destination and a selector that
  is the exact complement of `pod-identities`.
- Drift test passes, and fails as intended when drift is injected (verified with an
  escalated `iam:*` statement and a wrong service account).

## Goal

Provide an ACK-backed mirror of the existing `crossplane-pod-identity` addon so that
addon Pod Identity Associations on `provider: kro-ack` clusters are created by an
ArgoCD-generated app (with native per-addon `enable_*` gating), instead of being
created unconditionally by the `EksCluster` KRO RGD.

This resolves:
- The `ResourceInUseException` 409 conflict (ACK RGD vs Crossplane app on the same SA).
- The lack of per-addon conditionality on the RGD path (RGD can't see `enable_*`).
- The `external-dns` SA mismatch (RGD targets `external-dns/external-dns`; the controller
  actually runs as `kube-system/external-dns-sa`).

## Convention alignment

The repo already uses **one chart/app per backend** for the crossplane/kro-ack duality
(`abstractions/crossplane` vs `abstractions/kro`; `clusters-crossplane.yaml` vs
`clusters-kro.yaml`). Option 4 follows that convention. A single parameterized chart
(Option 5) was rejected as a new, inconsistent pattern.

## Selection by `provider` label

| App | selector | Applies to |
|-----|----------|------------|
| `crossplane-pod-identity` (existing) | `provider NotIn ["kro-ack"]` | crossplane/legacy clusters |
| `ack-pod-identity` (NEW) | `provider In ["kro-ack"]` | kro-ack clusters (hub + kro spokes) |

Prerequisite (fix **B**): kro-provisioned spokes must carry `provider: kro-ack` on their
cluster secret. Today `peeks-spoke-dev/prod` have `provider=""` (empty) because
`<cluster>/config.addons.provider` is empty. Source: the spoke declaration in
fleet-config (GitLab) + the `kro-clusters` values template in appmod-blueprints.

## Single source of truth for policies

`identities` + IAM policy documents live in ONE shared `values.yaml`, consumed by BOTH
charts. Only the rendered CRD kinds differ:

| | crossplane-pod-identity | ack-pod-identity |
|--|--|--|
| Role | `iam.aws.upbound.io/Role` | `iam.services.k8s.aws/Role` |
| Policy | `iam.aws.upbound.io/Policy` | `iam.services.k8s.aws/Policy` |
| Attach | `iam.aws.upbound.io/RolePolicyAttachment` | (ACK: `policies` list on Role) |
| Assoc | `eks.aws.upbound.io/PodIdentityAssociation` | `eks.services.k8s.aws/PodIdentityAssociation` |

## Identity → label → namespace/SA mapping (VERIFIED against live cluster 2026-08-24)

MIGRATE these 4 (enabled in at least one environment, real consumer exists):

| identity | `enable_*` label (gate) | namespace | serviceAccount | notes |
|----------|-------------------------|-----------|----------------|-------|
| eso / external-secrets | enable_external_secrets | external-secrets | external-secrets-sa | enabled control-plane+dev+prod |
| lbc | enable_aws_load_balancer_controller | kube-system | aws-load-balancer-controller-sa | verified live deploy SA |
| external-dns | enable_external_dns | **kube-system** | **external-dns-sa** | FIX A — see below |
| keycloak | enable_keycloak | keycloak | keycloak-config | control-plane only |

DO NOT MIGRATE YET — **disabled addons, NOT dead code** (correction, see below):

| identity | status |
|----------|--------|
| cni-metrics-helper | real registry addon (`observability.yaml:285`), `enable_cni_metrics_helper: false` in control-plane / absent in dev+prod |
| kyverno-policy-reporter | real registry addon (`security.yaml:138`), `enable_kyverno_policy_reporter: false` / absent |
| cloudwatch-observability | gate is `enable_cw_prometheus` (registry entry `cw-prometheus`, `observability.yaml:255`), `false` / absent; `amazon-cloudwatch` ns exists on no cluster |
| adot-collector | no `adot` registry entry, BUT `observability-aws/files/scraper-config.yaml` has an `adot-collector` scrape job and `enable_observability_aws: true` on the hub |

### CORRECTION: these are NOT dead code — migrate them, do not delete

An earlier revision of this doc called these four "dead code to delete". That was wrong.
All four map to real registry addons (or, for adot, to a real scrape target in an enabled
addon); they are merely **disabled in this particular install**, and `enable_*` is
per-environment config that anyone can flip to `true` tomorrow.

The RGD pre-creates their identities **unconditionally** — crude, but deliberate: the
identity exists in advance so that enabling the addon just works. Deleting the RGD blocks
*without* adding the identities to this chart would therefore be a **functional
regression**: enable `cni_metrics_helper` later and the addon comes up with no pod identity,
failing with exactly the `no EC2 IMDS role found` symptom that made external-dns so
annoying to diagnose.

Correct action: **migrate all of them into this chart with `enable_*` gating**, which is
strictly better than the RGD (conditional instead of unconditional).

**Blocked on verification first.** The namespace/serviceAccount owner is NOT established
for two of them: nothing confirms which component actually owns
`amazon-cloudwatch/cloudwatch-agent` (the CloudWatch Observability EKS addon is not
installed — `list-addons` on the hub returns only `aws-mountpoint-s3-csi-driver`) or
`adot-collector-kubeprometheus/adot-collector-kubeprometheus`. Migrating on an assumed
mapping would reproduce the external-dns SA bug exactly. Verify the real SA per addon
before adding these four identities.

### FIX A is a LIVE OUTAGE, not a latent mismatch

The RGD creates the external-dns PIA for `external-dns/external-dns` (wrong namespace AND
wrong SA). The actual controller on the hub is `kube-system/external-dns` with SA
`kube-system/external-dns-sa`. There is **no** association for that SA in AWS, so
external-dns cannot get credentials right now:

```
level=error msg="Failed to do run once: soft error
  records retrieval failed: soft error
  failed to list hosted zones: operation error Route 53: ListHostedZones,
  get identity: get credentials: failed to refresh cached credentials,
  no EC2 IMDS role found, ..."
```

Worth fixing independently of this migration.

### The hub's addon pod identities exist in AWS with NO CR — because their RGD lived in kind

`kubectl get podidentityassociations.eks.services.k8s.aws -A` returns only the
`peeks-spoke-dev-*` / `peeks-spoke-prod-*` set (created by the RGD, namespace = cluster
name) plus ray/cicd ones. The hub's own associations (external-secrets, lbc, keycloak,
external-dns, ...) exist in **AWS only**.

The hub was NOT provisioned without an RGD — its `EksCluster` RGD instance ran **in the
ephemeral bootstrap kind cluster**, which no longer exists. So the AWS resources follow the
**RGD naming convention** while having no CR on the hub. That single fact explains the role
swap documented below: the live roles are `peeks-hub-lbc-role` /
`peeks-hub-external-dns-role` / `peeks-hub-keycloak-config-role` (RGD naming), whereas this
chart uses the crossplane-pod-identity naming (`peeks-hub-LBCPodIdentityRole`, ...). Names
differ → Role/Policy are NOT adopted, they are created new → and because the
PodIdentityAssociation IS adopted (keyed on ns+SA), its `roleARN` gets repointed.

Moving that management onto the hub itself is tracked separately as **issue #775**
(`feat: hub self-adoption — pivot management from ephemeral kind to hub EKS`, CAPI pivot
pattern). Its implementation step 3 — "with `adopt: true` or by setting the correct owner
references so ACK adopts the existing AWS resources instead of recreating them" — is
answered concretely by the per-resource adoption semantics established here (see the
Migration section). Out of scope for this PR.

Bootstrap providers (`provider-aws-iam`, `provider-aws-eks`) STAY in the RGD
(`includeWhen: provider=="kro-ack" && enable_crossplane_aws=="true"`) — genuine
chicken-and-egg, not addon-gated. NOT migrated.

`otel-collector` in the Crossplane chart is DEAD CODE (no matching addon; real addon is
`opentelemetry-operator`, which needs no pod identity). Remove from shared values.

## RGD changes — and the deletion-policy trap (CORRECTED)

Blocks that the new app takes over on kro-ack clusters: externalDns, lbc, keycloakConfig.
The other four (adotCollector, cloudwatchObservability, cniMetricsHelper,
kyvernoPolicyReporter) must be **migrated, not deleted** — see the correction above.

**KEEP externalSecrets for now.** The `ack_pod_identities` registry entry deliberately does
NOT gate `eso`, mirroring `pod_identities` (the hub reuses an existing role for ESO and its
association is bootstrap-owned; spokes enable eso via the env overlay). Taking ESO over
would churn the identity that feeds every secret on the platform. The `eso` identity IS
present in the chart's `values.yaml` (default `enabled: false`), so it can be switched on
per-environment via overlay — remove the RGD `externalSecrets` block only once that is done
and verified.

KEEP also: clusterRole, nodeRole, podIdentityAddon, argocd*, crossplane*Provider
(bootstrap), capability roles, VPC/SG/cluster.

### !! Removing an RGD block DESTROYS the live AWS resource

All 18 `services.k8s.aws/deletion-policy: retain` annotations in `rg-eks.yaml` are
**commented out**, and the live spoke CRs confirm it (`deletion-policy: NOT SET` on
`peeks-spoke-dev-lbc`). ACK's default is to **delete the AWS resource** when the CR is
deleted. So removing a block → KRO deletes the child CR → **ACK deletes the live IAM role
and pod identity association** → the spoke addon loses its credentials. An earlier revision
of this doc said "just remove the blocks", which was dangerously incomplete.

### Why the spokes are harder than the hub

The hub had **no live overlap**: its RGD instance ran in the ephemeral kind cluster, so
nothing on the hub was managing those PIAs when the chart took over. The spokes DO have live
`EksclusterWithVpc` instances actively managing PIAs for the same cluster + namespace +
serviceAccount. Two ACK CRs targeting one association would fight over `roleARN`.

### Safe sequence for the spokes

1. **Compare policies first.** Do NOT assume the hub's happy outcome generalises: there the
   chart's `LBCControllerPolicy` happened to be byte-identical to the live `peeks-hub-lbc`.
   The spokes differ — e.g. `peeks-spoke-dev-external-dns-role` carries
   `peeks-spoke-dev-ack-iam`, not a same-named chart policy.
2. **Add `deletion-policy: retain`** to the blocks about to be removed. Deploy and confirm
   the annotation is present on the live CRs.
3. **Remove the blocks.** CRs disappear; AWS resources are retained, so the addons keep
   working.
4. **Set `addons.provider = "kro-ack"`** in `peeks-spoke-dev/config` and
   `peeks-spoke-prod/config` (Secrets Manager) → the chart is selected and adopts the
   retained resources.
5. Nothing to do for selectors: `multi-acct` already covers both spoke namespaces and the
   chart no longer creates any. See "Selector ownership" below.

Step 3 must precede step 4 so the RGD and the chart never manage the same association
simultaneously. Between the two nothing manages them, but the AWS resources persist
(retained), so there is no outage window.

Also: write `provider` into whatever **seeds** the cluster config (the `kro-clusters` values
template / RGD schema), not just the live secret — otherwise a re-seed silently drops it,
the same failure mode as `overlay_repo_url`.

## Sync ordering / bootstrap safety

Mirror the Crossplane chart:
- Role/Policy at sync-wave -3, attach -2, association -1.
- PreSync CRD-wait hook gating on ACK CRDs
  (`roles.iam.services.k8s.aws`, `podidentityassociations.eks.services.k8s.aws`).
- App itself at registry wave 4 (before consumers lbc/external-dns at wave 5).

## Migration (no downtime on live addons) — ACK adoption pattern

Reuse the adoption pattern established on branch `fix/ack-policy-adoption`
(commit ad7b6603). ACK resources can ADOPT a pre-existing AWS resource instead of
failing create with 409, via two annotations:

```yaml
annotations:
  services.k8s.aws/adoption-policy: adopt-or-create
  services.k8s.aws/adoption-fields: |
    {"arn":"arn:aws:iam::${accountId}:policy/${name}"}   # for Policy (keyed by ARN)
```

Key lessons from that branch:
- For **Policy**, `adopt-or-create` ALONE is insufficient — ACK keys policies by ARN and
  cannot derive it from `spec.name`, so without `adoption-fields` it falls back to
  CreatePolicy → 409 `EntityAlreadyExists`. Always supply the templated ARN.
- Where the ARN is derivable (accountId + name), supply `adoption-fields`; otherwise
  `adopt-or-create` alone surfaces an explicit 409 (acceptable fallback).

Apply to `ack-pod-identity`:
- Role + Policy CRs → `adopt-or-create` + `adoption-fields` (ARN from accountId+name) so
  the app ADOPTS the roles/policies the RGD already created (no 409, no recreate).
- **PodIdentityAssociation** → **RESOLVED, adoption works with `adopt-or-create` ALONE.**
  No `adoption-fields` needed. Proven empirically on 2026-08-24 (probe run + cleaned up):

  1. Pre-created an association out-of-band for an unused SA:
     `aws eks create-pod-identity-association --cluster-name peeks-spoke-dev
      --namespace default --service-account ack-adopt-probe-sa --role-arn <role>`
     → returned `a-w3m2xlndn6z4mzjju`.
  2. Applied an ACK CR with ONLY `adoption-policy: adopt-or-create` (no adoption-fields)
     and `deletion-policy: retain`.
  3. Result: `SYNCED=True` within ~11s and `status.associationID == a-w3m2xlndn6z4mzjju`
     — the SAME id. `aws eks list-pod-identity-associations` showed exactly ONE
     association, i.e. it ADOPTED rather than created a duplicate or 409'd.
  4. Deleting the CR with `deletion-policy: retain` left the AWS association intact
     (verified), so retain is a safe escape hatch.

  Conclusion: ACK's PIA lookup keys on **clusterName + namespace + serviceAccount**
  (`ListPodIdentityAssociations` filters), NOT on the AWS-generated `associationID`.
  This is why PIA differs from Policy — Policy is keyed by ARN and therefore *does*
  require `adoption-fields`. **Zero-downtime cutover is viable**, including adopting the
  hub's CR-less, bootstrap-created associations.

Cutover sequence:
1. Land adoption annotations first (this is what `fix/ack-policy-adoption` already does
   for Policies in rg-eks). 
2. Set `provider=kro-ack` on spokes (fix B) → `ack-pod-identity` app selected.
3. App adopts existing Role/Policy/Association in place.
4. Only then remove the addon PIA blocks from the RGD.

## Coordination with branch `fix/ack-policy-adoption` — DECIDED: build on it

Base branch for this work: **`fix/ack-policy-adoption`** (checked out; HEAD ad7b6603).
That branch already added ACK adoption annotations to the RGD **Policy** blocks
(ack-iam, lbc, keycloak-config, cni-metrics-helper). Option 4 is layered on top:

1. Create `ack-pod-identity` chart (mirror of crossplane-pod-identity) that renders ACK
   `iam.services.k8s.aws` Role/Policy + `eks.services.k8s.aws` PodIdentityAssociation,
   carrying the SAME adoption annotations (adopt-or-create + adoption-fields ARN) so it
   ADOPTS the resources the RGD already created — no 409, no recreate.
2. Add registry entry `ack_pod_identity` with selector `provider In ["kro-ack"]` and
   per-addon `enable_*` gating (mirrors pod_identities valuesObject).
3. Set `provider: kro-ack` on kro spokes (fix B).
4. Verify adoption succeeds, then REMOVE the addon PIA blocks (Role/Policy/Association)
   from the RGD for: externalSecrets, externalDns, lbc, keycloakConfig, adotCollector,
   kyvernoPolicyReporter, cniMetricsHelper, cloudwatchObservability. KEEP bootstrap
   crossplane*Provider blocks + cluster/node/capability infra.

Current RGD state on this branch (confirmed): all 8 addon PIA blocks still present;
Policy adoption annotations present on 4 of them.

## Ship to appmod-blueprints then PR

`~/environment/fleet-config` is seeded FROM appmod-blueprints by `task install`. All
changes (new chart, registry entry, RGD edits, `provider: kro-ack` in the kro-clusters
values template) go into appmod-blueprints source, then a PR. The live fleet-config spoke
declaration also needs `provider: kro-ack`.

## Open items — ALL RESOLVED (2026-08-24)

1. ~~cloudwatch-observability gate label~~ → **`enable_cw_prometheus`** (registry entry
   `cw-prometheus`). Moot: it is `false`/absent everywhere and `amazon-cloudwatch` exists
   on no cluster → block is dead code, delete rather than migrate.
2. ~~adot namespace/SA source~~ → schema fields `addons.adot_collector_namespace` /
   `adot_collector_service_account`, live value `adot-collector-kubeprometheus` for BOTH
   (the earlier guess of `amazon-cloudwatch` was wrong). Moot: **no `adot` registry entry
   exists at all** and the namespace exists nowhere → dead code, delete.
3. ~~ACK PodIdentityAssociation adoption semantics~~ → **RESOLVED FAVOURABLY.**
   `adopt-or-create` alone adopts by clusterName+namespace+serviceAccount; no
   `adoption-fields` required. Full evidence in the Migration section above.
4. ~~Shared values.yaml vs duplicate~~ → **DECISION: duplicate the values, guard with a CI
   drift test.** Rationale: the identity set is only 4 entries, but the IAM policy
   documents are large and identical, so silent drift between the two charts would be a
   security bug. A shared/library chart or symlink is fragile under ArgoCD path-based
   rendering (ArgoCD renders one chart directory; symlinks outside it are not resolved
   reliably). Cheapest robust option is a test asserting the `identities.*.policy.document`
   blocks are byte-identical between `crossplane-pod-identity` and `ack-pod-identity`.

### Additional prerequisite confirmed

Fix **B** is still required and unchanged: `peeks-hub` already carries `provider: kro-ack`,
but `peeks-spoke-dev` and `peeks-spoke-prod` carry `provider: ""` (empty), so they would
NOT be selected by `provider In ["kro-ack"]`. Must be set in the kro-clusters values
template (appmod-blueprints) AND the live fleet-config spoke declaration.

## Selector ownership: multi-acct only (resolved)

Initially this chart shipped its own `IAMRoleSelector`s because the hub was missing from
`multi-acct`'s `clusters` map, and without a selector ACK creates the CRs and then never
reconciles them (silently). That was a stopgap and it duplicated ownership: two selectors
with an identical `(namespace, group)` scope put the ACK controller in an infinite reconcile
loop — empty `status{}`, zero AWS API calls, no events (**issue #813**; identical role ARNs
do not help, the duplicated scope is the bug).

Resolved by making **`multi-acct` the sole owner**: the hub was added to its `clusters` map
and this chart's selector template was deleted outright rather than gated behind a flag.

**INVARIANT: any cluster running this addon must appear in `multi-acct`'s `clusters` map.**

This also unblocks **#775**. An on-hub `EksCluster` instance needs selectors for every ACK
group the RGD uses — measured on the 39 active resources: `eks` (18), `iam` (13), `ec2` (2,
the ingress security groups), `secretsmanager` (2). The hub namespace only ever had `eks`
and `iam` (from this chart's stopgap), so the security groups and secrets would never have
reconciled. `multi-acct` provides all seven groups, including the two that were missing.

Rollout order matters on a live hub, because the app runs with `prune: false`: removing the
selectors from the chart does NOT delete the live ones, so they had to be deleted explicitly
BEFORE multi-acct's arrived, otherwise the duplicate-scope window would have hit the working
hub. Sequence used: push the chart change → delete the 2 orphaned selectors → add the hub to
multi-acct. Between the last two steps the hub briefly has no selectors and its CRs are
unmanaged; that is safe (deletion-policy: retain, and ACK cannot delete anything without
credentials anyway).
