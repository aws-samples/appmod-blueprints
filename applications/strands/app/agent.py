"""Strands agent initialization and configuration."""

import logging
import os
from contextlib import ExitStack
from typing import Optional

# Configure logging early, before any submodule loggers are created
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models.litellm import LiteLLMModel
from strands.tools.mcp.mcp_client import MCPClient

from .config import config

logger = logging.getLogger(__name__)

# Holds open MCP context managers so they stay alive for the process lifetime
mcp_exit_stack: Optional[ExitStack] = None


def build_session_manager():
    """Build a session manager based on MEMORY_PROVIDER config."""
    if config.MEMORY_PROVIDER != "agentcore":
        return None

    mem_config = config.MEMORY_CONFIG
    memory_id = mem_config.get("memoryId")
    region = mem_config.get("region", config.AWS_REGION)

    if not memory_id:
        logger.warning("MEMORY_PROVIDER=agentcore but no memoryId in MEMORY_CONFIG")
        return None

    from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

    agentcore_config = AgentCoreMemoryConfig(memory_id=memory_id)
    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=agentcore_config,
        region_name=region,
    )
    logger.info(f"AgentCore memory session manager created (memory_id={memory_id})")
    return session_manager


def build_mcp_tools() -> tuple[list, Optional[ExitStack]]:
    """Initialize MCP clients for all configured servers.

    Returns a tuple of (tools, exit_stack). The exit_stack must be kept alive
    as long as the agent is in use; call exit_stack.close() on shutdown.
    """
    urls = config.MCP_SERVER_URLS
    if not urls:
        return [], None

    stack = ExitStack()
    tools: list = []

    for url in urls:
        logger.info(f"Connecting to MCP server: {url}")
        try:
            client = MCPClient(lambda u=url: streamablehttp_client(u))
            stack.enter_context(client)
            server_tools = client.list_tools_sync()
            logger.info(f"  Loaded {len(server_tools)} tools from {url}")
            tools.extend(server_tools)
        except Exception as exc:
            logger.warning(f"  Failed to connect to MCP server {url}: {exc}")
            # Non-fatal: continue without this server's tools

    return tools, stack


def create_agent() -> Agent:
    """Create and configure a Strands agent.

    Also initializes MCP clients and stores the exit stack globally so the
    connections remain open for the lifetime of the process.

    Returns:
        Configured Strands Agent instance.
    """
    global mcp_exit_stack

    logger.info(f"Creating agent: {config.AGENT_NAME}")
    logger.info(f"Model: {config.MODEL_ID}")
    logger.info(f"LLM Gateway: {config.LLM_GATEWAY_URL}")
    logger.info(f"MCP servers: {config.MCP_SERVER_NAMES or 'none'}")

    model = LiteLLMModel(
        client_args={
            "api_key": config.LLM_GATEWAY_API_KEY,
            "api_base": config.LLM_GATEWAY_URL,
            "use_litellm_proxy": True,
        },
        model_id=config.MODEL_ID,
        params={
            "max_tokens": 1000,
            "temperature": 0.7,
            "stream": True,
        },
    )

    mcp_tools, exit_stack = build_mcp_tools()
    mcp_exit_stack = exit_stack  # keep connections alive

    if mcp_tools:
        logger.info(f"Agent equipped with {len(mcp_tools)} MCP tool(s)")

    session_manager = build_session_manager()

    agent = Agent(
        model=model,
        system_prompt=config.SYSTEM_PROMPT,
        tools=mcp_tools or None,
        agent_id=config.AGENT_NAME,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
        session_manager=session_manager,
    )

    logger.info(f"Agent created successfully: {config.AGENT_NAME}")
    return agent


def shutdown_mcp() -> None:
    """Close all MCP client connections. Call on application shutdown."""
    global mcp_exit_stack
    if mcp_exit_stack is not None:
        logger.info("Closing MCP client connections")
        mcp_exit_stack.close()
        mcp_exit_stack = None


# Global agent instance (created on module import)
agent = create_agent()
