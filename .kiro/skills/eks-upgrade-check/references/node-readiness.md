# Node Readiness

## Purpose
Assess node groups, AMI types, version alignment, and migration requirements for the target version.

## Checks to Execute

### 5.1 — Node Group Inventory

**How to check:**
1. List all managed node groups → describe each for:
   - Kubernetes version
   - AMI type (AL2, AL2023, AL2_ARM_64, BOTTLEROCKET_x86_64, etc.)
   - Instance types
   - Scaling config (min/max/desired)
   - Capacity type (ON_DEMAND, SPOT)
   - Health status
2. List nodes via Kubernetes API → get:
   - `status.nodeInfo.kubeletVersion`
   - `status.nodeInfo.osImage`
   - `status.nodeInfo.kernelVersion`
   - `status.nodeInfo.containerRuntimeVersion`
   - Labels: `topology.kubernetes.io/zone`, `node.kubernetes.io/instance-type`
3. Check for Karpenter NodePools (`nodepools.karpenter.sh`)
4. Check for EKS Auto Mode (`computeConfig` in cluster describe)

**Output per node group:**
- Name, version, AMI type, instance types, scaling config
- Version skew against target (calculated in version-validation)

### 5.2 — AL2 to AL2023 Migration Assessment

**Why this matters:**
- AL2 standard support ended June 2025
- EKS 1.33+ does NOT publish AL2 AMIs — cannot create new AL2 node groups
- AL2 uses cgroup v1; AL2023 uses cgroup v2 (required for EKS 1.35+)

**How to check:**
1. From node group descriptions, identify AMI type
2. From node Kubernetes API, check `kernelVersion` for `amzn2` or `osImage` for `Amazon Linux 2`
3. Count AL2 nodes and node groups

**Rating:**
- No AL2 nodes → PASS
- AL2 nodes present, target < 1.33 → WARN (plan migration)
- AL2 nodes present, target >= 1.33 → FAIL (blocker — no AL2 AMI available)

**Migration guidance:**
1. Create new node group with AL2023 AMI type
2. Cordon old AL2 nodes: `kubectl cordon <node-name>`
3. Drain workloads: `kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data`
4. Delete old node group after all pods rescheduled
5. Key differences: cgroup v2 default, dnf instead of yum, different kernel

### 5.3 — Container Runtime Version

**Why this matters:** Kubernetes 1.35 is the LAST release supporting containerd 1.x. The 1.36
kubelet will not operate against a containerd 1.x runtime. How this surfaces depends on node type:
EKS-managed node groups (and Bottlerocket) pull containerd 2.0+ automatically when you upgrade the
node group to 1.36, so they self-heal. Self-managed nodes and custom AMIs that pin containerd 1.x
do NOT — their 1.36 kubelet will fail to run.

**How to check:**
1. List nodes → `status.nodeInfo.containerRuntimeVersion`
2. Check for containerd 1.x vs 2.x
3. For any node on containerd 1.x, determine whether it is **managed** (part of an EKS managed
   node group / Bottlerocket) or **self-managed / custom AMI** — reuse the classification from
   check 5.4.

**Rating:**
- All nodes on containerd 2.x → PASS
- Any node on containerd 1.x, target < 1.35 → WARN (plan upgrade)
- Any node on containerd 1.x, target == 1.35 → WARN (last version supporting containerd 1.x;
  the next version, 1.36, requires 2.0+)
- Any node on containerd 1.x, target >= 1.36:
  - **Managed node group / Bottlerocket** → INFO. Upgrading the node group to 1.36 replaces the
    AMI and pulls containerd 2.0+ automatically. No manual action, but call it out so the user
    knows the runtime jump happens during node rotation.
  - **Self-managed / custom AMI** → FAIL (HIGH) — hard blocker. The 1.36 kubelet will not run on
    containerd 1.x. The AMI must be rebuilt with containerd 2.0+ BEFORE upgrading the node.
    See report-generation.md hard blocker list.

### 5.4 — Self-Managed Nodes

**How to check:**
1. List all nodes
2. Compare against managed node group nodes (by labels or node group membership)
3. Nodes not in any managed node group or Karpenter → self-managed

**Rating:**
- No self-managed nodes → PASS
- Self-managed nodes present → WARN (no automated upgrade path, manual AMI update required)

### 5.5 — Subnet IP Capacity

**Why this matters:**
- EKS requires **at least 5 available IPs** in each cluster subnet to update the control plane
  (EKS creates new ENIs for the upgraded API server). If any subnet has < 5 IPs, the
  `update-cluster-version` API call will fail immediately.
- During node group rolling updates, new nodes are launched before old nodes are terminated
  (surge). Each new node consumes 1 IP for its primary ENI plus additional IPs for the VPC CNI
  warm pool (pod IPs). Insufficient capacity causes the node group update to hang.

**How to check:**
1. Get the cluster subnet IDs from the cluster description (already retrieved in pre-flight
   Action 2 — `resourcesVpcConfig.subnetIds`).
2. Run:
   ```bash
   aws ec2 describe-subnets --subnet-ids <subnet-id-1> <subnet-id-2> ... \
     --query 'Subnets[].{SubnetId:SubnetId,AZ:AvailabilityZone,AvailableIPs:AvailableIpAddressCount,CIDR:CidrBlock}' \
     --output table
   ```
3. For each subnet, evaluate `AvailableIpAddressCount` against thresholds.

**Thresholds:**

| Available IPs | Verdict | Severity |
|---------------|---------|----------|
| < 5 | **HARD BLOCKER** — control plane upgrade will fail | CRITICAL |
| 5–15 | **WARNING** — control plane OK, but node rolling update at risk if surge needs more IPs | MEDIUM |
| > 15 | PASS | — |

**Important context for the 5–15 warning:**
The exact number of IPs needed during node group surge depends on:
- Instance type (determines max ENIs and IPs per ENI)
- VPC CNI configuration (`WARM_IP_TARGET`, `MINIMUM_IP_TARGET`, `ENABLE_PREFIX_DELEGATION`)
- Node group `maxSurge` setting (default: 1 additional node)

Do NOT report a precise "you need X IPs" number — instead flag the risk and advise the user
to verify capacity is sufficient for their instance type and CNI config.

**If subnet has < 5 IPs, report:**

> **❌ Subnet IP exhaustion — control plane upgrade will fail**
>
> Subnet `<subnet-id>` in `<az>` has only `<N>` available IPs (CIDR: `<cidr>`).
> EKS requires at least 5 free IPs per subnet to place control plane ENIs during an upgrade.
>
> **Remediation (choose one):**
> 1. Remove unused ENIs: `aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=<subnet-id> Name=status,Values=available --query 'NetworkInterfaces[].NetworkInterfaceId'`
> 2. Add a new subnet to the cluster: `aws eks update-cluster-config --name <cluster> --resources-vpc-config subnetIds=<existing>,<new-subnet>`
> 3. Expand the subnet CIDR (if VPC allows)

**If subnet has 5–15 IPs, report:**

> **⚠️ Low subnet IP capacity — node group upgrade may stall**
>
> Subnet `<subnet-id>` in `<az>` has `<N>` available IPs. While this is sufficient for the
> control plane upgrade (minimum 5), the node group rolling update launches new nodes before
> terminating old ones. If your instance type + VPC CNI warm pool requires more IPs than are
> available, the surge node will fail to launch.
>
> **Before upgrading:** Verify capacity is sufficient for your configuration, or consider
> adding subnets / enabling VPC CNI prefix delegation to reduce per-pod IP consumption.

## Score Impact

> **Canonical scoring is defined in `references/report-generation.md` §Category 3 (Node Readiness) and §Category 8 (AL2 Nodes).**

| Finding | Deduction |
|---------|-----------|
| Subnet IPs < 5 (hard blocker) | 5 pts + hard blocker override (caps score ≤ 59%) |
| Subnet IPs 5–15 (warning) | 2 pts |
| AL2 nodes (target < 1.33) | 2-5 pts |
| AL2 nodes (target >= 1.33) | 10-15 pts |
| Containerd 1.x (target < 1.36, or managed node on any target) | 2 pts |
| Containerd 1.x on self-managed/custom AMI (target >= 1.36) | 5 pts + hard blocker override (caps score ≤ 59%) |
| Self-managed nodes | 3 pts |
| Max category (combined with version-validation skew) | 20 pts |
