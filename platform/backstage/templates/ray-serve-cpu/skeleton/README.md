# Ray Service Deployment: ${{values.name}}

This repository contains the GitOps configuration for deploying a Ray Service on Kubernetes using Kro abstraction.

## Overview

- **Service Name**: ${{values.name}}
- **Namespace**: ${{values.namespace}}
- **Ray Serve Config**: ${{values.rayServeFile}}
- **Worker Replicas**: ${{values.replicas}}
- **Head Resources**: ${{values.headCpu}}/${{values.headMemory}}
- **Worker Resources**: ${{values.workerCpu}}/${{values.workerMemory}}

## Architecture

This Ray Service deployment uses **Kro abstraction** for simplified management:

- **Single Kro Resource**: One `RayService` resource orchestrates everything
- **Automatic Orchestration**: Kro creates and manages all required resources
- **Dependency Management**: Proper resource ordering and lifecycle management
- **Status Aggregation**: Unified status across all managed resources

### Resources Created by Kro

The Kro `RayService` resource automatically creates and manages:

1. **Namespace**: Dedicated namespace for the Ray Service
2. **Ray Service**: Ray cluster with serve applications
3. **Kubernetes Service**: Exposes Ray Serve and Dashboard endpoints
4. **Ingress**: HTTP routing for external access

## Kro Benefits

- **Simplified Management**: Single resource manages complex Ray deployment
- **Resource Orchestration**: Automatic dependency handling and ordering
- **Status Aggregation**: Unified status across all managed resources
- **Lifecycle Management**: Coordinated creation, updates, and deletion
- **GitOps Integration**: Full visibility in ArgoCD applications

## GitOps Management

This deployment is managed via GitOps using ArgoCD:

- **Repository**: https://${{values.gitlab_hostname}}/${{values.git_username}}/${{values.name}}-ray-service
- **ArgoCD Application**: ${{values.name}}-ray-service
- **ArgoCD Project**: ${{values.name}}-ray-project

## Accessing Ray Services

### Ray Serve Endpoints
- **Base URL**: https://${{values.gitlab_hostname}}/ray-serve/${{values.name}}/
- **Health Check**: `GET /ray-serve/${{values.name}}/`
- **ML Endpoints**: `POST /ray-serve/${{values.name}}/summarize_translate`

### Ray Dashboard
- **Dashboard URL**: https://${{values.gitlab_hostname}}/ray-dashboard/${{values.name}}/

## Customization

To customize your Ray Service, modify the Kro `RayService` resource in `manifests/kro-ray-service.yaml`:

### Resource Configuration
```yaml
spec:
  replicas: 3  # Number of worker replicas
  resources:
    head:
      cpu: "2"
      memory: "4Gi"
    worker:
      cpu: "1"
      memory: "2Gi"
```

### Ray Serve Configuration
```yaml
spec:
  rayServeFile: "https://your-custom-serve-config.zip"
```

## Monitoring

Monitor your Ray Service through:

- **ArgoCD UI**: Application sync status and health
- **Kro Status**: Check the RayService resource status
- **Ray Dashboard**: Cluster metrics and job status
- **Kubernetes**: Pod logs and resource usage

## Troubleshooting

Common issues and solutions:

1. **Kro Resource Not Ready**: Check Kro controller logs and resource status
2. **Ray Service Not Starting**: Check Ray operator logs and resource availability
3. **Ingress Not Working**: Verify NGINX ingress controller and DNS resolution
4. **Workers Not Joining**: Check network policies and resource limits

### Checking Kro Status

```bash
# Check Kro RayService resource
kubectl get rayservice ${{values.name}}-ray-service -n ${{values.namespace}} -o yaml

# Check Kro controller logs
kubectl logs -n kro-system deployment/kro-controller

# Check managed resources
kubectl get all -n ${{values.namespace}} -l app.kubernetes.io/name=${{values.name}}
```

## Sample Code

See the `sample/` directory for example PyTorch code that can be used with Ray Serve.

For more information, see:
- [Ray Documentation](https://docs.ray.io/)
- [Kro Documentation](https://kro.run/)

---

**Created by**: ${{values.created_by}}  
**Template**: ray-serve-kubernetes (Kro)  
**GitOps**: Managed by ArgoCD  
**Orchestration**: Managed by Kro
