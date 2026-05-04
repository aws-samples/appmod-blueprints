# Platform Iteration: Operational Improvements and Addon Enablement

## Parent Issue

**Title:** Platform operational improvements, addon enablement, and extensibility

**Description:**
This iteration covers hardcoded value cleanup, addon verification, new cluster providers, and future extensibility.

---

## Sub-Issues

### 1. Remove hardcoded static values from addon charts

**Priority:** High
**Labels:** bug, cleanup

Several addon charts contain hardcoded values (`peeks`, `us-west-2`, `system-peeks`) that should be parameterized via `global.clusterName`, `global.region`, or chart values.

**Hardcoded values found:**

| File | Value | Fix |
|------|-------|-----|
| `devlake/templates/external-secret.yaml` | `peeks-devlake/mysql-connection` | Use `{{ .Values.global.clusterName }}-devlake/mysql-connection` |
| `grafana-dashboards/templates/external-secret.yaml` | `peeks-devlake/mysql-connection` | Same |
| `backstage/templates/install.yaml` | `karpenter.sh/nodepool: system-peeks` | Use `{{ .Values.global.clusterName }}` or make configurable |
| `platform-manifests/templates/huggingface-models.yaml` | `default "peeks"`, `default "peeks-hub"` | Already uses `global.clusterName` with fallback — remove hardcoded defaults |
| `platform-manifests/templates/ray-system-iamroleselectors.yaml` | `peeks-cluster-mgmt-iam`, `peeks-cluster-mgmt-eks` | Use `{{ .Values.global.clusterName }}-cluster-mgmt-*` |
| `ray-operator/templates/model-prestage-job.yaml` | `peeks-ray-models` | Use `{{ .Values.modelPrestage.s3Bucket }}` with `clusterName`-based default |
| `kro/resource-groups/manifests/appmod-service.yaml` | `peeks-cluster-mgmt-*`, `peeks/platform/amp` | Parameterize via schema `resourcePrefix` or `clusterName` |
| `kro/resource-groups/manifests/ray-service/ray-service.yaml` | `peeks-ray-models`, `us-west-2` | Use schema fields |
| `kro/resource-groups/manifests/eks/rg-eks-vpc.yaml` | `default="us-west-2"`, `default="peeks"` | Acceptable as schema defaults, but document |
| `grafana/templates/datasources.yaml` | `default "us-west-2"` | Use `{{ .Values.aws.region }}` without hardcoded default |
| `keycloak/templates/keycloak-config.yaml` | `s3.us-west-2.amazonaws.com`, kubectl 1.32.0 | Parameterize region, pin kubectl version via values |
| `addons/configs/image-prepuller/values.yaml` | `general-purpose-peeks` | Use `general-purpose-{{ clusterName }}` or make configurable |

**Acceptance criteria:**
- No `peeks` string in any template outside KRO schema defaults
- No hardcoded `us-west-2` in templates (use chart values with fallback)
- All nodepool references are parameterized

---

### 2. Enable and verify core addons (core.yaml)

**Priority:** High
**Labels:** testing, addons

Verify each addon in `core.yaml` deploys correctly and reaches Healthy/Synced:
- argocd
- metrics-server
- cert-manager
- external-secrets
- ingress-class-alb
- aws-load-balancer-controller (with pod identity via additionalResources)
- image-prepuller
- aws-efs-csi-driver
- external-dns (with pod identity via additionalResources)

**Test:** Enable all in `enabled-addons.yaml`, run `task install`, verify all apps Healthy/Synced.

---

### 3. Enable and verify gitops addons (gitops.yaml)

**Priority:** Medium
**Labels:** testing, addons

- argo-rollouts
- argo-events
- argo-workflows
- kargo
- flux

---

### 4. Enable and verify security addons (security.yaml)

**Priority:** Medium
**Labels:** testing, addons

- keycloak
- kyverno
- kyverno-policies
- kyverno-policy-reporter

---

### 5. Enable and verify observability addons (observability.yaml)

**Priority:** Medium
**Labels:** testing, addons

- grafana + grafana-operator
- grafana-dashboards
- kube-state-metrics
- prometheus-node-exporter
- opentelemetry-operator
- cw-prometheus
- aws-for-fluentbit
- cni-metrics-helper

---

### 6. Enable and verify platform addons (platform.yaml)

**Priority:** Medium
**Labels:** testing, addons

- crossplane + crossplane-base + crossplane-aws
- backstage
- kro + kro-manifests
- multi-acct
- kubevela
- devlake
- gitlab
- ACK controllers (iam, eks, ec2, ecr, s3, dynamodb, efs)
- platform-manifests

---

### 7. Enable and verify ML/AI addons (ml.yaml)

**Priority:** Medium
**Labels:** testing, addons

- jupyterhub
- kubeflow
- mlflow
- ray-operator
- spark-operator
- airflow

---

### 8. Add Terraform cluster provider

**Priority:** Medium
**Labels:** enhancement, new-provider

Add `cluster-providers/terraform/` as an alternative to kind-crossplane. Should follow the same bootstrap contract:
- Produce an EKS cluster with ArgoCD running
- Create cluster secret with correct labels/annotations
- Apply `bootstrap/root-appset.yaml`
- Support `task install`, `task destroy`, `task status`

Standardize the provider contract in `cluster-providers/README.md` so new providers are plug-and-play.

---

### 9. Standardize root Taskfile bootstrap contract

**Priority:** Medium
**Labels:** enhancement, dx

The root Taskfile delegates to providers but each provider implements tasks differently. Standardize:
- Required tasks: `install`, `destroy`, `status`, `validate`, `hub:update`, `hub:destroy-addons`
- Required vars: `CONFIG_FILE` (passed from root), `HUB_CLUSTER_NAME`, `AWS_REGION`
- Required outputs: Kind/EKS kubeconfig in `private/`, hub-kubeconfig in `private/`
- Document the contract in `cluster-providers/README.md`

---

### 10. Remove ArgoCD capability create/delete Job when Crossplane supports it

**Priority:** Low
**Labels:** enhancement, tech-debt
**Ref:** https://github.com/crossplane-contrib/provider-upjet-aws/pull/2015

The `create-capability.yaml` and `delete-capability.yaml` Jobs use AWS CLI to manage the EKS ArgoCD Capability because Crossplane's EKS provider doesn't support it yet. Once `provider-upjet-aws` adds `EKSCapability` support:
- Replace Jobs with Crossplane managed resources
- Remove `manifests/argocd/create-capability.yaml` and `delete-capability.yaml`
- Remove `argocd:capability` and `argocd:delete-capability` tasks
- Add capability to the PlatformCluster composition or as a separate claim

---

### 11. Agentic AI addons

**Priority:** Medium
**Labels:** enhancement, addons, ai

Add addon registry entries and charts for agentic AI workloads:
- Amazon Bedrock Agent runtime integration
- LangChain/LangGraph operator
- Vector database (pgvector, Milvus, or Weaviate)
- Model serving infrastructure (vLLM, TGI)
- Agent orchestration (CrewAI, AutoGen)
- Evaluation and observability (LangSmith, Phoenix)

Define as a new registry file `ai.yaml` or extend `ml.yaml`.

---

### 12. Create dedicated EKS Auto Mode nodepools for addons

**Priority:** Medium
**Labels:** enhancement, infrastructure

EKS Auto Mode uses a default nodepool for all workloads. Create dedicated nodepools for platform addons to:
- Isolate platform workloads from application workloads
- Set resource limits and instance types per addon category
- Support GPU nodepools for ML/AI addons
- Allow cost attribution per nodepool

Implementation:
- Add nodepool definitions to the PlatformCluster composition or as separate Crossplane resources
- Configure addon charts to use `nodeSelector` or `nodeAffinity` targeting the dedicated nodepool
- Parameterize nodepool name via `global.clusterName` (e.g., `system-{clusterName}`)

---

### 13. KRO resource groups — align naming with clusterName or appName

**Priority:** Medium
**Labels:** enhancement

KRO ResourceGroups use `resourcePrefix` for ECR repos, S3 buckets, IAM roles, capability roles. Align with the clusterName-based naming convention used by infrastructure resources.

**Files:**
- `kro/resource-groups/manifests/cicd-pipeline/cicd-pipeline.yaml`
- `kro/resource-groups/manifests/ray-service/ray-service.yaml`
- `kro/resource-groups/manifests/eks/rg-eks.yaml`
- `kro/resource-groups/manifests/eks/rg-eks-vpc.yaml`
- `kro/resource-groups/manifests/appmod-service.yaml`

---

### 14. Spoke cluster end-to-end validation

**Priority:** Medium
**Labels:** testing

Validate the full spoke lifecycle:
- PlatformCluster composition creates EKS cluster
- Secrets Manager seeding
- Fleet member registration
- Addon deployment including pod identities via additionalResources
- PostSync restart hook on spoke
- Destroy/cleanup

---

### 15. Remove resourcePrefix from config.yaml

**Priority:** Low
**Labels:** cleanup
**Blocked by:** #1, #13

Once all resources use `clusterName` and KRO resources are aligned, remove `resourcePrefix` from `config.yaml` and schema. Only remains in KRO ResourceGroup schemas if they keep using it.

---

### 16. Create PlatformCluster abstraction using KRO + ACK

**Priority:** Medium
**Labels:** enhancement, infrastructure

Create an alternative PlatformCluster implementation using KRO ResourceGroups and ACK controllers instead of Crossplane. The existing `kro/resource-groups/manifests/eks/` already has `rg-eks.yaml` and `rg-eks-vpc.yaml` as a starting point.

**Scope:**
- VPC + subnets + NAT + IGW + route tables (ACK EC2 controller)
- EKS cluster with Auto Mode (ACK EKS controller)
- IAM roles for cluster and nodes (ACK IAM controller)
- Conditional managed node group support
- ArgoCD Capability creation (if ACK EKS supports it, otherwise keep Job)
- Pod identity associations for providers

**Advantages over Crossplane:**
- AWS-native controllers (first-party, no Upbound dependency)
- Simpler orchestration (KRO ResourceGroups vs Crossplane Compositions + pipeline functions)
- No provider DRC/CRD ownership issues
- ACK uses Pod Identity natively

**Challenges to investigate:**
- ACK EKS controller support for Auto Mode and ArgoCD Capability
- KRO maturity for complex multi-resource orchestration
- VPC networking dependency ordering in KRO
- Migration path for existing Crossplane-provisioned clusters

---

### 17. Pluggable composition backends (Crossplane vs KRO+ACK)

**Priority:** Low
**Labels:** enhancement, architecture
**Blocked by:** #16

Allow users to choose between Crossplane and KRO+ACK for infrastructure provisioning, similar to how `cluster-providers/` offers pluggable bootstrap approaches.

**Design:**
- `abstractions/resource-groups/platform-cluster/` becomes the Crossplane backend
- `abstractions/resource-groups/platform-cluster-kro/` becomes the KRO+ACK backend
- `config.local.yaml` gets a `compositionBackend: crossplane | kro` field
- Bootstrap Taskfile selects the correct abstraction based on config
- Both backends produce the same outputs (EKS cluster, VPC, IAM roles)
- `bootstrap/clusters.yaml` ApplicationSet works with either backend

**Acceptance criteria:**
- Both backends can provision and destroy a hub cluster
- Spoke provisioning works with either backend
- Switching backends on a new install requires only a config change
