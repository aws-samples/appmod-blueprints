#!/bin/bash
  set -e

  INSTALL_YAML="./scripts/gitea/gitea-install.yaml"
  kubectl delete -f ${INSTALL_YAML} --namespace gitea >/dev/null 2>&1 || true
  rm -f ${INSTALL_YAML} ${GITEA_DIR}/values.yaml ${INSTALL_YAML}.bak