# EKS Observability Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Monitoring, logging, tracing, alerting, network performance monitoring, GPU observability, and detective controls for Amazon EKS clusters

---

## Table of Contents

1. [Observability Strategy](#observability-strategy)
2. [CloudWatch Container Insights](#cloudwatch-container-insights)
3. [CloudWatch Application Signals](#cloudwatch-application-signals)
4. [Prometheus and Grafana](#prometheus-and-grafana)
5. [Control Plane Monitoring](#control-plane-monitoring)
6. [Network Performance Monitoring](#network-performance-monitoring)
7. [Logging Architecture](#logging-architecture)
8. [Distributed Tracing](#distributed-tracing)
9. [GPU and AI/ML Observability](#gpu-and-aiml-observability)
10. [Detective Controls](#detective-controls)
11. [Alerting Patterns](#alerting-patterns)
12. [Monitoring High Availability](#monitoring-high-availability)
13. [Multi-Tenant Observability Isolation](#multi-tenant-observability-isolation)
14. [Tiered Log Retention Architecture](#tiered-log-retention-architecture)

---

## Observability Strategy

### Three Pillars for EKS

| Pillar | AWS-Managed Option | Open Source Option |
|--------|-------------------|-------------------|
| **Metrics** | CloudWatch Container Insights | Amazon Managed Prometheus (AMP) + Grafana |
| **Logs** | CloudWatch Logs | OpenSearch, Loki |
| **Traces** | AWS X-Ray / Application Signals | OpenTelemetry + Jaeger/Tempo |

### Decision Matrix

| Factor | CloudWatch Native | Managed Prometheus + Grafana |
|--------|------------------|------------------------------|
| **Setup effort** | Low (EKS add-on) | Medium (AMP workspace + ADOT) |
| **Custom metrics** | Limited (Container Insights) | Full PromQL |
| **APM** | Application Signals (auto-instrument) | Manual instrumentation |
| **Dashboarding** | CloudWatch dashboards | Grafana (rich ecosystem) |
| **Cost model** | Per metric, per log GB | Per metric series ingested |
| **Multi-cluster** | Per-account aggregation | Central AMP workspace |
| **Alerting** | CloudWatch Alarms | Prometheus Alertmanager |
| **Recommendation** | Simple setups, AWS-native | Production, complex monitoring |

### Key Supporting Components

| Component | Purpose | Deploy As |
|-----------|---------|-----------|
| **kube-state-metrics (KSM)** | Kubernetes object state (deployments, pods, nodes) | Deployment |
| **Metrics Server** | CPU/memory for HPA and `kubectl top` | Deployment |
| **Fluent Bit** | Log collection and forwarding | DaemonSet |
| **ADOT Collector** | Metrics, traces, logs collection (OpenTelemetry) | DaemonSet or sidecar |
| **DCGM Exporter** | GPU metrics (NVIDIA) | DaemonSet |

---

## CloudWatch Container Insights

### Enable Container Insights

```bash
# Enable via EKS add-on (recommended -- enables both Container Insights and Application Signals)
aws eks create-addon \
  --cluster-name my-cluster \
  --addon-name amazon-cloudwatch-observability
```

### Key Container Insights Metrics

| Metric | Level | Alert On |
|--------|-------|----------|
| `node_cpu_utilization` | Node | > 80% sustained |
| `node_memory_utilization` | Node | > 85% sustained |
| `pod_cpu_utilization` | Pod | > 90% of request |
| `pod_memory_utilization` | Pod | > 85% of limit |
| `pod_number_of_container_restarts` | Pod | > 3 in 5 minutes |
| `node_filesystem_utilization` | Node | > 80% |
| `cluster_failed_node_count` | Cluster | > 0 |

### Enhanced Observability

Enhanced observability (EKS add-on v1.5+) provides:
- Automatic pod-level Prometheus metrics collection
- EKS control plane metrics
- GPU metrics for ML workloads (via DCGM Exporter integration)
- Integration with CloudWatch Application Signals for APM

---

## CloudWatch Application Signals

Application Signals provides auto-instrumentation APM for EKS workloads -- it automatically collects metrics, traces, and service maps without code changes.

### Supported Languages

| Language | Auto-Instrumentation | Notes |
|----------|---------------------|-------|
| **Java** | Yes | Broadest coverage |
| **Python** | Yes | -- |
| **Node.js** | Yes | ESM modules require special setup |
| **.NET** | Yes | -- |

### What It Provides

| Capability | Detail |
|------------|--------|
| **Service map** | Auto-discovered dependency graph of all instrumented services |
| **SLO monitoring** | Define and track service-level objectives (latency, availability) |
| **Correlated traces** | Automatic trace correlation with metrics and logs |
| **Pre-built dashboards** | Latency, error rate, throughput per service -- no setup required |

### How to Enable

Enable via the CloudWatch Observability EKS add-on (same add-on as Container Insights), then annotate workloads:

```yaml
# Annotate deployment to enable auto-instrumentation
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"  # or inject-python, inject-nodejs, inject-dotnet
```

Or enable via the AWS console for selected namespaces/workloads.

Application Signals is the simplest path to APM on EKS -- if you're already using the CloudWatch Observability add-on, it's one annotation per workload.

---

## Prometheus and Grafana

### Amazon Managed Prometheus (AMP) Setup

```bash
# Create AMP workspace
aws amp create-workspace --alias my-cluster-metrics

# Deploy ADOT collector for metric collection
helm install adot-collector \
  open-telemetry/opentelemetry-collector \
  --namespace observability --create-namespace \
  --set config.exporters.prometheusremotewrite.endpoint=<AMP_REMOTE_WRITE_URL> \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=<IRSA_ROLE_ARN>
```

### Key Prometheus Metrics for EKS

**Cluster health:**
```promql
# Nodes not ready
kube_node_status_condition{condition="Ready",status="true"} == 0

# Pod restart rate (per namespace)
sum(increase(kube_pod_container_status_restarts_total[1h])) by (namespace) > 5

# Pending pods (scheduling issues)
kube_pod_status_phase{phase="Pending"} > 0  # for > 5 minutes

# PVC pending (storage issues)
kube_persistentvolumeclaim_status_phase{phase="Pending"} > 0
```

**Resource efficiency:**
```promql
# CPU request vs actual usage (over-provisioning)
1 - (
  sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (namespace)
  /
  sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace)
)

# Memory utilization vs requests
sum(container_memory_working_set_bytes{container!=""}) by (namespace)
/
sum(kube_pod_container_resource_requests{resource="memory"}) by (namespace)
```

### Amazon Managed Grafana (AMG)

**Recommended dashboards:**
- Kubernetes cluster overview (ID: 3119)
- Node Exporter (ID: 1860)
- Karpenter dashboard (ID: 20398)
- CoreDNS dashboard (ID: 15762)
- API server troubleshooter: [Troubleshooting Dashboards](https://github.com/RiskyAdventure/Troubleshooting-Dashboards)

---

## Control Plane Monitoring

EKS exposes Prometheus metrics for API server and etcd. Effective control plane monitoring helps distinguish between API server bottlenecks and downstream issues (etcd, webhooks, controllers).

### API Server Metrics

| Metric | What It Tells You |
|--------|-------------------|
| `apiserver_request_duration_seconds` | Request latency by verb and resource |
| `apiserver_request_total` | Request volume and error rates (watch for 429s and 5xx) |
| `apiserver_flowcontrol_nominal_limit_seats` | APF priority group capacity |
| `apiserver_flowcontrol_current_inqueue_request` | Requests queued per APF bucket (non-zero = saturation) |
| `apiserver_flowcontrol_rejected_requests_total` | Requests dropped per APF bucket |
| `apiserver_admission_controller_admission_duration_seconds` | Admission webhook latency |

### API vs etcd Latency

When API server latency is high, check if etcd is the bottleneck:

```promql
# API server request latency heatmap (use max, not avg, across API servers)
max(increase(apiserver_request_duration_seconds_bucket{subresource!="status",subresource!="token",verb!="WATCH"}[$__rate_interval])) by (le)

# etcd request latency
etcd_request_duration_seconds
```

If 15 seconds of etcd latency occurs alongside 20 seconds of API latency, the root cause is etcd, not the API server. Always check the whole chain before tuning one component.

### Asymmetric Traffic

EKS runs 2+ API servers. Never average metrics across them -- one server may be overloaded while others are idle. Use `max` or break out by instance.

### Finding Noisy Controllers

Use CloudWatch Logs Insights to identify controllers making excessive LIST calls:

```
fields @timestamp, @message
| filter @logStream like "kube-apiserver-audit"
| filter verb = "list"
| parse requestReceivedTimestamp /\d+-\d+-(?<StartDay>\d+)T(?<StartHour>\d+):(?<StartMinute>\d+):(?<StartSec>\d+).(?<StartMsec>\d+)Z/
| parse stageTimestamp /\d+-\d+-(?<EndDay>\d+)T(?<EndHour>\d+):(?<EndMinute>\d+):(?<EndSec>\d+).(?<EndMsec>\d+)Z/
| fields (StartHour * 3600 + StartMinute * 60 + StartSec + StartMsec / 1000000) as StartTime, (EndHour * 3600 + EndMinute * 60 + EndSec + EndMsec / 1000000) as EndTime, (EndTime - StartTime) as DeltaTime
| stats avg(DeltaTime) as AverageDeltaTime, count(*) as CountTime by requestURI, userAgent
| filter CountTime >=50
| sort AverageDeltaTime desc
```

**See also:** [Scalability -- Control Plane Scaling](scalability.md) for APF tuning and burst limit guidance

---

## Network Performance Monitoring

Network performance issues (DNS throttling, connection tracking exhaustion, bandwidth limits) are among the hardest EKS problems to diagnose because packet drops happen in seconds and aren't captured by flow logs.

### ENA Driver Metrics

The Elastic Network Adapter (ENA) driver exposes metrics that reveal network-level bottlenecks. All should be zero in healthy clusters:

| Metric | What It Means | Impact |
|--------|--------------|--------|
| `linklocal_allowance_exceeded` | PPS limit hit for local proxy services (DNS, IMDS, NTP) | DNS lookup failures, metadata timeouts |
| `conntrack_allowance_exceeded` | Connection tracking table full -- no new connections | Service-to-service connectivity failures |
| `conntrack_allowance_available` | Remaining tracked connections before limit | Early warning for conntrack exhaustion |
| `bw_in_allowance_exceeded` | Inbound bandwidth limit hit | Packet queuing/drops |
| `bw_out_allowance_exceeded` | Outbound bandwidth limit hit | Packet queuing/drops |
| `pps_allowance_exceeded` | Bidirectional PPS limit hit | Packet queuing/drops |

### Collecting ENA Metrics

Deploy Prometheus Node Exporter with the ethtool collector:

```bash
helm upgrade -i prometheus-node-exporter prometheus-community/prometheus-node-exporter \
  --set extraArgs[0]="--collector.ethtool" \
  --set extraArgs[1]="--collector.ethtool.device-include=(eth|em|eno|ens|enp)[0-9s]+" \
  --set extraArgs[2]="--collector.ethtool.metrics-include=.*"
```

Then scrape with ADOT or Prometheus and store in AMP. Set alerts for any non-zero `_exceeded` metric.

### DNS Throttling Detection

DNS queries are throttled at the ENI level (1024 PPS limit). Throttled queries don't appear in query logging or flow logs. The only reliable signal is `linklocal_allowance_exceeded`.

Remediation:
- Increase CoreDNS replicas (anti-affinity spreads them across ENIs)
- Deploy NodeLocal DNSCache
- Lower `ndots` to reduce query volume (see [Scalability -- CoreDNS](scalability.md))

---

## Logging Architecture

### Log Types and Destinations

| Log Type | Source | Recommended Destination |
|----------|--------|------------------------|
| **Control plane logs** | EKS API server, audit, scheduler, controller manager, authenticator | CloudWatch Logs (`/aws/eks/<cluster>/cluster`) |
| **Application logs** | Container stdout/stderr | CloudWatch Logs or OpenSearch |
| **Node logs** | kubelet, containerd | CloudWatch Logs via agent |
| **Data plane logs** | VPC CNI, kube-proxy | CloudWatch Logs |

### Fluent Bit Configuration

```bash
# Deploy as EKS add-on (recommended)
aws eks create-addon --cluster-name my-cluster --addon-name aws-for-fluent-bit
```

**Scaling Fluent Bit for large clusters:**

| Setting | Purpose |
|---------|---------|
| `Use_Kubelet: On` | Fetch pod metadata from local kubelet instead of API server -- critical at scale |
| `Kube_Meta_Cache_TTL: 60` | Cache metadata for 60+ seconds to reduce API calls |
| `Buffer_Chunk_Size` / `Buffer_Max_Size` | Tune for log volume to prevent backpressure |

For Fargate pods, use the built-in Fluent Bit sidecar -- configure via Fargate profile to send logs to CloudWatch Logs.

### Log Retention Strategy

| Log Type | Retention | Reason |
|----------|-----------|--------|
| **Audit logs** | 90-365 days | Compliance, forensics |
| **Application logs** | 14-30 days | Debugging |
| **Control plane logs** | 30-90 days | Troubleshooting |
| **Access logs (ALB)** | 90 days | Security review |

**Cost optimization -- hot/warm/cold architecture:**
- **Hot (0-30 days):** CloudWatch Logs -- fast queries with Logs Insights
- **Warm (30-90 days):** Export to S3 Standard/IA via subscription filters
- **Cold (90+ days):** S3 Glacier for compliance retention

### Structured Logging

DO:
- Output logs as JSON for structured parsing
- Include request ID, trace ID, and user context in every log line
- Log at appropriate levels (ERROR, WARN, INFO)
- Use Kubernetes labels/annotations to add metadata

DON'T:
- Log sensitive data (tokens, passwords, PII)
- Use unstructured text logs in production
- Log at DEBUG level in production (volume + cost)

---

## Distributed Tracing

### AWS Distro for OpenTelemetry (ADOT)

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: adot-collector
spec:
  mode: daemonset
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    exporters:
      awsxray:
        region: us-east-1
    service:
      pipelines:
        traces:
          receivers: [otlp]
          exporters: [awsxray]
```

### X-Ray vs OpenTelemetry

| Factor | AWS X-Ray | OpenTelemetry + Jaeger/Tempo |
|--------|-----------|------------------------------|
| **Setup** | Simple with ADOT | More configuration |
| **AWS integration** | Native (Lambda, API GW, etc.) | Manual |
| **Vendor lock-in** | AWS-specific | Vendor-neutral |
| **Querying** | X-Ray console, CloudWatch | Grafana (richer) |
| **Cost** | Per trace recorded | Storage-dependent |

### Strategic Sampling

Not all traces need the same sampling rate. Configure higher rates for critical paths and lower rates for high-volume, low-value routes:

| Traffic Type | Suggested Rate | Rationale |
|-------------|---------------|-----------|
| **Critical user paths** (checkout, login) | 100% or high | Full visibility for business-critical flows |
| **Health checks, readiness probes** | 0-1% | High volume, low diagnostic value |
| **Internal service-to-service** | 5-10% | Balance cost with troubleshooting needs |

Use X-Ray sampling rules or OpenTelemetry tail-based sampling in the ADOT collector to implement this.

---

## GPU and AI/ML Observability

For clusters running GPU workloads (training, inference), standard CPU/memory metrics are insufficient. GPU utilization, memory, power, and SM activity need dedicated monitoring.

### GPU Metrics

| Metric | Source | What It Tells You |
|--------|--------|-------------------|
| `DCGM_FI_DEV_GPU_UTIL` | DCGM Exporter | GPU utilization % (time executing any kernel) |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | DCGM Exporter | Memory controller utilization |
| `DCGM_FI_DEV_POWER_USAGE` | DCGM Exporter | Power draw -- best proxy for actual GPU engagement |
| `DCGM_FI_DEV_SM_ACTIVE` | DCGM Exporter | Streaming multiprocessor activity -- true parallelism |
| `DCGM_FI_DEV_XID_ERRORS` | DCGM Exporter | GPU error codes -- non-zero needs investigation |

GPU Utilization alone is misleading -- 100% can mean one lightweight kernel or full parallel workloads. Compare power draw against Thermal Design Power (TDP) to spot real underutilization.

### Collecting GPU Metrics

The CloudWatch Observability add-on auto-deploys DCGM Exporter on GPU nodes. Alternatively, deploy DCGM Exporter manually with Prometheus:

```bash
helm install dcgm-exporter gpu-helm-charts/dcgm-exporter \
  --namespace monitoring --create-namespace
```

### Inference Framework Metrics

| Framework | Native Metrics | Key Signals |
|-----------|---------------|-------------|
| **vLLM** | Yes | Request latency, memory usage, token throughput |
| **Ray Serve** | Yes | Task execution time, resource utilization, autoscaling state |
| **Hugging Face TGI** | Yes | Inference latency, batch size, queue depth |

These frameworks expose Prometheus endpoints -- scrape them alongside DCGM Exporter for full-stack GPU observability.

---

## Detective Controls

### EKS Audit Logging

```bash
# Enable all control plane log types
aws eks update-cluster-config \
  --name my-cluster \
  --logging '{
    "clusterLogging": [{
      "types": ["api", "audit", "authenticator", "controllerManager", "scheduler"],
      "enabled": true
    }]
  }'
```

**Key audit queries (CloudWatch Logs Insights):**

```
# Who created/deleted resources in last 24h
fields @timestamp, user.username, verb, objectRef.resource, objectRef.name, objectRef.namespace
| filter verb in ["create", "delete", "patch"]
| filter objectRef.resource not in ["events", "leases", "endpoints"]
| sort @timestamp desc
| limit 100

# Failed API calls (potential unauthorized access)
fields @timestamp, user.username, verb, objectRef.resource, responseStatus.code
| filter responseStatus.code >= 400
| sort @timestamp desc
| limit 50

# Exec into pods (security concern)
fields @timestamp, user.username, objectRef.namespace, objectRef.name
| filter objectRef.subresource = "exec"
| sort @timestamp desc

# RBAC changes
fields @timestamp, @message
| filter objectRef.resource in ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]
| filter verb in ["create", "update", "patch", "delete"]
| sort @timestamp desc
```

### Amazon GuardDuty for EKS

| Finding | Severity | Meaning |
|---------|----------|---------|
| `PrivilegeEscalation:Kubernetes/PrivilegedContainer` | High | Privileged container launched |
| `Persistence:Kubernetes/ContainerWithSensitiveMount` | Medium | Sensitive host path mounted |
| `Policy:Kubernetes/ExposedDashboard` | Medium | K8s dashboard exposed |
| `CredentialAccess:Kubernetes/MaliciousIPCaller` | High | API call from known malicious IP |
| `Impact:Runtime/CryptoCurrencyMiningDetected` | High | Crypto mining in container |

### CloudTrail for EKS

All `eks:*` API calls are logged. Key events to monitor:
- `CreateAccessEntry` / `DeleteAccessEntry` -- access changes
- `UpdateClusterConfig` -- cluster configuration changes
- `AssociateAccessPolicy` -- permission grants
- `CreateAddon` / `DeleteAddon` -- add-on changes

Use CloudTrail Insights to automatically detect unusual API activity patterns, including from pods using IRSA.

---

## Alerting Patterns

### Critical Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| **Node NotReady** | Node condition NotReady > 5 min | Critical |
| **Pod CrashLooping** | Restarts > 5 in 10 min | High |
| **PVC Pending** | PVC pending > 15 min | High |
| **API Server Errors** | 5xx rate > 1% | Critical |
| **Certificate Expiry** | < 30 days | Warning |
| **Disk Pressure** | Node disk > 85% | Warning |
| **OOMKilled** | Any OOMKilled event | High |
| **ENA allowance exceeded** | Any `_exceeded` metric > 0 | High |
| **APF requests dropped** | `flowcontrol_rejected_requests_total` > 0 | Warning |

### Prometheus Alert Rules

```yaml
groups:
- name: eks-alerts
  rules:
  - alert: PodCrashLooping
    expr: increase(kube_pod_container_status_restarts_total[10m]) > 5
    for: 5m
    labels:
      severity: high
    annotations:
      summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} is crash looping"

  - alert: NodeMemoryPressure
    expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Node {{ $labels.node }} has memory pressure"

  - alert: DNSThrottling
    expr: rate(node_ethtool_linklocal_allowance_exceeded[5m]) > 0
    for: 2m
    labels:
      severity: high
    annotations:
      summary: "DNS throttling detected on {{ $labels.instance }}"
```

### Avoiding Alert Fatigue

- Use multi-stage thresholds: warning before critical
- Correlate related alerts (node pressure + pod evictions = one incident, not two)
- Implement maintenance windows to suppress during planned changes
- Include runbook links and context (cluster name, namespace, pod) in every alert
- Track false positive rates and refine thresholds quarterly

---

## Monitoring High Availability

### Architecture Principles

| Principle | Implementation |
|-----------|---------------|
| **Cross-AZ redundancy** | Deploy monitoring components across multiple AZs |
| **Use managed services** | AMP, AMG, CloudWatch eliminate self-managed HA concerns |
| **Monitor the monitors** | Deploy a secondary lightweight system to alert on monitoring failures |
| **Redundant alerting** | Multiple notification channels (SNS + Slack + PagerDuty) |
| **Dedicated compute** | Run monitoring workloads on dedicated node groups to avoid contention |

### Self-Managed Prometheus HA

If running self-managed Prometheus (not AMP), pair it with Thanos or Cortex for:
- Long-term storage (S3-backed)
- Query federation across replicas
- Deduplication of metrics from HA pairs

AMP eliminates this complexity -- it handles replication, storage, and HA automatically.

---

## Multi-Tenant Observability Isolation

In multi-tenant EKS platforms, each tenant needs isolated observability data to prevent cross-tenant visibility and enable accurate cost attribution.

### OTEL Routing Processor

Use the OpenTelemetry routing processor to direct telemetry to tenant-specific backends based on resource attributes. The routing processor inspects an attribute on incoming telemetry (typically `k8s.namespace.name`) and routes matching data to the appropriate exporter. Each tenant maps to a dedicated AMP workspace (or other backend), while unmatched data falls through to a default platform exporter.

**Routing configuration pattern:**

| Routing Attribute | Match Pattern | Target Backend | Purpose |
|-------------------|--------------|----------------|---------|
| `k8s.namespace.name` | `team-a-*` | AMP workspace for Team A | Isolate Team A metrics |
| `k8s.namespace.name` | `team-b-*` | AMP workspace for Team B | Isolate Team B metrics |
| (default) | All other namespaces | Platform AMP workspace | Platform/shared metrics |

### Per-Tenant CloudWatch Isolation

| Data Type | Isolation Method | Naming Convention |
|-----------|-----------------|-------------------|
| **Log groups** | Separate log group per tenant | `/eks/<cluster>/<tenant>/application` |
| **Metric namespaces** | Metric dimensions by tenant | `EKS/Tenant/<tenant-name>` |
| **Dashboards** | Grafana workspace per tenant or folder-based RBAC | `<tenant>-overview`, `<tenant>-alerts` |
| **Alerts** | Per-tenant SNS topics | `eks-<tenant>-critical`, `eks-<tenant>-warning` |

### Isolated Grafana Dashboards

**Option A: Amazon Managed Grafana with workspace-per-tenant**
- Each tenant gets their own AMG workspace
- IAM Identity Center groups control access
- Highest isolation but highest cost

**Option B: Single AMG workspace with folder-based RBAC**
- One workspace with per-tenant folders
- Grafana Teams map to IAM Identity Center groups
- Team permissions scoped to their folder only
- Lower cost, moderate isolation

---

## Tiered Log Retention Architecture

For cost-effective log management, implement a tiered retention strategy that balances query performance with storage costs.

### Tier Architecture

```
Application Logs
     |
     v
CloudWatch Logs (Hot Tier)
  |-- Retention: 7-14 days
  |-- Use: Real-time debugging, recent incident investigation
  +-- Cost: ~$0.50/GB ingestion + $0.03/GB/month storage
     |
     v (Subscription Filter)
Kinesis Data Firehose
     |
     v
S3 Bucket (Warm Tier)
  |-- Storage class: S3 Intelligent-Tiering
  |-- Retention: 30-90 days
  |-- Use: Historical analysis, compliance queries via Athena
  +-- Cost: ~$0.023/GB/month (Frequent) -> $0.0125/GB/month (Infrequent)
     |
     v (Lifecycle Rule)
S3 Glacier (Cold Tier)
  |-- Storage class: Glacier Flexible Retrieval
  |-- Retention: 90 days - 7 years (per compliance)
  |-- Use: Compliance archive, audit, legal hold
  +-- Cost: ~$0.004/GB/month
```

### CloudWatch Subscription Filter

To stream logs from CloudWatch to S3 for archival, create a subscription filter on each log group. The filter forwards matching log events to a Kinesis Data Firehose delivery stream, which batches and writes them to an S3 bucket. Use an empty filter pattern to forward all events, or specify a pattern to selectively archive (e.g., only ERROR-level logs).

### Retention Policy by Log Type

| Log Type | Hot (CloudWatch) | Warm (S3 Standard) | Cold (Glacier) | Total Retention |
|----------|------------------|-------------------|----------------|-----------------|
| **Application logs** | 7 days | 23 days | 335 days | 1 year |
| **Audit logs** | 30 days | 60 days | 275 days | 1 year |
| **Security logs** | 30 days | 60 days | 6+ years | 7 years (compliance) |
| **Control plane logs** | 14 days | 76 days | — | 90 days |
| **Access logs (ALB)** | 14 days | 76 days | — | 90 days |

### Querying Archived Logs

For warm-tier logs stored in S3, use Amazon Athena with partition projection for efficient queries. Create an Athena table partitioned by year, month, day, and optionally tenant namespace. Athena can then query the archived logs using standard SQL, filtering by time range, namespace, log level, and other fields. Partition projection eliminates the need to run `MSCK REPAIR TABLE` as new partitions arrive automatically.

---

**Sources:**
- [AWS EKS Best Practices Guide -- Observability](https://docs.aws.amazon.com/eks/latest/best-practices/observability.html)
- [AWS EKS Best Practices Guide -- Control Plane Monitoring](https://docs.aws.amazon.com/eks/latest/best-practices/control_plane_monitoring.html)
- [AWS EKS Best Practices Guide -- Network Performance Monitoring](https://docs.aws.amazon.com/eks/latest/best-practices/monitoring_eks_workloads_for_network_performance_issues.html)
- [AWS EKS Best Practices Guide -- Auditing and Logging](https://docs.aws.amazon.com/eks/latest/best-practices/auditing-and-logging.html)
- [AWS EKS Best Practices Guide -- AI/ML Observability](https://docs.aws.amazon.com/eks/latest/best-practices/aiml-observability.html)
- [AWS Prescriptive Guidance -- EKS Observability Best Practices](https://docs.aws.amazon.com/prescriptive-guidance/latest/amazon-eks-observability-best-practices/introduction.html)
- [CloudWatch Application Signals for EKS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-EKS.html)
- [AWS Observability Best Practices](https://aws-observability.github.io/observability-best-practices/)
