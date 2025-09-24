module "eks" {
  #checkov:skip=CKV_TF_1:We are using version control for those modules
  #checkov:skip=CKV_TF_2:We are using version control for those modules
  for_each = var.clusters
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31.6"

  cluster_name                   = "${local.context_prefix}-${each.value.name}"
  cluster_version                = each.value.cluster_version
  cluster_endpoint_public_access = true

  vpc_id     = each.value.environment == "control-plane" ? var.hub_vpc_id : module.vpc[each.key].vpc_id
  subnet_ids = each.value.environment == "control-plane" ? var.hub_subnet_ids : module.vpc[each.key].private_subnets

  enable_cluster_creator_admin_permissions = true

  cluster_compute_config = {
    enabled    = true
    node_pools = ["general-purpose", "system"]
  }

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest"
  }
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