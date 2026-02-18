---
inclusion: fileMatch
fileMatchPattern: "applications/**/*"
---

# Application Development Guidelines

## Application Structure

Each application in `/applications` follows a consistent structure:
```
applications/<language>/
├── src/                 # Source code
├── Dockerfile          # Container image definition
├── k8s/                # Kubernetes manifests
├── .gitlab-ci.yml      # CI/CD pipeline
├── README.md           # Documentation
└── catalog-info.yaml   # Backstage catalog entry
```

## Supported Languages & Frameworks

### Java
- **Spring Boot**: Enterprise Java applications
- **Micronaut**: Lightweight microservices
- **Build Tools**: Maven or Gradle
- **Containerization**: Jib or Dockerfile

### Node.js
- **Express**: REST APIs
- **Next.js**: Full-stack React applications
- **Package Manager**: npm or yarn
- **TypeScript**: Preferred for type safety

### Python
- **FastAPI**: Modern async APIs
- **Flask**: Lightweight web applications
- **Django**: Full-featured web framework
- **Package Manager**: pip with requirements.txt or Poetry

### Go
- **Standard Library**: Minimal dependencies
- **Gin/Echo**: Web frameworks
- **Build**: Static binaries for containers

### .NET
- **ASP.NET Core**: Cross-platform web apps
- **Minimal APIs**: Lightweight endpoints
- **Container**: Multi-stage Dockerfile

## Containerization Best Practices

### Multi-Stage Builds
Use multi-stage builds to minimize image size:
```dockerfile
# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

# Runtime stage
FROM node:18-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
USER node
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

### Image Optimization
- Use Alpine or distroless base images
- Remove build dependencies in final stage
- Leverage layer caching
- Use .dockerignore to exclude unnecessary files
- Run as non-root user

### Health Checks
Implement health and readiness endpoints:
```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1
```

## Kubernetes Manifests

### Required Resources
Each application should include:
1. **Deployment**: Application pods
2. **Service**: Network access
3. **ConfigMap**: Configuration data
4. **HorizontalPodAutoscaler**: Auto-scaling
5. **ServiceAccount**: Pod identity

### Deployment Best Practices
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  labels:
    app: my-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      serviceAccountName: my-app
      containers:
      - name: app
        image: my-app:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        env:
        - name: LOG_LEVEL
          value: "info"
```

## CI/CD Integration

### GitLab CI Pipeline
Standard pipeline stages:
1. **Build**: Compile and test
2. **Containerize**: Build Docker image
3. **Push**: Push to ECR
4. **Deploy**: Update GitOps repo

## Observability

### Logging
- Use structured logging (JSON format)
- Include correlation IDs for request tracing
- Log at appropriate levels (ERROR, WARN, INFO, DEBUG)
- Avoid logging sensitive data

### Metrics
Expose Prometheus metrics:
- Request count and duration
- Error rates
- Business metrics
- Resource utilization

### Tracing
- Implement distributed tracing
- Use OpenTelemetry SDK
- Propagate trace context

## Security

### Application Security
- Validate all inputs
- Use parameterized queries
- Implement authentication/authorization
- Keep dependencies updated
- Scan for vulnerabilities

### Container Security
- Scan images for CVEs
- Use minimal base images
- Run as non-root user
- Set read-only root filesystem
- Drop unnecessary capabilities

## Backstage Integration

### Catalog Registration
Create `catalog-info.yaml`:
```yaml
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: my-app
  description: My application
  annotations:
    backstage.io/kubernetes-id: my-app
    argocd/app-name: my-app
spec:
  type: service
  lifecycle: production
  owner: team-name
```
