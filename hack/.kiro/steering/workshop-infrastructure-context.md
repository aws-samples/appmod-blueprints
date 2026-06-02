# Infrastructure Context — feature/cloudfront-exposure

## Purpose

Architecture and deployment context for the appmod-blueprints platform on the `feature/cloudfront-exposure` branch.

## Instructions

### Bootstrap (kind-crossplane provider)

- Bootstrap uses `task install` which delegates to `cluster-providers/kind-crossplane/Taskfile.yaml`
- Kind cluster runs Crossplane to provision the hub EKS cluster (VPC, subnets, IAM, EKS)
- After hub is ACTIVE, a Job creates EKS Capabilities (ArgoCD + KRO + ACK)
- ESO is installed on hub, seed secret applied, root-appset bootstraps self-management
- Kind cluster can be deleted after hub is self-managing (`task destroy-kind`)

### EKS Capabilities

- **ArgoCD** — managed GitOps, configured with IDC for SSO (ADMIN mapped to IDC group)
- **KRO** — managed Kube Resource Orchestrator, provides ResourceGraphDefinitions
- **ACK** — managed AWS Controllers for Kubernetes, provisions AWS resources from K8s
- All three created in `manifests/argocd/create-capability.yaml` Job
- They are NOT pods — they're EKS managed services

### Exposure Mode: CloudFront

- Single internet-facing ALB (`peeks-hub-platform`) shared by all ingresses via IngressClassParams group
- CloudFront distribution fronts the ALB (HTTPS termination, caching)
- Apps differentiated by path prefix with ALB URL rewrite (`transforms` annotation)
- No custom domain or Route53 needed
- CloudFront domain stored in `private/cloudfront-domain`

### ALB URL Rewrite Pattern

```yaml
annotations:
  alb.ingress.kubernetes.io/transforms.<service-name>: |
    [{"type":"url-rewrite","urlRewriteConfig":{"rewrites":[{"regex":"^\\/prefix\\/?(.*)$","replace":"/$1"}]}}]
```

Required for apps that don't natively serve at their path prefix (argo-workflows, backstage).
Not needed for apps that handle their own path (keycloak with `/keycloak` context path).

### Cluster Provisioning — Two Paths

**1. Crossplane (platform team)**
- `gitops/abstractions/crossplane/platform-cluster/` — XRD + Composition
- Creates `PlatformCluster` claims in `crossplane-system` namespace
- Provisions full stack: VPC, subnets, NAT, IGW, EKS, IAM roles, node roles
- Triggered by `gitops/fleet/kro-values/tenants/<tenant>/kro-clusters/values.yaml`
- ArgoCD `clusters.yaml` ApplicationSet watches these files

**2. KRO + ACK (self-service)**
- `gitops/addons/charts/kro/resource-groups/manifests/eks/` — ResourceGraphDefinitions
- Creates `EksCluster` custom resources reconciled by ACK capability
- Intended for tenant self-service via Backstage templates
- Expects existing VPC (or uses separate `rg-vpc.yaml` ResourceGraphDefinition)

### IDC ↔ Keycloak Federation

- `configure_identity_center.py` uses Playwright browser automation
- Changes IDC identity source to External IdP (Keycloak SAML)
- Enables SCIM automatic provisioning
- Syncs Keycloak users/groups to IDC
- Credentials seeded from EC2 instance profile → SSM parameter
- Taskfile task: `idc:configure` (runs after hub apps are synced)

### Addon Management

- Addons defined in `gitops/addons/registry/<domain>.yaml` (core, platform, security, observability, ml)
- Enablement via `gitops/overlays/environments/<env>/enabled-addons.yaml`
- Values layered: chart defaults → addon configs → environment overrides → cluster overrides
- `fleet-secret` chart generates ArgoCD cluster secrets with `enable_*` labels
- `appset-chart` ApplicationSets match labels to deploy addons to clusters

### Secrets Flow

- AWS Secrets Manager holds platform secrets (`peeks-hub/config`, `peeks-hub/keycloak`, `peeks-hub/secrets`)
- ExternalSecrets Operator (ESO) on hub syncs secrets into K8s via ClusterSecretStore
- Pod Identity provides ESO with AWS credentials (no static keys)

### Multi-Cluster Architecture

- **Hub** (`peeks-hub`) — control plane: ArgoCD, Backstage, Keycloak, Crossplane, observability
- **Spokes** (`spoke-dev`, `spoke-prod`) — workload clusters managed by hub
- Hub ArgoCD deploys addons to spokes via cluster secrets with `enable_*` labels
- Crossplane on hub manages spoke lifecycle (create/update/delete)

## Priority

Critical

## Error Handling

- If `task install` fails, it's idempotent — re-run safely
- If ESO pods are in ImagePullBackOff, check NAT gateway exists for private subnets
- If ALB creation fails with "no internet gateway", ensure IGW is attached to EKS VPC
- If Keycloak SAML update fails, verify CloudFront domain is propagated
- If IDC configure fails, check SSM parameter has valid credentials with RoleArn in description
