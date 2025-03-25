# do db migration, add some data to devlake
kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/devlake
kubectl wait --for=condition=ready pod -l devlakeComponent=lake -n devlake --timeout=60s
kubectl wait --for=condition=ready pod -l devlakeComponent=mysql -n devlake --timeout=60s
echo "Performing DB Migration"

kubectl port-forward -n devlake svc/devlake-lake 9090:8080 >/dev/null 2>&1 &
pid=$!
trap '{
  kill $pid
}' EXIT
echo "waiting for port forward to be ready"
while ! nc -vz localhost 9090 >/dev/null 2>&1; do
  sleep 2
done

curl -X POST localhost:9090/proceed-db-migration

projectName="modengg"

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
projectCreateResponse=$(curl -X POST localhost:9090/projects -d "$projectCreateRequest")
blueprintID=$(echo $projectCreateResponse | jq -r '.blueprint.id')
blueprintName=$(echo $projectCreateResponse | jq -r '.blueprint.name')
# {"name":"modengg","description":"","createdAt":"2025-03-21T23:46:01.144Z","updatedAt":"2025-03-21T23:46:01.144Z","_raw_data_params":"","_raw_data_table":"","_raw_data_id":0,"_raw_data_remark":"","metrics":[{"pluginName":"dora","pluginOption":{},"enable":true},{"pluginName":"issue_trace","pluginOption":{},"enable":true}],"blueprint":{"name":"test-Blueprint","projectName":"test","mode":"NORMAL","plan":null,"enable":true,"cronConfig":"0 0 * * 1","isManual":false,"beforePlan":null,"afterPlan":null,"labels":[],"connections":[],"skipOnFail":false,"timeAfter":"2024-09-21T00:00:00Z","skipCollectors":false,"fullSync":false,"id":1,"createdAt":"2025-03-21T23:46:01.148Z","updatedAt":"2025-03-21T23:46:01.148Z"}}

webhookCreateRequest=$(
  cat <<EOF
{
  "name": "$projectName_gitea"
}
EOF
)
webhookCreateResponse=$(curl -X POST localhost:9090/plugins/webhook/connections -d "$webhookCreateRequest")
webhookID=$(echo $webhookCreateResponse | jq -r '.id')
webhookApiKey=$(echo $webhookCreateResponse | jq -r '.apiKey.apiKey')
postIssuesEndpoint=$(echo $webhookCreateResponse | jq -r '.postIssuesEndpoint')
postPullRequestsEndpoint=$(echo $webhookCreateResponse | jq -r '.postPullRequestsEndpoint')
postPipelineDeployTaskEndpoint=$(echo $webhookCreateResponse | jq -r 'postPipelineDeployTaskEndpoint')

# {"name":"modengg_gitea","id":1,"createdAt":"2025-03-21T23:47:42.486Z","updatedAt":"2025-03-21T23:47:42.486Z","postIssuesEndpoint":"/rest/plugins/webhook/connections/1/issues","closeIssuesEndpoint":"/rest/plugins/webhook/connections/1/issue/:issueKey/close","postPullRequestsEndpoint":"/rest/plugins/webhook/connections/1/pull_requests","postPipelineTaskEndpoint":"/rest/plugins/webhook/connections/1/cicd_tasks","postPipelineDeployTaskEndpoint":"/rest/plugins/webhook/connections/1/deployments","closePipelineEndpoint":"/rest/plugins/webhook/connections/1/cicd_pipeline/:pipelineName/finish","apiKey":{"id":1,"createdAt":"2025-03-21T23:47:42.490396162Z","updatedAt":"2025-03-21T23:47:42.490396162Z","creator":"admin","creatorEmail":"","updater":"admin","updaterEmail":"","name":"webhook-1","apiKey":"fPaKeWtWhTUdtlpneoibhrtvwiMbBiPL3022Yyda30WrqrrBTX882NQ1b5uhLK4kzwQCMi4Qxl65m2Tfvc9h12nwR1btEmB2wbkMARbg0FQNTxAwFudqN9u7QB1atuLT","expiredAt":null,"allowedPath":"/plugins/webhook/connections/1/.*","type":"plugin:webhook","extra":"connectionId:1"}}

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
  "id": $blueprintID,
}
EOF
)
# "createdAt": "2025-03-21T23:46:01.148Z","updatedAt": "2025-03-21T23:46:01.148Z" MIGHT BE NEEDED IN ABOVE
curl -X PATCH localhost:9090/blueprints/$blueprintID -d "$blueprintPatchRequest"

# {"name":"test-Blueprint","projectName":"test","mode":"NORMAL","plan":[[{"plugin":"org","subtasks":["checkTokens"],"options":{"projectConnections":[{"PluginName":"webhook","ConnectionId":1}]}}],[{"plugin":"org","subtasks":["setProjectMapping"],"options":{"projectMappings":[{"projectName":"test","scopes":[{"table":"cicd_scopes","rowId":"webhook:1"},{"table":"boards","rowId":"webhook:1"},{"table":"repos","rowId":"webhook:1"}]}]}}],[{"plugin":"dora","subtasks":["generateDeployments","generateDeploymentCommits","enrichPrevSuccessDeploymentCommits"],"options":{"projectName":"test"}},{"plugin":"issue_trace","subtasks":["ConvertIssueStatusHistory","ConvertIssueAssigneeHistory"],"options":{"projectName":"test","scopeIds":null}}],[{"plugin":"refdiff","subtasks":["calculateDeploymentCommitsDiff"],"options":{"projectName":"test"}}],[{"plugin":"dora","subtasks":["calculateChangeLeadTime","ConvertIssuesToIncidents","ConnectIncidentToDeployment"],"options":{"projectName":"test"}}]],"enable":true,"cronConfig":"0 0 * * 1","isManual":false,"beforePlan":null,"afterPlan":null,"labels":[],"connections":[{"pluginName":"webhook","connectionId":1,"scopes":null}],"skipOnFail":false,"timeAfter":"2024-09-21T00:00:00Z","skipCollectors":false,"fullSync":false,"id":1,"createdAt":"2025-03-21T23:46:01.148Z","updatedAt":"2025-03-21T23:47:42.556Z"}

curl -X PATCH localhost:9090/projects/$projectName
{"name":"test","description":"","metrics":[{"pluginName":"dora","pluginOption":{},"enable":true},{"pluginName":"linker","pluginOption":{"prToIssueRegexp":"(?mi)(Closes)[\\s]*.*(((and )?#\\d+[ ]*)+)"},"enable":true},{"pluginName":"issue_trace","pluginOption":{},"enable":true}]}

curl -X POST localhost:9090/blueprints/$blueprintID/trigger
{"skipCollectors":false,"fullSync":false}
{"id":1,"createdAt":"2025-03-21T23:54:13.4Z","updatedAt":"2025-03-21T23:54:13.419Z","name":"test-Blueprint","blueprintId":1,"plan":[[{"plugin":"org","subtasks":["checkTokens"],"options":{"projectConnections":[{"PluginName":"webhook","ConnectionId":1}]}}],[{"plugin":"org","subtasks":["setProjectMapping"],"options":{"projectMappings":[{"projectName":"test","scopes":[{"table":"cicd_scopes","rowId":"webhook:1"},{"table":"boards","rowId":"webhook:1"},{"table":"repos","rowId":"webhook:1"}]}]}}],[{"plugin":"issue_trace","subtasks":["ConvertIssueStatusHistory","ConvertIssueAssigneeHistory"],"options":{"projectName":"test","scopeIds":null}},{"plugin":"linker","subtasks":["LinkPrToIssue"],"options":{"prToIssueRegexp":"(?mi)(Closes)[\\s]*.*(((and )?#\\d+[ ]*)+)","projectName":"test"}},{"plugin":"dora","subtasks":["generateDeployments","generateDeploymentCommits","enrichPrevSuccessDeploymentCommits"],"options":{"projectName":"test"}}],[{"plugin":"refdiff","subtasks":["calculateDeploymentCommitsDiff"],"options":{"projectName":"test"}}],[{"plugin":"dora","subtasks":["calculateChangeLeadTime","ConvertIssuesToIncidents","ConnectIncidentToDeployment"],"options":{"projectName":"test"}}]],"totalTasks":7,"finishedTasks":0,"beganAt":null,"finishedAt":null,"status":"TASK_CREATED","message":"","errorName":"","spentSeconds":0,"stage":0,"labels":[],"skipOnFail":false,"timeAfter":"2024-09-21T00:00:00Z","skipCollectors":false,"fullSync":false}
