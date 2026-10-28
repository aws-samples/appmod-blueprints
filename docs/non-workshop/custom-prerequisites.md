# 3 · Custom install — prerequisites and configuration

> Sections 1–2 (host and AWS account prerequisites) apply to every direct install; the quick paths
> link here for them. Sections 3–6 are specific to the custom path.

The custom path installs the platform directly (`kind-kro-ack`) with **your own** domain, fleet
repo and (optionally) cross‑account spokes. This page is the prerequisites and the annotated
`config.local.yaml` the other custom pages build on.

---

## 1. Host prerequisites

A Linux/macOS host (EC2, Cloud Desktop, or a laptop) with Docker running and these CLIs on `PATH`.
The install's pre‑flight checks `kind, kubectl, helm, yq, aws` plus `go-task`:

| Tool | Validated version | Purpose |
|---|---|---|
| `docker` | any recent | runs the ephemeral `kind` bootstrap cluster |
| `kind` | 0.24 | throwaway local cluster that bootstraps the hub |
| `kubectl` | 1.37 | matches the hub's default EKS `kubernetesVersion` |
| `helm` | 3.16 | installs the ACK / KRO / ESO bootstrap charts |
| `yq` | 4.53 | every config read is a `yq` v4 expression (v3 breaks) |
| `aws` | 2.36 | all AWS calls (v2) |
| `go-task` | 3.x | the `task` runner |
| `jq` | any recent | required by the CloudFront scripts (if you expose via CloudFront) |

AWS credentials for the target account must resolve in your shell
(`aws sts get-caller-identity` — never echo the secret values).

---

## 2. AWS account prerequisites

1. **IAM Identity Center (SSO) instance in the account.** The platform's ArgoCD is created as an EKS
   ArgoCD Capability, which requires an Identity Center instance. Confirm:
   ```bash
   aws sso-admin list-instances --region <region>
   ```
2. **(HTTPS/own-domain mode only) A validated ACM certificate** in the deploy region covering
   `*.<your-domain>`, status `ISSUED` (ALB listeners are regional). Confirm:
   ```bash
   aws acm list-certificates --region <region> \
     --query "CertificateSummaryList[?DomainName=='*.<your-domain>']"
   ```
   *CloudFront mode needs no ACM cert — see [quick-cloudfront.md](quick-cloudfront.md).*
3. **A public Route53 hosted zone for `<your-domain>`.** external-dns writes A/ALIAS records into it
   to point your hostnames at the ALB. The zone must be **public** and the account's nameservers
   must be authoritative for the domain (delegated from the registrar/parent zone). Confirm:
   ```bash
   aws route53 list-hosted-zones-by-name --dns-name <your-domain>
   ```

---

## 3. Fleet repo prerequisite — fork OR your own git provider

Spokes are declared in a **fleet repo** that ArgoCD reconciles. Pick one:

- **Fork the public example** [`allamand/fleet-config-peeks-example`](https://github.com/allamand/fleet-config-peeks-example)
  (recommended starting point — it already has the `dev`/`prod` structure). Keep it **public** and
  ArgoCD reads it anonymously (no token). This is the zero‑PAT path — see
  [quick-existing-fleet.md](quick-existing-fleet.md).
- **Point at your own git provider** (e.g. a private GitHub/GitLab repo). Then you need a git token
  (next section). Set the repo's layout to match the example's (`gitops/fleet/...`,
  `configs/multi-acct/...`, `overlays/clusters/...`).

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

## 4. Git token (only for a private fleet repo, or generative spoke push)

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

## 5. The annotated `config.local.yaml`

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

# Only if the fleet content lives in a DIFFERENT repo than the charts (see section 3).
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

# Optional cost-allocation / retention tags applied to EVERY resource the platform creates.
# platformTags:
#   project: <your-project>
#   owner: <your-team>

# Same-account spokes on the direct path -> see custom-multi-account.md (global.spokeNames).
# Cross-account spokes -> configs/multi-acct/values.yaml in your fleet repo (same doc).
```

> **Gotcha — named profile + IMDS (EC2 / Cloud Desktop host).** If IMDS is reachable, ACK
> controllers can be seeded with the **host's** instance role (wrong account) → `ec2:CreateVpc` 403.
> Set `aws.profile: <name>` **and** launch the install from a small script file that sets
> `AWS_PROFILE=<name>` in‑file (not with an `export` on a shell command line), so both the config
> reads and the bare host‑side `aws` calls resolve to the target account.

---

## 6. Install and verify

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

## Next

- Add a spoke / go cross‑account → [custom-multi-account.md](custom-multi-account.md)
- Delete a spoke → [custom-delete-spoke.md](custom-delete-spoke.md)
- See, reduce or stop the cost → [custom-cost.md](custom-cost.md)
- Keep your fork's README in sync → [custom-update-readme.md](custom-update-readme.md)
