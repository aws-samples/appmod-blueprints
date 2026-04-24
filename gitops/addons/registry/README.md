# Addon Registry

Structured catalog of all addon definitions. The appset-chart iterates over these entries to generate one ArgoCD ApplicationSet per addon.

## File Organization

Addons are grouped by domain:

| File | Domain | Examples |
|------|--------|----------|
| `_defaults.yaml` | Shared defaults inherited by all addons | syncPolicy, repo URLs, valueFiles |
| `core.yaml` | Core infrastructure | argocd, cert-manager, external-secrets, ingress, metrics-server |
| `gitops.yaml` | GitOps tooling | argo-workflows, argo-rollouts, argo-events, kargo, flux |
| `security.yaml` | Security and policy | keycloak, kyverno, kyverno-policies |
| `observability.yaml` | Monitoring and logging | grafana, opentelemetry-operator, kube-state-metrics, fluentbit |
| `platform.yaml` | Platform infrastructure | crossplane, kro, backstage, ACK controllers, devlake |
| `ml.yaml` | Machine learning / AI | jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow |

## _defaults.yaml

Provides values inherited by every addon unless overridden:

- `syncPolicy` -- automated sync with retry backoff, CreateNamespace, ServerSideApply
- `syncPolicyAppSet` -- preserveResourcesOnDeletion
- `repoURLGit` / `repoURLGitRevision` / `repoURLGitBasePath` -- git source coordinates (templated from cluster secret annotations)
- `overlayBasePath` -- base path for environment/cluster overlay value files
- `valueFiles` -- default list of value file names (`values.yaml`)
- `useSelectors` -- enables label-based cluster targeting (default `true`)

## Addon Entry Format

Each top-level key is the addon name. Required fields:

```yaml
my-addon:
  namespace: my-addon                    # Target namespace (required, serves as iteration key)
  annotationsAppSet:
    argocd.argoproj.io/sync-wave: '3'    # Deploy ordering
  selector:                              # Which clusters get this addon
    matchExpressions:
      - key: enable_my_addon
        operator: In
        values: ['true']
```

### Helm Chart Addons (upstream chart)

```yaml
  chartName: my-addon                    # Helm chart name
  chartRepository: https://example.com/charts  # Helm repo URL
  defaultVersion: '1.2.3'               # Chart version
  releaseName: my-addon                  # Optional, defaults to chartName
```

For OCI registries, add `chartNamespace`:

```yaml
  chartName: kro
  chartNamespace: kro/charts             # OCI path segment
  chartRepository: registry.k8s.io       # OCI registry
  defaultVersion: '0.6.1'
```

### Git Path Addons (custom chart or manifests)

```yaml
  path: '{{.metadata.annotations.addonsRepoBasepath}}addons/charts/my-addon'
```

### Manifest-Only Addons

```yaml
  type: manifest
  path: '{{.metadata.annotations.addonsRepoBasepath}}addons/configs/crossplane/manifests'
```

When `type: manifest` is set, the Helm rendering block is skipped entirely -- ArgoCD applies the directory contents as raw manifests.

## Optional Fields

| Field | Purpose |
|-------|---------|
| `valuesObject` | Inline Helm values with Go template expressions for cluster annotations |
| `ignoreDifferences` | ArgoCD diff customization (ignore status, managedFields, etc.) |
| `additionalResources` | Extra sources (manifests, charts) deployed alongside the main chart |
| `enableAckPodIdentity` | Enables ACK pod identity sidecar source |
| `directory` | Directory options for manifest-type addons (recurse, exclude) |
| `selectorMatchLabels` | Additional static label selectors beyond the enable_* label |
| `environments` | Per-environment version overrides using merge generators |
| `syncPolicy` | Per-addon override of the default syncPolicy |

## Sync-Wave Reference

| Wave | Category | Addons |
|------|----------|--------|
| -5 | Multi-account | multi-acct |
| -3 | Abstractions | kro |
| -2 | KRO Resource Groups | kro-manifests, kro-manifests-hub |
| -1 | Controllers | external-secrets, crossplane-pod-identity, ACK controllers (iam, eks, ec2, ecr, s3, dynamodb, efs) |
| 0 | Core | argocd, metrics-server |
| 1 | Ingress | ingress-class-alb |
| 2 | Certificates | cert-manager |
| 3 | Security / Observability | kyverno, argo-rollouts, argo-events, grafana-operator, kube-state-metrics, otel, cni-metrics-helper, aws-for-fluentbit |
| 4 | Platform / GitOps | lbc, efs-csi, grafana, kyverno-policies, kyverno-policy-reporter, kargo, flux, crossplane-aws |
| 5 | ML/AI / Dashboards | jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow, grafana-dashboards, cw-prometheus |
| 6 | Security (late) | keycloak |
| 7 | GitOps (late) | argo-workflows |

## How to Add a New Addon Entry

1. Choose the domain file that best fits (or create a new one).
2. Add a YAML block with at minimum: `namespace`, `selector`, `annotationsAppSet`, and a chart source (`chartRepository` + `defaultVersion`) or `path`.
3. Pick a sync-wave that respects dependency ordering -- addons that depend on others must use a higher wave number.
4. Use the naming convention `enable_<addon_name>` for the selector key, with underscores replacing hyphens.
5. Add `valuesObject` if the addon needs cluster-specific values injected from annotations.
