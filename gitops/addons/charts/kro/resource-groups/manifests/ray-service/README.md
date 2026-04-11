# Ray Service Kro Abstraction

This Kro ResourceGraphDefinition provides a high-level abstraction for deploying Ray Services on Kubernetes.

## Overview

The `rayservice.kro.run` ResourceGraphDefinition creates and manages:

- **Namespace**: Dedicated namespace for the Ray Service
- **RayService**: Ray cluster with serve applications
- **Service**: Kubernetes service to expose Ray endpoints
- **Ingress**: HTTP routing for Ray Serve and Dashboard

## Schema

```yaml
apiVersion: kro.run/v1alpha1
kind: RayService
metadata:
  name: my-ray-service
  namespace: my-namespace
spec:
  name: my-service
  namespace: ray-system
  rayServeFile: "https://github.com/mlops-on-kubernetes/Book/raw/main/Chapter%206/serve-config.zip"
  replicas: 2
  resources:
    head:
      cpu: "1"
      memory: "2Gi"
    worker:
      cpu: "500m"
      memory: "1Gi"
  gitlab:
    hostname: gitlab.example.com
    username: myuser
  createdBy: "backstage-user"
```

## Parameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | - | Name of the Ray Service |
| `namespace` | string | - | Kubernetes namespace |
| `rayServeFile` | string | Book example | URL to Ray Serve config zip |
| `replicas` | int | 2 | Number of Ray worker replicas |
| `resources.head.cpu` | string | "1" | Ray head CPU request |
| `resources.head.memory` | string | "2Gi" | Ray head memory request |
| `resources.worker.cpu` | string | "500m" | Ray worker CPU request |
| `resources.worker.memory` | string | "1Gi" | Ray worker memory request |
| `gitlab.hostname` | string | - | GitLab hostname for ingress |
| `gitlab.username` | string | - | GitLab username |
| `createdBy` | string | "unknown" | Creator identifier |

## Status Fields

The RayService resource provides status information:

- `rayServiceName`: Name of the created RayService
- `rayServiceNamespace`: Namespace of the RayService
- `serveServiceName`: Name of the Kubernetes service
- `dashboardServiceName`: Name of the dashboard service
- `ingressName`: Name of the ingress resource
- `rayClusterReady`: Ray cluster readiness status

## Endpoints

Once deployed, the Ray Service is accessible via:

- **Ray Serve API**: `https://{gitlab.hostname}/ray-serve/{name}/`
- **Ray Dashboard**: `https://{gitlab.hostname}/ray-dashboard/{name}/`

## Example Usage

```yaml
apiVersion: kro.run/v1alpha1
kind: RayService
metadata:
  name: text-ml-service
  namespace: team-ml
spec:
  name: text-ml
  namespace: ray-system
  rayServeFile: "https://github.com/mlops-on-kubernetes/Book/raw/main/Chapter%206/serve-config.zip"
  replicas: 3
  resources:
    head:
      cpu: "2"
      memory: "4Gi"
    worker:
      cpu: "1"
      memory: "2Gi"
  gitlab:
    hostname: gitlab.company.com
    username: ml-team
  createdBy: "ml-engineer"
```

## Dependencies

- Ray Operator must be installed in the cluster
- NGINX Ingress Controller for routing
- Kubernetes cluster with sufficient resources

## Monitoring

Monitor the Ray Service through:

1. **Kro Status**: Check the RayService resource status
2. **Ray Dashboard**: Access via the ingress endpoint
3. **Kubernetes**: Monitor pods, services, and ingress resources
4. **ArgoCD**: Track GitOps deployment status

## Troubleshooting

Common issues:

1. **Ray Service not starting**: Check Ray operator logs and resource availability
2. **Ingress not working**: Verify NGINX ingress controller and DNS resolution
3. **Workers not joining**: Check network policies and resource limits
4. **Serve applications failing**: Check Ray Dashboard for application logs

For more information, see the Ray documentation: https://docs.ray.io/
