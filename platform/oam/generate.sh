#!/usr/bin/env bash
# Generate KubeVela YAML ComponentDefinitions from CUE source files.
# Usage: ./generate.sh
# Requires: vela CLI (https://kubevela.io/docs/installation/kubernetes/#install-vela-cli)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUE_DIR="${SCRIPT_DIR}/definitions/components"
YAML_DIR="${SCRIPT_DIR}/../../gitops/addons/charts/kubevela/templates/components"

if ! command -v vela &>/dev/null; then
  echo "Error: vela CLI not found" >&2
  exit 1
fi

echo "Rendering CUE definitions → YAML"
echo "  Source: ${CUE_DIR}"
echo "  Output: ${YAML_DIR}"

vela def render "${CUE_DIR}" -o "${YAML_DIR}" \
  --message "# Code generated from CUE definitions. DO NOT EDIT."

echo "Done. Generated files:"
ls -1 "${YAML_DIR}"/*.yaml
