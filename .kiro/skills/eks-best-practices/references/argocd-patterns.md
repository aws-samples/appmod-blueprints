# ArgoCD Patterns for EKS

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** ArgoCD architecture patterns, deployment strategies, and multi-tenant RBAC for Amazon EKS

---

## Table of Contents

1. [ArgoCD Architecture on EKS](#argocd-architecture-on-eks)
2. [App of Apps Pattern](#app-of-apps-pattern)
3. [ApplicationSets](#applicationsets)
4. [GitOps Bridge Pattern](#gitops-bridge-pattern)
5. [Multi-Tenant RBAC](#multi-tenant-rbac)
6. [EKS ArgoCD Capability (Managed)](#eks-argocd-capability-managed)
7. [ACK and KRO Integration](#ack-and-kro-integration)

---

## ArgoCD Architecture on EKS

ArgoCD is a declarative GitOps continuous delivery tool for Kubernetes. It continuously monitors source repositories and reconciles the desired state with the live state in the cluster. ArgoCD supports multiple source types: **Git repositories**, **Helm registries** (HTTP and OCI), and **OCI images** — giving flexibility for different security and compliance requirements.

### Core Components

| Component | Role | Resource Profile |
|---|---|---|
| **API Server** | UI, CLI, API access, authentication | Low CPU, moderate memory |
| **Repo Server** | Clones Git repos, renders manifests (Helm, Kustomize) | CPU-intensive during sync |
| **Application Controller** | Reconciliation loop, compares desired vs live state | Memory-intensive (caches cluster state) |
| **Redis** | Caching layer for controller and API server | Low resource, critical for performance |
| **Dex / SSO** | Authentication (OIDC, SAML, LDAP) | Low resource |
| **Notifications Controller** | Sends alerts on sync status changes | Low resource |

### Self-Managed vs EKS Managed ArgoCD

| Factor | Self-Managed (Helm) | EKS ArgoCD Capability |
|---|---|---|
| **Installation** | Helm chart, you manage upgrades | AWS-managed, automatic upgrades |
| **Control plane** | Runs in your cluster | Runs in AWS-owned infrastructure |
| **Customization** | Full (plugins, custom tooling, RBAC) | Limited to supported configuration |
| **Multi-cluster** | Manual setup (cluster secrets) | Built-in hub-and-spoke |
| **IAM integration** | Manual OIDC/SAML setup | Native IAM Identity Center |
| **Cost** | Cluster compute only | EKS Capability pricing |
| **Best for** | Custom plugins, air-gapped, existing investment | Minimal ops, multi-account, new deployments |

---

## App of Apps Pattern

The App of Apps pattern uses a single "parent" ArgoCD Application that contains manifests defining other ArgoCD Applications. This enables declarative bootstrapping of an entire platform from a single entry point.

### Structure

| Level | What It Contains | Example |
|---|---|---|
| **Root App** | Points to a directory of Application manifests | `platform-root` → `apps/` directory |
| **Platform Apps** | Infrastructure add-ons (monitoring, ingress, cert-manager) | `apps/monitoring.yaml`, `apps/ingress.yaml` |
| **Tenant Apps** | Team workloads | `apps/team-a.yaml`, `apps/team-b.yaml` |

### When to Use

| Scenario | App of Apps | ApplicationSets |
|---|---|---|
| **Cluster bootstrapping** | Yes — single entry point for all platform components | Possible but more complex |
| **Static set of apps** | Good fit — each app is an explicit manifest | Overkill |
| **Dynamic app generation** | Poor fit — must manually create each manifest | Better — template-based |
| **Multi-cluster** | One root app per cluster | One ApplicationSet generates across clusters |

### Benefits and Limitations

| Benefits | Limitations |
|---|---|
| Single entry point for cluster bootstrap | Each new app requires a new manifest file |
| Explicit — every app is visible in Git | Doesn't scale well to hundreds of apps |
| Easy to understand and debug | No templating — each manifest is hand-written |
| Works with any manifest format | Changes require Git commit per app |

---

## ApplicationSets

ApplicationSets are a templating mechanism that generates multiple ArgoCD Applications from a single definition. They use generators to produce parameter sets, which are then applied to a template to create Applications.

### Generators

| Generator | What It Does | Use Case |
|---|---|---|
| **Git Directory** | Creates an app per directory in a Git repo | Monorepo with one dir per service |
| **Git File** | Creates an app per config file in a Git repo | Config-driven app definitions |
| **Cluster** | Creates an app per registered cluster | Multi-cluster deployments |
| **Matrix** | Combines two generators (cross-product) | Per-cluster × per-environment |
| **Merge** | Combines generators with override logic | Base config + cluster-specific overrides |
| **List** | Static list of parameter sets | Small, known set of targets |
| **Pull Request** | Creates app per open PR | Preview environments |

### Common Patterns

| Pattern | Generator | Description |
|---|---|---|
| **Per-environment** | Git Directory | `environments/dev/`, `environments/staging/`, `environments/prod/` |
| **Per-cluster** | Cluster | Deploy same app to all registered clusters |
| **Per-tenant** | Git File | One config file per tenant defines their apps |
| **Preview environments** | Pull Request | Ephemeral environment per PR |
| **Matrix (cluster × env)** | Matrix | Deploy to every cluster in every environment |

### ApplicationSets vs App of Apps

| Factor | ApplicationSets | App of Apps |
|---|---|---|
| **Scaling** | Handles hundreds of apps via templates | Manual — one manifest per app |
| **Dynamic generation** | Yes — new directory/file/cluster auto-generates | No — must commit new manifest |
| **Complexity** | Higher (generator logic, template syntax) | Lower (plain Application manifests) |
| **Debugging** | Harder (template rendering issues) | Easier (explicit manifests) |
| **Recommendation** | Use for dynamic, large-scale deployments | Use for static platform bootstrapping |

---

## GitOps Bridge Pattern

The GitOps Bridge pattern separates infrastructure provisioning (Terraform) from application/add-on management (ArgoCD). Terraform creates the cluster and bootstraps ArgoCD; ArgoCD manages everything else.

### How It Works

| Phase | Tool | What It Does |
|---|---|---|
| **1. Infrastructure** | Terraform | Provisions VPC, EKS cluster, node groups, IAM roles |
| **2. Bootstrap** | Terraform | Installs ArgoCD via Helm, creates root Application |
| **3. Add-ons** | ArgoCD | Manages all cluster add-ons (monitoring, ingress, policy engine) |
| **4. Applications** | ArgoCD | Manages all workload deployments |

### Integration with terraform-aws-modules/eks

The `terraform-aws-modules/eks` module provisions the cluster. Terraform then installs ArgoCD and creates a bootstrap Application pointing to the GitOps repository. From that point, ArgoCD takes over management of add-ons and applications.

| Terraform Manages | ArgoCD Manages |
|---|---|
| VPC, subnets, NAT | Cluster add-ons (monitoring, ingress, cert-manager) |
| EKS cluster, node groups | Policy engine (Kyverno, Gatekeeper) |
| IAM roles (cluster, node, Pod Identity) | Application deployments |
| KMS keys, S3 buckets | Namespace configuration, RBAC |
| ArgoCD installation (bootstrap only) | ArgoCD self-management (after bootstrap) |

---

## Multi-Tenant RBAC

ArgoCD Projects provide tenant isolation by restricting what each team can deploy, where they can deploy, and what cluster resources they can access.

### AppProject Scoping

| Restriction | What It Controls | Example |
|---|---|---|
| **Source repos** | Which Git repos the project can read | `https://github.com/org/team-a-*` |
| **Destinations** | Which clusters and namespaces apps can deploy to | `cluster: in-cluster, namespace: team-a-*` |
| **Cluster resources** | Which cluster-scoped resources are allowed | Deny `ClusterRole`, `Namespace` creation |
| **Namespaced resources** | Which namespaced resources are allowed/denied | Allow `Deployment`, `Service`; deny `ResourceQuota` |

### SSO Integration

| Provider | Integration Method | Notes |
|---|---|---|
| **OIDC** | Dex connector or built-in OIDC | Most common; works with Okta, Azure AD, Google |
| **SAML** | Dex connector | Enterprise SSO |
| **LDAP** | Dex connector | On-premises directory |
| **IAM Identity Center** | EKS ArgoCD Capability only | Native AWS SSO |

### RBAC Model

| Role | Scope | Permissions |
|---|---|---|
| **Platform admin** | All projects | Full access — create/delete apps, manage projects |
| **Tenant admin** | Own project | Create/sync/delete apps within project boundaries |
| **Tenant developer** | Own project | Sync apps, view logs; cannot create or delete |
| **Viewer** | All or specific projects | Read-only — view app status, logs |

---

## Multi-Cluster Architecture Patterns

When deploying ArgoCD (managed or self-managed) across multiple clusters, three patterns emerge:

### Hub-and-Spoke (Centralized)

All capabilities run on a central management cluster that orchestrates workloads and infrastructure across spoke clusters.

| Component | Where It Runs | What It Does |
|---|---|---|
| **ArgoCD** | Management cluster | Deploys apps to all workload clusters |
| **ACK** | Management cluster | Provisions AWS resources (RDS, S3, IAM) for all clusters |
| **KRO** | Management cluster | Creates portable abstractions across all clusters |

**Best for:** Centralized platform teams, audit/compliance requirements, fleet management.

### Decentralized

Each cluster runs its own capabilities independently.

| Component | Where It Runs | What It Does |
|---|---|---|
| **ArgoCD** | Each cluster | Manages local applications only |
| **ACK** | Each cluster | Provisions resources for local workloads |
| **KRO** | Each cluster | Local resource compositions |

**Best for:** Autonomous teams, independent clusters, minimal cross-cluster dependencies.

### Hybrid (Hub + Local ACK)

Combines centralized GitOps delivery with local resource management based on scope.

| Component | Hub Cluster | Spoke Clusters |
|---|---|---|
| **ArgoCD** | Deploys to all clusters | N/A (managed from hub) |
| **ACK** | Admin-scoped resources (production DBs, IAM, VPCs) | Workload-scoped resources (S3 buckets, SQS queues) |
| **KRO** | Reusable platform abstractions | Local building block patterns |

**Best for:** Platform teams managing critical infrastructure centrally while enabling self-service for application teams.

### Choosing a Pattern

| Factor | Hub-and-Spoke | Decentralized | Hybrid |
|---|---|---|---|
| **Org structure** | Centralized platform team | Autonomous teams | Platform team + app teams |
| **Compliance** | Easiest to audit | Hardest to audit | Balanced |
| **Operational complexity** | Fewer instances, possible bottleneck | More instances to manage | Moderate |
| **Self-service** | Via KRO abstractions from hub | Full autonomy | Admin from hub, workload locally |

You can start with one pattern and evolve — capabilities are independent and can be deployed differently across clusters.

---

## EKS ArgoCD Capability (Managed)

The EKS ArgoCD Capability is an AWS-managed ArgoCD service that runs in AWS-owned infrastructure, separate from your cluster. AWS handles scaling, patching, and upgrading. It does not consume worker node resources.

| Feature | Detail |
|---|---|
| **Control plane** | Runs in AWS infrastructure (not in your cluster, no node resource consumption) |
| **Multi-cluster** | Built-in hub-and-spoke — manage multiple EKS clusters from one instance |
| **Authentication** | Native IAM Identity Center integration (3 roles: admin, editor, viewer) |
| **Upgrades** | AWS-managed, automatic |
| **Sources** | Git (HTTPS/SSH), Helm registries (HTTP/OCI), OCI images, CodeCommit, CodeConnections (GitHub, GitLab, Bitbucket) |
| **Secrets** | Native Secrets Manager integration |
| **Registry** | Native ECR integration (OCI Helm charts) |
| **Private clusters** | Transparent access — no VPC peering or special networking needed |
| **Remote clusters** | Uses EKS access entries — no IRSA or cross-account role assumptions needed |
| **Pricing** | Hourly per capability + hourly per managed K8s resource |

### Managed Capability Limitations

Features **not available** in the managed capability (use self-managed if you need these):

| Unsupported Feature | Workaround |
|---|---|
| Config Management Plugins (CMPs) | Pre-render manifests in CI pipeline |
| Custom Lua health checks | Built-in checks cover standard resources |
| Notifications controller | Use EventBridge + CloudWatch for alerting |
| Custom SSO providers | Only IAM Identity Center (supports third-party federation through Identity Center) |
| UI extensions / custom banners | N/A |
| Direct argocd-cm ConfigMap access | Configure via capability API |
| Custom sync timeout | Fixed at 120 seconds |

### Key Operational Differences

- **Single namespace:** All ArgoCD CRs (Application, ApplicationSet, AppProject) must be created in one namespace (default: `argocd`). Workloads deploy to any namespace in any target cluster.
- **Only EKS targets:** Deployment targets must be EKS clusters identified by ARN (not arbitrary Kubernetes API server URLs).
- **Local cluster not auto-registered:** You must explicitly register the local cluster using its ARN to deploy to it.
- **CLI differences:** Use `argocd app sync namespace/appname` (namespace prefix required). `argocd admin` and `argocd login` are not supported — use account or project tokens.
- **Namespace isolation:** Keep only ArgoCD-relevant secrets in the ArgoCD namespace — the capability has access to all secrets in its namespace.

### When to Use EKS Managed vs Self-Managed

| Scenario | Recommendation |
|---|---|
| New deployment, minimal ops team | EKS Managed |
| Multi-account, hub-and-spoke | EKS Managed |
| Need IAM Identity Center SSO | EKS Managed |
| Private clusters with no extra networking | EKS Managed |
| Custom ArgoCD plugins (CMPs) | Self-managed |
| Air-gapped environment | Self-managed |
| Existing ArgoCD investment | Self-managed (unless migrating) |
| Need specific ArgoCD version | Self-managed |
| Need Notifications controller | Self-managed |

### Migrating from Self-Managed to EKS Managed

1. Review current config for unsupported features (CMPs, custom Lua, Notifications, UI extensions)
2. Scale self-managed ArgoCD controllers to zero replicas
3. Create ArgoCD capability resource on your cluster
4. Export existing Applications, ApplicationSets, and AppProjects
5. Migrate repository credentials and cluster secrets
6. Update `destination.server` fields to use cluster names or EKS cluster ARNs
7. Apply manifests to the managed instance
8. Verify applications sync correctly
9. Decommission self-managed installation

Existing Application/ApplicationSet manifests work with minimal modification — the managed capability uses the same Kubernetes APIs and CRDs.

---

## ACK and KRO Integration

### AWS Controllers for Kubernetes (ACK)

ACK lets you manage AWS resources using Kubernetes custom resources. Instead of using Terraform or CloudFormation for AWS resources, you define them as Kubernetes manifests that ArgoCD can manage via GitOps. ACK translates Kubernetes CR specs into AWS API calls and continuously reconciles to maintain desired state (detecting and correcting drift).

| ACK Controller | AWS Resources Managed |
|---|---|
| **S3** | Buckets, bucket policies |
| **RDS** | DB instances, DB clusters, parameter groups |
| **IAM** | Roles, policies |
| **EC2** | Security groups, VPC resources |
| **SQS** | Queues |
| **SNS** | Topics, subscriptions |
| **DynamoDB** | Tables |
| **ElastiCache** | Clusters, replication groups |
| **Lambda** | Functions, event source mappings |
| **EKS** | Clusters, node groups |

| Feature | Description |
|---|---|
| **Multi-account/multi-region** | Manage AWS resources across multiple AWS accounts and regions from a single cluster |
| **Resource adoption** | Bring existing AWS resources under ACK management without recreation |
| **Read-only resources** | Observe AWS resources without modification access |
| **Retention annotations** | Optionally retain AWS resources when Kubernetes CRs are deleted |

### Kube Resource Orchestrator (KRO)

KRO provides platform abstractions via `ResourceGraphDefinitions` (RGDs). Platform teams define golden path templates that combine multiple resources (Kubernetes + AWS via ACK) into a single custom resource that tenant teams consume. KRO automatically determines interdependencies and resource ordering, and uses Common Expression Language (CEL) for injecting values between resources and conditional logic.

| Concept | What It Does | Example |
|---|---|---|
| **ResourceGraphDefinition** | Defines a custom API combining multiple resources | "WebApp" = Deployment + Service + Ingress + RDS (via ACK) |
| **Instance** | A tenant creates an instance of the template | `kind: WebApp, name: team-a-api` |
| **Reconciliation** | KRO creates and manages all child resources | Creates Deployment, Service, Ingress, RDS instance |

### Combined Pattern: ArgoCD + ACK + KRO

| Layer | Tool | What It Manages |
|---|---|---|
| **GitOps delivery** | ArgoCD | Syncs all manifests from Git to cluster |
| **AWS resources** | ACK | Creates/updates AWS resources (RDS, S3, SQS) as K8s CRDs |
| **Platform abstractions** | KRO | Combines K8s + ACK resources into golden path templates |
| **Tenant self-service** | KRO instances | Tenants create a single CR, get a full stack |

---

**Sources:**
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [EKS Workshop — ArgoCD](https://eksworkshop.com/docs/automation/gitops/argocd/)
- [AWS EKS Capabilities](https://docs.aws.amazon.com/eks/latest/userguide/capabilities.html)
- [AWS Blog — GitOps with EKS Blueprints and ArgoCD](https://aws.amazon.com/blogs/containers/continuous-deployment-and-gitops-delivery-with-amazon-eks-blueprints-and-argocd/)
- [AWS Blog — Deep dive: Streamlining GitOps with EKS ArgoCD Capability](https://aws.amazon.com/blogs/containers/deep-dive-streamlining-gitops-with-amazon-eks-capability-for-argo-cd/)
