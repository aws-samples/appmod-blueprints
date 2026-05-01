module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = var.cluster_version

  cluster_endpoint_public_access = var.cluster_endpoint_public_access

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  # Managed system nodegroup — runs ArgoCD, Karpenter, CoreDNS, system workloads.
  # No Auto Mode. Karpenter (installed via GitOps) handles all workload scaling.
  eks_managed_node_groups = {
    system = {
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      ami_type       = "AL2023_x86_64_STANDARD"
      labels         = { role = "system" }
    }
  }

  # Core EKS managed addons
  cluster_addons = {
    kube-proxy = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
    }
    coredns = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
    }
    vpc-cni = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
    }
    eks-pod-identity-agent = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
    }
    aws-ebs-csi-driver = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
      service_account_role_arn    = aws_iam_role.ebs_csi.arn
    }
    aws-efs-csi-driver = {
      most_recent                 = true
      resolve_conflicts_on_create = "OVERWRITE"
      resolve_conflicts_on_update = "OVERWRITE"
      service_account_role_arn    = aws_iam_role.efs_csi.arn
    }
  }

  # Tag subnets for Karpenter auto-discovery
  node_security_group_tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }

  # Use EKS Access Entries API — auditable via CloudTrail, no aws-auth ConfigMap
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  access_entries = {}

  tags = local.tags
}
