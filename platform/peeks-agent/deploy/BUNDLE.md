# PEEKS read-only agent — single-bundle deploy

Deploys the **entire** PEEKS chat agent stack as **one KubeVela Application**
(`peeks-agent-app.yaml`). One `kubectl apply` recreates everything that was
built live during the demo, so nothing depends on hand-authored objects anymore.

## What the single Application contains

| Component | Type | Renders |
|---|---|---|
| `skills-mcp` | `mcp-server` (OAM) | skills MCP rollout + svc + HTTPRoute + AgentgatewayBackend |
| `peeks-agent` | `agent-fixed` (OAM) | agent rollout + svc + HTTPRoute + backend + agent-card + SA + **Pod Identity role** (trait `aws-service-identity`) |
| `eks-read-mcp` | `k8s-objects` | SA-less Deployment (reuses agent SA) + Service + HTTPRoute + AgentgatewayBackend |
| `chat-ui` | `k8s-objects` | Deployment (image bakes `app.py` + `static/`) + Service + Ingress (class `platform`). Branding is env-driven (`APP_TITLE`/`AGENT_LABEL`/`APP_INTRO`) — **no ConfigMap** |
| `agent-access` | `k8s-objects` | 3 ACK `AccessEntry` (hub + spoke-dev + spoke-prod) granting `peeks-agent-role` read-only RBAC (`AmazonEKSViewPolicy` + `AmazonEKSAdminViewPolicy`) |

> The chat-ui **image bakes** `app.py` + `static/index.html` (built from
> `src/a2a-chat-ui`). The exact working UI (markdown + GFM tables, colored
> rendering, history persistence, async job/poll) ships in the image — a single
> source of truth, no ConfigMap override to drift from.

### Identity design (why it is self-contained)

- The **agent** gets its IAM role + hub Pod Identity association from the
  `aws-service-identity` trait (rendered *inside* the Application, via Crossplane).
- **`eks-read-mcp` reuses the agent ServiceAccount `peeks-agent`** (see
  `serviceAccountName: peeks-agent` in its Deployment) so it inherits that same
  Pod Identity role — **no extra AWS PodIdentityAssociation to create**. This is
  the one deliberate change vs the live setup (which used a separate SA + its own
  association).

## Prerequisites (NOT in the bundle — platform/AWS-side, set once per env)

1. **OAP platform addons on the hub** — the hub cluster secret must carry the
   labels `enable_bifrost=true`, `enable_agent_gateway=true`,
   `enable_oam_components=true`. These install Bifrost, the AgentGateway, and the
   OAM ComponentDefinitions this bundle needs (`agent-fixed`, `mcp-server`,
   `k8s-objects`).
2. **AgentGateway addon on the PR #21 fork branch** — `agent-platform-addons`
   `valuesObject.repoURLGit` / `repoURLGitRevision` must point at the fork branch
   `fix/agentgateway-agents-empty-host-guard`. Without it the `agentgateway-agents`
   ingress renders HTTPS:443 **without a cert** and **poisons the shared `platform`
   ALB group** (the whole group stops reconciling → the chat ingress never gets an
   address).
3. **`jwt-auth-policy` (agentgateway-system)** with the **workload-identity**
   provider (issuer = hub OIDC `https://oidc.eks.<region>.amazonaws.com/id/<id>`,
   audience `agentgateway`, authz `jwt.sub.startsWith("system:serviceaccount:")`).
   Present on the hub by default; required so the agent's MCP calls through the
   gateway are not 401'd.
4. **Container images in ECR** (pin real tags, not `:latest`, for a stable demo):
   - `…/peeks-e2e/chat-ui`
   - `…/peeks-e2e/eks-mcp` (awslabs eks-mcp-server, started **read-only**:
     `--allow-sensitive-data-access --auth-mode iam`, **no** `--allow-write`)
   - the skills-mcp image (must be the **stateless** FastMCP build)
5. **ACK EKS controller must manage the target clusters** — the `agent-access`
   component creates 3 ACK `AccessEntry` objects (hub + both spokes) that grant
   `peeks-agent-role` read-only RBAC (`AmazonEKSViewPolicy` +
   `AmazonEKSAdminViewPolicy`, which covers CRDs like `applications.argoproj.io`/
   `kro.run` and `nodes`). This works because the platform's ACK EKS controller
   already manages the spokes (same account/region → default CARM); the entries can
   live in the `peeks-agent` namespace. No manual `aws eks` call is needed anymore.
   The role itself (`peeks-agent-role`) is created by the `aws-service-identity`
   trait; ACK retries the AccessEntry until the role exists. Read-only: no write
   policy is attached anywhere.

## Parameters to set per environment

Three placeholders must be substituted before applying:

```bash
CF=d2pefdj59hxapj.cloudfront.net   # this env's CloudFront domain (Keycloak token URL)
ACCT=290085271972                  # this env's AWS account ID (AccessEntry principalARN)
PREFIX=peeks-e2e                   # this env's cluster name prefix (<prefix>-hub / -spoke-dev / -spoke-prod)
REG=$ACCT.dkr.ecr.us-west-2.amazonaws.com/$PREFIX   # ECR registry+repo prefix for the images
TAG=<git-sha>                      # the pinned tag pushed by buildspec.yaml (NOT :latest)
# incident bridge only — AMP workspace ID. NOT in the cluster-secret (which only carries
# aws_grafana_url), but retrievable in-cluster from the Crossplane Workspace CR
# (name is deterministic: <prefix>-amp). Fallback to the AMP API by alias.
AMPWS=$(kubectl get workspace.amp.aws.upbound.io ${PREFIX}-amp \
          -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}' 2>/dev/null)
AMPWS=${AMPWS:-$(aws amp list-workspaces --alias ${PREFIX}-observability-amp \
          --query 'workspaces[0].workspaceId' --output text)}

sed -i "s#REPLACE_IMAGE_REGISTRY#${REG}#g; s/REPLACE_IMAGE_TAG/${TAG}/g; \
        s/REPLACE_CLOUDFRONT_DOMAIN/${CF}/g; s/REPLACE_ACCOUNT_ID/${ACCT}/g; \
        s/REPLACE_CLUSTER_PREFIX/${PREFIX}/g; s/REPLACE_AMP_WORKSPACE_ID/${AMPWS}/g" peeks-agent-app.yaml
```

> Placeholders in the manifest: `REPLACE_IMAGE_REGISTRY` + `REPLACE_IMAGE_TAG` (4 image
> refs incl. `incident-bridge`), `REPLACE_CLOUDFRONT_DOMAIN` (chat-ui Keycloak URL),
> `REPLACE_ACCOUNT_ID` + `REPLACE_CLUSTER_PREFIX` (3 ACK AccessEntry + the incident-bridge
> ARNs/PodIdentity), and `REPLACE_AMP_WORKSPACE_ID` (AMP AlertManager target workspace —
> incident bridge only). Images are **pinned** to `$TAG`, never `:latest`.

### Autonomous incident bridge (components `incident-bridge-selectors` + `incident-bridge-aws` + `incident-bridge`)
Optional. Wires the AMP-based autonomous-remediation loop, all in ACK (no Crossplane
provider changes; sns/sqs/iam/eks/prometheusservice controllers are on the hub):

```
AMP OOMKill alerting rule (observability-aws chart, amp.alerting.enabled)
  └─> AlertManagerDefinition (ACK) → SNS Topic (ACK)
        └─> Subscription (ACK, raw) → SQS Queue (ACK)
              └─> incident-bridge Deployment (SA incident-bridge, Pod Identity, SQS read)
                    long-polls SQS → POST agent A2A in-cluster (nothing exposed)
```

**CARM prerequisite (component `incident-bridge-selectors`, applied FIRST).**
The **managed** ACK capability does not use the classic CARM ConfigMap — it routes a
CR to a workload IAM role via a cluster-scoped **`IAMRoleSelector`** matching the CR's
namespace. With no match it falls back to the capability role, which only holds
`AssumeWorkloadRoles` + `ManageIRSARoles` and therefore **cannot** create SNS/SQS/AMP
resources (→ `AuthorizationError: not authorized to perform SNS:CreateTopic`). The
bundle ships two selectors for ns `peeks-agent`:
  - **`incident-bridge-iam`** → `<prefix>-cluster-mgmt-iam` (has `IAMFullAccess`, already
    trusted by the capability). Lets ACK create the two IAM roles declaratively —
    **no direct `aws iam` call**.
  - **`incident-bridge-aws`** → `<prefix>-cluster-mgmt-incident-bridge` (the provisioning
    role, created by ACK, armed with scoped SNS/SQS/aps perms). Named `cluster-mgmt-*`
    so the capability's `AssumeWorkloadRoles` (Resource `<prefix>-cluster-mgmt-*`) permits
    `sts:AssumeRole` on it.

> ⚠️ **Ordering matters (learned live).** The managed capability caches "no role selected"
> for a CR and does **not** re-evaluate a selector added *after* the CR's first reconcile
> (there is no controller pod to restart). Hence `incident-bridge-aws` **`dependsOn`
> `incident-bridge-selectors`**, and `incident-bridge` **`dependsOn` `incident-bridge-aws`**.
> On an existing cluster where the AWS CRs were applied before the selectors, force a fresh
> selection with: `kubectl -n peeks-agent delete topic/queue/subscription/alertmanagerdefinition … && kubectl apply`.

Prereqs: (1) the `observability-aws` chart with `amp.alerting.enabled=true` (adds the
`PodOOMKilled` rule); (2) the `incident-bridge` image built+pushed by `buildspec.yaml`;
(3) `REPLACE_AMP_WORKSPACE_ID` substituted. To omit the bridge, delete the three
`incident-bridge*` components before applying.

## Apply

```bash
kubectl -n peeks-agent apply -f peeks-agent-app.yaml
# KubeVela renders all 4 components. Watch:
kubectl -n peeks-agent get application peeks-agent-hub
kubectl -n peeks-agent get rollout,deploy,svc,ingress,cm
```

Chat URL (gated by Keycloak `user1`): `https://<CLOUDFRONT_DOMAIN>/peeks-agent-chat`.

## Ordering gotcha (MCP tools load once at boot)

The Strands agent loads its MCP tools **only once at startup**. If the agent pod
starts before `eks-read-mcp`/`skills-mcp` are ready, it drops those tools for its
whole life. After a fresh apply, if the chat says *"unable to connect to my
tools"*, **restart the agent** once the MCP pods are Running:

```bash
kubectl -n peeks-agent rollout restart rollout/peeks-agent
```

## MCP transport rules (why the two servers differ)

- **skills-mcp = FastMCP → must be STATELESS** (`stateless_http=True`,
  `json_response=True`). Each POST is self-contained; no persistent SSE stream for
  the L7 gateway to cut.
- **eks-read-mcp = supergateway wrapping a stdio server → must be STATEFUL**
  (`--stateful` + backend `sessionRouting: Stateful`). Stateless would spawn a new
  process per request that never received `initialize` → `tools/list` fails.

## Notes / next hardening

- Component `peeks-agent` uses the **`agent-fixed`** ComponentDefinition (the test
  CD carrying the CUE `list.Concat` fix). Switch to the stock `agent` CD once
  OAP PR #19 is merged and available on the platform.
- Access entries are now **in the bundle** as ACK `AccessEntry` resources
  (component `agent-access`), so the only truly out-of-bundle bits are the
  platform prerequisites (#1–#3) and the ECR images (#4).
