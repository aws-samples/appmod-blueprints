{{/*
Expand the name of the chart.
*/}}
{{- define "fleet-secret.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "fleet-secret.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "fleet-secret.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "fleet-secret.labels" -}}
helm.sh/chart: {{ include "fleet-secret.chart" . }}
{{ include "fleet-secret.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "fleet-secret.selectorLabels" -}}
app.kubernetes.io/name: {{ include "fleet-secret.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "fleet-secret.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "fleet-secret.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Effective addon enablement map: .Values.defaultEnabledAddons overlaid by
.Values.enabledAddons, key by key.

defaultEnabledAddons is set by the platform (appmod) for the clusters where it
wants a capability on unless the consumer says otherwise. Today only the hub
ApplicationSet (gitops/bootstrap/hub-fleet-secret.yaml) sets it, to turn the
Crossplane abstractions on for the hub. enabledAddons comes from the consumer's
enabled-addons.yaml and always wins, including an explicit `false`.

A plain loop with `set` is used instead of mergeOverwrite on purpose:
mergeOverwrite treats `false` as an empty value and would NOT let a consumer
switch a default off.

Returns YAML; callers use `include ... | fromYaml`.
*/}}
{{- define "fleet-secret.enabledAddons" -}}
{{- $eff := dict -}}
{{- range $addon, $enabled := (.Values.defaultEnabledAddons | default dict) }}
{{- $_ := set $eff $addon $enabled -}}
{{- end }}
{{- range $addon, $enabled := (.Values.enabledAddons | default dict) }}
{{- $_ := set $eff $addon $enabled -}}
{{- end }}
{{- toYaml $eff -}}
{{- end }}
