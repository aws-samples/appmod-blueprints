# EKS Cost Optimization

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Cost optimization framework, compute/networking/storage cost strategies, observability cost management, tagging, and cost visibility tools for Amazon EKS

---

## Table of Contents

1. [Cost Optimization Framework](#cost-optimization-framework)
2. [Compute Cost Optimization](#compute-cost-optimization)
3. [Networking Cost Optimization](#networking-cost-optimization)
4. [Storage Cost Optimization](#storage-cost-optimization)
5. [Observability Cost Optimization](#observability-cost-optimization)
6. [Tagging & Cost Visibility](#tagging--cost-visibility)

---

## Cost Optimization Framework

AWS Cloud Financial Management (CFM) organizes cost optimization into four pillars:

| Pillar | Focus | EKS Actions |
|--------|-------|-------------|
| **See** | Measurement & accountability | Tag resources, deploy Kubecost, enable Cost Explorer |
| **Save** | Eliminate waste, optimize purchasing | Right-size, Spot/Graviton, consolidation |
| **Plan** | Forecast & budget | Track unit economics (cost per request/transaction) |
| **Run** | Continuous improvement | FinOps flywheel -- iterate on See/Save/Plan |

The "See" pillar comes first because you can't optimize what you can't measure. Start with tagging and cost visibility before pursuing compute or networking savings.

### EKS Cost Components

| Component | Cost Driver | Optimization Lever |
|-----------|-----------|-------------------|
| **EKS control plane** | $0.10/hour per cluster | Fewer clusters, multi-tenant |
| **EC2 instances** | Instance type + hours | Right-sizing, Spot, Graviton |
| **EBS volumes** | Volume type + size + IOPS | gp3, right-size, cleanup unused |
| **Data transfer** | Cross-AZ, internet egress | Topology-aware routing, VPC endpoints |
| **Load balancers** | Per ALB/NLB + LCU/hour | Consolidate ingress, shared ALB |
| **NAT Gateway** | Per GB processed + hourly | VPC endpoints for AWS services |
| **Observability** | Log ingestion + metric storage | Filter, retain selectively, reduce cardinality |

### Quick Wins

| Action | Typical Savings | Effort |
|--------|----------------|--------|
| Switch to Graviton (arm64) | 20-40% | Low -- rebuild images for arm64 |
| Use Spot for non-critical | 60-90% | Low -- Karpenter handles fallback |
| Enable Karpenter consolidation | 20-30% | Low -- enable in NodePool |
| Right-size with VPA recommendations | 15-30% | Medium -- review and apply |
| Use gp3 instead of gp2 | 20% on EBS | Low -- update StorageClass |
| VPC endpoints for ECR/S3 | Eliminate NAT costs | Low -- one-time setup |
| Topology-aware routing | 50-80% on cross-AZ | Medium -- enable topology hints |
| Reduce log verbosity in prod | 30-50% on logging | Low -- adjust log levels |

---

## Compute Cost Optimization

Compute is typically the largest cost driver for EKS. Optimize in this order:

1. **Right-size workloads** -- match requests to actual usage
2. **Reduce unused capacity** -- autoscale and consolidate
3. **Optimize capacity types** -- Spot, Graviton, Savings Plans

### Right-Sizing Workloads

Requests should align with actual utilization. Overprovisioned requests waste capacity -- the largest factor in total cluster costs. Each container (including sidecars) should have its own requests and limits.

**Right-sizing tools:**

| Tool | Approach | Best For |
|------|----------|----------|
| **VPA (recommendation mode)** | Historical usage analysis | Per-deployment recommendations |
| **Goldilocks** | VPA-based dashboard | Cluster-wide visibility |
| **KRR (Robusta)** | Prometheus-based analysis | Quick right-sizing across namespaces |
| **Kubecost** | Cost-aware recommendations | Tying resource changes to dollar savings |

```yaml
# Deploy VPA in recommendation-only mode
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Off"  # Recommendations only
```

```bash
# View recommendations
kubectl get vpa app-vpa -o jsonpath='{.status.recommendation.containerRecommendations[*]}' | jq
```

**Right-sizing decision framework:**

| Signal | Action |
|--------|--------|
| CPU request >> actual usage (consistently) | Reduce CPU request to P95 usage |
| Memory request >> actual usage | Reduce memory request to P99 usage + 20% buffer |
| CPU throttling observed | Increase CPU request (or remove CPU limit) |
| OOMKilled events | Increase memory limit |
| Pod pending due to resources | Scale nodes or reduce requests |

### Reducing Unused Capacity

Use HPA to scale pods based on demand, then let node autoscalers remove empty or underutilized nodes. Restrictive PodDisruptionBudgets can block node scale-down -- set `minAvailable` well below your replica count (e.g. `minAvailable: 4` for a 6-pod deployment).

For event-driven scaling (SQS queues, Kafka, CloudWatch metrics), use [KEDA](https://keda.sh/) instead of HPA's built-in metrics.

### Karpenter Consolidation

Karpenter continuously monitors and bin-packs workloads onto fewer, optimally-sized instances:

```yaml
# Enable consolidation in NodePool
spec:
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 30s  # Fast for non-prod; use longer (e.g. 5m) in prod
```

Karpenter selects the most cost-effective instance from your allowed types. It replaces underutilized nodes with smaller ones and removes empty nodes automatically.

For workloads that shouldn't be interrupted (long batch jobs without checkpointing), use the `karpenter.sh/do-not-disrupt: "true"` annotation.

**See also:** [Karpenter Reference](karpenter.md) for detailed NodePool configuration, consolidation tuning, and Spot handling.

### Cluster Autoscaler Priority Expander

If using Cluster Autoscaler instead of Karpenter, the priority expander lets you prefer cheaper capacity:

```yaml
# Priority expander ConfigMap -- scale reserved/Spot groups before on-demand
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
  priorities: |-
    10:
      - .*ondemand.*
    50:
      - .*reserved.*
```

Also consider the [Kubernetes Descheduler](https://github.com/kubernetes-sigs/descheduler) alongside CAS -- it rebalances pod placement after scheduling to improve cluster-wide utilization, which CAS alone does not do.

### Graviton (arm64) Migration

Graviton instances deliver 20-40% better price/performance than equivalent x86:

```yaml
# Karpenter NodePool supporting both architectures
spec:
  template:
    spec:
      requirements:
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64", "arm64"]  # Karpenter prefers cheaper Graviton
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["c", "m", "r"]
```

DO:
- Build multi-arch container images (`docker buildx`)
- Test on arm64 in staging before production
- Use Karpenter -- it automatically selects the most cost-effective architecture

DON'T:
- Assume all container images support arm64 (check base images)
- Mix architectures within a single deployment without affinity rules

### Spot Instance Strategies

```yaml
# Karpenter: Diversified Spot strategy
spec:
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["spot", "on-demand"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["c", "m", "r"]     # Multiple families
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]                # Current gen only
      - key: karpenter.k8s.aws/instance-size
        operator: In
        values: ["large", "xlarge", "2xlarge"]  # Multiple sizes
```

**Spot suitability:**

| Workload Type | Spot Suitable? | Notes |
|--------------|----------------|-------|
| Stateless web/API | Yes | Use with PDBs + multi-AZ |
| Batch processing | Yes | Ideal -- tolerant of interruption |
| CI/CD runners | Yes | Short-lived, easily retried |
| Development/test | Yes | Cost savings, acceptable disruption |
| Databases/stateful | No | Use On-Demand for data safety |
| Single-replica critical | No | No fallback on interruption |
| Long-running ML training | Maybe | Use checkpointing + Spot |

Karpenter handles Spot interruptions automatically (receives 2-min notice, cordons, launches replacement, drains respecting PDBs). For MNG/self-managed nodes, deploy AWS Node Termination Handler.

### Savings Plans & Reserved Instances

For stable, predictable baseline capacity, Compute Savings Plans provide up to 66% savings over On-Demand. Layer them with Spot for variable workloads:

- **Baseline** (always running): Savings Plans or Reserved Instances
- **Variable** (scales up/down): Spot with On-Demand fallback

### Downscaling Patterns

```yaml
# KEDA cron-based scaling -- scale to zero at night
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: dev-app
spec:
  scaleTargetRef:
    name: dev-app
  minReplicaCount: 0
  maxReplicaCount: 5
  triggers:
  - type: cron
    metadata:
      timezone: America/New_York
      start: "0 8 * * 1-5"    # Scale up at 8 AM weekdays
      end: "0 20 * * 1-5"     # Scale down at 8 PM weekdays
      desiredReplicas: "3"
```

When all pods are evicted from a node, Karpenter removes it. Combined with HPA/KEDA scaling pods to zero, nodes automatically scale to zero.

---

## Networking Cost Optimization

Cross-AZ data transfer is a significant cost in multi-AZ EKS clusters. AWS charges for data crossing AZ boundaries, so keeping traffic local reduces costs.

### Pod-to-Pod Traffic: Topology-Aware Routing

By default, kube-proxy distributes traffic across all pods regardless of AZ placement, causing cross-AZ charges.

**Topology-aware routing** (beta) allocates endpoints proportionally across zones:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: orders-service
  annotations:
    service.kubernetes.io/topology-mode: Auto
spec:
  selector:
    app: orders
  type: ClusterIP
```

Works best with evenly distributed workloads. Use with pod topology spread constraints to keep replicas balanced across zones. Hints may not be assigned when capacity fluctuates across zones (e.g., with Spot instances).

**Traffic Distribution** (GA in K8s 1.33) is a simpler, more predictable alternative:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: orders-service
spec:
  trafficDistribution: PreferClose
  selector:
    app: orders
  type: ClusterIP
```

`PreferClose` routes to same-zone endpoints first, falling back to any endpoint when none are local. Can overload endpoints in high-traffic zones -- mitigate with per-zone deployments with independent HPAs, or topology spread constraints.

**Service Internal Traffic Policy** restricts traffic to the originating node:

```yaml
spec:
  internalTrafficPolicy: Local
```

Use for tightly coupled services with frequent inter-communication. Requires co-located replicas via pod affinity rules -- traffic is dropped when no local endpoint exists. Cannot be combined with topology-aware routing.

### Load Balancer to Pod Communication

The AWS Load Balancer Controller supports two traffic modes:

| Mode | Path | Cross-AZ Cost |
|------|------|---------------|
| **Instance mode** | LB -> NodePort -> kube-proxy -> Pod | Likely cross-AZ hops |
| **IP mode** | LB -> Pod directly | No extra hops |

Use **IP mode** to eliminate data transfer charges from LB-to-Pod traffic. Ensure the LB is deployed across all subnets in your VPC.

### Network Cost Quick Reference

| Strategy | Savings | Effort |
|----------|---------|--------|
| IP mode on ALB/NLB | Eliminates LB-to-Pod cross-AZ charges | Low |
| Topology-aware routing / Traffic Distribution | Reduces cross-AZ pod-to-pod traffic | Medium |
| Gateway VPC endpoints (S3, DynamoDB) | Free -- no hourly or data transfer cost | Low |
| Interface VPC endpoints (ECR, STS) | Avoids NAT Gateway data processing ($0.045/GB) | Low |
| NAT Gateway per AZ | Eliminates inter-AZ NAT traversal | Low |
| In-region ECR pulls | Free (vs cross-region data transfer) | Low |

**For detailed networking configuration, see:** [Networking Reference](networking.md) | [Networking -- Ingress & DNS](networking-ingress-dns.md)

---

## Storage Cost Optimization

### Ephemeral Storage

| Option | Cost | Best For |
|--------|------|----------|
| **gp3 root volume** | ~20% less than gp2 | Default choice for node root volumes |
| **EC2 instance stores** | No additional cost | Caches, scratch space, temporary data |

Instance stores are physically attached to the host -- free, but data is lost on termination. Use `HostPath` or the Local Persistent Volume Static Provisioner to expose them in Kubernetes.

### Persistent Volumes: EBS

Start with **gp3** -- 20% cheaper per GB than gp2 and allows independent IOPS/throughput scaling:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  fsType: ext4
volumeBindingMode: WaitForFirstConsumer
```

**Migration paths from gp2 to gp3:**

| Method | Downtime | Requires |
|--------|----------|----------|
| CSI Volume Snapshots (backup + restore) | Yes | EBS CSI driver |
| PVC annotation modification | No | EBS CSI driver >= v1.19 |
| VolumeAttributesClass API | No | EKS >= 1.31 + EBS CSI >= 1.35 |

For mission-critical workloads needing >16K IOPS or >1 GiB/s throughput, use **io2 Block Express** (up to 256K IOPS, 4 GiB/s, 64 TiB).

Dynamically resize volumes as data grows rather than overprovisioning upfront. Use AWS Trusted Advisor or [Popeye](https://github.com/derailed/popeye) to find dangling/unused volumes.

### Persistent Volumes: EFS

EFS charges only for stored data with no upfront provisioning. Use **Intelligent-Tiering** to automatically move infrequently accessed files to cheaper storage (up to 92% savings).

| Storage Class | Cost | Use When |
|--------------|------|----------|
| **EFS Standard** | Highest | Frequently accessed, multi-AZ |
| **EFS Standard-IA** | ~92% less | Infrequently accessed, multi-AZ |
| **EFS One Zone** | ~47% less than Standard | Single-AZ tolerance, frequent access |
| **EFS One Zone-IA** | Lowest | Single-AZ, infrequent access |

EFS lifecycle policies and Intelligent-Tiering must be configured outside the CSI driver (console or EFS API).

### Persistent Volumes: FSx

| Option | Best For | Key Advantage |
|--------|----------|---------------|
| **FSx for Lustre** | ML training, HPC, video processing | Sub-ms latency, hundreds of GB/s throughput |
| **FSx for NetApp ONTAP** | Multi-protocol (NFS/SMB/iSCSI) | Data tiering between SSD and capacity pool |

For FSx for Lustre, link to S3 for long-term storage -- lazy-load data into Lustre for processing, write results back to S3, then delete the filesystem.

### Storage Quick Reference

| Strategy | Savings |
|----------|---------|
| gp3 over gp2 | 20% lower $/GB, independent IOPS/throughput |
| EFS Intelligent-Tiering | Up to 92% on infrequently accessed files |
| Instance store for caches | Zero additional cost (ephemeral) |
| Container image optimization | Distroless/scratch base images, multi-stage builds |
| Clean up dangling volumes | Direct savings -- Popeye or AWS Trusted Advisor |
| EBS snapshot retention policy | Avoid unbounded snapshot growth via DLM or Velero TTL |

---

## Observability Cost Optimization

Observability costs scale with data volume. Optimize by collecting only what matters and retaining intelligently.

### Logging

**Control plane logs:** Evaluate which log types are needed per environment. Non-production clusters may only need API server logs enabled selectively. Production clusters benefit from all types for incident investigation. EKS control plane logs are classified as **Vended Logs** with volume discount pricing.

| Strategy | Impact |
|----------|--------|
| Selective log types per environment | Reduce ingestion volume |
| Stream to S3 via CloudWatch subscriptions | Cheaper long-term storage |
| Forward non-critical logs directly to S3 (FluentBit) | Skip CloudWatch entirely |
| Reduce log levels (ERROR in prod, DEBUG in dev) | Significant volume reduction |
| Filter Kubernetes metadata in FluentBit | Remove unnecessary enrichment |

### Metrics

| Strategy | Impact |
|----------|--------|
| Monitor only what matters (work backwards from KPIs) | Fewer metrics = lower storage cost |
| Reduce cardinality (drop unnecessary labels) | Fewer unique time series |
| Tune scrape intervals (15s -> 30s/60s for non-critical) | 50-75% fewer data points |
| Use recording rules for pre-aggregation | Replace high-cardinality queries |

Identify high-cardinality offenders:

```promql
# Top 5 scrape targets by metric count
topk_max(5, max_over_time(scrape_samples_scraped[1h]))

# Top 5 by churn rate (new series created per scrape)
topk_max(5, max_over_time(scrape_series_added[1h]))
```

Use [Grafana Mimirtool](https://grafana.com/docs/grafana-cloud/account-management/billing-and-usage/control-prometheus-metrics-usage/usage-analysis-mimirtool/) to find metrics collected but never used in dashboards or alerts.

### Traces

For high-volume services, implement sampling strategies:

- **Head-based sampling**: Decide at trace start (simple, but may miss important traces)
- **Tail-based sampling**: Decide after trace completes (captures errors/slow requests, more complex)

Use the ADOT Collector's tail sampling processor to retain only traces that exceed latency thresholds or contain errors.

---

## Tagging & Cost Visibility

### Tagging Strategy

Tags are the foundation of cost allocation. Without them, you can see total spend but not who's spending it.

```yaml
# Karpenter EC2NodeClass tags
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  tags:
    Team: platform
    CostCenter: engineering
    Environment: production
    ManagedBy: karpenter
    kubernetes.io/cluster/my-cluster: owned
```

| Resource | Tag Source | Notes |
|----------|-----------|-------|
| EC2 instances | NodePool/EC2NodeClass tags | Karpenter applies automatically |
| EBS volumes | StorageClass tags | Set `tagSpecification` in CSI driver |
| ALB/NLB | Service/Ingress annotations | Via AWS LBC |
| VPC endpoints | Terraform/CloudFormation | Tag at creation |

AWS resource tags don't directly correlate with Kubernetes labels. Use Kubernetes labels on pods/namespaces for in-cluster cost attribution (via Kubecost), and AWS tags for billing/Cost Explorer views.

### Cost Visibility Tools

| Tool | Scope | Cost | Best For |
|------|-------|------|----------|
| **AWS Cost Explorer** | Account-level | Free | High-level trends, SP/RI recommendations |
| **Kubecost** | Cluster-level | Free (open source) | Per-namespace/pod cost allocation |
| **CloudWatch Container Insights** | Cluster + pod | ~$0.30/container/month | Resource utilization monitoring |
| **AWS Billing + tags** | Account-level | Free | Chargeback by team/project |
| **Karpenter metrics** | Node-level | Free | Consolidation efficiency |

### Kubecost

Kubecost provides real-time cost monitoring, namespace/label allocation, and right-sizing recommendations:

```bash
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost --create-namespace \
  --set kubecostProductConfigs.clusterName=my-cluster \
  --set kubecostProductConfigs.cloudIntegrationSecret=cloud-integration
```

| Feature | Free | Enterprise |
|---------|------|-----------|
| Namespace/label cost allocation | Yes | Yes |
| Right-sizing recommendations | Yes | Yes |
| Idle cost detection | Yes | Yes |
| Multi-cluster | No | Yes |
| SSO/RBAC | No | Yes |
| Long-term storage | 15 days | Unlimited |

DO:
- Use namespace-level cost allocation for multi-tenant clusters
- Enable CUR integration for accurate AWS pricing (not list price estimates)
- Set up idle cost alerts -- unused resources are the biggest waste
- Use right-sizing recommendations to adjust resource requests

DON'T:
- Rely solely on CloudWatch for K8s cost attribution -- it lacks namespace-level granularity
- Skip resource requests on pods -- Kubecost needs requests to calculate allocation
- Ignore shared costs (control plane, monitoring, ingress) -- allocate proportionally

---

**Sources:**
- [AWS EKS Best Practices Guide -- Cost Optimization](https://docs.aws.amazon.com/eks/latest/best-practices/cost-opt.html)
- [Kubecost Documentation](https://docs.kubecost.com/)
