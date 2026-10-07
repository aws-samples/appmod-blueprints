# PEEKS skills overlay — bakes the PEEKS skills into the generic OAP skills-mcp image.
# This is how the PEEKS skills reach the agent: NOT in the agent image, but in the
# skills-mcp image the agent calls via the gateway (get_skill / list_skills).
#
# Build context MUST be the appmod-blueprints repo ROOT (to access .kiro/skills):
#   docker build \
#     -f workshop/aiops-agent/skills-overlay/Dockerfile \
#     --build-arg SKILLS_MCP_IMAGE=<registry>/skills-mcp:<tag> \
#     -t <registry>/<your-ecr-namespace>/skills-mcp:<tag> .
ARG SKILLS_MCP_IMAGE=public.ecr.aws/oap/skills-mcp:latest
FROM ${SKILLS_MCP_IMAGE}
# Replace the base image's placeholder skills with the PEEKS skills.
COPY .kiro/skills /payload/skills
# Bake the PEEKS steering corpus so skills.list_steering()/get_steering() have a
# backing (the base image ships none → those tools returned empty before). Served
# read-only by the skills-mcp server from $PAYLOAD_DIR/steering.
COPY .kiro/steering /payload/steering
