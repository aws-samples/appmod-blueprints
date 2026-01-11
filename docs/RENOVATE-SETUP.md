# Renovate Setup for Helm Chart Version Management

This repository is configured with Renovate to automatically monitor and update Helm chart versions in ArgoCD Application files and values.yaml files.

## Configuration

The Renovate configuration is defined in `renovate.json` and includes:

- **Base Branch**: All PRs will be created against the `riv25` branch
- **Schedule**: Runs every Monday at 6:00 AM UTC
- **Monitoring**: Tracks Helm charts in ArgoCD Application files and values.yaml files
- **Grouping**: Groups all Helm chart updates into a single PR per run

## Supported Chart Sources

- Bitnami charts (registry-1.docker.io/bitnamicharts)
- Standard Helm repositories (https://*.github.io/*)
- OCI registries (ghcr.io, public.ecr.aws)
- AWS EKS charts
- ArgoCD charts
- Prometheus community charts
- Grafana charts
- Cert-manager charts
- External Secrets charts
- Crossplane charts
- Backstage charts

## Setup Requirements

1. **GitHub Token**: Create a GitHub personal access token with repo permissions
2. **Repository Secret**: Add the token as `RENOVATE_TOKEN` in repository secrets
3. **Branch**: Ensure the `riv25` branch exists in your repository

## File Patterns Monitored

- `applications/**/*.yaml` - ArgoCD Application files
- `gitops/**/*.yaml` - GitOps configuration files  
- `**/values.yaml` - Helm values files

## Auto-merge

Patch updates for stable charts (redis, postgresql, mysql, etc.) are configured for auto-merge to reduce manual overhead.

## Manual Trigger

The workflow can be manually triggered from the GitHub Actions tab with optional debug logging.