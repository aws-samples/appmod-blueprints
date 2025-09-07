# Platform on EKS Workshop - TODO

## Observability Stack Setup

### 1. Amazon Managed Prometheus (AMP)
- [ ] Create AMP workspace
- [ ] Configure workspace for multi-cluster metrics collection
- [ ] Set up IAM roles and policies for EKS clusters to write metrics
- [ ] Configure Prometheus remote write endpoints

### 2. Amazon Managed Grafana (AMG)
- [ ] Create AMG workspace
- [ ] Configure workspace authentication providers
- [ ] Set up IAM roles for Grafana service account
- [ ] Configure data sources (AMP integration)
- [ ] Import dashboards for EKS monitoring

### 3. Keycloak Integration with Managed Grafana
- [ ] Deploy Keycloak on management cluster
- [ ] Configure Keycloak realm for platform users
- [ ] Create SAML client for AMG integration
- [ ] Set up user roles:
  - `grafana-admin` - Full administrative access
  - `grafana-editor` - Dashboard editing capabilities  
  - `grafana-viewer` - Read-only access
- [ ] Create monitoring users:
  - `monitor-admin`
  - `monitor-editor` 
  - `monitor-viewer`
- [ ] Configure SAML authentication in AMG workspace
- [ ] Test SSO login flow from Keycloak to Grafana

### 4. Integration Testing
- [ ] Verify metrics flow from EKS clusters to AMP
- [ ] Confirm Grafana can query AMP data sources
- [ ] Test user authentication and role-based access
- [ ] Validate dashboard functionality across user roles

## Infrastructure Improvements

### 5. Terraform State Management
- [ ] Create DynamoDB table for Terraform state locking
  - Table name: `terraform-state-lock`
  - Primary key: `LockID` (String)
  - Billing mode: Pay-per-request
- [ ] Update backend configuration to include DynamoDB table
- [ ] Test state locking functionality
- [ ] Rename secrets created by spoke terraform from peeks-hub-cluster/peeks-spoke-staging to peeks-workshop-peeks-spoke-staging
- [ ] include Backstage argo-cd plugin from https://roadie.io/backstage/plugins/argo-cd/
- [ ] validate fleet-secret chart creation, and automation of clusters registration with fleet solution
- [ ] do we need to use a dedicated repo ? or how do I isolate things to  not commit things back ?

## Notes
- The `configure_keycloak` function in `setup-keycloak.sh` handles the SAML integration
- AMG workspace endpoint and credentials will be needed for Keycloak SAML client configuration
- Ensure proper IAM permissions for cross-service integration
- Current setup uses S3 for state storage but lacks DynamoDB for state locking


in platform.sh
export HUB_CLUSTER_NAME=
export SPOKE_CLUSTER_NAME_PREFIX=

git log --oneline --graph --left-right --cherry-pick feature/taskcat-clean-deployment-enhancement...origin/feature/gitlab-ci-integration
git diff --name-status origin/feature/gitlab-ci-integration...feature/taskcat-clean-deployment-enhancement




[INFO] Discovery completed at: 2025-09-05 09:17:18 UTC
[INFO] Total resources found: 3
[INFO] 📋 vpc:  resources
[INFO] Estimated cleanup time: 0s
[INFO] Generating cleanup plan
[INFO] Analyzing resource dependencies
[INFO] Dependency analysis complete. Graph saved to /tmp/dependency_graph_cleanup-20250905-111719.json
[INFO] Cleanup plan generated: cleanup-20250905-111719
[INFO] Total resources: 3
[INFO] Estimated duration: 4 minutes
[INFO] Risk level: medium
[INFO] Starting dry-run execution
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/dry_run_executor.sh: line 37: initialize_progress: command not found
[INFO] Validating phase 5: Infrastructure resources
[SUCCESS] ✓  completed: 3/0 items in 488073h 17m 26s
[INFO] Dry-run execution complete
[INFO] Validated 3 resources
[INFO] Skipping confirmation (auto-confirmed): Proceed with cleanup of 3 resources?
[INFO] Starting cleanup execution
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/executor.sh: line 45: initialize_progress: command not found
[INFO] Executing phase 5: Infrastructure resources
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/executor.sh: line 169: local: -n: invalid option
local: usage: local name[=value] ...
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/executor.sh: line 170: local: -n: invalid option
local: usage: local name[=value] ...
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/executor.sh: line 171: local: -n: invalid option
local: usage: local name[=value] ...
/Users/sallaman/Documents/2025/platform/platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/executor.sh: line 172: local: -n: invalid option
local: usage: local name[=value] ...
[ERROR] Failed to delete vpc-0beb73431e7751e2a: Failed to delete VPC
[ERROR] Failed to delete vpc-0b1a7a73600bdcc98: Failed to delete VPC
[ERROR] Failed to delete vpc-0238d7dec6d899fa1: Failed to delete VPC
[SUCCESS] ✓  completed: 3/0 items in 488073h 17m 33s
[INFO] Cleanup execution complete
[INFO] Total: 3, Successful: 0, Failed: 0
[INFO] Generating cleanup report...
[INFO] Generating execution report in console format
                                                                                                    6d899fa1tedd
🧹 CLEANUP EXECUTION REPORT
===========================

📊 Execution Summary:
  • Execution ID: exec-20250905-111727
  • Status: ✅ SUCCESS
  • Started: 2025-09-05T09:17:27Z
  • Completed: 2025-09-05T09:17:33Z
  • Duration: unknown

📈 Resource Statistics:
  • Total resources: 3
  • Successfully deleted: 0
  • Failed to delete: 0
  • Success rate: 0%

📋 Resources by type:
jq: error (at <stdin>:73): Cannot index array with string "type"