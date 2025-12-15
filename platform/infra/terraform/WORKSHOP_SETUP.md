# Workshop Setup Guide

## ⚠️ Important: Setup Order Matters!

**Identity Center must be created FIRST** if you want SSO with EKS Capabilities.

## Option 1: Full Setup (With Identity Center SSO) - RECOMMENDED

### Step 1: Setup Identity Center FIRST
```bash
cd platform/infra/terraform/identity-center
./deploy.sh
```

### Step 2: Export Variables
Copy and run the export commands from Step 1:
```bash
export TF_VAR_identity_center_instance_arn="arn:aws:sso:::instance/ssoins-xxxxxxxxxx"
export TF_VAR_identity_center_admin_group_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export TF_VAR_identity_center_developer_group_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### Step 3: Deploy Clusters
```bash
cd ../cluster
./deploy.sh
```

## Option 2: Quick Start (No SSO)

```bash
cd platform/infra/terraform/cluster
./deploy.sh
```

## What Gets Created

- **EKS Clusters**: Hub (with capabilities) + Dev/Prod spokes
- **EKS Capabilities**: ArgoCD, ACK, Kro (hub cluster only)
- **Identity Center**: Groups and test user (if Option 1)

## Cleanup

```bash
# Destroy clusters first
cd platform/infra/terraform/cluster
./destroy.sh

# Then destroy identity center (optional)
cd ../identity-center
terraform destroy -auto-approve
```
