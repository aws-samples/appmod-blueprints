terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 4.67.0, < 6.0.0"
    }
  }

  # Backend configuration provided via CLI parameters
  backend "s3" {
    # bucket provided via -backend-config
    key = "clusters/terraform.tfstate"
    use_lockfile = true
  }
}
