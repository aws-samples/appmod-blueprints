# Provisioner Files - DEPRECATED

These files are deprecated as of the Kro migration. They have been replaced by:

1. **Kro Resource Group Definition (RGD)**: `appmod-blueprints/gitops/addons/charts/kro/resource-groups/cicd-pipeline/cicd-pipeline.yaml`
2. **Inline YAML manifests** in the Backstage template: `template-cicd-pipeline.yaml`

## Migration Summary

- `podidentity.yaml` → Replaced by ACK-based resources in Kro RGD
- `wf-templates.yaml` → Replaced by inline workflow templates in Backstage template
- `wf-run.yaml` → Replaced by inline workflow execution in Backstage template

## Files Replaced

### podidentity.yaml
- **Namespace creation** → Now handled by Kro RGD
- **ServiceAccount** → Now handled by Kro RGD with proper RBAC
- **PodIdentityAssociation** → Now uses ACK EKS controller in Kro RGD
- **IAM Role** → Now uses ACK IAM controller in Kro RGD
- **IAM Policy** → Now uses ACK IAM controller in Kro RGD
- **RolePolicyAttachment** → Now uses ACK IAM controller in Kro RGD

### wf-templates.yaml & wf-run.yaml
- **Workflow templates** → Now embedded in Kro RGD and inline in Backstage template
- **ECR repository creation** → Now handled by ACK ECR controller in Kro RGD
- **Docker registry secrets** → Now handled by Kro RGD with proper lifecycle management
- **GitLab webhook setup** → Now handled by inline workflow in Backstage template

## Benefits of Migration

1. **Simplified template execution** - No more file-based kube:apply actions
2. **Better resource orchestration** - Kro handles dependencies and readiness
3. **Native AWS integration** - ACK controllers provide better AWS resource management
4. **Improved maintainability** - Single RGD defines all resources with proper relationships
5. **Enhanced observability** - Better status tracking and error handling

These files are kept for reference and potential rollback scenarios.