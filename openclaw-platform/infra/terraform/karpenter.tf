# karpenter.tf — Karpenter controller bootstrap (IAM + SQS)
# Controller itself and NodePools/EC2NodeClass deploy via GitOps.
# No managed kata nodegroup; Karpenter provisions all workload nodes (system, kata-nested, kata-metal).

# SQS queue for EC2 interruption events (spot reclaim, health events)
resource "aws_sqs_queue" "karpenter_interruption" {
  name                      = "${local.cluster_name}-karpenter"
  message_retention_seconds = 300
  tags                      = local.tags
}

resource "aws_sqs_queue_policy" "karpenter_interruption" {
  queue_url = aws_sqs_queue.karpenter_interruption.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["events.amazonaws.com", "sqs.amazonaws.com"] }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.karpenter_interruption.arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "karpenter_spot" {
  name = "${local.cluster_name}-karpenter-spot"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Spot Instance Interruption Warning"]
  })
  tags = local.tags
}

resource "aws_cloudwatch_event_target" "karpenter_spot" {
  rule = aws_cloudwatch_event_rule.karpenter_spot.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_cloudwatch_event_rule" "karpenter_health" {
  name = "${local.cluster_name}-karpenter-health"
  event_pattern = jsonencode({
    source      = ["aws.health"]
    detail-type = ["AWS Health Event"]
  })
  tags = local.tags
}

resource "aws_cloudwatch_event_target" "karpenter_health" {
  rule = aws_cloudwatch_event_rule.karpenter_health.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

resource "aws_cloudwatch_event_rule" "karpenter_rebalance" {
  name = "${local.cluster_name}-karpenter-rebalance"
  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Instance Rebalance Recommendation"]
  })
  tags = local.tags
}

resource "aws_cloudwatch_event_target" "karpenter_rebalance" {
  rule = aws_cloudwatch_event_rule.karpenter_rebalance.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

# ---- Karpenter node IAM role (assumed by EC2 instances Karpenter launches) ----
resource "aws_iam_role" "karpenter_node" {
  name = "KarpenterNodeRole-${local.cluster_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "karpenter_node_worker" {
  role       = aws_iam_role.karpenter_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}
resource "aws_iam_role_policy_attachment" "karpenter_node_cni" {
  role       = aws_iam_role.karpenter_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}
resource "aws_iam_role_policy_attachment" "karpenter_node_ecr" {
  role       = aws_iam_role.karpenter_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}
resource "aws_iam_role_policy_attachment" "karpenter_node_ssm" {
  role       = aws_iam_role.karpenter_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "karpenter_node" {
  name = "KarpenterNodeInstanceProfile-${local.cluster_name}"
  role = aws_iam_role.karpenter_node.name
  tags = local.tags
}

# EKS access entry for Karpenter nodes so the kubelet can authenticate
resource "aws_eks_access_entry" "karpenter_node" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.karpenter_node.arn
  type          = "EC2_LINUX"
  tags          = local.tags
}

# ---- Karpenter controller IAM role (via Pod Identity) ----
resource "aws_iam_role" "karpenter_controller" {
  name = "KarpenterControllerRole-${local.cluster_name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "karpenter_controller" {
  name = "karpenter-controller"
  role = aws_iam_role.karpenter_controller.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowScopedEC2"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateTags",
          "ec2:TerminateInstances",
          "ec2:DeleteLaunchTemplate",
        ]
        Resource = "*"
      },
      {
        Sid      = "AllowEC2Describe"
        Effect   = "Allow"
        Action   = ["ec2:Describe*", "pricing:GetProducts", "ssm:GetParameter"]
        Resource = "*"
      },
      {
        Sid      = "AllowInterruptionQueue"
        Effect   = "Allow"
        Action   = ["sqs:DeleteMessage", "sqs:GetQueueUrl", "sqs:ReceiveMessage"]
        Resource = aws_sqs_queue.karpenter_interruption.arn
      },
      {
        Sid      = "AllowPassNodeRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.karpenter_node.arn
      },
      {
        Sid      = "AllowClusterDescribe"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = module.eks.cluster_arn
      }
    ]
  })
}

resource "aws_eks_pod_identity_association" "karpenter" {
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "karpenter"
  role_arn        = aws_iam_role.karpenter_controller.arn
  tags            = local.tags
}

# Discovery tags on VPC subnets + security group are required for Karpenter to
# find where to launch nodes. The subnets already get tagged by the EKS module;
# add karpenter.sh/discovery explicitly here.
resource "aws_ec2_tag" "karpenter_subnet" {
  count       = length(module.vpc.private_subnets)
  resource_id = module.vpc.private_subnets[count.index]
  key         = "karpenter.sh/discovery"
  value       = local.cluster_name
}

resource "aws_ec2_tag" "karpenter_sg" {
  resource_id = module.eks.node_security_group_id
  key         = "karpenter.sh/discovery"
  value       = local.cluster_name
}
