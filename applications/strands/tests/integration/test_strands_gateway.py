#!/usr/bin/env python3
"""Test Strands Agent with LiteLLM through AgentGateway."""

import logging
from strands import Agent
from strands.models.litellm import LiteLLMModel

# Enable debug logging to see HTTP requests
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configuration
GATEWAY_URL = "http://localhost:4000/"  # "http://agentgateway-proxy.agentgateway-system.svc.cluster.local"
MODEL_ID = "claude-sonnet" # "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
# For LiteLLM proxy, you can use either:
# Option 1: Prefix with litellm_proxy/
# MODEL_ID = "litellm_proxy/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
# Option 2: Use use_litellm_proxy=True in client_args (see below)


def test_strands_agent():
    """Test Strands Agent with LiteLLM through AgentGateway."""
    print("Testing Strands Agent with LiteLLM through AgentGateway")
    print(f"Gateway URL: {GATEWAY_URL}")
    print(f"Model ID: {MODEL_ID}")
    print()
    
    try:
        # 1. Initialize LiteLLM model pointing to AgentGateway
        # The gateway handles credentials internally via pod identity
        print("Creating LiteLLMModel with AgentGateway endpoint...")
        
        # Using OpenAI-compatible endpoint (not LiteLLM proxy)
        # The gateway is OpenAI-compatible, so we use the openai/ prefix
        kgateway_model = LiteLLMModel(
            client_args={
                "api_key": "sk-1234",  # Required by LiteLLM but gateway may ignore it
                "api_base": GATEWAY_URL,
                "use_litellm_proxy": True
            },
            model_id=MODEL_ID,  # openai/ prefix for OpenAI-compatible endpoints
            params={
                "max_tokens": 1000,
                "temperature": 0.7,
            }
        )
        
        # 2. Create the Strands Agent using this model
        print("Creating Strands Agent...")
        agent = Agent(
            model=kgateway_model,
            system_prompt="You are a helpful AI assistant communicating through AgentGateway."
        )
        
        # 3. Invoke the agent
        print("Invoking agent...")
        print()
        
        response = agent("Hello! Please respond with a short greeting.")
        
        print("✅ Success!")
        print()
        print(f"Response: {response}")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print(f"Error type: {type(e).__name__}")
        
        import traceback
        traceback.print_exc()
        
        return False


if __name__ == "__main__":
    import sys
    
    success = test_strands_agent()
    
    if success:
        print("✅ Test passed!")
        sys.exit(0)
    else:
        print("❌ Test failed")
        sys.exit(1)
