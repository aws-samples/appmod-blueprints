# GitOps Addon Management: Structure Evaluation & Recommendations

## 1. Current State Analysis

### appmod-blueprints/gitops (AWS-focused)

```
gitops/
├── addons/
│   ├── bootstrap/default/addons.yaml      # Single 1759-line monolith defining ALL addons
│   ├── charts/<addon-name>/               # 27 wrapper Helm charts (Chart.yaml + templates/)
│   ├── default/addons/<addon-name>/       # Per-addon default values.yaml
│   ├── environments/control-plane/        # Environment-level enable/disable overrides
│   └── tenants/control-plane/             # Tenant-level overrides (sparse)
├── fleet/
│   ├── bootstrap/addons.yaml              # ApplicationSet that renders the appset-chart
│   ├── bootstrap/clusters.yaml            # ApplicationSet for cluster provisioning via KRO
│   ├── bootstrap/fleet-secrets.yaml       # Matrix generator for fleet member secrets
│   └── members/                           # Registered fleet member clusters
├── platform/
│   ├── bootstrap/                         # Team namespace & workload ApplicationSets
│   ├── charts/teams/                      # Helm chart for team resource provisioning
│   └── teams/{backend,frontend}/          # Per-team environment/tenant overrides
├── apps/                                  # Application workload manifests
└── workloads/                             # ML/AI workload definitions
```

### reference-implementation-azure/packages (Azure-focused)

```
packages/
├── bootstrap.yaml                         # Root ArgoCD Application pointing to appset-chart
├── bootstrap/
│   ├── bootstrap-addons.yaml              # Bootstrap-phase addon definitions (ArgoCD, ESO, Crossplane, ingress)
│   ├── cnoe-addons.yaml                   # Hub cluster addon ApplicationSet definitions
│   └── manifests/{argocd,crossplane,external-secrets}/
├── appset-chart/                          # Shared Helm chart generating ApplicationSets
│   └── templates/
├── addons/
│   ├── values.yaml                        # All addon definitions in one file (~300 lines)
│   └── path-routing-values.yaml           # Routing-variant overrides
└── <addon-name>/                          # Per-addon: values.yaml + manifests/
    ├── values.yaml
    └── manifests/
```

---

## 2. Key Findings

### What works well

| Pattern | Where | Why it works |
|---------|-------|-------------|
| Value layering: default → environment → tenant → cluster | appmod-blueprints | Scales to 500 clusters without per-cluster files for most addons |
| Shared appset-chart as rendering engine | Both repos | Single template generates all ApplicationSets; avoids per-addon boilerplate |
| KRO ResourceGraphDefinitions for abstractions | appmod-blueprints | Decouples addon consumers from infrastructure providers (ACK/Crossplane/CAPI) |
| Per-addon `values.yaml` in `default/addons/<name>/` | appmod-blueprints | Clean separation of addon config from addon definition |
| Per-addon folders with `manifests/` + `values.yaml` | Azure repo | Easy to find everything related to one addon |
| Bootstrap phase separation | Both repos | Makes the chicken-and-egg dependency (ArgoCD managing itself) explicit |
| Cluster secret annotations for dynamic values | Both repos | Avoids per-cluster files; scales to hundreds of clusters |

### What needs improvement

| Issue | Impact | Where |
|-------|--------|-------|
| Monolithic `addons.yaml` (1759 lines) | Merge conflicts, hard to review, single point of failure | appmod-blueprints |
| Addon definition duplicated across `bootstrap-addons.yaml` and `addons/values.yaml` | ArgoCD defined in both files with slightly different configs | Azure repo |
| Wrapper charts in `charts/` mix custom charts with thin wrappers | Unclear which charts have real logic vs. just a `Chart.yaml` | appmod-blueprints |
| Sync-wave ordering scattered as inline comments | No central view of deployment ordering; easy to break dependencies | Both repos |
| `default/addons/` and `charts/` have overlapping addon names but different purposes | Confusing: is `keycloak` the chart or the values? | appmod-blueprints |
| KRO resource-groups buried inside `charts/kro/` | These are platform abstractions, not addon charts | appmod-blueprints |
| Fleet member registration is a flat directory with `.gitkeep` | No structure for organizing members by environment or region | appmod-blueprints |
| `enabled: false` in addons.yaml then `enabled: true` in environments | Two-step enable pattern is error-prone; easy to miss one | appmod-blueprints |

---

## 3. Recommended Folder Structure

Design constraints from your answers:
- AWS-first, but vendor-neutral patterns where possible
- 5 to 500 clusters — must scale without per-cluster file explosion
- Platform team owns addon versions; developers don't touch versioning
- KRO for abstractions; infrastructure provider is pluggable (ACK, Crossplane, CAPI)
- No CI build; manual review only — structure must be self-documenting
- Ignore team autonomy and path-routing for now

```
gitops/
│
├── bootstrap/                                    # Phase 0: Get ArgoCD running
│   ├── argocd-install.yaml                       # ArgoCD Application to install ArgoCD itself
│   ├── root-appset.yaml                          # Root ApplicationSet → renders addons via appset-chart
│   └── manifests/                                # Raw manifests needed before Helm/ArgoCD is ready
│       ├── argocd/
│       └── external-secrets/
│
├── appset-chart/                                 # The shared Helm chart that generates ApplicationSets
│   ├── Chart.yaml
│   ├── values.yaml                               # Global defaults: syncPolicy, repoURL templates
│   ├── README.md
│   └── templates/
│       ├── _helpers.tpl
│       ├── _application_set.tpl
│       ├── _pod_identity.tpl
│       └── _git_matrix.tpl
│
├── addons/                                       # Phase 1: Addon catalog + configuration
│   │
│   ├── registry/                                 # WHAT to deploy (one file per addon)
│   │   │                                         # Each file: chart source, version, namespace,
│   │   │                                         # selectors, sync-wave, ignoreDifferences
│   │   │
│   │   ├── _defaults.yaml                        # Shared defaults: syncPolicy, retry, valueFiles paths
│   │   │
│   │   ├── core/                                 # Infrastructure foundations
│   │   │   ├── cert-manager.yaml
│   │   │   ├── external-secrets.yaml
│   │   │   ├── external-dns.yaml
│   │   │   ├── ingress-nginx.yaml
│   │   │   └── metrics-server.yaml
│   │   │
│   │   ├── gitops/                               # GitOps & delivery tooling
│   │   │   ├── argocd.yaml
│   │   │   ├── argo-rollouts.yaml
│   │   │   ├── argo-events.yaml
│   │   │   ├── argo-workflows.yaml
│   │   │   ├── kargo.yaml
│   │   │   └── flux.yaml
│   │   │
│   │   ├── security/                             # Policy & identity
│   │   │   ├── keycloak.yaml
│   │   │   ├── kyverno.yaml
│   │   │   ├── kyverno-policies.yaml
│   │   │   └── kyverno-policy-reporter.yaml
│   │   │
│   │   ├── observability/                        # Monitoring & metrics
│   │   │   ├── grafana.yaml
│   │   │   ├── grafana-operator.yaml
│   │   │   ├── grafana-dashboards.yaml
│   │   │   ├── kube-state-metrics.yaml
│   │   │   ├── prometheus-node-exporter.yaml
│   │   │   ├── opentelemetry-operator.yaml
│   │   │   └── cloudwatch-prometheus.yaml
│   │   │
│   │   ├── platform/                             # Platform services
│   │   │   ├── backstage.yaml
│   │   │   ├── crossplane.yaml
│   │   │   ├── kubevela.yaml
│   │   │   └── devlake.yaml
│   │   │
│   │   └── ml/                                   # ML/AI platform
│   │       ├── jupyterhub.yaml
│   │       ├── kubeflow.yaml
│   │       ├── mlflow.yaml
│   │       ├── ray-operator.yaml
│   │       ├── spark-operator.yaml
│   │       └── airflow.yaml
│   │
│   ├── configs/                                  # HOW to configure each addon
│   │   └── <addon-name>/
│   │       ├── values.yaml                       # Default Helm values
│   │       └── manifests/                        # Extra K8s manifests (ExternalSecrets, RBAC, etc.)
│   │
│   └── charts/                                   # Custom wrapper charts (ONLY when upstream chart
│       └── <addon-name>/                         # doesn't suffice — e.g., keycloak, backstage)
│           ├── Chart.yaml
│           └── templates/
│
├── overlays/                                     # Layered overrides
│   │                                             # Precedence: configs/ → environments/ → clusters/
│   │
│   ├── environments/                             # Per-environment addon selection + overrides
│   │   └── <env-name>/                           # e.g., control-plane, staging, production
│   │       ├── enabled-addons.yaml               # Which addons are on/off for this environment
│   │       └── <addon-name>/
│   │           └── values.yaml                   # Environment-specific value overrides
│   │
│   └── clusters/                                 # Per-cluster overrides (use sparingly)
│       └── <cluster-name>/                       # Only for truly unique cluster config
│           └── <addon-name>/
│               └── values.yaml
│
├── abstractions/                                 # KRO ResourceGraphDefinitions
│   │                                             # Platform-level abstractions decoupled from addons
│   │
│   ├── resource-groups/                          # RGD definitions
│   │   ├── appmod-service.yaml                   # Composite: Rollout + Service + Ingress + DynamoDB
│   │   ├── s3-bucket.yaml
│   │   ├── pod-identity.yaml
│   │   └── eks-cluster.yaml
│   │
│   └── providers/                                # Infrastructure provider configs (pluggable)
│       ├── ack/                                  # ACK-specific: IAMRoleSelectors, controller configs
│       │   └── iam-role-selectors.yaml
│       ├── crossplane/                           # Crossplane providers + ProviderConfigs
│       │   ├── providers.yaml
│       │   └── provider-config.yaml
│       └── capi/                                 # Cluster API (future)
│           └── ...
│
├── fleet/                                        # Multi-cluster fleet management
│   ├── bootstrap/
│   │   ├── addons.yaml                           # ApplicationSet: deploy addons to all fleet members
│   │   ├── clusters.yaml                         # ApplicationSet: provision clusters via KRO
│   │   └── fleet-secrets.yaml                    # Matrix generator for fleet member secrets
│   ├── members/                                  # Fleet member definitions
│   │   └── <cluster-name>/
│   │       └── values.yaml                       # Cluster annotations, labels, provider details
│   └── kro-values/                               # KRO instance values for cluster provisioning
│       └── <cluster-name>/
│           └── values.yaml
│
└── apps/                                         # Application workloads (deployed onto clusters)
    └── <app-name>/
```

---

## 4. Design Decisions Explained

### 4.1 Split the monolith into `registry/<domain>/<addon>.yaml`

The 1759-line `addons.yaml` is the single biggest problem. At 500 clusters with manual review, reviewers need to quickly identify what changed. One file per addon means:

- PRs touch exactly the files that matter
- Domain grouping (`core/`, `security/`, `ml/`) makes the catalog scannable without tooling
- Adding a new addon = adding one file, not editing a shared monolith

The appset-chart already supports `ignoreMissingValueFiles: true`, so the `root-appset.yaml` in bootstrap can reference all registry files via a glob-like pattern in `valueFiles`. Alternatively, the appset-chart can be updated to iterate over files in a directory using ArgoCD's git file generator.

### 4.2 Separate `registry/` (what) from `configs/` (how) from `charts/` (custom logic)

Currently appmod-blueprints has three overlapping directories for addon data:
- `bootstrap/default/addons.yaml` — addon definitions (chart source, version, selectors, inline values)
- `default/addons/<name>/values.yaml` — default Helm values
- `charts/<name>/` — wrapper Helm charts

The problem: it's unclear where to look for what. The recommended split:

| Directory | Contains | Who edits | When |
|-----------|----------|-----------|------|
| `registry/<domain>/<addon>.yaml` | Chart source, version, namespace, selectors, sync-wave | Platform team | Adding/upgrading addons |
| `configs/<addon>/values.yaml` | Default Helm values for the addon | Platform team | Tuning addon behavior |
| `configs/<addon>/manifests/` | Extra K8s resources (ExternalSecrets, ClusterSecretStores) | Platform team | Adding sidecar resources |
| `charts/<addon>/` | Custom wrapper chart (only when upstream chart is insufficient) | Platform team | Rare; complex addons only |

This mirrors the Azure repo's clean `packages/<addon>/` pattern but adds the registry layer on top.

### 4.3 Cluster secret annotations over per-cluster files

At 500 clusters, you cannot maintain 500 `values.yaml` files. Both repos already use cluster secret annotations for dynamic values (`aws_region`, `aws_cluster_name`, `ingress_domain_name`, etc.). The recommended structure reinforces this:

- `overlays/clusters/<name>/` exists but should be used sparingly — only for truly unique overrides that can't be expressed as annotations or environment-level config
- Most cluster differentiation happens via labels on the ArgoCD cluster secret (`environment`, `fleet_member`, `enable_<addon>`)
- The appset-chart's `selector.matchExpressions` handles addon-to-cluster targeting

For 500 clusters, consider a naming convention for cluster secrets that encodes environment and region:
```
labels:
  environment: production
  region: us-west-2
  fleet_member: workload
  enable_kyverno: "true"
  enable_grafana: "true"
```

### 4.4 Promote KRO abstractions to a top-level `abstractions/` directory

Currently, KRO ResourceGraphDefinitions are buried in `charts/kro/resource-groups/manifests/`. These are platform-level abstractions that define how developers interact with infrastructure — they're not addon charts. Elevating them to `abstractions/` makes their importance visible and separates concerns:

- `abstractions/resource-groups/` — the KRO RGDs (AppmodService, S3Bucket, etc.)
- `abstractions/providers/` — pluggable infrastructure provider configs (ACK, Crossplane, CAPI)

This also makes the vendor-neutral intent explicit. When you add Crossplane or CAPI support, you add a new directory under `providers/` without touching the RGDs.

### 4.5 Platform team owns versions in the registry

Since developers don't touch addon versions, the `defaultVersion` field lives in `registry/<domain>/<addon>.yaml` and is the single source of truth. Environment overrides in `overlays/environments/<env>/enabled-addons.yaml` can optionally pin a different version for canary testing:

```yaml
# overlays/environments/staging/enabled-addons.yaml
cert-manager:
  enabled: true
  defaultVersion: "v1.16.0"  # Testing newer version in staging
```

But the normal flow is: platform team bumps version in registry → ArgoCD rolls it out to all environments that have the addon enabled.

### 4.6 `enabled-addons.yaml` per environment replaces the two-step enable pattern

Currently, addons are `enabled: false` in `bootstrap/default/addons.yaml` and then `enabled: true` in `environments/control-plane/addons.yaml`. This two-step pattern is error-prone. The recommended approach:

- Registry files define the addon but don't set `enabled` (or default to `false`)
- Each environment has one `enabled-addons.yaml` that explicitly lists what's on

This gives reviewers a single file per environment that answers "what runs here?"

### 4.7 Bootstrap stays minimal and separate

The bootstrap phase installs ArgoCD and the minimum needed for ArgoCD to manage everything else. The `bootstrap/manifests/` directory contains raw YAML (not Helm) because Helm isn't available yet. Once ArgoCD is running, `root-appset.yaml` takes over and renders the full addon catalog via the appset-chart.

---

## 5. Migration Path from Current Structure

For appmod-blueprints, the migration can be incremental:

1. Extract each addon block from `bootstrap/default/addons.yaml` into `registry/<domain>/<addon>.yaml`
2. Move `default/addons/<name>/values.yaml` to `configs/<name>/values.yaml`
3. Move `charts/<name>/` to `addons/charts/<name>/` (only keep charts with real template logic; delete thin wrappers)
4. Move `charts/kro/resource-groups/` to `abstractions/resource-groups/`
5. Rename `environments/control-plane/addons.yaml` to `overlays/environments/control-plane/enabled-addons.yaml`
6. Update `fleet/bootstrap/addons.yaml` valueFiles paths to point to new locations
7. Move `charts/application-sets/` to top-level `appset-chart/`

Each step can be a separate PR. The appset-chart's `ignoreMissingValueFiles: true` means old and new paths can coexist during migration.

---

## 6. Sync-Wave Reference

One thing both repos lack is a central view of deployment ordering. With the per-file registry, include a sync-wave comment at the top of each addon file and maintain this reference:

| Wave | Category | Addons |
|------|----------|--------|
| -5 | Multi-account | multi-acct |
| -3 | Abstractions | kro |
| -2 | KRO Resource Groups | kro-manifests, kro-manifests-hub |
| -1 | Controllers | ACK (iam, eks, ec2, ecr, s3, dynamodb, efs), external-secrets, platform-manifests-bootstrap |
| 0 | Core | argocd, metrics-server, ingress-class-alb |
| 1 | Ingress | ingress-nginx, image-prepuller |
| 2 | Certificates | cert-manager, gitlab |
| 3 | Security & Policy | keycloak, kyverno, kube-state-metrics, prometheus-node-exporter, kubevela, argo-events, opentelemetry |
| 4 | Platform Tools | argo-workflows, kargo, backstage, grafana, grafana-operator, flux, kyverno-policies, kyverno-policy-reporter |
| 5 | ML/AI & Advanced | jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow, crossplane, grafana-dashboards, cni-metrics-helper |
| 6 | Crossplane Providers | crossplane-aws, platform-manifests |
| 7 | Data Platform | devlake |
