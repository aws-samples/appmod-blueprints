# Application Model — the developer-facing app abstraction

The abstraction that lets developers describe an application — and its infrastructure dependencies — in one declarative file, without writing Deployments, Services, Ingresses, IAM, or ACK manifests directly.

## Choosing the abstraction (read first)

There are two supported ways to provide this layer; pick one and standardize on it.

- **Default — Backstage software templates + kro.** A Backstage template gathers parameters; a platform-authored kro `ResourceGraphDefinition` composes the workload and its dependencies into one custom resource. This keeps the platform on a **single composition engine** — the same kro used for environment and resource provisioning — which is the main reason it's the default. (kro is pre-1.0 / `v1alpha1` as of June 2026; see the maturity note in `SKILL.md`.)
- **Alternative — OAM / KubeVela** (this document). A richer, application-centric model (Components + Traits, authored in CUE) and a **fully supported** choice. Prefer it when you specifically want the OAM `Application` abstraction and its trait system.

> **Project-status note (verify before standardizing).** KubeVela is a **CNCF Incubating** project and is **not archived** — it shipped v1.10.8 (March 2026) with a v1.11 alpha in progress. However, its commit and release velocity has slowed, and the **Open Application Model spec itself has been largely dormant** (the `oam-dev/spec` repo's last release was v0.3.0 in 2021). This doesn't make KubeVela a wrong choice, but it does mean you should check current project health (commit cadence, maintainer activity, the CNCF/LFX Insights dashboard) before betting a platform on it — and it's why this skill defaults to Backstage + kro. The OAM concepts below remain a clear way to *think about* the application abstraction regardless of which engine renders it.

The rest of this document describes the OAM/KubeVela model in detail.

## OAM concepts

- **Component** — a runnable unit of work (a web service, a worker, or even a resource like a DynamoDB table).
- **Trait** — an operational feature attached to a component (ingress, autoscaling, an IAM policy, monitoring).
- **Application** — the developer-facing CRD that composes components + their traits.

KubeVela implements OAM on Kubernetes. Developers write `kind: Application`; KubeVela renders it into the underlying Kubernetes (and, via custom components, AWS) resources.

## Separation of concerns

- **Platform engineers** author component and trait **definitions** (in CUE) — type-safe, composable templates. They own the "how."
- **Developers** reference a component/trait by `type` and set its parameters. They own the "what." They never see the rendered Deployment/Service.

A minimal app:
```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: first-app
spec:
  components:
    - name: express-server
      type: webservice          # platform-defined component type
      properties:
        image: oamdev/hello-world
        ports: [{ port: 80, containerPort: 8000, expose: true }]
```
KubeVela renders this into a Deployment + Service: `kubectl get deployment,service -l app.oam.dev/name=first-app`.

## The platform's app components (the `appmod-service` pattern)

The PEEKS platform ships richer, opinionated components so a developer can request an app *and* its dependencies in one ordered manifest using `dependsOn`:

```yaml
spec:
  components:
    - name: dynamodb-table          # 1. the AWS resource (via ACK under the hood)
      type: dynamodb-table
      properties: { tableName: app-table, partitionKeyName: pk, sortKeyName: sk, region: us-west-2 }
      traits:
        - type: component-iam-policy
          properties: { service: dynamodb }
    - name: app-sa                  # 2. a service account scoped to that table (Pod Identity)
      type: dp-service-account
      properties: { componentNamesForAccess: [dynamodb-table], clusterName: peeks-spoke-dev, clusterRegion: us-west-2 }
      dependsOn: [dynamodb-table]
    - name: backend                 # 3. the app itself (canary via Argo Rollouts by default)
      type: appmod-service
      properties: { image: "<ecr-uri>:<tag>", port: 80, targetPort: 8080, replicas: 2, serviceAccount: app-sa }
      dependsOn: [app-sa]
      traits:
        - type: path-based-ingress
          properties: { rewritePath: true, http: { /app: 80 } }
```

What this single file produced: a DynamoDB table (ACK), a scoped IAM role + Pod Identity association, a canary-enabled Deployment + Service, and a path-based ingress — in dependency order. That is the power of the model: infrastructure + app + networking + security as one developer-authored unit.

Common `appmod-service` parameters: `image`, `replicas`, `port`/`targetPort`, `serviceAccount`, `resources`, `env`. Common traits: `path-based-ingress`, `component-iam-policy`. Plus the progressive-delivery gates (`functionalGate`/`performanceGate`/`metrics`) from `progressive-delivery.md`.

## CUE and extensibility

Component/trait definitions are written in CUE (e.g. the `webservice` definition lives in KubeVela's templates). CUE is chosen over raw YAML for type-safety and composition. Platform engineers add new component/trait types without changing the core platform; developers pick them up immediately by `type`. GenAI (via Kiro — see `genai-platform-engineering.md`) is commonly used to author new component definitions from an existing one + a CRD schema.

## Why OAM here

- Developers ship faster — one file, no Kubernetes plumbing.
- Standards enforced centrally — every app gets the platform's ingress/IAM/rollout conventions by construction.
- GitOps-native — Applications are YAML in Git, reconciled by ArgoCD, rendered by KubeVela; multi-cluster from a single definition.
