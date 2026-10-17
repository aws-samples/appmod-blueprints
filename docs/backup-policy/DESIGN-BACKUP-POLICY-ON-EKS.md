# Design: AWS Backup & Restore for EKS — the `BackupPolicy` and `RestoreSelection` ResourceGraphDefinitions

## Summary

This document consolidates the AWS Backup for EKS work into a single, reviewable
design, and extends it to cover the **restore** half — because a backup without a
restore path protects nothing. It describes two kro `ResourceGraphDefinition`s (RGDs):

- **`BackupPolicy`** — expands into ACK `backup.services.k8s.aws` resources (a
  **BackupVault**, a **BackupPlan**, and a **BackupSelection**) for three service
  tiers (gold / silver / bronze), together with **DR-aware tiered StorageClasses**
  that tag the EBS volumes they provision so `BackupSelection` can match them.
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

The design is self-contained: it ships the one IAM piece a working end-to-end
backup needs — a `<prefix>-cluster-mgmt-backup` workload role added to the platform's
IAM provisioning — as part of the consolidated PR rather than treating it as an
external prerequisite. The platform-capability history that led here and the exact
role specification are in
[Platform capability & the IAM role this design adds](#platform-capability--the-iam-role-this-design-adds).

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
│  name: peeks-<spoke>-<tier>
│  tags: <awsTags>              ── platform tags merged in (see Tag propagation)
│  adoption-policy: adopt-or-create
└────
   │
   ▼
┌─ BackupPlan (ACK)             ── one variant per tier (includeWhen)
│  rules: schedule + lifecycle
│  recoveryPointTags: platform.gitops.io/backup-tier, platform.gitops.io/spoke, <awsTags>
│  copyActions for gold / silver (cross-region)
└────
   │
   ▼
┌─ BackupSelection (ACK)        ── one variant per tier
│  iamRoleARN: <from claim; AWSBackupDefaultServiceRole>
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

| Tier   | Schedule              | RPO | Retention | Cold storage | Cross-region copy |
|--------|-----------------------|-----|-----------|--------------|-------------------|
| gold   | `cron(0 * * * ? *)`   | 1h  | 180d      | after 90d    | yes               |
| silver | `cron(0 2 * * ? *)`   | 24h | 14d       | —            | yes               |
| bronze | `cron(0 3 * * ? *)`   | 24h | 7d        | —            | no                |

Cross-region copy targets are supplied by the claim as `copyDestinationRegion` +
`copyDestinationVaultARN`. The destination vault is expected to already exist in the
DR region (see [Known limitations](#known-limitations-v1)).

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

PEEKS threads a platform-wide tag map through the whole provisioning chain, carried by
the `platform.gitops.io/prefix` + `platform.gitops.io/cluster` ownership tags:

```
config.local.yaml  platformTags: {…}
   │  (compact JSON)
   ▼
hub cluster-secret  annotation  platform_tags: '{…}'
   │  (clusters-kro ApplicationSet, global.platformTags)
   ▼
RGD schema field    spec.awsTags: map[string]string
   │  (kro CEL: Maps.merge — user keys win, platform keys cannot be silently dropped)
   ▼
ACK resource        spec.tags: {built-in… , <awsTags>}
```

The EKS RGD consumes `awsTags` with exactly this merge, e.g.:

```yaml
# how an ACK resource consumes awsTags in an existing RGD (rg-eks.yaml)
tags: '${ {"kro-management": schema.spec.name, "tenant": schema.spec.tenant}
         .merge(schema.spec.?awsTags.orValue({})) }'
```

`BackupPolicy` exposes the same `awsTags` schema field and merges it into:

- `BackupVault.spec.tags` — so vaults carry the platform ownership tags
  (`platform.gitops.io/prefix` + `platform.gitops.io/cluster`), cost-allocation tags,
  and the SpringClean `auto-delete=no` retention tag, exactly like every other
  platform-created AWS resource. This is what lets the teardown/cost sweepers enumerate
  and protect backup vaults.
- `BackupPlan.recoveryPointTags` — so every recovery point produced is self-describing
  (which spoke, which tier, which deployment), which the restore side relies on to
  find the right recovery point (see [Restore design](#restore-design--the-restoreselection-rgd)).

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

`BackupVault` and `BackupPlan` are name-keyed (ACK derives the key from `spec.name`),
so `adopt-or-create` alone is sufficient for them — no `adoption-fields` block needed.
`BackupSelection` is created fresh each time (it is cheap and derivable), so it does
not need adoption.

## StorageClass tiers + volume tagging

For `BackupSelection` to have anything to match, the EBS volumes must carry the
`platform.gitops.io/backup-tier` and `platform.gitops.io/spoke` tags. That is the job of the tiered
StorageClasses. Each tier StorageClass passes the tags to the EBS CSI driver via its
`tagSpecification_<N>` parameters; the driver stamps them onto every volume it
dynamically provisions from that class:

```yaml
# One StorageClass per tier; the EBS CSI driver copies these tags onto the volume.
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: peeks-gold-gp3
provisioner: ebs.csi.eks.amazonaws.com
reclaimPolicy: Retain          # gold / silver = Retain; bronze = Delete (ephemeral)
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
  tagSpecification_1: "platform.gitops.io/managed-by=peeks-platform"
  tagSpecification_2: "platform.gitops.io/backup-tier=gold"
  tagSpecification_3: "platform.gitops.io/spoke=<spokeName>"
```

`<spokeName>` is a single top-level value merged into every tier StorageClass as
`platform.gitops.io/spoke=<spokeName>`, which is what scopes a spoke's backups to that spoke.
The `reclaimPolicy: Retain` on gold/silver is deliberate: it keeps the EBS volume (and
therefore the recovery-point source) alive even if the PVC is deleted, which is a
precondition for a clean restore.

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
> [Platform capability & the IAM role this design adds](#platform-capability--the-iam-role-this-design-adds)):
> without it the whole tag-matching contract is a no-op — the volumes carry no
> `platform.gitops.io/*` tags, so every tier's `BackupSelection` matches zero volumes.
> (Also note the parameter spelling: Auto Mode expects a `tags` parameter; the
> `tagSpecification_<N>` form shown above is the self-managed driver's syntax and must be
> reconciled with the Auto Mode `tags` parameter when the classes are actually authored.)

> **`Retain` ≠ backup, and it leaks volumes.** `reclaimPolicy: Retain` keeps the source
> volume alive but it is **not** a backup (a backup is the recovery point in the vault),
> and it has a cost: when a PVC is deleted the volume is **not** reclaimed, so deleted
> gold/silver PVCs leave **orphaned `Released` PVs and detached EBS volumes** that accrue
> storage charges and residue indefinitely. The design must pair `Retain` with a cleanup
> guardrail — a reaper (or a reviewed, scheduled sweep) that deletes `Released` PVs whose
> recovery points are safely captured, scoped by the same `platform.gitops.io/spoke` tag.
> Without it, `Retain` turns every ephemeral gold/silver PVC into permanent orphaned
> spend — exactly the kind of residue the platform's teardown/cost sweepers exist to
> catch. Bronze stays `reclaimPolicy: Delete` precisely to avoid this for ephemeral data.

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

The three tier classes (`peeks-gold-gp3`, `peeks-silver-gp3`, `peeks-bronze-gp3`)
extend that chart's pattern — same provisioner and binding mode — adding the
`tagSpecification_<N>` tag parameters and the per-tier reclaim policy. The existing
single default class stays the cluster default; the tier classes are additive and
non-default, so workloads that do not opt into a tier keep the current behaviour
unchanged.

## Developer opt-in contract

Opting a workload into backup is declarative and auditable:

1. A namespace (or workload) is labelled with its backup tier via the
   `platform.gitops.io/backup-tier` tag, and scoped to a spoke via `platform.gitops.io/spoke`.
2. The workload's PersistentVolumeClaims reference the matching tier StorageClass
   (`peeks-gold-gp3` / `peeks-silver-gp3` / `peeks-bronze-gp3`).
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
does **not** expose a declarative `RestoreJob` CRD at the GA v1.2.1 surface. So
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
     iamRoleARN:         <AWSBackupDefaultServiceRole ARN>
   │
   ▼
┌─ a Kubernetes Job (or ACK controller once a RestoreJob CRD exists)
│  that resolves the recovery point by recoveryPointTags
│  (platform.gitops.io/spoke + platform.gitops.io/backup-tier, newest ≤ recoveryPointAt)
│  and calls backup:StartRestoreJob with:
│    metadata.pvName / newVolume tags → re-stamp platform.gitops.io/* so the restored
│                                        volume is itself re-selectable
│  then watches the restore job to completion
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
  pattern as `BackupPolicy`. Documented as the target end-state; not available at GA
  v1.2.1.

### The hard part: restore metadata, AZ placement, and the static-PV bind

The orchestrator sketch above hides the three things that are actually hard about an
EBS restore. They are called out here because they are ~80% of the real
`RestoreSelection` work and the design is not implementable until they are specified.

**1. A restore mints a NEW volume — it is never in-place, and it needs metadata.**
`StartRestoreJob` does not rehydrate the original volume; it creates a **new EBS volume
with a new volume ID** from the recovery point. The call also **requires restore
metadata** that is not implicit in the recovery point: volume `type`, `size` (GiB),
`iops`/`throughput`, `encrypted` + the KMS key, and the target **Availability Zone**.
The orchestrator must fetch the valid/required keys with
`backup:GetRecoveryPointRestoreMetadata` first, then pass a complete metadata document
to `StartRestoreJob`. So the Job is a two-step `get-restore-metadata → start-restore-job`,
not a one-liner, and the `<prefix>-cluster-mgmt-backup` role needs
`backup:GetRecoveryPointRestoreMetadata` alongside `backup:StartRestoreJob`.

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
  persistentVolumeReclaimPolicy: Retain                # never GC the restored data
  storageClassName: peeks-gold-gp3                     # match the PVC's class, so Argo's
                                                       # dynamic PVC binds here not to a new disk
  claimRef:                                            # PRE-BIND to the exact PVC → no race
    namespace: <workload-ns>
    name: <pvc-name>
  nodeAffinity:                                        # pin the pod to the volume's AZ
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.ebs.csi.eks.amazonaws.com/zone
              operator: In
              values: ["<restored-volume-az>"]
  csi:
    driver: ebs.csi.eks.amazonaws.com
    volumeHandle: <new-volume-id>                      # the id StartRestoreJob returned
```

The two load-bearing fields are `claimRef` (pre-binding the PV to the specific PVC so
the Argo-created dynamic PVC adopts the restored volume instead of provisioning a fresh
empty one — this closes the race where the PVC binds first) and `nodeAffinity` (so the
scheduler only places the stateful pod on a node in the restored volume's AZ). The
orchestrator fills `storage`, `<restored-volume-az>`, and `volumeHandle` from the
restore-job output and the restore metadata. **Re-stamp the `platform.gitops.io/*` tags
on the new volume** (step in the orchestrator sketch) so the restored volume is itself
re-selectable by the next backup cycle — otherwise the restored data would silently fall
out of its tier's `BackupSelection`.

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
point exists there. The credential half is **not** handled by anything in the backup
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
# BackupPlan rule (gold) — the data half: copy the recovery point to the DR region
rules:
  - ruleName: gold-hourly
    targetBackupVaultName: <prefix>-gold-vault        # primary region
    scheduleExpression: "cron(0 * * * ? *)"           # RPO 1h
    lifecycle:
      moveToColdStorageAfterDays: 90
      deleteAfterDays: 180                             # must be >= cold + 90 (AWS Backup rule)
    recoveryPointTags:
      platform.gitops.io/backup-tier: gold
      platform.gitops.io/spoke: <spokeName>
    copyActions:
      - destinationBackupVaultArn: >-
          arn:aws:backup:<dr-region>:<account-id>:backup-vault:<prefix>-gold-vault-dr
        lifecycle:
          deleteAfterDays: 30
```

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

The two `<dr-region>` values and the `<prefix>-gold-vault` / vault-`-dr` pairing are the
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
# Keycloak config Job — the credential half for a runtime-generated secret:
# create the secret WITH a DR replica on first run, then put new values idempotently.
# NOTE: --add-replica-regions is honored ONLY by create-secret. On a hub where the
# secret already exists, create-secret fails and the || path runs put-secret-value,
# which does NOT add a replica — so the replica must be ensured separately with
# replicate-secret-to-regions (idempotent; no-op if the replica already exists).
SECRET_ID="<spokeName>/keycloak-clients"

# first run: create-secret with an add-replica-region so the DR region has the secret too
aws secretsmanager create-secret \
  --name "$SECRET_ID" \
  --region "<primary-region>" \
  --add-replica-regions Region="<dr-region>" \
  --secret-string "$CLIENT_SECRETS_JSON" \
  --tags Key=platform.gitops.io/spoke,Value=<spokeName> \
         Key=platform.gitops.io/backup-tier,Value=gold \
  2>/dev/null \
|| {
     # secret already exists: push the new value AND ensure the DR replica exists,
     # because put-secret-value alone never adds a replica.
     aws secretsmanager put-secret-value \
       --secret-id "$SECRET_ID" \
       --region "<primary-region>" \
       --secret-string "$CLIENT_SECRETS_JSON"
     aws secretsmanager replicate-secret-to-regions \
       --secret-id "$SECRET_ID" \
       --region "<primary-region>" \
       --add-replica-regions Region="<dr-region>" \
       2>/dev/null || true   # idempotent: no-op if the replica is already configured
   }
```

```yaml
# ESO ExternalSecret consumed by langfuse (and other OIDC clients) in the DR spoke —
# resolves the replicated keycloak-clients secret from the DR-region SM, unchanged
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: langfuse-oidc
spec:
  secretStoreRef:
    name: cluster-secret-store      # ClusterSecretStore region = <dr-region> in DR spoke
    kind: ClusterSecretStore
  data:
    - secretKey: client-secret
      remoteRef:
        key: <spokeName>/keycloak-clients
        property: LANGFUSE_CLIENT_SECRET
```

The sequencing consequence is specific to Keycloak: because the client secret is minted
by Keycloak itself, a reprovisioned Keycloak in the DR region can generate a *different*
value than the one in the replica. The config Job must run and **re-push** (overwriting
the replica's primary) **before** OIDC consumers like langfuse start — otherwise an app
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

## Platform capability & the IAM role this design adds

This design has no external blocker: the backup CRDs are present on the current
platform, and the one IAM piece that makes the controller able to call AWS Backup is
**shipped by this PR** as part of the platform's IAM provisioning. This section records
the capability history that led here (so a reviewer understands why the obsolete
side-load path exists) and then specifies the IAM role the design adds.

### Capability history — why the side-load path is obsolete

**1. May 2026 — CRDs absent.** When this work began, the managed EKS ACK capability
provisioned roughly 180 CRDs but **none** from the `backup.services.k8s.aws` group.
There was no way to create `BackupVault` / `BackupPlan` / `BackupSelection` resources
in-cluster, so the only option was to **side-load** the upstream
`aws-controllers-k8s/backup-controller` **Preview v0.1.1** Helm chart as a GitOps addon
(the idea captured in PR #631).

**2. September 18 2026 — upstream controller reaches GA.** The upstream
`aws-controllers-k8s/backup-controller` reached **GA — v1.2.1** (ACK runtime v0.64.0).

**3. Now (verified live on a current PEEKS hub, 2026-10-08).** The managed ACK
capability **bundles all three backup CRDs** — `backupplans`, `backupselections`, and
`backupvaults` under `backup.services.k8s.aws`. Verified on a current PEEKS hub running
the managed ACK capability: **265 ACK CRDs across 68 service groups are present,
including the backup group.** PR #631's side-load addon is therefore **obsolete** and is
kept only as a documented **fallback** for clusters or regions whose capability version
predates backup support — not as the primary path.

### The IAM role this design provisions

The CRDs being present means the backup controller can *create the CRs in-cluster*. To
also let it **call the AWS Backup APIs**, this design adds one workload role to the
platform's existing IAM provisioning. The capability's IAM is structured so this is a
clean, additive change, not a workaround:

- The capability role (`<hub>-ack-capability-role`) carries **no service permissions
  directly**. It only has:
  - `AssumeWorkloadRoles` — permission to assume `<prefix>-cluster-mgmt-*` roles, and
  - `ManageIRSARoles` — permission to manage `<hub>-*` IRSA roles.
- The provisioned per-service management roles are
  `<prefix>-cluster-mgmt-{ec2,eks,iam,ecr,s3,dynamodb,secretsmanager,rds}` — eight roles,
  created by `scripts/create-cross-account-roles.sh` (its `for service in …` loop). This
  design adds the missing **`<prefix>-cluster-mgmt-backup`** sibling (a ninth role).

So the deliverable is: **add a `<prefix>-cluster-mgmt-backup` workload role** in the
PEEKS platform IAM provisioning (the terraform / hub-config layer that already mints the
other `cluster-mgmt-*` roles), granting AWS Backup permissions (e.g.
`AWSBackupFullAccess`, or a scoped `backup:*` policy that **must include
`backup:StartRestoreJob` and `backup:GetRecoveryPointRestoreMetadata`** for the restore
side), and make it assumable by the capability
role — exactly the shape of the five roles that already exist. Once that role is in
place the controller's reconcile can create vaults/plans/selections *and* drive restore
jobs end-to-end.

`AWSBackupDefaultServiceRole` — the service role that `BackupSelection` references via
`iamRoleARN` so AWS Backup can act on the selected resources, and that `RestoreSelection`
reuses to run the restore job — **already exists in the account**, so no additional
service role is needed; the design adds only the controller's own `cluster-mgmt-backup`
credential.

> **A second IAM deliverable: the Cluster IAM Role tag grant.** The `cluster-mgmt-backup`
> role above is what lets the *controller call AWS Backup*. Separately, for the tier
> `StorageClass`es to actually stamp `platform.gitops.io/*` tags onto the EBS volumes
> under EKS Auto Mode, the **EKS Cluster IAM Role** must be granted the matching custom-tag
> permissions (see [StorageClass tiers + volume tagging](#storageclass-tiers--volume-tagging)).
> Without that grant the tags silently never land and every `BackupSelection` matches zero
> volumes, so this grant is a prerequisite of the whole tag-matching contract — not an
> optional extra.

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
  [Platform capability & the IAM role this design adds](#platform-capability--the-iam-role-this-design-adds)),
  so it is documented here only as a **legacy fallback** for pre-backup capability
  versions, not carried forward as-is.
- **DROP — PR #633.** Its own final commit self-marks the branch `DEPRECATED`.
- **DROP — PR #644.** It is a 22-commit superset that carries unrelated
  ingress / kind / cert-manager work and so is not a clean source for this design.

All four PRs are **closed and replaced** by a single consolidated branch and PR in the
user's fork (`feat/peeks-backup-policy-consolidated`), which:

1. Homes the tier StorageClasses on the `default-storage-class` chart pattern (see
   [StorageClass tiers + volume tagging](#storageclass-tiers--volume-tagging)).
2. Uses the PEEKS tag-propagation and `adopt-or-create` mechanisms (see
   [Tag propagation & resource adoption](#tag-propagation--resource-adoption-reusing-peeks-platform-mechanisms)) —
   `awsTags` on the vault/plan and `adopt-or-create` + `deletion-policy: retain`
   on the vault.
3. Ships the **`RestoreSelection` RGD** (see [Restore design](#restore-design--the-restoreselection-rgd))
   alongside `BackupPolicy`, so the PR delivers a complete backup *and* restore kit.
4. Adds the **`<prefix>-cluster-mgmt-backup` workload role** to the platform IAM
   provisioning (see
   [Platform capability & the IAM role this design adds](#platform-capability--the-iam-role-this-design-adds)),
   so the backup controller can call AWS Backup and run restore jobs without any
   out-of-band IAM step.
5. Declares **Secrets Manager cross-region replication** for secrets that DR-region
   workloads depend on (see
   [Cross-region restore & Secrets Manager replication](#cross-region-restore--secrets-manager-replication)),
   so a cross-region restore recovers data *and* the credentials that unlock it.
6. Carries **no ingress / exposure content** — the PEEKS platform already has a
   validated exposure mechanism, and backup has no public endpoint regardless.

## Known limitations (v1)

- **No KMS custom key / rotation.** The vault uses the default vault key; custom-managed
  key encryption and rotation are not configured in v1.
- **Heavy stateful workloads need application-level backup.** AWS Backup provides a
  crash-consistent filesystem snapshot, not a logical database backup; Postgres, Kafka
  and similar need an app-level logical backup workflow layered on top.
- **`copyDestinationVaultARN` must pre-exist in the DR region.** Cross-region copy for
  gold / silver targets a vault that must already be provisioned in the destination
  region. Nesting that vault inside the RGD is a possible future iteration.
- **Restore is Job-orchestrated in v1, not ACK-native.** AWS Backup restore
  (`StartRestoreJob`) has no declarative ACK CRD at GA v1.2.1, so `RestoreSelection`
  drives it via a Kubernetes Job (option A). It collapses to a clean ACK resource only
  if/when the controller ships a declarative restore CRD (option B).
- **Restore sequencing is a known sharp edge.** The restored static PV must bind to the
  Git-created PVC *before* the stateful pod goes Ready, and the restore itself mints a
  **new volume in a fixed AZ** that must match where the pod schedules. Getting this
  right means: fetch restore metadata (`GetRecoveryPointRestoreMetadata`), choose the
  target AZ deliberately, create a static PV with `claimRef` (pre-bound to the PVC) and
  `nodeAffinity` (pinned to the volume's AZ), and re-stamp the volume's tier tags — see
  [The hard part](#the-hard-part-restore-metadata-az-placement-and-the-static-pv-bind).
  This is the bulk of the `RestoreSelection` implementation, not a detail.
- **Namespace labels are not proof of backup coverage.** The developer opt-in label on a
  namespace is intent; `BackupSelection` matches the **tag on the EBS volume**, stamped
  only when a PVC uses a tier StorageClass. A labelled namespace whose PVCs use the
  default (untagged) class is silently *not* backed up. Coverage must be audited over
  volumes (`describe-volumes` by tag), not namespaces, and a drift check should flag the
  difference — see [Developer opt-in contract](#developer-opt-in-contract).
- **`reclaimPolicy: Retain` leaves orphaned volumes.** Keeping gold/silver volumes on PVC
  deletion is a restore precondition but accrues orphaned `Released` PVs / detached EBS
  volumes and their cost until a reaper reclaims them. The design calls for a cleanup
  guardrail scoped by the spoke tag; without it, `Retain` is unbounded orphaned spend —
  see [StorageClass tiers + volume tagging](#storageclass-tiers--volume-tagging).
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
