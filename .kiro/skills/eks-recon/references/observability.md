# Module: Observability

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect observability stack - metrics, logging, tracing configuration

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [1. Metrics Collection](#1-metrics-collection)
  - [2. Logging Configuration](#2-logging-configuration)
  - [3. Tracing](#3-tracing)
  - [4. Application Signals (APM)](#4-application-signals-apm)
- [Output Schema](#output-schema)
- [Edge Cases](#edge-cases)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `describe_eks_resource`, `list_k8s_resources`
- **CLI fallback:** `aws eks`, `kubectl`, `aws logs`

---

## Detection Strategy

Observability has three pillars (plus control plane logging):

```
1. Metrics          -> Container Insights, Prometheus, Datadog, etc.
2. Logging          -> CloudWatch, FluentBit, OpenSearch, etc.
3. Tracing          -> X-Ray, ADOT, Jaeger, etc.
4. Control Plane    -> API server, audit, authenticator logs
```

**Why detect each pillar:**

| Pillar | Why It Matters |
|--------|----------------|
| Metrics | Understand resource utilization, HPA scaling decisions, capacity planning |
| Logging | Debug application issues, audit security events, compliance requirements |
| Tracing | Diagnose latency in distributed systems, identify service dependencies |
| Control Plane | Investigate API failures, audit access, debug networking issues |

---

## Detection Commands

### 1. Metrics Collection

Start with metrics detection to understand how the cluster tracks resource usage and supports autoscaling. Most clusters have at least one metrics solution.

**Container Insights (CloudWatch):**

Use Container Insights when you need AWS-native monitoring with automatic CloudWatch integration. This is the simplest option for teams already using AWS observability tools.

**MCP:**
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="amazon-cloudwatch-observability"
)
```

**CLI:**
```bash
# Check for CloudWatch add-on
aws eks describe-addon --cluster-name <cluster-name> \
  --addon-name amazon-cloudwatch-observability 2>/dev/null

# Alternative: Check for CloudWatch agent DaemonSet
kubectl get daemonset -n amazon-cloudwatch cloudwatch-agent 2>/dev/null

# Check for Fluent Bit (CloudWatch integration)
kubectl get daemonset -n amazon-cloudwatch fluent-bit 2>/dev/null
```

**Example output (add-on installed):**
```json
{
  "addon": {
    "addonName": "amazon-cloudwatch-observability",
    "clusterName": "prod-cluster",
    "status": "ACTIVE",
    "addonVersion": "v1.5.0-eksbuild.1"
  }
}
```

**Example output (not installed):**
```
An error occurred (ResourceNotFoundException) when calling the DescribeAddon operation
```

**Prometheus (Self-Managed):**

Use Prometheus when you need flexible metrics collection with PromQL queries, custom recording rules, or Grafana dashboards. Common in teams with existing Prometheus expertise.

```bash
# Check for Prometheus deployment
kubectl get deploy -n prometheus prometheus-server 2>/dev/null || \
kubectl get deploy -n monitoring prometheus-server 2>/dev/null || \
kubectl get statefulset -n prometheus prometheus-server 2>/dev/null

# Check for kube-prometheus-stack (Helm)
helm list -A --filter "prometheus\|kube-prometheus" 2>/dev/null

# Check for Prometheus Operator
kubectl get deploy -A -l "app.kubernetes.io/name=prometheus-operator" 2>/dev/null
```

**Example output (Prometheus detected):**
```
NAME                READY   UP-TO-DATE   AVAILABLE   AGE
prometheus-server   1/1     1            1           45d
```

**Amazon Managed Prometheus (AMP):**

Check for AMP when you need managed Prometheus with automatic scaling and AWS integration. Look for `aps-workspaces` URLs in remote write configurations.

```bash
# Check for ADOT or Prometheus remote write config
kubectl get configmap -A -o json | jq -r '
  .items[] |
  select(.data | to_entries | .[] | .value | contains("aps-workspaces")) |
  {namespace: .metadata.namespace, name: .metadata.name}'
```

**Example output (AMP configured):**
```json
{
  "namespace": "prometheus",
  "name": "prometheus-config"
}
```

**Grafana:**
```bash
# Check for Grafana deployment
kubectl get deploy -A -l "app.kubernetes.io/name=grafana" 2>/dev/null

# Check for Amazon Managed Grafana (external, check workspace)
# Note: AMG workspaces are external to cluster
```

**Other Metrics Tools:**

Third-party tools like Datadog and New Relic provide unified observability platforms. Check for these when the team uses a commercial APM solution.

```bash
# Datadog
kubectl get daemonset -n datadog datadog-agent 2>/dev/null

# New Relic
kubectl get daemonset -A -l "app.kubernetes.io/name=nri-bundle" 2>/dev/null

# Metrics Server (required for HPA - almost always present)
kubectl get deploy -n kube-system metrics-server 2>/dev/null
```

**Example output (Metrics Server):**
```
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
metrics-server   1/1     1            1           120d
```

### 2. Logging Configuration

Detect logging configuration to understand how application and cluster logs are collected and where they are sent. Control plane logging is critical for debugging and compliance.

**Control Plane Logging:**

Always check control plane logging first. Missing audit logs is a security/compliance gap.

```bash
# Check which control plane logs are enabled
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.logging.clusterLogging[*].{types:types,enabled:enabled}'
```

**Example output (all logs enabled):**
```json
[
  {
    "types": ["api", "audit", "authenticator", "controllerManager", "scheduler"],
    "enabled": true
  }
]
```

**Example output (no logs enabled - flag this):**
```json
[
  {
    "types": ["api", "audit", "authenticator", "controllerManager", "scheduler"],
    "enabled": false
  }
]
```

**Fluent Bit / Fluentd:**

Fluent Bit (lightweight) and Fluentd (feature-rich) are the most common log forwarders. Check their ConfigMaps to determine where logs are being sent.

```bash
# Fluent Bit DaemonSet
kubectl get daemonset -A -l "app.kubernetes.io/name=fluent-bit" 2>/dev/null

# Fluentd DaemonSet
kubectl get daemonset -A -l "app=fluentd" 2>/dev/null

# Check Fluent Bit ConfigMap for destinations
kubectl get configmap -n amazon-cloudwatch fluent-bit-config -o yaml 2>/dev/null | \
  grep -E "cloudwatch|opensearch|s3|kinesis" || true
```

**Example output (Fluent Bit detected):**
```
NAMESPACE          NAME         DESIRED   CURRENT   READY   AGE
amazon-cloudwatch  fluent-bit   3         3         3       60d
```

**OpenSearch / Elasticsearch:**
```bash
# Check for OpenSearch endpoint in configs
kubectl get configmap -A -o json | jq -r '
  .items[] |
  select(.data | to_entries | .[] | .value | contains("opensearch") or contains("elasticsearch")) |
  {namespace: .metadata.namespace, name: .metadata.name}'
```

**Loki:**
```bash
# Check for Loki deployment
kubectl get deploy -A -l "app.kubernetes.io/name=loki" 2>/dev/null
kubectl get statefulset -A -l "app.kubernetes.io/name=loki" 2>/dev/null
```

### 3. Tracing

Tracing is essential for debugging latency in microservices architectures. Without tracing, diagnosing cross-service issues requires correlating logs manually.

**AWS X-Ray / ADOT:**

ADOT (AWS Distro for OpenTelemetry) is the AWS-recommended approach for tracing. It can send traces to X-Ray, Jaeger, or other backends.

```bash
# Check for ADOT collector
kubectl get deploy -A -l "app.kubernetes.io/name=aws-otel-collector" 2>/dev/null

# Check for X-Ray daemon
kubectl get daemonset -A -l "app=xray-daemon" 2>/dev/null

# Check ADOT add-on
aws eks describe-addon --cluster-name <cluster-name> --addon-name adot 2>/dev/null
```

**Example output (ADOT add-on installed):**
```json
{
  "addon": {
    "addonName": "adot",
    "clusterName": "prod-cluster",
    "status": "ACTIVE",
    "addonVersion": "v0.88.0-eksbuild.1"
  }
}
```

**Jaeger:**

Jaeger is a popular open-source tracing backend. Check for it when the team uses a self-managed tracing solution.

```bash
# Check for Jaeger
kubectl get deploy -A -l "app.kubernetes.io/name=jaeger" 2>/dev/null
kubectl get deploy -A -l "app=jaeger" 2>/dev/null
```

**Tempo:**

Grafana Tempo is often used with Grafana and Loki for a unified observability stack.

```bash
# Check for Grafana Tempo
kubectl get deploy -A -l "app.kubernetes.io/name=tempo" 2>/dev/null
kubectl get statefulset -A -l "app.kubernetes.io/name=tempo" 2>/dev/null
```

### 4. Application Signals (APM)

Application Signals provides automatic instrumentation for common frameworks. Check for this when the team wants APM without modifying application code.

```bash
# Check for CloudWatch Application Signals
kubectl get deploy -n amazon-cloudwatch cloudwatch-agent-operator 2>/dev/null

# Check for auto-instrumentation
kubectl get instrumentations.opentelemetry.io -A 2>/dev/null
```

**Example output (auto-instrumentation configured):**
```
NAMESPACE   NAME       AGE   ENDPOINT
default     java-app   30d   http://adot-collector:4317
```

---

## Output Schema

```yaml
observability:
  metrics:
    container_insights:
      enabled: bool
      addon_version: string
      
    prometheus:
      detected: bool
      type: string         # self-managed | amp | operator
      namespace: string
      version: string
      
    grafana:
      detected: bool
      type: string         # self-managed | amg
      namespace: string
      
    metrics_server:
      detected: bool
      version: string
      
    other_tools: list      # datadog, newrelic, etc.
    
  logging:
    control_plane:
      enabled: bool
      log_types: list      # api, audit, authenticator, controllerManager, scheduler
      
    application:
      tool: string         # fluent-bit | fluentd | promtail | none
      destination: string  # cloudwatch | opensearch | loki | s3
      namespace: string
      
    log_destinations:
      cloudwatch: bool
      opensearch: bool
      s3: bool
      loki: bool
      
  tracing:
    tool: string           # xray | adot | jaeger | tempo | none
    adot:
      detected: bool
      version: string
    xray:
      detected: bool
    jaeger:
      detected: bool
    tempo:
      detected: bool
      
  apm:
    application_signals:
      enabled: bool
    auto_instrumentation:
      enabled: bool
      namespaces: list
```

---

## Edge Cases

### Multiple Metrics Solutions

Common to have:
- Metrics Server (for HPA)
- Prometheus (for detailed metrics)
- Container Insights (for AWS integration)

Note all and their purposes.

### Log Aggregation Outside Cluster

Logs may go to:
- External CloudWatch in different account
- Third-party SaaS (Datadog, Splunk)
- Self-managed OpenSearch/ELK

Check Fluent Bit/Fluentd configs for destinations.

### Control Plane Logging Not Enabled

```bash
# Check if any logs are enabled
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.logging.clusterLogging[?enabled==`true`].types'
```

If empty, flag as security/compliance gap.

### ADOT vs Self-Managed Collectors

```bash
# Check if using ADOT add-on or self-managed
aws eks describe-addon --cluster-name <cluster-name> --addon-name adot 2>/dev/null
# vs
kubectl get deploy -A -l "app=opentelemetry-collector" 2>/dev/null
```

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| No metrics solution | Enable Container Insights or deploy Prometheus |
| No control plane logs | Enable all log types for debugging/audit |
| No tracing | Consider ADOT for distributed tracing |
| Multiple overlapping tools | Consolidate to reduce overhead |
| No metrics server | Deploy for HPA functionality |
| Application Signals not enabled | Consider for APM capabilities |
