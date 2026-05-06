#!/bin/bash
# fix-bootstrap-post-clone.sh
# Run this on the IDE instance when the git/NFS bug in bootstrap-mise.sh
# prevents the workshop repo clone from completing. This script re-executes
# everything that comes AFTER the git clone in bootstrap-mise.sh.
#
# Usage: bash ~/environment/platform-on-eks-workshop/platform/infra/terraform/scripts/fix-bootstrap-post-clone.sh

set -e

export BASE_DIR="${WORKSPACE_PATH:-/home/ec2-user/environment}/${WORKING_REPO:-platform-on-eks-workshop}"

if [ ! -d "$BASE_DIR/.git" ]; then
  echo "ERROR: $BASE_DIR does not exist. Clone the repo first:"
  echo "  git clone --single-branch --no-tags --branch \$WORKSHOP_GIT_BRANCH \$WORKSHOP_GIT_URL $BASE_DIR"
  exit 1
fi

cd $BASE_DIR
echo "=== Running post-clone setup from $BASE_DIR ==="

# Ensure mise-managed tools (uv, etc.) are on PATH
eval "$(~/.local/bin/mise activate bash 2>/dev/null)" || true
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"

# Install uv if missing (git/NFS bug may have interrupted mise setup)
if ! command -v uv &>/dev/null; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Zsh config
cp hack/.zshrc hack/.p10k.zsh hack/.zsh_history ~/

# bashrc.d
mkdir -p ~/.bashrc.d
cp $BASE_DIR/hack/.bashrc.d/* ~/.bashrc.d/

# MCP servers
uv tool install mcp-proxy-for-aws || true
uv tool install awslabs.aws-iac-mcp-server || true

# Kiro config
mkdir -p ~/.kiro
cp -r $BASE_DIR/hack/.kiro/* ~/.kiro/

# k9s plugins
mkdir -p ~/.config/k9s
cp -r $BASE_DIR/hack/k9s/plugins ~/.config/k9s/ || true

# Aliases and completions
echo 'eval "$(mise activate bash)"' >> ~/.bashrc.d/aliases.sh
echo "export PATH=${KREW_ROOT:-/home/ec2-user/.krew}/bin:/home/ec2-user/.local/bin:~/go/bin:$PATH" | tee -a ~/.bashrc.d/aliases.sh
kubectl completion bash >> ~/.bash_completion
argocd completion bash >> ~/.bash_completion
helm completion bash >> ~/.bash_completion
echo "alias k=kubectl" >> ~/.bashrc.d/aliases.sh
echo "alias kgn='kubectl get nodes -L beta.kubernetes.io/arch -L eks.amazonaws.com/capacityType -L beta.kubernetes.io/instance-type -L eks.amazonaws.com/nodegroup -L topology.kubernetes.io/zone -L karpenter.sh/provisioner-name -L karpenter.sh/capacity-type'" | tee -a ~/.bashrc.d/aliases.sh
echo "alias ll='ls -la'" >> ~/.bashrc.d/aliases.sh
echo "alias ktx=kubectx" >> ~/.bashrc.d/aliases.sh
echo "alias kctx=kubectx" >> ~/.bashrc.d/aliases.sh
echo "alias kns=kubens" >> ~/.bashrc.d/aliases.sh
echo "export TERM=xterm-color" >> ~/.bashrc.d/aliases.sh
echo "alias code='~/.local/lib/code-editor-v*-linux-x64/dist/bin/remote-cli/code'" >> ~/.bashrc.d/aliases.sh
echo 'alias pytest=pytest-3' >> ~/.bashrc.d/aliases.sh
echo "alias open='xdg-open'" >> ~/.bashrc.d/aliases.sh
echo "complete -F __start_kubectl k" >> ~/.bashrc.d/aliases.sh

# Chromium deps for Playwright
sudo yum install -y atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib nss nspr libXScrnSaver libXtst gtk3

echo "=== Post-clone setup complete. Run 'source ~/.bashrc.d/platform.sh' ==="
