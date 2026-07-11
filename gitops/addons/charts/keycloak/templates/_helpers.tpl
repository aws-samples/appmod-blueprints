{{/*
keycloak.conf file content, shared between the keycloak-config ConfigMap and the
StatefulSet's checksum/config annotation (see templates/install.yaml). Keeping this in
one place ensures the checksum always reflects the actual rendered config — if the two
drifted, a config change could ship without triggering a pod restart, leaving Keycloak
running stale settings (e.g. hostname/SAML config) after `git pull` + ArgoCD sync only
updates the ConfigMap in place.
*/}}
{{- define "keycloak.conf" -}}
# Database
# The database vendor.
db=postgres

# The username of the database user.
db-url=jdbc:postgresql://postgresql.keycloak.svc.cluster.local:5432/postgres

# hostname settings — must use ingress_domain_name (platform CloudFront domain)
# Do NOT fall back to gitlab_domain_name — that domain routes to GitLab, not Keycloak
#
# IMPORTANT: `hostname` must be the bare base URL (scheme + host only), WITHOUT the
# /keycloak context path. `http-relative-path` below already supplies that path, and
# Keycloak appends it to `hostname` internally. Including "/keycloak" in BOTH settings
# causes a double-path bug in Keycloak's SAML metadata builder (observed on 26.3.3):
# the generated SAML EntityDescriptor/SSO/SLO Location URLs come out malformed as
# "https:/keycloak/realms/<realm>/..." (missing host, single slash after scheme),
# which AWS IAM Identity Center then rejects with "Unable to build attributes from
# provided metadata object as url validation failed" when importing the IdP metadata.
# OIDC is unaffected by this, which is why only the SAML/IDC federation flow broke.
# KC26 HostnameV2: hostname is used AS-IS for all generated URLs (issuer, SAML metadata).
# Include /keycloak in hostname so SAML URLs are correct.
# http-relative-path=keycloak is kept for Keycloak's own routing.
hostname=https://{{ .Values.global.ingress_domain_name }}/keycloak
hostname-admin=https://{{ .Values.global.ingress_domain_name }}/keycloak
hostname-strict=false
http-relative-path=keycloak
http-enabled=true
hostname-debug=true
# .../keycloak/realms/platform/hostname-debug

# Proxy configuration for CloudFront/ALB - use xforwarded for AWS setup
proxy-headers=xforwarded

# Enable account console and admin features
features=account,admin

# Development mode settings for better debugging
log-level=INFO
{{- end -}}
