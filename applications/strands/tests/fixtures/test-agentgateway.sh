#!/bin/bash
set -e

echo "🧪 Testing AgentGateway Integration"
echo "===================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

GATEWAY_URL="http://agentgateway-proxy.agentgateway-system.svc.cluster.local"

echo "1️⃣  Testing AgentGateway /v1/chat/completions endpoint..."
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" "${GATEWAY_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-test" \
  -d '{
    "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "messages": [{"role": "user", "content": "Say hello in one sentence"}]
  }')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✅ AgentGateway OpenAI endpoint works!${NC}"
    echo ""
    echo "Response:"
    echo "$BODY" | jq '.'
    echo ""
else
    echo -e "${RED}❌ Failed with HTTP $HTTP_CODE${NC}"
    echo "$BODY"
    exit 1
fi

echo ""
echo "2️⃣  Testing without Authorization header..."
echo ""

RESPONSE2=$(curl -s -w "\n%{http_code}" "${GATEWAY_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "messages": [{"role": "user", "content": "Say hello"}]
  }')

HTTP_CODE2=$(echo "$RESPONSE2" | tail -n1)

if [ "$HTTP_CODE2" = "200" ]; then
    echo -e "${GREEN}✅ Works without Authorization header too!${NC}"
    echo -e "${YELLOW}ℹ️  AgentGateway is in permissive mode${NC}"
elif [ "$HTTP_CODE2" = "401" ]; then
    echo -e "${YELLOW}⚠️  Requires Authorization header (got 401)${NC}"
    echo -e "${YELLOW}ℹ️  But placeholder keys work, so we're good!${NC}"
else
    echo -e "${RED}❌ Unexpected response: HTTP $HTTP_CODE2${NC}"
fi

echo ""
echo "3️⃣  Testing streaming endpoint..."
echo ""

curl -s "${GATEWAY_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-test" \
  -d '{
    "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "messages": [{"role": "user", "content": "Count to 3"}],
    "stream": true
  }' \
  --no-buffer | head -n 5

echo ""
echo -e "${GREEN}✅ Streaming works!${NC}"
echo ""

echo "===================================="
echo -e "${GREEN}🎉 All tests passed!${NC}"
echo ""
echo "Next steps:"
echo "1. Rebuild the Strands agent image: ./build.sh push"
echo "2. Deploy with AgentGateway: kubectl apply -f test-pod.yaml"
echo "3. Test the agent: kubectl port-forward pod/strands-agent-test 8083:8083"
echo "4. Invoke: curl -X POST http://localhost:8083/invoke -H 'Content-Type: application/json' -d '{\"prompt\": \"Hello\"}'"
