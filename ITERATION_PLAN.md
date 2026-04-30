# Platform Iteration: Resource Isolation and Operational Improvements

## Parent Issue

**Title:** Improve resource isolation, destroy reliability, and operational tooling

**Description:**
This iteration focuses on completing clusterName-based resource isolation across all platform components and fixing remaining operational issues.

### Already completed (this session):
- clusterName-based prefixing for Crossplane IAM roles/policies
- PostSync restart hook for pod identity credential injection
- Sanitized addonVersion label for branch names with `/`
- Removed SkipHealthCheck (confirmed null health on EKS Capability)
- Centralized hub:kubeconfig task
- Colored task output, hub:wait-for-sync, app generation wait
- Destroy ordering fix (cluster deletion before provider deletion)

---

## Sub-Issues

### 1. Align addon charts to use clusterName instead of resourcePrefix

**Priority:** High
**Labels:** enhancement, breaking-change

All addon charts currently use `global.resourcePrefix` for AWS resource naming. Replace with `global.clusterName` (from `aws_cluster_name` annotation) for natural per-deployment isolation.

**Charts to update:**
- `airflow/templates/external-secret.yaml` — `{resourcePrefix}-hub/keycloak-clients` → `{clusterName}/keycloak-clients`
- `jupyterhub/templates/external-secret.yaml` — same
- `kubeflow/templates/external-secret.yaml` — same
- `mlflow/templates/external-secret.yaml` — same
- `spark-operator/templates/external-secret.yaml` — same
- `image-prepuller/templates/daemonset.yaml` — DaemonSet name
- `platform-manifests/templates/huggingface-models.yaml` — S3 bucket name
- `ray-operator/templates/model-prestage-job.yaml` — Job name
- `multi-acct/templates/configmap.yaml` — cross-account IAM role names
- `multi-acct/templates/iam-role-selectors.yaml` — cross-account IAM role ARNs

**Registry to update:**
- `core.yaml`, `observability.yaml`, `ml.yaml` — change `resource_prefix` to `aws_cluster_name` in valuesObject

**Also update:**
- Addon chart `values.yaml` files — rename `global.resourcePrefix` to `global.clusterName`
- Secrets Manager keycloak key to use `{clusterName}/keycloak-clients` consistently

**Acceptance criteria:**
- All AWS resources created by addons are prefixed with clusterName
- Two platform instances with different clusterNames have zero collisions
- `resourcePrefix` only used for KRO tenant-facing resources

---

### 2. Fix provider DRC mismatch on Kind during destroy/reinstall

**Priority:** High
**Labels:** bug

Per-provider DRCs (ec2-drc, eks-drc, iam-drc) assign custom SAs designed for hub pod identity. On Kind, providers need the `default` DRC. After provider reinstall, providers start but never initialize controllers.

**Also:** Stale CRD ownerReferences — when providers are recreated, the family provider's CRD retains the old revision's UID, blocking the new revision.

**Fix needed:**
- Destroy task should switch providers to `default` DRC before deletion on Kind
- Add CRD ownerReference repair step after provider reinstall
- Consider a `crossplane:repair` task for manual recovery

**Acceptance criteria:**
- `task destroy` completes without stuck providers
- Provider reinstall on Kind works without manual intervention

---

### 3. Fix VPC deletion stuck on DependencyViolation

**Priority:** Medium
**Labels:** bug

After EKS cluster deletion, VPC deletion fails with `DependencyViolation` for 15-20+ minutes due to EKS Auto Mode cleanup lag.

**Proposed fix:**
- Add retry loop with timeout to VPC deletion in destroy task
- Add explicit cleanup of EKS-managed ENIs before VPC deletion

**Acceptance criteria:**
- Destroy task handles VPC deletion delay gracefully
- No manual AWS Console intervention needed

---

### 4. KRO resource groups — align naming with clusterName or appName

**Priority:** Medium
**Labels:** enhancement

KRO ResourceGroups use `resourcePrefix` for ECR repos, S3 buckets, IAM roles, capability roles.

**Decision needed:** Use `appName` only, `clusterName-appName`, or keep `resourcePrefix`.

**Files:**
- `kro/resource-groups/manifests/cicd-pipeline/cicd-pipeline.yaml`
- `kro/resource-groups/manifests/ray-service/ray-service.yaml`
- `kro/resource-groups/manifests/eks/rg-eks.yaml`
- `kro/resource-groups/manifests/eks/rg-eks-vpc.yaml`

---

### 5. Spoke cluster end-to-end validation

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

### 6. Remove resourcePrefix from config.yaml

**Priority:** Low
**Labels:** cleanup
**Blocked by:** #1, #4

Once all resources use `clusterName` and KRO resources are aligned, remove `resourcePrefix` from `config.yaml`.
