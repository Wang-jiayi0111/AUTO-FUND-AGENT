# 第一步：密钥与 API 配置清单

按顺序完成，每完成一项在 `.env` 中填入对应变量，最后运行验证命令。

## 你要做的事

- [ ] **1. 微信公众号 RSS**（4 条，WeWe RSS 自建）
  - 详见 [RSS_SETUP.md](RSS_SETUP.md)
  - 启动 WeWe RSS → 订阅 4 个公众号 → 复制 RSS 链接
  - 填入 `.env`：`RSS_LANJING` / `RSS_TIANTIAN` / `RSS_JIAZHI` / `RSS_YAGE`

- [ ] **2. 飞书多维表格**
  - 按 [feishu_schema.md](feishu_schema.md) 建 6 张表
  - [飞书开放平台](https://open.feishu.cn) 创建应用，开通 `bitable:app`
  - 填入：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_APP_TOKEN`
  - 填入 6 个 `FEISHU_TABLE_*`
  - 填入 `FEISHU_BASE_URL`（浏览器打开表格的完整 URL，用于生成确认链接）

- [ ] **3. 企业微信机器人**
  - 建群 → 添加机器人 → `WECOM_WEBHOOK_URL`

- [ ] **4. 阿里云百炼 LLM**
  - [百炼控制台](https://bailian.console.aliyun.com) 创建 API Key
  - 填入：`LLM_API_KEY`（默认模型 `qwen-plus` + `qwen-vl-plus`）

## 本地操作

```powershell
cd F:\AUTO-FUND-AGENT
.venv\Scripts\Activate.ps1

# 若还没有 .env
Copy-Item .env.example .env

# 编辑 .env 填入上面的密钥后运行：
python -m src.tools.check_setup

# 全部通过后，可选发送真实测试消息：
python -m src.tools.check_setup --live
```

## 完成标准

`python -m src.tools.check_setup` 输出 **「第一步已完成，所有检查通过。」** 且无 FAIL 项。

详细说明见 [API_SETUP.md](API_SETUP.md)。
