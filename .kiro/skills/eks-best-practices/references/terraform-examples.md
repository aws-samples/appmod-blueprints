# EKS Terraform Examples and Patterns

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Reference architecture examples from terraform-aws-modules/terraform-aws-eks with decision guidance

---

## Table of Contents

1. [Module Overview](#module-overview)
2. [Example Selection Guide](#example-selection-guide)
3. [Managed Compute Examples](#managed-compute-examples)
4. [Node Group Examples](#node-group-examples)
5. [Karpenter Example](#karpenter-example)
6. [Hybrid and Edge](#hybrid-and-edge)
7. [Reusable Submodules](#reusable-submodules)
8. [Common VPC Pattern](#common-vpc-pattern)
9. [Add-on Management](#add-on-management)
10. [Deployment Topology Patterns](#deployment-topology-patterns)
11. [Terraform State Management](#terraform-state-management)

---

## Module Overview

**[terraform-aws-modules/terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks)** is the most widely used community Terraform module for provisioning Amazon EKS clusters. It provides production-ready examples and reusable submodules.

### Architecture

```
terraform-aws-eks/
├── main.tf                          # Core EKS cluster resource
├── variables.tf                     # Module inputs (~50 inputs)
├── outputs.tf                       # Module outputs (40+)
├── modules/                         # Reusable submodules
│   ├── karpenter/                   # Karpenter IAM + infrastructure
│   ├── capability/                  # EKS Capabilities (ACK, ArgoCD, KRO)
│   ├── hybrid-node-role/            # Hybrid node IAM
│   ├── eks-managed-node-group/      # Single MNG configuration
│   ├── self-managed-node-group/     # Single self-managed ASG
│   └── fargate-profile/             # Fargate profile
└── examples/                        # Reference implementations
    ├── eks-auto-mode/
    ├── eks-capabilities/
    ├── eks-managed-node-group/
    ├── self-managed-node-group/
    ├── karpenter/
    └── eks-hybrid-nodes/
```

**Requirements:** Terraform >= 1.5.7, AWS Provider >= 6.28

### Provisioned Control Plane

The module supports EKS Provisioned Control Plane via `control_plane_scaling_config` for workloads requiring predictable, high-performance control plane capacity:

```hcl
module "eks" {
  source = "terraform-aws-modules/eks/aws"

  control_plane_scaling_config = {
    enabled   = true
    tier_name = "tier-xl"  # Options: tier-xl, tier-2xl, tier-4xl, tier-8xl
  }
}
```

| Tier | API Concurrency (seats) | Pod Scheduling (pods/sec) | etcd Size (GB) |
|------|------------------------|---------------------------|----------------|
| **XL** | 1,700 | 167 | 16 |
| **2XL** | 3,400 | 283 | 16 |
| **4XL** | 6,800 | 400 | 16 |
| **8XL** | 13,600 | 400 | 16 |

*Values shown for EKS v1.30+. Standard mode (default) auto-scales and is sufficient for most workloads.*

---

## Example Selection Guide

### By Use Case

| Use Case | Recommended Example | Complexity |
|----------|-------------------|------------|
| **Standard production cluster** | `karpenter` | Medium |
| **Minimal operations** | `eks-auto-mode` | Low |
| **Managed nodes (AL2023)** | `eks-managed-node-group` | Low |
| **Security-hardened (Bottlerocket)** | `eks-managed-node-group` | Low |
| **Full node control** | `self-managed-node-group` | Medium |
| **Platform capabilities (ArgoCD, ACK)** | `eks-capabilities` | Medium |
| **Hybrid/edge workloads** | `eks-hybrid-nodes` | High |

### Quick Decision Guide

- **Default choice:** `karpenter` — MNG for system pods + Karpenter for workloads
- **Zero ops priority:** `eks-auto-mode` — AWS manages everything
- **Need custom AMI/bootstrap:** `self-managed-node-group`
- **Standard managed nodes:** `eks-managed-node-group` (AL2023 or Bottlerocket)
- **On-premises extension:** `eks-hybrid-nodes`

### Cross-Example Comparison

| Feature | eks-auto-mode | eks-capabilities | eks-managed-node-group | self-managed-node-group | karpenter | eks-hybrid-nodes |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| **K8s Version** | 1.33 | 1.34 | 1.33 | 1.33 | 1.33 | 1.33 |
| **Compute** | Auto Mode | Auto Mode | MNG | ASG | MNG + Karpenter | Hybrid + Cilium |
| **AL2023** | — | — | ✅ | ✅ | — | — |
| **Bottlerocket** | — | — | ✅ | ✅ | — | — |
| **Spot Support** | Via Auto Mode | Via Auto Mode | Via config | Via config | ✅ Native | N/A |
| **GitOps** | — | ✅ ArgoCD | — | — | — | — |
| **Helm Provider** | — | — | — | — | ✅ | ✅ Cilium |
| **Multi-Region** | — | — | — | — | — | ✅ |

---

## Managed Compute Examples

### eks-auto-mode

**EKS Auto Mode — AWS fully manages node lifecycle.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/eks-auto-mode)

AWS handles node provisioning, scaling, OS updates, and security patches. No node groups or Karpenter needed.

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  cluster_name    = "auto-mode-cluster"
  cluster_version = "1.33"

  # Enable Auto Mode
  compute_config = {
    enabled    = true
    node_pools = ["general-purpose", "system"]
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_addons = {
    coredns                = {}
    eks-pod-identity-agent = {}
    kube-proxy             = {}
    vpc-cni                = {}
  }
}
```

**When to use:** Teams wanting minimal Kubernetes operational overhead.

**Variants included:**
- Default with `general-purpose` node pools
- Custom node pools (no presets, custom IAM)
- Disabled reference (`create = false`)

### eks-capabilities

**EKS Capabilities — ACK, ArgoCD, and KRO as managed features.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/eks-capabilities)

Deploys AWS Controllers for Kubernetes (ACK), ArgoCD, and Kubernetes Resource Orchestration (KRO) as first-class EKS features with integrated IAM.

```hcl
module "ack_capability" {
  source = "terraform-aws-modules/eks/aws//modules/capability"

  cluster_name = module.eks.cluster_name
  capability_type = "ACK"
  iam_role_policies = {
    admin = "arn:aws:iam::aws:policy/AdministratorAccess"
  }
}

module "argocd_capability" {
  source = "terraform-aws-modules/eks/aws//modules/capability"

  cluster_name    = module.eks.cluster_name
  capability_type = "ARGOCD"
  namespace       = "argocd"

  argocd_configuration = {
    admin_setup = {
      sso_enabled       = true
      identity_store_id = data.aws_ssoadmin_instances.this.identity_store_ids[0]
      roles = [{
        role_name = "ADMIN"
        groups    = [data.aws_identitystore_group.admin.group_id]
      }]
    }
  }
}
```

**When to use:** Platform teams wanting AWS-managed GitOps and Kubernetes operators.

---

## Node Group Examples

### eks-managed-node-group

**AWS Managed Node Groups with AL2023 and Bottlerocket.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/eks-managed-node-group)

Two independent configurations showing AL2023 and Bottlerocket side by side.

**AL2023 variant:**

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  cluster_name    = "mng-al2023"
  cluster_version = "1.33"

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m6i.large"]
      min_size       = 2
      max_size       = 5
      desired_size   = 2

      cloudinit_pre_nodeadm = [{
        content_type = "application/node.eks.aws"
        content      = <<-EOT
          ---
          apiVersion: node.eks.aws/v1alpha1
          kind: NodeConfig
          spec:
            kubelet:
              config:
                shutdownGracePeriod: 30s
        EOT
      }]
    }
  }

  cluster_addons = {
    coredns                = {}
    eks-pod-identity-agent = { before_compute = true }
    kube-proxy             = {}
    vpc-cni                = { before_compute = true }
  }
}
```

**Bottlerocket variant:**

```hcl
eks_managed_node_groups = {
  default = {
    ami_type       = "BOTTLEROCKET_x86_64"
    instance_types = ["m6i.large"]
    min_size       = 2
    max_size       = 5
    desired_size   = 2

    bootstrap_extra_args = <<-EOT
      [settings.host-containers.admin]
      enabled = false
      [settings.host-containers.control]
      enabled = true
      [settings.kernel.lockdown]
      value = "integrity"
    EOT
  }
}
```

**When to use:** Standard production workloads. Choose AL2023 for general use, Bottlerocket for security-hardened environments.

### self-managed-node-group

**Self-managed ASG-based node groups.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/self-managed-node-group)

Same AL2023 / Bottlerocket variants as MNG, but with full control over ASG and launch template.

**When to use:** Workloads requiring custom AMIs, specific kernel configurations, or bootstrap logic not supported by managed node groups.

---

## Karpenter Example

### karpenter

**Production-ready Karpenter on MNG — the recommended compute pattern.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/karpenter)

System pods run on a dedicated MNG while Karpenter dynamically provisions workload nodes.

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  cluster_name    = "karpenter-cluster"
  cluster_version = "1.33"

  # MNG for system pods (Karpenter controller runs here)
  eks_managed_node_groups = {
    karpenter = {
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2
    }
  }

  # Tag node security group for Karpenter discovery
  node_security_group_tags = {
    "karpenter.sh/discovery" = "karpenter-cluster"
  }

  cluster_addons = {
    coredns                = {}
    eks-pod-identity-agent = {}
    kube-proxy             = {}
    vpc-cni                = {}
  }
}

# Karpenter infrastructure (IAM, Pod Identity, instance profile)
module "karpenter" {
  source = "terraform-aws-modules/eks/aws//modules/karpenter"

  cluster_name          = module.eks.cluster_name
  enable_pod_identity   = true
  create_pod_identity_association = true

  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}

# Deploy Karpenter via Helm
resource "helm_release" "karpenter" {
  namespace  = "kube-system"
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "1.6.0"

  values = [
    <<-EOT
    nodeSelector:
      karpenter.sh/controller: 'true'
    settings:
      clusterName: ${module.eks.cluster_name}
      clusterEndpoint: ${module.eks.cluster_endpoint}
      interruptionQueue: ${module.karpenter.queue_name}
    EOT
  ]
}
```

**Post-deploy:** Apply Karpenter NodePool and EC2NodeClass CRDs, then deploy workloads.

**When to use:** Default for most production clusters — MNG stability for control plane components + Karpenter flexibility for workloads.

### VPC Subnet Tagging for Karpenter

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  private_subnet_tags = {
    "karpenter.sh/discovery" = "my-cluster"
  }
}
```

---

## Hybrid and Edge

### eks-hybrid-nodes

**Extend EKS to on-premises or edge locations.**

- [GitHub Example](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/eks-hybrid-nodes)

The most complex example — multi-region VPC peering, SSM activation for node registration, custom AMIs with Packer, and Cilium CNI.

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  cluster_name    = "hybrid-cluster"
  cluster_version = "1.33"

  # Enable hybrid node support
  remote_network_config = {
    remote_node_networks = [{ cidrs = ["172.16.0.0/16"] }]
    remote_pod_networks  = [{ cidrs = ["172.17.0.0/16"] }]
  }

  # Access entry for hybrid nodes
  access_entries = {
    hybrid = {
      principal_arn = module.hybrid_node_role.arn
      type          = "HYBRID_LINUX"
    }
  }
}

module "hybrid_node_role" {
  source = "terraform-aws-modules/eks/aws//modules/hybrid-node-role"
  # ...
}
```

**Key components:**
- VPC peering between primary (EKS) and remote (hybrid nodes) VPCs
- SSM activation for node registration
- Cilium CNI (Helm) for pod networking across hybrid boundary
- Custom Ubuntu AMI built with Packer

**When to use:** Organizations running workloads on-premises or at edge locations while maintaining a centralized EKS control plane.

---

## Reusable Submodules

The module provides 6 submodules under `modules/`:

| Submodule | Purpose | Key Resources |
|-----------|---------|---------------|
| **[karpenter](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/karpenter)** | All AWS infrastructure for Karpenter | IAM role, Pod Identity association, instance profile, SQS queue, EventBridge rules |
| **[capability](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/capability)** | EKS Capabilities (ACK, ArgoCD, KRO) | `aws_eks_capability`, IAM role + policy |
| **[hybrid-node-role](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/hybrid-node-role)** | IAM for hybrid nodes | IAM role with SSM trust policy, access entry |
| **[eks-managed-node-group](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/eks-managed-node-group)** | Single MNG | Launch template, EKS MNG, IAM role |
| **[self-managed-node-group](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/self-managed-node-group)** | Single self-managed ASG | Launch template, ASG, IAM role |
| **[fargate-profile](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/modules/fargate-profile)** | Fargate profile | EKS Fargate profile, IAM role |

---

## Common VPC Pattern

All examples use the same VPC pattern:

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = "eks-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b", "us-east-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.4.0/24", "10.0.5.0/24", "10.0.6.0/24"]
  intra_subnets   = ["10.0.7.0/28", "10.0.8.0/28", "10.0.9.0/28"]

  enable_nat_gateway = true
  single_nat_gateway = true  # Use one_nat_gateway_per_az for production

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}
```

✅ DO:
- Use `one_nat_gateway_per_az = true` for production (HA)
- Tag public subnets with `kubernetes.io/role/elb` for internet-facing LBs
- Tag private subnets with `kubernetes.io/role/internal-elb` for internal LBs
- Use 3 AZs minimum for production

❌ DON'T:
- Use `single_nat_gateway = true` in production (single point of failure)
- Forget to size subnets for pod IPs (especially with secondary IP mode)

---

## Add-on Management

### Recommended Production Add-ons

| Add-on | Purpose | Required? | Compute |
|---|---|---|---|
| **vpc-cni** | Pod networking (VPC CNI) | Yes — core networking | EC2 |
| **coredns** | Cluster DNS resolution | Yes — service discovery | EC2, Fargate, Auto Mode, Hybrid |
| **kube-proxy** | Service networking rules | Yes — ClusterIP/NodePort routing | EC2, Hybrid |
| **eks-pod-identity-agent** | Pod Identity credential injection | Yes for Pod Identity | EC2, Hybrid |
| **aws-ebs-csi-driver** | EBS persistent volumes | Yes if using EBS PVCs | EC2 |
| **aws-efs-csi-driver** | EFS shared storage | If EFS needed | EC2, Auto Mode |
| **aws-mountpoint-s3-csi-driver** | Mount S3 buckets as volumes | If S3 access needed | EC2, Auto Mode |
| **snapshot-controller** | Volume snapshots (Velero, backups) | Recommended for DR | EC2, Fargate, Auto Mode, Hybrid |
| **eks-node-monitoring-agent** | Node health issue detection | Recommended | EC2, Hybrid |
| **aws-guardduty-agent** | Runtime threat detection | Recommended for security | EC2, Auto Mode |
| **amazon-cloudwatch-observability** | Container Insights + Application Signals | If using CloudWatch | EC2, Auto Mode, Hybrid |
| **adot** | OpenTelemetry collector | If using ADOT for observability | EC2, Fargate, Auto Mode, Hybrid |
| **aws-secrets-store-csi-driver-provider** | Mount Secrets Manager / SSM params as files | If using external secrets | EC2, Auto Mode, Hybrid |
| **aws-privateca-connector** | X.509 certs from AWS Private CA | If using Private CA | EC2, Fargate, Auto Mode, Hybrid |

**Note:** EKS Auto Mode manages vpc-cni, kube-proxy, pod-identity-agent, EBS CSI driver, and AWS Load Balancer Controller automatically — do not install these as add-ons on Auto Mode clusters.

### Standard Add-on Block

```hcl
cluster_addons = {
  coredns = {
    most_recent = true
  }
  eks-pod-identity-agent = {
    before_compute = true  # Deploy before nodes for Pod Identity
  }
  kube-proxy = {
    most_recent = true
  }
  vpc-cni = {
    before_compute = true  # Deploy before nodes for networking
    most_recent    = true
    configuration_values = jsonencode({
      env = {
        ENABLE_PREFIX_DELEGATION = "true"
        WARM_PREFIX_TARGET       = "1"
      }
    })
  }
  aws-ebs-csi-driver = {
    most_recent              = true
    service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
  }
}
```

### Key Configuration Values

| Add-on | Configuration | Purpose |
|---|---|---|
| vpc-cni | `ENABLE_PREFIX_DELEGATION: "true"` | Higher pod density via /28 prefixes |
| vpc-cni | `ENABLE_POD_ENI: "true"` | Security Groups for Pods |
| vpc-cni | `ENABLE_NETWORK_POLICY: "true"` | Native network policy support |
| coredns | `computeType: "Fargate"` | Run CoreDNS on Fargate |
| ebs-csi | Pod Identity or IRSA for IAM | Required for EBS volume provisioning |

### Version Pinning

| Strategy | When to Use | Trade-off |
|---|---|---|
| `most_recent = true` | Non-production, staying current | May introduce breaking changes |
| Pin to specific version | Production | Must manually update; check compatibility |

**Recommendation:** Pin add-on versions in production and update deliberately during upgrade windows.

### Common Dependency Issues

| Issue | Cause | Solution |
|---|---|---|
| CoreDNS fails to start | No nodes available when add-on deploys | Ensure MNG/Fargate is ready first |
| VPC CNI version mismatch | Add-on incompatible with EKS version | Check compatibility matrix in EKS docs |
| EBS CSI has no IAM permissions | Missing Pod Identity / IRSA | Configure IAM before or alongside add-on |
| Add-on update blocked | Existing add-on has manual edits | Use `resolve_conflicts_on_update = "OVERWRITE"` |

✅ DO:
- Set `before_compute = true` for vpc-cni and eks-pod-identity-agent
- Use `most_recent = true` or pin specific versions
- Configure VPC CNI prefix delegation for high pod density

---

## Deployment Topology Patterns

### Private Cluster with Karpenter

```
VPC (3 AZs)
├── Private subnets → EKS nodes (MNG for system, Karpenter for workloads)
├── Public subnets  → ALB (internet-facing)
├── Intra subnets   → EKS control plane ENIs
└── NAT Gateway     → Outbound internet (1 per AZ for production)
```

```hcl
module "eks" {
  source = "terraform-aws-modules/eks/aws"

  cluster_endpoint_public_access  = false
  cluster_endpoint_private_access = true

  # MNG for system pods
  eks_managed_node_groups = {
    system = {
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 3
    }
  }

  # Karpenter manages workload nodes separately
}
```

### Multi-Tenant Platform

```
EKS Cluster (terraform-aws-modules/eks/aws)
├── kube-system         (platform: CoreDNS, kube-proxy, VPC CNI)
├── karpenter           (Karpenter controller)
├── monitoring          (shared: Prometheus, Grafana)
├── ingress             (shared: AWS LBC)
├── team-a namespace    (RBAC, NetworkPolicy, ResourceQuota)
├── team-b namespace    (RBAC, NetworkPolicy, ResourceQuota)
└── team-c namespace    (RBAC, NetworkPolicy, ResourceQuota)
```

Implement team isolation with Kubernetes resources (not Terraform module-level):
- `Role` + `RoleBinding` per namespace
- `NetworkPolicy` deny-all default per namespace
- `ResourceQuota` + `LimitRange` per namespace

### GPU/ML Workloads

Use the `karpenter` example as the base, add a GPU NodePool:

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu
spec:
  template:
    spec:
      requirements:
      - key: karpenter.k8s.aws/instance-gpu-count
        operator: Gt
        values: ["0"]
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand"]
      taints:
      - key: nvidia.com/gpu
        effect: NoSchedule
  limits:
    gpu: 32
```

**EFA (Elastic Fabric Adapter)** for distributed training and HPC — enable at both cluster and node group level:

```hcl
module "eks" {
  source = "terraform-aws-modules/eks/aws"

  eks_managed_node_groups = {
    gpu-efa = {
      instance_types   = ["p5.48xlarge"]
      enable_efa_support = true
      # EFA requires placement group for optimal performance
    }
  }
}
```

---

## Terraform State Management

### S3 Backend

Use an empty partial backend configuration in `backend.tf`:

```hcl
terraform {
  backend "s3" {}
}
```

All backend values are supplied via `-backend-config` at init time:

```hcl
# backend.hcl
bucket  = "my-state-bucket"
key     = "eks/terraform.tfstate"
region  = "us-east-1"
encrypt = true
```

```bash
terraform init -backend-config=backend.hcl
```

### State Locking

Add DynamoDB-based state locking by including `dynamodb_table` in `backend.hcl`:

```hcl
bucket         = "my-state-bucket"
key            = "eks/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "terraform-locks"
```

Create the DynamoDB table with a `LockID` string partition key.

### State Separation

Each pattern and environment should use a separate state file:

| Pattern | Environment | Recommended Key |
|---|---|---|
| EKS cluster | dev | `eks/dev/terraform.tfstate` |
| EKS cluster | prod | `eks/prod/terraform.tfstate` |
| ArgoCD + EKS | single-tenant | `eks/argocd/single-tenant/terraform.tfstate` |

### Recovering from State Issues

If state becomes corrupted or out of sync:

```bash
# List resources in state
terraform state list

# Import a resource that exists in AWS but not in state
terraform import 'module.eks_cluster.module.eks.aws_eks_cluster.this[0]' my-eks-cluster

# Remove a resource from state without destroying it
terraform state rm 'module.eks_tenants[0].kubernetes_namespace_v1.tenant["team-alpha"]'
```

---

**Source:** [terraform-aws-modules/terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks)
