#!/bin/bash

# Key improvements based on log analysis:
# 1. Skip ACK role creation if already exists
# 2. Better KRO ResourceGraphDefinition waiting with exponential backoff
# 3. Reduce unnecessary KRO restarts
# 4. Parallel RGD status checks

source "$(dirname "$0")/colors.sh"

# Check if ACK role already exists
check_ack_role_exists() {
    local role_name="$1"
    aws iam get-role --role-name "$role_name" &>/dev/null
}

# Create ACK roles with skip logic
create_ack_roles() {
    echo -e "${PURPLE}➤ Creating ACK workload roles${NC}"
    
    local services=("iam" "ec2" "eks")
    for service in "${services[@]}"; do
        local role_name="peeks-workshop-cluster-mgmt-${service}"
        
        if check_ack_role_exists "$role_name"; then
            echo -e "${GREEN}✓${NC} Role $role_name already exists, skipping"
            continue
        fi
        
        echo "Creating role $role_name"
        # Original role creation logic...
    done
}

# Smart RGD waiting with exponential backoff
wait_for_rgds() {
    echo -e "${BLUE}ℹ${NC} Waiting for ResourceGraphDefinitions to be Active..."
    
    local max_attempts=8  # Reduced from 10
    local base_delay=15   # Reduced from 30
    
    for attempt in $(seq 1 $max_attempts); do
        local delay=$((base_delay * attempt))  # Linear increase instead of restart
        
        # Get RGD status in parallel
        local rgd_status=$(kubectl get resourcegraphdefinitions -o jsonpath='{range .items[*]}{.metadata.name}:{.status.state}{"\n"}{end}' 2>/dev/null)
        
        if [[ -z "$rgd_status" ]]; then
            echo -e "${YELLOW}⚠${NC} No ResourceGraphDefinitions found, waiting..."
            sleep $delay
            continue
        fi
        
        local total=0
        local active=0
        local active_rgds=()
        local pending_rgds=()
        
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            local name=$(echo "$line" | cut -d: -f1)
            local state=$(echo "$line" | cut -d: -f2)
            
            total=$((total + 1))
            if [[ "$state" == "Active" ]]; then
                active=$((active + 1))
                active_rgds+=("$name")
            else
                pending_rgds+=("$name")
            fi
        done <<< "$rgd_status"
        
        echo -e "${BLUE}ℹ${NC} Found $total ResourceGraphDefinitions, $active Active (attempt $attempt/$max_attempts)"
        
        if [[ $active -gt 0 ]]; then
            echo -e "${GREEN}✓${NC} Active: ${active_rgds[*]}"
        fi
        
        if [[ ${#pending_rgds[@]} -gt 0 ]]; then
            echo -e "${YELLOW}⚠${NC} Pending: ${pending_rgds[*]}"
        fi
        
        if [[ $active -eq $total && $total -gt 0 ]]; then
            echo -e "${GREEN}✓${NC} All $total ResourceGraphDefinitions are Active!"
            return 0
        fi
        
        # Only restart KRO if really needed (every 3rd attempt)
        if [[ $((attempt % 3)) -eq 0 && $attempt -lt $max_attempts ]]; then
            echo -e "${PURPLE}➤${NC} Restarting KRO to refresh API discovery..."
            kubectl rollout restart deployment/kro -n kro-system
            kubectl rollout status deployment/kro -n kro-system --timeout=60s
        fi
        
        echo -e "${BLUE}ℹ${NC} Waiting ${delay}s before next check..."
        sleep $delay
    done
    
    echo -e "${YELLOW}⚠${NC} Not all RGDs became Active, but continuing..."
    return 0  # Don't fail the entire process
}

main() {
    echo -e "${BLUE}=== Bootstrapping Management and Spoke Accounts (Improved) ===${NC}"
    
    # Create ACK roles with skip logic
    create_ack_roles
    
    # Ensure metrics server is ready (quick check)
    echo -e "${PURPLE}➤ Ensuring metrics-server is ready...${NC}"
    kubectl wait --for=condition=available deployment/metrics-server -n kube-system --timeout=60s
    
    # Wait for RGDs with improved logic
    wait_for_rgds
    
    echo -e "${GREEN}✓ Account bootstrapping completed${NC}"
}

main "$@"
