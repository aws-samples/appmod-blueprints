# Golden Paths

A golden path is a paved, opinionated route from intent to running software, with guardrails baked in. It is the central deliverable of a platform team — not a document, but a working, self-service flow shipped as a Backstage template.

## The design heart — the developer contract

Every golden path is a contract: a small, stable set of things the developer provides, and everything else the platform handles.

| Developer provides | Platform handles |
|--------------------|------------------|
| A `Dockerfile` | Image build, push to ECR, caching, scanning |
| The app manifest (intent) — a kro custom resource on the default stack, or an OAM `Application` on KubeVela | CI/CD pipeline, GitOps wiring |
| Form parameters (name, region, size, …) | Infra provisioning (ACK/kro), networking (ingress/DNS) |
| `git push` | Security (IAM/Pod Identity), progressive delivery, rollback |
| Gate thresholds / metrics (optional) | Promotion (Kargo), observability, DORA metrics |

Keep the left column tiny and stable. The narrower the developer contract, the lower the cognitive load and the higher adoption.

## The four core golden paths

1. **Provision an environment** — template → kro composes VPC + EKS Auto Mode + add-ons + ArgoCD registration.
2. **Provision an AWS resource** — template → ACK manifest → Git → ArgoCD → resource exists.
3. **Onboard an application** — template → kro `CICDPipeline` → Argo Workflows CI + ArgoCD CD; developer provides Dockerfile + OAM manifest.
4. **Ship safely to prod** — Argo Rollouts canary + gates in dev; Kargo promotes the validated artifact to prod.

All four share the same Backstage → Git → ArgoCD → controllers loop (see `developer-portal-backstage.md`).

## Design principles

- **Make the golden path the easiest path.** Adoption is the #1 IDP challenge; if the paved road is also the path of least resistance, teams take it.
- **Guardrails, not gates everywhere.** Encode standards (PSA levels, IAM scoping, ingress conventions, configuration tiers) into the templates and OAM definitions so compliance is the default, not a review step.
- **Provide escape hatches.** Opinionated ≠ locked-in. A team with a genuine edge case can drop to a lower abstraction; just make the common case trivial.
- **One repo per provisioned component.** Clean GitOps reconciliation and clear ownership.
- **Self-service onboarding.** New apps, environments, resources, and even DORA monitoring start from a template — no tickets.
- **Iterate from real usage.** Watch what teams actually do; if every app independently reinvents the same manifest or script, fold it into a component/template.

## Onboarding a new team (typical sequence)

1. Team picks the "app CI/CD pipeline" template in Backstage, names the app and target cluster.
2. kro `CICDPipeline` reconciles; ArgoCD dev/prod apps appear; ECR repo created.
3. Team adds a `Dockerfile` + an OAM `Application` to their repo and pushes.
4. CI builds, CD deploys to dev with canary + gates; DORA tracking is live automatically.
5. When dev is validated, Kargo promotes to prod (manual approval).

## Anti-patterns

- A golden path that requires Kubernetes/AWS knowledge to use — the abstraction has leaked.
- A wide, unstable developer contract — every new requirement becomes a new field the developer must understand.
- Golden paths with no measurement — you can't tell if they're helping (see `measuring-success.md`).
- Treating the platform as a project, not a product — no iteration, no adoption.
