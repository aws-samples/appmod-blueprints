#!/bin/bash

# GitLab initialization script for creating application repositories
# This script creates GitLab repositories for dotnet, golang, java, rust and next-js applications
# Uses existing GitLab credentials from AWS Secrets Manager

export TIMEOUT=10
export RETRY_INTERVAL=10
export MAX_RETRIES=40

# Get GitLab configuration from Secrets Manager
echo "Retrieving GitLab configuration from AWS Secrets Manager..."

# Get GitLab credentials from hub secrets
HUB_SECRETS=$(aws secretsmanager get-secret-value --secret-id "${RESOURCE_PREFIX:-peeks}-hub/secrets" --region ${AWS_REGION:-us-east-1} --query 'SecretString' --output text)
HUB_CONFIG=$(aws secretsmanager get-secret-value --secret-id "${RESOURCE_PREFIX:-peeks}-hub/config" --region ${AWS_REGION:-us-east-1} --query 'SecretString' --output text)

if [ -z "$HUB_SECRETS" ] || [ -z "$HUB_CONFIG" ]; then
    echo "Error: GitLab configuration not found in Secrets Manager."
    echo "Expected secrets: ${RESOURCE_PREFIX:-peeks}-hub/secrets and ${RESOURCE_PREFIX:-peeks}-hub/config"
    exit 1
fi

export GITLAB_TOKEN=$(echo "$HUB_SECRETS" | jq -r '.git_token')
export GITLAB_HOSTNAME=$(echo "$HUB_CONFIG" | jq -r '.metadata.gitlab_domain_name')
export USERNAME=$(echo "$HUB_CONFIG" | jq -r '.metadata.git_username')
export GITLAB_URL="https://$GITLAB_HOSTNAME"

echo "Using GitLab: $GITLAB_URL"
echo "Using username: $USERNAME"

# Function to check if GitLab is available
check_gitlab_available() {
  echo "Checking if GitLab is available at $GITLAB_URL..."
  if curl -k -s -o /dev/null -w "%{http_code}" --connect-timeout $TIMEOUT $GITLAB_URL | grep -q "200\|302"; then
    echo "GitLab is available!"
    return 0
  else
    echo "GitLab is not available yet."
    return 1
  fi
}

# Wait for GitLab to be available
wait_for_gitlab() {
  local retries=0
  until check_gitlab_available || [ $retries -ge $MAX_RETRIES ]; do
    retries=$((retries+1))
    echo "Retry $retries/$MAX_RETRIES. Waiting $RETRY_INTERVAL seconds..."
    sleep $RETRY_INTERVAL
  done

  if [ $retries -ge $MAX_RETRIES ]; then
    echo "Error: GitLab is not available after $MAX_RETRIES retries."
    exit 1
  fi
}

# Check if repository exists
check_repo_exist() {
  local repo_name=$1
  local response=$(curl -k -s -o /dev/null -w "%{http_code}" -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$GITLAB_URL/api/v4/projects/$USERNAME%2F$repo_name")
  if [[ "$response" == "200" ]]; then
    echo "Repository $repo_name already exists."
    return 0
  else
    echo "Repository $repo_name does not exist."
    return 1
  fi
}

# Create repository
create_repo() {
  local repo_name=$1
  echo "Creating repository $repo_name..."
  curl -k -X POST "$GITLAB_URL/api/v4/projects" \
    -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$repo_name\", \"visibility\":\"private\"}"
  echo "Repository $repo_name created successfully!"
}

# Create repository content for applications
create_repo_content_application() {
  local repo_name=$1
  echo "Creating initial repo content for $repo_name..."
  export REPO_ROOT=$(git rev-parse --show-toplevel)

  # Create checkout directory
  mkdir -p ~/environment/applications
  rm -rf ~/environment/applications/$repo_name
  
  # Clone the repository
  git clone https://$USERNAME:$GITLAB_TOKEN@$GITLAB_HOSTNAME/$USERNAME/$repo_name.git ~/environment/applications/$repo_name
  
  pushd ~/environment/applications/$repo_name
  git config user.email "participants@workshops.aws"
  git config user.name "Workshop Participant"
  
  # Copy application source
  cp -r ${REPO_ROOT}/applications/$repo_name/* .
  cp -r ${REPO_ROOT}/applications/$repo_name/.* . 2>/dev/null || true
  
  git add .
  git commit -m "Initial commit: Add $repo_name application source"
  git push origin main
  
  popd
  echo "Repository $repo_name content created and checked out to ~/environment/applications/$repo_name"
}

# Check and create repository
check_and_create_repo() {
  local repo_name=$1
  if check_repo_exist "$repo_name"; then
    echo "Repository $repo_name already exists. Checking out to ~/environment/applications/$repo_name"
    mkdir -p ~/environment/applications
    rm -rf ~/environment/applications/$repo_name
    git clone https://$USERNAME:$GITLAB_TOKEN@$GITLAB_HOSTNAME/$USERNAME/$repo_name.git ~/environment/applications/$repo_name
  else
    create_repo "$repo_name"
    create_repo_content_application "$repo_name"
  fi
}

set_gitlab_remote_for_peeks() {
  pushd ~/environment/$WORKING_REPO
  
  git config user.email "participants@workshops.aws"
  git config user.name "Workshop Participant"
  
  # Fetch from GitLab
  git fetch gitlab
  
  # Switch to main branch from GitLab (creates if doesn't exist)
  git checkout -B main gitlab/main
  
  popd
  echo "GitLab remote set for ~/environment/$WORKING_REPO - switched to main branch"
}

# Main execution
echo "Starting GitLab application repositories initialization..."
wait_for_gitlab

# Create repositories for each application
echo "Creating application repositories..."
check_and_create_repo "dotnet"
check_and_create_repo "golang" 
check_and_create_repo "java"
check_and_create_repo "rust"
check_and_create_repo "next-js"
set_gitlab_remote_for_peeks
echo "All GitLab repositories created and checked out"
