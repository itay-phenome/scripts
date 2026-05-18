#!/bin/bash

# Graphviz Install/Update Script (Safe System-Wide Build with Logging)
set -e

LOG_FILE="/var/log/graphviz-install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -i "$LOG_FILE")
exec 2>&1

echo "========== Graphviz Install Script Started at $(date) =========="

# Variables
INSTALL_VERSION="12.2.0"
INSTALL_DIR="$HOME/graphviz-$INSTALL_VERSION"
TARBALL="graphviz-${INSTALL_VERSION}.tar.gz"
URL="https://gitlab.com/graphviz/graphviz/-/archive/${INSTALL_VERSION}/${TARBALL}"

# Step 1: Remove any APT version (just in case)
echo "[1/8] Removing APT-installed Graphviz (if any)..."
sudo apt-get remove --purge -y graphviz libgvc6 libcdt5 libcgraph6 libpathplan4 libgvpr2 || true

# Step 2: Install required build dependencies
echo "[2/8] Installing build dependencies..."
sudo apt-get update
sudo apt-get install -y build-essential bison flex libx11-dev libpng-dev \
    libcairo2-dev libpango1.0-dev libxml2-dev wget git autoconf libtool pkg-config


# Step 3: Download Graphviz source
echo "[3/8] Downloading Graphviz v${INSTALL_VERSION}..."
cd ~
wget --no-check-certificate -O "${TARBALL}" "${URL}"

# Step 4: Extract and prepare source
echo "[4/8] Extracting source..."
tar xzf "${TARBALL}"
cd "graphviz-${INSTALL_VERSION}"

# Step 5: Build and install
echo "[5/8] Running autogen.sh and compiling..."
./autogen.sh
./configure
make -j$(nproc)
sudo make install

# Step 6: Ensure /usr/bin/dot points to correct binary
echo "[6/8] Linking /usr/bin/dot to installed Graphviz..."
if [[ -f "/usr/local/bin/dot" ]]; then
    sudo ln -sf /usr/local/bin/dot /usr/bin/dot
    echo "✔ Symlink created: /usr/bin/dot -> /usr/local/bin/dot"
else
    echo "❌ Error: dot binary not found in /usr/local/bin."
    exit 1
fi

# Step 7: Update linker cache
echo "[7/8] Running ldconfig..."
sudo ldconfig

# Step 8: Final test
echo "[8/8] Testing dot command..."
if dot -V; then
    echo "✅ Graphviz installed successfully and working."
else
    echo "❌ dot command failed. Check installation log."
    exit 1
fi

echo "🎉 Installation complete. Log saved to: $LOG_FILE"

