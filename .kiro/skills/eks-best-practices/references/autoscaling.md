# EKS Autoscaling Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Autoscaler selection, Cluster Autoscaler, HPA, VPA, KEDA, and CoreDNS autoscaling for Amazon EKS

---

## Table of Contents

1. [Autoscaler Selection](#autoscaler-selection)
2. [Cluster Autoscaler](#cluster-autoscaler)
3. [EKS Auto Mode](#eks-auto-mode)
4. [Horizontal Pod Autoscaler](#horizontal-pod-autoscaler)
5. [Vertical Pod Autoscaler](#vertical-pod-autoscaler)
6. [KEDA Event-Driven Autoscaling](#keda-event-driven-autoscaling)
7. [CoreDNS Autoscaling](#coredns-autoscaling)

---

## Autoscaler Selection

### Node Autoscaler Decision Matrix

| Factor | Karpenter | Cluster Autoscaler (CAS) | EKS Auto Mode |
|--------|-----------|--------------------------|---------------|
| **Instance selection** | Flexible -- picks optimal from many types | Fixed to node group instance types | AWS-managed selection |
| **Scale-up speed** | Fast (~30s to provision) | Moderate (~60-90s) | Fast (AWS-managed) |
| **Consolidation** | Built-in, configurable | No native consolidation | AWS-managed |
| **Spot support** | Native Spot handling | Via mixed instance policy | AWS-managed |
| **Operational overhead** | Low -- CRD-based config | Medium -- ASG management | Lowest -- fully managed |
| **Customization** | High | Medium | Low |
| **Maturity** | GA (v1.0+) | Very mature | Newer -- evaluate for your use case |
| **Recommendation** | Default choice | When Karpenter is not an option | When minimal ops is top priority |

**For detailed Karpenter guidance, see:** [Karpenter Reference](karpenter.md)

### Pod Autoscaler Decision Matrix

| Scaler | Trigger | Use When |
|--------|---------|----------|
| **HPA** | CPU, memory, custom metrics | Stateless workloads with predictable load patterns |
| **VPA** | Historical resource usage | Right-sizing, non-scaling workloads |
| **KEDA** | External events (SQS, Kafka, etc.) | Event-driven, queue-based workloads |
| **HPA + KEDA** | Combined metrics | Complex scaling with both resource and event triggers |

---

## Cluster Autoscaler

### When to Use CAS Over Karpenter

- EKS on Outposts (Karpenter not supported)
- Self-managed node groups with specific AMI requirements
- Clusters already running CAS with complex ASG configurations
- Organizations requiring node group-level operational boundaries

### Operating the Cluster Autoscaler

CAS runs as a single-replica Deployment using leader election for HA. It is not horizontally scalable -- scale it vertically for large clusters.

Key requirements:
- **Version must match cluster version** -- cross-version compatibility is not tested or supported
- **Enable Auto Discovery** -- unless you have specific advanced use cases requiring manual ASG configuration
- **Use EKS Managed Node Groups** -- they provide automatic ASG discovery and graceful node termination

### IAM Least Privilege

Scope CAS's IAM permissions to the cluster's own ASGs. This prevents a CAS instance in one cluster from modifying node groups in another cluster:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:SetDesiredCapacity",
        "autoscaling:TerminateInstanceInAutoScalingGroup"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/k8s.io/cluster-autoscaler/enabled": "true",
          "aws:ResourceTag/k8s.io/cluster-autoscaler/my-cluster": "owned"
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:DescribeAutoScalingInstances",
        "autoscaling:DescribeLaunchConfigurations",
        "autoscaling:DescribeScalingActivities",
        "autoscaling:DescribeTags",
        "ec2:DescribeImages",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeLaunchTemplateVersions",
        "ec2:GetInstanceTypesFromInstanceRequirements",
        "eks:DescribeNodegroup"
      ],
      "Resource": "*"
    }
  ]
}
```

### Node Group Configuration

Nodes within a node group must have identical scheduling properties (labels, taints, resources). For MixedInstancePolicies:
- Instance types must have the same shape for CPU, memory, and GPU
- The first instance type in the policy is used for scheduling simulation
- Larger subsequent types waste resources after scale-out; smaller ones cause scheduling failures

Design principles:
- Prefer fewer node groups with many nodes over many node groups with few nodes -- this has the biggest impact on CAS scalability
- Use Namespaces for pod isolation instead of dedicated node groups (except in low-trust multi-tenant clusters)
- Use node taints or selectors as the exception, not the rule
- Define regional resources as a single ASG spanning multiple AZs

### Key CAS Configuration

```yaml
# Helm values for Cluster Autoscaler
autoDiscovery:
  clusterName: my-cluster
extraArgs:
  balance-similar-node-groups: true
  skip-nodes-with-local-storage: false
  expander: least-waste           # or: priority, random, most-pods
  scale-down-utilization-threshold: 0.5
  scale-down-delay-after-add: 10m
  scale-down-unneeded-time: 10m
  max-graceful-termination-sec: 600
```

### CAS Expander Selection

| Expander | Behavior | Use When |
|----------|----------|----------|
| **least-waste** | Least idle resources after scale-up | Default -- good for cost |
| **priority** | User-defined priority order | Prefer specific instance types |
| **most-pods** | Node fitting the most pending pods | Batch workloads |
| **random** | Random selection | Testing, simple setups |

### Priority Expander Example

Use the priority expander to prefer specific node groups with fallback:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler-priority-expander
  namespace: kube-system
data:
  priorities: |-
    10:
      - .*p2-node-group.*
    50:
      - .*p3-node-group.*
```

CAS tries `p3-node-group` first. If provisioning doesn't succeed within `--max-node-provision-time` (default 15 minutes), it falls back to `p2-node-group`.

### Spot Instances with CAS

Separate On-Demand and Spot capacity into different ASGs because their scheduling properties differ fundamentally (Spot nodes are typically tainted for preemption tolerance).

For MixedInstancePolicies with Spot:
- All instance types must have similar CPU and memory (e.g., m4, m5, m5a, m5n families)
- Use the [ec2-instance-selector](https://github.com/aws/amazon-ec2-instance-selector) tool to identify similar instance types
- Maximize diversity across instance families and AZs to reduce interruption impact
- Use `--expander=least-waste` to further optimize cost across diverse node groups

### Overprovisioning

CAS adds nodes only when needed, which means pods wait for node launch (~60-90s). For latency-sensitive workloads, use overprovisioning:

Deploy low-priority "pause" pods that occupy spare capacity. When real pods arrive with higher priority, the pause pods are preempted, and the real pods schedule immediately on the existing node. The now-unschedulable pause pods trigger CAS to scale out a new node in the background.

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning
value: -1  # Lower than default (0)
globalDefault: false
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: overprovisioning
spec:
  replicas: 3  # One per AZ for optimal zone scheduling
  template:
    spec:
      priorityClassName: overprovisioning
      containers:
      - name: pause
        image: registry.k8s.io/pause
        resources:
          requests:
            cpu: "1"
            memory: 2Gi
```

Size the pause pods to match your typical workload. Set replicas equal to the number of AZs to ensure spare capacity in each zone.

### Scaling from Zero

CAS can scale node groups to and from zero, providing significant cost savings for intermittent workloads. CAS detects node resources from the InstanceType in the LaunchConfiguration or LaunchTemplate.

For pods requiring additional resources, node selectors, or taints not discoverable from the launch config, use ASG tags:

```
k8s.io/cluster-autoscaler/node-template/resources/$RESOURCE_NAME: 5
k8s.io/cluster-autoscaler/node-template/label/$LABEL_KEY: $LABEL_VALUE
k8s.io/cluster-autoscaler/node-template/taint/$TAINT_KEY: NoSchedule
```

Note: when scaling to zero, capacity is returned to EC2 and may not be available when you scale back up.

### Prevent Scale-Down Eviction

For expensive-to-restart workloads (batch jobs, ML training, long test runs), prevent CAS from scaling down the node:

```yaml
metadata:
  annotations:
    cluster-autoscaler.kubernetes.io/safe-to-evict: "false"
```

### Scalability Tuning

For clusters approaching 1000+ nodes:

- **Vertically scale CAS** -- increase CPU and memory requests. CAS stores all pods and nodes in memory, which can exceed 1GB for large clusters. Use the Addon Resizer or VPA to automate this.
- **Reduce node groups** -- fewer, larger node groups improve CAS performance. Many small node groups is a CAS anti-pattern.
- **Tune scan interval** -- the default 10s scan interval works for most clusters. For large clusters, increasing to 30-60s reduces API call volume (6x fewer calls) with moderate scale-up latency increase. Since node launch takes ~60-90s anyway, a 30s scan interval adds only ~50% to total scale-up time.
- **Shard as last resort** -- deploy multiple CAS instances, each managing different ASGs. Use separate namespaces to avoid leader election conflicts. Caveat: shards don't communicate, so multiple shards may scale out for the same unschedulable pod.

### Advanced Use Cases

**EBS Volumes and Stateful Workloads:**
- Enable `balance-similar-node-groups=true` for cross-AZ balancing
- Configure identical node groups per AZ, each with its own EBS volumes

**Accelerators/GPU:**
- GPU device plugins can take minutes to advertise resources after node launch, causing repeated unnecessary scale-outs
- Label GPU nodes with `--node-labels k8s.amazonaws.com/accelerator=$ACCELERATOR_TYPE` on the kubelet
- CAS uses this label to trigger accelerator-optimized behavior (including scale-down of nodes with unused accelerators)

### CAS Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scan-interval` | How often cluster is evaluated for scaling | 10s |
| `scale-down-delay-after-add` | Cooldown after scale-up before scale-down evaluation | 10m |
| `scale-down-delay-after-delete` | Cooldown after node deletion before scale-down | scan-interval |
| `scale-down-delay-after-failure` | Cooldown after scale-down failure | 3m |
| `scale-down-unneeded-time` | How long a node must be unneeded before scale-down | 10m |
| `scale-down-unready-time` | How long an unready node must be unneeded before removal | 20m |
| `scale-down-utilization-threshold` | Utilization below which a node is considered for scale-down | 0.5 |
| `max-empty-bulk-delete` | Max empty nodes deleted simultaneously | 10 |
| `max-graceful-termination-sec` | Max time for pod graceful shutdown during scale-down | 600 |

---

## EKS Auto Mode

### What EKS Auto Mode Manages

EKS Auto Mode provides AWS-managed:
- **Node provisioning and scaling** (no node groups to manage)
- **Node OS patching and upgrades**
- **Compute optimization** (instance selection, Spot)
- **Cluster add-ons** (VPC CNI, CoreDNS, kube-proxy)

### When to Use Auto Mode

Use Auto Mode when:
- Minimizing operational overhead is the top priority
- Standard compute patterns (web apps, APIs, microservices)
- Teams without deep Kubernetes node management expertise
- Greenfield clusters where you can adopt Auto Mode from the start

Don't use Auto Mode when:
- You need custom AMIs or specific kernel configurations
- GPU/ML workloads requiring specific instance types or drivers
- Windows containers are required
- You need fine-grained control over node configuration
- Running on EKS Outposts or EKS Anywhere

### Auto Mode Configuration

```hcl
# Terraform
resource "aws_eks_cluster" "this" {
  name = "my-cluster"

  compute_config {
    enabled       = true
    node_pools    = ["general-purpose", "system"]
    node_role_arn = aws_iam_role.node.arn
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
  }

  storage_config {
    block_storage {
      enabled = true
    }
  }
}
```

**For detailed Auto Mode guidance, see:** [EKS Auto Mode Reference](eks-auto-mode.md)

---

## Horizontal Pod Autoscaler

### HPA Configuration Patterns

```yaml
# CPU-based HPA with scaling behavior
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 50
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300    # 5 min cooldown
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60               # Scale down 10% per minute
```

### HPA Best Practices

DO:
- Set CPU target to 60-80% (leave headroom for bursts)
- Configure `scaleDown.stabilizationWindowSeconds` (prevent flapping)
- Set `minReplicas` >= 2 for HA (>= 3 for production)
- Use `behavior` policies to control scaling speed

DON'T:
- Set target utilization to 90%+ (no burst headroom)
- Use HPA without setting resource requests (HPA needs requests for CPU %)
- Combine HPA and VPA on the same CPU/memory metric
- Set `minReplicas: 1` for production services

### Custom Metrics with CloudWatch

```yaml
# HPA with custom CloudWatch metric via KEDA or metrics-adapter
metrics:
- type: External
  external:
    metric:
      name: sqs-queue-depth
      selector:
        matchLabels:
          queue: order-processing
    target:
      type: AverageValue
      averageValue: "5"
```

---

## Vertical Pod Autoscaler

### VPA Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| **Off** | Only provides recommendations | Start here -- review before applying |
| **Initial** | Sets resources only at pod creation | Safe -- no restarts of running pods |
| **Auto** | Updates resources (may restart pods) | After validating recommendations |

### VPA Configuration

```yaml
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
    updateMode: "Off"  # Start with recommendations only
  resourcePolicy:
    containerPolicies:
    - containerName: app
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 4
        memory: 8Gi
      controlledResources: ["cpu", "memory"]
```

### VPA + HPA Coexistence

**Rule:** Never scale on the same metric.

Safe combinations:
- VPA manages memory requests + HPA scales on CPU
- VPA manages CPU/memory + HPA scales on custom metrics (QPS, queue depth)

Conflict:
- VPA manages CPU + HPA scales on CPU (fight each other)

---

## KEDA Event-Driven Autoscaling

### KEDA with SQS

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: sqs-consumer
spec:
  scaleTargetRef:
    name: queue-processor
  minReplicaCount: 0    # Scale to zero when no messages
  maxReplicaCount: 100
  cooldownPeriod: 300
  triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.us-east-1.amazonaws.com/123456789012/orders
      queueLength: "5"
      awsRegion: us-east-1
    authenticationRef:
      name: keda-aws-credentials
```

### Common KEDA Triggers for EKS

| Trigger | Source | Use Case |
|---------|--------|----------|
| **aws-sqs-queue** | SQS queue depth | Message processing |
| **aws-cloudwatch** | CloudWatch metric | Custom metric scaling |
| **aws-kinesis-stream** | Kinesis shard lag | Stream processing |
| **kafka** | Kafka consumer lag | Event streaming |
| **prometheus** | Prometheus query | Custom application metrics |
| **cron** | Time schedule | Predictive scaling |

---

## CoreDNS Autoscaling

### Proportional Autoscaler

```yaml
# Scale CoreDNS proportionally to cluster size
apiVersion: v1
kind: ConfigMap
metadata:
  name: dns-autoscaler
  namespace: kube-system
data:
  linear: |-
    {
      "coresPerReplica": 256,
      "nodesPerReplica": 16,
      "min": 2,
      "max": 20,
      "preventSinglePointFailure": true
    }
```

**Scaling formula:** `replicas = max(ceil(cores / coresPerReplica), ceil(nodes / nodesPerReplica))`

For a 100-node cluster with 400 cores: `max(ceil(400/256), ceil(100/16))` = `max(2, 7)` = 7 replicas

### CoreDNS Tuning

**Set lameduck duration to 30 seconds** -- delays CoreDNS shutdown during pod termination, allowing iptables rule propagation and in-flight request completion. Especially critical with Karpenter's rapid node churn.

**Optimize ndots setting** -- default `ndots: 5` causes excessive DNS queries (tries multiple search domain suffixes before resolving external names). Set to `2` for pods making external DNS calls:

```yaml
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"
```

Alternatively, use trailing dots for FQDNs in application config: `api.example.com.`

**Use NodeLocal DNSCache** with Karpenter to prevent DNS failures during node scaling events.

---

**Sources:**
- [AWS EKS Best Practices Guide -- Cluster Autoscaler](https://docs.aws.amazon.com/eks/latest/best-practices/cas.html)
- [AWS EKS Best Practices Guide -- Auto Mode](https://docs.aws.amazon.com/eks/latest/best-practices/automode.html)
- [AWS EKS Best Practices Guide -- Karpenter](https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html)
