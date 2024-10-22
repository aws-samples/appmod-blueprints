terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"  # You can adjust this version as needed
    }
  }
}

provider "aws" {
  region = var.aws_region  # We'll define this variable
}
