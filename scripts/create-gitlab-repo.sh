#!/bin/bash

# Script to create GitLab repository for Backstage templates
# Usage: ./create-gitlab-repo.sh <repository-name>

if [ -z "$1" ]; then
    echo "Usage: $0 <repository-name>"
    echo "Example: $0 devprodseb8"
    exit 1
fi

REPO_NAME="$1"

echo "Creating GitLab repository: $REPO_NAME"

curl -X POST "https://${GITLAB_URL#https://}/api/v4/projects" \
  -H "PRIVATE-TOKEN: $GITLABPW" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$REPO_NAME\",
    \"path\": \"$REPO_NAME\",
    \"description\": \"Dev and Prod environment created by Backstage\",
    \"visibility\": \"private\",
    \"initialize_with_readme\": true
  }" | jq -r '.path_with_namespace // .message'

echo "Repository created! You can now use '$REPO_NAME' in the Backstage template."
