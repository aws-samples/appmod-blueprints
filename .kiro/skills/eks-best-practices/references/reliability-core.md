# Reliability & Resiliency — Core Patterns

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Everyday reliability patterns for production EKS workloads — high availability, pod disruption budgets, health probes, topology spread, resource limits, and container lifecycle.

---

## Table of Contents

1. [Control Plane Reliability](#control-plane-reliability)
2. [Data Plane Reliability](#data-plane-reliability)
3. [Pod Disruption Budgets](#pod-disruption-budgets)
4. [Health Probe Design](#health-probe-design)
5. [Load Balancer Health Checks](#load-balancer-health-checks)
6. [Container Lifecycle](#container-lifecycle)
7. [Topology Spread Constraints](#topology-spread-constraints)
8. [Resource Management](#resource-management)
9. [Complete Reliable Deployment Template](#complete-reliable-deployment-template)
10. [PDB Configuration](#pdb-configuration)
11. [Probe Configuration Guidance](#probe-configuration-guidance)
12. [Disaster Recovery](#disaster-recovery)

---

## Control Plane Reliability

### EKS Control Plane Architecture

The EKS control plane is managed by AWS and runs across **3 availability zones** by default:
- API server endpoints are behind a Network Load Balancer
- etcd is replicated across 3 AZs
- Control plane scales automatically based on cluster size

**What you control:**
- API server endpoint access (public, private, or both)
- Kubernetes audit logging
- Add-on versions and configurations

**Best practices for API server usage:**

- Use informers/watches instead of polling LIST calls
- Set appropriate QPS and burst limits on controllers
- Enable API Priority and Fairness (APF) for throttling
- Cache responses client-side where possible
- Don't run tight polling loops against the API server
- Don't use `list --all-namespaces` without field selectors in controllers
- Don't deploy many custom controllers without load testing

### Control Plane Monitoring Metrics

Monitor these key metrics via Prometheus or CloudWatch Container Insights (`kubectl get --raw /metrics`):

**API Server:**

| Metric | What It Tells You |
|--------|------------------|
| `apiserver_request_total` | Request count by verb, resource, response code |
| `apiserver_request_duration_seconds` | Response latency — detect slow API calls |
| `apiserver_admission_webhook_rejection_count` | Webhook rejections — detect policy issues |
| `rest_client_request_duration_seconds` | Latency of API server's own outbound calls |

**etcd:**

| Metric | What It Tells You |
|--------|------------------|
| `etcd_request_duration_seconds` | etcd latency by operation and object type |
| `apiserver_storage_size_bytes` | etcd database size (EKS v1.28+) |

When the etcd database size limit is exceeded, etcd stops accepting writes and the cluster becomes **read-only** — no new pods, no scaling, no deployments.

### Admission Webhook Safety

Poorly configured admission webhooks can destabilize the control plane by blocking cluster-critical operations:

- Avoid "catch-all" webhooks that match `apiGroups: ["*"]`, `resources: ["*"]`, `operations: ["*"]`
- Set `failurePolicy: Ignore` (fail-open) with `timeoutSeconds` < 30
- Exempt system namespaces (`kube-system`, `kube-node-lease`) from webhook scope

### Cluster Endpoint Connectivity

During control plane scaling or patching, API server IPs can change (DNS TTL is 60s). Kubernetes API consumers should:

- Implement **DNS re-resolution** (don't cache resolved IPs)
- Implement **retries with backoff and jitter** for transient failures
- Set **client timeouts** (e.g., `kubectl get pods --request-timeout 10s`)

### Block Unsafe Sysctls

Pods with unsafe `sysctls` will be repeatedly scheduled but never launch, creating an infinite loop that strains the control plane. Use OPA Gatekeeper or Kyverno to reject pods with unsafe sysctl profiles.

### API Server Availability

| Configuration | Access | Use When |
|--------------|--------|----------|
| **Public + Private** | kubectl from internet + nodes via private | Development, mixed access |
| **Private only** | kubectl via VPN/bastion only | Production, security-sensitive |
| **Public only** | kubectl from internet, nodes via public | ⚠️ Not recommended |

---

## Data Plane Reliability

### Node Group Strategy

| Approach | Reliability | Flexibility | Operational Overhead |
|----------|------------|-------------|---------------------|
| **Managed Node Groups (MNG)** | High — AWS handles updates | Medium | Low |
| **Karpenter** | High — auto-replaces unhealthy | High | Low |
| **Self-managed** | Depends on config | Full control | High |

### Multi-AZ Node Distribution

✅ DO:
- Spread nodes across at least 3 AZs
- Use multiple instance types in Karpenter NodePools for availability
- Configure AZ-balanced autoscaling in MNGs

❌ DON'T:
- Run all nodes in a single AZ
- Use a single instance type (risk of insufficient capacity)
- Ignore AZ-balanced distribution when scaling

### EKS Auto Mode for Reliability

EKS Auto Mode is the easiest path to a resilient data plane. AWS manages node provisioning, scaling, and OS patching automatically:
- Scales nodes up/down as pods scale
- Deploys CVE fixes and security patches automatically
- Control update timing via disruption settings on NodePools
- Includes the Node Monitoring Agent by default

### Node Monitoring Agent

The [Node Monitoring Agent](https://docs.aws.amazon.com/eks/latest/userguide/node-health.html) monitors node health and publishes Kubernetes events when issues are detected. EKS Auto Mode, MNG, and Karpenter can all auto-repair nodes based on fatal conditions reported by this agent. Install as an EKS add-on for non-Auto Mode clusters.

### Node Health and Replacement

**Karpenter automatic node replacement:**
- Drift detection: Replaces nodes when AMI, security group, or subnet changes
- Node expiry: `expireAfter` forces periodic node replacement
- Consolidation: Replaces underutilized nodes to save cost

**MNG automatic replacement:**
- Health checks: Replaces EC2-reported unhealthy instances
- Update strategy: Rolling updates with configurable max unavailable

### EBS Volume AZ Alignment

Pods using EBS-backed PersistentVolumes **must** be in the same AZ as the volume — a pod cannot access an EBS volume in a different AZ. Ensure:
- **EKS Auto Mode / Karpenter:** NodeClass selects subnets in each AZ
- **Managed Node Groups:** A node group exists in each AZ
- Use `volumeBindingMode: WaitForFirstConsumer` in StorageClass to defer volume creation until pod scheduling

### NodeLocal DNSCache

For large clusters, deploy [NodeLocal DNSCache](https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/) as a DaemonSet to improve DNS reliability and reduce CoreDNS load. Each node runs a local DNS cache, eliminating cross-node DNS queries. Included automatically in EKS Auto Mode. Also consider enabling [CoreDNS auto-scaling](https://docs.aws.amazon.com/eks/latest/userguide/coredns-autoscaling.html) to dynamically scale CoreDNS replicas based on cluster size.

---

## Pod Disruption Budgets

### PDB Configuration Rules

**Always create PDBs for production workloads with replicas > 1:**

```yaml
# ✅ GOOD — Percentage-based, scales with replicas
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: app-pdb
  namespace: production
spec:
  minAvailable: "50%"
  selector:
    matchLabels:
      app: my-app
```

```yaml
# ✅ GOOD — Absolute number for small deployments
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: redis-pdb
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: redis
```

### PDB Decision Guide

| Workload Type | Replicas | Recommended PDB |
|--------------|----------|-----------------|
| **Stateless web app** | 3+ | `minAvailable: "50%"` or `maxUnavailable: 1` |
| **Stateful (database)** | 3 (quorum) | `minAvailable: 2` or `maxUnavailable: 1` |
| **Singleton** | 1 | No PDB (would block all disruptions) |
| **Batch/job** | Varies | `maxUnavailable: "50%"` (allow faster drain) |
| **DaemonSet** | N/A | Not needed — 1 per node by design |

✅ DO:
- Use `minAvailable` percentage for auto-scaling workloads
- Use `maxUnavailable: 1` for stateful quorum-based systems
- Test PDB behavior with `kubectl drain --dry-run`

❌ DON'T:
- Set `minAvailable` equal to replica count (blocks all disruptions)
- Create PDBs for single-replica deployments
- Forget PDBs — Karpenter/node drains will evict without respecting availability

### PDB with Karpenter and Node Upgrades

Karpenter respects PDBs during:
- **Consolidation** — Won't consolidate if PDB would be violated
- **Drift replacement** — Waits for PDB budget before cordoning
- **Expiry** — Respects PDB during node replacement

If a PDB blocks node drain for >15 minutes (default), Karpenter's `terminationGracePeriod` on the NodePool determines behavior.

---

## Health Probe Design

### Probe Types and Purpose

| Probe | Purpose | Failure Action | Required? |
|-------|---------|---------------|-----------|
| **Startup** | Wait for slow-starting apps | Delays liveness/readiness | ✅ For apps with slow init |
| **Liveness** | Detect deadlocks/hangs | Restarts container | Situational — not always needed |
| **Readiness** | Traffic routing control | Removes from Service endpoints | ✅ For all Services |

### Probe Configuration Patterns

```yaml
# ✅ GOOD — Complete probe configuration
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: app
    ports:
    - containerPort: 8080

    # Startup probe: wait for slow initialization
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
      failureThreshold: 30    # 5 + (5 × 30) = up to 155s to start

    # Readiness probe: control traffic routing
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 10
      failureThreshold: 3
      successThreshold: 1

    # Liveness probe: detect deadlocks (use cautiously)
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 15
      failureThreshold: 3
      timeoutSeconds: 5
```

### Probe Anti-Patterns

❌ **DON'T make liveness probes check dependencies:**
```yaml
# ❌ BAD — Database check in liveness probe
# If DB goes down, ALL pods restart, causing cascading failure
livenessProbe:
  httpGet:
    path: /healthz?check=database
```

✅ **DO check dependencies in readiness — but with caution:**
```yaml
# ✅ GOOD — Database check in readiness probe
# If DB goes down, pods are removed from Service but stay running
readinessProbe:
  httpGet:
    path: /ready  # Checks database connectivity
```

**Important nuance:** Even readiness probes with external dependency checks carry risk. If a shared dependency (database, cache) becomes unavailable, ALL pods fail readiness simultaneously, removing all endpoints from the Service — effectively making the entire application unreachable. Consider:
- Using readiness for dependencies only the specific pod needs (not shared infrastructure)
- Implementing circuit breakers in the application instead of failing readiness on transient dependency issues
- For shared dependencies, prefer degraded responses over failing the readiness check entirely

### Probe Timing Rules

| Setting | Startup | Readiness | Liveness |
|---------|---------|-----------|----------|
| `initialDelaySeconds` | 0-10s | 0s (after startup) | 0s (after startup) |
| `periodSeconds` | 5-10s | 5-15s | 10-30s |
| `timeoutSeconds` | 1-5s | 1-5s | 1-5s |
| `failureThreshold` | 20-60 | 2-5 | 3-5 |
| `successThreshold` | 1 | 1-2 | 1 (always) |

**Key insight:** Use startup probes to handle slow initialization. This avoids setting large `initialDelaySeconds` on liveness probes, which delays deadlock detection.

---

## Load Balancer Health Checks

### ALB/NLB Health Check Alignment

**ALB health checks must align with readiness probes:**

```yaml
# Ingress annotation for ALB health check
annotations:
  alb.ingress.kubernetes.io/healthcheck-path: /ready
  alb.ingress.kubernetes.io/healthcheck-interval-seconds: "15"
  alb.ingress.kubernetes.io/healthcheck-timeout-seconds: "5"
  alb.ingress.kubernetes.io/healthy-threshold-count: "2"
  alb.ingress.kubernetes.io/unhealthy-threshold-count: "3"
```

✅ DO:
- Use the **same endpoint** for ALB health check and readiness probe
- Set ALB health check interval ≥ readiness probe period
- Account for NLB health check during graceful shutdown (use `deregistration_delay`)

❌ DON'T:
- Use different health endpoints for LB and K8s probes (leads to split-brain)
- Set health check thresholds too aggressively (causes flapping)

---

## Container Lifecycle

### Graceful Shutdown Pattern

**Complete graceful shutdown sequence:**

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 60  # Must be > preStop + shutdown time
      containers:
      - name: app
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
        # Application must handle SIGTERM gracefully
```

**Shutdown sequence timeline:**
1. Pod receives termination signal
2. Pod marked as `Terminating` — removed from Service endpoints
3. `preStop` hook executes (e.g., `sleep 15`)
4. SIGTERM sent to container process
5. Application handles SIGTERM (drain connections, finish requests)
6. After `terminationGracePeriodSeconds`, SIGKILL sent

### Why `sleep` in preStop?

The `sleep 15` in preStop gives time for:
- kube-proxy to update iptables rules (remove pod from Service)
- AWS Load Balancer Controller to deregister the target
- In-flight requests to complete routing to this pod

**Without the sleep, requests may still route to the terminating pod after SIGTERM.**

### PreStop Hook Patterns

| Workload Type | PreStop Command | Grace Period |
|--------------|----------------|--------------|
| **HTTP service behind ALB** | `sleep 15` | 45-60s |
| **gRPC service** | `sleep 10` | 30-45s |
| **Worker/consumer** | Custom drain script | Match job duration |
| **Database** | Graceful shutdown command | 60-120s |

### SIGTERM and PID 1

SIGTERM is sent to PID 1 in the container. If the main application process is not PID 1 (e.g., launched via a shell script wrapper), it won't receive SIGTERM and will be killed abruptly by SIGKILL.

```dockerfile
# BAD — shell script is PID 1, python app won't get SIGTERM
ENTRYPOINT ["./script.sh"]  # script.sh runs: python app.py

# GOOD — python app is PID 1
ENTRYPOINT ["python", "app.py"]

# GOOD — use dumb-init to forward signals
ENTRYPOINT ["dumb-init", "--", "python", "app.py"]
```

Use [dumb-init](https://github.com/Yelp/dumb-init) or [tini](https://github.com/krallin/tini) as an init process when your application can't easily be PID 1.

### Lifecycle Best Practices

- Set `terminationGracePeriodSeconds` > preStop duration + app shutdown time
- Use preStop sleep for services behind load balancers
- Handle SIGTERM in application code
- Ensure your main process is PID 1 or use an init system (dumb-init/tini)
- Don't set `terminationGracePeriodSeconds` to 0 in production
- Don't rely solely on SIGKILL for shutdown
- Don't forget preStop when using external load balancers

---

## Topology Spread Constraints

### Multi-AZ Pod Distribution

```yaml
# ✅ Spread pods evenly across AZs
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 6
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: my-app
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: my-app
```

### Topology Spread Decision Guide

| `whenUnsatisfiable` | Behavior | Use When |
|--------------------|----------|----------|
| **DoNotSchedule** | Strict — pod stays pending | Critical services, hard HA requirement |
| **ScheduleAnyway** | Best-effort — may be uneven | Non-critical, prefer availability over balance |

**Recommended pattern:** Use `DoNotSchedule` for zone spread + `ScheduleAnyway` for host spread. This ensures AZ distribution while allowing scheduling flexibility across nodes.

### Pod Anti-Affinity Alternative

```yaml
# Simple anti-affinity (spread across nodes)
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: my-app
        topologyKey: kubernetes.io/hostname
```

**Prefer `topologySpreadConstraints` over `podAntiAffinity`** — it provides more granular control and better behavior with multiple topology keys.

---

## Resource Management

### Resource Requests and Limits

```yaml
# ✅ GOOD — Requests set, limits set judiciously
resources:
  requests:
    cpu: 250m        # Scheduling guarantee
    memory: 512Mi    # Scheduling guarantee
  limits:
    memory: 1Gi      # OOM protection
    # cpu: omitted   # No CPU throttling
```

**Resource strategy:**

| Setting | CPU | Memory |
|---------|-----|--------|
| **Requests** | ✅ Always set (scheduling) | ✅ Always set (scheduling) |
| **Limits** | ❌ Usually omit (avoid throttling) | ✅ Always set (OOM protection) |

- Set memory limits = 1.5-2x memory requests
- Use VPA recommendations for right-sizing (also: Goldilocks, Parca)
- Set CPU requests based on actual usage (not peak)
- Don't set CPU limits on latency-sensitive workloads (causes throttling)
- For critical apps needing Guaranteed QoS (eviction protection), set requests = limits
- Correctly sized requests are critical for Karpenter/Cluster Autoscaler node provisioning
- Don't set limits much larger than requests (overcommit risk, higher eviction chance)

### Namespace Resource Controls

Use `ResourceQuota` and `LimitRange` together to prevent noisy neighbors:
- **ResourceQuota** — limits aggregate CPU, memory, pod count per namespace
- **LimitRange** — sets default requests/limits per container and enforces min/max

If ResourceQuota is enabled for compute resources, every container in that namespace must specify requests or limits.

---

## Complete Reliable Deployment Template

A production-ready deployment combining all reliability patterns:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      terminationGracePeriodSeconds: 60
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: my-app
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: my-app
      containers:
      - name: app
        image: my-app:v1.2.3
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: "250m"
            memory: "256Mi"
          limits:
            memory: "512Mi"       # No CPU limit — allow bursting
        startupProbe:
          httpGet:
            path: /healthz
            port: 8080
          failureThreshold: 30
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          periodSeconds: 10
          failureThreshold: 3
          timeoutSeconds: 5
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          periodSeconds: 5
          failureThreshold: 3
          timeoutSeconds: 3
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: my-app
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## PDB Configuration

### PDB for Different Workload Types

| Workload Type | Replicas | Recommended PDB | Rationale |
|---|---|---|---|
| Stateless web service | 3+ | `minAvailable: "50%"` | Allow rolling updates while maintaining capacity |
| Stateful quorum (etcd, ZooKeeper) | 3 | `maxUnavailable: 1` | Maintain quorum (2 of 3) at all times |
| Stateful primary-replica | 2+ | `minAvailable: 1` | Keep at least one replica available |
| Batch/job processor | Variable | `maxUnavailable: "50%"` | Allow fast drain while keeping throughput |
| Singleton controller | 1 | No PDB | PDB would block all evictions |

### PDB Interaction with Karpenter

Karpenter respects PDBs during node consolidation and drift replacement. If a PDB blocks eviction, Karpenter waits until the PDB allows it. Configure Karpenter disruption budgets alongside PDBs:

| Karpenter Setting | Purpose | Interaction with PDB |
|---|---|---|
| `disruption.budgets[].nodes` | Max nodes disrupted simultaneously | Limits how many nodes Karpenter drains at once |
| `disruption.consolidateAfter` | Wait time before consolidating | Gives pods time to rebalance before next consolidation |
| `expireAfter` | Force node replacement | Triggers drain which respects PDBs |

### PDB for System Components

| Component | Recommended PDB | Notes |
|---|---|---|
| CoreDNS | `maxUnavailable: 1` | Critical for DNS resolution; never drain all replicas |
| AWS Load Balancer Controller | `maxUnavailable: 1` | Ingress reconciliation must continue |
| Karpenter | `maxUnavailable: 1` (if 2+ replicas) | Node provisioning must continue |
| Kyverno | `minAvailable: 2` (if 3 replicas) | Admission webhook must remain available |

### Common PDB Mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| PDB on singleton (1 replica) | Blocks all evictions, node drain hangs | Don't create PDB for single-replica workloads |
| `minAvailable` equals replica count | Same as singleton — blocks all evictions | Use `minAvailable < replicas` or `maxUnavailable >= 1` |
| No PDB on critical workloads | All replicas evicted simultaneously during node drain | Add PDB to every production workload with >1 replica |
| PDB too restrictive during upgrades | Cluster upgrade stalls waiting for PDB | Temporarily relax PDB or use `maxUnavailable` instead |

---

## Probe Configuration Guidance

### Startup Probes

Use startup probes for applications with slow initialization (>10 seconds). The startup probe runs first; liveness and readiness probes don't start until the startup probe succeeds.

| Application Type | Typical Startup Time | Recommended Config |
|---|---|---|
| Java/Spring Boot | 30-120s | `failureThreshold: 30`, `periodSeconds: 10` (up to 5 min) |
| .NET | 15-60s | `failureThreshold: 12`, `periodSeconds: 10` (up to 2 min) |
| Go/Node.js | 1-5s | Usually not needed; use if >10s |
| ML model loading | 60-300s | `failureThreshold: 60`, `periodSeconds: 10` (up to 10 min) |

### Readiness vs Liveness Separation

| Rule | Readiness Probe | Liveness Probe |
|---|---|---|
| **Check dependencies?** | YES — check DB, cache, downstream services | NEVER — only check the process itself |
| **What happens on failure?** | Pod removed from Service endpoints (no traffic) | Pod restarted (container killed) |
| **Use for** | "Can this pod serve traffic right now?" | "Is this process deadlocked or hung?" |
| **Endpoint** | `/ready` or `/healthz` with dependency checks | `/livez` or simple TCP check |

**Critical rule:** Liveness probes must NOT check external dependencies. If the database goes down and liveness checks the DB, ALL pods restart simultaneously — causing cascading failure instead of graceful degradation.

### Recommended Timing

| Parameter | Readiness | Liveness | Notes |
|---|---|---|---|
| `initialDelaySeconds` | 5 | 15 | Liveness starts later to avoid killing slow-starting pods |
| `periodSeconds` | 10 | 15 | Liveness checks less frequently |
| `failureThreshold` | 3 | 3 | 3 consecutive failures before action |
| `timeoutSeconds` | 3 | 3 | Avoid long timeouts that mask issues |

---

## Disaster Recovery

### Cluster Recovery

The Terraform state file is the primary recovery artifact. If the cluster is destroyed:

1. Ensure the S3 state bucket has versioning enabled.
2. Re-run `terraform apply` with the same configuration to recreate the cluster.
3. Restore workloads from backups (Velero, if enabled).

### State Backup

Enable S3 versioning on the state bucket:

```bash
aws s3api put-bucket-versioning \
  --bucket my-state-bucket \
  --versioning-configuration Status=Enabled
```

To recover a previous state version:

```bash
aws s3api list-object-versions --bucket my-state-bucket --prefix eks/terraform.tfstate
aws s3api get-object --bucket my-state-bucket --key eks/terraform.tfstate --version-id <version-id> terraform.tfstate.backup
```

### Velero Backups

If Velero is enabled, schedule regular cluster backups:

```bash
velero schedule create daily-backup --schedule="0 2 * * *" --ttl 168h0m0s
```

Restore from backup:

```bash
velero restore create --from-backup daily-backup-<timestamp>
```

### Multi-Region Considerations

For multi-region disaster recovery:

1. Replicate the S3 state bucket to a secondary region.
2. Maintain a parallel config directory for the DR region with the appropriate VPC and subnet values.
3. Test the recovery procedure periodically by applying the DR config to a fresh region.

---

For deployment strategies, zonal shift, large-cluster guidance, admission-controller topology enforcement, and chaos engineering, see [reliability-advanced.md](reliability-advanced.md).

---

**Sources:**
- [AWS EKS Best Practices Guide — Reliability](https://docs.aws.amazon.com/eks/latest/best-practices/reliability.html)
- [AWS EKS Best Practices Guide — High Availability](https://aws.github.io/aws-eks-best-practices/reliability/docs/)
