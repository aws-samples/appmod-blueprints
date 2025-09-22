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
- [x] Rename secrets created by spoke terraform from peeks-hub-cluster/peeks-spoke-staging to peeks-workshop-peeks-spoke-staging
- [ ] include Backstage argo-cd plugin from https://roadie.io/backstage/plugins/argo-cd/
- [x] validate fleet-secret chart creation, and automation of clusters registration with fleet solution
- [ ] do we need to use a dedicated repo ? or how do I isolate things to  not commit things back ?
- [x] check that in platform.sh export HUB_CLUSTER_NAME= and export SPOKE_CLUSTER_NAME_PREFIX= are not emplty
- [x] Fix tf-backend-bucket bucket stat
- [x] change default prefix from peeks-workshop to peeks-
  - [x] for gitops, the resource_prefix should be declare in argocd applicationset as cluster secret annotation
- [x] change project_context_prefix to resource_prefix
- [ ] check database is created with appropriate prefix
- [x] ensure RESOURCE_PREFIX is provided to codebuild, and ssm, and store in platform.sh env var
- [ ] also add (resource_prefix) for kro cluster secret
- [x] do we still need const DEFAULT_HUB_CLUSTER_NAME and DEFAULT_SPOKE_CLUSTER_NAME_PREFIX ? only in terraform
- [x] same for : export HUB_CLUSTER_NAME='$HUB_CLUSTER_NAME_PARAM' and export SPOKE_CLUSTER_NAME_PREFIX='$SPOKE_CLUSTER_NAME_PREFIX_PARAM'
- [x] PEEKSIDEPEEKSIdePasswordSecret29-hw1gags77MYB -> you need to look at the tags: taskcat-project-name=peeks-workshop-test
- [x] do we still uses GiteaExternalUrl ? NO!
- [x] In many places in cdk, we see things like : name: `${resourcePrefix}-setup-ide-${this.stackName}`, putting a name imply that cdk won't generate the name by itself, and I think this is a problem. we should let cdk generate resources name, but ensure, it has the tags using the prefix to list for deletion
- [x] delete with list buckets, or with tags : ResourcePrefix=peeks-workshop
- [ ] delete logs groups
  - [ ] logs groups created by codebuld don't have tags : /aws/codebuild/PEEKSGITIAMStackDeployProje-OOIUub3Momy3
- [x] Explain how the workshop is setup, with cluster secrets, terraform stacks, dependencies, en vvar, gitlab... -> platform-engineering-on-eks/Platform-setup-flow.md
- [x] check /peeks-hub-cluster/argocd-hub-role (delete)
- [ ] move access entry for participantassumerole from cdk to codebuild ?
- [x] remove Cloud9
- [x] renomer prefix de peeks-workshop à peeks

- update kro vars : /Users/sallaman/Documents/2025/platform/appmod-blueprints/gitops/addons/charts/multi-acct/templates/configmap.yaml
  ec2.{{ $key }}: "arn:aws:iam::{{ $value }}:role/peeks-cluster-mgmt-ec2"
  eks.{{ $key }}: "arn:aws:iam::{{ $value }}:role/peeks-cluster-mgmt-eks"
  iam.{{ $key }}: "arn:aws:iam::{{ $value }}:role/peeks-cluster-mgmt-iam"


- the CFN do not upload lmbda assets to the s3 bucket, so it is not found..


task taskcat-clean-deployment


- [x] clean elastic ip - like peeks-spoke-dev-us-east-1a
- [x] clean ebs volumes - peeks-hub-cluster-dynamic-pvc-5c3ffb10-f081-43d2-ad13-2ef6de2022b3
- [x] clean parameter store : like peeks-workshop-tf-backend-bucket
- [x] cloudwatch logs groups - like /aws/codebuild/PEEKSGITIAMStackDeployProje-30HWWmiBcgx0 or /aws/lambda/tCaT-peeks-workshop-test--IDEPEEKSIdePasswordExpor-OOmtoIML4oGw or tCaT-peeks-workshop-test-fleet-workshop-test-92b4118d493d47dcb827190d4e5ac6b9-IDEPEEKSIdeLogGroup3808F7B1-xMtRAbEgY8Ho


- Does WORKSHOP_ID=28c283c1-1d60-43fa-a604-4e983e0e8038 is the goor one ?
- update region in backstage templates

- gitlab - {"message":{"project_namespace.path":["can only include non-accented letters, digits, '_', '-' and '.'. It must not start with '-', '_', or '.', nor end with '-', '_', '.', '.git', or '.atom'."],"path":["can only include non-accented letters, digits, '_', '-' and '.'. It must not start with '-', '_', or '.', nor end with '-', '_', '.', '.git', or '.atom'."]}}

#### Production Security Hardening - the hardening should be done, in a gitops manner, not using kubectl
- same for installing network policy, load balancer controller, all should be done with gitops, and maybe gitops-bridge if we need dependency with resources deployed in terraform
- add also the cleanup after destroy with tsk taskcat-clean-deployment-force, that can help remove any remaining aws resources deploy by the platform

