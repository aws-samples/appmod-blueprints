---
inclusion: fileMatch
fileMatchPattern: "**/rollouts/**/*,**/flagger/**/*"
---

# Progressive Delivery Guidelines

## Argo Rollouts

Progressive delivery and advanced deployment strategies.

**Location**: Integrated via ArgoCD addon

**Documentation**: 
- `docs/Argo-Rollouts-Metrics-Driven-Deployment.md`
- `docs/Argo-Rollouts-Metrics-Driven-Progressive-Delivery.md`
- `docs/Argo-Rollouts-Metrics-Manifest.md`

## Deployment Strategies

### Blue-Green Deployment
Zero-downtime deployment with instant rollback.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
spec:
  replicas: 3
  strategy:
    blueGreen:
      activeService: my-app-active
      previewService: my-app-preview
      autoPromotionEnabled: false
      scaleDownDelaySeconds: 30
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: my-app:v2
```

**Use When**:
- Need instant rollback capability
- Can afford duplicate resources
- Testing in production-like environment

### Canary Deployment
Gradual traffic shift with automated analysis.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
spec:
  replicas: 5
  strategy:
    canary:
      steps:
      - setWeight: 20
      - pause: {duration: 5m}
      - setWeight: 40
      - pause: {duration: 5m}
      - setWeight: 60
      - pause: {duration: 5m}
      - setWeight: 80
      - pause: {duration: 5m}
      analysis:
        templates:
        - templateName: success-rate
        startingStep: 2
        args:
        - name: service-name
          value: my-app
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: my-app:v2
```

**Use When**:
- Want gradual rollout
- Need automated analysis
- Risk mitigation is priority
- Have good metrics

## Analysis Templates

### Success Rate Analysis
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  args:
  - name: service-name
  metrics:
  - name: success-rate
    interval: 1m
    successCondition: result[0] >= 0.95
    failureLimit: 3
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          sum(rate(
            http_requests_total{
              service="{{args.service-name}}",
              status!~"5.."
            }[5m]
          )) /
          sum(rate(
            http_requests_total{
              service="{{args.service-name}}"
            }[5m]
          ))
```

### Latency Analysis
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: latency
spec:
  args:
  - name: service-name
  metrics:
  - name: p95-latency
    interval: 1m
    successCondition: result[0] <= 500
    failureLimit: 3
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          histogram_quantile(0.95,
            rate(http_request_duration_seconds_bucket{
              service="{{args.service-name}}"
            }[5m])
          ) * 1000
```

## Metrics-Driven Deployment

### Required Metrics
Applications must expose:
1. **Request Rate**: Total requests per second
2. **Error Rate**: 4xx and 5xx responses
3. **Latency**: P50, P95, P99 response times
4. **Saturation**: Resource utilization

### Prometheus Integration
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  selector:
    app: my-app
  ports:
  - port: 8080
    targetPort: 8080
```

## Best Practices

### Rollout Configuration
- Start with small traffic percentages
- Use appropriate pause durations
- Implement multiple analysis metrics
- Set reasonable failure limits
- Configure automatic rollback

### Monitoring
- Monitor both versions during rollout
- Track business metrics
- Set up alerts for anomalies
- Log rollout events
- Review rollout history

### Rollback Strategy
- Define clear rollback criteria
- Test rollback procedures
- Automate rollback on failures
- Document rollback process
- Communicate rollback events
