# Progressive Delivery and Promotion

How the platform rolls out new versions safely (Argo Rollouts) and promotes them across environments (Kargo).

## Strategies

| Strategy | What it does | When |
|----------|--------------|------|
| **Canary** (default) | Shift traffic gradually to the new version; gate at checkpoints | Most services — the platform default |
| **Blue/Green** | Two identical environments; instant switch + instant rollback | Need zero in-flight risk / instant rollback |
| **A/B** | Run two versions to compare behavior | Experimentation / measuring effectiveness |

The platform's `appmod-service` OAM component wires Argo Rollouts canary automatically — developers get progressive delivery without writing Rollout specs.

## The default canary

```
new version → 20% traffic   [functional gate]
            → 40% (pause)
            → 60% (pause)
            → 80%           [performance gate / metrics gate]
            → 100%          old version retired
```

Any gate failure (or an image-pull failure, etc.) triggers **automatic rollback** to the last stable version.

## Quality gates (Argo Rollouts Analyses)

Three gate types, all developer-configured, platform-executed:

- **Functional gate** — a smoke/correctness check at ~20% traffic. Example: verify the served page color matches expected.
  ```yaml
  functionalGate: { pause: "20s", image: "httpd:alpine", extraArgs: "red" }   # "red" = expected
  ```
- **Performance gate** — a load/latency check at ~80% traffic (e.g. Artillery image), pass/fail on a threshold.
  ```yaml
  performanceGate: { pause: "10s", image: "httpd:alpine", extraArgs: "160" }  # 160 = max avg ms
  ```
- **Metrics gate** — developer-defined Prometheus queries, the most powerful gate. Each criterion: a function (`sum|avg|max|min|count`) over a metric, a comparison, a threshold, and whether breaching means success or failure.
  ```yaml
  metrics:
    pause: "2s"
    evaluationCriteria:
      - interval: "1s"
        count: 1
        function: "avg"
        successOrFailCondition: "fail"        # breaching this fails the rollout
        metric: "rocket_http_requests_duration_seconds_sum"
        comparisonType: ">"
        threshold: 3                          # avg response time > 3s → rollback
  ```

**Principle — developers own "healthy."** The platform supplies the mechanism (canary + analysis); each team defines the metrics and thresholds that define health for *their* app. Gates are config in the OAM manifest, not platform code.

## Multi-stage promotion — Kargo

Kargo orchestrates dev→prod promotion GitOps-natively. Resources:

- **Project** — Kargo namespace for the app (`<app>-kargo`).
- **Warehouse** — watches ECR for new images (produces "Freight").
- **Stages** — `dev` (auto-promote) and `prod` (manual approval).
- **PromotionTask** — how to update the app's manifests for a stage.

Flow:
```
Argo Workflows builds image → Warehouse detects it
   → dev stage AUTO-promotes: commits image into deployment/dev/application.yaml → ArgoCD deploys dev
   → human clicks "Promote" in Kargo UI for prod
   → prod stage commits the SAME image into deployment/prod/application.yaml → ArgoCD deploys prod
```

Key properties:
- **Same-artifact promotion** — prod runs the exact image that passed dev; no rebuild, no drift.
- **Auto dev / manual prod** — speed in lower environments, an approval gate for production.
- **GitOps-native** — every promotion is a Git commit: auditable, reversible.

Verify: `kubectl get warehouse,stages -n <app>-kargo -o wide`; confirm the prod manifest's `image:` updated after promotion.

## Watching a rollout

```bash
kubectl argo rollouts get rollout <name> -n <ns> -w     # live progression + gate status
kubectl argo rollouts retry rollout <name> -n <ns>      # retry after a fix
```
