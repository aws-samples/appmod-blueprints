#!/usr/bin/env bash
set -euxo pipefail

echo ">>> Installing Kata Containers with Cloud Hypervisor for AL2023"

# =============================================================================
# 0. Grow root partition to use full disk
# =============================================================================
echo ">>> Growing root partition..."
sudo growpart /dev/nvme0n1 1 || sudo growpart /dev/xvda 1 || true
sudo xfs_growfs / || sudo resize2fs /dev/nvme0n1p1 || sudo resize2fs /dev/xvda1 || true
df -h /

# =============================================================================
# 1. Install dependencies
# =============================================================================
sudo dnf install -y jq tar gzip zstd

# =============================================================================
# 2. Configure KVM module auto-load
# Works on both bare metal AND nested virtualization (c8i/m8i/r8i instances)
# On nested virt: AWS Nitro (L0) passes through VT-x to KVM (L1 hypervisor)
# =============================================================================
echo ">>> Configuring KVM module auto-load..."

cat <<EOF | sudo tee /etc/modules-load.d/kvm.conf
kvm
kvm_intel
kvm_amd
EOF

# =============================================================================
# 3. Download and install Kata Containers
# =============================================================================
KATA_VERSION="${KATA_VERSION:-3.26.0}"
WORKDIR="$HOME/kata-install"

echo ">>> Installing Kata Containers ${KATA_VERSION}..."

mkdir -p "$WORKDIR"
cd "$WORKDIR"

echo ">>> Downloading Kata static release..."
curl -fSL --retry 3 --retry-delay 5 -o kata-static.tar.zst \
    "https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-amd64.tar.zst"

# Verify download isn't empty/truncated (tarball should be >100MB)
FILESIZE=$(stat -c%s kata-static.tar.zst)
echo ">>> Downloaded file size: ${FILESIZE} bytes"
if [ "$FILESIZE" -lt 100000000 ]; then
    echo "ERROR: Downloaded file too small (${FILESIZE} bytes), likely corrupted"
    exit 1
fi

echo ">>> Decompressing with zstd..."
zstd -d -f kata-static.tar.zst -o kata-static.tar
ls -lh kata-static.tar

echo ">>> Extracting tar..."
sudo tar -xvf kata-static.tar -C /
# NOTE: A mid-script `sudo sync` here flushes ~4.7GB and can exceed SSH idle
# timeout, killing the provisioner. The final `sync` at the end does this
# once extraction + config writes are all done.

# Verify binaries are not empty
echo ">>> Verifying Kata installation..."
ls -la /opt/kata/bin/
SHIM_SIZE=$(stat -c%s /opt/kata/bin/containerd-shim-kata-v2)
if [ "$SHIM_SIZE" -eq 0 ]; then
    echo "ERROR: containerd-shim-kata-v2 is 0 bytes - extraction failed"
    exit 1
fi
/opt/kata/bin/kata-runtime --version

# Cleanup
cd /
rm -rf "$WORKDIR"

# Create symlinks
sudo ln -sf /opt/kata/bin/kata-runtime /usr/local/bin/kata-runtime
sudo ln -sf /opt/kata/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2

# =============================================================================
# 4. Configure Kata for Cloud Hypervisor
# =============================================================================
echo ">>> Configuring Kata for Cloud Hypervisor..."

sudo mkdir -p /etc/kata-containers
sudo cp /opt/kata/share/defaults/kata-containers/configuration-clh.toml \
    /etc/kata-containers/configuration.toml
sudo ln -sf /etc/kata-containers/configuration.toml \
    /etc/kata-containers/configuration-clh.toml

# =============================================================================
# 5. Containerd runtime config is handled by nodeadm via EC2NodeClass userData
# =============================================================================
# NOTE: Do NOT configure containerd here. EKS AL2023 uses nodeadm which
# regenerates /etc/containerd/config.toml at boot. The kata runtime entries
# are injected via the NodeConfig containerd.config field in the Karpenter
# EC2NodeClass userData, which nodeadm merges before starting containerd.

# =============================================================================
# 6. Create verification script
# =============================================================================
cat <<'EOF' | sudo tee /usr/local/bin/verify-kata.sh
#!/bin/bash
echo "=== KVM Check ==="
ls -la /dev/kvm 2>/dev/null || echo "KVM not available"
lsmod | grep kvm || echo "KVM modules not loaded"

echo ""
echo "=== Kata Version ==="
/opt/kata/bin/kata-runtime --version

echo ""
echo "=== Containerd Config ==="
grep -A5 kata /etc/containerd/config.toml
EOF
sudo chmod +x /usr/local/bin/verify-kata.sh

echo ">>> Kata Containers installation complete!"
echo ">>> Final verification:"
/opt/kata/bin/kata-runtime --version

# =============================================================================
# CRITICAL: Flush page cache to disk before Packer stops the instance
# =============================================================================
# The ~4.7GB Kata release sits in Linux page cache after extraction.
# Without sync, Packer may stop the instance before dirty pages are written
# to the EBS volume, resulting in 0-byte files in the AMI.
echo ">>> Syncing filesystem..."
sync
sleep 5
sync
