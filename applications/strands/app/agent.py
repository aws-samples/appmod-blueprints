"""Strands agent initialization and configuration."""

import logging
from typing import Optional

from strands import Agent
from strands.models.litellm import LiteLLMModel

from .config import config

logger = logging.getLogger(__name__)


def create_agent() -> Agent:
    """Create and configure a Strands agent.
    
    Returns:
        Configured Strands Agent instance.
    """
    logger.info(f"Creating agent: {config.AGENT_NAME}")
    logger.info(f"Model: {config.MODEL_ID}")
    logger.info(f"Region: {config.AWS_REGION}")
    logger.info(f"LLM Gateway: {config.LLM_GATEWAY_URL}")
    logger.info(f"MCP Servers: {config.MCP_SERVERS}")
    
    # Use LiteLLM model with LLM Gateway (LiteLLM proxy)
    # The gateway handles Bedrock authentication via pod identity
    model = LiteLLMModel(
        client_args={
            "api_key": config.LLM_GATEWAY_API_KEY,
            "api_base": config.LLM_GATEWAY_URL,
            "use_litellm_proxy": True
        },
        model_id=config.MODEL_ID,
        params={
            "max_tokens": 1000,
            "temperature": 0.7,
            "stream": True,  # Enable streaming for real-time responses
        }
    )
    
    logger.info("✅ Using LiteLLMModel with LLM Gateway")
    logger.info("Gateway handles Bedrock authentication via pod identity")
    
    # Prepare tools list
    tools: Optional[list] = None
    
    # TODO: Add MCP server integration when available
    # For now, MCP servers would need to be integrated via custom tool providers
    if config.MCP_SERVERS:
        logger.warning(
            "MCP server integration is configured but requires custom implementation. "
            f"Configured servers: {config.MCP_SERVERS}"
        )
        # Example of how MCP integration might work:
        # from strands_tools.mcp import MCPToolProvider
        # tools = []
        # for mcp_url in config.MCP_SERVERS:
        #     tools.append(MCPToolProvider(url=mcp_url))
    
    # Create agent
    agent = Agent(
        model=model,
        system_prompt=config.SYSTEM_PROMPT,
        tools=tools,
        agent_id=config.AGENT_NAME,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
    )
    
    logger.info(f"Agent created successfully: {config.AGENT_NAME}")
    return agent

# Global agent instance (created on module import)
agent = create_agent()
