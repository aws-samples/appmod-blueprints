#!/bin/bash

# Test script for sed replacements on kro-clusters values.yaml

# Set environment variables
export MGMT_ACCOUNT_ID=665742499430
export WORKSPACE_PATH=/home/ec2-user/environment
export WORKING_REPO=platform-on-eks-workshop
export GITLAB_URL=https://dlu6mbvnpgi1g.cloudfront.net/gitlab
export GIT_USERNAME=root

echo "=== Testing sed replacements on kro-clusters values.yaml ==="
echo "Environment variables:"
echo "  MGMT_ACCOUNT_ID: $MGMT_ACCOUNT_ID"
echo "  GITLAB_URL: $GITLAB_URL"
echo "  GIT_USERNAME: $GIT_USERNAME"
echo

TARGET_FILE="$WORKSPACE_PATH/$WORKING_REPO/gitops/fleet/kro-values/tenants/tenant1/kro-clusters/values.yaml"

echo "Target file: $TARGET_FILE"
echo

echo "=== BEFORE sed replacements ==="
head -35 "$TARGET_FILE"
echo

echo "=== Applying sed replacements ==="
sed -i \
  -e 's/managementAccountId: "[^"]*"/managementAccountId: "'"$MGMT_ACCOUNT_ID"'"/g' \
  -e 's/accountId: "[^"]*"/accountId: "'"$MGMT_ACCOUNT_ID"'"/g' \
  -e 's|addonsRepoUrl: "[^"]*"|addonsRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|fleetRepoUrl: "[^"]*"|fleetRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|platformRepoUrl: "[^"]*"|platformRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  -e 's|workloadRepoUrl: "[^"]*"|workloadRepoUrl: "'"$GITLAB_URL"'/'"$GIT_USERNAME"'/'"$WORKING_REPO"'.git"|g' \
  "$TARGET_FILE"

echo "=== AFTER sed replacements ==="
head -35 "$TARGET_FILE"
echo

echo "=== Applying uncommenting sed with END MARKER boundary ==="
sed -i '
# First uncomment the section headers
s/^  # cluster-dev:/  cluster-dev:/g
s/^  # cluster-prod:/  cluster-prod:/g

# Uncomment content between cluster-dev and its END MARKER
/^  cluster-dev:/,/^  # #END MARKER FOR SED/ {
  /^  # #END MARKER FOR SED/!s/^  #/  /g
}
# Uncomment content between cluster-prod and its END MARKER (if it exists)
/^  cluster-prod:/,/^  # #END MARKER FOR SED/ {
  /^  # #END MARKER FOR SED/!s/^  #/  /g
}' "$TARGET_FILE"

echo "=== FINAL RESULT ==="
head -40 "$TARGET_FILE"
echo

echo "=== Test completed ==="
