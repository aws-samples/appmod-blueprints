# argocd-status-mcp — read-only FastMCP server: Argo CD Applications not Synced+Healthy.
# Same build shape as skills-mcp. Base pulled from the ECR-public Docker mirror (not
# Docker Hub) to avoid throttling.
FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY status.py server.py ./
ENV PORT=8000 ARGOCD_NAMESPACE=argocd
EXPOSE 8000
# Numeric non-root user so the pod's runAsNonRoot check can verify it.
USER 1000:1000
CMD ["python", "server.py"]
