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

### Workshop Context

- Infrastructure is pre-deployed and managed via Terraform - focus on understanding and extending rather than creating from scratch (ID: TF_PREDEPLOYED)
- Terraform files are located in `/home/ec2-user/environment/platform-on-eks-workshop/platform/infra/terraform` directory with organized structure: vpc.tf, eks.tf, alb.tf, csi.tf (ID: TF_WORKSHOP_STRUCTURE)
- Use `terraform show` and `terraform state show` to explore existing resources without modifications (ID: TF_EXPLORE)
- When running Terraform commands, ALWAYS pass variables: `terraform apply -var="cluster_name=$CLUSTER_NAME" -auto-approve` (ID: TF_PASS_VARS)
- Never use terraform apply, or terraform destroy, always use the associated shell scripts `deploy.sh` or `destroy.sh`

## Priority

Critical
