################################################################################
# External Secrets EKS Access
################################################################################
module "external_secrets_pod_identity" {
  count   = local.aws_addons.enable_external_secrets ? 1 : 0
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.4.0"

  name = "external-secrets"

  attach_external_secrets_policy        = true
  external_secrets_kms_key_arns         = ["arn:aws:kms:${local.region}:*:key/${local.cluster_info.cluster_name}/*"]
  external_secrets_secrets_manager_arns = [
    "arn:aws:secretsmanager:${local.region}:*:secret:${local.cluster_info.cluster_name}/*",
    # Allow access to common platform secrets (e.g., Backstage PostgreSQL password)
    "arn:aws:secretsmanager:${local.region}:*:secret:${var.resource_prefix}-*"
  ]
  external_secrets_ssm_parameter_arns   = ["arn:aws:ssm:${local.region}:*:parameter/${local.cluster_info.cluster_name}/*"]
  external_secrets_create_permission    = true
  attach_custom_policy                  = true
  policy_statements = [
    {
      sid       = "ecr"
      actions   = ["ecr:*"]
      resources = ["*"]
    }
  ]
  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = local.cluster_info.cluster_name
      namespace       = local.external_secrets.namespace
      service_account = local.external_secrets.service_account
    }
    keycloak-config = {
      cluster_name    = local.cluster_info.cluster_name
      namespace       = "keycloak"
      service_account = "keycloak-config"
    }
  }

  tags = local.tags
}

################################################################################
# Crossplane AWS Provider EKS Pod Identity
################################################################################
# NOTE: AdministratorAccess is used for demo purposes. In production environments,
# this should be restricted to only the specific AWS resources that Crossplane
# will manage to follow security best practices and principle of least privilege.
module "crossplane_aws_provider_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.4.0"

  name = "crossplane-aws-provider"

  attach_custom_policy = true
  policy_statements = [
    {
      sid = "CrossplaneAdministratorAccess"
      # WARNING: AdministratorAccess provides full AWS access
      # In production, replace with specific policies for resources Crossplane will manage
      actions   = ["*"]
      resources = ["*"]
    }
  ]

  # Pod Identity Associations
  associations = {
    crossplane-provider = {
      cluster_name    = local.cluster_info.cluster_name
      namespace       = "crossplane-system"
      service_account = "provider-aws"
    }
  }

  tags = local.tags
}

################################################################################
# ArgoCD Hub Management
################################################################################
data "aws_ssm_parameter" "argocd_hub_role" {
  name = "${var.resource_prefix}-argocd-central-role"
}

resource "aws_eks_pod_identity_association" "argocd_controller" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-application-controller"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}

resource "aws_eks_pod_identity_association" "argocd_server" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-server"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}

resource "aws_eks_pod_identity_association" "argocd_repo_server" {
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "argocd"
  service_account = "argocd-repo-server"
  role_arn        = data.aws_ssm_parameter.argocd_hub_role.value
}


# Define variables for the policy URLs
variable "policy_arn_urls" {
  type    = map(string)
  default = {
    iam      = "https://raw.githubusercontent.com/aws-controllers-k8s/iam-controller/main/config/iam/recommended-policy-arn"
    ec2      = "https://raw.githubusercontent.com/aws-controllers-k8s/ec2-controller/main/config/iam/recommended-policy-arn"
    eks      = "https://raw.githubusercontent.com/aws-controllers-k8s/eks-controller/main/config/iam/recommended-policy-arn"
    s3       = "https://raw.githubusercontent.com/aws-controllers-k8s/s3-controller/main/config/iam/recommended-policy-arn"
    dynamodb = "https://raw.githubusercontent.com/aws-controllers-k8s/dynamodb-controller/main/config/iam/recommended-policy-arn"
  }
}

variable "inline_policy_urls" {
  type    = map(string)
  default = {
    iam      = "https://raw.githubusercontent.com/aws-controllers-k8s/iam-controller/main/config/iam/recommended-inline-policy"
    ec2      = "https://raw.githubusercontent.com/aws-controllers-k8s/ec2-controller/main/config/iam/recommended-inline-policy"
    eks      = "https://raw.githubusercontent.com/aws-controllers-k8s/eks-controller/main/config/iam/recommended-inline-policy"
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

# Create IAM roles for ACK controllers
resource "aws_iam_role" "ack_controller" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])
  name        = "${var.resource_prefix}-ack-${each.key}-controller-role-mgmt"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "AllowEksAuthToAssumeRoleForPodIdentity"
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = ["sts:AssumeRole", "sts:TagSession"]
      }
    ]
  })
  description = "IRSA role for ACK ${each.key} controller deployment on EKS cluster using Helm charts"
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
    for k, v in local.valid_policies : k => v
    if v != null && can(regex("^arn:aws", v))
  }

  role       = aws_iam_role.ack_controller[each.key].name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "ack_controller_inline_policy" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])

  role   = aws_iam_role.ack_controller[each.key].name
  policy = can(jsondecode(data.http.inline_policy[each.key].body)) ? data.http.inline_policy[each.key].body : jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "${each.key}:*"
        ]
        Resource = "*"
      }
    ]
  })
}

data "aws_iam_policy_document" "ack_controller_cross_account_policy" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])

  statement {
    sid    = "AllowCrossAccountAccess"
    effect = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    resources = [
      for account in split(" ", var.account_ids) : "arn:aws:iam::${account}:role/${local.name}-cluster-mgmt-${each.key}"
    ]
  }
}

resource "aws_iam_role_policy" "ack_controller_cross_account_policy" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])

  role   = aws_iam_role.ack_controller[each.key].name
  policy = data.aws_iam_policy_document.ack_controller_cross_account_policy[each.key].json
}

resource "aws_eks_pod_identity_association" "ack_controller" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])

  cluster_name    = local.cluster_info.cluster_name
  namespace       = "ack-system"
  service_account = "ack-${each.key}-controller"
  role_arn        = aws_iam_role.ack_controller[each.key].arn
}

################################################################################
# Kargo ECR Access
################################################################################

resource "aws_iam_role" "kargo_controller_role" {
  name = "${local.name}-kargo-controller-role"
  
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
  cluster_name    = local.cluster_info.cluster_name
  namespace       = "kargo"
  service_account = "kargo-controller"
  role_arn        = aws_iam_role.kargo_controller_role.arn
}

################################################################################
# ACK Workload Roles (Cross-Account Access)
################################################################################

# Create ACK workload roles that can be assumed by ACK controllers
resource "aws_iam_role" "ack_workload_role" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])
  name     = "${local.name}-cluster-mgmt-${each.key}"
  
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
    s3 = [
      "arn:aws:iam::aws:policy/AmazonS3FullAccess"
    ]
    dynamodb = [
      "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
    ]
  }
}

# Attach managed policies to ACK workload roles
resource "aws_iam_role_policy_attachment" "ack_workload_managed_policies" {
  for_each = {
    for combo in flatten([
      for service, policies in local.ack_managed_policies : [
        for policy in policies : {
          service = service
          policy  = policy
          key     = "${service}-${replace(policy, "/[^a-zA-Z0-9]/", "-")}"
        }
      ]
    ]) : combo.key => combo
  }

  role       = aws_iam_role.ack_workload_role[each.value.service].name
  policy_arn = each.value.policy
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

# Attach inline policies to ACK workload roles
resource "aws_iam_role_policy" "ack_workload_inline_policies" {
  for_each = toset(["iam", "ec2", "eks", "s3", "dynamodb"])

  name   = "ack-${each.key}-workload-policy"
  role   = aws_iam_role.ack_workload_role[each.key].name
  policy = jsonencode(local.ack_inline_policies[each.key])
}