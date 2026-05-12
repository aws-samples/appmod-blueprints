# BackupPolicy RGD

Kro `ResourceGraphDefinition` that exposes a single `BackupPolicy` custom resource
and expands it into an ACK-managed AWS Backup stack:

- `BackupVault` (created in the policy's region)
- `BackupPlan` with tier-specific lifecycle & schedule
- `BackupSelection` that matches resources by AWS tag

## Why AWS Backup in a GitOps platform

The platform uses GitOps (Argo CD + kro + ACK) as the source of truth for the
**control plane** — cluster shape, capabilities, IAM, workload manifests — and
AWS Backup as the source of truth for the **data plane** — persistent volumes
and any Kubernetes kind that cannot be reconstructed from Git.

This split enables three concrete use cases that share the same primitive:

- **Disaster Recovery (cross-region)** — a spoke in `eu-west-1` is destroyed;
  kro + ACK recreates an equivalent spoke in `eu-west-3` via the normal
  `SpokeCluster` path, Argo CD re-syncs every workload from Git, and AWS Backup
  restores the PVs from cross-region copies (produced by the `gold`/`silver`
  plans defined here). The DR spoke is never "adopted post-facto" — it is born
  through the standard provisioning path with its data rehydrated on top.

- **Blue/green cluster migrations** — stand up a new spoke alongside the live
  one, restore data from the latest backup into the new spoke, flip traffic
  when workloads report ready, decommission the old spoke. Same mechanism as
  DR, planned instead of reactive.

- **Environment cloning** — clone a stateful environment (prod snapshot into a
  staging/dev spoke) for testing, without a bespoke export/import pipeline.
  AWS Backup restore jobs target the destination spoke in `existingCluster`
  mode; Argo CD already deployed the empty workload shells.

In all three cases, the `BackupPlan` and `BackupSelection` produced by this
RGD are what makes a snapshot available at the moment it is needed. Retention
and copy policy are chosen per-tier to match the recovery objective of each
workload class, not a one-size-fits-all vault.

## Tiers

| Tier   | Schedule               | RPO  | Retention | Cold storage | Cross-region copy |
| ------ | ---------------------- | ---- | --------- | ------------ | ----------------- |
| gold   | `cron(0 */1 * * ? *)`  | 1 h  | 30 d      | after 90 d   | yes               |
| silver | `cron(0 2 * * ? *)`    | 24 h | 14 d      | no           | yes               |
| bronze | `cron(0 3 * * ? *)`    | 24 h | 7 d       | no           | no                |

Gold and silver require `copyDestinationRegion` and `copyDestinationVaultARN`
(a BackupVault pre-created in the DR region). Bronze stays same-region — it
covers workloads whose recovery policy is "redeploy fresh if the region is
lost", not full geo-DR.

## Usage

The expected pattern is **one `BackupPolicy` instance per tier per spoke**
(3 instances max per spoke, typically declared by the `SpokeCluster` RGD so
the platform team doesn't hand-roll them).

```yaml
apiVersion: kro.run/v1alpha1
kind: BackupPolicy
metadata:
  name: spoke-prod-euw1-bronze
spec:
  tier: bronze
  spokeName: spoke-prod-euw1
  region: eu-west-1
  iamRoleARN: arn:aws:iam::<acct>:role/AWSBackupDefaultServiceRole
```

See `examples/instance-{gold,silver,bronze}.yaml`.

## Developer contract

A workload opts into backup by putting the right tags on its resources:

- `peeks.io/backup-tier=<tier>` (gold | silver | bronze)
- `peeks.io/spoke=<spokeName>`

The recommended way on EKS is to label the namespace or the PVC; the EBS CSI
driver propagates those tags onto the underlying EBS volumes, and the
`BackupSelection.conditions.stringEquals` block matches them. No central
ConfigMap or platform-team ticket needed — opt-in is visible in the app's Git
manifests and auditable with a single `kubectl get ns -l peeks.io/backup-tier=<tier>`.

Included resource ARNs (for the selection):

- `arn:aws:ec2:*:*:volume/*` — EBS volumes
- `arn:aws:eks:*:*:cluster/*` — EKS add-on backup

## What this RGD does NOT cover

Documented explicitly because the boundary matters for DR correctness:

- **Secrets** — handled by External Secrets Operator (source of truth: AWS
  Secrets Manager, replicated cross-region). Never restored from a K8s-level
  snapshot.
- **Anything derivable from Git** — Deployments, Services, ConfigMaps,
  Ingresses, PVC templates. Argo CD re-syncs them on the recovery spoke.
- **Heavy stateful workloads (Postgres, Kafka)** — AWS Backup gives a
  crash-consistent filesystem snapshot, not a logically consistent database
  backup. Those workloads need an application-level backup on top
  (`pg_basebackup` + WAL archiving to S3, Kafka tiered storage, etc.) — see
  task 2.2 in the DR plan.
- **PVC restore targeting** — the actual mechanism that attaches restored
  volumes to the new pods in an `existingCluster` restore is handled by a
  separate RGD (`RestoreSelection`, task 2.1), not here. This RGD only
  produces the backups; restoring them is a different concern.

## Validation

```sh
# syntax
yq eval '.' rgd-backup-policy.yaml

# kro server-side validation
kubectl --context hub apply --dry-run=server -f rgd-backup-policy.yaml

# apply & check
kubectl --context hub apply -f rgd-backup-policy.yaml
kubectl --context hub get rgd backuppolicy.kro.run

# end-to-end: instance expands into BackupVault + BackupPlan + BackupSelection
kubectl --context hub apply -f examples/instance-bronze.yaml
kubectl --context hub get backupvault,backupplan,backupselection -A
```

## Known limits (v1)

- No KMS key rotation / custom encryption — uses the default vault key.
- Heavy PVCs (e.g. Postgres on large EBS) need an app-level snapshot workflow
  in addition to AWS Backup.
- `copyDestinationVaultARN` must be pre-provisioned in the DR region. A future
  iteration could nest that vault in the same RGD.
- Restore side (how the PVs land in a target cluster) is the responsibility of
  a separate `RestoreSelection` RGD — not in this directory.
