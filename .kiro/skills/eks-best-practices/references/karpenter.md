# Karpenter Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Comprehensive Karpenter configuration and operational guidance for Amazon EKS

---

## Table of Contents

1. [Operational Best Practices](#operational-best-practices)
2. [NodePool Configuration](#nodepool-configuration)
3. [EC2NodeClass Configuration](#ec2nodeclass-configuration)
4. [Spot Best Practices](#spot-best-practices)
5. [Consolidation](#consolidation)
6. [Multiple NodePool Strategy](#multiple-nodepool-strategy)
7. [Cost Controls](#cost-controls)
8. [Resource Management](#resource-management)
9. [Private Clusters](#private-clusters)
10. [CoreDNS with Karpenter](#coredns-with-karpenter)

---

## Operational Best Practices

### Run Karpenter on Fargate or a Dedicated MNG

The Karpenter controller and webhook run as a Deployment that must be available before Karpenter can scale your cluster. Run them on infrastructure Karpenter does not manage -- either a small MNG (at least one worker node) or a Fargate profile for the `karpenter` namespace. If Karpenter runs on a node it manages, it could scale down that node and lose the ability to provision replacements.

### Lock Down AMIs in Production

Pin well-known AMI versions for production clusters. Using `@latest` or methods that deploy untested AMIs risks workload failures and downtime.

```yaml
amiSelectorTerms:
- alias: al2023@v20240807  # Pin tested version in production
# Use al2023@latest only in dev/test
```

Test newer AMI versions in non-production clusters before rolling to production.

### No Custom Launch Templates

Karpenter v1 APIs do not support custom launch templates. Use custom user data and/or directly specify custom AMIs in the EC2NodeClass instead. See the [Karpenter NodeClasses documentation](https://karpenter.sh/docs/concepts/nodeclasses/) for details.

### Version Compatibility

Unlike Cluster Autoscaler, Karpenter is not tightly coupled to Kubernetes versions. However, always consult the [Karpenter compatibility matrix](https://karpenter.sh/docs/upgrading/compatibility/) when upgrading.

---

## NodePool Configuration

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  template:
    metadata:
      labels:
        workload-type: general
    spec:
      requirements:
      - key: kubernetes.io/arch
        operator: In
        values: ["amd64"]
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand", "spot"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["c", "m", "r"]
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]
      - key: karpenter.k8s.aws/instance-size
        operator: NotIn
        values: ["nano", "micro", "small"]
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      expireAfter: 720h  # 30 days -- force node replacement

  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m

  limits:
    cpu: "1000"
    memory: 2000Gi

  weight: 50  # Priority relative to other NodePools
```

### Exclude Instance Types That Don't Fit

Avoid provisioning instance types your workloads don't need. For example, exclude large Graviton instances if you only run small workloads:

```yaml
- key: node.kubernetes.io/instance-type
  operator: NotIn
  values:
  - m6g.16xlarge
  - r6g.16xlarge
  - c6g.16xlarge
```

Use the [ec2-instance-selector](https://github.com/aws/amazon-ec2-instance-selector) CLI to discover instance types matching your compute requirements.

### Use Timers for Automatic Node Replacement

The `expireAfter` field sets a TTL on nodes. When a node reaches its expiry, Karpenter cordons, drains, and replaces it. This is a practical mechanism for:
- Rolling out AMI updates (nodes get the latest pinned AMI on replacement)
- Preventing long-lived nodes from accumulating drift
- Limiting blast radius of kernel or OS-level issues

Set `expireAfter` based on your AMI update cadence -- 720h (30 days) is a reasonable default for production.

---

## EC2NodeClass Configuration

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  role: KarpenterNodeRole-my-cluster
  amiSelectorTerms:
  - alias: al2023@v20240807  # Pin AMI version in production
  subnetSelectorTerms:
  - tags:
      karpenter.sh/discovery: my-cluster
  securityGroupSelectorTerms:
  - tags:
      karpenter.sh/discovery: my-cluster
  blockDeviceMappings:
  - deviceName: /dev/xvda
    ebs:
      volumeSize: 100Gi
      volumeType: gp3
      encrypted: true
      iops: 3000
      throughput: 125
  tags:
    Environment: production
    ManagedBy: karpenter
```

---

## Spot Best Practices

### Instance Diversity

The more instance types Karpenter can choose from, the better EC2 can optimize Spot availability and pricing. Karpenter uses the Price Capacity Optimized allocation strategy -- it picks from the deepest Spot pools with the lowest interruption risk, then selects the cheapest among those.

By default, Karpenter considers all instance types in your region/AZs and intelligently filters based on pod requirements (e.g., no GPU nodes for non-GPU pods). Avoid over-constraining instance types, especially with Spot -- if all instances of a type are reclaimed and no alternatives are available, pods stay pending until capacity returns.

DO:
- Include many instance types in requirements (broad categories: c, m, r)
- Use `capacity-type: ["on-demand", "spot"]` -- Karpenter handles fallback
- Spread across multiple AZs for deeper Spot pool access
- Use `consolidationPolicy: WhenEmptyOrUnderutilized` for cost optimization

DON'T:
- Restrict to a single instance type (loses Spot availability and diversity)
- Mix Karpenter and Cluster Autoscaler on the same workloads
- Set `expireAfter` too short (causes excessive churn)
- Forget to set resource limits on NodePools

### Enable Interruption Handling

Configure `--interruption-queue` with an SQS queue so Karpenter can respond to:
- **Spot interruptions** (2-minute notice) -- Karpenter immediately provisions a replacement and drains the affected node
- **Scheduled maintenance events**
- **Instance termination/stopping events**

When Karpenter detects these events, it taints, drains, and terminates affected nodes ahead of schedule, giving workloads time for graceful shutdown. This is especially important for pods that need checkpointing or graceful draining within the 2-minute Spot interruption window.

Do not use Karpenter interruption handling alongside AWS Node Termination Handler -- they conflict.

---

## Consolidation

### Consolidation Modes

| Policy | Behavior | Use When |
|--------|----------|----------|
| **WhenEmpty** | Only replaces nodes with zero pods | Conservative -- minimal disruption |
| **WhenEmptyOrUnderutilized** | Replaces underutilized nodes too | Default -- best cost optimization |

**Consolidation respects:**
- Pod disruption budgets
- `karpenter.sh/do-not-disrupt: "true"` annotation on pods or nodes

### Set requests=limits for Non-CPU Resources

Consolidation packs pods based on resource **requests**, not limits. Pods with memory limits higher than requests can burst above requests. If several pods on the same node burst simultaneously, this can trigger OOM kills. Consolidation makes this more likely because it packs nodes more tightly.

To prevent this, set `requests == limits` for memory and other non-CPU resources. CPU is the exception -- CPU is compressible and throttling (not OOM) is the consequence of exceeding limits.

---

## Multiple NodePool Strategy

### Create Mutually Exclusive or Weighted NodePools

If multiple NodePools match a pod's scheduling requirements and they are neither mutually exclusive (via taints/selectors) nor weighted, Karpenter **randomly chooses** which NodePool to use. This causes unpredictable scheduling. Design NodePools so they either:
- **Don't overlap** -- use taints on specialized NodePools (GPU, high-memory) so only pods with matching tolerations schedule there
- **Use weights** -- set `weight` to establish preference ordering among overlapping NodePools

### Example: GPU + General Workloads

```yaml
# High-priority: GPU workloads (tainted -- only GPU pods schedule here)
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu
spec:
  template:
    spec:
      requirements:
      - key: karpenter.k8s.aws/instance-gpu-count
        operator: Gt
        values: ["0"]
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand"]  # GPU on On-Demand only
      taints:
      - key: nvidia.com/gpu
        effect: NoSchedule
  weight: 100  # Higher priority than default

# Standard: General workloads
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  weight: 50
```

Deployment tolerating the GPU taint:

```yaml
spec:
  tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
```

### Example: Team-Based NodePools with Node Affinity

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: team-a
spec:
  template:
    metadata:
      labels:
        billing-team: team-a
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
      - key: node.kubernetes.io/instance-type
        operator: In
        values: ["m5.large", "m5.xlarge", "c5.large", "c5.xlarge"]
```

Deployment using node affinity to target the team's NodePool:

```yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: "billing-team"
            operator: "In"
            values: ["team-a"]
```

---

## Cost Controls

### Set Resource Limits on Every NodePool

The `limits` field caps the total compute a NodePool can provision. Without limits, Karpenter keeps adding capacity as long as there are pending pods -- which can cause runaway costs from misconfigurations or unexpected load.

```yaml
spec:
  limits:
    cpu: 1000
    memory: 1000Gi
```

Limits apply per NodePool -- there is no global cluster-wide limit. When a limit is exceeded, Karpenter logs `memory resource usage of 1001 exceeds limit of 1000` and stops provisioning.

### Create Billing Alarms

Even with NodePool limits, create AWS billing alarms as a safety net:
- **CloudWatch billing alarms** -- alert when estimated charges exceed a threshold
- **AWS Cost Anomaly Detection** -- ML-based monitoring for unusual spend patterns
- **AWS Budgets** with budget actions -- send email, SNS, or Slack notifications at specific thresholds

If routing Karpenter container logs to CloudWatch Logs, create a metrics filter for the limit-exceeded log pattern and alarm on it.

### Use do-not-disrupt for Long-Running Workloads

For batch jobs, ML training, or stateful workloads that are expensive to restart, annotate pods with `karpenter.sh/do-not-disrupt: "true"`. This prevents Karpenter from terminating the node even if `expireAfter` has been reached or consolidation would normally trigger. The annotation is respected until the pod terminates or the annotation is removed.

Note: if the only non-daemonset pods left on a node are from completed Jobs (status succeeded or failed), Karpenter can still terminate that node.

---

## Resource Management

### Use LimitRanges for Default Resource Requests

Kubernetes does not set default requests or limits. Pods without resource requests are treated as requesting zero resources by the scheduler and Karpenter, leading to poor bin-packing and potential node over-commitment. Use LimitRanges to set sensible namespace-level defaults:

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-resources
  namespace: my-namespace
spec:
  limits:
  - default:
      cpu: 500m
      memory: 512Mi
    defaultRequest:
      cpu: 250m
      memory: 256Mi
    type: Container
```

### Apply Accurate Resource Requests

Karpenter provisions right-sized nodes based on pod resource requests. Inaccurate requests lead to:
- **Over-requests:** Nodes are too large, wasting money
- **Under-requests:** Nodes are too small, causing OOM kills or CPU starvation

Use VPA in recommendation mode to measure actual usage and right-size requests. This is especially important when using consolidation, since consolidation packs pods tightly based on requests.

---

## Private Clusters

When running EKS in a VPC with no internet access, Karpenter requires these VPC endpoints:

| Endpoint | Why |
|----------|-----|
| **STS** | Karpenter uses IRSA/Pod Identity, which exchanges credentials via STS |
| **SSM** | Karpenter queries SSM parameters for AMI IDs during node provisioning |
| **EC2** | Standard EC2 API calls for instance provisioning |
| **EKS** | EKS API calls |

**No VPC endpoint exists for the Price List Query API.** Karpenter bundles on-demand pricing data in its binary, but this data only updates when Karpenter is upgraded. You'll see non-fatal errors about pricing data retrieval -- these are expected in private clusters.

See the [Karpenter private cluster documentation](https://karpenter.sh/docs/getting-started/getting-started-with-karpenter/#private-clusters) for the full list of required VPC endpoints.

---

## CoreDNS with Karpenter

Karpenter's rapid node churn (creating and terminating nodes dynamically) makes CoreDNS reliability critical. Key configurations:

- **Set lameduck duration to 30 seconds** -- delays CoreDNS shutdown during pod termination, allowing iptables rule propagation and in-flight DNS request completion
- **Use NodeLocal DNSCache** -- prevents DNS failures during node scaling events by caching DNS responses locally
- **Configure CoreDNS readiness probes** -- ensures DNS queries are not directed to pods that aren't ready

For detailed CoreDNS scaling configuration, see the [Autoscaling Reference -- CoreDNS section](autoscaling.md#coredns-autoscaling).

---

**Sources:**
- [AWS EKS Best Practices Guide -- Karpenter](https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html)
- [Karpenter Documentation](https://karpenter.sh/docs/)
- [Karpenter Blueprints](https://github.com/aws-ia/terraform-aws-eks-blueprints-addons)
