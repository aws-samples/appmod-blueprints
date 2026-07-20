# EKS Auto Mode

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Auto Mode architecture, managed NodePools/NodeClasses, migration from standard EKS, comparison with self-managed Karpenter, limitations and FAQ

---

## Overview

Amazon EKS Auto Mode represents a significant evolution in Kubernetes infrastructure management, combining secure and scalable cluster infrastructure with integrated Kubernetes capabilities managed by AWS. The service provides fully-managed worker node operations, eliminating the need for customers to set up Managed Node Groups or AutoScaling groups.

The key architectural difference is that EKS Auto Mode uses a Karpenter-based system that automatically provisions EC2 instances in response to pod requests. These instances run on Bottlerocket AMIs with pre-installed add-ons like EBS CSI drivers, making the infrastructure truly managed by AWS.

## When to Use Auto Mode

Auto Mode is geared towards users that want the benefits of Kubernetes and EKS but need to minimize operational burden around upgrades and installation/maintenance of critical platform pieces like autoscaling, load balancing, and storage. Auto Mode takes EKS a step further in the minimization of the undifferentiated heavy lifting that goes along with Kubernetes maintenance.

### Decision: Auto Mode vs Standard EKS with Karpenter

| Factor | EKS Auto Mode | Standard EKS + Karpenter |
|--------|--------------|--------------------------|
| **Autoscaling management** | Fully managed by AWS | Customer manages Karpenter deployment, scaling, and upgrades |
| **Add-ons (LBC, EBS CSI, VPC CNI, CoreDNS, kube-proxy)** | Managed off-cluster by AWS | Customer installs and maintains |
| **AMI customization** | No -- Bottlerocket only | Full control (AL2023, Bottlerocket, custom AMIs) |
| **NodePool/NodeClass config** | Works same as open source Karpenter | Works same as open source Karpenter |
| **Host-level tooling** | DaemonSets only (no AMI customization) | AMI customization or DaemonSets |
| **Compliance (custom AMI pinning, air-gapped)** | Limited -- no custom AMIs | Full control |
| **Cost** | Standard EC2 pricing + Auto Mode management fee on managed nodes | Standard EC2 pricing + self-managed operational cost |
| **Mix with other compute** | Yes -- can run MNG alongside Auto Mode nodes | Yes -- can run MNG alongside Karpenter nodes |
| **Troubleshooting managed components** | AWS Support ticket (components run off-cluster) | Direct access to pod logs |

**Choose Auto Mode when:** Minimal ops is the priority, standard Bottlerocket AMIs are acceptable, and you don't need custom AMI configurations or air-gapped setups.

**Choose Standard EKS + Karpenter when:** You need full control over AMIs, node configuration, add-on versions, or have compliance requirements (PCI-DSS, FedRAMP) that mandate AMI pinning and detailed audit trails of node-level components.

## Comparison with Other Scaling Approaches

| Approach | Instance Flexibility | Management Overhead | Node Group Required |
|----------|---------------------|--------------------|--------------------|
| **Cluster Autoscaler (CAS)** | Single instance type per node group | High -- manual node group management | Yes |
| **Self-managed Karpenter** | Multiple instance types via EC2 Fleet API | Medium -- customer manages Karpenter | No |
| **EKS Auto Mode** | Multiple instance types via managed Karpenter | Low -- AWS manages everything | No |

## Architecture

### Managed Components (Run Off-Cluster)

EKS Auto Mode completely automates the deployment of most data plane components needed for production-grade Kubernetes:

- **Karpenter** -- autoscaling the compute of your cluster
- **AWS Load Balancer Controller** -- automated Elastic Load Balancer integration
- **VPC CNI** -- pod networking
- **Cluster DNS** -- service discovery
- **kube-proxy** -- service networking
- **EBS CSI** -- persistent storage
- **EKS Pod Identity Agent** -- IAM for pods
- **EKS Node Monitoring Agent** -- node health

These components run in AWS-managed infrastructure separate from your cluster. The only pods running in the data plane of a new Auto Mode cluster are Kubernetes Metrics Server pods.

### Operational Features

- Automatic pod-driven scaling without manual node group configuration
- Built-in managed load balancer controllers that automatically create ALB/NLB based on Ingress resources
- Integrated security features with pre-configured Pod Identity
- Maximum node runtime of 21 days with automatic replacement

## Default NodePools

A new Auto Mode cluster comes pre-configured with two NodePools:

### general-purpose

Provisions nodes with:
- Capacity Type: On-Demand
- Instance Types: C, M, or R families
- Instance Generation: 4+
- Architecture: AMD (x86_64)
- OS: Linux
- Disruption: max 10% of nodes disrupted at any time, consolidation when empty or underutilized

### system

Similar to general-purpose with key differences:
- Allows both ARM and AMD architecture
- Tainted with `CriticalAddonsOnly=true:NoSchedule` -- reserved for EKS add-ons

### Custom NodePools

You may create custom NodePools depending on your needs. NodePool configuration works the same as open source Karpenter. Consult the Karpenter documentation for details.

## Cost Model

EKS Auto Mode uses standard EC2 pricing plus an Auto Mode management fee that applies only to Auto Mode-managed nodes. Self-managed nodes (MNG or self-managed ASGs) running alongside Auto Mode nodes are not subject to the management fee.

## Migration from Standard EKS to Auto Mode

You can enable EKS Auto Mode on an existing cluster. See the [official migration guide](https://docs.aws.amazon.com/eks/latest/userguide/auto-enable-existing.html) for detailed instructions. Key steps:

1. **Enable Auto Mode** on the cluster via AWS Console, CLI, or Terraform
2. **Uninstall redundant components** -- after enabling Auto Mode, remove any self-managed components now managed by Auto Mode (Karpenter, AWS Load Balancer Controller, EBS CSI driver, etc.)
3. **Ensure add-ons are up-to-date** before migration -- see AWS documentation for version requirements
4. **Test workload scheduling** -- verify pods schedule correctly on Auto Mode-managed nodes

## Limitations and FAQ

### AMI Customization
Currently the only supported AMIs are Amazon-provided Bottlerocket. No custom AMIs.

### Host-Level Software
Because AMI customization is not supported, if you need host-level software for things like security scanning, deploy it as a Kubernetes DaemonSet.

### Troubleshooting Managed Components
With EKS Auto Mode, components like the AWS Load Balancer Controller and Karpenter are managed outside your cluster. You won't have direct visibility into their logs. If troubleshooting is needed, create an AWS Support Ticket.

### Mixed Compute
You may run managed node groups alongside Auto Mode-managed nodes in the same cluster.

### Upgrades
Customers retain responsibility for cluster version management. Performing a cluster upgrade triggers rolling updates of Auto Mode worker nodes automatically.

**Sources:**
- [EKS Auto Mode Documentation](https://docs.aws.amazon.com/eks/latest/userguide/automode.html)
- [EKS Best Practices Guide -- Auto Mode](https://docs.aws.amazon.com/eks/latest/best-practices/)
