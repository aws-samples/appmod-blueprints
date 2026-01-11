#!/usr/bin/env bash

# Add this function to utils.sh after the initialize_terraform function

# Force unlock Terraform state if locked
force_unlock_if_needed() {
  local script_dir=$1
  local max_wait=300  # 5 minutes max wait for lock
  local wait_time=0
  
  log "Checking for Terraform state locks..."
  
  # Try to get state lock info
  if terraform -chdir=$script_dir plan -detailed-exitcode -lock-timeout=10s &>/dev/null; then
    log "No state lock detected"
    return 0
  fi
  
  # If plan fails due to lock, try to get lock info
  local lock_output=$(terraform -chdir=$script_dir plan -lock-timeout=1s 2>&1 || true)
  
  if echo "$lock_output" | grep -q "Error acquiring the state lock"; then
    log_warning "State lock detected, attempting to resolve..."
    
    # Extract lock ID from error message
    local lock_id=$(echo "$lock_output" | grep -A 20 "Lock Info:" | grep "ID:" | awk '{print $2}' | head -1)
    
    if [[ -n "$lock_id" ]]; then
      log "Found lock ID: $lock_id"
      
      # Check if lock is stale (older than 30 minutes)
      local lock_created=$(echo "$lock_output" | grep -A 20 "Lock Info:" | grep "Created:" | cut -d' ' -f4-)
      if [[ -n "$lock_created" ]]; then
        local lock_age_seconds=$(( $(date +%s) - $(date -d "$lock_created" +%s 2>/dev/null || echo 0) ))
        
        if [[ $lock_age_seconds -gt 1800 ]]; then  # 30 minutes
          log_warning "Lock is stale (${lock_age_seconds}s old), forcing unlock..."
          if terraform -chdir=$script_dir force-unlock -force "$lock_id"; then
            log_success "Successfully unlocked stale state lock"
            return 0
          else
            log_error "Failed to force unlock state"
            return 1
          fi
        else
          log "Lock is recent (${lock_age_seconds}s old), waiting..."
          sleep 30
          return 1
        fi
      else
        log_warning "Cannot determine lock age, forcing unlock..."
        if terraform -chdir=$script_dir force-unlock -force "$lock_id"; then
          log_success "Successfully unlocked state lock"
          return 0
        else
          log_error "Failed to force unlock state"
          return 1
        fi
      fi
    else
      log_error "Could not extract lock ID from error message"
      return 1
    fi
  fi
  
  return 0
}
