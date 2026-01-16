# S3 bucket for Ray model storage
resource "aws_s3_bucket" "ray_models" {
  bucket = "${var.resource_prefix}-ray-models"

  tags = {
    Name        = "${var.resource_prefix}-ray-models"
    Environment = "platform"
    ManagedBy   = "terraform"
  }
}

# Enable versioning for model tracking
resource "aws_s3_bucket_versioning" "ray_models" {
  bucket = aws_s3_bucket.ray_models.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Intelligent tiering for cost optimization
resource "aws_s3_bucket_intelligent_tiering_configuration" "ray_models" {
  bucket = aws_s3_bucket.ray_models.id
  name   = "EntireModelBucket"

  tiering {
    access_tier = "ARCHIVE_ACCESS"
    days        = 90
  }

  tiering {
    access_tier = "DEEP_ARCHIVE_ACCESS"
    days        = 180
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "ray_models" {
  bucket = aws_s3_bucket.ray_models.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# IAM role for model pre-staging job
resource "aws_iam_role" "model_prestage" {
  name = "${var.resource_prefix}-model-prestage-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = {
    Name = "${var.resource_prefix}-model-prestage-role"
  }
}

# IAM policy for model pre-staging
resource "aws_iam_role_policy" "model_prestage" {
  name = "${var.resource_prefix}-model-prestage-policy"
  role = aws_iam_role.model_prestage.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.ray_models.arn,
          "${aws_s3_bucket.ray_models.arn}/*"
        ]
      }
    ]
  })
}

# Pod Identity association for model pre-staging
resource "aws_eks_pod_identity_association" "model_prestage" {
  for_each = var.clusters

  cluster_name    = each.value.name
  namespace       = "ray-system"
  service_account = "model-prestage-sa"
  role_arn        = aws_iam_role.model_prestage.arn

  tags = {
    Name = "${var.resource_prefix}-model-prestage-${each.value.name}"
  }
}

# IAM role for Ray workers to access models
resource "aws_iam_role" "ray_worker" {
  name = "${var.resource_prefix}-ray-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = {
    Name = "${var.resource_prefix}-ray-worker-role"
  }
}

# IAM policy for Ray workers (read-only)
resource "aws_iam_role_policy" "ray_worker" {
  name = "${var.resource_prefix}-ray-worker-policy"
  role = aws_iam_role.ray_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.ray_models.arn,
          "${aws_s3_bucket.ray_models.arn}/*"
        ]
      }
    ]
  })
}

# Pod Identity association for Ray workers
resource "aws_eks_pod_identity_association" "ray_worker" {
  for_each = var.clusters

  cluster_name    = each.value.name
  namespace       = "ray-system"
  service_account = "ray-worker-sa"
  role_arn        = aws_iam_role.ray_worker.arn

  tags = {
    Name = "${var.resource_prefix}-ray-worker-${each.value.name}"
  }
}

# Outputs
output "ray_models_bucket_name" {
  description = "S3 bucket name for Ray models"
  value       = aws_s3_bucket.ray_models.id
}

output "ray_models_bucket_arn" {
  description = "S3 bucket ARN for Ray models"
  value       = aws_s3_bucket.ray_models.arn
}

output "model_prestage_role_arn" {
  description = "IAM role ARN for model pre-staging"
  value       = aws_iam_role.model_prestage.arn
}

output "ray_worker_role_arn" {
  description = "IAM role ARN for Ray workers"
  value       = aws_iam_role.ray_worker.arn
}
