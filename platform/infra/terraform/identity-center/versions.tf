terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.42.0, <= 6.46.0"
    }
  }

  backend "s3" {
    key = "identity-center/terraform.tfstate"
    use_lockfile = true
  }
}
