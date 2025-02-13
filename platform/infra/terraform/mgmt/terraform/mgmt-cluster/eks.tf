################################################################################
# Cluster
################################################################################

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.10"

  cluster_name    = local.name
  cluster_version = "1.30"

  # Give the Terraform identity admin access to the cluster
  # which will allow it to deploy resources into the cluster
  enable_cluster_creator_admin_permissions = true
  cluster_endpoint_public_access           = true

  # Enable Auto Mode and reference our custom NodePool
  cluster_compute_config = {
    enabled    = true
  }

  cluster_addons = {
    # EKS Auto Mode makes this not needed. Would we want to add any tolerations though here outside of Karpenter?
    # coredns = {
    #   configuration_values = jsonencode({
    #     tolerations = [
    #       # Allow CoreDNS to run on the same nodes as the Karpenter controller
    #       # for use during cluster creation when Karpenter nodes do not yet exist
    #       {
    #         key    = "karpenter.sh/controller"
    #         value  = "true"
    #         effect = "NoSchedule"
    #       }
    #     ]
    #   })
    # }
    eks-pod-identity-agent = {}
    kube-proxy             = {}
    vpc-cni                = {}
    # aws-ebs-csi-driver     = { # EKS Auto Mode installs and manages EBS CSI driver so this is not needed.
    #  service_account_role_arn = module.ebs_csi_driver_irsa.iam_role_arn
    #}
  }

  enable_irsa = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # EKS Auto Mode will now manage node groups, so no need for this section.
  # eks_managed_node_groups = {
  #   static_ng = {
  #     use_custom_launch_template = false
  #     launch_template_name       = ""
  #     instance_types             = ["m5.2xlarge"]

  #     min_size     = 2
  #     max_size     = 6
  #     desired_size = 2
  #     disk_size    = 100

  #     block_device_mappings = {
  #       xvda = {
  #         device_name = "/dev/xvda"
  #         ebs = {
  #           volume_size           = 100
  #           volume_type           = "gp3"
  #           delete_on_termination = true
  #         }
  #       }
  #     }
  #     labels = {
  #       # Used to ensure Karpenter runs on nodes that it does not manage
  #       "karpenter.sh/controller" = "true"
  #     }
  #   }
  # }

    tags = merge(local.tags, {
  #   # NOTE - if creating multiple security groups with this module, only tag the
  #   # security group that Karpenter should utilize with the following tag
  #   # (i.e. - at most, only one security group should have this tag in your account)
  #   "karpenter.sh/discovery" = local.name
      "eks.amazonaws.com/discovery" = "modern-engineering"
    })
  }

output "configure_kubectl" {
  description = "Configure kubectl: make sure you're logged in with the correct AWS profile and run the following command to update your kubeconfig"
  value       = "aws eks --region ${local.region} update-kubeconfig --name ${local.name}"
}

################################################################################
# EBS Configuration
################################################################################

#module "ebs_csi_driver_irsa" { #-------------------------------------------------------------------------------------------------------------------
#  source                = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
#  role_name             = "${local.name}-ebs-csi-driver"
#  role_policy_arns = {
#    policy = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
#  }
#  oidc_providers = {
#    main = {
#      provider_arn               = module.eks.oidc_provider_arn
#      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
#    }
#  }
#  tags = local.tags
#}

## This remiains the same since EKS Auto Mode and Karpenter utilize StorageClass in the same way. EKS Auto Mode simply does not need the IRSA role Karpenter needed.
resource "kubernetes_storage_class" "ebs-gp3-sc" {
  metadata {
    name = "gp3"
  }

  storage_provisioner = "ebs.csi.eks.amazonaws.com" # Altering this to target EKS Auto Mode.
  volume_binding_mode = "WaitForFirstConsumer"
  reclaim_policy      = "Delete"

  parameters = {
    type      = "gp3"     # Required: Specify volume type # Is this fine?-------------------------------------------------------------------------------------------------------------------
    encrypted = "true"    # Required: EKS Auto Mode provisions encrypted volumes # Is this fine?-------------------------------------------------------------------------------------------------------------------
  }
}

################################################################################
# Controller & Node IAM roles
################################################################################

# EKS Auto Mode will now manage node groups so no need for this section.
# module "karpenter" {
#   source  = "terraform-aws-modules/eks/aws//modules/karpenter"
#   version = "~> 20.26.0"

#   cluster_name = module.eks.cluster_name

#   # Name needs to match role name passed to the EC2NodeClass
#   node_iam_role_use_name_prefix   = false
#   node_iam_role_name              = local.name
#   create_pod_identity_association = true

#   tags = local.tags
# }

# Revised IAM Role for EKS Auto Mode
resource "aws_iam_role" "eks_node_role" {
  name = "modern-engineering"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "modern-engineering-node-role"
  }
}

# Attach Required IAM Policies for EKS Auto Mode
resource "aws_iam_role_policy_attachment" "eks_node_policies" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodeMinimalPolicy",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/AmazonSSMPatchAssociation"
  ])

  policy_arn = each.key
  role       = aws_iam_role.eks_node_role.name
}

# Attach Custom IAM Policy for Auto Mode (custom-aws-tagging-eks-auto)
resource "aws_iam_policy" "custom_aws_tagging_eks_auto" {
  name        = "custom-aws-tagging-eks-auto"
  description = "Custom IAM policy for EKS Auto Mode node permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Compute"
        Effect = "Allow"
        Action = [
          "ec2:CreateFleet",
          "ec2:RunInstances",
          "ec2:CreateLaunchTemplate"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
          StringLike = {
            "aws:RequestTag/eks:kubernetes-node-class-name" = "*"
            "aws:RequestTag/eks:kubernetes-node-pool-name"  = "*"
          }
        }
      },
      {
        Sid    = "Storage"
        Effect = "Allow"
        Action = [
          "ec2:CreateVolume",
          "ec2:CreateSnapshot"
        ]
        Resource = [
          "arn:aws:ec2:*:*:volume/*",
          "arn:aws:ec2:*:*:snapshot/*"
        ]
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
        }
      },
      {
        Sid    = "Networking"
        Effect = "Allow"
        Action = "ec2:CreateNetworkInterface"
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
          StringLike = {
            "aws:RequestTag/eks:kubernetes-cni-node-name" = "*"
          }
        }
      },
      {
        Sid    = "LoadBalancer"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateTargetGroup",
          "elasticloadbalancing:CreateListener",
          "elasticloadbalancing:CreateRule",
          "ec2:CreateSecurityGroup"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
        }
      },
      {
        Sid    = "ShieldProtection"
        Effect = "Allow"
        Action = [
          "shield:CreateProtection"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
        }
      },
      {
        Sid    = "ShieldTagResource"
        Effect = "Allow"
        Action = [
          "shield:TagResource"
        ]
        Resource = "arn:aws:shield::*:protection/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/eks:eks-cluster-name" = "$${aws:PrincipalTag/eks:eks-cluster-name}"
          }
        }
      }
    ]
  })
}

## Below is responsible for giving EKS Auto Mode the permissions it needs to access the cluster and create its needed instances.
# Attach the Custom IAM Policy to the EKS Node Role
resource "aws_iam_role_policy_attachment" "custom_aws_tagging_eks_auto_attach" {
  policy_arn = aws_iam_policy.custom_aws_tagging_eks_auto.arn
  role       = aws_iam_role.eks_node_role.name
}

# Create the access entry for EC2 nodes in EKS Auto Mode
resource "aws_eks_access_entry" "auto_mode_node_access" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.eks_node_role.arn  # Dynamically uses modern-engineering role
  type          = "EC2"
}

# Associate the Auto Node Policy with EKS Auto Mode Nodes
resource "aws_eks_access_policy_association" "auto_mode_node_policy" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.eks_node_role.arn  # Dynamically uses modern-engineering role
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAutoNodePolicy"

  access_scope {
    type = "cluster"
  }
}

################################################################################
# Helm charts
################################################################################

# EKS Auto Mode will now manage node groups so no need for this section.
# resource "helm_release" "karpenter" {
#   namespace           = "kube-system"
#   name                = "karpenter"
#   repository          = "oci://public.ecr.aws/karpenter"
#   chart               = "karpenter"
#   version             = "0.36.2"
#   wait                = false

#   values = [
#     <<-EOT
#     nodeSelector:
#       karpenter.sh/controller: 'true'
#     tolerations:
#       - key: CriticalAddonsOnly
#         operator: Exists
#       - key: karpenter.sh/controller
#         operator: Exists
#         effect: NoSchedule
#     settings:
#       clusterName: ${module.eks.cluster_name}
#       clusterEndpoint: ${module.eks.cluster_endpoint}
#       interruptionQueue: ${module.karpenter.queue_name}
#     EOT
#   ]

#   lifecycle {
#     ignore_changes = [
#       repository_password
#     ]
#   }

# }