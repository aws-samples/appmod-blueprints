# Observability Setup Comparison: Accelerator vs. New Approach

## Overview
This document compares the terraform-aws-observability-accelerator module setup with our new GitOps-based approach.

---

## Component Comparison

### 1. Amazon Managed Grafana (AMG)
| Feature | Accelerator | New Approach | Status |
|---------|-------------|--------------|--------|
| Workspace Creation | ✅ Via Terraform | ✅ Via Terraform | ✅ Same |
| SAML Configuration | ✅ Configured | ✅ Configured | ✅ Same |
| API Keys | ✅ Created | ✅ Created | ✅ Same |
| Data Sources | ✅ AMP, CloudWatch, X-Ray | ✅ AMP, CloudWatch, X-Ray | ✅ Same |

### 2. Amazon Managed Prometheus (AMP)
| Feature | Accelerator | New Approach | Status |
|---------|-------------|--------------|--------|
| Workspace Creation | ✅ Via Terraform | ✅ Via Terraform | ✅ Same |
| Metrics Collection | ✅ ADOT Collector | ✅ AWS Prometheus Scraper | ✅ Different (Native AWS Service) |
| Recording Rules | ✅ Deployed via Terraform | ❌ Not implemented | ⚠️ Optional |
| Alerting Rules | ✅ Deployed via Terraform | ❌ Not implemented | ⚠️ Optional |

### 3. Metrics Collection Components

#### Accelerator Approach
```
ADOT Operator (Helm via Terraform)
  ├── OpenTelemetry Collector (deployed as DaemonSet/Deployment)
  ├── Scrapes metrics from pods/services
  ├── Sends to AMP via remote_write
  └── Requires cert-manager (deployed by module)
```

#### New Approach
```
AWS Prometheus Scraper (Native AWS Service)
  ├── Managed by AWS (no operator needed)
  ├── Scrapes metrics directly from EKS
  ├── Sends to AMP natively
  └── Uses existing cert-manager (via ArgoCD)
```

### 4. Kubernetes Components

| Component | Accelerator | New Approach | Deployment Method |
|-----------|-------------|--------------|-------------------|
| **kube-state-metrics** | ✅ Deployed via Helm | ✅ Deployed via ArgoCD | GitOps (hub-config.yaml) |
| **prometheus-node-exporter** | ✅ Deployed via Helm | ✅ Deployed via ArgoCD | GitOps (hub-config.yaml) |
| **cert-manager** | ✅ Deployed by module | ✅ Already via ArgoCD | Reused existing |
| **external-secrets** | ✅ Deployed by module | ✅ Already via ArgoCD | Reused existing |
| **grafana-operator** | ✅ Deployed by module | ✅ Already via ArgoCD | Reused existing |
| **ADOT Operator** | ✅ Deployed via Helm | ❌ Not deployed | Not needed with Scraper |
| **OpenTelemetry Collector** | ✅ Deployed via Helm | ❌ Not deployed | Not needed with Scraper |

### 5. Grafana Dashboards

| Dashboard | Accelerator | New Approach | Source |
|-----------|-------------|--------------|--------|
| Cluster Overview | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Namespace Workloads | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Node Exporter | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Nodes | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Workloads | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Kubelet | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| Java/JMX | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| NGINX | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| API Server (Basic) | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| API Server (Advanced) | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |
| API Server (Troubleshooting) | ✅ Via Grafana Operator | ✅ Via Grafana Operator | GitOps |

**Dashboard URLs**: All dashboards reference the same GitHub raw URLs from the accelerator repository.

### 6. Metrics Scraping Configuration

#### Accelerator Scrape Jobs
The accelerator deployed these via OpenTelemetry Collector configuration:
- kubernetes-apiservers
- kubernetes-nodes
- kubernetes-nodes-cadvisor
- kubelet
- kube-state-metrics
- node-exporter
- adot-collector (self-monitoring)
- custom-metrics (port 8080)
- java-jmx
- nginx-ingress
- kubernetes-service-endpoints
- kubernetes-pods
- coredns
- aws-cni-metrics
- karpenter

#### New Approach Scrape Jobs
All the same jobs are configured in `scraper-config-accelerator.yaml`:
- ✅ All accelerator jobs included
- ✅ Same metric relabeling rules
- ✅ Same filtering and dropping rules
- ✅ Custom metrics on port 8080 with unspecified prefix dropping

### 7. Secrets Management

| Secret | Accelerator | New Approach | Method |
|--------|-------------|--------------|--------|
| Grafana API Key | ✅ kubectl_manifest | ✅ ExternalSecret | GitOps (grafana-dashboards chart) |
| Grafana MySQL Creds | ❌ Not managed | ✅ ExternalSecret | GitOps (grafana-dashboards chart) |
| Storage | AWS Secrets Manager | AWS Secrets Manager | Same |

---

## What We're NOT Implementing (Optional Features)

### 1. Prometheus Recording Rules
**What they do**: Pre-compute expensive queries and store as new metrics
**Accelerator had**: 
- Infrastructure recording rules (CPU, memory aggregations)
- Java-specific recording rules
- NGINX-specific recording rules

**Why not needed now**: 
- Can be added later via Terraform if needed
- AMP supports recording rules natively
- Not critical for initial observability

### 2. Prometheus Alerting Rules
**What they do**: Define alert conditions based on metrics
**Accelerator had**:
- Node alerts (high CPU, memory, disk)
- Pod alerts (crash loops, OOM kills)
- API server alerts
- Java-specific alerts
- NGINX-specific alerts

**Why not needed now**:
- Can be added later via Terraform if needed
- AMG has unified alerting enabled
- Teams can define their own alerts in Grafana

### 3. Alert Manager Configuration
**What it does**: Routes alerts to notification channels
**Accelerator had**: Basic configuration for SNS integration

**Why not needed now**:
- AMG unified alerting handles this
- Can be configured in Grafana UI
- More flexible for teams to manage

---

## Key Differences Summary

### Advantages of New Approach

1. **Native AWS Service**: Prometheus Scraper is fully managed by AWS
   - No operator pods to maintain
   - No ADOT collector resource overhead
   - Automatic scaling and HA

2. **Reduced Complexity**: 
   - Fewer Helm releases to manage
   - No Terraform-managed Kubernetes resources
   - Leverages existing ArgoCD-deployed components

3. **GitOps Alignment**:
   - All Kubernetes resources via ArgoCD
   - Dashboards deployed declaratively
   - Easier to version control and audit

4. **Cost Optimization**:
   - No ADOT collector pods consuming cluster resources
   - Scraper runs outside cluster (AWS-managed)

5. **Separation of Concerns**:
   - Terraform: AWS resources (AMG, AMP, Scraper)
   - ArgoCD: Kubernetes resources (exporters, operators)
   - Clear boundaries

### What We Kept from Accelerator

1. ✅ All dashboard definitions (same URLs)
2. ✅ All scrape job configurations
3. ✅ Grafana Operator for dashboard management
4. ✅ External Secrets for credential management
5. ✅ Same metrics collection scope
6. ✅ Same custom metrics patterns

### What Changed

1. 🔄 ADOT Collector → AWS Prometheus Scraper
2. 🔄 Helm deployments → ArgoCD deployments
3. 🔄 Terraform-managed K8s resources → GitOps-managed
4. ❌ Recording rules (can add later if needed)
5. ❌ Alerting rules (can add later if needed)

---

## Configuration Files Reference

### New Approach Files
```
appmod-blueprints/
├── platform/infra/terraform/
│   ├── hub-config.yaml                          # Addon enablement
│   └── common/
│       ├── observability.tf                     # AMG, AMP, Scraper
│       └── manifests/
│           └── scraper-config-accelerator.yaml  # Scrape configuration
└── gitops/addons/charts/grafana-dashboards/
    └── templates/
        ├── observability-dashboards.yaml        # Dashboard CRs
        ├── external-secret.yaml                 # Grafana credentials
        ├── datasources.yaml                     # AMG data sources
        └── grafana.yaml                         # Grafana instance CR
```

### Enabled Addons (hub-config.yaml)
```yaml
spoke-dev & spoke-prod:
  enable_kube_state_metrics: true
  enable_prometheus_node_exporter: true
  enable_prometheus_scraper: true
  enable_cni_metrics_helper: true
  enable_cert_manager: true          # Already enabled
  enable_external_secrets: true      # Already enabled
  enable_grafana_operator: true      # Already enabled (hub only)
```

---

## Migration Impact

### No Impact (Already Working)
- ✅ Existing metrics collection continues
- ✅ Existing dashboards remain functional
- ✅ Grafana access unchanged
- ✅ SAML authentication unchanged

### Improvements
- ✅ Reduced cluster resource usage (no ADOT pods)
- ✅ Simplified troubleshooting (fewer moving parts)
- ✅ Better GitOps alignment
- ✅ Easier to audit and version control

### To Add Later (If Needed)
- Recording rules for query optimization
- Alerting rules for proactive monitoring
- Alert Manager routing configuration

---

## Validation Checklist

After deployment, verify:

- [ ] AMG workspace accessible
- [ ] AMP workspace receiving metrics
- [ ] Prometheus Scraper running (check AWS console)
- [ ] kube-state-metrics pods running in clusters
- [ ] prometheus-node-exporter pods running in clusters
- [ ] Grafana dashboards visible in AMG
- [ ] Dashboards showing data from both clusters
- [ ] Custom metrics (port 8080) being scraped
- [ ] Java/JMX metrics visible (if Java apps deployed)
- [ ] NGINX metrics visible

---

## Conclusion

The new approach provides **equivalent observability** to the accelerator module while:
- Using native AWS services (Prometheus Scraper)
- Following GitOps best practices
- Reducing operational complexity
- Maintaining all dashboard and metrics collection capabilities

Recording and alerting rules can be added later via Terraform if teams require them, but the core observability stack is complete and functional.
