# Infrastructure Abstraction — ACK and kro

How the platform turns Kubernetes into the universal control plane for AWS resources (ACK) and composes many resources into one self-service unit (kro).

## ACK — AWS Controllers for Kubernetes

ACK represents AWS resources (S3, DynamoDB, IAM, EC2, ECR, EKS, …) as Kubernetes **Custom Resources**. A controller reconciles each CRD to the actual AWS resource.

**Why ACK in this platform:**
- Kubernetes-native — no separate IaC tool or context switch; same `kubectl`/RBAC/GitOps model as everything else.
- GitOps-friendly — an ACK manifest in Git is reconciled by ArgoCD and provisioned by the controller, with drift detection for free.
- Credential-free — controllers use IRSA/Pod Identity; no AWS keys in the cluster.

**The provisioning golden path:**
```
Backstage template → ACK manifest committed to Git → ArgoCD syncs → ACK controller provisions the AWS resource
```
Example: a developer fills an "S3 bucket" form (name, env, region, namespace, config tier) → a `kind: Bucket` ACK manifest lands in a new repo → ArgoCD applies it → the bucket exists. Verify in ArgoCD (synced/healthy) + the AWS console.

**Conventions:** namespace-scoped resources for multi-tenancy; configuration tiers (platform-defined profiles) so developers choose vetted settings rather than free-typing.

## kro — Kubernetes Resource Orchestrator

kro composes **multiple** resources into a **single** custom API. The platform team defines a `ResourceGraphDefinition`; developers instantiate one CRD and get the whole graph.

**Why kro:** it raises the abstraction from "many manifests" to "one intent." Two platform-defining examples:

- **`CICDPipeline`** — one CRD reconciles into Argo Workflow templates + Argo Events sensor/trigger + ECR repo + dev/prod ArgoCD applications + caches. This is what the app-onboarding Backstage template emits (see `gitops-delivery.md`).
  ```bash
  kubectl get cicdpipelines <app>-cicd-pipeline -n <team-ns>   # STATE=ACTIVE, SYNCED=True
  ```
- **Environment provisioning** — a kro composition creates VPC + EKS Auto Mode cluster + add-ons + ArgoCD registration as one unit (golden path 1). Self-service environments in minutes, not days; each gets its own VPC + cluster for isolation.

## ACK vs kro — they layer, not compete

- **ACK** = the building blocks (individual AWS resources as CRDs).
- **kro** = the composition (bundle ACK CRDs + native K8s objects into one developer-facing API).
- A kro `ResourceGraphDefinition` commonly *contains* ACK resources. The Backstage template is the friendly form over the kro CRD; kro fans out to ACK + native resources; ArgoCD keeps it all reconciled.

## Why not raw Terraform/CloudFormation here

The platform deliberately keeps provisioning in the Kubernetes/GitOps plane so there's one reconciliation model, one RBAC model, and one source of truth. Terraform/CDK still bootstrap the *platform itself* (the hub, initial clusters); ACK/kro handle *day-to-day self-service* on top. (For standalone Terraform module work, that's the `terraform-skill`, not this skill.)
