# Per-cluster Crossplane `env-config` — Design & Decisions

Status: implemented on `feature/agent-platform-shapirov` (Jul 2026). Live-validated on
`peeks-hub` + `spoke-dev` + `spoke-prod`.

## Objective

Every cluster (hub + every spoke, including future ones) must expose a **cluster-scoped
Crossplane `EnvironmentConfig` named `env-config`** carrying that cluster's ambient
metadata, in a consistent location, so downstream Compositions (e.g. the OAP
`aws-service-identity` / pod-identity Composition) resolve cluster facts via
`spec.environment` without callers passing them.

Required data (all mandatory):
`clusterName`, `region`, `vpcId`, `privateSubnetIds`, `publicSubnetIds`
(plus `clusterSecurityGroupId` as an existing extra consumed by the RDS composition).

Acceptance: `kubectl get environmentconfig env-config -o jsonpath='{.data}'` returns all
of the above on the hub and each spoke.

## Final design (one line)

Each cluster's provisioner writes the VPC facts as **annotations on that cluster's ArgoCD
cluster-secret**, and a **plain `EnvironmentConfig` Helm manifest** (addon) renders
`env-config` from those annotations. Pure declarative GitOps — **no Job, no runtime AWS
calls, no Pod Identity, no terraform**. ArgoCD keeps it in sync (self-healing).

### Data flow

```
                         cluster-secret annotations                 env-config addon
                         (aws_vpc_id, aws_private_subnet_ids,        (plain EnvironmentConfig
                          aws_public_subnet_ids,                      manifest, values from
                          aws_cluster_security_group_id)             those annotations)
 HUB   ── kind Taskfile hub:seed-secret ──►  hub argocd secret  ──►  env-config on hub
 SPOKE ── platform-cluster Composition  ──►  spoke argocd secret ─►  env-config on spoke
```

- `clusterName` / `region` come from the `fleet-secret` static annotations (always present).
- `vpcId` / subnet ids / `clusterSecurityGroupId` come from the provisioner (above).
- Consumers may resolve by **name** (`env-config`) or by the **`env=<clusterName>` label**
  (preserved for the existing `function-environment-configs` Selector, keyed to `spec.deploy`).

## Key decisions (with rationale)

### D1. A plain manifest fed by cluster-secret annotations — NOT a discovery Job
An earlier iteration used a Job that self-discovered VPC facts from the AWS API via Pod
Identity. **Rejected after live testing** because it is fundamentally fragile:
- Pod Identity injects credentials at **pod admission**; a Job pod admitted before the
  `PodIdentityAssociation` was active never got creds (`restartPolicy: OnFailure` restarts
  the container in the *same* pod → never recovers). `restartPolicy: Never` helps, but…
- As an ArgoCD **Sync hook**, a stuck Job (`backoffLimit` not exhausted) wedges the sync
  operation, which then blocks applying the fix — a self-deadlock.
- Runtime discovery adds an IAM identity + ordering dependency for data that is already
  known at provision time.

The data is known when the cluster is created, so we inject it then. Declarative, no
ordering, self-healing.

### D2. Inject at provision time, via the provisioner that creates each cluster
Both hub and spokes are created by the **same `platform-cluster` Composition** — the hub
via the kind bootstrap cluster's Crossplane, spokes via the hub's Crossplane. So the
composition is the natural injector.

- **Spokes**: the composition (running on the hub, which reconciles the spoke
  `PlatformCluster`s) writes the annotations to the spoke's argocd cluster-secret — the
  same `Object` it already used to publish `aws_vpc_id`.
- **Hub**: the composition that created it ran on the **ephemeral kind cluster**
  (provider-kubernetes `default` ProviderConfig = `InjectedIdentity` = kind), and the
  hub's *real* cluster-secret is the seed secret the kind Taskfile creates directly on the
  hub. The hub is **not** re-imported as a self-managed `PlatformCluster` (only spokes are).
  So the composition-on-kind cannot write the hub's real secret. The **kind provider's
  `hub:seed-secret` task IS the hub's provisioner**, so it stamps the same annotations
  (values discovered via AWS CLI in that bootstrap task — appropriate, it's imperative
  one-time bootstrap, not a runtime controller).

  Same *outcome* (cluster-secret annotations → env-config), different injector per cluster
  type — inherent, because the hub and spokes have different provisioners.

Rejected hub alternatives: (B) composition-on-kind writing to the hub via a hub-targeted
ProviderConfig — extra shared-composition conditional; (C) re-importing the hub as a
self-managed `PlatformCluster` — the composition would try to re-adopt the hub's existing
VPC/EKS. Both riskier than (A).

### D3. Gate on `enable_crossplane`, NOT a new `enable_env_config` label
`env-config` is a **Crossplane-intrinsic** resource (an `EnvironmentConfig` consumed by
Crossplane Compositions) — meaningless without Crossplane. **Spoke enablement is
consumer-owned**: OAP (the consumer) sets `crossplane: true` in its own
`overlays/environments/{dev,prod}/enabled-addons.yaml`, which becomes the
`enable_crossplane` label on the spoke's cluster secret. A dedicated `enable_env_config`
label would force **every** consumer to opt in in their own config or silently get no
env-config. Gating on `enable_crossplane` delivers it wherever Crossplane runs, with zero
consumer wiring, automatically for future spokes. Precedent: the `pod_identities` addon
uses `environment: Exists` (no `enable_` label) for the same "foundational" reason.

### D4. No terraform dependency (kind cluster provider only)
The hub is provisioned by the kind cluster provider (`cluster-providers/kind-crossplane`),
not the classic `platform/infra/terraform`. All hub wiring lives in the kind provider's
Taskfile. Earlier exploratory edits to `platform/infra/terraform/common` and
`cluster-providers/terraform/secrets-manager.tf` were **reverted** — not part of this design.

### D5. Rename `vpc-config` → `env-config`
The stable identifier is the name `env-config` (OAP resolves via `spec.environment`).
Consumers previously selected by the `env=<clusterName>` label (not the name), so the
rename is safe; the label is preserved. Old imperative `vpc-config` objects (if any linger
on pre-existing clusters) are orphans to be deleted once `env-config` is confirmed.

## Implementation map

| Concern | File |
|---|---|
| env-config manifest (addon chart) | `gitops/addons/charts/crossplane-env-config/` (Chart, values, `templates/environmentconfig.yaml`) |
| Addon registration (selector `enable_crossplane`, values from annotations) | `gitops/addons/registry/core.yaml` (`env_config:`) |
| Spoke injection (subnet ids → XR status → cluster-secret annotations) | `gitops/abstractions/resource-groups/platform-cluster/templates/composition.yaml` + `xrd.yaml` |
| Hub injection (seed-secret annotations, AWS-CLI discovery) | `cluster-providers/kind-crossplane/Taskfile.yaml` (`hub:seed-secret`) |

Composition details:
- Each of the 4 subnets: `ToCompositeFieldPath status.atProvider.id → status.{public,private}SubnetId{A,B}`.
- EKS cluster: `ToCompositeFieldPath status.atProvider.vpcConfig.clusterSecurityGroupId → status.clusterSecurityGroupId`
  (NOTE: `vpcConfig` is an **object**, not a list — `vpcConfig[0]` is wrong and renders a
  fatal error that sets the composite `Synced=False`).
- cluster-secret `Object`: `CombineFromComposite` joins A+B subnet ids into
  `aws_private_subnet_ids` / `aws_public_subnet_ids` (comma-joined); `FromCompositeFieldPath`
  writes `aws_cluster_security_group_id`. The env-config chart `splitList`s the comma-joined
  annotations into YAML sequences.

Annotation names (identical on hub + spokes):
`aws_vpc_id`, `aws_private_subnet_ids`, `aws_public_subnet_ids`, `aws_cluster_security_group_id`.

## Verification / live acceptance

Parse: `helm template` (chart + composition + pod-identity), `yq` (registry + Taskfile).
Live (us-west-2): after ArgoCD auto-synced, `env-config` was present on all 3 clusters with
complete data (clusterName/region/vpcId/clusterSecurityGroupId + 2 private + 2 public subnets
each). Auto-sync required no manual step; a manual `argocd refresh` was only used during
validation to skip the ~3-min git-poll interval.

## Migration notes (pre-existing clusters)

- **Fresh installs**: fully automatic (spokes via composition, hub via kind Taskfile).
- **Existing spokes**: converged automatically once the composition change synced (hub
  Crossplane re-reconciled the spoke `PlatformCluster`s → annotations → env-config).
- **Existing hub**: its seed secret predates the Taskfile change, so `aws_public_subnet_ids`
  was added once by hand:
  `kubectl annotate secret <hub> -n argocd aws_public_subnet_ids="<comma,joined>" --overwrite`
  (then refresh `env-config-<hub>`). Not needed for fresh installs.
- **Abandoned Job-approach remnants**: the earlier `envconfig` Pod Identity role/association
  may linger as orphans (`prune:false`); inert, safe to delete.

## Commits (feature/agent-platform-shapirov)

- `fd71b9f7` — composition + XRD + manifest chart + registry; removed Job/pod-identity.
- `abf36282` — hub `hub:seed-secret` annotations (kind provider).
- `65789c8f` — fix `clusterSecurityGroupId` path (`vpcConfig` object, not array).
- (superseded: `fc6a66dc` / `38d6445d` — the discredited discovery-Job approach.)
