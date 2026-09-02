# Design: ingress domain resolution (`domainResolver`)

How the platform obtains its ingress hostname, and why the mechanism is shaped the way it
is. Implemented on branch `feat/cluster-provider-parity-cloudfront`.

## Problem

The platform never provisions a domain. `config.yaml` has always said so: the ingress
hostname is "provisioned by YOU (Route53, CloudFront, etc.)". For a consumer with a
registered domain that is trivial — set `domain` and install.

It breaks down when the hostname **does not exist yet at install time**. The motivating
case is CloudFront: a consumer creates a distribution over the platform ALB, and its
`*.cloudfront.net` hostname is only known once the distribution has been created, which
takes 5–15 minutes. Two bad options follow:

- wait for it before installing — serialises 5–15 min in front of a ~20 min cluster build
- install without it — every addon that templates `ingress_domain_name` (keycloak,
  backstage, grafana, argo-workflows) renders against an empty host

The previous answer was a file, `private/async-domain`, that an external job wrote and the
provider polled. That worked but had three problems: it was only implemented on
`kind-kro-ack`, it made an internal path part of the consumer-facing contract, and a stale
file could silently override an explicitly configured `domain`.

## Requirements

1. `task install` stays the **single public command**. The platform is a black box with
   documented extension points, not a set of phases a consumer orchestrates.
2. The consumer's hostname provisioning must **overlap** the cluster build, not serialise
   in front of it.
3. Both cluster providers must behave identically — see
   [#833](https://github.com/aws-samples/appmod-blueprints/issues/833) for why capability
   asymmetry between providers is treated as a defect.
4. Never deploy with an empty domain. Fail loudly instead.
5. An explicitly configured `domain` must always win. No internal artifact may override it.

## Design

### Resolution order

| Order | Source | Notes |
|-------|--------|-------|
| 1 | `domain` in `config.local.yaml` | when set, the resolver is **not run** |
| 2 | `domainResolver` | a consumer command; result is written back into config |
| 3 | *(internal)* `private/async-domain` | back-compat only, see below |
| 4 | — | install **fails** with actionable guidance |

Items 1 and 2 are the entire public contract. Item 3 exists only for a `config.local.yaml`
written by an older `create-config.sh`; it is undocumented in `config.yaml` and
`config.schema.json`, and is removable without notice.

### The resolver contract

`domainResolver` is a path (repo-root-relative or absolute) to an executable that:

- **blocks** until the hostname is known, then exits 0
- prints the hostname as the **last non-empty line of stdout**
- puts progress output on stderr (leading stdout lines are discarded, so a chatty
  resolver still works, but stderr keeps it unambiguous)

The platform passes context via the environment so no arguments are needed and
`domainResolver` stays a plain path:

- `PLATFORM_CONFIG_FILE` — absolute path to `config.local.yaml`
- `PLATFORM_REPO_ROOT` — absolute path to the platform repo root

The returned value is validated against the same hostname pattern as
`config.schema.json`'s `domain` **before** being persisted. A malformed value fails at the
seam rather than surfacing much later as broken ingress and a bad OIDC issuer.

`scripts/resolve-cloudfront-domain.sh` is the shipped implementation, used by the in-repo
workshop and intended for external consumers. It finds the distribution by its `Comment`
(`<hub.clusterName>-platform`, matching what `create-config.sh` sets) rather than reading a
recorded id, so it is idempotent and survives the distribution or ALB being recreated. It
waits for the distribution to **exist**, not to be `Deployed`: `create-distribution`
returns `DomainName` immediately, and the platform only needs the hostname string.

### The domain seam

`install` is split at the first point that needs the domain:

```
init → kind:create → credentials:setup → crossplane:setup → hub:seed-infra
                                                                  │
                                            ─────── domain seam ──┤
                                                                  │
                            domain:resolve → _install:platform (hub:seed-platform → …)
```

Everything above the seam is domain-independent, **including the ~20 minute EKS build**
inside `hub:seed-infra`. Everything below needs it, starting with `secrets-manager:seed`,
which writes `ingress_domain_name` into `<hub>/config`.

Placing the seam here is what delivers requirement 2: by the time `domain:resolve` runs,
the consumer's CloudFront distribution has usually already been created, so the resolver
returns immediately.

`hub:seed` is retained as a wrapper (`hub:seed-infra` → `domain:resolve` →
`hub:seed-platform`) so direct invocations and documentation references still work.

Note that no addon can render before the domain exists regardless: `hub:apply-root-appset`,
which is when ArgoCD starts deploying addons, is the **last** step of `hub:seed-platform`,
six steps after `secrets-manager:seed`.

### Why the second phase is a separate process

This is the non-obvious part, and the reason the design looks the way it does.

**go-task evaluates global `vars:` with `sh:` exactly once, at parse time.** A task that
updates `config.local.yaml` cannot change `{{.DOMAIN}}` for the remainder of that process.
Verified:

```
BEFORE: DOMAIN=[]
config now: [d123.cloudfront.net]      <- task wrote it
AFTER (templated var): DOMAIN=[]       <- still empty
AFTER (runtime read):  DOMAIN=[d123.cloudfront.net]
```

So `domain:resolve` can resolve and persist the hostname, and every `{{.DOMAIN}}` consumer
in the same process still sees the pre-resolution value. There are four per provider:

| Provider | `{{.DOMAIN}}` consumers |
|---|---|
| `kind-crossplane` | `urls`, `INGRESS_DOMAIN` in `secrets-manager:seed`, the GitLab domain fallback, `KC_DOMAIN` |
| `kind-kro-ack` | the claim's `domainName`, `INGRESS_DOMAIN`, the GitLab fallback, `KC_DOMAIN` |

The alternative was converting all eight call sites to runtime shell reads and keeping them
that way forever. `kind-kro-ack` had already attempted this and converted only one
(`hub:seed`), leaving three reading the parse-time value — a latent bug in async mode.

Instead, the domain-dependent phase is invoked as a **nested `task` process**, a plain
shell command rather than a `task:` dependency:

```yaml
- |
  REPO_ROOT="{{.ROOT_DIR}}" \
    sh -c 'cd "$REPO_ROOT" && task <provider>:_install:platform'
```

A fresh process re-parses global vars, so `{{.DOMAIN}}` is correct everywhere with no
per-site changes. It also fixed kro-ack's three unconverted sites for free.

### Why `desc:` omission, not `internal: true`

The phase tasks must stay off the public surface (requirement 1) while remaining invocable
by the platform itself. `internal: true` does not work: go-task refuses to run an internal
task even when it is invoked from another task, which is what the nested-process approach
does.

Tasks **without a `desc:`** are hidden from `task --list` but remain invocable. So
`_install:platform`, `domain:resolve`, `hub:seed`, `hub:seed-infra` and `hub:seed-platform`
carry no `desc:`, and `task --list` still shows `install` as the entry point.

This is a convention, not an enforcement: someone reading the Taskfile can still call
`_install:platform` directly. A sentinel-var guard was considered and not implemented.

## Consumer model

`workshop/` is the reference consumer, and `workshop/Taskfile.yaml:28-30` describes the
pattern as "OAP-style": pin the platform via `platform.ref`/`platform.repo`, prepare the
artifact, then run its `task install` as a black box. An external consumer should be a
**sibling** of `workshop/`, not a caller of it — `workshop:install` is the full workshop
install (platform + GitLab + Ray + IDC federation) and assumes CDK-provisioned
prerequisites.

The workshop's own flow after this change:

1. `create-config.sh` creates the SG, internal ALB, listener, VPC origin and distribution
   in the background, and returns immediately.
2. It writes `domain: ""` plus `domainResolver: "scripts/resolve-cloudfront-domain.sh"`.
3. `task install` builds the cluster, then `domain:resolve` runs the resolver, which finds
   the distribution by `Comment`.

That removed the `WAIT_FOR_CF` dual mode, a PID-file/`kill -0` rejoin loop, `cf-domain.txt`,
the `private/async-domain` writes, and a **duplicate** `create-distribution` call site
(−84 net lines in `create-config.sh`).

### CloudFront requires a pre-existing VPC

An important ordering constraint for any consumer wanting CloudFront exposure:

CloudFront needs an origin → the origin is an internal ALB → the ALB must exist **before**
`task install` so the AWS Load Balancer Controller adopts rather than replaces it → the ALB
must be in the same VPC as the hub → therefore the consumer must create the VPC and pass
`hub.network.vpcId`.

`kind-kro-ack` supports that import; `kind-crossplane` does not
([#833](https://github.com/aws-samples/appmod-blueprints/issues/833)). `kind-crossplane`
now **fails pre-flight** if `hub.network.vpcId` is set, rather than silently creating a
second VPC and leaving CloudFront pointed at an unusable ALB.

`insecure: true` is also required with CloudFront, since CloudFront terminates TLS and the
ALB must serve plain HTTP. `domain:resolve` warns (does not fail) when it resolves a
`*.cloudfront.net` hostname while `insecure` is false.

## Traps encountered

Recorded because each failed **silently** and each is easy to reintroduce. See
[#836](https://github.com/aws-samples/appmod-blueprints/issues/836) for the underlying
shell-in-YAML tech debt.

1. **`errexit` + `&&`.** Under go-task's mvdan/sh, a failing `[ ... ] && cmd` as the last
   statement of a block makes the enclosing compound return non-zero and aborts the script.
   The first `domain:resolve` exited 1 before printing any of its six diagnostic lines; the
   same script ran correctly under `bash -e`. These scripts use explicit `if` only.
2. **Background jobs are killed.** `( ... ) &` in a `cmds:` block is terminated when the
   task body exits — verified that the redirect target was never even created, so
   `install:phase1-observability-bg` never ran its 30+ minute AMP seed on either provider.
   Fixed with a double-fork (`sh -c '... &'`).
3. **`yq '.domain'` returns the string `"null"`** for a missing key. Non-empty, so it
   defeated `[ -z ... ]` guards; `ingress_domain_name: "null"` could reach the cluster
   secret. Every read normalises with `// ""` plus an explicit `"null"` check.
4. **`{{.ROOT_DIR}}` was believed to expand empty in a backgrounded subshell.** It does
   not; templating precedes shell execution. The workshop env vars added to work around
   this were unnecessary and wrong on any non-workshop machine.

## Verification

Verified by running, with heavy tasks stubbed (11/11):

- both providers parse; `domain:resolve` byte-identical across them
- `domain` in config wins and the resolver is not run
- a chatty resolver resolves to its last non-empty line
- malformed resolver output is rejected before being persisted
- a resolver printing nothing gets a distinct error
- the internal file fallback resolves, and is polled only when the file exists
- no domain at all fails immediately with guidance
- `*.cloudfront.net` + `insecure: false` warns and proceeds
- the `hub.network.vpcId` guard fires, and clears when unset
- `scripts/resolve-cloudfront-domain.sh` prints only the hostname on stdout, exits 2 on
  timeout naming the provisioning log, exits 1 on a missing prerequisite

**Not** verified: no real EKS cluster or CloudFront distribution has been provisioned
against this branch. `create-config.sh`'s CloudFront path in particular cannot be exercised
outside a Workshop-Studio-like environment, and is validated by pointing a workshop branch
at this branch.

## Open items

- A failed background distribution creation now surfaces as a `domain:resolve` timeout
  naming the log, rather than being retried from a second code path. That duplicate path
  was the drift risk being removed, but it is a behaviour change.
- `subnetIds[2]` is written by `create-config.sh` but ignored by the provider, which reads
  only `[0]` and `[1]`. Unclear whether the 2-AZ limit is intentional.
- The `desc:`-omission convention is not enforced.
