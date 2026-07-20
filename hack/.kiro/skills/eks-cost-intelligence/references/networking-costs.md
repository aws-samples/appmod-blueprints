# Networking Costs

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Checks for topology-aware routing configuration, instance mode vs IP mode on load balancers, VPC endpoints for ECR/S3/STS, cross-AZ traffic potential based on service topology and pod distribution, and NAT Gateway cost estimation

---

## Overview

Networking costs is a mid-weight dimension (15 points max deduction). It evaluates whether the cluster minimizes cross-AZ data transfer charges ($0.01/GB each direction), avoids unnecessary NAT Gateway processing fees ($0.045/GB), and uses efficient load balancer target modes.

Cross-AZ traffic is often the largest hidden cost in multi-AZ EKS clusters. A single service with pods spread across 3 AZs and no topology-aware routing can generate significant monthly charges that are invisible without deliberate inspection.

### Checks Summary

| # | Check | Default Threshold | Severity Logic |
|---|-------|-------------------|----------------|
| 1 | Topology-aware routing on cross-AZ services | Missing on services with cross-AZ pods | By estimated cross-AZ cost |
| 2 | Instance mode vs IP mode on load balancers | Instance mode with cross-AZ targets | MEDIUM per LB |
| 3 | VPC endpoints for ECR, S3, STS | Missing endpoint | MEDIUM (per Req 7.5) |
| 4 | Cross-AZ traffic potential | Services with pods in multiple AZs | By estimated monthly cost |
| 5 | NAT Gateway cost estimation | AWS service traffic without VPC endpoints | By estimated NAT cost |

---

## Pre-requisites

These checks require:
- **kubectl access** to the cluster (for service specs, pod distribution, annotations)
- **AWS CLI access** for `ec2:DescribeVpcEndpoints`, `ec2:DescribeSubnets`, `ec2:DescribeNatGateways`
- **Optional:** CloudWatch metrics for actual data transfer volumes (improves estimate accuracy)

No metrics-server is required — checks use configuration inspection and traffic estimation.

---

## Check 1: Topology-Aware Routing Configuration

### What it detects

Services with pods distributed across multiple availability zones that do not have topology-aware routing enabled, causing unnecessary cross-AZ traffic at $0.01/GB in each direction ($0.02/GB round-trip).

### Background

Kubernetes topology-aware routing (formerly Topology Aware Hints) instructs kube-proxy to prefer routing traffic to endpoints in the same AZ as the client pod. Without it, traffic is distributed randomly across all healthy endpoints regardless of AZ placement.

### Data collection

**Via kubectl:**

```bash
# Find services WITHOUT topology-aware routing annotations/hints
kubectl get services --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.spec.type != "ExternalName") |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(
      (.metadata.annotations["service.kubernetes.io/topology-mode"] // "none") == "none" and
      (.metadata.annotations["service.kubernetes.io/topology-aware-hints"] // "none") == "none"
    ) |
    "\(.metadata.namespace)/\(.metadata.name) type=\(.spec.type) selector=\(.spec.selector | to_entries | map("\(.key)=\(.value)") | join(","))"
  '

# Check which of those services have pods in multiple AZs
for svc in $(kubectl get services --all-namespaces -o json | \
  jq -r '.items[] | select(.spec.type != "ExternalName") |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select((.metadata.annotations["service.kubernetes.io/topology-mode"] // "none") == "none" and
           (.metadata.annotations["service.kubernetes.io/topology-aware-hints"] // "none") == "none") |
    "\(.metadata.namespace)|\(.metadata.name)|\(.spec.selector | to_entries | map("\(.key)=\(.value)") | join(","))"'); do
  
  NS=$(echo "$svc" | cut -d'|' -f1)
  NAME=$(echo "$svc" | cut -d'|' -f2)
  SELECTOR=$(echo "$svc" | cut -d'|' -f3)
  
  # Count unique AZs for pods matching this service selector
  AZ_COUNT=$(kubectl get pods -n "$NS" -l "$SELECTOR" -o json 2>/dev/null | \
    jq '[.items[].spec.nodeName] | unique | length')
  
  if [ "$AZ_COUNT" -gt 1 ]; then
    echo "CROSS-AZ: $NS/$NAME has pods in $AZ_COUNT AZs without topology routing"
  fi
done
```

**Simplified single-command approach:**

```bash
# Get all services and their endpoint zone distribution in one pass
kubectl get endpoints --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.subsets != null) |
    select([.subsets[].addresses[]?.nodeName // empty] | unique | length > 1) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      endpoint_count: ([.subsets[].addresses[]?] | length),
      zones: ([.subsets[].addresses[]?.zone // empty] | unique)
    } |
    select(.zones | length > 1) |
    "\(.namespace)/\(.name) endpoints=\(.endpoint_count) zones=\(.zones | join(","))"
  '
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Service",
  api_version="v1",
  namespace="all"
)
# Filter for services missing topology-mode annotation
# Then check EndpointSlices for zone distribution:

list_k8s_resources(
  cluster_name="<cluster>",
  kind="EndpointSlice",
  api_version="discovery.k8s.io/v1",
  namespace="<namespace>"
)
# Check .endpoints[].zone for multi-AZ distribution
```

### Analysis logic

```
For each Service in non-system namespaces:
  has_topology_routing = (
    annotations["service.kubernetes.io/topology-mode"] == "Auto" OR
    annotations["service.kubernetes.io/topology-aware-hints"] == "Auto"
  )
  
  If NOT has_topology_routing:
    Get EndpointSlice for this service
    zones = unique zones from endpoints
    
    If len(zones) > 1:
      endpoint_count = total endpoints
      # Estimate: without topology routing, ~66% of traffic crosses AZ in a 3-AZ setup
      cross_az_fraction = 1 - (1 / len(zones))
      
      → Flag for topology-aware routing recommendation
      → Estimate cross-AZ cost (see Check 4 for detailed calculation)
```

### Severity classification

| Estimated Monthly Cross-AZ Cost | Severity |
|---------------------------------|----------|
| > $500 | CRITICAL |
| $200–$500 | HIGH |
| $50–$200 | MEDIUM |
| < $50 | LOW |

### Remediation

```bash
# Enable topology-aware routing on a service (Kubernetes 1.27+)
kubectl annotate service <service-name> -n <namespace> \
  service.kubernetes.io/topology-mode=Auto

# For Kubernetes 1.27–1.30, use the topology-mode annotation (trafficDistribution field not available)
kubectl annotate service <service-name> -n <namespace> \
  service.kubernetes.io/topology-aware-hints=Auto
```

```yaml
# Service manifest with topology-aware routing enabled
apiVersion: v1
kind: Service
metadata:
  name: <service-name>
  namespace: <namespace>
  annotations:
    service.kubernetes.io/topology-mode: "Auto"
spec:
  selector:
    app: <app-label>
  ports:
  - port: 80
    targetPort: 8080
```

> **Important:** Topology-aware routing requires that each zone has a roughly equal number of endpoints. If pod distribution is heavily skewed (e.g., 10 pods in us-east-1a, 1 pod in us-east-1b), Kubernetes may disable hints automatically. Ensure balanced pod distribution across AZs using topology spread constraints.

---

## Check 2: Instance Mode vs IP Mode on Load Balancers

### What it detects

AWS Load Balancer Controller targets configured in "instance" mode, where traffic routes to the node's NodePort and then kube-proxy forwards to the pod — potentially crossing AZ boundaries. IP mode routes directly to the pod IP, eliminating the extra hop and any cross-AZ forwarding by kube-proxy.

### Background

- **Instance mode (default):** LB → NodePort on any node → kube-proxy → pod (may cross AZ)
- **IP mode:** LB → pod IP directly (no cross-AZ hop from kube-proxy)

With instance mode, if the LB sends traffic to a node in AZ-a but the target pod is in AZ-b, you pay $0.01/GB for that cross-AZ hop. IP mode eliminates this entirely.

### Data collection

**Via kubectl:**

```bash
# Find Ingress resources using instance target type (or missing the annotation = defaults to instance)
kubectl get ingress --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      target_type: (.metadata.annotations["alb.ingress.kubernetes.io/target-type"] // "instance"),
      class: (.spec.ingressClassName // .metadata.annotations["kubernetes.io/ingress.class"] // "unknown")
    } |
    select(.target_type == "instance") |
    "\(.namespace)/\(.name) class=\(.class) target-type=\(.target_type)"
  '

# Find Services of type LoadBalancer using instance target type
kubectl get services --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.spec.type == "LoadBalancer") |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      target_type: (.metadata.annotations["service.beta.kubernetes.io/aws-load-balancer-nlb-target-type"] // 
                    .metadata.annotations["service.beta.kubernetes.io/aws-load-balancer-target-type"] // "instance"),
      lb_type: (.metadata.annotations["service.beta.kubernetes.io/aws-load-balancer-type"] // "classic")
    } |
    select(.target_type == "instance") |
    "\(.namespace)/\(.name) lb-type=\(.lb_type) target-type=\(.target_type)"
  '

# Check TargetGroupBindings for target type
kubectl get targetgroupbindings --all-namespaces -o json 2>/dev/null | \
  jq -r '
    .items[] |
    select(.spec.targetType == "instance") |
    "\(.metadata.namespace)/\(.metadata.name) targetType=\(.spec.targetType)"
  '
```

**Via AWS CLI (verify from AWS side):**

```bash
# List target groups and their target type
aws elbv2 describe-target-groups \
  --query 'TargetGroups[?contains(TargetGroupName, `k8s`)].{Name:TargetGroupName,Type:TargetType,ARN:TargetGroupArn}' \
  --output table

# For each instance-mode target group, check cross-AZ targets
aws elbv2 describe-target-health \
  --target-group-arn <target-group-arn> \
  --query 'TargetHealthDescriptions[].Target.{Id:Id,AZ:AvailabilityZone}'
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="Ingress",
  api_version="networking.k8s.io/v1",
  namespace="all"
)
# Check annotations for alb.ingress.kubernetes.io/target-type

list_k8s_resources(
  cluster_name="<cluster>",
  kind="Service",
  api_version="v1",
  namespace="all"
)
# Filter type=LoadBalancer, check target-type annotations
```

### Analysis logic

```
For each Ingress or LoadBalancer Service:
  target_type = annotation value (default: "instance" if not specified)
  
  If target_type == "instance":
    # Check if backend pods span multiple AZs
    Get pods matching the service selector
    pod_zones = unique AZs of those pods
    
    If len(pod_zones) > 1:
      → Finding: instance mode with cross-AZ pod distribution
      severity = MEDIUM (per-LB, cross-AZ hops on every request)
      
    If len(pod_zones) == 1:
      → No finding (single AZ, no cross-AZ risk from target mode)
```

### Severity classification

| Condition | Severity |
|-----------|----------|
| Instance mode + pods in 3+ AZs + high-traffic service | HIGH |
| Instance mode + pods in 2+ AZs | MEDIUM |
| Instance mode + pods in 1 AZ only | No finding |

### Remediation

```yaml
# For ALB Ingress — switch to IP mode
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <ingress-name>
  namespace: <namespace>
  annotations:
    alb.ingress.kubernetes.io/target-type: "ip"  # Changed from "instance"
spec:
  ingressClassName: alb
  rules:
  - host: example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: <service>
            port:
              number: 80
```

```yaml
# For NLB Service — switch to IP mode
apiVersion: v1
kind: Service
metadata:
  name: <service-name>
  namespace: <namespace>
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "external"
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: "ip"  # Changed from "instance"
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"
spec:
  type: LoadBalancer
  selector:
    app: <app-label>
  ports:
  - port: 443
    targetPort: 8443
```

> **Note:** Switching from instance to IP mode requires the AWS Load Balancer Controller (not the legacy in-tree cloud provider). Ensure the controller is installed before changing target types.

---

## Check 3: VPC Endpoints for ECR, S3, STS

### What it detects

Missing VPC endpoints for frequently accessed AWS services (ECR, S3, STS). Without VPC endpoints, all traffic to these services routes through NAT Gateways, incurring $0.045/GB processing fees plus $0.045/hour per NAT Gateway.

EKS clusters access these services constantly:
- **ECR** — Every pod pull fetches container images (can be GBs per deployment)
- **S3** — ECR image layers are stored in S3; also used by many workloads directly
- **STS** — Every IRSA/Pod Identity token exchange calls STS (high frequency, low bandwidth)

### Severity

**MEDIUM** — Per Requirement 7.5, missing VPC endpoints for ECR or S3 always generates a MEDIUM severity finding with estimated NAT Gateway cost savings.

### Data collection

**Via AWS CLI:**

```bash
# Get the VPC ID for the EKS cluster
CLUSTER_VPC=$(aws eks describe-cluster \
  --name <cluster> \
  --query 'cluster.resourcesVpcConfig.vpcId' \
  --output text)

# List existing VPC endpoints in the cluster's VPC
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$CLUSTER_VPC" \
  --query 'VpcEndpoints[].{Service:ServiceName,Type:VpcEndpointType,State:State,Id:VpcEndpointId}' \
  --output table

# Check specifically for required endpoints
REGION=$(aws configure get region)
REQUIRED_SERVICES=(
  "com.amazonaws.${REGION}.ecr.api"
  "com.amazonaws.${REGION}.ecr.dkr"
  "com.amazonaws.${REGION}.s3"
  "com.amazonaws.${REGION}.sts"
)

EXISTING_ENDPOINTS=$(aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$CLUSTER_VPC" \
  --query 'VpcEndpoints[].ServiceName' \
  --output text)

for svc in "${REQUIRED_SERVICES[@]}"; do
  if echo "$EXISTING_ENDPOINTS" | grep -q "$svc"; then
    echo "✅ $svc — endpoint exists"
  else
    echo "❌ $svc — MISSING (traffic routes through NAT Gateway)"
  fi
done
```

**Check NAT Gateway existence and usage (for cost estimation):**

```bash
# List NAT Gateways in the VPC
aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$CLUSTER_VPC" \
  --query 'NatGateways[?State==`available`].{Id:NatGatewayId,SubnetId:SubnetId,AZ:ConnectivityType}' \
  --output table

# Get NAT Gateway data transfer metrics (last 7 days)
NAT_GW_ID="<nat-gateway-id>"
aws cloudwatch get-metric-statistics \
  --namespace "AWS/NATGateway" \
  --metric-name "BytesOutToDestination" \
  --dimensions "Name=NatGatewayId,Value=$NAT_GW_ID" \
  --start-time "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --period 604800 \
  --statistics Sum \
  --region <region>
```

**Via EKS MCP Server:**

```
# Get cluster VPC info
get_eks_cluster(cluster_name="<cluster>")
# Extract resourcesVpcConfig.vpcId

# Then use AWS CLI for VPC endpoint checks (no direct MCP equivalent)
# The MCP server does not have ec2:DescribeVpcEndpoints — fall back to AWS CLI
```

### Analysis logic

```
required_endpoints = [
  "com.amazonaws.<region>.ecr.api",   # ECR API calls
  "com.amazonaws.<region>.ecr.dkr",   # ECR Docker registry (image pulls)
  "com.amazonaws.<region>.s3",        # S3 (ECR layers + workload data)
  "com.amazonaws.<region>.sts"        # STS (IRSA/Pod Identity token exchange)
]

existing_endpoints = list VPC endpoints in cluster VPC

missing = required_endpoints - existing_endpoints

If "ecr.api" OR "ecr.dkr" OR "s3" in missing:
  → Generate MEDIUM severity finding (per Req 7.5)
  → Estimate NAT Gateway cost for ECR/S3 traffic (see Check 5)

If "sts" in missing:
  → Generate LOW severity finding (STS traffic is low bandwidth)
  → Note: high frequency but small payload, cost impact is minimal

If ALL required endpoints present:
  → No finding for this check
```

### Severity classification

| Missing Endpoint | Severity | Rationale |
|------------------|----------|-----------|
| ECR (ecr.api or ecr.dkr) | MEDIUM | Image pulls route through NAT — high bandwidth |
| S3 | MEDIUM | ECR layers + workload data through NAT |
| STS | LOW | High frequency but tiny payloads |
| Multiple missing | MEDIUM (combined finding) | Aggregate NAT cost estimate |

> **Per Requirement 7.5:** Missing VPC endpoints for ECR or S3 SHALL always generate a MEDIUM severity finding with estimated NAT Gateway cost savings.

### Remediation

```hcl
# Terraform — Create VPC endpoints for EKS
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = var.vpc_id
  service_name = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  
  tags = {
    Name = "${var.cluster_name}-s3-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  
  tags = {
    Name = "${var.cluster_name}-ecr-api-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  
  tags = {
    Name = "${var.cluster_name}-ecr-dkr-endpoint"
  }
}

resource "aws_vpc_endpoint" "sts" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true
  
  tags = {
    Name = "${var.cluster_name}-sts-endpoint"
  }
}

# Security group for interface endpoints
resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.cluster_name}-vpc-endpoints-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}
```

```bash
# AWS CLI — Create S3 Gateway endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.<region>.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids <private-rtb-id-1> <private-rtb-id-2>

# AWS CLI — Create ECR Interface endpoints
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.<region>.ecr.api \
  --vpc-endpoint-type Interface \
  --subnet-ids <subnet-1> <subnet-2> <subnet-3> \
  --security-group-ids <sg-id> \
  --private-dns-enabled
```

---

## Check 4: Cross-AZ Traffic Potential

### What it detects

Services with pods distributed across multiple availability zones that are likely generating cross-AZ data transfer charges. This check quantifies the potential cost based on service topology, pod distribution, and estimated traffic volume.

### Cost model

| Traffic Type | Cost per GB | Direction |
|--------------|-------------|-----------|
| Cross-AZ within VPC | $0.01 | Per direction (sender pays + receiver pays) |
| Total round-trip cross-AZ | $0.02 | Request + response |

### Data collection

**Via kubectl:**

```bash
# Get all services with their endpoint distribution across AZs
kubectl get endpointslices --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.endpoints != null) |
    {
      namespace: .metadata.namespace,
      service: (.metadata.labels["kubernetes.io/service-name"] // "unknown"),
      total_endpoints: (.endpoints | length),
      zones: [.endpoints[].zone // empty] | group_by(.) | map({zone: .[0], count: length}),
      unique_zones: ([.endpoints[].zone // empty] | unique | length)
    } |
    select(.unique_zones > 1) |
    "\(.namespace)/\(.service) endpoints=\(.total_endpoints) zones=\(.unique_zones) distribution=\(.zones | map("\(.zone):\(.count)") | join(","))"
  '

# Get pod distribution by zone for high-replica deployments
kubectl get pods --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    select(.status.phase == "Running") |
    {
      namespace: .metadata.namespace,
      pod: .metadata.name,
      node: .spec.nodeName,
      owner: (.metadata.ownerReferences[0].name // "standalone")
    }' | \
  jq -s '
    # Correlate with node zones
    group_by(.namespace + "/" + .owner) |
    map(select(length > 1)) |
    map({
      workload: (.[0].namespace + "/" + .[0].owner),
      replicas: length,
      nodes: [.[].node] | unique
    }) |
    .[] | select(.nodes | length > 1) |
    "\(.workload) replicas=\(.replicas) nodes=\(.nodes | length)"
  '

# Get node-to-zone mapping
kubectl get nodes -o json | \
  jq -r '.items[] | "\(.metadata.name) \(.metadata.labels["topology.kubernetes.io/zone"])"'
```

**Estimate traffic volume (when Container Insights available):**

```bash
# Get pod network bytes (requires Container Insights)
aws cloudwatch get-metric-data \
  --metric-data-queries '[
    {
      "Id": "net_rx",
      "MetricStat": {
        "Metric": {
          "Namespace": "ContainerInsights",
          "MetricName": "pod_network_rx_bytes",
          "Dimensions": [
            {"Name": "ClusterName", "Value": "<cluster>"},
            {"Name": "Namespace", "Value": "<namespace>"},
            {"Name": "Service", "Value": "<service>"}
          ]
        },
        "Period": 604800,
        "Stat": "Sum"
      }
    }
  ]' \
  --start-time "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --region <region>
```

**Via EKS MCP Server:**

```
list_k8s_resources(
  cluster_name="<cluster>",
  kind="EndpointSlice",
  api_version="discovery.k8s.io/v1",
  namespace="all"
)
# Analyze zone distribution across endpoints

get_cloudwatch_metrics(
  cluster_name="<cluster>",
  metric_name="pod_network_rx_bytes",
  namespace="ContainerInsights",
  dimensions={"ClusterName": "<cluster>", "Namespace": "<ns>", "Service": "<svc>"},
  period=604800,
  stat="Sum"
)
```

### Analysis logic

```
For each Service with endpoints in multiple AZs:
  zone_count = number of unique AZs
  endpoint_count = total endpoints
  has_topology_routing = Check 1 result for this service
  
  # Estimate cross-AZ traffic fraction
  If has_topology_routing:
    cross_az_fraction = 0.05  # Small residual (imperfect balancing)
  Else:
    cross_az_fraction = 1 - (1 / zone_count)
    # 3 AZs → 66% cross-AZ, 2 AZs → 50% cross-AZ
  
  # Estimate monthly traffic volume
  If Container Insights available:
    monthly_bytes = pod_network_rx_bytes (7-day sum) × (30/7)
  Else:
    # Conservative estimate based on replica count and service type
    If service is ClusterIP (internal):
      estimated_monthly_gb = endpoint_count × 10  # 10 GB/month per endpoint baseline
    If service is LoadBalancer/NodePort (external-facing):
      estimated_monthly_gb = endpoint_count × 50  # Higher traffic assumption
  
  # Calculate cross-AZ cost
  cross_az_gb = estimated_monthly_gb × cross_az_fraction
  monthly_cross_az_cost = cross_az_gb × 0.02  # $0.01 each direction
  
  If monthly_cross_az_cost > threshold:
    → Generate finding with estimated cost
```

### Severity classification

| Estimated Monthly Cross-AZ Cost | Severity |
|---------------------------------|----------|
| > $500 | CRITICAL |
| $200–$500 | HIGH |
| $50–$200 | MEDIUM |
| < $50 | LOW |

### Confidence levels

| Data Source | Confidence | Notes |
|-------------|------------|-------|
| Container Insights network metrics | HIGH | Actual measured traffic |
| VPC Flow Logs (if available) | HIGH | Actual cross-AZ bytes |
| Estimation from replica count | MEDIUM | Assumes baseline traffic per pod |
| No traffic data available | LOW | Conservative estimate only |

### Remediation

```yaml
# 1. Enable topology-aware routing (see Check 1)
# 2. Use topology spread constraints to balance pods
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <deployment>
  namespace: <namespace>
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
            app: <app-label>
```

```bash
# Check current pod zone distribution for a deployment
kubectl get pods -n <namespace> -l app=<app-label> -o wide | \
  awk '{print $7}' | sort | uniq -c
```

---

## Check 5: NAT Gateway Cost Estimation

### What it detects

Estimated NAT Gateway costs for AWS service traffic that could be eliminated with VPC endpoints. NAT Gateways charge $0.045/GB for data processing plus $0.045/hour (~$32.40/month) per gateway.

> **Note:** NAT Gateway data processing is $0.045/GB for the first 10 TB/month, then tiered lower ($0.04/GB for next 30 TB, $0.035/GB thereafter). The skill uses $0.045/GB as a conservative estimate suitable for most EKS clusters under 10 TB/month of NAT traffic.

### Cost model

| NAT Gateway Component | Cost |
|-----------------------|------|
| Hourly charge | $0.045/hour (~$32.40/month per gateway) |
| Data processing | $0.045/GB processed |
| Cross-AZ data (if NAT in different AZ) | Additional $0.01/GB |

### Data collection

**Via AWS CLI:**

```bash
# Get NAT Gateways in the cluster VPC
CLUSTER_VPC=$(aws eks describe-cluster --name <cluster> \
  --query 'cluster.resourcesVpcConfig.vpcId' --output text)

aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$CLUSTER_VPC" "Name=state,Values=available" \
  --query 'NatGateways[].{Id:NatGatewayId,SubnetId:SubnetId,State:State}' \
  --output json

# Get NAT Gateway data transfer over last 30 days
NAT_GW_IDS=$(aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$CLUSTER_VPC" "Name=state,Values=available" \
  --query 'NatGateways[].NatGatewayId' --output text)

for NAT_ID in $NAT_GW_IDS; do
  echo "=== $NAT_ID ==="
  
  # Bytes out to destination (internet/AWS services)
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/NATGateway" \
    --metric-name "BytesOutToDestination" \
    --dimensions "Name=NatGatewayId,Value=$NAT_ID" \
    --start-time "$(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 2592000 \
    --statistics Sum \
    --output json
  
  # Bytes in from destination
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/NATGateway" \
    --metric-name "BytesInFromDestination" \
    --dimensions "Name=NatGatewayId,Value=$NAT_ID" \
    --start-time "$(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 2592000 \
    --statistics Sum \
    --output json
  
  # Connection attempts (indicates traffic volume)
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/NATGateway" \
    --metric-name "ConnectionAttemptCount" \
    --dimensions "Name=NatGatewayId,Value=$NAT_ID" \
    --start-time "$(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 2592000 \
    --statistics Sum \
    --output json
done
```

**Estimate ECR/S3 traffic portion (when VPC endpoints are missing):**

```bash
# Get VPC Flow Logs for NAT Gateway ENI (if flow logs enabled)
# This shows destination IPs which can be correlated to AWS service IP ranges
# Note: This is optional and requires VPC Flow Logs to be enabled

# Alternative: estimate from container image sizes and pull frequency
# Get image sizes for running pods
kubectl get pods --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.status.phase == "Running") |
    .status.containerStatuses[]? |
    .imageID' | \
  sort | uniq -c | sort -rn | head -20

# Count pod restarts (each restart = image pull if imagePullPolicy != IfNotPresent)
kubectl get pods --all-namespaces -o json | \
  jq -r '
    .items[] |
    select(.status.phase == "Running") |
    select(.metadata.namespace | test("^kube-|^amazon-|^aws-") | not) |
    {
      namespace: .metadata.namespace,
      name: .metadata.name,
      restarts: ([.status.containerStatuses[]?.restartCount // 0] | add),
      pull_policy: [.spec.containers[].imagePullPolicy] | unique
    } |
    select(.restarts > 0 or (.pull_policy | any(. == "Always"))) |
    "\(.namespace)/\(.name) restarts=\(.restarts) policy=\(.pull_policy | join(","))"
  '
```

**Via EKS MCP Server:**

```
# Get cluster VPC for NAT Gateway lookup
get_eks_cluster(cluster_name="<cluster>")
# Extract VPC ID, then use AWS CLI for NAT Gateway metrics

get_cloudwatch_metrics(
  cluster_name="<cluster>",
  metric_name="BytesOutToDestination",
  namespace="AWS/NATGateway",
  dimensions={"NatGatewayId": "<nat-gw-id>"},
  period=2592000,
  stat="Sum"
)
```

### Analysis logic

```
# Step 1: Calculate total NAT Gateway cost
nat_gateways = list NAT Gateways in cluster VPC
nat_hourly_cost = len(nat_gateways) × $0.045/hour
nat_monthly_fixed = nat_hourly_cost × 730  # hours/month

For each NAT Gateway:
  bytes_processed = BytesOutToDestination + BytesInFromDestination (30-day sum)
  gb_processed = bytes_processed / (1024^3)
  processing_cost = gb_processed × $0.045

total_nat_monthly = nat_monthly_fixed + sum(processing_cost for each NAT)

# Step 2: Estimate portion attributable to AWS services (saveable with VPC endpoints)
If VPC endpoints for ECR/S3 are MISSING (from Check 3):
  # ECR/S3 typically accounts for 60-80% of NAT traffic in EKS clusters (based on field experience across production EKS deployments)
  # Conservative estimate: 50% of NAT traffic is ECR/S3
  estimated_aws_service_fraction = 0.50
  
  saveable_cost = total_nat_processing_cost × estimated_aws_service_fraction
  
  # If we can measure actual image pull sizes:
  If image_pull_data_available:
    monthly_image_pulls_gb = (avg_image_size × daily_pulls × 30) / 1024
    ecr_nat_cost = monthly_image_pulls_gb × $0.045
    saveable_cost = ecr_nat_cost  # More accurate estimate
  
  → Generate finding with saveable_cost as monthly_savings

# Step 3: Check if NAT Gateways are even needed
If VPC endpoints exist for ALL required services AND no internet egress needed:
  → Consider if NAT Gateways can be removed entirely
  → monthly_savings = nat_monthly_fixed (gateway hourly charges)
```

### Severity classification

| Estimated Saveable NAT Cost | Severity |
|-----------------------------|----------|
| > $500/month | CRITICAL |
| $200–$500/month | HIGH |
| $50–$200/month | MEDIUM |
| < $50/month | LOW |

> **Note:** This check's severity combines with Check 3 (VPC endpoints). If VPC endpoints are missing AND NAT costs are high, the combined finding severity may escalate.

### Worked example

```
Cluster: 3 NAT Gateways (one per AZ), no VPC endpoints for ECR/S3

Fixed cost:
  3 × $0.045/hour × 730 hours = $98.55/month

Data processing (measured from CloudWatch):
  NAT-1: 150 GB processed → $6.75
  NAT-2: 200 GB processed → $9.00
  NAT-3: 180 GB processed → $8.10
  Total processing: $23.85/month

Total NAT cost: $98.55 + $23.85 = $122.40/month

Estimated saveable (50% is ECR/S3 traffic):
  Processing savings: $23.85 × 0.50 = $11.93/month
  
  Note: Fixed NAT cost ($98.55) remains unless ALL traffic can use VPC endpoints
  and no internet egress is needed.

Finding:
  severity: MEDIUM (saveable amount < $50)
  monthly_savings: ~$12/month from data processing
  additional_note: "VPC endpoints also reduce latency for ECR pulls"
```

### Remediation

See Check 3 remediation for VPC endpoint creation.

Additional NAT Gateway optimization:

```bash
# Check if NAT Gateways can be consolidated (if traffic is low)
# Review per-AZ NAT usage — if one AZ has minimal traffic, 
# consider routing through another AZ's NAT (trade-off: cross-AZ cost vs NAT fixed cost)

# Check NAT Gateway idle connections
aws cloudwatch get-metric-statistics \
  --namespace "AWS/NATGateway" \
  --metric-name "ActiveConnectionCount" \
  --dimensions "Name=NatGatewayId,Value=<nat-gw-id>" \
  --start-time "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --period 3600 \
  --statistics Maximum \
  --output json
```

---

## Scoring Contribution

The networking costs dimension has a **maximum deduction of 15 points**.

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

### Typical finding combinations and their score impact

| Scenario | Findings | Total Deduction |
|----------|----------|-----------------|
| No VPC endpoints + no topology routing + instance mode LBs | 1 MEDIUM (VPC) + 1 MEDIUM (topology) + 1 MEDIUM (LB) | min(6.75, 15) = 6.75 |
| Missing VPC endpoints only | 1 MEDIUM | 2.25 |
| High cross-AZ traffic without topology routing | 1 HIGH | 4.5 |
| All optimized (VPC endpoints + topology routing + IP mode) | No findings | 0 |
| Worst case: high cross-AZ + no VPC endpoints + instance mode | 1 CRITICAL + 2 MEDIUM | min(9.0 + 4.5, 15) = 13.5 |

### Dimension status

| Condition | Status |
|-----------|--------|
| All checks completed | ASSESSED |
| VPC endpoint check failed (permission denied) | ASSESSED (partial, with note) |
| kubectl unavailable | SKIPPED |

If the dimension is fully SKIPPED, it contributes **zero deduction** and is excluded from the score denominator.

---

## Cross-AZ Cost Calculation Reference

### Formula

```
monthly_cross_az_cost = cross_az_gb_transferred × $0.01 × 2
                      = cross_az_gb_transferred × $0.02 (both directions)

Where:
  cross_az_gb_transferred = total_service_traffic_gb × cross_az_fraction

  cross_az_fraction (without topology routing):
    2 AZs: 0.50 (50% of traffic crosses AZ)
    3 AZs: 0.67 (67% of traffic crosses AZ)
    4 AZs: 0.75 (75% of traffic crosses AZ)
  
  cross_az_fraction (with topology routing):
    ~0.05 (5% residual due to imperfect balancing)
```

### Worked example

```
Service: payment-api
  Replicas: 9 (3 per AZ across 3 AZs)
  Monthly traffic: 500 GB (measured from Container Insights)
  Topology routing: NOT enabled

  cross_az_fraction = 1 - (1/3) = 0.67
  cross_az_gb = 500 × 0.67 = 335 GB
  monthly_cost = 335 × $0.02 = $6.70/month

  With topology routing enabled:
  cross_az_gb = 500 × 0.05 = 25 GB
  monthly_cost = 25 × $0.02 = $0.50/month

  Savings from enabling topology routing: $6.20/month for this service

Aggregate across all services:
  If 20 services × avg $5/month cross-AZ = $100/month cluster-wide
  → MEDIUM severity finding
```

### Traffic estimation when metrics unavailable

When Container Insights or VPC Flow Logs are not available, use conservative estimates:

| Service Type | Estimated Monthly Traffic per Endpoint |
|--------------|----------------------------------------|
| Internal API (ClusterIP) | 10 GB |
| Database proxy (ClusterIP) | 50 GB |
| External-facing (LoadBalancer) | 50 GB |
| Message queue consumer | 20 GB |
| gRPC service (high-frequency) | 30 GB |

These are conservative baselines. Actual traffic may be significantly higher for data-intensive services.

---

## Decision Tree

```
START
  │
  ├─ Can we access the cluster VPC info? (eks:DescribeCluster)
  │   ├─ YES → Continue
  │   └─ NO  → Skip VPC endpoint checks (3, 5), still run checks 1, 2, 4
  │
  ├─ Run Check 3: VPC Endpoints
  │   ├─ ec2:DescribeVpcEndpoints available?
  │   │   ├─ YES → Check for ECR, S3, STS endpoints
  │   │   └─ NO  → Skip Check 3, note permission gap
  │   └─ Missing endpoints found?
  │       ├─ YES → Generate MEDIUM finding (per Req 7.5)
  │       └─ NO  → Pass
  │
  ├─ Run Check 1: Topology-Aware Routing
  │   ├─ Get all services and their endpoint zone distribution
  │   ├─ For services with multi-AZ endpoints:
  │   │   ├─ Has topology-mode annotation? → Pass
  │   │   └─ Missing annotation? → Estimate cross-AZ cost → Generate finding
  │   └─ No multi-AZ services? → Pass (single-AZ cluster)
  │
  ├─ Run Check 2: Instance vs IP Mode
  │   ├─ Get Ingress and LoadBalancer Services
  │   ├─ For each with target-type=instance:
  │   │   ├─ Backend pods in multiple AZs? → Generate MEDIUM finding
  │   │   └─ Backend pods in single AZ? → Pass
  │   └─ All using IP mode? → Pass
  │
  ├─ Run Check 4: Cross-AZ Traffic Potential
  │   ├─ Container Insights available?
  │   │   ├─ YES → Use actual network metrics for cost calculation
  │   │   └─ NO  → Use estimation based on replica count and service type
  │   ├─ Calculate aggregate cross-AZ cost across all services
  │   └─ Generate finding if above threshold
  │
  ├─ Run Check 5: NAT Gateway Cost Estimation
  │   ├─ NAT Gateways exist in VPC?
  │   │   ├─ YES → Get CloudWatch metrics for data processed
  │   │   └─ NO  → Skip (no NAT cost)
  │   ├─ VPC endpoints missing (from Check 3)?
  │   │   ├─ YES → Estimate saveable portion of NAT traffic
  │   │   └─ NO  → NAT traffic is non-AWS-service (can't save with endpoints)
  │   └─ Generate finding with estimated savings
  │
  └─ Aggregate findings → Calculate dimension deduction (capped at 15)
```

---

## Common Patterns and Quick Wins

### Pattern 1: New EKS cluster with default networking

**Symptoms:** No VPC endpoints, no topology routing, instance mode on LBs
**Typical cost impact:** $50–$200/month for medium clusters
**Quick wins:**
1. Create S3 Gateway endpoint (free, immediate savings)
2. Create ECR Interface endpoints ($7.20/month per endpoint per AZ, but saves NAT processing)
3. Annotate high-traffic services with topology-mode=Auto

### Pattern 2: Large cluster with many internal services

**Symptoms:** 50+ services, pods spread across 3 AZs, no topology routing
**Typical cost impact:** $200–$1000/month in cross-AZ charges
**Quick wins:**
1. Enable topology-aware routing on top-10 highest-traffic services
2. Ensure topology spread constraints balance pods evenly across AZs
3. Consider zone-aware service mesh (Istio locality load balancing)

### Pattern 3: CI/CD heavy cluster with frequent deployments

**Symptoms:** High image pull frequency, no ECR VPC endpoint, large images
**Typical cost impact:** $100–$500/month in NAT processing for ECR pulls
**Quick wins:**
1. Create ECR VPC endpoints (ecr.api + ecr.dkr + s3)
2. Use `imagePullPolicy: IfNotPresent` where possible
3. Consider ECR pull-through cache for third-party images

---

*This reference is loaded on-demand when the networking costs dimension is being assessed. See [report-generation.md](./report-generation.md) for how findings from this dimension contribute to the overall Cost Score.*
