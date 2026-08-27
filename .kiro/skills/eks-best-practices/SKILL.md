---
name: eks-best-practices
description: Advisory guidance for Amazon EKS architecture and configuration decisions — compute strategy, networking, security, reliability, cost, autoscaling, observability, multi-tenancy, and upgrade planning. Also answers Terraform configuration questions about terraform-aws-modules/terraform-aws-eks. Use for any EKS planning or architectural judgment call, even when phrased casually. Do NOT use for generating documents or code (eks-design, eks-build), scoring or auditing a live cluster (eks-operation-review, eks-upgrade-check), discovering what is running (eks-recon), MCP tooling setup (eks-mcp-server), building developer platforms and IDPs (eks-platform-engineering), GenAI/LLM workload decisions — GPU vs Trainium/Inferentia, vLLM/Ray serving, distributed training, ML storage (eks-genai), or compliance-regime hardening and audit prep — HIPAA/PCI/FedRAMP, CIS benchmarks, GuardDuty, image signing (eks-security).
---

# EKS Best Practices

Comprehensive guidance for designing, deploying, and operating Amazon EKS clusters. Consolidates guidance from the AWS EKS Best Practices Guide, AWS EKS HA/Resiliency Guide, and terraform-aws-modules/terraform-aws-eks examples.

## When to Use This Skill

**Activate this skill when:**
- Designing a new EKS cluster architecture
- Choosing between EKS compute options (Fargate, MNG, Karpenter, Auto Mode)
- Configuring EKS networking (VPC CNI, ingress, service mesh)
- Implementing EKS security (IAM, pod security, secrets)
- Planning cluster upgrades or migrations
- Reviewing EKS architecture decisions
- Working with terraform-aws-modules/terraform-aws-eks examples
- Optimizing EKS cost or scaling to large clusters

**Don't use this skill for:**
- Generic Kubernetes concepts (Claude knows these)
- Provider-specific API reference (link to AWS docs)
- Non-EKS container orchestration (ECS, Lambda)
- Step-by-step EKS upgrade execution — this skill covers upgrade strategy and architectural decisions, not the per-version procedures themselves.

## EKS Architecture Decision Framework

### When to Use EKS

| Requirement | EKS | ECS | Lambda |
|-------------|-----|-----|--------|
| **Kubernetes ecosystem** | ✅ Native K8s | ❌ AWS-proprietary | ❌ |
| **Portable across clouds** | ✅ Standard K8s API | ❌ AWS-only | ❌ AWS-only |
| **Long-running services** | ✅ | ✅ | ⚠️ 15 min limit |
| **Minimal ops overhead** | Medium | Low | Lowest |
| **GPU/ML workloads** | ✅ Best support | Limited | ❌ |
| **Complex networking** | ✅ Full control | Medium | Limited |
| **Team has K8s expertise** | Required | Not required | Not required |

### EKS Deployment Models

| Model | Description | Operational Overhead | Use When |
|-------|-------------|---------------------|----------|
| **EKS Standard** | Full control over nodes, add-ons, networking | Medium-High | Need full customization |
| **EKS Auto Mode** | AWS manages nodes, add-ons, scaling | Low | Want minimal ops, standard workloads |
| **EKS with Fargate** | Serverless pods, per-pod billing | Low | Batch, low-density workloads |
| **EKS on Outposts** | Run EKS on-premises | High | Data residency, low-latency edge |
| **EKS Anywhere** | EKS on your own infrastructure | Highest | Air-gapped, custom hardware |

### Shared Responsibility

| Component | AWS Manages | You Manage |
|-----------|-------------|------------|
| **Control plane** | API server, etcd, HA, patching | RBAC, admission control, audit logging |
| **Data plane (MNG)** | AMI updates, node health | Instance type, scaling, pod scheduling |
| **Data plane (Fargate)** | Everything | Pod spec, resource requests |
| **Data plane (Auto Mode)** | Node lifecycle, OS patching | Workload definitions |
| **Networking** | ENI attachment, VPC CNI releases | Subnet design, IP planning, ingress |
| **Security** | Control plane auth | IAM, pod security, secrets, network policies |

## Compute Selection Matrix

### Decision Table

| Factor | Fargate | MNG | Karpenter | Auto Mode | Self-Managed |
|--------|---------|-----|-----------|-----------|-------------|
| **Best for** | Batch, small scale | Stable, predictable | Dynamic, varied | Minimal ops | Custom AMI/kernel |
| **Scaling** | Per-pod | ASG-based | Fast, flexible | AWS-managed | Manual ASG |
| **Spot support** | ❌ | ✅ | ✅ Native | ✅ | ✅ |
| **GPU support** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **DaemonSets** | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Cost model** | Per vCPU/GB/hr | Per EC2 instance | Per EC2 instance | Per EC2 instance | Per EC2 instance |
| **Max pods/node** | 1 | ENI-based | ENI-based | AWS-managed | ENI-based |
| **Node SSH** | ❌ | ✅ | ✅ | ❌ | ✅ |
| **Operational** | Lowest | Low | Low | Lowest | Highest |

### Quick Decision Guide

- **Default choice:** Karpenter — best balance of flexibility, cost, and automation
- **Zero ops priority:** EKS Auto Mode — AWS manages nodes, add-ons, and scaling via managed Karpenter. Best for teams that want Kubernetes benefits without operational overhead around upgrades, autoscaling, load balancing, and storage
- **Serverless/batch:** Fargate — no nodes to manage, per-pod billing
- **Predictable, stable:** MNG — familiar ASG model, managed updates
- **Custom requirements:** Self-managed — full control, highest overhead

✅ DO:
- Use Karpenter as the default node autoscaler for new clusters
- Run system components (CoreDNS, Karpenter) on MNG or Fargate
- Use multiple instance types for availability and cost optimization

❌ DON'T:
- Use self-managed nodes without a specific technical requirement
- Run Fargate for GPU or DaemonSet-dependent workloads
- Mix Karpenter and Cluster Autoscaler on the same node groups

## Networking Quick Reference

### VPC CNI Mode Decision

| Mode | Use When | Pod Density |
|------|----------|-------------|
| **Secondary IP** (default) | Most workloads, simple setup | Limited by ENI × IPs per ENI |
| **Prefix Delegation** | >30 pods/node, IP-constrained VPC | 4-16× more pods per node |
| **Custom Networking** | Pods need different CIDR than nodes | Same as underlying mode |

### Ingress Pattern Selection

| Pattern | Best For | Key Feature |
|---------|----------|-------------|
| **ALB (via LBC)** | HTTP/HTTPS web apps | Native WAF, Cognito auth |
| **NLB (via LBC)** | TCP/UDP, gRPC, low latency | Static IPs, source IP preservation |
| **Gateway API** | Multi-team, new deployments | ✅ Recommended standard |
| **VPC Lattice** | Cross-VPC service-to-service | No sidecar, IAM auth |

### IPv4 vs IPv6

| Factor | IPv4 | IPv6 |
|--------|------|------|
| **Default choice** | ✅ Yes | When facing IP exhaustion |
| **AWS service support** | Full | Most (check specific services) |
| **Complexity** | Standard | Requires dual-stack VPC |

**For detailed networking guidance, see:** [Networking — VPC CNI & IP](references/networking.md) | [Networking — Ingress & DNS](references/networking-ingress-dns.md)

## Security Essentials

### IAM Strategy

| Approach | Use When | Setup |
|----------|----------|-------|
| **Pod Identity** | ✅ New workloads (EKS 1.24+) | EKS add-on + association |
| **IRSA** | Older clusters, Fargate | OIDC provider + trust policy |

**Key rules:**
- ✅ Use Pod Identity for new workloads — simpler setup, session tags, role chaining
- ✅ Use EKS access entries (API mode) over aws-auth ConfigMap
- ✅ Move VPC CNI permissions from node role to Pod Identity/IRSA
- ❌ Don't use wildcard conditions in IRSA trust policies
- ❌ Don't attach application permissions to node IAM roles

### Pod Security Baseline

Apply Pod Security Admission (PSA) labels to all namespaces:

```yaml
# Minimum: enforce baseline, warn on restricted
metadata:
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/warn: restricted
```

### Secrets Management

| Approach | Complexity | Best For |
|----------|-----------|----------|
| **External Secrets Operator** | Medium | ✅ GitOps workflows |
| **Secrets Store CSI** | Medium | Mount secrets as volumes |
| **KMS envelope encryption** | Low | Encrypt etcd secrets |

**Always enable KMS envelope encryption for Kubernetes secrets.**

**For detailed security guidance, see:** [Security Reference](references/security.md) | [Runtime & Network](references/security-runtime-network.md) | [Supply Chain & Compliance](references/security-supply-chain.md)

## Reliability Essentials

### Pod Disruption Budgets

**Create PDBs for every production workload with >1 replica:**

| Workload | Recommended PDB |
|----------|----------------|
| **Stateless (3+ replicas)** | `minAvailable: "50%"` |
| **Stateful quorum (3)** | `maxUnavailable: 1` |
| **Batch/job** | `maxUnavailable: "50%"` |
| **Singleton** | No PDB (would block all disruptions) |

### Health Probe Strategy

| Probe | Purpose | Key Rule |
|-------|---------|----------|
| **Startup** | Wait for slow init | Use for apps >10s startup |
| **Readiness** | Traffic routing | ✅ Check dependencies here |
| **Liveness** | Detect deadlocks | ❌ Never check dependencies |

**Critical rule:** Liveness probes must NOT check external dependencies. If the database goes down and liveness checks the DB, ALL pods restart — causing cascading failure.

### Graceful Shutdown Pattern

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 15"]
```

**Why `sleep 15`:** Gives kube-proxy and load balancer time to remove the pod from traffic routing before SIGTERM.

### Multi-AZ Distribution

```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: DoNotSchedule
```

**For detailed reliability guidance, see:** [Reliability & Resiliency — Core](references/reliability-core.md) (see also [reliability-advanced.md](references/reliability-advanced.md) for DR, deployment strategies, and large-cluster guidance)

## Cluster Upgrade Strategy

### Upgrade Sequence (Strict Order)

```
1. Control Plane → 2. EKS Add-ons → 3. Data Plane → 4. Custom Add-ons
```

### Pre-Upgrade Checklist

1. Check EKS Cluster Insights for upgrade readiness
2. Scan for deprecated APIs (Pluto, kube-no-trouble)
3. Verify add-on compatibility with target version
4. Test in non-prod environment first
5. Ensure PDBs are configured for graceful node drain
6. Back up cluster state (Velero or GitOps repo)

### Upgrade Strategy Decision

| Factor | In-Place | Blue-Green |
|--------|---------|------------|
| **Risk** | Low-Medium | Lowest |
| **Cost** | No extra | 2× during migration |
| **Rollback** | ❌ No CP rollback | ✅ Switch back |
| **Use when** | ✅ Most upgrades | Critical workloads |

### Data Plane with Karpenter

Karpenter automatically replaces nodes via drift detection after control plane upgrade. Control the speed with `disruption.budgets`:

```yaml
disruption:
  budgets:
  - nodes: "10%"  # Max 10% of nodes replaced at a time
```

**For detailed upgrade guidance, see:** [Cluster Upgrades Reference](references/cluster-upgrades.md)

## Autoscaling Quick Reference

### Node Autoscaler Selection

| | Karpenter | Cluster Autoscaler | Auto Mode |
|--|-----------|-------------------|-----------|
| **Default choice** | ✅ Yes | Legacy/Outposts | Minimal ops |
| **Scale-up speed** | ~30s | ~60-90s | AWS-managed |
| **Consolidation** | ✅ Built-in | ❌ | ✅ |
| **Customization** | High | Medium | Low |

### Pod Autoscaler Selection

| Scaler | Trigger | Use Case |
|--------|---------|----------|
| **HPA** | CPU, memory, custom | Stateless services |
| **VPA** | Historical usage | Right-sizing (recommendation mode) |
| **KEDA** | External events (SQS, Kafka) | Event-driven workloads |

**For detailed autoscaling guidance, see:** [Autoscaling Reference](references/autoscaling.md) | [Karpenter Reference](references/karpenter.md)

## Terraform Examples Quick Start

Based on [terraform-aws-modules/terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks).

### Example Selection

| Starting Point | Recommended Example |
|---------------|-------------------|
| **General production** | `karpenter` (MNG for system + Karpenter for workloads) |
| **Minimal ops** | `eks-auto-mode` |
| **Managed nodes** | `eks-managed-node-group` (AL2023 or Bottlerocket) |
| **Full node control** | `self-managed-node-group` |
| **Platform capabilities** | `eks-capabilities` (ArgoCD, ACK, KRO) |
| **Hybrid/edge** | `eks-hybrid-nodes` |

### Common Deployment Topologies

**Private cluster with Karpenter:**
```
VPC (3 AZs, terraform-aws-modules/vpc/aws)
├── Private subnets → EKS nodes (MNG for system, Karpenter for workloads)
├── Public subnets  → ALB (internet-facing)
├── Intra subnets   → EKS control plane ENIs
└── NAT Gateway     → 1 per AZ for production
```

**Multi-tenant platform:**
```
EKS Cluster (terraform-aws-modules/eks/aws)
├── kube-system         (platform: CoreDNS, kube-proxy, VPC CNI)
├── karpenter           (Karpenter controller on MNG)
├── monitoring          (shared: Prometheus, Grafana)
├── ingress             (shared: AWS LBC)
├── team-a namespace    (RBAC, NetworkPolicy, ResourceQuota)
├── team-b namespace    (RBAC, NetworkPolicy, ResourceQuota)
└── team-c namespace    (RBAC, NetworkPolicy, ResourceQuota)
```

**For detailed examples and terraform patterns, see:** [Terraform Examples Reference](references/terraform-examples.md)

## Cost Optimization Quick Wins

| Action | Savings | Effort |
|--------|---------|--------|
| **Graviton (arm64)** | 20-40% | Low |
| **Spot for non-critical** | 60-90% | Low |
| **Karpenter consolidation** | 20-30% | Low |
| **VPA right-sizing** | 15-30% | Medium |
| **gp3 over gp2** | 20% on EBS | Low |
| **VPC endpoints** | Eliminate NAT costs | Low |

**For detailed cost guidance, see:** [Cost Optimization Reference](references/cost-optimization.md) | **For scalability guidance, see:** [Scalability Reference](references/scalability.md)

## Observability Quick Reference

| Pillar | AWS-Managed | Open Source |
|--------|-------------|-------------|
| **Metrics** | Container Insights | AMP + Grafana |
| **Logs** | CloudWatch Logs | OpenSearch, Loki |
| **Traces** | X-Ray | ADOT + Jaeger/Tempo |

**Essential:** Enable EKS audit logging and GuardDuty EKS Runtime Monitoring for security visibility.

**For detailed observability guidance, see:** [Observability Reference](references/observability.md)

## EKS Capabilities

EKS Capabilities are AWS-managed features installed and updated as part of the EKS platform. They run in AWS-owned infrastructure separate from your clusters, with AWS handling scaling, patching, and upgrading.

| Capability | What It Does | When to Use Managed | When to Self-Manage |
|-----------|-------------|--------------------|--------------------|
| **ArgoCD** | GitOps continuous delivery | Multi-account hub-and-spoke, IAM IDC integration, minimal ops | Custom plugins, air-gapped, existing ArgoCD investment |
| **ACK** | Manage AWS resources via K8s CRDs (S3, RDS, IAM, etc.) | Standard AWS resource management | Specific controller version pinning, custom config |
| **KRO** | Platform abstractions via ResourceGroupDefinitions | Golden path templates, multi-resource compositions | Early adoption risk concerns, custom reconciliation logic |

**Combined pattern:** ArgoCD deploys ACK resources + KRO compositions via GitOps, providing a single workflow for both infrastructure and applications.

**For detailed ArgoCD patterns, see:** [ArgoCD Patterns Reference](references/argocd-patterns.md)

**Sources:**
- [EKS Capabilities Documentation](https://docs.aws.amazon.com/eks/latest/userguide/capabilities.html)
- [AWS Blog — Deep dive: Simplifying resource orchestration with Amazon EKS Capabilities](https://aws.amazon.com/blogs/containers/deep-dive-simplifying-resource-orchestration-with-amazon-eks-capabilities/)

## Detailed References

This skill uses **progressive disclosure** — essential guidance is in this main file, detailed reference material is loaded on demand:

- **[Security](references/security.md)** — IAM, Cluster Access Manager, Pod Identity, IRSA, pod security standards, multi-tenancy, secrets management, data encryption
- **[Security — Runtime & Network](references/security-runtime-network.md)** — Runtime threat detection (GuardDuty, seccomp, AppArmor, Falco), network policies, SG for pods, encryption in transit, detective controls
- **[Security — Supply Chain & Compliance](references/security-supply-chain.md)** — Image security (SBOMs, attestations, ECR hardening), infrastructure hardening (Bottlerocket, CIS benchmarks), regulatory compliance, incident response
- **[Networking](references/networking.md)** — VPC CNI modes (secondary IP, prefix delegation, custom networking), subnet/CIDR planning, IPv4 vs IPv6, Security Groups for Pods, IP address management
- **[Networking — Ingress & DNS](references/networking-ingress-dns.md)** — Ingress patterns (ALB, NLB, Gateway API), AWS Load Balancer Controller, service mesh, DNS/CoreDNS tuning, private cluster connectivity
- **[Reliability & Resiliency — Core](references/reliability-core.md)** — HA patterns, PDBs, health probes, load balancer health checks, lifecycle hooks, topology spread, resource management
- **[Reliability & Resiliency — Advanced](references/reliability-advanced.md)** — disaster recovery, zonal shift, deployment strategies, large cluster guidance, chaos engineering, admission-controller topology enforcement
- **[Autoscaling](references/autoscaling.md)** — Autoscaler selection, Cluster Autoscaler (IAM, Spot, overprovisioning, parameter tuning), HPA, VPA, KEDA, CoreDNS autoscaling
- **[Karpenter](references/karpenter.md)** — Operational best practices, NodePools, EC2NodeClass, Spot/interruption handling, consolidation, multiple NodePool strategy, cost controls, resource management, private clusters, CoreDNS with Karpenter
- **[Cluster Upgrades](references/cluster-upgrades.md)** — In-place and blue-green upgrades, pre-upgrade validation, add-on management, API deprecation detection, version skew policy, Bottlerocket updates, rollback procedures
- **[Cost Optimization](references/cost-optimization.md)** — CFM framework, compute/networking/storage cost strategies, observability cost management, Spot, Graviton, tagging, Kubecost
- **[Scalability](references/scalability.md)** — Scaling theory (churn rate, QPS), control plane (APF, monitoring), data plane (node sizing, diversity), cluster services (CoreDNS, Metrics Server), workload patterns, IPVS, large-cluster guidance
- **[Observability](references/observability.md)** — Observability strategy, CloudWatch Container Insights & Application Signals, Prometheus/Grafana, control plane monitoring, network performance monitoring, logging architecture, distributed tracing, GPU/AI-ML observability, detective controls, alerting patterns
- **[Terraform Examples](references/terraform-examples.md)** — terraform-aws-modules/terraform-aws-eks examples, submodules, add-on management, Provisioned Control Plane, EFA, VPC patterns, deployment topologies
- **[ArgoCD Patterns](references/argocd-patterns.md)** — ArgoCD architecture, App of Apps, ApplicationSets, GitOps Bridge, multi-cluster patterns (hub-and-spoke, decentralized, hybrid), EKS ArgoCD Capability (managed vs self-managed, migration), ACK/KRO integration, multi-tenant RBAC
- **[Container Registry](references/container-registry.md)** — ECR architecture, operating models, image promotion, vulnerability scanning, base image curation, lifecycle policies, pull-through cache, repository creation templates, managed signing (AWS Signer), archival storage class, registry configuration
- **[EKS Auto Mode](references/eks-auto-mode.md)** — Auto Mode architecture, managed NodePools/NodeClasses, migration from standard EKS, comparison with self-managed Karpenter, limitations and FAQ

**How to use:** When you need detailed information on a topic, reference the appropriate guide. Claude will load it on demand.

## Sources

- [AWS EKS Best Practices Guide](https://docs.aws.amazon.com/eks/latest/best-practices/)
- [terraform-aws-modules/terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks)
