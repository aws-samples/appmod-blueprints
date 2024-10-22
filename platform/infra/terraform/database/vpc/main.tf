variable "vpc_name" {
  description = "Name of the existing VPC (leave empty to create a new VPC)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (used when creating a new VPC)"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = []
}

data "aws_vpcs" "existing_vpcs" {
  filter {
    name   = "tag:Name"
    values = [var.vpc_name]
  }
}

locals {
  vpc_exists = length(data.aws_vpcs.existing_vpcs.ids) > 0
}

data "aws_vpc" "existing_vpc" {
  count = local.vpc_exists ? 1 : 0
  id    = data.aws_vpcs.existing_vpcs.ids[0]
}

resource "aws_vpc" "new_vpc" {
  count      = local.vpc_exists ? 0 : 1
  cidr_block = var.vpc_cidr
  
  tags = {
    Name = "${var.name_prefix}mod-engg-wksp-vpc"
  }
}

locals {
  vpc_id   = local.vpc_exists ? data.aws_vpc.existing_vpc[0].id : aws_vpc.new_vpc[0].id
  vpc_cidr = local.vpc_exists ? data.aws_vpc.existing_vpc[0].cidr_block : var.vpc_cidr
}

data "aws_subnets" "existing_subnets" {
  count = local.vpc_exists ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  availability_zones = length(var.availability_zones) > 0 ? var.availability_zones : slice(data.aws_availability_zones.available.names, 0, 3)
}

resource "aws_subnet" "new_subnets" {
  count             = local.vpc_exists ? 0 : length(local.availability_zones)
  vpc_id            = local.vpc_id
  cidr_block        = cidrsubnet(local.vpc_cidr, 8, count.index)
  availability_zone = local.availability_zones[count.index]

  tags = {
    Name = "${var.name_prefix}mod-engg-wksp-subnet-${count.index}"
  }
}

data "aws_subnet" "subnet_details" {
  count = length(local.subnet_ids)
  id    = local.subnet_ids[count.index]
}

locals {
  #subnet_ids = local.vpc_exists ? data.aws_subnets.existing_subnets[0].ids : aws_subnet.new_subnets[*].id
  subnet_ids = local.vpc_exists ? data.aws_subnets.existing_subnets[0].ids : aws_subnet.new_subnets[*].id
  subnet_ids_with_az = [for subnet in data.aws_subnet.subnet_details : {
    id = subnet.id
    az = subnet.availability_zone
  }]
  
  selected_subnet_ids = distinct([
    for subnet in local.subnet_ids_with_az :
    subnet.id if index(local.subnet_ids_with_az, subnet) < 2 || 
               subnet.az != local.subnet_ids_with_az[0].az
  ])
  #subnet_azs = local.vpc_exists ? data.aws_subnets.existing_subnets[0].ids : aws_subnet.new_subnets[*].availability_zone
}


output "vpc_id" {
  value = local.vpc_id
}

#output "subnet_ids" {
 # value = local.subnet_ids
#}

output "subnet_ids" {
  value = local.selected_subnet_ids
}

output "vpc_cidr" {
  value = local.vpc_cidr
}

output "availability_zones" {
  value = distinct([for subnet in local.subnet_ids_with_az : subnet.az if contains(local.selected_subnet_ids, subnet.id)])
}

output "vpc_exists" {
  value = local.vpc_exists
}