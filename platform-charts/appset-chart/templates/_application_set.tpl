{{/*
Template to generate additional resources configuration.
Iterates over $chartConfig.additionalResources as a list, rendering one
additional source entry per item. Supports three resource types:
  - manifest-type: uses repoURLGitBasePath for path construction
  - chart-type: uses the resource's own repoURL and chart
  - path-type: uses the resource's path field directly
Each resource with helm config gets its own releaseName, valuesObject, and valueFiles.
*/}}
{{- define "application-sets.additionalResources" -}}
{{- $chartName := .chartName -}}
{{- $chartConfig := .chartConfig -}}
{{- $valueFiles := .valueFiles -}}
{{- $values := .values -}}

{{- range $resource := $chartConfig.additionalResources }}
{{- if and $resource.repoURL $resource.chart }}
- repoURL: {{ $resource.repoURL | squote }}
  chart: {{ $resource.chart | squote }}
  targetRevision: {{ $resource.chartVersion | default "latest" | squote }}
{{- else }}
- repoURL: {{ $values.repoURLGit | squote }}
  targetRevision: {{ $values.repoURLGitRevision | squote }}
  path: {{- if eq (default "" $resource.type) "manifests" }}
    '{{ $values.repoURLGitBasePath }}/{{ $chartName }}{{ if $values.useValuesFilePrefix }}{{ $values.valuesFilePrefix }}{{ end }}/{{ $resource.manifestPath }}'
  {{- else }}
    {{ $resource.path | squote }}
  {{- end }}
{{- end }}
{{- if and $resource.helm (ne (default "" $resource.type) "manifest") }}
  helm:
    releaseName: '{{`{{ .name }}`}}-{{ $resource.helm.releaseName }}'
    {{- if $resource.helm.valuesObject }}
    valuesObject:
    {{- $resource.helm.valuesObject | toYaml | nindent 6 }}
    {{- end }}
    ignoreMissingValueFiles: true
    valueFiles:
    {{- include "application-sets.valueFiles" (dict
      "nameNormalize" $chartName
      "chartConfig" $chartConfig
      "valueFiles" $valueFiles
      "values" $values
      "chartType" $resource.type) | nindent 6 }}
{{- end }}
{{- end }}
{{- end }}


{{/*
Generate value file paths for Helm sources.
Layering order:
  1. Default addon config values (from repoURLGitBasePath/<addon>/values.yaml)
  2. Per-addon custom valueFiles (from chartConfig.valueFiles)
  3. Environment overlay values (from overlayBasePath/environments/<env>/<addon>/values.yaml)
  4. Cluster overlay values (from overlayBasePath/clusters/<cluster>/<addon>/values.yaml)
All paths use ignoreMissingValueFiles: true so missing files are silently skipped.
*/}}
{{- define "application-sets.valueFiles" -}}
{{- $nameNormalize := .nameNormalize -}}
{{- $chartConfig := .chartConfig -}}
{{- $valueFiles := .valueFiles -}}
{{- $chartType := .chartType -}}
{{- $values := .values -}}
{{/* 1. Default addon config values */}}
{{- with .valueFiles }}
{{- range . }}
- $values/{{ $values.repoURLGitBasePath }}/{{ $nameNormalize }}{{ if $chartType }}/{{ $chartType }}{{ end }}/{{ if $chartConfig.valuesFileName }}{{ $chartConfig.valuesFileName }}{{ else }}{{ . }}{{ end }}
{{- if $values.useValuesFilePrefix }}
- $values/{{ $values.repoURLGitBasePath }}/{{ $values.valuesFilePrefix }}{{ . }}/{{ $nameNormalize }}{{ if $chartType }}/{{ $chartType }}{{ end }}/{{ if $chartConfig.valuesFileName }}{{ $chartConfig.valuesFileName }}{{ else }}values.yaml{{ end }}
{{- end }}
{{- end }}
{{- end }}
{{/* 2. Per-addon custom valueFiles */}}
{{- with $chartConfig.valueFiles }}
{{- range . }}
- $values/{{ $values.repoURLGitBasePath }}/{{ $nameNormalize }}{{ if $chartType }}/{{ $chartType }}{{ end }}/{{ if $chartConfig.valuesFileName }}{{ $chartConfig.valuesFileName }}{{ else }}{{ . }}{{ end }}
{{- end }}
{{- end }}
{{/* 3. Environment overlay values */}}
{{- if $values.overlayBasePath }}
- $values/{{ $values.overlayBasePath }}/environments/{{`{{.metadata.labels.environment}}`}}/{{ $nameNormalize }}{{ if $chartType }}/{{ $chartType }}{{ end }}/values.yaml
{{/* 4. Cluster overlay values */}}
- $values/{{ $values.overlayBasePath }}/clusters/{{`{{.nameNormalized}}`}}/{{ $nameNormalize }}{{ if $chartType }}/{{ $chartType }}{{ end }}/values.yaml
{{- end }}
{{- end }}
