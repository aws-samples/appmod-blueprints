"""Strands agent initialization — per-session agents with AgentCore memory."""

import logging
import os
import uuid
from contextlib import ExitStack
from typing import Optional

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

# ── shared resources (created once) ──────────────────────────────────────

_model: Optional[LiteLLMModel] = None
_mcp_tools: list = []
_mcp_exit_stack: Optional[ExitStack] = None


def _get_model() -> LiteLLMModel:
    global _model
    if _model is None:
        _model = LiteLLMModel(
            client_args={
                "api_key": config.LLM_GATEWAY_API_KEY,
                "api_base": config.LLM_GATEWAY_URL,
                "use_litellm_proxy": True,
            },
            model_id=config.MODEL_ID,
            params={"max_tokens": 1000, "temperature": 0.7, "stream": True},
        )
    return _model


def _get_mcp_tools() -> list:
    global _mcp_tools, _mcp_exit_stack
    if _mcp_exit_stack is not None:
        return _mcp_tools

    urls = config.MCP_SERVER_URLS
    if not urls:
        return []

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

    _mcp_tools = tools
    _mcp_exit_stack = stack
    return _mcp_tools


# ── per-session agent creation ───────────────────────────────────────────

def _build_session_manager(session_id: str, actor_id: str):
    """Build an AgentCoreMemorySessionManager for a specific session."""
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

    agentcore_config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=actor_id,
    )
    sm = AgentCoreMemorySessionManager(
        agentcore_memory_config=agentcore_config,
        region_name=region,
    )
    logger.info(f"AgentCore session manager created (memory={memory_id}, session={session_id}, actor={actor_id})")
    return sm


def create_agent(session_id: Optional[str] = None, actor_id: str = "user") -> Agent:
    """Create a Strands agent for a given session.

    Args:
        session_id: Conversation session id. A new UUID is generated when None.
        actor_id: Identity of the caller (default "user").
    """
    session_id = session_id or str(uuid.uuid4())
    session_manager = _build_session_manager(session_id, actor_id)
    tools = _get_mcp_tools() or None

    agent = Agent(
        model=_get_model(),
        system_prompt=config.SYSTEM_PROMPT,
        tools=tools,
        agent_id=config.AGENT_NAME,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
        session_manager=session_manager,
    )
    logger.info(f"Agent created: {config.AGENT_NAME} session={session_id}")
    return agent


# ── session cache ────────────────────────────────────────────────────────

_agents: dict[str, Agent] = {}


def get_or_create_agent(session_id: Optional[str] = None, actor_id: str = "user") -> tuple[Agent, str]:
    """Return a cached agent for *session_id*, creating one if needed.

    Returns (agent, session_id).
    """
    if session_id and session_id in _agents:
        return _agents[session_id], session_id

    sid = session_id or str(uuid.uuid4())
    agent = create_agent(session_id=sid, actor_id=actor_id)
    _agents[sid] = agent
    return agent, sid


# ── cleanup ──────────────────────────────────────────────────────────────

def shutdown_mcp() -> None:
    global _mcp_exit_stack
    if _mcp_exit_stack is not None:
        logger.info("Closing MCP client connections")
        _mcp_exit_stack.close()
        _mcp_exit_stack = None
