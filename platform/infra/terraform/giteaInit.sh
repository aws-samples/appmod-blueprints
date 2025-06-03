#!/bin/bash

# This script requires DOMAIN_NAME variable to be setup already
# DOMAIN_NAME is the domain name of the cluster

export DOMAIN_NAME=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
export PASSWORD=$(kubectl get secret gitea-credential -n gitea -o jsonpath='{.data.password}' | base64 --decode)
export USERNAME=$(kubectl get secret gitea-credential -n gitea -o jsonpath='{.data.username}' | base64 --decode)
export USER_PASS="${USERNAME}:${PASSWORD}"
export ENCODED_USER_PASS=$(echo "$USER_PASS" | tr -d \\n | base64)

export TIMEOUT=10
export RETRY_INTERVAL=10
export MAX_RETRIES=40


# Function to check if Gitea is available
check_gitea_available() {
  echo "Checking if Gitea is available at https://$DOMAIN_NAME/gitea..."
  if curl -k -s -o /dev/null -w "%{http_code}" --connect-timeout $TIMEOUT https://$DOMAIN_NAME/gitea | grep -q "200\|302"; then
    echo "Gitea is available!"
    return 0
  else
    echo "Gitea is not available yet."
    return 1
  fi
}

# Wait for Gitea to be available
wait_for_gitea() {
  local retries=0
  until check_gitea_available || [ $retries -ge $MAX_RETRIES ]; do
    retries=$((retries+1))
    echo "Retry $retries/$MAX_RETRIES. Waiting $RETRY_INTERVAL seconds..."
    sleep $RETRY_INTERVAL
  done

  if [ $retries -ge $MAX_RETRIES ]; then
    echo "Error: Gitea is not available after $MAX_RETRIES retries."
    exit 1
  fi
}

# Create token function
create_token() {
  TOKEN_NAME="token_$(cat /dev/urandom | LC_ALL=C tr -dc 'a-zA-Z0-9' | fold -w 8 | head -n 1)"
  echo "Creating Gitea authentication token $TOKEN_NAME for user $USERNAME..."

  # Create the token
  local response=$(curl -k -s -X POST \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$TOKEN_NAME\", \"scopes\": [\"write:repository\"]}" \
    -u "$USERNAME:$PASSWORD" \
    -w "\n%{http_code}" \
    https://$DOMAIN_NAME/gitea/api/v1/users/$USERNAME/tokens)


  echo "Response for tolken"
  echo "$response"
  # Extract the HTTP status code
  local status_code=$(echo "$response" | tail -n1)
  # Extract the response body
  local body=$(echo "$response" | sed '$d')

  # Check if the request was successful
  if [[ "$status_code" == "2"* ]]; then
    # Extract the token
    TOKEN=$(echo "$body" | jq -r .sha1 | tr -d '\n' | base64 | tr -d '\n')

    if [ -z "$TOKEN" ] || [ "$TOKEN" == "null" ]; then
      echo "Error: Failed to extract token from response."
      echo "Response: $body"
      exit 1
    fi

    echo "Token created successfully!"
    echo "Encoded token: ${TOKEN:0:10}... (truncated for security)"
    kubectl patch secret gitea-credential -p '{"data": {"token": "'"$TOKEN"'"}}' -n gitea
    return 0
  else
    echo "Error: Failed to create token. Status code: $status_code"
    echo "Response: $body"
    echo "Status Code: $status_code"
    return 1
  fi
}

# Try to create token
try_create_token() {
  local retries=0
  until create_token || [ $retries -ge $MAX_RETRIES ]; do
    retries=$((retries+1))
    echo "Retry $retries/$MAX_RETRIES. Waiting $RETRY_INTERVAL seconds..."
    sleep $RETRY_INTERVAL
  done

  if [ $retries -ge $MAX_RETRIES ]; then
    echo "Error: Can't create Gitea TOKEN after $MAX_RETRIES retries."
    exit 1
  fi
}

# Create repositories in gitea
check_repo_exist() {
  local repo_name=$1
  local response=$(curl -k -s -o /dev/null -w "%{http_code}" -H "Authorization: Basic $ENCODED_USER_PASS" "https://$DOMAIN_NAME/gitea/api/v1/repos/$USERNAME/$repo_name")
  if [[ "$response" == "200" ]]; then
    echo "Repository $repo_name already exists."
    return 0
  else
    echo "Repository $repo_name does not exist."
    return 1
  fi
}

create_repo() {
  local repo_name=$1
  echo "Creating repository $repo_name..."
  curl -k -X POST "https://$DOMAIN_NAME/gitea/api/v1/user/repos" -H "content-type: application/json" -H "Authorization: Basic $ENCODED_USER_PASS" --data '{"name":"'$repo_name'"}'
  echo "Repository $repo_name created successfully!"
}


create_repo_content_application() {
    local repo_name=$1
    echo "Creating initial repo content for $repo_name..."
    export REPO_ROOT=$(git rev-parse --show-toplevel)

    rm -rf ${REPO_ROOT}/applications/gitea
    mkdir -p ${REPO_ROOT}/applications/gitea
    git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git ${REPO_ROOT}/applications/gitea/$repo_name
    pushd ${REPO_ROOT}/applications/gitea/$repo_name
    git config user.email "participants@workshops.aws"
    git config user.name "Workshop Participant"
    cp -r ${REPO_ROOT}/applications/$repo_name ${REPO_ROOT}/applications/gitea/
    git add .
    git -c http.sslVerify=false commit -m "first commit"
    git remote remove origin
    git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git
    git -c http.sslVerify=false push -u origin main

    popd
}

create_repo_content_terraform_eks() {
    local repo_name=$1
    echo "Creating initial repo content for $repo_name..."
    export REPO_ROOT=$(git rev-parse --show-toplevel)

    rm -rf ${REPO_ROOT}/applications/gitea
    mkdir -p ${REPO_ROOT}/applications/gitea
    git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git ${REPO_ROOT}/applications/gitea/$repo_name
    pushd ${REPO_ROOT}/applications/gitea/$repo_name
    git config user.email "participants@workshops.aws"
    git config user.name "Workshop Participant"

    cp -r ${REPO_ROOT}/platform/infra/terraform/dev ${REPO_ROOT}/applications/gitea/$repo_name/
    cp -r ${REPO_ROOT}/platform/infra/terraform/prod ${REPO_ROOT}/applications/gitea/$repo_name/
    # Added for Aurora and DB Setup
    cp -r ${REPO_ROOT}/platform/infra/terraform/database ${REPO_ROOT}/applications/gitea/$repo_name/
    cp ${REPO_ROOT}/platform/infra/terraform/.gitignore ${REPO_ROOT}/applications/gitea/$repo_name/
    cp ${REPO_ROOT}/platform/infra/terraform/create-cluster.sh  ${REPO_ROOT}/applications/gitea/$repo_name/
    cp ${REPO_ROOT}/platform/infra/terraform/create-database.sh ${REPO_ROOT}/applications/gitea/$repo_name/

    git add .
    git -c http.sslVerify=false commit -m "first commit"
    git remote remove origin
    git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git
    git -c http.sslVerify=false push -u origin main

    popd
}

create_repo_content_platform() {
    local repo_name=$1
    echo "Creating initial repo content for $repo_name..."
    export REPO_ROOT=$(git rev-parse --show-toplevel)

    rm -rf ${REPO_ROOT}/applications/gitea
    mkdir -p ${REPO_ROOT}/applications/gitea
    git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git ${REPO_ROOT}/applications/gitea/$repo_name
    pushd ${REPO_ROOT}/applications/gitea/$repo_name
    git config user.email "participants@workshops.aws"
    git config user.name "Workshop Participant"

    cp -r ${REPO_ROOT}/deployment/addons/kubevela ${REPO_ROOT}/applications/gitea/$repo_name/
    cp -r ${REPO_ROOT}/platform/backstage ${REPO_ROOT}/applications/gitea/$repo_name/
    # Replacing hostname in backstage catalog file
    sed -e "s#HOSTNAME#${DOMAIN_NAME}#g" ${REPO_ROOT}/platform/backstage/templates/catalog-info.yaml > ${REPO_ROOT}/applications/gitea/$repo_name/backstage/templates/catalog-info.yaml

    git add .
    git -c http.sslVerify=false commit -m "first commit"
    git remote remove origin
    git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/$repo_name.git
    git -c http.sslVerify=false push -u origin main

    popd
}

check_and_create_repo() {
  local repo_name=$1
  if check_repo_exist "$repo_name"; then
    echo "Repository $repo_name already exists."
  else
    create_repo "$repo_name"
    # if repo_name is dotnet, golang, java, rust, next-js
    if [[ "$repo_name" == "dotnet" || "$repo_name" == "golang" || "$repo_name" == "java" || "$repo_name" == "rust" || "$repo_name" == "next-js" ]]; then
      echo "Repository $repo_name created successfully!"
      # Create intial repo content
      create_repo_content_application "$repo_name"
    fi
    # if repo_name is terraform-eks
    if [[ "$repo_name" == "terraform-eks" ]]; then
      echo "Repository $repo_name created successfully!"
      # Create intial repo content
      create_repo_content_terraform_eks "$repo_name"
    fi
    # if repo_name is platform
    if [[ "$repo_name" == "platform" ]]; then
      echo "Repository $repo_name created successfully!"
      # Create intial repo content
      create_repo_content_platform "$repo_name"
    fi
  fi
}


# main
wait_for_gitea
try_create_token

git config --global credential.helper store
check_and_create_repo "dotnet"
check_and_create_repo "golang"
check_and_create_repo "java"
check_and_create_repo "rust"
check_and_create_repo "next-js"

check_and_create_repo "terraform-eks"
check_and_create_repo "platform"

# cleanup temp gitea folder
rm -rf ${REPO_ROOT}/applications/gitea

echo "Copied all repositories to Gitea"

# Create ClusterSecretStore for gitea-credential
# TODO this should move to install.sh of gitea
echo "Creating ClusterSecretStore for gitea-credential..."
kubectl apply -f ${REPO_ROOT}/platform/infra/terraform/deploy-apps/gitea/gitea-cluster-secret.yaml