# Terraform Infrastructure Management

## Purpose

Ensures all Terraform operations follow Infrastructure as Code best practices and properly integrate with the workshop's pre-deployed infrastructure managed through Terraform MCP server.

## Instructions

### Terraform MCP Server Usage

- ALWAYS review the variables.tf before running plan or apply (ID: TF_VARIABLES)
- ALWAYS prefer Terraform MCP server tools over direct terraform CLI commands when available (ID: TF_PREFER_MCP)
- For Terraform operations (plan, apply, destroy), use `ExecuteTerraformCommand` MCP tool instead of direct terraform CLI (ID: TF_USE_TERRAFORM_CMD)
- For the tool ExecuteTerraformCommand only use the variable cluster_name (ID: TF_USE_EXECUTETERRAFORMCOMMAND_MCP)
- For AWS provider documentation, use `SearchAwsProviderDocs` or `SearchAwsccProviderDocs` MCP tools for reference (ID: TF_SEARCH_DOCS)
- For module discovery, use `SearchSpecificAwsIaModules` for AWS modules or `SearchUserProvidedModule` for custom modules (ID: TF_SEARCH_MODULES)

### State Management and Safety

- Use terraform CLI for `terraform state list`, `terraform state show`, and `terraform show` (ID: TF_STATE_CLI_ONLY)
- NEVER run `terraform destroy` without explicit user confirmation and explanation of what will be destroyed (ID: TF_DESTROY_CONFIRM)
- ALWAYS create a backup before state manipulation: `terraform state pull > backup.tfstate` (ID: TF_STATE_BACKUP)

### Cluster Provider Context

- Terraform is now **one of several pluggable cluster providers** (`kind-crossplane`, `kind-kro-ack`, `terraform`, `byoc`), selected via `clusterProvider` in `config.local.yaml` — it is no longer the default nor the only deployment path (ID: TF_PROVIDER_MODEL)
- The Terraform provider lives in `cluster-providers/terraform/` (flat `.tf` files: `eks.tf`, `vpc.tf`, `iam.tf`, `argocd-capability.tf`, `secrets-manager.tf`, etc.) — the old `platform/infra/terraform/` tree has been removed (ID: TF_PROVIDER_STRUCTURE)
- Use `terraform show` and `terraform state show` to explore existing resources without modifications (ID: TF_EXPLORE)
- NEVER run `terraform apply`/`terraform destroy` directly — always drive the provider through the Taskfile: `task install` / `task destroy` (which delegate to `terraform:install` / `terraform:destroy` when `clusterProvider: terraform`) (ID: TF_USE_TASKFILE)

## Priority

Critical
