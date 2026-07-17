# Module: Storage

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect storage configuration - CSI drivers, StorageClasses, PVCs, snapshots

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [1. CSI Drivers](#1-csi-drivers)
  - [2. StorageClasses](#2-storageclasses)
  - [3. Persistent Volume Claims](#3-persistent-volume-claims)
  - [4. Volume Snapshots](#4-volume-snapshots)
- [Output Schema](#output-schema)
- [Edge Cases](#edge-cases)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `describe_eks_resource`, `list_k8s_resources`
- **CLI fallback:** `aws eks`, `kubectl`

---

## Detection Strategy

Storage detection covers the full stack from drivers to volumes:

```
1. CSI Drivers       -> What storage backends are available
2. StorageClasses    -> How storage is provisioned
3. PVCs              -> What storage is currently used
4. Snapshots         -> Backup capability
```

---

## Detection Commands

### 1. CSI Drivers

Detect which CSI drivers are installed. EKS commonly uses EBS, EFS, and S3 Mountpoint drivers.

**EKS-Managed CSI Add-ons:**

**MCP:**
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="aws-ebs-csi-driver"
)
```

**CLI:**
```bash
# Check EBS CSI driver (EKS add-on)
aws eks describe-addon --cluster-name <cluster-name> --addon-name aws-ebs-csi-driver \
  --query 'addon.{name:addonName,version:addonVersion,status:status}' 2>/dev/null

# Check EFS CSI driver (EKS add-on)
aws eks describe-addon --cluster-name <cluster-name> --addon-name aws-efs-csi-driver \
  --query 'addon.{name:addonName,version:addonVersion,status:status}' 2>/dev/null

# Check S3 Mountpoint CSI driver (EKS add-on)
aws eks describe-addon --cluster-name <cluster-name> --addon-name aws-mountpoint-s3-csi-driver \
  --query 'addon.{name:addonName,version:addonVersion,status:status}' 2>/dev/null
```

**Example output (EBS CSI detected):**
```json
{
  "name": "aws-ebs-csi-driver",
  "version": "v1.28.0-eksbuild.1",
  "status": "ACTIVE"
}
```

**All CSI Drivers (including self-managed):**
```bash
# List all CSI drivers in cluster
kubectl get csidrivers -o json | jq '.items[] | {name: .metadata.name, attachRequired: .spec.attachRequired}'
```

**Example output:**
```json
{"name": "ebs.csi.aws.com", "attachRequired": true}
{"name": "efs.csi.aws.com", "attachRequired": false}
{"name": "s3.csi.aws.com", "attachRequired": false}
```

**Check if EKS Auto Mode manages storage:**
```bash
# Auto Mode includes EBS CSI automatically
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.storageConfig.blockStorage.enabled'
```

### 2. StorageClasses

Enumerate StorageClasses to understand provisioning options.

**CLI:**
```bash
# List all StorageClasses
kubectl get storageclasses -o json | jq '.items[] | {
  name: .metadata.name,
  provisioner: .provisioner,
  default: (.metadata.annotations["storageclass.kubernetes.io/is-default-class"] == "true"),
  volumeBindingMode: .volumeBindingMode,
  reclaimPolicy: .reclaimPolicy,
  parameters: .parameters
}'
```

**Example output:**
```json
{
  "name": "gp3",
  "provisioner": "ebs.csi.aws.com",
  "default": true,
  "volumeBindingMode": "WaitForFirstConsumer",
  "reclaimPolicy": "Delete",
  "parameters": {"type": "gp3", "encrypted": "true"}
}
{
  "name": "efs-sc",
  "provisioner": "efs.csi.aws.com",
  "default": false,
  "volumeBindingMode": "Immediate",
  "reclaimPolicy": "Delete",
  "parameters": {"provisioningMode": "efs-ap"}
}
```

**Count and identify default:**
```bash
# Count StorageClasses
kubectl get storageclasses --no-headers | wc -l

# Find default StorageClass
kubectl get storageclasses -o json | jq -r '.items[] | select(.metadata.annotations["storageclass.kubernetes.io/is-default-class"] == "true") | .metadata.name'
```

### 3. Persistent Volume Claims

Inventory PVCs to understand actual storage usage.

**CLI:**
```bash
# PVC summary by storage class
kubectl get pvc -A -o json | jq '[
  .items | 
  group_by(.spec.storageClassName) | 
  .[] | 
  {
    storageClass: .[0].spec.storageClassName,
    count: length,
    totalRequested: ([.[].spec.resources.requests.storage] | join(", ")),
    statuses: (group_by(.status.phase) | map({status: .[0].status.phase, count: length}))
  }
]'
```

**Example output:**
```json
[
  {
    "storageClass": "gp3",
    "count": 5,
    "totalRequested": "10Gi, 20Gi, 50Gi, 10Gi, 100Gi",
    "statuses": [{"status": "Bound", "count": 5}]
  },
  {
    "storageClass": "efs-sc",
    "count": 2,
    "totalRequested": "5Gi, 5Gi",
    "statuses": [{"status": "Bound", "count": 2}]
  }
]
```

**Detailed PVC list:**
```bash
# List all PVCs with details
kubectl get pvc -A -o json | jq '.items[] | {
  namespace: .metadata.namespace,
  name: .metadata.name,
  storageClass: .spec.storageClassName,
  capacity: .status.capacity.storage,
  status: .status.phase,
  accessModes: .spec.accessModes
}'
```

**Find pending PVCs (potential issues):**
```bash
kubectl get pvc -A --field-selector status.phase=Pending -o json | jq '.items[] | {
  namespace: .metadata.namespace,
  name: .metadata.name,
  storageClass: .spec.storageClassName
}'
```

### 4. Volume Snapshots

Check snapshot capability for backup/restore.

**Snapshot Controller:**
```bash
# Check if snapshot controller is installed
kubectl get deploy -n kube-system snapshot-controller 2>/dev/null

# Or check EKS add-on
aws eks describe-addon --cluster-name <cluster-name> --addon-name snapshot-controller \
  --query 'addon.{name:addonName,version:addonVersion,status:status}' 2>/dev/null
```

**VolumeSnapshotClasses:**
```bash
# List snapshot classes
kubectl get volumesnapshotclasses -o json 2>/dev/null | jq '.items[] | {
  name: .metadata.name,
  driver: .driver,
  deletionPolicy: .deletionPolicy
}'
```

**Existing snapshots:**
```bash
# Count snapshots
kubectl get volumesnapshots -A --no-headers 2>/dev/null | wc -l

# List snapshots with details
kubectl get volumesnapshots -A -o json 2>/dev/null | jq '.items[] | {
  namespace: .metadata.namespace,
  name: .metadata.name,
  sourcePVC: .spec.source.persistentVolumeClaimName,
  readyToUse: .status.readyToUse,
  restoreSize: .status.restoreSize
}'
```

---

## Output Schema

```yaml
storage:
  csi_drivers:
    ebs:
      detected: bool
      version: string
      managed_by: string  # eks-addon | self-managed | auto-mode
    efs:
      detected: bool
      version: string
      managed_by: string
    s3:
      detected: bool
      version: string
    other: list  # Other CSI drivers found
      
  storage_classes:
    count: int
    default: string  # Name of default StorageClass
    list:
      - name: string
        provisioner: string
        volume_binding_mode: string
        reclaim_policy: string
        encrypted: bool
        
  pvcs:
    total: int
    by_storage_class:
      - class: string
        count: int
        total_capacity: string
    by_status:
      bound: int
      pending: int
      lost: int
      
  snapshots:
    controller_installed: bool
    snapshot_classes: int
    volume_snapshots: int
```

---

## Edge Cases

### Auto Mode Storage

EKS Auto Mode includes EBS CSI automatically:
- Check `cluster.storageConfig.blockStorage.enabled`
- Don't flag missing EBS CSI add-on if Auto Mode is enabled

### No Default StorageClass

If no default StorageClass exists:
- PVCs without explicit storageClassName will fail
- Recommend setting a default

### Pending PVCs

Investigate pending PVCs:
- Missing StorageClass
- Insufficient capacity
- Zone mismatch (EBS is AZ-specific)

### EFS vs EBS Choice

| Use Case | Recommended |
|----------|-------------|
| Single-pod access | EBS (gp3) |
| Multi-pod access | EFS |
| High IOPS | EBS (io2) |
| Shared config/data | EFS |

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| No EBS CSI driver | Install aws-ebs-csi-driver add-on (or enable Auto Mode) |
| No default StorageClass | Set a default to simplify PVC creation |
| Pending PVCs | Investigate - likely zone or capacity issue |
| No snapshot controller | Install for backup capability |
| gp2 StorageClass in use | Migrate to gp3 for better performance/cost |
| Unencrypted StorageClass | Enable encryption for compliance |
