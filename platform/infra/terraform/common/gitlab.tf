################################################################################
# GitLab Token and Project Creation
################################################################################
# Get user ID for the username
data "gitlab_user" "workshop" {
  username = local.git_username
}
resource "gitlab_personal_access_token" "workshop" {
  user_id    = data.gitlab_user.workshop.id
  name       = "Workshop Personal access token for ${var.git_username} - 2026"
  expires_at = "2026-12-31"

  scopes = ["api", "read_api","read_repository", "write_repository"]
  
  lifecycle {
    replace_triggered_by = [
      # Force recreation when expiration date changes
      self.expires_at
    ]
  }
}

locals {
  gitlab_token   = gitlab_personal_access_token.workshop.token
}

# resource "gitlab_project" "workshop" {
#   name        = "platform-on-eks-workshop"
#   description = "Platform on EKS Workshop Project"
#   visibility_level = "public"
#   permanently_delete_on_destroy = true
#   namespace_id = data.gitlab_user.workshop.namespace_id
# }
