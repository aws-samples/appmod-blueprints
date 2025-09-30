# ${{ values.name }} - Kro Job ResourceGroup

${{ values.description }}

## Overview

This repository contains a Kro ResourceGroup definition for a job deployment that creates:

- **Job**: Kubernetes batch job that runs a specific task
- **Deployment**: Long-running deployment for continuous services

## Configuration

### Job Settings
- **Name**: ${{ values.name }}
- **Namespace**: ${{ values.namespace }}
- **Environment**: ${{ values.environment }}
- **Job Image**: ${{ values.jobImage }}
- **Job Command**: {{ values.jobCommand | join(' ') }}
- **Delay**: ${{ values.delayInSeconds }} seconds
- **Restart Policy**: ${{ values.restartPolicy }}
- **TTL After Finished**: ${{ values.ttlSecondsAfterFinished }} seconds

### Deployment Settings
- **Deployment Image**: ${{ values.deploymentImage }}
- **Replicas**: ${{ values.replicas }}
- **Port**: ${{ values.deploymentPort }}

## Deployment

### Prerequisites

1. Kro controller must be installed in the target Kubernetes cluster
2. Required RBAC permissions for ResourceGroup operations

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
kubectl get jobdeployment ${{ values.name }} -n ${{ values.namespace }}

# Check created resources
kubectl get job,deployment -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}

# Check job status
kubectl get job ${{ values.name }}-job -n ${{ values.namespace }}

# Check deployment status
kubectl get deployment ${{ values.name }} -n ${{ values.namespace }}

# Check pods
kubectl get pods -n ${{ values.namespace }} -l app.kubernetes.io/name=${{ values.name }}
```

## Customization

You can customize the deployment by modifying the `instance.yaml` file:

```yaml
apiVersion: kro.run/v1alpha1
kind: JobDeployment
metadata:
  name: ${{ values.name }}
  namespace: ${{ values.namespace }}
spec:
  # Job configuration
  delayInSeconds: 60
  jobImage: your-custom-job-image:latest
  restartPolicy: OnFailure
  ttlSecondsAfterFinished: 600
  
  # Deployment configuration
  replicas: 2
  deploymentImage: your-custom-app:latest
  deploymentPort: 8080
```

## Monitoring

### Check Job Progress

```bash
# Watch job completion
kubectl get job ${{ values.name }}-job -n ${{ values.namespace }} -w

# Check job logs
kubectl logs job/${{ values.name }}-job -n ${{ values.namespace }}
```

### Check Deployment Status

```bash
# Check deployment status
kubectl get deployment ${{ values.name }} -n ${{ values.namespace }}

# Check deployment logs
kubectl logs deployment/${{ values.name }} -n ${{ values.namespace }} -f
```

## Troubleshooting

### Common Issues

1. **ResourceGroup not found**: Ensure Kro controller is installed and running
2. **Job failing**: Check job logs and resource limits
3. **Deployment not starting**: Verify image availability and resource constraints

### Debug Commands

```bash
# Check ResourceGroup status
kubectl describe jobdeployment ${{ values.name }} -n ${{ values.namespace }}

# Check job details
kubectl describe job ${{ values.name }}-job -n ${{ values.namespace }}

# Check deployment details
kubectl describe deployment ${{ values.name }} -n ${{ values.namespace }}

# Check events
kubectl get events -n ${{ values.namespace }} --sort-by='.lastTimestamp'
```

### Job Lifecycle

1. **Job Creation**: The job is created when the ResourceGroup instance is applied
2. **Job Execution**: The job runs the specified command for the configured duration
3. **Job Completion**: The job completes and shows completion time
4. **Cleanup**: {% if values.ttlSecondsAfterFinished > 0 %}Job is automatically cleaned up after ${{ values.ttlSecondsAfterFinished }} seconds{% else %}Job is kept indefinitely (TTL disabled){% endif %}

## Support

For issues related to:
- **Kro ResourceGroups**: Check the [Kro documentation](https://github.com/awslabs/kro)
- **Backstage integration**: Contact the platform team
- **Job-specific issues**: Check job logs and configuration