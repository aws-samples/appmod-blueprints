# Install guide — choose your path

Platform Engineering on Amazon EKS can be deployed in several ways. This guide is a
**decision diagram**: pick the branch that matches your situation and follow the one
procedure it points to. Every leaf of the diagram maps to a dedicated, step‑by‑step
procedure (exact `config.local.yaml` + guard‑rails).

> **Workshop vs. direct install.** If you are here for the **guided workshop** (an AWS
> event, or self‑paced), follow the hosted workshop — there is nothing to re‑document.
> If you want to install the platform **directly** into your own AWS account with the
> `kind-kro-ack` cluster provider (no Workshop Studio CloudFormation), this guide is the
> one you want.

## Choose your path

```mermaid
flowchart TD
    Start(["Deploy Platform Engineering on EKS"]) --> Q1{"Guided workshop<br/>or direct install?"}

    Q1 -->|"Guided workshop"| W{"Where are you<br/>running it?"}
    W -->|"At an AWS event"| W1["1a · AWS event"]
    W -->|"On your own / self-paced"| W2["1b · Self-paced catalog"]

    Q1 -->|"Direct install (kind-kro-ack)"| D{"How much do you<br/>need to customise?"}

    D -->|"Quick setup"| QX{"How are the platform<br/>UIs exposed?"}
    QX -->|"CloudFront (no domain needed)"| QC["2a · Quick / CloudFront"]
    QX -->|"Reuse the example fleet-config"| QF["2b · Quick / existing fleet-config"]

    D -->|"Full custom"| C["3 · Custom install"]
    C --> C2["3.2 · Multi-account + add a spoke"]
    C --> C6["3.6 · Restrict the ALB by source IP"]

    click W1 "https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/01_aws_event" _blank
    click W2 "https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/02_self_paced" _blank
    click QC "quick-cloudfront.md"
    click QF "quick-existing-fleet.md"
    click C "custom-prerequisites.md"
    click C2 "custom-multi-account.md"
    click C6 "custom-alb-ip-allowlist.md"

    classDef leaf fill:#e8f0fe,stroke:#4285f4,color:#111;
    class W1,W2,QC,QF,C,C2,C6 leaf;
```

**Go to:** [1a · AWS event](https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/01_aws_event) ·
[1b · Self-paced](https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/02_self_paced) ·
[2a · CloudFront](quick-cloudfront.md) ·
[2b · Existing fleet-config](quick-existing-fleet.md) ·
[3 · Custom install](custom-prerequisites.md) ·
[3.2 · Multi-account](custom-multi-account.md) ·
[3.6 · ALB allowlist](custom-alb-ip-allowlist.md)

> **Note on the links.** GitHub's Mermaid renderer ignores `click` links in diagrams, so use the
> line above (other Mermaid renderers make the leaves clickable).

Prerequisites, cost, deleting a spoke and README upkeep are not path choices: they are listed under
[Advanced operations](#advanced-operations-all-modes).

## Procedures

| # | Leaf | What it covers | Go to |
|---|------|----------------|-------|
| 1a | AWS event | The guided workshop, run at an AWS‑led event (access code, account provided) | [Workshop — AWS event](https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/01_aws_event) *(external)* · upcoming events: [AWS Events](https://aws.amazon.com/events/) |
| 1b | Self‑paced | The same workshop, run on your own account | [Workshop — self‑paced](https://catalog.workshops.aws/platform-engineering-on-eks/en-US/00_start_workshop/02_self_paced) *(external)* |
| 2a | Quick / CloudFront | Direct install exposed behind a free `*.cloudfront.net` host — **no domain, no ACM cert needed** | [quick-cloudfront.md](quick-cloudfront.md) |
| 2b | Quick / existing fleet‑config | Direct install that reuses the public example fleet repo (`fleet-config-peeks-example`) — **zero‑fork, zero‑PAT** | [quick-existing-fleet.md](quick-existing-fleet.md) |
| 3 | Custom install | Your own domain/cert and fleet repo: annotated `config.local.yaml`, install, verify | [custom-prerequisites.md](custom-prerequisites.md) |
| 3.2 | Multi‑account + add a spoke | Configure cross‑account CARM and create a spoke in another account | [custom-multi-account.md](custom-multi-account.md) |
| 3.6 | Restrict the ALB by source IP | Set, change or remove the source‑IP allowlist of the shared `platform` ALB (all hub UIs), plus closing Langfuse self‑registration | [custom-alb-ip-allowlist.md](custom-alb-ip-allowlist.md) |

## Choose your fleet-config

The fleet repo (`fleetRepo` in `config.local.yaml`) holds the spoke declarations ArgoCD reconciles.
Pick one of three options:

| Option | When | What to do |
|---|---|---|
| **(a) Upstream example, unchanged** | Quickest start; spokes `dev`/`prod` in the hub's account; you accept that the declarations (names, regions, CIDRs — no account IDs) are public | Point `fleetRepo.url` at [`fleet-config-peeks-example`](https://github.com/allamand/fleet-config-peeks-example) — no fork, no token. Procedure: [2b](quick-existing-fleet.md) |
| **(b) Fork of the example** | You want to add/change spokes or edit enabled addons | [Fork the example repo](https://github.com/allamand/fleet-config-peeks-example/fork) and set `fleetRepo.url` to your fork. A **public** fork is read anonymously (no PAT). A **private** fork, or the generative `spokes:*` flows that push to the repo, need a PAT — see below |
| **(c) Your own git provider** | Private GitHub/GitLab repo, or a layout you control | Follow [custom-prerequisites.md — fleet repo](custom-prerequisites.md#3-fleet-repo-prerequisite--fork-or-your-own-git-provider) and [git token](custom-prerequisites.md#4-git-token-only-for-a-private-fleet-repo-or-generative-spoke-push) |

Config keys: `fleetRepo.{url,revision,basepath}`, each falling back to `repo.*` when omitted
([example block](custom-prerequisites.md#3-fleet-repo-prerequisite--fork-or-your-own-git-provider)).

**PAT (private fork, option c, or `spokes:*` push).** There is no token key in `config.local.yaml`:
the PAT goes into AWS Secrets Manager and an ArgoCD `repository` Secret `argocd/fleet-config-repo`.
Minimal scopes and manifests:
[custom-prerequisites.md, section 4](custom-prerequisites.md#4-git-token-only-for-a-private-fleet-repo-or-generative-spoke-push).

## Advanced operations (all modes)

These pages are not install paths. Each one states which modes it applies to.

| Topic | Modes | What it covers | Go to |
|---|---|---|---|
| Prerequisites | Direct installs (the workshop IDE is pre-provisioned) | Host tools and versions, AWS account prerequisites (Identity Center, ACM, Route53); sections 3–6 are the custom install itself | [custom-prerequisites.md](custom-prerequisites.md) |
| Solution cost | All (nothing to pay at an AWS event) | What the solution creates, how to estimate, track, reduce and stop the cost | [custom-cost.md](custom-cost.md) |
| Delete a spoke | All (the workshop also has ready-made tasks) | Cleanly tear down one spoke (spec → prune → sweep) | [custom-delete-spoke.md](custom-delete-spoke.md) |
| Update the README | Any mode where you keep your own fork | Record your deployment choices in your fork's README, zero‑secret | [custom-update-readme.md](custom-update-readme.md) |

## How the paths relate

All three **direct‑install** paths run the same `task install` with the `kind-kro-ack`
cluster provider — an ephemeral local `kind` cluster bootstraps a self‑managed EKS **hub**,
which then becomes self‑managing through ArgoCD. They differ only in two independent choices:

1. **How the UIs are exposed** — set by the `insecure` key in `config.local.yaml`:
   - `insecure: true` → the ALB stays HTTP‑only and something upstream terminates TLS. The
     simplest case is **CloudFront** with a free `*.cloudfront.net` name → **path 2a**.
   - `insecure: false` → the ALB serves **HTTPS** with your own ACM certificate on your own
     Route53 domain → the **custom** path ([prerequisites](custom-prerequisites.md) cover the domain/cert).
2. **Where the spoke declarations live** — a *fleet repo* (`fleetRepo.url`):
   - reuse the **public example** repo as‑is → **path 2b** (zero‑fork, zero‑PAT);
   - fork it or point at your own git provider → see [Choose your fleet-config](#choose-your-fleet-config).

The **custom** path (3.x) is the superset: it adds your own domain/cert, your own fleet
repo and cross‑account spokes. Day‑2 operations (delete a spoke, cost) are under
[Advanced operations](#advanced-operations-all-modes).

## Honest status of the direct path

- **Hub: works today.** A direct `kind-kro-ack` `task install` brings up a working hub.
- **Agentic platform (OAP): wired, not yet self-standing on the direct path.** When the
  `agenticRepo` block is set, its coordinates are mirrored into the hub cluster-secret annotations
  (`addons_repo_url` / `addons_repo_revision`) that the agent-platform appsets consume — but no
  appmod Taskfile yet applies OAP's `agent-platform-app.yaml`, so the direct `task install` does
  **not** stand the agentic platform up on its own today. Tracked in
  [#1157](https://github.com/aws-samples/appmod-blueprints/issues/1157) and
  [open-agentic-platform#98](https://github.com/awslabs/open-agentic-platform/issues/98).
- **Same‑account spokes:** covered by `global.spokeNames` (the fix that ships with
  [#1157](https://github.com/aws-samples/appmod-blueprints/issues/1157)) plus a fleet repo
  that declares them — see [quick-existing-fleet.md](quick-existing-fleet.md) and
  [custom-multi-account.md](custom-multi-account.md).
- **Cross‑account spokes:** declared through `configs/multi-acct/values.yaml` with an
  explicit account ID per spoke — see [custom-multi-account.md](custom-multi-account.md).

Each procedure states precisely what is verified and flags anything still to validate.
