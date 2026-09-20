# EKS Runtime & Network Security

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Runtime threat detection, network policy enforcement, security groups for pods, and encryption in transit

**For core IAM, pod security, and secrets, see:** [Security](security.md)
**For supply chain, infrastructure, and compliance, see:** [Supply Chain & Compliance](security-supply-chain.md)

---

## Table of Contents

1. [Runtime Security](#runtime-security)
2. [Network Security](#network-security)
3. [Encryption in Transit](#encryption-in-transit)
4. [Detective Controls](#detective-controls)

---

## Runtime Security

### Amazon GuardDuty for EKS

**Enable EKS Runtime Monitoring** as the first line of defense. GuardDuty analyzes K8s audit logs, VPC flow logs, and DNS logs using ML and threat intelligence to detect threats without manual configuration.

**Enable both:**
- **EKS Audit Log Monitoring** — analyzes K8s audit logs for threats
- **EKS Runtime Monitoring** — agent-based, detects container-level threats

**Key finding types:**
- `Execution:Runtime/CryptocurrencyMiningDetected`
- `PrivilegeEscalation:Runtime/DockerSocketAccess`
- `Persistence:Runtime/ReverseShell`
- `UnauthorizedAccess:IAMUser/AnomalousBehavior`

GuardDuty produces security findings viewable in the console or via EventBridge for automated response.

### Seccomp Profiles

Seccomp (secure computing) restricts which system calls a container can make, reducing the attack surface. Containers only need a fraction of the hundreds of available syscalls.

**Use RuntimeDefault as the baseline for all workloads:**

```yaml
securityContext:
  seccompProfile:
    type: RuntimeDefault
```

As of Kubernetes 1.27 (stable), you can set `RuntimeDefault` for all pods on a node using the kubelet flag `--seccomp-default`, then only override in `securityContext` for workloads needing custom profiles.

**Custom profiles** can be generated using:
- **Inspektor Gadget** — uses eBPF to record baseline syscall usage and generate seccomp profiles
- **Security Profiles Operator** — automates deploying and managing seccomp, AppArmor, and SELinux profiles across nodes

Consider adding/dropping Linux capabilities before writing seccomp policies — capabilities are coarser but simpler. Seccomp filters all syscalls before they run, while capabilities check permissions in specific kernel functions.

### AppArmor and SELinux

Both provide mandatory access control (MAC) beyond what capabilities and seccomp offer:

| Feature | AppArmor | SELinux |
|---------|----------|---------|
| **Supported on** | Debian, Ubuntu | RHEL, CentOS, Bottlerocket, Amazon Linux 2023 |
| **K8s integration** | Via annotations (pre-1.30), security context (1.30+) | Via `seLinuxOptions` in security context |
| **Granularity** | File path, network, capabilities | Labels on files/processes/ports |

**SELinux on EKS:**
- Containers use the `container_t` label, isolating them from each other
- Configure via `securityContext.seLinuxOptions` in pod spec:

```yaml
securityContext:
  seLinuxOptions:
    level: s0:c144:c154  # Unique MCS label per container
```

Bottlerocket has SELinux enabled by default, providing an additional isolation layer.

### Falco for Runtime Threat Detection

```bash
# Deploy Falco as a DaemonSet via Helm
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco \
  --namespace falco --create-namespace \
  --set driver.kind=modern_ebpf \
  --set falcosidekick.enabled=true
```

**Key detection rules for EKS:**
- Container drift detection (unexpected process execution)
- Sensitive file access (/etc/shadow, /etc/kubernetes)
- Outbound connections to suspicious IPs
- Shell spawned in container

---

## Network Security

### Network Policies

**Use EKS-native VPC CNI network policies (v1.14+):**

```yaml
# Enable network policy support in VPC CNI
aws eks create-addon --cluster-name my-cluster \
  --addon-name vpc-cni \
  --addon-version v1.14.0-eksbuild.3 \
  --configuration-values '{"enableNetworkPolicy": "true"}'
```

Network policy support is NOT enabled by default — you must enable the `ENABLE_NETWORK_POLICY` flag on the VPC CNI add-on.

### Start with Default Deny + DNS Allow

**Step 1: Default deny all traffic per namespace:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

**Step 2: Allow DNS queries to CoreDNS (required after default deny):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-access
  namespace: production
spec:
  podSelector:
    matchLabels: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

**Step 3: Incrementally allow specific traffic:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
```

### Security Groups for Pods

Use when you need AWS-level network isolation (NACLs, VPC Flow Logs per pod):

```yaml
apiVersion: vpcresources.k8s.aws/v1beta1
kind: SecurityGroupPolicy
metadata:
  name: app-sgp
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: database-client
  securityGroups:
    groupIds:
    - sg-0123456789abcdef0  # Allow access to RDS
```

**Important SG for Pods requirements:**
- You **must** create SG rules allowing port 53 outbound to the cluster SG (DNS)
- You **must** update the cluster SG to accept port 53 inbound from the pod SG
- You **must** create rules for inbound traffic from the cluster SG for all health probes
- SG for pods uses ENI trunking — the number of branch ENIs varies by instance type

### Network Policy vs SG for Pods Decision

| Use Case | Network Policy | SG for Pods |
|----------|---------------|-------------|
| **Pod-to-pod traffic** (east-west) | Primary tool | Not designed for this |
| **Pod-to-AWS-service** (RDS, ElastiCache) | Cannot target AWS resources | Primary tool |
| **Reuse existing SG rules** | No | Yes — reuse EC2 SGs |
| **Isolate pod from node traffic** | No | Yes (`strict` mode) |
| **Overhead** | Low (eBPF-based) | Higher (ENI trunking) |

**Best practice: Use both as layers.** Network policies for pod-to-pod isolation, SG for Pods for AWS service-level isolation.

### SG Enforcing Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| **`standard`** | Node SG and pod SG both apply | Using both NP and SG for Pods |
| **`strict`** | Only pod SG applies, fully isolated from node | Complete pod traffic isolation |

You **must** use `standard` mode when combining Network Policy and Security Groups for Pods.

### Third-Party Network Policy Engines

Consider third-party engines when you need advanced features:

| Engine | Key Features Beyond K8s NP |
|--------|---------------------------|
| **Calico** | Global policies, layer 7 with Istio, DNS hostname rules, service account scoping |
| **Cilium** | Layer 7 (HTTP), DNS hostname rules, eBPF-native |
| **Calico Enterprise** | Map K8s NP to AWS security groups, compliance reporting |

**Migration:** If switching from Calico/Cilium to VPC CNI network policies, use the [K8s Network Policy Migrator](https://github.com/awslabs/k8s-network-policy-migrator) tool to convert CRDs to native K8s NetworkPolicy resources. Test in a separate cluster before production.

### Ensure Network Policies Exist via OPA

Use OPA/Gatekeeper to prevent pods from being created without a corresponding network policy:

```
package kubernetes.admission
import data.kubernetes.networkpolicies

deny[msg] {
    input.request.kind.kind == "Pod"
    pod_label_value := {v["k8s-app"] | v := input.request.object.metadata.labels}
    contains_label(pod_label_value, "sample-app")
    np_label_value := {v["k8s-app"] | v := networkpolicies[_].spec.podSelector.matchLabels}
    not contains_label(np_label_value, "sample-app")
    msg := sprintf("Pod %v missing an associated Network Policy.", [input.request.object.metadata.name])
}
```

### Service Mesh vs Network Policy

| Factor | Service Mesh (Istio, Linkerd) | Network Policy |
|--------|------------------------------|---------------|
| **OSI Layer** | Layer 7 (application) | Layer 3/4 (network/transport) |
| **mTLS** | Built-in | Not available |
| **Observability** | Latency, error rates, request volume | Basic allow/deny |
| **Overhead** | Sidecar per pod | Minimal (eBPF) |
| **Use when** | Need mTLS, traffic management, observability | Simpler pod-to-pod isolation |

Network policies and service mesh can be used together — NP for baseline isolation, mesh for mTLS and observability.

---

## Encryption in Transit

### Nitro Instance Automatic Encryption

Traffic between Nitro instance types (C5n, G4, I3en, M5dn, M5n, P3dn, R5dn, R5n, etc.) is automatically encrypted by default. No configuration needed. However, traffic through intermediate hops (transit gateway, load balancer) is not encrypted by this mechanism.

### Service Mesh mTLS

For end-to-end encryption between pods:
- **Istio** — automatic mTLS between all meshed services
- **Linkerd** — automatic mTLS with minimal configuration
- **App Mesh** — mTLS with X.509 certificates or Envoy SDS

### Ingress and Load Balancer TLS

**ALB with ACM certificates:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:region:account:certificate/cert-id
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
```

**NLB with TLS termination:**
```yaml
apiVersion: v1
kind: Service
metadata:
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-ssl-cert: arn:aws:acm:region:account:certificate/cert-id
```

Where you terminate TLS depends on your security policy:
- **At the load balancer** — simplest, offloads CPU from pods
- **At the ingress controller** — more control, still centralized
- **At the pod** — end-to-end encryption, highest CPU cost

---

## Detective Controls

### Enable EKS Audit Logging

```bash
# Enable all log types
aws eks update-cluster-config \
  --name my-cluster \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'
```

**Key audit log queries (CloudWatch Logs Insights):**

```
# Failed authentication attempts
fields @timestamp, @message
| filter @logStream like /kube-apiserver-audit/
| filter responseStatus.code >= 400
| sort @timestamp desc
| limit 50

# Privileged pod creation
fields @timestamp, user.username, objectRef.resource, objectRef.namespace
| filter @logStream like /kube-apiserver-audit/
| filter objectRef.resource = "pods" and verb = "create"
| filter requestObject.spec.containers.0.securityContext.privileged = true
```

### Amazon GuardDuty for EKS

Enable both:
- **EKS Audit Log Monitoring** — analyzes K8s audit logs for threats
- **EKS Runtime Monitoring** — detects container-level threats via agent

### AWS CloudTrail for EKS API Calls

All EKS API calls (`eks:*`) are logged in CloudTrail. Monitor for:
- `CreateCluster`, `DeleteCluster` events
- `UpdateClusterConfig` changes
- `CreateAccessEntry` for unauthorized access grants

### VPC Flow Logs

Enable VPC Flow Logs to capture metadata about traffic flowing through the VPC. Useful for detecting suspicious pod-to-pod communication, but pod IPs change frequently — combine with pod labels from Calico Enterprise or similar tools for better correlation.

### Monitoring Network Policy Enforcement

- Scrape Prometheus metrics from VPC CNI node agents for agent health and SDK errors
- Review audit logs for unauthorized network policy changes
- Implement automated testing to verify policies in a mirror environment
- Periodically audit policies to remove redundant rules as applications evolve

---

**Sources:**
- [AWS EKS Best Practices Guide — Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html)
- [AWS EKS Best Practices Guide — Network Security](https://docs.aws.amazon.com/eks/latest/best-practices/network-security.html)
- [AWS EKS Best Practices Guide — Detective Controls](https://docs.aws.amazon.com/eks/latest/best-practices/detective-controls.html)
