locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
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
    replace(
      replace(var.workshop_participant_role_arn, "sts::", "iam::"),
      regex("assumed-role/([^/]+)/.*", var.workshop_participant_role_arn)[0],
      "role/${regex("assumed-role/([^/]+)/.*", var.workshop_participant_role_arn)[1]}"
    ) : var.workshop_participant_role_arn
  ) : ""
}
