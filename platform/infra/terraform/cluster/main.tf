module "eks" {
  #checkov:skip=CKV_TF_1:We are using version control for those modules
  #checkov:skip=CKV_TF_2:We are using version control for those modules
  for_each = var.clusters
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.10.1"

  name                   = each.value.name
  kubernetes_version     = each.value.kubernetes_version
  endpoint_public_access = true

  vpc_id     = each.value.environment == "control-plane" ? var.hub_vpc_id : module.vpc[each.key].vpc_id
  subnet_ids = each.value.environment == "control-plane" ? var.hub_subnet_ids : module.vpc[each.key].private_subnets

  enable_cluster_creator_admin_permissions = true

  access_entries = merge(
    local.workshop_participant_iam_role_arn != "" ? {
      # This is the role that will be used by workshop participant
      participant = {
        principal_arn = local.workshop_participant_iam_role_arn

        policy_associations = {
          admin = {
            policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = {
              type = "cluster"
            }
          }
        }
      }
    } : {},
    # Add ArgoCD capability role access to spoke clusters
    each.value.environment != "control-plane" ? {
      argocd_capability = {
        principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.context_prefix}-${var.clusters[local.hub_cluster_key].name}-argocd-capability-role"

        policy_associations = {
          admin = {
            policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = {
              type = "cluster"
            }
          }
        }
      }
    } : {}
  )

  security_group_additional_rules = {
    ingress_hub_vpc = {
      description = "Allow all traffic from IDE"
      protocol    = "-1"
      from_port   = 0
      to_port     = 65535
      type        = "ingress"
      cidr_blocks = [data.aws_vpc.hub_vpc.cidr_block]
    }
  }
  
  # Enable EKS Auto Mode with IAM resources only (no default node pools)
  create_auto_mode_iam_resources = true
  
  compute_config = {
    enabled = true
    # Omit node_pools to create only IAM resources for custom node pools
  }

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest"
  }
}

################################################################################
# EKS Capabilities (Hub cluster only)
################################################################################

# ArgoCD Capability (Hub cluster only, conditional on Identity Center configuration)
resource "aws_eks_capability" "argocd" {
  for_each = { 
    for k, v in var.clusters : k => v 
    if v.environment == "control-plane" && var.identity_center_instance_arn != ""
  }
  
  cluster_name              = module.eks[each.key].cluster_name
  capability_name           = "argocd"
  type                      = "ARGOCD"
  role_arn                  = aws_iam_role.eks_capability_argocd[each.key].arn
  delete_propagation_policy = "RETAIN"

  configuration {
    argo_cd {
      aws_idc {
        idc_instance_arn = var.identity_center_instance_arn
      }
      namespace = "argocd"
      rbac_role_mapping {
        identity {
          id   = var.identity_center_admin_group_id
          type = "SSO_GROUP"
        }
        role = "ADMIN"
      }
      rbac_role_mapping {
        identity {
          id   = var.identity_center_developer_group_id
          type = "SSO_GROUP"
        }
        role = "EDITOR"
      }
    }
  }
}

# ACK Capability (all clusters)
resource "aws_eks_capability" "ack" {
  for_each = var.clusters
  
  cluster_name              = module.eks[each.key].cluster_name
  capability_name           = "ack"
  type                      = "ACK"
  role_arn                  = aws_iam_role.eks_capability_ack[each.key].arn
  delete_propagation_policy = "RETAIN"

  depends_on = [module.eks]
  tags = local.tags
}

# Kro Capability (all clusters)
resource "aws_eks_capability" "kro" {
  for_each = var.clusters
  
  cluster_name              = module.eks[each.key].cluster_name
  capability_name           = "kro"
  type                      = "KRO"
  role_arn                  = aws_iam_role.eks_capability_kro[each.key].arn
  delete_propagation_policy = "RETAIN"

  depends_on = [module.eks]
  tags = local.tags
}

################################################################################
# EKS Capabilities IAM Roles (Hub cluster only)
################################################################################

# ArgoCD Capability Role (Hub cluster only, requires Identity Center)
resource "aws_iam_role" "eks_capability_argocd" {
  for_each = { for k, v in var.clusters : k => v if v.environment == "control-plane" }
  
  name = "${local.context_prefix}-${each.value.name}-argocd-capability-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "capabilities.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = local.tags
}

# ACK Capability Role (all clusters)
resource "aws_iam_role" "eks_capability_ack" {
  for_each = var.clusters
  
  name = "${local.context_prefix}-${each.value.name}-ack-capability-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "capabilities.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = local.tags
}

# ACK Capability Role Policies (all clusters)
resource "aws_iam_role_policy_attachment" "eks_capability_ack_policies" {
  for_each = { 
    for pair in flatten([
      for k, v in var.clusters : [
        for service in ["ec2", "eks", "iam", "ecr", "s3", "dynamodb"] : {
          cluster_key = k
          service = service
          cluster = v
        }
      ]
    ]) : "${pair.cluster_key}-${pair.service}" => pair
  }

  role       = aws_iam_role.eks_capability_ack[each.value.cluster_key].name
  policy_arn = local.ack_service_policies[each.value.service]
}

# ArgoCD Capability Role Policies (requires Identity Center)
resource "aws_iam_role_policy_attachment" "eks_capability_argocd_secrets" {
  for_each = { for k, v in var.clusters : k => v if v.environment == "control-plane" }
  
  role       = aws_iam_role.eks_capability_argocd[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AWSSecretsManagerClientReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "eks_capability_argocd_codecommit" {
  for_each = { for k, v in var.clusters : k => v if v.environment == "control-plane" }
  
  role       = aws_iam_role.eks_capability_argocd[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AWSCodeCommitReadOnly"
}

# Custom policy for CodeConnections (requires Identity Center)
resource "aws_iam_role_policy" "eks_capability_argocd_codeconnections" {
  for_each = { for k, v in var.clusters : k => v if v.environment == "control-plane" }
  
  name = "codeconnections-policy"
  role = aws_iam_role.eks_capability_argocd[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "codeconnections:UseConnection",
          "codeconnections:GetConnection"
        ]
        Resource = "*"
      }
    ]
  })
}

# ArgoCD Capability EKS Access Policy Association (requires Identity Center)
resource "aws_eks_access_policy_association" "argocd" {
  for_each = { for k, v in var.clusters : k => v if v.environment == "control-plane" }
  depends_on = [
    aws_eks_capability.argocd
  ]
  cluster_name  = module.eks[each.key].cluster_name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  principal_arn = aws_iam_role.eks_capability_argocd[each.key].arn

  access_scope {
    type = "cluster"
  }
}

# ACK Capability EKS Access Policy Association (all clusters)
resource "aws_eks_access_policy_association" "ack" {
  for_each = var.clusters
  depends_on = [
    aws_eks_capability.ack
  ]
  cluster_name  = module.eks[each.key].cluster_name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  principal_arn = aws_iam_role.eks_capability_ack[each.key].arn

  access_scope {
    type = "cluster"
  }
}

# Kro Capability EKS Access Policy Association (all clusters)
resource "aws_eks_access_policy_association" "kro" {
  for_each = var.clusters
  depends_on = [
    aws_eks_capability.kro
  ]
  cluster_name  = module.eks[each.key].cluster_name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  principal_arn = aws_iam_role.eks_capability_kro[each.key].arn

  access_scope {
    type = "cluster"
  }
}

# Kro Capability Role (all clusters)
resource "aws_iam_role" "eks_capability_kro" {
  for_each = var.clusters
  
  name = "${local.context_prefix}-${each.value.name}-kro-capability-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "capabilities.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = local.tags
}

# Kro needs EKS cluster admin permissions to manage external-secrets CRDs (all clusters)
resource "aws_iam_role_policy_attachment" "eks_capability_kro_cluster_admin" {
  for_each = var.clusters
  
  role       = aws_iam_role.eks_capability_kro[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

################################################################################
# VPC for spoke cluster
################################################################################
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  for_each = local.spoke_clusters
  name = "${local.context_prefix}-${each.value.name}"
  cidr = local.vpc_cidr

  azs             = local.azs
  private_subnets = [for k, v in local.azs : cidrsubnet(local.vpc_cidr, 4, k)]
  public_subnets  = [for k, v in local.azs : cidrsubnet(local.vpc_cidr, 8, k + 48)]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
    # Tags subnets for Karpenter auto-discovery
    "karpenter.sh/discovery" = "${local.context_prefix}-${each.value.name}"
  }

  tags = local.tags
}