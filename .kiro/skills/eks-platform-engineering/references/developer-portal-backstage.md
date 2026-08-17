# Developer Portal — Backstage

Backstage is the platform's front door: a self-service catalog plus software templates (the "scaffolder"). Developers interact with the platform here and rarely touch raw Kubernetes or AWS.

## Why Backstage

- Open-source, CNCF, plugin-based — extensible without forking.
- Software Templates encode golden paths with parameters and guardrails.
- Service Catalog gives a single pane of glass (components, APIs, docs, owners).
- Integrates with Keycloak SSO so it shares identity with every other tool.

## Anatomy of a software template

A Backstage template is a folder:

```
my-template/
├── template.yaml          # definition: parameters + steps (actions)
└── skeleton/              # scaffolded files, rendered with parameter values
    ├── catalog-info.yaml  # registers the new component in the catalog
    └── manifests/         # e.g. an OAM Application or ACK manifest
```

- **`template.yaml`** declares the form parameters the developer fills, then the ordered **steps/actions**: fetch skeleton → publish to Git → register in ArgoCD/catalog → trigger provisioning.
- **`skeleton/`** is the payload: the manifests and `catalog-info.yaml` that get committed to a new Git repo, rendered with the developer's parameter values.

## The self-service flow (every template follows this shape)

```
Developer fills Backstage form
   → template creates a new GitLab repo with rendered skeleton (manifests)
   → registers the repo/app with ArgoCD (and the catalog)
   → ArgoCD syncs the manifests to the target cluster
   → controllers reconcile (KubeVela renders the app; ACK provisions AWS resources)
```

This is the same loop whether the artifact is an AWS resource (ACK manifest), an environment (kro composition), a CI/CD pipeline (kro `CICDPipeline`), or an ML serving endpoint (Ray Serve manifest). One repo per provisioned component is the default — it keeps GitOps reconciliation and ownership clean.

## Opinionated template conventions

- **Guardrails via fixed parameters / configuration tiers.** Pre-define profiles (e.g. an S3 "standard" config) so developers pick a vetted option rather than free-typing settings.
- **Namespace + region as parameters** with sensible defaults (e.g. `us-west-2`, team namespace).
- **Templates reference cluster-side definitions.** A template emits an OAM `Application` that references a `type` (e.g. `ddb-table`) whose component definition the platform team owns — the template is just the friendly form over it.
- **Register via `catalog-info.yaml`** so the new component appears in the catalog with its owner, links (source repo, ArgoCD app, dashboards), and docs.

## Catalog as the operational hub

Once registered, a component's catalog page links its source repo, its ArgoCD application (sync/health), its dashboards, and (for ML/data) execution details (Spark runs, Argo Workflow pipelines). This gives developers troubleshooting visibility without cluster access — directly answering the "fixing problems" adoption challenge.

## Generating templates with GenAI

**Kiro** (AWS's spec-driven agentic tool, the successor to Amazon Q Developer) can scaffold a whole new template from an existing one (e.g. "use the S3 template to make a DynamoDB template"). Pattern: point the agent at a reference template + the target resource's CRD/composition schema, generate, then `diff` against a validated version before registering. See `genai-platform-engineering.md`.
