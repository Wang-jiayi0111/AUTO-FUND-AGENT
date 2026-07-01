# VPS Deployment

## Prerequisites

- Ubuntu 22.04+ lightweight VPS (1C2G)
- Python 3.11+
- `.env` configured per [API_SETUP.md](API_SETUP.md)

## systemd (recommended)

```bash
sudo useradd -r -s /bin/bash -m -d /opt/auto-fund auto-fund || true
sudo mkdir -p /opt/AUTO-FUND-AGENT
sudo rsync -av --exclude .venv --exclude .git ./ /opt/AUTO-FUND-AGENT/
cd /opt/AUTO-FUND-AGENT
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/auto-fund-poll.service deploy/auto-fund-poll.timer /etc/systemd/system/
sudo cp deploy/auto-fund-digest.service deploy/auto-fund-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auto-fund-poll.timer auto-fund-digest.timer
```

Runs **weekdays 14:30 and 14:35**: poll latest RSS articles.  
Runs **weekdays 14:40**: send digest push (trading-day check inside digest).

Verify:

```bash
systemctl list-timers | grep auto-fund
sudo -u auto-fund bash -c 'cd /opt/AUTO-FUND-AGENT && .venv/bin/python -m src.jobs.poll --dry-run --limit 5'
sudo -u auto-fund bash -c 'cd /opt/AUTO-FUND-AGENT && .venv/bin/python -m src.jobs.digest --dry-run --force'
```

## cron (alternative)

```bash
crontab -e
# paste contents of deploy/crontab.example (weekday 14:30/14:35 poll + 14:40 digest)
```

## Logs

```bash
journalctl -u auto-fund-poll.service -f
journalctl -u auto-fund-digest.service -f
```

`auto-fund-daily.timer` remains in `deploy/` for the older single-task workflow, but the recommended setup is the separated 14:30/14:35 poll + 14:40 digest timers.

## Secrets

- Store `.env` only on server, chmod 600
- Never commit `.env` to git
