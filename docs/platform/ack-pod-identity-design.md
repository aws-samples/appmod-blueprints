# Design: `ack-pod-identity` addon (Option 4)

Status: **STEPS 1-2 IMPLEMENTED** (chart + registry entry + drift test), verified by
render only — NOT yet deployed. Steps 3-4 (set `provider: kro-ack` on spokes, then strip
the RGD blocks) still pending. All 4 original open items resolved with live evidence
(2026-08-24); see "Open items" at the bottom.

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
  exist). Gated by `iamRoleSelectors.enabled` so it can be turned off if `multi-acct` is
  extended to cover the namespace.

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

DO NOT MIGRATE — dead code, delete from RGD (no consumer on ANY cluster):

| identity | why dead (evidence) |
|----------|---------------------|
| adot-collector | **No `adot` entry in the addon registry at all.** Live PIA targets `adot-collector-kubeprometheus/adot-collector-kubeprometheus` (from schema `adot_collector_namespace`/`_service_account`); that namespace does not exist on hub, spoke-dev or spoke-prod. Same category as `otel-collector`. |
| cloudwatch-observability | Gate label is `enable_cw_prometheus` (registry entry `cw-prometheus`, ns `amazon-cloudwatch`) — set **false** in control-plane, absent in dev/prod. The `amazon-cloudwatch` namespace does not exist on any cluster, and the CloudWatch Observability EKS addon is not installed (`list-addons` on hub returns only `aws-mountpoint-s3-csi-driver`). |
| cni-metrics-helper | `enable_cni_metrics_helper: false` in control-plane, absent in dev/prod. |
| kyverno-policy-reporter | `enable_kyverno_policy_reporter: false` in control-plane, absent in dev/prod. (The `kyverno` ns does exist on spokes, but the reporter addon is off.) |

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

### The hub has NO ACK CRs for its addon pod identities

`kubectl get podidentityassociations.eks.services.k8s.aws -A` returns only the
`peeks-spoke-dev-*` / `peeks-spoke-prod-*` set (created by the RGD, namespace = cluster
name) plus ray/cicd ones. The hub's own associations (external-secrets, lbc, keycloak,
external-dns, ...) exist in **AWS only** — created by the kind/crossplane bootstrap, with
no CR. So on the hub `ack-pod-identity` MUST adopt pre-existing AWS associations. This is
why open item 3 was the gating risk. It is now proven to work.

Bootstrap providers (`provider-aws-iam`, `provider-aws-eks`) STAY in the RGD
(`includeWhen: provider=="kro-ack" && enable_crossplane_aws=="true"`) — genuine
chicken-and-egg, not addon-gated. NOT migrated.

`otel-collector` in the Crossplane chart is DEAD CODE (no matching addon; real addon is
`opentelemetry-operator`, which needs no pod identity). Remove from shared values.

## RGD changes (must accompany, else ACK-vs-ACK 409)

Remove these addon PIA blocks (Role+Policy+Association) from `rg-eks.yaml`:

- **Migrated** (the new app owns them on kro-ack clusters): externalDns, lbc,
  keycloakConfig.
- **Dead code** (no consumer anywhere — just delete, nothing takes over): adotCollector,
  cloudwatchObservability, cniMetricsHelper, kyvernoPolicyReporter.

**KEEP externalSecrets for now.** The `ack_pod_identities` registry entry deliberately does
NOT gate `eso`, mirroring `pod_identities` (the hub reuses an existing role for ESO and its
association is bootstrap-owned; spokes enable eso via the env overlay). Taking ESO over
would churn the identity that feeds every secret on the platform. The `eso` identity IS
present in the chart's `values.yaml` (default `enabled: false`), so it can be switched on
per-environment via overlay — remove the RGD `externalSecrets` block only once that is done
and verified.

KEEP also: clusterRole, nodeRole, podIdentityAddon, argocd*, crossplane*Provider
(bootstrap), capability roles, VPC/SG/cluster.

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
