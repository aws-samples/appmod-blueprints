# Incident Response & Forensics

A first-class security area in the AWS EKS Best Practices guide. Detection (Layer 5) and audit logging (Layer 6) produce the signals; this is how you **respond** when something fires. Have a defined, rehearsed plan *before* an incident — it materially improves posture and is itself an audit expectation.

## Prerequisites (must be in place before an incident)

- **Detective signal:** GuardDuty for EKS (EKS Protection + Runtime Monitoring) → Security Hub (Layer 5).
- **Forensic trail:** EKS control-plane `audit` + `authenticator` logs, CloudTrail, VPC Flow Logs, with retention that meets the regime (Layer 6).
- **A runbook** mapping common detections (container breakout, reverse shell, crypto-mining, anomalous API call, leaked credential) to response steps and owners.

## The response loop for a compromised pod/node

1. **Identify & triage** — confirm the GuardDuty finding; scope the affected pod(s), node(s), namespace, service account, and the IAM role behind it.
2. **Isolate the pod (network)** — apply a **deny-all NetworkPolicy** to the suspect pod (label-selected) so it can't talk to anything while you investigate. Preserves the pod for forensics (vs immediate deletion).
3. **Isolate the node** — `cordon` the node (stop new scheduling) and label/taint it for investigation; **avoid `drain`** if you need to preserve the running compromised process for capture. Detach it from load balancers.
4. **Revoke credentials** — if a workload identity is implicated, revoke/rotate it: for **Pod Identity** remove the association / tighten the role; for **IRSA** rotate and review the role's trust + permissions. Rotate any leaked secret in Secrets Manager.
5. **Capture forensics** — snapshot the node's EBS volume; capture process/network state (e.g. via the runtime agent or a forensic sidecar) **before** terminating; export the relevant audit-log window.
6. **Eradicate & recover** — terminate the compromised node (Karpenter/MNG replaces it from a clean AMI); redeploy the workload from a known-good, signed image; confirm the entry vector is closed (patched CVE, removed over-broad permission, fixed misconfig).
7. **Post-incident** — root-cause; update Kyverno/PSA policies and NetworkPolicies to prevent recurrence; record evidence for the auditor (a forensics capability is itself a compliance control).

## Design choices that make response possible

- **Immutable, minimal nodes** (Bottlerocket) shrink the attack surface and make "replace the node" the clean default (Layer 1).
- **Least-privilege workload IAM** (Pod Identity/IRSA) limits blast radius when a pod is compromised.
- **Default-deny NetworkPolicy** means an isolation policy is a small delta, not a from-scratch lockdown.
- **Signed images + admission control** (Layer 4) make "redeploy from known-good" trustworthy.

## Shared responsibility (incident response)

| AWS manages | Customer manages |
|---|---|
| Control-plane integrity; GuardDuty detections; durable logs/snapshots primitives; clean replacement AMIs | The IR runbook + rehearsal; isolation/eradication actions; credential rotation; forensic capture + evidence retention; post-incident hardening |

## Sources
- [EKS Best Practices: Incident response and forensics](https://docs.aws.amazon.com/eks/latest/best-practices/incident-response-and-forensics.html) · [EKS Best Practices: Detective controls](https://docs.aws.amazon.com/eks/latest/best-practices/detective-controls.html)
- [EKS Best Practices: Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html) · [GuardDuty EKS integration](https://docs.aws.amazon.com/eks/latest/userguide/integration-guardduty.html)
