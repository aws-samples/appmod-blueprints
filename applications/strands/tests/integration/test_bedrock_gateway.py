#!/usr/bin/env python3
"""Test Bedrock Converse API through AgentGateway using boto3."""

import boto3
import json
import sys

# Configuration
GATEWAY_URL = "http://localhost:8080" #"http://agentgateway-proxy.agentgateway-system.svc.cluster.local"
MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
REGION = "us-west-2"


def test_converse():
    """Test Bedrock converse API through AgentGateway."""
    print("Testing Bedrock Converse API through AgentGateway")
    print(f"Gateway URL: {GATEWAY_URL}")
    print(f"Model ID: {MODEL_ID}")
    print(f"Region: {REGION}")
    print()
    
    # Create bedrock-runtime client pointing to AgentGateway
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=GATEWAY_URL,
        region_name=REGION,
    )
    
    print("Client created, sending request...")
    print()
    
    try:
        # Call converse API
        response = client.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": "Hello! Please respond with a short greeting."
                        }
                    ]
                }
            ]
        )
        
        print("✅ Success!")
        print()
        print("Response:")
        print(json.dumps(response, indent=2, default=str))
        print()
        
        # Extract the text response
        output_message = response.get("output", {}).get("message", {})
        content = output_message.get("content", [])
        if content:
            text = content[0].get("text", "")
            print(f"Assistant: {text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print(f"Error type: {type(e).__name__}")
        
        if hasattr(e, 'response'):
            print(f"Response: {e.response}")
        
        import traceback
        traceback.print_exc()
        
        return False


def test_converse_stream():
    """Test Bedrock converse stream API through AgentGateway."""
    print("\n" + "="*60)
    print("Testing Bedrock Converse Stream API through AgentGateway")
    print("="*60 + "\n")
    
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=GATEWAY_URL,
        region_name=REGION,
    )
    
    try:
        # Call converse stream API
        response = client.converse_stream(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": "Count to 3"
                        }
                    ]
                }
            ]
        )
        
        print("✅ Streaming response:")
        print()
        
        # Process stream
        stream = response.get('stream')
        full_text = ""
        
        for event in stream:
            if 'contentBlockDelta' in event:
                delta = event['contentBlockDelta']['delta']
                if 'text' in delta:
                    text = delta['text']
                    full_text += text
                    print(text, end='', flush=True)
        
        print()
        print()
        print(f"Full response: {full_text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Test non-streaming
    success1 = test_converse()
    
    # Test streaming
    success2 = test_converse_stream()
    
    if success1 and success2:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)
