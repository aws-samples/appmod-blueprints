# Workshop IDE Environment

## Context

This is the Kiro agent running on the workshop IDE instance (Code Editor on EC2). The user is a workshop participant or the workshop developer debugging/testing the platform.

## Environment

- User: `ec2-user`
- Workshop repo: `/home/ec2-user/environment/platform-on-eks-workshop`
- Clusters: `peeks-hub`, `peeks-spoke-dev`, `peeks-spoke-prod` (context aliases: `hub`, `dev`, `prod`)
- EKS Auto Mode — no Karpenter pods in clusters
- EKS Capabilities — ArgoCD, Kro, ACK run as managed services, not in-cluster

## Repository Layout

| Path | Purpose |
|------|---------|
| `platform/infra/terraform/cluster/` | EKS cluster Terraform (hub + spokes) |
| `platform/infra/terraform/common/` | Platform addons Terraform |
| `platform/infra/terraform/hub-config.yaml` | Cluster addon enablement (single source of truth) |
| `platform/infra/terraform/scripts/` | Init, ArgoCD utils, IDC config |
| `gitops/addons/` | ArgoCD addon definitions, charts, environments |
| `gitops/apps/` | Application deployment manifests |
| `applications/` | Sample apps (Rust, Java, Go, .NET, Next.js) |
| `backstage/` | Backstage IDP |

## Key Rules

- **Use deploy.sh/destroy.sh** — never raw `terraform apply` or `terraform destroy`
- **GitOps first** — modify Git files and let ArgoCD sync, don't `kubectl apply` manually
- **Dynamic values only in addons.yaml** — never put template expressions in values.yaml
- **Check env vars with echo** — `echo $AWS_REGION` etc., don't dump full environment
- **ArgoCD token refresh** — if `argocd` CLI auth fails, run `argocd-refresh-token` then `source ~/.bashrc.d/platform.sh`

## Credentials

Workshop passwords are in `~/.bashrc.d/platform.sh` (temporary, workshop-scoped — not sensitive beyond the session).

| Service | Username | Password |
|---------|----------|----------|
| Backstage | `user1` | `$USER1_PASSWORD` |
| GitLab | `user1` | `$USER1_PASSWORD` |
| ArgoCD | `admin` | `$IDE_PASSWORD` |
| Grafana | `user1` | `$USER1_PASSWORD` |
