terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.23.0, <= 6.34.0"
    }
  }

  # Backend configuration disabled - using local state
  # backend "s3" {
  #   # bucket provided via -backend-config
  #   key = "clusters/terraform.tfstate"
  #   use_lockfile = true
  # }
}
