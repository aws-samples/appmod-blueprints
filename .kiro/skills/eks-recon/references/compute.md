# Module: Compute

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect compute strategy - Karpenter, Managed Node Groups, Auto Mode, Fargate, self-managed

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [Auto Mode Detection](#1-auto-mode-detection)
  - [Karpenter Detection](#2-karpenter-detection)
  - [Managed Node Group Detection](#3-managed-node-group-detection)
  - [Fargate Detection](#4-fargate-detection)
  - [Self-Managed Node Detection](#5-self-managed-node-detection)
- [Output Schema](#output-schema)
- [Strategy Determination Logic](#strategy-determination-logic)
- [Edge Cases](#edge-cases)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `describe_eks_resource`, `list_eks_resources`, `list_k8s_resources`
- **CLI fallback:** `aws eks`, `kubectl`

---

## Detection Strategy

Run detections in this order because later strategies depend on ruling out earlier ones:

```
1. Auto Mode      -> If enabled, strategy is "Auto Mode" (may have MNG for system)
2. Karpenter      -> Check for NodePool CRDs and controller
3. MNG            -> List managed node groups
4. Fargate        -> List Fargate profiles
5. Self-managed   -> Nodes without MNG labels
```

**Why this order matters:**
- Auto Mode can coexist with MNG for system workloads, so check it first
- Karpenter clusters often have a bootstrap MNG that should not define the strategy
- Fargate-only clusters are rare; check MNG before assuming Fargate-only
- Self-managed is the fallback when no managed solution is detected

**Determine the final strategy:**
- Single method detected -> Use that method
- Multiple methods detected -> Report "Mixed" and detail which methods
- Nothing detected -> Report "Self-managed" or "Unknown"

---

## Detection Commands

### 1. Auto Mode Detection

Check Auto Mode first because it fundamentally changes how the cluster provisions compute. Auto Mode clusters let EKS manage nodes automatically, so you may not see traditional node groups.

**MCP:**
```
describe_eks_resource(
  resource_type="cluster",
  cluster_name="<cluster-name>"
)
-> Check response for cluster.computeConfig.enabled
```

**CLI:**
```bash
aws eks describe-cluster \
  --name <cluster-name> \
  --query 'cluster.computeConfig.enabled'
```

**Example output (Auto Mode enabled):**
```
true
```

**Example output (Auto Mode not enabled):**
```
null
```

**Interpret the result:** `true` = Auto Mode enabled, `false` or `null` = Not using Auto Mode

### 2. Karpenter Detection

Detect Karpenter to identify clusters using just-in-time node provisioning. Karpenter is common in cost-optimized or scale-heavy clusters because it provisions nodes faster than Cluster Autoscaler.

**MCP (check for NodePools):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="NodePool",
  api_version="karpenter.sh/v1"
)
```

If empty, try v1beta1 (older Karpenter versions use this API):
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="NodePool",
  api_version="karpenter.sh/v1beta1"
)
```

**MCP (check for controller):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="kube-system",
  label_selector="app.kubernetes.io/name=karpenter"
)
```

**CLI:**
```bash
# Check for NodePools
kubectl get nodepools.karpenter.sh 2>/dev/null

# Check for controller deployment
kubectl get deploy -n kube-system -l app.kubernetes.io/name=karpenter -o json 2>/dev/null | \
  jq -r '.items[0].spec.template.spec.containers[0].image'
```

**Example output (Karpenter detected):**
```
NAME      NODECLASS
default   default
gpu-pool  gpu-nodes
```

**Example controller image:**
```
public.ecr.aws/karpenter/controller:1.0.5
```

**Extract version:** Parse the image tag from the controller deployment to report the Karpenter version.

### 3. Managed Node Group Detection

Detect Managed Node Groups (MNG) to identify AWS-managed EC2 capacity. MNGs are the most common compute strategy and handle node lifecycle, patching, and scaling automatically.

**MCP:**
```
list_eks_resources(
  resource_type="nodegroup",
  cluster_name="<cluster-name>"
)
```

**CLI:**
```bash
aws eks list-nodegroups --cluster-name <cluster-name> --query 'nodegroups'
```

**Example output:**
```json
["system-ng", "app-ng-spot", "app-ng-ondemand"]
```

For each node group, get details to understand instance types and scaling configuration:

**MCP:**
```
describe_eks_resource(
  resource_type="nodegroup",
  cluster_name="<cluster-name>",
  resource_name="<nodegroup-name>"
)
```

**CLI:**
```bash
aws eks describe-nodegroup \
  --cluster-name <cluster-name> \
  --nodegroup-name <nodegroup-name> \
  --query 'nodegroup.{
    name:nodegroupName,
    status:status,
    amiType:amiType,
    instanceTypes:instanceTypes,
    desiredSize:scalingConfig.desiredSize,
    minSize:scalingConfig.minSize,
    maxSize:scalingConfig.maxSize
  }'
```

**Example output:**
```json
{
  "name": "app-ng-spot",
  "status": "ACTIVE",
  "amiType": "AL2_x86_64",
  "instanceTypes": ["m5.large", "m5a.large", "m5d.large"],
  "desiredSize": 3,
  "minSize": 1,
  "maxSize": 10
}
```

### 4. Fargate Detection

Detect Fargate profiles to identify serverless compute. Fargate eliminates node management entirely - pods run on AWS-managed infrastructure. Use this when you see no nodes or need to understand which namespaces run serverless.

**MCP:** Not available, use CLI

**CLI:**
```bash
aws eks list-fargate-profiles --cluster-name <cluster-name> --query 'fargateProfileNames'
```

**Example output:**
```json
["fp-default", "fp-kube-system"]
```

For each profile, get selectors to understand which pods run on Fargate:
```bash
aws eks describe-fargate-profile \
  --cluster-name <cluster-name> \
  --fargate-profile-name <profile-name> \
  --query 'fargateProfile.{
    name:fargateProfileName,
    status:status,
    selectors:selectors
  }'
```

**Example output:**
```json
{
  "name": "fp-default",
  "status": "ACTIVE",
  "selectors": [
    {"namespace": "default"},
    {"namespace": "app", "labels": {"fargate": "true"}}
  ]
}
```

### 5. Self-Managed Node Detection

Detect self-managed nodes when other strategies are not found. Self-managed nodes are EC2 instances joined to the cluster manually or via custom automation (Terraform, CloudFormation ASGs). These require manual patching and lifecycle management.

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Node",
  api_version="v1"
)
```

**CLI:**
```bash
# Find nodes without the MNG label (indicates self-managed)
kubectl get nodes -o json | jq -r '
  .items[] |
  select(.metadata.labels["eks.amazonaws.com/nodegroup"] == null) |
  .metadata.name'
```

**Example output (self-managed nodes found):**
```
ip-10-0-1-50.ec2.internal
ip-10-0-2-75.ec2.internal
```

**Example output (no self-managed nodes):**
```
(empty - all nodes belong to MNGs or Karpenter)
```

---

## Output Schema

```yaml
compute:
  strategy: string  # Karpenter | MNG | Auto Mode | Fargate | Mixed | Self-managed | Unknown
  
  auto_mode:
    enabled: bool
    
  karpenter:
    detected: bool
    version: string      # e.g., "1.0.5"
    api_version: string  # v1 or v1beta1
    nodepools: int       # Count of NodePool resources
    nodepool_names: list # Names of NodePools
    
  mng:
    detected: bool
    count: int
    groups:
      - name: string
        status: string
        ami_type: string
        instance_types: list
        desired_size: int
        min_size: int
        max_size: int
        
  fargate:
    detected: bool
    profiles: int
    profile_names: list
    
  self_managed:
    detected: bool
    node_count: int
```

---

## Strategy Determination Logic

```
if auto_mode.enabled:
    if mng.detected and mng.count > 0:
        strategy = "Auto Mode"  # Auto Mode may have MNG for system workloads
    else:
        strategy = "Auto Mode"
        
elif karpenter.detected and karpenter.nodepools > 0:
    if mng.detected and mng.count > 0:
        strategy = "Mixed"
        note = "Karpenter for workloads, MNG for system"
    else:
        strategy = "Karpenter"
        
elif mng.detected and mng.count > 0:
    if fargate.detected:
        strategy = "Mixed"
        note = "MNG + Fargate"
    else:
        strategy = "MNG"
        
elif fargate.detected:
    strategy = "Fargate"
    
elif self_managed.detected:
    strategy = "Self-managed"
    
else:
    strategy = "Unknown"
```

---

## Edge Cases

Handle these special scenarios to provide accurate compute reporting.

### Cluster Autoscaler vs Karpenter

Check for Cluster Autoscaler when Karpenter is not detected. CAS is the legacy autoscaling solution and affects how you interpret MNG scaling behavior.

```bash
kubectl get deploy -n kube-system cluster-autoscaler 2>/dev/null
```

**Why this matters:** If CAS is present, MNG scaling is automated. If neither CAS nor Karpenter is present, MNGs use static sizing only.

### Bottlerocket Nodes

Identify Bottlerocket nodes by checking the AMI type. Bottlerocket is a security-hardened OS that affects troubleshooting (no SSH, read-only filesystem).

Look for these values in `amiType`:
- `BOTTLEROCKET_x86_64`
- `BOTTLEROCKET_ARM_64`

### GPU Nodes

Detect GPU nodes for clusters running ML/AI workloads. GPU nodes require special scheduling consideration.

```bash
kubectl get nodes -l "nvidia.com/gpu" -o name
```

**Example output:**
```
node/ip-10-0-3-100.ec2.internal
```

### Graviton/ARM Nodes

Identify ARM-based Graviton nodes for cost optimization reporting. Graviton instances offer better price-performance but require ARM-compatible container images.

Look for these indicators:
- `amiType: AL2_ARM_64` or `AL2023_ARM_64_STANDARD`
- Instance types: `m6g`, `m7g`, `c6g`, `c7g`, `r6g`, `r7g`
