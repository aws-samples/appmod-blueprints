---
name: troubleshoot-platform
description: Systematic troubleshooting for the PEEKS workshop platform — EKS clusters, Terraform state, ingress, load balancers, MCP tool failures, YAML validation. Use when something is broken, not deploying, or behaving unexpectedly. Also covers resource deletion safety. Do NOT use for KRO-specific issues — use troubleshoot-kro instead. Do NOT use for addon configuration — use manage-addons instead.
---

# Troubleshoot Platform

## Overview

Systematic troubleshooting methodology for the workshop environment. Prioritizes investigation over immediate fixes and enforces safety gates on destructive operations.

## Parameters

- **symptom** (required): Description of what's broken or unexpected
- **component** (optional): "eks", "terraform", "ingress", "argocd", "mcp", or "general"

## Workflow

### 1. Verify the Problem Exists

**Constraints:**
- You MUST verify the actual problem exists before starting troubleshooting because symptoms may be transient
- You MUST validate YAML syntax after modifying any YAML file: `yq eval '.' <file> > /dev/null` for config files, `kubectl apply --dry-run=client -f <file>` for K8s manifests
- You MUST search EKS troubleshooting guide and documentation with 3-4 different query variations using EKS MCP tools before attempting fixes because the answer is usually documented

### 2. Investigate Systematically

**For ArgoCD issues (ALWAYS check first):**

Before any other investigation, check for stuck ArgoCD state:

```bash
# Check for apps stuck in Deleting state
kubectl get applications.argoproj.io -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" del="}{.metadata.deletionTimestamp}{"\n"}{end}' | grep "del=2"

# Check for stuck operations (Running > 5 min)
kubectl get applications.argoproj.io -n argocd -o json | jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.items[] | select(.status.operationState.phase == "Running" and ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)) | .metadata.name'

# Check for ComparisonError (git cache stale)
kubectl get applications.argoproj.io -n argocd -o json | jq -r '.items[] | select(.status.operationState.message // "" | contains("ComparisonError")) | .metadata.name + ": " + .status.operationState.message'
```

**Recovery procedures:**

1. **Stuck operations (Running > 5 min):** Terminate and re-trigger
   ```bash
   kubectl patch applications.argoproj.io <app> -n argocd --type merge -p '{"status":{"operationState":null}}'
   kubectl annotate applications.argoproj.io <app> -n argocd argocd.argoproj.io/refresh=hard --overwrite
   ```

2. **Apps stuck Deleting:** The EKS ArgoCD Capability controller re-adds finalizers. You cannot force-delete while the controller is running. Options:
   - Wait for the controller to complete cleanup (may take 5-10 min)
   - If the target cluster no longer exists, delete the cluster secret so the controller stops trying:
     ```bash
     kubectl delete secret <cluster-name> -n argocd
     ```
   - For apps targeting the hub itself: the controller will eventually succeed once it confirms resources are gone

3. **Git cache stale ("app path does not exist"):** The EKS ArgoCD Capability caches git repos. Force refresh:
   ```bash
   kubectl annotate applications.argoproj.io <app> -n argocd argocd.argoproj.io/refresh=hard --overwrite
   ```
   If that doesn't work, delete and let the ApplicationSet recreate:
   ```bash
   kubectl patch applications.argoproj.io <app> -n argocd --type merge -p '{"metadata":{"finalizers":[]}}'
   kubectl delete applications.argoproj.io <app> -n argocd --wait=false
   ```

4. **All apps disappeared (ExternalSecret flicker):** The hub cluster secret was momentarily reset, causing ArgoCD to delete all apps. Recovery:
   ```bash
   # Re-apply root-appset
   kubectl apply -f gitops/bootstrap/root-appset.yaml
   # Wait for bootstrap to regenerate child appsets
   # Then run argocd-sync to recover stuck apps
   ./scripts/argocd-sync.sh
   ```

5. **Use the recovery script:**
   ```bash
   ./scripts/argocd-sync.sh          # refresh all + terminate stuck ops
   ./scripts/argocd-sync.sh <app>    # refresh specific app
   ```

**Key insight:** With EKS ArgoCD Capability, you CANNOT force-remove finalizers — the managed controller re-adds them. The only way to unstick a deleting app is to fix the underlying issue (remove stale cluster secrets, wait for resource cleanup) or wait for the controller timeout.

**CRITICAL:** You MUST ALWAYS ask the user before deleting any ArgoCD Application or ApplicationSet. Deleting an app with `preserveResourcesOnDeletion: false` (the default) will CASCADE-DELETE all Kubernetes resources it manages. This can destroy entire namespaces, deployments, secrets, and PVCs. Even deleting a single ApplicationSet can wipe out dozens of apps and their resources across multiple clusters. NEVER delete ArgoCD apps without explicit user confirmation.

**For infrastructure issues:**
- Use `terraform state list` then `terraform state show <resource>` before checking AWS CLI because Terraform state is the source of truth
- For networking issues, examine Terraform config files first
- You MUST NOT use `get_eks_vpc_config` MCP tool because it returns incomplete data — use Terraform state instead

**For EKS issues:**
- You MUST check cluster config with `describe-cluster` to confirm AutoMode status before assuming missing controllers because EKS Auto Mode means Karpenter is NOT running as pods
- After subnet tag changes, you MUST recreate LoadBalancer services to trigger new ALB creation

**For ingress-nginx webhook issues:**
- If Ingress creation fails with `x509: certificate signed by unknown authority`, check `ingress-nginx-admission` ValidatingWebhookConfiguration for empty `caBundle`
- Fix: `CA_BUNDLE=$(kubectl get secret ingress-nginx-admission -n ingress-nginx -o jsonpath='{.data.ca}') && kubectl patch validatingwebhookconfiguration ingress-nginx-admission --type='json' -p="[{\"op\":\"replace\",\"path\":\"/webhooks/0/clientConfig/caBundle\",\"value\":\"${CA_BUNDLE}\"}]"`

**For MCP tool failures:**
- If EKS MCP tools fail, provide equivalent kubectl or AWS CLI commands as fallback
- If Terraform MCP tools fail, use `terraform state` commands for inspection only
- You MUST NOT run `terraform apply` or `terraform destroy` directly — use `deploy.sh`/`destroy.sh` scripts because they handle backend config and state management

**Constraints:**
- You MUST wait at least 150 seconds after a new AWS Load Balancer shows "active" before testing connectivity because DNS propagation takes up to 5 minutes
- You MUST explicitly acknowledge tool usage and summarize key findings
- If initial investigation is inconclusive, you MUST return to AWS docs with refined queries

### 3. Apply Fixes

**Constraints:**
- You SHOULD update Terraform config and use deployment scripts rather than creating resources manually because manual resources drift
- If Terraform plan shows unexpected destroy operations, you MUST STOP and investigate state drift before proceeding
- If multiple issues are found, you MUST address them in dependency order: infrastructure → platform → application

### 4. Resource Deletion Safety

See [references/deletion-safety.md](references/deletion-safety.md) for the full deletion approval process.

**Constraints:**
- You MUST NOT execute any delete command (kubectl delete, terraform destroy, ArgoCD app delete) without explicit user confirmation because these may affect production resources
- You MUST explain what will be deleted and the impact before asking for confirmation
- You MUST consider non-destructive alternatives first (update, refresh, sync) before suggesting deletion
- You MUST NOT assume silence or implicit approval means "yes"
