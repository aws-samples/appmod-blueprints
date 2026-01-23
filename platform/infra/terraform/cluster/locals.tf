locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
  }

  # ACK service policy mappings for EKS Capabilities
  ack_service_policies = {
    ec2      = "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
    eks      = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
    iam      = "arn:aws:iam::aws:policy/IAMFullAccess"
    ecr      = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess"
    s3       = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
    dynamodb = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
  }

}

locals {
  azs                       = slice(data.aws_availability_zones.available.names, 0, 2)
  hub_cluster_key           = [for k, v in var.clusters : k if v.environment == "control-plane"][0]
  hub_cluster               = [for k, v in var.clusters : v if v.environment == "control-plane"][0]
  spoke_clusters            = { for k, v in var.clusters : k => v if v.environment != "control-plane" }
  vpc_cidr                  = "10.0.0.0/16"

  # Convert assumed role ARN to IAM role ARN for EKS access entries
  # Handles both cases:
  # 1. Assumed role: arn:aws:sts::012345678910:assumed-role/WSParticipantRole/Participant -> arn:aws:iam::012345678910:role/WSParticipantRole
  # 2. IAM role: arn:aws:iam::012345678910:role/WSParticipantRole -> arn:aws:iam::012345678910:role/WSParticipantRole (unchanged)
  workshop_participant_iam_role_arn = var.workshop_participant_role_arn != "" ? (
    can(regex("^arn:aws:sts::", var.workshop_participant_role_arn)) ? 
    format("arn:aws:iam::%s:role/%s", 
      split(":", var.workshop_participant_role_arn)[4],
      split("/", split(":", var.workshop_participant_role_arn)[5])[1]
    ) : var.workshop_participant_role_arn
  ) : ""
}
