# Module: IaC (Infrastructure as Code)

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect IaC tooling - Terraform, CloudFormation, CDK, eksctl, Pulumi

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [1. Terraform Detection](#1-terraform-detection)
  - [2. CloudFormation Detection](#2-cloudformation-detection)
  - [3. CDK Detection](#3-cdk-detection)
  - [4. eksctl Detection](#4-eksctl-detection)
  - [5. Pulumi Detection](#5-pulumi-detection)
  - [6. Tag-Based Detection (Fallback)](#6-tag-based-detection-fallback)
- [Output Schema](#output-schema)
- [Confidence Determination](#confidence-determination)
- [Edge Cases](#edge-cases)

---

## Prerequisites

- **Cluster name required:** No (workspace scan), Yes (for tag verification)
- **MCP tools used:** None (filesystem scan)
- **CLI fallback:** `find`, `grep`, `aws cloudformation`

---

## Detection Strategy

IaC detection is primarily workspace-based. Scan the local filesystem for IaC configuration files:

```
1. Terraform     -> .tf files with aws_eks_cluster or module "eks"
2. CloudFormation -> .yaml/.json with AWS::EKS::Cluster
3. CDK           -> cdk.json + package.json with aws-cdk
4. eksctl        -> yaml files with kind: ClusterConfig
5. Pulumi        -> Pulumi.yaml + aws provider
```

**Confidence scoring:**
- **High**: IaC files found with cluster name matching target
- **Medium**: IaC files found but cluster name doesn't match
- **Low**: Only cluster tags suggest IaC tool
- **Unknown**: No evidence found

---

## Detection Commands

### 1. Terraform Detection

Start with Terraform detection because it is the most common IaC tool for EKS clusters in production environments.

```bash
# Find Terraform files with EKS resources
find . -name "*.tf" -type f 2>/dev/null | head -50 | \
  xargs grep -l "aws_eks_cluster\|module.*eks" 2>/dev/null | head -10
```

**Example output:**
```
./infrastructure/eks/main.tf
./infrastructure/eks/cluster.tf
./modules/eks-cluster/main.tf
```

**If files found, extract details to determine which module or resource configuration is used:**
```bash
# Check for terraform-aws-modules/eks
grep -r "source.*terraform-aws-modules/eks" --include="*.tf" . 2>/dev/null | head -5

# Check for cluster name in tf files
grep -r "cluster_name\s*=" --include="*.tf" . 2>/dev/null | head -5

# Check for tfvars
find . -name "*.tfvars" -type f 2>/dev/null | head -5
```

**Example output:**
```
./infrastructure/eks/main.tf:  source  = "terraform-aws-modules/eks/aws"
./infrastructure/eks/main.tf:  cluster_name    = "my-production-cluster"
./infrastructure/eks/terraform.tfvars
```

**Terraform state check (optional) - Use this to verify if Terraform has been applied:**
```bash
# Check if state exists
find . -name "terraform.tfstate" -o -name ".terraform" -type d 2>/dev/null | head -3
```

### 2. CloudFormation Detection

Check for CloudFormation templates when Terraform is not found, or when the organization uses AWS-native tooling.

```bash
# Find CFN templates with EKS resources
find . \( -name "*.yaml" -o -name "*.yml" -o -name "*.json" \) -type f 2>/dev/null | head -50 | \
  xargs grep -l "AWS::EKS::Cluster\|AWSTemplateFormatVersion" 2>/dev/null | head -10
```

**Example output:**
```
./cloudformation/eks-cluster.yaml
./templates/infrastructure.yaml
```

**Check for deployed stacks (if cluster name known) - This confirms the stack was actually deployed:**
```bash
# List stacks with EKS resources
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?contains(StackName, `eks`) || contains(StackName, `EKS`)].StackName'
```

**Example output:**
```json
[
    "eks-production-cluster",
    "eks-nodegroup-stack"
]
```

### 3. CDK Detection

Check for AWS CDK projects when the codebase uses TypeScript, Python, or other CDK-supported languages. CDK is common in organizations with strong development practices.

```bash
# Check for CDK project - cdk.json is the definitive marker
find . -name "cdk.json" -type f 2>/dev/null | head -3

# Check for CDK in package.json (TypeScript/JavaScript)
find . -name "package.json" -type f 2>/dev/null | head -10 | \
  xargs grep -l "aws-cdk\|@aws-cdk" 2>/dev/null | head -5

# Check for CDK in requirements.txt (Python)
find . -name "requirements.txt" -type f 2>/dev/null | head -5 | \
  xargs grep -l "aws-cdk" 2>/dev/null | head -3

# Check for cdk.out (synthesized templates) - indicates CDK has been synthesized
find . -name "cdk.out" -type d 2>/dev/null | head -3
```

**Example output:**
```
./infra/cdk.json
./infra/package.json
./infra/cdk.out
```

### 4. eksctl Detection

Check for eksctl when the cluster was created for development, testing, or quick deployments. eksctl is commonly used for simpler cluster setups.

```bash
# Find eksctl cluster configs
find . \( -name "eksctl*.yaml" -o -name "eksctl*.yml" -o -name "cluster*.yaml" -o -name "cluster*.yml" \) \
  -type f 2>/dev/null | head -10 | \
  xargs grep -l "kind:\s*ClusterConfig\|apiVersion:\s*eksctl.io" 2>/dev/null | head -5
```

**Example output:**
```
./eksctl-config.yaml
./clusters/dev-cluster.yaml
```

**Verify with eksctl CLI (if available) - Confirms eksctl can manage this cluster:**
```bash
# Check if eksctl recognizes the cluster
eksctl get cluster --name <cluster-name> --region <region> 2>/dev/null
```

**Example output:**
```
NAME                REGION          EKSCTL CREATED
my-dev-cluster      us-west-2       True
```

### 5. Pulumi Detection

Check for Pulumi when the organization uses infrastructure-as-real-code with TypeScript, Python, or Go. Pulumi is less common than Terraform but growing in adoption.

```bash
# Find Pulumi project files - Pulumi.yaml is the definitive marker
find . -name "Pulumi.yaml" -type f 2>/dev/null | head -3

# Check for AWS provider in Pulumi
find . -name "Pulumi.*.yaml" -type f 2>/dev/null | head -5 | \
  xargs grep -l "aws:" 2>/dev/null | head -3

# Check for EKS in Pulumi code
find . \( -name "*.ts" -o -name "*.py" -o -name "*.go" \) -type f 2>/dev/null | head -50 | \
  xargs grep -l "eks.Cluster\|pulumi_eks\|@pulumi/eks" 2>/dev/null | head -5
```

**Example output:**
```
./pulumi/Pulumi.yaml
./pulumi/Pulumi.production.yaml
./pulumi/index.ts
```

### 6. Tag-Based Detection (Fallback)

Use tag-based detection when workspace scan finds nothing. IaC tools often add identifying tags to the resources they create.

**MCP:**
```
describe_eks_resource(
  resource_type="cluster",
  cluster_name="<cluster-name>"
)
-> Check response for cluster.tags
```

**CLI:**
```bash
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.tags' --output json
```

**Example output (Terraform-managed cluster):**
```json
{
    "Environment": "production",
    "terraform": "true",
    "managed-by": "terraform"
}
```

**Example output (CloudFormation-managed cluster):**
```json
{
    "aws:cloudformation:stack-name": "eks-production-cluster",
    "aws:cloudformation:stack-id": "arn:aws:cloudformation:us-west-2:123456789012:stack/eks-production-cluster/abc123",
    "aws:cloudformation:logical-id": "EKSCluster"
}
```

**Common IaC tags:**
- Terraform: `terraform`, `tf-*`, `managed-by: terraform`
- CloudFormation: `aws:cloudformation:stack-name`
- CDK: `aws:cdk:*`
- Pulumi: `pulumi:*`

---

## Output Schema

```yaml
iac:
  tool: string        # Terraform | CloudFormation | CDK | eksctl | Pulumi | CLI | unknown
  confidence: string  # high | medium | low
  evidence: string    # Path to files or reason for determination
  
  details:
    # Terraform-specific
    terraform:
      detected: bool
      files: list           # Paths to .tf files
      module: string        # e.g., "terraform-aws-modules/eks/aws"
      state_backend: string # local | s3 | remote
      
    # CloudFormation-specific
    cloudformation:
      detected: bool
      templates: list       # Paths to CFN templates
      stack_name: string    # Deployed stack name (if found)
      
    # CDK-specific
    cdk:
      detected: bool
      language: string      # typescript | python | java | go
      cdk_json_path: string
      
    # eksctl-specific
    eksctl:
      detected: bool
      config_files: list
      
    # Pulumi-specific
    pulumi:
      detected: bool
      project_path: string
      language: string
```

---

## Confidence Determination

| Scenario | Confidence | Reasoning |
|----------|------------|-----------|
| IaC files found with matching cluster name | High | Direct evidence |
| IaC files found, cluster name in tfvars/config | High | Indirect but strong |
| IaC files found, no cluster name match | Medium | Files exist but may be different cluster |
| Only cluster tags suggest IaC | Low | Tags can be manually added |
| No evidence found | Unknown | Might be CLI-created or IaC elsewhere |

---

## Edge Cases

### Multiple IaC Tools Detected

If multiple tools are found (e.g., Terraform + CDK):
- Report primary tool as most likely (based on EKS-specific files)
- Note secondary tools in details
- Ask user to clarify if ambiguous

### IaC in Different Directory

User may have IaC in a separate repo or directory:
- Note that scan is workspace-limited
- Suggest user point to IaC directory if known

### GitOps-Managed IaC

IaC may be applied via GitOps (ArgoCD/Flux deploying Crossplane or ACK):
- Check for Crossplane XRDs/compositions
- Check for ACK resources
- Note as "GitOps + IaC"

### No IaC (CLI-Created)

If no IaC evidence found:
- Cluster may have been created via `aws eks create-cluster` or console
- Note as "CLI or Console (no IaC detected)"
- Warn that upgrades will need manual CLI commands
