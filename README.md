# AUTO-FUND-AGENT

AUTO-FUND-AGENT 是一个个人基金公众号跟踪工具，用来自动读取公众号文章，识别博主的基金操作，并把结果写入飞书多维表，最后通过企业微信推送每日汇总。

当前项目定位是“个人稳定版”：

- 使用 WeWe RSS 获取公众号文章 URL。
- 使用 LLM/OCR 解析文章中的买入、卖出、加仓、减仓、定投、观望等信息。
- 使用飞书多维表保存文章、操作、待确认记录和基金映射。
- 使用企业微信群机器人推送每日摘要。
- 当 WeWe RSS 失效时，可以通过飞书 `ManualSubmissions` 表手动提交文章 URL。

## 工作流程

```text
WeWe RSS / ManualSubmissions
        ↓
poll 读取文章并解析
        ↓
Articles 去重和状态跟踪
        ↓
Operations / PendingReview / FundMapping
        ↓
digest 企业微信每日推送
```

默认测试时间节点：

```text
14:15  WeWe RSS 第一次刷新
14:20  poll：先处理 ManualSubmissions，再刷新 RSS 并解析
14:23  WeWe RSS 第二次刷新
14:25  poll：补抓延迟文章
14:30  digest：企业微信推送汇总
```

## 一、准备环境

进入项目目录：

```powershell
cd E:\Project\AUTO-FUND-AGENT
```

创建并启用虚拟环境：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

复制环境变量文件：

```powershell
copy .env.example .env
```

然后编辑 `.env`，填写 RSS、飞书、企业微信和 LLM 配置。

## 二、配置 WeWe RSS

WeWe RSS 用来自动获取公众号文章 URL。

启动 WeWe RSS：

```powershell
deploy\start-wewe-rss.bat
```

或使用 Docker Compose：

```powershell
docker compose -f deploy\docker-compose.wewe-rss.yml up -d
```

在 WeWe RSS 后台添加公众号后，把每个公众号的 RSS 地址填入 `.env`：

```env
RSS_账号一=http://localhost:4000/feeds/xxx.rss
RSS_账号二=http://localhost:4000/feeds/xxx.rss
```

需要跟踪的公众号在 [config/bloggers.yaml](config/bloggers.yaml) 中配置。每个账号需要配置：

- `id`：内部使用的账号标识。
- `name`：显示名称。
- `wechat_name`：公众号名称。
- `rss_url_env`：对应 `.env` 中的 RSS 环境变量名。

详细说明见 [docs/RSS_SETUP.md](docs/RSS_SETUP.md)。

## 三、配置飞书多维表

按照 [docs/feishu_schema.md](docs/feishu_schema.md) 创建飞书多维表。

必需表：

- `Bloggers`
- `FocusList`
- `Articles`
- `Operations`
- `FundMapping`
- `PendingReview`

推荐额外创建：

- `ManualSubmissions`

`ManualSubmissions` 是给用户使用的手动入口。当 WeWe RSS 没抓到文章时，只需要在这张表新增一行，填写博主和文章 URL，自动任务会把文章同步进正式表。

在 `.env` 中填写表 ID：

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_APP_TOKEN=
FEISHU_TABLE_BLOGGERS=
FEISHU_TABLE_FOCUS_LIST=
FEISHU_TABLE_OPERATIONS=
FEISHU_TABLE_ARTICLES=
FEISHU_TABLE_MANUAL_SUBMISSIONS=
FEISHU_TABLE_FUND_MAPPING=
FEISHU_TABLE_PENDING_REVIEW=
```

验证飞书配置：

```powershell
python -m src.tools.validate_feishu
```

验证字段写入：

```powershell
python -m src.tools.validate_feishu --write-test
```

## 四、配置 LLM 和企业微信

在 `.env` 中填写 LLM 配置：

```env
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_VISION_MODEL=qwen-vl-plus
```

填写企业微信群机器人 webhook：

```env
WECOM_WEBHOOK_URL=
```

详细说明见 [docs/API_SETUP.md](docs/API_SETUP.md)。

## 五、手动测试

先验证 RSS 和飞书状态：

```powershell
python -m src.tools.health
```

试运行 poll，不写入飞书：

```powershell
python -m src.jobs.poll --dry-run --limit 1 --refresh-rss
```

正式运行 poll：

```powershell
python -m src.jobs.poll --limit 1 --refresh-rss
```

预览每日推送内容：

```powershell
python -m src.jobs.digest --dry-run --force
```

正式推送：

```powershell
python -m src.jobs.digest --force
```

## 六、配置 Windows 自动执行

自动脚本：

```text
deploy\run_poll.bat
deploy\run_digest.bat
```

建议在 Windows 任务计划程序中配置四个任务：

| 时间 | 脚本 | 作用 |
|---|---|---|
| 14:20 | `deploy\run_poll.bat` | 处理手动提交，刷新 RSS，解析文章 |
| 14:25 | `deploy\run_poll.bat` | 补抓延迟同步文章 |
| 14:30 | `deploy\run_digest.bat` | 企业微信推送汇总 |

任务计划程序中：

- “程序或脚本”填写 bat 的完整路径。
- “起始于”填写项目根目录，例如 `E:\Project\AUTO-FUND-AGENT`。
- 勾选“使用最高权限运行”。
- 建议允许按需运行任务。

详细步骤见 [docs/WINDOWS_SCHEDULER.md](docs/WINDOWS_SCHEDULER.md)。

日志查看：

```powershell
Get-Content logs\poll.log -Tail 100 -Encoding utf8
Get-Content logs\digest.log -Tail 100 -Encoding utf8
```

## 七、WeWe 失效时如何处理

WeWe RSS 的作用只是自动发现公众号文章 URL。它失效时，可以使用 `ManualSubmissions` 表替代。

在飞书 `ManualSubmissions` 表新增一行：

| 字段 | 填写 |
|---|---|
| `blogger` | `blogger_id`、显示名称或公众号名称 |
| `article_url` | 公众号文章 URL |
| `title` | 可选，建议填写 |
| `status` | `待处理`，也可以留空 |

下一次 `run_poll.bat` 会自动处理该行。

如果脚本无法直接抓取微信文章正文，可以把正文复制到 `article_text` 字段，然后把 `status` 改回 `待处理`。

也可以用命令手动处理：

```powershell
python -m src.tools.submit_article --blogger <blogger_id> --url "https://mp.weixin.qq.com/s/xxx"
```

如果连 URL 抓取也失败，可以复制正文到文本文件：

```powershell
python -m src.tools.submit_text --blogger <blogger_id> --url "https://mp.weixin.qq.com/s/xxx" --title "文章标题" --file article.txt
```

## 八、人工确认流程

低置信度或需要人工判断的操作会进入 `PendingReview`。

处理步骤：

1. 在飞书 `PendingReview` 中修正 `action`、`fund_code`、`fund_name`、`amount_or_ratio` 等字段。
2. 将 `status` 改为 `已通过` 或 `已拒绝`。
3. 预览处理结果：

```powershell
python -m src.tools.apply_reviews --dry-run
```

4. 正式应用：

```powershell
python -m src.tools.apply_reviews
```

通过的记录会写入 `Operations`，并回写 `operation_id` 和 `processed_at`。

## 九、常用命令

```powershell
# 检查飞书配置
python -m src.tools.validate_feishu --write-test

# 检查 RSS 和飞书运行状态
python -m src.tools.health

# 处理飞书 ManualSubmissions 待处理记录
python -m src.tools.apply_manual_submissions

# 预览手动提交记录处理
python -m src.tools.apply_manual_submissions --dry-run

# 指定博主补历史文章
python -m src.tools.backfill --blogger <blogger_id> --limit 20

# 指定 URL 重跑
python -m src.tools.reparse_article --blogger <blogger_id> --url "https://mp.weixin.qq.com/s/xxx"

# 编译检查
python -m compileall src tests

# 单元测试
python -m unittest discover -s tests -v
```

## 十、数据去重和状态说明

`Articles` 是文章级状态源：

- 同一篇文章不会重复解析入库。
- 状态为 `已解析`、`无操作`、`待确认`、`已忽略` 的文章默认跳过。
- 状态为 `解析失败` 的文章默认不自动重试，需要手动重跑。

`Operations` 也有操作级去重：

- 同一文章、同一基金、同一动作、同一金额不会重复写入。
- 即使 `--force` 重跑，也会尽量复用已有操作记录。

digest 中会区分：

- `RSS 异常博主`
- `今日未检查 RSS`
- `RSS 未发现当天文章（需人工确认是否发文）`

这避免把“没有抓到文章”误判成“博主没有发文”。

## 十一、项目结构

| 目录 | 作用 |
|---|---|
| `src/ingest/` | RSS、URL、正文抓取 |
| `src/parse/` | LLM/OCR 解析和基金代码匹配 |
| `src/store/` | 飞书多维表读写 |
| `src/jobs/` | 自动任务：poll 和 digest |
| `src/tools/` | 运维工具和手动兜底工具 |
| `src/notify/` | 企业微信推送 |
| `deploy/` | Windows、systemd、crontab 部署脚本 |
| `docs/` | 配置和运维文档 |
| `tests/` | 单元测试 |

## 十二、测试

```powershell
python -m compileall src tests
python -m unittest discover -s tests -v
```

当前项目适合作为个人稳定运行版使用。最大外部风险仍然是公众号来源不稳定，因此项目保留了 RSS 自动抓取、飞书手动 URL、手动正文三层兜底。
