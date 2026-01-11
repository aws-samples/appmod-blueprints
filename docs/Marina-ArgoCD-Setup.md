# Marina ArgoCD Capability Setup

This document describes the configuration changes needed when using AWS EKS Marina (managed ArgoCD capability) instead of self-hosted ArgoCD.

## Overview

When using Marina, ArgoCD runs as a managed service outside the cluster. The cluster needs to be properly configured to allow Marina's ArgoCD instance to manage resources.

## Required Changes

### 1. GitOps Bridge Configuration

Update the `gitops_bridge_bootstrap` module in `platform/infra/terraform/common/argocd.tf` to create the cluster secret with the EKS cluster ARN:

```hcl
module "gitops_bridge_bootstrap" {
  source  = "gitops-bridge-dev/gitops-bridge/helm"
  version = "0.1.0"
  
  create  = true
  install = false  # Skip ArgoCD installation since Marina provides it
  
  cluster = {
    cluster_name = local.hub_cluster.name
    environment  = local.hub_cluster.environment
    metadata     = local.addons_metadata[local.hub_cluster_key]
    addons       = local.addons[local.hub_cluster_key]
    server       = data.aws_eks_cluster.clusters[local.hub_cluster_key].arn  # Use cluster ARN
  }

  apps = local.argocd_apps
}
```

**Key points:**
- Set `install = false` to skip ArgoCD installation
- Set `server` to the EKS cluster ARN instead of `https://kubernetes.default.svc`

### 2. EKS Access Policy

The Marina ArgoCD role needs cluster admin permissions. Associate the cluster admin policy:

```bash
aws eks associate-access-policy \
  --cluster-name <cluster-name> \
  --principal-arn "arn:aws:iam::<account-id>:role/AmazonEKSCapabilityArgoCDRole" \
  --policy-arn "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy" \
  --access-scope type=cluster \
  --region <region>
```

**Example:**
```bash
aws eks associate-access-policy \
  --cluster-name peeks-hub \
  --principal-arn "arn:aws:iam::382076407153:role/AmazonEKSCapabilityArgoCDRole" \
  --policy-arn "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy" \
  --access-scope type=cluster \
  --region ap-northeast-2
```

### 3. Kubernetes RBAC (Optional)

If additional RBAC is needed beyond EKS access policies, create a ClusterRoleBinding:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: "arn:aws:iam::<account-id>:role/AmazonEKSCapabilityArgoCDRole"
```

Apply with:
```bash
kubectl apply -f argocd-ack-permissions.yaml
```

## Verification

1. Check that the cluster secret is created with the correct ARN:
```bash
kubectl get secret <cluster-name> -n argocd -o jsonpath='{.data.server}' | base64 -d
```

2. Verify the access policy is associated:
```bash
aws eks list-associated-access-policies \
  --cluster-name <cluster-name> \
  --principal-arn "arn:aws:iam::<account-id>:role/AmazonEKSCapabilityArgoCDRole" \
  --region <region>
```

3. Check ArgoCD can sync applications:
```bash
# Using ArgoCD CLI or API
argocd app list
```

## Troubleshooting

### Error: "is forbidden: User cannot get/list resource"

**Cause:** The ArgoCD role lacks necessary permissions.

**Solution:** Ensure the `AmazonEKSClusterAdminPolicy` is associated with the ArgoCD role (see step 2 above).

### Error: "there are no clusters with this name"

**Cause:** The cluster secret uses `name` instead of `server` with the cluster ARN.

**Solution:** Update the gitops_bridge_bootstrap module to include `server = data.aws_eks_cluster.clusters[...].arn` (see step 1 above).

### Error: "cluster is disabled"

**Cause:** ArgoCD cannot find the cluster by the server URL.

**Solution:** Verify the cluster secret has the correct EKS cluster ARN in the `server` field.

## References

- [AWS EKS Access Policies](https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html)
- [GitOps Bridge Module](https://github.com/gitops-bridge-dev/gitops-bridge)
- [ArgoCD Cluster Management](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters)
