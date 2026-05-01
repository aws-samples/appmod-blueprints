# Cognito user pool — fronts the finance-assistant UI via ALB auth.
# Self-signup is allowed but the PreSignUp Lambda rejects any email
# whose domain isn't exactly @amazon.com.

resource "aws_cognito_user_pool" "finance" {
  name = "${var.project_name}-finance-users"

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  lambda_config {
    pre_sign_up = aws_lambda_function.presignup.arn
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  auto_verified_attributes = ["email"]

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 3
      max_length = 256
    }
  }

  tags = local.tags
}

resource "aws_cognito_user_pool_client" "finance" {
  name         = "${var.project_name}-finance-alb"
  user_pool_id = aws_cognito_user_pool.finance.id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://${var.finance_ui_host}/oauth2/idpresponse"]
  logout_urls                          = ["https://${var.finance_ui_host}/"]

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]
}

resource "aws_cognito_user_pool_domain" "finance" {
  domain       = "${var.project_name}-finance-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.finance.id
}
