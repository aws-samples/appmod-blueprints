  module "vpc" {
    source             = "../vpc"
    vpc_name           = var.vpc_name
    vpc_cidr           = var.vpc_cidr
    name_prefix        = var.name_prefix
    availability_zones = var.availability_zones
  }
  
  module "aurora" {
    source      = "../aurora"
    vpc_id      = module.vpc.vpc_id
    subnet_ids  = module.vpc.subnet_ids
    vpc_cidr    = module.vpc.vpc_cidr
    name_prefix = var.name_prefix
    db_username = var.db_username
    availability_zones = module.vpc.availability_zones
  }
  
  module "ec2" {
    source      = "../ec2"
    vpc_id      = module.vpc.vpc_id
    subnet_id   = module.vpc.subnet_ids[0]
    vpc_cidr    = module.vpc.vpc_cidr
    name_prefix = var.name_prefix
    key_name    = var.key_name 
  }
  