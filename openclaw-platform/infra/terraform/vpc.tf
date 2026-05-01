module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 4, k)]
  public_subnets  = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 8, k + 48)]
  intra_subnets   = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 8, k + 52)]

  enable_nat_gateway     = true
  single_nat_gateway     = true
  enable_dns_hostnames   = true
  enable_dns_support     = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"            = 1
    "karpenter.sh/discovery"                     = local.cluster_name
  }

  intra_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }

  tags = local.tags
}

# EKS Auto Mode places nodes on intra subnets — add NAT route so they can pull images
resource "aws_route" "intra_nat_gateway" {
  count                  = length(module.vpc.intra_route_table_ids) > 0 ? 1 : 0
  route_table_id         = module.vpc.intra_route_table_ids[0]
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = module.vpc.natgw_ids[0]

  depends_on = [module.vpc]
}
