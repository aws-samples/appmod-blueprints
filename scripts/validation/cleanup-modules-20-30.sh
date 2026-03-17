#!/usr/bin/env bash
set -euo pipefail

echo "============================================"
echo "  Cleanup: Workshop Modules 20 & 30 Tests"
echo "============================================"
echo ""

# --- GitLab token ---
GL_TOKEN=$(curl -sLk "${GITLAB_URL}/oauth/token" \
  -d "grant_type=password&username=user1&password=${USER1_PASSWORD}" | jq -r '.access_token')
echo "GitLab token obtained"

# --- Backstage token ---
source ~/environment/platform-on-eks-workshop/scripts/validation/backstage-auth.sh 2>/dev/null
BS_TOKEN=$(backstage_get_token)
echo "Backstage token obtained"

# =============================================
# 1. Delete CICDPipelines (Kro instances) on hub
# =============================================
echo ""
echo ">>> Deleting CICDPipelines on hub cluster..."
kubectl config use-context peeks-hub
kubectl delete cicdpipeline rust-cicd-pipeline -n team-rust --ignore-not-found
kubectl delete cicdpipeline java-cicd-pipeline -n team-java --ignore-not-found
echo "Waiting 60s for Kro to clean up resources..."
sleep 60

# =============================================
# 2. Delete ArgoCD Applications on hub
# =============================================
echo ""
echo ">>> Deleting ArgoCD Applications..."
for app in rust-cicd rust-dev-cd rust-prod-cd java-cicd java-dev-cd java-prod-cd; do
  kubectl delete application ${app} -n argocd --ignore-not-found 2>/dev/null || true
done
sleep 30

# =============================================
# 3. Clean up dev cluster resources
# =============================================
echo ""
echo ">>> Cleaning up dev cluster..."
kubectl config use-context peeks-spoke-dev

# Delete AppModServices (Kro instances)
kubectl delete appmodservice rust-microservice -n team-rust --ignore-not-found 2>/dev/null || true
kubectl delete appmodservice progressive-app -n team-java --ignore-not-found 2>/dev/null || true
kubectl delete appmodservice next-js-app -n team-nextjs --ignore-not-found 2>/dev/null || true

# Delete services
kubectl delete svc rust-microservice rust-microservice-preview -n team-rust --ignore-not-found 2>/dev/null || true
kubectl delete svc progressive-app progressive-app-preview -n team-java --ignore-not-found 2>/dev/null || true
kubectl delete svc next-js-app next-js-app-preview -n team-nextjs --ignore-not-found 2>/dev/null || true

sleep 30

# Delete namespaces
kubectl delete namespace team-rust --ignore-not-found 2>/dev/null || true
kubectl delete namespace team-java --ignore-not-found 2>/dev/null || true
kubectl delete namespace team-nextjs --ignore-not-found 2>/dev/null || true

# =============================================
# 4. Clean up hub cluster namespaces
# =============================================
echo ""
echo ">>> Cleaning up hub cluster namespaces..."
kubectl config use-context peeks-hub
kubectl delete namespace team-rust --ignore-not-found 2>/dev/null || true
kubectl delete namespace team-java --ignore-not-found 2>/dev/null || true

# =============================================
# 5. Delete ECR repositories
# =============================================
echo ""
echo ">>> Deleting ECR repositories..."
for repo in peeks/rust peeks/rust/cache peeks/java peeks/java/cache; do
  aws ecr delete-repository --repository-name "${repo}" --region ${AWS_REGION} --force 2>/dev/null || true
  echo "  Deleted ECR: ${repo}"
done

# =============================================
# 6. Delete Backstage components
# =============================================
echo ""
echo ">>> Deleting Backstage catalog entities..."
for entity in "component:default/rust-cicd-pipeline" "component:default/java-cicd-pipeline"; do
  KIND=$(echo $entity | cut -d: -f1)
  NS_NAME=$(echo $entity | cut -d: -f2)
  NS=$(echo $NS_NAME | cut -d/ -f1)
  NAME=$(echo $NS_NAME | cut -d/ -f2)
  
  # Unregister entity
  ENTITY_UID=$(curl -sLk "${BACKSTAGE_URL}/api/catalog/entities/by-name/${KIND}/${NS}/${NAME}" \
    -H "Authorization: Bearer ${BS_TOKEN}" | jq -r '.metadata.uid // empty')
  
  if [ -n "$ENTITY_UID" ]; then
    # Find the location
    LOC_REF=$(curl -sLk "${BACKSTAGE_URL}/api/catalog/entities/by-name/${KIND}/${NS}/${NAME}" \
      -H "Authorization: Bearer ${BS_TOKEN}" | jq -r '.metadata.annotations["backstage.io/managed-by-origin-location"] // empty')
    
    if [ -n "$LOC_REF" ]; then
      # Delete by unregistering location
      LOC_ID=$(curl -sLk "${BACKSTAGE_URL}/api/catalog/locations" \
        -H "Authorization: Bearer ${BS_TOKEN}" | jq -r ".[] | select(.data.target == \"${LOC_REF#url:}\") | .data.id // empty" 2>/dev/null)
      
      if [ -n "$LOC_ID" ]; then
        curl -sLk -X DELETE "${BACKSTAGE_URL}/api/catalog/locations/${LOC_ID}" \
          -H "Authorization: Bearer ${BS_TOKEN}" 2>/dev/null || true
      fi
    fi
    
    # Force delete entity
    curl -sLk -X DELETE "${BACKSTAGE_URL}/api/catalog/entities/by-uid/${ENTITY_UID}" \
      -H "Authorization: Bearer ${BS_TOKEN}" 2>/dev/null || true
    echo "  Deleted Backstage entity: ${entity}"
  else
    echo "  Entity not found: ${entity}"
  fi
done

# =============================================
# 7. Delete GitLab CI/CD repos
# =============================================
echo ""
echo ">>> Deleting GitLab CI/CD repositories..."
for repo_name in rust-cicd java-cicd; do
  PROJECT_ID=$(curl -sLk "${GITLAB_URL}/api/v4/projects?search=${repo_name}" \
    -H "Authorization: Bearer ${GL_TOKEN}" | jq -r ".[0].id // empty")
  
  if [ -n "$PROJECT_ID" ] && [ "$PROJECT_ID" != "null" ]; then
    curl -sLk -X DELETE "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}" \
      -H "Authorization: Bearer ${GL_TOKEN}" 2>/dev/null || true
    echo "  Deleted GitLab project: ${repo_name} (ID: ${PROJECT_ID})"
  else
    echo "  GitLab project not found: ${repo_name}"
  fi
done

# =============================================
# 8. Reset application repos
# =============================================
echo ""
echo ">>> Resetting application repositories..."

# Reset Rust repo
cd ~/environment/applications/rust
rm -f deployment/dev/application.yaml deployment/dev/services.yaml
rm -f deployment/prod/application.yaml deployment/prod/services.yaml
git checkout -- src/api/services/ui.rs 2>/dev/null || true
git add -A
git diff --cached --quiet || git commit -m "Cleanup: reset to pre-test state"
git push origin main 2>/dev/null || true

# Reset Java repo
cd ~/environment/applications/java
rm -f deployment/dev/application.yaml deployment/dev/services.yaml
sed -i 's|argoproj/rollouts-demo:yellow|argoproj/rollouts-demo:blue|' progressive-app.yaml 2>/dev/null || true
git checkout -- src/src/main/webapp/index.jsp 2>/dev/null || true
git checkout -- README.md 2>/dev/null || true
git add -A
git diff --cached --quiet || git commit -m "Cleanup: reset to pre-test state"
git push origin main 2>/dev/null || true

echo ""
echo "============================================"
echo "  Cleanup Complete!"
echo "============================================"
echo ""
echo "Remaining manual checks:"
echo "  - Verify ArgoCD apps are removed: kubectl get applications -n argocd | grep -E 'rust|java|next'"
echo "  - Verify namespaces are deleted: kubectl get ns | grep -E 'team-rust|team-java|team-nextjs'"
echo "  - Verify ECR repos are deleted: aws ecr describe-repositories --region ${AWS_REGION} --query 'repositories[].repositoryName' | grep peeks"
