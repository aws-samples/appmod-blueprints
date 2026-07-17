# Deprecated API Detection

## Purpose
Scan live cluster resources for usage of deprecated or removed Kubernetes APIs that will break during or after the upgrade.

## How to Check

### Step 1: Get EKS Upgrade Insights

Use the EKS Insights API with category `UPGRADE_READINESS` — this is the most reliable source for deprecated API detection as AWS scans the audit logs.

1. Get EKS Insights → filter for UPGRADE_READINESS
2. For any non-PASSING insights → get detailed description
3. Record: insight status, affected resources, recommended action

### Step 2: Scan Live Resources

Run **two scans in parallel** for each resource type. Both are required because
they catch different failure modes.

**Resource types to scan:**
- Deployments, DaemonSets, StatefulSets, ReplicaSets
- CronJobs, Jobs
- Ingresses
- NetworkPolicies
- PodDisruptionBudgets
- HorizontalPodAutoscalers
- CustomResourceDefinitions
- ValidatingWebhookConfigurations, MutatingWebhookConfigurations
- FlowSchemas, PriorityLevelConfigurations

#### Step 2a: Object `apiVersion` scan

For each resource type, list resources and check the live `apiVersion` field
against the deprecation table in Step 3.

#### Step 2b: `managedFields` apiVersion scan

For each resource, inspect every entry in `metadata.managedFields[]` and check
its `apiVersion` against the deprecation table in Step 3. The API server may
auto-convert resources to the storage version, so Step 2a alone misses
manifests originally applied under a deprecated apiVersion. `managedFields`
preserves the apiVersion used by every writer (kubectl, controllers, Argo CD,
Flux, Helm), so this scan covers all configuration sources.

```bash
kubectl get <kind> --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"/"}{.metadata.name}{"\t"}{range .metadata.managedFields[*]}{.manager}{"="}{.apiVersion}{","}{end}{"\n"}{end}'
```

Output is `namespace/name<TAB>manager1=apiVersion1,manager2=apiVersion2,...`.
The `manager` portion identifies which writer used each apiVersion (e.g.,
`kubectl-client-side-apply`, `argocd-application-controller`, controller
names) — this points to where the source manifest needs to be updated.

**Anti-pattern — do not pre-filter with naïve substring greps.**

```bash
# WRONG — `v1` is a prefix of `v1beta3`, so `grep -v` strips both lines.
... | grep -v "flowcontrol.apiserver.k8s.io/v1"
```

A single resource often has multiple `manager=apiVersion` entries on the
same line (e.g., a controller writing `v1` plus the user writing `v1beta3`).
Filter-then-decide pipelines drop the line entirely as soon as any benign
apiVersion matches. Walk the full output line by line and check each
`manager=apiVersion` pair against the deprecation table in Step 3 instead.

**Anti-pattern — do not substitute `-o yaml` or `-o json`.**

```bash
# WRONG — kubectl 1.21+ hides managedFields from -o yaml / -o json by default,
# so this scan returns false negatives.
kubectl get <kind> -A -o yaml | grep apiVersion
```

Use the `-o jsonpath` form above. It accesses `managedFields` directly and
is not affected by the default-hide behavior.

### Step 3: Check for Removed APIs by Target Version

| Target | Removed API | Replacement |
|--------|------------|-------------|
| 1.22 | `networking.k8s.io/v1beta1` Ingress | `networking.k8s.io/v1` |
| 1.22 | `rbac.authorization.k8s.io/v1beta1` | `rbac.authorization.k8s.io/v1` |
| 1.25 | `policy/v1beta1` PodSecurityPolicy | Pod Security Standards |
| 1.25 | `policy/v1beta1` PodDisruptionBudget | `policy/v1` |
| 1.25 | `batch/v1beta1` CronJob | `batch/v1` |
| 1.25 | `discovery.k8s.io/v1beta1` EndpointSlice | `discovery.k8s.io/v1` |
| 1.26 | `autoscaling/v2beta1` HPA | `autoscaling/v2` |
| 1.26 | `flowcontrol.apiserver.k8s.io/v1beta1` | `flowcontrol.apiserver.k8s.io/v1beta3` |
| 1.29 | `flowcontrol.apiserver.k8s.io/v1beta2` | `flowcontrol.apiserver.k8s.io/v1` |
| 1.32 | `flowcontrol.apiserver.k8s.io/v1beta3` | `flowcontrol.apiserver.k8s.io/v1` |

### Step 4: Classify Findings

For each deprecated API found, record the **source** (`object` from Step 2a /
`managedFields` from Step 2b) and severity:

- **Removed in target version** → HIGH severity, action required
- **Deprecated but still available in target** → LOW severity, plan migration
- **Removed in future version** → INFO, awareness only

If a single resource is flagged by both Step 2a and Step 2b, report it once
with `source: object+managedFields`. Counting at the API-path level (not the
resource level) is canonical — see `references/report-generation.md` Category 2.

## Output Format

For each finding, report:
- API version and kind
- Resource name and namespace
- **Source** (`object` / `managedFields` / `object+managedFields`)
- Whether it's removed in the target version or just deprecated
- Specific migration command (e.g., update apiVersion field, re-apply manifests
  with the new apiVersion)

## Score Impact

> **Canonical scoring is defined in `references/report-generation.md` §Category 2 (Deprecated APIs).**

| Finding | Deduction |
|---------|-----------|
| API removed in target version | 5 pts per API path (max 20) |
| API deprecated but available | 1 pt per API path (max 5) |
