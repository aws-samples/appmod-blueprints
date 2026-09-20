# EKS Networking — Ingress, Load Balancing & DNS

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Ingress patterns (ALB, NLB, Gateway API), AWS Load Balancer Controller, service mesh, DNS/CoreDNS tuning, private cluster connectivity

**For VPC CNI, subnet planning, IPv6, and IP management, see:** [Networking](networking.md)
**For network policies and traffic control, see:** [Security — Runtime & Network](security-runtime-network.md)

---

## Table of Contents

1. [Ingress Patterns](#ingress-patterns)
2. [AWS Load Balancer Controller — ALB](#aws-load-balancer-controller-alb)
3. [AWS Load Balancer Controller — NLB](#aws-load-balancer-controller-nlb)
4. [Gateway API](#gateway-api)
5. [Service Mesh Options](#service-mesh-options)
6. [DNS and CoreDNS](#dns-and-coredns)
7. [Private Cluster Patterns](#private-cluster-patterns)
8. [Network Policies](#network-policies)

---

## Ingress Patterns

### Ingress Controller Decision Matrix

| Controller | Protocol | Use When | Key Feature |
|-----------|----------|----------|-------------|
| **AWS ALB (via LBC)** | HTTP/HTTPS, gRPC | Web apps, REST APIs | Native WAF, Cognito auth |
| **AWS NLB (via LBC)** | TCP/UDP, TLS | Non-HTTP, ultra-low latency | Static IPs, preserve source IP |
| **Gateway API + LBC** | HTTP/HTTPS | New standard, future-proof | Multi-team route management |
| **VPC Lattice** | HTTP/HTTPS | Cross-VPC, service-to-service | No ingress controller needed |
| **NGINX Ingress** | HTTP/HTTPS | Complex routing, rate limiting | Most configurable |
| **Istio Gateway** | HTTP/HTTPS, TCP | Service mesh users | Integrated with Istio |

### ALB vs NLB Quick Decision

| Factor | NLB | ALB |
|--------|-----|-----|
| **Protocol** | TCP, UDP, TLS | HTTP, HTTPS, gRPC (L7) |
| **Latency** | Lower (L4) | Higher (L7 processing) |
| **Static IPs** | Yes (Elastic IPs) | No |
| **Source IP preservation** | Native | Via X-Forwarded-For header |
| **WAF integration** | No | Yes |
| **Auth integration** | No | Yes (Cognito, OIDC) |
| **Best for** | TCP/UDP, gRPC, low latency | HTTP web apps, WAF, auth |

---

## AWS Load Balancer Controller (ALB)

The AWS Load Balancer Controller provisions Application Load Balancers for Kubernetes Ingress resources. ALB is the default ingress pattern for HTTP/HTTPS workloads, with native AWS WAF, Cognito, and ACM integration.

### ALB Ingress Example

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip  # Required for Fargate
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
    alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws:wafv2:...
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

### Key ALB Annotations

| Annotation | Purpose | Common Values |
|---|---|---|
| `alb.ingress.kubernetes.io/scheme` | Internet-facing or internal | `internet-facing`, `internal` |
| `alb.ingress.kubernetes.io/target-type` | How pods are registered | `ip` (recommended), `instance` |
| `alb.ingress.kubernetes.io/group.name` | Share ALB across Ingresses | Any string (e.g., `shared-alb`) |
| `alb.ingress.kubernetes.io/listen-ports` | Listener ports | `[{"HTTPS":443}]` |
| `alb.ingress.kubernetes.io/certificate-arn` | ACM certificate | ACM ARN |
| `alb.ingress.kubernetes.io/ssl-redirect` | HTTP to HTTPS redirect | `443` |
| `alb.ingress.kubernetes.io/wafv2-acl-arn` | WAF integration | WAF ACL ARN |
| `alb.ingress.kubernetes.io/auth-type` | Authentication | `cognito`, `oidc` |
| `alb.ingress.kubernetes.io/ip-address-type` | IPv4 or dual-stack | `ipv4`, `dualstack` |

### IP Mode vs Instance Mode

| Factor | IP Mode | Instance Mode |
|---|---|---|
| **Target registration** | Pod IP directly | Node IP + NodePort |
| **Network hops** | Fewer (ALB → pod) | More (ALB → node → pod) |
| **Pod density** | Better (no NodePort exhaustion) | Limited by NodePort range |
| **Fargate support** | Yes | No |
| **Recommendation** | Default choice | Legacy or specific requirements |

✅ DO:
- Use IP target type for new deployments — fewer hops, better performance
- Use `group.name` to share a single ALB across multiple Ingress resources — reduces cost and avoids ALB limits
- Enable SSL redirect (HTTP → HTTPS) for all internet-facing ALBs
- Attach WAF ACL for internet-facing ALBs
- Configure appropriate health check paths — ALB defaults may not match your app

❌ DON'T:
- Create one ALB per Ingress without grouping — expensive and hits ALB quotas
- Use instance target type with Fargate (not supported)
- Mix Ingress annotations from different controllers

---

## AWS Load Balancer Controller (NLB)

The LBC provisions Network Load Balancers for Kubernetes Services of type LoadBalancer. NLB handles TCP/UDP workloads, gRPC, and scenarios requiring static IPs or source IP preservation.

### NLB Service Example

```yaml
apiVersion: v1
kind: Service
metadata:
  name: app-nlb
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
    service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled: "true"
spec:
  type: LoadBalancer
  selector:
    app: my-app
  ports:
  - port: 443
    targetPort: 8443
    protocol: TCP
```

### Key NLB Annotations

| Annotation | Purpose | Common Values |
|---|---|---|
| `service.beta.kubernetes.io/aws-load-balancer-type` | Use LBC (not in-tree) | `external` |
| `service.beta.kubernetes.io/aws-load-balancer-nlb-target-type` | Target registration | `ip` (recommended), `instance` |
| `service.beta.kubernetes.io/aws-load-balancer-scheme` | Internet-facing or internal | `internet-facing`, `internal` |
| `service.beta.kubernetes.io/aws-load-balancer-proxy-protocol-v2-enabled` | Proxy protocol | `true`, `false` |
| `service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled` | Cross-AZ balancing | `true` |
| `service.beta.kubernetes.io/aws-load-balancer-ssl-cert` | TLS termination at NLB | ACM ARN |

✅ DO:
- Use `aws-load-balancer-type: external` to ensure LBC manages the NLB (not the legacy in-tree controller)
- Use IP target type for consistency with ALB and fewer network hops
- Enable cross-zone load balancing for even traffic distribution

❌ DON'T:
- Use NLB for HTTP workloads that need WAF or Cognito — use ALB instead
- Forget to set `externalTrafficPolicy: Local` if you need source IP preservation with instance targets

---

## Gateway API

Gateway API is the successor to the Ingress resource, offering role-oriented resource model and multi-team route management. **Recommended for new deployments.**

```yaml
# GatewayClass (one per cluster — defines which controller)
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: amazon-alb
spec:
  controllerName: application-networking.k8s.aws/gateway-api-controller

---
# Gateway (per team/environment — defines listeners)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: app-gateway
spec:
  gatewayClassName: amazon-alb
  listeners:
  - name: https
    port: 443
    protocol: HTTPS
    tls:
      certificateRefs:
      - name: app-cert

---
# HTTPRoute (per service — defines routing rules)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
spec:
  parentRefs:
  - name: app-gateway
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    backendRefs:
    - name: api-service
      port: 80
```

**Why Gateway API over Ingress:**
- **Role separation** — infrastructure teams manage GatewayClass/Gateway, application teams manage HTTPRoutes
- **Multi-team** — multiple HTTPRoutes can attach to one Gateway without annotation conflicts
- **Richer routing** — header matching, traffic splitting, URL rewriting built-in
- **Portable** — same resources work across ALB, NLB, NGINX, Istio, and other implementations

✅ DO:
- Use `target-type: ip` for pod-direct traffic (required for Fargate)
- Use Gateway API for new multi-team setups — cleaner separation of concerns than Ingress

❌ DON'T:
- Mix Gateway API and Ingress for the same service — pick one approach
- Forget to set health check paths on ALB target groups

---

## Service Mesh Options

| Option | Managed | Complexity | Best For |
|--------|---------|-----------|----------|
| **VPC Lattice** | Fully managed | Low | Cross-VPC, AWS-native |
| **Istio (on EKS)** | Self-managed | High | Full service mesh features |
| **App Mesh** | AWS managed | Medium | **Maintenance mode — avoid for new projects** |

**VPC Lattice** is recommended for new AWS-native service-to-service networking:
- No sidecar proxies needed
- Cross-VPC and cross-account routing
- IAM-based auth policies
- Integrates with Gateway API

---

## DNS and CoreDNS

### CoreDNS Tuning for Large Clusters

**Scale CoreDNS with cluster size:**

```yaml
# Enable CoreDNS autoscaling via proportional autoscaler
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dns-autoscaler
  namespace: kube-system
spec:
  # Scales CoreDNS replicas based on node/core count
  # linear: {"coresPerReplica": 256, "nodesPerReplica": 16, "min": 2, "max": 10}
```

**Optimize DNS resolution:**

```yaml
# Pod DNS config — reduce search domain lookups
apiVersion: v1
kind: Pod
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"  # Default is 5, causing unnecessary search domain queries
  dnsPolicy: ClusterFirst
```

**Deploy NodeLocal DNSCache** for clusters >100 nodes — reduces CoreDNS load by 80%+. Note: NodeLocal DNSCache is **not supported** with Security Groups for Pods in strict mode, because strict mode routes all traffic through the VPC (including traffic to the node).

✅ DO:
- Deploy NodeLocal DNSCache for clusters >100 nodes
- Set `ndots: 2` for pods making many external DNS calls
- Monitor CoreDNS metrics (cache hit rate, latency, errors)
- Use proportional autoscaler — don't manually set replica counts

❌ DON'T:
- Run CoreDNS with only 2 replicas on large clusters
- Ignore DNS latency as source of application slowness
- Enable DNS64 on subnets with IPv6 pods unless you intend NAT64 routing (causes unexpected NAT GW costs)

### External DNS

```bash
# Auto-manage Route 53 records for Services/Ingresses
helm install external-dns external-dns/external-dns \
  --set provider=aws \
  --set policy=sync \
  --set registry=txt \
  --set txtOwnerId=my-cluster
```

---

## Private Cluster Patterns

### Fully Private Cluster

**No public endpoint, all traffic stays within VPC:**

```hcl
# Terraform configuration
resource "aws_eks_cluster" "private" {
  vpc_config {
    endpoint_private_access = true
    endpoint_public_access  = false
    subnet_ids              = var.private_subnet_ids
  }
}
```

**Required VPC endpoints:**
- `com.amazonaws.<region>.eks` — EKS API
- `com.amazonaws.<region>.eks-auth` — EKS auth
- `com.amazonaws.<region>.ecr.api` — ECR API
- `com.amazonaws.<region>.ecr.dkr` — ECR Docker
- `com.amazonaws.<region>.s3` (Gateway) — ECR image layers
- `com.amazonaws.<region>.sts` — STS for IRSA/Pod Identity
- `com.amazonaws.<region>.logs` — CloudWatch Logs
- `com.amazonaws.<region>.ec2` — EC2 API (for nodes)
- `com.amazonaws.<region>.elasticloadbalancing` — ELB (if using LBC)

### Access Patterns for Private Clusters

| Access Method | Complexity | Use When |
|--------------|-----------|----------|
| **VPN/Direct Connect** | Medium | Existing corporate network |
| **SSM Session Manager** | Low | Ad-hoc access via bastion |
| **PrivateLink** | Medium | Cross-VPC or cross-account |
| **Cloud9 in VPC** | Low | Development/testing |

---

## Network Policies

For detailed network policy guidance including default-deny patterns, DNS allow rules, and policy engine comparison (VPC CNI native, Calico, Cilium), see **[Security — Runtime & Network](security-runtime-network.md#network-policies)**.

**Quick summary:**

| Option | Standard | EKS Support | Features |
|--------|----------|-------------|----------|
| **VPC CNI Network Policy** | K8s NetworkPolicy | Native (v1.14+) | L3/L4 policies, eBPF-based |
| **Calico** | K8s + Calico extended | Add-on | L3/L4 + DNS-based policies |
| **Cilium** | K8s + Cilium extended | Self-managed | L3/L4/L7 + DNS + identity |

**Recommendation:** Use VPC CNI native network policies for most workloads. Use Cilium or Calico only if you need L7 policies or advanced features like DNS hostname rules.

---

**Sources:**
- [AWS EKS Best Practices Guide — Networking](https://docs.aws.amazon.com/eks/latest/best-practices/networking.html)
- [AWS Load Balancer Controller Documentation](https://kubernetes-sigs.github.io/aws-load-balancer-controller)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
