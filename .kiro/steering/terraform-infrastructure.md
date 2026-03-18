---
inclusion: fileMatch
fileMatchPattern: "**/terraform/**/*"
---

# Terraform Infrastructure Guidelines

## Infrastructure Location

All Terraform code is located in: `platform/infra/terraform/`

## Project Structure

```
platform/infra/terraform/
├── modules/              # Reusable Terraform modules
├── environments/         # Environment-specific configurations
├── scripts/             # Helper scripts
└── main.tf              # Root module
```

## EKS Cluster Configuration

### Cluster Design Principles
1. **Multi-AZ Deployment**: Spread across 3 availability zones
2. **Managed Node Groups**: Use EKS managed node groups
3. **IRSA**: IAM Roles for Service Accounts for pod-level permissions
4. **VPC CNI**: Use AWS VPC CNI for networking
5. **Add-ons**: Deploy essential add-ons (CoreDNS, kube-proxy, VPC CNI)

### Node Group Strategy
- **System Node Group**: For platform components (ArgoCD, Backstage)
- **Application Node Group**: For application workloads
- **GPU Node Group**: For ML/AI workloads (optional)
- Use taints and tolerations for workload isolation

## Module Development

### Module Structure
```
modules/<module-name>/
├── main.tf              # Main resources
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── versions.tf          # Provider versions
└── README.md            # Documentation
```

### Variable Naming Conventions
- Use snake_case for variable names
- Prefix with resource type when applicable
- Use descriptive names: `eks_cluster_name` not `name`
- Group related variables together

### Output Best Practices
- Export values needed by other modules or external tools
- Include descriptions for all outputs
- Export ARNs, IDs, and endpoints
- Use consistent naming across modules

## State Management

### Remote State
- Store state in S3 with DynamoDB locking
- Use separate state files per environment
- Enable versioning on S3 bucket
- Encrypt state at rest

### State Configuration Example
```hcl
terraform {
  backend "s3" {
    bucket         = "platform-terraform-state"
    key            = "eks/terraform.tfstate"
    region         = "us-west-2"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
```

## AWS Resource Tagging

### Required Tags
All resources must include:
- `Environment`: dev, staging, prod
- `ManagedBy`: terraform
- `Project`: platform-engineering
- `Owner`: team name

## Security Best Practices

### IAM Policies
- Use least privilege principle
- Create specific policies per service
- Use IAM roles, not users
- Implement IRSA for pod-level permissions
- Document policy purposes

### Network Security
- Use private subnets for EKS nodes
- Implement security groups with minimal rules
- Enable VPC flow logs
- Use AWS PrivateLink where possible
- Restrict API server access

### Secrets Management
- Never commit secrets to Git
- Use AWS Secrets Manager or Parameter Store
- Reference secrets via data sources
- Rotate secrets regularly
- Use External Secrets Operator in Kubernetes

## Common Patterns

### EKS Cluster with Add-ons
```hcl
module "eks" {
  source = "terraform-aws-modules/eks/aws"
  
  cluster_name    = var.cluster_name
  cluster_version = "1.28"
  
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets
  
  enable_irsa = true
  
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
  }
}
```

### IRSA Configuration
```hcl
module "irsa_role" {
  source = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  
  role_name = "${var.cluster_name}-service-role"
  
  oidc_providers = {
    main = {
      provider_arn = module.eks.oidc_provider_arn
      namespace_service_accounts = ["default:my-service"]
    }
  }
  
  role_policy_arns = {
    policy = aws_iam_policy.service_policy.arn
  }
}
```

## Testing Infrastructure

### Validation Commands
```bash
# Format check
terraform fmt -check -recursive

# Validate configuration
terraform validate

# Plan with detailed output
terraform plan -out=tfplan

# Security scanning
tfsec .
checkov -d .
```

## Troubleshooting

### Common Issues
- **State Lock**: Check DynamoDB for stuck locks
- **Provider Version**: Ensure compatible provider versions
- **Resource Limits**: Check AWS service quotas
- **Permissions**: Verify IAM permissions for Terraform execution
