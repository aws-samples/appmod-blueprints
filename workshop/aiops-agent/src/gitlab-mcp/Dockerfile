# gitlab-mcp — the upstream @zereight/mcp-gitlab MCP server (stdio) wrapped by
# supergateway so it can be fronted by an AgentGateway over streamable-HTTP, exactly
# like eks-mcp. Gives the PEEKS agent its GitLab write path (branches / MRs).
#
# NOTE ON PROVENANCE: the authoritative published image is public.ecr.aws/seb-demo/gitlab-mcp
# (registry-to-registry copy of the validated-live upstream image). This Dockerfile is the
# reproducible SOURCE so the image can be rebuilt in a permissioned account from scratch;
# re-verify the tools/list handshake against the live image on the next rebuild.
#
# Base pulled from the ECR-public Docker mirror (not Docker Hub) to avoid throttling.
FROM public.ecr.aws/docker/library/node:22-bookworm-slim
# Pinned versions (reproducible builds). @zereight/mcp-gitlab 2.1.69 makes
# `commit_id` OPTIONAL on create_or_update_file (schemas.js: z.string().optional())
# and takes the POST path for a new file ("no need for commit IDs for new files").
# Older/unpinned `latest` baked a build where `commit_id` was REQUIRED, so the agent
# could not commit a brand-new file (MCPError "Invalid arguments: commit_id: Required"
# -> GitLab API 400) and could never open its own remediation MR.
RUN npm install -g supergateway@4.0.0 @zereight/mcp-gitlab@2.1.69
# Curate the tool surface. 2.1.69 exposes 118 tools by default, bloating every LLM
# call. This DENY regex drops the pipeline/issue/label/wiki/group/emoji/etc. clusters,
# keeping ~35 repo+MR+commit+project tools the agent actually uses. It is the IMAGE
# DEFAULT (so a bare `docker run` is already curated); the k8s Deployment sets the same
# value explicitly as the tunable, GitOps-visible override. Constraints (denied-regex.js):
# <=200 chars, SAFE_PATTERN_CHARS excludes '!' so NO negative-lookahead allowlist.
ENV GITLAB_DENIED_TOOLS_REGEX="issue|emoji|draft|group|label|protect|discussion|thread|todo|namespace|commit_status|catalog|ci_lint|approv|fork|_user|member|_event|whoami|health|download|upload|pipeline|create_note|create_repo"
EXPOSE 8000
# The k8s Deployment sets securityContext.runAsNonRoot=true with no runAsUser, so the
# image MUST define a non-root user or kubelet refuses to start it. The node base image
# ships the `node` user (uid 1000).
USER node
# Wrap the stdio server. IMPORTANT: run STATEFUL — supergateway wrapping a stdio server
# needs a warm process + per-session routing, otherwise each request spawns a fresh
# process that never received `initialize` and tools/list fails. Config is env-driven
# (GITLAB_API_URL / GITLAB_PERSONAL_ACCESS_TOKEN / GITLAB_READ_ONLY_MODE) — see the
# gitlab-mcp Deployment in the aiops-agent chart.
CMD ["supergateway", "--stdio", "mcp-gitlab", \
     "--outputTransport", "streamableHttp", "--port", "8000", \
     "--streamableHttpPath", "/mcp", "--healthEndpoint", "/health", "--stateful", "--logLevel", "info"]
