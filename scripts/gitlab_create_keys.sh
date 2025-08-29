#!/bin/bash
set -e

echo "Adding an SSH key for $GIT_USERNAME ..."

# Check if SSH key exists, if not create one
if [ ! -f ~/.ssh/id_rsa ]; then
    echo "Creating SSH key..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -C "$GIT_USERNAME@$(hostname)"
fi

PUB_KEY=$(cat ~/.ssh/id_rsa.pub)
TITLE="$(hostname)-$(date +%s)"

# Get user ID
USER_ID=$(curl -sS "$GITLAB_URL/api/v4/users?search=$GIT_USERNAME" -H "PRIVATE-TOKEN: $IDE_PASSWORD" | jq -r '.[0].id')

if [ "$USER_ID" = "null" ]; then
    echo "Error: User $GIT_USERNAME not found in GitLab"
    exit 1
fi

echo "Found user ID: $USER_ID"

# Try to add SSH key using root token (for admin operations)
ROOT_TOKEN="root-$IDE_PASSWORD"
RESPONSE=$(curl -sS -X 'POST' "$GITLAB_URL/api/v4/users/$USER_ID/keys" \
  -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d "{
  \"key\": \"$PUB_KEY\",
  \"title\": \"$TITLE\"
}")

# Check if the response contains an error
if echo "$RESPONSE" | jq -e '.message' > /dev/null 2>&1; then
    ERROR_MSG=$(echo "$RESPONSE" | jq -r '.message')
    if [[ "$ERROR_MSG" == *"already been taken"* ]]; then
        echo "SSH key already exists for this user - continuing..."
    else
        echo "Error adding SSH key: $ERROR_MSG"
        # Try to continue anyway as the key might already exist
    fi
else
    echo "SSH key added successfully"
    echo "$RESPONSE" | jq '.'
fi

# Add GitLab host to known_hosts
echo "Adding GitLab host to known_hosts..."
ssh-keyscan -H $NLB_DNS >> ~/.ssh/known_hosts 2>/dev/null || true

echo ""
echo "GitLab Configuration:"
echo "GitLab URL: $GITLAB_URL"
echo "GitLab username: $GIT_USERNAME"
echo "GitLab password: $IDE_PASSWORD"
echo "SSH host: $NLB_DNS"
