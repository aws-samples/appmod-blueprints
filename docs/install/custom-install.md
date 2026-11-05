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

# REQUIRED (true) when another hub runs in the same AWS account, or when the fleet repo is a
# fork / shared by several hubs -> see section 3a. Set it BEFORE the first install.
fleetScopeByPrefix: false

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

**Restricting the ALB by source IP (optional, own‑domain mode).** The `inboundCidrs` allowlist
is set after install from your fleet repo, see
[Restrict the platform ALB by source IP](../platform/alb-ip-allowlist.md). It must include the
NAT egress IPs of the hub and of OAP spokes (`<nat-eip>/32`), re‑checked after each reinstall,
or SSO breaks ([pitfall 1](../platform/alb-ip-allowlist.md#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes)).

---

## 3a. Shared account or forked fleet repo: scope the fleet

> [!WARNING]
> **Set `fleetScopeByPrefix: true` and a unique, non-empty `resourcePrefix` BEFORE the first
> install** if any of these is true:
>
> - another hub (any install of this platform) already runs in the **same AWS account**;
> - your fleet repo is a **fork** of another hub's fleet repo, or a branch of it, and still carries
>   that hub's spoke entries;
> - several hubs read the **same** fleet repo (for example the public example repo of
>   [quick-existing-fleet.md](quick-existing-fleet.md)).
>
> The key is off by default. A hub without it provisions **every** spoke entry it finds in the
> fleet repo, including the spokes of other hubs.

### What happens without it

The `clusters-kro` ApplicationSet creates one `EksclusterWithVpc` per marker file
`fleet/spoke-values/tenants/*/kro-clusters/clusters/*.json`. The EKS cluster of that graph is
declared with `services.k8s.aws/adoption-policy: adopt-or-create`, and its `deletionPolicy`
defaults to `delete`. The same misconfiguration fails in one of two ways, depending on whether
the other hub's spoke already exists when this hub reconciles the entry:

| Form | When | What this hub does | Main damage |
|---|---|---|---|
| **Adoption** | The other hub's spoke already exists | Adopts the existing EKS cluster and name-keyed resources, duplicates the rest | Its teardown deletes the other hub's clusters |
| **Name preemption** | The other hub's spoke does not exist yet | Creates the spoke under the names generated for it | The other hub's install fails on names already taken |

**Name preemption is the most likely form on a new account**, or on any account where the other
hub has not installed its spokes yet: whichever hub reconciles a spoke entry first takes the
names.

#### Form 1: adoption

When the marker names a spoke that another hub already created in the same account and region:

1. **ACK adopts the existing EKS cluster** (same name) instead of failing, with
   `deletion-policy: delete`, and so do the name-keyed resources of the graph that already exist
   (IAM roles, OIDC provider, access entries). The new hub now owns resources it did not create.
2. What ACK cannot find by name is created again: a **duplicate VPC** (same name, same CIDR), NAT
   gateways, Elastic IPs, subnets, route tables, and any IAM role whose name does not exist yet.
   One incident counted about a hundred duplicate AWS resources for two spokes.
3. ACK keeps trying to move the adopted cluster onto the new subnets. EKS rejects the update, so
   the resources stay in an error loop.
4. **Any delete on the new hub deletes the original clusters**: pruning its spoke Application,
   [delete-spoke.md](delete-spoke.md), or `task destroy`.

#### Form 2: name preemption

When the marker names a spoke that the other hub has not created yet, there is nothing to adopt.
This hub **creates** the whole spoke graph under the names generated for that spoke: the EKS
cluster, its VPC, subnets, NAT gateways and Elastic IPs, the `<spoke>-*` IAM roles, the OIDC
provider, access entries and Pod Identity associations.

1. **The legitimate install fails later.** When the other hub reconciles its own entry, every
   name-keyed resource already exists. Depending on the resource, its ACK controller either
   reports a conflict (`AlreadyExists`, `EntityAlreadyExists`, `ResourceInUseException`) or adopts
   the resource that this hub created, so the two hubs end up managing the same resources.
2. **The resources look legitimate.** They carry the names the other hub expects, so nothing in
   their names tells you which hub created them, and a quick look at the account suggests the
   other hub's spokes are installed.
3. **Cleanup is harder than for adoption.** The resources have the right names but belong to the
   wrong hub: deleting them by name may delete what the other hub has started to adopt, and
   leaving them blocks the other hub. Their deletion policy is `delete` on this hub, so any delete
   on this hub removes them, even after the other hub depends on them.
4. The preempting hub also consumes per-region quotas (VPCs, Elastic IPs, NAT gateways), which
   can make the other hub's install fail for a reason unrelated to names.

The same applies to `fleet/members/*/values.yaml`, which registers clusters with this hub's ArgoCD.

### How scoping works

With `fleetScopeByPrefix: true`, `hub:seed` stamps `fleet_scope_by_prefix: "true"` on the hub's
cluster-secret, and the hub only reads its own sub-directory:

| Without scoping (default) | With `fleetScopeByPrefix: true` |
|---|---|
| `fleet/spoke-values/tenants/<tenant>/kro-clusters/clusters/<name>.json` | `fleet/spoke-values/tenants/<tenant>/kro-clusters/clusters/<resourcePrefix>/<name>.json` |
| `fleet/members/<name>/values.yaml` | `fleet/members/<resourcePrefix>/<name>/values.yaml` |

Rules that go with it:

- **`resourcePrefix` must be unique per hub and non-empty.** With an empty prefix the template
  inserts no segment and the hub falls back to the flat layout, so it is not scoped at all.
- **Spoke names must still be unique in the account and region.** Scoping limits what a hub
  reads; it does not rename anything. Two hubs that each declare a spoke `dev` still target the
  same EKS cluster. Give spokes distinct names (for example `<prefix>-dev`).
- **Remove the entries you inherited** from a forked fleet repo (markers, specs in
  `kro-clusters/values.yaml`, members) before the install, even with scoping on.
- **Write your markers and members under the prefix directory.** The generative
  `spokes:enable-kro` task and the Backstage EKS cluster template write the flat layout; with
  scoping on, move what they write under `<resourcePrefix>/`.
- The flag is sticky: a value set on `<hub>/config` is kept on re-seed. To turn it off, remove
  the key from `<hub>/config` too ([kind-kro-ack README](../../cluster-providers/kind-kro-ack/README.md#multi-hub-fleet-scoping-opt-in)).

### If a hub has already adopted or preempted another hub's spokes

First find out which form you have. For each spoke entry that belongs to another hub, check
whether that spoke existed before this hub reconciled it: compare the cluster's `createdAt`
(`aws eks describe-cluster`) and the creator of `CreateCluster` in CloudTrail (step 3 of the
preemption procedure) with the time this hub first synced the entry. If the spoke existed,
follow the adoption procedure; if it did not, follow the preemption procedure. In both cases, do **not** run `task destroy`,
[delete-spoke.md](delete-spoke.md) or a pruning sync on the misconfigured hub first: each of
them deletes resources that may belong to, or be needed by, the other hub.

#### Adoption: retain, then disengage

Do **not** run `task destroy`, [delete-spoke.md](delete-spoke.md) or a pruning sync on the hub
that adopted the spokes: each of them would delete the original clusters. In this order:

1. **Retain first.** In the fleet branch that this hub reads, set `deletionPolicy: retain` on each
   adopted entry of `fleet/spoke-values/tenants/<tenant>/kro-clusters/values.yaml`, push, and let
   ArgoCD sync. Check that every ACK resource of the spoke now carries the retain annotation
   before going further:

   ```bash
   SPOKE=<spoke-name>
   for k in $(kubectl api-resources --namespaced -o name | grep 'services.k8s.aws$'); do
     kubectl get "$k" -n "$SPOKE" -o jsonpath='{range .items[*]}{.kind}/{.metadata.name} {.metadata.annotations.services\.k8s\.aws/deletion-policy}{"\n"}{end}'
   done
   ```

2. **Record the IDs of the duplicates** while the ACK resources still exist: the VPC, subnet, NAT
   gateway, Elastic IP and route table IDs from each resource's `.status` (for example
   `.status.vpcID`, or `.status.ackResourceMetadata.arn`). Compare them with the original
   cluster's VPC (`aws eks describe-cluster --name <spoke> --query cluster.resourcesVpcConfig`):
   the original resources are the ones the cluster uses.
3. **Remove the entries** (spec, marker, member) from that fleet branch and prune, as in
   [delete-spoke.md](delete-spoke.md). With `retain`, ACK leaves every AWS resource in place.
4. **Delete the duplicates by ID only**, from the list of step 2. Never select them by name, tag
   or CIDR: the duplicates carry the same name, CIDR and tags as the originals. An IAM role whose
   name matches an existing role is the original role, adopted, not a copy: keep it.
5. Turn on `fleetScopeByPrefix` with a unique `resourcePrefix` on that hub before declaring its
   own spokes again.

#### Name preemption: identify the owner before any deletion

The resources carry the expected names, so the name never tells you who created them. Establish
the owner of each resource **before** deleting anything, and stop the misconfigured hub from
changing them while you do:

1. **Freeze the misconfigured hub.** Set `deletionPolicy: retain` on the entries it preempted,
   push, sync, and check the retain annotation as in step 1 of the adoption procedure. Then
   remove those entries from the fleet branch it reads, so that it stops reconciling them. With
   `retain`, ACK leaves the AWS resources in place.
2. **Read the tags.** The graphs tag the cluster, VPC, NAT gateways and Elastic IPs with
   `platform.gitops.io/prefix` and `platform.gitops.io/cluster`, plus the hub's `platformTags`, and
   ACK adds its own controller tags (`services.k8s.aws/*`). The prefix tag comes from the entry's
   `resourcePrefix` when the entry sets one, otherwise from the hub's: a forked entry that pins
   the other hub's prefix produces the same tags on both hubs. Tags are therefore a hint, not a
   proof. Compare them with the values of each hub:

   ```bash
   aws eks describe-cluster --name <spoke> --query cluster.tags
   aws ec2 describe-vpcs --filters Name=tag:Name,Values=<spoke>* --query 'Vpcs[].{id:VpcId,tags:Tags}'
   aws iam list-role-tags --role-name <spoke>-<suffix>
   ```

3. **Check the creator in CloudTrail.** Tags can be copied or missing, so confirm with the
   identity that called the create API (`CreateCluster`, `CreateVpc`, `CreateRole`, ...). The
   principal is the ACK controller's role (or the credentials) of one hub; match it with the role
   that hub's ACK controllers use:

   ```bash
   aws cloudtrail lookup-events \
     --lookup-attributes AttributeKey=ResourceName,AttributeValue=<spoke> \
     --query 'Events[?EventName==`CreateCluster`].{time:EventTime,user:Username,event:CloudTrailEvent}'
   ```

   CloudTrail event history covers the last 90 days in the region of the call (IAM calls are
   recorded in `us-east-1`). For older resources, query the trail logs instead.
4. **Decide per resource, by ID.** A resource created by the misconfigured hub and not yet used
   by the other hub can be deleted, by ID only, so that the other hub can create its own. A
   resource the other hub has already adopted or depends on stays: hand it over to that hub
   (its own entry, with its own deletion policy) instead of deleting it. Never select resources
   by name, tag or CIDR alone.
5. Re-run the other hub's install, then turn on `fleetScopeByPrefix` with a unique
   `resourcePrefix` on the misconfigured hub before declaring its own spokes again.

### Stopping the bootstrap reconciler vs running a destroy target

Stopping the kind bootstrap cluster and running a destroy target look alike, but they have
opposite effects on AWS (kind-kro-ack provider, `cluster-providers/kind-kro-ack/Taskfile.yaml`):

- **Safe: these only remove the kind reconciler.** `docker stop` on the kind nodes,
  `kind delete cluster` and `task destroy-kind` (which runs only `kind delete cluster`) issue no
  AWS delete. No custom resource is gracefully deleted, so the ACK finalizers never run: the AWS
  resources stay in place and are simply no longer reconciled from kind. `docker stop` is
  recoverable; starting the nodes again resumes reconciliation of the spec kind holds.
  `hub:update` also ends with `task destroy-kind`.
- **Destructive by design: `task destroy` and `task hub:destroy-addons`.** `hub:destroy-addons`
  runs against the **hub** EKS cluster (`private/hub-kubeconfig`), not kind. It deletes the
  ApplicationSets, then every Application in `argocd`, while the hub controllers are still
  running, so that ACK, kro and Crossplane delete the AWS resources they manage, spoke clusters
  included. `task destroy` sets the hub's `deletionPolicy` back to `delete`, deletes kind, runs
  `hub:destroy-addons`, then deletes the hub through the AWS API. Never run either of them to
  "just stop kind", and never run them on a hub that has adopted or preempted another hub's
  resources (see above): they would delete those resources too.
- **What `task destroy` protects, and what it does not.** It sets `deletionPolicy: delete` only on
  the hub's own kro instance. It never changes the policy of a spoke. `hub:destroy-addons` then
  deletes, with cascade, every Application on the hub, including the `clusters-kro` ApplicationSet
  and its `clusters-kro-<member>` Applications. Every member still in the hub's fleet, including
  another hub's spoke adopted by mistake, is then protected only by its own
  `deletionPolicy: retain`; with `delete`, the default, ACK deletes it. Before any destroy, remove
  foreign members from the fleet branch explicitly, one at a time, and check that the hub no
  longer has their `clusters-kro-<member>` Application.
- **The destroy does not infer ownership.** To exclude a member from a destroy, mark it
  `deletionPolicy: retain` or remove it before running destroy. Do not extend the hub's
  retain->delete flip to members.

> [!NOTE]
> Before you run a task, read what it executes (`task --summary <name>`, or its `cmds:` in the
> Taskfile). A similar name is not enough: `destroy-kind` and `destroy` differ by one word and
> by the whole fleet.

A generator that is too broad applies a correct chain to someone else's resources, and for a
spoke that chain ends in a deletion. This is why `fleetScopeByPrefix` is a safety setting, not a
tidiness one.

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
