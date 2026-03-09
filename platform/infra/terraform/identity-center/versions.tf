terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.23.0, <= 6.34.0"
    }
  }

  backend "s3" {
    key = "identity-center/terraform.tfstate"
    use_lockfile = true
  }
}
