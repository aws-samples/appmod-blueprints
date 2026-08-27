# Measuring Platform Success

A platform you can't measure is a platform you can't improve or justify. The default metrics framework is DORA, collected automatically by Apache DevLake and visualized in Grafana.

## Why measure

Industry signal: a large share of platform teams don't measure success at all, yet leading adopters report markedly faster time to market. Without measurement you can't identify bottlenecks, make data-driven decisions, validate investment, or demonstrate ROI. DORA gives a vocabulary both engineers and business leaders understand.

## The four DORA metrics

| Metric | Question | Axis |
|--------|----------|------|
| **Deployment Frequency** | How often do we release to prod? | Velocity |
| **Lead Time for Changes** | Commit → production, how long? | Velocity |
| **Change Failure Rate** | % of deploys causing incidents | Stability |
| **Recovery Time** | Time to restore after an incident | Stability |

Balance matters: velocity (frequency, lead time) **and** stability (failure rate, recovery). Healthy platforms move lead times from weeks to hours and failure rates from ~20% to under 5% while keeping recovery fast.

## Apache DevLake — the measurement engine

- Purpose-built for DORA, with standardized, industry-aligned calculations.
- Integrates across the toolchain (Git, CI/CD, deployment, issue tracking).
- Automated collection (no manual data gathering), historical trending, and cross-team comparison.

## Platform integration (how the data flows)

```
GitLab webhooks (commits, PRs, issues)  ┐
Argo Workflows (deployment events)       ├─▶ Apache DevLake ─▶ Grafana DORA dashboards
Argo Rollouts (deploy success/failure)  ┘        (calculates + stores)
```

- Argo Workflows processes deployment/measurement events.
- Argo Rollouts signals whether a deploy succeeded.
- DevLake computes and stores the four metrics.
- Grafana renders DORA Overview + per-metric detail dashboards.

## Zero-overhead, self-service measurement

The key design choice: **measurement is wired in when a team onboards via Backstage.** Creating the CI/CD pipeline also deploys the DORA tracking workflows and the GitLab webhook event managers. Teams get measured simply by using the platform — no extra tooling or process. This is what makes DORA sustainable rather than a one-off audit.

## Using the metrics as a platform team

- Identify bottlenecks (e.g. long lead time → CI is slow; high failure rate → weak gates).
- Make data-driven roadmap decisions and validate that a platform change actually helped.
- Demonstrate ROI to leadership in a shared language.
- Compare/benchmark teams to spread the best golden paths.
