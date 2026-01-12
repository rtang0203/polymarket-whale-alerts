## Deployment (DigitalOcean)

Target: Ubuntu 22.04+ droplet ($6/mo basic tier sufficient)

**Quick deploy:**
```bash
# On droplet as root:
git clone <repo> /opt/polymarket-scanner
cd /opt/polymarket-scanner
sudo bash deploy/setup.sh

# Edit config:
sudo nano /var/lib/polymarket-scanner/.env

# Start:
sudo systemctl start polymarket-scanner
sudo systemctl start polymarket-cleanup.timer
```

**Files created by setup:**
- `/opt/polymarket-scanner/` - application code
- `/var/lib/polymarket-scanner/.env` - configuration
- `/var/lib/polymarket-scanner/polymarket_whales.db` - database

**Useful commands:**
```bash
# View logs
journalctl -u polymarket-scanner -f

# Restart after update
systemctl restart polymarket-scanner

# Check cleanup timer
systemctl list-timers | grep polymarket

# Manual cleanup
sudo -u app /opt/polymarket-scanner/venv/bin/python3 scripts/cleanup.py --dry-run
```