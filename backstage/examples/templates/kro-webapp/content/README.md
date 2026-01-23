# ${{ values.name }} - Kro WebApp ResourceGroup

${{ values.description }}

## Overview

This repository contains a Kro ResourceGroup definition for a web application that creates:

- **Deployment**: Kubernetes deployment with configurable replicas and container settings
{% if values.serviceEnabled %}- **Service**: Kubernetes service for internal communication{% endif %}
{% if values.ingressEnabled %}- **Ingress**: Kubernetes ingress for external access using ${{ values.ingressClass }} ingress class{% endif %}

## Configuration

### Application Settings
- **Name**: ${{ values.name }}
- **Namespace**: ${{ values.namespace }}
- **Environment**: ${{ values.environment }}
- **Image**: ${{ values.image }}
- **Port**: ${{ values.port }}
- **Replicas**: ${{ values.replicas }}

### Service Configuration
{% if values.serviceEnabled %}- **Service Enabled**: Yes
- **Service Port**: ${{ values.servicePort }}{% else %}- **Service Enabled**: No{% endif %}

### Ingress Configuration
{% if values.ingressEnabled %}- **Ingress Enabled**: Yes
- **Ingress Class**: ${{ values.ingressClass }}
- **Health Check Path**: ${{ values.healthCheckPath }}{% else %}- **Ingress Enabled**: No{% endif %}

## Deployment

### Prerequisites

1. Kro controller must be installed in the target Kubernetes cluster
2. Required RBAC permissions for ResourceGroup operations
3. {% if values.ingressEnabled %}${{ values.ingressClass }} ingress controller must be installed{% endif %}

### Deploy the ResourceGroup Definition

```bash
kubectl apply -f resourcegroup.yaml
```

### Create an Instance

```bash
kubectl apply -f instance.yaml
```

### Verify Deployment

```bash
# Check the ResourceGroup instance
kubectl get webapp ${{ values.name }} -n ${{ values.namespace }}

# Check created resources
kubectl get deployment,service{% if values.ingressEnabled %},ingress{% endif %} -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}

# Check pod status
kubectl get pods -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}
```

## Customization

You can customize the deployment by modifying the `instance.yaml` file:

```yaml
apiVersion: kro.run/v1alpha1
kind: WebApp
metadata:
  name: ${{ values.name }}
  namespace: ${{ values.namespace }}
spec:
  # Modify these values as needed
  replicas: 3
  image: your-custom-image:latest
  port: 8080
  service:
    enabled: true
    port: 80
  ingress:
    enabled: true
```

## Monitoring

{% if values.ingressEnabled %}### Access the Application

Once deployed, the application will be accessible via the ingress URL. Check the ingress status:

```bash
kubectl get ingress ${{ values.name }} -n ${{ values.namespace }}
```
{% endif %}

### Check Application Health

The application includes health checks on the `${{ values.healthCheckPath }}` endpoint.

### View Logs

```bash
kubectl logs -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }} -f
```

## Troubleshooting

### Common Issues

1. **ResourceGroup not found**: Ensure Kro controller is installed and running
2. **Pods not starting**: Check image availability and resource limits
3. **Service not accessible**: Verify service configuration and network policies
{% if values.ingressEnabled %}4. **Ingress not working**: Check ingress controller and DNS configuration{% endif %}

### Debug Commands

```bash
# Check ResourceGroup status
kubectl describe webapp ${{ values.name }} -n ${{ values.namespace }}

# Check deployment status
kubectl describe deployment ${{ values.name }} -n ${{ values.namespace }}

# Check events
kubectl get events -n ${{ values.namespace }} --sort-by='.lastTimestamp'
```

## Support

For issues related to:
- **Kro ResourceGroups**: Check the [Kro documentation](https://github.com/awslabs/kro)
- **Backstage integration**: Contact the platform team
- **Application-specific issues**: Check application logs and configuration