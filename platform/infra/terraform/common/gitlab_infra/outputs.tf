output "gitlab_domain_name" {
   value = aws_cloudfront_distribution.gitlab.domain_name
   description = "Gitlab domain name"
}

output "gitlab_security_groups" {
  description = "Gitlab security groups"
  value = local.gitlab_security_groups
}