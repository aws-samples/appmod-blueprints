# Kro ResourceGraphDefinition Troubleshooting

## Purpose

Provides systematic troubleshooting methodology for Kro ResourceGraphDefinitions (RGDs) that create ACK resources, focusing on dependency chains and IAM authentication issues.

## Instructions

### Understanding Kro Resource Dependencies

- ALWAYS check the topological order to understand resource creation sequence (ID: KRO_CHECK_TOPOLOGY)
- Use `kubectl get resourcegraphdefinition <name> -o jsonpath='{.status.topologicalOrder}'` to see creation order (ID: KRO_GET_TOPOLOGY)
- Resources are created in dependency order - if a resource fails, all dependent resources are blocked (ID: KRO_DEPENDENCY_CHAIN)

### Systematic Troubleshooting Approach

When a Kro instance is stuck in IN_PROGRESS state:

1. **Check instance status** to identify which resource is blocking (ID: KRO_CHECK_INSTANCE_STATUS)
   ```bash
   kubectl get <kind> <name> -n <namespace> -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
   ```

2. **Identify ACK resources in the RGD** (ID: KRO_IDENTIFY_ACK_RESOURCES)
   ```bash
   kubectl get resourcegraphdefinition <name> -o yaml | grep -E "apiVersion: (ecr|iam|eks|s3|dynamodb).services.k8s.aws"
   ```

3. **Check each ACK resource status in topological order** (ID: KRO_CHECK_ACK_STATUS)
   ```bash
   kubectl describe <ack-resource-type> <name> -n <namespace> | tail -30
   ```

4. **Look for common ACK errors** (ID: KRO_COMMON_ACK_ERRORS):
   - `AccessDenied: User is not authorized to perform: sts:TagSession` - Trust policy missing EKS Capability role
   - `EntityAlreadyExists` - Resource exists from previous deployment
   - `Resource already exists but is not managed by ACK` - Need to delete AWS resource or adopt it

### ACK IAM Authentication Issues

- ACK controllers running as EKS Capabilities use `<prefix>-<cluster-name>-ack-capability-role` (ID: KRO_ACK_CAPABILITY_ROLE)
- ACK workload roles MUST trust the capability role in their trust policy (ID: KRO_WORKLOAD_TRUST_POLICY)
- Check trust policy: `aws iam get-role --role-name <workload-role> --query 'Role.AssumeRolePolicyDocument'` (ID: KRO_CHECK_TRUST_POLICY)
- Verify capability role is in the Principal.AWS list (ID: KRO_VERIFY_CAPABILITY_TRUST)

### ACK Resource Status Conditions

Each ACK resource has these key conditions (ID: KRO_ACK_CONDITIONS):
- `ACK.IAMRoleSelected` - IAMRoleSelector found and role selected
- `ACK.ResourceSynced` - Resource successfully synced with AWS
- `Ready` - Resource is ready for use
- `ACK.Terminal` - Unrecoverable error (usually resource already exists)
- `ACK.Recoverable` - Temporary error (usually IAM permission issue)

### Cleaning Up Conflicting Resources

When ACK reports "Resource already exists":

1. **Find the AWS resource** (ID: KRO_FIND_AWS_RESOURCE)
   ```bash
   # For ECR
   aws ecr describe-repositories --repository-names <name>
   
   # For IAM Policy
   aws iam get-policy --policy-arn <arn>
   
   # For IAM Role
   aws iam get-role --role-name <name>
   ```

2. **Delete from AWS first** (ID: KRO_DELETE_AWS_FIRST)
   ```bash
   # ECR
   aws ecr delete-repository --repository-name <name> --force
   
   # IAM Policy (detach first if attached)
   aws iam list-entities-for-policy --policy-arn <arn>
   aws iam detach-role-policy --role-name <role> --policy-arn <arn>
   aws iam delete-policy --policy-arn <arn>
   
   # IAM Role
   aws iam delete-role --role-name <name>
   ```

3. **Delete Kubernetes resource to force recreation** (ID: KRO_DELETE_K8S_RESOURCE)
   ```bash
   kubectl delete <ack-resource-type> <name> -n <namespace>
   ```

### Forcing Kro Reconciliation

- Add annotation to trigger reconciliation: `kubectl annotate <kind> <name> -n <namespace> kro.run/reconcile="$(date +%s)" --overwrite` (ID: KRO_FORCE_RECONCILE)
- Kro will re-evaluate the entire resource graph and create missing resources (ID: KRO_REEVALUATE_GRAPH)

### Common Kro + ACK Patterns

**ECR Repository Creation**:
- Depends on: IAMRoleSelector (ecr)
- Creates: ECR repository in AWS
- Common issue: Repository name conflicts from previous deployments

**IAM Policy/Role Creation**:
- Depends on: IAMRoleSelector (iam), sometimes ECR repos for policy content
- Creates: IAM policy and role in AWS
- Common issue: Policy/role already exists, or trust policy issues

**Pod Identity Association**:
- Depends on: IAM role, service account
- Creates: EKS Pod Identity Association
- Common issue: Role not ready yet, or service account missing

**Service Account**:
- Depends on: Pod Identity Association (for role ARN annotation)
- Creates: Kubernetes ServiceAccount
- Blocks: All workload resources that need the service account

### Debugging Workflow Example

```bash
# 1. Check what's blocking
kubectl get cicdpipeline rust-cicd-pipeline -n team-rust -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
# Output: "waiting for unresolved resource 'sensor'"

# 2. Check topological order to find dependencies
kubectl get resourcegraphdefinition cicdpipeline.kro.run -o jsonpath='{.status.topologicalOrder}' | jq -r '.[]' | grep -n sensor
# Output shows sensor depends on serviceaccount, which depends on IAM resources

# 3. Check ACK resources in order
kubectl get repository.ecr.services.k8s.aws -n team-rust
kubectl get policy.iam.services.k8s.aws -n team-rust
kubectl get role.iam.services.k8s.aws -n team-rust

# 4. Describe failed resource
kubectl describe policy.iam.services.k8s.aws <name> -n team-rust | tail -30
# Shows: "EntityAlreadyExists: A policy called X already exists"

# 5. Clean up and let Kro recreate
aws iam delete-policy --policy-arn <arn>
kubectl delete policy.iam.services.k8s.aws <name> -n team-rust

# 6. Wait for Kro to recreate the chain
kubectl get sensor -n team-rust --watch
```

## Priority

High

## Error Handling

- If ACK resource shows AccessDenied for sts:TagSession, update Terraform workload role trust policies to include EKS Capability roles
- If resource shows EntityAlreadyExists, clean up AWS resources from previous deployments before recreating
- If Kro instance stays IN_PROGRESS for >5 minutes, manually check each ACK resource in topological order
- If service account is missing, check that all IAM resources (policy, role, pod identity) are Ready
