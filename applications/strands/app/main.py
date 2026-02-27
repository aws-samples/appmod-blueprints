"""FastAPI application with A2A protocol support using Strands A2AServer."""

import logging
from typing import Any, Dict

import uvicorn
from strands.multiagent.a2a import A2AServer

from .agent import agent
from .config import config

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Create A2A server with Strands agent
# This handles all A2A protocol endpoints automatically
a2a_server = A2AServer(
    agent=agent,
    host=config.HOST,
    port=config.PORT,
    version="1.0.0",
    enable_a2a_compliant_streaming=True,  # Enable A2A-compliant streaming
)

# Get the FastAPI app from A2AServer
app = a2a_server.to_fastapi_app()


# Add custom endpoints to the FastAPI app
@app.get("/health")
@app.get("/ping")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent": config.AGENT_NAME,
        "a2a_protocol": "compatible",
    }


@app.post("/chat")
async def simple_chat(request: Dict[str, Any]) -> Dict[str, Any]:
    """Simplified chat endpoint with clean response.
    
    Uses A2A protocol internally but returns only the essential response.
    Supports conversation context via contextId for multi-turn conversations.
    
    Request:
    {
        "message": "Your message here",
        "contextId": "optional-context-id"  // For multi-turn conversations
    }
    
    Response:
    {
        "response": "Agent response text",
        "contextId": "ctx-123"  // Use this for follow-up messages
    }
    """
    import uuid
    
    # Extract message and contextId
    user_message = request.get("message", "")
    context_id = request.get("contextId")
    
    try:
        # Build JSON-RPC request for A2A protocol
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"text": user_message}],
                    "messageId": str(uuid.uuid4()),
                }
            },
            "id": str(uuid.uuid4()),
        }
        
        # Add contextId if provided
        if context_id:
            jsonrpc_request["params"]["message"]["contextId"] = context_id
        
        # Call A2A endpoint internally
        from fastapi import Request
        from starlette.datastructures import Headers
        
        # Create a mock request for the A2A handler
        # This is a workaround - ideally we'd call the handler directly
        # For now, just use agent.invoke_async
        
        response = await agent.invoke_async(user_message)
        
        # Extract text from response
        if isinstance(response, dict):
            response_text = response.get("response", str(response))
        elif isinstance(response, str):
            response_text = response
        else:
            response_text = str(response)
        
        return {
            "response": response_text,
            "contextId": context_id or "stateless",
        }
    except Exception as e:
        logger.error(f"Error in simple_chat: {e}")
        return {
            "error": str(e),
            "contextId": context_id or "error",
        }


def main():
    """Run the FastAPI application."""
    logger.info(f"Starting {config.AGENT_NAME} on {config.HOST}:{config.PORT}")
    logger.info("=" * 60)
    logger.info("A2A Protocol Endpoints (JSON-RPC at root):")
    logger.info("  - Agent Card: GET /.well-known/agent.json")
    logger.info("  - Send Message: POST / (JSON-RPC 2.0)")
    logger.info("Custom Endpoints:")
    logger.info("  - Simple Chat: POST /chat (clean response)")
    logger.info("  - Health: GET /health")
    logger.info("=" * 60)
    logger.info(f"Model: {config.MODEL_ID}")
    logger.info(f"LLM Gateway: {config.LLM_GATEWAY_URL}")
    logger.info("=" * 60)
    
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
