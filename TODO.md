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

#### Notes
- The `configure_keycloak` function in `setup-keycloak.sh` handles the SAML integration
- AMG workspace endpoint and credentials will be needed for Keycloak SAML client configuration
- Ensure proper IAM permissions for cross-service integration
- Current setup uses S3 for state storage but lacks DynamoDB for state locking

### 4. Integration Testing
- [ ] Verify metrics flow from EKS clusters to AMP
- [ ] Confirm Grafana can query AMP data sources
- [ ] Test user authentication and role-based access
- [ ] Validate dashboard functionality across user roles

## Infrastructure Improvements

### 5. Terraform State Management
- [x] Create DynamoDB table for Terraform state locking
- [x] Update backend configuration to include DynamoDB table
- [x] Test state locking functionality
- [ ] Rename secrets created by spoke terraform from peeks-hub-cluster/peeks-spoke-staging to peeks-workshop-peeks-spoke-staging
- [ ] include Backstage argo-cd plugin from https://roadie.io/backstage/plugins/argo-cd/
- [x] validate fleet-secret chart creation, and automation of clusters registration with fleet solution
- [ ] do we need to use a dedicated repo ? or how do I isolate things to  not commit things back ?

- [ ] check that in platform.sh export HUB_CLUSTER_NAME= and export SPOKE_CLUSTER_NAME_PREFIX= are not emplty


- [x] Fix tf-backend-bucket bucket stat
- [x] change default prefix from peeks-workshop to peeks-
  - [x] for gitops, the resource_prefix should be declare in argocd applicationset as cluster secret annotation
- [ ] change project_context_prefix to resource_prefix
- [ ] check database is created with appropriate prefix
- [ ] ensure RESOURCE_PREFIX is provided to codebuild, and ssm, and store in platform.sh env var
- [ ] also add (resource_prefix) for kro cluster secret
 
- [ ] do we still need const DEFAULT_HUB_CLUSTER_NAME and DEFAULT_SPOKE_CLUSTER_NAME_PREFIX ?
- [ ] same for : export HUB_CLUSTER_NAME='$HUB_CLUSTER_NAME_PARAM' and export SPOKE_CLUSTER_NAME_PREFIX='$SPOKE_CLUSTER_NAME_PREFIX_PARAM'

- [x] PEEKSIDEPEEKSIdePasswordSecret29-hw1gags77MYB -> you need to look at the tags: taskcat-project-name=peeks-workshop-test
- [x] do we still uses GiteaExternalUrl ? NO!
- [x] In many places in cdk, we see things like : name: `${resourcePrefix}-setup-ide-${this.stackName}`, putting a name imply that cdk won't generate the name by itself, and I think this is a problem. we should let cdk generate resources name, but ensure, it has the tags using the prefix to list for deletion

- [ ] delete with list buckets, or with tags : ResourcePrefix=peeks-workshop
- [ ] delete logs groups

- [ ] logs groups created by codebuld don't have tags : /aws/codebuild/PEEKSGITIAMStackDeployProje-OOIUub3Momy3

- [x] look at the task tack-cleanup-deployment, which is the older version of the new task taskcat-deployment-force enhanced version. there are many ressources that are correclty find and deleted in the previous versions, like s3 buckets starting with preffix peeks or tCAT-peeks, cloudwatch logs that contains tCat-peeks in the name, or iam roles that contains tCat-peeks. 

- [x] Exactly! The enhanced version has empty stub scanners that return no results. That's why it's not finding CloudWatch logs, CloudFront distributions, Lambda functions, or ECR repositories. The enhanced version needs these scanners implemented to match the old script's functionality.

- [x] enhanced the IAM scanner in the enhanced cleanup and delete any IAM roles and policies that has tag : Blueprint=peeks-spoke-staging, peeks-spoke-dev, peeks-spoke-prod, peeks-hub-cluster
  - the list of tags could be : tag : Blueprint=peeks-spoke-staging, peeks-spoke-dev, peeks-spoke-prod, peeks-hub-cluster, with peeks be the prefix global configuration


- [ ] if task clean force script hangs, maybe we can add a timeout
   ● Path: platform-engineering-on-eks/taskcat/scripts/enhanced-cleanup/scanners/iam_scanner.sh

  18, 18:     # Get customer-managed policies only (Scope=Local)
  19, 19:     local policies
- 20    :     policies=$(aws_cli iam list-policies --scope Local --query 'Policies[].[PolicyName,Arn,CreateDate,Description,AttachmentCount]' --output text 2>/dev/null || echo "")
+     20:     policies=$(run_with_timeout 120 "aws_cli iam list-policies --scope Local --query 'Policies[].[PolicyName,Arn,CreateDate,Description,AttachmentCount]' --output text" 2>/dev/null || echo "")



- [ERROR] Failed to terminate EC2 instance: peeks-workshop/IDE-PEEKS/IDE-PEEKS
[ERROR] Failed to delete i-02578cd4811fe2802: Failed to terminate EC2 instance, but the ec2 deletion works, I guess the script didn't handle the ec2 state change ? maybe just needs to wait a little ? or just hack the ec2 state change


Fail to delete
IDEPEEKSIdePasswordExporter0D143AF0
CustomResourcePhysicalID
IDEPEEKSIdePrefixListResource296503CB



- [ ] Explain how the workshop is setup, with cluster secrets, terraform stacks, dependencies, en vvar, gitlab...