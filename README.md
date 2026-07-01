# AUTO-FUND-AGENT

Automated fund blogger operation tracker:

WeChat RSS (WeWe RSS) → LLM + OCR parse → Feishu Bitable → WeCom digest on A-share trading days.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env     # fill in secrets
```

See [docs/API_SETUP.md](docs/API_SETUP.md), [docs/RSS_SETUP.md](docs/RSS_SETUP.md), [docs/STEP1_CHECKLIST.md](docs/STEP1_CHECKLIST.md), and [docs/WINDOWS_SCHEDULER.md](docs/WINDOWS_SCHEDULER.md) for local scheduling.

## Run jobs

```bash
# Poll RSS and parse new articles
python -m src.jobs.poll
python -m src.jobs.poll --dry-run

# Weekday flow: poll at 14:30 and 14:35, digest push at 14:40
deploy\run_poll.bat
deploy\run_digest.bat

# Send trading-day digest only
python -m src.jobs.digest
python -m src.jobs.digest --dry-run
python -m src.jobs.digest --force   # ignore trading calendar
```

## Architecture

| Layer | Module | Role |
|-------|--------|------|
| Ingest | `src/ingest/rss_poller.py` | RSS polling (WeWe RSS), image extraction |
| Parse | `src/parse/` | LLM extract, fund code search (Eastmoney API) |
| Store | `src/store/feishu.py` | Feishu Bitable read/write |
| Notify | `src/notify/wecom.py` | WeCom webhook push |
| Jobs | `src/jobs/` | `poll.py`（工作日 14:30/14:35 获取）+ `digest.py`（工作日 14:40 推送） |

## Deployment (VPS)

```bash
sudo useradd -r -m auto-fund
sudo mkdir -p /opt/AUTO-FUND-AGENT
sudo cp -r . /opt/AUTO-FUND-AGENT
cd /opt/AUTO-FUND-AGENT && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp deploy/auto-fund-poll.service deploy/auto-fund-poll.timer /etc/systemd/system/
sudo cp deploy/auto-fund-digest.service deploy/auto-fund-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auto-fund-poll.timer auto-fund-digest.timer
```

Or use [deploy/crontab.example](deploy/crontab.example) (weekday 14:30/14:35 poll + 14:40 digest).

## Bloggers (MVP)

- 蓝鲸跃财 (`lanjing`)
- 天天的理财日记 (`tiantian`)
- 价值跃迁-only (`jiazhi`)
- 鸭哥养基 (`yage`)

Configure RSS URLs in `.env` per `config/bloggers.yaml`. See [docs/RSS_SETUP.md](docs/RSS_SETUP.md).

## Tests

```bash
python -m unittest discover -s tests -v
```
