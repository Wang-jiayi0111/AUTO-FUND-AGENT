# Operations Runbook

## Daily Flow

- 14:25: WeWe RSS refreshes subscriptions.
- 14:30: `python -m src.jobs.poll --limit 5`
- 14:33: WeWe RSS refreshes subscriptions again.
- 14:35: `python -m src.jobs.poll --limit 5`
- 14:40: `python -m src.jobs.digest`

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
