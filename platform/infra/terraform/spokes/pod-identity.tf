################################################################################
# External Secrets EKS Access
################################################################################
module "external_secrets_pod_identity" {
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "external-secrets"

  attach_external_secrets_policy        = true
  external_secrets_ssm_parameter_arns   = ["arn:aws:ssm:*:*:parameter/*"] # In case you want to restrict access to specific SSM parameters "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter/${local.name}/*"
  external_secrets_secrets_manager_arns = ["arn:aws:secretsmanager:*:*:secret:*"] # In case you want to restrict access to specific Secrets Manager secrets "arn:aws:secretsmanager:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:secret:${local.name}/*"
  external_secrets_kms_key_arns         = ["arn:aws:kms:*:*:key/*"] # In case you want to restrict access to specific KMS keys "arn:aws:kms:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:key/*"
  external_secrets_create_permission    = false

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = module.eks.cluster_name
      namespace       = local.external_secrets.namespace
      service_account = local.external_secrets.service_account
    },
    fleet = {
      cluster_name    = module.eks.cluster_name
      namespace       = local.external_secrets.namespace_fleet
      service_account = local.external_secrets.service_account
    }
  }

  tags = local.tags
}

################################################################################
# CloudWatch Observability EKS Access
################################################################################
module "aws_cloudwatch_observability_pod_identity" {
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "aws-cloudwatch-observability"

  attach_aws_cloudwatch_observability_policy = true

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name = module.eks.cluster_name
      namespace       = "amazon-cloudwatch"
      service_account = "cloudwatch-agent"
    }
  }

  tags = local.tags
}

################################################################################
# Kyverno Policy Reporter SecurityHub Access
################################################################################
module "kyverno_policy_reporter_pod_identity" {
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "kyverno-policy-reporter"

  additional_policy_arns = {
    AWSSecurityHub = "arn:aws:iam::aws:policy/AWSSecurityHubFullAccess"
  }

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name = module.eks.cluster_name
      namespace       = "kyverno"
      service_account = "policy-reporter"
    }
  }

  tags = local.tags
}

################################################################################
# EBS CSI EKS Access
################################################################################
module "aws_ebs_csi_pod_identity" {
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "aws-ebs-csi"

  attach_aws_ebs_csi_policy = true
  aws_ebs_csi_kms_arns      = ["arn:aws:kms:*:*:key/*"]

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "ebs-csi-controller-sa"
    }
  }

  tags = local.tags
}

################################################################################
# AWS ALB Ingress Controller EKS Access
################################################################################
module "aws_lb_controller_pod_identity" {
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "aws-lbc"

  attach_aws_lb_controller_policy = true


  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name = module.eks.cluster_name
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
  source = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"
  name = "cni-metrics-helper-${terraform.workspace}"

  additional_policy_arns = {
    "cni-metrics-help" : aws_iam_policy.cni_metrics_helper_pod_identity_policy.arn
  }

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "cni-metrics-helper"
    }
  }
  tags = local.tags
}

################################################################################
# ACK S3 Controller EKS Access
################################################################################
module "ack_s3_pod_identity" {
  count   = local.aws_addons.enable_ack_s3 ? 1 : 0
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "ack-s3-controller"

  additional_policy_arns = {
    AmazonS3FullAccess = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
  }

  policy_statements = [
    {
      sid    = "S3AllPermission"
      effect = "Allow"
      actions = [
        "s3:*",
        "s3-object-lambda:*"
      ]
      resources = ["*"]
    },
    {
      sid    = "S3ReplicationPassRole"
      effect = "Allow"
      actions = ["iam:PassRole"]
      resources = ["*"]
      condition = {
        StringEquals = {
          "iam:PassedToService" = "s3.amazonaws.com"
        }
      }
    }
  ]

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = module.eks.cluster_name
      namespace       = "ack-system"
      service_account = "ack-s3-controller"
    }
  }

  tags = local.tags
}

################################################################################
# ACK DynamoDB Controller EKS Access
################################################################################
module "ack_dynamodb_pod_identity" {
  count   = local.aws_addons.enable_ack_dynamodb ? 1 : 0
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 1.11.0"

  name = "ack-dynamodb-controller"

  additional_policy_arns = {
    AmazonDynamoDBFullAccess = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
  }

  policy_statements = [
    {
      sid    = "DynamoDBAllPermission"
      effect = "Allow"
      actions = [
        "dynamodb:*"
      ]
      resources = ["*"]
    }
  ]

  # Pod Identity Associations
  associations = {
    addon = {
      cluster_name    = module.eks.cluster_name
      namespace       = "ack-system"
      service_account = "ack-dynamodb-controller"
    }
  }

  tags = local.tags
}
