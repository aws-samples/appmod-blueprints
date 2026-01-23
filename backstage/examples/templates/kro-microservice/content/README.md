# ${{ values.name }} - Kro Microservice ResourceGroup

${{ values.description }}

## Overview

This repository contains a comprehensive Kro ResourceGroup definition for a production-ready microservice that creates:

{% if values.configMapEnabled %}- **ConfigMap**: Application configuration{% endif %}
{% if values.secretEnabled %}- **Secret**: Sensitive configuration data{% endif %}
- **Deployment**: Kubernetes deployment with health checks and resource limits
- **Service**: Kubernetes service for internal communication
{% if values.ingressEnabled %}- **Ingress**: Kubernetes ingress for external access{% endif %}

## Configuration

### Application Settings
- **Name**: ${{ values.name }}
- **Namespace**: ${{ values.namespace }}
- **Environment**: ${{ values.environment }}
- **Image**: ${{ values.image }}
- **Port**: ${{ values.port }}
- **Replicas**: ${{ values.replicas }}
- **Service Account**: ${{ values.serviceAccount }}

### Resource Configuration
- **CPU Request**: ${{ values.cpuRequest }}
- **Memory Request**: ${{ values.memoryRequest }}
- **CPU Limit**: ${{ values.cpuLimit }}
- **Memory Limit**: ${{ values.memoryLimit }}

### Service Configuration
- **Service Type**: ${{ values.serviceType }}
- **Service Port**: ${{ values.servicePort }}

### Ingress Configuration
{% if values.ingressEnabled %}- **Ingress Enabled**: Yes
- **Ingress Class**: ${{ values.ingressClass }}
{% if values.hostname %}- **Hostname**: ${{ values.hostname }}{% endif %}
- **Path Prefix**: ${{ values.pathPrefix }}
- **TLS Enabled**: ${{ values.tlsEnabled }}{% else %}- **Ingress Enabled**: No{% endif %}

### Health Checks
- **Health Check Path**: ${{ values.healthCheckPath }}
- **Readiness Check Path**: ${{ values.readinessCheckPath }}
- **Liveness Initial Delay**: ${{ values.livenessInitialDelay }}s
- **Readiness Initial Delay**: ${{ values.readinessInitialDelay }}s

### Configuration Management
{% if values.configMapEnabled %}- **ConfigMap Enabled**: Yes
- **Configuration Data**:
  {% for key, value in values.configData.items() %}- {{ key }}: {{ value }}
  {% endfor %}{% else %}- **ConfigMap Enabled**: No{% endif %}

{% if values.secretEnabled %}- **Secret Enabled**: Yes
- **Secret Keys**: {{ values.secretData.keys() | list | join(', ') }}{% else %}- **Secret Enabled**: No{% endif %}

## Deployment

### Prerequisites

1. Kro controller must be installed in the target Kubernetes cluster
2. Required RBAC permissions for ResourceGroup operations
3. {% if values.ingressEnabled %}${{ values.ingressClass }} ingress controller must be installed{% endif %}
4. {% if values.tlsEnabled %}TLS certificate management (cert-manager recommended){% endif %}

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
kubectl get microservice ${{ values.name }} -n ${{ values.namespace }}

# Check created resources
kubectl get {% if values.configMapEnabled %}configmap,{% endif %}{% if values.secretEnabled %}secret,{% endif %}deployment,service{% if values.ingressEnabled %},ingress{% endif %} -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}

# Check pod status
kubectl get pods -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}

# Check pod logs
kubectl logs -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }} -f
```

## Customization

You can customize the deployment by modifying the `instance.yaml` file:

```yaml
apiVersion: kro.run/v1alpha1
kind: Microservice
metadata:
  name: ${{ values.name }}
  namespace: ${{ values.namespace }}
spec:
  # Scale the application
  replicas: 5
  
  # Update the image
  image: your-custom-image:v2.0.0
  
  # Adjust resources
  resources:
    requests:
      cpu: "200m"
      memory: "256Mi"
    limits:
      cpu: "1"
      memory: "1Gi"
  
  # Configure ingress
  ingress:
    enabled: true
    hostname: api.example.com
    tlsEnabled: true
```

## Monitoring and Observability

### Health Endpoints

The microservice exposes the following health endpoints:
- **Liveness**: `${{ values.healthCheckPath }}` - Used by Kubernetes to restart unhealthy pods
- **Readiness**: `${{ values.readinessCheckPath }}` - Used by Kubernetes to route traffic

### Accessing the Application

{% if values.ingressEnabled %}#### External Access

{% if values.hostname %}The application is accessible at: {% if values.tlsEnabled %}https{% else %}http{% endif %}://${{ values.hostname }}${{ values.pathPrefix }}{% else %}Check the ingress status for the external URL:

```bash
kubectl get ingress ${{ values.name }} -n ${{ values.namespace }}
```{% endif %}
{% endif %}

#### Internal Access

The service is accessible within the cluster at:
- **Service Name**: `${{ values.name }}.${{ values.namespace }}.svc.cluster.local`
- **Port**: `${{ values.servicePort }}`

### Monitoring Commands

```bash
# Check deployment status
kubectl get deployment ${{ values.name }} -n ${{ values.namespace }}

# Check service endpoints
kubectl get endpoints ${{ values.name }} -n ${{ values.namespace }}

# View application logs
kubectl logs deployment/${{ values.name }} -n ${{ values.namespace }} -f

# Check resource usage
kubectl top pods -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}
```

## Scaling

### Horizontal Scaling

```bash
# Scale up
kubectl patch microservice ${{ values.name }} -n ${{ values.namespace }} --type='merge' -p='{"spec":{"replicas":5}}'

# Scale down
kubectl patch microservice ${{ values.name }} -n ${{ values.namespace }} --type='merge' -p='{"spec":{"replicas":2}}'
```

### Vertical Scaling

Update the resource limits in the `instance.yaml` file and reapply:

```yaml
spec:
  resources:
    requests:
      cpu: "500m"
      memory: "512Mi"
    limits:
      cpu: "2"
      memory: "2Gi"
```

## Troubleshooting

### Common Issues

1. **ResourceGroup not found**: Ensure Kro controller is installed and running
2. **Pods not starting**: Check image availability and resource limits
3. **Health checks failing**: Verify health endpoints are implemented correctly
4. **Service not accessible**: Check service configuration and network policies
{% if values.ingressEnabled %}5. **Ingress not working**: Verify ingress controller and DNS configuration{% endif %}
{% if values.configMapEnabled or values.secretEnabled %}6. **Configuration issues**: Check ConfigMap and Secret data{% endif %}

### Debug Commands

```bash
# Check ResourceGroup status
kubectl describe microservice ${{ values.name }} -n ${{ values.namespace }}

# Check deployment details
kubectl describe deployment ${{ values.name }} -n ${{ values.namespace }}

# Check pod details
kubectl describe pods -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}

# Check service details
kubectl describe service ${{ values.name }} -n ${{ values.namespace }}

{% if values.ingressEnabled %}# Check ingress details
kubectl describe ingress ${{ values.name }} -n ${{ values.namespace }}
{% endif %}

# Check events
kubectl get events -n ${{ values.namespace }} --sort-by='.lastTimestamp'

# Test health endpoints
kubectl port-forward deployment/${{ values.name }} 8080:${{ values.port }} -n ${{ values.namespace }}
curl http://localhost:8080${{ values.healthCheckPath }}
curl http://localhost:8080${{ values.readinessCheckPath }}
```

### Performance Tuning

1. **Resource Optimization**: Monitor actual resource usage and adjust requests/limits
2. **Replica Tuning**: Use Horizontal Pod Autoscaler (HPA) for automatic scaling
3. **Health Check Tuning**: Adjust probe timing based on application startup time
4. **Image Optimization**: Use multi-stage builds and minimal base images

## Security Considerations

1. **Service Account**: Use dedicated service accounts with minimal permissions
2. **Network Policies**: Implement network policies to restrict traffic
3. **Secret Management**: Use external secret management systems in production
4. **Image Security**: Scan images for vulnerabilities regularly
{% if values.tlsEnabled %}5. **TLS Configuration**: Ensure proper certificate management{% endif %}

## Support

For issues related to:
- **Kro ResourceGroups**: Check the [Kro documentation](https://github.com/awslabs/kro)
- **Backstage integration**: Contact the platform team
- **Application-specific issues**: Check application logs and configuration
- **Infrastructure issues**: Contact the infrastructure team