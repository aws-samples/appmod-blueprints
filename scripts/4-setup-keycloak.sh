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
  export CLIENT_JSON=$(cat <<EOF
{
  "clientId": "https://${GRAFANAURL}/saml/metadata",
  "name": "amazon-managed-grafana",
  "enabled": true,
  "protocol": "saml",
  "adminUrl": "https://${GRAFANAURL}/login/saml",
  "redirectUris": [
    "https://${GRAFANAURL}/saml/acs"
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
export ADMIN_JSON=$(cat <<EOF
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
export EDITOR_JSON=$(cat <<EOF
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
export VIEWER_JSON=$(cat <<EOF
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
# CMD construction moved to after password retrieval
  echo "Checking keycloak pod status..."
  export POD_NAME=$(kubectl get pods -n keycloak --no-headers -o custom-columns=":metadata.name" | grep -i keycloak)
  export POD_PHASE=$(kubectl get pod $POD_NAME -n keycloak -o jsonpath='{.status.phase}')
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to check keycloak pod status."
  fi
  while [ "$POD_PHASE" != "Running" ]
  do
    echo "Keycloak pod status is '$POD_PHASE'. Waiting for 10 seconds."
    sleep 10
    export POD_PHASE=$(kubectl get pod $POD_NAME -n keycloak -o jsonpath='{.status.phase}')
    CMD_RESULT=$?
    if [ $CMD_RESULT -ne 0 ]; then
      handle_error "ERROR: Failed to check keycloak pod status."
    fi
  done
  export KEYCLOAK_ADMIN_PASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 -d)
  
  # Build the command with the actual password value
  KEYCLOAK_CMD=$(cat <<EOF
unset HISTFILE
cat >/tmp/client.json <<'CLIENTEOF'
$(echo -e "$CLIENT_JSON")
CLIENTEOF
cat >/tmp/admin.json <<'ADMINEOF'
$(echo -e "$ADMIN_JSON")
ADMINEOF
cat >/tmp/editor.json <<'EDITOREOF'
$(echo -e "$EDITOR_JSON")
EDITOREOF
cat >/tmp/viewer.json <<'VIEWEREOF'
$(echo -e "$VIEWER_JSON")
VIEWEREOF
while true; do
    cd /opt/keycloak/bin/
    ./kcadm.sh config credentials --server http://localhost:8080/keycloak --realm master --user admin --password "$KEYCLOAK_ADMIN_PASSWORD" --config /tmp/kcadm.config
    ./kcadm.sh update realms/master -s sslRequired=NONE --config /tmp/kcadm.config
    ./kcadm.sh update realms/$KEYCLOAK_REALM -s ssoSessionIdleTimeout=7200 --config /tmp/kcadm.config
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-admin --config /tmp/kcadm.config
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-editor --config /tmp/kcadm.config
    ./kcadm.sh create roles -r $KEYCLOAK_REALM -s name=grafana-viewer --config /tmp/kcadm.config
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/admin.json --config /tmp/kcadm.config
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/editor.json --config /tmp/kcadm.config
    ./kcadm.sh create users -r $KEYCLOAK_REALM -f /tmp/viewer.json --config /tmp/kcadm.config
    ./kcadm.sh add-roles --uusername user1 --rolename "grafana-admin" -r $KEYCLOAK_REALM --config /tmp/kcadm.config
    # Set password for user1 to match GitLab/ArgoCD password
    USER1_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=user1 --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'"' -f2 | tr -d '\n')
    ./kcadm.sh update users/\$USER1_USER_ID -r $KEYCLOAK_REALM -s "credentials=[{\"type\":\"password\",\"value\":\"$IDE_PASSWORD\"}]" --config /tmp/kcadm.config
    ADMIN_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-admin --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'"' -f2 | tr -d '\n')
    ./kcadm.sh update users/\$ADMIN_USER_ID -r $KEYCLOAK_REALM -s "credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_ADMIN_PASSWORD\"}]" --config /tmp/kcadm.config
    EDIT_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-editor --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'"' -f2 | tr -d '\n')
    ./kcadm.sh update users/\$EDIT_USER_ID -r $KEYCLOAK_REALM -s "credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_EDITOR_PASSWORD\"}]" --config /tmp/kcadm.config
    VIEW_USER_ID=\$(./kcadm.sh get users -r $KEYCLOAK_REALM -q username=monitor-viewer --fields id --config /tmp/kcadm.config 2>/dev/null | cut -d' ' -f5 | cut -d'"' -f2 | tr -d '\n')
    ./kcadm.sh update users/\$VIEW_USER_ID -r $KEYCLOAK_REALM -s "credentials=[{\"type\":\"password\",\"value\":\"$KEYCLOAK_USER_VIEWER_PASSWORD\"}]" --config /tmp/kcadm.config
    ./kcadm.sh create clients -r $KEYCLOAK_REALM -f /tmp/client.json --config /tmp/kcadm.config
    break
  echo "Keycloak admin server not available. Waiting for 10 seconds..."
  sleep 10
done
EOF
)
  
  kubectl exec -it $POD_NAME -n keycloak -- /bin/bash -c "$KEYCLOAK_CMD"
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to configure keycloak."
  fi
}

function update_workspace_saml_auth() {
  # Ensure required variables are set
  if [ -z "$DOMAIN_NAME" ]; then
    handle_error "ERROR: DOMAIN_NAME is not set. Cannot configure SAML."
  fi
  if [ -z "$WORKSPACE_ID" ]; then
    handle_error "ERROR: WORKSPACE_ID is not set. Cannot configure SAML."
  fi
  if [ -z "$KEYCLOAK_REALM" ]; then
    handle_error "ERROR: KEYCLOAK_REALM is not set. Cannot configure SAML."
  fi
  
  export SAML_URL=https://$DOMAIN_NAME/keycloak/realms/$KEYCLOAK_REALM/protocol/saml/descriptor
  echo "Using SAML URL: $SAML_URL"
  echo "Workspace ID: $WORKSPACE_ID"
  echo "Keycloak Realm: $KEYCLOAK_REALM"
  export EXPECTED_SAML_CONFIG=$(cat <<EOF | jq --sort-keys -r '.'
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
  export WORKSPACE_AUTH_CONFIG=$(aws grafana describe-workspace-authentication --workspace-id $WORKSPACE_ID --region $AWS_REGION)
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to retrieve AMG workspace SAML authentication configuration."
  fi
  echo "Checking if SAML authentication is configured..."
  export AUTH_PROVIDERS=$(echo $WORKSPACE_AUTH_CONFIG | jq --compact-output -r '.authentication.providers')
  export SAML_INDEX=$(echo $WORKSPACE_AUTH_CONFIG | jq -r '.authentication.providers | index("SAML")')
  if [ "$SAML_INDEX" != "null" ]; then
    echo "Parsing actual SAML authentication configuration..."
    export ACTUAL_SAML_CONFIG=$(echo $WORKSPACE_AUTH_CONFIG | jq --sort-keys -r '.authentication.saml.configuration | {assertionAttributes: .assertionAttributes, idpMetadata: .idpMetadata, loginValidityDuration: .loginValidityDuration, roleValues: .roleValues}')
    CMD_RESULT=$?
    if [ $CMD_RESULT -ne 0 ]; then
      handle_error "ERROR: Failed to JSON parse AMG workspace SAML authentication configuration."
    fi
    echo "Comparing actual SAML authentication configuration with expected configuration..."
    export DIFF=$(diff <(echo "$EXPECTED_SAML_CONFIG") <(echo "$ACTUAL_SAML_CONFIG"))
    CMD_RESULT=$?
    if [ $CMD_RESULT -eq 0 ]; then
      echo "AMG workspace SAML authentication configuration matches expected configuration."
      echo "However, forcing update to ensure configuration is properly applied..."
    else
      echo "AMG workspace SAML authentication configuration does not match expected configuration."
      echo "Expected config:"
      echo "$EXPECTED_SAML_CONFIG"
      echo "Actual config:"
      echo "$ACTUAL_SAML_CONFIG"
      echo "Differences:"
      echo "$DIFF"
    fi
    echo "Configuration will be updated."
  else
    echo "AMG workspace is not configured for SAML authentication."
  fi
  
  echo "Generating AMG workspace SAML authentication input configuration..."
  export MERGED_AUTH_PROVIDERS=$(jq --compact-output --argjson arr1 "$AUTH_PROVIDERS" --argjson arr2 '["SAML"]' -n '$arr1 + $arr2 | unique_by(.)')
  export WORKSPACE_AUTH_SAML_INPUT_CONFIG=$(cat <<EOF | jq --compact-output -r '.'
{
    "authenticationProviders": $MERGED_AUTH_PROVIDERS,
    "samlConfiguration":
        ${EXPECTED_SAML_CONFIG},
    "workspaceId": "${WORKSPACE_ID}"
}
EOF
)

  echo "Updating AMG workspace SAML authentication..."
  echo "Input configuration:"
  echo "$WORKSPACE_AUTH_SAML_INPUT_CONFIG" | jq '.'
  
  export WORKSPACE_AUTH_SAML_STATUS=$(aws grafana update-workspace-authentication \
    --cli-input-json "$WORKSPACE_AUTH_SAML_INPUT_CONFIG" --query "authentication.saml.status" --output text --region "$AWS_REGION")
  CMD_RESULT=$?
  if [ $CMD_RESULT -ne 0 ]; then
    handle_error "ERROR: Failed to update AMG workspace SAML authentication."
  fi
  echo "AMG workspace SAML authentication status: $WORKSPACE_AUTH_SAML_STATUS"
  
  # Verify the update was successful
  echo "Verifying SAML configuration update..."
  sleep 5  # Wait for the update to propagate
  export UPDATED_WORKSPACE_AUTH_CONFIG=$(aws grafana describe-workspace-authentication --workspace-id $WORKSPACE_ID --region $AWS_REGION)
  export UPDATED_SAML_CONFIG=$(echo $UPDATED_WORKSPACE_AUTH_CONFIG | jq --sort-keys -r '.authentication.saml.configuration | {assertionAttributes: .assertionAttributes, idpMetadata: .idpMetadata, loginValidityDuration: .loginValidityDuration, roleValues: .roleValues}')
  
  export FINAL_DIFF=$(diff <(echo "$EXPECTED_SAML_CONFIG") <(echo "$UPDATED_SAML_CONFIG"))
  if [ $? -eq 0 ]; then
    echo "✅ SAML configuration successfully updated and verified!"
  else
    echo "⚠️  SAML configuration update may not have been fully applied:"
    echo "$FINAL_DIFF"
  fi
  echo ""
}

# Define handle_error function if not already defined
handle_error() {
    echo "ERROR: $1"
    exit 1
}

# Main execution - call configure_keycloak when script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Setting up Keycloak configuration..."
    configure_keycloak
    echo "Keycloak configuration completed successfully!"
    echo "Update SAML Configuration in Grafana"
    
    # Set DOMAIN_NAME for SAML configuration - use Keycloak CloudFront domain
    export DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'keycloak') || contains(Comment, 'keycloak')].DomainName | [0]" --output text)
    if [ -z "$DOMAIN_NAME" ] || [ "$DOMAIN_NAME" = "None" ] || [ "$DOMAIN_NAME" = "null" ]; then
        echo "Warning: Could not find Keycloak CloudFront domain, trying ingress domain"
        # Fallback to ingress domain if Keycloak domain not found
        export DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?Origins.Items[?contains(DomainName, 'ingress')]].DomainName | [0]" --output text)
    fi
    echo "Using DOMAIN_NAME for SAML: $DOMAIN_NAME"
    
    update_workspace_saml_auth
    echo "SAML Configuration Updated in Grafana"
fi
