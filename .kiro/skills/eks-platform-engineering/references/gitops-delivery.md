# GitOps Delivery — ArgoCD + Argo Workflows

The delivery backbone. Git is the single source of truth; ArgoCD reconciles cluster state to match; Argo Workflows runs the build pipelines that feed it.

## Division of labor

- **Argo Workflows (+ Argo Events)** = CI. Webhook-triggered, container-native pipelines that build images, run tests, push to ECR, and update deployment manifests in Git.
- **ArgoCD** = CD. Watches Git, detects manifest changes, syncs them to the target cluster, reports sync/health, and detects drift.

Keeping CI and CD separate (rather than one monolithic pipeline) means a failed build never half-deploys, and the deployed state is always exactly what's in Git.

## ArgoCD patterns

- **App-of-apps / ApplicationSets** — a bootstrap `Application` points at a Git path of child `Application`s; ApplicationSets template one app per cluster/environment from a generator (e.g. the cluster-registration secrets from the GitOps Bridge). This is how 60+ platform add-ons stay in sync across hub + spokes.
- **Cluster registration** — a new spoke registers with the hub's ArgoCD; ApplicationSets then deploy the full add-on set to it automatically.
- **One ArgoCD Application per deployment target** — e.g. `app-dev-cd` watches `deployment/dev/`, `app-prod-cd` watches `deployment/prod/`. Promotion = changing what's in the prod path (done by Kargo, see `progressive-delivery.md`).
- **SSO** — ArgoCD logs in via Keycloak; no separate credentials.

## The application CI/CD pipeline (golden path 3)

The platform provisions an app's whole pipeline from one Backstage template that emits a kro `CICDPipeline` (see `infrastructure-abstraction.md`). That single CRD reconciles into:

- Argo Workflow templates (build + push to ECR + update manifest)
- Argo Events sensor/trigger (fires the workflow on `git push`)
- ECR repository
- ArgoCD applications for dev and prod (`<app>-dev-cd`, `<app>-prod-cd`)
- build caches

Two workflows typically run: a one-time `*-setup-workflow` (cache warming / provisioning) and the recurring `*-initial-build-workflow` (build → push → update the `image:` field in `deployment/dev/application.yaml`).

## The developer contract for delivery

The developer provides only:
1. A **`Dockerfile`** in the repo (the platform expects nothing else for build — multi-stage builds, static linking, non-root, minimal base images are the recommended convention).
2. The platform's **application manifest** in `deployment/dev/` describing what to run — a kro-rendered custom resource on the default stack, or an **OAM `Application`** if you run the KubeVela abstraction (see `application-model-oam.md`). The examples below use the OAM form.

Then: `git push` → Argo Workflows builds and pushes the image and bumps the manifest → ArgoCD syncs → the app abstraction (kro composition or KubeVela) renders the app + its DynamoDB/IAM/ingress. "Deploying" is just pushing to Git.

## Verifying

- kro pipeline object: `kubectl get cicdpipelines <name> -n <team-ns>` → expect `STATE=ACTIVE, SYNCED=True`.
- ArgoCD app: check Synced/Healthy (UI or `argocd app get <app>`); force with `argocd app sync <app>`.
- Workflow run: Argo Workflows UI shows build progress; `kubectl get pods -n <team-ns> --watch` shows the rollout.
- Allow ~3–5 minutes for ArgoCD to detect a Git change on default sync intervals.
