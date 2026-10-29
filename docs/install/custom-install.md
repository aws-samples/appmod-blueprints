# 3 · Custom install — fleet repo, configuration, install

The custom path installs the platform directly (`kind-kro-ack`) with **your own** domain, fleet
repo and (optionally) cross‑account spokes. This page is the fleet-repo and git-token setup, the
annotated `config.local.yaml` the other custom pages build on, the install itself, and how to
document your deployment.

> **Before you start:** complete the host and AWS account [prerequisites](prerequisites.md)
> (tools, IAM Identity Center, ACM certificate, Route53 hosted zone).

---

## 1. Fleet repo prerequisite — fork OR your own git provider

Spokes are declared in a **fleet repo** that ArgoCD reconciles. Pick one:

- **Fork the public example** [`allamand/fleet-config-peeks-example`](https://github.com/allamand/fleet-config-peeks-example)
  (recommended starting point — it already has the `dev`/`prod` structure). Keep it **public** and
  ArgoCD reads it anonymously (no token). This is the zero‑PAT path — see
  [quick-existing-fleet.md](quick-existing-fleet.md).
- **Point at your own git provider** (e.g. a private GitHub/GitLab repo). Then you need a git token
  (next section). Set the repo's layout to match the example's (`gitops/fleet/...`,
  `overlays/clusters/...`).

Reference it in config:

```yaml
fleetRepo:
  url: https://github.com/<org>/<your-fleet-repo>.git
  revision: main
  basepath: ""      # "" when the fleet content sits at the repo root, like the example
```

If the fleet content lives in the **same** repo as the charts, you can omit `fleetRepo` entirely —
each field falls back to `repo.*`.

---

## 2. Git token (only for a private fleet repo, or generative spoke push)

There is **no credential field in `config.local.yaml`** — `config.schema.json` exposes only
`fleetRepo.{url,revision,basepath}`. The credential is a **Kubernetes Secret ArgoCD recognises**,
named `fleet-config-repo` in the `argocd` namespace, carrying the label
`argocd.argoproj.io/secret-type: repository`. You need it when:

- the fleet repo is **private** (ArgoCD must authenticate to read/reconcile), or
- you use the **generative** `spokes:enable-kro` / `spokes:enable-crossplane` flow that writes the
  trigger files back to the repo.

A **public** fleet repo read anonymously needs none of this.

### (a) Mint a PAT — minimal scope

- GitHub classic: `repo` (private) / `public_repo` (public).
- GitHub fine‑grained: repository access limited to the one fleet repo, permission **Contents:
  Read and write** (Read‑only if ArgoCD only ever reads).

Keep the token in **AWS Secrets Manager**, not on disk. The platform's own External Secrets wiring
reads it from the property **`git_token`** of the per‑hub secret `<hub-cluster-name>/secrets`:

```bash
# Option 1 — add git_token to the hub's existing <hub>/secrets (merge, don't clobber):
aws secretsmanager get-secret-value --secret-id "<hub-cluster-name>/secrets" \
  --query SecretString --output text \
  | jq --arg t "<PAT>" '. + {git_token: $t}' \
  | aws secretsmanager put-secret-value --secret-id "<hub-cluster-name>/secrets" \
      --secret-string file:///dev/stdin

# Option 2 — a dedicated secret an ExternalSecret points at:
aws secretsmanager create-secret --name "<secret-name>" --secret-string '{"git_token":"<PAT>"}'
```

> Never paste a real token into config, into any repo, or into chat. `<PAT>` / `<secret-name>` are
> placeholders.

### (b) Create the ArgoCD `repository` secret

**Direct (`kubectl apply`):**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fleet-config-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://github.com/<org>/<private-fleet-repo>.git
  username: <org>          # any non-empty value; GitHub ignores it when a PAT is the password
  password: <PAT>          # the token — placeholder, never the real value
```

**Or via External Secrets (self‑heals on rotation):**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: fleet-config-repo
  namespace: argocd
spec:
  secretStoreRef:
    name: aws-secrets-manager      # your ClusterSecretStore
    kind: ClusterSecretStore
  refreshInterval: "5m"
  target:
    name: fleet-config-repo
    creationPolicy: Owner
    template:
      engineVersion: v2
      metadata:
        labels:
          argocd.argoproj.io/secret-type: repository
      data:
        type: git
        url: "https://github.com/<org>/<private-fleet-repo>.git"
        username: "<org>"
        password: "{{ .GIT_PASSWORD }}"
  data:
    - secretKey: GIT_PASSWORD
      remoteRef:
        key: <secret-name>          # or <hub-cluster-name>/secrets
        property: git_token
```

ArgoCD reads this secret **continuously** to reconcile; the `kind-kro-ack` provider reads the **same**
secret for its own GitOps writes and refuses the pivot if it is absent.

---

## 3. The annotated `config.local.yaml`

Create `config.local.yaml` in the repo root. Every key below is actually read by the provider
(`cluster-providers/kind-kro-ack/Taskfile.yaml` is the authoritative key list — **not**
`config.schema.json`, which omits `agenticRepo` and `spokes`).

```yaml
# yaml-language-server: $schema=config.schema.json

clusterProvider: kind-kro-ack        # the direct (non-workshop) hub provisioner

repo:                                 # where the platform CHARTS live
  url: https://github.com/aws-samples/appmod-blueprints
  revision: <release-tag>             # a tag or branch (e.g. a vX.Y.Z-rcN release tag)
  basepath: gitops/                   # MUST end with '/'

# REQUIRED for the agentic platform (OAP). Absent from config.schema.json but READ by the
# provider; omit it and you silently get a hub with NO agentic platform.
agenticRepo:
  url: https://github.com/awslabs/open-agentic-platform
  revision: <oap-release-tag>
  basepath: gitops/addons/

# Only if the fleet content lives in a DIFFERENT repo than the charts (see section 1).
fleetRepo:
  url: https://github.com/<org>/<your-fleet-repo>.git
  revision: main
  basepath: ""

hub:
  clusterName: <hub-name>             # DNS-safe, unique per account+region; prefixes IAM roles & secrets
  kubernetesVersion: "1.37"           # optional; default 1.37
  vpcCidr: "10.0.0.0/16"              # optional; must not overlap peered stacks/spokes
  autoMode: true                      # EKS Auto Mode for the hub

aws:
  region: <region>                    # e.g. us-west-2
  accountId: "<account-id>"           # 12-digit string
  profile: <profile-name>             # optional; see the IMDS gotcha below

domain: <your-domain>                 # you own the Route53 zone; the platform never creates it
insecure: false                       # false => HTTPS ALB + ACM cert (own-domain mode).
                                      # true  => HTTP-only ALB (CloudFront terminates TLS) -> quick-cloudfront.md
certificateArn: arn:aws:acm:<region>:<account-id>:certificate/<cert-id>   # ISSUED, covers *.<your-domain>

resourcePrefix: <prefix>              # lowercase, starts with a letter; prefixes ECR repos / S3 buckets / IAM roles

adminRoleName: Admin                  # IAM role granted cluster-admin + used by Backstage templates

identityCenter:                       # REQUIRED — the ArgoCD Capability needs an IdC instance
  instanceArn: arn:aws:sso:::instance/<ssoins-id>
  region: <region>                    # where the IdC instance lives (often us-east-1)
  adminGroupId: <group-id>            # IdC group granted ArgoCD admin

# AWS tags applied to EVERY resource the platform creates (hub, spokes, their VPCs).
# auto-delete: "no" keeps an account cleanup sweeper from reaping a long-lived install;
# add any other tag the same way (e.g. owner, cost-center).
platformTags:
  auto-delete: "no"
#   owner: <your-team>
#   cost-center: <your-cost-center>

# Spokes are declared in your fleet repo (kro-clusters/values.yaml), not here; add accountId
# to a spoke's entry for a cross-account spoke -> see custom-multi-account.md.
```

> **Gotcha — named profile + IMDS (EC2 / Cloud Desktop host).** If IMDS is reachable, ACK
> controllers can be seeded with the **host's** instance role (wrong account) → `ec2:CreateVpc` 403.
> Set `aws.profile: <name>` **and** launch the install from a small script file that sets
> `AWS_PROFILE=<name>` in‑file (not with an `export` on a shell command line), so both the config
> reads and the bare host‑side `aws` calls resolve to the target account.

---

## 4. Install and verify

```bash
aws sts get-caller-identity
task install          # idempotent & resumable; ~30–55 min
```

The install is resumable — if `hub:wait-for-eks` times out while EKS is still `CREATING`, or an ECR
Public token goes stale mid‑run (403), just re‑run `task install`.

```bash
export KUBECONFIG=$PWD/private/kubeconfig
kubectl get nodes
kubectl get applications -A                   # hub (+ agentic) apps Synced/Healthy
task status                                   # prints the published URLs
# own-domain mode:
curl -sS -o /dev/null -w '%{http_code}\n' https://argocd.<your-domain>
curl -sS -o /dev/null -w '%{http_code}\n' https://backstage.<your-domain>
```

---

## 5. Document your deployment

If you keep your own fork of the platform or fleet repo, record in its README the choices you made
so the next operator can reproduce the deployment. Nothing here changes the running system.

### What to update in your fork's README

Record the decisions that differ from the defaults:

1. **Install path.** State which path you followed (CloudFront / existing fleet‑config / custom) and
   link back to this guide's entry page, [README.md](README.md).
2. **Exposure mode.** `insecure: true` (CloudFront) vs `insecure: false` (your own domain + ACM).
   Note the hostname pattern (generically — e.g. `*.<your-domain>`), never a real host or cert ARN.
3. **Fleet repo.** Which repo holds your spokes (`fleetRepo.url`) and whether it is public
   (zero‑PAT) or private (credential via `argocd/fleet-config-repo`).
4. **Spokes.** The list of spoke names and whether they are same‑account (no `accountId`) or
   cross‑account (`accountId` in the spoke's `kro-clusters/values.yaml` entry).
5. **Versions.** The `repo.revision` / `agenticRepo.revision` tags you pinned.
6. **Cost tags.** The `platformTags` keys you set, so cost reports are reproducible
   ([cost.md](cost.md)).

### The one rule — keep it generic / zero‑secret

A README is public (or shared). **Never** commit:

- AWS account IDs, VPC/subnet/instance IDs, internal IPs;
- real hostnames, CloudFront domains, IDE URLs or tokens;
- ACM/role ARNs, Secrets Manager values, PATs;
- usernames / aliases / internal references.

Use placeholders everywhere: `<account-id>`, `<your-domain>`, `<cluster-prefix>`, `<org>`,
`<secret-name>`. Scan before you commit:

```bash
# Flag the usual leaks in your staged README changes before committing
git diff --cached -- README.md \
  | grep -nE '[0-9]{12}|ghp_|github_pat_|AKIA|ASIA|-----BEGIN|arn:aws:(iam|acm)|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  && echo "⚠ review the matches above — redact before committing" || echo "clean"
```

Pushing the README to a public or shared repo is a separate step: review the diff and the scan first.

### Suggested snippet to add to your fork's README

```markdown
## Our deployment

This fork runs Platform Engineering on EKS via the **<CloudFront | own-domain | custom>** path
(see [docs/install/README.md](docs/install/README.md)).

- Exposure: `insecure: <true|false>` (<CloudFront *.cloudfront.net | HTTPS on *.your-domain>)
- Fleet repo: `<org>/<your-fleet-repo>` (<public zero-PAT | private>)
- Spokes: `<dev, prod, ...>` (<same-account | cross-account via accountId in kro-clusters/values.yaml>)
- Pinned: platform `<release-tag>`, OAP `<oap-release-tag>`
- Cost tags: `platformTags.{project, environment, owner}`
```

---

## Next

- Add a spoke / go cross‑account → [custom-multi-account.md](custom-multi-account.md)
- Delete a spoke → [delete-spoke.md](delete-spoke.md)
- See, reduce or stop the cost → [cost.md](cost.md)
