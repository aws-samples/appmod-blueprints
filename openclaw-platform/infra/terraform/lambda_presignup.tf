# Pre-signup Lambda: reject signups whose email is not @amazon.com.
# Triggered by Cognito before the user record is created.

data "archive_file" "presignup_zip" {
  type        = "zip"
  output_path = "${path.module}/.presignup.zip"
  source {
    filename = "index.py"
    content  = <<-PY
      import re

      ALLOWED_DOMAIN = "amazon.com"

      def handler(event, context):
          attrs = event.get("request", {}).get("userAttributes", {}) or {}
          email = (attrs.get("email") or "").strip().lower()
          if not email or "@" not in email:
              raise Exception("Email is required for signup.")
          domain = email.rsplit("@", 1)[-1]
          if domain != ALLOWED_DOMAIN:
              raise Exception(
                  "Signup is restricted to @amazon.com email addresses. "
                  f"Your email domain ({domain}) is not allowed."
              )
          # Amazon emails are pre-verified — skip the confirmation email loop.
          event["response"]["autoConfirmUser"] = True
          event["response"]["autoVerifyEmail"] = True
          return event
    PY
  }
}

resource "aws_iam_role" "presignup" {
  name = "${local.cluster_name}-presignup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "presignup_logs" {
  role       = aws_iam_role.presignup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "presignup" {
  function_name    = "${local.cluster_name}-presignup"
  role             = aws_iam_role.presignup.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.presignup_zip.output_path
  source_code_hash = data.archive_file.presignup_zip.output_base64sha256
  timeout          = 5
  memory_size      = 128

  tags = local.tags
}

resource "aws_lambda_permission" "presignup_cognito" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presignup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.finance.arn
}
