provider "aws" {
  # Rate limiting and retry configuration to handle API throttling
  retry_mode = "adaptive"
  max_retries = 10
  
  # Increase default timeouts for operations
  default_tags {
    tags = {
      ManagedBy = "Terraform"
    }
  }
}
