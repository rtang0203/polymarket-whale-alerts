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
systemctl restart polymarket-cleanup

# Check cleanup timer
systemctl list-timers | grep polymarket

# Manual cleanup
sudo -u app /opt/polymarket-scanner/venv/bin/python3 scripts/cleanup.py --dry-run
```

**Moving db to /var/lib**
# Stop the service                                                            
systemctl stop polymarket-scanner                                             
                                                                                
# Move the database                                                           
mv /opt/polymarket-scanner/polymarket_whales.db /var/lib/polymarket-scanner/  
                                                                                
# Fix ownership                                                               
chown app:app /var/lib/polymarket-scanner/polymarket_whales.db                
                                                                                
# Update .env to use absolute path                                            
nano /var/lib/polymarket-scanner/.env                                         
# Change: DATABASE_PATH=polymarket_whales.db                                  
# To:     DATABASE_PATH=/var/lib/polymarket-scanner/polymarket_whales.db      
                                                                                
# Start the service
systemctl start polymarket-scanner

---

## Correlation Checker Deployment

The correlation checker detects whale trades that precede related news articles. It runs as a cron job after the news scraper.

### Prerequisites

- News scraper deployed at `/opt/news-scraper/` with database at `/var/lib/news-scraper/articles.db`
- Polymarket scanner already running with database at `/var/lib/polymarket-scanner/polymarket_whales.db`
- Separate Discord webhook for correlation alerts (recommended: dedicated channel)

### Step 1: Update Code on Droplet

```bash
# SSH to droplet
ssh root@your-droplet-ip

# Pull latest code (includes correlation module)
cd /opt/polymarket-scanner
git pull origin main

# Or manually copy if not using git:
# scp -r src/correlation/ root@droplet:/opt/polymarket-scanner/src/
# scp check_correlations.py root@droplet:/opt/polymarket-scanner/
```

### Step 2: Update Configuration

Add correlation settings to `/var/lib/polymarket-scanner/.env`:

```bash
sudo nano /var/lib/polymarket-scanner/.env
```

Add these lines:
```bash
# Correlation checker
CORRELATION_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN
NEWS_DB_PATH=/var/lib/news-scraper/articles.db
SCANNER_DB_PATH=/var/lib/polymarket-scanner/polymarket_whales.db
```

### Step 3: Test Manually

```bash
# Switch to app user
sudo -u app bash

# Activate venv
cd /opt/polymarket-scanner
source venv/bin/activate

# Test webhook connectivity
python3 check_correlations.py --test

# Run a manual check (dry run - see what would match)
python3 check_correlations.py --lookback 60 -v

# Exit app user shell
exit
```

### Step 4: Set Up Cron Job

Chain the correlation checker after the news scraper using `&&`. This ensures:
- Correlation only runs after scraper succeeds
- No race condition (scraper always finishes first)
- Single cron entry to manage

```bash
# Edit crontab for app user
sudo crontab -u app -e
```

Replace the existing news scraper cron with this chained version:
```bash
# News scraper -> Correlation checker (chained)
*/10 * * * * /opt/news-scraper/venv/bin/python3 /opt/news-scraper/news_scraper/scraper.py >> /var/lib/news-scraper/scraper.log 2>&1 && /opt/polymarket-scanner/venv/bin/python3 /opt/polymarket-scanner/check_correlations.py >> /var/log/correlation.log 2>&1
```

This runs:
1. News scraper every 10 minutes
2. If scraper succeeds → correlation checker runs immediately after
3. If scraper fails → correlation checker is skipped (no new articles anyway)

### Step 5: Set Up Log Rotation

```bash
sudo nano /etc/logrotate.d/correlation
```

Add:
```
/var/log/correlation.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 app app
}
```

Create the log file with correct permissions:
```bash
sudo touch /var/log/correlation.log
sudo chown app:app /var/log/correlation.log
```

### Useful Commands

```bash
# View recent correlation logs
tail -f /var/log/correlation.log

# Check cron is running
grep correlation /var/log/syslog | tail -20

# Query correlation matches in database
sudo -u app sqlite3 /var/lib/polymarket-scanner/polymarket_whales.db \
  "SELECT confidence, COUNT(*) FROM correlation_matches GROUP BY confidence"

# View recent high-confidence matches
sudo -u app sqlite3 /var/lib/polymarket-scanner/polymarket_whales.db \
  "SELECT market_title, article_title, matched_keywords,
          time_delta_seconds/3600.0 as hours_before
   FROM correlation_matches
   WHERE confidence='high'
   ORDER BY created_at DESC LIMIT 10"

# Wallets with multiple correlations (potential insiders)
sudo -u app sqlite3 /var/lib/polymarket-scanner/polymarket_whales.db \
  "SELECT wallet_address, COUNT(*) as correlations
   FROM correlation_matches
   GROUP BY wallet_address
   HAVING correlations >= 2
   ORDER BY correlations DESC"
```

### Troubleshooting

**No matches found:**
- Check both databases exist and have recent data
- Verify NEWS_DB_PATH and SCANNER_DB_PATH are correct in .env
- Run with `-v` flag to see article/trade counts

**Webhook not sending:**
- Test with `python3 check_correlations.py --test`
- Verify CORRELATION_WEBHOOK_URL is correct
- Check Discord channel permissions

**Cron not running:**
- Check cron syntax: `crontab -u app -l`
- Check syslog: `grep CRON /var/log/syslog | tail -20`
- Ensure venv path is correct