# Waste Calculation Formulas

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Dollar waste formulas for computing waste from utilization gaps, idle nodes, storage inefficiency, network costs, and missed Spot/Graviton opportunities

---

## Core Principle

**Waste = money spent on capacity that is allocated but not used, or money overspent by not using cheaper alternatives.**

Every formula follows the same structure:
1. **Inputs** — what data you need to collect
2. **Calculation** — the formula to compute waste
3. **Output** — `monthly_waste` and `monthly_savings` values for the finding

---

## 1. Compute Waste (Request vs P95 Utilization)

### Per-Pod Compute Waste

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `cpu_request_cores` | Pod spec `.resources.requests.cpu` | 0.800 (800m) |
| `cpu_p95_cores` | metrics-server / Container Insights / Prometheus | 0.065 |
| `mem_request_bytes` | Pod spec `.resources.requests.memory` | 1073741824 (1Gi) |
| `mem_p95_bytes` | metrics-server / Container Insights / Prometheus | 398458880 (380Mi) |
| `pod_monthly_cost` | Allocated share of node cost (see cost-estimation-fallback.md) | $185.00 |

#### Calculation

```python
# Step 1: Calculate waste ratios for each resource
cpu_waste_ratio = max(0, (cpu_request_cores - cpu_p95_cores) / cpu_request_cores)
mem_waste_ratio = max(0, (mem_request_bytes - mem_p95_bytes) / mem_request_bytes)

# Step 2: Use the LOWER ratio (conservative — waste only what BOTH resources confirm)
waste_ratio = min(cpu_waste_ratio, mem_waste_ratio)

# Step 3: Calculate dollar waste
monthly_waste = waste_ratio * pod_monthly_cost

# Step 4: Calculate savings (account for 1.5x headroom buffer on right-sized requests)
headroom_factor = 0.85  # savings after keeping 15% headroom above p95
monthly_savings = monthly_waste * headroom_factor
```

#### Worked Example

```
Pod: payments/checkout-7f8b9c-abc12
  CPU request:    800m (0.800 cores)
  CPU P95 actual: 65m  (0.065 cores)
  Memory request:    1Gi  (1024 MiB)
  Memory P95 actual: 380Mi

Step 1:
  cpu_waste_ratio = (0.800 - 0.065) / 0.800 = 0.919 (91.9%)
  mem_waste_ratio = (1024 - 380) / 1024     = 0.629 (62.9%)

Step 2:
  waste_ratio = min(0.919, 0.629) = 0.629

Step 3:
  pod_monthly_cost = $185.00
  monthly_waste = 0.629 × $185.00 = $116.37

Step 4:
  monthly_savings = $116.37 × 0.85 = $98.91

Finding:
  monthly_waste:   $116.37
  monthly_savings: $98.91
  fix: Set CPU to 100m (1.5× P95), memory to 570Mi (1.5× P95)
```

### Per-Node Compute Waste (Aggregate)

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `node_allocatable_cpu` | `kubectl get node -o json` → `.status.allocatable.cpu` | 4.0 cores |
| `node_total_requests_cpu` | Sum of all pod CPU requests on node | 1.2 cores |
| `node_p95_cpu` | CloudWatch / Prometheus node-level metric | 0.8 cores |
| `node_hourly_cost` | Instance pricing (see table below) | $0.192 |

#### Calculation

```python
# Node-level waste: gap between total requests and actual usage
node_waste_ratio = max(0, (node_total_requests_cpu - node_p95_cpu) / node_allocatable_cpu)
node_monthly_cost = node_hourly_cost * 24 * 30
monthly_waste = node_waste_ratio * node_monthly_cost
```

### Severity Thresholds

| Waste Ratio | Severity | Action |
|-------------|----------|--------|
| > 70% | CRITICAL | Right-size immediately |
| 40–70% | HIGH | Review and adjust within sprint |
| 20–40% | MEDIUM | Monitor trend, plan adjustment |
| < 20% | LOW | Acceptable headroom |

---

## 2. Idle Node Waste

### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `node_avg_cpu_7d` | CloudWatch `CPUUtilization` (7-day avg) | 6% |
| `node_avg_mem_7d` | CloudWatch / kubelet metrics (7-day avg) | 12% |
| `instance_type` | `kubectl get node` labels | m5.xlarge |
| `instance_hourly_rate` | AWS Price List (see reference table) | $0.192 |
| `node_has_gpu` | Node labels `nvidia.com/gpu` | false |

#### Reference: Instance Hourly Rates (us-east-1, On-Demand)

> ⚠️ **Fallback only — last verified June 2026.** Prefer the AWS Price List API for production assessments. See `cost-estimation-fallback.md` Step 2.

| Instance Type | vCPU | Memory | Hourly Rate |
|---------------|------|--------|-------------|
| m5.large | 2 | 8 GiB | $0.096 |
| m5.xlarge | 4 | 16 GiB | $0.192 |
| m5.2xlarge | 8 | 32 GiB | $0.384 |
| m6i.large | 2 | 8 GiB | $0.096 |
| m6i.xlarge | 4 | 16 GiB | $0.192 |
| m6i.2xlarge | 8 | 32 GiB | $0.384 |
| m7i.xlarge | 4 | 16 GiB | $0.202 |
| m7i.2xlarge | 8 | 32 GiB | $0.403 |
| m6g.xlarge | 4 | 16 GiB | $0.154 |
| m7g.xlarge | 4 | 16 GiB | $0.163 |
| c5.xlarge | 4 | 8 GiB | $0.170 |
| c5.2xlarge | 8 | 16 GiB | $0.340 |
| c7i.xlarge | 4 | 8 GiB | $0.178 |
| c7g.xlarge | 4 | 8 GiB | $0.145 |
| r5.xlarge | 4 | 32 GiB | $0.252 |
| r5.2xlarge | 8 | 64 GiB | $0.504 |
| r7i.xlarge | 4 | 32 GiB | $0.264 |
| r7g.xlarge | 4 | 32 GiB | $0.214 |

For instance types not in this table, use the AWS Price List API:
```bash
aws pricing get-products --service-code AmazonEC2 --region us-east-1 \
  --filters "Type=TERM_MATCH,Field=instanceType,Value=<INSTANCE_TYPE>" \
            "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" \
            "Type=TERM_MATCH,Field=location,Value=US East (N. Virginia)" \
            "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
            "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" \
            "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
  --query 'PriceList[0]' --output text | jq -r '.terms.OnDemand | to_entries[0].value.priceDimensions | to_entries[0].value.pricePerUnit.USD'
```

#### Detection Criteria

A node is **idle** if ALL of:
- Average CPU utilization < 10% over 7 days
- Average memory utilization < 20% over 7 days
- No GPU workloads scheduled (`nvidia.com/gpu` not present)

#### Calculation

```python
# Per idle node
is_idle = (node_avg_cpu_7d < 0.10 and
           node_avg_mem_7d < 0.20 and
           not node_has_gpu)

if is_idle:
    monthly_waste = instance_hourly_rate * 24 * 30
    monthly_savings = monthly_waste  # full node cost is recoverable

# Aggregate across all idle nodes
total_idle_waste = sum(node.monthly_waste for node in idle_nodes)
```

#### Worked Example

```
Node: ip-10-0-1-42.ec2.internal
  Instance type: m5.xlarge
  Avg CPU (7d):  6%
  Avg Memory (7d): 12%
  GPU workloads: none

Detection:
  6% < 10% ✓  AND  12% < 20% ✓  AND  no GPU ✓  → IDLE

Calculation:
  monthly_waste = $0.192/hr × 24 × 30 = $138.24/month
  monthly_savings = $138.24/month

Cluster has 3 idle nodes (m5.xlarge):
  total_monthly_waste = 3 × $138.24 = $414.72/month
  total_annual_savings = $414.72 × 12 = $4,976.64/year
```

### Karpenter Consolidation Savings (when consolidation is disabled)

```python
# If Karpenter is installed but consolidateAfter is not set or consolidation is off
consolidation_monthly_savings = (
    idle_node_count * avg_instance_hourly_rate * 24 * 30 * 0.25
)
# 25% is conservative — actual savings depend on workload packing density
```

---

## 3. Storage Waste

### 3a. gp2 → gp3 Migration Savings

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `provisioned_gb` | PVC `.spec.resources.requests.storage` | 100 GiB |
| `storage_class` | PVC `.spec.storageClassName` | gp2 |

#### Pricing

| Storage Class | Cost per GiB/month |
|---------------|-------------------|
| gp2 | $0.10 |
| gp3 | $0.08 |
| **Savings** | **$0.02/GiB/month (20%)** |

#### Calculation

```python
# Per volume
gp2_monthly_cost = provisioned_gb * 0.10
gp3_monthly_cost = provisioned_gb * 0.08
monthly_waste = gp2_monthly_cost - gp3_monthly_cost  # = provisioned_gb * 0.02
monthly_savings = monthly_waste  # full savings, zero-effort migration

# Aggregate across all gp2 volumes
total_gp2_waste = sum(pvc.provisioned_gb for pvc in gp2_pvcs) * 0.02
```

#### Worked Example

```
Cluster has 12 gp2 PVCs totaling 850 GiB:
  monthly_waste = 850 × $0.02 = $17.00/month
  annual_savings = $17.00 × 12 = $204.00/year

Individual PVC: data-postgres-0 (500 GiB, gp2)
  monthly_waste = 500 × $0.02 = $10.00/month
  monthly_savings = $10.00/month
  effort: Low (create gp3 StorageClass, migrate PVC)
```

### 3b. Unused PVC Waste

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `pvc_status` | PVC `.status.phase` | Bound |
| `pvc_provisioned_gb` | PVC `.spec.resources.requests.storage` | 50 GiB |
| `storage_class` | PVC `.spec.storageClassName` | gp3 |
| `last_mount_time` | Pod events / volume attachment events | 14 days ago |
| `storage_rate` | Rate for the storage class | $0.08/GiB/month |

#### Detection Criteria

A PVC is **unused** if:
- Status is `Bound` but no pod has mounted it in the last 7 days, OR
- Status is `Released` (volume freed but PVC object remains)

#### Calculation

```python
# Per unused PVC — the FULL cost is waste since nothing uses it
monthly_waste = pvc_provisioned_gb * storage_rate
monthly_savings = monthly_waste  # delete PVC to recover full cost
```

#### Worked Example

```
PVC: logging/elasticsearch-data-2
  Status: Bound
  Size: 200 GiB
  Storage class: gp3 ($0.08/GiB/month)
  Last mounted: 21 days ago (pod was deleted)

Calculation:
  monthly_waste = 200 × $0.08 = $16.00/month
  monthly_savings = $16.00/month

Cluster has 4 unused PVCs totaling 500 GiB (gp3):
  total_monthly_waste = 500 × $0.08 = $40.00/month
```

### 3c. Oversized Volume Waste

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `provisioned_gb` | PVC `.spec.resources.requests.storage` | 500 GiB |
| `actual_used_gb` | CloudWatch `VolumeUsedBytes` / kubelet volume stats | 45 GiB |
| `storage_rate` | Rate for the storage class | $0.08/GiB/month |

#### Detection Criteria

Flag if:
- `waste_ratio > 50%` AND `provisioned_gb > 20 GiB` (ignore small volumes)

#### Calculation

```python
waste_ratio = (provisioned_gb - actual_used_gb) / provisioned_gb
wasted_gb = provisioned_gb - actual_used_gb

# Can't always shrink EBS volumes, so savings = cost of excess capacity
monthly_waste = wasted_gb * storage_rate

# Savings assumes right-sizing to 2x actual usage (safety buffer)
right_sized_gb = max(actual_used_gb * 2, 20)  # minimum 20 GiB
monthly_savings = (provisioned_gb - right_sized_gb) * storage_rate
```

#### Worked Example

```
PVC: analytics/clickstream-data
  Provisioned: 500 GiB (gp3)
  Actual used: 45 GiB
  Storage rate: $0.08/GiB/month

Detection:
  waste_ratio = (500 - 45) / 500 = 91%
  91% > 50% ✓  AND  500 > 20 GiB ✓  → OVERSIZED

Calculation:
  wasted_gb = 500 - 45 = 455 GiB
  monthly_waste = 455 × $0.08 = $36.40/month

  right_sized_gb = max(45 × 2, 20) = 90 GiB
  monthly_savings = (500 - 90) × $0.08 = $32.80/month

  effort: Medium (requires volume snapshot + restore to smaller size)
```

---

## 4. Network Waste

### 4a. Cross-AZ Data Transfer

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `cross_az_gb_per_month` | VPC Flow Logs / Container Insights network metrics | 500 GiB |
| `cross_az_rate` | AWS pricing (fixed) | $0.01/GiB |

#### Calculation

```python
# Current cross-AZ cost
monthly_waste = cross_az_gb_per_month * 0.01

# Savings from topology-aware routing (typically 50–80% reduction)
reduction_factor = 0.65  # conservative 65% reduction
monthly_savings = monthly_waste * reduction_factor
```

#### Worked Example

```
Cluster: production-us-east-1
  Pods spread across 3 AZs (us-east-1a, 1b, 1c)
  Service "order-api" has 6 replicas across all 3 AZs
  Estimated cross-AZ traffic: 500 GiB/month

Calculation:
  monthly_waste = 500 × $0.01 = $5.00/month
  monthly_savings = $5.00 × 0.65 = $3.25/month

  fix: Enable topology-aware routing on high-traffic services
  effort: Low (add annotation to Service)
```

#### Estimating Cross-AZ Traffic

When direct metrics are unavailable, estimate from service topology:

```python
# For each Service with pods in multiple AZs:
# Assume uniform traffic distribution across replicas
# Traffic that hits a replica in a different AZ = cross-AZ

num_azs = len(set(pod.az for pod in service.pods))
cross_az_probability = (num_azs - 1) / num_azs  # e.g., 2/3 for 3 AZs

# If service handles ~1000 requests/sec at ~10KB avg response:
estimated_monthly_gb = (requests_per_sec * avg_response_kb / 1024 / 1024) * 86400 * 30
cross_az_gb = estimated_monthly_gb * cross_az_probability
```

### 4b. NAT Gateway Waste

#### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `nat_gb_per_month` | CloudWatch `NatGatewayBytesOutToDestination` | 200 GiB |
| `nat_rate` | AWS pricing (fixed) | $0.045/GiB |
| `num_azs` | Number of AZs with private subnets | 3 |
| `vpc_endpoint_hourly_rate` | AWS pricing (fixed) | $0.01/hr/AZ |

#### Calculation

```python
# Current NAT cost for AWS service traffic
monthly_waste = nat_gb_per_month * 0.045

# VPC endpoint cost (per endpoint, per AZ)
endpoint_monthly_cost = vpc_endpoint_hourly_rate * 24 * 30 * num_azs
# = $0.01 × 24 × 30 × 3 = $21.60/month per endpoint

# Savings = NAT cost eliminated minus endpoint cost
# Typically need endpoints for: ECR (2 endpoints), S3 (gateway, free), STS (1)
num_interface_endpoints = 3  # ecr.api, ecr.dkr, sts
total_endpoint_cost = endpoint_monthly_cost * num_interface_endpoints

monthly_savings = monthly_waste - total_endpoint_cost
# Only recommend if savings > 0 (break-even analysis)
```

#### Worked Example

```
Cluster: production-us-east-1
  NAT Gateway traffic to AWS services: 200 GiB/month
  AZs: 3
  No VPC endpoints configured

Current NAT cost:
  monthly_waste = 200 × $0.045 = $9.00/month

VPC endpoint cost (if added):
  S3 gateway endpoint: FREE
  ECR endpoints (ecr.api + ecr.dkr): 2 × ($0.01 × 24 × 30 × 3) = $43.20/month
  STS endpoint: 1 × ($0.01 × 24 × 30 × 3) = $21.60/month
  Total endpoint cost: $64.80/month

Break-even analysis:
  $9.00 < $64.80 → VPC endpoints NOT cost-effective at this traffic level

  → Only recommend VPC endpoints when NAT traffic > ~1,440 GiB/month
  → Break-even: nat_gb × $0.045 > num_endpoints × $21.60
  → Break-even GB = (3 × $21.60) / $0.045 = 1,440 GiB/month

Higher-traffic example (2,000 GiB/month):
  monthly_waste = 2,000 × $0.045 = $90.00/month
  endpoint_cost = $64.80/month
  monthly_savings = $90.00 - $64.80 = $25.20/month ✓
```

---

## 5. Spot Opportunity

### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `workload_is_stateless` | No PVCs, no StatefulSet | true |
| `workload_replicas` | Deployment `.spec.replicas` | 4 |
| `workload_has_pdb` | PodDisruptionBudget exists | true |
| `workload_node_type` | Node capacity-type label | on-demand |
| `workload_monthly_cost` | Allocated node cost for this workload | $280.00 |
| `spot_discount` | Typical Spot discount (region/instance dependent) | 0.65 (65% off) |

#### Spot Eligibility Criteria

A workload is Spot-eligible if ALL of:
- Stateless (no PersistentVolumeClaims)
- Not a database or stateful system (not a StatefulSet)
- Has multiple replicas (replicas > 1)
- Has a PodDisruptionBudget configured
- Currently running on On-Demand nodes

#### Getting Accurate Spot Pricing

The default 65% discount is a conservative estimate. For **production-grade findings**, query actual Spot prices for the customer's instance types and region:

```bash
# Get current Spot prices for the instance types in use
aws ec2 describe-spot-price-history \
  --instance-types m5.xlarge m6g.xlarge c5.xlarge c7g.xlarge \
  --product-descriptions "Linux/UNIX" \
  --start-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --query 'SpotPriceHistory[].{Type:InstanceType,AZ:AvailabilityZone,Price:SpotPrice}' \
  --output table
```

When live Spot pricing is available:
- Use `actual_spot_discount = 1 - (spot_price / on_demand_price)` per instance type
- Confidence level: **High**
- Report exact dollar savings

When live Spot pricing is NOT available (no `ec2:DescribeSpotPriceHistory` permission):
- Use 65% default discount
- Confidence level: **Medium**
- Prefix savings with "~" (approximate)

#### Calculation

```python
# Identify Spot-eligible workloads currently on On-Demand
spot_eligible = [
    w for w in workloads
    if w.is_stateless
    and w.replicas > 1
    and w.has_pdb
    and w.node_capacity_type == "on-demand"
    and not w.is_statefulset
]

# Per workload
on_demand_cost = workload_monthly_cost
spot_savings = on_demand_cost * spot_discount  # typically 60–70%

monthly_waste = spot_savings  # "waste" = premium paid for On-Demand
monthly_savings = spot_savings

# Aggregate
total_spot_opportunity = sum(w.monthly_savings for w in spot_eligible)
```

#### Worked Example

```
Workload: frontend/web-app
  Replicas: 6
  Stateless: yes (no PVCs)
  PDB: yes (minAvailable: 4)
  Current capacity: On-Demand (m5.xlarge nodes)
  Monthly cost: $280.00

Spot discount for m5.xlarge in us-east-1: ~65%

Calculation:
  monthly_waste = $280.00 × 0.65 = $182.00/month
  monthly_savings = $182.00/month

Cluster has 5 Spot-eligible workloads:
  | Workload | Monthly Cost | Spot Savings |
  |----------|-------------|--------------|
  | frontend/web-app | $280 | $182 |
  | api/gateway | $420 | $273 |
  | workers/processor | $560 | $364 |
  | cache/redis-proxy | $140 | $91 |
  | monitoring/collector | $96 | $62 |
  | **Total** | **$1,496** | **$972/month** |

  total_annual_savings = $972 × 12 = $11,664/year
  effort: Medium (create Spot NodePool, add tolerations, verify PDBs)
```

---

## 6. Graviton Opportunity

### Inputs

| Input | Source | Example |
|-------|--------|---------|
| `workload_architecture` | Node label `kubernetes.io/arch` | amd64 |
| `image_supports_arm64` | `docker manifest inspect` or ECR image index | true |
| `workload_monthly_cost` | Allocated node cost | $192.00 |
| `graviton_discount` | Graviton vs x86 price differential | 0.20 (20% cheaper) |

#### Graviton Eligibility Criteria

A workload is Graviton-eligible if:
- Currently running on x86 (amd64) nodes
- Container image supports arm64 platform (multi-arch manifest)
- No x86-specific binary dependencies (e.g., custom native libraries compiled for x86 only)

#### Calculation

```python
# Identify Graviton-eligible workloads on x86
graviton_eligible = [
    w for w in workloads
    if w.current_arch == "amd64"
    and w.image_supports_arm64
    and not w.requires_x86_specific_features
]

# Per workload
x86_cost = workload_monthly_cost
graviton_savings = x86_cost * graviton_discount  # typically 20%

monthly_waste = graviton_savings  # "waste" = premium paid for x86
monthly_savings = graviton_savings

# Aggregate
total_graviton_opportunity = sum(w.monthly_savings for w in graviton_eligible)
```

#### Checking arm64 Support

```bash
# Check if image has arm64 manifest
docker manifest inspect nginx:1.25 | jq '.manifests[] | select(.platform.architecture == "arm64")'

# For ECR images:
aws ecr batch-get-image --repository-name my-app --image-ids imageTag=latest \
  --query 'images[].imageManifest' | jq -r '.' | jq '.manifests[].platform.architecture'
```

#### Worked Example

```
Workload: api/order-service
  Current arch: amd64 (running on m5.xlarge)
  Image: 123456789.dkr.ecr.us-east-1.amazonaws.com/order-service:v2.1
  arm64 support: yes (multi-arch image)
  Monthly cost on x86: $192.00

Graviton equivalent: m6g.xlarge (20% cheaper than m5.xlarge)
  m5.xlarge:  $0.192/hr
  m6g.xlarge: $0.154/hr  (19.8% savings)

Calculation:
  monthly_waste = $192.00 × 0.20 = $38.40/month
  monthly_savings = $38.40/month

Cluster has 8 Graviton-eligible workloads:
  Total x86 monthly cost: $2,400.00
  total_monthly_savings = $2,400 × 0.20 = $480.00/month
  total_annual_savings = $480 × 12 = $5,760/year

  effort: Medium (build arm64 images, add nodeSelector/affinity, test)
```

---

## Aggregation and Prioritization

### Combining All Waste Categories

After calculating waste for each category, aggregate into a single prioritized list:

```python
findings = []

# Compute waste (per-pod, aggregated by namespace)
for namespace in namespaces:
    waste = calculate_compute_waste(namespace)
    if waste.monthly_waste > 0:
        findings.append({
            "id": f"compute-over-provisioned-{namespace.name}",
            "dimension": "compute",
            "type": "over_provisioned_pods",
            "affected_resource": namespace.name,
            "monthly_waste": waste.monthly_waste,
            "monthly_savings": waste.monthly_savings,
            "effort": "low",  # right-sizing requests
            "confidence": "high" if has_metrics else "medium"
        })

# Idle nodes
for node in idle_nodes:
    findings.append({
        "id": f"idle-node-{node.name}",
        "dimension": "idle",
        "type": "idle_node",
        "affected_resource": node.name,
        "monthly_waste": node.monthly_waste,
        "monthly_savings": node.monthly_savings,
        "effort": "low",  # drain and terminate
        "confidence": "high"
    })

# Storage waste (gp2, unused PVCs, oversized)
# ... similar pattern for each storage sub-category

# Network waste (cross-AZ, NAT)
# ... similar pattern

# Spot opportunity
# ... similar pattern

# Graviton opportunity
# ... similar pattern
```

### Prioritization Logic

Sort findings by **savings descending**, then by **effort ascending**:

```python
EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2}

findings.sort(key=lambda f: (
    -f["monthly_savings"],           # highest savings first
    EFFORT_ORDER[f["effort"]]        # lowest effort first (tiebreaker)
))
```

### Severity Assignment (Based on Monthly Waste)

```python
def assign_severity(monthly_waste: float) -> str:
    if monthly_waste > 500:
        return "CRITICAL"
    elif monthly_waste > 200:
        return "HIGH"
    elif monthly_waste > 50:
        return "MEDIUM"
    else:
        return "LOW"
```

### Summary Aggregation

```python
# Total savings potential
total_monthly_savings = sum(f["monthly_savings"] for f in findings)
total_annual_savings = total_monthly_savings * 12

# By dimension
savings_by_dimension = {}
for f in findings:
    dim = f["dimension"]
    savings_by_dimension[dim] = savings_by_dimension.get(dim, 0) + f["monthly_savings"]

# Quick wins (high savings + low effort)
quick_wins = [f for f in findings if f["effort"] == "low" and f["monthly_savings"] > 50]
```

### Complete Worked Example (Full Cluster)

```
Cluster: production-us-east-1 (15 nodes, 120 pods)

Findings (sorted by savings DESC, effort ASC):

| # | Type | Resource | Monthly Waste | Monthly Savings | Effort | Severity |
|---|------|----------|---------------|-----------------|--------|----------|
| 1 | Spot opportunity | 5 workloads | $972 | $972 | Medium | CRITICAL |
| 2 | Over-provisioned | payments/ | $847 | $720 | Low | CRITICAL |
| 3 | Graviton opportunity | 8 workloads | $480 | $480 | Medium | HIGH |
| 4 | Idle nodes | 3× m5.xlarge | $414 | $414 | Low | HIGH |
| 5 | Over-provisioned | api/ | $312 | $265 | Low | HIGH |
| 6 | Oversized volumes | analytics/ | $36 | $33 | Medium | LOW |
| 7 | Unused PVCs | logging/ | $40 | $40 | Low | LOW |
| 8 | gp2 volumes | 12 PVCs | $17 | $17 | Low | LOW |
| 9 | Cross-AZ traffic | order-api | $5 | $3 | Low | LOW |

Summary:
  Total monthly waste:   $3,123
  Total monthly savings: $2,944
  Total annual savings:  $35,328

  Quick wins (low effort, >$50 savings):
    - Right-size payments/ pods: $720/month
    - Drain idle nodes: $414/month
    - Right-size api/ pods: $265/month

  Savings by dimension:
    - Compute:      $985/month (33%)
    - Spot/Graviton: $1,452/month (49%)
    - Idle:         $414/month (14%)
    - Storage:      $90/month (3%)
    - Networking:   $3/month (<1%)
```

---

## Confidence Levels

Each waste calculation has an associated confidence level based on data quality:

| Confidence | Criteria | Impact on Reporting |
|------------|----------|---------------------|
| **High** | Direct metrics available (Container Insights, metrics-server, Cost Explorer) | Report exact dollar amounts |
| **Medium** | Estimated from node-level data or partial metrics | Report as "estimated ~$X/month" |
| **Low** | Inferred from configuration only (no utilization data) | Report as "potential savings up to $X/month" |

```python
def determine_confidence(data_sources: list[str]) -> str:
    if "cost_explorer" in data_sources or "container_insights" in data_sources:
        return "high"
    elif "metrics_server" in data_sources or "node_metrics" in data_sources:
        return "medium"
    else:
        return "low"
```

---

## Notes

- All prices are US East (N. Virginia) On-Demand rates. **Use the AWS Price List API for region-specific pricing** (see `cost-estimation-fallback.md` Step 2).
- Spot discounts vary by instance type and region (40–90%). Use 65% as conservative default. **For production accuracy, query live Spot prices:**
  ```bash
  aws ec2 describe-spot-price-history \
    --instance-types <type1> <type2> \
    --product-descriptions "Linux/UNIX" \
    --start-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --query 'SpotPriceHistory[].{Type:InstanceType,AZ:AvailabilityZone,Price:SpotPrice}' \
    --output table
  ```
- Graviton savings vary by instance family (15–40%). Use 20% as conservative default.
- Cross-AZ pricing is consistent across regions ($0.01/GiB each direction).
- NAT Gateway pricing is consistent across regions ($0.045/GiB processed).
- Storage pricing varies by region; us-east-1 rates used as reference.
- **EKS control plane cost:** $0.10/hr (standard support) or $0.60/hr (extended support for older K8s versions). Always check the cluster's K8s version — see `cost-estimation-fallback.md` for details.
- **Static pricing data in this file is a fallback.** The skill should prefer live API lookups for dollar-accurate findings. Mark findings using static prices as "Medium" or "Low" confidence.
