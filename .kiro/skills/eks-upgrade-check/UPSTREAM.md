# Upstream Provenance

This skill is **vendored** from an upstream repo. Do not edit files here directly — your changes will be overwritten by the next sync.

| Field | Value |
|---|---|
| Source repo | https://github.com/aws-samples/sample-eks-upgrade-skill.git |
| Source path | `.claude/skills/eks-upgrade/` |
| Refresh command | `./misc/sync-eks-upgrade-skill.sh` |
| License | See `LICENSE` (copied verbatim from upstream) |

## Local modifications applied at sync time

The sync script applies three deterministic edits to upstream content:

1. **`### MCP Server Setup` section is replaced.** Apex does not ship a project-root `.mcp.json`; MCP setup is delegated to the `eks-mcp-server` skill in this repo. The upstream's fallback note ("falls back to AWS CLI and kubectl") is preserved.
2. **`steering/` -> `references/` rename.** Upstream's progressive-disclosure docs live under `steering/`, but apex already uses a top-level `steering/` directory at the repo root for workflow orchestration (different concept). The sync script renames the directory on copy and rewrites all internal cross-refs from `steering/` to `references/` inside `SKILL.md` and the 8 progressive-disclosure files. This aligns the layout with the Anthropic skill spec's canonical name for "additional documentation agents read on demand."
3. **`description:` frontmatter is replaced with a "pushy" wording.** Upstream's description is a keyword list. Apex review feedback (#36) calls for natural-question phrasings ("can I upgrade my cluster?", "is my cluster ready for 1.32?", etc.) that mirror sibling skills like `eks-best-practices` and `eks-recon`. The sync script replaces the whole `description:` line on every run.

Everything else is byte-for-byte from upstream.

## To propose changes

Open a PR against the upstream repo:
https://github.com/aws-samples/sample-eks-upgrade-skill.git

Then re-run the sync script here.
