# Cognito hosted-UI theme for finance-assistant.
#
# Uploads the CSS from terraform/cognito_ui/finance-ui.css and, if present,
# the rasterized logo.png. Run terraform/cognito_ui/render-logo.sh to
# produce logo.png from logo.svg before the first apply.
#
# Changes are live on the hosted UI immediately after apply — no UI redeploy.

locals {
  cognito_ui_dir = "${path.module}/cognito_ui"
  cognito_ui_css = file("${local.cognito_ui_dir}/finance-ui.css")
  # fileexists() lets us keep the apply working before anyone runs
  # render-logo.sh; the theme still looks good with just CSS.
  cognito_ui_logo_path    = "${local.cognito_ui_dir}/logo.png"
  cognito_ui_logo_present = fileexists(local.cognito_ui_logo_path)
  cognito_ui_logo_b64     = local.cognito_ui_logo_present ? filebase64(local.cognito_ui_logo_path) : null
}

resource "aws_cognito_user_pool_ui_customization" "finance" {
  user_pool_id = aws_cognito_user_pool.finance.id
  client_id    = aws_cognito_user_pool_client.finance.id

  css        = local.cognito_ui_css
  image_file = local.cognito_ui_logo_b64

  # A domain must exist before a UI customization can attach — Cognito
  # rejects the call otherwise. Terraform figures ordering from the
  # reference, but making it explicit avoids a first-apply race.
  depends_on = [aws_cognito_user_pool_domain.finance]
}

output "finance_cognito_hosted_ui_url" {
  description = "Branded hosted sign-in URL (share with users)"
  value = format(
    "https://%s.auth.%s.amazoncognito.com/login?client_id=%s&response_type=code&scope=%s&redirect_uri=%s",
    aws_cognito_user_pool_domain.finance.domain,
    var.region,
    aws_cognito_user_pool_client.finance.id,
    "openid+email+profile",
    urlencode("https://${var.finance_ui_host}/oauth2/idpresponse"),
  )
}
