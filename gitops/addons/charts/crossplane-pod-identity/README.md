# crossplane-pod-identity

Helm chart that creates AWS IAM roles, policies, and EKS PodIdentityAssociations for platform addons. Not a standalone ArgoCD addon — used as an `additionalResources` source by consumer addons (LBC, external-dns).

## How it works

Each identity creates four Crossplane resources in order:
1. **IAM Role** (wave -3) — assume role for `pods.eks.amazonaws.com`
2. **IAM Policy** (wave -3) — least-privilege policy for the addon
3. **RolePolicyAttachment** (wave -2) — attaches policy to role
4. **PodIdentityAssociation** (wave -1) — links the role to a Kubernetes ServiceAccount on a specific EKS cluster

After the main addon deploys (wave 0), a **PostSync restart hook** checks if the addon's pods received credentials. EKS Pod Identity injects credentials at pod creation time via a webhook. If the PodIdentityAssociation didn't exist when the pod started, the pod runs without credentials permanently. The hook detects this by checking for the `AWS_CONTAINER_CREDENTIALS_FULL_URI` environment variable and restarts the deployment if missing. On subsequent syncs, credentials are already present and no restart occurs.

## Identities

All identities are disabled by default. Each consumer addon enables only its own.

| Identity | Service Account | Namespace | Policy |
|----------|----------------|-----------|--------|
| `eso` | `external-secrets-sa` | `external-secrets` | Secrets Manager read/write |
| `lbc` | `aws-load-balancer-controller-sa` | `kube-system` | ELB, EC2, WAF, Shield, Cognito |
| `external-dns` | `external-dns-sa` | `kube-system` | Route53 record management |

## Usage

### As additionalResources in the addon registry

```yaml
# addons/registry/core.yaml
aws-load-balancer-controller:
  ...
  additionalResources:
    - path: '{{.metadata.annotations.addonsRepoBasepath}}addons/charts/crossplane-pod-identity'
      helm:
        releaseName: lbc-pod-identity
        valuesObject:
          aws:
            region: '{{.metadata.annotations.aws_region}}'
            clusterName: '{{.metadata.annotations.aws_cluster_name}}'
            accountId: '{{.metadata.annotations.aws_account_id}}'
          identities:
            lbc:
              enabled: true
```

### During bootstrap (ESO only)

```bash
helm template crossplane-pod-identity addons/charts/crossplane-pod-identity \
  --set aws.region=us-west-2 \
  --set aws.clusterName=hub \
  --set aws.accountId=123456789012 \
  --set identities.eso.enabled=true \
  | kubectl apply -f -
```

## Resource naming

IAM roles and policies are prefixed with `clusterName` to prevent collisions when multiple platform instances share an AWS account:

| Resource | AWS Name |
|----------|----------|
| ESO Role | `{clusterName}-ESOPodIdentityRole` |
| ESO Policy | `{clusterName}-ESOSecretsManagerPolicy` |
| LBC Role | `{clusterName}-LBCPodIdentityRole` |
| LBC Policy | `{clusterName}-LBCControllerPolicy` |
| External DNS Role | `{clusterName}-ExternalDNSPodIdentityRole` |
| External DNS Policy | `{clusterName}-ExternalDNSRoute53Policy` |

## PostSync restart hook

The chart includes a PostSync hook per enabled identity that:

1. Finds the deployment using the identity's ServiceAccount
2. Checks if pods have `AWS_CONTAINER_CREDENTIALS_FULL_URI` injected
3. If missing, restarts the deployment so the EKS Pod Identity webhook injects credentials
4. If present, exits without action

The hook creates a temporary ServiceAccount, Role, and RoleBinding (all with `HookSucceeded` delete policy) scoped to the target namespace with minimal permissions (get/list pods, get/list/patch deployments).

## Bootstrap / Hub handover

ESO's pod identity is created during Kind bootstrap and is permanent infrastructure — the hub never recreates it. LBC and external-dns identities are created fresh by the hub via `additionalResources` on their respective addon apps.
