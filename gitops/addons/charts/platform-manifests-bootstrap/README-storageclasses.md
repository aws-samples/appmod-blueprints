# storageclass-resources

Helm chart that provisions cluster `StorageClass` resources, both EFS and EBS.

## What's new — Peeks DR-aware EBS StorageClasses

Three EBS StorageClasses ship by default, one per backup tier:

| StorageClass | Tier | RPO | Retention | Cross-region copy |
|---|---|---|---|---|
| `peeks-gold-gp3` | gold | 1 h | 30 d | yes |
| `peeks-silver-gp3` | silver | 24 h | 14 d | yes |
| `peeks-bronze-gp3` | bronze | 24 h | 7 d | no |

Every EBS volume provisioned by one of these SCs inherits, as an AWS resource
tag:

- `peeks.io/backup-tier=<tier>`
- `peeks.io/spoke=<spokeName>` (from the `spokeName` Helm value)
- `peeks.io/managed-by=peeks-platform`

These tags are what the `BackupSelection` resource produced by the companion
`BackupPolicy` RGD matches on — so a workload opts into a backup tier simply
by picking the right StorageClass in its PVC manifest. No central ConfigMap,
no platform ticket.

### Developer contract

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pgdata
spec:
  storageClassName: peeks-gold-gp3   # <-- declares the backup tier
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
```

That's it. The EBS CSI driver stamps the volume with the three tags at
provisioning time, the tier-level `BackupSelection` includes the volume in
its next snapshot cycle, and everything downstream (cross-region copy,
restore targeting) follows from there.

### Why not "just label the namespace"?

The EBS CSI driver's `tagSpecification_<N>` parameter only expands the
tokens `${pvc.name}`, `${pvc.namespace}`, and `${pv.name}` — it does **not**
propagate arbitrary namespace or PVC labels onto the underlying AWS tags.
A mutating admission webhook could watch namespaces and inject the right
StorageClass or rewrite tags on the fly, but that's an extra piece of
infrastructure to operate.

The per-SC strategy is the explicit contract in v1: it's visible in every
PVC manifest, requires no custom controllers, and reviewable in a pull
request.

### Custom tags per StorageClass

Any EBS SC can carry arbitrary tags via the `tags:` map:

```yaml
storageClasses:
  ebs:
    my-custom-sc:
      volumeType: gp3
      reclaimPolicy: Retain
      tags:
        cost-center: "1234"
        env: prod
```

These are rendered as `tagSpecification_<N>` on the SC's `parameters`.
The `peeks.io/spoke` tag from `spokeName` is merged in automatically.

## Usage

```sh
helm template . --set spokeName=spoke-prod-euw1 | kubectl apply -f -
```

Or, in a gitops context, set `spokeName` via the Argo CD ApplicationSet
parameter so each spoke gets its own tag value.
