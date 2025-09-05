terraform {
  required_version = ">= 1.3.0"
  backend "s3" {}
}

module "aurora" {
  source      = "../../database/aurora"
  vpc_id      = var.vpc_id
  vpc_private_subnets  = var.vpc_private_subnets
  vpc_cidr    = var.vpc_cidr
  name_prefix = var.name_prefix
  db_username = var.db_username
  availability_zones = var.availability_zones
}

module "ec2" {
  source      = "../../database/ec2"
  vpc_id      = var.vpc_id
  vpc_private_subnets   = var.vpc_private_subnets
  vpc_cidr    = var.vpc_cidr
  name_prefix = var.name_prefix
  key_name    = var.key_name
  region      = var.aws_region
}
