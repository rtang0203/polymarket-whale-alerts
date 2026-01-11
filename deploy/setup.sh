#!/bin/bash
# Polymarket Whale Scanner - Droplet Setup Script
# Run as root on a fresh Ubuntu 22.04+ droplet
#
# Usage:
#   1. Copy this repo to the droplet
#   2. Run: sudo bash deploy/setup.sh
#   3. Edit /var/lib/polymarket-scanner/.env with your Discord webhook
#   4. Run: sudo systemctl start polymarket-scanner

set -e

echo "=== Polymarket Whale Scanner Setup ==="

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
    adduser --system --group --home /var/lib/polymarket-scanner app
fi

# Create directories
echo "[3/6] Setting up directories..."
mkdir -p /opt/polymarket-scanner
mkdir -p /var/lib/polymarket-scanner

# Copy application code
echo "[4/6] Deploying application..."
cp -r src requirements.txt scripts /opt/polymarket-scanner/

# Setup Python environment
echo "[5/6] Setting up Python environment..."
cd /opt/polymarket-scanner
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env template if it doesn't exist
if [ ! -f /var/lib/polymarket-scanner/.env ]; then
    cat > /var/lib/polymarket-scanner/.env << 'EOF'
# Polymarket Whale Scanner Configuration
# IMPORTANT: Replace YOUR_WEBHOOK_URL with your actual Discord webhook

DISCORD_WEBHOOK_URL=YOUR_WEBHOOK_URL
WHALE_THRESHOLD_USD=10000
RESOLUTION_CHECK_INTERVAL_HOURS=1
DATABASE_PATH=/var/lib/polymarket-scanner/polymarket_whales.db
DATA_RETENTION_DAYS=30
EOF
    echo "Created /var/lib/polymarket-scanner/.env - YOU MUST EDIT THIS!"
fi

# Set permissions
chown -R app:app /opt/polymarket-scanner
chown -R app:app /var/lib/polymarket-scanner
chmod 600 /var/lib/polymarket-scanner/.env

# Install systemd services
echo "[6/6] Installing systemd services..."
cp deploy/polymarket-scanner.service /etc/systemd/system/
cp deploy/polymarket-cleanup.service /etc/systemd/system/
cp deploy/polymarket-cleanup.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable polymarket-scanner
systemctl enable polymarket-cleanup.timer

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit your Discord webhook URL:"
echo "     sudo nano /var/lib/polymarket-scanner/.env"
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
