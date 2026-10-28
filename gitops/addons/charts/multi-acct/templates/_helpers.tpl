{{/*
multi-acct.hub -> "<name>=<account>" of the ONE cluster this chart covers: the hub it runs on,
or "" when there is nothing to render.

multi-acct renders the HUB's own CARM coverage only (its Namespace and IAMRoleSelectors).
Spoke coverage is owned by the kro-clusters chart, which renders the selectors of every spoke
it defines (gitops/abstractions/kro/kro-clusters/templates/iam-role-selectors.yaml), so a
spoke can no longer exist without its selectors and no object has two owners.

.Values.clusters (configs/multi-acct/values.yaml in the fleet repo) is read for ONE key only:
the hub's own name, to pin a different account for the hub. Every other key is a legacy spoke
entry (written by spokes:enable-kro before this change, or by hand) and is IGNORED: the same
objects are now rendered by clusters-kro-<spoke>, which adopts them in place (see the
kro-clusters README, "Migration"). Ignoring rather than failing keeps existing fleet repos
rendering after the upgrade; deleting those entries is optional cleanup.

Why self-coverage: ACK cannot reconcile ANY resource in a namespace that no selector covers
-- it creates the CR and then silently never reconciles it (no error, no events) -- so without
it every hub-side ACK resource (notably the ack-pod-identity addon) fails silently on a
from-scratch install. Derived from global.clusterName rather than a hardcoded name or the
resource prefix: cluster names are customer-supplied and arbitrary.
*/}}
{{- define "multi-acct.hub" -}}
{{- $clusters := default dict .Values.clusters -}}
{{- $self := default "" .Values.global.clusterName -}}
{{- if $self -}}
{{-   $pinned := hasKey $clusters $self -}}
{{-   $acct := (get $clusters $self) | default .Values.global.accountId | default "" | toString -}}
{{-   if $acct -}}
{{- printf "%s=%s" $self $acct -}}
{{-   else if $pinned -}}
{{-     fail (printf "multi-acct: hub %q has no AWS account. Set clusters.%s to an account ID, or provide global.accountId. Without one the IAMRoleSelector ARN renders as arn:aws:iam:::role/... which ACK silently never reconciles." $self $self) -}}
{{-   end -}}
{{- end -}}
{{- end -}}
