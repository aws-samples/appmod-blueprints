terraform {
  required_version = ">= 1.3.0"
  backend "s3" {}
}

locals {
  name_prefix = "${var.cluster_name_prefix}-${terraform.workspace}"
}

module "aurora" {
  source             = "../../database/aurora"
  cluster_name_prefix = var.cluster_name_prefix
  vpc_id             = var.vpc_id
  vpc_private_subnets = var.vpc_private_subnets
  vpc_cidr           = var.vpc_cidr
  name_prefix        = local.name_prefix
  db_username        = var.db_username
  availability_zones = var.availability_zones
}

module "ec2" {
  source              = "../../database/ec2"
  cluster_name_prefix = var.cluster_name_prefix
  vpc_id              = var.vpc_id
  vpc_private_subnets = var.vpc_private_subnets
  vpc_cidr            = var.vpc_cidr
  name_prefix         = local.name_prefix
  key_name            = var.key_name
  region              = var.aws_region
}
