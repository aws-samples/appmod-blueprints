# Cost Estimation Fallback

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Node-based cost estimation when Cost Explorer tags are missing, Split Cost Allocation is not enabled, or Cost Explorer API is unavailable

---

## When to Use This Fallback

Use node-based estimation when:
- Cluster resources are not tagged with `eks:cluster-name` or namespace tags
- Split Cost Allocation Data is not enabled
- Cost Explorer returns no data for the cluster
- Running in a restricted environment without `ce:GetCostAndUsage` permission
- Account is newly created (Cost Explorer needs 24 hours of data)

Node-based estimation is less precise than Cost Explorer data but still produces
useful directional findings. Always note the estimation method and confidence
level in the output.

---

## Pricing Lookup Strategy (Priority Order)

**Always prefer dynamic pricing over static tables:**

1. **AWS Price List API** (preferred) — Call `aws pricing get-products` for real-time, region-accurate pricing. See Step 2, Option B below.
2. **Reference pricing table** (fallback only) — Use the static table below ONLY when the Price List API is unavailable (e.g., no `pricing:GetProducts` permission, network-restricted environment). Mark findings as **Low confidence** when using the static table.

> ⚠️ **The reference pricing table is a point-in-time snapshot (last verified: June 2026, us-east-1).** AWS adjusts EC2 pricing periodically. Always prefer the Price List API for production assessments. If using the static table for a non-us-east-1 region, apply a ±15% confidence margin.

---

## EKS Control Plane Pricing

The EKS control plane cost depends on the cluster's Kubernetes version support status:

| Support Status | Hourly Rate | Monthly Cost (730h) | How to Detect |
|----------------|-------------|---------------------|---------------|
| **Standard support** (within first ~14 months of K8s version release) | $0.10/hr | $73.00/month | `aws eks describe-cluster` → check K8s version vs [EKS version calendar](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html) |
| **Extended support** (K8s version past standard support window) | $0.60/hr | $438.00/month | Cluster running a K8s version that has exited standard support |

```python
# Determine control plane hourly cost based on K8s version support status
# Versions in extended support as of June 2026: 1.25, 1.26, 1.27, 1.28
# NOTE: This list is illustrative and rotates as new K8s versions release.
# Always verify against: https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
# In production, query `aws eks describe-cluster` and compare the version against the EKS calendar.
EXTENDED_SUPPORT_VERSIONS = ["1.23", "1.24", "1.25", "1.26", "1.27", "1.28"]

def get_control_plane_hourly_rate(k8s_version: str) -> float:
    """Return EKS control plane hourly rate based on version support status."""
    minor_version = ".".join(k8s_version.split(".")[:2])
    if minor_version in EXTENDED_SUPPORT_VERSIONS:
        return 0.60  # Extended support: $0.60/hr
    return 0.10  # Standard support: $0.10/hr
```

> **Important:** Always check the cluster's Kubernetes version. A cluster on K8s 1.27 in extended support costs **6× more** for the control plane than one on 1.31 in standard support. This is often overlooked and can be a significant finding itself.

---

## Confidence Levels

| Scenario | Confidence | Accuracy | Notes |
|----------|-----------|----------|-------|
| Cost Explorer + namespace tags + Container Insights | **High** | ±5% | Most accurate — real billing data with per-namespace attribution |
| Cost Explorer + cluster tag only | **Medium** | ±15% | Cluster total accurate, namespace allocation estimated by requests |
| Node-based + Container Insights utilization | **Medium** | ±20% | Good for waste ratios, less accurate for absolute dollar cost |
| Node-based + kubectl requests only | **Low** | ±30% | Directional only — flag as estimate in all findings |

**Rules for confidence reporting:**
- Always include the confidence level in every finding's `confidence` field
- Always include `"estimation_method": "node_based"` in the data sources
- When confidence is Low, prefix savings estimates with "~" (approximate)
- Never present Low-confidence estimates as exact dollar amounts

---

## Step 1: Gather Node Inventory

Collect instance types, counts, and capacity types from the cluster:

```bash
# Full node inventory with cost-relevant labels
kubectl get nodes -o json | jq '[.items[] | {
  name: .metadata.name,
  instance_type: .metadata.labels["node.kubernetes.io/instance-type"],
  arch: .metadata.labels["kubernetes.io/arch"],
  region: .metadata.labels["topology.kubernetes.io/region"],
  zone: .metadata.labels["topology.kubernetes.io/zone"],
  capacity_type: (
    .metadata.labels["karpenter.sh/capacity-type"] //
    .metadata.labels["eks.amazonaws.com/capacityType"] //
    "on-demand"
  ),
  allocatable_cpu: .status.allocatable.cpu,
  allocatable_memory: .status.allocatable.memory,
  node_group: (
    .metadata.labels["eks.amazonaws.com/nodegroup"] //
    .metadata.labels["karpenter.sh/nodepool"] //
    "unknown"
  )
}]'
```

### Summary View (for quick assessment)

```bash
# Count nodes by instance type and capacity type
kubectl get nodes -o json | jq '
  [.items[] | {
    instance_type: .metadata.labels["node.kubernetes.io/instance-type"],
    capacity_type: (
      .metadata.labels["karpenter.sh/capacity-type"] //
      .metadata.labels["eks.amazonaws.com/capacityType"] //
      "on-demand"
    )
  }] | group_by(.instance_type + "-" + .capacity_type)
  | map({
      instance_type: .[0].instance_type,
      capacity_type: .[0].capacity_type,
      count: length
    })
  | sort_by(-.count)'
```

### Expected Output Example

```json
[
  {"instance_type": "m5.xlarge", "capacity_type": "on-demand", "count": 3},
  {"instance_type": "m6g.xlarge", "capacity_type": "spot", "count": 5},
  {"instance_type": "c5.2xlarge", "capacity_type": "on-demand", "count": 2}
]
```

---

## Step 2: Look Up Instance Pricing

**Primary method: AWS Price List API** — provides real-time, region-accurate pricing.
**Fallback: Reference table** — use only when the API is unavailable.

### Option B (PRIMARY): AWS Price List API Lookup

### Option A: Reference Pricing Table (FALLBACK ONLY — us-east-1, On-Demand, Linux)

> ⚠️ **Last verified: June 2026.** This table is a fallback for when the Price List API (Option B) is unavailable. Prices may drift. Always prefer Option B for production assessments.

Use this table ONLY when:
- `pricing:GetProducts` permission is not available
- Network-restricted environment cannot reach the Price List API endpoint
- Quick directional estimate needed (mark all findings as Low confidence)

| Instance Type | vCPU | Memory (GiB) | Arch | $/hour | $/month (730h) |
|---------------|------|--------------|------|--------|-----------------|
| t3.medium | 2 | 4 | x86 | $0.042 | $30.66 |
| t3.large | 2 | 8 | x86 | $0.083 | $60.59 |
| t3.xlarge | 4 | 16 | x86 | $0.166 | $121.18 |
| m5.large | 2 | 8 | x86 | $0.096 | $70.08 |
| m5.xlarge | 4 | 16 | x86 | $0.192 | $140.16 |
| m5.2xlarge | 8 | 32 | x86 | $0.384 | $280.32 |
| m5.4xlarge | 16 | 64 | x86 | $0.768 | $560.64 |
| m6i.large | 2 | 8 | x86 | $0.096 | $70.08 |
| m6i.xlarge | 4 | 16 | x86 | $0.192 | $140.16 |
| m6i.2xlarge | 8 | 32 | x86 | $0.384 | $280.32 |
| m7i.large | 2 | 8 | x86 | $0.100 | $73.00 |
| m7i.xlarge | 4 | 16 | x86 | $0.202 | $147.46 |
| m7i.2xlarge | 8 | 32 | x86 | $0.403 | $294.19 |
| m6g.large | 2 | 8 | arm64 | $0.077 | $56.21 |
| m6g.xlarge | 4 | 16 | arm64 | $0.154 | $112.42 |
| m6g.2xlarge | 8 | 32 | arm64 | $0.308 | $224.84 |
| m7g.large | 2 | 8 | arm64 | $0.082 | $59.86 |
| m7g.xlarge | 4 | 16 | arm64 | $0.163 | $118.99 |
| m7g.2xlarge | 8 | 32 | arm64 | $0.326 | $237.98 |
| c5.large | 2 | 4 | x86 | $0.085 | $62.05 |
| c5.xlarge | 4 | 8 | x86 | $0.170 | $124.10 |
| c5.2xlarge | 8 | 16 | x86 | $0.340 | $248.20 |
| c6i.xlarge | 4 | 8 | x86 | $0.170 | $124.10 |
| c6i.2xlarge | 8 | 16 | x86 | $0.340 | $248.20 |
| c7i.large | 2 | 4 | x86 | $0.089 | $64.97 |
| c7i.xlarge | 4 | 8 | x86 | $0.178 | $129.94 |
| c7i.2xlarge | 8 | 16 | x86 | $0.357 | $260.61 |
| c6g.xlarge | 4 | 8 | arm64 | $0.136 | $99.28 |
| c6g.2xlarge | 8 | 16 | arm64 | $0.272 | $198.56 |
| c7g.large | 2 | 4 | arm64 | $0.073 | $53.29 |
| c7g.xlarge | 4 | 8 | arm64 | $0.145 | $105.85 |
| c7g.2xlarge | 8 | 16 | arm64 | $0.290 | $211.70 |
| r5.large | 2 | 16 | x86 | $0.126 | $91.98 |
| r5.xlarge | 4 | 32 | x86 | $0.252 | $183.96 |
| r5.2xlarge | 8 | 64 | x86 | $0.504 | $367.92 |
| r6i.large | 2 | 16 | x86 | $0.126 | $91.98 |
| r6i.xlarge | 4 | 32 | x86 | $0.252 | $183.96 |
| r7i.large | 2 | 16 | x86 | $0.132 | $96.36 |
| r7i.xlarge | 4 | 32 | x86 | $0.264 | $192.72 |
| r6g.xlarge | 4 | 32 | arm64 | $0.202 | $147.46 |
| r6g.2xlarge | 8 | 64 | arm64 | $0.403 | $294.19 |
| r7g.large | 2 | 16 | arm64 | $0.107 | $78.11 |
| r7g.xlarge | 4 | 32 | arm64 | $0.214 | $156.22 |

**Pricing adjustments:**
- **Spot instances:** Apply ~70% discount → `spot_rate ≈ on_demand_rate × 0.30` (see Spot pricing note below)
- **Graviton (arm64):** Already reflected in table (~20% lower than x86 equivalent)
- **Other regions:** Rates vary ±5–15% from us-east-1; **use Price List API (Option B) for accuracy**
- **Unknown instance type:** Use the Price List API. If unavailable, default to $0.192/hour (m5.xlarge equivalent) and flag as Low confidence

> **Spot pricing note:** The 70% discount (30% of On-Demand) is a conservative average. Actual Spot discounts vary by instance type, region, and AZ (range: 40–90%). For accurate Spot pricing, query live Spot prices:
> ```bash
> aws ec2 describe-spot-price-history \
>   --instance-types m5.xlarge m6g.xlarge c5.xlarge \
>   --product-descriptions "Linux/UNIX" \
>   --start-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
>   --query 'SpotPriceHistory[].{Type:InstanceType,AZ:AvailabilityZone,Price:SpotPrice}' \
>   --output table
> ```
> Use this command to get the customer's actual Spot rate for their specific instance types and AZs. This produces **High confidence** Spot savings estimates vs the 30% assumption which is **Low confidence**.

### Option A (FALLBACK): Reference Pricing Table

For accurate, region-specific pricing:

```python
import boto3
import json

def get_instance_price(instance_type: str, region: str = "us-east-1") -> float:
    """Look up On-Demand hourly price for an EC2 instance type."""
    # Price List API is only available in us-east-1 and ap-south-1
    pricing = boto3.client("pricing", region_name="us-east-1")

    # Map region code to location name
    REGION_MAP = {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-2": "US West (Oregon)",
        "eu-west-1": "EU (Ireland)",
        "eu-central-1": "EU (Frankfurt)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
    }
    location = REGION_MAP.get(region, "US East (N. Virginia)")

    response = pricing.get_products(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ],
        MaxResults=1,
    )

    if not response["PriceList"]:
        return None  # Instance type not found

    price_data = json.loads(response["PriceList"][0])
    terms = price_data["terms"]["OnDemand"]
    # Navigate the nested pricing structure
    for term in terms.values():
        for dimension in term["priceDimensions"].values():
            return float(dimension["pricePerUnit"]["USD"])

    return None
```

**AWS CLI equivalent:**

```bash
aws pricing get-products \
  --service-code AmazonEC2 \
  --region us-east-1 \
  --filters \
    "Type=TERM_MATCH,Field=instanceType,Value=m5.xlarge" \
    "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" \
    "Type=TERM_MATCH,Field=location,Value=US East (N. Virginia)" \
    "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
    "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" \
    "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
  --query 'PriceList[0]' --output text | jq -r '
    .terms.OnDemand | to_entries[0].value.priceDimensions
    | to_entries[0].value.pricePerUnit.USD'
```

---

## Step 3: Calculate Total Cluster Cost

Sum all node costs plus the EKS control plane fee:

```python
HOURS_PER_MONTH = 730  # 24 hours × 30.4 days

# Extended support K8s versions (update as versions rotate)
# Check: https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
EXTENDED_SUPPORT_VERSIONS = ["1.23", "1.24", "1.25", "1.26", "1.27", "1.28"]

# Reference pricing table (FALLBACK — prefer Price List API)
# Last verified: June 2026, us-east-1
INSTANCE_HOURLY_RATES = {
    "t3.medium": 0.042, "t3.large": 0.083, "t3.xlarge": 0.166,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384, "m5.4xlarge": 0.768,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384,
    "m7i.large": 0.100, "m7i.xlarge": 0.202, "m7i.2xlarge": 0.403,
    "m6g.large": 0.077, "m6g.xlarge": 0.154, "m6g.2xlarge": 0.308,
    "m7g.large": 0.082, "m7g.xlarge": 0.163, "m7g.2xlarge": 0.326,
    "c5.large": 0.085, "c5.xlarge": 0.170, "c5.2xlarge": 0.340,
    "c6i.xlarge": 0.170, "c6i.2xlarge": 0.340,
    "c7i.large": 0.089, "c7i.xlarge": 0.178, "c7i.2xlarge": 0.357,
    "c6g.xlarge": 0.136, "c6g.2xlarge": 0.272,
    "c7g.large": 0.073, "c7g.xlarge": 0.145, "c7g.2xlarge": 0.290,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
    "r6i.large": 0.126, "r6i.xlarge": 0.252,
    "r7i.large": 0.132, "r7i.xlarge": 0.264,
    "r6g.xlarge": 0.202, "r6g.2xlarge": 0.403,
    "r7g.large": 0.107, "r7g.xlarge": 0.214,
}


def get_control_plane_hourly_rate(k8s_version: str) -> float:
    """Return EKS control plane hourly rate based on version support status."""
    minor_version = ".".join(k8s_version.split(".")[:2])
    if minor_version in EXTENDED_SUPPORT_VERSIONS:
        return 0.60  # Extended support: $0.60/hr ($438/month)
    return 0.10  # Standard support: $0.10/hr ($73/month)


def estimate_cluster_cost(
    nodes: list[dict],
    k8s_version: str = "1.31",
    region: str = "us-east-1",
    use_price_list_api: bool = True,
) -> dict:
    """
    Estimate total monthly cluster cost from node inventory.

    Args:
        nodes: List of node dicts with 'instance_type' and 'capacity_type' keys
        k8s_version: Cluster Kubernetes version (for control plane pricing)
        region: AWS region (used for Price List API and confidence)
        use_price_list_api: Whether to attempt Price List API for accuracy

    Returns:
        Dict with total cost, breakdown, and metadata
    """
    total_compute = 0.0
    breakdown = []
    unknown_types = []
    pricing_source = "reference_table"

    for node in nodes:
        instance_type = node["instance_type"]
        capacity_type = node.get("capacity_type", "on-demand").lower()

        # Primary: try Price List API for accurate, region-specific pricing
        hourly_rate = None
        if use_price_list_api:
            try:
                hourly_rate = get_instance_price(instance_type, region)
                pricing_source = "price_list_api"
            except Exception:
                pass  # Fall back to reference table

        # Fallback: reference pricing table
        if hourly_rate is None:
            hourly_rate = INSTANCE_HOURLY_RATES.get(instance_type)
            pricing_source = "reference_table"

        if hourly_rate is None:
            # Last resort: default to m5.xlarge and flag
            hourly_rate = 0.192
            unknown_types.append(instance_type)

        # Apply Spot discount (use live Spot pricing if available, else conservative estimate)
        if capacity_type == "spot":
            # TODO: For higher confidence, query aws ec2 describe-spot-price-history
            hourly_rate *= 0.30  # ~70% discount (conservative estimate)

        monthly_cost = hourly_rate * HOURS_PER_MONTH
        total_compute += monthly_cost

        breakdown.append({
            "node": node.get("name", "unknown"),
            "instance_type": instance_type,
            "capacity_type": capacity_type,
            "hourly_rate": round(hourly_rate, 4),
            "monthly_cost": round(monthly_cost, 2),
        })

    # EKS control plane cost (depends on K8s version support status)
    control_plane_hourly = get_control_plane_hourly_rate(k8s_version)
    control_plane_cost = control_plane_hourly * HOURS_PER_MONTH

    # Determine confidence
    if pricing_source == "price_list_api" and not unknown_types:
        confidence = "high"
    elif pricing_source == "reference_table" and not unknown_types and region == "us-east-1":
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "total_monthly_cost": round(total_compute + control_plane_cost, 2),
        "compute_cost": round(total_compute, 2),
        "control_plane_cost": round(control_plane_cost, 2),
        "control_plane_hourly": control_plane_hourly,
        "k8s_version": k8s_version,
        "extended_support": k8s_version in EXTENDED_SUPPORT_VERSIONS,
        "node_count": len(nodes),
        "node_breakdown": breakdown,
        "unknown_instance_types": unknown_types,
        "estimation_method": "node_based",
        "pricing_source": pricing_source,
        "confidence": confidence,
        "notes": (
            f"Pricing source: {pricing_source}. "
            f"{'Price List API used for region-accurate rates. ' if pricing_source == 'price_list_api' else 'Reference table (us-east-1 rates, last verified June 2026). '}"
            f"Spot nodes estimated at 30% of On-Demand (query describe-spot-price-history for accuracy). "
            f"{'Unknown types defaulted to $0.192/hr. ' if unknown_types else ''}"
            f"EKS control plane: ${control_plane_cost:.2f}/month "
            f"({'extended support' if k8s_version in EXTENDED_SUPPORT_VERSIONS else 'standard support'})."
        ),
    }
```

### Worked Example: Total Cluster Cost

**Cluster inventory:**
- 3× m5.xlarge (On-Demand)
- 5× m6g.xlarge (Spot)
- 2× c5.2xlarge (On-Demand)

**Calculation:**

| Node Type | Count | Capacity | $/hour | Monthly (×730h) | Subtotal |
|-----------|-------|----------|--------|-----------------|----------|
| m5.xlarge | 3 | On-Demand | $0.192 | $140.16 | $420.48 |
| m6g.xlarge | 5 | Spot | $0.154 × 0.30 = $0.046 | $33.73 | $168.63 |
| c5.2xlarge | 2 | On-Demand | $0.340 | $248.20 | $496.40 |
| **Compute subtotal** | | | | | **$1,085.51** |
| EKS control plane | 1 | — | $0.10 | $73.00 | $73.00 |
| **Total** | | | | | **$1,158.51/month** |

---

## Step 4: Allocate Cost to Namespaces

Without Cost Explorer namespace tags, allocate cluster compute cost proportionally
based on resource requests. This gives a directional view of which namespaces
consume the most cost.

### Gather Namespace Resource Requests

```bash
# Sum CPU and memory requests per namespace (excluding system namespaces)
kubectl get pods --all-namespaces -o json | jq '
  [.items[]
   | select(.metadata.namespace | test("^kube-|^amazon-|^karpenter$") | not)
   | select(.status.phase == "Running")
   | {
       namespace: .metadata.namespace,
       cpu_millicores: ([.spec.containers[].resources.requests.cpu // "0"
                        | if endswith("m") then rtrimstr("m") | tonumber
                          else tonumber * 1000 end] | add),
       memory_mib: ([.spec.containers[].resources.requests.memory // "0"
                    | if endswith("Mi") then rtrimstr("Mi") | tonumber
                      elif endswith("Gi") then rtrimstr("Gi") | tonumber * 1024
                      elif endswith("Ki") then rtrimstr("Ki") | tonumber / 1024
                      else tonumber / 1048576 end] | add)
     }
  ] | group_by(.namespace)
  | map({
      namespace: .[0].namespace,
      total_cpu_millicores: (map(.cpu_millicores) | add),
      total_memory_mib: (map(.memory_mib) | add),
      pod_count: length
    })
  | sort_by(-.total_cpu_millicores)'
```

### Allocation Formula

```python
def allocate_cost_by_requests(
    total_compute_cost: float,
    namespace_requests: dict,  # {namespace: {"cpu_cores": float, "memory_gib": float}}
    cpu_weight: float = 0.50,
    mem_weight: float = 0.50,
) -> dict:
    """
    Allocate cluster compute cost to namespaces proportionally by resource requests.

    Args:
        total_compute_cost: Total monthly compute cost (excluding control plane)
        namespace_requests: Dict mapping namespace to CPU (cores) and memory (GiB) requests
        cpu_weight: Weight for CPU in allocation (default 50%)
        mem_weight: Weight for memory in allocation (default 50%)

    Returns:
        Dict mapping namespace to allocated monthly cost and share percentage
    """
    total_cpu = sum(v["cpu_cores"] for v in namespace_requests.values())
    total_mem = sum(v["memory_gib"] for v in namespace_requests.values())

    allocation = {}
    for ns, requests in namespace_requests.items():
        # Calculate proportional share for each resource
        cpu_share = (requests["cpu_cores"] / total_cpu) if total_cpu > 0 else 0
        mem_share = (requests["memory_gib"] / total_mem) if total_mem > 0 else 0

        # Weighted combination
        weighted_share = (cpu_share * cpu_weight) + (mem_share * mem_weight)

        allocation[ns] = {
            "monthly_cost": round(total_compute_cost * weighted_share, 2),
            "share_percent": round(weighted_share * 100, 1),
            "cpu_cores": requests["cpu_cores"],
            "memory_gib": requests["memory_gib"],
        }

    return dict(sorted(allocation.items(), key=lambda x: -x[1]["monthly_cost"]))
```

### Worked Example: Namespace Cost Allocation

**Given:** Total compute cost = $1,085.51/month (from Step 3 example)

**Namespace resource requests:**

| Namespace | CPU (cores) | Memory (GiB) | Pods |
|-----------|-------------|--------------|------|
| production | 8.0 | 24.0 | 12 |
| staging | 3.0 | 8.0 | 6 |
| data-pipeline | 4.0 | 16.0 | 4 |
| monitoring | 1.0 | 4.0 | 3 |
| **Total** | **16.0** | **52.0** | **25** |

**Allocation calculation (50% CPU weight, 50% memory weight):**

| Namespace | CPU Share | Mem Share | Weighted Share | Monthly Cost |
|-----------|-----------|-----------|----------------|--------------|
| production | 8/16 = 50.0% | 24/52 = 46.2% | 48.1% | $522.04 |
| data-pipeline | 4/16 = 25.0% | 16/52 = 30.8% | 27.9% | $302.73 |
| staging | 3/16 = 18.8% | 8/52 = 15.4% | 17.1% | $185.30 |
| monitoring | 1/16 = 6.2% | 4/52 = 7.7% | 7.0% | $75.44 |
| **Total** | | | **100%** | **$1,085.51** |

---

## Complete Worked Example: End-to-End Estimation

### Scenario

A production EKS cluster in us-east-1 with no Cost Explorer access:

**Step 1 — Node inventory:**
```
5× m5.xlarge (On-Demand) — general workloads
3× m6g.xlarge (Spot) — batch processing
1× r5.xlarge (On-Demand) — Redis/caching
```

**Step 2 — Pricing lookup (reference table):**
- m5.xlarge On-Demand: $0.192/hr
- m6g.xlarge Spot: $0.154 × 0.30 = $0.046/hr
- r5.xlarge On-Demand: $0.252/hr

**Step 3 — Total cluster cost:**

| Component | Calculation | Monthly Cost |
|-----------|-------------|--------------|
| 5× m5.xlarge OD | 5 × $0.192 × 730 | $700.80 |
| 3× m6g.xlarge Spot | 3 × $0.046 × 730 | $101.11 |
| 1× r5.xlarge OD | 1 × $0.252 × 730 | $183.96 |
| EKS control plane | 1 × $0.10 × 730 | $73.00 |
| **Total** | | **$1,058.87/month** |

**Step 4 — Namespace allocation:**

Namespace requests gathered via kubectl:
- `checkout`: 4.0 CPU, 12 GiB memory
- `catalog`: 3.0 CPU, 8 GiB memory
- `batch-jobs`: 2.5 CPU, 6 GiB memory
- `platform`: 1.5 CPU, 4 GiB memory

Total: 11.0 CPU, 30 GiB memory
Compute cost (excluding control plane): $985.87

| Namespace | Weighted Share | Estimated Cost |
|-----------|----------------|----------------|
| checkout | (4/11×0.5)+(12/30×0.5) = 38.2% | $376.49 |
| catalog | (3/11×0.5)+(8/30×0.5) = 26.9% | $265.53 |
| batch-jobs | (2.5/11×0.5)+(6/30×0.5) = 21.4% | $210.72 |
| platform | (1.5/11×0.5)+(4/30×0.5) = 13.5% | $133.13 |

**Confidence: Low** (node-based estimation, no utilization data, requests-only allocation)

---

## Integration with Findings

When using node-based estimation, set these fields on every finding:

```yaml
finding:
  confidence: low          # or medium if Container Insights available
  data_sources:
    - kubernetes_api
    - reference_pricing_table   # or "price_list_api" if API was used
  monthly_cost: 1058.87    # from Step 3
  # Prefix savings with "~" for low confidence
  monthly_waste: ~215.00
  monthly_savings: ~180.00
```

### Reporting the Estimation Method

Include this section in the report's Methodology & Confidence Notes:

```markdown
### Cost Estimation Method

| Aspect | Method Used |
|--------|-------------|
| Total cluster cost | Node-based estimation (reference pricing table) |
| Namespace allocation | Proportional by resource requests (50% CPU / 50% memory) |
| Spot pricing | Estimated at 30% of On-Demand (conservative) |
| Confidence level | Low — no Cost Explorer or utilization data available |

**To improve accuracy:**
1. Enable Cost Explorer and tag EKS resources with `eks:cluster-name`
2. Enable Split Cost Allocation Data for namespace-level attribution
3. Install metrics-server or enable Container Insights for utilization data
```

---

## Limitations and Caveats

1. **No Savings Plans / Reserved Instances reflected** — Node-based estimation uses On-Demand rates; actual cost may be lower if SP/RI coverage exists
2. **Spot pricing is approximate when using default 65% discount** — Real Spot prices fluctuate; query `describe-spot-price-history` for accuracy. The 30% of On-Demand is a conservative average.
3. **Region pricing differences** — Reference table uses us-east-1; other regions may differ by 5–15%. **Always use the Price List API (Option B) for non-us-east-1 regions.**
4. **No data transfer costs** — This method estimates compute only; networking costs require separate analysis
5. **System overhead not subtracted** — DaemonSets and system pods consume resources but are not allocated to user namespaces in the simple model above
6. **Extended support clusters** — Clusters on older K8s versions (in extended support) incur $0.60/hr control plane cost instead of $0.10/hr. The skill detects this automatically.
