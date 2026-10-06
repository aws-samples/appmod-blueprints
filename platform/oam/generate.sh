#!/usr/bin/env bash
# Generate KubeVela ComponentDefinition / TraitDefinition YAML from CUE sources.
#
#   platform/oam/definitions/components/*.cue -> gitops/addons/charts/kubevela/templates/components/
#   platform/oam/definitions/traits/*.cue     -> gitops/addons/charts/kubevela/templates/traits/
#
# Usage: platform/oam/generate.sh
#
# Requires the vela CLI and a reachable KubeVela cluster in the current kube
# context: `vela def render` resolves CUE packages from the cluster and fails
# without one.
#
# Output file names follow the CUE file names, so each .cue overwrites the YAML of
# the same name. Only definitions that have a CUE source are written; the chart's
# other templates are untouched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFS_DIR="${SCRIPT_DIR}/definitions"
CHART_TEMPLATES="${SCRIPT_DIR}/../../gitops/addons/charts/kubevela/templates"
MESSAGE="# Code generated from CUE definitions. DO NOT EDIT."

if ! command -v vela &>/dev/null; then
  echo "Error: vela CLI not found" >&2
  exit 1
fi

for kind in components traits; do
  src="${DEFS_DIR}/${kind}"
  out="${CHART_TEMPLATES}/${kind}"
  [ -d "${src}" ] || continue
  echo "Rendering ${src} -> ${out}"
  # vela exits non-zero without a message when it cannot reach a cluster, so say why.
  if ! vela def render "${src}" -o "${out}" --message "${MESSAGE}"; then
    echo "Error: vela def render failed for ${src}." >&2
    echo "  It needs a reachable KubeVela cluster in the current kube context" >&2
    echo "  (current: $(kubectl config current-context 2>/dev/null || echo none))." >&2
    echo "  A CUE syntax error is reported above; other files may already be written," >&2
    echo "  so check: git status -- gitops/addons/charts/kubevela/templates" >&2
    exit 1
  fi
done

echo "Done. Review with: git diff --stat -- gitops/addons/charts/kubevela/templates"
