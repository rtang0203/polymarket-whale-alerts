#!/bin/bash
# Polymarket Whale Scanner - Droplet Setup Script
# Run as root on a fresh Ubuntu 22.04+ droplet
#
# Usage:
#   1. Clone repo to /opt/polymarket-scanner (or anywhere else)
#   2. Run: sudo bash deploy/setup.sh
#   3. Edit /var/lib/polymarket-scanner/.env with your Discord webhook
#   4. Run: sudo systemctl start polymarket-scanner

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/polymarket-scanner"
DATA_DIR="/var/lib/polymarket-scanner"

echo "=== Polymarket Whale Scanner Setup ==="
echo "Source: $REPO_DIR"
echo "Install: $INSTALL_DIR"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo bash deploy/setup.sh)"
    exit 1
fi

# Install dependencies
echo "[1/6] Installing system dependencies..."
apt update
apt install -y python3 python3-venv python3-pip

# Create app user
echo "[2/6] Creating app user..."
if ! id "app" &>/dev/null; then
    adduser --system --group --home "$DATA_DIR" app
fi

# Create directories
echo "[3/6] Setting up directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR"

# Copy application code (skip if already in place)
echo "[4/6] Deploying application..."
if [ "$REPO_DIR" != "$INSTALL_DIR" ]; then
    cp -r "$REPO_DIR/src" "$REPO_DIR/requirements.txt" "$REPO_DIR/scripts" "$REPO_DIR/deploy" "$INSTALL_DIR/"
else
    echo "  Already in $INSTALL_DIR, skipping copy"
fi

# Set ownership before creating venv (so app user owns it)
chown -R app:app "$INSTALL_DIR"

# Setup Python environment as app user
echo "[5/6] Setting up Python environment..."
cd "$INSTALL_DIR"
sudo -u app python3 -m venv venv
sudo -u app venv/bin/pip install --upgrade pip
sudo -u app venv/bin/pip install -r requirements.txt

# Create .env template if it doesn't exist
if [ ! -f "$DATA_DIR/.env" ]; then
    cat > "$DATA_DIR/.env" << 'EOF'
# Polymarket Whale Scanner Configuration
# IMPORTANT: Replace YOUR_WEBHOOK_URL with your actual Discord webhook

DISCORD_WEBHOOK_URL=YOUR_WEBHOOK_URL
WHALE_THRESHOLD_USD=10000
RESOLUTION_CHECK_INTERVAL_HOURS=1
DATABASE_PATH=/var/lib/polymarket-scanner/polymarket_whales.db
DATA_RETENTION_DAYS=30
EOF
    echo "  Created $DATA_DIR/.env - YOU MUST EDIT THIS!"
fi

# Set permissions
chown -R app:app "$DATA_DIR"
chmod 600 "$DATA_DIR/.env"

# Install systemd services
echo "[6/6] Installing systemd services..."
cp "$INSTALL_DIR/deploy/polymarket-scanner.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/polymarket-cleanup.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/polymarket-cleanup.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable polymarket-scanner
systemctl enable polymarket-cleanup.timer

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit your Discord webhook URL:"
echo "     sudo nano $DATA_DIR/.env"
echo ""
echo "  2. Start the scanner:"
echo "     sudo systemctl start polymarket-scanner"
echo ""
echo "  3. Start the cleanup timer:"
echo "     sudo systemctl start polymarket-cleanup.timer"
echo ""
echo "  4. Check status:"
echo "     sudo systemctl status polymarket-scanner"
echo "     sudo journalctl -u polymarket-scanner -f"
echo ""
