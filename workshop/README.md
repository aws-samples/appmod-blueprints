# Platform Engineering on EKS — Workshop Installation

## Quick Start

```bash
cd workshop
./create-config.sh      # Step 1: generate config + create ALB + CloudFront
task install            # Step 2: full workshop installation
```

> Both commands are **idempotent** — safe to re-run after failures.

---

## Step 1 — `./create-config.sh`

Auto-detects your AWS environment and generates `config.local.yaml` at the repo root.

**What it does:**
1. Detects AWS region, account ID, IAM Identity Center instance, Developers group, admin role
2. Reads `ClusterProvider` from the CloudFormation stack parameter (or `CLUSTER_PROVIDER` env var)
3. **Reserves a CloudFront hostname** via `scripts/cloudfront-reserve-domain.sh` — creates a
   distribution with a placeholder origin, which returns its `d*.cloudfront.net` name in about
   a second and needs no VPC and no load balancer
4. Writes `config.local.yaml` with that hostname as a static `domain` plus `insecure: true`

The ALB is **not** created here. The platform's load balancer controller creates it during
`task install` (named `<clusterName>-platform` and `internal`, because `insecure: true`). The
distribution is pointed at it afterwards:

```bash
scripts/cloudfront-attach-origin.sh    # after task install
```

That ordering is deliberate. The platform needs its hostname at install time, but deriving the
hostname from infrastructure the install creates would be circular. Reserving the name up front
breaks the cycle, so `domain` is an ordinary static value and nothing has to resolve it
mid-install. See [docs/platform/cloudfront-exposure.md](../docs/platform/cloudfront-exposure.md).

**Environment overrides:**

| Variable | Default | Description |
|----------|---------|-------------|
| `FORCE` | `false` | Set to `true` to overwrite existing config |
| `CLUSTER_PROVIDER` | from CFN / `kind-kro-ack` | `kind-kro-ack` or `kind-crossplane` |
| `RESOURCE_PREFIX` | `peeks` | Prefix for all AWS resources |
| `REPO_URL` | appmod-blueprints GitHub URL | Platform repo to clone |
| `REPO_REVISION` | `$WORKSHOP_GIT_BRANCH` | Branch/tag of the platform repo |
| `HUB_VPC_ID` | from CDK bootstrap | IDE VPC ID (triggers ALB+CF creation) |
| `HUB_SUBNET_IDS` | from CDK bootstrap | Private subnet IDs for the ALB |
| `ADMIN_ROLE_NAME` | from `WS_PARTICIPANT_ROLE_ARN` | IAM role for cluster admin access |

---

## Step 2 — `task install`

Full workshop installation. Runs from the `workshop/` directory.

**Install sequence:**

| Phase | Task | Duration | Description |
|-------|------|----------|-------------|
| 1 | `gitlab:init-ec2` | ~2min | Wait for GitLab CE, create PAT, seed repos |
| 2 | `cd platform && task install` | ~15min | Platform black-box install: |
| | `hub:claim` | | Apply EksCluster (domainName from config ✅) |
| | `hub:wait-for-eks` | ~20min | Wait for hub EKS cluster ACTIVE |
| | `hub:authorize-ide-access` | | Add VPC CIDR → cluster SG :443 |
| | `hub:seed` | | Deploy ArgoCD, seed cluster secret |
| | `hub:wait-for-sync` | ~10min | Wait for addons synced, LBC adopts ALB ✅ |
| 3 | `set-overlay-repo` | ~1min | Wire fleet-config GitLab → hub ArgoCD |
| 4 | `spokes:enable-kro` × 2 | ~20min | Declare spoke-dev + spoke-prod via KRO |
| 5 | `ray:setup` | ~2min | Ray S3 bucket, ECR, IAM roles, build image |
| 6 | `post-install` | ~5min | IDC ↔ Keycloak SAML+SCIM federation |
| 7 | `ray:wait-image` | background | Wait for vLLM image build |
| 8 | `wait-for-spokes` | ~1min | Confirm spoke clusters ready |

**Total: ~60-70 minutes** on a fresh account.

---

## Troubleshooting

### Task install stopped after platform phase

Re-run `task install` — it's idempotent. The workshop steps (`set-overlay-repo`, `spokes:enable-kro`, `idc:configure`) will run from where it stopped.

### Keycloak not reachable / IDC skipped

The `idc:configure` pre-checks Keycloak (30s timeout). If 404, it skips with a warning.
Fix: ensure the LBC has reconciled the ALB (`kubectl get ingress -A` should show an ADDRESS).
Then run: `task idc:configure`

### Wrong clusterProvider (e.g. kind-crossplane instead of kind-kro-ack)

Re-run with explicit provider:
```bash
FORCE=true CLUSTER_PROVIDER=kind-kro-ack ./create-config.sh
task install
```

### Stale spoke values from previous run

```bash
git -C ~/environment/fleet-config pull
# Clear crossplane spoke values if using kro-ack:
echo "clusters: {}" > ~/environment/fleet-config/gitops/fleet/spoke-values/tenants/workshop/crossplane-clusters/values.yaml
git -C ~/environment/fleet-config add -A && git -C ~/environment/fleet-config commit -m "chore: clear stale crossplane spokes" && git -C ~/environment/fleet-config push
```
