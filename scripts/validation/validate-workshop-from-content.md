# Validate Workshop Modules 20 & 30 — From Workshop Content

You are a Kiro agent running on the workshop IDE instance. Your job is to execute the
workshop instructions from the S3 content bucket, following the exact steps a participant
would perform. Verify each phase before moving to the next.

## Configuration

**Abstraction tool**: `{{ABSTRACTION_TOOL}}` — set to `kro` or `kubevela` before starting.

The agent MUST replace `{{ABSTRACTION_TOOL}}` with the user's choice and follow ONLY the
matching tab instructions from the workshop content files.

## Content Source

Workshop instructions are in: `/tmp/workshop-content/content/`

Download them first:

```bash
aws s3 cp s3://peeks-workshop-content-549022276298/content.tar.gz /tmp/content.tar.gz
rm -rf /tmp/workshop-content && mkdir -p /tmp/workshop-content
tar -xzf /tmp/content.tar.gz -C /tmp/workshop-content/ 2>/dev/null
```

The content files map to phases as follows:

| Phase | Content File | Section |
|-------|-------------|---------|
| 1 | `20_ApplicationDelivery/01_Rust/01_Intro/index.en.md` | "Manually deploy the frontend" |
| 2 | `20_ApplicationDelivery/01_Rust/02_Backstage/index.en.md` | Full page (Backstage provisioning) |
| 3 | `20_ApplicationDelivery/01_Rust/03_CI/index.en.md` | Full page (wait for CI workflows) |
| 4 | `20_ApplicationDelivery/01_Rust/04_CD/index.en.md` | "Deploying the Application" through "Promoting to Production" |
| 5 | `20_ApplicationDelivery/01_Rust/04_CD/index.en.md` | "Promoting to Production" |
| 6 | `30_ProgressiveApplicationDelivery/10_progressive-delivery/index.en.md` | Full page (blue→yellow demo) |
| 7 | `30_ProgressiveApplicationDelivery/20_create-cicd/index.en.md` | Full page (Java CI/CD via Backstage) |
| 8 | `30_ProgressiveApplicationDelivery/20_create-cicd/index.en.md` | Steps 8-11 (copy template, trigger build, verify) |
| 9 | `30_ProgressiveApplicationDelivery/30_function-performance-test-java/index.en.md` | "Changing the Java Application" |
| 10 | `30_ProgressiveApplicationDelivery/30_function-performance-test-java/index.en.md` | "Fixing the Issue" |
| 11 | `30_ProgressiveApplicationDelivery/50_metrics-driven-decisions/index.en.md` | "Implementing Metrics-Driven Decisions" |
| 12 | `30_ProgressiveApplicationDelivery/50_metrics-driven-decisions/index.en.md` | "Exploring Errors" |
| 13 | `30_ProgressiveApplicationDelivery/50_metrics-driven-decisions/index.en.md` | "Restoring the App" |

## Environment

- You are `ec2-user` on the IDE instance.
- Application repos: `~/environment/applications/{rust,java,next-js}`
- Workshop repo: `~/environment/platform-on-eks-workshop`
- Cluster contexts: `peeks-hub`, `peeks-spoke-dev`, `peeks-spoke-prod`
- The workshop uses `hub`, `dev`, `prod` as aliases — use `kubectl config use-context peeks-{name}` instead.

## Credentials

| Service   | Username | Password          |
|-----------|----------|-------------------|
| Backstage | `user1`  | `$USER1_PASSWORD` |
| GitLab    | `user1`  | `$USER1_PASSWORD` |
| ArgoCD    | `admin`  | `$IDE_PASSWORD`   |

## Required env vars

```bash
echo "BACKSTAGE=$BACKSTAGE_URL ARGOCD=$ARGOCD_URL WORKFLOWS=$WORKFLOWS_URL"
echo "DNS_DEV=$DNS_DEV DNS_PROD=$DNS_PROD ACCOUNT=$AWS_ACCOUNT_ID REGION=$AWS_REGION"
```

If any are empty, stop and report.

---

## Execution Instructions

For each phase:

1. **Read** the corresponding content file from the table above
2. **Extract** the commands from the `{{ABSTRACTION_TOOL}}` tab (ignore the other tab)
3. **Execute** the commands, adapting UI steps (like "click Create in Backstage") to their
   CLI/API equivalents using the `backstage-auth.sh` helper for Backstage operations
4. **Verify** the expected outcome described in the content
5. **Report** the phase result (pass/fail) and time taken
6. **If a step fails**, investigate and report — do NOT silently skip

### Backstage API Helper

For phases that say "open Backstage and create...", use the scaffolder API instead:

```bash
source ~/environment/platform-on-eks-workshop/scripts/validation/backstage-auth.sh

# Rust CI/CD (Phase 2)
backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"rust","aws_region":"us-west-2","dockerfile_path":".","deployment_path":"./deployment"}'

# Java CI/CD (Phase 7)
backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"java","aws_region":"us-west-2","dockerfile_path":"./src","deployment_path":"./deployment"}'
```

### Workflow Polling

The workshop says "wait for workflow to finish" with a UI link. Use CLI polling instead:

```bash
# Workflows don't have app=<name> labels — list all in namespace
kubectl get workflows -n <namespace> --sort-by=.metadata.creationTimestamp --no-headers
```

### ArgoCD Sync

The workshop offers kubectl/UI/CLI tabs for syncing. Always use the kubectl approach:

```bash
hub
kubectl patch application <app-name> -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'
```

### Rollout Watching

The workshop says `kubectl argo rollouts get rollout <name> -n <ns> -w`. Since we can't
use `-w` (interactive), poll instead:

```bash
for i in $(seq 1 N); do
  PHASE=$(kubectl get rollout <name> -n <ns> -o jsonpath='{.status.phase}')
  echo "[$i] Phase: $PHASE"
  [ "$PHASE" = "Healthy" ] || [ "$PHASE" = "Degraded" ] && break
  sleep 30
done
```

---

## Summary of Expected Outcomes

| Phase | What                           | Expected Result                              |
|-------|--------------------------------|----------------------------------------------|
| 1     | Next.js frontend               | Pods running, /unicorn responds              |
| 2     | Rust CI/CD via Backstage       | cicdpipeline ACTIVE                          |
| 3     | Rust CI build                  | ECR image exists                             |
| 4     | Rust DEV deploy                | Pods running, /rust-app returns JSON         |
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
