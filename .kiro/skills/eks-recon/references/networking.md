# Module: Networking

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect network configuration - VPC CNI, ingress controllers, service mesh, DNS

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [1. VPC CNI Configuration](#1-vpc-cni-configuration)
  - [2. Ingress Controllers](#2-ingress-controllers)
  - [3. Service Mesh Detection](#3-service-mesh-detection)
  - [4. DNS Configuration](#4-dns-configuration)
  - [5. Network Policies](#5-network-policies)
- [Output Schema](#output-schema)
- [Edge Cases](#edge-cases)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `describe_eks_resource`, `get_eks_vpc_config`, `list_k8s_resources`
- **CLI fallback:** `aws eks`, `kubectl`

---

## Detection Strategy

Network configuration spans multiple layers:

```
1. VPC CNI          -> Pod networking mode and configuration
2. Ingress          -> How external traffic enters the cluster
3. Service Mesh     -> Service-to-service communication
4. DNS              -> CoreDNS configuration
5. Network Policies -> Pod-to-pod traffic control
```

---

## Detection Commands

### 1. VPC CNI Configuration

**Why check this:** VPC CNI mode directly impacts pod IP capacity and networking behavior. Prefix delegation can increase pods-per-node from ~29 to ~110 on m5.large. Custom networking is required when pod subnets differ from node subnets.

**MCP:**
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="vpc-cni"
)
```

```
get_eks_vpc_config(
  cluster_name="<cluster-name>"
)
```

**CLI:**
```bash
# Get VPC CNI add-on status
aws eks describe-addon --cluster-name <cluster-name> --addon-name vpc-cni \
  --query 'addon.{version:addonVersion,status:status,config:configurationValues}'

# Get CNI configuration from aws-node DaemonSet
kubectl get daemonset aws-node -n kube-system -o json | jq -r '
  .spec.template.spec.containers[0].env | 
  map(select(.name | startswith("AWS_") or startswith("ENABLE_"))) |
  from_entries'
```

**VPC CNI Mode Detection:**

```bash
# Check for prefix delegation
kubectl get daemonset aws-node -n kube-system -o json | \
  jq -r '.spec.template.spec.containers[0].env[] | select(.name=="ENABLE_PREFIX_DELEGATION") | .value'

# Check for custom networking
kubectl get eniconfigs.crd.k8s.amazonaws.com 2>/dev/null | head -5
```

**Modes:**
- **Secondary IP** (default): `ENABLE_PREFIX_DELEGATION` not set or `false`
- **Prefix Delegation**: `ENABLE_PREFIX_DELEGATION=true`
- **Custom Networking**: ENIConfig CRDs exist

**Example output (prefix delegation enabled):**
```json
{
  "ENABLE_PREFIX_DELEGATION": "true",
  "WARM_PREFIX_TARGET": "1",
  "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "false"
}
```

### 2. Ingress Controllers

**Why check this:** Ingress controllers determine how external traffic reaches cluster services. Multiple controllers may coexist (e.g., AWS LBC for ALB/NLB, nginx for internal routing). Understanding the ingress topology is essential for troubleshooting connectivity issues.

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
# AWS Load Balancer Controller
kubectl get deploy -n kube-system aws-load-balancer-controller 2>/dev/null

# NGINX Ingress Controller
kubectl get deploy -A -l "app.kubernetes.io/name=ingress-nginx" 2>/dev/null

# Traefik
kubectl get deploy -A -l "app.kubernetes.io/name=traefik" 2>/dev/null

# Kong
kubectl get deploy -A -l "app=kong" 2>/dev/null

# List all IngressClasses
kubectl get ingressclasses -o json | jq -r '.items[] | {name: .metadata.name, controller: .spec.controller}'
```

**Check for Gateway API:**
```bash
# Gateway API CRDs
kubectl get crds | grep -E "gateways|httproutes|grpcroutes" 2>/dev/null

# Gateway resources
kubectl get gateways.gateway.networking.k8s.io -A 2>/dev/null | head -10
```

**Example output (IngressClasses):**
```json
{"name": "alb", "controller": "ingress.k8s.aws/alb"}
{"name": "nginx", "controller": "k8s.io/ingress-nginx"}
```

### 3. Service Mesh Detection

**Why check this:** Service meshes add mTLS, observability, and traffic management at the application layer. Detecting mesh presence explains sidecar containers, elevated resource usage, and additional CRDs. The mesh type affects troubleshooting approaches.

**Istio:**
```bash
# Check for Istio control plane
kubectl get deploy -n istio-system istiod 2>/dev/null

# Check for Istio sidecar injection
kubectl get ns -l istio-injection=enabled -o name 2>/dev/null

# Get Istio version
kubectl get deploy -n istio-system istiod -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null

# Check for ambient mode
kubectl get daemonset -n istio-system ztunnel 2>/dev/null
```

**AWS App Mesh:**
```bash
# Check for App Mesh controller
kubectl get deploy -n appmesh-system appmesh-controller 2>/dev/null

# Check for virtual services
kubectl get virtualservices.appmesh.k8s.aws -A 2>/dev/null | head -5
```

**Linkerd:**
```bash
# Check for Linkerd
kubectl get deploy -n linkerd linkerd-destination 2>/dev/null
```

**Example output (Istio detected):**
```
NAME     READY   UP-TO-DATE   AVAILABLE   AGE
istiod   2/2     2            2           45d
```
```
namespace/default
namespace/production
namespace/staging
```

### 4. DNS Configuration

**Why check this:** CoreDNS is critical for service discovery. Misconfigured DNS causes intermittent connectivity failures. NodeLocal DNSCache improves DNS performance and reduces CoreDNS load. Custom Corefile entries may indicate special routing requirements.

**MCP:**
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="coredns"
)
```

**CLI:**
```bash
# CoreDNS deployment
kubectl get deploy -n kube-system coredns -o json | jq '{
  replicas: .spec.replicas,
  version: .spec.template.spec.containers[0].image
}'

# CoreDNS ConfigMap (custom configuration)
kubectl get configmap -n kube-system coredns -o yaml 2>/dev/null

# Check for NodeLocal DNSCache
kubectl get daemonset -n kube-system node-local-dns 2>/dev/null
```

**Example output (CoreDNS info):**
```json
{
  "replicas": 2,
  "version": "602401143452.dkr.ecr.us-west-2.amazonaws.com/eks/coredns:v1.10.1-eksbuild.6"
}
```

### 5. Network Policies

**Why check this:** Network policies enforce pod-to-pod traffic rules. Their absence means all pods can communicate freely, which may violate security requirements. Calico and Cilium extend native Kubernetes policies with cluster-wide and advanced L7 rules.

```bash
# Check if any network policies exist
kubectl get networkpolicies -A 2>/dev/null | wc -l

# List network policies by namespace
kubectl get networkpolicies -A -o json | jq -r '.items | group_by(.metadata.namespace) | map({namespace: .[0].metadata.namespace, count: length})'
```

**Calico/Cilium Network Policies:**
```bash
# Calico
kubectl get globalnetworkpolicies.crd.projectcalico.org 2>/dev/null | head -5
kubectl get networkpolicies.crd.projectcalico.org -A 2>/dev/null | head -5

# Cilium
kubectl get ciliumnetworkpolicies -A 2>/dev/null | head -5
```

**Example output (network policy count by namespace):**
```json
[
  {"namespace": "production", "count": 12},
  {"namespace": "staging", "count": 8},
  {"namespace": "kube-system", "count": 3}
]
```

---

## Output Schema

```yaml
networking:
  vpc_cni:
    version: string
    status: string
    mode: string            # secondary-ip | prefix-delegation | custom-networking
    custom_networking:
      enabled: bool
      eniconfigs: int       # Count of ENIConfig resources
    prefix_delegation:
      enabled: bool
    security_groups_for_pods:
      enabled: bool
      
  ingress:
    controllers:
      - name: string
        type: string        # aws-lb | nginx | traefik | kong | other
        namespace: string
        version: string
    ingress_classes: list
    gateway_api:
      enabled: bool
      gateways: int
      
  service_mesh:
    detected: string        # istio | appmesh | linkerd | none
    istio:
      detected: bool
      version: string
      mode: string          # sidecar | ambient
      injection_namespaces: list
    appmesh:
      detected: bool
      virtual_services: int
      
  dns:
    coredns:
      version: string
      replicas: int
      custom_config: bool
    nodelocal_dns:
      enabled: bool
      
  network_policies:
    count: int
    namespaces_with_policies: int
    calico:
      detected: bool
      global_policies: int
    cilium:
      detected: bool
```

---

## Edge Cases

### Multiple Ingress Controllers

Common to have both AWS LBC and nginx:
- AWS LBC for external traffic (ALB/NLB)
- nginx for internal routing

Note both and document IngressClass usage.

### VPC CNI Custom Configuration

Check for non-default settings:
```bash
# Security Groups for Pods
kubectl get daemonset aws-node -n kube-system -o json | \
  jq '.spec.template.spec.containers[0].env[] | select(.name=="ENABLE_POD_ENI")'

# External SNAT
kubectl get daemonset aws-node -n kube-system -o json | \
  jq '.spec.template.spec.containers[0].env[] | select(.name=="AWS_VPC_K8S_CNI_EXTERNALSNAT")'
```

### IP Address Exhaustion Risk

```bash
# Check available IPs in subnets (requires subnet IDs from cluster)
aws ec2 describe-subnets --subnet-ids <ids> \
  --query 'Subnets[*].[SubnetId,AvailableIpAddressCount,CidrBlock]'
```

### Private Cluster Networking

```bash
# Check endpoint access configuration
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.resourcesVpcConfig.{
    endpointPublicAccess:endpointPublicAccess,
    endpointPrivateAccess:endpointPrivateAccess,
    publicAccessCidrs:publicAccessCidrs
  }'
```

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| Secondary IP mode, high pod density | Consider prefix delegation for more IPs per node |
| No ingress controller | Consider AWS LBC for ALB/NLB integration |
| Multiple ingress controllers | Document routing strategy, consider consolidation |
| No network policies | Add network policies for security isolation |
| No service mesh | Consider Istio or App Mesh for observability/security |
