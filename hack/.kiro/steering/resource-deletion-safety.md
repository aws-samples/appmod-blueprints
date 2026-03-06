# Resource Deletion Safety

## Purpose

Prevents destructive operations without explicit user approval to protect production resources and maintain system stability.

## Instructions

### Deletion Operations Requiring Approval

- NEVER execute kubectl delete commands without explicit user confirmation (ID: SAFETY_NO_DELETE_KUBECTL)
- NEVER execute terraform destroy commands without explicit user confirmation (ID: SAFETY_NO_DELETE_TERRAFORM)
- NEVER delete ArgoCD Applications without explicit user confirmation (ID: SAFETY_NO_DELETE_ARGOCD_APP)
- NEVER delete ArgoCD AppProjects without explicit user confirmation (ID: SAFETY_NO_DELETE_ARGOCD_PROJECT)
- NEVER delete Kubernetes namespaces without explicit user confirmation (ID: SAFETY_NO_DELETE_NAMESPACE)
- NEVER delete PersistentVolumes or PersistentVolumeClaims without explicit user confirmation (ID: SAFETY_NO_DELETE_PV)
- NEVER delete AWS resources (S3 buckets, RDS instances, etc.) without explicit user confirmation (ID: SAFETY_NO_DELETE_AWS)
- NEVER delete KRO ResourceGraphDefinitions without explicit user confirmation (ID: SAFETY_NO_DELETE_RGD)
- NEVER delete custom resources that manage infrastructure without explicit user confirmation (ID: SAFETY_NO_DELETE_CR)

### Required Approval Process

When a deletion operation is needed:
1. STOP and explain what will be deleted and the impact (ID: SAFETY_EXPLAIN_IMPACT)
2. EXPLICITLY ask user: "Do you want me to delete [resource]? This will [explain consequences]. Please confirm: yes/no" (ID: SAFETY_ASK_CONFIRMATION)
3. WAIT for explicit user confirmation with "yes" or similar affirmative response (ID: SAFETY_WAIT_CONFIRMATION)
4. ONLY proceed if user explicitly confirms (ID: SAFETY_PROCEED_ONLY_IF_CONFIRMED)

### Safe Operations (No Approval Needed)

- Read-only operations: kubectl get, kubectl describe, terraform show, terraform state show (ID: SAFETY_READONLY_OK)
- Creating new resources (ID: SAFETY_CREATE_OK)
- Updating existing resources (ID: SAFETY_UPDATE_OK)
- Viewing logs: kubectl logs, get_pod_logs (ID: SAFETY_LOGS_OK)
- Listing resources (ID: SAFETY_LIST_OK)

### Alternative Approaches

Before suggesting deletion:
- ALWAYS consider non-destructive alternatives first (ID: SAFETY_CONSIDER_ALTERNATIVES)
- Suggest updating resources instead of deleting and recreating (ID: SAFETY_SUGGEST_UPDATE)
- Explain why deletion might not be necessary (ID: SAFETY_EXPLAIN_ALTERNATIVES)

### Example Correct Behavior

**User asks:** "The application isn't syncing, can you fix it?"

**Correct response:**
"I can see the application needs to be refreshed. I have two options:
1. Non-destructive: Trigger an ArgoCD sync/refresh (recommended)
2. Destructive: Delete and recreate the application

Would you like me to try option 1 first?"

**Incorrect response:**
"Let me delete the application and it will be recreated." ❌

## Priority

Critical

## Error Handling

- If user says "no" or doesn't confirm, provide alternative solutions
- If deletion is the only option, clearly explain why and wait for confirmation
- Never assume silence or implicit approval means "yes"
