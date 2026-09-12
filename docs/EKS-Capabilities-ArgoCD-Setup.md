# EKS Capabilities ArgoCD Setup

This document describes the configuration changes needed when using AWS EKS Capabilities (managed ArgoCD capability) instead of self-hosted ArgoCD.

## Overview

When using EKS Capabilities, ArgoCD runs as a managed service outside the cluster. The cluster needs to be properly configured to allow the managed ArgoCD instance to manage resources.

## Required Changes

### 1. Cluster Secret (ArgoCD cluster registration)

The active cluster provider (under `cluster-providers/`) creates the ArgoCD **seed cluster secret**
in the `argocd` namespace during bootstrap. Because ArgoCD runs as an EKS Capability outside the
cluster, the secret's `server` field must be the **EKS cluster ARN** (not
`https://kubernetes.default.svc`). The minimal seed secret looks like:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <clusterName>
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    fleet_member: control-plane
    environment: control-plane
  annotations:
    addonsRepoURL: <repo.url>
    addonsRepoRevision: <repo.revision>
    addonsRepoBasepath: <repo.basepath>
stringData:
  name: <clusterName>
  server: <clusterARN>   # EKS cluster ARN, NOT https://kubernetes.default.svc
  config: '{"tlsClientConfig":{"insecure":false}}'
```

The `fleet-secret` chart later enriches this seed secret with the full set of `enable_*` labels and
metadata annotations. See `cluster-providers/README.md` ("Seed Cluster Secret" and "The Contract")
for the complete provider contract. Where the secret is created depends on the provider — e.g.
`cluster-providers/terraform/` (`argocd-capability.tf` / `secrets-manager.tf`) for the terraform
provider, or the Crossplane Composition / KRO RGD for the kind providers.

**Key points:**
- ArgoCD is provided by the EKS Capability — no ArgoCD is installed into the cluster
- Set `server` to the EKS cluster ARN instead of `https://kubernetes.default.svc`

### 2. EKS Access Policy

The EKS Capabilities ArgoCD role needs cluster admin permissions. Associate the cluster admin policy:

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

**Solution:** Ensure the cluster secret sets `server` to the EKS cluster ARN (see step 1 above).

### Error: "cluster is disabled"

**Cause:** ArgoCD cannot find the cluster by the server URL.

**Solution:** Verify the cluster secret has the correct EKS cluster ARN in the `server` field.

## References

- [AWS EKS Access Policies](https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html)
- [GitOps Bridge Module](https://github.com/gitops-bridge-dev/gitops-bridge)
- [ArgoCD Cluster Management](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters)
