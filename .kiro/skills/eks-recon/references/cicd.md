# Module: CI/CD

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect CI/CD pipelines and GitOps tools - GitHub Actions, GitLab CI, Jenkins, ArgoCD, Flux

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [Workspace CI/CD](#workspace-cicd)
  - [In-Cluster GitOps](#in-cluster-gitops)
- [Output Schema](#output-schema)
- [Integration Patterns](#integration-patterns)
- [Edge Cases](#edge-cases)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Partial (only for in-cluster GitOps detection)
- **MCP tools used:** `list_k8s_resources` (for GitOps)
- **CLI fallback:** `find`, `kubectl`

---

## Detection Strategy

CI/CD detection has two parts:

1. **Workspace scan** - Find CI/CD config files in local filesystem
2. **In-cluster scan** - Detect GitOps controllers running in the cluster

```
Workspace:
- GitHub Actions  -> .github/workflows/*.yml
- GitLab CI       -> .gitlab-ci.yml
- Jenkins         -> Jenkinsfile
- CircleCI        -> .circleci/config.yml
- AWS CodePipeline -> buildspec.yml, pipeline.json

In-Cluster:
- ArgoCD          -> Deployment in argocd namespace
- Flux            -> Deployment in flux-system namespace
```

---

## Detection Commands

### Workspace CI/CD

#### GitHub Actions

**Why detect GitHub Actions:** GitHub Actions is the most common CI/CD for projects hosted on GitHub. Finding EKS-related workflows reveals how deployments happen and what credentials/roles are used.

```bash
# Find GitHub Actions workflows
find . -path "./.github/workflows/*.yml" -o -path "./.github/workflows/*.yaml" 2>/dev/null | head -10
```

**Example output:**
```
./.github/workflows/ci.yml
./.github/workflows/deploy-staging.yml
./.github/workflows/deploy-prod.yml
```

**If found, check for EKS-related jobs** to identify deployment workflows:
```bash
grep -l "aws-actions/configure-aws-credentials\|kubectl\|helm\|eks" \
  .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null | head -5
```

**Example output:**
```
./.github/workflows/deploy-staging.yml
./.github/workflows/deploy-prod.yml
```

#### GitLab CI

**Why detect GitLab CI:** For projects on GitLab, this is the native CI/CD. Finding EKS references helps understand deployment pipelines and AWS integration.

```bash
# Find GitLab CI config
find . -name ".gitlab-ci.yml" -type f 2>/dev/null | head -3
```

**Example output:**
```
./.gitlab-ci.yml
```

**If found, check for EKS-related stages** to confirm Kubernetes deployments:
```bash
grep -l "kubectl\|helm\|aws eks\|eksctl" .gitlab-ci.yml 2>/dev/null
```

#### Jenkins

**Why detect Jenkins:** Jenkins remains common in enterprise environments. Pipeline libraries in `vars/` indicate shared deployment logic across teams.

```bash
# Find Jenkinsfile
find . -name "Jenkinsfile" -type f 2>/dev/null | head -5
```

**Example output:**
```
./Jenkinsfile
./pipelines/Jenkinsfile.deploy
```

**Check for pipeline libraries** that may contain shared EKS deployment steps:
```bash
find . -path "*/vars/*.groovy" -type f 2>/dev/null | head -5
```

**Example output:**
```
./vars/deployToEKS.groovy
./vars/helmDeploy.groovy
```

#### CircleCI

**Why detect CircleCI:** Popular cloud CI service with orbs for EKS deployments. Config structure differs from GitHub Actions.

```bash
# Find CircleCI config
find . -path "./.circleci/config.yml" -type f 2>/dev/null
```

**Example output:**
```
./.circleci/config.yml
```

#### AWS CodePipeline/CodeBuild

**Why detect CodePipeline/CodeBuild:** Native AWS CI/CD that integrates directly with IAM roles. Often used with EKS for seamless AWS permissions.

```bash
# Find buildspec files
find . -name "buildspec*.yml" -o -name "buildspec*.yaml" 2>/dev/null | head -5
```

**Example output:**
```
./buildspec.yml
./buildspec-deploy.yml
```

```bash
# Find pipeline definitions
find . -name "pipeline*.json" -o -name "codepipeline*.json" 2>/dev/null | head -3
```

**Example output:**
```
./infra/codepipeline.json
```

---

### In-Cluster GitOps

#### ArgoCD Detection

**Why detect ArgoCD:** ArgoCD is the most popular GitOps tool for Kubernetes. Understanding ArgoCD setup helps coordinate cluster upgrades with application deployments and reveals the GitOps repository structure.

**MCP (check for deployment):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="argocd"
)
```

**MCP (check for Applications CRD):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Application",
  api_version="argoproj.io/v1alpha1"
)
```

**CLI:**
```bash
# Check for ArgoCD namespace and deployments
kubectl get deploy -n argocd 2>/dev/null
```

**Example output:**
```
NAME                               READY   UP-TO-DATE   AVAILABLE   AGE
argocd-applicationset-controller   1/1     1            1           45d
argocd-dex-server                  1/1     1            1           45d
argocd-notifications-controller    1/1     1            1           45d
argocd-redis                       1/1     1            1           45d
argocd-repo-server                 1/1     1            1           45d
argocd-server                      1/1     1            1           45d
```

```bash
# Check for Applications
kubectl get applications.argoproj.io -A 2>/dev/null | head -10
```

**Example output:**
```
NAMESPACE   NAME              SYNC STATUS   HEALTH STATUS
argocd      platform-addons   Synced        Healthy
argocd      app-frontend      Synced        Healthy
argocd      app-backend       Synced        Progressing
```

```bash
# Get ArgoCD version
kubectl get deploy -n argocd argocd-server -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null
```

**Example output:**
```
quay.io/argoproj/argocd:v2.10.5
```

**EKS Managed ArgoCD (Capability):** Check if using EKS ArgoCD Capability (AWS-managed) vs self-managed:
```bash
# Check if ArgoCD is EKS-managed
kubectl get deploy -n argocd -o json 2>/dev/null | \
  jq -r '.items[].metadata.labels["eks.amazonaws.com/component"]' 2>/dev/null
```

**Example output (EKS-managed):**
```
argocd
```

#### Flux Detection

**Why detect Flux:** Flux is the CNCF GitOps tool, often preferred for multi-cluster setups. Understanding Flux configuration helps coordinate upgrades with GitRepository and Kustomization reconciliation cycles.

**MCP (check for deployment):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Deployment",
  api_version="apps/v1",
  namespace="flux-system"
)
```

**MCP (check for Kustomizations):**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="Kustomization",
  api_version="kustomize.toolkit.fluxcd.io/v1"
)
```

**CLI:**
```bash
# Check for Flux namespace and deployments
kubectl get deploy -n flux-system 2>/dev/null
```

**Example output:**
```
NAME                          READY   UP-TO-DATE   AVAILABLE   AGE
helm-controller               1/1     1            1           90d
kustomize-controller          1/1     1            1           90d
notification-controller       1/1     1            1           90d
source-controller             1/1     1            1           90d
```

```bash
# Check for GitRepositories
kubectl get gitrepositories.source.toolkit.fluxcd.io -A 2>/dev/null | head -10
```

**Example output:**
```
NAMESPACE     NAME          URL                                       AGE    READY
flux-system   flux-system   ssh://git@github.com/org/gitops-repo      90d    True
flux-system   app-repo      ssh://git@github.com/org/app-manifests    45d    True
```

```bash
# Check for Kustomizations
kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A 2>/dev/null | head -10
```

**Example output:**
```
NAMESPACE     NAME          AGE   READY   STATUS
flux-system   flux-system   90d   True    Applied revision: main@sha1:abc123
flux-system   apps          90d   True    Applied revision: main@sha1:def456
```

```bash
# Get Flux version
flux version --client 2>/dev/null || \
  kubectl get deploy -n flux-system source-controller -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null
```

**Example output:**
```
ghcr.io/fluxcd/source-controller:v1.2.4
```

---

## Output Schema

```yaml
cicd:
  workspace:
    detected: list      # List of tools found in workspace
    details:
      github_actions:
        detected: bool
        workflows: list   # Paths to workflow files
        eks_related: bool # Contains EKS/kubectl/helm references
        
      gitlab_ci:
        detected: bool
        config_path: string
        
      jenkins:
        detected: bool
        jenkinsfile_path: string
        
      circleci:
        detected: bool
        config_path: string
        
      codepipeline:
        detected: bool
        buildspec_paths: list
        
  gitops:
    tool: string        # ArgoCD | Flux | none
    detected: bool
    
    argocd:
      detected: bool
      namespace: string
      version: string
      eks_managed: bool   # EKS ArgoCD Capability
      applications: int   # Count of Application resources
      
    flux:
      detected: bool
      namespace: string
      version: string
      gitrepositories: int
      kustomizations: int
```

---

## Integration Patterns

### GitOps Bridge (Terraform + ArgoCD)

**Why this matters:** The GitOps Bridge pattern uses Terraform to bootstrap ArgoCD, then ArgoCD manages all applications. Understanding this pattern is critical because cluster changes may require coordinating Terraform applies with ArgoCD sync.

If both Terraform and ArgoCD detected:
```bash
# Check for gitops-bridge pattern
grep -r "gitops_bridge\|argocd_bootstrap" --include="*.tf" . 2>/dev/null | head -3
```

**Example output:**
```
./main.tf:module "gitops_bridge" {
./main.tf:  source = "gitops-bridge-dev/gitops-bridge/helm"
```

### App of Apps

**Why this matters:** App of Apps is a common ArgoCD pattern where one Application manages other Applications. Identify this to understand the deployment hierarchy and find the root Application that controls others.

If ArgoCD detected:
```bash
# Check for App of Apps pattern
kubectl get applications.argoproj.io -A -o json 2>/dev/null | \
  jq -r '.items[] | select(.spec.source.path | contains("apps") or contains("applications")) | .metadata.name' | head -5
```

**Example output:**
```
root-apps
platform-apps
```

### ApplicationSets

**Why this matters:** ApplicationSets generate multiple Applications from templates. Understanding ApplicationSet usage reveals how multi-cluster or multi-environment deployments work.

```bash
# Check for ApplicationSets
kubectl get applicationsets.argoproj.io -A 2>/dev/null | head -10
```

**Example output:**
```
NAMESPACE   NAME               AGE
argocd      cluster-addons     45d
argocd      workload-apps      30d
```

---

## Edge Cases

### Multiple CI/CD Tools

Common to have multiple tools:
- GitHub Actions for CI (build/test)
- ArgoCD for CD (deploy to cluster)

Report all detected tools, note integration pattern.

### CI/CD in Different Repo

Application repo may be separate from infra repo:
- Note scan is workspace-limited
- GitOps tools in cluster indicate deployment mechanism

### Atlantis (Terraform CI/CD)

**Why detect Atlantis:** Atlantis automates Terraform via pull request comments. If found, infrastructure changes flow through PR approvals.

```bash
# Check for Atlantis config
find . -name "atlantis.yaml" -type f 2>/dev/null
```

**Example output:**
```
./atlantis.yaml
```

### Tekton Pipelines

**Why detect Tekton:** Tekton is a Kubernetes-native CI/CD framework. Pipelines run as pods in the cluster itself.

```bash
# Check for Tekton
kubectl get pipelines.tekton.dev -A 2>/dev/null | head -5
```

**Example output:**
```
NAMESPACE   NAME              AGE
tekton      build-pipeline    60d
tekton      deploy-pipeline   60d
```

```bash
kubectl get pipelineruns.tekton.dev -A 2>/dev/null | head -5
```

### Spinnaker

**Why detect Spinnaker:** Enterprise deployment platform with advanced deployment strategies (canary, blue-green). Often used in large organizations.

```bash
# Check for Spinnaker
kubectl get deploy -n spinnaker 2>/dev/null
```

**Example output:**
```
NAME                READY   UP-TO-DATE   AVAILABLE   AGE
spin-clouddriver    1/1     1            1           120d
spin-deck           1/1     1            1           120d
spin-gate           1/1     1            1           120d
spin-orca           1/1     1            1           120d
```

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| No CI/CD detected | Suggest setting up GitHub Actions or ArgoCD |
| CI only, no CD | Consider ArgoCD for GitOps deployment |
| ArgoCD detected | Use ArgoCD for add-on management during upgrades |
| Flux detected | Coordinate upgrades with Flux reconciliation |
| Multiple tools | Document integration points |
