# skills-mcp — FastMCP server exposing get_skill / list_skills over a skills dir
FROM python:3.12-slim
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# Consumers provide their skills under $PAYLOAD_DIR/skills: bake an overlay image
# (`FROM this` + `COPY skills /payload/skills`) or mount a volume at /payload/skills.
COPY example-skills/ /payload/skills/
ENV PAYLOAD_DIR=/payload PORT=8000 \
    FASTMCP_STATELESS_HTTP=true FASTMCP_JSON_RESPONSE=true
EXPOSE 8000
USER app
CMD ["python", "server.py"]
