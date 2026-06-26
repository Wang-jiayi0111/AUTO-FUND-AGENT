# Feishu Bitable Schema

Create one Bitable app with 6 data tables.

## Bloggers

| Field | Type | Notes |
|-------|------|-------|
| blogger_id | Text (primary) | e.g. lanjing |
| name | Text | Display name |
| wechat_name | Text | WeChat account name |
| rss_url | URL | WeWe RSS 订阅链接（`/feeds/MP_WXS_xxx.rss`） |
| status | Single select | 启用 / 停用 |

## FollowList

| Field | Type | Notes |
|-------|------|-------|
| blogger_id | Link → Bloggers | |
| note | Text | Optional |
| active | Checkbox | Default true |

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
| action | Single select | 买入/卖出/加仓/减仓/定投 |
| fund_code | Text | Can be empty |
| fund_name | Text | Required |
| sector | Text | |
| amount_or_ratio | Text | |
| reason | Long text | |
| confidence | Number | 0-1 |
| article_url | URL | |
| published_at | DateTime | |
| status | Single select | 已确认/自动入库/已忽略/风险提示 |

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
| fund_name | Text | |
| code_candidates | Long text | JSON array |
| article_url | URL | |
| confidence | Number | |
| status | Single select | 待确认/已通过/已拒绝 |
