# Validate Workshop — Full End-to-End from Content Files

You are a Kiro agent running on the workshop IDE instance. Your job is to execute the
workshop instructions from the S3 content bucket, following the exact steps a participant
would perform. You validate **every module** from start to finish.

## Primary Goal: Instruction Validation

You are NOT just trying to make things work. You are **auditing the workshop instructions**.

### Rules

1. **Follow instructions literally** — execute every command exactly as written in each content file.
   Do NOT fix, adapt, or work around problems on your own.
2. **Flag instruction issues** — when a command fails, an expected output doesn't match, a step
   is ambiguous, or something is missing, **log it as an issue** instead of silently fixing it.
3. **Propose fixes** — for every issue found, propose a concrete fix (corrected command, missing
   step, better wording) that would make the instruction work for a participant.
4. **Continue after flagging** — after logging an issue and applying your proposed fix locally,
   continue to the next step so you can validate the rest of the module.
5. **Record everything** — for each phase, record: commands run, actual output (trimmed),
   pass/fail status, and any issues found.

### What Counts as an Issue

- A command that fails or produces an error
- An expected output that doesn't match reality (wrong resource name, wrong status, etc.)
- A missing step (e.g., a `cd` or `git pull` that should be there but isn't)
- An ambiguous instruction that a participant could misinterpret
- A wrong file path, resource name, namespace, or label
- An incorrect `sed` pattern that doesn't match the actual file content
- A timing assumption that is too short or too long
- A missing prerequisite or dependency between phases

---

## Configuration

**Abstraction tool**: `{{ABSTRACTION_TOOL}}` — must be set to `kro` or `kubevela` before starting.
**Ask the user for their choice!**

**Language**: Only validate and modify English content files (`.en.md`). French (`.fr.md`) and Chinese (`.zh-CN.md`) translations are maintained separately and should not be edited.

The agent MUST replace `{{ABSTRACTION_TOOL}}` with the user's choice and follow ONLY the
matching tab instructions from the workshop content files when tabs apply. Some parts use
kro independently of the tab selection.

---

## Content Source

Download the content archive from S3 and extract it:

```bash
CONTENT_FILE="content-$(echo $WORKSHOP_GIT_BRANCH | tr '/' '-').tgz"
aws s3 cp "s3://$ASSETS_BUCKET_NAME/${ASSETS_BUCKET_PREFIX}${CONTENT_FILE}" /tmp/
mkdir -p ~/environment/content
tar xzf "/tmp/${CONTENT_FILE}" -C ~/environment/content/
```

Content will be in `~/environment/content/`. All content file paths below are relative to that directory.

---

## Environment

- You are `ec2-user` on the IDE instance.
- Application repos: `~/environment/applications/{rust,java,next-js}`
- Workshop repo: `~/environment/platform-on-eks-workshop`
- Cluster contexts: `peeks-hub`, `peeks-spoke-dev`, `peeks-spoke-prod`
- Aliases: `hub`, `dev`, `prod` (use `kubectl config use-context peeks-{name}` as fallback)

## Credentials

| Service   | Username | Password          |
|-----------|----------|-------------------|
| Backstage | `user1`  | `$USER1_PASSWORD` |
| GitLab    | `user1`  | `$USER1_PASSWORD` |
| ArgoCD    | `admin`  | `$IDE_PASSWORD`   |
| Grafana   | `user1`  | `$USER1_PASSWORD` |

## Required Environment Variables

Env vars are defined in `~/.bashrc.d/platform.sh` and `~/.bashrc.d/aliases.sh`.

```bash
echo "BACKSTAGE=$BACKSTAGE_URL ARGOCD=$ARGOCD_URL WORKFLOWS=$WORKFLOWS_URL"
echo "DNS_DEV=$DNS_DEV DNS_PROD=$DNS_PROD ACCOUNT=$AWS_ACCOUNT_ID REGION=$AWS_REGION"
echo "GITLAB=$GITLAB_URL GRAFANA=$GRAFANA_URL"
```

If any are empty, stop and report.

---

## Content-to-Phase Mapping

### Module 10 — Platform Engineering (exploration, mostly read-only)

| Phase | Content File                                                                                                 | Description                      |
|-------|--------------------------------------------------------------------------------------------------------------|----------------------------------|
| 10.1  | `10_PlatformEngineering/11_PlatformEngineering/001_Section1_IDP_Platform/index.en.md`                        | IDP platform overview            |
| 10.2  | `10_PlatformEngineering/11_PlatformEngineering/002_Section1_EKS_CAPABILITIES/index.en.md`                    | EKS capabilities overview        |
| 10.2a | `10_PlatformEngineering/11_PlatformEngineering/002_Section1_EKS_CAPABILITIES/010-identity-center.md`         | Identity Center login            |
| 10.2b | `10_PlatformEngineering/11_PlatformEngineering/002_Section1_EKS_CAPABILITIES/020-first-login-walkthrough.md` | First login walkthrough          |
| 10.2c | `10_PlatformEngineering/11_PlatformEngineering/002_Section1_EKS_CAPABILITIES/030-kro-and-ack.md`             | KRO and ACK overview             |
| 10.3  | `10_PlatformEngineering/11_PlatformEngineering/003_Section1_Basic_Tools/index.en.md`                         | Basic tools (kubectl, k9s, etc.) |
| 10.4  | `10_PlatformEngineering/11_PlatformEngineering/004_Section1_GitOps_tools/index.en.md`                        | GitOps tools (ArgoCD)            |
| 10.5  | `10_PlatformEngineering/11_PlatformEngineering/005_section1_ProvisionEnvironments/index.en.md`               | Provision environments           |

### Module 10 — ACK & KRO Deep Dive

| Phase | Content File                                                          | Description                          |
|-------|-----------------------------------------------------------------------|--------------------------------------|
| 10.6  | `10_PlatformEngineering/12_ACK_KRO/001_Section3_ACK/index.en.md`      | ACK (AWS Controllers for Kubernetes) |
| 10.7  | `10_PlatformEngineering/12_ACK_KRO/002_Section3_KRO/index.en.md`      | KRO (Kubernetes Resource Operator)   |
| 10.8  | `10_PlatformEngineering/12_ACK_KRO/003_Alternative_Tools/index.en.md` | Alternative tools (kubevela)         |

### Module 10 — GenAI with Platform Engineering (optional)

| Phase | Content File                                                                                | Description                      |
|-------|---------------------------------------------------------------------------------------------|----------------------------------|
| 10.9  | `10_PlatformEngineering/13_GenAIwithPlatformEng/001_Code_Gen_Usecase/index.en.md`           | Code generation use case         |
| 10.10 | `10_PlatformEngineering/13_GenAIwithPlatformEng/002_Q_Backstage_Generation/index.en.md`     | Q Developer Backstage generation |
| 10.11 | `10_PlatformEngineering/13_GenAIwithPlatformEng/003_Q_DDB_Backstage_Deployment/index.en.md` | DDB Backstage deployment         |
| 10.12 | `10_PlatformEngineering/13_GenAIwithPlatformEng/005_Section4_Gitlab_Push/index.en.md`       | GitLab push                      |

### Module 20 — Application Delivery (Rust)

| Phase | Content File                                              | Description                        |
|-------|-----------------------------------------------------------|------------------------------------|
| 20.1  | `20_ApplicationDelivery/01_Rust/01_Intro/index.en.md`     | Intro + manually deploy frontend   |
| 20.2  | `20_ApplicationDelivery/01_Rust/02_Backstage/index.en.md` | Provision Rust CI/CD via Backstage |
| 20.3  | `20_ApplicationDelivery/01_Rust/03_CI/index.en.md`        | Wait for CI workflows              |
| 20.4  | `20_ApplicationDelivery/01_Rust/04_CD/index.en.md`        | Deploy to DEV + promote to PROD    |

### Module 20 — Rust Feature Development (optional)

| Phase | Content File                                                   | Description                 |
|-------|----------------------------------------------------------------|-----------------------------|
| 20.5  | `20_ApplicationDelivery/01_Rust/feature-dev-rust.en.md`        | Feature development on Rust |
| 20.6  | `20_ApplicationDelivery/01_Rust/feature-dev-deploy-rust.en.md` | Deploy Rust feature branch  |

### Module 30 — Progressive Application Delivery

| Phase | Content File                                                                      | Description                             |
|-------|-----------------------------------------------------------------------------------|-----------------------------------------|
| 30.1  | `30_ProgressiveApplicationDelivery/10_progressive-delivery/index.en.md`           | Progressive delivery demo (blue→yellow) |
| 30.2  | `30_ProgressiveApplicationDelivery/20_create-cicd/index.en.md`                    | Java CI/CD via Backstage + build        |
| 30.3  | `30_ProgressiveApplicationDelivery/30_function-performance-test-java/index.en.md` | Functional & performance gate tests     |
| 30.4  | `30_ProgressiveApplicationDelivery/40_production-deploy-kargo/index.en.md`        | Production deploy with Kargo            |
| 30.5  | `30_ProgressiveApplicationDelivery/50_metrics-driven-decisions/index.en.md`       | Metrics-driven decisions (Rust)         |
| 30.6  | `30_ProgressiveApplicationDelivery/60_measuring_platform_success/index.en.md`     | Measuring platform success intro        |

### Module 40 — AI/ML Delivery (optional)

| Phase | Content File                                                            | Description                    |
|-------|-------------------------------------------------------------------------|--------------------------------|
| 40.1  | `40_AIMLDelivery/41_Platform Engineering_for_AIML_Delivery/index.en.md` | Platform engineering for AI/ML |
| 40.2  | `40_AIMLDelivery/42_Using_Platform_to_build_Models/index.en.md`         | Using platform to build models |
| 40.3  | `40_AIMLDelivery/43_ML_Model_Use_Case/index.en.md`                      | ML model use case              |
| 40.4  | `40_AIMLDelivery/44_Using_Platform_for_Data_Engineering/index.en.md`    | Data engineering with Airflow  |

### Module 70 — Measuring Platform Success / DORA Metrics (optional)

| Phase | Content File                                                                              | Description                   |
|-------|-------------------------------------------------------------------------------------------|-------------------------------|
| 70.1  | `70_MeasuringPlatformSuccess/71_DORAOnboarding/index.en.md`                               | DORA onboarding intro         |
| 70.1a | `70_MeasuringPlatformSuccess/71_DORAOnboarding/devlake.en.md`                             | DevLake setup                 |
| 70.2  | `70_MeasuringPlatformSuccess/72_DeploymentFrequency/index.en.md`                          | Deployment frequency theory   |
| 70.2a | `70_MeasuringPlatformSuccess/72_DeploymentFrequency/001_Section2_DF_Practice/index.en.md` | Deployment frequency practice |
| 70.3  | `70_MeasuringPlatformSuccess/73_ChangeFailureRate/index.en.md`                            | Change failure rate theory    |
| 70.3a | `70_MeasuringPlatformSuccess/73_ChangeFailureRate/001_Section3_FR_Practice/index.en.md`   | Change failure rate practice  |
| 70.4  | `70_MeasuringPlatformSuccess/74_RecoveryTime/index.en.md`                                 | Recovery time theory          |
| 70.4a | `70_MeasuringPlatformSuccess/74_RecoveryTime/001_Section4_RT_Practice/index.en.md`        | Recovery time practice        |
| 70.5  | `70_MeasuringPlatformSuccess/75_LeadTimeForChanges/index.en.md`                           | Lead time for changes theory  |
| 70.5a | `70_MeasuringPlatformSuccess/75_LeadTimeForChanges/001_Section5_LTC_Practice/index.en.md` | Lead time practice            |

---

## Execution Instructions

### Timing

Track the wall-clock time for every phase. Record start and end timestamps:

```bash
echo "⏱️ Phase X.Y START: $(date +%H:%M)"
# ... execute phase ...
echo "⏱️ Phase X.Y END: $(date +%H:%M)"
```

Format durations as `1h15mn`, `45mn`, or `3mn`. Use these thresholds to flag slow phases:

| Module type              | Expected max | Flag as ⏰ SLOW if exceeds |
|--------------------------|-------------|---------------------------|
| Read-only / exploration  | 5mn         | 10mn                      |
| CLI commands only        | 10mn        | 15mn                      |
| Backstage + CI build     | 15mn        | 25mn                      |
| Full deploy + promote    | 20mn        | 30mn                      |
| Progressive rollout      | 15mn        | 25mn                      |

Phases flagged as slow should be investigated — the cause is usually a wait loop polling too long, a pod stuck in pending, or an instruction that requires a manual workaround.

For each phase:

1. **Read** the corresponding content file from the mapping table above
2. **Extract** the commands from the `{{ABSTRACTION_TOOL}}` tab (ignore the other tab)
3. **Execute** the commands, adapting UI steps (like "click Create in Backstage") to their
   CLI/API equivalents using the helpers below
4. **Verify** the expected outcome described in the content
5. **Report** the phase result (pass/fail), time taken, and any issues
6. **If a step fails**, log the issue, apply your proposed fix, and continue

### Backstage API Helper

For phases that say "open Backstage and create...", use the scaffolder API:

```bash
source ~/environment/platform-on-eks-workshop/scripts/validation/backstage-auth.sh

# Rust CI/CD (Phase 20.2)
backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"rust","aws_region":"us-west-2","dockerfile_path":".","deployment_path":"./deployment"}'

# Java CI/CD (Phase 30.2)
backstage_scaffolder "template:default/cicd-pipeline-gitops" \
  '{"appname":"java","aws_region":"us-west-2","dockerfile_path":"./src","deployment_path":"./deployment"}'
```

### Workflow Polling

The workshop says "wait for workflow to finish" with a UI link. Use CLI polling:

```bash
kubectl get workflows -n <namespace> --sort-by=.metadata.creationTimestamp --no-headers
```

**IMPORTANT: Only wait for the workflow that matters.** Workflows prefixed with `dora-deploy`
or `dora-setup` are DORA metrics side-effects — they are **never blocking** for workshop
progress. When waiting for a CI build, poll only the specific `cicd-cicd-*` or
`setup-workflow` by name:

```bash
# Wait for the CI build only — ignore dora-* workflows
for i in $(seq 1 20); do
  LATEST=$(kubectl get workflows -n <ns> --sort-by=.metadata.creationTimestamp --no-headers \
    -o custom-columns=NAME:.metadata.name,PHASE:.status.phase | grep "cicd-cicd" | tail -1)
  echo "[$i] $LATEST"
  echo "$LATEST" | grep -q "Succeeded" && echo "CI DONE" && break
  echo "$LATEST" | grep -q "Failed" && echo "CI FAILED" && break
  sleep 30
done
```

Do NOT wait for all workflows to finish — that wastes time on non-blocking dora workflows.

### Shell Environment Setup

Helper functions (`argocd-sync`, `argocd-refresh-token`, `trigger-devlake`) are defined in
`~/.bashrc.d/ssm-setup-ide-logs.sh` but may not be loaded in non-interactive shells.
**Always source it at the start of the validation run:**

```bash
source ~/.bashrc.d/ssm-setup-ide-logs.sh
```

### ArgoCD Sync

Prefer argocd CLI, fallback to kubectl if auth errors:

```bash
# CLI
argocd app sync <app-name>
```

If CLI auth fails, run `argocd-refresh-token` then `source ~/.bashrc.d/platform.sh`.

```bash
# kubectl fallback
hub
kubectl patch application <app-name> -n argocd --type merge \
  -p '{"operation": {"initiatedBy": {"username": "admin"}, "sync": {"revision": "HEAD"}}}'
```

### Backstage Scaffolder Failures

If a Backstage scaffolder task fails with a 401 Unauthorized on the `kube:apply` step,
the Backstage pod's service account token may be stale. Restart the pod:

```bash
hub
kubectl rollout restart deployment backstage -n backstage
kubectl rollout status deployment backstage -n backstage --timeout=120s
sleep 15
```

Then re-source `backstage-auth.sh` and retry with a **new unique name** (the previous
GitLab repo may already exist from the partial run).

### Kiro AI Generation Exercises

Some phases ask the participant to "open Kiro and create a chat session" to generate manifests.
Since you **are already running as a Kiro agent** in a `kiro-cli chat` session, you do NOT need
to open a new session or log in. Instead:

1. **Execute the exercise directly** — read the prompt from the content, check the relevant
   Kubernetes schemas (ComponentDefinitions, TraitDefinitions, ResourceGraphDefinitions), and
   generate the requested manifest file.
2. **Run the diff commands** shown in the content to compare your generated manifest against
   the workshop reference.
3. **Report** any differences as part of the phase validation.

Do NOT skip these exercises — they validate that the schemas and prompts produce correct output.

### Kargo UI Promotions

Kargo promotions are designed for the UI. The IDE IAM role cannot create Promotion
resources directly. Use service account impersonation:

```bash
FREIGHT=$(kubectl get freight -n <project-ns> -o jsonpath='{.items[0].metadata.name}')
kubectl -n <project-ns> create --as=system:serviceaccount:kargo:kargo-admin -f - <<EOF
apiVersion: kargo.akuity.io/v1alpha1
kind: Promotion
metadata:
  name: prod-manual
  namespace: <project-ns>
spec:
  stage: prod
  freight: $FREIGHT
  steps:
  - task:
      name: update-image
EOF
```

### Rollout Watching

The workshop uses `kubectl argo rollouts get rollout <name> -n <ns> -w`. Since we can't
use `-w` (interactive), **always discover the rollout name first** then poll:

```bash
# Step 1: Discover the actual rollout name (never guess)
kubectl get rollouts -n <ns> --no-headers

# Step 2: Poll using the discovered name
ROLLOUT_NAME=$(kubectl get rollouts -n <ns> --no-headers -o custom-columns=NAME:.metadata.name | head -1)
for i in $(seq 1 20); do
  PHASE=$(kubectl get rollout $ROLLOUT_NAME -n <ns> -o jsonpath='{.status.phase}')
  echo "[$i] Phase: $PHASE"
  [ "$PHASE" = "Healthy" ] || [ "$PHASE" = "Degraded" ] && break
  sleep 15
done
```

### Polling Safety Rule

When polling for a resource status, if the first iteration returns an **empty result**,
immediately stop and investigate (wrong name, wrong namespace, resource not yet created).
Do NOT continue polling with empty results — that wastes time.

### Module 10 — Exploration Phases

Module 10 is mostly exploration and read-only. For these phases:
- Execute any `kubectl` commands shown in the content
- Verify URLs are accessible (Backstage, ArgoCD, GitLab, Grafana)
- For Identity Center login (10.2a), verify the login flow works with `user1` credentials
- For GenAI phases (10.9-10.12), these require Q Developer — flag if not available and skip

### Module 40 — AI/ML Phases

Module 40 requires JupyterHub, MLflow, and Airflow. These may not be deployed in all environments.
Check if the addons are available before starting:

```bash
hub
kubectl get applications -n argocd | grep -E "jupyterhub|mlflow|airflow|ray|spark"
```

If not deployed, skip the affected phases and note it in the report.

For phases that use Backstage templates (e.g., Ray model serving), use the `backstage_scaffolder`
helper just like for CI/CD pipelines — do NOT skip phases just because they mention a UI.
Read the content file, find the template name and parameters, and call the scaffolder API.

For phases that require interactive notebooks (JupyterHub), execute any CLI commands shown
in the content and verify the infrastructure is accessible. Flag notebook-only steps as
"requires interactive session" but still validate everything around them.

**Ray model warmup**: After Ray pods show `Running`, the model still needs time to load
into memory — from ~1 minute for small models (TinyLlama) up to many minutes for larger
ones (Mistral-7B, etc.). If the inference endpoint returns an empty `generated_text`,
keep retrying every 30s. Do NOT flag this as a failure on empty responses during warmup.

### Module 70 — DORA Metrics Phases

Module 70 requires DevLake. Check availability:

```bash
hub
kubectl get applications -n argocd | grep devlake
```

If not deployed, skip module 70 and note it in the report.

---

## Summary of Expected Outcomes

| Phase | What                            | Expected Result                                     |
|-------|---------------------------------|-----------------------------------------------------|
| 10.x  | Platform exploration            | URLs accessible, kubectl commands work              |
| 20.1  | Next.js frontend                | Pods running, /unicorn responds                     |
| 20.2  | Rust CI/CD via Backstage        | cicdpipeline ACTIVE                                 |
| 20.3  | Rust CI build                   | ECR image exists                                    |
| 20.4  | Rust DEV deploy + PROD promote  | Pods running, /rust-app returns JSON, prod synced   |
| 30.1  | Progressive demo (blue→yellow)  | Canary rollout completes                            |
| 30.2  | Java CI/CD + build              | cicdpipeline ACTIVE, ECR image in manifest          |
| 30.3  | Functional/performance gates    | Gate failure then fix, rollout healthy              |
| 30.4  | Kargo production deploy         | Kargo freight promoted to prod                      |
| 30.5  | Metrics-driven decisions (Rust) | Rollout with metrics passes, then fails with delay  |
| 30.6  | Measuring success               | Read-only exploration                               |
| 40.x  | AI/ML delivery                  | JupyterHub/MLflow/Airflow accessible and functional |
| 70.x  | DORA metrics                    | DevLake configured, metrics visible                 |

---

## Final Output — Validation Report

After completing all phases, produce a **Validation Report** with this structure:

### 1. Phase Results Table

| Phase | Name                  | Status                    | Duration | Timing  | Notes      |
|-------|-----------------------|---------------------------|----------|---------|------------|
| 10.1  | IDP Platform overview | ✅ PASS / ❌ FAIL / ⏭️ SKIP | 3mn      | ✅ / ⏰  | brief note |
| ...   | ...                   | ...                       | ...      | ...     | ...        |
| **—** | **TOTAL**             |                           | **2h30mn** |       |            |

Duration format: `1h15mn`, `45mn`, `3mn`. Flag with ⏰ if the phase exceeded its expected max (see timing thresholds above).

### 2. Instruction Issues Found

For each issue:

```
#### Issue #N — [Phase X] Short title

**Severity**: 🔴 Blocker / 🟡 Wrong output / 🟢 Minor / 🔵 Improvement

**What the instruction says**:
> (quote the exact instruction text)

**What actually happened**:
(describe the actual behavior or error)

**Root cause**:
(why the instruction is wrong)

**Proposed fix**:
(the corrected instruction text or additional step)
```

Severity definitions:
- 🔴 **Blocker** — instruction cannot work as written, participant is stuck
- 🟡 **Wrong output** — command works but output doesn't match documentation
- 🟢 **Minor** — cosmetic or confusing but participant can figure it out
- 🔵 **Improvement** — instruction works but could be clearer or more robust

### 3. Summary Statistics

```
Total phases: X
Passed: X
Failed: X
Skipped: X
Issues found: X (🔴 N blockers, 🟡 N wrong output, 🟢 N minor, 🔵 N improvements)

Timing:
  Total duration: 2h30mn
  Phases on time: X
  Phases slow (⏰): X
  Slowest phase: X.Y (45mn) — reason
```

### 4. Slow Phases Analysis

For each phase flagged ⏰:

```
#### ⏰ Phase X.Y — Name (actual: 45mn, expected max: 15mn)

**Time spent on**: what consumed the time (polling, pod startup, retry, workaround)
**Root cause**: why it was slow (image pull, resource quota, broken instruction, etc.)
**Recommendation**: how to reduce time (fix instruction, increase timeout, pre-pull image, etc.)
```

### 5. Recommended Changes

List the content files that need updates and the specific changes, grouped by file.
