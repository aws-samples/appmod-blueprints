# Resource Deletion Safety

## Resources Requiring Explicit Approval

- kubectl delete (any resource)
- terraform destroy
- ArgoCD Applications and AppProjects
- Kubernetes namespaces
- PersistentVolumes / PersistentVolumeClaims
- AWS resources (S3, RDS, IAM, etc.)
- KRO ResourceGraphDefinitions
- Custom resources that manage infrastructure

## Approval Process

1. STOP and explain what will be deleted and the impact
2. Ask: "Do you want me to delete [resource]? This will [consequences]. Please confirm: yes/no"
3. Wait for explicit "yes" or similar affirmative
4. Only proceed if confirmed

## Safe Operations (No Approval Needed)

- Read-only: kubectl get, describe, logs, terraform show, state show
- Creating new resources
- Updating existing resources
- Listing resources

## Always Consider Alternatives First

Before suggesting deletion:
- Can the resource be updated instead?
- Can ArgoCD sync/refresh fix it?
- Can the issue be resolved by fixing config upstream in Git?

## Example

**User:** "The application isn't syncing, can you fix it?"

**Correct:** "I can try a non-destructive ArgoCD refresh first. If that doesn't work, I can delete and recreate — but I'll ask before doing that."

**Wrong:** "Let me delete the application and recreate it." ❌
