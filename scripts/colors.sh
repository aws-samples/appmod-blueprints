#!/bin/bash

# ANSI color codes for better readability
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[0;33m'
export BLUE='\033[0;34m'
export MAGENTA='\033[0;35m'
export CYAN='\033[0;36m'
export BOLD='\033[1m'
export UNDERLINE='\033[4m'
export NC='\033[0m' # No Color

# Function to print section headers
print_header() {
    echo -e "\n${BOLD}${BLUE}=== $1 ===${NC}\n"
}

# Function to print success messages
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print error messages
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to print warning messages
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print info messages
print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Function to print step messages
print_step() {
    echo -e "${MAGENTA}➤ $1${NC}"
}

# Function to update or add environment variable to ~/.bashrc.d/platform.sh
update_workshop_var() {
    local var_name="$1"
    local var_value="$2"
    local workshop_file="$HOME/.bashrc.d/platform.sh"
    
    # Check if variable already exists in the file
    if grep -q "^export ${var_name}=" "$workshop_file" 2>/dev/null; then
        # Variable exists, update it
        sed -i "s|^export ${var_name}=.*|export ${var_name}=\"${var_value}\"|" "$workshop_file"
        print_info "Updated ${var_name} in ${workshop_file}"
    else
        # Variable doesn't exist, add it
        echo "export ${var_name}=\"${var_value}\"" >> "$workshop_file"
        print_info "Added ${var_name} to ${workshop_file}"
    fi
}