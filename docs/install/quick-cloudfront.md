# 2a · Quick setup — expose via CloudFront (no domain needed)

Deploy the platform **directly** (non‑workshop, `kind-kro-ack` provider) and expose the UIs
behind a free `*.cloudfront.net` hostname. **You need no Route53 domain and no ACM certificate** —
CloudFront terminates TLS, and the ALB stays HTTP‑only as a private VPC origin.

The platform ships the two scripts that do the work; they are idempotent and already know how to
reuse‑or‑create a distribution. This path is **three gestures**, no code change.

---

## Prerequisites

- A Linux/macOS host with Docker and the install CLIs on `PATH`
  (`kind`, `kubectl`, `helm`, `yq` v4, `aws` v2, `go-task`) — plus **`jq`** (both CloudFront
  scripts parse JSON with it). See [prerequisites.md](prerequisites.md) for the
  validated versions.
- AWS credentials for the target account, resolvable by the AWS CLI/SDK. Confirm with
  `aws sts get-caller-identity` (never echo the secret values).
- An **IAM Identity Center** instance in the account (the platform's ArgoCD is an EKS ArgoCD
  Capability and requires one). Confirm: `aws sso-admin list-instances --region <region>`.

> **The CloudFront mode is selected by `insecure: true`, NOT by an empty `domain`.** An empty
> `domain` makes the install **fail** (`hub:seed` exits). You must put the CloudFront hostname in
> `domain:` *before* installing, because Keycloak realms, the OIDC issuer, ingress hosts and the
> ArgoCD/Backstage base URLs are all derived from it and ArgoCD starts applying them as soon as the
> install finishes.

---

## The two branches at a glance

Both branches share the exact same mechanics; the only difference is **where the
`*.cloudfront.net` hostname comes from**.

| | Branch 1 — reuse your own distribution | Branch 2 — let the script create/reserve one |
|---|---|---|
| Starting point | You already have a CloudFront distribution | You have none |
| Get the hostname | `aws cloudfront get-distribution --id <id> --query Distribution.DomainName` | `scripts/cloudfront-reserve-domain.sh` (its output = the hostname) |

They converge from gesture 2 onward.

---

## Branch 1 — reuse an existing distribution

### Gesture 1 — resolve your distribution's hostname

```bash
aws cloudfront get-distribution --id <distribution-id> \
  --query Distribution.DomainName --output text
# -> e.g. <dist-id>.cloudfront.net
```

> The attach step (gesture 3) finds the distribution by its **`Comment`** (default
> `<cluster>-platform`). To attach the ALB to *your* distribution, either its `Comment` must be
> `<cluster>-platform`, or override it with `CF_COMMENT=<your-comment>` on gesture 3. The scripts
> do not accept a distribution **ID** as input — they search by `Comment`.

### Gesture 2 — `config.local.yaml` + install

Keep all your other keys (`clusterProvider`, `repo`, `agenticRepo`, `identityCenter`,
`resourcePrefix`, …) exactly as in [custom-install.md](custom-install.md#3-the-annotated-configlocalyaml). The
exposure‑relevant keys are:

```yaml
# ── CloudFront exposure — Branch 1 (reuse) ──────────────────────────────────
domain: <hostname>.cloudfront.net   # resolved in gesture 1 — MUST be non-empty
insecure: true                      # ALB HTTP-only; CloudFront terminates TLS
# certificateArn: ""                # NOT used in CloudFront mode (CloudFront carries the cert)
hub:
  clusterName: <cluster>            # both scripts derive their names from this
aws:
  region: <region>                  # e.g. us-west-2
```

```bash
aws sts get-caller-identity         # confirm the target account
task install                        # idempotent & resumable; ~30–55 min
```

### Gesture 3 — attach your distribution to the ALB

```bash
# If your distribution's Comment == <cluster>-platform:
scripts/cloudfront-attach-origin.sh
# Otherwise point it at your Comment:
CF_COMMENT=<your-comment> scripts/cloudfront-attach-origin.sh
```

---

## Branch 2 — let the scripts create/reserve a distribution

### Gesture 1 — reserve the hostname

```bash
domain=$(scripts/cloudfront-reserve-domain.sh)
echo "$domain"      # the *.cloudfront.net hostname to paste into config
```

The script derives a durable `Comment` = `<cluster>-platform` (override with `CF_COMMENT`). If a
distribution with that `Comment` already exists it is **reused**; otherwise one is created with a
non‑resolvable placeholder origin (`PriceClass_100` by default, override with `CF_PRICE_CLASS`). The
hostname is the **last line of stdout**, so `$(...)` captures it cleanly.

### Gesture 2 — `config.local.yaml` + install

Same as Branch 1, with `domain:` set to the reserved hostname:

```yaml
# ── CloudFront exposure — Branch 2 (create/reserve) ─────────────────────────
domain: <hostname>.cloudfront.net   # output of cloudfront-reserve-domain.sh — MUST be non-empty
insecure: true
hub:
  clusterName: <cluster>
aws:
  region: <region>
```

```bash
aws sts get-caller-identity
task install
```

### Gesture 3 — attach

The default `Comment` already matches what was reserved, so no override is needed:

```bash
scripts/cloudfront-attach-origin.sh
```

---

## Mandatory order: reserve/resolve → install → attach

Each gesture depends on state produced by the previous one:

1. **Reserve/resolve the domain first.** `hub:seed` (during `task install`) requires a non‑empty
   `domain` and exits otherwise; the hostname is also wired into all derived config that ArgoCD
   applies right after install.
2. **`task install` next.** The install is what creates the internal ALB `<cluster>-platform` (via
   the AWS Load Balancer Controller, asynchronously ~1–3 min after the ingress reconciles).
3. **Attach last.** `cloudfront-attach-origin.sh` requires the ALB to exist (it waits up to 600 s,
   then fails). A CloudFront VPC origin can only point at an existing ALB.

---

## Verify

```bash
export KUBECONFIG=$PWD/private/kubeconfig
kubectl get applications -A          # platform apps Synced/Healthy
kubectl get ingress -A               # the ingress has an ALB address

# ALB is internal (not internet-facing) and active:
aws elbv2 describe-load-balancers --names <cluster>-platform --region <region> \
  --query 'LoadBalancers[0].[Scheme,State.Code]' --output text   # -> internal  active

# The platform answers through the CloudFront hostname (real content, not just 200):
curl -sS https://<hostname>.cloudfront.net/keycloak/realms/master   # -> a real Keycloak realm JSON
curl -sS -o /dev/null -w '%{http_code}\n' https://<hostname>.cloudfront.net
```

Intermittent errors between the attach and full CloudFront propagation are **expected**. If **all**
URLs hang (`curl 000`) after a later redeploy, the ALB was recreated and the VPC origin points at
nothing — just re‑run `scripts/cloudfront-attach-origin.sh`, which detects the drift and
re‑creates/swaps automatically.

---

## Security note

With `insecure: true` the ALB is **internal**, and CloudFront is the public edge. Treat every UI
behind it as internet‑exposed: ensure each enforces its own auth, and consider a WAF on the
distribution. If that WAF filters by source IP, add the NAT egress IPs of the hub and of OAP
spokes to its IP set, or in‑cluster SSO times out
([pitfall 1](../platform/alb-ip-allowlist.md#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes)). See the repo's [docs/platform/cloudfront-exposure.md](../platform/cloudfront-exposure.md)
for the full exposure design.

---

## Next

- Need your **own domain** with HTTPS on the ALB instead? Use the custom path —
  [custom-install.md](custom-install.md).
- Want spokes? See [custom-multi-account.md](custom-multi-account.md).
- A one‑command orchestration of reserve→install→attach is a possible **future** enhancement; it is
  intentionally **not** required for this procedure.
