# Feishu Bitable Schema

Create one Bitable app with 6 required data tables. `ManualSubmissions` is optional
but recommended as the user-facing fallback when WeWe RSS misses an article.

## Bloggers

| Field | Type | Notes |
|-------|------|-------|
| blogger_id | Text (primary) | e.g. lanjing |
| name | Text | Display name |
| wechat_name | Text | WeChat account name |
| rss_url | URL | WeWe RSS 订阅链接（`/feeds/MP_WXS_xxx.rss`） |
| status | Single select | 启用 / 停用；停用后跳过 poll 和 digest |
| last_checked_at | DateTime | RSS health check time |
| last_success_at | DateTime | Last successful RSS check |
| last_article_title | Text | Latest RSS article title |
| last_article_url | URL | Latest RSS article URL |
| last_published_at | DateTime | Latest RSS article publish time |
| last_error | Long text | Latest RSS error |
| consecutive_failures | Number | RSS failure count |

## FocusList

| Field | Type | Notes |
|-------|------|-------|
| focus_id | Text (primary) | UUID |
| blogger_id | Link → Bloggers | Required |
| fund_code | Text | Optional |
| fund_name | Text | Recommended |
| note | Text | Optional |
| active | Checkbox | Default true |
| created_at | DateTime | |

## Operations

| Field | Type | Notes |
|-------|------|-------|
| op_id | Text (primary) | UUID |
| blogger_id | Link → Bloggers | |
| action | Single select | 买入/卖出/加仓/减仓/定投/观望 |
| article_id | Link → Articles | |
| article_guid | Text | RSS guid/id |
| fund_code | Text | Can be empty |
| fund_name | Text | Required |
| sector | Text | |
| amount_or_ratio | Text | |
| reason | Long text | |
| confidence | Number | 0-1 |
| article_url | URL | |
| published_at | DateTime | |
| created_at | DateTime | |
| source | Single select | text/image/merged/manual |
| status | Single select | 已确认/自动入库/已忽略/风险提示 |

## Articles

| Field | Type | Notes |
|-------|------|-------|
| article_id | Text (primary) | UUID |
| blogger_id | Link → Bloggers | |
| guid | Text | RSS guid/id |
| title | Text | |
| article_url | URL | |
| published_at | DateTime | RSS publish time |
| discovered_at | DateTime | First seen by poll job |
| parsed_at | DateTime | Last parse completion time |
| status | Single select | 待解析/解析中/已解析/无操作/待确认/解析失败/已忽略 |
| operation_count | Number | Saved Operations count |
| pending_review_count | Number | PendingReview count |
| last_error | Long text | Last parse error |
| raw_excerpt | Long text | First 2000 chars of article text |
| raw_json | Long text | Parse raw JSON summary |

## FundMapping

| Field | Type | Notes |
|-------|------|-------|
| mapping_id | Text (primary) | |
| blogger_id | Link → Bloggers | |
| fund_code | Text | Can be empty |
| fund_name | Text | Normalized name |
| fund_name_raw | Text | Original from article |
| sector | Text | |
| latest_action | Single select | Same as Operations.action |
| latest_op_id | Link → Operations | |
| updated_at | DateTime | |

## PendingReview

| Field | Type | Notes |
|-------|------|-------|
| review_id | Text (primary) | |
| raw_json | Long text | |
| blogger_id | Link → Bloggers | |
| article_id | Link → Articles | |
| action | Single select | 买入/卖出/加仓/减仓/定投/观望 |
| fund_code | Text | |
| fund_name | Text | |
| sector | Text | |
| amount_or_ratio | Text | |
| reason | Long text | |
| source | Single select | text/image/merged/manual |
| code_candidates | Long text | JSON array |
| article_url | URL | |
| published_at | DateTime | |
| confidence | Number | |
| processed_at | DateTime | |
| operation_id | Link → Operations | |
| status | Single select | 待确认/已通过/已拒绝/已处理 |

## ManualSubmissions Optional

This table is the user-facing fallback input. When WeWe RSS fails or misses an
article, add one row here. The next scheduled `run_poll.bat` will process it
before RSS polling.

| Field | Type | Notes |
|-------|------|-------|
| submission_id | Text (primary) | Optional UUID/manual id |
| blogger | Text | Required. Accepts `blogger_id`, display name, or WeChat name |
| article_url | URL | Required. WeChat article URL |
| title | Text | Optional if URL can be fetched; recommended |
| published_at | DateTime | Optional |
| article_text | Long text | Optional fallback when direct URL fetching is blocked |
| status | Single select | 待处理/处理中/已处理/处理失败 |
| last_error | Long text | Processing error |
| article_id | Link → Articles | Filled after processing |
| processed_at | DateTime | Filled after processing |
| created_at | DateTime | Optional |
