{{- /*
Forge of the fleet repo, DERIVED from values the registry entry already injects from
cluster-secret annotations (no new parameter):
  gitlabDomain  <- gitlab_domain_name
  fleetRepoUrl  <- overlay_repo_url, else a separate fleetRepoURL (registry platform.yaml)
Result:
  "gitlab"  gitlabDomain is set AND (the fleet repo host is that domain, case-insensitive,
            or there is no fleet repo URL). The workshop is always this case: the fleet repo
            is https://<GIT_DOMAIN>/<user>/fleet-config.git and gitlab_domain_name = GIT_DOMAIN.
  "none"    anything else: no GitLab domain, or a fleet repo on another host (github.com,
            GHES, a self-managed GitLab that is not gitlab_domain_name). Fail-safe: the agent
            is rendered read-only, without a forge MCP (the incident path stays, without its
            GitLab dup-check).
Optional chart value `forge` overrides the derivation: "" or "auto" (default) keeps it as
described above; "gitlab" or "none" forces that variant (e.g. "none" for a GitHub/GHES install
that sets gitlabDomain for another purpose). "gitlab" still needs gitlabDomain for the
gitlab-mcp API host. Any other value fails the render.
The host is the URL authority without scheme, user info or port (https://h/x, git@h:x).
Usage: include "aiops-agent.forge" $
*/ -}}
{{- define "aiops-agent.forge" -}}
{{- $override := .Values.forge | default "" | toString | lower -}}
{{- if not (has $override (list "" "auto" "gitlab" "none")) -}}
{{- fail (printf "aiops-agent: unknown forge %q (allowed: \"\", \"auto\", \"gitlab\", \"none\")" $override) -}}
{{- end -}}
{{- $url := .Values.fleetRepoUrl | default "" | toString -}}
{{- $host := lower (regexReplaceAll "^(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^@/]*@)?([^/:]*).*$" $url "${1}") -}}
{{- $gl := lower (.Values.gitlabDomain | default "" | toString) -}}
{{- if or (eq $override "gitlab") (eq $override "none") -}}{{- $override -}}
{{- else if and $gl (or (not $url) (eq $host $gl)) -}}gitlab{{- else -}}none{{- end -}}
{{- end -}}

{{- /*
IAM role name the platform's aws-service-identity trait gives a ServiceAccount of this
chart (platform/oam/definitions/traits/aws-service-identity.cue), so AccessEntries can
name the role the trait creates:
  <first 50 of "<cluster>-<sa>">-<sha256("<region>/<cluster>/<namespace>/<sa>")[:8]>-role
The trait requires global.clusterName, so this helper requires clusterPrefix.

ASSUMPTION: the trait reads the hub's real name (aws_cluster_name annotation); this chart
only has clusterPrefix, so it uses "<clusterPrefix>-hub", the same name the hub
AccessEntry and the spoke-access destination already assume. A hub named otherwise gets
AccessEntries for a role that does not exist.

Usage: include "aiops-agent.podIdentityRoleName" (dict "root" $ "sa" "aiops-agent")
*/ -}}
{{- define "aiops-agent.podIdentityRoleName" -}}
{{- $v := .root.Values -}}
{{- $cluster := printf "%s-hub" (required "aiops-agent: clusterPrefix is required (the hub is <clusterPrefix>-hub; the role and policy names derive from it)" $v.clusterPrefix) -}}
{{- $key := printf "%s/%s/aiops-agent/%s" $v.region $cluster .sa -}}
{{- printf "%s-%s-role" (printf "%s-%s" $cluster .sa | trunc 50) (sha256sum $key | trunc 8) -}}
{{- end -}}
