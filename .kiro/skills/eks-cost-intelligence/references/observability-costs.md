# Observability Costs

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Checks for EKS control plane logging configuration (all log types enabled unnecessarily), high-cardinality metric sources (Prometheus scrape configs, CloudWatch agent), DEBUG/TRACE log levels in production, and log filtering/sampling configurations (FluentBit, CloudWatch agent)

---

## Overview

Observability costs is a lower-weight dimension (10 points max deduction). It evaluates whether the cluster's logging, metrics, and tracing configurations are cost-efficient or generating unnecessary expense through excessive log ingestion, high-cardinality metrics, or verbose log levels in production.

CloudWatch Logs ingestion is one of the most common hidden costs in EKS clusters. A single cluster with all five control plane log types enabled can ingest 10–50 GB/month of logs at $0.50/GB (based on field experience; actual volume depends on cluster size and API activity) — often without anyone actively using them. Similarly, verbose application logging at DEBUG/TRACE levels or unfiltered Prometheus scrapes can generate hundreds of dollars in monthly charges.

### Checks Summary

| # | Check | Default Threshold | Severity Logic |
|---|-------|-------------------|----------------|
| 1 | EKS control plane logging (all log types) | All 5 types enabled in non-prod | By estimated CW Logs cost |
| 2 | High-cardinality metric sources | Prometheus scrape configs, CW agent | By metric count × cost |
| 3 | DEBUG/TRACE log levels in production | Any DEBUG/TRACE in prod namespaces | MEDIUM per workload |
| 4 | Log filtering/sampling configurations | Missing FluentBit filters or CW agent sampling | MEDIUM–HIGH |

---

## Pre-requisites

These checks require:
- **kubectl access** to the cluster (for ConfigMaps, DaemonSets, Deployments)
- **AWS CLI access** for `eks:DescribeCluster` (control plane logging config), `logs:DescribeLogGroups` (log group sizing)
- **Optional:** CloudWatch metrics for log ingestion volume (improves cost estimates)

No metrics-server is required — checks use configuration inspection and AWS API queries.

---

## Check 1: EKS Control Plane Logging Configuration

### What it detects

EKS clusters with all five control plane log types enabled when not all are necessary. Each enabled log type generates CloudWatch Logs ingestion at $0.50/GB. Many clusters enable all log types "just in case" — especially in non-production environments where audit and authenticator logs provide little operational value.

### Background

EKS control plane log types:
| Log Type | Typical Volume | Use Case |
|----------|---------------|----------|
| `api` | HIGH (5–20 GB/month) | API server request logging — audit trail |
| `audit` | HIGH (10–50 GB/month) | Detailed audit of all API operations |
| `authenticator` | LOW (0.5–2 GB/month) | Authentication decisions |
| `controllerManager` | MEDIUM (1–5 GB/month) | Controller reconciliation activity |
| `scheduler` | LOW (0.5–2 GB/month) | Pod scheduling decisions |

**Cost reference:** CloudWatch Logs ingestion = $0.50/GB. A cluster with all 5 types enabled can cost $10–$40/month in log ingestion alone. At scale (many clusters), this compounds to hundreds of dollars.

### Data collection

**Via AWS CLI:**

```bash
# Get control plane logging configuration
aws eks describe-cluster \
  --name <cluster> \
  --query 'cluster.logging.clusterLogging[?enabled==`true`].types[]' \
  --output json

# Example output: ["api", "audit", "authenticator", "controllerManager", "scheduler"]
```

```bash
# Get the log group size to estimate actual ingestion cost
CLUSTER_NAME="<cluster>"
REGION="<region>"

# Control plane log groups follow this pattern
LOG_GROUPS=(
  "/aws/eks/${CLUSTER_NAME}/cluster"
)

for LG in "${LOG_GROUPS[@]}"; do
  echo "=== $LG ==="
  
  # Get stored bytes (approximate ingestion over retention period)
  aws logs describe-log-groups \
    --log-group-name-prefix "$LG" \
    --query 'logGroups[].{Name:logGroupName,StoredBytes:storedBytes,RetentionDays:retentionInDays}' \
    --output table
  
  # Get incoming bytes over last 7 days for cost estimation
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/Logs" \
    --metric-name "IncomingBytes" \
    --dimensions "Name=LogGroupName,Value=$LG" \
    --start-time "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 604800 \
    --statistics Sum \
    --region "$REGION"
done
```

```bash
# Estimate monthly ingestion cost
# Get 7-day ingestion and extrapolate to 30 days
SEVEN_DAY_BYTES=$(aws cloudwatch get-metric-statistics \
  --namespace "AWS/Logs" \
  --metric-name "IncomingBytes" \
  --dimensions "Name=LogGroupName,Value=/aws/eks/${CLUSTER_NAME}/cluster" \
  --start-time "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --period 604800 \
  --statistics Sum \
  --query 'Datapoints[0].Sum' \
  --output text \
  --region "$REGION")

# Convert to monthly GB and estimate cost
MONTHLY_GB=$(echo "scale=2; ($SEVEN_DAY_BYTES / 1073741824) * (30/7)" | bc)
MONTHLY_COST=$(echo "scale=2; $MONTHLY_GB * 0.50" | bc)
echo "Estimated monthly control plane log ingestion: ${MONTHLY_GB} GB = \$${MONTHLY_COST}"
```

**Via EKS MCP Server:**

```
get_eks_cluster(cluster_name="<cluster>")
# Extract cluster.logging.clusterLogging[].types and enabled status

get_cloudwatch_metrics(
  cluster_name="<cluster>",
  metric_name="IncomingBytes",
  namespace="AWS/Logs",
  dimensions={"LogGroupName": "/aws/eks/<cluster>/cluster"},
  period=604800,
  stat="Sum"
)
```

### Analysis logic

```
enabled_log_types = list of enabled control plane log types

If len(enabled_log_types) == 5:  # All types enabled
  # Check if this is a production or non-production cluster
  # Indicators: cluster name contains "prod", tags contain "environment=production"
  
  cluster_tags = get cluster tags
  is_production = ("prod" in cluster_name) OR (tags["environment"] in ["production", "prod"])
  
  If NOT is_production:
    → Finding: all 5 log types enabled in non-production cluster
    recommendation = "Disable audit and authenticator logs in non-prod; keep api + controllerManager"
    severity = by estimated monthly cost
  
  If is_production:
    # In production, all types may be justified — check if audit logs are high volume
    If monthly_audit_ingestion_gb > 20:
      → Finding: high-volume audit logging — consider retention reduction or filtering
      recommendation = "Reduce audit log retention to 7 days or apply CloudWatch subscription filter"
      severity = by estimated monthly cost
    Else:
      → No finding (production with all types is a valid security posture)

If len(enabled_log_types) >= 3 AND len(enabled_log_types) < 5:
  # Partial enablement — check if audit is enabled without being used
  # No finding unless cost is significant (> $50/month)
  If monthly_ingestion_cost > 50:
    → Finding: consider whether all enabled types are actively monitored
    severity = MEDIUM

If len(enabled_log_types) == 0:
  # No logging at all — this is a security concern, not a cost concern
  # Note: NOT a cost finding. This is an operational risk captured by eks-operation-review.
  → No finding for cost dimension (skip)

# Check retention settings
log_retention = describe log group retention
If log_retention == "Never expire" AND monthly_ingestion_gb > 5:
  → Finding: unlimited retention on high-volume log group
  recommendation = "Set retention to 30-90 days for control plane logs"
  severity = by projected storage growth cost
```

### Cost estimation

```
CloudWatch Logs pricing (us-east-1 reference):
  Ingestion:  $0.50/GB
  Storage:    $0.03/GB/month
  Analysis:   $0.0065/GB scanned (Logs Insights queries)

Monthly control plane log cost estimate:
  ingestion_cost = monthly_ingestion_gb × $0.50
  storage_cost   = stored_gb × $0.03
  total_monthly  = ingestion_cost + storage_cost

Savings from disabling unnecessary log types:
  If all 5 types enabled and 2 disabled (audit + authenticator in non-prod):
    typical_savings = 60-70% of total ingestion (audit is highest volume)
```

### Severity classification

| Estimated Monthly Waste | Severity |
|-------------------------|----------|
| > $500 (rare for single cluster, possible with audit) | CRITICAL |
| $200–$500 | HIGH |
| $50–$200 | MEDIUM |
| < $50 | LOW |

### Remediation

```bash
# Disable unnecessary control plane log types (e.g., keep only api + controllerManager)
aws eks update-cluster-config \
  --name <cluster> \
  --logging '{
    "clusterLogging": [
      {
        "types": ["api", "controllerManager"],
        "enabled": true
      },
      {
        "types": ["audit", "authenticator", "scheduler"],
        "enabled": false
      }
    ]
  }'
```

```bash
# Set retention on control plane log group (default is Never Expire)
aws logs put-retention-policy \
  --log-group-name "/aws/eks/<cluster>/cluster" \
  --retention-in-days 30
```

```hcl
# Terraform — configure selective logging
resource "aws_eks_cluster" "main" {
  name = var.cluster_name
  # ...

  enabled_cluster_log_types = ["api", "controllerManager"]
  # Omit: "audit", "authenticator", "scheduler" in non-prod
}

# Set retention via aws_cloudwatch_log_group
resource "aws_cloudwatch_log_group" "eks_control_plane" {
  name              = "/aws/eks/${var.cluster_name}/cluster"
  retention_in_days = 30
}
```

---

## Check 2: High-Cardinality Metric Sources

### What it detects

Prometheus scrape configurations or CloudWatch agent settings that generate excessive metric cardinality, leading to high storage and query costs. High-cardinality metrics are the #1 cost driver for managed Prometheus (AMP) and CloudWatch custom metrics.

### Background

Common high-cardinality sources in EKS:
| Source | Cardinality Risk | Monthly Cost Impact |
|--------|-----------------|---------------------|
| Prometheus with all default scrapers | HIGH — can generate 500K+ active series | $200–$1000+ (AMP) |
| Unfiltered kube-state-metrics | MEDIUM — labels on every resource | $50–$200 |
| CW agent collecting all container metrics | MEDIUM — per-container per-metric | $50–$300 |
| Custom application metrics without aggregation | HIGH — per-user/per-request dimensions | Variable |
| ADOT collector with unfiltered spans | HIGH — per-trace storage | $100–$500+ |

**Cost reference:**
- Amazon Managed Prometheus (AMP): $0.003/million samples ingested + $0.03/GB storage
- CloudWatch custom metrics: $0.30/metric/month (first 10K), $0.10/metric (next 240K)
- CloudWatch Logs (metric filter sources): $0.50/GB ingested

### Data collection

**Check Prometheus/AMP scrape configs:**

```bash
# Find Prometheus-related ConfigMaps (scrape configs)
kubectl get configmaps --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(
      .metadata.name | test("prometheus|prom-|monitoring") 
    ) |
    select(.data != null) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      keys: (.data | keys)
    } |
    "\(.namespace)/\(.name) keys=\(.keys | join(","))"
  '

# Get Prometheus scrape config content
kubectl get configmap -n <monitoring-namespace> <prometheus-config> -o yaml

# Count active scrape targets (if Prometheus is accessible)
kubectl exec -n <monitoring-namespace> <prometheus-pod> -- \
  wget -qO- http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets | length'
```

```bash
# Check for ServiceMonitors and PodMonitors (Prometheus Operator pattern)
kubectl get servicemonitors --all-namespaces -o json | \
  jq -r '
    .items[] | {
      namespace: .metadata.namespace,
      name: .metadata.name,
      endpoints: (.spec.endpoints | length),
      interval: (.spec.endpoints[0].interval // "30s"),
      has_metric_relabeling: (.spec.endpoints[0].metricRelabelings != null)
    } |
    "\(.namespace)/\(.name) endpoints=\(.endpoints) interval=\(.interval) filtered=\(.has_metric_relabeling)"
  '

kubectl get podmonitors --all-namespaces -o json | \
  jq -r '
    .items[] | {
      namespace: .metadata.namespace,
      name: .metadata.name,
      endpoints: (.spec.podMetricsEndpoints | length),
      interval: (.spec.podMetricsEndpoints[0].interval // "30s"),
      has_metric_relabeling: (.spec.podMetricsEndpoints[0].metricRelabelings != null)
    } |
    "\(.namespace)/\(.name) endpoints=\(.endpoints) interval=\(.interval) filtered=\(.has_metric_relabeling)"
  '
```

**Check CloudWatch agent configuration:**

```bash
# Find CloudWatch agent ConfigMap
kubectl get configmap -n amazon-cloudwatch -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("cloudwatch|cwagent")) |
    "\(.metadata.namespace)/\(.metadata.name)"
  '

# Get CloudWatch agent configuration detail
kubectl get configmap -n amazon-cloudwatch cloudwatch-agent-config -o yaml 2>/dev/null || \
kubectl get configmap -n amazon-cloudwatch cwagent-config -o yaml 2>/dev/null
```

```bash
# Check for ADOT (AWS Distro for OpenTelemetry) collector configs
kubectl get opentelemetrycollectors --all-namespaces -o json 2>/dev/null | \
  jq -r '
    .items[] | {
      namespace: .metadata.namespace,
      name: .metadata.name,
      mode: .spec.mode,
      config_length: (.spec.config | length)
    } |
    "\(.namespace)/\(.name) mode=\(.mode)"
  '

# Get ADOT collector config
kubectl get opentelemetrycollectors -n <namespace> <name> -o yaml 2>/dev/null
```

**Check custom metrics volume via CloudWatch:**

```bash
# Count custom metrics in the cluster namespace
aws cloudwatch list-metrics \
  --namespace "ContainerInsights" \
  --dimensions "Name=ClusterName,Value=<cluster>" \
  --query 'Metrics | length(@)' \
  --output text

# Check for high-cardinality EKS-specific metric namespaces
aws cloudwatch list-metrics \
  --namespace "ContainerInsights/Prometheus" \
  --dimensions "Name=ClusterName,Value=<cluster>" \
  --query 'Metrics | length(@)' \
  --output text 2>/dev/null
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="ConfigMap",
  api_version="v1",
  namespace="amazon-cloudwatch"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="ServiceMonitor",
  api_version="monitoring.coreos.com/v1",
  namespace="all"
)

list_k8s_resources(
  cluster_name="<cluster>",
  kind="PodMonitor",
  api_version="monitoring.coreos.com/v1",
  namespace="all"
)
```

### Analysis logic

```
# Prometheus cardinality check
If Prometheus/AMP detected:
  scrape_configs = parse scrape configuration
  
  For each scrape job:
    has_metric_relabeling = (metricRelabelings is present and non-empty)
    scrape_interval = interval (default 30s)
    
    # Flag overly frequent scraping without filtering
    If scrape_interval < "15s" AND NOT has_metric_relabeling:
      → Finding: high-frequency scraping without metric filtering
      severity = MEDIUM
    
    # Flag scrape-all patterns (no metric_relabel_configs to drop unused metrics)
    If NOT has_metric_relabeling AND job_name matches "kubernetes-pods" or "kubernetes-service-endpoints":
      → Finding: unfiltered scrape target collecting all exposed metrics
      severity = MEDIUM

  # Check total ServiceMonitor + PodMonitor count
  total_monitors = count(ServiceMonitors) + count(PodMonitors)
  If total_monitors > 20 AND few have metricRelabelings:
    → Finding: many unfiltered metric monitors — likely high cardinality
    severity = HIGH (high cost potential)

# CloudWatch agent check
If CloudWatch agent detected:
  config = parse agent configuration
  
  If config.metrics.metrics_collected includes "kubernetes" with all container metrics:
    If no metric filtering/exclusion configured:
      → Finding: CloudWatch agent collecting all container metrics without filtering
      severity = MEDIUM
  
  If enhanced container insights is enabled with per-container metrics:
    → Finding: per-container metrics enabled — verify cost justification
    severity = LOW (may be intentional)

# ADOT collector check
If ADOT collector detected:
  If traces are collected without tail sampling:
    → Finding: ADOT collecting all traces without sampling
    severity = MEDIUM–HIGH (depends on trace volume)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Active series > 500K (AMP) with estimated cost > $500/month | CRITICAL |
| Unfiltered Prometheus scraping all pod metrics + no relabeling | HIGH |
| CW agent collecting all container metrics without exclusions | MEDIUM |
| ServiceMonitors without metricRelabelings (> 10 monitors) | MEDIUM |
| ADOT collecting all traces without sampling | MEDIUM |
| Enhanced Container Insights enabled (per-container) | LOW |

### Remediation

```yaml
# Add metric relabeling to drop unused metrics (Prometheus Operator)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <service>-monitor
  namespace: <namespace>
spec:
  selector:
    matchLabels:
      app: <service>
  endpoints:
  - port: metrics
    interval: 30s
    metricRelabelings:
    # Drop high-cardinality metrics you don't use
    - sourceLabels: [__name__]
      regex: '(go_gc_.*|process_.*|promhttp_.*)'
      action: drop
    # Drop high-cardinality labels
    - regex: '(pod_template_hash|controller_revision_hash)'
      action: labeldrop
```

```yaml
# CloudWatch agent config — limit collected metrics
{
  "metrics": {
    "metrics_collected": {
      "kubernetes": {
        "enhanced_container_insights": false,
        "cluster_name": "<cluster>",
        "metrics_collection_interval": 60,
        "metric_declaration": [
          {
            "dimensions": [["Namespace", "ClusterName"]],
            "metric_name_selectors": [
              "pod_cpu_utilization",
              "pod_memory_utilization",
              "node_cpu_utilization",
              "node_memory_utilization"
            ]
          }
        ]
      }
    }
  }
}
```

```yaml
# ADOT collector — add tail sampling for traces
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
    - name: errors-policy
      type: status_code
      status_code: {status_codes: [ERROR]}
    - name: slow-traces
      type: latency
      latency: {threshold_ms: 1000}
    - name: probabilistic-sample
      type: probabilistic
      probabilistic: {sampling_percentage: 10}
```

---

## Check 3: DEBUG/TRACE Log Levels in Production

### What it detects

Workloads in production namespaces running with DEBUG or TRACE log levels, generating excessive log volume at $0.50/GB ingestion cost. Verbose logging in production is often left behind after troubleshooting sessions and can silently increase costs.

### Background

Log volume impact by level:
| Log Level | Typical Volume vs INFO | Monthly Cost Impact (per workload) |
|-----------|------------------------|-------------------------------------|
| TRACE | 10–50× INFO volume | $10–$100+ per workload |
| DEBUG | 5–20× INFO volume | $5–$50+ per workload |
| INFO | Baseline | Baseline |
| WARN/ERROR | 0.01–0.1× INFO | Minimal |

### Data collection

**Via kubectl — check environment variables and config:**

```bash
# Find workloads with DEBUG/TRACE log level in environment variables
kubectl get deployments --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    . as $dep |
    .spec.template.spec.containers[] |
    select(.env != null) |
    select(.env[] | 
      select(.name | test("LOG_LEVEL|LOGGING_LEVEL|LOG_LVL|RUST_LOG|LOGLEVEL|VERBOSE|DEBUG"; "i")) |
      select(.value | test("debug|trace|verbose|all"; "i"))
    ) |
    "\($dep.metadata.namespace)/\($dep.metadata.name) container=\(.name) \(.env[] | select(.name | test("LOG_LEVEL|LOGGING_LEVEL|LOG_LVL|RUST_LOG|LOGLEVEL|VERBOSE|DEBUG"; "i")) | "\(.name)=\(.value)")"
  '

# Also check StatefulSets
kubectl get statefulsets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    . as $sts |
    .spec.template.spec.containers[] |
    select(.env != null) |
    select(.env[] | 
      select(.name | test("LOG_LEVEL|LOGGING_LEVEL|LOG_LVL|RUST_LOG|LOGLEVEL|VERBOSE|DEBUG"; "i")) |
      select(.value | test("debug|trace|verbose|all"; "i"))
    ) |
    "\($sts.metadata.namespace)/\($sts.metadata.name) container=\(.name) \(.env[] | select(.name | test("LOG_LEVEL|LOGGING_LEVEL|LOG_LVL|RUST_LOG|LOGLEVEL|VERBOSE|DEBUG"; "i")) | "\(.name)=\(.value)")"
  '
```

```bash
# Check for DEBUG log levels in ConfigMaps used by workloads
kubectl get configmaps --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.data != null) |
    . as $cm |
    (.data | to_entries[] | 
      select(.value | test("level.*=.*debug|level.*=.*trace|logLevel.*debug|logLevel.*trace|log_level.*debug|log_level.*trace"; "i"))
    ) |
    "\($cm.metadata.namespace)/\($cm.metadata.name) key=\(.key)"
  '
```

```bash
# Check command-line args for verbose flags
kubectl get deployments --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    . as $dep |
    .spec.template.spec.containers[] |
    select(.args != null) |
    select(.args[] | test("-v=5|-v=6|-v=7|-v=8|-v=9|--debug|--verbose|--trace|--log-level=debug|--log-level=trace"; "i")) |
    "\($dep.metadata.namespace)/\($dep.metadata.name) container=\(.name) args=\([.args[] | select(test("-v=[5-9]|--debug|--verbose|--trace|--log-level"; "i"))] | join(" "))"
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
# Parse containers[].env for LOG_LEVEL=debug/trace patterns
# Parse containers[].args for --debug/--verbose/--trace flags
```

### Analysis logic

```
production_namespaces = namespaces matching:
  - name contains "prod", "production", "prd"
  - labels contain "environment=production" OR "env=prod"
  - OR: all namespaces if cluster name indicates production

For each workload in production_namespaces:
  For each container:
    log_level = detect from:
      1. Environment variables: LOG_LEVEL, LOGGING_LEVEL, LOG_LVL, RUST_LOG, LOGLEVEL
      2. ConfigMap references with log level settings
      3. Command args: --debug, --verbose, -v=5+, --log-level=debug
    
    If log_level in ["debug", "trace", "verbose", "all"]:
      → Finding: verbose logging in production
      severity = MEDIUM (per workload)
      
      # Estimate cost impact
      replica_count = spec.replicas
      # Conservative: DEBUG adds ~5 GB/month per replica
      estimated_extra_gb = replica_count × 5
      estimated_monthly_cost = estimated_extra_gb × $0.50
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| DEBUG/TRACE in production namespace, > 3 replicas | HIGH |
| DEBUG/TRACE in production namespace, ≤ 3 replicas | MEDIUM |
| DEBUG/TRACE in non-production namespace | LOW (informational only) |
| Multiple workloads with DEBUG in same prod namespace | HIGH (cumulative) |

### Remediation

```bash
# Patch deployment to set INFO log level
kubectl set env deployment/<deployment> -n <namespace> LOG_LEVEL=info

# Or patch specific environment variable
kubectl patch deployment <deployment> -n <namespace> --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/env/0/value", "value": "info"}
]'
```

```yaml
# Use a ConfigMap for centralized log level management
apiVersion: v1
kind: ConfigMap
metadata:
  name: logging-config
  namespace: <namespace>
data:
  LOG_LEVEL: "info"
  # Change to "debug" only during active troubleshooting
---
# Reference in Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <deployment>
spec:
  template:
    spec:
      containers:
      - name: app
        envFrom:
        - configMapRef:
            name: logging-config
```

> **Best practice:** Use a centralized log level ConfigMap that can be toggled during incidents without redeploying. Combine with a process to revert to INFO after troubleshooting windows.

---

## Check 4: Log Filtering and Sampling Configurations

### What it detects

Missing log filtering or sampling in the logging pipeline. Without filters, every log line (including noisy health checks, repetitive status messages, and low-value informational logs) is shipped to CloudWatch Logs or other destinations at full ingestion cost.

### Background

Common EKS logging pipelines:
| Component | Role | Filtering Capability |
|-----------|------|---------------------|
| FluentBit (DaemonSet) | Log collection + forwarding | Filters, parsers, multiline, sampling |
| CloudWatch agent | Log + metric collection | Inclusion/exclusion patterns |
| Fluentd | Log collection + forwarding | Filters, transforms, buffering |
| ADOT (Fluent Forward) | Log collection via OTel | Processors, filters |

**Cost impact of unfiltered logging** (estimates based on field experience across production EKS deployments):
- Health check logs: 30–60% of total log volume in microservice architectures
- Kubernetes event noise: 5–15% of volume
- Repetitive status/heartbeat messages: 10–20% of volume

Filtering out this noise can reduce log ingestion costs by 40–70% (based on field experience; actual results vary by workload mix).

### Data collection

**Check FluentBit configuration:**

```bash
# Find FluentBit ConfigMaps or DaemonSets
kubectl get configmaps --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("fluent-bit|fluentbit|fluent"; "i")) |
    "\(.metadata.namespace)/\(.metadata.name)"
  '

# Get FluentBit DaemonSet to confirm it's running
kubectl get daemonsets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("fluent-bit|fluentbit"; "i")) |
    "\(.metadata.namespace)/\(.metadata.name) ready=\(.status.numberReady)/\(.status.desiredNumberScheduled)"
  '

# Get FluentBit config content
kubectl get configmap -n <logging-namespace> <fluent-bit-config> -o json | \
  jq -r '.data'
```

```bash
# Check FluentBit config for FILTER sections
kubectl get configmap -n <logging-namespace> <fluent-bit-config> -o json | \
  jq -r '.data["fluent-bit.conf"] // .data["fluent-bit-config"] // empty' | \
  grep -A5 -i "\[FILTER\]"

# Look for Kubernetes filter with Exclude or Grep
kubectl get configmap -n <logging-namespace> <fluent-bit-config> -o json | \
  jq -r '.data["fluent-bit.conf"] // .data["fluent-bit-config"] // empty' | \
  grep -ci "exclude\|grep\|throttle\|sampling"
```

**Check CloudWatch agent log filtering:**

```bash
# Get CloudWatch agent config
kubectl get configmap -n amazon-cloudwatch \
  $(kubectl get configmap -n amazon-cloudwatch -o name | grep -i "cwagent\|cloudwatch-agent" | head -1 | cut -d'/' -f2) \
  -o json | jq -r '.data'

# Check for log_filters or exclusion patterns
kubectl get configmap -n amazon-cloudwatch cloudwatch-agent-config -o json 2>/dev/null | \
  jq -r '.data[] | select(test("exclude|filter|blacklist"; "i"))' 
```

```bash
# Check for Fluentd (alternative to FluentBit)
kubectl get configmaps --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("fluentd"; "i")) |
    "\(.metadata.namespace)/\(.metadata.name)"
  '

kubectl get daemonsets --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.name | test("fluentd"; "i")) |
    "\(.metadata.namespace)/\(.metadata.name) ready=\(.status.numberReady)/\(.status.desiredNumberScheduled)"
  '
```

```bash
# Check if any log pipeline exists at all
echo "--- Logging pipeline detection ---"
echo "FluentBit:"
kubectl get ds -A -l app.kubernetes.io/name=fluent-bit --no-headers 2>/dev/null | wc -l
echo "Fluentd:"
kubectl get ds -A -l app=fluentd --no-headers 2>/dev/null | wc -l
echo "CloudWatch agent:"
kubectl get ds -A -l app.kubernetes.io/name=cloudwatch-agent --no-headers 2>/dev/null | wc -l
echo "ADOT:"
kubectl get ds -A -l app.kubernetes.io/name=adot-collector --no-headers 2>/dev/null | wc -l
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="DaemonSet",
  api_version="apps/v1",
  namespace="all"
)
# Filter for fluent-bit, fluentd, cloudwatch-agent, adot-collector

list_k8s_resources(
  cluster_name="<cluster>",
  kind="ConfigMap",
  api_version="v1",
  namespace="<logging-namespace>"
)
# Parse config for filter/exclude/sampling directives
```

### Analysis logic

```
# Step 1: Identify logging pipeline
pipeline = detect_logging_pipeline()  # FluentBit, Fluentd, CW Agent, ADOT, or None

If pipeline == None:
  # No centralized logging — either logs go directly to stdout/CloudWatch
  # or there's no pipeline (unusual in production)
  → Note: no logging pipeline detected — logs may use direct CloudWatch collection
  # Check if Container Insights is collecting logs directly
  If container_insights_logs_enabled:
    → Finding: Container Insights collecting all stdout/stderr without filtering
    severity = MEDIUM
  Else:
    → Skip (no logging cost to optimize)

# Step 2: Check for filtering in the detected pipeline
If pipeline == "FluentBit":
  config = parse FluentBit configuration
  
  has_exclude_filter = config contains [FILTER] with "Exclude" directive
  has_grep_filter = config contains [FILTER] with "Grep" or "grep" type
  has_throttle = config contains [FILTER] with "throttle" type
  has_sampling = config contains sampling rate configuration
  
  If NOT (has_exclude_filter OR has_grep_filter OR has_throttle OR has_sampling):
    → Finding: FluentBit running without any log filtering
    severity = HIGH (all logs shipped unfiltered — likely 40-70% unnecessary)
    monthly_waste_estimate = total_monthly_log_ingestion_cost × 0.40
  
  # Check for common missing filters
  If NOT config.excludes_health_checks:
    → Finding: health check logs not filtered
    severity = MEDIUM (health checks are typically 30-60% of log volume)
  
  If NOT config.excludes_kube_system:
    → Finding: kube-system namespace logs not filtered
    severity = LOW

If pipeline == "CloudWatch Agent":
  config = parse CW agent configuration
  
  If config.logs.logs_collected.kubernetes.log_filters is null or empty:
    → Finding: CloudWatch agent collecting all logs without filtering
    severity = MEDIUM
  
  If config lacks exclude patterns for health checks:
    → Finding: health check logs not excluded from collection
    severity = MEDIUM

# Step 3: Estimate cost savings from filtering
If has_filtering_finding:
  # Get current log ingestion cost
  monthly_ingestion_gb = get CloudWatch Logs IncomingBytes metric
  monthly_ingestion_cost = monthly_ingestion_gb × $0.50
  
  # Conservative estimate: filtering saves 40% of ingestion
  estimated_savings = monthly_ingestion_cost × 0.40
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| No log filtering at all (pipeline running, no filters) | HIGH |
| Health check logs not filtered (30-60% of volume) | MEDIUM |
| No sampling on high-throughput services (> 1000 logs/sec) | MEDIUM |
| Filtering present but missing common exclusions | LOW |
| No logging pipeline detected (logs go nowhere or direct CW) | LOW (informational) |

### Remediation

```ini
# FluentBit — Add filters to exclude health checks and noisy logs
[FILTER]
    Name    grep
    Match   kube.*
    Exclude log /health|/ready|/alive|/ping|healthz|readyz

[FILTER]
    Name    grep
    Match   kube.*
    Exclude kubernetes.namespace_name kube-system

[FILTER]
    Name    throttle
    Match   kube.*
    Rate    1000
    Window  5
    Print_Status true
    Interval 30s
```

```ini
# FluentBit — Sampling configuration for high-volume services
[FILTER]
    Name         sampling
    Match        kube.production.high-traffic-service.*
    Percentage   10
    # Only ship 10% of logs from high-volume services
```

```yaml
# CloudWatch agent config with log filtering
{
  "logs": {
    "metrics_collected": {
      "kubernetes": {
        "cluster_name": "<cluster>",
        "enhanced_container_insights": true
      }
    },
    "logs_collected": {
      "kubernetes": {
        "namespace_exclude": ["kube-system", "amazon-cloudwatch"],
        "log_filters": [
          {
            "type": "exclude",
            "expression": "health|ready|alive|ping|healthz"
          }
        ]
      }
    }
  }
}
```

```yaml
# FluentBit Helm values for filtering (common deployment pattern)
config:
  filters: |
    [FILTER]
        Name    kubernetes
        Match   kube.*
        Merge_Log On
        Keep_Log Off
        K8S-Logging.Parser On
        K8S-Logging.Exclude On

    [FILTER]
        Name    grep
        Match   kube.*
        Exclude log ^GET /health
    
    [FILTER]
        Name    grep
        Match   kube.*
        Exclude log ^GET /ready
    
    [FILTER]
        Name    modify
        Match   kube.*
        Remove  stream
        Remove  logtag
```

---

## Scoring Contribution

The observability costs dimension has a **maximum deduction of 10 points**.

### Deduction calculation

```
deduction = 0

For each finding in this dimension:
  If severity == CRITICAL: deduction += 10 × 0.6 = 6.0
  If severity == HIGH:     deduction += 10 × 0.3 = 3.0
  If severity == MEDIUM:   deduction += 10 × 0.15 = 1.5
  If severity == LOW:      deduction += 10 × 0.05 = 0.5

actual_deduction = min(deduction, 10)  # Cap at maximum
```

### Dimension status

| Condition | Status |
|-----------|--------|
| All checks completed | ASSESSED |
| Some checks skipped (no logging pipeline) | ASSESSED (with note) |
| Cannot access cluster logging config at all | SKIPPED |

If the dimension is fully SKIPPED, it contributes **zero deduction** and is excluded from the score denominator.

---

## Cost Estimation Reference

### CloudWatch Logs pricing (us-east-1)

| Component | Cost |
|-----------|------|
| Ingestion | $0.50/GB |
| Storage (standard) | $0.03/GB/month |
| Storage (infrequent access) | $0.0125/GB/month |
| Logs Insights queries | $0.0065/GB scanned |
| Live Tail | $0.01/minute per session |

### Amazon Managed Prometheus (AMP)

| Component | Cost |
|-----------|------|
| Sample ingestion | $0.003/million samples |
| Storage (first 2 months) | $0.03/GB/month |
| Query processing | $0.007/million samples scanned |

### CloudWatch custom metrics

| Volume | Cost per metric/month |
|--------|----------------------|
| First 10,000 | $0.30 |
| Next 240,000 | $0.10 |
| Next 750,000 | $0.05 |
| Over 1,000,000 | $0.02 |

### Quick cost estimation formulas

```
# Control plane log cost
control_plane_monthly_cost = monthly_ingestion_gb × $0.50 + stored_gb × $0.03

# Application log cost savings from filtering
filtering_savings = total_monthly_log_gb × filter_reduction_percentage × $0.50
# Conservative filter_reduction_percentage: 0.40 (40%)
# Aggressive (with health check + debug removal): 0.60 (60%)

# Prometheus/AMP cost from cardinality
amp_monthly_cost = active_series × samples_per_series_per_month × $0.003/million
# samples_per_series_per_month at 30s interval = 86,400 samples/day × 30 = 2,592,000/month
# 100K active series at 30s scrape = 259.2 billion samples/month = ~$777/month

# CloudWatch agent metric cost
cw_metric_cost = unique_metric_count × $0.30 (first 10K) or $0.10 (10K-250K)
```

---

## Decision Tree

```
START
  │
  ├─ Check 1: Control Plane Logging
  │   ├─ Get enabled log types (aws eks describe-cluster)
  │   ├─ All 5 types enabled?
  │   │   ├─ YES + non-prod cluster → Finding (MEDIUM–HIGH by cost)
  │   │   ├─ YES + prod + audit > 20 GB/month → Finding (retention recommendation)
  │   │   └─ NO or justified → No finding
  │   └─ Check log group retention
  │       └─ "Never expire" + high volume → Finding (MEDIUM)
  │
  ├─ Check 2: High-Cardinality Metrics
  │   ├─ Prometheus/AMP detected?
  │   │   ├─ YES → Check scrape configs for filtering
  │   │   │   ├─ No metricRelabelings → Finding (MEDIUM–HIGH)
  │   │   │   └─ Filtered → No finding
  │   │   └─ NO → Skip Prometheus check
  │   ├─ CloudWatch agent detected?
  │   │   ├─ YES → Check metric collection scope
  │   │   │   ├─ All container metrics, no exclusions → Finding (MEDIUM)
  │   │   │   └─ Scoped collection → No finding
  │   │   └─ NO → Skip CW agent check
  │   └─ ADOT collector detected?
  │       ├─ YES → Check for tail sampling
  │       │   ├─ No sampling → Finding (MEDIUM)
  │       │   └─ Sampling configured → No finding
  │       └─ NO → Skip ADOT check
  │
  ├─ Check 3: DEBUG/TRACE Log Levels
  │   ├─ Scan deployments + statefulsets for log level env vars/args
  │   ├─ Filter to production namespaces
  │   ├─ Any DEBUG/TRACE found?
  │   │   ├─ YES → Finding per workload (MEDIUM–HIGH by replica count)
  │   │   └─ NO → No finding
  │   └─ Check ConfigMaps for debug log configurations
  │
  ├─ Check 4: Log Filtering/Sampling
  │   ├─ Identify logging pipeline (FluentBit, Fluentd, CW Agent, ADOT)
  │   ├─ Pipeline detected?
  │   │   ├─ YES → Check config for filters/excludes/sampling
  │   │   │   ├─ No filtering → Finding (HIGH)
  │   │   │   ├─ Filtering but missing health checks → Finding (MEDIUM)
  │   │   │   └─ Comprehensive filtering → No finding
  │   │   └─ NO → Note (informational) or Finding if Container Insights collecting all
  │   └─ Estimate savings from adding filters
  │
  └─ Aggregate findings → Calculate dimension deduction (max 10 points)
```
