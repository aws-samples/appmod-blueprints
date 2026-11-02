{{/*
Name of the per-member objects (ConfigMap + Job) this chart renders on the hub.

Keyed on the Helm release name, which the client-provisioner ApplicationSet
(gitops/bootstrap/client-provisioner.yaml) sets to
"client-provisioner-<clusterName>", i.e. one per fleet member. It used to be
"keycloak-client-provisioner-<environment>", so two members sharing an
environment label (e.g. an extra spoke labelled environment: dev) rendered the
same ConfigMap/Job in the hub keycloak namespace and Argo CD flagged a shared
resource (OutOfSync). Only the Kubernetes object names change: the Keycloak
clientId ("<name>-<environment>") and the Secrets Manager path
("<prefix>/<environment>/oidc/<name>") stay environment-scoped.
Truncated to 63 chars because the Job name is copied into pod labels.
*/}}
{{- define "keycloak-client-provisioner.name" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
