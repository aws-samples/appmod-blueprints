# Idle Resources

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Checks for zero-replica Deployments idle for extended periods, LoadBalancer Services with no healthy endpoints, namespaces with no running workloads but allocated quotas, orphaned ConfigMaps/Secrets not referenced by running workloads, and per-hour cost of unused load balancers

---

## Overview

Idle resources is a mid-weight dimension (15 points max deduction). It detects resources that are provisioned and potentially incurring cost but serving no active workload — forgotten deployments scaled to zero, load balancers with no backends, empty namespaces with quotas, and orphaned configuration objects.

Unlike compute efficiency (which identifies *under-utilized* resources), this dimension targets resources that are doing **nothing at all** — pure waste with zero productive value.

### Cost Reference: Unused Load Balancers

| Load Balancer Type | Hourly Cost (idle) | Monthly Cost (idle) |
|--------------------|-------------------|---------------------|
| Network Load Balancer (NLB) | ~$0.0225/hr | ~$16.43/month |
| Application Load Balancer (ALB) | ~$0.0225/hr | ~$16.43/month |
| Classic Load Balancer (CLB) | ~$0.025/hr | ~$18.25/month |

> Prices are US East (N. Virginia) baseline. Actual costs vary by region but the idle hourly rate applies even with zero traffic.

### Checks Summary

| # | Check | Default Threshold | Severity Logic |
|---|-------|-------------------|----------------|
| 1 | Zero-replica Deployments idle for extended periods | 0 replicas for > 7 days | By count × resource allocation |
| 2 | LoadBalancer Services with no healthy endpoints | 0 healthy endpoints | **HIGH** (Req 10.5) — per LB hourly cost |
| 3 | Namespaces with no running workloads but allocated quotas | 0 running pods + active quota | MEDIUM |
| 4 | Orphaned ConfigMaps/Secrets not referenced by running workloads | Not mounted/envFrom by any running pod | LOW–MEDIUM by count |

---

## Pre-requisites

These checks require:
- **kubectl access** to the cluster (for Deployments, Services, Endpoints, Namespaces, ConfigMaps, Secrets)
- **AWS CLI access** for `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetHealth` (optional — enriches LB cost data)
- **No metrics-server required** — all checks use Kubernetes API state inspection only

---

## Check 1: Zero-Replica Deployments Idle for Extended Periods

### What it detects

Deployments that have been scaled to zero replicas and appear to have been in this state for an extended period (> 7 days). These represent forgotten or abandoned workloads that may still have associated resources (PVCs, ConfigMaps, Secrets, ServiceAccounts) consuming cluster overhead.

### Data collection

**Via kubectl:**

```bash
# Find all Deployments with 0 replicas in non-system namespaces
kubectl get deployments --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.spec.replicas == 0) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      replicas: .spec.replicas,
      last_updated: (.metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"] // "unknown"),
      generation: .metadata.generation,
      conditions: [.status.conditions[]? | {type: .type, lastTransitionTime: .lastTransitionTime}]
    }'
```

```bash
# Check when the Deployment was last scaled (using events or annotations)
kubectl get events --all-namespaces --field-selector reason=ScalingReplicaSet \
  --sort-by='.lastTimestamp' -o json | \
  jq -r '
    .items[] |
    select(.involvedObject.kind == "Deployment") |
    select(.message | contains("Scaled down replica set") and contains(" to 0")) |
    "\(.involvedObject.namespace)/\(.involvedObject.name) scaled-to-zero at \(.lastTimestamp)"
  ' | tail -50
```

```bash
# Alternative: check last transition time on Available condition
kubectl get deployments --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.spec.replicas == 0) |
    . as $dep |
    ($dep.status.conditions[]? | select(.type == "Available")) as $cond |
    "\($dep.metadata.namespace)/\($dep.metadata.name) | lastTransition=\($cond.lastTransitionTime // "unknown")"
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
# Filter results for spec.replicas == 0
# Check status.conditions[].lastTransitionTime for idle duration
```

### Analysis logic

```
For each Deployment in non-system namespaces:
  If spec.replicas == 0:
    idle_since = status.conditions["Available"].lastTransitionTime
    idle_days = (now - idle_since).days

    If idle_days > 7:
      → Generate finding
      
    # Estimate residual cost (associated resources still consuming)
    associated_pvcs = count PVCs referenced by the Deployment's pod template
    associated_secrets = count Secrets referenced by the Deployment's pod template
    residual_monthly_cost = sum(pvc_costs) + quota_overhead
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Zero-replica Deployment idle > 30 days with associated PVCs | HIGH |
| Zero-replica Deployment idle > 30 days, no PVCs | MEDIUM |
| Zero-replica Deployment idle 7–30 days | LOW |
| Multiple (5+) zero-replica Deployments in same namespace | MEDIUM (governance gap) |

### Remediation

```bash
# Review and delete abandoned Deployments
kubectl delete deployment <name> -n <namespace>

# Or scale back up if it should be running
kubectl scale deployment <name> -n <namespace> --replicas=1

# List all associated resources before cleanup
kubectl get all,pvc,configmap,secret -n <namespace> -l app=<deployment-label>
```

```bash
# Bulk identification: list all zero-replica deploys older than 30 days
kubectl get deployments --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.spec.replicas == 0) |
    select(.status.conditions[]? | 
      select(.type == "Available") |
      (.lastTransitionTime | fromdateiso8601) < (now - 2592000)) |
    "\(.metadata.namespace)/\(.metadata.name)"
  '
```

---

## Check 2: LoadBalancer Services with No Healthy Endpoints

### What it detects

Kubernetes Services of type `LoadBalancer` that have no healthy backend endpoints. These services provision AWS load balancers (NLB or ALB) that incur hourly charges (~$0.0225/hr for NLB, ~$0.0225/hr for ALB) even with zero traffic and no healthy targets.

> **Severity: HIGH** (per Requirement 10.5) — Each idle load balancer costs ~$16.43/month minimum regardless of traffic.

### Data collection

**Via kubectl:**

```bash
# Find all LoadBalancer Services
kubectl get services --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.spec.type == "LoadBalancer") |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      lb_type: (if .metadata.annotations["service.beta.kubernetes.io/aws-load-balancer-type"] == "nlb" 
                or .metadata.annotations["service.beta.kubernetes.io/aws-load-balancer-type"] == "external"
                then "NLB" else "CLB/ALB" end),
      external_ip: (.status.loadBalancer.ingress[0].hostname // "pending"),
      selector: .spec.selector
    }'
```

```bash
# Check endpoints health for each LoadBalancer Service
kubectl get endpoints --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.subsets == null or .subsets == [] or 
           (.subsets[]?.addresses == null or .subsets[]?.addresses == [])) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      ready_addresses: 0,
      not_ready: ([.subsets[]?.notReadyAddresses[]?] | length)
    }'
```

```bash
# Combined: LoadBalancer Services with zero healthy endpoints
kubectl get services --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.spec.type == "LoadBalancer") |
    .metadata.namespace as $ns |
    .metadata.name as $name |
    "\($ns)/\($name)"
  ' | while read svc; do
    ns=$(echo "$svc" | cut -d'/' -f1)
    name=$(echo "$svc" | cut -d'/' -f2)
    ready=$(kubectl get endpoints "$name" -n "$ns" -o json 2>/dev/null | \
      jq '[.subsets[]?.addresses[]?] | length')
    if [ "${ready:-0}" -eq 0 ]; then
      echo "IDLE_LB: $svc (0 healthy endpoints)"
    fi
  done
```

**Via AWS CLI (enriches with actual LB details):**

```bash
# List ELBv2 load balancers and check target group health
aws elbv2 describe-load-balancers --query 'LoadBalancers[*].{
  Name:LoadBalancerName,
  ARN:LoadBalancerArn,
  Type:Type,
  State:State.Code,
  DNSName:DNSName
}' --output table

# For each LB, check target group health
aws elbv2 describe-target-groups \
  --load-balancer-arn <lb-arn> \
  --query 'TargetGroups[*].TargetGroupArn' --output text | \
  while read tg_arn; do
    echo "Target Group: $tg_arn"
    aws elbv2 describe-target-health \
      --target-group-arn "$tg_arn" \
      --query 'TargetHealthDescriptions[*].{Target:Target.Id,Health:TargetHealth.State}'
  done
```

```bash
# List Classic Load Balancers and check instance health
aws elb describe-load-balancers --query 'LoadBalancerDescriptions[*].{
  Name:LoadBalancerName,
  Instances:Instances[*].InstanceId
}' --output json | \
  jq '.[] | select(.Instances == null or (.Instances | length) == 0) | .Name'
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Service",
  api_version="v1",
  namespace="all"
)
# Filter for spec.type == "LoadBalancer"
# Then check endpoints for each:

list_k8s_resources(
  cluster_name="<cluster>",
  kind="Endpoints",
  api_version="v1",
  namespace="<namespace>"
)
# Check subsets[].addresses length for each matching endpoint
```

### Analysis logic

```
For each Service with spec.type == "LoadBalancer":
  endpoints = get Endpoints object with same name/namespace
  healthy_count = count(endpoints.subsets[].addresses[])

  If healthy_count == 0:
    # Determine LB type from annotations
    lb_type = annotations["service.beta.kubernetes.io/aws-load-balancer-type"]
    
    If lb_type in ["nlb", "external", "nlb-ip"]:
      hourly_cost = 0.0225  # NLB idle cost
    Else if lb_type == "alb" or ingress-controller managed:
      hourly_cost = 0.0225  # ALB idle cost
    Else:
      hourly_cost = 0.025   # CLB idle cost (legacy)
    
    monthly_cost = hourly_cost × 730
    → Generate HIGH severity finding (per Req 10.5)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Any LoadBalancer Service with 0 healthy endpoints | **HIGH** |
| Multiple idle LoadBalancers (3+) | **HIGH** (compounding waste) |

> Per Requirement 10.5: Idle LoadBalancer Services always generate HIGH severity findings because they represent direct, ongoing AWS billing with zero value.

### Per-hour cost breakdown

| LB Type | Hourly Idle Cost | Monthly Idle Cost | Annual Idle Cost |
|---------|-----------------|-------------------|------------------|
| NLB | ~$0.0225/hr | ~$16.43/month | ~$197.10/year |
| ALB | ~$0.0225/hr | ~$16.43/month | ~$197.10/year |
| CLB | ~$0.025/hr | ~$18.25/month | ~$219.00/year |

> These are base charges. LCU/NLCU charges are zero when there is no traffic, but the hourly fee applies regardless.

### Remediation

```bash
# Delete the idle LoadBalancer Service (removes AWS LB)
kubectl delete service <name> -n <namespace>

# Or switch to ClusterIP if the LB is no longer needed externally
kubectl patch service <name> -n <namespace> -p '{"spec": {"type": "ClusterIP"}}'

# Verify the AWS LB was actually deleted after Service removal
aws elbv2 describe-load-balancers --query 'LoadBalancers[*].LoadBalancerName'
```

```bash
# If the Service should have backends, check why pods are unhealthy
kubectl get pods -n <namespace> -l <service-selector-labels>
kubectl describe endpoints <service-name> -n <namespace>
```

---

## Check 3: Namespaces with No Running Workloads but Allocated Quotas

### What it detects

Namespaces that have ResourceQuotas or LimitRanges defined but contain no running pods. This indicates abandoned environments that still reserve cluster capacity through quotas or create governance overhead.

### Data collection

**Via kubectl:**

```bash
# Find namespaces with ResourceQuotas
kubectl get resourcequotas --all-namespaces -o json | \
  jq -r '.items[] | "\(.metadata.namespace)"' | sort -u
```

```bash
# Find namespaces with zero running pods
kubectl get pods --all-namespaces --field-selector=status.phase=Running -o json | \
  jq -r '[.items[].metadata.namespace] | unique[]' > /tmp/active_namespaces.txt

kubectl get namespaces -o json | \
  jq -r '.items[].metadata.name' | \
  grep -v -F -f /tmp/active_namespaces.txt | \
  grep -v -E "^(kube-|amazon-|aws-|default$)"
```

```bash
# Combined: namespaces with quotas but no running workloads
kubectl get namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("^kube-|^amazon-|^aws-|^default$") | not) |
    .metadata.name
  ' | while read ns; do
    pod_count=$(kubectl get pods -n "$ns" --field-selector=status.phase=Running \
      --no-headers 2>/dev/null | wc -l)
    quota_count=$(kubectl get resourcequotas -n "$ns" --no-headers 2>/dev/null | wc -l)
    limitrange_count=$(kubectl get limitranges -n "$ns" --no-headers 2>/dev/null | wc -l)
    
    if [ "$pod_count" -eq 0 ] && [ "$((quota_count + limitrange_count))" -gt 0 ]; then
      echo "EMPTY_NS_WITH_QUOTA: $ns (quotas=$quota_count, limitranges=$limitrange_count, running_pods=0)"
    fi
  done
```

```bash
# Get quota details for empty namespaces (shows reserved capacity)
kubectl get resourcequotas -n <namespace> -o json | \
  jq '.items[] | {
    name: .metadata.name,
    hard: .spec.hard,
    used: .status.used
  }'
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Namespace",
  api_version="v1"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="ResourceQuota",
  api_version="v1",
  namespace="<namespace>"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="Pod",
  api_version="v1",
  namespace="<namespace>"
)
# Check for running pods; if zero, flag namespace with quotas
```

### Analysis logic

```
For each non-system namespace:
  running_pods = count pods with status.phase == "Running"
  has_quota = (ResourceQuotas exist in namespace)
  has_limitrange = (LimitRanges exist in namespace)

  If running_pods == 0 AND (has_quota OR has_limitrange):
    # Calculate reserved capacity from quota spec
    reserved_cpu = quota.spec.hard["requests.cpu"]
    reserved_mem = quota.spec.hard["requests.memory"]
    
    → Generate finding
    # Note: quotas don't directly consume resources, but indicate 
    # governance overhead and often mean the namespace was intended for workloads
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Empty namespace with quota + no pods for > 30 days | MEDIUM |
| Empty namespace with quota + associated PVCs still bound | HIGH |
| Empty namespace with quota only (no PVCs) | LOW–MEDIUM |
| Multiple (3+) empty namespaces with quotas | MEDIUM (governance gap) |

### Remediation

```bash
# Review and delete empty namespaces (CAUTION: deletes all resources in namespace)
kubectl delete namespace <namespace>

# Or remove just the quota if the namespace may be reused
kubectl delete resourcequota <quota-name> -n <namespace>
kubectl delete limitrange <limitrange-name> -n <namespace>

# Before deleting, check for any non-running resources (PVCs, Secrets, etc.)
kubectl get all,pvc,configmap,secret,serviceaccount -n <namespace>
```

---

## Check 4: Orphaned ConfigMaps and Secrets Not Referenced by Running Workloads

### What it detects

ConfigMaps and Secrets that exist in non-system namespaces but are not referenced by any running pod — either as volume mounts, environment variable sources (envFrom/valueFrom), or projected volumes. These represent configuration debt and potential security exposure (orphaned secrets).

### Data collection

**Via kubectl:**

```bash
# Step 1: Get all ConfigMaps/Secrets referenced by running pods
kubectl get pods --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.status.phase == "Running") |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    .metadata.namespace as $ns |
    (
      # Volume mounts (configMap and secret)
      ([.spec.volumes[]? | 
        select(.configMap) | "\($ns)/configmap/\(.configMap.name)"] +
       [.spec.volumes[]? | 
        select(.secret) | "\($ns)/secret/\(.secret.secretName)"] +
       [.spec.volumes[]? | 
        select(.projected) | .projected.sources[]? |
        (if .configMap then "\($ns)/configmap/\(.configMap.name)"
         elif .secret then "\($ns)/secret/\(.secret.name)"
         else empty end)] +
      # EnvFrom references
       [.spec.containers[]?.envFrom[]? |
        (if .configMapRef then "\($ns)/configmap/\(.configMapRef.name)"
         elif .secretRef then "\($ns)/secret/\(.secretRef.name)"
         else empty end)] +
      # Individual env valueFrom references
       [.spec.containers[]?.env[]?.valueFrom? |
        (if .configMapKeyRef then "\($ns)/configmap/\(.configMapKeyRef.name)"
         elif .secretKeyRef then "\($ns)/secret/\(.secretKeyRef.name)"
         else empty end)]
    )[]
  ' | sort -u > /tmp/referenced_configs.txt
```

```bash
# Step 2: Get all ConfigMaps in non-system namespaces (excluding system ones)
kubectl get configmaps --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.metadata.name | test("^kube-root-ca") | not) |
    "\(.metadata.namespace)/configmap/\(.metadata.name)"
  ' | sort > /tmp/all_configmaps.txt

# Step 3: Get all Secrets in non-system namespaces (excluding service account tokens)
kubectl get secrets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.type != "kubernetes.io/service-account-token") |
    select(.metadata.name | test("^default-token-") | not) |
    "\(.metadata.namespace)/secret/\(.metadata.name)"
  ' | sort > /tmp/all_secrets.txt
```

```bash
# Step 4: Find orphaned ConfigMaps (not referenced by any running pod)
comm -23 /tmp/all_configmaps.txt /tmp/referenced_configs.txt

# Step 5: Find orphaned Secrets (not referenced by any running pod)
comm -23 /tmp/all_secrets.txt /tmp/referenced_configs.txt
```

```bash
# Simplified single-command approach (summary by namespace)
kubectl get pods --all-namespaces -o json | \
  jq -r '
    [.items[] |
     select(.status.phase == "Running") |
     select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
     .metadata.namespace as $ns |
     (
       [.spec.volumes[]?.configMap?.name // empty] +
       [.spec.volumes[]?.secret?.secretName // empty] +
       [.spec.containers[]?.envFrom[]?.configMapRef?.name // empty] +
       [.spec.containers[]?.envFrom[]?.secretRef?.name // empty] +
       [.spec.containers[]?.env[]?.valueFrom?.configMapKeyRef?.name // empty] +
       [.spec.containers[]?.env[]?.valueFrom?.secretKeyRef?.name // empty]
     )[] | {ns: $ns, ref: .}
    ] | group_by(.ns) | map({namespace: .[0].ns, referenced: [.[].ref] | unique})
  '
```

**Via EKS MCP Server:**

```
# Get all pods to build reference map
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Pod",
  api_version="v1",
  namespace="all"
)
# Parse spec.volumes, spec.containers[].envFrom, spec.containers[].env[].valueFrom
# to build set of referenced ConfigMaps and Secrets

# Get all ConfigMaps
list_k8s_resources(
  cluster_name="<cluster>",
  kind="ConfigMap",
  api_version="v1",
  namespace="<namespace>"
)

# Get all Secrets
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Secret",
  api_version="v1",
  namespace="<namespace>"
)
# Diff: all - referenced = orphaned
```

### Exclusions

Always exclude from orphan detection:
- ConfigMaps named `kube-root-ca.crt` (system-managed)
- Secrets of type `kubernetes.io/service-account-token` (auto-created)
- Secrets matching `^default-token-` pattern (legacy SA tokens)
- ConfigMaps/Secrets in system namespaces (`kube-*`, `amazon-*`, `aws-*`)
- Helm release secrets (type `helm.sh/release.v1`) — these track Helm state
- ConfigMaps with label `app.kubernetes.io/managed-by: Helm` that match a deployed release

### Analysis logic

```
For each non-system namespace:
  referenced_cms = set of ConfigMap names used by running pods (volumes, envFrom, valueFrom)
  referenced_secrets = set of Secret names used by running pods (volumes, envFrom, valueFrom)
  
  all_cms = set of all ConfigMaps in namespace (excluding system CMs)
  all_secrets = set of all Secrets in namespace (excluding SA tokens, Helm releases)
  
  orphaned_cms = all_cms - referenced_cms
  orphaned_secrets = all_secrets - referenced_secrets
  
  If len(orphaned_cms) + len(orphaned_secrets) > 0:
    → Generate finding
    # Secrets carry more risk (potential credential exposure)
    # ConfigMaps are lower risk (just configuration debt)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| > 10 orphaned Secrets in a namespace | MEDIUM |
| Orphaned Secrets (any count) | LOW |
| > 20 orphaned ConfigMaps in a namespace | MEDIUM |
| Orphaned ConfigMaps (any count) | LOW |
| Total orphaned objects across cluster > 50 | MEDIUM (cluster hygiene) |

> Note: Orphaned ConfigMaps/Secrets have minimal direct cost impact but indicate configuration debt, potential security exposure (stale credentials in Secrets), and complicate cluster operations.

### Remediation

```bash
# Review orphaned ConfigMaps before deleting
kubectl get configmap <name> -n <namespace> -o yaml

# Delete confirmed orphaned ConfigMaps
kubectl delete configmap <name> -n <namespace>

# Delete confirmed orphaned Secrets (review first!)
kubectl get secret <name> -n <namespace> -o yaml | head -20  # Check type and annotations
kubectl delete secret <name> -n <namespace>
```

```bash
# Bulk cleanup: delete all orphaned ConfigMaps in a namespace (use with caution)
# First generate the list, review it, then delete
comm -23 /tmp/all_configmaps.txt /tmp/referenced_configs.txt | \
  grep "^<namespace>/" | \
  sed 's|.*/configmap/||' | \
  xargs -I{} kubectl delete configmap {} -n <namespace> --dry-run=client

# Remove --dry-run=client after confirming the list is correct
```

---

## Scoring Contribution

The idle resources dimension has a **maximum deduction of 15 points**.

### Deduction calculation

```
deduction = 0

For each finding in this dimension:
  If severity == CRITICAL: deduction += 15 × 0.6 = 9.0
  If severity == HIGH:     deduction += 15 × 0.3 = 4.5
  If severity == MEDIUM:   deduction += 15 × 0.15 = 2.25
  If severity == LOW:      deduction += 15 × 0.05 = 0.75

actual_deduction = min(deduction, 15)  # Cap at maximum
```

### Dimension status

| Condition | Status |
|-----------|--------|
| All checks completed | ASSESSED |
| Some checks partially completed | ASSESSED (with note) |
| No Kubernetes API access | Cannot assess — skill halts at pre-flight |

This dimension is never SKIPPED because all checks require only the Kubernetes API (no metrics sources needed).

---

## Decision Tree

```
START
  │
  ├─ Check 1: Zero-replica Deployments
  │   ├─ List all Deployments with spec.replicas == 0
  │   ├─ Check idle duration via status.conditions[].lastTransitionTime
  │   ├─ If idle > 7 days → Generate finding (severity by duration + PVCs)
  │   └─ Check for associated PVCs still bound
  │
  ├─ Check 2: Idle LoadBalancer Services
  │   ├─ List all Services with spec.type == "LoadBalancer"
  │   ├─ For each, check Endpoints object for healthy addresses
  │   ├─ If 0 healthy endpoints → Generate HIGH severity finding
  │   ├─ Calculate per-hour cost: NLB ~$0.0225/hr, ALB ~$0.0225/hr
  │   └─ Optionally verify via AWS ELBv2 API for target group health
  │
  ├─ Check 3: Empty Namespaces with Quotas
  │   ├─ List namespaces with ResourceQuotas or LimitRanges
  │   ├─ For each, count running pods
  │   ├─ If 0 running pods + quota exists → Generate finding
  │   └─ Check for bound PVCs in empty namespace (escalates severity)
  │
  ├─ Check 4: Orphaned ConfigMaps/Secrets
  │   ├─ Build reference map from all running pods
  │   ├─ List all ConfigMaps/Secrets (excluding system objects)
  │   ├─ Diff: all - referenced = orphaned
  │   ├─ Exclude Helm releases, SA tokens, system CMs
  │   └─ Generate finding if orphan count exceeds threshold
  │
  └─ Aggregate findings → Calculate dimension deduction (max 15 pts)
```

---

## Examples

### Example Finding: Idle Load Balancer

```yaml
finding:
  id: "idle-lb-staging-api-gateway"
  dimension: "idle"
  severity: "HIGH"
  affected_resource: "staging/api-gateway (Service type=LoadBalancer)"
  current_state: "NLB provisioned with 0 healthy endpoints for 14 days"
  monthly_cost: 16.43
  monthly_waste: 16.43
  monthly_savings: 16.43
  effort: "Low"
  fix_summary: "Delete unused LoadBalancer Service or fix backend pods"
  remediation: "kubectl delete service api-gateway -n staging"
  confidence: "high"
  data_sources: ["kubernetes_api", "aws_elb_api"]
```

### Example Finding: Zero-Replica Deployment

```yaml
finding:
  id: "idle-deploy-dev-old-backend"
  dimension: "idle"
  severity: "MEDIUM"
  affected_resource: "dev/old-backend (Deployment, 0 replicas since 2024-08-15)"
  current_state: "Scaled to 0 replicas for 45 days, 2 PVCs still bound (50Gi total)"
  monthly_cost: 5.00
  monthly_waste: 5.00
  monthly_savings: 5.00
  effort: "Low"
  fix_summary: "Delete abandoned deployment and associated PVCs"
  remediation: "kubectl delete deployment old-backend -n dev && kubectl delete pvc old-backend-data-0 old-backend-data-1 -n dev"
  confidence: "medium"
  data_sources: ["kubernetes_api"]
```

### Example Finding: Orphaned Secrets

```yaml
finding:
  id: "idle-orphaned-secrets-production"
  dimension: "idle"
  severity: "LOW"
  affected_resource: "production namespace (8 orphaned Secrets)"
  current_state: "8 Secrets not referenced by any running pod"
  monthly_cost: 0
  monthly_waste: 0
  monthly_savings: 0
  effort: "Low"
  fix_summary: "Review and delete orphaned Secrets to reduce configuration debt"
  remediation: "Review each Secret and delete if no longer needed"
  confidence: "medium"
  data_sources: ["kubernetes_api"]
```
