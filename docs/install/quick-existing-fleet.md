# 2b · Quick setup — reuse the example fleet-config (zero-fork, zero-PAT)

Deploy the platform **directly** (non‑workshop, `kind-kro-ack` provider) and get two spokes
(`dev` / `prod`) without forking anything and without a git token. You point your install at the
**public example fleet repo**, which already carries the spoke declarations; ArgoCD reads it
**read‑only (anonymous clone)** and reconciles the spokes. **No Personal Access Token is needed.**

The example repo is [`allamand/fleet-config-peeks-example`](https://github.com/allamand/fleet-config-peeks-example)
— a generic, placeholder‑only fleet repo (no account IDs, no tokens, no real domains).

---

## When to use this path

- You want the quickstart with the fewest moving parts.
- You are happy for the spoke **declarations** (names, regions, CIDRs — no account IDs) to be public.
- You do **not** need cross‑account spokes yet (every spoke runs in the hub's account).

If any of those is false, use the custom path: [custom-install.md](custom-install.md)
and [custom-multi-account.md](custom-multi-account.md).

---

## Prerequisites

- The install host + CLIs as in [prerequisites.md](prerequisites.md).
- AWS credentials for the target account (`aws sts get-caller-identity` — never echo secrets).
- An **IAM Identity Center** instance in the account.
- An exposure choice — either CloudFront ([quick-cloudfront.md](quick-cloudfront.md)) or your own
  domain. This path only concerns the **fleet repo**; it composes with either exposure mode.

---

## How it works (why no PAT)

The hub's `clusters-kro` ApplicationSet globs
`fleet/spoke-values/tenants/*/kro-clusters/clusters/*.json` — one trigger JSON **per cluster** — and
reads each spoke's spec from `tenants/<tenant>/kro-clusters/values.yaml`. The `fleet-secrets`
ApplicationSet globs `fleet/members/*/values.yaml` to register each spoke with ArgoCD.

Because the example repo already **commits** `dev.json` + `prod.json` and their specs, ArgoCD only
has to **read** the repo — which it does anonymously over a public clone. A PAT is only needed when
something **writes** to the fleet repo (the generative `spokes:apply` flow, or a private repo).

**`accountId` is deliberately absent** from every spec in the example repo: the `kro-clusters`
chart defaults it to `global.accountId`, which the hub propagates from its own cluster‑secret (your
real account) at reconcile time — so no account number ever lives in the public repo.

---

## Config — point `fleetRepo` at the example repo

Add a `fleetRepo` block to your `config.local.yaml` (keep all the other keys from
[custom-install.md](custom-install.md#3-the-annotated-configlocalyaml)):

```yaml
clusterProvider: kind-kro-ack
fleetRepo:
  url: https://github.com/allamand/fleet-config-peeks-example.git
  revision: main
  basepath: ""
```

Then run the install from the repo root:

```bash
aws sts get-caller-identity
task install        # idempotent & resumable; ~30–55 min
```

> Prefer **your own copy** of the example repo (a fork) if you want a stable pin and the freedom to
> add spokes. A fork is still read anonymously (still zero‑PAT) as long as it stays public.

---

## Add or change a spoke (still zero-PAT)

Commit directly to **your copy** of the fleet repo — there is no installer push, so still no PAT:

1. add `gitops/fleet/spoke-values/tenants/default/kro-clusters/clusters/<name>.json` containing
   `{"clusterName": "<name>"}`;
2. add a `<name>:` block under `clusters:` in
   `gitops/fleet/spoke-values/tenants/default/kro-clusters/values.yaml` with a **disjoint**
   `cidr.vpcCidr`, a `region`, and `k8sVersion`;
3. add `gitops/fleet/members/<name>/values.yaml` (copy the `dev/` member);
4. `git commit && git push` to your copy.

ArgoCD picks up the change on its next sync.

> **CARM / same‑account coverage.** For the spoke's hub‑side ACK resources to reconcile, its
> namespace needs an IAMRoleSelector. On this direct path you declare the spoke names through
> `global.spokeNames` (the fix that ships with
> [#1157](https://github.com/aws-samples/appmod-blueprints/issues/1157)) — see
> [custom-multi-account.md](custom-multi-account.md), "Same‑account spokes". Cross‑account spokes
> need `configs/multi-acct/values.yaml` with an explicit account ID (same doc).

---

## Verify

```bash
export KUBECONFIG=$PWD/private/kubeconfig
kubectl get applications -A | grep -E 'clusters-kro|fleet-secret'   # one app per spoke
kubectl get eksclusterwithvpcs.kro.run -A                          # dev + prod reconciling
kubectl get nodes --context <spoke-context>                        # once the spoke EKS is ACTIVE
```

---

## If you need a private fleet repo

Making the fleet repo **public** removes the credential for the read/clone path and for the
pre‑filled spokes. If your fleet repo must be private, you need an ArgoCD `repository` credential —
there is **no credential field in `config.local.yaml`**; it is wired through the ArgoCD Secret
`argocd/fleet-config-repo` (directly, or projected from AWS Secrets Manager by External Secrets
Operator). See [custom-install.md](custom-install.md#2-git-token-only-for-a-private-fleet-repo-or-generative-spoke-push), "Git token / private fleet repo".
