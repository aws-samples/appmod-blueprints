# Restrict the platform ALB by source IP

All platform UIs on the hub (Backstage, Keycloak, ArgoCD, Grafana, Argo Workflows, Kargo,
Langfuse, …) share **one** Application Load Balancer: the IngressGroup `platform`, defined by the
`ingress-class-alb` addon. This page explains how to **set, change or remove** a source‑IP
allowlist on that shared ALB, from your fleet repo, through GitOps.

> **Scope.** Applies to any hub whose addon values you can override from a fleet repo you own
> (the `$overlay` source, see [Where to put it](#where-to-put-it)). With `insecure: true` +
> CloudFront ([CloudFront exposure](cloudfront-exposure.md)) the ALB is **internal** — read
> [pitfall 4](#4-cloudfront-mode-do-not-apply-a-client-allowlist) before setting anything.

---

## What the setting does

The `ingress-class-alb` chart accepts three optional values that you set:

| Key | Role |
|-----|------|
| `inboundCidrs` | Base allowlist (the stable list you keep) |
| `extraInboundCidrs` | Extra entries **appended** after the base (ad‑hoc additions without touching the base) |
| `prefixListIds` | Managed prefix list IDs (`pl-...`) allowed on the ALB, see [Use managed prefix lists](#use-managed-prefix-lists) |

A fourth value, `clusterEgressCidrs`, is filled automatically and only matters once an allowlist
is set: see [pitfall 1](#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes).

Each key accepts a **YAML list** *or* a **comma‑separated string**; blank entries are dropped. The
two CIDR lists are concatenated and rendered into `IngressClassParams.spec.inboundCIDRs` of the
`platform` IngressClassParams; the prefix list IDs are rendered into `spec.prefixListsIDs`:

```text
inboundCidrs + extraInboundCidrs (+ clusterEgressCidrs, only when an allowlist is set)
  └─> IngressClassParams "platform" .spec.inboundCIDRs
prefixListIds
  └─> IngressClassParams "platform" .spec.prefixListsIDs
        └─> load balancer controller rewrites the inbound rules of the ALB's managed security group
              └─> applies to EVERY ingress of the "platform" group at once
```

"An allowlist is set" means at least one of `inboundCidrs`, `extraInboundCidrs` or
`prefixListIds` is non-empty.

- **Unset by default.** With all three keys empty neither field is rendered: the ALB stays open to
  `0.0.0.0/0`, exactly as before (rendered output is byte‑identical).
- **Group‑wide.** `inboundCIDRs` is the group‑level form of the `inbound-cidrs` ingress annotation:
  it is applied once to the shared managed security group and takes precedence over any per‑ingress
  annotation, so there is no IngressGroup annotation conflict.
- **Both controller modes.** The chart renders `eks.amazonaws.com/v1` IngressClassParams on EKS Auto
  Mode (`alb_controller_mode` unset or `auto`, the default) and `elbv2.k8s.aws/v1beta1` with the
  open‑source AWS Load Balancer Controller (`alb_controller_mode: oss`). Both support
  `inboundCIDRs` and `prefixListsIDs` under the same field names (see the
  [EKS Auto Mode IngressClassParams reference](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-alb.html#ingress-reference));
  the same values work in either mode.

---

## Use managed prefix lists

`prefixListIds` admits the CIDRs of one or more managed prefix lists (for example a corporate
egress list) instead of listing them by hand:

```yaml
# overlays/clusters/<hub-name>/ingress-class-alb/values.yaml
prefixListIds:
  - pl-0123456789abcdef0      # placeholder: your managed prefix list ID
# Spoke NAT egress IPs still go here (pitfall 1):
# extraInboundCidrs: "203.0.113.201/32"
```

- **No `0.0.0.0/0`.** With prefix lists only (no `inboundCIDRs`), the controller does not add its
  `0.0.0.0/0` default to the managed security group.
- **The cluster's NAT `/32` is still added.** `clusterEgressCidrs` is appended to `inboundCIDRs`
  whenever an allowlist is set, prefix lists included. On kind-kro-ack and kind-crossplane a
  prefix-list-only allowlist therefore renders `inboundCIDRs: ["<hub-nat-eip>/32"]` next to
  `prefixListsIDs`, and in-cluster SSO keeps working ([pitfall 1](#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes)).
  Spoke NAT EIPs are not added: list them in `extraInboundCidrs`.
- **Quota.** A prefix list counts against the security group rule quota by its **maximum size**,
  not its current entry count, once per listener port. See [pitfall 3](#3-securitygroup-rule-limits).
- AWS-managed prefix lists are read-only: you cannot add your NAT IPs to them, use
  `extraInboundCidrs`. The list must exist in the ALB's region.
- Check the size before choosing a list (`MaxEntries` may not be reported for AWS-managed
  lists; then the current entry count is a lower bound, not the number the quota uses):

  ```bash
  aws ec2 describe-managed-prefix-lists --prefix-list-ids <pl-id> \
    --query 'PrefixLists[].[PrefixListName,MaxEntries]' --output text
  aws ec2 get-managed-prefix-list-entries --prefix-list-id <pl-id> --query 'length(Entries)'
  ```

---

## Where to put it

The hub reads per‑addon value overrides from your fleet repo (the `$overlay` source of the
`cluster-addons` ApplicationSet). It resolves that repo as follows:

1. the `overlay_repo_url` / `overlay_repo_revision` annotations of the hub cluster secret, when set;
2. otherwise the addons repo itself (in that case there is no fleet‑repo overlay to edit: set
   `overlay_repo_url` / `overlay_repo_revision` / `overlay_repo_basepath` on the hub, see
   [fleet-secret README](../../platform-charts/fleet-secret/README.md)).

> [#1169](https://github.com/aws-samples/appmod-blueprints/pull/1169) proposes falling back to the hub's own `fleetRepoURL` / `fleetRepoRevision`
> when it is a separate repo from the addons repo, so a direct install with a dedicated fleet repo
> needs no `overlay_repo_url`. Until it is merged, wire `overlay_repo_url` explicitly.

Overlay content lives at the **root** of the fleet repo (or under `overlay_repo_basepath` when
set). Create:

```text
<fleet-config-repo>/
└── overlays/
    └── clusters/
        └── <hub-name>/                 # the hub's name as registered in ArgoCD
            └── ingress-class-alb/
                └── values.yaml
```

```yaml
# overlays/clusters/<hub-name>/ingress-class-alb/values.yaml
#
# Source-IP allowlist for the shared "platform" ALB (all hub UIs).
# IPv4 CIDRs. The hub's own NAT egress IP(s) are added automatically on kind-kro-ack and
# kind-crossplane installs; elsewhere, list them here. The NAT egress IP(s) of every OAP spoke
# always go here, and must be updated after each reinstall (see pitfall 1).
inboundCidrs:
  - 203.0.113.0/25        # corporate / VPN egress range
  # - 203.0.113.200/32    # hub NAT egress IP -- only outside kind-kro-ack / kind-crossplane
  # - 203.0.113.201/32    # NAT egress IP of a spoke running OAP addons, if any
# Optional ad-hoc additions, appended after the base (list or comma-separated string):
extraInboundCidrs: "203.0.113.10/32,203.0.113.11/32"
```

The file is optional (`ignoreMissingValueFiles: true`): absent means no allowlist. To apply the
same list to every cluster of an environment instead, use
`overlays/environments/<env>/ingress-class-alb/values.yaml`; a cluster file wins over the
environment file.

> **Why a values file and not the registry `valuesObject`.** The addon registry already sets
> `controllerMode`, `loadBalancerName`, `scheme` and `clusterEgressCidrs` through `valuesObject`,
> and in ArgoCD `valuesObject` takes precedence over value files — so those keys cannot be
> overridden here. `inboundCidrs` / `extraInboundCidrs` are **not** set by the registry, so the values file is
> authoritative for them. (Equivalent alternative: add
> `ingress-class-alb: { valuesObject: { inboundCidrs: [...] } }` to
> `overlays/clusters/<hub-name>/overrides.yaml`, which merges into the registry entry.)

---

## Change the allowed IPs

1. Edit the lists in `overlays/clusters/<hub-name>/ingress-class-alb/values.yaml`.
2. Commit and push to the **revision the hub actually tracks** (`overlay_repo_revision`). This is
   not necessarily `main`. Check it with:

   ```bash
   kubectl -n argocd get secret -l argocd.argoproj.io/secret-type=cluster \
     -o jsonpath='{range .items[*]}{.metadata.name}{"  overlay="}{.metadata.annotations.overlay_repo_url}{"@"}{.metadata.annotations.overlay_repo_revision}{"\n"}{end}'
   ```

3. Wait for ArgoCD to pick it up (~3 min polling), or sync the addon app now — it is named
   `ingress-class-alb-<hub-name>`:

   ```bash
   argocd app sync ingress-class-alb-<hub-name>
   # or, without an ArgoCD CLI session:
   kubectl -n argocd annotate application ingress-class-alb-<hub-name> \
     argocd.argoproj.io/refresh=hard --overwrite
   ```

4. Verify the rendered IngressClassParams and the ALB security group:

   ```bash
   # Rendered allowlist (Auto Mode: ingressclassparams.eks.amazonaws.com,
   # OSS controller: ingressclassparams.elbv2.k8s.aws)
   kubectl get ingressclassparams platform -o yaml | grep -A10 inboundCIDRs

   # Inbound rules of the ALB's security groups
   ALB_DNS=$(kubectl get ingress -A -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}')
   SGS=$(aws elbv2 describe-load-balancers \
     --query "LoadBalancers[?DNSName=='${ALB_DNS}'].SecurityGroups[]" --output text)
   aws ec2 describe-security-groups --group-ids $SGS \
     --query 'SecurityGroups[].IpPermissions[].[FromPort,IpRanges[].CidrIp]' --output json
   ```

   Expect one rule per CIDR **per listener port** (80, and 443 when `insecure: false`), and no
   `0.0.0.0/0`. With `prefixListIds`, the prefix lists appear under
   `IpPermissions[].PrefixListIds[].PrefixListId`.

---

## Remove the filtering

Delete the keys (or the whole `ingress-class-alb/values.yaml` file), or set them empty:

```yaml
inboundCidrs: []
extraInboundCidrs: ""
prefixListIds: []
```

Commit, push to the tracked revision and sync as above. The `inboundCIDRs` and `prefixListsIDs` fields disappear from
the IngressClassParams and the controller restores the default `0.0.0.0/0` inbound rules. Verify
with the same two commands: `inboundCIDRs` no longer appears, and the security group shows
`0.0.0.0/0` on the listener ports.

---

## Pitfalls

### 1. Include the NAT egress IPs of the hub (and of OAP spokes)

The Keycloak issuer is the **public** URL `https://<domain>/keycloak/realms/platform`. Every app
that signs users in or validates a token calls it **server‑side** (OIDC discovery, token endpoint,
JWKS), through this same ALB, from inside the cluster: Backstage, Argo Workflows, Kargo, Langfuse,
Agent Gateway, GitLab omniauth, and ArgoCD OSS when `enable_argocd` is set (the EKS ArgoCD
capability signs in through IAM Identity Center and is not affected). That traffic leaves via the
VPC's NAT gateway(s), so the ALB sees the **NAT Elastic IP** as source. If it is not in the
allowlist, the ALB security group drops the connection (a TCP timeout, not a 403).

**Symptoms.** The UIs load from your browser, but SSO fails on a timeout: Langfuse returns
`/api/auth/error?error=OAuthSignin`, Argo Workflows answers 500 on `/oauth2/redirect`, Backstage
and Kargo SSO fail on OIDC discovery, the Agent Gateway JWT policy cannot fetch its JWKS (MCP calls
get 401). The app logs show timeouts to `https://<domain>/keycloak/...`.

The allowlist must contain, as `/32`s (for example `<nat-eip>/32`):

- every NAT gateway Elastic IP of the **hub** VPC;
- every NAT gateway Elastic IP of **each spoke that runs agentic platform (OAP) addons**: those
  spokes also call the hub's public ALB (OTel export to `https://<hub-domain>/api/public/otel`,
  Agent Gateway JWKS from the hub's Keycloak).

#### Hub NAT: added automatically on kind-kro-ack and kind-crossplane

At install, `secrets-manager:seed` looks up the public IP of every available NAT gateway of the
hub VPC and writes them as `/32`s to the `nat_egress_cidrs` metadata key of `<hub>/config`. ESO
turns it into an annotation of the hub cluster secret, and the registry passes it to the chart as
`clusterEgressCidrs`. The chart appends it to `inboundCidrs` + `extraInboundCidrs` (no duplicate if
you already listed it) **only when an allowlist is set** (CIDRs or `prefixListIds`): without an
allowlist the ALB stays open and the value is ignored. Nothing to commit in your fleet repo for the hub, and the
allowlist is complete from the ALB's creation.

- A re-seed whose NAT lookup **fails** (API or IAM error) keeps the value already stored, so an
  active allowlist never loses the NAT on a transient error. A lookup that **succeeds** writes what
  it finds: a new EIP replaces the stored one, and no NAT removes the key, so a released EIP never
  stays in the allowlist.
- A hub reinstall recreates the VPC and re-runs the seed, so the hub value follows the new EIP on
  its own.
- If the NAT gateway or its EIP is replaced on a **live** hub, refresh only that key (do not
  re-run the full `secrets-manager:seed`, which would drop keys other tasks merged in since):

  ```bash
  task kind-kro-ack:secrets-manager:seed-nat-egress     # or kind-crossplane:secrets-manager:seed-nat-egress
  ```

  It uses the same lookup as the seed, merges only `nat_egress_cidrs` into `<hub>/config` (failed
  lookup: nothing written, the task fails; no NAT: key removed), then forces an ESO refresh so
  ArgoCD re-renders `ingress-class-alb`. Without the task runner, the manual equivalent is to set
  or delete `nat_egress_cidrs` in the JSON string of `<hub>/config`'s `metadata` field, then
  annotate the hub cluster-secret `ExternalSecret` in `argocd` with `force-sync=$(date +%s)`.
- Check it: `kubectl -n argocd get secret -l argocd.argoproj.io/secret-type=cluster
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.nat_egress_cidrs}{"\n"}{end}'`
- The install role needs `ec2:DescribeNatGateways`.
- To opt out on one hub, set the registry entry in `overlays/clusters/<hub-name>/overrides.yaml`:
  `ingress-class-alb: { valuesObject: { clusterEgressCidrs: "" } }`.
- **A NAT gateway that other workloads share** (bring-your-own VPC) is added the same way, so the
  ALB is also open to everything else that egresses through it, exactly as if you had listed it by
  hand. Opt out as above if that is not acceptable.
- **Only the hub VPC's own NAT gateways are looked up.** A hub that egresses through something
  else (a Transit Gateway to a central egress VPC, a proxy, a firewall) gets nothing added: list
  that egress IP yourself in `inboundCidrs` or `extraInboundCidrs`.

#### Still manual

- the hub NAT on other providers (`byoc`, `terraform`);
- the NAT egress IPs of **spokes running OAP**, on every provider: add them to the hub list in
  `inboundCidrs` or `extraInboundCidrs`.

#### Spoke NAT EIPs are unknown when the hub ALB is created

`nat_egress_cidrs` is looked up only for the **hub** VPC, by the hub's seed. Nothing in this repo
writes a spoke's NAT EIP into the hub's allowlist, and a spoke's VPC (with its NAT gateway) is
created after the hub, so its EIP does not exist yet when the hub ALB gets its allowlist. On a
fresh install with an allowlist (CIDRs or prefix lists), spoke-to-hub calls (OTel export, Agent
Gateway JWKS) time out until you:

1. wait for the spoke VPC, then read its NAT EIP(s) with the `describe-nat-gateways` command below;
2. add them as `/32`s to `extraInboundCidrs` in the hub's `ingress-class-alb/values.yaml`, push to
   the tracked revision and sync `ingress-class-alb-<hub-name>`.

Repeat after every spoke reinstall. A hub allowlist set under `overlays/clusters/<hub-name>/` or
`overlays/environments/control-plane/` does not change the spokes' own ALBs.

To list the NAT gateway Elastic IPs of a VPC:

```bash
aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=<hub-or-spoke-vpc-id> \
  --query 'NatGateways[].NatGatewayAddresses[].PublicIp' --output text
```

> **Re-check after every reinstall.** A NAT Elastic IP is stable while the NAT gateway exists,
> but it changes whenever the VPC is recreated — each hub (or spoke) reinstall. For every IP you
> listed by hand (spokes, and the hub outside kind-kro-ack / kind-crossplane), replace the old
> `/32` with the new one, or SSO breaks again.

Nothing to do when `inboundCidrs` / `extraInboundCidrs` / `prefixListIds` are unset. In CloudFront mode the ALB
carries no allowlist ([pitfall 4](#4-cloudfront-mode-do-not-apply-a-client-allowlist)), but the
same NAT IPs must be in the WAF IP set if you filter clients at the edge. The automatic hub value
only reaches the ALB allowlist, never a WAF IP set: list the hub NAT there yourself.

### 2. The IP the ALB sees may not be the one a "what is my IP" service shows

A `checkip`‑style service can return a different address than the one your traffic actually
presents to the ALB in its region (split egress, regional proxies, VPN routing). Before relying on
an address, confirm it from the ALB side: enable **VPC Flow Logs** on the ALB's network interfaces
(description `ELB app/<alb-name>/...`) and look for `REJECT` records on ports 80/443 — their source
address is the IP you need to allow.

### 3. Security‑group rule limits

Each CIDR becomes one inbound rule **per listener port**: with HTTP + HTTPS listeners that is two
rules per CIDR. A security group allows 60 inbound rules by default, so plan for **about 30 CIDRs
at most** (about 60 with an HTTP‑only ALB). Summarise ranges, or move to AWS WAF, beyond that. The
platform ALB is IPv4 by default, so list IPv4 CIDRs; IPv6 entries are only useful on a dual‑stack
ALB.

A managed prefix list in `prefixListIds` counts as **its maximum size**, not its current entry
count, once per listener port, on top of one rule per `/32` per port from `inboundCIDRs`. Example on
an HTTP + HTTPS ALB with a quota of 60: a list of maximum size 8 plus one NAT `/32` needs
2 × 8 + 2 × 1 = 18 rules; a list of maximum size 58 needs 116 before any `/32`, over the quota.
Check the maximum size (see [Use managed prefix lists](#use-managed-prefix-lists)) before
choosing a list.

### 4. CloudFront mode: do not apply a client allowlist

With `insecure: true` and CloudFront ([CloudFront exposure](cloudfront-exposure.md)) the ALB is **internal** and
reached through a CloudFront **VPC origin**: it sees the private IPs of the CloudFront origin
interfaces, never the client's IP. A corporate allowlist there **cuts CloudFront off** and every
URL fails. Filter clients at the edge instead — AWS WAF on the distribution (IP set rule), or
CloudFront functions — and leave `inboundCidrs` unset on that ALB. If you use a WAF IP set, add
the hub's and OAP spokes' NAT egress IPs to it too: their server‑side calls to Keycloak go out
through the NAT and come back through CloudFront ([pitfall 1](#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes)).

### 5. Do not lock yourself out

The change applies to **every** UI at once, ArgoCD included. Add the IP you are working from (and
the NAT egress IPs you must list by hand, see [pitfall 1](#1-include-the-nat-egress-ips-of-the-hub-and-of-oap-spokes))
**before** enabling the list, and keep `kubectl` access to the hub (the EKS API
endpoint is not behind this ALB) so you can revert from the cluster if needed: removing the keys in
Git and syncing, or as a last resort editing the IngressClassParams directly (ArgoCD will reconcile
it back to Git on the next sync).

---

## Related hardening: close Langfuse self‑registration

The other half of the same AppSec fix is to stop anyone who can reach Langfuse from creating a
local account. When the agentic platform (OAP) is deployed, use its `langfuse` chart's
`keycloak.disableUsernamePassword`, rendered as `AUTH_DISABLE_USERNAME_PASSWORD`. It turns off
Langfuse's local email/password sign‑up **and** sign‑in, while Keycloak SSO keeps working,
first‑time SSO users included. This key is added by
[awslabs/open-agentic-platform#103](https://github.com/awslabs/open-agentic-platform/pull/103),
with a default of `"true"`: once that PR is in the OAP revision you deploy, nothing needs to be
set. Until then, the key is ignored. To set it explicitly, use the overlay of your fleet repo:

```yaml
# overlays/clusters/<hub-name>/langfuse/values.yaml
keycloak:
  disableUsernamePassword: "true"   # string value; "false" brings back local accounts
```

On a hub that is already running, the Langfuse pod must restart before the change takes effect.

> **Do not use `keycloak.disableSignup: "true"`** (`AUTH_DISABLE_SIGNUP`) to close
> self‑registration. Langfuse then refuses to create **any** new user, SSO included: a Keycloak
> user who has never opened Langfuse cannot sign in, and gets "Sign up is disabled." On a fresh
> install that is every user. Keep it at its default `"false"`.
