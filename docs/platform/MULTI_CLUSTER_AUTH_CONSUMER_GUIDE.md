# OIDC Consumer Guide

**Audience**: chart authors adding OIDC-secured workloads (sidecars, oauth2-proxy, Envoy JWT
filter, Spring Security, ASP.NET JwtBearer, etc.) to the platform.

**Prerequisite**: The `keycloak-client-provisioner` (or equivalent IdP provisioner chart) is
deployed for the target environment. See
[MULTI_CLUSTER_AUTH.md §D4](./MULTI_CLUSTER_AUTH.md) for how clients are declared and
provisioned.

---

## What the platform provides

Every spoke cluster secret in ArgoCD carries two annotations written by the `fleet-secret`
chart:

| Annotation | Default | Description |
|---|---|---|
| `oidc_issuer_url` | `""` | HTTPS issuer base URL (e.g. `https://keycloak.dev.peeks.example.com/realms/peeks`) |
| `oidc_insecure_origin` | `"false"` | Set to `"true"` **only** in dev/exploration for HTTP-between-LB-and-cluster scenarios — see §D7 of the design doc |

And one existing annotation useful for ingress hostname construction:

| Annotation | Example |
|---|---|
| `ingress_domain_name` | `dev.peeks.example.com` |

These annotations are populated at bootstrap time by the `fleet-secrets` ApplicationSet
reading them from the hub cluster secret (seeded by Terraform/Crossplane). Until Batch B
lands, `oidc_issuer_url` defaults to `""`.

---

## Step 1 — Declare your OIDC client

Pass a `clients` fragment to the provisioner chart (either as a dependency or via a shared
values file):

```yaml
# In your chart's values.yaml or the provisioner release values
clients:
  - name: my-service
    environment: dev          # matches .labels.environment on the fleet-member values
    type: confidential        # or "public"
    flows: [resource_server]  # or authorization_code, client_credentials, etc.
    audience: my-service-dev
    consumerSecretPath: peeks/dev/oidc/my-service-client
```

The provisioner creates the client in Keycloak (or your IdP) and writes the contract to
`peeks/<environment>/oidc/<client-name>` in AWS Secrets Manager.

---

## Step 2 — Read the OIDC contract via ExternalSecret

Create an `ExternalSecret` that pulls the contract written by the provisioner:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: my-service-oidc-client
  namespace: my-service
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  refreshInterval: "5m"
  target:
    name: my-service-oidc-client
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: peeks/{{ .Values.environment }}/oidc/my-service-client
```

The resulting Kubernetes Secret contains these keys (written by the provisioner per the
[contract schema](./MULTI_CLUSTER_AUTH.md)):

| Key | Example |
|---|---|
| `client_id` | `my-service-dev` |
| `client_secret` | `<secret>` (empty for public clients) |
| `issuer` | `https://keycloak.dev.peeks.example.com/realms/peeks` |
| `jwks_uri` | `<issuer>/protocol/openid-connect/certs` |
| `token_endpoint` | `<issuer>/protocol/openid-connect/token` |
| `audience` | `my-service-dev` |
| `groups_claim` | `realm_access.roles` (Keycloak default) |

---

## Step 3 — Configure JWT validation

Reference the Secret from your workload. Example for oauth2-proxy:

```yaml
# oauth2-proxy Deployment env vars
env:
  - name: OAUTH2_PROXY_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: my-service-oidc-client
        key: client_id
  - name: OAUTH2_PROXY_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: my-service-oidc-client
        key: client_secret
  - name: OAUTH2_PROXY_OIDC_ISSUER_URL
    valueFrom:
      secretKeyRef:
        name: my-service-oidc-client
        key: issuer
```

### Insecure-origin mode (dev/exploration only)

When `oidc_insecure_origin: "true"` is set on the cluster secret (opt-in, see §D7 of the
design doc), the LB terminates TLS but the in-cluster hop is plain HTTP. The `issuer`
value in the contract still reflects the HTTPS hostname (what external clients see). Your
JWT-validating component must be configured to **skip TLS verification on the JWKS fetch
only** — not to accept HTTP tokens. For oauth2-proxy, add:

```yaml
  - name: OAUTH2_PROXY_SSL_INSECURE_SKIP_VERIFY
    value: "true"
```

**Do not enable this in production.** Its sole purpose is local/lab environments where
you cannot provision a valid TLS cert for the internal service.

---

## Step 4 — Construct your ingress hostname

Use the `ingress_domain_name` annotation from the cluster secret (already plumbed as
`hub.domain` in the fleet-secret chart and available as a value in any addon chart that
references it via the ApplicationSet's `valuesObject`):

```
<service>.<environment>.<ingress_domain_name>
# e.g. my-service.dev.peeks.example.com
```

Or use the environment-level subdomain directly when a single ingress covers the
whole environment:

```
<environment>.<ingress_domain_name>
# e.g. dev.peeks.example.com
```

---

## Per-IdP notes

### Keycloak (platform default)
- `groups_claim`: `realm_access.roles`
- Tokens include roles under `realm_access.roles[]` (string array)
- Client scopes: the provisioner sets `roles` scope by default

### Okta
- `groups_claim`: `groups`
- Requires "Groups" claim added to the Access Token in the Okta app

### Azure AD / Entra ID
- `groups_claim`: `roles` (app roles) or `groups` (security group OIDs)
- Use `roles` claim with app roles for explicit RBAC; `groups` gives OIDs that need a
  Graph API lookup for human-readable names

### Auth0
- `groups_claim`: custom — typically `https://your-namespace/roles` (namespaced custom claim)
- Set the namespace in the Action/Rule that adds the claim

---

## Reading cluster annotations directly in a chart template

If your addon chart needs to read `oidc_issuer_url` at Helm render time (rather than
at runtime via a Secret), it is available through the ApplicationSet's `valuesObject`
as a Helm value. Add it to your chart's values block and reference it in the ApplicationSet
that deploys your chart:

```yaml
# In your ApplicationSet valuesObject (example)
oidcIssuerUrl: '{{ or (index .metadata.annotations "oidc_issuer_url") "" }}'
oidcInsecureOrigin: '{{ or (index .metadata.annotations "oidc_insecure_origin") "false" }}'
```

The `or (index ...)` pattern is required because the hub cluster secret may not carry
these annotations yet (before Batch B lands), and both ApplicationSets use
`goTemplateOptions: ["missingkey=error"]`.

---

## Related docs

- [MULTI_CLUSTER_AUTH.md](./MULTI_CLUSTER_AUTH.md) — full design (D1–D7)
- [HUB_NETWORKING.md](./HUB_NETWORKING.md) — VPC and domain ownership design
