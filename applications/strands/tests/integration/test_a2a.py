"""Test script to inspect A2AServer structure."""

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.multiagent.a2a.server import A2AServer

# Create a simple agent
model = BedrockModel(model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0")
agent = Agent(model=model, system_prompt="You are a helpful assistant")

# Create A2A server
a2a_server = A2AServer(agent)

# Inspect the server
print("A2AServer type:", type(a2a_server))
print("\nA2AServer attributes:")
for attr in dir(a2a_server):
    if not attr.startswith('_'):
        print(f"  - {attr}")

print("\nChecking for ASGI app attributes:")
if hasattr(a2a_server, 'app'):
    print(f"  - a2a_server.app: {type(a2a_server.app)}")
if hasattr(a2a_server, 'asgi_app'):
    print(f"  - a2a_server.asgi_app: {type(a2a_server.asgi_app)}")
if hasattr(a2a_server, '_app'):
    print(f"  - a2a_server._app: {type(a2a_server._app)}")
if hasattr(a2a_server, 'application'):
    print(f"  - a2a_server.application: {type(a2a_server.application)}")

print("\nIs callable?", callable(a2a_server))
print("Has __call__?", hasattr(a2a_server, '__call__'))

# Check if it's an ASGI app
print("\nASGI check:")
import inspect
sig = inspect.signature(a2a_server.__class__.__init__)
print(f"  - __init__ signature: {sig}")
