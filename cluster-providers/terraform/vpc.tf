# VPC + networking — mirrors the Crossplane composition's networking section
# 2 public subnets, 2 private subnets, IGW, single NAT GW, route tables

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  vpc_prefix = split(".", var.vpc_cidr)[0] # e.g. "10" from "10.0.0.0/16"
  vpc_second = split(".", var.vpc_cidr)[1] # e.g. "0"
  common_tags = {
    "platform.gitops.io/cluster" = var.cluster_name
    "platform.gitops.io/prefix"  = var.resource_prefix
    "ManagedBy"                  = "terraform"
  }
}

resource "aws_vpc" "hub" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(local.common_tags, { Name = var.cluster_name })
}

# --- Internet Gateway ---
resource "aws_internet_gateway" "hub" {
  vpc_id = aws_vpc.hub.id
  tags   = merge(local.common_tags, { Name = "${var.cluster_name}-igw" })
}

# --- Elastic IP + NAT Gateway (single AZ, matches Crossplane composition) ---
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${var.cluster_name}-nat-eip" })
}

resource "aws_nat_gateway" "hub" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(local.common_tags, { Name = "${var.cluster_name}-natgw" })
  depends_on    = [aws_internet_gateway.hub]
}

# --- Public Subnets (AZ-a, AZ-b) ---
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.hub.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 3, count.index) # /19 blocks: .0.0/19, .32.0/19
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags = merge(local.common_tags, {
    Name                     = "${var.cluster_name}-public-${local.azs[count.index]}"
    "kubernetes.io/role/elb" = "1"
  })
}

# --- Private Subnets (AZ-a, AZ-b) ---
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.hub.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 3, count.index + 4) # /19 blocks: .128.0/19, .160.0/19
  availability_zone = local.azs[count.index]
  tags = merge(local.common_tags, {
    Name                              = "${var.cluster_name}-private-${local.azs[count.index]}"
    "kubernetes.io/role/internal-elb" = "1"
  })
}

# --- Route Tables ---
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.hub.id
  tags   = merge(local.common_tags, { Name = "${var.cluster_name}-public-rt" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.hub.id
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.hub.id
  tags   = merge(local.common_tags, { Name = "${var.cluster_name}-private-rt" })
}

resource "aws_route" "private_nat" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.hub.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
