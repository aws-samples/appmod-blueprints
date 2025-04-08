#!/bin/bash
if [ $# -lt 2 ]; then
    echo "Usage: $0 <base_url> <appname>"
    echo "Example: $0 http://localhost:4000 rust"
    exit 1
fi

BASE_URL=$1
curl -X GET ${BASE_URL}/proceed-db-migration

projectName=$2

projectCreateRequest=$(
  cat <<EOF
{
  "name": "$projectName",
  "description": "",
  "metrics": [
    {
      "pluginName": "dora",
      "pluginOption": {},
      "enable": true
    },
    {
      "pluginName": "issue_trace",
      "pluginOption": {},
      "enable": true
    }
  ]
}
EOF
)
projectCreateResponse=$(curl -X POST -H "Content-Type: application/json" ${BASE_URL}/projects -d "$projectCreateRequest")
blueprintID=$(echo $projectCreateResponse | jq -r '.blueprint.id')
blueprintName=$(echo $projectCreateResponse | jq -r '.blueprint.name')

webhookCreateRequest=$(
  cat <<EOF
{
  "name": "${projectName}_webhook"
}
EOF
)
webhookCreateResponse=$(curl -X POST -H "Content-Type: application/json" ${BASE_URL}/plugins/webhook/connections -d "$webhookCreateRequest")
webhookID=$(echo $webhookCreateResponse | jq -r '.id')
webhookApiKey=$(echo $webhookCreateResponse | jq -r '.apiKey.apiKey')
# postIssuesEndpoint=$(echo $webhookCreateResponse | jq -r '.postIssuesEndpoint')
# postPullRequestsEndpoint=$(echo $webhookCreateResponse | jq -r '.postPullRequestsEndpoint')
# postPipelineDeployTaskEndpoint=$(echo $webhookCreateResponse | jq -r '.postPipelineDeployTaskEndpoint')

blueprintPatchRequest=$(
  cat <<EOF
{
  "name": "$blueprintName",
  "projectName": "$projectName",
  "mode": "NORMAL",
  "plan": null,
  "enable": true,
  "cronConfig": "0 0 * * 1",
  "isManual": false,
  "beforePlan": null,
  "afterPlan": null,
  "labels": [],
  "connections": [
    {
      "pluginName": "webhook",
      "connectionId": $webhookID
    }
  ],
  "skipOnFail": false,
  "timeAfter": "2024-09-21T00:00:00Z",
  "skipCollectors": false,
  "fullSync": false,
  "id": $blueprintID
}
EOF
)

resp=$(curl -X PATCH -H "Content-Type: application/json" ${BASE_URL}/blueprints/$blueprintID -d "$blueprintPatchRequest")

resp=$(curl -X POST -H "Content-Type: application/json" ${BASE_URL}/blueprints/${blueprintID}/trigger -d '{"skipCollectors":false,"fullSync":false}')

echo "$webhookApiKey|$webhookID"
