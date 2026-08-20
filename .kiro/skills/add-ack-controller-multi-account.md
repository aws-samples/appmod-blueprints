---
name: add-ack-controller-multi-account
description: Guide for adding a new ACK controller service for multi-account cross-account resource management. Use when onboarding a new AWS service (e.g., secretsmanager, rds, lambda) to the ACK multi-account pattern.
---

# Adding an ACK Controller for Multi-Account

This skill explains how to configure a new ACK service controller for cross-account resource management in spoke clusters.

## Overview

The platform uses ACK (AWS Controllers for Kubernetes) on the hub cluster to manage AWS resources in spoke accounts. Each ACK service (ec2, eks, iam, ecr, s3, dynamodb, secretsmanager) needs:

1. An **IAMRoleSelector** on the hub — routes ACK requests for a namespace to the correct cross-account role
2. A **cluster-mgmt role** in each spoke account — assumed by the hub ACK capability role
3. The hub ACK capability role's **AssumeWorkloadRoles** policy must cover the spoke account

## Files to Modify

| File | Change |
|------|--------|
| `gitops/addons/charts/multi-acct/templates/iam-role-selectors.yaml` | Add IAMRoleSelector for the new service |
| `scripts/create-cross-account-roles.sh` | Add service to the roles loop + policies |

## Step 1: Add IAMRoleSelector

In `gitops/addons/charts/multi-acct/templates/iam-role-selectors.yaml`, add a new block following the existing pattern:

```yaml
---
apiVersion: services.k8s.aws/v1alpha1
kind: IAMRoleSelector
metadata:
  name: <service>-{{ $key }}
spec:
  arn: "arn:aws:iam::{{ $value }}:role/{{ $.Values.global.resourcePrefix | default "peeks" }}-cluster-mgmt-<service>"
  namespaceSelector:
    names:
      - {{ $key }}
  resourceTypeSelector:
    - group: <service>.services.k8s.aws
      kind: ""
      version: ""
```

Replace `<service>` with the ACK service name (e.g., `secretsmanager`, `rds`, `lambda`).

The `resourceTypeSelector.group` must match the ACK CRD API group (check with `kubectl get crd | grep <service>`).

## Step 2: Update Cross-Account Roles Script

In `scripts/create-cross-account-roles.sh`:

1. Add the service to the loop:
```bash
for service in ec2 eks iam ecr s3 dynamodb secretsmanager <new-service>; do
```

2. Add managed policy:
```bash
MANAGED_POLICIES[<service>]="arn:aws:iam::aws:policy/<ManagedPolicyName>"
```

3. Add inline policy:
```bash
INLINE_POLICIES[<service>]='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["<service>:*"],"Resource":"*"}]}'
```

## Step 3: Create the Role in Spoke Accounts

Run the script from the hub account for each target spoke account:

```bash
export TARGET_ACCOUNT_ID=<spoke-account-id>
export RESOURCE_PREFIX=peeks
export HUB_CLUSTER_NAME=peeks-hub
./scripts/create-cross-account-roles.sh
```

This creates `peeks-cluster-mgmt-<service>` in the spoke account with:
- Trust policy allowing the hub ACK capability role to assume it
- Permissions for the AWS service

## Step 4: Sync ArgoCD

The `multi-acct` app on the hub deploys the IAMRoleSelectors. Sync it:

```bash
argocd app sync multi-acct-peeks-hub
```

## How It Works

```
Hub Cluster                          Spoke Account (825765380480)
┌─────────────────────┐              ┌──────────────────────────┐
│ ACK Capability Role │──assumes──>  │ peeks-cluster-mgmt-<svc> │
│ (peeks-peeks-hub-   │              │   - Trust: hub ACK role  │
│  ack-capability-role)│              │   - Policy: <svc>:*      │
└─────────────────────┘              └──────────────────────────┘
         │
         │ IAMRoleSelector routes
         │ namespace → role
         ▼
┌─────────────────────┐
│ ACK <svc> resource  │
│ namespace: spoke-ns │
└─────────────────────┘
```

## Validation

After setup, verify:

```bash
# Check IAMRoleSelector exists
kubectl get iamroleselectors | grep <service>

# Check ACK resource picks up the role
kubectl get <resource>.services.k8s.aws -n <spoke-namespace> -o jsonpath='{.status.conditions[?(@.type=="ACK.IAMRoleSelected")].message}'
```

## Common Issues

- **"sts:TagSession not authorized"**: The spoke role trust policy must include `sts:TagSession` alongside `sts:AssumeRole`
- **"Resource already exists"**: The AWS resource exists but wasn't created by ACK. Delete it or use adoption annotations
- **ACK creates resource in wrong account**: IAMRoleSelector not matching — check the `namespaceSelector` and `resourceTypeSelector.group`
