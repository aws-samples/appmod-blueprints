# Agent Platform Troubleshooting Guide

This guide helps you diagnose and resolve common issues with the agent platform.

## Table of Contents

1. [Deployment Issues](#deployment-issues)
2. [Kagent Issues](#kagent-issues)
3. [LiteLLM Issues](#litellm-issues)
4. [Langfuse Issues](#langfuse-issues)
5. [Tofu Controller Issues](#tofu-controller-issues)
6. [Agent Core Issues](#agent-core-issues)
7. [Networking Issues](#networking-issues)
8. [Performance Issues](#performance-issues)
9. [Diagnostic Commands](#diagnostic-commands)

---

## Deployment Issues

### Issue: Agent Platform Not Deploying

**Symptoms**:
- No agent platform applications in ArgoCD
- Individual component applications not created
- Feature flag appears enabled but nothing happens

**Diagnosis**:
```bash
# Check feature flag
kubectl get configmap -n argocd -o yaml | grep -A 5 agent-platform

# Check for individual applications
kubectl get applications -n argocd | grep agent-platform

# Check bridge chart deployment
helm list -n argocd | grep agent-platform

# Check ArgoCD application controller logs
kubectl logs -n argocd deployment/argocd-application-controller --tail=100
```

**Solutions**:

1. **Feature flag not properly set**:
```bash
# Verify bootstrap configuration
cat gitops/addons/bootstrap/default/addons.yaml | grep -A 2 agent-platform

# Should show:
# agent-platform:
#   enabled: true

# If not, update and commit
vim gitops/addons/bootstrap/default/addons.yaml
git commit -am "Enable agent platform"
git push
```

2. **Bridge chart not deployed**:
```bash
# Check if bridge chart exists
helm list -n argocd | grep agent-platform

# If not, manually deploy
cd gitops/addons/charts/agent-platform
helm install agent-platform . -n argocd \
  --set enabled=true \
  -f ../../default/addons/agent-platform/values.yaml
```

3. **Application controller issues**:
```bash
# Restart application controller
kubectl rollout restart deployment/argocd-application-controller -n argocd

# Wait for restart
kubectl rollout status deployment/argocd-application-controller -n argocd
```

### Issue: Applications Stuck in Progressing

**Symptoms**:
- Applications created but stuck in "Progressing" state
- Sync never completes
- Resources not appearing in cluster

**Diagnosis**:
```bash
# Check application status
argocd app get agent-platform-kagent

# Check sync status
kubectl get application agent-platform-kagent -n argocd -o yaml

# Check events
kubectl get events -n argocd --sort-by='.lastTimestamp' | grep agent-platform
```

**Solutions**:

1. **Sync wave issues**:
```bash
# Check if dependencies are ready
kubectl get applications -n argocd | grep agent-platform

# Manually sync in order
argocd app sync agent-platform-tofu-controller --force
argocd app sync agent-platform-kagent-crds --force
argocd app sync agent-platform-kagent --force
```

2. **External repository access issues**:
```bash
# Test Git repository access
git ls-remote https://github.com/aws-samples/sample-agent-platform-on-eks

# Check ArgoCD repository credentials
argocd repo list

# Add repository if missing
argocd repo add https://github.com/aws-samples/sample-agent-platform-on-eks
```

3. **Resource conflicts**:
```bash
# Check for existing resources
kubectl get all -n agent-platform

# Delete conflicting resources
kubectl delete deployment kagent -n agent-platform

# Retry sync
argocd app sync agent-platform-kagent --force
```

---

## Kagent Issues

### Issue: Kagent Pods CrashLoopBackOff

**Symptoms**:
- Kagent pods repeatedly crashing
- Error logs showing authentication failures
- Pods in CrashLoopBackOff state

**Diagnosis**:
```bash
# Check pod status
kubectl get pods -n agent-platform -l app=kagent

# Check logs
kubectl logs -n agent-platform deployment/kagent --tail=100

# Check events
kubectl describe pod -n agent-platform -l app=kagent
```

**Solutions**:

1. **IAM role not configured**:
```bash
# Check service account annotation
kubectl get sa kagent -n agent-platform -o yaml | grep role-arn

# Should show:
# eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/KagentRole

# If missing, add annotation
kubectl annotate sa kagent -n agent-platform \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/KagentRole

# Restart pods
kubectl rollout restart deployment/kagent -n agent-platform
```

2. **IAM permissions insufficient**:
```bash
# Test AWS credentials from pod
kubectl run -it --rm aws-cli --image=amazon/aws-cli --restart=Never \
  --serviceaccount=kagent -n agent-platform -- \
  sts get-caller-identity

# Test Bedrock access
kubectl run -it --rm aws-cli --image=amazon/aws-cli --restart=Never \
  --serviceaccount=kagent -n agent-platform -- \
  bedrock list-foundation-models --region us-east-1

# If fails, update IAM policy
aws iam put-role-policy --role-name KagentRole \
  --policy-name BedrockAccess \
  --policy-document file://kagent-policy.json
```

3. **CRDs not installed**:
```bash
# Check CRDs
kubectl get crd | grep kagent

# Should show:
# agents.kagent.dev
# modelconfigs.kagent.dev
# toolservers.kagent.dev

# If missing, install CRDs
argocd app sync agent-platform-kagent-crds --force
```

### Issue: Agent Creation Fails

**Symptoms**:
- Agent CR created but not becoming ready
- Agent status shows errors
- No agent pods created

**Diagnosis**:
```bash
# Check agent status
kubectl get agent -n agent-platform

# Describe agent
kubectl describe agent my-agent -n agent-platform

# Check operator logs
kubectl logs -n agent-platform deployment/kagent --tail=100
```

**Solutions**:

1. **Invalid model configuration**:
```yaml
# Verify model name is correct
kubectl get agent my-agent -n agent-platform -o yaml

# Update with correct model
kubectl patch agent my-agent -n agent-platform --type=merge -p '
spec:
  modelConfig:
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
'
```

2. **Model access not enabled**:
```bash
# Enable model access in AWS console
# Or via CLI
aws bedrock put-model-invocation-logging-configuration \
  --region us-east-1 \
  --logging-config '{
    "cloudWatchConfig": {
      "logGroupName": "/aws/bedrock/modelinvocations",
      "roleArn": "arn:aws:iam::ACCOUNT:role/BedrockLoggingRole"
    }
  }'
```

---

## LiteLLM Issues

### Issue: LiteLLM Cannot Connect to Bedrock

**Symptoms**:
- LiteLLM health check failing
- Errors in logs about AWS credentials
- Requests timing out

**Diagnosis**:
```bash
# Check pod status
kubectl get pods -n agent-platform -l app=litellm

# Check logs
kubectl logs -n agent-platform deployment/litellm --tail=100

# Test health endpoint
kubectl exec -it deployment/litellm -n agent-platform -- \
  curl http://localhost:4000/health
```

**Solutions**:

1. **AWS region not set**:
```bash
# Check environment variables
kubectl exec -it deployment/litellm -n agent-platform -- env | grep AWS

# Update deployment
kubectl set env deployment/litellm -n agent-platform \
  AWS_REGION=us-east-1
```

2. **Service account missing IAM role**:
```bash
# Check service account
kubectl get sa litellm -n agent-platform -o yaml

# Add IAM role annotation
kubectl annotate sa litellm -n agent-platform \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/LiteLLMRole

# Restart deployment
kubectl rollout restart deployment/litellm -n agent-platform
```

3. **Network connectivity issues**:
```bash
# Test Bedrock endpoint connectivity
kubectl exec -it deployment/litellm -n agent-platform -- \
  curl -v https://bedrock-runtime.us-east-1.amazonaws.com

# Check security groups and NACLs
# Ensure outbound HTTPS (443) is allowed
```

### Issue: High Latency in LiteLLM

**Symptoms**:
- Requests taking longer than expected
- Timeouts occurring
- Poor user experience

**Diagnosis**:
```bash
# Check metrics
kubectl port-forward -n agent-platform svc/litellm 4000:4000
curl http://localhost:4000/metrics | grep duration

# Check resource usage
kubectl top pods -n agent-platform -l app=litellm

# Check HPA status
kubectl get hpa -n agent-platform
```

**Solutions**:

1. **Insufficient resources**:
```bash
# Increase resources
kubectl patch deployment litellm -n agent-platform --type=merge -p '
spec:
  template:
    spec:
      containers:
      - name: litellm
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
'
```

2. **Need more replicas**:
```bash
# Scale up
kubectl scale deployment litellm -n agent-platform --replicas=5

# Or enable autoscaling
kubectl autoscale deployment litellm -n agent-platform \
  --min=3 --max=10 --cpu-percent=70
```

3. **Enable caching**:
```yaml
# Update configuration
litellm:
  cache:
    enabled: true
    type: redis
    endpoint: redis://redis:6379
    ttl: 3600
```

---

## Langfuse Issues

### Issue: Langfuse UI Not Accessible

**Symptoms**:
- Cannot access Langfuse web interface
- Port forward not working
- Ingress not routing traffic

**Diagnosis**:
```bash
# Check pod status
kubectl get pods -n agent-platform -l app=langfuse

# Check service
kubectl get svc langfuse -n agent-platform

# Test port forward
kubectl port-forward -n agent-platform svc/langfuse 3000:3000
curl http://localhost:3000
```

**Solutions**:

1. **Pod not ready**:
```bash
# Check pod logs
kubectl logs -n agent-platform deployment/langfuse --tail=100

# Check readiness probe
kubectl describe pod -n agent-platform -l app=langfuse

# If database connection issues, check PostgreSQL
kubectl get pods -n agent-platform -l app=langfuse-postgres
```

2. **Database connection issues**:
```bash
# Check PostgreSQL pod
kubectl get pods -n agent-platform -l app=langfuse-postgres

# Check database logs
kubectl logs -n agent-platform statefulset/langfuse-postgres --tail=100

# Test database connection
kubectl exec -it langfuse-postgres-0 -n agent-platform -- \
  psql -U langfuse -d langfuse -c "SELECT 1;"
```

3. **Ingress not configured**:
```bash
# Check ingress
kubectl get ingress -n agent-platform

# If missing, create ingress
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: langfuse
  namespace: agent-platform
spec:
  rules:
    - host: langfuse.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: langfuse
                port:
                  number: 3000
EOF
```

### Issue: Langfuse Database Full

**Symptoms**:
- Langfuse errors about disk space
- PostgreSQL pod evicted
- Cannot write new traces

**Diagnosis**:
```bash
# Check PVC usage
kubectl exec -it langfuse-postgres-0 -n agent-platform -- df -h

# Check PVC size
kubectl get pvc -n agent-platform
```

**Solutions**:

1. **Expand PVC**:
```bash
# Edit PVC (if storage class supports expansion)
kubectl patch pvc langfuse-postgres-data-0 -n agent-platform -p '
spec:
  resources:
    requests:
      storage: 20Gi
'

# Restart pod to apply
kubectl delete pod langfuse-postgres-0 -n agent-platform
```

2. **Clean old data**:
```bash
# Connect to database
kubectl exec -it langfuse-postgres-0 -n agent-platform -- \
  psql -U langfuse -d langfuse

# Delete old traces (older than 30 days)
DELETE FROM traces WHERE created_at < NOW() - INTERVAL '30 days';

# Vacuum database
VACUUM FULL;
```

---

## Tofu Controller Issues

### Issue: Terraform Resources Not Provisioning

**Symptoms**:
- Terraform CR stuck in pending
- No AWS resources created
- Tofu Controller logs show errors

**Diagnosis**:
```bash
# Check Terraform CR status
kubectl get terraform -n agent-platform

# Describe Terraform CR
kubectl describe terraform agent-core -n agent-platform

# Check Tofu Controller logs
kubectl logs -n flux-system deployment/tofu-controller --tail=100
```

**Solutions**:

1. **IAM permissions insufficient**:
```bash
# Check service account
kubectl get sa tofu-controller -n flux-system -o yaml

# Test AWS credentials
kubectl run -it --rm aws-cli --image=amazon/aws-cli --restart=Never \
  --serviceaccount=tofu-controller -n flux-system -- \
  sts get-caller-identity

# Update IAM policy
aws iam put-role-policy --role-name TofuControllerRole \
  --policy-name BedrockAgentAccess \
  --policy-document file://tofu-policy.json
```

2. **Terraform source not accessible**:
```bash
# Check GitRepository
kubectl get gitrepository -n flux-system

# Check source controller logs
kubectl logs -n flux-system deployment/source-controller --tail=100

# Manually test Git access
git ls-remote https://github.com/elamaran11/eks-agent-core-pocs
```

3. **Terraform state issues**:
```bash
# Check Terraform state secret
kubectl get secret -n agent-platform | grep tfstate

# Delete and recreate if corrupted
kubectl delete terraform agent-core -n agent-platform
kubectl apply -f terraform-cr.yaml
```

### Issue: Terraform Apply Fails

**Symptoms**:
- Terraform plan succeeds but apply fails
- AWS API errors in logs
- Resources partially created

**Diagnosis**:
```bash
# Check Terraform CR status
kubectl get terraform agent-core -n agent-platform -o yaml

# Check detailed logs
kubectl logs -n flux-system deployment/tofu-controller --tail=200 | grep agent-core
```

**Solutions**:

1. **AWS service limits**:
```bash
# Check service quotas
aws service-quotas list-service-quotas \
  --service-code bedrock \
  --region us-east-1

# Request quota increase if needed
aws service-quotas request-service-quota-increase \
  --service-code bedrock \
  --quota-code L-12345678 \
  --desired-value 10
```

2. **Resource conflicts**:
```bash
# Check existing AWS resources
aws bedrock list-agents --region us-east-1

# Delete conflicting resources
aws bedrock delete-agent --agent-id AGENT_ID --region us-east-1

# Retry Terraform
kubectl annotate terraform agent-core -n agent-platform \
  reconcile.fluxcd.io/requestedAt="$(date +%s)"
```

---

## Networking Issues

### Issue: Components Cannot Communicate

**Symptoms**:
- Agent Gateway cannot reach LiteLLM
- Kagent cannot reach Jaeger
- Timeouts between services

**Diagnosis**:
```bash
# Test service DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- \
  nslookup litellm.agent-platform.svc.cluster.local

# Test service connectivity
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://litellm.agent-platform:4000/health

# Check network policies
kubectl get networkpolicies -n agent-platform
```

**Solutions**:

1. **Network policy blocking traffic**:
```bash
# Check network policies
kubectl get networkpolicy -n agent-platform -o yaml

# Temporarily disable for testing
kubectl delete networkpolicy --all -n agent-platform

# If that fixes it, update network policy to allow required traffic
```

2. **Service not created**:
```bash
# Check services
kubectl get svc -n agent-platform

# If missing, create service
kubectl expose deployment litellm -n agent-platform \
  --port=4000 --target-port=4000 --name=litellm
```

3. **DNS issues**:
```bash
# Check CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Restart CoreDNS if needed
kubectl rollout restart deployment/coredns -n kube-system
```

---

## Performance Issues

### Issue: High CPU Usage

**Symptoms**:
- Pods using 100% CPU
- Requests slowing down
- HPA scaling to max replicas

**Diagnosis**:
```bash
# Check resource usage
kubectl top pods -n agent-platform

# Check HPA status
kubectl get hpa -n agent-platform

# Check metrics
kubectl port-forward -n agent-platform svc/kagent 8080:8080
curl http://localhost:8080/metrics
```

**Solutions**:

1. **Increase CPU limits**:
```bash
# Update deployment
kubectl patch deployment kagent -n agent-platform --type=merge -p '
spec:
  template:
    spec:
      containers:
      - name: kagent
        resources:
          requests:
            cpu: "1000m"
          limits:
            cpu: "2000m"
'
```

2. **Scale horizontally**:
```bash
# Increase replicas
kubectl scale deployment kagent -n agent-platform --replicas=5

# Or adjust HPA
kubectl patch hpa kagent -n agent-platform --type=merge -p '
spec:
  maxReplicas: 20
  targetCPUUtilizationPercentage: 60
'
```

### Issue: High Memory Usage

**Symptoms**:
- Pods being OOMKilled
- Memory usage at limit
- Frequent pod restarts

**Diagnosis**:
```bash
# Check memory usage
kubectl top pods -n agent-platform

# Check pod events
kubectl get events -n agent-platform | grep OOMKilled

# Check memory limits
kubectl get pods -n agent-platform -o yaml | grep -A 5 resources
```

**Solutions**:

1. **Increase memory limits**:
```bash
# Update deployment
kubectl patch deployment litellm -n agent-platform --type=merge -p '
spec:
  template:
    spec:
      containers:
      - name: litellm
        resources:
          requests:
            memory: "2Gi"
          limits:
            memory: "4Gi"
'
```

2. **Enable caching to reduce memory pressure**:
```yaml
# Update LiteLLM configuration
litellm:
  cache:
    enabled: true
    type: redis
    maxSize: 1000
```

---

## Diagnostic Commands

### Quick Health Check

```bash
#!/bin/bash
# health-check.sh

echo "=== Agent Platform Health Check ==="

echo -e "\n1. Checking ApplicationSet..."
kubectl get applicationset -n argocd | grep agent-platform

echo -e "\n2. Checking Applications..."
kubectl get applications -n argocd | grep agent-platform

echo -e "\n3. Checking Pods..."
kubectl get pods -n agent-platform

echo -e "\n4. Checking Services..."
kubectl get svc -n agent-platform

echo -e "\n5. Checking Resource Usage..."
kubectl top pods -n agent-platform

echo -e "\n6. Checking Recent Events..."
kubectl get events -n agent-platform --sort-by='.lastTimestamp' | tail -10

echo -e "\n=== Health Check Complete ==="
```

### Collect Logs

```bash
#!/bin/bash
# collect-logs.sh

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_DIR="agent-platform-logs-$TIMESTAMP"

mkdir -p "$OUTPUT_DIR"

echo "Collecting logs to $OUTPUT_DIR..."

# Pod logs
for pod in $(kubectl get pods -n agent-platform -o name); do
  kubectl logs -n agent-platform $pod > "$OUTPUT_DIR/${pod//\//-}.log" 2>&1
done

# Describe pods
kubectl describe pods -n agent-platform > "$OUTPUT_DIR/pods-describe.txt"

# Events
kubectl get events -n agent-platform --sort-by='.lastTimestamp' > "$OUTPUT_DIR/events.txt"

# Applications
kubectl get applications -n argocd -o yaml > "$OUTPUT_DIR/applications.yaml"

# Terraform CRs
kubectl get terraform -n agent-platform -o yaml > "$OUTPUT_DIR/terraform-crs.yaml"

echo "Logs collected in $OUTPUT_DIR"
tar czf "$OUTPUT_DIR.tar.gz" "$OUTPUT_DIR"
echo "Archive created: $OUTPUT_DIR.tar.gz"
```

### Test Connectivity

```bash
#!/bin/bash
# test-connectivity.sh

echo "=== Testing Agent Platform Connectivity ==="

echo -e "\n1. Testing LiteLLM..."
kubectl run -it --rm curl --image=curlimages/curl --restart=Never -- \
  curl -s http://litellm.agent-platform:4000/health

echo -e "\n2. Testing Langfuse..."
kubectl run -it --rm curl --image=curlimages/curl --restart=Never -- \
  curl -s http://langfuse.agent-platform:3000/api/health

echo -e "\n3. Testing Jaeger..."
kubectl run -it --rm curl --image=curlimages/curl --restart=Never -- \
  curl -s http://jaeger.agent-platform:16686/

echo -e "\n4. Testing DNS Resolution..."
kubectl run -it --rm busybox --image=busybox --restart=Never -- \
  nslookup litellm.agent-platform.svc.cluster.local

echo -e "\n=== Connectivity Test Complete ==="
```

---

## Getting Help

If you're still experiencing issues:

1. **Check GitHub Issues**: [appmod-blueprints/issues](https://github.com/aws-samples/appmod-blueprints/issues)
2. **Review Documentation**: [DESIGN.md](./DESIGN.md), [README.md](./README.md), [COMPONENTS.md](./COMPONENTS.md)
3. **Contact Support**: Reach out to your AWS account team
4. **Community**: Join discussions in GitHub Discussions

When reporting issues, please include:
- Output from health check script
- Relevant logs (use collect-logs.sh)
- Kubernetes version and EKS version
- Steps to reproduce the issue
