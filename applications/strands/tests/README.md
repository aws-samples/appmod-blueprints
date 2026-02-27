# Tests

This directory contains all test files and fixtures for the Strands Agent application.

## Structure

```
tests/
├── __init__.py
├── integration/              # Integration tests
│   ├── test_a2a.py          # A2A protocol tests
│   ├── test_multimodal_a2a.py  # Multi-modal API tests
│   ├── test_bedrock_gateway.py # Bedrock gateway tests
│   └── test_strands_gateway.py # Strands with gateway tests
└── fixtures/                 # Test fixtures and helpers
    ├── create-test-role.sh  # Script to create test IAM role
    ├── test-pod.yaml        # Kubernetes test pod manifest
    ├── test-pod-direct-bedrock.yaml  # Direct Bedrock test pod
    ├── test-agentgateway.sh # AgentGateway test script
    ├── multimodal-curl-examples.txt  # Curl examples
    └── debug-request.py     # Debug helper script
```

## Running Tests

### Integration Tests

Run all integration tests:
```bash
uv run pytest tests/integration/
```

Run specific test:
```bash
uv run python tests/integration/test_multimodal_a2a.py
```

### Prerequisites

1. Start the server:
```bash
uv run python -m app.main
```

2. For gateway tests, ensure AgentGateway is running:
```bash
kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:80
```

## Test Categories

### A2A Protocol Tests
- `test_a2a.py` - Basic A2A protocol compliance
- `test_multimodal_a2a.py` - Multi-modal content (text + images)

### Gateway Integration Tests
- `test_bedrock_gateway.py` - Direct Bedrock via gateway
- `test_strands_gateway.py` - Strands agent via LiteLLM gateway

## Fixtures

The `fixtures/` directory contains:
- Kubernetes manifests for testing in cluster
- Shell scripts for setup and testing
- Example curl commands
- Debug utilities

## Adding New Tests

1. Create test file in `tests/integration/`
2. Follow naming convention: `test_*.py`
3. Use pytest or standalone script format
4. Add fixtures to `tests/fixtures/` if needed
5. Update this README

## Notes

- Integration tests require a running server
- Some tests require AWS credentials or AgentGateway access
- See main TESTING.md for detailed testing documentation
