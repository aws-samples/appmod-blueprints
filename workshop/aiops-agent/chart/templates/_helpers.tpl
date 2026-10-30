{{- /*
IAM role name the platform's aws-service-identity trait gives a ServiceAccount of this
chart (platform/oam/definitions/traits/aws-service-identity.cue), so AccessEntries can
name the role the trait creates:
  <first 50 of "<cluster>-<sa>">-<sha256("<region>/<cluster>/<namespace>/<sa>")[:8]>-role
and "<sa>-role" without a cluster, as the trait does without global.clusterName.

ASSUMPTION: the trait reads the hub's real name (aws_cluster_name annotation); this chart
only has clusterPrefix, so it uses "<clusterPrefix>-hub", the same name the hub
AccessEntry and the spoke-access destination already assume. A hub named otherwise gets
AccessEntries for a role that does not exist.

Usage: include "aiops-agent.podIdentityRoleName" (dict "root" $ "sa" "aiops-agent")
*/ -}}
{{- define "aiops-agent.podIdentityRoleName" -}}
{{- $v := .root.Values -}}
{{- if not $v.clusterPrefix -}}
{{- printf "%s-role" .sa -}}
{{- else -}}
{{- $cluster := printf "%s-hub" $v.clusterPrefix -}}
{{- $key := printf "%s/%s/aiops-agent/%s" $v.region $cluster .sa -}}
{{- printf "%s-%s-role" (printf "%s-%s" $cluster .sa | trunc 50) (sha256sum $key | trunc 8) -}}
{{- end -}}
{{- end -}}
