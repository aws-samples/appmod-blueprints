# GenAI-Assisted Platform Engineering

GenAI accelerates both sides of the platform: developers generating application code, and platform engineers generating the platform's own artifacts (Backstage templates, kro or OAM compositions, deployment manifests). Always human-in-the-loop.

## Tooling — use Kiro (successor to Amazon Q Developer)

**Kiro** is AWS's spec-driven, agentic development tool (IDE, CLI, and web), and the **official successor to Amazon Q Developer** for IDE/agentic coding. If existing material or a workshop references Amazon Q Developer's IDE plugins, `/dev`, or Customizations, treat that as legacy and use Kiro instead.

> **Migration note (verify current dates at [the official notice](https://aws.amazon.com/blogs/devops/amazon-q-developer-end-of-support-announcement/)).** As announced April 30, 2026:
> - Amazon Q Developer **IDE plugins and paid subscriptions reach end of support on April 30, 2027** (critical bugfixes continue until then).
> - **New Q Developer Free Tier accounts and new subscriptions were blocked as of May 15, 2026** (existing subscribers can still add seats).
> - In scope of the sunset: the IDE plugins, Q Developer Pro, the `/dev` agent, and Q Developer Customizations.
> - **Not** in scope (these continue): Amazon Q Developer in the AWS Management Console, the AWS Console Mobile App, and Q Developer in chat apps (Slack/Teams).
> - **Kiro is the named replacement** for IDE/agentic coding; an official migration guide lives at `kiro.dev/docs/migrating-from-q-developer/`.
>
> Note: **AWS DevOps Agent** (GA March 31, 2026) is a *distinct* frontier agent for SRE/operational excellence (incident investigation, MTTR reduction) — it is **not** a Q Developer successor and does not replace the platform-generation workflow described here.

## Two tracks

- **Code generation** (app developers) — snippets, functions, whole features in unfamiliar languages.
- **Platform generation** (platform engineers) — Backstage templates, kro `ResourceGraphDefinition`s (or OAM component definitions if you run KubeVela), deployment/IaC manifests, runbooks, automation.

The goal is to *accelerate adoption* of platform practices, not replace judgment.

## Kiro's spec-driven workflow maps onto platform work

Kiro structures agentic work as **spec → design → tasks**, with a few primitives that fit platform engineering directly:

- **Specs** — capture the requirements for a new template or composition as a structured spec before code is generated, so the artifact is reviewable against an explicit contract (not just a prompt).
- **Steering files** — persistent, project-level context (conventions, naming, the platform's reference examples). This replaces the older "manually paste the platform conventions into every prompt" pattern and the Q Developer Customizations approach.
- **Hooks** — event-driven automation (e.g. regenerate/validate an artifact on a file change).
- **Custom subagents** — scoped agents for repeatable platform tasks.

Point Kiro's steering context at the platform's reference examples (`platform-meta/examples/`, existing templates and compositions) so generations follow platform conventions by default.

## The reliable generation pattern

```
reference example  +  target schema/CRD  +  a precise prompt (or spec)  →  generated artifact  →  human review (diff)  →  use
```

Examples from the platform:
- **Generate a kro composition** — "use the S3 `ResourceGraphDefinition` as a template and create a `ddb-table` composition from this DynamoDB ACK CRD; only required properties except `billingMode: PAY_PER_REQUEST`; 4 params." Developers then self-serve the resulting custom resource. *(On a KubeVela platform, the analogous task is generating an OAM `ddb-table` component into `vela-system`.)*
- **Generate a Backstage template** — "use the S3 Backstage template's folder structure and stages to create a DynamoDB template; reference this composition." Produces `template.yaml` + `skeleton/` (catalog-info + manifests).
- **Generate a deployment manifest** — "create the application manifest using these templates, in strict dependency order: DynamoDB table → service account → app → path-based ingress; default/required params; reference `src/` for context."

## Prompt / spec essentials

- Be specific: state the goal, the inputs, the constraints, and the expected output shape.
- Provide context: point at the reference file, the schema, and existing code (`src/`, `platform-meta/examples/`) — or encode it once in a steering file.
- Decompose complex tasks; iterate — GenAI is non-deterministic, so the same prompt may vary.
- Give acceptance criteria (error handling, tests, docs, conventions).

## Human-in-the-loop is non-negotiable

Expect hallucinations (non-existent methods) and missed integration steps (e.g. a new route not wired into `main`). Always `diff` generated artifacts against a validated version before registering/deploying. GenAI produces the skeleton; the engineer validates and finishes. Then it ships through the *same* golden path as hand-written code — `git push` → CI/CD → canary.
