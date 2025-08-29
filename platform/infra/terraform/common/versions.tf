terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 4.67.0, < 6.0.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.1"
    }
  }

  # Backend configuration provided via CLI parameters
  backend "s3" {
    # bucket and dynamodb_table provided via -backend-config
    key    = "terraform.tfstate"
  }
}
