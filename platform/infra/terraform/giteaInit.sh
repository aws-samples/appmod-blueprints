#!/bin/sh

# This script requires DOMAIN_NAME variable to be setup already
# DOMAIN_NAME is the domain name of the cluster

export DOMAIN_NAME=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export REPO_ROOT=$(git rev-parse --show-toplevel)
echo "Creating app repositories in gitea"

# Install Binaries below if needed
# apk add gitea
# apk add git
# apk add openssh-client

cd ${REPO_ROOT}/applications

export PASSWORD=$(kubectl get secret gitea-credential -n gitea -o jsonpath='{.data.password}' | base64 --decode)
export USERNAME=$(kubectl get secret gitea-credential -n gitea -o jsonpath='{.data.username}' | base64 --decode)
export USER_PASS="${USERNAME}:${PASSWORD}"
export ENCODED_USER_PASS=$(echo "$USER_PASS" | tr -d \\n | base64)

curl -k -X POST "https://$DOMAIN_NAME/gitea/api/v1/admin/users/$USERNAME/repos" -H "content-type: application/json" -H "Authorization: Basic $ENCODED_USER_PASS" --data '{"name":"dotnet"}'
curl -k -X POST "https://$DOMAIN_NAME/gitea/api/v1/admin/users/$USERNAME/repos" -H "content-type: application/json" -H "Authorization: Basic $ENCODED_USER_PASS" --data '{"name":"golang"}'
curl -k -X POST "https://$DOMAIN_NAME/gitea/api/v1/admin/users/$USERNAME/repos" -H "content-type: application/json" -H "Authorization: Basic $ENCODED_USER_PASS" --data '{"name":"java"}'
curl -k -X POST "https://$DOMAIN_NAME/gitea/api/v1/admin/users/$USERNAME/repos" -H "content-type: application/json" -H "Authorization: Basic $ENCODED_USER_PASS" --data '{"name":"terraform-eks"}'

git config --global credential.helper store
mkdir -p ${REPO_ROOT}/applications/gitea
cd ${REPO_ROOT}/applications/gitea
git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/dotnet.git
cd dotnet
cp -r ${REPO_ROOT}/applications/dotnet ${REPO_ROOT}/applications/gitea/
git add .
git -c http.sslVerify=false commit -m "first commit" --no-verify
git remote remove origin
git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/dotnet.git
git -c http.sslVerify=false push -u origin main --no-verify

cd ..
git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/java.git
cd java
cp -r ${REPO_ROOT}/applications/java ${REPO_ROOT}/applications/gitea/
git add .
git -c http.sslVerify=false commit -m "first commit" --no-verify
git remote remove origin
git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/java.git
git -c http.sslVerify=false push -u origin main --no-verify

cd ..
git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/golang.git
cd golang
cp -r ${REPO_ROOT}/applications/golang ${REPO_ROOT}/applications/gitea/
git add .
git -c http.sslVerify=false commit -m "first commit" --no-verify
git remote remove origin
git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/golang.git
git -c http.sslVerify=false push -u origin main --no-verify

cd ..
git clone -c http.sslVerify=false https://$USER_PASS@$DOMAIN_NAME/gitea/$USERNAME/terraform-eks.git
cd terraform-eks
cp -r ${REPO_ROOT}/platform/infra/terraform/dev ${REPO_ROOT}/applications/gitea/terraform-eks/
cp -r ${REPO_ROOT}/platform/infra/terraform/prod ${REPO_ROOT}/applications/gitea/terraform-eks/
cp ${REPO_ROOT}/platform/infra/terraform/.gitignore ${REPO_ROOT}/applications/gitea/terraform-eks/
cp ${REPO_ROOT}/platform/infra/terraform/create-cluster.sh  ${REPO_ROOT}/applications/gitea/terraform-eks/
cp -r ${REPO_ROOT}/platform/infra/terraform/database ${REPO_ROOT}/applications/gitea/terraform-eks/ # for database
cp ${REPO_ROOT}/platform/infra/terraform/create-database.sh  ${REPO_ROOT}/applications/gitea/terraform-eks/ # for database
git add .
git -c http.sslVerify=false commit -m "first commit" --no-verify
git remote remove origin
git remote add origin https://$DOMAIN_NAME/gitea/$USERNAME/terraform-eks.git
git -c http.sslVerify=false push -u origin main --no-verify

# cleanup temp gitea folder
rm -rf ${REPO_ROOT}/applications/gitea

echo "Copied all repositories to Gitea"