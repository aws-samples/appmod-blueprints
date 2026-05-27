# Multi-Cluster Authentication Design

## Status

**Proposed** — Phase 1 implementation pending.

This document defines how authentication and authorization work across the
hub and spoke clusters of the agent platform. It introduces a generic
**OIDC Provider Abstraction** so that customers can use the reference
Keycloak implementation, swap in their own provider (Okta, Ping, Auth0,
Azure AD, custom OIDC), or mix approaches.

## Context

The agent platform is deployed across multiple clusters:

- **Hub** (`peeks-hub`) — control plane, IdP, ArgoCD, Crossplane, Backstage
- **Spokes** (`peeks-spoke-dev`, `peeks-spoke-prod`) — workload clusters
  running agent components (agentgateway, kagent, langfuse, etc.)

Each cluster exposes user-facing services through an ALB ingress.
Components like `agentgateway` enforce JWT-based authorization on
incoming requests.

### Current state (problems we are solving)

1. **Single shared hostname across clusters**: all clusters were configured
   to use `peeks.dev.<base-domain>`, causing DNS conflicts. ExternalDNS on
   each cluster races for the same Route 53 record.

2. **Spoke agentgateways cannot validate JWTs**: the JWT auth policy on
   spokes references a Keycloak Service in-cluster
   (`keycloak.keycloak.svc.cluster.local`). Keycloak only runs on the hub,
   so the JWKS fetch fails, the policy is `PartiallyValid`, and the policy
   is **not attached** to the gateway. Effective behaviour: spoke gateways
   either reject everything or (worse) allow everything depending on
   default-deny vs default-allow semantics.

3. **No client provisioning for spokes**: there is no mechanism that
   creates Keycloak (or other IdP) clients for each cluster/environment.
   Every component reuses the hub client, which conflates audiences and
   makes per-environment audit and revocation impossible.

4. **No customer extension path**: the design hard-codes Keycloak. Most
   enterprise customers already operate an IdP (Okta, Ping, Azure AD) and
   need to plug it in without forking the platform.

## Goals

- **Single IdP, multi-cluster validation**: tokens issued by one IdP can be
  validated by resource servers on any cluster.
- **Per-environment isolation**: each environment (dev, prod, hub) has
  distinct DNS, distinct OAuth clients, and distinct token audiences.
- **Provider-agnostic consumers**: charts that consume OIDC (agentgateway,
  kagent, UI) must not depend on Keycloak specifics. They speak OIDC.
- **Pluggable provisioner**: the component that creates OAuth clients in
  the IdP is provider-specific, but conforms to a stable contract that
  customer-built provisioners can also satisfy.
- **Reference implementation**: ship a working Keycloak reference so the
  workshop is self-contained.
- **Standard delegation pattern (future)**: support audit identity in the
  form "user X did Y via agent Z" using RFC 8693 token exchange and the
  `act` claim on providers that support it.

## Non-Goals

- **Federated multi-IdP topologies**: running a separate IdP on each
  spoke and federating between them. Significantly more complex and
  unnecessary for the workshop scale.
- **Kubernetes-native workload identity** (SPIFFE/SPIRE) for agent-to-agent
  authentication. Out of scope here; could be a future addition.
- **VPC peering or PrivateLink for in-cluster JWKS**. Public JWKS over
  HTTPS is the standard pattern and avoids cross-cluster networking
  complexity.

---

## OIDC Provider Abstraction

The key insight enabling provider portability: most of what we need from
an IdP is **OIDC standard**. Only client provisioning is provider-specific.

| Concern | Provider-Agnostic (OIDC) | Provider-Specific |
|---|---|---|
| JWT validation (signature, exp, aud, iss) | ✅ | — |
| Issuer URL, JWKS URL, OIDC discovery | ✅ | — |
| OIDC authorization code flow | ✅ | — |
| Client credentials flow | ✅ | — |
| Token endpoint, refresh tokens | ✅ | — |
| Admin API for client provisioning | — | ✅ |
| Admin API authentication | — | ✅ |
| Group/role claim location in JWT | partly standardized | ✅ Often provider-specific |
| Token Exchange (RFC 8693) | Standard | ✅ Support varies |

### The contract

Decoupling consumers from providers requires a **stable contract**.
This contract is a schema of credentials and metadata stored in
**AWS Secrets Manager**, written by a provisioner and consumed by
ExternalSecrets on each cluster.

**Path convention**: `peeks/<env>/oidc/<service>-client`

Example: `peeks/dev/oidc/agentgateway-client`

**Schema** (JSON):

```json
{
  "client_id":       "agentgateway-dev",
  "client_secret":   "<opaque-string>",
  "issuer":          "https://login.example.com/oauth2/default",
  "jwks_uri":        "https://login.example.com/oauth2/default/v1/keys",
  "token_endpoint":  "https://login.example.com/oauth2/default/v1/token",
  "audience":        "agentgateway-dev",
  "groups_claim":    "groups"
}
```

Notes:

- `groups_claim` is a JSONPath-style hint for where group/role claims
  live in the issued JWT. Default `groups`. Examples:
  - Keycloak realm roles: `realm_access.roles`
  - Okta groups: `groups`
  - Azure AD app roles: `roles`
  - Auth0 custom: `https://example.com/groups`
- `client_secret` may be empty for public clients (e.g., browser-based
  UIs using PKCE).
- For pure resource servers (e.g., agentgateway validating tokens but
  never issuing them), the entry may omit `client_secret` and exists
  only to publish issuer/JWKS/audience metadata.

**Consumers** (charts) read this via ExternalSecrets, projected into a
Kubernetes Secret with the same key names. They never speak Keycloak,
Okta, or any other admin API directly.

---

## Architecture

```
                        ┌───────────────────────────────────┐
                        │ Hub Cluster (peeks-hub)           │
                        │                                   │
                        │  ┌─────────────────────────────┐  │
                        │  │ OIDC Provider               │  │
                        │  │ (Keycloak in reference impl,│◀─┼──── Public HTTPS
                        │  │  external IdP otherwise)    │  │     (issuer, JWKS,
                        │  └─────────────────────────────┘  │     token endpoint)
                        │              ▲                    │
                        │              │ admin API          │
                        │              │                    │
                        │  ┌───────────┴─────────────────┐  │
                        │  │ Client Provisioner (Job)    │  │
                        │  │  - per-env clients          │  │
                        │  │  - writes to Secrets Mgr    │──┼──┐
                        │  └─────────────────────────────┘  │  │
                        │                                   │  │
                        │  agentgateway-hub                 │  │
                        └───────────────────────────────────┘  │
                                                               ▼
                                          ┌────────────────────────────┐
                                          │  AWS Secrets Manager       │
                                          │   peeks/dev/oidc/...       │
                                          │   peeks/prod/oidc/...      │
                                          │   peeks/hub/oidc/...       │
                                          └────────────────────────────┘
                                                       │
                            ┌──────────────────────────┴──────────────────────────┐
                            │ Spoke (peeks-spoke-dev)        │ Spoke (peeks-spoke-prod)
                            │                                │                     │
                            │  ExternalSecrets ──┐           │  ExternalSecrets    │
                            │                    ▼           │      ↓              │
                            │  K8s Secret: oidc-client       │  K8s Secret         │
                            │                                │                     │
                            │  agentgateway, kagent, UI      │  (same)             │
                            │   - issuer, jwks, audience     │                     │
                            │   - groups_claim path          │                     │
                            │                                │                     │
                            │  Ingress (ALB):                │                     │
                            │   dev.peeks.dev.<domain>       │  prod.peeks.dev....  │
                            │   ExternalDNS → Route 53       │                     │
                            └────────────────────────────────┴─────────────────────┘
                                          │                              │
                                          │  Public JWKS over HTTPS      │
                                          ▼                              ▼
                                   (validates JWTs from issuer, regardless of provider)
```

---

## Design Decisions

### D1: DNS — subdomain per environment

**Decision**: each environment gets a subdomain of the platform base
domain. Hub is at the bare base domain to preserve workshop convention.

| Environment | Hostname |
|---|---|
| Hub (control plane) | `peeks.dev.<base-domain>` |
| Spoke-dev | `dev.peeks.dev.<base-domain>` |
| Spoke-prod | `prod.peeks.dev.<base-domain>` |

ExternalDNS on each cluster manages records in the same Route 53 hosted
zone. ACM wildcard cert `*.peeks.dev.<base-domain>` covers all
subdomains.

**Alternatives considered**:

- **Service-prefixed subdomain** (e.g., `agents-dev.peeks.dev...`) —
  rejected as the per-env scheme keeps things simpler and we can add
  service prefixes later if a single env needs multiple top-level
  ingresses.
- **Path prefix on hub** (e.g., `peeks.dev/spokes/dev/agentgateway`) —
  rejected because it makes the hub a network choke point, defeats
  multi-cluster decoupling, and complicates ALB routing.

### D2: JWT validation — public JWKS over HTTPS

**Decision**: spokes fetch JWKS directly from the IdP's public OIDC
discovery endpoint. The agentgateway already supports remote JWKS with
caching (`cacheDuration: 5m`).

**Alternatives considered**:

- **JWKS sync via ExternalSecrets** — rejected as added complexity for
  marginal benefit. JWKS over HTTPS with 5m cache handles the same
  failure modes as ExternalSecrets sync (the IdP being unreachable
  affects both).
- **VPC peering / PrivateLink** — rejected as heavy infrastructure for a
  problem standard OIDC already solves.

### D3: Client provisioning — one-shot job per env, Keycloak as reference

**Decision**: a one-shot Helm-managed Job runs after a new environment
is registered. The Job calls the IdP admin API, creates the required
clients, and writes credentials to AWS Secrets Manager.

The reference implementation targets Keycloak. The Job chart is named
`keycloak-client-provisioner` to make its provider scope explicit.

**Alternatives considered**:

- **Crossplane composition** (declarative client objects via a Keycloak
  Crossplane provider) — defer to Phase 3. Cleaner long-term but the
  Crossplane provider for Keycloak is community-maintained and adds a
  dependency we want to defer until basics work.
- **Reconciler/operator** — defer until lifecycle requirements
  (per-cluster secret rotation, drift detection) actually emerge.
- **Single shared client across environments** — rejected because it
  removes per-env audit, revocation, and audience isolation.

### D4: One client per service per env

**Decision**: provision distinct clients per (service, env) pair. For
the workshop scale this gives sensible isolation without explosion.

| Client | Type | Flows | Audience |
|---|---|---|---|
| `agentgateway-<env>` | confidential | resource server only (validates) | `agentgateway-<env>` |
| `kagent-<env>` | confidential | client_credentials, token-exchange | issuer-default |
| `ui-<env>` | public + PKCE | authorization code | service-defined |

This is a reasonable starting point. Customers can adjust granularity
(more or fewer clients) without changing the contract.

**Alternative considered**: per-cluster clients. Rejected because in
practice an environment is bigger than a cluster (a customer's "dev"
environment may span multiple clusters), and naming them per cluster
creates churn whenever clusters are recreated.

### D5: Client lifecycle — create, do not delete on cluster destruction

**Decision**: clients live with the environment, not the cluster.
Destroying a cluster does not delete the client. Re-provisioning the
cluster reuses the existing client.

The provisioner Job is **idempotent**: it skips client creation when
one already exists, and only refreshes the Secrets Manager entry if it
is missing or invalid.

**Rationale**: an environment may have multiple clusters (blue/green,
DR, regions). Tying client identity to cluster lifecycle would create
dangling secrets and break consumers in other clusters of the same env.

### D6: Group/role claim — configurable

**Decision**: the path to group claims in the JWT is a configurable
value (`groups_claim`). Authorization expressions in `AgentgatewayPolicy`
are templated against this path.

Default `groups`. Customers configure per provider.

**Rationale**: Keycloak realm roles live at `realm_access.roles`, Okta
groups at `groups`, Azure AD app roles at `roles`. Hard-coding any of
these breaks the others.

---

## Reference Implementation: Keycloak

### Components

| Component | Location | Purpose |
|---|---|---|
| Keycloak (existing) | `gitops/addons/charts/keycloak/` | The IdP itself. Hosts realm `platform`. |
| `keycloak-client-provisioner` (new) | `gitops/addons/charts/keycloak-client-provisioner/` | Helm chart wrapping a Job that creates clients via Keycloak admin API and writes to AWS Secrets Manager. |
| `agentgateway` (modified) | `gitops/addons/charts/agentgateway/` | Parameterized issuer, JWKS, audience, hostname, groups_claim. ExternalSecret pulls client config. |

### Provisioner Job behaviour

For each registered environment in the fleet:

1. Authenticate to Keycloak admin API using IRSA-derived credentials
   stored in AWS Secrets Manager (`peeks/hub/keycloak/admin`).
2. For each required client (`agentgateway-<env>`, `kagent-<env>`,
   `ui-<env>`):
   - Check if the client exists in realm `platform`.
   - If not, create it with appropriate flow configuration and audience
     mapper.
   - Read or rotate the client secret as needed.
   - Write the contract schema to `peeks/<env>/oidc/<client>`.
3. Exit. The Job is fire-and-forget; rerunning is safe.

### ExternalSecret pattern on consumers

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: agentgateway-oidc-client
  namespace: agentgateway-system
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: agentgateway-oidc-client
  dataFrom:
    - extract:
        key: peeks/{{ .Values.env }}/oidc/agentgateway-client
```

The agentgateway chart consumes the resulting K8s Secret. No Keycloak
URLs or SDK calls in the chart itself.

---

## Replacing With an External OIDC Provider

Customers integrating with Okta, Ping, Auth0, Azure AD, or a custom
OIDC implementation have **three paths**.

### Path A — Reference Keycloak (default)

Deploy as-is. Workshop uses this. No customer action required.

### Path B — External OIDC, manual client provisioning

The customer's IdP is the source of truth. Clients are created out-of-band
(via the IdP's admin console, customer's IaC, or existing identity
governance).

Customer steps:

1. **Disable Keycloak** in the platform: set
   `enable_keycloak: false` and
   `enable_keycloak_client_provisioner: false` on cluster secrets.
2. **Manually provision clients** in the external IdP:
   - One per (service, env) pair, matching the naming convention.
   - Issue a client secret for confidential clients.
   - Configure audience claim to match `<service>-<env>`.
   - Note JWKS URL, issuer URL, and token endpoint.
3. **Populate Secrets Manager** with entries matching the contract
   schema (D1). For example:
   ```bash
   aws secretsmanager create-secret \
     --name peeks/dev/oidc/agentgateway-client \
     --secret-string '{
       "client_id": "agentgateway-dev",
       "client_secret": "...",
       "issuer": "https://acme.okta.com/oauth2/default",
       "jwks_uri": "https://acme.okta.com/oauth2/default/v1/keys",
       "token_endpoint": "https://acme.okta.com/oauth2/default/v1/token",
       "audience": "agentgateway-dev",
       "groups_claim": "groups"
     }'
   ```
4. **Configure the platform** with the IdP's issuer URL on cluster
   secrets:
   ```yaml
   oidc_issuer_url: "https://acme.okta.com/oauth2/default"
   ```

ExternalSecrets and consumer charts do the rest.

### Path C — External OIDC with auto-provisioning

The customer wants programmatic client lifecycle in their own IdP.

Customer steps:

1. **Disable** the Keycloak provisioner.
2. **Implement a custom provisioner** following the same contract:
   - Reads the list of registered envs (e.g., from cluster secret
     labels).
   - Calls their IdP's admin API to create the required clients.
   - Writes the contract schema to `peeks/<env>/oidc/<client>` in
     AWS Secrets Manager.
3. **Deploy as a Helm chart** alongside the platform (e.g.,
   `okta-client-provisioner`, `azure-ad-client-provisioner`).

The reference Keycloak provisioner serves as a template — a Job, a
ServiceAccount, IRSA for Secrets Manager write, idempotent client
creation logic.

---

## Provider Capability Matrix

| Capability | Keycloak | Okta | Ping Identity | Auth0 | Azure AD |
|---|---|---|---|---|---|
| OIDC discovery (`/.well-known`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Client credentials grant | ✅ | ✅ | ✅ | ✅ | ✅ |
| Authorization code + PKCE | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Token Exchange (RFC 8693)** | ✅ since 12 | ⚠️ Limited (custom claims) | ✅ | ⚠️ Limited | ✅ (on-behalf-of) |
| Group claim default location | `realm_access.roles` | `groups` | `groups` | custom (e.g., `https://example.com/groups`) | `roles` |
| Admin API auth model | admin-cli token | API token (`SSWS`) | OAuth client credentials | Management API audience | Microsoft Graph |
| Per-resource audience | ✅ | ✅ via authorization servers | ✅ | ✅ | ✅ via app roles |
| Bulk client provisioning | ✅ | ✅ | ✅ | ✅ | ✅ |

The matrix shapes what is achievable on each provider:

- **Audit identity** (`act` claim, "user X did Y via agent Z") works
  cleanly on Keycloak, Ping, and Azure AD. On Okta and Auth0, alternative
  patterns are needed (e.g., propagate user identity in a custom header
  alongside the agent's token, log gateway-side with multi-token
  correlation).
- **Group claim** location varies. The platform exposes `groups_claim`
  per env so authorization expressions can be retargeted.

---

## Implementation Plan

### Phase 1 — Foundation

Goal: working multi-cluster auth with Keycloak as the IdP.

**In `appmod-blueprints`:**

1. **New chart** `gitops/addons/charts/keycloak-client-provisioner/`
   - Job + ServiceAccount + IRSA for Secrets Manager
   - Idempotent client creation against Keycloak admin API
   - Writes contract schema entries
2. **Modify** `gitops/addons/charts/agentgateway/`
   - Parameterize `issuer`, `jwksUrl`, `audience`, `hostname`,
     `groupsClaim`
   - Replace Service-ref JWKS with public URL
   - Add ExternalSecret reading the contract entry
3. **Modify** `gitops/fleet/members/spoke-{dev,prod}/values.yaml`
   - Add `env: dev` / `env: prod` labels
4. **ACM wildcard cert** `*.peeks.dev.<base-domain>` (Terraform module).
5. **Cluster secret labels**: add `oidc_issuer_url` (default points at
   reference Keycloak; customers override).

**In `open-agentic-platform`:**

1. Per-env overlays for agentgateway:
   - `gitops/overlays/environments/dev/agentgateway-values.yaml`
     (`hostname: dev.peeks.dev...`, `env: dev`)
   - Same for prod and hub (hub at bare base domain).

**Acceptance criteria:**

- Hub agentgateway responds with 401 when called without token (today's
  behaviour preserved).
- Spoke agentgateways enforce JWT validation and return 401 (today: do
  not enforce).
- Per-env DNS resolves correctly; no Route 53 conflicts.
- AgentgatewayPolicy on each spoke shows `Attached: True` and
  `Accepted: True`.
- A token issued for `audience=agentgateway-dev` is rejected by
  agentgateway-prod with HTTP 401.

### Phase 2 — Audit identity

Goal: support "user X did Y via agent Z" in audit logs.

1. Configure the `kagent-<env>` clients with token-exchange permission
   (Keycloak) or equivalent on supporting providers.
2. Update agent code path: receive user token, call token-exchange,
   forward delegated token to agentgateway.
3. Update agentgateway access logging to capture `sub` and `act.sub`.
4. Wire structured logs to the existing observability stack
   (Loki/CloudWatch).
5. **Document the alternative pattern** for non-supporting providers
   (custom header propagation + multi-token correlation).

**Acceptance criteria:**

- A request initiated by user `alice` through `kagent` results in a log
  entry containing both `user=alice` and `agent=kagent`.
- The agent cannot impersonate the user beyond the scopes granted by
  token exchange.

### Phase 3 — Lifecycle and ergonomics

- Replace one-shot Job with a Crossplane composition (Keycloak
  Crossplane provider) for declarative client lifecycle.
- Per-service ExternalSecret patterns documented as reusable templates.
- CLI helper for customers populating Secrets Manager when not using
  the reference Keycloak.
- Audit hardening: token signing key rotation, secret rotation policy.

---

## Open Questions / Follow-ups

1. **Hub naming** — keep the bare base domain (`peeks.dev.<base-domain>`)
   for hub or move to `hub.peeks.dev...` for symmetry with spokes? Bare
   preserves workshop convention. Decide before Phase 1 implementation.

2. **Wildcard certificate** — does the workshop CFN/Terraform already
   provision `*.peeks.dev.<base-domain>` or do we need to add it? Phase
   1 prerequisite.

3. **Hub Keycloak admin credentials** — currently in
   `peeks-hub/keycloak/admin` Secrets Manager entry. Confirm IRSA
   permissions on the provisioner ServiceAccount cover read of that
   secret and write of the per-env entries.

4. **Granular client model** — the design ships one client per
   (service, env). Customers running large agent fleets may want
   per-agent clients. Document the extension pattern; revisit if a
   user reports the need.

5. **Token exchange on Okta/Auth0** — quantify the gap. Sketch the
   alternative custom-header pattern in Phase 2 docs so customers on
   those providers can still implement audit identity.

6. **Backstage SSO alignment** — Backstage already integrates with
   Keycloak. Confirm Backstage works unchanged when a customer swaps
   to an external IdP, or document the matching SSO config change.

---

## References

- [RFC 8693 — OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693)
- [RFC 9728 — OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [Keycloak Token Exchange](https://www.keycloak.org/docs/latest/securing_apps/#_token-exchange)
- [Agent Platform Design — provider-agnostic principle](./DESIGN.md)
- [Modular Architecture / UPGRADE-APPROACH](../UPGRADE-APPROACH.md)
