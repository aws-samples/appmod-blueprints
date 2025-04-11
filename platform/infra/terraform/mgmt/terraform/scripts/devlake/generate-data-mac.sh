#!/bin/bash

if [ $# -lt 3 ]; then
    echo "Usage: $0 <base_url> <api_key> <connection_id>"
    echo "Example: $0 http://localhost:4000 your-api-key 2"
    exit 1
fi

BASE_URL="$1"
API_KEY="$2"
CONNECTION_ID="$3"

rand() {
    od -N 4 -t uL -An /dev/urandom | tr -d " "
}

# Function to create a pull request and return the merge commit SHA
create_pr() {
    local pr_id=$1
    local created_date=$2
    local merged_date=$3
    local merge_commit_sha=$4
    
    response=$(curl -s "${BASE_URL}/api/rest/plugins/webhook/connections/${CONNECTION_ID}/pull_requests" -X 'POST' \
         -H "Authorization: Bearer ${API_KEY}" \
         -H 'Content-Type: application/json' \
         -d '{
      "id": "PR-'"$pr_id"'",
      "headRepoId": "repo-'"$(($(rand) % 1000))"'",
      "status": "MERGED",
      "originalStatus": "OPEN",
      "displayTitle": "Feature: Add new functionality '"$pr_id"'",
      "description": "This PR adds new features",
      "url": "https://github.com/org/repo/pull/'"$pr_id"'",
      "pullRequestKey": '"$pr_id"',
      "createdDate": "'"$created_date"'",
      "mergedDate": "'"$merged_date"'",
      "closedDate": null,
      "mergeCommitSha": "'"$merge_commit_sha"'",
      "headRef": "feature-branch-'"$pr_id"'",
      "baseRef": "main",
      "baseCommitSha": "'"$(openssl rand -hex 20)"'",
      "headCommitSha": "'"$(openssl rand -hex 20)"'",
      "isDraft": false
    }') 
}

# Function to create a deployment
create_deployment() {
    local deploy_id=$1
    local start_date=$2
    local commit_sha=$3
    local finish_date=$4
    
    response=$(curl -s "${BASE_URL}/api/rest/plugins/webhook/connections/${CONNECTION_ID}/deployments" -X 'POST' \
         -H "Authorization: Bearer ${API_KEY}" \
         -d "{
      \"id\": \"DEPLOY-$deploy_id\",
      \"startedDate\": \"$start_date\",
      \"finishedDate\": \"$finish_date\",
      \"result\": \"SUCCESS\",
      \"url\": \"https://deploy.example.com/$deploy_id\",
      \"deploymentCommits\":[
        {
          \"repoUrl\": \"https://github.com/org/repo\",
          \"refName\": \"main\",
          \"startedDate\": \"$start_date\",
          \"finishedDate\": \"$finish_date\",
          \"commitSha\": \"$commit_sha\",
          \"commitMsg\": \"Deployment $deploy_id\"
        }
      ]
    }")
    
    echo $finish_date
}

# Function to create an incident
create_incident() {
    local incident_id=$1
    local created_date=$2
    
    response=$(curl -s "${BASE_URL}/api/rest/plugins/webhook/connections/${CONNECTION_ID}/issues" -X 'POST' \
         -H "Authorization: Bearer ${API_KEY}" \
         -d "{
      \"issueKey\":\"INC-$incident_id\",
      \"title\":\"Incident $incident_id\",
      \"type\":\"INCIDENT\",
      \"originalStatus\":\"TODO\",
      \"status\":\"TODO\",
      \"createdDate\":\"$created_date\",
      \"updatedDate\":\"$created_date\"
    }")
}

# Function to update incident status to DONE
update_incident_status() {
    local incident_id=$1
    local created_date=$2
    local updated_date=$3
    
    response=$(curl -s "${BASE_URL}/api/rest/plugins/webhook/connections/${CONNECTION_ID}/issues" -X 'POST' \
         -H "Authorization: Bearer ${API_KEY}" \
         -d "{
      \"issueKey\":\"INC-$incident_id\",
      \"title\":\"Incident $incident_id\",
      \"type\":\"INCIDENT\",
      \"originalStatus\":\"TODO\",
      \"status\":\"DONE\",
      \"createdDate\":\"$created_date\",
      \"updatedDate\":\"$updated_date\",
      \"resolutionDate\":\"$updated_date\"
    }")
}

cap_timestamp() {
    local ts=$1
    local current_ts=$(date +%s)
    if [ $ts -gt $current_ts ]; then
        echo $current_ts
    else
        echo $ts
    fi
}

ONE_HOUR=3600
ONE_DAY=$((24*ONE_HOUR))
ONE_WEEK=$((ONE_DAY * 7))

end_ts=$(date +%s)
start_ts=$(date -v-180d +%s)
current_ts=$start_ts
pr_id=1
deploy_id=1
incident_id=1

# Main loop to generate data for the last six months
while [ $current_ts -lt $end_ts ];do
    # Generate random timestamp more efficiently
    created_date=$(date -r $current_ts +"%Y-%m-%dT%H:%M:%S%z")
    
    # Create PR
    merged_ts=$(cap_timestamp $((current_ts + ONE_HOUR + $(rand) % ONE_WEEK)))
    merged_date=$(date -r $merged_ts +"%Y-%m-%dT%H:%M:%S%z")
    merge_commit_sha=$(openssl rand -hex 20)
    
    create_pr $pr_id "$created_date" "$merged_date" "$merge_commit_sha"
    
    # Create deployment
    deploy_finish_ts=$(cap_timestamp $((merged_ts + ONE_HOUR + $(rand) % (2*ONE_HOUR))))
    deploy_finish_date=$(date -r $deploy_finish_ts +"%Y-%m-%dT%H:%M:%S%z")
    create_deployment $deploy_id "$merged_date" "$merge_commit_sha" "$deploy_finish_date"
    
    current_ts=$deploy_finish_ts
    # 1/7 chance of creating an incident
    if [ $(($(rand) % 10)) -eq 0 ]; then
        incident_ts=$(cap_timestamp $((deploy_finish_ts + $(rand) % ONE_DAY)))
        incident_date=$(date -r $incident_ts +"%Y-%m-%dT%H:%M:%S%z")
        create_incident $incident_id "$incident_date"
        
        # Create fix PR and deployment
        fix_pr_merge_ts=$(cap_timestamp $((incident_ts + ONE_HOUR + $(rand) % (3*ONE_DAY))))
        fix_pr_merge_date=$(date -r $fix_pr_merge_ts +"%Y-%m-%dT%H:%M:%S%z")
        fix_merge_commit_sha=$(openssl rand -hex 20)
        pr_id=$((pr_id+1))
        create_pr $pr_id "$incident_date" "$fix_pr_merge_date" "$fix_merge_commit_sha"
        
        fix_deploy_finish_ts=$(cap_timestamp $((fix_pr_merge_ts + ONE_HOUR + $(rand) % (2*ONE_HOUR))))
        fix_deploy_finish_date=$(date -r $fix_deploy_finish_ts +"%Y-%m-%dT%H:%M:%S%z")
        deploy_id=$((deploy_id+1))
        create_deployment $deploy_id "$fix_pr_merge_date" "$fix_merge_commit_sha" "$fix_deploy_finish_date"
        
        update_incident_status $incident_id "$incident_date" "$fix_deploy_finish_date"
        incident_id=$((incident_id+1))

        current_ts=$fix_deploy_finish_ts
    fi
    current_ts=$((current_ts + $(rand) % 2*ONE_DAY))
    pr_id=$((pr_id + 1))
    deploy_id=$((deploy_id + 1))
done

echo "Data generation complete. Created $((pr_id - 1)) pull requests, $((deploy_id - 1)) deployments, and $((incident_id - 1)) incidents."

