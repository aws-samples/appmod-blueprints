#!/usr/bin/env python3
"""Debug script to test AgentGateway with OpenAI client directly."""

import asyncio
import json
import openai

GATEWAY_URL = "http://agentgateway-proxy.agentgateway-system.svc.cluster.local"
MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"


async def test_basic_request():
    """Test basic OpenAI request to AgentGateway."""
    print("Testing basic OpenAI request to AgentGateway...")
    print(f"URL: {GATEWAY_URL}/v1")
    print(f"Model: {MODEL_ID}")
    print()
    
    client = openai.AsyncOpenAI(
        base_url=f"{GATEWAY_URL}/v1",
        api_key="sk-test",
        timeout=60.0,
    )
    
    try:
        # Test 1: Minimal request
        print("Test 1: Minimal request")
        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": "Say hello"}
            ],
        )
        print(f"✅ Success: {response.choices[0].message.content}")
        print()
        
        # Test 2: With temperature
        print("Test 2: With temperature parameter")
        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": "Count to 3"}
            ],
            temperature=0.7,
        )
        print(f"✅ Success: {response.choices[0].message.content}")
        print()
        
        # Test 3: With max_tokens
        print("Test 3: With max_tokens parameter")
        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": "Tell me a joke"}
            ],
            max_tokens=100,
        )
        print(f"✅ Success: {response.choices[0].message.content}")
        print()
        
        # Test 4: With system message
        print("Test 4: With system message")
        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi"}
            ],
        )
        print(f"✅ Success: {response.choices[0].message.content}")
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"Type: {type(e)}")
        if hasattr(e, 'response'):
            print(f"Response: {e.response}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.close()


async def test_strands_style():
    """Test with parameters that Strands might use."""
    print("\nTesting Strands-style request...")
    
    client = openai.AsyncOpenAI(
        base_url=f"{GATEWAY_URL}/v1",
        api_key="sk-test",
        timeout=60.0,
    )
    
    try:
        # Strands might send additional parameters
        response = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": "Hello"}
            ],
            # Common Strands/Bedrock parameters
            temperature=0.7,
            max_tokens=1000,
            top_p=0.9,
        )
        print(f"✅ Success: {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_basic_request())
    asyncio.run(test_strands_style())
