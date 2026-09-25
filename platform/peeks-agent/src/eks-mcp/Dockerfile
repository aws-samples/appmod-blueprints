# eks-mcp — the upstream awslabs EKS MCP server (stdio) wrapped by supergateway
# so it can be fronted by an AgentGateway over streamable-HTTP.
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g supergateway@4.0.0
RUN pip3 install --no-cache-dir --break-system-packages awslabs.eks-mcp-server==0.2.1
EXPOSE 8000
# Wrap the stdio server. IMPORTANT: run STATEFUL — supergateway wrapping a stdio
# server needs a warm process + per-session routing, otherwise each request spawns
# a new process that never received `initialize` and tools/list fails.
CMD ["supergateway", "--stdio", "awslabs.eks-mcp-server --allow-sensitive-data-access --auth-mode iam", \
     "--outputTransport", "streamableHttp", "--port", "8000", \
     "--streamableHttpPath", "/mcp", "--healthEndpoint", "/health", "--stateful", "--logLevel", "info"]
