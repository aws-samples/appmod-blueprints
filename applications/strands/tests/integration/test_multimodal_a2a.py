#!/usr/bin/env python3
"""Test multi-modal A2A API with text and images."""

import base64
import json
import requests
from pathlib import Path


def encode_image(image_path: str) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def test_text_only():
    """Test with text only."""
    print("=" * 60)
    print("Test 1: Text-only message")
    print("=" * 60)
    
    url = "http://localhost:8083/message"
    
    payload = {
        "role": "user",
        "parts": [
            {
                "kind": "text",
                "text": "Hello! What is 2+2?"
            }
        ]
    }
    
    print(f"Request: {json.dumps(payload, indent=2)}")
    print()
    
    response = requests.post(url, json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_text_with_image():
    """Test with text and image."""
    print("=" * 60)
    print("Test 2: Multi-modal message (text + image)")
    print("=" * 60)
    
    url = "http://localhost:8083/message"
    
    # Create a simple test image (1x1 red pixel PNG)
    # This is a valid PNG image encoded in base64
    test_image_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    
    payload = {
        "role": "user",
        "parts": [
            {
                "kind": "text",
                "text": "What's in this image?"
            },
            {
                "kind": "file",
                "type": "image/png",
                "data": test_image_base64,
                "filename": "test.png"
            }
        ]
    }
    
    print(f"Request: {json.dumps({**payload, 'parts': [payload['parts'][0], {'kind': 'file', 'type': 'image/png', 'data': '<base64_data>', 'filename': 'test.png'}]}, indent=2)}")
    print()
    
    response = requests.post(url, json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_multiple_parts():
    """Test with multiple text and data parts."""
    print("=" * 60)
    print("Test 3: Multiple parts (text + JSON + text)")
    print("=" * 60)
    
    url = "http://localhost:8083/message"
    
    payload = {
        "role": "user",
        "parts": [
            {
                "kind": "text",
                "text": "Here's some data:"
            },
            {
                "kind": "json",
                "json": {
                    "name": "Alice",
                    "age": 30,
                    "city": "Seattle"
                }
            },
            {
                "kind": "text",
                "text": "Can you summarize this information?"
            }
        ]
    }
    
    print(f"Request: {json.dumps(payload, indent=2)}")
    print()
    
    response = requests.post(url, json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_agent_card():
    """Test agent card endpoint."""
    print("=" * 60)
    print("Test 4: Agent Card (capabilities)")
    print("=" * 60)
    
    url = "http://localhost:8083/.well-known/agent.json"
    
    response = requests.get(url)
    
    print(f"Status: {response.status_code}")
    print(f"Agent Card: {json.dumps(response.json(), indent=2)}")
    print()


if __name__ == "__main__":
    print("\n🧪 Testing Multi-Modal A2A API\n")
    
    try:
        # Test agent card first
        test_agent_card()
        
        # Test text-only
        test_text_only()
        
        # Test with image
        test_text_with_image()
        
        # Test multiple parts
        test_multiple_parts()
        
        print("✅ All tests completed!")
        
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to the server.")
        print("Make sure the server is running on http://localhost:8083")
        print("Run: uv run python -m app.main")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
