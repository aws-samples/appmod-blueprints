# Findings Format

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Output schema, severity thresholds, finding types enumeration, and remediation snippet templates for cost intelligence findings

---

## Finding Schema

Every finding produced by the assessment engine MUST include all of the following fields:

```yaml
finding:
  id: string                      # unique identifier, e.g. "compute-over-provisioned-checkout"
  dimension: string               # one of: compute | spot_graviton | networking | storage | observability | idle
  severity: CRITICAL | HIGH | MEDIUM | LOW
  affected_resource: string       # namespace/workload or resource identifier
  current_state: string           # what is happening now (human-readable description)
  monthly_cost: number            # current monthly cost of this resource ($)
  monthly_waste: number           # estimated waste ($) — drives severity classification
  monthly_savings: number         # projected savings after fix ($)
  effort: Low | Medium | High     # implementation effort
  fix_summary: string             # one-line description of the fix
  remediation: string             # kubectl/Terraform/YAML snippet (ready to apply)
  confidence: high | medium | low # estimate confidence level
  data_sources: list[string]      # which data sources informed this finding
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier combining dimension prefix and resource, e.g. `compute-over-provisioned-checkout` |
| `dimension` | enum | The cost dimension this finding belongs to: `compute`, `spot_graviton`, `networking`, `storage`, `observability`, or `idle` |
| `severity` | enum | CRITICAL, HIGH, MEDIUM, or LOW — determined by `monthly_waste` thresholds below |
| `affected_resource` | string | The specific resource, e.g. `payments/checkout` (namespace/deployment) or `node-group-general` |
| `current_state` | string | Human-readable description of the current inefficiency |
| `monthly_cost` | number | Current monthly cost of the affected resource in USD |
| `monthly_waste` | number | Estimated monthly waste in USD (cost that could be eliminated) |
| `monthly_savings` | number | Projected monthly savings after implementing the fix |
| `effort` | enum | Implementation effort: `Low` (< 1 hour), `Medium` (1–4 hours), `High` (> 4 hours or requires planning) |
| `fix_summary` | string | One-line description of the recommended fix |
| `remediation` | string | Ready-to-apply code snippet (kubectl command, YAML manifest, or Terraform block) |
| `confidence` | enum | Confidence in the estimate: `high` (metrics-backed), `medium` (partial data), `low` (heuristic-based) |
| `data_sources` | list | Data sources used, e.g. `["metrics-server", "Cost Explorer"]` or `["kubernetes-api", "ec2-describe-instances"]` |

---

## Severity Thresholds

Severity is determined by the `monthly_waste` value:

| Monthly Waste | Severity | Description |
|---------------|----------|-------------|
| > $500/month | **CRITICAL** | Major cost inefficiency requiring immediate attention |
| $200–$500/month | **HIGH** | Significant waste that should be addressed within days |
| $50–$200/month | **MEDIUM** | Moderate waste worth addressing in the next sprint |
| < $50/month | **LOW** | Minor inefficiency — address opportunistically |

### Severity Assignment Rules

1. Severity is ALWAYS determined by `monthly_waste` — no manual overrides
2. When multiple resources share the same finding type, aggregate waste determines severity for the group finding
3. When waste cannot be precisely calculated (confidence: low), use conservative estimates and note the uncertainty
4. Findings with `confidence: low` should not be classified above HIGH regardless of estimated waste

---

## Finding Types

Finding types are organized by dimension. Each type maps to a specific cost inefficiency pattern:

### Compute Dimension (`compute`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `over_provisioned_pods` | CPU/memory requests significantly exceed actual P95 usage | MEDIUM–CRITICAL |
| `missing_resource_requests` | Workloads without CPU/memory requests defined | LOW–MEDIUM |
| `idle_nodes` | Nodes running at < 10% utilization for extended periods | HIGH–CRITICAL |
| `consolidation_disabled` | Karpenter installed but consolidation not enabled or ineffective | MEDIUM–HIGH |

### Spot/Graviton Dimension (`spot_graviton`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `spot_opportunity` | Stateless multi-replica workloads running exclusively on On-Demand | HIGH–CRITICAL |
| `graviton_opportunity` | x86 workloads with arm64-compatible images not using Graviton | MEDIUM–HIGH |
| `low_instance_diversity` | Spot NodePools with insufficient instance type diversity | MEDIUM |
| `missing_interruption_handling` | Spot nodes without Node Termination Handler or Karpenter interruption handling | MEDIUM |

### Networking Dimension (`networking`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `cross_az_traffic` | High cross-AZ data transfer without topology-aware routing | MEDIUM–HIGH |
| `nat_gateway_aws_traffic` | AWS service traffic (ECR, S3, STS) routed through NAT Gateway | MEDIUM–HIGH |
| `missing_vpc_endpoints` | VPC endpoints not configured for frequently accessed AWS services | MEDIUM |
| `instance_mode_lb` | Load balancers using instance mode where IP mode would reduce cross-AZ hops | LOW–MEDIUM |

### Storage Dimension (`storage`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `gp2_volumes` | EBS volumes using gp2 instead of gp3 (20% cost reduction available) | MEDIUM |
| `unused_pvcs` | PVCs bound but not mounted by any running pod | LOW–HIGH |
| `oversized_volumes` | Provisioned capacity significantly exceeds used capacity | MEDIUM–HIGH |
| `missing_efs_tiering` | EFS volumes without Intelligent-Tiering or lifecycle policies | LOW–MEDIUM |

### Observability Dimension (`observability`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `excessive_control_plane_logging` | All EKS control plane log types enabled unnecessarily | LOW–MEDIUM |
| `high_cardinality_metrics` | Prometheus/CloudWatch scraping high-cardinality metric sources | MEDIUM–HIGH |
| `debug_logging_production` | Workloads logging at DEBUG/TRACE level in production | LOW–MEDIUM |
| `missing_log_filtering` | No log filtering or sampling in the logging pipeline | LOW–MEDIUM |

### Idle Resources Dimension (`idle`)

| Type | Description | Typical Severity |
|------|-------------|-----------------|
| `orphaned_load_balancers` | LoadBalancer Services with no healthy backend endpoints | HIGH–CRITICAL |
| `zero_scale_deployments` | Deployments scaled to zero replicas for extended periods | LOW–MEDIUM |
| `empty_namespaces` | Namespaces with no running workloads but allocated quotas | LOW |
| `orphaned_config_resources` | ConfigMaps/Secrets not referenced by any running workload | LOW |

---

## Remediation Snippet Templates

Each finding type has a ready-to-apply remediation template. Replace `<placeholders>` with actual values from the finding.

### VPA Recommendation (`over_provisioned_pods`)

```yaml
# Install VPA and create a recommendation-only VPA for the workload
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: <deployment-name>-vpa
  namespace: <namespace>
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
  updatePolicy:
    updateMode: "Off"  # Recommendation-only mode — review before applying
  resourcePolicy:
    containerPolicies:
    - containerName: "*"
      controlledResources: ["cpu", "memory"]
```

```bash
# View VPA recommendations after ~5 minutes of data collection
kubectl get vpa <deployment-name>-vpa -n <namespace> \
  -o jsonpath='{.status.recommendation.containerRecommendations[*]}' | jq '.'

# Apply recommended requests manually (after review)
kubectl set resources deployment/<deployment-name> -n <namespace> \
  -c <container-name> \
  --requests="cpu=<target-cpu>,memory=<target-memory>"
```

---

### gp3 StorageClass (`gp2_volumes`)

```yaml
# Create a gp3 StorageClass and set as default
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  fsType: ext4
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
allowVolumeExpansion: true
```

```bash
# Remove default annotation from existing gp2 StorageClass
kubectl annotate storageclass gp2 \
  storageclass.kubernetes.io/is-default-class- --overwrite

# For existing volumes: modify EBS volume type directly (no downtime with EBS CSI >= 1.19)
aws ec2 modify-volume --volume-id <vol-id> --volume-type gp3

# Verify migration
aws ec2 describe-volumes --volume-ids <vol-id> \
  --query 'Volumes[0].{Type:VolumeType,State:State}'
```

---

### Karpenter Consolidation (`consolidation_disabled`)

```yaml
# Enable Karpenter consolidation in NodePool spec
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: <nodepool-name>
spec:
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 5m    # Production: 5m minimum; Non-prod: 30s acceptable
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand"]
```

```bash
# Verify consolidation is active
kubectl get nodepools -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.disruption.consolidationPolicy}{"\n"}{end}'

# Check consolidation events
kubectl get events --field-selector reason=Consolidating -A --sort-by='.lastTimestamp' | tail -10
```

---

### VPC Endpoints — Terraform (`nat_gateway_aws_traffic` / `missing_vpc_endpoints`)

```hcl
# Terraform: VPC endpoints for ECR, S3, and STS
# Eliminates NAT Gateway charges for AWS service traffic

# ECR API endpoint (Interface type)
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.cluster_name}-ecr-api"
  }
}

# ECR Docker endpoint (Interface type)
resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.cluster_name}-ecr-dkr"
  }
}

# S3 endpoint (Gateway type — no hourly charge)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids

  tags = {
    Name = "${var.cluster_name}-s3"
  }
}

# STS endpoint (Interface type — required for IRSA/Pod Identity)
resource "aws_vpc_endpoint" "sts" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.cluster_name}-sts"
  }
}

# Security group for Interface endpoints
resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.cluster_name}-vpce-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "HTTPS from VPC"
  }

  tags = {
    Name = "${var.cluster_name}-vpc-endpoints"
  }
}
```

---

### Topology-Aware Routing (`cross_az_traffic`)

```yaml
# Kubernetes 1.31+ (Beta, enabled by default) — use the trafficDistribution field
# This became GA/Stable in Kubernetes 1.33
apiVersion: v1
kind: Service
metadata:
  name: <service-name>
  namespace: <namespace>
spec:
  trafficDistribution: PreferClose   # Beta in 1.31, GA in 1.33
  selector:
    app: <app-label>
  ports:
  - port: 80
    targetPort: 8080
```

```yaml
# Kubernetes 1.27–1.30 — use the topology-mode annotation (legacy approach)
# This annotation is superseded by trafficDistribution in 1.31+ but still functional
apiVersion: v1
kind: Service
metadata:
  name: <service-name>
  namespace: <namespace>
  annotations:
    service.kubernetes.io/topology-mode: Auto
spec:
  selector:
    app: <app-label>
  ports:
  - port: 80
    targetPort: 8080
```

```yaml
# Ensure pods are spread across AZs (required for topology routing to be effective)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <deployment-name>
  namespace: <namespace>
spec:
  replicas: 3   # Minimum 3 replicas for effective zone distribution
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: <app-label>
```

---

### Spot NodePool (`spot_opportunity`)

```yaml
# Karpenter NodePool with Spot priority and On-Demand fallback
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: <workload-name>-spot
spec:
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["spot", "on-demand"]   # Spot preferred, On-Demand fallback
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["c", "m", "r"]         # Broad category for availability
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]                   # Current-gen instances only
      - key: karpenter.k8s.aws/instance-size
        operator: In
        values: ["large", "xlarge", "2xlarge", "4xlarge"]
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64", "arm64"]      # Include Graviton for additional savings
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 30s               # Aggressive consolidation for Spot
  limits:
    cpu: "100"
    memory: 400Gi
```

```bash
# Verify Spot nodes are being provisioned
kubectl get nodes -l karpenter.sh/capacity-type=spot \
  -o custom-columns=NAME:.metadata.name,TYPE:.metadata.labels.karpenter\\.sh/capacity-type,INSTANCE:.metadata.labels.node\\.kubernetes\\.io/instance-type

# Check Spot vs On-Demand distribution
echo "Spot nodes: $(kubectl get nodes -l karpenter.sh/capacity-type=spot --no-headers | wc -l)"
echo "On-Demand nodes: $(kubectl get nodes -l karpenter.sh/capacity-type=on-demand --no-headers | wc -l)"
```

---

## Finding Prioritization Rules

When presenting findings in the report, apply the following sort order:

1. **Primary sort:** Severity (CRITICAL > HIGH > MEDIUM > LOW)
2. **Secondary sort:** Monthly savings (descending — highest savings first)
3. **Tertiary sort:** Effort (ascending — Low effort first for tie-breaking)

This ensures the most impactful, easiest-to-implement fixes appear at the top of the recommendations list.

---

## Example Finding

```yaml
finding:
  id: "compute-over-provisioned-payments-checkout"
  dimension: "compute"
  severity: "CRITICAL"
  affected_resource: "payments/checkout"
  current_state: "Deployment requests 4 CPU / 8Gi memory per pod (3 replicas) but P95 usage is 0.8 CPU / 2.1Gi"
  monthly_cost: 1120
  monthly_waste: 847
  monthly_savings: 720
  effort: "Low"
  fix_summary: "Install VPA in recommendation mode, then right-size requests to P95 + 20% headroom"
  remediation: |
    apiVersion: autoscaling.k8s.io/v1
    kind: VerticalPodAutoscaler
    metadata:
      name: checkout-vpa
      namespace: payments
    spec:
      targetRef:
        apiVersion: apps/v1
        kind: Deployment
        name: checkout
      updatePolicy:
        updateMode: "Off"
  confidence: "high"
  data_sources:
    - "metrics-server"
    - "Container Insights"
    - "Cost Explorer"
```

---

*This reference file is part of the eks-cost-intelligence skill, provided as sample code
for educational and demonstration purposes only. See the project's README and LICENSE
for full terms.*
