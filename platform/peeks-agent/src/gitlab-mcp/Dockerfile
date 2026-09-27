# gitlab-mcp — the upstream @zereight/mcp-gitlab MCP server (stdio) wrapped by
# supergateway so it can be fronted by an AgentGateway over streamable-HTTP, exactly
# like eks-mcp. Gives the PEEKS agent its GitLab write path (branches / MRs).
#
# NOTE ON PROVENANCE: the authoritative published image is public.ecr.aws/seb-demo/gitlab-mcp
# (registry-to-registry copy of the validated-live peeks-e2e image). This Dockerfile is the
# reproducible SOURCE so the image can be rebuilt in a permissioned account from scratch;
# re-verify the tools/list handshake against the live image on the next rebuild.
#
# Base pulled from the ECR-public Docker mirror (not Docker Hub) to avoid throttling.
FROM public.ecr.aws/docker/library/node:22-bookworm-slim
RUN npm install -g supergateway@4.0.0 @zereight/mcp-gitlab
EXPOSE 8000
# The k8s Deployment sets securityContext.runAsNonRoot=true with no runAsUser, so the
# image MUST define a non-root user or kubelet refuses to start it. The node base image
# ships the `node` user (uid 1000).
USER node
# Wrap the stdio server. IMPORTANT: run STATEFUL — supergateway wrapping a stdio server
# needs a warm process + per-session routing, otherwise each request spawns a fresh
# process that never received `initialize` and tools/list fails. Config is env-driven
# (GITLAB_API_URL / GITLAB_PERSONAL_ACCESS_TOKEN / GITLAB_READ_ONLY_MODE) — see the
# gitlab-mcp Deployment in the peeks-agent chart.
CMD ["supergateway", "--stdio", "mcp-gitlab", \
     "--outputTransport", "streamableHttp", "--port", "8000", \
     "--streamableHttpPath", "/mcp", "--healthEndpoint", "/health", "--stateful", "--logLevel", "info"]
