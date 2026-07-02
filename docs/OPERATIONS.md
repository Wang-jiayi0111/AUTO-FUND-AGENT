# Operations Runbook

## Daily Flow

- 14:15: WeWe RSS refreshes subscriptions.
- 14:20: `python -m src.jobs.poll --limit 1 --refresh-rss`
- 14:23: WeWe RSS refreshes subscriptions again.
- 14:25: `python -m src.jobs.poll --limit 1 --refresh-rss`
- 14:30: `python -m src.jobs.digest`

## Manual URL fallback

WeWe RSS is only used to discover article URLs. If WeWe misses an article or the
account login expires, the preferred user-facing path is the optional Feishu
`ManualSubmissions` table:

1. Add one row in `ManualSubmissions`.
2. Fill `blogger` with the blogger id, display name, or WeChat name.
3. Fill `article_url`.
4. Set `status` to `待处理` or leave it empty.
5. Wait for the next scheduled `run_poll.bat`; it runs `apply_manual_submissions`
   before RSS polling.

If the URL cannot be fetched by the script, paste the article body into
`article_text` and set `status` back to `待处理`.

CLI fallback remains available:

```powershell
python -m src.tools.submit_article --blogger lanjing --url "https://mp.weixin.qq.com/s/xxx"
```

Useful options:

```powershell
python -m src.tools.submit_article --blogger lanjing --url "https://mp.weixin.qq.com/s/xxx" --dry-run
python -m src.tools.submit_article --blogger lanjing --url "https://mp.weixin.qq.com/s/xxx" --title "7.2 调仓"
python -m src.tools.submit_article --blogger lanjing --url "https://mp.weixin.qq.com/s/xxx" --force
python -m src.tools.apply_manual_submissions --dry-run
python -m src.tools.apply_manual_submissions
```

This path bypasses RSS scanning, but still uses the same Articles, Operations,
PendingReview, and operation-level dedupe logic.

If both WeWe RSS and direct WeChat page fetching fail, copy the article body to a
UTF-8 text file and submit it manually:

```powershell
python -m src.tools.submit_text --blogger lanjing --url "https://mp.weixin.qq.com/s/xxx" --title "7.2 调仓" --file article.txt
```

Use `--dry-run` first if you want to inspect the parsed operations before writing
to Feishu.

`Articles` is the idempotency table. Re-running `poll` must not duplicate an article that already has a final status.

## Common Commands

```bash
python -m src.tools.validate_feishu
python -m src.tools.health
python -m src.tools.apply_reviews --dry-run
python -m src.tools.apply_reviews
python -m src.tools.backfill --blogger lanjing --limit 20
python -m src.tools.reparse_article --url "https://..."
```

## Review Workflow

1. Open `PendingReview` in Feishu.
2. Correct `action`, `fund_code`, `fund_name`, `sector`, `amount_or_ratio`, and `reason`.
3. Set `status` to `已通过` or `已拒绝`.
4. Run `python -m src.tools.apply_reviews --dry-run`.
5. If the output is correct, run `python -m src.tools.apply_reviews`.

Approved reviews create `Operations` rows and are marked `已处理`.

## Failure Checks

- RSS empty or stale: run `python -m src.tools.health`.
- Parse failures: check `Articles.status=解析失败` and `last_error`.
- Missing digest items: check `Operations.created_at`, `Articles.status`, and `PendingReview`.
- Duplicate concern: check `Articles.guid` and `article_url`; these are the dedupe keys.
