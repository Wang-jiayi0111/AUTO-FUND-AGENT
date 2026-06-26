# API Setup Guide

Complete these steps before running the automation.

## 1. WeChat RSS via WeWe RSS (4 feeds)

Use **WeWe RSS** (self-hosted, Docker). See [RSS_SETUP.md](../RSS_SETUP.md).

Quick steps:
1. Start WeWe RSS: `docker compose -f deploy/docker-compose.wewe-rss.yml up -d`
2. Open http://localhost:4000, log in with WeChat Reading
3. Add 4 public accounts: 蓝鲸跃财、天天的理财日记、价值跃迁-only、鸭哥养基
4. Copy each RSS URL into `.env`:
   - `RSS_LANJING`
   - `RSS_TIANTIAN`
   - `RSS_JIAZHI`
   - `RSS_YAGE`

## 2. Feishu Bitable + Open API

1. Create a Bitable with 6 tables per [feishu_schema.md](feishu_schema.md)
2. Create a custom app at [open.feishu.cn](https://open.feishu.cn)
3. Enable permission: `bitable:app`
4. Publish app and copy `app_id`, `app_secret`
5. Add the app as collaborator on the Bitable
6. From the Bitable URL, copy `app_token` (segment after `/base/`)
7. Copy each table's `table_id` from its URL into `.env`

## 3. WeCom Webhook

1. Create a WeCom group
2. Add group robot → copy Webhook URL to `WECOM_WEBHOOK_URL`

## 4. 阿里云百炼 LLM（DashScope）

1. 打开 [百炼控制台](https://bailian.console.aliyun.com)（或 [DashScope 控制台](https://dashscope.console.aliyun.com)）
2. 进入 **API-KEY 管理** → 创建 Key
3. 填入项目（二选一）：
   - **方式 A**：`.env` 里 `LLM_API_KEY=sk-xxx`
   - **方式 B**：Windows **系统环境变量**（见下），`.env` 中 `LLM_API_KEY` 留空
4. 确认已开通模型：
   - 文本解析：`qwen-plus`（默认，可改为 `qwen-max`）
   - 图片 OCR：`qwen-vl-plus`（默认，可改为 `qwen-vl-max`）
4. 默认使用 **OpenAI 兼容接口**，无需改代码：

```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_VISION_MODEL=qwen-vl-plus
```

### 使用 Windows 系统环境变量（方式 B）

1. `Win + R` → 输入 `sysdm.cpl` → 回车
2. **高级** → **环境变量**
3. 在「用户变量」或「系统变量」中 **新建**：
   - 变量名：`DASHSCOPE_API_KEY`（百炼官方常用名）或 `LLM_API_KEY`
   - 变量值：你的 API Key（如 `sk-xxxxxxxx`）
4. 确定保存后，**重新打开** PowerShell / Cursor 终端（旧终端读不到新变量）
5. `.env` 里 `LLM_API_KEY=` 保持留空即可

验证：

```powershell
# 应能打印出 key（不要发给他人）
echo $env:DASHSCOPE_API_KEY
# 或
echo $env:LLM_API_KEY

python -m src.tools.check_setup
```

> 项目优先读 `LLM_API_KEY`，没有则读 `DASHSCOPE_API_KEY`。系统变量不会被 `.env` 里的空值覆盖。

## 5. Quick verify

```powershell
Copy-Item .env.example .env   # if .env does not exist yet
# fill in values in .env
python -m src.tools.check_setup
python -m src.tools.check_setup --live   # optional: test WeCom + LLM
```

See [STEP1_CHECKLIST.md](STEP1_CHECKLIST.md) for a printable checklist.
