# Kro Plugin Security Configuration

This document describes the security configuration and permissions setup for the Kro Backstage plugin.

## Overview

The Kro plugin implements comprehensive security measures including:

- **RBAC Validation**: Validates user permissions against Kubernetes RBAC
- **Audit Logging**: Logs all ResourceGroup operations for security monitoring
- **Error Handling**: Provides proper error messages for authorization failures
- **Permission Integration**: Integrates with Backstage's permission system

## Security Components

### 1. RBAC Validation

The `KroRBACValidator` validates user permissions against Kubernetes RBAC before allowing operations:

```typescript
// Example usage
const validation = await rbacValidator.validateKubernetesPermissions(
  user,
  'create',
  'kro.run/v1alpha1/resourcegraphdefinitions',
  'default',
  'my-cluster'
);
```

### 2. Audit Logging

The `KroAuditLogger` logs all ResourceGroup operations:

```typescript
// Example audit event
auditLogger.logResourceGroupSuccess(
  KroAuditEventType.RESOURCE_GROUP_CREATED,
  user,
  { type: 'ResourceGroup', name: 'my-rg', namespace: 'default' },
  'create',
  { templateUsed: 'cicd-pipeline' }
);
```

### 3. Error Handling

The `KroErrorHandler` provides user-friendly error messages:

```typescript
// Example error handling
const errorResponse = errorHandler.handleAuthorizationError(
  error,
  user,
  {
    cluster: 'my-cluster',
    operation: 'create',
    resource: 'ResourceGroup',
    requiredPermissions: ['kro.run/resourcegraphdefinitions:create']
  }
);
```

## Configuration

### App Configuration

Add the following to your `app-config.yaml`:

```yaml
kro:
  enablePermissions: true
  enableAuditLogging: true
  
  rbacValidation:
    enabled: true
    strictMode: false
    cacheTimeout: 300
  
  auditLogging:
    enabled: true
    logLevel: 'info'
    includeSuccessEvents: true
  
  errorHandling:
    enableDetailedErrors: true
    includeStackTrace: false
```

### Kubernetes RBAC

Apply the RBAC configuration:

```bash
kubectl apply -f k8s-rbac/kro-rbac.yaml
```

## Required Permissions

### Service Account Permissions

The Backstage service account requires the following permissions:

#### Full Access (Admin)
- `kro.run/resourcegraphdefinitions`: get, list, watch, create, update, patch, delete
- `kro.run/cicdpipelines`: get, list, watch, create, update, patch, delete
- `kro.run/eksclusters`: get, list, watch, create, update, patch, delete
- `kro.run/eksclusterwithvpcs`: get, list, watch, create, update, patch, delete
- `kro.run/vpcs`: get, list, watch, create, update, patch, delete
- `events`: get, list, watch

#### Read-Only Access
- `kro.run/*`: get, list, watch
- `events`: get, list, watch

### User Permissions

Users are mapped to the following groups based on their roles:

- **kro-admins**: Full access to all ResourceGroup operations
- **platform-engineers**: Full access to infrastructure ResourceGroups
- **developers**: Access to application ResourceGroups
- **kro-readers**: Read-only access to all ResourceGroups

## Security Features

### 1. Permission Validation

Before any ResourceGroup operation, the plugin:

1. Validates the user's identity
2. Checks Kubernetes RBAC permissions
3. Logs the permission check result
4. Returns appropriate error messages if access is denied

### 2. Audit Trail

All operations are logged with:

- User identity
- Resource details (name, namespace, cluster)
- Operation type (create, update, delete, view)
- Result (success/failure)
- Timestamp
- Additional context

### 3. Error Messages

Authorization failures provide:

- Clear explanation of what was denied
- Required permissions
- Guidance on how to request access
- Contact information for platform administrators

## Monitoring and Alerting

### Audit Log Format

```json
{
  "eventType": "resourcegroup.created",
  "timestamp": "2024-01-15T10:30:00Z",
  "user": {
    "userEntityRef": "user:default/john.doe",
    "type": "user"
  },
  "resource": {
    "type": "ResourceGroup",
    "name": "my-pipeline",
    "namespace": "default",
    "cluster": "prod-cluster"
  },
  "action": "create",
  "result": "success",
  "component": "kro-audit"
}
```

### Security Alerts

Monitor for:

- Multiple permission denied events from the same user
- Failed authentication attempts
- Unusual ResourceGroup operations
- Operations outside normal business hours

## Troubleshooting

### Common Issues

1. **Permission Denied Errors**
   - Check user group membership
   - Verify Kubernetes RBAC configuration
   - Review service account permissions

2. **Authentication Failures**
   - Verify service account token
   - Check token expiration
   - Validate cluster connectivity

3. **Audit Logging Issues**
   - Check log level configuration
   - Verify logger initialization
   - Review log output format

### Debug Commands

```bash
# Check service account permissions
kubectl auth can-i create resourcegraphdefinitions --as=system:serviceaccount:backstage:backstage-kro

# View audit logs
kubectl logs -n backstage deployment/backstage | grep "kro-audit"

# Check RBAC configuration
kubectl get clusterrole backstage-kro-admin -o yaml
```

## Best Practices

1. **Principle of Least Privilege**: Grant only necessary permissions
2. **Regular Audits**: Review permissions and access logs regularly
3. **Monitoring**: Set up alerts for security events
4. **Documentation**: Keep security documentation up to date
5. **Testing**: Regularly test permission scenarios

## Security Considerations

1. **Service Account Security**: Rotate service account tokens regularly
2. **Network Security**: Use TLS for all Kubernetes API communications
3. **Secrets Management**: Store sensitive configuration in Kubernetes secrets
4. **Access Control**: Implement proper user authentication and authorization
5. **Audit Retention**: Retain audit logs for compliance requirements