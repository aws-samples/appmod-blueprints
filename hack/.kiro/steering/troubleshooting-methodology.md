# Troubleshooting Methodology

## Purpose

Provides a systematic approach for troubleshooting issues in the workshop environment, prioritizing investigation over immediate fixes.

## Instructions

### General Troubleshooting Approach

- ALWAYS verify the actual problem exists before starting troubleshooting (ID: TROUBLESHOOT_VERIFY_PROBLEM_EXISTS)
- ALWAYS start troubleshooting by searching EKS troubleshooting guide and EKS documentation with 3 to 4 different query variations using the EKS MCP tools `search_eks_troubleshooting_guide` and `search_eks_documentation` (ID: TROUBLESHOOT_SEARCH_FIRST)
- If initial investigation doesn't reach a clear conclusion, return to AWS documentation with refined queries based on findings (ID: TROUBLESHOOT_ITERATIVE_SEARCH)
- ALWAYS wait at least 150 seconds after new AWS Load Balancer shows as "active" before testing connectivity. Complete provisioning including DNS propagation can take up to 5 minutes (ID: TROUBLESHOOT_LB_WAIT)
- EXPLICITLY acknowledge tool usage and results by stating why the tool was chosen and summarizing key findings from the tool's output (ID: TROUBLESHOOT_ACKNOWLEDGE_TOOLS)
- When falling back from MCP tools to alternative methods, EXPLICITLY explain why the fallback is necessary and what alternative approach is being used (ID: TROUBLESHOOT_EXPLAIN_FALLBACK)

### Infrastructure Troubleshooting Priority

- Use `terraform state list` to identify resources, then `terraform state show <resource>` to inspect detailed configuration and current state before checking AWS CLI or console (ID: TROUBLESHOOT_TF_STATE_INSPECT)
- For networking issues (LoadBalancers, Ingress), examine terraform configuration files in the workshop repository (ID: TROUBLESHOOT_TF_NETWORKING)
- When resources are missing or misconfigured, update Terraform configuration and use deployment scripts rather than creating resources manually (ID: TROUBLESHOOT_TF_UPDATE)
- NEVER use `get_eks_vpc_config` MCP tool - always use Terraform state and configuration files for VPC information (ID: TROUBLESHOOT_NO_EKS_VPC_CONFIG)

### EKS-Specific Troubleshooting

- ALWAYS check EKS cluster configuration using `describe-cluster` to confirm AutoMode status before assuming missing controllers (ID: TROUBLESHOOT_EKS_AUTOMODE)
- After subnet tag changes (kubernetes.io/role/elb), ALWAYS recreate LoadBalancer services to trigger new AWS Load Balancer creation (ID: TROUBLESHOOT_LB_RECREATE_AFTER_SUBNET_CHANGES)

### MCP Server Troubleshooting

- If EKS MCP tools fail, provide equivalent kubectl or AWS CLI commands as fallback (ID: TROUBLESHOOT_EKS_MCP_FALLBACK)
- If Terraform MCP tools fail, use terraform state commands for inspection only - never apply/destroy directly (ID: TROUBLESHOOT_TF_MCP_FALLBACK)

### Terraform State Troubleshooting

- If plan shows unexpected destroy operations, STOP and investigate state drift or configuration changes (ID: TROUBLESHOOT_TF_UNEXPECTED_DESTROY)
- For state inconsistencies, compare `terraform state show` with actual AWS resources (ID: TROUBLESHOOT_TF_STATE_DRIFT)

## Priority

Critical

## Error Handling

- When troubleshooting reveals missing prerequisites, guide user through setup before proceeding
- If multiple issues are found, address them in order of dependency (infrastructure → platform → application)
- Always provide clear explanation of what was wrong and why the fix works
