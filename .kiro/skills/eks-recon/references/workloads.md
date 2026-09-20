# Module: Workloads

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect running workloads - deployments, services, ingresses, jobs

**Note:** This is an optional module for migration assessments or workload inventory. Skip for basic infrastructure recon.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Understand the Detection Strategy](#understand-the-detection-strategy)
3. [List Workloads by Type](#list-workloads-by-type)
   - [List Deployments](#1-list-deployments)
   - [List StatefulSets](#2-list-statefulsets)
   - [List DaemonSets](#3-list-daemonsets)
   - [List CronJobs and Jobs](#4-list-cronjobs-and-jobs)
   - [List Services](#5-list-services)
   - [List Ingresses](#6-list-ingresses)
   - [List HPAs](#7-list-hpas)
4. [Generate Summary Statistics](#generate-summary-statistics)
5. [Output Schema](#output-schema)
6. [Analyze Workload Patterns](#analyze-workload-patterns)
   - [Check Workload Health](#check-workload-health)
   - [Audit Resource Requests and Limits](#audit-resource-requests-and-limits)
   - [Inventory Container Images](#inventory-container-images)
   - [Review PVC Usage](#review-pvc-usage)
7. [Handle Edge Cases](#handle-edge-cases)
8. [Apply Recommendations](#apply-recommendations)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `list_k8s_resources`, `read_k8s_resource`
- **CLI fallback:** `kubectl`

---

## Understand the Detection Strategy

Use this section to understand the scope of workload inventory before running commands. Workload inventory covers:

```
1. Deployments      -> Long-running applications
2. StatefulSets     -> Stateful applications
3. DaemonSets       -> Node-level agents
4. CronJobs/Jobs    -> Batch workloads
5. Services         -> Network exposure
6. Ingresses        -> External access
7. HPAs             -> Autoscaling configuration
```

---

## List Workloads by Type

Use these commands to enumerate workloads across namespaces. Start with Deployments (most common), then expand to StatefulSets, DaemonSets, and Jobs based on what you find.

### 1. List Deployments

Run this first to identify the main application workloads. Deployments are the most common workload type and reveal the core services running in the cluster.

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Deployment",
  api_version="apps/v1"
)
```

**CLI:**
```bash
# List all deployments with replica counts
kubectl get deploy -A -o json | jq -r '
  .items[] |
  select(.metadata.namespace | startswith("kube-") | not) |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    replicas: .spec.replicas,
    ready: .status.readyReplicas,
    image: .spec.template.spec.containers[0].image
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "api-gateway",
  "replicas": 3,
  "ready": 3,
  "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/api-gateway:v2.1.0"
}
```

### 2. List StatefulSets

Check StatefulSets when you need to understand stateful applications like databases, message queues, or caches. These require special handling during migrations due to persistent storage.

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="StatefulSet",
  api_version="apps/v1"
)
```

**CLI:**
```bash
# List StatefulSets
kubectl get statefulsets -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    replicas: .spec.replicas,
    volumeClaimTemplates: [.spec.volumeClaimTemplates[]?.metadata.name]
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "redis-cluster",
  "replicas": 3,
  "volumeClaimTemplates": ["data"]
}
```

### 3. List DaemonSets

List DaemonSets to identify node-level agents (monitoring, logging, security). These run on every node and reveal operational tooling in use.

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="DaemonSet",
  api_version="apps/v1"
)
```

**CLI:**
```bash
# List DaemonSets
kubectl get daemonsets -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    desired: .status.desiredNumberScheduled,
    ready: .status.numberReady
  }'
```

**Example output:**
```json
{
  "namespace": "kube-system",
  "name": "aws-node",
  "desired": 5,
  "ready": 5
}
```

### 4. List CronJobs and Jobs

Check batch workloads to understand scheduled tasks (backups, reports) and one-time jobs. Important for understanding maintenance windows and resource usage patterns.

**CLI:**
```bash
# List CronJobs
kubectl get cronjobs -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    schedule: .spec.schedule,
    suspend: .spec.suspend,
    lastSchedule: .status.lastScheduleTime
  }'

# List active Jobs
kubectl get jobs -A --field-selector status.successful!=1 -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    active: .status.active,
    failed: .status.failed
  }'
```

**Example output (CronJob):**
```json
{
  "namespace": "production",
  "name": "db-backup",
  "schedule": "0 2 * * *",
  "suspend": false,
  "lastSchedule": "2026-04-22T02:00:00Z"
}
```

### 5. List Services

List Services to understand network exposure. Services reveal how applications communicate internally (ClusterIP) and externally (LoadBalancer, NodePort).

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Service",
  api_version="v1"
)
```

**CLI:**
```bash
# List services with types
kubectl get svc -A -o json | jq -r '
  .items[] |
  select(.metadata.namespace | startswith("kube-") | not) |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    type: .spec.type,
    ports: [.spec.ports[]? | "\(.port)/\(.protocol)"]
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "api-gateway",
  "type": "LoadBalancer",
  "ports": ["443/TCP", "80/TCP"]
}
```

### 6. List Ingresses

Check Ingresses to identify external access points and routing rules. Ingresses show domain mappings, TLS configuration, and which services are publicly accessible.

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Ingress",
  api_version="networking.k8s.io/v1"
)
```

**CLI:**
```bash
# List Ingresses
kubectl get ingress -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    class: .spec.ingressClassName,
    hosts: [.spec.rules[]?.host]
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "api-ingress",
  "class": "alb",
  "hosts": ["api.example.com", "api-internal.example.com"]
}
```

### 7. List HPAs

List Horizontal Pod Autoscalers to understand autoscaling configuration. HPAs reveal which workloads scale automatically and their scaling thresholds.

**CLI:**
```bash
# List HPAs with current metrics
kubectl get hpa -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    target: .spec.scaleTargetRef.name,
    minReplicas: .spec.minReplicas,
    maxReplicas: .spec.maxReplicas,
    currentReplicas: .status.currentReplicas,
    metrics: [.spec.metrics[]?.type]
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "api-gateway-hpa",
  "target": "api-gateway",
  "minReplicas": 2,
  "maxReplicas": 10,
  "currentReplicas": 4,
  "metrics": ["Resource", "External"]
}
```

---

## Generate Summary Statistics

Run this command to get a high-level view of workload distribution across namespaces. Use this for initial assessment before diving into details.

```bash
# Quick summary of workload counts by namespace
kubectl get deploy,statefulsets,daemonsets,jobs -A -o json | jq -r '
  .items |
  group_by(.metadata.namespace) |
  map({
    namespace: .[0].metadata.namespace,
    total: length,
    by_kind: group_by(.kind) | map({key: .[0].kind, value: length}) | from_entries
  })'
```

**Example output:**
```json
[
  {
    "namespace": "production",
    "total": 12,
    "by_kind": {"Deployment": 8, "StatefulSet": 2, "DaemonSet": 2}
  },
  {
    "namespace": "staging",
    "total": 6,
    "by_kind": {"Deployment": 5, "Job": 1}
  }
]
```

---

## Output Schema

```yaml
workloads:
  summary:
    total_deployments: int
    total_statefulsets: int
    total_daemonsets: int
    total_cronjobs: int
    total_services: int
    total_ingresses: int
    namespaces_with_workloads: int
    
  by_namespace:
    - namespace: string
      deployments: int
      statefulsets: int
      services: int
      ingresses: int
      
  deployments:
    - namespace: string
      name: string
      replicas: int
      ready_replicas: int
      image: string
      labels: object
      
  statefulsets:
    - namespace: string
      name: string
      replicas: int
      volume_claims: list
      storage_class: string
      
  services:
    - namespace: string
      name: string
      type: string          # ClusterIP | NodePort | LoadBalancer
      ports: list
      selector: object
      
  ingresses:
    - namespace: string
      name: string
      ingress_class: string
      hosts: list
      tls_enabled: bool
      
  hpas:
    - namespace: string
      name: string
      target: string
      min_replicas: int
      max_replicas: int
      current_replicas: int
      metrics: list
```

---

## Analyze Workload Patterns

Use these analysis commands to identify issues, assess health, and gather insights for migration planning or operational review.

### Check Workload Health

Run health checks when troubleshooting or before migrations. Identify pods not running and deployments not at desired replica count.

```bash
# Pods not in Running state
kubectl get pods -A --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name): \(.status.phase)"'

# Deployments not at desired replicas
kubectl get deploy -A -o json | jq -r '
  .items[] |
  select(.spec.replicas != .status.readyReplicas) |
  "\(.metadata.namespace)/\(.metadata.name): \(.status.readyReplicas)/\(.spec.replicas)"'
```

**Example output:**
```
production/api-gateway: 2/3
staging/worker: 0/2
```

### Audit Resource Requests and Limits

Check resource configuration before capacity planning or when investigating scheduling issues. Pods without requests can cause node resource contention.

```bash
# Pods without resource requests
kubectl get pods -A -o json | jq -r '
  .items[] |
  select(.spec.containers[].resources.requests == null) |
  "\(.metadata.namespace)/\(.metadata.name)"' | wc -l
```

**Example output:**
```
23
```

### Inventory Container Images

Run image inventory for security audits, registry migration planning, or identifying outdated versions. Understanding image sources helps with compliance and dependency management.

```bash
# Unique images across cluster
kubectl get pods -A -o json | jq -r '
  [.items[].spec.containers[].image] | unique | sort[]'

# Images by registry
kubectl get pods -A -o json | jq -r '
  [.items[].spec.containers[].image] |
  group_by(split("/")[0]) |
  map({registry: .[0] | split("/")[0], count: length})'
```

**Example output (images by registry):**
```json
[
  {"registry": "123456789012.dkr.ecr.us-west-2.amazonaws.com", "count": 15},
  {"registry": "docker.io", "count": 3},
  {"registry": "quay.io", "count": 2}
]
```

### Review PVC Usage

Check PVC status for storage health and capacity planning. Bound PVCs indicate active storage; Pending PVCs indicate provisioning issues.

```bash
# List PVCs with status
kubectl get pvc -A -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    status: .status.phase,
    storage_class: .spec.storageClassName,
    capacity: .status.capacity.storage
  }'
```

**Example output:**
```json
{
  "namespace": "production",
  "name": "redis-data-redis-0",
  "status": "Bound",
  "storage_class": "gp3",
  "capacity": "20Gi"
}
```

---

## Handle Edge Cases

### Exclude System Namespaces

Filter out system namespaces to focus on user workloads. Typically exclude:
- `kube-system`
- `kube-public`
- `kube-node-lease`
- `amazon-cloudwatch`
- `argocd` (unless specifically interested)

### Handle Large Clusters

For clusters with many workloads, avoid overwhelming output:
- Paginate results
- Focus on user namespaces
- Provide summary first, details on request

### Identify Orphaned Resources

Check for Services without matching pods to find potential cleanup opportunities or misconfiguration.

```bash
# Services without matching deployments
kubectl get svc -A -o json | jq -r '
  .items[] |
  select(.spec.selector != null and .spec.type != "ExternalName") |
  {namespace: .metadata.namespace, name: .metadata.name, selector: .spec.selector}'
```

---

## Apply Recommendations

Use these recommendations to guide follow-up actions based on your findings:

| Finding | Recommendation |
|---------|---------------|
| Deployments without HPA | Consider autoscaling for variable load |
| Pods without resource requests | Add requests for scheduler optimization |
| Many LoadBalancer services | Consider Ingress for consolidation |
| StatefulSets without PDBs | Add PDBs for upgrade safety |
| Old image versions | Consider image update policy |
