# DynamoDB table with the lock id for tf state file
resource "aws_dynamodb_table" "terraform-lock" {
    name            = "${var.tfe_project}-tf-lock"
    hash_key        = "LockID"
    billing_mode    = "PAY_PER_REQUEST"
    attribute {
        name = "LockID"
        type = "S"
    }
}
