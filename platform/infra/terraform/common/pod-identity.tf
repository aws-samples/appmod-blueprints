################################################################################
# ArgoCD Hub Management
################################################################################

resource "aws_eks_pod_identity_association" "argocd_controller" {
  cluster_name    = local.hub_cluster.name
  namespace       = "argocd"
  service_account = "argocd-application-controller"
  role_arn        = aws_iam_role.argocd_central.arn
}

resource "aws_eks_pod_identity_association" "argocd_server" {
  cluster_name    = local.hub_cluster.name
  namespace       = "argocd"
  service_account = "argocd-server"
  role_arn        = aws_iam_role.argocd_central.arn
}

resource "aws_eks_pod_identity_association" "argocd_repo_server" {
  cluster_name    = local.hub_cluster.name
  namespace       = "argocd"
  service_account = "argocd-repo-server"
  role_arn        = aws_iam_role.argocd_central.arn
}

################################################################################
# External Secrets EKS Access
################################################################################
module "external_secrets_pod_identity" {
  for_each = { for k, v in var.clusters : k => v if try(v.addons.enable_external_secrets, false) }
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.4.0"

  name = "external-secrets"

  attach_external_secrets_policy        = true
  external_secrets_kms_key_arns         = ["arn:aws:kms:${each.value.region}:*:key/${each.value.name}/*"]
  external_secrets_secrets_manager_arns = ["arn:aws:secretsmanager:${each.value.region}:*:secret:${local.context_prefix}*"]
  external_secrets_ssm_parameter_arns   = ["arn:aws:ssm:${each.value.region}:*:parameter/${each.value.name}/*"]
  external_secrets_create_permission    = each.value.environment == "control-plane" ? true : false #only for hub
  attach_custom_policy                  = each.value.environment == "control-plane" ? true : false #only for hub
  policy_statements = [
    {
      sid       = "ecr"
      actions   = ["ecr:*"]
      resources = ["*"]
    }
  ]
  # Pod Identity Associations
  associations = merge(
    {
      addon = {
        cluster_name    = each.value.name
        namespace       = local.external_secrets.namespace
        service_account = local.external_secrets.service_account
      }
    },
    each.value.environment == "control-plane" ? { # only for hub cluster
      keycloak-config = {
        cluster_name    = each.value.name
        namespace       = local.keycloak.namespace
        service_account = local.keycloak.service_account
      }
      } : {
      fleet = {
        cluster_name    = each.value.name
        namespace       = local.external_secrets.namespace_fleet
        service_account = local.external_secrets.service_account
      }
    }
  )

  tags = local.tags
}

################################################################################
# CloudWatch Observability EKS Access
################################################################################
module "aws_cloudwatch_observability_pod_identity" {
  for_each = local.spoke_clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "aws-cloudwatch-observability"

  attach_aws_cloudwatch_observability_policy = true

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.cloudwatch.namespace
      service_account = local.cloudwatch.service_account
    }
  }

  tags = local.tags
}

################################################################################
# Kyverno Policy Reporter SecurityHub Access
################################################################################
module "kyverno_policy_reporter_pod_identity" {
  for_each = local.spoke_clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "kyverno-policy-reporter"

  additional_policy_arns = {
    AWSSecurityHub = "arn:aws:iam::aws:policy/AWSSecurityHubFullAccess"
  }

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.kyverno.namespace
      service_account = local.kyverno.service_account
    }
  }

  tags = local.tags
}

################################################################################
# EBS CSI EKS Access
################################################################################
module "aws_ebs_csi_pod_identity" {
  for_each = local.spoke_clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "aws-ebs-csi"

  attach_aws_ebs_csi_policy = true
  aws_ebs_csi_kms_arns      = ["arn:aws:kms:*:*:key/*"]

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.ebs_csi_controller.namespace
      service_account = local.ebs_csi_controller.service_account
    }
  }

  tags = local.tags
}

################################################################################
# AWS ALB Ingress Controller EKS Access
################################################################################
module "aws_lb_controller_pod_identity" {
  for_each = local.spoke_clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "aws-lbc"

  attach_aws_lb_controller_policy = true


  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.aws_load_balancer_controller.namespace
      service_account = local.aws_load_balancer_controller.service_account
    }
  }

  tags = local.tags
}

################################################################################
# VPC CNI Helper
################################################################################
resource "aws_iam_policy" "cni_metrics_helper_pod_identity_policy" {
  name_prefix = "cni_metrics_helper_pod_identity"
  path        = "/"
  description = "Policy to allow cni metrics helper put metcics to cloudwatch"

  # Terraform's "jsonencode" function converts a
  # Terraform expression result to valid JSON syntax.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "cloudwatch:PutMetricData",
        ]
        Effect   = "Allow"
        Resource = "*"
      },
    ]
  })
}

module "cni_metrics_helper_pod_identity" {
  for_each = local.spoke_clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"
  name     = "cni-metrics-helper-${each.value.name}"

  additional_policy_arns = {
    "cni-metrics-help" : aws_iam_policy.cni_metrics_helper_pod_identity_policy.arn
  }

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.cni_metric_helper.namespace
      service_account = local.cni_metric_helper.service_account
    }
  }
  tags = local.tags
}

################################################################################
# ADOT EKS Access
################################################################################

module "adot_collector_pod_identity" {
  for_each = local.spoke_clusters # only for spoke clusters
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "adot-collector"

  additional_policy_arns = {
    "PrometheusReadWrite" : "arn:aws:iam::aws:policy/AmazonPrometheusRemoteWriteAccess"
  }

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = local.adot_collector.namespace
      service_account = local.adot_collector.service_account
    }
  }
  tags = local.tags
}


# Define variables for the policy URLs
variable "policy_arn_urls" {
  type = map(string)
  default = {
    iam      = "https://raw.githubusercontent.com/aws-controllers-k8s/iam-controller/main/config/iam/recommended-policy-arn"
    ec2      = "https://raw.githubusercontent.com/aws-controllers-k8s/ec2-controller/main/config/iam/recommended-policy-arn"
    eks      = "https://raw.githubusercontent.com/aws-controllers-k8s/eks-controller/main/config/iam/recommended-policy-arn"
    ecr      = "https://raw.githubusercontent.com/aws-controllers-k8s/ecr-controller/main/config/iam/recommended-policy-arn"
    s3       = "https://raw.githubusercontent.com/aws-controllers-k8s/s3-controller/main/config/iam/recommended-policy-arn"
    dynamodb = "https://raw.githubusercontent.com/aws-controllers-k8s/dynamodb-controller/main/config/iam/recommended-policy-arn"
  }
}

variable "inline_policy_urls" {
  type = map(string)
  default = {
    iam      = "https://raw.githubusercontent.com/aws-controllers-k8s/iam-controller/main/config/iam/recommended-inline-policy"
    ec2      = "https://raw.githubusercontent.com/aws-controllers-k8s/ec2-controller/main/config/iam/recommended-inline-policy"
    eks      = "https://raw.githubusercontent.com/aws-controllers-k8s/eks-controller/main/config/iam/recommended-inline-policy"
    ecr      = "https://raw.githubusercontent.com/aws-controllers-k8s/ecr-controller/main/config/iam/recommended-inline-policy"
    s3       = "https://raw.githubusercontent.com/aws-controllers-k8s/s3-controller/main/config/iam/recommended-inline-policy"
    dynamodb = "https://raw.githubusercontent.com/aws-controllers-k8s/dynamodb-controller/main/config/iam/recommended-inline-policy"
  }
}

# Fetch the recommended policy ARNs
data "http" "policy_arn" {
  for_each = var.policy_arn_urls
  url      = each.value
}

# Fetch the recommended inline policies
data "http" "inline_policy" {
  for_each = var.inline_policy_urls
  url      = each.value
}

# Create locals for ACK cluster-service combinations
locals {
  ack_combinations = {
    for combination in flatten([
      for cluster_key, cluster_value in var.clusters : [
        for service in ["iam", "ec2", "eks", "ecr", "s3", "dynamodb"] : {
          key           = "${cluster_key}-${service}"
          cluster_key   = cluster_key
          cluster_value = cluster_value
          service       = service
        }
      ]
    ]) : combination.key => combination
  }
}

# Create IAM roles for ACK controllers
resource "aws_iam_role" "ack_controller" {
  for_each = local.ack_combinations
  name     = "${var.resource_prefix}-ack-${each.value.service}-controller-role-${each.value.cluster_key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEksAuthToAssumeRoleForPodIdentity"
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = ["sts:AssumeRole", "sts:TagSession"]
      }
    ]
  })
  description = "IRSA role for ACK ${each.value.service} controller deployment on EKS cluster ${each.value.cluster_key} using Helm charts"
  tags        = local.tags
}

# First, create a local variable to determine valid policies
locals {
  valid_policies = {
    for k, v in data.http.policy_arn : k => v.status_code == 200 ? trimspace(v.body) : null
  }
}

# Then modify your policy attachment to only create when there's a valid ARN
resource "aws_iam_role_policy_attachment" "ack_controller_policy_attachment" {
  for_each = {
    for k, v in local.ack_combinations : k => v
    if lookup(local.valid_policies, v.service, null) != null && can(regex("^arn:aws", lookup(local.valid_policies, v.service, "")))
  }

  role       = aws_iam_role.ack_controller[each.key].name
  policy_arn = local.valid_policies[each.value.service]
}

resource "aws_iam_role_policy" "ack_controller_inline_policy" {
  for_each = local.ack_combinations

  role = aws_iam_role.ack_controller[each.key].name
  policy = can(jsondecode(data.http.inline_policy[each.value.service].body)) ? data.http.inline_policy[each.value.service].body : jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "${each.value.service}:*"
        ]
        Resource = "*"
      }
    ]
  })
}

data "aws_iam_policy_document" "ack_controller_cross_account_policy" {
  for_each = local.ack_combinations

  statement {
    sid     = "AllowCrossAccountAccess"
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.context_prefix}-cluster-mgmt-${each.key}"
    ]
  }
}

resource "aws_iam_role_policy" "ack_controller_cross_account_policy" {
  for_each = local.ack_combinations

  role   = aws_iam_role.ack_controller[each.key].name
  policy = data.aws_iam_policy_document.ack_controller_cross_account_policy[each.key].json
}

resource "aws_eks_pod_identity_association" "ack_controller" {
  for_each = local.ack_combinations

  cluster_name    = each.value.cluster_value.name
  namespace       = "ack-system"
  service_account = "ack-${each.value.service}-controller"
  role_arn        = aws_iam_role.ack_controller[each.key].arn
}

################################################################################
# ACK Workload Roles (Cross-Account Access)
################################################################################

# Define service-specific managed policies
locals {
  ack_managed_policies = {
    iam = ["arn:aws:iam::aws:policy/IAMFullAccess"]
    ec2 = [
      "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
      "arn:aws:iam::aws:policy/AmazonVPCFullAccess"
    ]
    eks = [
      "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
      "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
      "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
      "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    ]
    ecr = [
      "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess"
    ]
    s3 = [
      "arn:aws:iam::aws:policy/AmazonS3FullAccess"
    ]
    dynamodb = [
      "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
    ]
  }

  # Combined structure for roles and policy attachments
  ack_workload_resources = {
    for k, v in local.ack_combinations : k => {
      combination   = v
      policies      = lookup(local.ack_managed_policies, v.service, [])
      inline_policy = lookup(local.ack_inline_policies, v.service, null)
    }
  }
}

# Create ACK workload roles that can be assumed by ACK controllers
resource "aws_iam_role" "ack_workload_role" {
  for_each = local.ack_workload_resources
  name     = "${local.context_prefix}-cluster-mgmt-${each.key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.ack_controller[each.key].arn
        }
        Action = ["sts:AssumeRole", "sts:TagSession"]
      }
    ]
  })

  description = "Workload role for ACK ${each.key} controller"
  tags        = local.tags
}

# Attach managed policies to ACK workload roles
resource "aws_iam_role_policy_attachment" "ack_workload_managed_policies" {
  for_each = {
    for combo in flatten([
      for k, v in local.ack_workload_resources : [
        for policy in v.policies : {
          combination_key = k
          policy          = policy
          key             = "${k}-${replace(policy, "/[^a-zA-Z0-9]/", "-")}"
        }
      ]
    ]) : combo.key => combo
  }

  role       = aws_iam_role.ack_workload_role[each.value.combination_key].name
  policy_arn = each.value.policy
}

# Attach inline policies to ACK workload roles
resource "aws_iam_role_policy" "ack_workload_inline_policies" {
  for_each = {
    for k, v in local.ack_workload_resources : k => v
    if v.inline_policy != null
  }

  name   = "ack-${each.value.combination.service}-workload-policy"
  role   = aws_iam_role.ack_workload_role[each.key].name
  policy = jsonencode(each.value.inline_policy)
}

# Define service-specific inline policies
locals {
  ack_inline_policies = {
    iam = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "iam:CreateRole",
            "iam:DeleteRole",
            "iam:GetRole",
            "iam:UpdateRole",
            "iam:ListRoles",
            "iam:TagRole",
            "iam:UntagRole",
            "iam:AttachRolePolicy",
            "iam:DetachRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:CreatePolicy",
            "iam:DeletePolicy",
            "iam:GetPolicy",
            "iam:ListPolicies",
            "iam:CreatePolicyVersion",
            "iam:DeletePolicyVersion",
            "iam:GetPolicyVersion",
            "iam:ListPolicyVersions"
          ]
          Resource = "*"
        }
      ]
    }
    ec2 = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "ec2:CreateVpc",
            "ec2:DeleteVpc",
            "ec2:DescribeVpcs",
            "ec2:ModifyVpcAttribute",
            "ec2:CreateSubnet",
            "ec2:DeleteSubnet",
            "ec2:DescribeSubnets",
            "ec2:ModifySubnetAttribute",
            "ec2:CreateSecurityGroup",
            "ec2:DeleteSecurityGroup",
            "ec2:DescribeSecurityGroups",
            "ec2:AuthorizeSecurityGroupIngress",
            "ec2:AuthorizeSecurityGroupEgress",
            "ec2:RevokeSecurityGroupIngress",
            "ec2:RevokeSecurityGroupEgress",
            "ec2:CreateTags",
            "ec2:DeleteTags",
            "ec2:DescribeTags"
          ]
          Resource = "*"
        }
      ]
    }
    eks = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "eks:CreateCluster",
            "eks:DeleteCluster",
            "eks:DescribeCluster",
            "eks:ListClusters",
            "eks:UpdateClusterConfig",
            "eks:UpdateClusterVersion",
            "eks:TagResource",
            "eks:UntagResource",
            "eks:CreateNodegroup",
            "eks:DeleteNodegroup",
            "eks:DescribeNodegroup",
            "eks:ListNodegroups",
            "eks:UpdateNodegroupConfig",
            "eks:UpdateNodegroupVersion",
            "eks:CreateAddon",
            "eks:DeleteAddon",
            "eks:DescribeAddon",
            "eks:ListAddons",
            "eks:UpdateAddon",
            "eks:CreateAccessEntry",
            "eks:DeleteAccessEntry",
            "eks:DescribeAccessEntry",
            "eks:ListAccessEntries",
            "eks:UpdateAccessEntry",
            "eks:AssociateAccessPolicy",
            "eks:DisassociateAccessPolicy",
            "eks:ListAssociatedAccessPolicies",
            "iam:PassRole"
          ]
          Resource = "*"
        }
      ]
    }
    ecr = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "ecr:CreateRepository",
            "ecr:DeleteRepository",
            "ecr:DescribeRepositories",
            "ecr:ListTagsForResource",
            "ecr:TagResource",
            "ecr:UntagResource",
            "ecr:PutRepositoryPolicy",
            "ecr:DeleteRepositoryPolicy",
            "ecr:GetRepositoryPolicy",
            "ecr:PutLifecyclePolicy",
            "ecr:GetLifecyclePolicy",
            "ecr:DeleteLifecyclePolicy",
            "ecr:PutImageScanningConfiguration",
            "ecr:PutImageTagMutability",
            "ecr:PutReplicationConfiguration",
            "ecr:DescribeRegistry",
            "ecr:GetRegistryPolicy",
            "ecr:PutRegistryPolicy",
            "ecr:DeleteRegistryPolicy"
          ]
          Resource = "*"
        }
      ]
    }
    s3 = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "s3:CreateBucket",
            "s3:DeleteBucket",
            "s3:GetBucketLocation",
            "s3:GetBucketVersioning",
            "s3:ListBucket",
            "s3:ListAllMyBuckets",
            "s3:PutBucketVersioning",
            "s3:PutBucketTagging",
            "s3:GetBucketTagging",
            "s3:DeleteBucketTagging",
            "s3:PutBucketPolicy",
            "s3:GetBucketPolicy",
            "s3:DeleteBucketPolicy",
            "s3:PutBucketAcl",
            "s3:GetBucketAcl",
            "s3:PutBucketCors",
            "s3:GetBucketCors",
            "s3:DeleteBucketCors",
            "s3:PutBucketNotification",
            "s3:GetBucketNotification"
          ]
          Resource = "*"
        }
      ]
    }
    dynamodb = {
      Version = "2012-10-17"
      Statement = [
        {
          Effect = "Allow"
          Action = [
            "dynamodb:CreateTable",
            "dynamodb:DeleteTable",
            "dynamodb:DescribeTable",
            "dynamodb:ListTables",
            "dynamodb:UpdateTable",
            "dynamodb:TagResource",
            "dynamodb:UntagResource",
            "dynamodb:ListTagsOfResource",
            "dynamodb:CreateBackup",
            "dynamodb:DeleteBackup",
            "dynamodb:DescribeBackup",
            "dynamodb:ListBackups",
            "dynamodb:RestoreTableFromBackup",
            "dynamodb:PutItem",
            "dynamodb:GetItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
            "dynamodb:Query",
            "dynamodb:Scan"
          ]
          Resource = "*"
        }
      ]
    }
  }
}

################################################################################
# Kargo ECR Access
################################################################################

resource "aws_iam_role" "kargo_controller_role" {
  name = "${local.hub_cluster.name}-kargo-controller-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  description = "IAM role for Kargo to access Amazon ECR"
  tags        = local.tags
}

resource "aws_iam_role_policy_attachment" "kargo_ecr_policy" {
  role       = aws_iam_role.kargo_controller_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_eks_pod_identity_association" "kargo_controller" {
  cluster_name    = local.hub_cluster.name
  namespace       = local.kargo.namespace
  service_account = local.kargo.service_account
  role_arn        = aws_iam_role.kargo_controller_role.arn
}

################################################################################
# Crossplane Provider AWS EKS Access
################################################################################
module "crossplane_provider_aws_pod_identity" {
  for_each = { for k, v in var.clusters : k => v if try(v.addons.enable_crossplane, false) }
  source   = "terraform-aws-modules/eks-pod-identity/aws"
  version  = "~> 1.11.0"

  name = "crossplane-provider-aws-${each.key}"

  additional_policy_arns = {
    AdministratorAccess = "arn:aws:iam::aws:policy/AdministratorAccess"
  }

  associations = {
    addon = {
      cluster_name    = each.value.name
      namespace       = "crossplane-system"
      service_account = "provider-aws"
    }
  }

  tags = local.tags
}
