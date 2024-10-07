#!/bin/bash
  set -e
  
  INSTALL_YAML="./gitea-install.yaml"
  GITEA_DIR="."
  CHART_VERSION="10.1.4"
  DOMAIN_NAME=$1
  
  echo "# GITEA INSTALL RESOURCES" >${INSTALL_YAML}
  echo "# This file is auto-generated with 'gitea/generate-manifests.sh'" >>${INSTALL_YAML}
  sed "s/DOMAIN_NAME/${DOMAIN_NAME}/g" ${GITEA_DIR}/values.yaml.tmpl > ${GITEA_DIR}/values.yaml
  
  helm repo add gitea-charts --force-update https://dl.gitea.com/charts/
  helm repo update
  helm template my-gitea gitea-charts/gitea -f ${GITEA_DIR}/values.yaml --version ${CHART_VERSION}>>${INSTALL_YAML}
  sed -i.bak '3d' ${INSTALL_YAML}

  sed -i.bak 's/namespace: default/namespace: gitea/g' ${INSTALL_YAML}

  kubectl apply -n gitea -f ${INSTALL_YAML}