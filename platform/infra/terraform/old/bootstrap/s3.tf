resource "random_uuid" "uuid" {}

resource "aws_s3_bucket" "terraform-states-s3-bucket" {
  bucket = "${var.tfe_project}-${random_uuid.uuid.result}"
}

resource "aws_s3_bucket_versioning" "terraform-state-version" {
  bucket = aws_s3_bucket.terraform-states-s3-bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}
