# Validate Workshop — GenAI & Agentic AI Sections (40.5 + 40.6)

You are a Kiro agent running on the workshop IDE instance. Your job is to execute the
workshop instructions for the **GenAI and Agentic AI sections only**, following the exact
steps a participant would perform.

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
- A missing step (e.g., a `cd` or `pip install` that should be there but isn't)
- An ambiguous instruction that a participant could misinterpret
- A wrong file path, resource name, namespace, or label
- A timing assumption that is too short or too long
- A missing prerequisite or dependency between phases

---

## Content Source

Download the content archive from S3 and extract it:

```bash
aws s3 cp s3://$ASSETS_BUCKET_NAME/$ASSETS_BUCKET_PREFIX/content-$WORKSHOP_GIT_BRANCH.tgz /tmp/
mkdir -p ~/environment/content
tar xzf /tmp/content-$WORKSHOP_GIT_BRANCH.tgz -C ~/environment/content/
```

Content will be in `~/environment/content/`. All content file paths below are relative to that directory.

---

## Environment

- You are `ec2-user` on the IDE instance.
- Cluster contexts: `peeks-hub`, `peeks-spoke-dev`, `peeks-spoke-prod`
- Aliases: `hub`, `dev`, `prod`

## Credentials

| Service    | Username | Password          |
|------------|----------|-------------------|
| JupyterHub | `user1`  | `$USER1_PASSWORD` |
| Backstage  | `user1`  | `$USER1_PASSWORD` |
| ArgoCD     | `admin`  | `$IDE_PASSWORD`   |

## Required Environment Variables

```bash
source ~/.bashrc.d/platform.sh
source ~/.bashrc.d/aliases.sh
echo "JUPYTERHUB=$JUPYTERHUB_URL BACKSTAGE=$BACKSTAGE_URL REGION=$AWS_REGION"
```

If any are empty, stop and report.

---

## Pre-flight Checks

Before starting the sections, verify the GenAI addons are deployed:

```bash
hub
echo "=== GenAI Addon Pods ==="
kubectl get pods -n litellm 2>/dev/null || echo "litellm: NOT DEPLOYED"
kubectl get pods -n langfuse 2>/dev/null || echo "langfuse: NOT DEPLOYED"
kubectl get pods -n qdrant 2>/dev/null || echo "qdrant: NOT DEPLOYED"
kubectl get pods -n mlflow 2>/dev/null || echo "mlflow: NOT DEPLOYED"
kubectl get pods -n keda 2>/dev/null || echo "keda: NOT DEPLOYED"

echo "=== ArgoCD App Health ==="
kubectl get applications -n argocd | grep -E "litellm|langfuse|qdrant|mlflow|keda"

echo "=== Bedrock Access ==="
aws bedrock list-inference-profiles --region $AWS_REGION \
  --query 'inferenceProfileSummaries[?contains(inferenceProfileId,`claude`)].inferenceProfileId' \
  --output text | head -3

echo "=== JupyterHub ==="
kubectl get pods -n jupyterhub -l component=singleuser-server 2>/dev/null | head -3
```

If LiteLLM, Langfuse, or Qdrant are NOT DEPLOYED, **stop and report** — the GenAI addons
need to be enabled in hub-config.yaml first.

---

## Content-to-Phase Mapping

### Section 5: Agentic AI with CrewAI (40.5)

| Phase | Content File | Description |
|-------|-------------|-------------|
| 40.5 | `40_AIMLDelivery/45_Agentic_AI_with_CrewAI/index.en.md` | Full CrewAI section |

**Sub-steps to validate:**

| Step | What to Validate | Expected |
|------|-----------------|----------|
| 40.5.1 | Open JupyterHub, login with user1 | JupyterHub UI accessible |
| 40.5.2 | `pip install crewai crewai-tools boto3` | Installs without errors |
| 40.5.3 | Configure Bedrock LLM, test call | Response from Claude |
| 40.5.4 | Define 3 agents (Analyst, Security, Writer) | No errors |
| 40.5.5 | Define 3 tasks with cluster_info | No errors |
| 40.5.6 | Run `crew.kickoff()` | Markdown report generated with all 3 agent contributions |
| 40.5.7 | Extending examples (optional) | Verify code snippets are syntactically correct |

**JupyterHub validation approach:**
Since you can't interact with the JupyterHub UI directly, validate by:
1. Checking JupyterHub is accessible: `curl -s $JUPYTERHUB_URL/hub/health`
2. Running the Python code in a standalone script on the IDE:
   ```bash
   pip install crewai crewai-tools boto3
   python3 << 'EOF'
   # Paste the notebook code here and run it
   EOF
   ```
3. If the code requires JupyterHub-specific features (IRSA), test with the IDE's own credentials

### Section 6: GenAI Stack — RAG Pipeline (40.6)

| Phase | Content File | Description |
|-------|-------------|-------------|
| 40.6 | `40_AIMLDelivery/46_GenAI_Stack_RAG_Pipeline/index.en.md` | Full RAG pipeline section |

**Sub-steps to validate:**

| Step | What to Validate | Expected |
|------|-----------------|----------|
| 40.6.1 | Verify GenAI stack pods | litellm, langfuse, qdrant, mlflow all Running |
| 40.6.2 | LiteLLM health + model list | `healthy`, Bedrock models listed |
| 40.6.3 | LiteLLM test completion via OpenAI SDK | Response from Claude via LiteLLM |
| 40.6.4 | Install qdrant-client, create collection | Collection created in Qdrant |
| 40.6.5 | Embed docs with Titan, upsert to Qdrant | N documents ingested |
| 40.6.6 | RAG query: retrieve + generate | Answer grounded in retrieved docs |
| 40.6.7 | Multiple RAG queries | All return relevant answers with sources |
| 40.6.8 | Langfuse traces visible | Traces appear (check via API if UI not accessible) |
| 40.6.9 | Argo CronWorkflow (optional) | CronWorkflow created successfully |

**Service access from IDE:**
The GenAI services are ClusterIP. Use port-forward or kubectl exec:

```bash
# LiteLLM
kubectl port-forward svc/litellm 4000:4000 -n litellm &
export LITELLM_URL="http://localhost:4000"

# Qdrant
kubectl port-forward svc/qdrant 6333:6333 -n qdrant &
export QDRANT_URL="http://localhost:6333"

# Langfuse
kubectl port-forward svc/langfuse 3000:3000 -n langfuse &
export LANGFUSE_URL="http://localhost:3000"
```

Then run the Python code from the content file as a standalone script.

---

## Execution Instructions

For each phase:

1. **Read** the corresponding content file
2. **Extract** all commands and code blocks
3. **Execute** them in order, using port-forwards for ClusterIP services
4. **Verify** the expected outcome
5. **Report** pass/fail and any issues
6. **If a step fails**, log the issue, apply your proposed fix, and continue

---

## Final Output — Validation Report

After completing all phases, produce a **Validation Report**:

### 1. Phase Results Table

| Phase  | Name                    | Status                    | Duration | Notes      |
|--------|-------------------------|---------------------------|----------|------------|
| 40.5.1 | JupyterHub access       | ✅ PASS / ❌ FAIL / ⏭️ SKIP | ~Xs      | brief note |
| 40.5.2 | CrewAI install          | ...                       | ...      | ...        |
| ...    | ...                     | ...                       | ...      | ...        |

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

### 3. Summary Statistics

```
Total phases: X
Passed: X
Failed: X
Skipped: X
Issues found: X (🔴 N blockers, 🟡 N wrong output, 🟢 N minor, 🔵 N improvements)
Total duration: X min
```

### 4. Recommended Changes

List the content files that need updates and the specific changes.
