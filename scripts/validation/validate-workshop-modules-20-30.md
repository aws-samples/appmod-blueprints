# Validate Workshop Modules 20 & 30 — End-to-End

You are a Kiro agent running on the workshop IDE instance. Your job is to execute all the
commands below in order, verifying each phase before moving to the next. You do NOT have
access to the workshop content files — everything you need is in this prompt.

## Environment

- You are `ec2-user` on the IDE instance.
- Application repos: `~/environment/applications/{rust,java,next-js}`
- Workshop repo: `~/environment/platform-on-eks-workshop`
- Hub cluster context alias: `hub` (runs `kubectl config use-context peeks-hub`)
- Dev cluster context alias: `dev` (runs `kubectl config use-context peeks-spoke-dev`)
- Prod cluster context alias: `prod` (runs `kubectl config use-context peeks-spoke-prod`)

## Credentials

| Service   | Username | Password          |
|-----------|----------|-------------------|
| Backstage | `user1`  | `$USER1_PASSWORD` |
| GitLab    | `user1`  | `$USER1_PASSWORD` |
| ArgoCD    | `admin`  | `$IDE_PASSWORD`   |
| Grafana   | `user1`  | `$USER1_PASSWORD` |

## Required env vars (should already be set)

`$BACKSTAGE_URL`, `$ARGOCD_URL`, `$WORKFLOWS_URL`, `$DNS_DEV`, `$DNS_PROD`,
`$AWS_ACCOUNT_ID`, `$AWS_REGION`, `$USER1_PASSWORD`, `$IDE_PASSWORD`,
`$GITLAB_URL`, `$GRAFANA_URL`

Verify they exist before starting:

```bash
echo "BACKSTAGE=$BACKSTAGE_URL ARGOCD=$ARGOCD_URL WORKFLOWS=$WORKFLOWS_URL"
echo "DNS_DEV=$DNS_DEV DNS_PROD=$DNS_PROD ACCOUNT=$AWS_ACCOUNT_ID REGION=$AWS_REGION"
```

If any are empty, stop and report.

---

## Phase 1 — Deploy Next.js Frontend

The Rust backend has a Next.js frontend. Deploy it first so it's ready when the backend comes up.

```bash
cd ~/environment/applications/next-js
dev
kubectl create namespace team-nextjs --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f ./deployment/dev/application.yaml
sleep 20
kubectl get pods -n team-nextjs
```

**Expected**: Pods running. `curl -sLk http://$DNS_DEV/unicorn` returns a page (500 is OK — backend not deployed yet).

---

## Phase 2 — Provision Rust CI/CD via Backstage

Use the Backstage scaffolder API to create the Rust CI/CD pipeline. This is equivalent to
clicking `Create... → Deploy CI/CD Pipeline With kro (GitOps)` in the Backstage UI.

Authenticate to Backstage via Keycloak and call the scaffolder API:

```bash
source ~/environment/platform-on-eks-workshop/scripts/validation/backstage-auth.sh

backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"rust","aws_region":"us-west-2","dockerfile_path":".","deployment_path":"./deployment"}'
```

The script authenticates as `user1` through Keycloak OIDC, obtains a Backstage identity token,
submits the scaffolder task, and polls until completion.

**Verify** (wait up to 5 minutes for ArgoCD sync):

```bash
hub
kubectl get cicdpipelines rust-cicd-pipeline -n team-rust
```

Should show `STATE: ACTIVE`. If not ready, wait 30s and retry (up to 10 retries).

---

## Phase 3 — Wait for Rust CI Pipelines

The Backstage template triggers two Argo Workflow pipelines in sequence:
1. `rust-cicd-setup-workflow` — warms caches (~5 min)
2. `rust-cicd-initial-build-workflow` — builds and pushes the container image (~5-10 min)

Poll until both complete:

```bash
hub
# Check setup workflow
kubectl get workflows -n team-rust -l app=rust --sort-by=.metadata.creationTimestamp
```

Wait until you see both workflows with `Succeeded` phase. This can take up to 15 minutes total.

**Verify**:

```bash
aws ecr describe-images --repository-name peeks/rust --region ${AWS_REGION} \
  --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageTags[0]' --output text
```

Should return an image tag (not empty).

---

## Phase 4 — Deploy Rust to DEV (kro path)

Copy the kro template manifests into the dev sync folder, replace the image placeholder
with the real ECR image, commit, and push. ArgoCD will pick up the change and deploy.

```bash
cd ~/environment/applications/rust

IMAGE_TAG=$(aws ecr describe-images --repository-name peeks/rust --region ${AWS_REGION} \
  --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageTags[0]' --output text)

cp deployment/templates/kro/application.yaml deployment/dev/application.yaml
cp deployment/templates/kro/services.yaml    deployment/dev/services.yaml

sed -i "s|<image>|${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/peeks/rust:${IMAGE_TAG}|" \
  deployment/dev/application.yaml

sed -i "s|\${AWS_ACCOUNT_ID}|${AWS_ACCOUNT_ID}|g" deployment/dev/application.yaml

git pull
git add .
git commit -m "Deploy Rust kro manifest to dev"
git push origin main
```

Wait 3-4 minutes for ArgoCD to sync and pods to start.

**Verify**:

```bash
dev
kubectl get pods -n team-rust
```

Pods should be `Running`. If you see `CrashLoopBackOff` (Pod Identity race condition with kro),
restart the deployment and wait:

```bash
kubectl rollout restart deployment/rust-microservice -n team-rust
sleep 30
kubectl get pods -n team-rust
```

Then verify the backend responds:

```bash
curl --request GET -sLk --url "http://${DNS_DEV}/rust-app/collection/FRONT_PAGE" | head -c 200
```

Should return JSON product data. Also verify the frontend now works:

```bash
curl -sLk -o /dev/null -w "%{http_code}" "http://${DNS_DEV}/unicorn"
```

Should return `200`.

---

## Phase 5 — Promote Rust to PROD

Copy the same kro templates to the prod sync folder, adjust for prod environment.

```bash
cd ~/environment/applications/rust

cp deployment/templates/kro/application.yaml deployment/prod/application.yaml
cp deployment/templates/kro/services.yaml    deployment/prod/services.yaml

sed -i "s|<image>|${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/peeks/rust:${IMAGE_TAG}|" \
  deployment/prod/application.yaml

sed -i 's/peeks-spoke-dev/peeks-spoke-prod/' deployment/prod/application.yaml

sed -i "s|\${AWS_ACCOUNT_ID}|${AWS_ACCOUNT_ID}|g" deployment/prod/application.yaml

git add .
git commit -m "Promote Rust to production"
git push origin main
```

**Verify** (wait 3-4 min):

```bash
hub
kubectl get application rust-prod-cd -n argocd -o jsonpath='{.status.sync.status}'
```

Should return `Synced`.

---

## Phase 6 — Progressive Delivery Demo (Java blue→yellow)

Deploy a demo app that visually shows canary rollout traffic shifting.

```bash
dev
cd ~/environment/applications/java
kubectl create namespace team-java --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f progressive-app.yaml
```

**Verify**:

```bash
kubectl get appmodservices progressive-app -n team-java -o wide
```

Should show `STATE: ACTIVE`. Verify the app serves traffic:

```bash
curl -sLk -o /dev/null -w "%{http_code}" "http://${DNS_DEV}/progressive/"
```

Should return `200`.

Now trigger a canary rollout by changing the image color from blue to yellow:

```bash
sed -i 's|argoproj/rollouts-demo:blue|argoproj/rollouts-demo:yellow|' \
  ~/environment/applications/java/progressive-app.yaml
kubectl apply -f ~/environment/applications/java/progressive-app.yaml
```

**Verify** — watch the rollout progress:

```bash
kubectl argo rollouts get rollout progressive-app -n team-java --no-color
```

Wait until status shows `Healthy` (full promotion, ~2 min). The canary progresses
20% → 40% → 60% → 80% → 100%.

---

## Phase 7 — Provision Java CI/CD via Backstage

Same as Phase 2 but for the Java application. IMPORTANT: Dockerfile path is `./src` (not default).

```bash
source ~/environment/platform-on-eks-workshop/scripts/validation/backstage-auth.sh

backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"java","aws_region":"us-west-2","dockerfile_path":"./src","deployment_path":"./deployment"}'
```

**Verify** (wait up to 5 min):

```bash
hub
kubectl get cicdpipelines java-cicd-pipeline -n team-java
```

Should show `STATE: ACTIVE`.

---

## Phase 8 — Wait for Java CI Setup + Copy Template + Trigger Build

Wait for the `java-cicd-setup-workflow` to complete, then place the kro template and trigger a build.

```bash
hub
# Poll for setup workflow completion (up to 10 min)
kubectl get workflows -n team-java -l app=java --sort-by=.metadata.creationTimestamp
```

Once `java-cicd-setup-workflow` shows `Succeeded`, copy the template and trigger CI:

```bash
cd ~/environment/applications/java

cp deployment/templates/kro/application.yaml deployment/dev/application.yaml
cp deployment/templates/kro/services.yaml    deployment/dev/services.yaml

git add .
echo "# Trigger build" >> README.md
git add README.md
git commit -m "Add kro template and trigger build"
git push origin main
```

Wait for `java-cicd-cicd-*` workflow to complete (~4 min):

```bash
hub
kubectl get workflows -n team-java -l app=java --sort-by=.metadata.creationTimestamp
```

**Verify** — the CI pipeline updated the image tag:

```bash
cd ~/environment/applications/java
git pull
grep "image:" deployment/dev/application.yaml
```

Should show a real ECR URI like `<account>.dkr.ecr.<region>.amazonaws.com/peeks/java:<hash>`,
not `<image>`.

Verify the Java app is accessible:

```bash
curl -sLk -o /dev/null -w "%{http_code}" "http://${DNS_DEV}/java-app/java-app/"
```

Should return `200`. The page shows a red background.

---

## Phase 9 — Quality Gates: Trigger Functional Gate Failure

The Java kro template already includes `functionalGate` (expects color "red") and
`performanceGate`. We'll change the app color to orange to trigger a rollout failure.

Create a new `index.jsp` with orange background:

```bash
cd ~/environment/applications/java
cat > src/src/main/webapp/index.jsp << 'EOF'
<html>
<body style='background-color: orange;'>
<h2>Hello team, this is <%= System.getenv("APP_ENV") %> environment version 2</h2>
</html>
EOF

git add -A
git commit -m "Change color to orange - should fail functional gate"
git pull --rebase
git push
```

Wait for the CI pipeline to build the new image (~4 min):

```bash
hub
kubectl get workflows -n team-java -l app=java --sort-by=.metadata.creationTimestamp --no-headers | tail -1
```

Once the latest workflow shows `Succeeded`, force sync and watch the rollout:

```bash
hub
kubectl patch application java-dev-cd -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'

dev
kubectl argo rollouts get rollout java-webservice -n team-java --no-color
```

**Expected**: The rollout should show `Degraded` / `Failed` because the functional gate
expects "red" but the app now returns "orange". The rollout rolls back automatically.

**Verify** the app is still red (rolled back):

```bash
curl -sLk "http://${DNS_DEV}/java-app/java-app/" | grep background-color
```

Should still contain `red` (not orange).

---

## Phase 10 — Quality Gates: Fix Functional Gate and Succeed

Update the functional gate to expect "orange" so the rollout succeeds.

```bash
cd ~/environment/applications/java
git pull

# Update extraArgs from "red" to "orange" in the kro manifest
sed -i '/functionalGate:/,/performanceGate:/ s/extraArgs: "red"/extraArgs: "orange"/' \
  deployment/dev/application.yaml

git add -A
git commit -m "Fix functional gate to expect orange"
git pull --rebase
git push
```

Force sync and watch the rollout:

```bash
hub
kubectl patch application java-dev-cd -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'
```

Verify the analysis template was updated:

```bash
dev
kubectl get analysistemplate functional-gate-java-webservice -n team-java \
  -o jsonpath='{.spec.metrics[0].provider.job.spec.template.spec.containers[0].args[1]}' \
  | grep -o "Testing for: [a-z]*"
```

Should show `Testing for: orange`.

Trigger a new rollout:

```bash
dev
kubectl patch rollout java-webservice -n team-java --type json \
  -p='[{"op": "replace", "path": "/spec/template/metadata/annotations/restart-trigger", "value": "'$(date +%s)'"}]'
```

**Verify** — wait ~2 min, the rollout should succeed:

```bash
kubectl argo rollouts get rollout java-webservice -n team-java --no-color
```

Should show `Healthy` status. The app now shows orange:

```bash
curl -sLk "http://${DNS_DEV}/java-app/java-app/" | grep background-color
```

Should contain `orange`.

---

## Phase 11 — Metrics-Driven Decisions (Rust)

Edit the Rust dev manifest to add `functionalGate`, `performanceGate`, and `metrics` sections.
The Rust app is already deployed from Phase 4.

```bash
cd ~/environment/applications/rust
git pull
```

Open `deployment/dev/application.yaml` and add the following fields at the end of the `spec` block
(after the `ingress` section, before the closing of the spec):

```yaml
  functionalGate:
    enabled: true
    image: "httpd:alpine"
    extraArgs: "{"
  performanceGate:
    enabled: true
    image: "artilleryio/artillery:latest"
  metrics:
    enabled: true
    path: "/collection/test"
```

The final file should have `functionalGate`, `performanceGate`, and `metrics` as siblings of
`ingress` under `spec`.

Commit and push:

```bash
cd ~/environment/applications/rust
git add -A
git commit -m "Add metrics-driven decisions to Rust app"
git push
```

Sync and watch:

```bash
hub
kubectl patch application rust-dev-cd -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'

dev
kubectl argo rollouts retry rollout rust-microservice -n team-rust
kubectl argo rollouts get rollout rust-microservice -n team-rust --no-color
```

**Verify**: Rollout should progress through performance gate and pass all 5 metrics,
eventually showing `Healthy`.

---

## Phase 12 — Metrics Failure Test (Rust)

Introduce a 3-second delay in the Rust app to trigger a metrics failure.

```bash
cd ~/environment/applications/rust
sed -i 's|^    // sleep(Duration::from_secs(3)).await;|    sleep(Duration::from_secs(3)).await;|' \
  src/api/services/ui.rs

git add -A
git commit -m "Introduce delay to fail metrics"
git pull --rebase
git push
```

Wait for the CI pipeline to build (~5-10 min), then sync:

```bash
hub
kubectl patch application rust-dev-cd -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'

dev
kubectl argo rollouts get rollout rust-microservice -n team-rust --no-color
```

**Expected**: Rollout should fail and roll back (metrics threshold exceeded — avg response > 3s).

---

## Phase 13 — Restore Rust App

Revert the delay:

```bash
cd ~/environment/applications/rust
sed -i 's|^    sleep(Duration::from_secs(3)).await;|    // sleep(Duration::from_secs(3)).await;|' \
  src/api/services/ui.rs

git add -A
git commit -m "Revert delay - restore healthy app"
git pull --rebase
git push
```

Wait for CI, then sync and verify the rollout succeeds again.

---

## Summary of Expected Outcomes

| Phase | What                           | Expected Result                              |
|-------|--------------------------------|----------------------------------------------|
| 1     | Next.js frontend               | Pods running, 500 on /unicorn (no backend)   |
| 2     | Rust CI/CD via Backstage       | cicdpipeline ACTIVE                          |
| 3     | Rust CI build                  | ECR image exists                             |
| 4     | Rust DEV deploy (kro)          | Pods running, /rust-app returns JSON         |
| 5     | Rust PROD promote              | rust-prod-cd Synced                          |
| 6     | Progressive demo (blue→yellow) | Canary rollout completes                     |
| 7     | Java CI/CD via Backstage       | cicdpipeline ACTIVE                          |
| 8     | Java CI build + template       | ECR image in manifest, /java-app returns 200 |
| 9     | Functional gate failure        | Rollout Degraded, app still red              |
| 10    | Functional gate fix            | Rollout Healthy, app now orange              |
| 11    | Rust metrics-driven deploy     | Rollout Healthy with metrics                 |
| 12    | Rust metrics failure           | Rollout fails and rolls back                 |
| 13    | Rust restore                   | Rollout succeeds again                       |

If any phase fails, stop and report the phase number, the command that failed, and the output.
