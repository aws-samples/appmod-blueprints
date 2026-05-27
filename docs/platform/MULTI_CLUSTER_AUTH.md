# Multi-Cluster Authentication

## Status

**Proposed** — Phase 1 implementation pending.

This document defines how authentication works across the hub and spoke
clusters of the Platform Engineering on EKS solution. It introduces a
generic **OIDC Provider Abstraction** so that customers can use the
reference Keycloak implementation, swap in their own provider (Okta,
Ping, Auth0, Azure AD, custom OIDC), or mix approaches.

The mechanism described here is a platform building block. Workloads
deployed onto the platform — whether internal services, customer
applications, or third-party stacks like the [Open Agentic Platform][1]
— consume this mechanism rather than reimplementing it. See
*Consumer Pattern* below.

[1]: https://github.com/aws-samples/sample-open-agentic-platform

## Context

The platform is deployed across multiple clusters:

- **Hub** (`peeks-hub`) — control plane: IdP, ArgoCD, Crossplane,
  Backstage.
- **Spokes** (`peeks-spoke-dev`, `peeks-spoke-prod`) — workload clusters
  hosting customer and platform services that need to authenticate end
  users and machine clients.

Each cluster exposes user-facing services through an ALB ingress.
Services that protect their endpoints typically validate JWTs issued by
the platform's IdP.

### Current state (problems we are solving)

1. **Single shared hostname across clusters**: ingresses on multiple
   clusters were configured with the same hostname, causing DNS
   conflicts. ExternalDNS on each cluster races for the same Route 53
   record.

2. **Workloads on spokes cannot validate JWTs**: when a workload's JWT
   policy references the IdP via an in-cluster Service
   (`keycloak.keycloak.svc.cluster.local`), the lookup fails on spokes
   because the IdP only runs on the hub. JWKS fetch fails, the policy
   is `PartiallyValid`, and authentication is effectively broken.

3. **No per-environment client provisioning**: there is no mechanism
   that creates OAuth clients for each environment. Workloads either
   reuse hub-only clients (no isolation) or have no clients at all
   (no machine-to-machine flows).

4. **No customer extension path**: the platform was wired directly to
   Keycloak. Most enterprise customers already operate an IdP (Okta,
   Ping, Azure AD) and need to plug it in without forking the platform.

## Goals

- **Single IdP, multi-cluster validation**: tokens issued by one IdP
  can be validated by resource servers on any cluster.
- **Per-environment isolation**: each environment (dev, prod, hub) has
  distinct DNS, distinct OAuth clients, and distinct token audiences.
- **Provider-agnostic consumers**: charts and workloads that consume
  OIDC must not depend on Keycloak specifics. They speak OIDC.
- **Pluggable provisioner**: the component that creates OAuth clients
  in the IdP is provider-specific, but conforms to a stable contract
  that customer-built provisioners can also satisfy.
- **Reference implementation**: ship a working Keycloak reference so
  the workshop is self-contained.

## Non-Goals

- **Federated multi-IdP topologies**: running a separate IdP on each
  spoke and federating between them. Significantly more complex and
  unnecessary at workshop scale.
- **Kubernetes-native workload identity** (SPIFFE/SPIRE) for
  service-to-service authentication. Out of scope here; could be a
  future addition.
- **VPC peering or PrivateLink for in-cluster JWKS**. Public JWKS over
  HTTPS is the standard pattern and avoids cross-cluster networking
  complexity.
- **Workload-specific authorization semantics**. This document
  defines the auth foundation. Workloads define their own authorization
  policies (group/role mappings, scope checks) on top of it.

---

## OIDC Provider Abstraction

The key insight enabling provider portability: most of what we need
from an IdP is **OIDC standard**. Only client provisioning is
provider-specific.

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

**Path convention**: `peeks/<env>/oidc/<client-name>`

Examples: `peeks/dev/oidc/my-service-client`,
`peeks/prod/oidc/checkout-api-client`.

**Schema** (JSON):

```json
{
  "client_id":       "my-service-dev",
  "client_secret":   "<opaque-string>",
  "issuer":          "https://login.example.com/oauth2/default",
  "jwks_uri":        "https://login.example.com/oauth2/default/v1/keys",
  "token_endpoint":  "https://login.example.com/oauth2/default/v1/token",
  "audience":        "my-service-dev",
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
- For pure resource servers (services that validate tokens but never
  issue them), the entry may omit `client_secret` and exists only to
  publish issuer/JWKS/audience metadata.

**Consumers** (charts, workloads) read this via ExternalSecrets,
projected into a Kubernetes Secret with the same key names. They never
speak Keycloak, Okta, or any other admin API directly.

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
                            │  Consumer workloads            │  (same)             │
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
domain. Hub keeps the bare base domain to preserve workshop convention.

| Environment | Hostname |
|---|---|
| Hub (control plane) | `peeks.dev.<base-domain>` |
| Spoke-dev | `dev.peeks.dev.<base-domain>` |
| Spoke-prod | `prod.peeks.dev.<base-domain>` |

ExternalDNS on each cluster manages records in the same Route 53
hosted zone. TLS is satisfied by either a wildcard ACM cert
(`*.peeks.dev.<base-domain>`) or per-env ACM certs (one per
`<env>.peeks.dev.<base-domain>`); ingress charts accept a configurable
certificate ARN so either model works.

**Alternatives considered**:

- **Service-prefixed subdomain** (e.g., `service-dev.peeks.dev...`) —
  rejected as the per-env scheme keeps things simpler and we can add
  service prefixes later if a single env needs multiple top-level
  ingresses.
- **Path prefix on hub** (e.g., `peeks.dev/spokes/dev/...`) — rejected
  because it makes the hub a network choke point, defeats
  multi-cluster decoupling, and complicates ALB routing.

### D2: JWT validation — public JWKS over HTTPS

**Decision**: spokes fetch JWKS directly from the IdP's public OIDC
discovery endpoint. Most JWT-aware proxies and frameworks support
remote JWKS with caching.

**Alternatives considered**:

- **JWKS sync via ExternalSecrets** — rejected as added complexity for
  marginal benefit. JWKS over HTTPS with caching handles the same
  failure modes as ExternalSecrets sync (the IdP being unreachable
  affects both).
- **VPC peering / PrivateLink** — rejected as heavy infrastructure for
  a problem standard OIDC already solves.

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

### D4: Client model — driven by consumer requirements

**Decision**: the platform does not prescribe a fixed set of clients.
Consumers declare their required clients per env, and the provisioner
materializes them.

A consumer registers clients by providing a values fragment to the
provisioner Helm release:

```yaml
clients:
  - name: my-service
    env: dev
    type: confidential                  # or "public"
    flows: [resource_server]            # or client_credentials,
                                        #    authorization_code, etc.
    audience: my-service-dev
    consumerSecretPath: peeks/dev/oidc/my-service-client
```

The provisioner ensures one client exists per `(name, env)` pair and
publishes the contract entry at `consumerSecretPath`.

This is a reasonable starting point. Consumers can adjust granularity
(more or fewer clients, per-instance vs shared) without changing the
contract.

**Alternative considered**: per-cluster clients. Rejected because in
practice an environment is bigger than a cluster (a customer's "dev"
environment may span multiple clusters), and naming them per cluster
creates churn whenever clusters are recreated.

### D5: Client lifecycle — create, do not delete on cluster destruction

**Decision**: clients live with the environment, not the cluster.
Destroying a cluster does not delete the client. Re-provisioning the
cluster reuses the existing client.

The provisioner Job is **idempotent**: it skips client creation when
one already exists, and only refreshes the Secrets Manager entry if
it is missing or invalid.

**Rationale**: an environment may have multiple clusters (blue/green,
DR, regions). Tying client identity to cluster lifecycle would create
dangling secrets and break consumers in other clusters of the same
env.

### D6: Group/role claim — configurable

**Decision**: the path to group claims in the JWT is a configurable
value (`groups_claim`). Authorization expressions in consumer
workloads are templated against this path.

Default `groups`. Customers configure per provider.

**Rationale**: Keycloak realm roles live at `realm_access.roles`,
Okta groups at `groups`, Azure AD app roles at `roles`. Hard-coding
any of these breaks the others.

---

## Reference Implementation: Keycloak

### Components

| Component | Location | Purpose |
|---|---|---|
| Keycloak (existing) | `gitops/addons/charts/keycloak/` | The IdP itself. Hosts the platform realm. |
| `keycloak-client-provisioner` (new) | `gitops/addons/charts/keycloak-client-provisioner/` | Helm chart wrapping a Job that creates clients via Keycloak admin API and writes to AWS Secrets Manager. |

### Provisioner Job behaviour

For each registered environment in the fleet:

1. Authenticate to Keycloak admin API using IRSA-derived credentials
   stored in AWS Secrets Manager (`peeks/hub/keycloak/admin`).
2. For each client declared by consumers (D4):
   - Check if the client exists in the platform realm.
   - If not, create it with the requested flow configuration and
     audience mapper.
   - Read or rotate the client secret as needed.
   - Write the contract schema to the consumer-specified
     Secrets Manager path.
3. Exit. The Job is fire-and-forget; rerunning is safe.

### ExternalSecret pattern on consumers

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: my-service-oidc-client
  namespace: my-service-system
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: my-service-oidc-client
  dataFrom:
    - extract:
        key: peeks/{{ .Values.env }}/oidc/my-service-client
```

The consumer chart consumes the resulting K8s Secret. No Keycloak
URLs or SDK calls in the chart itself.

---

## Replacing With an External OIDC Provider

Customers integrating with Okta, Ping, Auth0, Azure AD, or a custom
OIDC implementation have **three paths**.

### Path A — Reference Keycloak (default)

Deploy as-is. Workshop uses this. No customer action required.

### Path B — External OIDC, manual client provisioning

The customer's IdP is the source of truth. Clients are created
out-of-band (via the IdP's admin console, customer's IaC, or existing
identity governance).

Customer steps:

1. **Disable Keycloak** in the platform: set `enable_keycloak: false`
   and `enable_keycloak_client_provisioner: false` on cluster secrets.
2. **Manually provision clients** in the external IdP, matching the
   names and audiences each consumer declares (D4).
3. **Populate Secrets Manager** with entries matching the contract
   schema. For example:
   ```bash
   aws secretsmanager create-secret \
     --name peeks/dev/oidc/my-service-client \
     --secret-string '{
       "client_id": "my-service-dev",
       "client_secret": "...",
       "issuer": "https://acme.okta.com/oauth2/default",
       "jwks_uri": "https://acme.okta.com/oauth2/default/v1/keys",
       "token_endpoint": "https://acme.okta.com/oauth2/default/v1/token",
       "audience": "my-service-dev",
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
   - Reads consumer client declarations.
   - Calls their IdP's admin API to create the required clients.
   - Writes the contract schema to
     `peeks/<env>/oidc/<client-name>` in AWS Secrets Manager.
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

- **Delegated identity / "on-behalf-of"** flows (e.g., `act` claim,
  RFC 8693 token exchange) work cleanly on Keycloak, Ping, and Azure
  AD. On Okta and Auth0, alternative patterns are needed (e.g.,
  propagate user identity in a custom header alongside the machine's
  token, log application-side with multi-token correlation). Consumers
  that need delegation document their fallback for these providers.
- **Group claim** location varies. The platform exposes
  `groups_claim` per env so authorization expressions in consumer
  workloads can be retargeted.

---

## Consumer Pattern

A workload or workload-stack that needs OIDC consumes the platform
mechanism by:

1. **Declaring its required clients** in a values fragment passed to
   the provisioner (D4). Includes per-env names, types, flows, and
   audiences.
2. **Reading the contract entries** via ExternalSecrets in the cluster
   where the workload runs.
3. **Configuring its own JWT validation** using the issuer, JWKS URL,
   audience, and group claim path provided by the contract.
4. **Configuring its own ingress hostname** as
   `<env>.peeks.dev.<base-domain>` (or service-prefixed subdomain if
   needed).

Workloads do not embed Keycloak-specific URLs or admin-API calls. They
work the same way regardless of which IdP the platform is configured
with.

### Example consumers

- **[Open Agentic Platform](https://github.com/aws-samples/sample-open-agentic-platform)** — declares
  `agentgateway-<env>` and `agent-runtime-<env>` clients. See its
  consumption doc for specifics.
- **Customer applications** — register their own clients (one or more
  per env) and configure their middleware (e.g., oauth2-proxy, Envoy
  JWT filter, Spring Security, ASP.NET JwtBearer) against the contract.

---

## Implementation Plan

### Phase 1 — Foundation

Goal: working multi-cluster auth with Keycloak as the IdP.

**In `appmod-blueprints`:**

1. **New chart** `gitops/addons/charts/keycloak-client-provisioner/`
   - Job + ServiceAccount + IRSA for Secrets Manager
   - Idempotent client creation against Keycloak admin API
   - Reads consumer client declarations from values, materializes them
   - Writes contract schema entries
2. **Modify** `gitops/fleet/members/spoke-{dev,prod}/values.yaml`
   - Add `env: dev` / `env: prod` labels
3. **TLS certificate**: provision an ACM cert covering the per-env
   hostnames. Reference module uses a wildcard
   `*.peeks.dev.<base-domain>`; per-env certs are equally supported.
4. **Cluster secret labels**: add `oidc_issuer_url` (default points at
   reference Keycloak; customers override).
5. **Documentation**: this doc + a short consumer guide for chart
   authors.

**Acceptance criteria:**

- Per-env DNS resolves correctly; no Route 53 conflicts.
- For a sample consumer with a declared client `sample-dev`,
  `peeks/dev/oidc/sample-client` exists in Secrets Manager and
  contains the contract schema.
- ExternalSecrets in the dev spoke pulls the secret into a K8s Secret
  successfully.
- A token issued for `audience=sample-dev` is rejected by a separate
  consumer expecting `audience=other-dev`.
- Re-running the provisioner Job is a no-op when clients already
  exist.

### Phase 2 — Delegation and audit identity

Goal: support delegated-identity patterns ("user X did Y via service
Z") for consumers that need it.

1. Configure the platform realm (Keycloak) with token-exchange
   permission for clients that opt in via D4.
2. Document the standard `act`-claim pattern (RFC 8693) and the
   alternative custom-header pattern for non-supporting providers.
3. Provide a reusable structured-logging convention so consumer
   workloads can emit `user=...` and `actor=...` fields uniformly.

### Phase 3 — Lifecycle and ergonomics

- Replace one-shot Job with a Crossplane composition (Keycloak
  Crossplane provider) for declarative client lifecycle.
- Per-service ExternalSecret patterns documented as reusable templates.
- CLI helper for customers populating Secrets Manager when not using
  the reference Keycloak.
- Audit hardening: token signing key rotation, secret rotation policy.

---

## Open Questions / Follow-ups

1. **Hub Keycloak admin credentials** — currently in
   `peeks-hub/keycloak/admin` Secrets Manager entry. Confirm IRSA
   permissions on the provisioner ServiceAccount cover read of that
   secret and write of the per-env entries.

2. **Consumer client declaration mechanism** — the design assumes
   consumers pass values to the provisioner Helm release. Should we
   also support a CRD-style declaration (`OIDCClient` custom resource
   that the provisioner watches)? More Kubernetes-native, more code.
   Defer until customer demand is concrete.

3. **Token exchange on Okta/Auth0** — quantify the gap. The Phase 2
   alternative custom-header pattern needs a worked example so
   consumers on those providers can implement delegated identity.

4. **Backstage SSO alignment** — Backstage already integrates with
   Keycloak. Confirm Backstage works unchanged when a customer swaps
   to an external IdP, or document the matching SSO config change.

---

## References

- [RFC 8693 — OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693)
- [RFC 9728 — OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [Keycloak Token Exchange](https://www.keycloak.org/docs/latest/securing_apps/#_token-exchange)
- [GitOps Bridge Architecture](./gitops-bridge-architecture.md)
- [Modular Architecture / UPGRADE-APPROACH](../UPGRADE-APPROACH.md)
