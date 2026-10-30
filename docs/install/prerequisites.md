# Prerequisites — direct installs

> Applies to every **direct** install (`kind-kro-ack`): the quick paths
> ([CloudFront](quick-cloudfront.md), [existing fleet-config](quick-existing-fleet.md)) and the
> [custom install](custom-install.md). The guided workshop's IDE is pre-provisioned, so there is
> nothing to do here for the workshop.

---

## 1. Host prerequisites

A Linux/macOS host (EC2, Cloud Desktop, or a laptop) with Docker running and these CLIs on `PATH`.
The install's pre‑flight checks `kind, kubectl, helm, yq, aws` plus `go-task`:

| Tool | Validated version | Purpose |
|---|---|---|
| `docker` | any recent | runs the ephemeral `kind` bootstrap cluster |
| `kind` | 0.24 | throwaway local cluster that bootstraps the hub |
| `kubectl` | 1.37 | matches the hub's default EKS `kubernetesVersion` |
| `helm` | 3.16 | installs the ACK / KRO / ESO bootstrap charts |
| `yq` | 4.53 | every config read is a `yq` v4 expression (v3 breaks) |
| `aws` | 2.36 | all AWS calls (v2) |
| `go-task` | 3.x | the `task` runner |
| `jq` | any recent | required by the CloudFront scripts (if you expose via CloudFront) |

AWS credentials for the target account must resolve in your shell
(`aws sts get-caller-identity` — never echo the secret values).

---

## 2. AWS account prerequisites

1. **IAM Identity Center (SSO) instance in the account.** The platform's ArgoCD is created as an EKS
   ArgoCD Capability, which requires an Identity Center instance. Confirm:
   ```bash
   aws sso-admin list-instances --region <region>
   ```
2. **(HTTPS/own-domain mode only) A validated ACM certificate** in the deploy region covering
   `*.<your-domain>`, status `ISSUED` (ALB listeners are regional). Confirm:
   ```bash
   aws acm list-certificates --region <region> \
     --query "CertificateSummaryList[?DomainName=='*.<your-domain>']"
   ```
   *CloudFront mode needs no ACM cert — see [quick-cloudfront.md](quick-cloudfront.md).*
3. **(HTTPS/own-domain mode only) A public Route53 hosted zone for `<your-domain>`.** external-dns writes A/ALIAS records into it
   to point your hostnames at the ALB. The zone must be **public** and the account's nameservers
   must be authoritative for the domain (delegated from the registrar/parent zone). Confirm:
   ```bash
   aws route53 list-hosted-zones-by-name --dns-name <your-domain>
   ```
   *CloudFront mode needs no domain — the `*.cloudfront.net` name is used instead.*

---

## Next

- Quick install behind CloudFront (no domain) → [quick-cloudfront.md](quick-cloudfront.md)
- Quick install reusing the example fleet-config → [quick-existing-fleet.md](quick-existing-fleet.md)
- Custom install (own domain, own fleet repo) → [custom-install.md](custom-install.md)
