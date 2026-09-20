# Layer 3 — Workload Security (Pod Security + Network)

Two compounding concerns: **pod security posture** (what a pod is allowed to do) and **network policy** (what a pod is allowed to talk to).

## Pod security — three layers that compound

```text
3a — Pod Security Admission (PSA, Kubernetes-native)
     restricted profile   → MOST WORKLOADS (default for new namespaces)
     baseline profile     → workloads needing limited extra privileges
     privileged profile   → AVOID; only system / kube-system

3b — Custom policy engine (choose ONE)
     Kyverno              → Kubernetes-native, no Rego DSL; preferred for new adoption
     OPA Gatekeeper       → Rego-based; for teams with existing OPA/Rego expertise

3c — Image admission control (a sub-rule of 3b)
     Kyverno verifyImages → block unsigned / high-severity images at admission
```

- **PSA `restricted`** is the default recommendation for production namespaces. Roll out in **`audit` mode first**, confirm no workloads break, then switch to **`enforce`**.
- **Kyverno** is preferred for new adoption (Kubernetes-native YAML policies, no Rego). **OPA Gatekeeper** suits teams already invested in Rego/OPA. Both are CNCF.
- **PodSecurityPolicy (PSP) was removed in Kubernetes 1.25+** — clusters on 1.25+ have no PSP. PSA + Kyverno/OPA is the canonical replacement. Do not recommend PSP.

References: [Pod Security Admission (Kubernetes)](https://kubernetes.io/docs/concepts/security/pod-security-admission/) · [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) · [aws/aws-eks-best-practices OPA policies](https://github.com/aws/aws-eks-best-practices/tree/master/policies/opa) · [Kyverno policy library](https://kyverno.io/policies/).

## Network policy on EKS — VPC CNI is now native

- **VPC CNI native NetworkPolicy** — the AWS VPC CNI enforces standard Kubernetes `NetworkPolicy` without a third-party CNI. Default-deny on production namespaces, then allowlist required ingress/egress. Reference: [Limit pod traffic with Kubernetes network policies](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html).
- **Enhanced capabilities (current versions matter).** EKS added **cluster-wide enforcement** via **ClusterNetworkPolicy** and **FQDN-based egress policies** (filter egress to cluster-external destinations by domain name). Availability specifics, framed precisely: the **VPC CNI v1.21 managed add-on with these features is offered for Kubernetes 1.29+** (a practical packaging constraint, not a hard API gate — the base NetworkPolicy [prerequisites](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy-configure.html) still list 1.26.7/1.27.4); use **VPC CNI v1.21.0+**, with **v1.21.1+ recommended** (v1.21.0 has a documented Network Policy Agent defect); **ClusterNetworkPolicy** works in all cluster launch modes, while **DNS/FQDN-based policies are supported only on EKS Auto Mode-launched EC2 instances**. References: [Enhanced network security policies (Dec 2025)](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-eks-enhanced-network-security-policies/) · [Enhanced network policy capabilities](https://aws.amazon.com/blogs/containers/amazon-eks-introduces-enhanced-network-policy-capabilities) · [DNS and Admin Network Policies](https://aws.amazon.com/blogs/containers/enhance-amazon-eks-network-security-posture-with-dns-and-admin-network-policies).
- **EKS Auto Mode** supports NetworkPolicy out of the box. Reference: [Network policies with EKS Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html).
- **Cilium CNI** — **not supported on EKS Auto Mode (as of June 2026)**; available on self-managed / managed node groups for advanced features (eBPF, Hubble, Cluster Mesh).

## Security Groups for Pods (SGP)

For compliance workloads needing **network-layer isolation between pods** (e.g., PHI-handling pods isolated from non-PHI pods in the same cluster), attach VPC Security Groups at pod granularity via the VPC CNI trunk/branch-ENI feature. Reference: [Leveraging CNI custom networking alongside Security Groups for Pods](https://aws.amazon.com/blogs/containers/leveraging-cni-custom-networking-alongside-security-groups-for-pods-in-amazon-eks).

> **SGP limitations — material for a compliance design (don't promise isolation it doesn't deliver).** Per [Security groups for Pods](https://docs.aws.amazon.com/eks/latest/userguide/security-groups-for-pods.html):
> - **Not supported on EKS Auto Mode or Windows nodes** (hard exclusion) — if you need pod-SG isolation, you can't be on Auto Mode.
> - **Same-node traffic:** in `standard` mode, pod SG rules are **not applied** to traffic between pods on the *same node*; the default `strict` mode does apply them but routes all pod traffic through the VPC, which breaks NodeLocal DNSCache and `externalTrafficPolicy=Local`.
> - No `t`-family instance support; trunk/branch ENIs reduce pod density per node.
> Combine SGP with Kubernetes NetworkPolicy (default-deny) rather than treating SGP alone as the isolation boundary.

## Service-mesh mTLS (east-west encryption in transit)

For **intra-cluster pod-to-pod mTLS**, use a service mesh — **Istio** (sidecar mode), **Linkerd**, or **Cilium Service Mesh** — all run on EKS and issue/rotate workload certificates for east-west traffic.

> **Don't position VPC Lattice as an mTLS mesh — it isn't one.** VPC Lattice provides **cross-VPC / cross-cluster service connectivity with IAM-based authentication (SigV4)**, not certificate-based mTLS between pods. Use it for secure *cross-boundary* service-to-service connectivity; use a service mesh (Istio/Linkerd/Cilium) for *intra-cluster* mTLS. References: [VPC Lattice integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-vpc-lattice.html) · [VPC Lattice SigV4 auth](https://docs.aws.amazon.com/vpc-lattice/latest/ug/sigv4-authenticated-requests.html).

> **Gotcha:** **AWS App Mesh reaches end of support on September 30, 2026** (new sign-ups already closed). Do not recommend App Mesh for new deployments — use Istio/Linkerd/Cilium mesh or VPC Lattice. Reference: [AWS App Mesh end-of-support notice](https://docs.aws.amazon.com/app-mesh/latest/userguide/what-is-app-mesh.html).

## Shared responsibility (Layer 3)

| AWS manages | Customer manages |
|---|---|
| VPC CNI + NetworkPolicy enforcement engine; PSA controller (built into the managed control plane); SGP trunk/branch ENI plumbing | PSA profile labels per namespace; Kyverno/OPA policy authoring + rollout; NetworkPolicy rules (default-deny + allowlists); SGP assignment; service-mesh deployment + mTLS config |

## Sources
- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/) · [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) · [Kyverno policies](https://kyverno.io/policies/) · [aws-eks-best-practices OPA policies](https://github.com/aws/aws-eks-best-practices/tree/master/policies/opa)
- [VPC CNI NetworkPolicy](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html) · [Enhanced network policy capabilities](https://aws.amazon.com/blogs/containers/amazon-eks-introduces-enhanced-network-policy-capabilities) · [DNS & Admin Network Policies](https://aws.amazon.com/blogs/containers/enhance-amazon-eks-network-security-posture-with-dns-and-admin-network-policies) · [NetworkPolicy on Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html)
- [Security Groups for Pods](https://aws.amazon.com/blogs/containers/leveraging-cni-custom-networking-alongside-security-groups-for-pods-in-amazon-eks) · [VPC Lattice integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-vpc-lattice.html) · [App Mesh EOS notice](https://docs.aws.amazon.com/app-mesh/latest/userguide/what-is-app-mesh.html)
