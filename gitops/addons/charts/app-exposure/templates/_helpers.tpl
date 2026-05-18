{{/*
Common helpers for app-exposure chart.
*/}}

{{/* Standard labels applied to all resources rendered by this chart. */}}
{{- define "app-exposure.labels" -}}
app.kubernetes.io/name: app-exposure
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
peeks.io/component: app-exposure
{{- end -}}

{{/* Name of the edge-config ConfigMap referenced by the RGD. */}}
{{- define "app-exposure.edgeConfigName" -}}
app-exposure-edge-config
{{- end -}}
