# AWS Environment Variables

## Purpose

Enforces environment variable usage for all AWS operations to prevent hardcoded values and ensure secure, portable configurations.

## Instructions

### Core Environment Variable Validation

- BEFORE executing ANY AWS-related command or MCP tool, you MUST FIRST use shell to retrieve environment variable values: `echo "Region: $AWS_REGION, Account: $AWS_ACCOUNT_ID"` (ID: AWS_ENV_VALIDATE)
- When working with EKS clusters, you MUST FIRST confirm the cluster name to work with, they should be already configured in kubectl, by default it is peeks-hub, peeks-spoke-dev, and peeks-spoke-prod, before passing it to ANY MCP tool or kubectl command. NEVER assume or hardcode cluster names (ID: AWS_ENV_VALIDATE_EKS)
- The shell tool MUST be the FIRST tool called in any workflow involving AWS resources or EKS clusters to retrieve actual environment variable values (ID: AWS_ENV_BASH_FIRST)
- NEVER proceed with AWS operations if environment variables return empty values (ID: AWS_ENV_REQUIRED)
- NEVER use placeholder values like "eks-cluster" or "$CLUSTER_NAME" directly in MCP tools - always use the actual value retrieved from shell (ID: AWS_ENV_NO_PLACEHOLDERS)

### Hardcoded Value Prevention

- NEVER use hardcoded AWS regions (e.g., `us-east-1`, `eu-west-1`) in any command, script, or configuration file (ID: AWS_ENV_NO_HARDCODE_REGION)
- NEVER use hardcoded AWS account IDs (e.g., `123456789012`) in any context (ID: AWS_ENV_NO_HARDCODE_ACCOUNT)
- NEVER use hardcoded resource names that should be environment-specific (ID: AWS_ENV_NO_HARDCODE_RESOURCES)
- ALWAYS use environment variable values: `$AWS_REGION`, `$AWS_ACCOUNT_ID`, `$CLUSTER_NAME` (ID: AWS_ENV_USE_VARIABLES)

### Configuration File Management

- When generating YAML, JSON, or other configuration files, ALWAYS use environment variable substitution or templating (ID: AWS_ENV_CONFIG_TEMPLATES)
- For Infrastructure as Code (Terraform, CloudFormation), use variable declarations instead of hardcoded values (ID: AWS_ENV_IAC_VARIABLES)
- When using Terraform specifically, use deployment scripts instead of direct terraform commands (ID: AWS_ENV_TF_SCRIPTS)
- NEVER commit files containing actual AWS account IDs, access keys, or other sensitive data (ID: AWS_ENV_NO_COMMIT_SENSITIVE)

## Priority

Critical
