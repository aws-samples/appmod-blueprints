# Module: Add-ons

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect add-on inventory - EKS-managed add-ons, Helm releases, manifest-installed components

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [EKS-Managed Add-ons](#1-eks-managed-add-ons)
  - [Helm Releases](#2-helm-releases)
  - [Common Platform Components](#3-common-platform-components)
  - [Custom Resource Definitions](#4-custom-resource-definitions-crds)
- [Output Schema](#output-schema)
- [Add-on Health Check](#add-on-health-check)
- [Edge Cases](#edge-cases)
  - [Self-Managed vs EKS-Managed](#self-managed-vs-eks-managed)
  - [Add-on Version Compatibility](#add-on-version-compatibility)
  - [Helm Release in Pending State](#helm-release-in-pending-state)
  - [Orphaned Resources](#orphaned-resources)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `list_eks_resources`, `describe_eks_resource`, `list_k8s_resources`
- **CLI fallback:** `aws eks`, `kubectl`, `helm`

---

## Detection Strategy

Add-ons can be installed via multiple mechanisms:

```
1. EKS-managed add-ons  -> AWS manages lifecycle, uses EKS add-on API
2. Helm releases        -> Installed via Helm, tracked in secrets
3. Manifest-installed   -> Raw YAML applied, no tracking metadata
4. Operator-managed     -> CRDs and controllers (e.g., cert-manager)
```

---

## Detection Commands

### 1. EKS-Managed Add-ons

**MCP:**
```
list_eks_resources(
  resource_type="addon",
  cluster_name="<cluster-name>"
)
```

For each add-on:
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="<addon-name>"
)
```

**CLI:**
```bash
# List all EKS-managed add-ons
aws eks list-addons --cluster-name <cluster-name> --query 'addons'

# Get details for each add-on
aws eks describe-addon --cluster-name <cluster-name> --addon-name <addon-name> \
  --query 'addon.{
    name:addonName,
    version:addonVersion,
    status:status,
    serviceAccountRoleArn:serviceAccountRoleArn,
    configurationValues:configurationValues
  }'
```

**Core EKS add-ons to check:**
- `vpc-cni` (Amazon VPC CNI)
- `coredns` (DNS resolution)
- `kube-proxy` (Service networking)
- `aws-ebs-csi-driver` (EBS volumes)
- `aws-efs-csi-driver` (EFS volumes)
- `eks-pod-identity-agent` (Pod Identity)
- `amazon-cloudwatch-observability` (Container Insights)
- `aws-mountpoint-s3-csi-driver` (S3 mounts)
- `snapshot-controller` (Volume snapshots)

### 2. Helm Releases

Use Helm detection when you need to inventory third-party components that were installed via Helm charts. Many platform teams use Helm for add-ons not available as EKS-managed add-ons.

**CLI (Helm required):**
```bash
# List all Helm releases across namespaces
helm list -A --output json 2>/dev/null | jq -r '.[] | {name: .name, namespace: .namespace, chart: .chart, version: .app_version, status: .status}'
```

**Example output:**
```json
{
  "name": "aws-load-balancer-controller",
  "namespace": "kube-system",
  "chart": "aws-load-balancer-controller-1.6.2",
  "version": "v2.6.2",
  "status": "deployed"
}
{
  "name": "external-dns",
  "namespace": "external-dns",
  "chart": "external-dns-1.13.1",
  "version": "0.13.6",
  "status": "deployed"
}
```

**Alternative (kubectl, no Helm CLI):**

Use this approach when Helm CLI is not installed but you still need to detect Helm-managed releases. Helm stores release metadata as Kubernetes secrets.

```bash
# Helm stores releases as secrets with label owner=helm
kubectl get secrets -A -l owner=helm,status=deployed -o json 2>/dev/null | \
  jq -r '.items[] | {
    name: .metadata.labels["name"],
    namespace: .metadata.namespace,
    version: .metadata.labels["version"]
  }'
```

### 3. Common Platform Components

Check for common components that may be manifest-installed:

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="kube-system"
)
```

**CLI:**
```bash
# List deployments in kube-system
kubectl get deploy -n kube-system -o json | jq -r '.items[].metadata.name'

# List deployments across all namespaces with common labels
kubectl get deploy -A -o json | jq -r '
  .items[] | 
  select(.metadata.labels["app.kubernetes.io/name"] != null) |
  {
    name: .metadata.labels["app.kubernetes.io/name"],
    namespace: .metadata.namespace,
    component: .metadata.labels["app.kubernetes.io/component"]
  }'
```

**Common components to detect:**
- AWS Load Balancer Controller
- External DNS
- Cert-Manager
- Metrics Server
- Cluster Autoscaler
- Karpenter (covered in compute module)
- External Secrets Operator
- Secrets Store CSI Driver

### 4. Custom Resource Definitions (CRDs)

Check CRDs to identify operators and controllers that extend Kubernetes functionality. CRDs reveal what platform capabilities are available even when the component was installed via raw manifests without Helm tracking.

```bash
# List all CRDs (indicates operators/controllers)
kubectl get crds -o json | jq -r '.items[].metadata.name' | sort
```

**Example output:**
```
certificates.cert-manager.io
clusterissuers.cert-manager.io
externalsecrets.external-secrets.io
issuers.cert-manager.io
nodepools.karpenter.sh
provisioners.karpenter.sh
secretstores.external-secrets.io
```

**Common CRD patterns:**
- `*.cert-manager.io` -> cert-manager
- `*.argoproj.io` -> ArgoCD
- `*.karpenter.sh` -> Karpenter
- `*.external-secrets.io` -> External Secrets
- `*.kyverno.io` -> Kyverno
- `*.gatekeeper.sh` -> OPA Gatekeeper
- `*.istio.io` -> Istio

---

## Output Schema

```yaml
addons:
  eks_managed:
    - name: string
      version: string
      status: string          # ACTIVE, CREATING, UPDATING, DEGRADED, DELETING
      service_account_role: string  # Pod Identity/IRSA role ARN
      configuration: object   # Custom configuration values
      
  helm_releases:
    - name: string
      namespace: string
      chart: string
      version: string
      status: string          # deployed, failed, pending-*
      
  platform_components:
    aws_load_balancer_controller:
      detected: bool
      version: string
      namespace: string
      
    external_dns:
      detected: bool
      version: string
      
    cert_manager:
      detected: bool
      version: string
      
    metrics_server:
      detected: bool
      version: string
      
    external_secrets:
      detected: bool
      version: string
      
    secrets_store_csi:
      detected: bool
      version: string
      
  crds:
    count: int
    notable: list           # CRDs that indicate specific tools
```

---

## Add-on Health Check

Run health checks before cluster upgrades to identify degraded add-ons that need attention. Upgrading a cluster with unhealthy add-ons can cause cascading failures.

For each EKS-managed add-on, check health:

```bash
# Check if add-on pods are running
kubectl get pods -n kube-system -l "app.kubernetes.io/name=<addon-name>" \
  --field-selector status.phase!=Running 2>/dev/null
```

**Example output (healthy - no results):**
```
No resources found in kube-system namespace.
```

**Example output (unhealthy):**
```
NAME                       READY   STATUS             RESTARTS   AGE
coredns-7f89c5b6d8-abc12   0/1     CrashLoopBackOff   5          10m
```

**Status interpretation:**
- `ACTIVE` - Add-on is healthy
- `CREATING` - Add-on is being installed
- `UPDATING` - Add-on is being updated
- `DEGRADED` - Add-on has issues (check pod status)
- `DELETING` - Add-on is being removed

---

## Edge Cases

### Self-Managed vs EKS-Managed

Some add-ons can be installed both ways. Distinguishing between them matters because EKS-managed add-ons receive automatic security patches and have validated compatibility with EKS versions, while self-managed add-ons require manual updates.

- Check EKS add-on API first
- If not found but component exists, it's self-managed

```bash
# Example: VPC CNI might be self-managed
kubectl get daemonset -n kube-system aws-node -o jsonpath='{.metadata.labels}' 2>/dev/null
```

**Example output (EKS-managed):**
```json
{"app.kubernetes.io/managed-by":"eks","app.kubernetes.io/name":"aws-node"}
```

**Example output (self-managed - no eks label):**
```json
{"app":"aws-node","k8s-app":"aws-node"}
```

### Add-on Version Compatibility

Check version compatibility when planning Kubernetes version upgrades. Some add-on versions only work with specific Kubernetes versions, and upgrading the cluster without updating add-ons can break workloads.

```bash
# Get compatible versions for target K8s version
aws eks describe-addon-versions \
  --addon-name vpc-cni \
  --kubernetes-version <target-version> \
  --query 'addons[0].addonVersions[0:3].addonVersion'
```

**Example output:**
```json
[
    "v1.15.1-eksbuild.1",
    "v1.15.0-eksbuild.2",
    "v1.14.1-eksbuild.1"
]
```

### Helm Release in Pending State

Detect stuck Helm releases before upgrades. Pending releases indicate failed or interrupted installations that can block subsequent operations on the same release.

```bash
# Check for stuck Helm releases
helm list -A --pending --output json 2>/dev/null
```

**Example output (stuck release):**
```json
[{
  "name": "failed-release",
  "namespace": "default",
  "status": "pending-install",
  "chart": "my-chart-1.0.0"
}]
```

### Orphaned Resources

Check for orphaned CRDs when you suspect incomplete add-on uninstalls. Orphaned CRDs can cause confusion during reinstallation and may contain stale custom resources.

```bash
# Check for CRDs without controller
kubectl get crds -o json | jq -r '
  .items[] | 
  select(.status.conditions[].type == "NamesAccepted" and .status.conditions[].status == "True") |
  .metadata.name'
```

Cross-reference with running deployments to identify orphans:
```bash
# List CRDs and check if their controller exists
kubectl get crds -o name | while read crd; do
  group=$(echo $crd | sed 's/.*\.//')
  echo "CRD: $crd"
done
```

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| vpc-cni not EKS-managed | Consider migrating to EKS add-on for managed updates |
| Multiple ingress controllers | Consolidate to AWS LBC or document routing strategy |
| No external secrets solution | Consider ESO or Secrets Store CSI for secrets management |
| CAS detected (not Karpenter) | Consider migrating to Karpenter for better scaling |
| Degraded add-ons | Investigate pod logs before proceeding with upgrades |
