#!/bin/bash
# K9s setup script for workshop instances

set -e

echo "Setting up k9s configuration and plugins..."

# Create k9s config directory
mkdir -p ~/.config/k9s/plugins

# Copy plugins
cp -r "$(dirname "$0")/plugins/"* ~/.config/k9s/plugins/

# Install required tools
echo "Installing required tools..."

# Install stern for log streaming
if ! command -v stern &> /dev/null; then
    echo "Installing stern..."
    wget -q https://github.com/stern/stern/releases/download/v1.30.0/stern_1.30.0_linux_amd64.tar.gz
    tar xzf stern_1.30.0_linux_amd64.tar.gz
    sudo mv stern /usr/local/bin/
    rm stern_1.30.0_linux_amd64.tar.gz
    echo "✓ stern installed"
fi

# Install eks-node-viewer
if ! command -v eks-node-viewer &> /dev/null; then
    echo "Installing eks-node-viewer..."
    wget -q https://github.com/awslabs/eks-node-viewer/releases/download/v0.7.4/eks-node-viewer_Linux_x86_64 -O eks-node-viewer
    chmod +x eks-node-viewer
    sudo mv eks-node-viewer /usr/local/bin/
    echo "✓ eks-node-viewer installed"
fi

echo "✓ K9s configuration complete!"
echo ""
echo "Available plugins:"
echo "  ArgoCD (in :apps view):"
echo "    s         - Sync application"
echo "    Shift-R   - Hard refresh"
echo "    Shift-J   - Disable auto-sync"
echo "    Shift-B   - Enable auto-sync"
echo ""
echo "  General (various views):"
echo "    Shift-D   - Describe resource"
echo "    Ctrl-L    - Stern logs"
echo ""
echo "  Nodes (in :nodes view):"
echo "    Shift-X   - EKS Node Viewer"
echo ""
echo "  Containers (in containers view):"
echo "    Shift-D   - Debug container"
echo ""
echo "Restart k9s to load the plugins!"
