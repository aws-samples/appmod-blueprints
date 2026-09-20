---
name: troubleshoot-kro
description: Troubleshoot Kro ResourceGraphDefinition (RGD) issues — stuck instances, ACK resource failures, IAM trust policy problems, resource conflicts. Use when a Kro instance is stuck IN_PROGRESS, ACK resources fail to sync, or RGD dependency chains are broken. Do NOT use for general platform troubleshooting — use troubleshoot-platform instead.
---

# Troubleshoot KRO

## Overview

Systematic troubleshooting for Kro ResourceGraphDefinitions that create ACK-managed AWS resources. Focuses on dependency chains, IAM authentication, and resource conflict resolution.

## Parameters

- **rgd_name** (required): ResourceGraphDefinition name (e.g., `cicdpipeline.kro.run`)
- **instance_name** (required): Instance name (e.g., `rust-cicd-pipeline`)
- **namespace** (required): Kubernetes namespace

## Workflow

### 1. Check Instance Status

Identify which resource in the dependency chain is blocking.

```bash
kubectl get <kind> <name> -n <namespace> -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
```

**Constraints:**
- You MUST check the topological order first to understand creation sequence: `kubectl get resourcegraphdefinition <name> -o jsonpath='{.status.topologicalOrder}'`
- You MUST check resources in topological order because if an early resource fails, all dependents are blocked

### 2. Identify ACK Resources

```bash
kubectl get resourcegraphdefinition <name> -o yaml | grep -E "apiVersion: (ecr|iam|eks|s3|dynamodb).services.k8s.aws"
```

Check each ACK resource status:
```bash
kubectl describe <ack-resource-type> <name> -n <namespace> | tail -30
```

### 3. Diagnose Common Failures

**ACK resource status conditions:**

| Condition | Meaning |
|-----------|---------|
| `ACK.IAMRoleSelected` | IAMRoleSelector found and role selected |
| `ACK.ResourceSynced` | Successfully synced with AWS |
| `Ready` | Resource ready for use |
| `ACK.Terminal` | Unrecoverable error (usually resource already exists) |
| `ACK.Recoverable` | Temporary error (usually IAM permission issue) |

**Common errors:**

| Error | Cause | Fix |
|-------|-------|-----|
| `AccessDenied: sts:TagSession` | Trust policy missing EKS Capability role | Update Terraform workload role trust policy |
| `EntityAlreadyExists` | Resource from previous deployment | Delete AWS resource, then K8s resource |
| `Resource not managed by ACK` | Resource exists but wasn't created by ACK | Delete AWS resource or adopt it |

### 4. Fix IAM Trust Policy Issues

ACK controllers running as EKS Capabilities use `<prefix>-<cluster-name>-ack-capability-role`.

```bash
# Check trust policy
aws iam get-role --role-name <workload-role> --query 'Role.AssumeRolePolicyDocument'
```

**Constraints:**
- You MUST verify the capability role is in the Principal.AWS list
- You MUST update trust policies through Terraform, not manual AWS CLI because manual changes drift

### 5. Clean Up Conflicting Resources

When ACK reports "Resource already exists":

```bash
# 1. Find the AWS resource
aws ecr describe-repositories --repository-names <name>
aws iam get-policy --policy-arn <arn>

# 2. Delete from AWS first
aws ecr delete-repository --repository-name <name> --force
aws iam delete-policy --policy-arn <arn>

# 3. Delete K8s resource to force recreation
kubectl delete <ack-resource-type> <name> -n <namespace>
```

**Constraints:**
- You MUST NOT delete AWS or Kubernetes resources without explicit user confirmation because these may be production resources
- You MUST delete the AWS resource before the K8s resource because ACK will try to recreate it immediately

### 6. Force Reconciliation

```bash
kubectl annotate <kind> <name> -n <namespace> kro.run/reconcile="$(date +%s)" --overwrite
```

Kro will re-evaluate the entire resource graph and create missing resources.

**Constraints:**
- You SHOULD wait at least 60 seconds after cleanup before forcing reconciliation because ACK needs time to process deletions
