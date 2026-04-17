"""Configuration management for Strands agent."""

import json
import os
from typing import Optional


class Config:
    """Application configuration from environment variables."""

    # Agent configuration
    AGENT_NAME: str = os.getenv("AGENT_NAME", "strands-agent")
    AGENT_DESCRIPTION: str = os.getenv(
        "AGENT_DESCRIPTION", "A Strands agent with A2A protocol support"
    )
    
    # System prompt
    SYSTEM_PROMPT: str = os.getenv(
        "SYSTEM_PROMPT",
        """You are a helpful AI assistant with access to various tools and capabilities.
You can help with general questions, data analysis, and task automation.
Always be clear, concise, and helpful in your responses.
Use the A2A protocol to communicate with other agents when needed.
When tools are available, always prefer using them over relying on your training data.
For example, always use the time tool when asked about the current time or date.""",
    )
    
    # Model configuration
    MODEL_ID: str = os.getenv("MODEL_ID", "claude-sonnet")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-west-2")
    
    # LLM Gateway configuration (LiteLLM proxy)
    LLM_GATEWAY_URL: str = os.getenv(
        "LLM_GATEWAY_URL",
        "http://litellm-proxy.agentgateway-system.svc.cluster.local:4000"
    )
    # Gateway API key (optional - some gateways don't require it)
    LLM_GATEWAY_API_KEY: str = os.getenv("LLM_GATEWAY_API_KEY", "sk-1234")
    
    # AgentGateway MCP proxy base URL (internal cluster DNS)
    GATEWAY_URL: str = os.getenv(
        "GATEWAY_URL",
        "http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80"
    )

    # MCP server names to load via the gateway (comma-separated, maps to /mcp/<name>)
    MCP_SERVER_NAMES_RAW: Optional[str] = os.getenv("MCP_SERVER_NAMES")

    @property
    def MCP_SERVER_NAMES(self) -> list[str]:
        """Parse MCP server names from comma-separated string."""
        if not self.MCP_SERVER_NAMES_RAW:
            return []
        return [s.strip() for s in self.MCP_SERVER_NAMES_RAW.split(",") if s.strip()]

    @property
    def MCP_SERVER_URLS(self) -> list[str]:
        """Build full MCP URLs from server names via the gateway."""
        return [
            f"{self.GATEWAY_URL}/mcp/{name}"
            for name in self.MCP_SERVER_NAMES
        ]
    
    # Memory configuration
    MEMORY_PROVIDER: Optional[str] = os.getenv("MEMORY_PROVIDER")
    _MEMORY_CONFIG_RAW: Optional[str] = os.getenv("MEMORY_CONFIG")

    @property
    def MEMORY_CONFIG(self) -> dict:
        """Parse MEMORY_CONFIG from JSON string."""
        if not self._MEMORY_CONFIG_RAW:
            return {}
        return json.loads(self._MEMORY_CONFIG_RAW)

    # Server configuration
    PORT: int = int(os.getenv("PORT", "8083"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # A2A configuration
    A2A_BASE_PATH: str = ""  # Mount at root
    
    def __repr__(self) -> str:
        """String representation of config (hiding sensitive data)."""
        return (
            f"Config(agent_name={self.AGENT_NAME}, "
            f"model_id={self.MODEL_ID}, "
            f"region={self.AWS_REGION}, "
            f"llm_gateway={self.LLM_GATEWAY_URL}, "
            f"mcp_servers={self.MCP_SERVER_NAMES}, "
            f"port={self.PORT})"
        )


# Global config instance
config = Config()
