locals {

  context_prefix = var.resource_prefix

  tags = {
    Blueprint  = local.context_prefix
    GithubRepo = "github.com/aws-samples/appmod-blueprints"
  }

}

locals {
  azs                       = slice(data.aws_availability_zones.available.names, 0, 2)
  hub_cluster_key           = [for k, v in var.clusters : k if v.environment == "control-plane"][0]
  hub_cluster               = [for k, v in var.clusters : v if v.environment == "control-plane"][0]
  spoke_clusters            = { for k, v in var.clusters : k => v if v.environment != "control-plane" }
  vpc_cidr                  = "10.0.0.0/16"
}
