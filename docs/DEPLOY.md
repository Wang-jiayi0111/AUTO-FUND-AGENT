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
sudo cp deploy/auto-fund-daily.service deploy/auto-fund-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auto-fund-daily.timer
```

Runs **weekdays 14:20**: poll all bloggers, then digest push (trading-day check inside digest).

Verify:

```bash
systemctl list-timers | grep auto-fund
sudo -u auto-fund bash -c 'cd /opt/AUTO-FUND-AGENT && .venv/bin/python -m src.jobs.poll --dry-run --limit 1'
sudo -u auto-fund bash -c 'cd /opt/AUTO-FUND-AGENT && .venv/bin/python -m src.jobs.digest --dry-run --force'
```

## cron (alternative)

```bash
crontab -e
# paste contents of deploy/crontab.example (single weekday 14:20 line)
```

## Logs

```bash
journalctl -u auto-fund-daily.service -f
```

Legacy high-frequency timers (`auto-fund-poll.timer` + `auto-fund-digest.timer`) remain in `deploy/` but are not recommended.

## Secrets

- Store `.env` only on server, chmod 600
- Never commit `.env` to git
