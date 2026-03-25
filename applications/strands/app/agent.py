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

    agent = Agent(
        model=model,
        system_prompt=config.SYSTEM_PROMPT,
        tools=mcp_tools or None,
        agent_id=config.AGENT_NAME,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
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
