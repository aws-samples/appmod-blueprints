# Troubleshoot with Kiro

## Prompt to debug Argo CD

```text
Please analyze the ArgoCD applications in the peeks-hub cluster and provide the following information:

1. List all ArgoCD applications with their current status:
   - Application name
   - Sync status (Synced/OutOfSync)
   - Health status (Healthy/Progressing/Degraded/Missing)
   - Sync wave annotation (argocd.argoproj.io/sync-wave)
   - Any error messages from status.conditions or status.operationState.message

2. For any applications that are NOT "Synced/Healthy", provide:
   - The full status.conditions array
   - The status.operationState (phase, message, startedAt, finishedAt)
   - The status.resources array showing which specific resources are unhealthy

3. Identify any applications with:
   - Operations stuck in "Running" phase for >5 minutes
   - ComparisonError or revision conflict messages
   - CRD annotation size errors
   - Missing namespace errors
   - Resource dependency issues

4. Group the unhealthy applications by their sync wave to show the dependency order

5. Check for any pods in CrashLoopBackOff state across the cluster

Please format the output in a structured way that shows the dependency relationships and root causes of issues.
``