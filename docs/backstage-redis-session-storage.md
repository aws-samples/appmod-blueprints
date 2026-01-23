# Backstage Redis Session Storage Implementation

## Problem Statement

Backstage stores OAuth session state in memory by default. When Backstage pods restart or Keycloak pods restart, all active user sessions become invalid, causing authentication errors:

- `error="expired_code"` in Keycloak logs
- `401` errors on `/api/auth/keycloak-oidc/refresh` in Backstage logs
- Users see "Login timeout" or "invalid_grant" errors

**Root Cause:** In-memory session storage doesn't survive pod restarts, and Keycloak session invalidation isn't communicated to Backstage.

## Solution: Redis Session Storage

Using Redis as a shared session store ensures sessions persist across:
- Backstage pod restarts
- Backstage rolling updates
- Horizontal scaling (multiple Backstage replicas)

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Backstage  │────▶│    Redis    │◀────│  Backstage  │
│   Pod 1     │     │   (Shared   │     │   Pod 2     │
│             │     │   Sessions) │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
       │                                        │
       └────────────────┬───────────────────────┘
                        │
                        ▼
                 ┌─────────────┐
                 │  Keycloak   │
                 │   (OIDC)    │
                 └─────────────┘
```

## Implementation Steps

### Step 1: Deploy Redis

Add Redis to the platform addons:

**File:** `gitops/addons/bootstrap/default/addons.yaml`

```yaml
redis:
  enabled: false
  annotationsAppSet:
    argocd.argoproj.io/sync-wave: '2'
  namespace: redis
  chartName: redis
  chartRepository: https://charts.bitnami.com/bitnami
  defaultVersion: '18.4.0'
  selector:
    matchExpressions:
      - key: enable_redis
        operator: In
        values: ['true']
  valuesObject:
    global:
      resourcePrefix: '{{.metadata.annotations.resource_prefix}}'
    architecture: standalone
    auth:
      enabled: true
      password: '{{.metadata.annotations.redis_password}}'
    master:
      persistence:
        enabled: true
        size: 8Gi
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          memory: 256Mi
    replica:
      replicaCount: 0  # Standalone mode for simplicity
```

**Enable in environment:**

**File:** `gitops/addons/environments/control-plane/addons.yaml`

```yaml
redis:
  enabled: true
```

**Enable in cluster:**

**File:** `platform/infra/terraform/hub-config.yaml`

```yaml
clusters:
  hub:
    addons:
      enable_redis: true
```

### Step 2: Create Redis Password Secret

Add Redis password to AWS Secrets Manager:

```bash
# Get current secrets
SECRETS=$(aws secretsmanager get-secret-value \
  --secret-id peeks-hub/secrets \
  --query SecretString --output text)

# Add Redis password
UPDATED_SECRETS=$(echo $SECRETS | jq '. + {"redis_password": "'$(openssl rand -base64 32)'"}')

# Update secret
aws secretsmanager update-secret \
  --secret-id peeks-hub/secrets \
  --secret-string "$UPDATED_SECRETS"
```

### Step 3: Update Backstage Configuration

**File:** `gitops/addons/charts/backstage/values.yaml`

Add Redis session configuration:

```yaml
backstage:
  appConfig:
    auth:
      environment: development
      session:
        secret: ${SESSION_SECRET}
        store: redis
        redis:
          host: redis-master.redis.svc.cluster.local
          port: 6379
          password: ${REDIS_PASSWORD}
          db: 0
          ttl: 86400  # 24 hours
          prefix: 'backstage:session:'
```

### Step 4: Add Redis Password to External Secrets

**File:** `gitops/addons/charts/backstage/templates/external-secret.yaml`

Add Redis password retrieval:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: backstage-secrets
  namespace: {{ .Values.namespace }}
spec:
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: backstage-secrets
    creationPolicy: Owner
  data:
    - secretKey: POSTGRES_PASSWORD
      remoteRef:
        key: '{{.Values.global.aws_cluster_name}}/secrets'
        property: backstage_postgresql_password
    - secretKey: KEYCLOAK_CLIENT_SECRET
      remoteRef:
        key: '{{.Values.global.aws_cluster_name}}/secrets'
        property: backstage_client_secret
    - secretKey: SESSION_SECRET
      remoteRef:
        key: '{{.Values.global.aws_cluster_name}}/secrets'
        property: backstage_session_secret
    - secretKey: REDIS_PASSWORD
      remoteRef:
        key: '{{.Values.global.aws_cluster_name}}/secrets'
        property: redis_password
```

### Step 5: Update Backstage Deployment

**File:** `gitops/addons/charts/backstage/templates/deployment.yaml`

Add Redis password environment variable:

```yaml
env:
  - name: REDIS_PASSWORD
    valueFrom:
      secretKeyRef:
        name: backstage-secrets
        key: REDIS_PASSWORD
  # ... other env vars
```

### Step 6: Install Redis Client Dependency

**File:** `gitops/addons/charts/backstage/templates/configmap.yaml`

Update the app-config to include Redis session store configuration:

```yaml
auth:
  environment: development
  session:
    secret: ${SESSION_SECRET}
    store: redis
    redis:
      host: ${REDIS_HOST:-redis-master.redis.svc.cluster.local}
      port: ${REDIS_PORT:-6379}
      password: ${REDIS_PASSWORD}
      db: 0
      ttl: 86400
      prefix: 'backstage:session:'
```

### Step 7: Deploy Changes

```bash
# 1. Update secrets in AWS Secrets Manager (done in Step 2)

# 2. Commit GitOps changes
cd /home/ec2-user/environment/platform-on-eks-workshop
git add gitops/addons/
git commit -m "Add Redis session storage for Backstage"
git push

# 3. Apply Terraform to enable Redis addon
cd platform/infra/terraform/common
./deploy.sh

# 4. Wait for Redis deployment
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=redis -n redis --timeout=300s

# 5. Restart Backstage to pick up new configuration
kubectl rollout restart deployment/backstage -n backstage
kubectl rollout status deployment/backstage -n backstage
```

## Verification

### 1. Check Redis is Running

```bash
kubectl get pods -n redis
# Should show: redis-master-0   1/1   Running
```

### 2. Test Redis Connection

```bash
kubectl exec -n redis redis-master-0 -- redis-cli -a $(kubectl get secret redis -n redis -o jsonpath='{.data.redis-password}' | base64 -d) ping
# Should return: PONG
```

### 3. Verify Backstage Session Storage

```bash
# Login to Backstage
# Then check Redis for session keys
kubectl exec -n redis redis-master-0 -- redis-cli -a $(kubectl get secret redis -n redis -o jsonpath='{.data.redis-password}' | base64 -d) KEYS "backstage:session:*"
# Should show session keys
```

### 4. Test Session Persistence

```bash
# 1. Login to Backstage
# 2. Restart Backstage pod
kubectl delete pod -n backstage -l app.kubernetes.io/name=backstage
# 3. Refresh Backstage - should still be logged in
```

## Benefits

### Session Persistence
- Sessions survive Backstage pod restarts
- Sessions survive Backstage rolling updates
- Sessions survive Keycloak restarts (until token expiry)

### Horizontal Scaling
- Multiple Backstage replicas share session state
- Load balancer can route to any pod
- No sticky sessions required

### Operational Improvements
- Reduced authentication errors
- Better user experience during deployments
- Easier troubleshooting (sessions visible in Redis)

## Monitoring

### Redis Metrics

Monitor these Redis metrics:

```bash
# Session count
kubectl exec -n redis redis-master-0 -- redis-cli -a $REDIS_PASSWORD DBSIZE

# Memory usage
kubectl exec -n redis redis-master-0 -- redis-cli -a $REDIS_PASSWORD INFO memory | grep used_memory_human

# Connected clients (should match Backstage pod count)
kubectl exec -n redis redis-master-0 -- redis-cli -a $REDIS_PASSWORD INFO clients | grep connected_clients
```

### Backstage Logs

Check for Redis connection issues:

```bash
kubectl logs -n backstage deployment/backstage | grep -i redis
```

## Troubleshooting

### Issue: Backstage can't connect to Redis

**Symptoms:**
- Backstage logs show `ECONNREFUSED` or `Redis connection failed`
- Users can't login

**Solution:**
```bash
# Check Redis is running
kubectl get pods -n redis

# Check Redis service
kubectl get svc -n redis

# Test connection from Backstage pod
kubectl exec -n backstage deployment/backstage -- nc -zv redis-master.redis.svc.cluster.local 6379
```

### Issue: Authentication still fails after Redis implementation

**Symptoms:**
- Sessions exist in Redis but auth fails
- `invalid_token` errors in Keycloak logs

**Solution:**
This indicates Keycloak token expiry, not session issues. Check token lifetimes:

```bash
# Keycloak token settings (default: 5 minutes for access token)
# Sessions persist but tokens need refresh
# Ensure Backstage refresh token flow is working
```

### Issue: Redis memory usage growing

**Symptoms:**
- Redis memory continuously increases
- Old sessions not expiring

**Solution:**
```bash
# Check TTL is set correctly
kubectl exec -n redis redis-master-0 -- redis-cli -a $REDIS_PASSWORD TTL "backstage:session:SOME_KEY"

# Should return positive number (seconds until expiry)
# If -1, TTL not set - check session.ttl in config
```

## Alternative: Redis Sentinel for HA

For production, use Redis Sentinel for high availability:

```yaml
redis:
  valuesObject:
    architecture: replication
    sentinel:
      enabled: true
      quorum: 2
    master:
      persistence:
        enabled: true
    replica:
      replicaCount: 2
      persistence:
        enabled: true
```

Update Backstage config:

```yaml
auth:
  session:
    redis:
      sentinels:
        - host: redis-sentinel.redis.svc.cluster.local
          port: 26379
      name: mymaster
      password: ${REDIS_PASSWORD}
```

## Security Considerations

### 1. Redis Password Rotation

Rotate Redis password periodically:

```bash
# Generate new password
NEW_PASSWORD=$(openssl rand -base64 32)

# Update in AWS Secrets Manager
aws secretsmanager update-secret \
  --secret-id peeks-hub/secrets \
  --secret-string "$(aws secretsmanager get-secret-value --secret-id peeks-hub/secrets --query SecretString --output text | jq --arg pwd "$NEW_PASSWORD" '.redis_password = $pwd')"

# External Secrets Operator will sync automatically
# Restart Backstage to pick up new password
kubectl rollout restart deployment/backstage -n backstage
```

### 2. Network Policies

Restrict Redis access to Backstage only:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: redis-access
  namespace: redis
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: redis
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: backstage
      ports:
        - protocol: TCP
          port: 6379
```

### 3. TLS Encryption

For production, enable TLS for Redis connections:

```yaml
redis:
  valuesObject:
    tls:
      enabled: true
      authClients: true
      autoGenerated: true
```

## Cost Considerations

**Redis Resource Usage:**
- Standalone: ~128Mi memory, 100m CPU
- With replication: ~384Mi memory (3 pods), 300m CPU

**Session Storage:**
- Average session size: ~2KB
- 1000 concurrent users: ~2MB
- Redis overhead: ~50MB base

**Total:** ~200Mi memory for typical workload

## Migration from In-Memory Sessions

If migrating from existing in-memory sessions:

1. Deploy Redis (sessions will be empty)
2. Update Backstage config to use Redis
3. Rolling restart Backstage (users will need to re-login once)
4. Monitor Redis for session creation
5. Old in-memory sessions are lost (expected)

**User Impact:** One-time re-authentication required during migration.

## Limitations: Keycloak Restarts

**Important:** Redis session storage **only solves Backstage restart issues**, not Keycloak restart issues.

### What Happens When Keycloak Restarts:

1. Keycloak invalidates all issued tokens (access tokens, refresh tokens)
2. Backstage sessions in Redis still exist but contain invalid tokens
3. When users try to use Backstage, token refresh fails
4. Users must re-authenticate

### Session Persistence Matrix:

| Event | Without Redis | With Redis | With Keycloak Session Persistence |
|-------|---------------|------------|-----------------------------------|
| Backstage restart | ❌ Re-login | ✅ Stay logged in | ✅ Stay logged in |
| Keycloak restart | ❌ Re-login | ❌ Re-login | ✅ Stay logged in |
| Backstage scale-out | ❌ Inconsistent | ✅ Shared state | ✅ Shared state |

## Complete Solution: Keycloak + Backstage Session Persistence

To survive **both** Backstage and Keycloak restarts, implement both:

### 1. Keycloak Session Persistence (PostgreSQL)

Keycloak already uses PostgreSQL for user data. Ensure session persistence is enabled:

**File:** `gitops/addons/charts/keycloak/values.yaml`

```yaml
keycloak:
  # Keycloak uses Infinispan for session clustering
  # Sessions are replicated across pods but not persisted to DB by default
  
  # Enable session persistence to PostgreSQL
  extraEnv: |
    - name: KC_CACHE
      value: "ispn"
    - name: KC_CACHE_STACK
      value: "kubernetes"
    - name: KC_CACHE_CONFIG_FILE
      value: "cache-ispn-jdbc-ping.xml"
    - name: JAVA_OPTS_APPEND
      value: >-
        -Djgroups.dns.query=keycloak-headless.keycloak.svc.cluster.local
        -Dkeycloak.profile.feature.persistent_user_sessions=enabled
  
  # Ensure PostgreSQL persistence
  postgresql:
    enabled: true
    persistence:
      enabled: true
      size: 8Gi
```

**Note:** Keycloak's session persistence to database is **experimental** and has performance implications. The recommended approach is:

### 2. Recommended: Increase Token Lifetimes

Instead of persisting sessions, increase token lifetimes to reduce re-authentication frequency:

**Keycloak Realm Settings:**

```bash
# Access Keycloak admin console
# Realm Settings → Tokens

# Access Token Lifespan: 5 minutes → 1 hour
# SSO Session Idle: 30 minutes → 8 hours  
# SSO Session Max: 10 hours → 24 hours
# Client Session Idle: 30 minutes → 8 hours
# Client Session Max: 10 hours → 24 hours
```

This means:
- Users stay logged in for 8 hours of activity
- Maximum session: 24 hours
- Keycloak restart only affects users who haven't refreshed in last hour

### 3. Graceful Session Handling in Backstage

Add automatic re-authentication on token expiry:

**File:** `gitops/addons/charts/backstage/values.yaml`

```yaml
backstage:
  appConfig:
    auth:
      providers:
        keycloak-oidc:
          development:
            metadataUrl: ${KEYCLOAK_NAME_METADATA}
            clientId: backstage
            clientSecret: ${KEYCLOAK_CLIENT_SECRET}
            prompt: auto
            # Automatically redirect to login on token expiry
            signIn:
              resolvers:
                - resolver: autoSignIn
```

### 4. Session Cleanup Job

Clean up stale sessions in Redis after Keycloak restarts:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: backstage-session-cleanup
  namespace: backstage
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: redis:7-alpine
            command:
            - sh
            - -c
            - |
              # Delete sessions older than 24 hours
              redis-cli -h redis-master.redis.svc.cluster.local \
                -a $REDIS_PASSWORD \
                --scan --pattern "backstage:session:*" | \
                xargs -L 1 redis-cli -h redis-master.redis.svc.cluster.local \
                  -a $REDIS_PASSWORD DEL
            env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: backstage-secrets
                  key: REDIS_PASSWORD
          restartPolicy: OnFailure
```

## Practical Recommendations

### For Development/Testing:
- **Redis session storage** for Backstage (prevents frequent re-login during development)
- Accept that Keycloak restarts require re-authentication
- Keep default token lifetimes (5 min access, 30 min idle)

### For Production:
1. **Redis session storage** for Backstage (horizontal scaling + restart resilience)
2. **Increased token lifetimes** in Keycloak (8h idle, 24h max)
3. **Keycloak HA with 2+ replicas** (reduces restart frequency)
4. **Graceful Keycloak updates** (rolling restart, one pod at a time)
5. **Session cleanup job** (remove stale sessions)

### What Users Experience:

**With Redis + Increased Token Lifetimes:**
- Backstage updates: ✅ No re-login needed
- Keycloak updates: ⚠️ Re-login if session > 1 hour old
- Daily usage: ✅ Stay logged in all day
- Overnight: ⚠️ Re-login next morning (24h max)

## Summary

**Redis session storage solves:**
- ✅ Backstage restart issues
- ✅ Backstage horizontal scaling
- ✅ Backstage rolling updates

**Redis session storage does NOT solve:**
- ❌ Keycloak restart issues (tokens invalidated)
- ❌ Token expiry (controlled by Keycloak)

**Complete solution requires:**
1. Redis for Backstage session persistence
2. Increased Keycloak token lifetimes
3. Keycloak HA (2+ replicas)
4. Graceful update procedures

**Recommendation:** Implement Redis session storage for Backstage + increase Keycloak token lifetimes to 8h idle / 24h max. This provides the best balance of security and user experience.
