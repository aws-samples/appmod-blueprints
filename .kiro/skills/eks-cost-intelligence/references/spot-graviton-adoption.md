# Spot and Graviton Adoption

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Checks for Graviton (arm64) adoption percentage, node groups/NodePools without arm64 in allowed architectures, workloads with explicit amd64 affinity, Spot vs On-Demand percentage, stateless multi-replica workloads on On-Demand, instance type diversity for Spot, and Node Termination Handler/Karpenter interruption handling

---

## Overview

Spot and Graviton adoption is the second-highest weighted dimension (20 points max deduction). It evaluates whether the cluster takes advantage of Graviton processors (~20% cost savings at equivalent performance per [AWS Graviton](https://aws.amazon.com/ec2/graviton/)) and Spot instances (up to 90% discount) where workloads are eligible.

### Checks Summary

| # | Check | Default Threshold | Severity Logic |
|---|-------|-------------------|----------------|
| 1 | Graviton (arm64) adoption percentage | < 50% of eligible nodes | HIGH if below 50% |
| 2 | Node groups/NodePools without arm64 | Any group missing arm64 | MEDIUM per group |
| 3 | Workloads with explicit amd64 affinity | Any workload pinned to amd64 | LOW–MEDIUM |
| 4 | Spot vs On-Demand percentage | No Spot + stateless workloads exist | HIGH |
| 5 | Stateless multi-replica workloads on On-Demand | Eligible workloads not on Spot | By waste $ |
| 6 | Instance type diversity for Spot | < 5 instance types in Spot pool | MEDIUM |
| 7 | Node Termination Handler / interruption handling | Missing handler with Spot nodes | HIGH |

---

## Pre-requisites

These checks require:
- **kubectl access** to the cluster (for node labels, pod specs, affinity rules)
- **AWS CLI access** for `eks:DescribeNodegroup`, `ec2:DescribeInstances`

No metrics sources are required — all checks use configuration and label inspection.

---

## Check 1: Graviton (arm64) Adoption Percentage

### What it detects

The ratio of nodes running on Graviton (arm64) architecture versus x86 (amd64), identifying clusters that are not leveraging Graviton's price-performance advantage.

### Data collection

**Via kubectl:**

```bash
# Count nodes by architecture
kubectl get nodes -o json | \
  jq -r '
    .items[] | {
      name: .metadata.name,
      arch: .status.nodeInfo.architecture,
      instance_type: .metadata.labels["node.kubernetes.io/instance-type"],
      capacity_type: (.metadata.labels["karpenter.sh/capacity-type"] // 
                      .metadata.labels["eks.amazonaws.com/capacityType"] // "on-demand"),
      nodegroup: (.metadata.labels["eks.amazonaws.com/nodegroup"] // 
                  .metadata.labels["karpenter.sh/nodepool"] // "unknown")
    }' | jq -s '
    {
      total: length,
      arm64: [.[] | select(.arch == "arm64")] | length,
      amd64: [.[] | select(.arch == "amd64")] | length,
      arm64_pct: (([.[] | select(.arch == "arm64")] | length) * 100 / length),
      by_nodegroup: (group_by(.nodegroup) | map({
        nodegroup: .[0].nodegroup,
        total: length,
        arm64: [.[] | select(.arch == "arm64")] | length,
        amd64: [.[] | select(.arch == "amd64")] | length
      }))
    }'
```

**Via AWS CLI (node group level):**

```bash
# List node groups and their instance types
CLUSTER="<cluster>"
for NG in $(aws eks list-nodegroups --cluster-name $CLUSTER --query 'nodegroups[]' --output text); do
  echo "=== $NG ==="
  aws eks describe-nodegroup --cluster-name $CLUSTER --nodegroup-name $NG \
    --query '{name: nodegroup.nodegroupName, instanceTypes: nodegroup.instanceTypes, capacityType: nodegroup.capacityType}' \
    --output json
done

# Check if instance types are Graviton (contain 'g' suffix in family)
# Graviton families: t4g, m6g, m7g, c6g, c7g, r6g, r7g, m6gd, c6gd, etc.
aws ec2 describe-instance-types \
  --instance-types m6g.large m6i.large c6g.xlarge c6i.xlarge \
  --query 'InstanceTypes[].{Type: InstanceType, Arch: ProcessorInfo.SupportedArchitectures[0]}' \
  --output table
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Node",
  api_version="v1"
)
# Parse .status.nodeInfo.architecture and .metadata.labels for each node

list_eks_resources(
  cluster_name="<cluster>",
  resource_type="nodegroups"
)
# Check instanceTypes in each nodegroup configuration
```

### Analysis logic

```
total_nodes = count(all nodes)
arm64_nodes = count(nodes where .status.nodeInfo.architecture == "arm64")
amd64_nodes = count(nodes where .status.nodeInfo.architecture == "amd64")

graviton_pct = arm64_nodes / total_nodes × 100

If graviton_pct < 50%:
  → Generate HIGH severity finding
  savings_estimate = amd64_nodes × avg_node_hourly_cost × 0.20 × 730
  # Graviton typically provides ~20% cost savings at equivalent performance
```

### Severity classification

| Graviton Adoption | Severity |
|-------------------|----------|
| 0% (no Graviton at all) | HIGH |
| 1–49% | HIGH |
| 50–79% | MEDIUM |
| 80%+ | No finding (good adoption) |

> **Key threshold:** Below 50% Graviton adoption triggers a HIGH severity finding per Requirement 5.4.

### Remediation

```yaml
# Karpenter NodePool with Graviton preference
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: graviton-preferred
spec:
  template:
    spec:
      requirements:
      - key: kubernetes.io/arch
        operator: In
        values: ["arm64"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]
```

```bash
# For Managed Node Groups — create a Graviton node group
aws eks create-nodegroup \
  --cluster-name <cluster> \
  --nodegroup-name graviton-workers \
  --instance-types m7g.large m7g.xlarge c7g.large c7g.xlarge \
  --scaling-config minSize=2,maxSize=10,desiredSize=3 \
  --node-role <node-role-arn> \
  --subnets <subnet-ids>
```

---

## Check 2: Node Groups/NodePools Without arm64 in Allowed Architectures

### What it detects

Node groups or Karpenter NodePools that are configured to only launch x86 (amd64) instances, missing the opportunity to use Graviton.

### Data collection

**Via kubectl (Karpenter NodePools):**

```bash
# Check NodePool architecture requirements
kubectl get nodepools -o json | \
  jq '.items[] | {
    name: .metadata.name,
    arch_requirement: (
      .spec.template.spec.requirements[] | 
      select(.key == "kubernetes.io/arch") | 
      {operator: .operator, values: .values}
    )
  }'

# NodePools that explicitly exclude arm64 or only allow amd64
kubectl get nodepools -o json | \
  jq '[.items[] | 
    select(
      .spec.template.spec.requirements[] | 
      select(.key == "kubernetes.io/arch") |
      ((.operator == "In" and (.values | contains(["arm64"]) | not)) or
       (.operator == "NotIn" and (.values | contains(["arm64"]))))
    ) | .metadata.name]'
```

**Via AWS CLI (Managed Node Groups):**

```bash
# Check instance types in each node group — identify non-Graviton-only groups
CLUSTER="<cluster>"
for NG in $(aws eks list-nodegroups --cluster-name $CLUSTER --query 'nodegroups[]' --output text); do
  TYPES=$(aws eks describe-nodegroup --cluster-name $CLUSTER --nodegroup-name $NG \
    --query 'nodegroup.instanceTypes' --output json)
  
  # Check if any instance type is Graviton (contains 'g' before the dot)
  HAS_GRAVITON=$(echo "$TYPES" | jq '[.[] | select(test("\\d+g[de]?\\."))] | length > 0')
  
  if [ "$HAS_GRAVITON" = "false" ]; then
    echo "NO_GRAVITON: $NG uses only x86 types: $TYPES"
  fi
done
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="NodePool",
  api_version="karpenter.sh/v1"
)
# Check spec.template.spec.requirements for kubernetes.io/arch

list_eks_resources(
  cluster_name="<cluster>",
  resource_type="nodegroups"
)
# Check instanceTypes for Graviton families
```

### Analysis logic

```
For each NodePool:
  arch_req = find requirement where key == "kubernetes.io/arch"
  
  If arch_req.operator == "In" AND "arm64" NOT in arch_req.values:
    → Finding: NodePool restricted to amd64 only
  
  If arch_req is missing (no architecture constraint):
    → OK (Karpenter will consider both architectures)

For each Managed Node Group:
  instance_types = nodegroup.instanceTypes
  has_graviton = any(type matches graviton pattern for type in instance_types)
  
  If NOT has_graviton:
    → Finding: Node group uses only x86 instance types
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| All node groups/NodePools are amd64-only | HIGH |
| Some node groups/NodePools are amd64-only | MEDIUM |
| Only system/addon node groups are amd64-only | LOW |

### Remediation

```yaml
# Add arm64 to existing NodePool requirements
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  template:
    spec:
      requirements:
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64", "arm64"]  # Allow both architectures
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]
```

```bash
# For Managed Node Groups — add a Graviton node group alongside existing
# (cannot change instance types on existing node group)
aws eks create-nodegroup \
  --cluster-name <cluster> \
  --nodegroup-name <existing-name>-graviton \
  --instance-types m7g.large m7g.xlarge c7g.large \
  --scaling-config minSize=1,maxSize=10,desiredSize=2 \
  --node-role <node-role-arn> \
  --subnets <subnet-ids>
```

---

## Check 3: Workloads With Explicit amd64 Affinity

### What it detects

Workloads (Deployments, StatefulSets) that have explicit node affinity or node selectors pinning them to amd64 architecture, preventing them from being scheduled on Graviton nodes even when available.

### Data collection

**Via kubectl:**

```bash
# Find workloads with explicit amd64 node selector
kubectl get deployments,statefulsets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(
      (.spec.template.spec.nodeSelector // {} | .["kubernetes.io/arch"] == "amd64") or
      (.spec.template.spec.nodeSelector // {} | .["beta.kubernetes.io/arch"] == "amd64")
    ) |
    "\(.metadata.namespace)/\(.metadata.name) (kind: \(.kind)) — nodeSelector pins to amd64"
  '

# Find workloads with amd64 node affinity
kubectl get deployments,statefulsets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(
      .spec.template.spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[]?.matchExpressions[]? |
      select(.key == "kubernetes.io/arch" or .key == "beta.kubernetes.io/arch") |
      select(.operator == "In" and (.values | contains(["arm64"]) | not))
    ) |
    "\(.metadata.namespace)/\(.metadata.name) (kind: \(.kind)) — nodeAffinity pins to amd64"
  '
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="all"
)
# Filter for spec.template.spec.nodeSelector["kubernetes.io/arch"] == "amd64"
# or nodeAffinity expressions restricting to amd64

list_k8s_resources(
  cluster_name="<cluster>",
  kind="StatefulSet",
  api_version="apps/v1",
  namespace="all"
)
# Same filtering logic
```

### Analysis logic

```
For each Deployment/StatefulSet in non-system namespaces:
  has_amd64_selector = nodeSelector contains "kubernetes.io/arch": "amd64"
                       OR "beta.kubernetes.io/arch": "amd64"
  
  has_amd64_affinity = nodeAffinity.required contains matchExpression
                       where key is arch AND values only include "amd64"

  If has_amd64_selector OR has_amd64_affinity:
    # Check if workload genuinely needs x86 (known x86-only dependencies)
    # Common legitimate reasons: specific binary dependencies, GPU workloads
    → Generate finding (potential Graviton candidate)
    
    replicas = workload.spec.replicas
    estimated_savings = replicas × per_pod_cost × 0.20  # ~20% Graviton savings
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| > 10 workloads pinned to amd64 | MEDIUM |
| 1–10 workloads pinned to amd64 | LOW |
| Workloads with high replica count (>5) pinned to amd64 | MEDIUM |

### Remediation

```yaml
# Remove architecture constraint (allow scheduling on both)
# Before:
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/arch: amd64

# After (remove the constraint or allow both):
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference:
              matchExpressions:
              - key: kubernetes.io/arch
                operator: In
                values: ["arm64"]  # Prefer Graviton but allow amd64 fallback
```

```bash
# Remove amd64 nodeSelector from a deployment
kubectl patch deployment <name> -n <namespace> --type=json \
  -p='[{"op": "remove", "path": "/spec/template/spec/nodeSelector/kubernetes.io~1arch"}]'
```

> **Note:** Before removing architecture constraints, verify the workload's container images support multi-arch (linux/arm64). Check with: `docker manifest inspect <image> | jq '.manifests[].platform'`

---

## Check 4: Spot vs On-Demand Capacity Percentage

### What it detects

The ratio of nodes running on Spot instances versus On-Demand, identifying clusters that are not leveraging Spot's significant cost savings for eligible workloads.

### Data collection

**Via kubectl:**

```bash
# Count nodes by capacity type
kubectl get nodes -o json | \
  jq -r '
    .items[] | {
      name: .metadata.name,
      capacity_type: (.metadata.labels["karpenter.sh/capacity-type"] // 
                      .metadata.labels["eks.amazonaws.com/capacityType"] // "ON_DEMAND"),
      instance_type: .metadata.labels["node.kubernetes.io/instance-type"],
      nodegroup: (.metadata.labels["eks.amazonaws.com/nodegroup"] // 
                  .metadata.labels["karpenter.sh/nodepool"] // "unknown")
    }' | jq -s '
    {
      total: length,
      spot: [.[] | select(.capacity_type == "spot" or .capacity_type == "SPOT")] | length,
      on_demand: [.[] | select(.capacity_type == "on-demand" or .capacity_type == "ON_DEMAND")] | length,
      spot_pct: (([.[] | select(.capacity_type == "spot" or .capacity_type == "SPOT")] | length) * 100 / (if length == 0 then 1 else length end)),
      by_nodegroup: (group_by(.nodegroup) | map({
        nodegroup: .[0].nodegroup,
        capacity_type: .[0].capacity_type,
        count: length
      }))
    }'
```

**Via AWS CLI:**

```bash
# Get capacity type from EC2 instances backing the cluster
CLUSTER="<cluster>"
INSTANCE_IDS=$(kubectl get nodes -o json | \
  jq -r '.items[].spec.providerID' | sed 's|.*/||')

aws ec2 describe-instances \
  --instance-ids $INSTANCE_IDS \
  --query 'Reservations[].Instances[].{
    Id: InstanceId,
    Type: InstanceType,
    Lifecycle: InstanceLifecycle,
    State: State.Name
  }' --output table
# InstanceLifecycle: "spot" for Spot, null/absent for On-Demand
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Node",
  api_version="v1"
)
# Parse labels: karpenter.sh/capacity-type or eks.amazonaws.com/capacityType
# Values: "spot" / "on-demand" (Karpenter) or "SPOT" / "ON_DEMAND" (EKS MNG)
```

### Analysis logic

```
total_nodes = count(all nodes)
spot_nodes = count(nodes with capacity_type in ["spot", "SPOT"])
on_demand_nodes = count(nodes with capacity_type in ["on-demand", "ON_DEMAND"])

spot_pct = spot_nodes / total_nodes × 100

# Check if stateless multi-replica workloads exist (see Check 5)
has_spot_eligible_workloads = (count of Spot-eligible workloads > 0)

If spot_pct == 0 AND has_spot_eligible_workloads:
  → Generate HIGH severity finding (Requirement 6.5)
  savings_estimate = eligible_workload_cost × 0.60  # ~60% Spot discount average

If spot_pct > 0 AND spot_pct < 30 AND has_spot_eligible_workloads:
  → Generate MEDIUM severity finding (room for more Spot)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| 0% Spot + eligible workloads exist | HIGH |
| 1–29% Spot + more eligible workloads | MEDIUM |
| 30%+ Spot or no eligible workloads | No finding |

### Remediation

```yaml
# Karpenter NodePool for Spot workloads
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-workers
spec:
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["spot"]
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64", "arm64"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 30s
```

```bash
# For Managed Node Groups — create a Spot node group
aws eks create-nodegroup \
  --cluster-name <cluster> \
  --nodegroup-name spot-workers \
  --capacity-type SPOT \
  --instance-types m5.large m5.xlarge m5a.large m5a.xlarge c5.large c5.xlarge c5a.large \
  --scaling-config minSize=0,maxSize=20,desiredSize=3 \
  --node-role <node-role-arn> \
  --subnets <subnet-ids>
```

---

## Check 5: Stateless Multi-Replica Workloads on On-Demand Only

### What it detects

Workloads that are good candidates for Spot instances (stateless, multiple replicas, have PodDisruptionBudgets) but are currently running exclusively on On-Demand nodes.

### Spot eligibility criteria

A workload is considered **Spot-eligible** when ALL of the following are true:

| Criterion | Rationale |
|-----------|-----------|
| **Stateless** (Deployment, not StatefulSet) | Can tolerate interruption without data loss |
| **Multiple replicas** (replicas ≥ 2) | Service remains available during Spot interruption |
| **Has PodDisruptionBudget (PDB)** | Ensures graceful handling of node termination |
| **Not in a system namespace** | System workloads should remain on stable capacity |

Optional positive signals (increase confidence):
- Workload has `topologySpreadConstraints` (already spread across zones)
- Workload has readiness/liveness probes (health-aware)
- Workload image has multiple architecture support

### Data collection

**Via kubectl:**

```bash
# Step 1: Find Deployments with replicas >= 2 in non-system namespaces
kubectl get deployments --all-namespaces -o json | \
  jq '[.items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.spec.replicas >= 2) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      replicas: .spec.replicas,
      has_topology_spread: (.spec.template.spec.topologySpreadConstraints != null),
      node_selector: .spec.template.spec.nodeSelector,
      tolerations: [.spec.template.spec.tolerations[]?.key]
    }]'

# Step 2: Check which of those have PDBs
kubectl get pdb --all-namespaces -o json | \
  jq '[.items[] | {
    namespace: .metadata.namespace,
    name: .metadata.name,
    selector: .spec.selector.matchLabels,
    minAvailable: .spec.minAvailable,
    maxUnavailable: .spec.maxUnavailable
  }]'

# Step 3: Check which pods are running on On-Demand nodes
kubectl get pods --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.status.phase == "Running") |
    {
      namespace: .metadata.namespace,
      pod: .metadata.name,
      node: .spec.nodeName,
      owner: (.metadata.ownerReferences[0].name // "none")
    }' | jq -s '.'

# Cross-reference with node capacity types
kubectl get nodes -o json | \
  jq '[.items[] | {
    name: .metadata.name,
    capacity_type: (.metadata.labels["karpenter.sh/capacity-type"] // 
                    .metadata.labels["eks.amazonaws.com/capacityType"] // "ON_DEMAND")
  }]'
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="all"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="PodDisruptionBudget",
  api_version="policy/v1",
  namespace="all"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="Node",
  api_version="v1"
)
```

### Analysis logic

```
spot_eligible_workloads = []

For each Deployment in non-system namespaces:
  If replicas >= 2:
    has_pdb = PDB exists matching this deployment's labels
    pods_on_spot = count(pods on nodes with capacity_type == "spot")
    pods_on_demand = count(pods on nodes with capacity_type == "on-demand")
    
    If has_pdb AND pods_on_spot == 0 AND pods_on_demand > 0:
      → Spot-eligible workload running entirely on On-Demand
      spot_eligible_workloads.append(workload)
      
      per_pod_cost = estimate_pod_cost(workload)
      monthly_savings = pods_on_demand × per_pod_cost × 0.60  # ~60% Spot savings

If len(spot_eligible_workloads) > 0 AND cluster_spot_pct == 0:
  → Generate HIGH severity finding (Requirement 6.5)

If len(spot_eligible_workloads) > 0 AND cluster_spot_pct > 0:
  → Generate MEDIUM severity finding (more workloads could use Spot)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Eligible workloads on On-Demand + zero Spot in cluster | HIGH |
| Eligible workloads on On-Demand + some Spot exists | MEDIUM |
| Monthly savings > $500 | CRITICAL |
| Monthly savings $200–$500 | HIGH |
| Monthly savings $50–$200 | MEDIUM |
| Monthly savings < $50 | LOW |

> **Spot pricing note:** The discount used (60-65%) is a conservative average. Actual Spot discounts vary 40-90% by instance type, region, and AZ. For production assessments, query live Spot prices: `aws ec2 describe-spot-price-history --instance-types <types> --product-descriptions "Linux/UNIX"`

### Remediation

```yaml
# Add Spot toleration to eligible workloads
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <workload>
  namespace: <namespace>
spec:
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: <workload>
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 90
            preference:
              matchExpressions:
              - key: karpenter.sh/capacity-type
                operator: In
                values: ["spot"]
```

```yaml
# Ensure PDB exists for Spot workloads
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: <workload>-pdb
  namespace: <namespace>
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: <workload>
```

---

## Check 6: Instance Type Diversity for Spot Availability

### What it detects

Spot node groups or NodePools configured with too few instance types, which increases the risk of Spot interruptions and capacity unavailability. AWS recommends at least 5+ instance types across multiple families for Spot.

### Data collection

**Via kubectl (Karpenter NodePools):**

```bash
# Check instance type diversity in Spot NodePools
kubectl get nodepools -o json | \
  jq '.items[] | 
    select(.spec.template.spec.requirements[] | 
      select(.key == "karpenter.sh/capacity-type") |
      .values | contains(["spot"])) |
    {
      name: .metadata.name,
      instance_categories: ([.spec.template.spec.requirements[] | 
        select(.key == "karpenter.k8s.aws/instance-category") | .values] | flatten),
      instance_families: ([.spec.template.spec.requirements[] | 
        select(.key == "karpenter.k8s.aws/instance-family") | .values] | flatten),
      instance_sizes: ([.spec.template.spec.requirements[] | 
        select(.key == "karpenter.k8s.aws/instance-size") | .values] | flatten),
      excluded_types: ([.spec.template.spec.requirements[] | 
        select(.key == "node.kubernetes.io/instance-type" and .operator == "NotIn") | .values] | flatten)
    }'
```

**Via AWS CLI (Managed Node Groups):**

```bash
# Check instance type count in Spot node groups
CLUSTER="<cluster>"
for NG in $(aws eks list-nodegroups --cluster-name $CLUSTER --query 'nodegroups[]' --output text); do
  CAPACITY=$(aws eks describe-nodegroup --cluster-name $CLUSTER --nodegroup-name $NG \
    --query 'nodegroup.capacityType' --output text)
  
  if [ "$CAPACITY" = "SPOT" ]; then
    TYPES=$(aws eks describe-nodegroup --cluster-name $CLUSTER --nodegroup-name $NG \
      --query 'nodegroup.instanceTypes' --output json)
    COUNT=$(echo "$TYPES" | jq 'length')
    echo "SPOT group $NG: $COUNT instance types — $TYPES"
    
    if [ "$COUNT" -lt 5 ]; then
      echo "  WARNING: Fewer than 5 instance types (recommended minimum for Spot)"
    fi
  fi
done
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="NodePool",
  api_version="karpenter.sh/v1"
)
# Check requirements for capacity-type == spot, then count instance diversity

list_eks_resources(
  cluster_name="<cluster>",
  resource_type="nodegroups"
)
# Filter for capacityType == SPOT, check instanceTypes array length
```

### Analysis logic

```
For each Spot-enabled NodePool or node group:
  If using Karpenter:
    # Karpenter with broad categories (m, c, r) is inherently diverse
    categories = requirements["karpenter.k8s.aws/instance-category"].values
    If len(categories) >= 3:
      → Sufficient diversity (Karpenter will select from many types)
    If len(categories) < 2 AND no instance-family specified:
      → Finding: limited instance diversity for Spot
    
    # Check if specific instance types are overly restricted
    If instance-family is specified AND len(families) < 3:
      → Finding: limited instance family diversity

  If using Managed Node Groups:
    instance_types = nodegroup.instanceTypes
    If len(instance_types) < 5:
      → Finding: fewer than 5 instance types for Spot
      severity = MEDIUM (availability risk)
    
    # Check family diversity
    families = unique([type.split(".")[0] for type in instance_types])
    If len(families) < 2:
      → Finding: all Spot types from single family (concentration risk)
      severity = MEDIUM
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Spot node group with only 1–2 instance types | HIGH |
| Spot node group with 3–4 instance types | MEDIUM |
| Spot NodePool with only 1 instance category | MEDIUM |
| All Spot from single instance family | MEDIUM |
| 5+ types across 2+ families | No finding |

### Remediation

```bash
# Update Managed Node Group with more instance types (requires recreation)
# Recommended: at least 5 types across 2+ families, similar vCPU/memory
aws eks create-nodegroup \
  --cluster-name <cluster> \
  --nodegroup-name spot-diverse \
  --capacity-type SPOT \
  --instance-types m5.large m5a.large m5.xlarge m5a.xlarge c5.large c5a.large c5.xlarge m6i.large c6i.large r5.large \
  --scaling-config minSize=0,maxSize=20,desiredSize=3 \
  --node-role <node-role-arn> \
  --subnets <subnet-ids>
```

```yaml
# Karpenter NodePool with broad instance diversity
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-diverse
spec:
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["spot"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]          # 3+ categories
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["4"]                     # Gen 5+ for better availability
      - key: karpenter.k8s.aws/instance-size
        operator: In
        values: ["large", "xlarge", "2xlarge"]
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64", "arm64"]        # Both architectures
```

---

## Check 7: Node Termination Handler / Karpenter Interruption Handling

### What it detects

Whether the cluster has proper Spot interruption handling configured. Without it, Spot instance terminations (2-minute warning) can cause ungraceful pod evictions and service disruption.

### Data collection

**Step 1: Check if Spot nodes exist**

```bash
# Quick check for any Spot nodes
SPOT_COUNT=$(kubectl get nodes -o json | \
  jq '[.items[] | select(
    .metadata.labels["karpenter.sh/capacity-type"] == "spot" or
    .metadata.labels["eks.amazonaws.com/capacityType"] == "SPOT"
  )] | length')

echo "Spot nodes: $SPOT_COUNT"
```

**Step 2: Check for AWS Node Termination Handler (NTH)**

```bash
# Check for NTH deployment (common names and namespaces)
kubectl get deployment -n kube-system aws-node-termination-handler 2>/dev/null || \
kubectl get daemonset -n kube-system aws-node-termination-handler 2>/dev/null || \
kubectl get deployment --all-namespaces -l app.kubernetes.io/name=aws-node-termination-handler 2>/dev/null

# Check for NTH via Helm release
kubectl get configmap -n kube-system -l app.kubernetes.io/name=aws-node-termination-handler 2>/dev/null
```

**Step 3: Check Karpenter interruption handling**

```bash
# Karpenter natively handles Spot interruptions (v0.30+)
# Verify Karpenter is running and has the interruption controller
kubectl get deployment -n kube-system karpenter -o json 2>/dev/null | \
  jq '{
    name: .metadata.name,
    replicas: .status.readyReplicas,
    version: .metadata.labels["app.kubernetes.io/version"]
  }'

# Check Karpenter settings for interruption handling
kubectl get configmap -n kube-system karpenter-global-settings -o json 2>/dev/null | \
  jq '.data'

# For Karpenter v1+, interruption is always enabled (built-in)
# For older versions, check if aws.interruptionQueue is configured
kubectl get deployment -n kube-system karpenter -o json 2>/dev/null | \
  jq '.spec.template.spec.containers[0].env[] | select(.name | test("INTERRUPTION"))'
```

**Step 4: Check for SQS queue (Karpenter interruption queue)**

```bash
# Karpenter uses an SQS queue for Spot interruption events
aws sqs list-queues --queue-name-prefix "karpenter" --output json 2>/dev/null

# Or check via Karpenter EC2NodeClass
kubectl get ec2nodeclasses -o json 2>/dev/null | \
  jq '.items[].spec | {amiFamily, role: .role}'
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="kube-system"
)
# Look for "aws-node-termination-handler" or "karpenter"

list_k8s_resources(
  cluster_name="<cluster>",
  kind="DaemonSet",
  api_version="apps/v1",
  namespace="kube-system"
)
# Look for "aws-node-termination-handler" DaemonSet mode
```

### Analysis logic

```
If spot_node_count == 0:
  → Skip this check (no Spot nodes, not applicable)

If spot_node_count > 0:
  karpenter_installed = (karpenter deployment exists and is ready)
  nth_installed = (aws-node-termination-handler deployment/daemonset exists)
  
  If karpenter_installed:
    # Karpenter v0.30+ has native interruption handling
    karpenter_version = parse version from deployment labels
    If karpenter_version >= "0.30":
      → Interruption handling is built-in (OK)
      # Verify SQS queue exists for optimal handling
      If no SQS queue configured:
        → LOW finding: SQS queue recommended for faster interruption response
    Else:
      If NOT nth_installed:
        → HIGH finding: older Karpenter without NTH
  
  If NOT karpenter_installed AND NOT nth_installed:
    → HIGH finding: Spot nodes without any interruption handler
    # Risk: pods get hard-killed on Spot termination without graceful drain
  
  If nth_installed:
    → OK (interruption handling present)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Spot nodes present + no interruption handler (no Karpenter, no NTH) | HIGH |
| Older Karpenter (< v0.30) without NTH | HIGH |
| Karpenter v0.30+ without SQS queue | LOW |
| NTH or Karpenter v0.30+ with SQS present | No finding |

### Remediation

```bash
# Install AWS Node Termination Handler via Helm
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-node-termination-handler eks/aws-node-termination-handler \
  --namespace kube-system \
  --set enableSpotInterruptionDraining=true \
  --set enableRebalanceRecommendation=true \
  --set enableScheduledEventDraining=true
```

```yaml
# For Karpenter — ensure SQS queue is configured (Terraform)
resource "aws_sqs_queue" "karpenter_interruption" {
  name                      = "karpenter-${var.cluster_name}"
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true
}

resource "aws_cloudwatch_event_rule" "spot_interruption" {
  name        = "karpenter-spot-interruption-${var.cluster_name}"
  description = "Spot interruption events for Karpenter"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Spot Instance Interruption Warning"]
  })
}

resource "aws_cloudwatch_event_target" "spot_interruption" {
  rule      = aws_cloudwatch_event_rule.spot_interruption.name
  target_id = "KarpenterInterruptionQueueTarget"
  arn       = aws_sqs_queue.karpenter_interruption.arn
}
```

---

## Scoring Contribution

The Spot/Graviton adoption dimension has a **maximum deduction of 20 points**.

### Deduction calculation

```
deduction = 0

For each finding in this dimension:
  If severity == CRITICAL: deduction += 20 × 0.6 = 12
  If severity == HIGH:     deduction += 20 × 0.3 = 6
  If severity == MEDIUM:   deduction += 20 × 0.15 = 3
  If severity == LOW:      deduction += 20 × 0.05 = 1

actual_deduction = min(deduction, 20)  # Cap at maximum
```

### Dimension status

| Condition | Status |
|-----------|--------|
| All checks completed | ASSESSED |
| No Spot nodes and no eligible workloads | ASSESSED (no findings) |
| Cannot access node labels or AWS API | SKIPPED |

If the dimension is fully SKIPPED, it contributes **zero deduction** and is excluded from the score denominator.

---

## Decision Tree

```
START
  │
  ├─ Gather node inventory (architecture + capacity type labels)
  │
  ├─ GRAVITON CHECKS
  │   ├─ Calculate arm64 vs amd64 percentage (Check 1)
  │   │   └─ If < 50% → HIGH finding
  │   ├─ Identify node groups/NodePools without arm64 (Check 2)
  │   │   └─ For each amd64-only group → MEDIUM finding
  │   └─ Find workloads pinned to amd64 (Check 3)
  │       └─ For each pinned workload → LOW/MEDIUM finding
  │
  ├─ SPOT CHECKS
  │   ├─ Calculate Spot vs On-Demand percentage (Check 4)
  │   │   └─ If 0% Spot + eligible workloads → HIGH finding
  │   ├─ Identify Spot-eligible workloads on On-Demand (Check 5)
  │   │   ├─ Criteria: stateless + replicas ≥ 2 + has PDB
  │   │   └─ For each eligible workload on OD → finding by waste $
  │   ├─ Check instance type diversity for Spot (Check 6)
  │   │   └─ If < 5 types or single family → MEDIUM finding
  │   └─ Check interruption handling (Check 7)
  │       └─ If Spot nodes + no handler → HIGH finding
  │
  └─ Aggregate findings → Calculate dimension deduction (capped at 20)
```

---

## Common Scenarios

### Scenario A: All On-Demand, No Graviton

- Check 1: HIGH (0% Graviton)
- Check 2: MEDIUM (all groups amd64-only)
- Check 4: HIGH (0% Spot + eligible workloads)
- Check 5: Multiple findings (eligible workloads on OD)
- Check 7: Skipped (no Spot nodes)
- **Expected deduction:** 12–20 points (likely capped at 20)

### Scenario B: Karpenter with Spot + Graviton

- Check 1: No finding (>80% Graviton)
- Check 2: No finding (NodePools allow arm64)
- Check 4: No finding (>30% Spot)
- Check 6: No finding (broad instance categories)
- Check 7: No finding (Karpenter v1 handles interruptions)
- **Expected deduction:** 0 points

### Scenario C: Spot Without Proper Handling

- Check 4: No finding (Spot exists)
- Check 6: MEDIUM (only 3 instance types)
- Check 7: HIGH (no NTH, no Karpenter interruption queue)
- **Expected deduction:** 6–9 points
