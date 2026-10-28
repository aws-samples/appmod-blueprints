# Design: AWS Backup & Restore for EKS — the `BackupPolicy` and `RestoreSelection` ResourceGraphDefinitions

## Summary

This document consolidates the AWS Backup for EKS work into a single, reviewable
design, and extends it to cover the **restore** half — because a backup without a
restore path protects nothing. It describes two kro `ResourceGraphDefinition`s (RGDs):

- **`BackupPolicy`** — expands into ACK `backup.services.k8s.aws` resources (a
  **BackupVault**, a **BackupPlan**, and a **BackupSelection**) for three service
  tiers (gold / silver / bronze). It is paired with **DR-aware tiered StorageClasses**
  that tag the EBS volumes they provision so `BackupSelection` can match them; those
  StorageClasses are rendered by the platform's `default-storage-class` chart (which
  runs per spoke), not by the hub-side `BackupPolicy` RGD, because a hub-side RGD
  cannot place a StorageClass into a spoke (see
  [StorageClass placement](#storageclass-placement--extending-default-storage-class)).
- **`RestoreSelection`** — the companion that turns a recovery point back into
  attachable PVs in a target cluster. Because AWS Backup restore is an *imperative*
  API (`StartRestoreJob`) with no declarative ACK CRD, this RGD is shaped differently
  from `BackupPolicy`; the [Restore design](#restore-design--the-restoreselection-rgd)
  section explains how.

The design draws an explicit **line between what AWS Backup recreates and what Argo CD
/ GitOps recreates** on recovery (see
[Recovery responsibility boundary](#recovery-responsibility-boundary--backup-vs-argo-cd--gitops)),
and it uses two platform mechanisms that already run on `main`: the **platform
tag-propagation** path (`platformTags` → `awsTags` → ACK `spec.tags`) and the ACK
**`adopt-or-create`** adoption policy, so vaults/plans created out-of-band or in a
prior deployment are adopted rather than duplicated.

This PR is **docs-only** — it delivers the design and the exact IAM *shape* a working
end-to-end backup needs, so the implementation PR has no IAM guesswork. That shape is
more than a single role: a `<prefix>-cluster-mgmt-backup` controller role (added at the
three sites that mint the other `cluster-mgmt-*` roles, plus an `IAMRoleSelector`), a
platform-created AWS Backup **service role** whose name matches the `*AWSBackup*`
pattern `AWSBackupFullAccess` scopes `iam:PassRole` to, a separate **restore Job**
identity, and the **EKS Cluster IAM Role tag grant** already noted. The platform-
capability history that led here and the full IAM table are in
[Platform capability & the IAM this design adds](#platform-capability--the-iam-this-design-adds).

## Motivation / use cases

Today a platform operator who wants AWS Backup on an EKS hub either writes raw ACK
Backup custom resources by hand or wires AWS Backup out-of-band. There is no
first-class, workload-driven primitive. `BackupPolicy` closes that gap using the same
kro/ACK pattern as the rest of the `resource-groups` directory, and the single
BackupPlan + BackupSelection primitive it produces, paired with `RestoreSelection`,
serves three distinct platform use cases:

- **Cross-region disaster recovery (DR).** Gold and silver tiers copy recovery points
  to a vault in a second region. On a region-level failure, kro + ACK recreates an
  equivalent spoke in the DR region through the normal provisioning path, Argo CD
  re-syncs every workload from Git, and `RestoreSelection` rehydrates the PVs from the
  cross-region copies. The DR spoke is **born through the standard path with its data
  restored on top** — never "adopted post-facto".
- **Blue/green cluster migration.** Stand up a replacement spoke alongside the live
  one, restore data into it from the latest recovery point, flip traffic when
  workloads report ready, decommission the old spoke. Same mechanism as DR, planned
  instead of reactive.
- **Environment cloning.** A recovery point is a portable, point-in-time copy of a
  workload's state, so a staging or test environment can be seeded from a known-good
  snapshot of another environment — no bespoke export/import pipeline.

All three are the same backup → recovery-point → restore mechanic viewed from a
different angle, which is why two small RGDs cover them.

## Recovery responsibility boundary — Backup vs Argo CD / GitOps

This is the single most important design decision in the document, so it is stated up
front as a hard contract. On any recovery (DR, blue/green, clone), the state of a
spoke is reconstructed by **two cooperating systems with a clean, non-overlapping
split**:

| State class | Example objects | Recreated by | Why / source of truth |
|---|---|---|---|
| **Declarative desired state** | Deployments, StatefulSets, Services, Ingress, ConfigMaps, HPA, NetworkPolicy, RBAC, CRs, PVC *templates* | **Argo CD re-sync from Git** | Git is the source of truth; replaying it is deterministic and faster than restoring it. |
| **Secrets — from Secrets Manager / SSM** | app credentials, API tokens, TLS keys, **RDS master password** (`manageMasterUserPassword` → SM) | **External Secrets Operator** (`ExternalSecret`, from AWS Secrets Manager — must be present in the *target region*) | Source of truth is SM; a snapshot of the K8s Secret is a stale copy of something ESO already owns. Cross-region DR requires the SM secret to be replicated into the DR region. |
| **Secrets — committed in Git** | service-account tokens, static config Secrets rendered by a chart | **Argo CD re-sync from Git** | Rendered deterministically from the chart on every sync; same rule as any Git-derived object. |
| **Secrets — generated at runtime, not in Git or SM** | a controller/operator-minted random password that was never pushed to SM | **⚠ nobody — potential gap** | Not in Git (Argo can't), not in SM (ESO can't), and excluded from the EBS backup. See [The Secret gap](#the-secret-gap-runtime-generated-credentials) + guardrail. |
| **Cluster / infra shell** | EKS cluster, VPC, NAT, node pools, add-ons | **kro + ACK provisioning** (`SpokeCluster` path) | Born through the standard path, not restored. |
| **Persistent data on volumes** | EBS volume contents behind a PVC (app data dirs, uploaded files, embedded DB files) | **AWS Backup restore** (`RestoreSelection`) | The one class Git cannot regenerate — it is the *only* thing backup is responsible for. |
| **Logical database / stream state** | Postgres, Kafka internal state | **application-level backup**, layered on top | AWS Backup gives a crash-consistent FS snapshot, not a logically consistent DB dump — see [Boundaries](#boundaries-what-this-does-not-cover). |

The rule that falls out of the table: **if a thing is derivable from Git, Argo CD
owns its recreation and backup must NOT try to restore it.** Restoring Git-derivable
objects from a snapshot is not just wasteful — it reintroduces drift (a snapshot is
older than `HEAD`) and causes Argo CD to fight the restored object. So the
`BackupSelection` is scoped to **EBS volumes only**
(`arn:aws:ec2:<region>:<account-id>:volume/*`), never
to Kubernetes API objects. A full recovery is therefore:

```
1. kro + ACK            → provision the DR/target spoke (cluster shell)
2. Argo CD              → re-sync all manifests from Git (desired state, empty PVCs)
3. External Secrets     → repopulate Secrets from Secrets Manager *in the target region*
4. RestoreSelection     → restore EBS volume data into the PVs the PVCs bound to
5. workloads start      → with recreated config + restored data
```

Steps 1–3 are the standard way a fresh spoke comes up; step 4 (`RestoreSelection`) is
sequenced after the PVCs exist but before (or as a precondition of) the stateful pods
going Ready.

> **Cross-region caveat on step 3.** ESO's `ClusterSecretStore` and the Keycloak
> config Job's SM push are both pinned to the **cluster's own region**
> (`region: {{ .Values.aws.region }}`), and RDS `manageMasterUserPassword` writes the
> master secret into Secrets Manager in the DB's region with **no replica**. So in a
> *different-region* DR, step 3 reads an **empty** Secrets Manager unless the secrets
> were replicated into the DR region. This makes **Secrets Manager cross-region
> replication the symmetric twin of the EBS cross-region copy** in the tier table:
> restoring a gold/silver data volume into a DR region is useless if the credential
> that unlocks or connects to it is not also present there. See
> [Cross-region restore & Secrets Manager replication](#cross-region-restore--secrets-manager-replication).

### The Secret gap: runtime-generated credentials

The Secrets row above splits into three sub-cases, and only two of them are safe by
construction. The third is a real DR gap worth calling out explicitly, because it is
the one that silently breaks a restore:

- Secrets whose source of truth is **Secrets Manager / SSM** (incl. the RDS master
  password via `manageMasterUserPassword`) are rehydrated by **ESO** — safe.
- Secrets **committed in Git** (service-account tokens, static chart-rendered Secrets)
  are rehydrated by **Argo CD** — safe.
- Secrets **generated at runtime** by a controller or config Job — minted in-cluster,
  never in Git, and (unless something pushes them) never in Secrets Manager. Neither
  Argo CD nor ESO can recreate these, and this design deliberately does **not** back up
  K8s Secret objects. **This is the gap.** On restore the data volume comes back but the
  credential that unlocks/authenticates it is regenerated *different* (or missing), and
  the workload fails to come up.

**The fix is not to back up K8s Secrets** (that would break the Backup/GitOps boundary
and make a stale snapshot compete with ESO). The fix is to **forbid the category**:
every runtime-generated secret must be pushed to Secrets Manager — via an ESO
`PushSecret` (as `devlake` already does for its MySQL connection) or a synchronous
`put-secret-value` in the generating Job — which moves it into the first, safe sub-case.

**Worked example — the Langfuse OIDC client secret (verified in the repo).** The
`LANGFUSE_CLIENT_SECRET` is generated at runtime by Keycloak and harvested by the
`keycloak-config` Job (`get_client_secret "langfuse"`); it is in neither Git nor an
`ExternalSecret`, so it is squarely in the gap category. PEEKS closes it the right way:
immediately after writing the in-cluster `keycloak-clients` Secret, the same Job does a
**synchronous push to Secrets Manager** (`<cluster>/keycloak-clients`,
`put-secret-value`-or-`create-secret`; the Secret even carries
`backup-location: aws-secrets-manager`). So on DR/restore the recovery path is: Argo CD
re-syncs the Keycloak chart → its config Job re-exports the client secret to Secrets
Manager → apps consume the recreated Secret. Langfuse is recoverable **only because of
that explicit push** — not because of the EBS backup. Any new runtime-generated secret
that omits this push would be the gap, live.

> **Design consequence.** The restore runbook must sequence Keycloak (and any other
> runtime-secret generator) *before* the apps that consume those secrets, so Secrets
> Manager is repopulated before ESO/consumers read it. This ordering is part of the
> `RestoreSelection` sequencing concern, not the EBS restore itself.

## Architecture — the resource graph

A `BackupPolicy` claim is a small, declarative CR. kro reconciles it into a chain of
ACK resources, in dependency order:

```
BackupPolicy CR (claim)
   │
   ▼
┌─ BackupVault (ACK)            ── always
│  name: <prefix>-<spoke>-<tier>  (truncate+hash to fit ^[A-Za-z0-9\-_]{2,50}$)
│  tags: <awsTags> + built-in platform.gitops.io/{prefix,cluster}  (see Tag propagation)
│  adoption-policy: adopt-or-create
└────
   │
   ▼
┌─ BackupPlan (ACK)             ── one variant per tier (includeWhen)
│  rules: schedule + lifecycle
│  recoveryPointTags: platform.gitops.io/backup-tier, platform.gitops.io/spoke
│                     (the keys the restore side queries — NOT the whole <awsTags> map;
│                      a recovery point caps at 50 tags, see Tag propagation)
│  copyActions for gold / silver (cross-region)
└────
   │
   ▼
┌─ BackupSelection (ACK)        ── one variant per tier
│  iamRoleARN: <from claim; the platform *AWSBackup* service role, <backup-service-role-arn>>
│  resources:
│    - arn:aws:ec2:<region>:<account-id>:volume/*     (EBS volumes ONLY)
│  conditions: platform.gitops.io/backup-tier + platform.gitops.io/spoke
└────
```

kro reconciles the chain in order: `BackupSelection` waits for the `BackupPlan` to
report its `ACK.ResourceSynced` condition before it applies, so the selection never
references a plan that does not yet exist.

### Tier model

Tier semantics are declared *in the RGD* so they are reviewable and versioned
alongside the primitive, rather than living in operator runbooks:

| Tier            | Schedule              | Start window | RPO | Warm retention | DR-copy retention | Cold storage | Cross-region copy | RTO target |
|-----------------|-----------------------|--------------|-----|----------------|-------------------|--------------|-------------------|------------|
| gold            | `cron(0 * * * ? *)`   | 60 min       | 1h  | 14d            | 30d               | —            | yes               | ≤ 1h\*     |
| gold-archive†   | `cron(0 0 1 * ? *)`   | 60 min       | 30d | 30d            | —                 | after 30d    | no (cold)         | up to 72h  |
| silver          | `cron(0 2 * * ? *)`   | 60 min       | 24h | 14d            | 7d                | —            | yes               | ≤ 4h\*     |
| bronze          | `cron(0 3 * * ? *)`   | 60 min       | 24h | 7d             | —                 | —            | no                | best effort|

\* RTO targets are platform intents, **not** AWS SLAs — AWS Backup gives no restore
SLA, restored EBS volumes hydrate lazily (increased I/O latency until blocks are first
read), and an archive restore takes up to 72h. Each target also assumes the restore
orchestration (static-PV bind, AZ placement, `eks:eks-cluster-name` re-tag) is already
in place — see [The hard part](#the-hard-part-restore-metadata-az-placement-and-the-static-pv-bind).

† **gold-archive is optional and separate from the hourly rule.** AWS Backup only
transitions EBS to cold storage (Amazon EBS Snapshots Archive) when a rule's frequency
is **monthly or less often** ([Create a backup
plan](https://docs.aws.amazon.com/aws-backup/latest/devguide/creating-a-backup-plan.html)),
so putting `moveToColdStorageAfterDays` on the *hourly* gold rule archives nothing and
silently keeps ~4,320 warm snapshots per volume. Long-term gold history therefore needs
a **second, monthly rule** that sets `moveToColdStorageAfterDays`,
`lifecycle.optInToArchiveForSupportedResources: true` and `deleteAfterDays ≥ cold + 90`
(a plan allows up to 10 rules). Archive also caps at 25 archived snapshots per volume,
archived snapshots are full (not incremental), restore from archive takes up to 72h,
and cold-tier recovery points **cannot** be copied cross-region
([Creating backup copies across AWS
Regions](https://docs.aws.amazon.com/aws-backup/latest/devguide/cross-region-backup.html)) —
hence `gold-archive` carries no cross-region copy.

The `startWindowMinutes` is set explicitly: without it the AWS Backup console default
of **8 hours** applies ("Start within defaults to 8 hours"), which would make the
"1h RPO" claim false. Note also that AWS Backup allows **1 concurrent backup/copy job
per resource**, so a slow first full cross-Region copy can push back the next hourly
job.

Cross-region copy targets are supplied by the claim as a single
`copyDestinationVaultARN` (the Region is already encoded in the ARN, so no separate
`copyDestinationRegion` field — one field avoids a region/ARN mismatch). The
destination vault must already exist in the DR region **and must be keyed with a CMK or
`aws/ebs`, not a Backup-managed key** (see
[finding on the DR vault key](#cross-region-restore--secrets-manager-replication) and
[Known limitations](#known-limitations-v1)).

### The tag-matching contract

`BackupSelection` does not enumerate volumes; it matches them by AWS resource tag.
The conditions are:

```yaml
# BackupSelection conditions in the BackupPolicy RGD
conditions:
  stringEquals:
    - conditionKey: "aws:ResourceTag/platform.gitops.io/backup-tier"
      conditionValue: <tier>
    - conditionKey: "aws:ResourceTag/platform.gitops.io/spoke"
      conditionValue: <spokeName>
```

Those two tags are placed on the EBS volume at provision time by the StorageClass
(next section), so inclusion in a BackupPlan is a direct consequence of *which
StorageClass a workload picked* — no imperative registration step.

> **Use `conditions`, not `listOfTags` — the two combine differently.** ACK's
> `BackupSelection` models both a `conditions` block (used above) and a `listOfTags`
> block, and they are **not interchangeable**. Multiple keys inside `conditions`
> (`stringEquals`) are combined with a Boolean **AND** — a volume must match
> `backup-tier` **and** `spoke` to be selected, which is the intent here. `listOfTags`
> combines its entries with a Boolean **OR** — a volume matching *either* tag would be
> selected, which would pull every spoke's volumes of a given tier (or every tier of a
> given spoke) into one plan. The RGD must express the tier+spoke match through
> `conditions`; a future contributor who moves it to `listOfTags` silently widens the
> selection. This is pinned in the RGD and worth a comment at the point of use.

## Tag propagation & resource adoption (reusing PEEKS platform mechanisms)

Two platform capabilities on `main` carry this design: a way to **propagate tags onto
ACK objects**, and a way to **adopt pre-existing AWS resources**. The RGDs use both
directly.

### Platform tag propagation (`platformTags` → `awsTags` → ACK `spec.tags`)

PEEKS threads a platform-wide tag map through the whole provisioning chain. The two
**ownership** tags — `platform.gitops.io/prefix` and `platform.gitops.io/cluster` — are
**not** carried inside `awsTags`; they are derived from dedicated schema fields
(`schema.spec.resourcePrefix` and `schema.spec.name`) and merged as built-ins, with the
user-supplied `awsTags` overlaid on top:

```
config.local.yaml  platformTags: {…}
   │  (compact JSON)
   ▼
hub cluster-secret  annotation  platform_tags: '{…}'
   │  (clusters-kro ApplicationSet, global.platformTags)
   ▼
RGD schema field    spec.resourcePrefix, spec.name  (ownership); spec.awsTags (overlay)
   │  (kro CEL: built-in ownership tags from resourcePrefix/name, then .merge(awsTags))
   ▼
ACK resource        spec.tags: {built-in ownership (from resourcePrefix/name)… , <awsTags>}
```

The EKS RGD builds the ownership tags from the dedicated fields and merges `awsTags`
over them — the ownership keys come from `resourcePrefix`/`name`, **not** from `awsTags`
(`rg-eks.yaml:454`):

```yaml
# how an ACK resource builds ownership tags + merges awsTags in an existing RGD (rg-eks.yaml)
tags: '${ {"kro-management": schema.spec.name, "tenant": schema.spec.tenant,
           "platform.gitops.io/prefix": schema.spec.resourcePrefix,
           "platform.gitops.io/cluster": schema.spec.name}
         .merge(schema.spec.?awsTags.orValue({})) }'
```

`BackupPolicy` therefore needs its own `resourcePrefix` and `clusterName` schema fields
(as `rg-eks` has `resourcePrefix`/`name`) and derives the ownership tags from them, then
merges `awsTags`:

- `BackupVault.spec.tags` — so vaults carry the platform ownership tags
  (`platform.gitops.io/prefix` + `platform.gitops.io/cluster`, **from the dedicated
  `resourcePrefix`/`clusterName` fields above**), plus any cost-allocation and
  SpringClean `auto-delete=no` retention tags supplied through `awsTags`, exactly like
  every other platform-created AWS resource. This is what lets the teardown/cost
  sweepers enumerate and protect backup vaults.
- `BackupPlan.recoveryPointTags` — so every recovery point produced is self-describing
  (which spoke, which tier), which the restore side relies on to
  find the right recovery point (see [Restore design](#restore-design--the-restoreselection-rgd)).
  **Mind the per-recovery-point tag cap:** AWS Backup assigns both the
  source-resource tags and the backup-assigned tags to each recovery point, **up to a
  maximum of 50** (an AWS limitation; backup-assigned tags take priority, copied in
  alphabetical order — [Copy tags onto
  backups](https://docs.aws.amazon.com/aws-backup/latest/devguide/tags-on-backups.html)).
  So `recoveryPointTags` + the merged `awsTags` + whatever source tags the volume
  already carries must stay within 50, or the backup job can fail — keep
  `recoveryPointTags` to the few keys the restore side actually queries
  (`backup-tier`, `spoke`) rather than echoing the whole `awsTags` map.

> **Important distinction.** `awsTags` on the vault/plan (platform ownership /
> cost / retention tags on the *AWS Backup objects themselves*) is a **different
> concern** from the `platform.gitops.io/backup-tier` + `platform.gitops.io/spoke` tags on the *EBS
> volumes* that drive `BackupSelection` matching. The first describes the backup
> infrastructure; the second is the workload opt-in. Both flow through tag mechanisms,
> but they tag different resources for different readers — do not conflate them.

### Resource adoption (`adopt-or-create`)

PEEKS uses ACK's adoption annotations extensively (pod-identity policies/roles,
cicd-pipeline ECR policies, the EKS RGD) to make GitOps **idempotent over
pre-existing AWS resources** — so re-applying a manifest adopts the live resource
instead of failing `…AlreadyExists`, and a redeploy of the same stack does not
duplicate infrastructure. The pattern:

```yaml
metadata:
  annotations:
    services.k8s.aws/adoption-policy: adopt-or-create
    # adoption-fields only when ACK cannot derive the primary key from spec.name
    # (e.g. ARN-keyed resources). For name-keyed resources the policy alone suffices.
    services.k8s.aws/adoption-fields: |
      {"<primary-key>": "<value>"}
    # retain the AWS resource on prune — it may hold data or be referenced elsewhere
    services.k8s.aws/deletion-policy: retain
```

Adoption applied to backup matters for two reasons:

1. **BackupVault adoption is a correctness requirement, not a convenience.** A vault
   accumulates recovery points over time; it must **never** be deleted-and-recreated
   on a redeploy, or the deployment's entire backup history is destroyed. So the
   `BackupVault` in this RGD carries `adoption-policy: adopt-or-create` **and**
   `deletion-policy: retain`. A fresh deployment that points at an existing vault name
   adopts it (and its recovery points); a prune leaves the vault and its data intact.
   This is the single most dangerous resource in the design to get wrong, which is why
   adoption + retain are mandatory on it.
2. **Adopting backups taken before this RGD existed.** Operators who created AWS
   Backup vaults/plans by hand (the pre-RGD status quo) can bring them under GitOps
   management by naming them in a `BackupPolicy` claim: `adopt-or-create` adopts the
   existing vault/plan rather than erroring, so migration onto the platform primitive
   is non-destructive and requires no manual import step.

The `BackupVault` is name-keyed (ACK derives the key from `spec.name`),
so `adopt-or-create` alone is sufficient for the **vault only**. The **BackupPlan is
NOT name-keyed** in ACK — its primary key is `id` (the AWS `BackupPlanId`): `sdkFind`
returns `NotFound` while `status.id` is nil, and `PopulateResourceFromAnnotation`
requires `id`. So `adopt-or-create` on a plan **without**
`services.k8s.aws/adoption-fields: {"id": "<planId>"}` **creates** a new plan rather
than adopting the existing one. The RGD must supply the plan's `id` in `adoption-fields`
if adoption of a pre-existing plan is intended.

`BackupSelection` is created fresh each time (it is cheap and derivable), so it does
not need adoption — but it also **cannot be updated**: the ACK controller has no update
API for it and goes `Terminal` ("BackupSelection resources cannot be updated. Delete and
recreate the resource to apply changes.") on any spec change. Because kro updates in
place, changing a claim's tier, spoke or role would **wedge** the instance. The RGD must
therefore put a short **hash of the selection inputs in the selection's name**, so a
changed input produces a *new* object (delete-and-recreate) rather than an in-place
update.

**kro ordering is not automatic.** The `BackupSelection` only applies after the
`BackupPlan` exists if the selection **references `${backupplan.status.id}`** and the
plan carries a `readyWhen` on `ACK.ResourceSynced` (repo precedent: `appmod-service.yaml`).
State that dependency explicitly in the RGD; ACK's `backupPlanRef` is the alternative to
the raw id reference.

## StorageClass tiers + volume tagging

For `BackupSelection` to have anything to match, the EBS volumes must carry the
`platform.gitops.io/backup-tier` and `platform.gitops.io/spoke` tags. That is the job of the tiered
StorageClasses. Each tier StorageClass passes the tags to the EBS CSI driver via its
`tagSpecification_<N>` parameters; the driver stamps them onto every volume it
dynamically provisions from that class:

```yaml
# One StorageClass per tier; the EBS CSI driver copies these tags onto the volume.
# NOTE: the parameter that stamps custom tags under EKS Auto Mode is NOT settled — the
# Auto Mode StorageClass parameter table documents neither `tagSpecification_<N>` (the
# self-managed driver's form, shown here) nor a `tags` form. Confirm the exact spelling
# ON A CLUSTER before authoring the classes.
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: <prefix>-<spokeName>-gold          # <prefix>-<spoke>-<tier>, passes name_is_ours
provisioner: ebs.csi.eks.amazonaws.com
reclaimPolicy: Retain          # gold = Retain (conditional, see below); silver/bronze = Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
  # tag-parameter spelling unconfirmed for Auto Mode — see note above
  tagSpecification_1: "platform.gitops.io/prefix=<prefix>"
  tagSpecification_2: "platform.gitops.io/backup-tier=gold"
  tagSpecification_3: "platform.gitops.io/spoke=<spokeName>"
```

`<spokeName>` is a single top-level value merged into every tier StorageClass as
`platform.gitops.io/spoke=<spokeName>`, which is what scopes a spoke's backups to that spoke.
The `reclaimPolicy` is **not** uniform: `Retain` is **not** a restore precondition —
recovery points are independent of the source volume and a restore always mints a *new*
volume (see [The hard part](#the-hard-part-restore-metadata-az-placement-and-the-static-pv-bind)),
so **silver and bronze use `Delete`**. `Retain` is kept for **gold only**, and only
**conditional on the cleanup reaper shipping** (finding below + [Teardown](#teardown--reaping-vaults-recovery-points-replicas-and-retained-volumes)):
its purpose is **not** "needed to restore" but preserving the writes made **since the
last recovery point** when a PVC is deleted by mistake — a mistake-deletion window that
matters for a 1h-RPO tier.

> **Auto Mode custom tags need a Cluster IAM Role grant — otherwise no tag lands and
> `BackupSelection` matches nothing.** These tier classes use the EKS **Auto Mode**
> provisioner (`ebs.csi.eks.amazonaws.com`), not the self-managed `aws-ebs-csi-driver`.
> Under Auto Mode, `StorageClass` tagging is the supported way to stamp custom tags, but
> AWS only applies them if the **EKS Cluster IAM Role is granted the matching tag
> permissions** — custom `StorageClass` tags silently do **not** land otherwise ([Create
> a storage class — *Custom Tags on Dynamically Provisioned Volumes*](https://docs.aws.amazon.com/eks/latest/userguide/create-storage-class.html);
> [Custom AWS tags for EKS Auto resources](https://docs.aws.amazon.com/eks/latest/userguide/auto-cluster-iam-role.html#tag-prop)).
> That makes the Cluster IAM Role tag grant a **second IAM deliverable** alongside the
> `<prefix>-cluster-mgmt-backup` role (see
> [Platform capability & the IAM this design adds](#platform-capability--the-iam-this-design-adds)):
> without it the whole tag-matching contract is a no-op — the volumes carry no
> `platform.gitops.io/*` tags, so every tier's `BackupSelection` matches zero volumes.
> (The exact tag-parameter spelling under Auto Mode is unconfirmed: the Auto Mode
> `StorageClass` parameter table documents **neither** `tagSpecification_<N>` (the
> self-managed driver's form) **nor** a `tags` form, so the spelling must be settled on a
> cluster before the classes are authored.)

> **`Retain` ≠ backup, and it leaks volumes.** On the **gold** tier `reclaimPolicy:
> Retain` keeps the source volume alive but it is **not** a backup (a backup is the
> recovery point in the vault), and it has a cost: when a PVC is deleted the volume is
> **not** reclaimed, so deleted gold PVCs leave **orphaned `Released` PVs and detached
> EBS volumes** that accrue storage charges and residue indefinitely. Gold `Retain` is
> therefore kept **only if** it is paired with a cleanup guardrail — the reaper in
> [Teardown](#teardown--reaping-vaults-recovery-points-replicas-and-retained-volumes)
> that deletes `Released` PVs whose recovery points are safely captured, scoped by the
> same `platform.gitops.io/spoke` tag. Without that reaper, gold `Retain` is unbounded
> orphaned spend — exactly the residue the platform's teardown/cost sweepers exist to
> catch. **Silver and bronze stay `reclaimPolicy: Delete`** precisely to avoid this.

> **Tag namespace.** `platform.gitops.io/backup-tier` and `platform.gitops.io/spoke`
> live in the same `platform.gitops.io/*` namespace the platform already stamps on its
> ACK-created infra (`platform.gitops.io/prefix`, `platform.gitops.io/cluster`) via the
> `awsTags` merge (see [Tag propagation](#platform-tag-propagation-platformtags--awstags--ack-spectags)).
> They are applied by a different path, though: the infra keys ride the
> `awsTags`→`spec.tags` merge onto the AWS Backup objects, whereas these opt-in keys are
> stamped onto the **EBS volumes** by the StorageClass `tagSpecification_<N>` parameter
> (the EBS CSI path), because `BackupSelection` matches on the volumes, not on
> namespaces. `<spokeName>` names the spoke and, on a hub, aligns with the
> `platform.gitops.io/cluster` value the platform already sets.

### StorageClass placement — extending `default-storage-class`

The tiered StorageClasses live alongside the platform's existing storage chart. On
`main`:

- `gitops/addons/charts/default-storage-class/` is a standalone chart that emits a
  single default `gp3` StorageClass (`provisioner: ebs.csi.eks.amazonaws.com`,
  `volumeBindingMode: WaitForFirstConsumer`, `encrypted: true`), marked
  `storageclass.kubernetes.io/is-default-class: "true"`.
- It emits **no tags** and has no per-tier variants.

The three tier classes (`<prefix>-<spoke>-gold`, `<prefix>-<spoke>-silver`,
`<prefix>-<spoke>-bronze`) extend that chart's pattern — same provisioner and binding
mode — adding the tag parameters and the per-tier reclaim policy. They are rendered by
the **`default-storage-class` chart**, which runs per spoke, **not** by the hub-side
`BackupPolicy` RGD: a hub-side RGD cannot place a StorageClass into a spoke. The chart
gains a `clusterName` entry in its `valuesObject` so it can stamp
`platform.gitops.io/spoke=<spokeName>` per spoke. The existing single default class
stays the cluster default; the tier classes are additive and non-default, so workloads
that do not opt into a tier keep the current behaviour unchanged.

## Developer opt-in contract

Opting a workload into backup is declarative and auditable:

1. A namespace (or workload) optionally carries a Kubernetes **label**
   `platform.gitops.io/backup-tier=<tier>` as a human-readable intent signal. This label
   is **not** what drives selection — nothing reads it for `BackupSelection` — so it may
   be dropped entirely; the real opt-in is the StorageClass a PVC picks (step 2).
2. The workload's PersistentVolumeClaims reference the matching tier StorageClass
   (`<prefix>-<spoke>-gold` / `<prefix>-<spoke>-silver` / `<prefix>-<spoke>-bronze`).
3. The EBS CSI driver stamps `platform.gitops.io/backup-tier` and `platform.gitops.io/spoke` onto each
   provisioned volume via the StorageClass `tagSpecification_<N>` parameters.
4. The `BackupSelection` for that tier matches those tags
   (`aws:ResourceTag/platform.gitops.io/backup-tier` + `aws:ResourceTag/platform.gitops.io/spoke`) and the
   volume is included in the tier's BackupPlan.

There is **no central ConfigMap** and no platform ticket: the opt-in lives next to the
workload. But **auditing what is actually backed up must query the volumes, not the
namespaces.** The namespace label is an *intent* signal; the thing `BackupSelection`
actually matches is the **tag on the EBS volume**, stamped only when a PVC uses a tier
StorageClass. A namespace labelled `platform.gitops.io/backup-tier=gold` whose PVCs use
the default (untagged) StorageClass is **not backed up** — the label gives a false sense
of coverage. So the authoritative audit is over AWS resources:

```sh
# AUTHORITATIVE: which volumes are actually in a tier's BackupSelection (AWS truth)
aws ec2 describe-volumes \
  --filters "Name=tag:platform.gitops.io/backup-tier,Values=gold" \
            "Name=tag:platform.gitops.io/spoke,Values=<spokeName>" \
  --query 'Volumes[].{id:VolumeId,az:AvailabilityZone}'

# INTENT ONLY (not proof of backup): namespaces that asked for a tier
kubectl get ns -l platform.gitops.io/backup-tier=gold
```

A coverage gap is exactly the set difference between the two: namespaces that declare a
tier but whose volumes carry no matching tag. A drift check (CI, or a periodic Job)
should flag that difference rather than trust the namespace labels alone.

## Restore design — the `RestoreSelection` RGD

A backup is only insurance if it can be restored. This section specifies the restore
side so the design is complete end-to-end.

### Why restore is shaped differently from backup

`BackupPolicy` maps cleanly onto ACK because vault/plan/selection are **declarative,
long-lived** AWS Backup objects. Restore is not: AWS Backup restore is an
**imperative, one-shot** operation (`StartRestoreJob`) that produces a new EBS volume
from a recovery point and then completes. The ACK `backup.services.k8s.aws` controller
models the declarative objects (`BackupVault`, `BackupPlan`, `BackupSelection`); it
does **not** expose a declarative `RestoreJob` CRD at the version the capability ships
(its `generator.yaml` models vaults/plans/selections only). So
`RestoreSelection` cannot be "just another ACK resource" the way `BackupPolicy` is.

The design therefore makes `RestoreSelection` a kro RGD that **orchestrates** a restore
rather than declaring one AWS object:

```
RestoreSelection CR (claim)
   spec:
     sourceSpoke:        <spokeName>        # which spoke's recovery points
     tier:               <gold|silver|bronze>
     recoveryPointAt:    <timestamp|latest> # point-in-time selector
     targetCluster:      <existing|new>     # existingCluster vs born-fresh
     iamRoleARN:         <backup-service-role-arn>   # the platform *AWSBackup* service role
   │
   ▼
┌─ a Kubernetes Job (or ACK controller once a RestoreJob CRD exists)
│  that resolves the recovery point by recoveryPointTags
│  (platform.gitops.io/spoke + platform.gitops.io/backup-tier, newest ≤ recoveryPointAt)
│  then drives the restore in four steps:
│    1. backup:GetRecoveryPointRestoreMetadata → the required EBS restore metadata
│    2. backup:StartRestoreJob (returns a RestoreJobId only)
│    3. poll backup:DescribeRestoreJob → CreatedResourceArn (an ARN; parse the
│       vol-... volume id out of it — it is NOT a bare volume id)
│    4. ec2:CreateTags on the new volume:
│         eks:eks-cluster-name=<target>          → REQUIRED or Auto Mode won't attach it
│         platform.gitops.io/spoke=<TARGET spoke> → the spoke being restored INTO, not the
│                                                   source (a source tag would let a
│                                                   same-Region blue/green restore be
│                                                   re-selected by the SOURCE spoke's
│                                                   BackupSelection)
│         platform.gitops.io/backup-tier=<tier>  → so it re-enters its tier's selection
│         platform.gitops.io/prefix=<prefix>     → REQUIRED so teardown step 5 can find
│                                                   the detached volume by the prefix tag
└────
   │
   ▼
┌─ a PersistentVolume (static) bound to the target PVC, pointing at the
│  restored EBS volume (volumeHandle = new volume id), so the stateful pod
│  attaches restored data instead of an empty disk.
└────
```

Two implementation options for the orchestrator, documented as an explicit choice for
the review:

- **(A) Job-based (v1, recommended).** A small container image (or the existing
  platform tooling image) running `aws backup start-restore-job` + poll, driven by the
  RGD. Works today, no dependency on an unreleased CRD. The RGD owns the Job and the
  resulting static PV.
- **(B) ACK-native (future).** If/when the ACK backup-controller ships a declarative
  restore/`RestoreJob` resource, `RestoreSelection` collapses to the same clean ACK
  pattern as `BackupPolicy`. Documented as the target end-state; no restore CRD exists
  at the version the capability ships (the backup-controller's `generator.yaml` models
  vaults/plans/selections only, and ignores `RestoreTestingPlan`/`RestoreTestingSelection`).

### The hard part: restore metadata, AZ placement, and the static-PV bind

The orchestrator sketch above hides the three things that are actually hard about an
EBS restore. They are called out here because they are ~80% of the real
`RestoreSelection` work and the design is not implementable until they are specified.

**1. A restore mints a NEW volume — it is never in-place, and it needs metadata.**
`StartRestoreJob` does not rehydrate the original volume; it creates a **new EBS volume
with a new volume ID** from the recovery point. Two API details the orchestrator must
get right:

- `StartRestoreJob` returns **only a `RestoreJobId`** — it does not return the new
  volume. The new volume comes from polling `backup:DescribeRestoreJob` and reading
  **`CreatedResourceArn`**, which is a full **ARN**
  (`arn:aws:ec2:<region>:<account>:volume/vol-…`); the `volumeHandle` the static PV
  needs is the bare `vol-…` id, so the orchestrator must **parse it out of the ARN**
  (e.g. the segment after `volume/`), not pass the ARN through.
- The call **requires a restore-metadata document** fetched first with
  `backup:GetRecoveryPointRestoreMetadata`. There is **no `pvName` key**; the EBS
  restore-metadata keys are `availabilityZone`, `encrypted`, `iops`, `kmsKeyId`,
  `throughput`, `volumeType`, `volumeSize`, `temporaryRestoreDays`, `restoreType`.

So the Job is at least `get-restore-metadata → start-restore-job → describe-restore-job`
(poll), not a one-liner.

**The restored volume will not attach on an EKS Auto Mode cluster unless it is
re-tagged.** EKS Auto Mode attaches a volume only if it carries
`eks:eks-cluster-name=<cluster>`; AWS Backup **does not set this tag on restored
volumes**, so a restored volume lands untagged and its pod stays `ContainerCreating`
with `FailedAttachVolume`. `StartRestoreJob` copies source tags only when
`CopySourceTagsToRestoredResource` is true, and even then the copied value names the
**source** cluster — so blue/green, clone and DR restores still fail to attach. The
orchestrator must therefore `ec2:CreateTags` the new volume with
`eks:eks-cluster-name=<target-cluster>` **plus** the `platform.gitops.io/backup-tier`,
the `platform.gitops.io/spoke` of the **target** spoke (the one being restored into —
using the *source* spoke's value would let a same-Region blue/green restore be picked up
by the source spoke's `BackupSelection`), and `platform.gitops.io/prefix` (so the
teardown reaper can later find the detached volume by the prefix tag), so the restored
volume re-enters the correct tier's `BackupSelection` **before** the pod is scheduled.

The restore side of the `<prefix>-cluster-mgmt-backup` controller role is therefore not
enough on its own — the restore Job needs its own identity with
`backup:StartRestoreJob`, `backup:GetRecoveryPointRestoreMetadata`,
`backup:DescribeRestoreJob`, `backup:ListRecoveryPointsByBackupVault`, `backup:ListTags`,
`ec2:CreateTags`, `ec2:DescribeVolumes`, `iam:PassRole` on the restore role, and KMS on
the CMK if one is used (see
[Platform capability & the IAM this design adds](#platform-capability--the-iam-this-design-adds)).

**2. The AZ the new volume lands in must match where the pod schedules.** An EBS volume
is zonal — it can only attach to a node in its own AZ. The restore metadata lets the
orchestrator *choose* the target AZ, so `RestoreSelection` must set it deliberately
rather than take the default:

- For `targetCluster: existing` (blue/green, clone), restore into an AZ the target
  cluster has nodes in, and constrain the consuming pod to that AZ (nodeAffinity on the
  static PV's `nodeAffinity.required` — see below).
- `volumeBindingMode: WaitForFirstConsumer` on the *tier* StorageClass does **not** save
  this case: that mode defers *dynamic provisioning* until a pod is scheduled, but a
  restored volume already exists in a fixed AZ before any pod is scheduled. The binding
  therefore runs the other way — the PV's AZ constrains the pod, via the PV's
  `nodeAffinity`, not the pod's placement choosing the volume's AZ.

**3. The restored volume must be adopted by a STATIC, pre-bound PV — not a dynamic PVC.**
Argo CD recreates the PVC empty from Git (dynamic, pointing at the tier StorageClass). A
restore produces a loose EBS volume with no PV. Binding them requires a **static PV**
the orchestrator creates, carrying:

```yaml
# static PV the RestoreSelection orchestrator creates to adopt the restored volume
apiVersion: v1
kind: PersistentVolume
metadata:
  name: restored-<pvc-name>
spec:
  capacity:
    storage: <restored size, from restore metadata>   # must be >= the PVC request
  accessModes: ["ReadWriteOnce"]
  persistentVolumeReclaimPolicy: Retain                # TIER-DERIVED, not fixed: Retain for
                                                       # gold only (if the teardown reaper ships);
                                                       # Delete for silver/bronze — otherwise the
                                                       # silver/bronze orphan this design avoids
                                                       # comes back for restored volumes
  storageClassName: <prefix>-<spokeName>-gold          # match the PVC's class, so Argo's
                                                       # dynamic PVC binds here not to a new disk
  claimRef:                                            # PRE-BIND to the exact PVC → no race
    namespace: <workload-ns>
    name: <pvc-name>
  nodeAffinity:                                        # pin the pod to the volume's AZ
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.kubernetes.io/zone         # the Auto Mode zone label
              operator: In
              values: ["<restored-volume-az>"]
  csi:
    driver: ebs.csi.eks.amazonaws.com
    volumeHandle: <new-volume-id>                      # the bare vol-... id PARSED from
                                                       # DescribeRestoreJob.CreatedResourceArn (an ARN)
```

The two load-bearing fields are `claimRef` (pre-binding the PV to the specific PVC so
the Argo-created dynamic PVC adopts the restored volume instead of provisioning a fresh
empty one — this closes the race where the PVC binds first) and `nodeAffinity` (so the
scheduler only places the stateful pod on a node in the restored volume's AZ). The
orchestrator fills `storage`, `<restored-volume-az>`, and `volumeHandle` from the
restore-job output and the restore metadata. **Before creating this PV**, the
orchestrator must `ec2:CreateTags` the new volume with `eks:eks-cluster-name=<target>`
(or Auto Mode never attaches it) **and** the `platform.gitops.io/backup-tier`, the
`platform.gitops.io/spoke` of the **target** spoke, and the `platform.gitops.io/prefix`
tags (so the restored volume is re-selectable by the next backup cycle under the correct
spoke, and findable by the teardown reaper — otherwise the restored data silently falls
out of its tier's `BackupSelection`, or a source-spoke tag pulls it into the wrong
selection).

> **StatefulSets break the "Argo recreates the PVC empty, then we bind the PV"
> assumption.** For a standalone PVC the static-PV `claimRef` above wins the race. But a
> StatefulSet's PVCs are created by the StatefulSet controller from
> `volumeClaimTemplates` **together with the pod**, and `WaitForFirstConsumer` then
> provisions a fresh empty volume as soon as the pod is schedulable — a `claimRef`'d PV
> that appears *after* that bind sits `Available` forever. So for StatefulSets the
> restore must be **sequenced to complete before the workload's Argo app syncs** (gate
> the Argo app on `RestoreSelection` ready), or the STS must be scaled to 0 and back
> after the PVs exist. Use the deterministic PVC names
> `<template>-<sts>-<ordinal>` for the `claimRef`. State the same-cluster behaviour
> explicitly: if the original PVC is still bound, the orchestrator must **refuse** or
> restore into a **new** claim rather than silently no-op.

### Recovery-point discovery via tags

The restore side depends on the backup side having tagged its recovery points. Because
`BackupPlan.recoveryPointTags` stamps `platform.gitops.io/spoke` and `platform.gitops.io/backup-tier` on
every recovery point (see [Tag propagation](#tag-propagation--resource-adoption-reusing-peeks-platform-mechanisms)),
`RestoreSelection` can resolve "the newest gold recovery point for spoke X at or before
time T" by tag query, with no out-of-band index. This is why the two tag concerns in
this design are not optional decoration — the recovery-point tags are the join key the
restore relies on.

### Cross-region restore & Secrets Manager replication

A cross-region restore is only complete when **both** halves of a workload's state
land in the DR region: the **data** (EBS recovery point) and the **credentials** that
unlock or connect to it (Secrets Manager). The data half is already handled — gold and
silver `BackupPlan`s set a `copyAction` to a vault in the DR region, so the recovery
point exists there, **but only if the DR vault's key is right**:

- **The DR vault must be keyed with a CMK or `aws/ebs`, not a Backup-managed key.** EBS
  is not a fully-managed AWS Backup resource, so copying an EBS recovery point into a
  destination vault keyed with a Backup-managed key (which is what a *default* vault
  uses, `aws/backup`) **fails the copy job**. Create the DR vault with
  `encryptionKeyARN` = the `aws/ebs` managed key (or a CMK) in the DR Region.
- **The v1-limitation wording about keys points at the wrong vault.** The *primary* EBS
  recovery points keep the **source volume's** key (independent AWS Backup encryption is
  not supported for EBS); the key that governs the copy is the **destination** vault's.
- **Cross-account copy is out of scope for v1.** Cross-account copy with AWS-managed
  keys is not supported for resources that are not fully managed by AWS Backup, and the
  tier StorageClasses use `encrypted: "true"` → the AWS-managed `aws/ebs` key. Copying
  into a spoke in a *different account* (which PEEKS supports) would require a CMK set in
  the StorageClass `kmsKeyId`, so it is deferred.
- **Cost note.** An EBS copy into a vault with a *different* key is a **full (not
  incremental)** copy.

The credential half is **not** handled by anything in the backup
path, and this is a real hole the design must close:

- ESO's `ClusterSecretStore` is configured `region: <cluster-region>`. In the DR
  spoke that value is the DR region, so ESO reads Secrets Manager **in the DR region**.
- The source secrets were written to Secrets Manager **in the source region** — by
  `manageMasterUserPassword` (RDS), by the Keycloak config Job's `put-secret-value`,
  and by any `PushSecret`. None of these set a replica.
- Therefore, after a region failover, ESO finds the DR-region Secrets Manager **empty**
  for those keys, the `ExternalSecret`s stay unready, and the restored data volume is
  present but **unusable** — the exact "backup without a usable restore" failure the
  recovery boundary is meant to prevent.

The design closes this by making **Secrets Manager cross-region replication a
first-class, tier-aligned requirement**, symmetric to the EBS cross-region copy:

| Secret origin | How it reaches the DR region | Owned by |
|---|---|---|
| RDS master (`manageMasterUserPassword`) | Secrets Manager **multi-region replica** on the managed secret, created in the DR region | add a replica region to the RDS RGD / SM provisioning |
| Runtime-generated + pushed (Keycloak, `PushSecret`) | the generator writes to the DR region too — either an SM replica on the pushed secret, or the push targets both regions | the generating Job / ESO `PushSecret` spec |
| ESO-managed app secrets | the underlying SM secret carries a replica in the DR region | SM secret provisioning |

Concretely, the recommended v1 mechanism is **AWS Secrets Manager multi-region
replica secrets**: a secret created in the source region declares the DR region as a
replica, and SM keeps the replica in sync automatically. This keeps the *source of
truth single* (the primary secret) while making the value readable in the DR region,
so ESO in the DR spoke resolves its `ExternalSecret`s with no change to how workloads
consume them. For runtime-generated secrets, the generator's push must either target a
replicated secret or write to both regions, so the push-to-SM guardrail from
[The Secret gap](#the-secret-gap-runtime-generated-credentials) extends to "push to a
secret that is replicated to the DR region."

Concretely, the two halves line up as follows. The **data** half is the `copyAction`
the `BackupPlan` rule already carries for gold/silver, pointing a recovery-point copy
at the DR-region vault:

```yaml
# BackupPlan rules (gold) — the data half: hourly warm rule + optional monthly archive.
# The hourly rule carries NO cold-storage transition: AWS Backup only archives EBS on a
# monthly-or-rarer rule, so cold storage on an hourly rule archives nothing.
rules:
  - ruleName: gold-hourly
    targetBackupVaultName: <prefix>-<spoke>-gold        # primary region
    scheduleExpression: "cron(0 * * * ? *)"           # RPO 1h
    startWindowMinutes: 60                            # else the console 8h default applies
    lifecycle:
      deleteAfterDays: 14                              # warm only; no cold on an hourly rule
    recoveryPointTags:
      platform.gitops.io/backup-tier: gold
      platform.gitops.io/spoke: <spokeName>
    copyActions:
        # DR vault MUST be keyed with a CMK or aws/ebs (NOT a Backup-managed key):
        # EBS is not fully managed by AWS Backup, so a copy into a Backup-managed-key
        # vault fails. Warm recovery points only — cold-tier points can't be copied.
      - destinationBackupVaultARN: >-
          arn:aws:backup:<dr-region>:<account-id>:backup-vault:<prefix>-<spoke>-gold-dr
        lifecycle:
          deleteAfterDays: 30
  # OPTIONAL long-term archive: a SECOND, monthly rule is the only way to reach cold
  # storage for EBS. Omit it if long-term gold history is not required.
  - ruleName: gold-archive
    targetBackupVaultName: <prefix>-<spoke>-gold
    scheduleExpression: "cron(0 0 1 * ? *)"            # monthly — required for EBS archive
    startWindowMinutes: 60                             # keep SHORT: this rule fires at 00:00
                                                       # on the 1st, the same instant as the
                                                       # hourly rule. AWS Backup optimizes
                                                       # overlapping start windows to the
                                                       # longer-retention rule, so a wide
                                                       # (e.g. 8h) window here would suppress
                                                       # up to 8 hourly gold points on the 1st.
    lifecycle:
      moveToColdStorageAfterDays: 30
      optInToArchiveForSupportedResources: true        # REQUIRED for EBS archive
      deleteAfterDays: 120                              # must be >= cold + 90 (AWS Backup rule)
    recoveryPointTags:
      platform.gitops.io/backup-tier: gold
      platform.gitops.io/spoke: <spokeName>
    # no copyActions: cold-tier recovery points cannot be copied cross-region
```

> **Why `gold-archive`'s start window must be short.** `gold-hourly` and `gold-archive`
> both fire at `00:00` on the 1st of the month. When the start windows of different
> rules overlap, AWS Backup keeps the recovery point of the rule with the **longer
> retention**, and the optimization takes the **full** start window into account
> ([Create a backup
> plan](https://docs.aws.amazon.com/aws-backup/latest/devguide/creating-a-backup-plan.html)).
> With an 8h (`480`) window, `gold-archive` (120d) would win that whole window and
> suppress up to 8 hourly gold points on the 1st — and because `gold-archive` carries
> **no `copyActions`**, the one surviving monthly point is never copied to DR, so the
> 1h RPO is broken for up to 8h once a month. Pinning `startWindowMinutes: 60` (the API
> minimum) shrinks the overlap to a single hour; the one hourly point displaced in that
> hour has no DR copy, which is the only residual gap and is acceptable monthly.

The **credential** half is the matching Secrets Manager multi-region replica, so the
secret the restored volume needs is readable in the same `<dr-region>`:

```yaml
# ACK secretsmanager.services.k8s.aws Secret — the credential half:
# one source-region secret, replicated into the DR region
apiVersion: secretsmanager.services.k8s.aws/v1alpha1
kind: Secret
metadata:
  name: <prefix>-app-db-credentials
spec:
  name: <spokeName>/app/db-credentials                # single source of truth
  replicaRegions:
    - region: <dr-region>                             # SM keeps this replica in sync
  tags:
    - key: platform.gitops.io/spoke
      value: <spokeName>
    - key: platform.gitops.io/backup-tier
      value: gold
```

```yaml
# ESO ClusterSecretStore in the DR spoke resolves from the replica automatically —
# region is the DR spoke's own region, no per-workload change
spec:
  provider:
    aws:
      service: SecretsManager
      region: <dr-region>        # reads the replica of <spokeName>/app/db-credentials
```

The two `<dr-region>` values and the `<prefix>-<spoke>-gold` / `-dr` vault pairing are the
single wiring contract: the `BackupPlan` copies the volume into `<dr-region>`, and the
SM replica makes the unlocking secret present in that same `<dr-region>`, so ESO in the
DR spoke resolves the `ExternalSecret` and the restored volume comes up usable. For a
runtime-generated secret (Keycloak), the same `replicaRegions` lives on the secret the
config Job's `put-secret-value` targets, so the push lands on a replicated secret.

For the Keycloak case the secret is not born in Git or managed by RDS — the config Job
generates the OIDC client secret at runtime and pushes it to Secrets Manager. The push
must therefore itself ensure the replica exists in the DR region, so the pushed value
is readable there after failover:

```bash
# Keycloak config Job — the credential half for a runtime-generated secret.
# Mirrors the repo's Keycloak Job pattern: describe-secret -> put-or-create, with NO
# silent-failure masking (2>/dev/null || true would turn AccessDenied/throttling into a
# silently missing replica — exactly the DR hole this section warns about).
set -euo pipefail
SECRET_ID="<spokeName>/keycloak-clients"
PRIMARY="<primary-region>"
DR="<dr-region>"

if aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$PRIMARY" >/dev/null 2>&1; then
  # exists: push the new value, then ensure the DR replica exists (put-secret-value
  # never adds a replica, so replicate separately).
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_ID" --region "$PRIMARY" \
    --secret-string "$CLIENT_SECRETS_JSON"
  # Add the replica ONLY if it is missing. The API reference does not promise that
  # replicate-secret-to-regions is a no-op for an already-present region, so under
  # `set -e` a blind re-run could fail every reconcile. Read ReplicationStatus first.
  HAVE_REPLICA="$(aws secretsmanager describe-secret \
    --secret-id "$SECRET_ID" --region "$PRIMARY" \
    --query "ReplicationStatus[?Region=='$DR'] | length(@)" --output text)"
  if [ "$HAVE_REPLICA" = "0" ]; then
    aws secretsmanager replicate-secret-to-regions \
      --secret-id "$SECRET_ID" --region "$PRIMARY" \
      --add-replica-regions Region="$DR"
  fi
else
  # first run: create WITH the DR replica so the secret exists in both regions.
  aws secretsmanager create-secret \
    --name "$SECRET_ID" --region "$PRIMARY" \
    --add-replica-regions Region="$DR" \
    --secret-string "$CLIENT_SECRETS_JSON" \
    --tags Key=platform.gitops.io/spoke,Value=<spokeName> \
           Key=platform.gitops.io/backup-tier,Value=gold
fi

# GATE (not just a print): fail unless the DR replica reports InSync, so a half-made
# or Failed replica stops the Job rather than leaving a silent DR hole.
STATUS="$(aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$PRIMARY" \
  --query "ReplicationStatus[?Region=='$DR'].Status | [0]" --output text)"
if [ "$STATUS" != "InSync" ]; then
  echo "DR replica for $SECRET_ID in $DR is '$STATUS', not InSync" >&2
  exit 1
fi
```

> **Writing in the DR region during a real outage needs `StopReplicationToReplica`
> first.** A replica secret **cannot be updated independently** of its primary, so if
> the primary region is unreachable the DR-region Keycloak re-push cannot write the
> replica directly. The DR runbook must first call
> `aws secretsmanager stop-replication-to-replica --secret-id <arn> --region <dr-region>`,
> which promotes the DR replica to a standalone secret that can then be written; a
> failback step re-establishes replication from the (recovered) primary afterwards.

> **RDS-managed secrets are an unverified case — keep them out of v1 DR until tested.**
> Replicating the RDS-managed `rds!…` secret is not documented either way, and
> `ReplicateSecretToRegions` can return "the secret is managed by another service, and
> you must use that service to update it". So the RDS master-credential replica is
> marked **test-live-or-defer**: either verify it on an account, or keep RDS out of the
> v1 cross-region DR scope and rely on the RDS engine's own cross-region mechanisms.

```yaml
# ESO ExternalSecret consumed by langfuse (and other OIDC clients) in the DR spoke —
# resolves the replicated keycloak-clients secret from the DR-region SM, unchanged
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: langfuse-oidc
spec:
  secretStoreRef:
    name: aws-secrets-manager       # the repo's ClusterSecretStore name; its region = <dr-region> in the DR spoke
    kind: ClusterSecretStore
  data:
    - secretKey: client-secret
      remoteRef:
        key: <spokeName>/keycloak-clients
        property: LANGFUSE_CLIENT_SECRET
```

The sequencing consequence is specific to Keycloak: because the client secret is minted
by Keycloak itself, a reprovisioned Keycloak in the DR region can generate a *different*
value than the one in the replica. The config Job must run and **re-push** (after
promoting the DR replica to a standalone secret with `StopReplicationToReplica` — a
replica cannot be written while it is still a replica, see above) **before** OIDC
consumers like langfuse start — otherwise an app
reads a stale replicated value that no longer matches Keycloak. Replication removes the
cold-start emptiness; it does not remove the Keycloak-before-consumers ordering.

This also tightens the restore sequencing: in a cross-region DR the credential
generators (Keycloak et al.) still run before their consumers (per
[The Secret gap](#the-secret-gap-runtime-generated-credentials)), but if replication is
in place ESO can resolve immediately from the DR-region replica without waiting for a
generator to re-push — which is the faster and more reliable path. Replication is
therefore preferred over "re-generate on failover" wherever a secret supports it.

### Sequencing into a recovery

`RestoreSelection` slots into step 4 of the recovery flow in
[Recovery responsibility boundary](#recovery-responsibility-boundary--backup-vs-argo-cd--gitops):
Argo CD has already created the PVC (empty) from Git; `RestoreSelection` restores the
volume and binds a static PV to that PVC, so the stateful pod comes up on restored
data. For blue/green and cloning, `targetCluster: existing` points the restore at an
already-provisioned spoke; for reactive DR, the DR spoke is provisioned first by the
normal `SpokeCluster` path, then restored into.

## Alternatives considered: native AWS Backup support for Amazon EKS

Since **2025-11-10** AWS Backup supports **Amazon EKS as a resource type**
([AWS Backup now supports Amazon
EKS](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-backup-supports-amazon-eks/)),
which is a legitimate alternative to the EBS-only path this design takes, and the design
would be incomplete not to weigh it.

**What native EKS backup does.** Backing up an EKS cluster produces a **composite
recovery point** that includes both the Kubernetes cluster state and the persistent
storage attached via PVCs (EBS, EFS, S3), with a child recovery point per resource
([Amazon EKS
backups](https://docs.aws.amazon.com/aws-backup/latest/devguide/eks-backups.html);
[Back up your EKS Clusters with AWS
Backup](https://docs.aws.amazon.com/eks/latest/userguide/integration-backup.html)). A
restore targets an existing cluster, a brand-new cluster AWS Backup creates for you, or
specified namespaces, or restores persistent storage alone; AWS Backup restores the
`StorageClass`/PV/PVC objects for you
([Restore an Amazon EKS
cluster](https://docs.aws.amazon.com/aws-backup/latest/devguide/restoring-eks.html)).
The `BackupSelection` would then name the cluster
(`arn:aws:eks:<region>:<account-id>:cluster/<spoke>`) rather than EBS volumes, so the
`BackupPolicy` shape barely changes, and our spokes already meet the prerequisite
(`authenticationMode: API_AND_CONFIG_MAP`, confirmed in `rg-eks.yaml`). This collapses
most of the hard `RestoreSelection` work (the static-PV bind, metadata, AZ placement) —
a strong reason to consider it.

**Why v1 keeps the EBS-only, data-only path anyway (and does NOT invert the order).**
The native path's semantics actually argue *for* the data-only boundary this design
already draws, not for inverting to "restore-then-sync":

- **Cluster state includes Secrets**, which crosses the recovery boundary deliberately
  drawn in [Recovery responsibility
  boundary](#recovery-responsibility-boundary--backup-vs-argo-cd--gitops): Secrets are
  owned by ESO/Git, and a snapshot of a K8s Secret is a stale copy of something ESO
  already owns.
- **A namespace restore is not actually namespace-scoped:** the restore page states that
  for a namespace-level restore "**All cluster-scoped resources will also be restored**"
  ([Restore an Amazon EKS
  cluster](https://docs.aws.amazon.com/aws-backup/latest/devguide/restoring-eks.html)),
  so even the granular path reintroduces cluster-scoped objects (CRDs, ClusterRoles,
  webhooks) that Git owns — another reason the EBS-only, data-only path keeps the
  boundary clean.
- **Restores are non-destructive — "existing objects are not overwritten"** (verified on
  the restore page). So in an Argo-first recovery the restored PVCs/objects are
  **skipped**, which means a native restore cannot simply be layered after an Argo sync;
  it would have to run *first* and then fight Argo, the exact drift the boundary avoids.
- **Quotas:** 1 restore job per target cluster and 5 EKS restore jobs per account.
- **Auto Mode re-tagging** of restored EBS volumes (`eks:eks-cluster-name`, finding on
  [the hard part](#the-hard-part-restore-metadata-az-placement-and-the-static-pv-bind))
  is still required for cross-cluster restores.

**Decision.** Record native EKS backup as a first-class alternative and the likely
future direction (it would simplify the restore orchestrator substantially), but keep
the **EBS-only, data-only restore** as the v1 path for boundary cleanliness (Secrets
stay out of the restore), Argo-owns-Git correctness, and the quota profile. This is a
deliberate design choice, not an omission — and it is the one point of this revision
explicitly left open for the reviewer to disagree with.

## RPO / RTO targets and a learner-visible verify path

The tier table states an RPO and an RTO target per tier. Two caveats make those honest:

- **RPO** depends on `startWindowMinutes` being set (done in the tier rules): without it
  the console default of 8h applies, breaking a "1h RPO" claim. And because AWS Backup
  allows only **1 concurrent backup/copy job per resource**, a slow first full
  cross-Region copy can delay the next hourly job.
- **RTO** is a platform intent, **not** an AWS SLA: AWS Backup publishes no restore SLA,
  restored EBS volumes hydrate **lazily** (elevated I/O latency until blocks are first
  read), and an **archive** restore takes **up to 72h**. The RTO also presumes the
  restore orchestration is in place.

**A learner never sees a scheduled backup**, because silver fires at 02:00 UTC and
bronze at 03:00 UTC — outside a workshop session. So the design includes an **on-demand
verify path** that exercises the whole backup→restore loop in-session:

```bash
# 1. On-demand backup of a tagged volume (don't wait for the tier schedule).
aws backup start-backup-job \
  --backup-vault-name "<prefix>-<spoke>-gold" \
  --resource-arn "arn:aws:ec2:<region>:<account-id>:volume/<vol-id>" \
  --iam-role-arn "<backup-service-role-arn>"

# 2. Confirm it completed and a recovery point exists.
aws backup list-backup-jobs --by-state COMPLETED \
  --query 'BackupJobs[?BackupVaultName==`<prefix>-<spoke>-gold`].RecoveryPointArn'
aws backup list-recovery-points-by-backup-vault \
  --backup-vault-name "<prefix>-<spoke>-gold"

# 3. Restore into a scratch namespace and run a data check (see RestoreSelection),
#    then delete the scratch namespace and the restored volume.
```

## Teardown — reaping vaults, recovery points, replicas and retained volumes

Nothing in `task destroy` or the platform sweep knows about AWS Backup or detached EBS
volumes today, so without a dedicated reaper a torn-down stack leaves vaults, recovery
points, DR copies, SM replicas and retained volumes behind. This is a genuine hole, not
a nuance, and the design closes it with an **ordered, per-Region reaper that runs
BEFORE the IAM reaper** (because EBS recovery points must be deleted by the same role
that created them — if the backup service role is reaped first, the recovery points can
no longer be deleted).

First, **once globally, before any Region is drained:**

1. **Delete selections, then plans — all of them, up front.** `delete-backup-selection`
   for every selection, then `delete-backup-plan` (which works **only after all its
   selections are deleted**). Tolerate `NotFound`, since ACK may already have removed
   them on prune. This is done **once, before any vault is drained**, not inside the
   per-Region loop: the plan and its schedule live only in the **primary** Region, but
   the gold/silver rules carry a cross-Region `copyAction`, so while the plan is still
   live its copy action keeps landing fresh recovery points in the **DR** vault ([copy
   to a destination vault is a rule on the scheduled plan](https://docs.aws.amazon.com/aws-backup/latest/devguide/cross-region-backup.html#scheduled-crb)).
   If the plan were deleted only per-Region, a DR-first pass would drain the DR vault
   while the primary plan kept copying new points straight back into it, and the
   subsequent `delete-backup-vault` on DR would fail. Deleting all plans first stops
   every schedule **and** every cross-Region copy action, so no *new* recovery point
   can be created in either vault while they are being drained.

Then, **for each Region (primary + DR)**, for vaults owned by this stack (`name_is_ours`
or the prefix ownership tag), in this order:

2. **Wait for in-flight jobs** — poll `list-backup-jobs` / `list-copy-jobs` for this
   vault until no job is `RUNNING`/`CREATED`. A backup or cross-Region copy already in
   flight will still land a recovery point after step 1, so the vault is not provably
   drainable until these finish.
3. **Delete recovery points, then poll until the vault is empty**
   (`list-recovery-points-by-backup-vault` → `delete-recovery-point`, repeat). Deletion
   is **asynchronous** — points sit in `DELETING` — and `delete-recovery-point` returns
   `InvalidResourceStateException` while AWS Backup is already acting on a point, so the
   reaper must retry and re-list rather than assume one pass empties the vault. Cold-tier
   recovery points carry a pro-rated 90-day minimum charge on early deletion.
4. **Delete the vault** (`delete-backup-vault`) — this succeeds **only when the vault is
   empty** ([DeleteBackupVault](https://docs.aws.amazon.com/aws-backup/latest/devguide/API_DeleteBackupVault.html):
   "A vault can be deleted only if it is empty"), hence steps 1–3 first.
5. **Secrets Manager replicas, then detached volumes.**
   - `remove-regions-from-replication` (a primary secret that still has replicas
     **cannot be deleted**), *then* delete the secret. The current sweep swallows that
     ordering error and the secret silently survives.
   - Delete detached tier volumes by tag — retained `Released` gold volumes (and any
     silver/bronze that slipped through) carry the `platform.gitops.io/prefix` tag, so
     the reaper finds them by tag and deletes the detached ones.

Additional teardown facts the reaper must respect:

- **The DR Region is never swept today.** The platform sweep runs a single Region, so
  the DR vault, its copies and the SM replicas are invisible to it — the reaper must
  iterate both Regions explicitly.
- **Prefix-tagged vaults vs the §17d gate.** If vaults carry the prefix ownership tag
  (finding 9), the platform's §17d residue gate reports them as `tagged:` residue with
  no handler, so **every** teardown ends `DESTROY INCOMPLETE` until this reaper handles
  them — tagging and reaping must land together.
- **No Vault Lock in v1.** ACK does not model Vault Lock (which is good). State it
  explicitly: in compliance mode, after the ≥72h grace period a vault cannot be deleted
  and its recovery points cannot be deleted until their lifecycle completes (14d for
  the gold warm tier, 120d for the `gold-archive` tier), which would make teardown
  impossible — so v1 uses **no Vault
  Lock**.
- **Workshop default.** Delete everything on teardown, with an explicit **opt-out** for
  long-lived stacks that must keep their backup history.

This reaper (and the gated-app/RBAC/IAMRoleSelector wiring in [Platform wiring
required](#platform-wiring-required)) is the natural follow-up PR once this design
lands.

## Boundaries (what this does NOT cover)

This design is deliberately narrow. The following are explicitly out of scope and are
each already handled by an existing mechanism or a named future piece of work (the
rationale for each is the [Recovery responsibility boundary](#recovery-responsibility-boundary--backup-vs-argo-cd--gitops)):

- **Secrets** — covered by the External Secrets Operator; never captured in or
  restored from a volume snapshot.
- **Anything derivable from Git** — Deployments, Services, ConfigMaps, Ingresses, PVC
  templates: recovered by an Argo CD re-sync, not by restoring a snapshot. Backup must
  not restore these (it would reintroduce drift against `HEAD`).
- **Heavy stateful workloads (Postgres, Kafka, …)** — AWS Backup gives a
  *crash-consistent filesystem snapshot*, not a logical database backup. These
  workloads need an application-level logical backup (`pg_basebackup` + WAL archiving,
  Kafka tiered storage, etc.) *on top of* the FS snapshot this design provides.
- **Exposure / ingress** — backup/restore has no public endpoint, so exposure does not
  feature. Where exposure *is* needed elsewhere, the existing PEEKS platform mechanism
  is used; inventing an exposure mechanism is out of scope for this document.

## Platform capability & the IAM this design adds

This design has no external blocker: the backup CRDs are present on the current
platform. But the IAM is **more than one role** — a working end-to-end backup+restore
needs a controller role at three mint sites, a platform-created AWS Backup **service**
role, a separate **restore Job** identity, and the EKS Cluster IAM Role tag grant. This
section records the capability history (so a reviewer understands why the obsolete
side-load path exists), then specifies the full IAM shape and the platform wiring the
RGD needs.

### Capability history — why the side-load path is obsolete

**1. May 2026 — CRDs absent.** When this work began, the managed EKS ACK capability
provisioned roughly 180 CRDs but **none** from the `backup.services.k8s.aws` group.
There was no way to create `BackupVault` / `BackupPlan` / `BackupSelection` resources
in-cluster, so the only option was to **side-load** the upstream
`aws-controllers-k8s/backup-controller` Helm chart as a GitOps addon (the idea captured
in PR #631).

**2. Upstream controller reaches GA.** The upstream
`aws-controllers-k8s/backup-controller` reached GA in its 1.x line; the first 1.x
release is `v1.0.0` (2026-07-02) and the latest at the time of writing is `v1.3.1`
(2026-10-13). The ACK field names and behaviours in this doc are checked against the
version the capability actually ships — **pin that version** rather than citing a
specific runtime bump as "the latest".

**3. Now — CRDs bundled by the capability.** The managed ACK capability bundles all
three backup CRDs (`backupplans`, `backupselections`, `backupvaults` under
`backup.services.k8s.aws`). This was observed on a current PEEKS hub as part of a large
ACK CRD set across many service groups. **That live count is Region- and capability-
version-specific** — the exact number of CRDs/groups depends on which Region and
capability version the hub runs, and the fallback below exists precisely for a Region or
version that predates backup support — so treat the live count as an illustration, not a
guarantee. PR #631's side-load addon is therefore kept only as a documented **fallback**,
not the primary path.

### The IAM shape this design provisions

The CRDs being present lets the controller *create the CRs in-cluster*; calling the AWS
Backup APIs and running restores needs the following IAM, all additive to the platform's
existing provisioning:

| IAM piece | What it is | Where it is added |
|---|---|---|
| **Controller role** `<prefix>-cluster-mgmt-backup` | lets the backup controller call `backup:*` to create vaults/plans/selections | the **three** sites that mint the other `cluster-mgmt-*` roles (`scripts/create-cross-account-roles.sh`, `cluster-providers/kind-kro-ack/Taskfile.yaml`, `cluster-providers/kind-crossplane/Taskfile.yaml`) — each `for service in …` loop + policy map gains `backup` — **plus** a `backup-<cluster>` `IAMRoleSelector` in `multi-acct` (without it ACK creates the CR and never reconciles it) |
| **Backup service role** (platform-created) | the role AWS Backup assumes to act on selected resources and to run restores; `BackupSelection.iamRoleARN` / `RestoreSelection` reference it | platform IAM; its **name must match `*AWSBackup*`** (see PassRole note) and it carries `AWSBackupServiceRolePolicyForBackup` + `AWSBackupServiceRolePolicyForRestores` |
| **Restore Job role** | Pod Identity role in the cluster where the restore Job runs | platform IAM; permissions below |
| **Cluster IAM Role tag grant** | lets EKS Auto Mode stamp custom `platform.gitops.io/*` tags on provisioned EBS volumes | EKS Cluster IAM Role (already noted in [StorageClass tiers](#storageclass-tiers--volume-tagging)) |

Three facts correct the earlier "ships the one IAM piece" framing:

- **The AWS Backup service role is NOT auto-present.** `AWSBackupDefaultServiceRole` is
  created on **first console use**, or manually via the CLI — it does **not** exist in a
  fresh workshop account by default. The design must create it (or an equivalent
  platform-named service role), not assume it exists.
- **PassRole is name-scoped.** `AWSBackupFullAccess` grants `iam:PassRole` only on role
  names matching `arn:aws:iam::*:role/*AwsBackup*` / `*AWSBackup*` (to
  `backup.amazonaws.com`). A platform-created service role must therefore **match that
  name pattern**, or `cluster-mgmt-backup` needs its own explicit `PassRole` statement.
- **The restore Job needs its own identity** — the backup-controller models vaults/
  plans/selections only (no restore CRD), so `backup:StartRestoreJob` on the controller
  role is never exercised. The restore Job's Pod Identity role needs:
  `backup:StartRestoreJob`, `backup:GetRecoveryPointRestoreMetadata`,
  `backup:DescribeRestoreJob`, `backup:ListRecoveryPointsByBackupVault`,
  `backup:ListTags`, `iam:PassRole` on the restore role, `ec2:CreateTags`,
  `ec2:DescribeVolumes`, and KMS on the CMK if one is used.
- **Permissions boundary.** The repo's role scripts set no IAM permissions boundary. In
  accounts that enforce one, the new `cluster-mgmt-backup` controller role, the backup
  service role and the restore Job role must each attach the mandated boundary; the
  implementation should make the boundary a configurable input rather than assume its
  absence.

> **The Cluster IAM Role tag grant** (row 4) is a prerequisite of the whole tag-matching
> contract, not an optional extra: without it EKS Auto Mode silently never stamps the
> `platform.gitops.io/*` tags, so every `BackupSelection` matches zero volumes (see
> [StorageClass tiers + volume tagging](#storageclass-tiers--volume-tagging)).

### Platform wiring required

Beyond IAM, the RGD needs five pieces of platform wiring on `main`, each verified
against the repo:

- **a. A gated hub app.** `.../manifests/backup-policy/` would otherwise land in both the
  `kro-manifests-hub` and spoke `kro-manifests` apps, which exclude only listed subtrees.
  If the backup CRDs are absent (the doc's own fallback case) the RGD stays `Ready=False`
  and stalls the shared wave chain — the exact reason `ray-service` and `amp-incident`
  got dedicated gated apps. Add a `kro-backup-policy-rgd-hub` app (path
  `.../manifests/backup-policy`) gated on **both** `enable_kro_manifests_hub` **and**
  `enable_backup_policy` (the hub carries `enable_kro_manifests_hub`, never
  `enable_kro_manifests`, so this two-key selector keeps the hub RGD on the hub and off
  every spoke — the ray/amp shape at `platform.yaml:272-277`/`:298-303`, where the hub
  omits `enable_kro_manifests` at `:320-323`), and add
  `backup-policy/**` to the `exclude` list of **both** the `kro-manifests-hub` and the
  spoke `kro-manifests` apps. The restore subtree in (e) gets the same treatment on the
  spoke side (its own excluded subtree + dedicated gated app), so the generic exclusion
  in (a) can stay symmetric without stranding restore.
- **b. RBAC.** The `eks-capabilities-rbac` ClusterRole has **no** `backup.services.k8s.aws`
  rule (and no `storage.k8s.io`), so the kro capability cannot create the CRs as-is. Add
  the rule (same lesson as #1110).
- **c. IAMRoleSelector.** `multi-acct/iam-role-selectors.yaml` ends at `rds`; without a
  `backup-<cluster>` selector ACK creates the CR and never reconciles it.
- **d. StorageClass home.** A hub-side RGD cannot place StorageClasses into a spoke. The
  tier classes are rendered by the `default-storage-class` chart (add `clusterName` to
  its `valuesObject`), **not** by the `BackupPolicy` RGD — and the doc's earlier
  self-contradiction ("the RGD renders them") is corrected to the chart throughout.
- **e. `RestoreSelection` is a SPOKE-side object with its own gated app.** The same rule
  as (d) applies to restore: `RestoreSelection` materializes a Kubernetes Job and a
  static PV that must exist in the **target spoke**, and the gated
  `kro-backup-policy-rgd-hub` app from (a) runs on the hub — a hub RGD cannot place a
  Job or a PV into a spoke. But it **cannot** simply ride the generic spoke
  `kro-manifests` app either: that app is gated only on `enable_kro_manifests`, and (a)
  excludes `backup-policy/**` from it — so the restore objects would be either ungated
  (shipped to every `enable_kro_manifests` spoke regardless of whether backup is on) or
  excluded along with the rest of `backup-policy/**`. Resolve both by giving restore its
  **own subtree** — `.../manifests/backup-restore/` — and a **dedicated spoke-side app**,
  `kro-backup-restore-spoke` (path `.../manifests/backup-restore`), gated on **both**
  `enable_kro_manifests` **and** `enable_backup_policy` — the spoke discriminator the hub
  lacks, so the restore Job and static PV land only on `enable_kro_manifests` spokes and
  never on the hub (the exact failure (e) exists to prevent: the hub must carry
  `enable_backup_policy` for the declarative objects in (a), so gating restore on that
  flag alone would also generate `kro-backup-restore-spoke` on the hub). Add
  `backup-restore/**` to the `exclude` list of the
  spoke `kro-manifests` app (and the hub app) so it is not double-applied, mirroring how
  `ray-service` and `amp-incident` are each excluded from the generic trees and shipped by
  their own gated apps. The restore Job then authenticates as a **spoke Pod Identity role**
  (the "Restore Job role" in the IAM table), not as the hub controller role. Net: the
  declarative `BackupPolicy` vault/plan/selection objects are hub-reconciled ACK resources
  under the **`enable_kro_manifests_hub` + `enable_backup_policy`**-gated **hub** app, and the
  restore Job + static PV are placed by the **`enable_kro_manifests` + `enable_backup_policy`**-gated
  **spoke** app — `enable_backup_policy` stays the single feature toggle (turn it on for the hub
  and the target spokes to enable the whole feature), while the existing `enable_kro_manifests*`
  role discriminator keeps each object on its correct cluster, exactly mirroring the StorageClass
  split in (d).

## Consolidation plan & PR provenance

This is a **fresh consolidation, not a rebase.** The PRs it supersedes targeted
`feature/platform-cluster-kro-ack` (from PR #642), which was closed and never merged,
so they sit on a dead feature line. The
`gitops/addons/charts/kro/resource-groups/manifests/` structure they relied on is on
`main`, and there is **no backup content on `main` today**, so the `BackupPolicy` RGD
lands cleanly at `.../manifests/backup-policy/`.

Disposition of the prior PRs:

- **KEEP — PR #661** as the canonical `BackupPolicy` RGD plus the DR-aware tier
  StorageClasses. It is clean, additive, and 9 commits of focused scope.
- **KEEP THE IDEA — PR #631** (making the ACK backup controller available). As written
  it is now **obsolete** (the capability bundles the CRDs — see
  [Platform capability & the IAM this design adds](#platform-capability--the-iam-this-design-adds)),
  so it is documented here only as a **legacy fallback** for pre-backup capability
  versions, not carried forward as-is.
- **DROP — PR #633.** Its own final commit self-marks the branch `DEPRECATED`.
- **DROP — PR #644.** It is a 22-commit superset that carries unrelated
  ingress / kind / cert-manager work and so is not a clean source for this design.

All four PRs are **closed and replaced** by a single consolidated branch and PR
(`feat/peeks-backup-policy-consolidated`), which:

1. Homes the tier StorageClasses on the `default-storage-class` chart pattern (see
   [StorageClass tiers + volume tagging](#storageclass-tiers--volume-tagging)).
2. Uses the PEEKS tag-propagation and `adopt-or-create` mechanisms (see
   [Tag propagation & resource adoption](#tag-propagation--resource-adoption-reusing-peeks-platform-mechanisms)) —
   `awsTags` on the vault/plan and `adopt-or-create` + `deletion-policy: retain`
   on the vault.
3. Specifies the **`RestoreSelection` RGD** (see [Restore design](#restore-design--the-restoreselection-rgd))
   alongside `BackupPolicy`, so the design covers a complete backup *and* restore kit.
4. Specifies the full **IAM shape** the implementation needs (see
   [Platform capability & the IAM this design adds](#platform-capability--the-iam-this-design-adds)):
   the `<prefix>-cluster-mgmt-backup` controller role at its three mint sites, the
   platform-created AWS Backup service role, the restore Job role, and the Cluster IAM
   Role tag grant. This PR is **docs-only** — it delivers the design and that IAM shape,
   not the IAM itself.
5. Declares **Secrets Manager cross-region replication** for secrets that DR-region
   workloads depend on (see
   [Cross-region restore & Secrets Manager replication](#cross-region-restore--secrets-manager-replication)),
   so a cross-region restore recovers data *and* the credentials that unlock it.
6. Carries **no ingress / exposure content** — the PEEKS platform already has a
   validated exposure mechanism, and backup has no public endpoint regardless.

## Known limitations (v1)

- **No KMS custom key / rotation on the primary vault.** The primary EBS recovery points
  keep the **source volume's** key (independent AWS Backup encryption is not supported
  for EBS); custom-managed-key and rotation configuration are not in v1. The **DR vault
  is the exception that matters**: it must be keyed with a CMK or `aws/ebs`, because an
  EBS cross-Region copy into a Backup-managed-key vault fails.
- **Heavy stateful workloads need application-level backup.** AWS Backup provides a
  crash-consistent filesystem snapshot, not a logical database backup; Postgres, Kafka
  and similar need an app-level logical backup workflow layered on top.
- **`copyDestinationVaultARN` must pre-exist in the DR region, keyed with a CMK/`aws/ebs`.**
  Cross-region copy for gold / silver targets a vault that must already be provisioned in
  the destination region (the Region is encoded in the ARN — there is no separate
  `copyDestinationRegion` field). Nesting that vault inside the RGD is a possible future
  iteration. **Cross-account** copy is out of scope for v1 (it needs a CMK set in the
  StorageClass `kmsKeyId`).
- **Restore is Job-orchestrated in v1, not ACK-native.** AWS Backup restore
  (`StartRestoreJob`) has no declarative ACK CRD at the version the capability ships, so
  `RestoreSelection` drives it via a Kubernetes Job (option A). It collapses to a clean
  ACK resource only if/when the controller ships a declarative restore CRD (option B).
- **Native EKS backup is deliberately not used in v1.** The composite EKS recovery point
  (GA 2025-11-10) would simplify restore but its cluster-state-includes-Secrets and
  non-destructive-skip semantics cross this design's recovery boundary, so v1 stays on
  the EBS-only data path — see
  [Alternatives considered](#alternatives-considered-native-aws-backup-support-for-amazon-eks).
- **Restore sequencing is a known sharp edge.** The restored static PV must bind to the
  Git-created PVC *before* the stateful pod goes Ready, and the restore itself mints a
  **new volume in a fixed AZ** that must match where the pod schedules. Getting this
  right means: fetch restore metadata (`GetRecoveryPointRestoreMetadata`), poll
  `DescribeRestoreJob` for `CreatedResourceArn`, `ec2:CreateTags` the new volume with
  `eks:eks-cluster-name=<target>` (or Auto Mode won't attach it) plus the tier tags,
  then create a static PV with `claimRef` (pre-bound to the PVC) and `nodeAffinity`
  (`topology.kubernetes.io/zone`). **StatefulSets** need the restore gated before the
  Argo app syncs (or a scale-to-0/back), because their PVCs are created with the pod —
  see [The hard part](#the-hard-part-restore-metadata-az-placement-and-the-static-pv-bind).
  This is the bulk of the `RestoreSelection` implementation, not a detail.
- **Teardown needs a dedicated ordered reaper (does not exist yet).** `task destroy` and
  the sweep know nothing about AWS Backup vaults, recovery points, DR copies, SM replicas
  or retained volumes, and the sweep is single-Region. Without the ordered, per-Region
  reaper (recovery points → vault → selections/plans → remove-replication/secret →
  detached volumes, before the IAM reaper) a torn-down stack leaves residue and, if
  vaults are prefix-tagged, ends `DESTROY INCOMPLETE`. v1 uses **no Vault Lock** (which
  would make a compliance-mode vault undeletable until its lifecycle completes). See
  [Teardown](#teardown--reaping-vaults-recovery-points-replicas-and-retained-volumes).
- **Namespace labels are not proof of backup coverage.** The developer opt-in label on a
  namespace is intent; `BackupSelection` matches the **tag on the EBS volume**, stamped
  only when a PVC uses a tier StorageClass. A labelled namespace whose PVCs use the
  default (untagged) class is silently *not* backed up. Coverage must be audited over
  volumes (`describe-volumes` by tag), not namespaces, and a drift check should flag the
  difference — see [Developer opt-in contract](#developer-opt-in-contract).
- **Gold `reclaimPolicy: Retain` leaves orphaned volumes.** `Retain` is **not** a restore
  precondition (a restore always mints a new volume); silver/bronze use `Delete`. Gold
  keeps `Retain` only for the mistake-deletion window, and only if paired with the
  cleanup reaper — otherwise deleted gold PVCs leave orphaned `Released` PVs / detached
  EBS volumes that accrue cost. See
  [Teardown](#teardown--reaping-vaults-recovery-points-replicas-and-retained-volumes).
- **Runtime-generated secrets must self-push to Secrets Manager.** A credential minted
  in-cluster (e.g. a Keycloak OIDC client secret) is recoverable only if its generator
  pushes it to Secrets Manager (`PushSecret` or a Job `put-secret-value`); this design
  does not back up K8s Secrets. The gap is a convention, not an enforced constraint — a
  future lint could reject a chart that generates a secret without a push. See
  [The Secret gap](#the-secret-gap-runtime-generated-credentials).
- **Cross-region restore depends on Secrets Manager replication being set up.** ESO and
  the secret generators are pinned to the cluster's own region, so a different-region
  restore recovers the EBS data but not the credentials unless the SM secrets carry a
  replica in the DR region. The design calls for SM multi-region replicas on
  DR-relevant secrets; wiring that into the RDS RGD / SM provisioning is an
  implementation task, and a secret missing its replica is a silent DR hole until
  tested. See
  [Cross-region restore & Secrets Manager replication](#cross-region-restore--secrets-manager-replication).
