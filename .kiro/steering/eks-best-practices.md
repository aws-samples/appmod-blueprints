# EKS Operations

## Purpose

Ensures all EKS and Kubernetes operations leverage the EKS MCP server capabilities appropriately.

## Instructions

### EKS MCP Server Usage

- For ALL Kubernetes resource operations (pods, services, deployments, configmaps), use `manage_k8s_resource` for CRUD operations and `list_k8s_resources` for listing/filtering resources, DO NOT USE kubectl unless absolutely necssary (ID: EKS_USE_MCP_TOOLS)
- We are using EKS Auto mode, that mean that Karpenter is not running in the EKS clusters (ID: EKS_AUTO)
- We are using EKS capabilities for Argocd, kro and ACK, that mean that thoses controlleurs are not running inside the EKS clusters (ID: EKS_CAPABILITIES)
- When troubleshooting, ALWAYS use `get_k8s_events` and `get_pod_logs` MCP tools before attempting manual debugging (ID: EKS_MCP_TROUBLESHOOT)
- For CloudWatch metrics and logs, prefer `get_cloudwatch_logs` and `get_cloudwatch_metrics` MCP tools over AWS CLI commands (ID: EKS_MCP_MONITORING)
- When applying YAML manifests, use the `apply_yaml` MCP tool to benefit from validation and error handling (ID: EKS_MCP_APPLY)

### ArgoCD CLI Authentication

- If the `argocd` CLI returns authentication errors or token expired messages, run the `argocd-refresh-token` bash function to obtain a new 12-hour token (ID: EKS_ARGOCD_REFRESH_TOKEN)
- `argocd-refresh-token` updates `~/.bashrc.d/platform.sh` with the new token. After running it, source the file to pick up the change: `source ~/.bashrc.d/platform.sh` (ID: EKS_ARGOCD_SOURCE_TOKEN)
- The token is valid for 12 hours — no need to refresh again within that window (ID: EKS_ARGOCD_TOKEN_TTL)

### Security Best Practices

- Follow least-privilege principles for IAM roles (ID: EKS_IAM_LEAST_PRIVILEGE)
- Validate security implications of AI-generated resources before applying (ID: EKS_VALIDATE_AI_SECURITY)
- Use proper RBAC configurations for Kubernetes access control (ID: EKS_RBAC_CONFIG)
- Implement network policies and security contexts for pod security (ID: EKS_POD_SECURITY)

## Priority

Critical
