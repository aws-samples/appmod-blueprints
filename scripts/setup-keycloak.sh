#!/bin/bash
#
# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

#title           setup-keycloak.sh
#description     This script sets up keycloak related resources for Amazon Managed Grafana SAML authentication.
#version         1.0
#==============================================================================

function configure_keycloak() {
  echo "Configuring keycloak..."
  CLIENT_JSON=$(cat <<EOF
{
  "clientId": "https://${WORKSPACE_ENDPOINT}/saml/metadata",
  "name": "amazon-managed-grafana",
  "enabled": true,
  "protocol": "saml",
  "adminUrl": "https://${WORKSPACE_ENDPOINT}/login/saml",
  "redirectUris": [
    "https://${WORKSPACE_ENDPOINT}/saml/acs"
  ],
  "attributes": {
    "saml.authnstatement": "true",
    "saml.server.signature": "true",
    "saml_name_id_format": "email",
    "saml_force_name_id_format": "true",
    "saml.assertion.signature": "true",
    "saml.client.signature": "false"
  },
  "defaultClientScopes": [],
  "protocolMappers": [
    {
      "name": "name",
      "protocol": "saml",
      "protocolMapper": "saml-user-property-mapper",
      "consentRequired": false,
      "config": {
        "attribute.nameformat": "Unspecified",
        "user.attribute": "firstName",
        "attribute.name": "displayName"
      }
    },
    {
      "name": "email",
      "protocol": "saml",
      "protocolMapper": "saml-user-property-mapper",
      "consentRequired": false,
      "config": {
        "attribute.nameformat": "Unspecified",
        "user.attribute": "email",
        "attribute.name": "mail"
      }
    },
    {
      "name": "role list",
      "protocol": "saml",
      "protocolMapper": "saml-role-list-mapper",
      "config": {
        "single": "true",
        "attribute.nameformat": "Unspecified",
        "attribute.name": "role"
      }
    }
  ]
}
EOF
)
ADMIN_JSON=$(cat <<EOF
{
  "username": "monitor-admin",
  "email": "admin@keycloak",
  "enabled": true,
  "firstName": "Admin",
  "realmRoles": [
      "grafana-admin"
  ]
}
EOF
)
EDITOR_JSON=$(cat <<EOF
{
  "username": "monitor-editor",
  "email": "editor@keycloak",
  "enabled": true,
  "firstName": "Editor",
  "realmRoles": [
    "grafana-editor"
  ]
}
EOF
)
VIEWER_JSON=$(cat <<EOF
{
  "username": "monitor-viewer",
  "email": "viewer@keycloak",
  "enabled": true,
  "firstName": "Viewer",
  "realmRoles": [
    "grafana-viewer"
  ]
}
EOF
)
  CMD="unset HISTFILE\n
cat >/tmp/client.json <<EOF\n$(echo -e "$CLIENT_JSON")\nEOF\n
cat >/tmp/admin.json <<EOF\n$(echo -e "$ADMIN_JSON")\nEOF\n
cat >/tmp/editor.json <<EOF\n$(echo -e "$EDITOR_JSON")\nEOF\n
cat >/tmp/viewer.json <<EOF\n$(echo -e "$VIEWER_JSON")\nEOF\n
while true; do\n
    cd /opt/keycloak/bin/\n
    ./kcadm.sh config credentials --server http://localhost:8080/keycloak --realm master --user modernengg-admin --password $KEYCLOAK_ADMIN_PASSWORD --config /tmp/kcadm.config\n
    ./kcadm.sh update realms/master -s sslRequired=NONE --config /tmp/kcadm.config\n
    ./kcadm.sh update realms/$KEYCLOAK_REALM -s ssoSessionIdleTimeout=7200 --config /tmp/kcadm.config\n
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-admin --config /tmp/kcadm.config\n
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-editor --config /tmp/kcadm.config\n
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-viewer --config /tmp/kcadm.config\n
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/admin.json --config /tmp/kcadm.config\n
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/editor.json --config /tmp/kcadm.config\n
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/viewer.json --config /tmp/kcadm.config\n
    ./kcadm.sh add-roles --uusername user1 --rolename "grafana-admin" -r $KEYCLOAK_REALM --config /tmp/kcadm.config\n
    ADMIN_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-admin --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'\"' -f2 | tr -d '\\\n')\n
    ./kcadm.sh update users/\$ADMIN_USER_ID -r $KEYCLOAK_REALM -s 'credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_ADMIN_PASSWORD\"}]' --config /tmp/kcadm.config\n
    EDIT_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-editor --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'\"' -f2 | tr -d '\\\n')\n
    ./kcadm.sh update users/\$EDIT_USER_ID -r $KEYCLOAK_REALM -s 'credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_EDITOR_PASSWORD\"}]' --config /tmp/kcadm.config\n
    VIEW_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-viewer --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'\"' -f2 | tr -d '\\\n')\n
    ./kcadm.sh update users/\$VIEW_USER_ID -r $KEYCLOAK_REALM -s 'credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_VIEWER_PASSWORD\"}]' --config /tmp/kcadm.config\n
    ./kcadm.sh create clients -r $KEYCLOAK_REALM -f /tmp/client.json --config /tmp/kcadm.config\n
    break\n
  echo \"Keycloak admin server not available. Waiting for 10 seconds...\"\n
  sleep 10\n
done;"
  echo "Checking keycloak pod status..."
  POD_NAME=$(kubectl get pod -n keycloak -o jsonpath={.items[0].metadata.name} | grep -i keycloak)
  POD_PHASE=$(kubectl get pod $POD_NAME -n keycloak -o jsonpath={.status.phase})
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to check keycloak pod status."
  fi
  while [ "$POD_PHASE" != "Running" ]
  do
    echo "Keycloak pod status is '$POD_PHASE'. Waiting for 10 seconds."
    sleep 10
    POD_PHASE=$(kubectl get pod $POD_NAME -n keycloak -o jsonpath={.status.phase})
    CMD_RESULT=$?
    if [ $CMD_RESULT -ne 0 ]; then
      handle_error "ERROR: Failed to check keycloak pod status."
    fi
  done
  KEYCLOAK_ADMIN_PASSWORD=$(kubectl exec -it $POD_NAME -n keycloak -- env | grep -i KEYCLOAK_ADMIN_PASSWORD )
  kubectl exec -it $POD_NAME -n keycloak -- /bin/bash -c "$(echo -e $CMD)"
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to configure keycloak."
  fi
}

function update_workspace_saml_auth() {
  ELB_HOSTNAME=$(kubectl get ingress \
              -n $KEYCLOAK_NAMESPACE \
              -o json 2> /dev/null| jq -r '.items[] | .spec.rules[] | .host as $host  | ( $host + .path)' | sort | grep -v ^/)
  SAML_URL=http://$ELB_HOSTNAME/keycloak/realms/$KEYCLOAK_REALM/protocol/saml/descriptor
  EXPECTED_SAML_CONFIG=$(cat <<EOF | jq --sort-keys -r '.'
{
  "assertionAttributes": {
    "email": "mail",
    "login": "mail",
    "name": "displayName",
    "role": "role"
  },
  "idpMetadata": {
    "url": "${SAML_URL}"
  },
  "loginValidityDuration": 120,
  "roleValues": {
    "admin": [
      "grafana-admin"
    ],
    "editor": [
      "grafana-editor",
      "grafana-viewer"
    ]
  }
}
EOF
)
  echo "Retrieving AMG workspace authentication configuration..."
  WORKSPACE_AUTH_CONFIG=$(aws grafana describe-workspace-authentication --workspace-id $WORKSPACE_ID --region $AWS_REGION)
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to retrieve AMG workspace SAML authentication configuration."
  fi
  echo "Checking if SAML authentication is configured..."
  AUTH_PROVIDERS=$(echo $WORKSPACE_AUTH_CONFIG | jq --compact-output -r '.authentication.providers')
  SAML_INDEX=$(echo $WORKSPACE_AUTH_CONFIG | jq -r '.authentication.providers | index("SAML")')
  if [ "$SAML_INDEX" != "null" ]; then
    echo "Parsing actual SAML authentication configuration..."
    ACTUAL_SAML_CONFIG=$(echo $WORKSPACE_AUTH_CONFIG | jq --sort-keys -r '.authentication.saml.configuration | {assertionAttributes: .assertionAttributes, idpMetadata: .idpMetadata, loginValidityDuration: .loginValidityDuration, roleValues: .roleValues}')
    CMD_RESULT=$?
    if [ $CMD_RESULT -ne 0 ]; then
      handle_error "ERROR: Failed to JSON parse AMG workspace SAML authentication configuration."
    fi
    echo "Comparing actual SAML authentication configuration with expected configuration..."
    DIFF=$(diff <(echo "$EXPECTED_SAML_CONFIG") <(echo "$ACTUAL_SAML_CONFIG"))
    CMD_RESULT=$?
    if [ $CMD_RESULT -eq 0 ]; then
      echo "AMG workspace SAML authentication configuration matches expected configuration."
      return 0
    fi
    echo "AMG workspace SAML authentication configuration does not match expected configuration."
    echo "Configuration will be updated."
  else
    echo "AMG workspace is not configured for SAML authentication."
  fi
  
  echo "Generating AMG workspace SAML authentication input configuration..."
  MERGED_AUTH_PROVIDERS=$(jq --compact-output --argjson arr1 "$AUTH_PROVIDERS" --argjson arr2 '["SAML"]' -n '$arr1 + $arr2 | unique_by(.)')
  WORKSPACE_AUTH_SAML_INPUT_CONFIG=$(cat <<EOF | jq --compact-output -r '.'
{
    "authenticationProviders": $MERGED_AUTH_PROVIDERS,
    "samlConfiguration":
        ${EXPECTED_SAML_CONFIG},
    "workspaceId": "${WORKSPACE_ID}"
}
EOF
)

  echo "Updating AMG workspace SAML authentication..."
  WORKSPACE_AUTH_SAML_STATUS=$(aws grafana update-workspace-authentication \
    --cli-input-json "$WORKSPACE_AUTH_SAML_INPUT_CONFIG" --query "authentication.saml.status" --output text --region "$AWS_REGION")
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to update AMG workspace SAML authentication."
  fi
  echo "AMG workspace SAML authentication status: $WORKSPACE_AUTH_SAML_STATUS"
  echo ""
}
