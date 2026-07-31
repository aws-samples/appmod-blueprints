# BackupPolicy examples

Sample `kro.run/v1alpha1` `BackupPolicy` instances for manual testing of the
RGD defined in `../manifests/backup-policy/`.

These are **NOT** picked up by Argo CD (they live outside the `manifests/`
directory consumed by the `kro-manifests-hub` ApplicationSet). Apply them by
hand once the RGD is `Active` and the underlying ACK Backup CRDs
(`backup.services.k8s.aws/{BackupVault,BackupPlan,BackupSelection}`) exist on
the hub:

```bash
kubectl --context hub apply -f instance-bronze.yaml
kubectl --context hub get backupvault,backupplan,backupselection -A
```

| File                     | Tier   | Region scope          | Use case             |
|--------------------------|--------|-----------------------|----------------------|
| `instance-bronze.yaml`   | bronze | same-region           | dev / sandbox        |
| `instance-silver.yaml`   | silver | + cross-region copy   | staging              |
| `instance-gold.yaml`     | gold   | + cross-region copy   | prod / DR coverage   |

Update `iamRoleARN` to the actual `AWSBackupDefaultServiceRole` ARN of the
target account before applying.
