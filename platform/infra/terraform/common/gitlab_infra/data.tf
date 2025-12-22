# Data sources for common stack
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_iam_session_context" "current" {
  # This data source provides information on the IAM source role of an STS assumed role
  # For non-role ARNs, this data source simply passes the ARN through issuer ARN
  # Ref https://github.com/terraform-aws-modules/terraform-aws-eks/issues/2327#issuecomment-1355581682
  # Ref https://github.com/hashicorp/terraform-provider-aws/issues/28381
  arn = data.aws_caller_identity.current.arn
}

data "aws_eks_cluster" "clusters" {
  for_each = var.clusters
  name     = each.value.name
}

# Reference the managed policies by name instead of ID
data "aws_cloudfront_cache_policy" "use_origin_cache_control_headers_query_strings" {
  name = "UseOriginCacheControlHeaders-QueryStrings"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

# Get public subnets for the hub cluster
data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [local.cluster_vpc_ids[local.hub_cluster.name]]
  }
  tags = {
    "kubernetes.io/role/elb" = "1"
  }
}

data "aws_subnet" "public" {
  for_each = toset(data.aws_subnets.public.ids)
  id       = each.value
}