# K9s Configuration for Platform on EKS Workshop

This directory contains k9s configuration and plugins for the workshop environment.

## Quick Setup

Run the setup script to install k9s plugins and required tools:

```bash
cd /home/ec2-user/environment/platform-on-eks-workshop/hack/k9s
./setup-k9s.sh
```

## Plugins Included

### ArgoCD Management (`:apps` view)
- `s` - Sync ArgoCD application
- `Shift-R` - Hard refresh application
- `Shift-J` - Disable auto-sync
- `Shift-B` - Enable auto-sync

### General Utilities
- `Shift-D` - Describe resource (works on most resources)
- `Ctrl-L` - Stream logs with stern (pods, deployments, etc.)

### EKS Specific (`:nodes` view)
- `Shift-X` - Launch EKS Node Viewer with cluster visualization

### Debug Tools (containers view)
- `Shift-D` - Attach debug container to running pod

## Required Tools

The setup script automatically installs:
- **stern** (v1.30.0) - Multi-pod log streaming
- **eks-node-viewer** (v0.7.4) - Real-time cluster visualization

## Usage

1. Start k9s: `k9s`
2. Navigate to resource type (e.g., `:apps`, `:nodes`, `:pods`)
3. Select a resource with arrow keys
4. Press plugin shortcut key
5. Press `?` to see available shortcuts in any view

## Manual Installation

If you prefer manual setup:

```bash
# Copy plugins
mkdir -p ~/.config/k9s
cp -r plugins ~/.config/k9s/

# Install tools manually
# (see setup-k9s.sh for commands)
```
