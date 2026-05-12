# BackupPolicy RGD (peeks DR Pattern B)

Kro `ResourceGraphDefinition` that exposes a single `BackupPolicy` custom resource
and expands it into an ACK-managed AWS Backup stack:

- `BackupVault` (created in the policy's region)
- `BackupPlan` with tier-specific lifecycle & schedule
- `BackupSelection` that matches resources by AWS tag

## Tiers

| Tier   | Schedule               | RPO  | Retention | Cold storage | Cross-region copy |
| ------ | ---------------------- | ---- | --------- | ------------ | ----------------- |
| gold   | `cron(0 */1 * * ? *)`  | 1 h  | 30 d      | after 90 d   | yes               |
| silver | `cron(0 2 * * ? *)`    | 24 h | 14 d      | no           | yes               |
| bronze | `cron(0 3 * * ? *)`    | 24 h | 7 d       | no           | no                |

Gold and silver require `copyDestinationRegion` and `copyDestinationVaultARN`
(a BackupVault pre-created in the DR region). Bronze stays same-region.

## Usage

The expected pattern is **one `BackupPolicy` instance per tier per spoke**
(3 instances max per spoke, typically declared by the `SpokeCluster` RGD).

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
ConfigMap or platform-team ticket needed.

Included resource ARNs (for the selection):

- `arn:aws:ec2:*:*:volume/*` — EBS volumes
- `arn:aws:eks:*:*:cluster/*` — EKS add-on backup

## Validation

```sh
# syntax
yq eval '.' rgd-backup-policy.yaml

# kro server-side validation
kubectl --context hub apply --dry-run=server -f rgd-backup-policy.yaml

# apply & check
kubectl --context hub apply -f rgd-backup-policy.yaml
kubectl --context hub get rgd backuppolicy.kro.run
```

## Known limits (v1)

- No KMS key rotation / custom encryption — uses the default vault key.
- Heavy PVCs (e.g. Postgres on large EBS) need an app-level snapshot workflow
  in addition to AWS Backup; covered in task 2.2.
- `copyDestinationVaultARN` must be pre-provisioned in the DR region. A future
  iteration could nest that vault in the same RGD.

## Related

- ADR — PeEKS DR Pattern B (GitOps control plane + AWS Backup data plane):
  https://github.com/allamand/peeks-veille/blob/main/blogs/analyses/adr-peeks-dr-pattern-b.md
