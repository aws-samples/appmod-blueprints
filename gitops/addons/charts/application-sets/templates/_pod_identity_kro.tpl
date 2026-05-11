{{/*
Template to generate pod-identity configuration via kro + ACK
Uses the kro-pi-instance chart (gitops/addons/charts/kro/instances/pod-identity)
which expands to ACK iam.Policy + iam.Role + eks.PodIdentityAssociation via the
RGD podidentity.kro.run (gitops/addons/charts/kro/resource-groups/manifests/pod-identity).
*/}}
{{- define "application-sets.pod-identity-kro" -}}
{{- $chartName := .chartName -}}
{{- $chartConfig := .chartConfig -}}
{{- $valueFiles := .valueFiles -}}
{{- $values := .values -}}
{{- $pi := $chartConfig.podIdentity -}}
- repoURL: '{{ $values.repoURLGit }}'
  targetRevision: '{{ $values.repoURLGitRevision }}'
  path: 'gitops/addons/charts/kro/instances/pod-identity'
  helm:
    releaseName: '{{`{{ .name }}`}}-{{ $chartConfig.chartName | default $chartName }}-pi'
    valuesObject:
      name: '{{`{{ .name }}`}}-{{ $chartConfig.chartName | default $chartName }}'
      clusterName: '{{`{{ .name }}`}}'
      region: '{{`{{ .metadata.annotations.aws_region }}`}}'
      accountId: '{{`{{ .metadata.annotations.aws_account_id }}`}}'
      piNamespace: {{ default $chartConfig.namespace $pi.piNamespace }}
      serviceAccounts:
      {{- toYaml $pi.serviceAccounts | nindent 6 }}
      policyDocument:
      {{- toYaml $pi.policyDocument | nindent 6 }}
    ignoreMissingValueFiles: true
{{- end }}
