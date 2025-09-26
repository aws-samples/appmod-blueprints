locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
  }

}

locals {
  region                    = data.aws_region.current.id
  hub_cluster               = [for k, v in var.clusters : v if v.environment == "control-plane"][0]
  hub_cluster_key           = [for k, v in var.clusters : k if v.environment == "control-plane"][0]
  cluster_vpc_ids           = { for k, v in var.clusters : v.name => data.aws_eks_cluster.clusters[k].vpc_config[0].vpc_id }
  gitlab_security_groups    = "${aws_security_group.gitlab_ssh.id},${aws_security_group.gitlab_http.id}"
  gitlab_domain_name        = aws_cloudfront_distribution.gitlab.domain_name
}
