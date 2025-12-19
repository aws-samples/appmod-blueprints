# Kro RBAC Deployment Strategy

This document outlines how the Kro Backstage plugin RBAC configuration should be deployed and managed in different environments.

## Production Deployment Approaches

### 1. GitOps with ArgoCD (Recommended)

The RBAC configuration should be deployed through the existing GitOps workflow using ArgoCD:

```yaml
# In gitops/platform/backstage/kro-rbac/
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backstage-kro-rbac
  namespace: argocd
spec:
  project: platform
  source:
    repoURL: https://your-git-repo.com/platform-config
    targetRevision: main
    path: backstage/k8s-rbac
  destination:
    server: https://kubernetes.default.svc
    namespace: backstage
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Benefits:**
- Version controlled
- Automated deployment
- Consistent across environments
- Audit trail
- Rollback capability

### 2. Helm Chart Integration

Integrate the RBAC configuration into the existing Backstage Helm chart:

```yaml
# In backstage/helm/templates/kro-rbac.yaml
{{- if .Values.kro.enabled }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .Values.kro.serviceAccount.name }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "backstage.labels" . | nindent 4 }}
    app.kubernetes.io/component: kro-integration
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ .Values.kro.rbac.clusterRoleName }}
  labels:
    {{- include "backstage.labels" . | nindent 4 }}
rules:
  {{- toYaml .Values.kro.rbac.rules | nindent 2 }}
{{- end }}
```

**Configuration in values.yaml:**
```yaml
kro:
  enabled: true
  serviceAccount:
    name: backstage-kro-service-account
  rbac:
    clusterRoleName: backstage-kro-reader
    rules:
      - apiGroups: ['kro.run']
        resources: ['resourcegraphdefinitions']
        verbs: ['get', 'list', 'watch']
      # ... other rules
```

### 3. Terraform/CDK Integration

For infrastructure managed with Terraform or CDK, include RBAC as part of the EKS cluster setup:

```hcl
# terraform/modules/eks-addons/backstage-rbac.tf
resource "kubernetes_namespace" "backstage" {
  metadata {
    name = "backstage"
  }
}

resource "kubernetes_service_account" "backstage_kro" {
  metadata {
    name      = "backstage-kro-service-account"
    namespace = kubernetes_namespace.backstage.metadata[0].name
  }
}

resource "kubernetes_cluster_role" "backstage_kro_reader" {
  metadata {
    name = "backstage-kro-reader"
  }

  rule {
    api_groups = ["kro.run"]
    resources  = ["resourcegraphdefinitions", "*"]
    verbs      = ["get", "list", "watch"]
  }
  
  # Additional rules...
}

resource "kubernetes_cluster_role_binding" "backstage_kro_reader" {
  metadata {
    name = "backstage-kro-reader-binding"
  }
  
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.backstage_kro_reader.metadata[0].name
  }
  
  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.backstage_kro.metadata[0].name
    namespace = kubernetes_service_account.backstage_kro.metadata[0].namespace
  }
}
```

### 4. Crossplane Integration

Since this platform uses Crossplane, the RBAC could be managed as Crossplane compositions:

```yaml
# platform/crossplane/compositions/backstage-rbac-composition.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: backstage-kro-rbac
spec:
  compositeTypeRef:
    apiVersion: platform.example.com/v1alpha1
    kind: BackstageKroRBAC
  resources:
    - name: service-account
      base:
        apiVersion: kubernetes.crossplane.io/v1alpha1
        kind: Object
        spec:
          forProvider:
            manifest:
              apiVersion: v1
              kind: ServiceAccount
              metadata:
                name: backstage-kro-service-account
    # Additional resources...
```

## Environment-Specific Considerations

### Development Environment
- Manual application for testing: `kubectl apply -f k8s-rbac/backstage-kro-rbac.yaml`
- Temporary tokens for development
- Relaxed permissions for debugging

### Staging Environment
- Deployed through GitOps pipeline
- Production-like RBAC configuration
- Automated testing of permissions

### Production Environment
- Strict GitOps deployment only
- Minimal required permissions
- Automated token rotation
- Audit logging enabled

## Token Management

### Service Account Token Creation

**For Kubernetes 1.24+:**
```bash
# Create long-lived token (managed by CI/CD)
kubectl create token backstage-kro-service-account \
  --namespace backstage \
  --duration=8760h \
  --output=json
```

**For older Kubernetes versions:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: backstage-kro-service-account-token
  namespace: backstage
  annotations:
    kubernetes.io/service-account.name: backstage-kro-service-account
type: kubernetes.io/service-account-token
```

### Token Rotation Strategy

1. **Automated Rotation (Recommended):**
   - Use External Secrets Operator to manage tokens
   - Rotate tokens every 30-90 days
   - Store in AWS Secrets Manager or similar

2. **Manual Rotation:**
   - Scheduled maintenance windows
   - Update tokens in configuration management
   - Restart Backstage pods

## Security Best Practices

### Principle of Least Privilege
- Grant only necessary permissions
- Use namespace-scoped roles where possible
- Regular permission audits

### Network Security
- Network policies to restrict Backstage pod communication
- Service mesh integration for mTLS
- API server access controls

### Monitoring and Auditing
- Enable Kubernetes audit logging
- Monitor RBAC permission usage
- Alert on permission escalation attempts

## Deployment Checklist

### Pre-deployment
- [ ] RBAC configuration reviewed and approved
- [ ] Service account permissions validated
- [ ] Token management strategy defined
- [ ] Network policies configured

### Deployment
- [ ] Apply RBAC configuration through chosen method
- [ ] Verify service account creation
- [ ] Test permissions with `kubectl auth can-i`
- [ ] Generate and securely store service account token

### Post-deployment
- [ ] Verify Backstage can connect to Kubernetes
- [ ] Test Kro resource discovery
- [ ] Validate catalog integration
- [ ] Monitor for permission errors

### Ongoing Maintenance
- [ ] Regular permission audits
- [ ] Token rotation schedule
- [ ] Update permissions as Kro evolves
- [ ] Monitor security advisories

## Troubleshooting

### Common Issues

1. **Permission Denied Errors:**
   ```bash
   # Check current permissions
   kubectl auth can-i get resourcegraphdefinitions \
     --as=system:serviceaccount:backstage:backstage-kro-service-account
   ```

2. **Token Expiration:**
   ```bash
   # Check token validity
   kubectl --token=$TOKEN auth can-i get pods
   ```

3. **Service Account Not Found:**
   ```bash
   # Verify service account exists
   kubectl get serviceaccount -n backstage
   ```

### Debug Commands

```bash
# List all RBAC resources
kubectl get clusterroles,clusterrolebindings,roles,rolebindings -A | grep backstage

# Check service account details
kubectl describe serviceaccount backstage-kro-service-account -n backstage

# Test specific permissions
kubectl auth can-i list resourcegraphdefinitions \
  --as=system:serviceaccount:backstage:backstage-kro-service-account
```

## Integration with Existing Platform

This RBAC configuration should be integrated with the existing platform deployment process:

1. **Add to GitOps Repository:** Include RBAC manifests in the platform GitOps repository
2. **Update Helm Charts:** Integrate with existing Backstage Helm chart
3. **Terraform Integration:** Add to existing EKS/platform Terraform modules
4. **CI/CD Pipeline:** Include RBAC validation in deployment pipelines
5. **Documentation:** Update platform documentation and runbooks

## Conclusion

The RBAC configuration for the Kro Backstage plugin should be treated as critical infrastructure and deployed through the same rigorous processes as other platform components. Manual application should only be used for development and testing purposes.