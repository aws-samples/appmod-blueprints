#!/bin/bash
set -e

echo "Configuring GitLab access for $GIT_USERNAME using HTTPS..."

# Get user ID
USER_ID=$(curl -sS "$GITLAB_URL/api/v4/users?search=$GIT_USERNAME" -H "PRIVATE-TOKEN: $IDE_PASSWORD" | jq -r '.[0].id')

if [ "$USER_ID" = "null" ]; then
    echo "Error: User $GIT_USERNAME not found in GitLab"
    exit 1
fi

echo "Found user ID: $USER_ID"

# Configure Git to use HTTPS with credentials
echo "Configuring Git for HTTPS access..."
git config --global credential.helper store
git config --global user.name "$GIT_USERNAME"
git config --global user.email "$GIT_USERNAME@workshop.local"

# Create credentials file for HTTPS access
GITLAB_DOMAIN=$(echo "$GITLAB_URL" | sed 's|https://||')
echo "https://$GIT_USERNAME:$IDE_PASSWORD@$GITLAB_DOMAIN" > ~/.git-credentials

echo ""
echo "GitLab Configuration:"
echo "GitLab URL: $GITLAB_URL (for web and Git access)"
echo "GitLab username: $GIT_USERNAME"
echo "GitLab password: $IDE_PASSWORD"
echo "Git configured for HTTPS access using CloudFront URL"
