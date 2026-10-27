# 3.5 · Custom — update the README

When you fork the platform (or your fleet repo) for a custom deployment, keep the **README of your
copy** honest about the choices you made, so the next operator — or future‑you — can reproduce it.
This is documentation hygiene, not a platform step; nothing here changes the running system.

---

## What to update in your fork's README

Record the decisions that differ from the defaults:

1. **Install path.** State which path you followed (CloudFront / existing fleet‑config / custom) and
   link back to this guide's entry page, [README.md](README.md).
2. **Exposure mode.** `insecure: true` (CloudFront) vs `insecure: false` (your own domain + ACM).
   Note the hostname pattern (generically — e.g. `*.<your-domain>`), never a real host or cert ARN.
3. **Fleet repo.** Which repo holds your spokes (`fleetRepo.url`) and whether it is public
   (zero‑PAT) or private (credential via `argocd/fleet-config-repo`).
4. **Spokes.** The list of spoke names and whether they are same‑account (`global.spokeNames`) or
   cross‑account (`configs/multi-acct/values.yaml`).
5. **Versions.** The `repo.revision` / `agenticRepo.revision` tags you pinned.
6. **Cost tags.** The `platformTags` keys you set, so cost reports are reproducible
   ([custom-cost.md](custom-cost.md)).

---

## The one rule — keep it generic / zero‑secret

A README is public (or shared). **Never** commit:

- AWS account IDs, VPC/subnet/instance IDs, internal IPs;
- real hostnames, CloudFront domains, IDE URLs or tokens;
- ACM/role ARNs, Secrets Manager values, PATs;
- usernames / aliases / internal references.

Use placeholders everywhere: `<account-id>`, `<your-domain>`, `<cluster-prefix>`, `<org>`,
`<secret-name>`. Scan before you commit:

```bash
# Flag the usual leaks in your staged README changes before committing
git diff --cached -- README.md \
  | grep -nE '[0-9]{12}|ghp_|github_pat_|AKIA|ASIA|-----BEGIN|arn:aws:(iam|acm)|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  && echo "⚠ review the matches above — redact before committing" || echo "clean"
```

---

## Suggested snippet to add to your fork's README

```markdown
## Our deployment

This fork runs Platform Engineering on EKS via the **<CloudFront | own-domain | custom>** path
(see [docs/non-workshop/README.md](docs/non-workshop/README.md)).

- Exposure: `insecure: <true|false>` (<CloudFront *.cloudfront.net | HTTPS on *.your-domain>)
- Fleet repo: `<org>/<your-fleet-repo>` (<public zero-PAT | private>)
- Spokes: `<dev, prod, ...>` (<same-account via global.spokeNames | cross-account via configs/multi-acct>)
- Pinned: platform `<release-tag>`, OAP `<oap-release-tag>`
- Cost tags: `platformTags.{project, environment, owner}`
```

---

## Reminder — pushing is a separate, explicit action

Editing the README is a local change. Pushing it to a public/shared repo under your identity is a
**separate, deliberate** step — review the diff and confirm the zero‑secret scan passed before you
push.
