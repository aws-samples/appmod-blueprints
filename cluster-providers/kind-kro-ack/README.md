# Kind + KRO + ACK Provider

Zero-Terraform bootstrap for the hub cluster using KRO ResourceGraphDefinitions and ACK controllers instead of Crossplane. Spins up an ephemeral Kind cluster, installs ACK (IAM, EKS, EC2) + KRO, provisions all AWS infrastructure (VPC, EKS, IAM), seeds ArgoCD on the hub, and then the Kind cluster can be deleted.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| kind | Local Kubernetes cluster |
| kubectl | Cluster access |
| helm 3.x | Chart installation |
| yq | YAML processing |
| aws CLI | Configured with credentials |
| `config.local.yaml` | Must have `hub.clusterName`, `aws.region`, `aws.accountId`, `repo.url` set |

## Task Commands

| Command | Description |
|---------|-------------|
| `task install` | Full bootstrap: Kind → ACK+KRO → AWS infra → ArgoCD → self-managing hub |
| `task status` | Show state of Kind, Helm releases, KRO RGDs, instances |
| `task destroy-kind` | Delete Kind cluster only (hub persists) |
| `task destroy` | Full teardown: delete KRO instances, wait for ACK cleanup, delete Kind |
| `task credentials:refresh` | Force-refresh AWS credentials secret |

## Bootstrap Flow

```
task install
  1. kind:create         Create Kind cluster
  2. credentials:setup   Create aws-credentials secret for ACK controllers
  3. argocd:install      Helm install ArgoCD
  4. ack:install         Helm install ACK controllers (IAM v1.3.16, EKS v1.6.0, EC2 v1.3.4)
  5. kro:install         Helm install KRO (v0.6.1)
  6. kro:apply-rgds      Apply ResourceGraphDefinitions (rg-vpc, rg-eks, rg-eks-vpc)
  7. hub:claim           Apply EksclusterWithVpc instance (creates VPC + EKS + IAM + pod identities)
  8. hub:seed            Wait for ACTIVE, create access entry, ArgoCD capability, seed secrets, ESO, root-appset
  9. hub:wait-for-sync   Wait for hub ArgoCD apps to converge
```

## Architecture: Crossplane vs KRO+ACK

| Aspect | kind-crossplane | kind-kro-ack |
|--------|----------------|--------------|
| Controllers | Crossplane + AWS providers | ACK IAM + EKS + EC2 + KRO |
| Resource model | XRD → Composition → Managed Resources | ResourceGraphDefinition → ACK CRs |
| Credentials | ProviderConfig + Secret | `aws.credentials.secretName` in Helm values |
| ArgoCD Capability | Job (EKS API) | Job (same — ACK Capability CRD used on hub only) |
| Dependency ordering | Composition pipeline functions | KRO `readyWhen` expressions |
| Spoke provisioning | Hub Crossplane | Hub ACK+KRO (via EKS Capabilities) |

## Key Differences

1. **No Crossplane dependency** — ACK controllers are first-party AWS, no Upbound provider DRC issues
2. **Simpler resource model** — KRO ResourceGraphDefinitions are plain YAML with CEL expressions
3. **Same RGDs for bootstrap and runtime** — the hub uses identical RGDs to provision spokes
4. **Pod Identity native** — ACK uses Pod Identity on the hub; on Kind bootstrap, credentials Secret is mounted

## Credentials on Kind

ACK controllers on Kind cannot use Pod Identity (no IMDS). The Taskfile creates an `aws-credentials` Secret and configures each ACK controller Helm chart with:

```yaml
aws:
  credentials:
    secretName: aws-credentials
    secretKey: credentials
```

On the hub (after bootstrap), ACK runs as an EKS Capability with its own IAM role — no credentials Secret needed.

### Keeping the Kind cluster alive

If you keep the Kind cluster running (e.g. to manage hub infrastructure updates), AWS session tokens will expire (typically 12h). When this happens, ACK controllers stop reconciling and resources show `SYNCED: Unknown`.

Fix:
```bash
task credentials:refresh
kubectl rollout restart deploy -n ack-system
```

For long-lived Kind clusters, consider using an IAM user with static credentials or running on an EC2 instance with an instance profile (credentials auto-rotate via IMDS).
