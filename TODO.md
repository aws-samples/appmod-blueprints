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
