# Exposure architecture — CloudFront / ALB / per-app routing

> **Status**: design proposal extending the bootstrap work landed on
> [`feature/platform-cluster-kro-ack`](https://github.com/aws-samples/appmod-blueprints/tree/feature/platform-cluster-kro-ack)
> (PR #642 family). This document is **not yet code** — it freezes the
> architecture that the upcoming `AppExposure` RGD (PR 2) and `prod-public`
> mode (PR 3) will implement.
>
> Audience: platform engineers operating PeEKS clusters, blog drafters,
> reviewers of follow-up PRs.

## TL;DR

- One **shared edge** (CloudFront → ALB) per cluster, provisioned in **Phase 0**
  (out-of-band) by the kind-kro-ack bootstrap. Already mostly done by
  `task hub:ingress` + `task hub:cloudfront`.
- Apps expose themselves in **Phase 1** (GitOps) through a single CRD —
  `AppExposure` — that fans out to ACK ELBv2 `TargetGroup` + `ListenerRule`
  and AWS LBC `TargetGroupBinding`. **No `Ingress` resource** in this path.
- The shared-edge URL is published into the **ArgoCD cluster Secret** so
  ApplicationSets templating downstream apps (Keycloak issuer URL, Backstage
  `app.baseUrl`, …) can read it without chicken-and-egg.
- Three modes covered by the same RGD: `workshop-studio` (CloudFront cert on
  `*.cloudfront.net`, no public domain required), `prod-public` (your domain
  + ACM + Route53), `internal-only` (ALB internal + private Route53, no CF).

## 1. Why this design

### Previous architecture (pre-PR #642)

```
client ─HTTPS─► CloudFront ─HTTP/HTTPS─► NLB (internet-facing)
                                          │
                                          ▼
                                       nginx Ingress Controller pods
                                          │
                                          ▼
                                       app pods
```

Issues:
- nginx Ingress doubles L7 routing the ALB can do natively → extra hop, extra
  pods to operate, extra failure domain.
- NLB→nginx target type `instance` requires NodePort + kube-proxy hop.
- nginx config drift: rewrite rules, auth filters, rate limits scattered
  across `nginx.ingress.kubernetes.io/*` annotations.
- Hard to share the same edge across multiple apps cleanly when each app
  brings its own nginx-flavored annotations.

### New architecture (PR #642 + this proposal)

```
client ─HTTPS─► CloudFront ─HTTP─► ALB (internet-facing or VPC Origin)
                                    │
                                    │ Listener :80 or :443
                                    │   ├── ListenerRule host=keycloak.* → TG-keycloak
                                    │   ├── ListenerRule host=backstage.* → TG-backstage
                                    │   └── ListenerRule path=/api/*      → TG-api
                                    ▼
                                 pods (TargetGroupBinding, target type ip)
```

Wins:
- ALB does L7 routing natively. nginx is gone.
- Target type `ip` → CF/ALB talk directly to pod IPs via VPC CNI. No
  NodePort hop.
- ACK manages the AWS resources declaratively (TG + Rule), AWS LBC manages
  the pod-to-TG sync (TGB). Two responsibilities, two CRDs, no overlap.
- Shared ALB: every app shares one Listener, just adds a Rule. Quota: 100
  rules per ALB by default — plenty for a workshop or a small platform.

## 2. Two-phase bootstrap

The chicken-and-egg problem: **ArgoCD ApplicationSets need the public URL of
the cluster** (Keycloak `KC_HOSTNAME`, Backstage `app.baseUrl`, OAuth
callbacks, etc.) to template app manifests correctly. That URL only exists
once the edge (CloudFront + ALB) is created. Resolving it: **the edge is
created before ArgoCD takes over**.

### Phase 0 — out-of-band bootstrap

Driven by `cluster-providers/kind-kro-ack/Taskfile.yaml` (or any equivalent
Terraform / CFN / Crossplane provider). Order:

1. `task install` brings up the kind bootstrap cluster, installs ACK + KRO,
   applies the `EksclusterWithVpc` RGD instance.
2. ACK provisions VPC + EKS Auto Mode + IAM (15–25 min).
3. `task hub:ingress` — creates ALB + Security Group via raw AWS CLI (not
   ACK, see "ACK gap" below). Already implemented.
4. `task hub:cloudfront` — creates CloudFront distribution, origin = ALB
   DNS, viewer cert = AWS-managed `*.cloudfront.net`. Already implemented.
   Writes `cloudfront.domain` back to `config.local.yaml`.
5. `task hub:seed-secret` — applies the ArgoCD `cluster` Secret. **Gap to
   close: the Secret must carry the edge URL + ALB ARN as annotations so
   downstream ApplicationSets can read them.**
6. `task hub:apply-root-appset` — ArgoCD takes over.

The kind cluster is destroyed afterwards (`task destroy-kind`). All AWS
resources persist; reconciliation moves to the in-cluster ACK + AWS LBC
controllers installed by ArgoCD addons.

### Phase 1 — GitOps reconciliation

ArgoCD ApplicationSets read the cluster Secret annotations and template app
manifests with the right hostname / base path. Per-app exposure resources
(`AppExposure` CR) are committed to the GitOps repo and reconciled into
ACK + LBC CRDs.

### Phase boundary — what crosses

The **only** information that crosses Phase 0 → Phase 1 is the cluster
Secret. Everything else (CRD reconciliation, app deployment, addon config)
is GitOps. This is the same boundary the gitops-bridge chart formalizes
elsewhere in this repo — we are simply extending its annotations.

## 3. Cluster Secret contract

The current `hub:seed-secret` task in `cluster-providers/kind-kro-ack/Taskfile.yaml`
writes annotations for `addonsRepoURL`, `fleetRepoURL`, `aws_cluster_name`.
We extend it with edge metadata:

```yaml
apiVersion: v1
kind: Secret
type: Opaque
metadata:
  name: hub
  namespace: argocd
  annotations:
    # Existing (PR #642)
    addonsRepoURL: "https://github.com/<org>/appmod-blueprints"
    addonsRepoRevision: "<sha>"
    addonsRepoBasepath: "gitops/addons/"
    fleetRepoURL: "..."
    fleetRepoRevision: "..."
    fleetRepoBasepath: "gitops/fleet/"
    aws_cluster_name: hub

    # NEW — exposure metadata
    peeks.io/exposure-mode: "workshop-studio"        # workshop-studio | prod-public | internal-only
    peeks.io/edge-domain: "d1234abc.cloudfront.net"  # CloudFront domain (always set when CF in use)
    peeks.io/edge-domain-public: ""                  # set in prod-public mode (e.g. "apps.peeks.example.com")
    peeks.io/edge-scheme: "https"                    # what clients see
    peeks.io/alb-arn: "arn:aws:elasticloadbalancing:eu-west-1:...:loadbalancer/app/hub-ingress/..."
    peeks.io/alb-listener-arn: "arn:aws:...:listener/..."   # The HTTP:80 listener (or HTTPS:443 in prod-public)
    peeks.io/alb-vpc-id: "vpc-xxxxxxxx"
    peeks.io/cloudfront-distribution-id: "E1ABCDEF1234"
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: control-plane
    fleet_member: control-plane
stringData:
  name: hub
  server: "<EKS cluster ARN — workshop ArgoCD Capability mode>"
  config: '{"awsAuthConfig":{"clusterName":"hub","roleARN":"<argocd-role-arn>"},"tlsClientConfig":{"insecure":false}}'
```

**Annotation lookup pattern** (used by both ApplicationSets and the
`AppExposure` RGD):

```yaml
# In an ApplicationSet generator — Cluster generator with Secret
# templating
template:
  spec:
    source:
      helm:
        values: |
          ingress:
            host: keycloak.{{.metadata.annotations.peeks.io/edge-domain}}
          # or for path-based (workshop-studio mode):
          baseUrl: https://{{.metadata.annotations.peeks.io/edge-domain}}/keycloak
```

The `AppExposure` RGD resolves `peeks.io/alb-listener-arn` from the cluster
Secret to know which Listener to attach its `ListenerRule` to.

## 4. The three exposure modes

The same `AppExposure` CRD covers all three. The mode is selected by a
single field; the RGD branches resource creation accordingly.

### Mode A — `workshop-studio`

**Constraint**: no public domain, no ACM cert. Used by AWS Workshop Studio
labs and any sandbox where you cannot register a domain.

**Trick**: CloudFront ships with a free, valid HTTPS cert on
`*.cloudfront.net`. Clients see HTTPS; CF→ALB is HTTP. No cert needed on
the ALB.

```
client ─HTTPS─► CloudFront (cert *.cloudfront.net) ─HTTP─► ALB :80
                                                            │
                                                            ▼
                                                          pods
```

- **CloudFront**: 1 distribution, viewer cert auto, origin = ALB DNS,
  protocol policy `http-only`. Already implemented by `hub:cloudfront`.
- **ALB**: internet-facing, listener :80 only, default action 404. PR #642
  uses this layout (commit `b332f081` "ingress listen on HTTP:80,
  CloudFront terminates TLS").
- **Routing**: **path-based only** (single CF domain, can't host-shard).
  Apps must support a base path. Compatibility checklist:
  - Keycloak: `KC_HTTP_RELATIVE_PATH=/keycloak` ✓
  - Backstage: `app.baseUrl=https://${edge-domain}/backstage` ✓
  - ArgoCD UI: `--rootpath /argocd` ✓
  - Generic apps with hardcoded `/` paths: ✗ — keep them out of the shared
    edge or fork.
- **Access from outside the VPC**: HTTPS on `dXXX.cloudfront.net`.
- **Direct ALB access**: still possible (ALB is internet-facing) but
  **must be locked down** by SG → see security note below.

**Security note**: in this mode the ALB is internet-facing and accepts
plain HTTP. Anyone bypassing CloudFront can hit the apps directly. Two
mitigations, in order of strength:

1. **Mandatory** for any non-toy use: WAF rule on the ALB requiring a
   custom header injected by CloudFront (e.g. `X-CF-Secret`). Not yet
   implemented in PR #642 — to add in PR 3 of this series.
2. Stronger: switch to `internal-only` mode + CloudFront VPC Origins
   (see Mode C). VPC Origins removes the public ALB entirely. Requires
   the AWS-managed `CloudFront-VPCOrigins-Service-SG` to be authorized
   on the ALB SG (already documented in PR #644 work).

### Mode B — `prod-public`

**Constraint**: you own a public domain (e.g. `peeks.example.com`) with a
Route53 public hosted zone.

```
client ─HTTPS(your-cert)─► CloudFront (cert ACM us-east-1)
                              │
                              ▼
client ──── HTTPS(your-cert)─► ALB :443 (cert ACM eu-west-1)
                              │
                              ▼
                           pods
```

- **Two ACM certs** for the same domain set:
  - One in **us-east-1** (CloudFront viewer cert — only us-east-1 is
    accepted by CF).
  - One in the **ALB region** (ALB listener cert).
  - Both DNS-validated through Route53. The validation `CNAME` records can
    be managed by ACK Route53 in the same RGD as the cert (KRO chains the
    dependency).
- **CloudFront**: same distribution as mode A but with viewer cert ARN +
  alternate domain names (`Aliases`) set to your public hostname.
- **ALB**: internet-facing, listener :443 with the eu-west-1 cert,
  listener :80 with a 301 redirect to :443.
- **Route53 public**: alias A record `apps.peeks.example.com` → CF
  distribution, alternative SAN records as needed.
- **Routing**: host-based becomes practical (one wildcard cert
  `*.peeks.example.com`, host-shard apps as `keycloak.peeks.example.com`).
  Path-based still supported.
- **Security note**: in this mode the WAF header secret is still
  recommended (defense in depth) — same pattern as mode A. The ALB DNS
  itself remains discoverable.

### Mode C — `internal-only`

**Constraint**: no internet-facing edge desired. ALB internal, no
CloudFront. Access is from within the VPC (Cloud9 IDE, bastion, VPN,
Direct Connect).

```
in-VPC client ─HTTP/HTTPS─► ALB internal
                              │
                              ▼
                           pods
```

- **No CloudFront**.
- **ALB**: internal scheme, listener :80 (plus :443 if you have an ACM
  private CA cert via ACM PCA — rarely worth the complexity).
- **Route53 private**: hosted zone `peeks.internal` (or any private
  domain), alias A record `apps.peeks.internal` → ALB DNS. Created via
  ACK Route53 alongside the ALB.
- **Routing**: host-based works (private DNS, free wildcards).
- **Use cases**: workshops where Cloud9 is the access point, internal
  platforms with no public exposure, regulated environments.

### Mode comparison

| Aspect | `workshop-studio` | `prod-public` | `internal-only` |
|---|---|---|---|
| Public DNS required | No | Yes | No |
| CloudFront | Yes | Yes | No |
| ALB scheme | internet-facing | internet-facing | internal |
| ALB listener | :80 HTTP | :443 HTTPS + :80→443 | :80 HTTP (or :443 PCA) |
| ACM cert | None | 2 (us-east-1 + region) | Optional (private CA) |
| Routing | Path-based | Host or path | Host or path |
| Client TLS | CF cert `*.cloudfront.net` | Your domain | None / private |
| Status | PR #642 implements (no WAF) | PR 3 of this series | PR 3 (optional) |

## 5. The `AppExposure` CRD (Phase 1)

A single ResourceGraphDefinition (RGD) that an app team includes in its
GitOps repo. The RGD reads the cluster Secret to learn the edge layout,
emits the right ACK + LBC CRs.

### Claim shape

```yaml
apiVersion: peeks.io/v1alpha1
kind: AppExposure
metadata:
  name: keycloak
  namespace: keycloak
spec:
  service:
    name: keycloak-svc      # Service in the same namespace
    port: 8080
  routing:
    # Mode A (workshop-studio): use path
    path: /keycloak
    # Mode B (prod-public): use host
    # host: keycloak.peeks.example.com
  healthCheck:
    path: /keycloak/health/ready
    intervalSec: 30
    healthyThreshold: 2
  protocol: HTTP            # HTTP | HTTPS | GRPC | HTTP2
  # Optional — defaults to whatever the cluster Secret says
  edgeRefOverride: ""       # only set if you want a non-default ALB
```

### Reconciliation graph

```
AppExposure CR
   │
   ▼
┌─ TargetGroup (ACK ELBv2) ──────────────────────────┐
│  spec:                                              │
│    targetType: ip                                   │
│    protocol: ${spec.protocol}                       │
│    port: ${spec.service.port}                       │
│    vpcID: ${cluster-secret.alb-vpc-id}              │
│    healthCheckPath: ${spec.healthCheck.path}        │
└────────────────────────────────────────────────────┘
   │ (status.ackResourceMetadata.arn)
   ▼
┌─ ListenerRule (ACK ELBv2) ─────────────────────────┐
│  spec:                                              │
│    listenerARN: ${cluster-secret.alb-listener-arn}  │
│    priority: <hash of name, 1000-49999>             │
│    conditions: [path or host based on routing]      │
│    actions:                                         │
│      - type: forward                                │
│        targetGroupARN: ${tg.status.ackResourceMetadata.arn}
└────────────────────────────────────────────────────┘
   │
   ▼
┌─ TargetGroupBinding (AWS LBC) ─────────────────────┐
│  spec:                                              │
│    serviceRef:                                      │
│      name: ${spec.service.name}                     │
│      port: ${spec.service.port}                     │
│    targetGroupARN: ${tg.status.ackResourceMetadata.arn}
│    targetType: ip                                   │
└────────────────────────────────────────────────────┘
```

Mode-A only: a CloudFront `CacheBehavior` is patched onto the shared
distribution (path → ALB origin). Optional, can be skipped if the default
behavior catches everything (path-based routing on a single origin).

### Why KRO matters here

`TargetGroupBinding` requires the TG to **exist and be reconciled**
(status populated with the ARN) before it can bind. KRO's CEL-based
expression engine waits for `targetgroup.status.ackResourceMetadata.arn`
to be non-empty before instantiating the TGB. Without KRO, you write a
post-create script that polls for the ARN — works but reintroduces the
imperative coupling we are removing from nginx.

Same dependency chain for `ListenerRule`: it references the TG ARN +
listener ARN; KRO orders it after the TG.

### Priority allocation

Listener rules need an integer priority (1–50000, lower = first match).
For a shared listener with N apps, two strategies:

1. **Hash of name into [1000, 49999]** — collisions detected by ACK at
   apply time, easy to reason about. Simpler for the workshop scope.
2. **Explicit priority field** in the claim, default to hash. Ops team
   takes over when multiple apps need a specific evaluation order.

The RGD will start with strategy 1 and expose an override field for
strategy 2.

### What `AppExposure` does NOT do

- Does **not** create the ALB or the Listener — those are Phase 0
  resources, shared, owned by the platform.
- Does **not** create the CloudFront distribution — same reason.
- Does **not** create ACM certs in mode A (CloudFront has its own).
- Does **not** manage DNS records — Route53 records are in Phase 0
  (private zone) or in mode B's RGD (public alias).
- Does **not** install AWS LBC — that's an addon installed by ArgoCD
  (already in PR #642 via `enable_ingress_class_alb` flag on the
  `EksCluster` RGD).

Tight scope, so the RGD stays maintainable and reviewable.

## 6. Gaps in current PR #642 implementation

This document is forward-looking. Things `feature/platform-cluster-kro-ack`
does **not** yet do, that the next PRs will close:

### Gap 1 — cluster Secret enrichment

`hub:seed-secret` writes addons/fleet repo annotations but no edge
metadata. CloudFront domain is captured in `config.local.yaml` (yq write
in `hub:cloudfront`), never propagated to the cluster Secret. ApplicationSets
templating Keycloak / Backstage have to either hard-code the domain or
rely on environment-specific value files — unsustainable across modes.

**Fix (PR 2)**: extend `hub:seed-secret` to read the ALB ARN, ALB
listener ARN, CloudFront domain + distribution ID, and the chosen
exposure mode, then write them as `peeks.io/*` annotations on the
cluster Secret. The full annotation contract is defined in §3 above.

### Gap 2 — `AppExposure` RGD does not exist

PR #642 ships RGDs for `EksclusterWithVpc`, `BackupPolicy`, etc., but
nothing for per-app exposure. Apps that need exposure today either use
ingress-nginx (legacy) or write raw `Ingress` resources picked up by AWS
LBC.

**Fix (PR 2)**: add `gitops/addons/charts/kro/resource-groups/manifests/app-exposure/rgd-app-exposure.yaml`
implementing the graph described in §5.

### Gap 3 — WAF / shared-secret CF→ALB

PR #642 leaves the ALB internet-facing and unprotected. Anyone who finds
the ALB DNS bypasses CloudFront. PR #644 adds the SG-to-SG rule for
`CloudFront-VPCOrigins-Service-SG` (good for VPC Origins specifically)
but does not add a header-based WAF rule for the non-VPC-Origin path.

**Fix (PR 3)**: add an optional WAF Web ACL with a rule requiring a
custom header value injected by CloudFront. Header secret stored in
Secrets Manager, rotated by an ACK SecretsManager resource.

### Gap 4 — `prod-public` and `internal-only` modes

Today only `workshop-studio` is implemented. The Taskfile has
`ingress.mode: cloudfront | tls` (commit `3bf31533`) which is a step
toward this, but the `tls` path lacks the ACM + Route53 wiring.

**Fix (PR 3)**: complete `tls` mode = `prod-public`, add `internal-only`
mode (no CF, ALB internal, private R53 zone), unify mode names with the
ones used in this doc.

### Gap 5 — ACK ELBv2 controller not bootstrapped

The current `hub:ingress` task uses raw `aws elbv2 create-load-balancer`
because ACK ELBv2 is not yet installed by Phase 0. This is a chicken-and-egg
of its own: ACK runs on EKS, EKS runs after VPC, VPC + ALB share a Phase 0
slot.

**Fix (PR 3)**: install ACK ELBv2 controller as a Phase 0 chart (in the
kind bootstrap cluster), apply the `LoadBalancer` + `Listener` ACK CRs
from kind (which writes to the AWS account being prepared), then hand
off the in-cluster ACK ELBv2 (running on EKS) to keep reconciling. Same
pattern as the existing ACK EC2 / ACK EKS in `cluster-providers/kind-kro-ack`.

This gap is the most invasive — happy to keep raw AWS CLI for `hub:ingress`
in the workshop and only switch to ACK ELBv2 for the per-app `AppExposure`
RGD. Decision deferred to PR 3 review.

## 7. Migration path from the legacy NLB + nginx stack

For environments still on the pre-PR #642 stack:

1. **Deploy the new edge alongside** the old one. CloudFront supports
   multiple distributions; the new ALB is a new resource. No conflict.
2. **Migrate one app at a time**: write the app's `AppExposure` claim,
   GitOps reconciles, app is reachable through both edges (new path on
   the new edge, legacy path on nginx).
3. **Cut over DNS / users to the new edge**, soak.
4. **Delete the old `Ingress` resource** for that app. nginx releases its
   route. The TG/TGB on the new path keeps serving.
5. Once all apps migrated, **decommission nginx-ingress + NLB**.

CloudFront + Route53 weighted routing makes a 10/90 canary trivial if you
are nervous about the cutover.

## 8. Open questions for review

1. **WAF header rotation cadence** in PR 3 — manual / monthly / on every
   `task install`? Argument for monthly: rotation as a feature is a story
   to demo. Argument for static: simpler.
2. **CloudFront VPC Origins** — adopt as the default for `prod-public` to
   eliminate the public ALB? Pro: smaller attack surface. Con: VPC Origins
   support in ACK CloudFront is recent, may drift. Decision deferred.
3. **ALB sharing across clusters** — the `AppExposure` RGD assumes one ALB
   per cluster (read from the cluster Secret). For multi-cluster fleets
   sharing one ALB, the Secret can point to a shared ARN, but the
   `TargetGroupBinding` needs target type `ip` + cross-cluster routing
   enabled in VPC peering. Out of scope for PR 2 / PR 3, design noted for
   v3.
4. **`tls` mode naming** — keep PR #642's `cloudfront | tls` or rename to
   `workshop-studio | prod-public | internal-only`? Aliases supported
   either way; preference for the latter (clearer intent).

## 9. Cross-references

- Implementation base: `feature/platform-cluster-kro-ack` (PR #642 + #644
  follow-ups)
- Bootstrap orchestrator: `cluster-providers/kind-kro-ack/Taskfile.yaml`
- Existing edge tasks: `hub:ingress`, `hub:cloudfront`, `hub:seed-secret`
- KRO RGDs reference: `docs/kro/`
- ArgoCD Capability + GitOps Bridge contract: `docs/EKS-Capabilities-ArgoCD-Setup.md`

## 10. Roadmap of the PR series

| PR | Scope | Branch (target = `feature/platform-cluster-kro-ack`) |
|---|---|---|
| **PR 1 (this doc)** | Architecture document, no code | `feat/exposure-architecture-doc` |
| PR 2 | `AppExposure` RGD (mode A only) + extended `hub:seed-secret` annotations | `feat/app-exposure-rgd` |
| PR 3 | Modes B + C, WAF header secret, optional ACK ELBv2 in Phase 0 | `feat/exposure-modes-prod-internal` |

Each PR is reviewable independently; PR 2 unblocks Keycloak / Backstage /
ArgoCD UI on workshop-studio without the legacy nginx layer; PR 3 makes
the same patterns reusable in production.
