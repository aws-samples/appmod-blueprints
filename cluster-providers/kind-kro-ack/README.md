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
| `config.local.yaml` | See below |

### config.local.yaml

```yaml
hub:
  clusterName: hub
  kubernetesVersion: "1.37"
  vpcCidr: "10.0.0.0/16"
  adminRoleName: Admin  # IAM role for cluster admin access entry
aws:
  accountId: "123456789012"
  region: us-west-2
  profile: default
repo:
  url: https://github.com/aws-samples/appmod-blueprints
  revision: main
  basepath: gitops
domain: example.com
resourcePrefix: peeks
ingressName: hub-ingress
ingressSecurityGroups: ""
argocdCapability:
  enabled: "true"  # Set to "false" to use Helm-installed ArgoCD instead
identityCenter:
  instanceArn: arn:aws:sso:::instance/ssoins-XXXXXXXX  # Must exist
  region: us-east-1  # Region where IDC is deployed
  identityStoreId: d-XXXXXXXXXX  # Optional, auto-detected if omitted
  adminGroupId: ""  # Optional, created by idc:setup if empty
platformTags:  # Optional AWS tags on the hub and every spoke (EKS, VPC, NAT, EIP)
  auto-delete: "no"  # e.g. the retention tag of the account's cleanup sweeper, if any
  # Any other AWS tag works the same way (e.g. owner, cost-center): each key is
  # propagated to the hub, the spokes and their VPCs.
  # owner: "<your-team>"
```

`platformTags` is optional. Without it nothing is tagged and `task install` prints a warning, because an account cleanup sweeper may then reap the hub or the spokes. Set it before installing: `hub:claim` tags the hub and `hub:seed` passes the tags to every spoke (hub cluster-secret `platform_tags` annotation, then `awsTags` on each `EksclusterWithVpc`).

**IDC prerequisite**: An Identity Center instance must exist in your account/organization. The `idc:setup` task creates groups and users automatically. With `IDC_CONFIGURE_SKIP=true` (for example a second stack in an account whose Identity Center another stack already uses) it prints a notice, creates nothing and makes no Identity Center call. It then also leaves `identityCenter.identityStoreId` and `identityCenter.adminGroupId` unset, and `hub:claim` maps the Argo CD capability's ADMIN SSO group from `adminGroupId`, so set both keys in `config.local.yaml` yourself when you use the knob.

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

## KUBECONFIG constraints

- **Do not export `KUBECONFIG` before `task install`.** This Taskfile sets `env: KUBECONFIG: <repo>/private/kubeconfig`, but go-task gives a variable already set in your shell priority over a Taskfile `env:` entry ([go-task env precedence](https://taskfile.dev/docs/experiments/env-precedence)). The template value `{{.KUBECONFIG}}` keeps the Taskfile path, so `kind create cluster --kubeconfig {{.KUBECONFIG}}` writes the kind context to `private/kubeconfig`, while the plain `kubectl`/`helm` calls that follow read your exported file. That file has no kind context, so the install fails at the first `kubectl` step after `kind:create`. Run `unset KUBECONFIG` first, or export exactly `$PWD/private/kubeconfig` from the repo root.
- **The provider install does not touch `~/.kube/config`.** It writes only `private/kubeconfig` (kind) and `private/hub-kubeconfig` (hub, via `aws eks update-kubeconfig --kubeconfig ...`).
- **`task kubeconfig` (root Taskfile) does.** It runs `aws eks update-kubeconfig --alias <name>` for every EKS cluster named `<resourcePrefix>-*`, writing to your default kubeconfig (`$KUBECONFIG`, else `~/.kube/config`). Each call switches the current context. The task then runs `kubectl config use-context <resourcePrefix>-hub || true`: if your `hub.clusterName` is not `<resourcePrefix>-hub`, that step fails silently and you stay on whichever cluster was written last.
- **`aws eks update-kubeconfig` with a wrong `--name`** (for example a hub name that differs from your `hub.clusterName`) returns an error and changes nothing. If that error is hidden (`>/dev/null 2>&1 || true`), the previous context stays current and your next `kubectl` runs against another cluster. Check `kubectl config current-context` before trusting a `kubectl` result.

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

## Multi-hub fleet scoping (opt-in)

Several hubs can share one fleet repo by setting `fleetScopeByPrefix: true` in `config.local.yaml`. `hub:seed` then writes `fleet_scope_by_prefix: "true"` into the `<hub>/config` metadata, which ESO copies onto the hub cluster-secret, and the hub discovers only `clusters/<resourcePrefix>/*.json` and `fleet/members/<resourcePrefix>/*/values.yaml`. When the key is absent or `false`, nothing is written and the flat `clusters/*.json` / `fleet/members/*/values.yaml` layout is used, exactly as before. A value set by hand on `<hub>/config` is kept on re-seed; to turn it off, remove the key from `<hub>/config` too.

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
