#!/bin/bash

# Monitor EKS Auto Mode node consolidation events
echo "=== Last 2 hours of consolidation events ==="
kubectl get events --all-namespaces --sort-by='.lastTimestamp' --field-selector involvedObject.kind!=Pod | \
grep -E "(Drained|InstanceTerminating|DisruptionTerminating|DisruptionBlocked|Evicted|Unconsolidatable|RemovingNode)" | \
tail -20

echo -e "\n=== Live monitoring (press Ctrl+C to stop) ==="
kubectl get events --all-namespaces -w | \
grep -E "(Drained|InstanceTerminating|DisruptionTerminating|DisruptionBlocked|Evicted|Unconsolidatable|RemovingNode)" | \
while read line; do
    echo "[$(date)] $line"
done
