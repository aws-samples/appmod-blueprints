"""FastAPI application with A2A protocol support and per-session agents."""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

import uvicorn
from strands.multiagent.a2a import A2AServer

from .agent import create_agent, get_or_create_agent, shutdown_mcp
from .config import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    yield
    shutdown_mcp()


# A2A server needs an agent for the agent card / default executor.
# Per-session routing for A2A would require a custom executor; for now
# the default A2A executor uses this shared agent (no memory).
_default_agent = create_agent()

a2a_server = A2AServer(
    agent=_default_agent,
    host=config.HOST,
    port=config.PORT,
    version="1.0.0",
    enable_a2a_compliant_streaming=True,
)

app = a2a_server.to_fastapi_app()
app.router.lifespan_context = lifespan


@app.get("/health")
@app.get("/ping")
async def health() -> Dict[str, str]:
    return {
        "status": "healthy",
        "agent": config.AGENT_NAME,
        "a2a_protocol": "compatible",
    }


@app.post("/chat")
async def simple_chat(request: Dict[str, Any]) -> Dict[str, Any]:
    """Chat endpoint with per-session agent and AgentCore memory.

    Request:
        { "message": "...", "contextId": "optional-session-id" }
    Response:
        { "response": "...", "contextId": "session-id" }
    """
    user_message = request.get("message", "")
    context_id = request.get("contextId")

    try:
        agent, session_id = get_or_create_agent(session_id=context_id)
        result = await agent.invoke_async(user_message)

        if isinstance(result, dict):
            response_text = result.get("response", str(result))
        elif isinstance(result, str):
            response_text = result
        else:
            response_text = str(result)

        return {"response": response_text, "contextId": session_id}
    except Exception as e:
        logger.error(f"Error in /chat: {e}")
        return {"error": str(e), "contextId": context_id or "error"}


def main():
    logger.info(f"Starting {config.AGENT_NAME} on {config.HOST}:{config.PORT}")
    logger.info("=" * 60)
    logger.info("A2A Protocol Endpoints (JSON-RPC at root):")
    logger.info("  - Agent Card: GET /.well-known/agent.json")
    logger.info("  - Send Message: POST / (JSON-RPC 2.0)")
    logger.info("Custom Endpoints:")
    logger.info("  - Simple Chat: POST /chat (per-session agent)")
    logger.info("  - Health: GET /health")
    logger.info("=" * 60)
    logger.info(f"Model: {config.MODEL_ID}")
    logger.info(f"LLM Gateway: {config.LLM_GATEWAY_URL}")
    logger.info(f"Memory: {config.MEMORY_PROVIDER or 'none'}")
    logger.info("=" * 60)
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level=config.LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
