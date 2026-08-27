# Terraform Cluster Provider

Direct Terraform provisioning of the hub cluster — no Kind bootstrap cluster, no Crossplane.

## What It Creates

| Resource | Details |
|----------|---------|
| VPC | 2 public + 2 private subnets (/19), IGW, single NAT GW |
| EKS | Auto Mode cluster (general-purpose + system node pools) |
| IAM | Cluster role, node role, ArgoCD capability role, ESO pod identity role |
| ArgoCD | EKS ArgoCD Capability (via AWS CLI) |
| Secrets Manager | `<cluster>/config` + `<cluster>/keycloak` |
| ESO | External Secrets Operator via Helm |
| ClusterSecretStore | `aws-secrets-manager` |
| Seed secret | Minimal cluster secret in `argocd` namespace |
| Root appset | `bootstrap/root-appset.yaml` applied |

## Prerequisites

- Terraform >= 1.5
- AWS CLI configured with sufficient permissions
- `kubectl`, `helm` (for provider auth)

## Usage

1. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in values from `config.local.yaml`:

```hcl
cluster_name       = "my-hub"
aws_region         = "us-west-2"
aws_account_id     = "123456789012"
repo_url           = "https://github.com/org/repo.git"
repo_revision      = "main"
repo_basepath      = "gitops/"
domain             = "idp.example.com"
idc_instance_arn   = "arn:aws:sso:::instance/ssoins-..."
idc_region         = "us-east-1"
idc_admin_group_id = "abc-123"
```

2. Run via Taskfile:

```bash
task terraform:install
task terraform:status
task terraform:destroy
```

Or directly:

```bash
cd cluster-providers/terraform
terraform init
terraform apply -var-file=../../terraform.tfvars
```

## Contract Compliance

This provider satisfies the same contract as `kind-crossplane` — see `cluster-providers/README.md`.
After `root-appset.yaml` is applied, ArgoCD takes over and the system is self-managing.
