# Engagement & Response Framework

How to run an EKS security/compliance conversation: the full discovery question set, the adoption-challenge archetypes, the 8-step response structure, and escalation criteria.

## Discovery — Required questions (the minimum for a defensible recommendation)

Do NOT proceed to a recommendation without these. The first four determine ~80% of the answer.

1. **Compliance regime(s)?** None / SOC 2 / HIPAA / PCI-DSS / FedRAMP Moderate / FedRAMP High / GDPR / ISO 27001/27017/27018 / HITRUST / NIST 800-53/171 / CJIS / DISA IL2-IL5 / industry-specific — rank primary/secondary if multiple.
2. **Workload sensitivity?** Public / internal-confidential / PII / PHI (HIPAA) / cardholder data (PCI) / federal-classified / mixed.
3. **OS / AMI strategy?** Open to AWS defaults / Bottlerocket-first / AL2023+CIS custom AMI / Ubuntu mandate / RHEL mandate / custom hardened / EKS Auto Mode.
4. **Audit timeline?** None (greenfield posture) / <3 mo (urgent) / 3-6 mo / 6-12 mo / continuous (e.g., FedRAMP ConMon).
5. **Cluster topology?** Single/multi-cluster, single/multi-account, multi-region, EKS Anywhere, Hybrid Nodes, GovCloud.
6. **Team K8s/security skill?** Low / moderate / high / mixed.
7. **Operational-overhead tolerance?** Zero (managed-only) / low / moderate / high.
8. **Current security tooling baseline?** None / AWS-native / third-party CNAPP / OSS / hybrid / heritage on-prem.

## Discovery — Recommended questions (sharpen the answer when depth allows)

Org standardization mandate (AWS-native / vendor-OS / OSS / CNAPP-vendor / none) · cluster scale envelope (the **5,000 Pod-Identity-association** hard limit matters >~ that many SAs) · data residency / sovereignty · encryption posture (default KMS / CMK / FIPS 140-3 / BYOK / CloudHSM) · image-supply-chain posture · runtime-tooling preference · secrets-management posture · audit-log retention requirement · SIEM in use · network topology constraints · existing pentest/red-team findings · customer segment (XS–XXL+, drives escalation).

> **The #1 mistake:** recommending "use Bottlerocket" or "AL2023 + CIS hardening" reflexively without confirming compliance regime, OS-standardization mandate, audit timeline, and operational-overhead tolerance. The right stack is a function of *(compliance regime × OS mandate × team skill × audit timeline × workload sensitivity × air-gap × scale × ops tolerance)*.

## The 5 adoption-challenge archetypes

Identify the customer's #1 concern early — it shapes every subsequent step:
1. **Compliance audit panic** — audit imminent, posture gap unclear → lead with the priority-ordered hardening roadmap + `kube-bench` baseline.
2. **OS/AMI standardization conflict** — customer vendor-OS mandate vs AWS-canonical defaults → lead with the Layer-1 decision matrix; respect the mandate.
3. **Skills gap** — no kube-bench/PSA/Kyverno experience → lead with managed services (Bottlerocket + GuardDuty + Inspector) and a staged rollout.
4. **Tooling sprawl** — many tools, no unified posture → lead with Security Hub aggregation.
5. **Shared-responsibility confusion** — unclear what AWS vs customer manages → lead with the per-layer shared-responsibility split.

## Response framework (8 steps)

Skip a step only if the question is narrow enough that it doesn't apply.
1. **Acknowledgment + context summary** — restate regime(s), sensitivity, OS strategy, timeline, topology, skill, ops tolerance, baseline; name the #1 adoption challenge.
2. **Compliance-regime position** — which programs apply; native-in-scope vs alignment/framework; call out workload-level ownership for framework regimes. **Always add the live-page disclaimer.**
3. **Top-level stack recommendation** — one paragraph naming the choice at each of the 7 layers, each one-sentence-justified against the discovery answers; surface alternatives (vendor-OS path, third-party CNAPP) with the conditions that justify deviating.
4. **Layer-by-layer detail** — walk all 7 layers; cite the specific AWS doc/blog/workshop for each; give the **shared-responsibility split** per layer (critical for audit conversations).
5. **30/60/90 hardening roadmap** — baseline (non-disruptive) → identity + workload → OS + image + accelerators; greenfield deploys the full stack at creation.
6. **Security baseline (non-negotiable)** — include the full baseline from SKILL.md regardless of regime.
7. **Known gotchas (surface 3-5 relevant ones)** — Auto Mode no custom AMI; Cilium not on Auto Mode; PSP removed 1.25+; Pod Identity 5,000-association hard limit; audit-log all-or-nothing (cost); HIPAA needs BAA; FedRAMP High = GovCloud; FIPS 140-3 not 140-2; CIS AL2 ≠ AL2023; aws-auth→Access-Entries lockout window; EKS Anywhere shifts all responsibility to customer; Hybrid Nodes outside the FedRAMP boundary; App Mesh EOS Sept 30 2026; AL2 OS EOL June 30 2026.
8. **Cite sources** — every recommendation cites an AWS-published reference. If you can't ground a claim, **say so and recommend escalation — do not synthesize.** Customers validate every claim against an auditor.

## Escalation criteria

Escalate (SpecReq / Specialist / Security review) when any holds:
- First-time certification on a **mission-critical regulated workload** (highest stakes).
- **XXL+ segment** (all security/compliance recommendations require human review).
- **FedRAMP High / GovCloud** → federal partner engagement.
- **Top Secret / Secret classified** → AWS Top Secret/Secret region partner (out of scope here — commercial + GovCloud only).
- **EKS Anywhere (air-gapped) or Hybrid Nodes inside a FedRAMP boundary** → shared-responsibility boundary mapping (AWS manages no control plane in air-gapped EKS Anywhere; Hybrid on-prem nodes are outside the FedRAMP boundary).
- **Multi-tenant SaaS** with cross-tenant PHI / cardholder / federal isolation.
- **Customer vs auditor disagreement** on AWS-managed-control acceptability (e.g., AWS-managed AMI patching vs documented patch cycle) → joint review with the auditor.
- **Written legal commitment** beyond Artifact (custom DPA, FedRAMP ConMon SLA, sovereignty-plus).
- **Deprecated/KTLO** redirect needed (PSP, `aws-auth` as primary, App Mesh, NTH-with-Karpenter, AL2, IRSA-for-new-when-Pod-Identity-fits).
- **AI/ML workloads with PHI/cardholder/federal data** → joint AI/ML + Security review (and route ML-specific security to `eks-genai`).
- **Cannot ground the response** → do not synthesize; escalate. Rejected compliance guidance leads to audit findings and erodes trust.

## Sources
- [EKS Best Practices: Compliance](https://docs.aws.amazon.com/eks/latest/best-practices/compliance.html) · [Runtime Security](https://docs.aws.amazon.com/eks/latest/best-practices/runtime-security.html)
- [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) · [EKS Security Immersion Workshop](https://catalog.us-east-1.prod.workshops.aws/workshops/165b0729-2791-4452-8920-53b734419050)
