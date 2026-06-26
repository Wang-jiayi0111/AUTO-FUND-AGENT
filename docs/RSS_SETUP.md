# 数据源方案（2026-06 更新）

**主方案：WeWe RSS 自建**（Feeddd 已停维护，不再使用）

```
微信公众号 → WeWe RSS（微信读书） → 标准 RSS → AUTO-FUND-AGENT 轮询解析
```

优势：
- 任意能通过微信读书订阅的公众号都可添加
- 自建、免费、RSS 链接可控
- 支持全文模式（`FEED_MODE=fulltext`），利于 LLM 解析

## 快速启动

```powershell
cd F:\AUTO-FUND-AGENT\deploy
docker compose -f docker-compose.wewe-rss.yml up -d
# 或双击 start-wewe-rss.bat
```

管理后台：**http://localhost:4000/dash**

详细步骤见 [RSS_SETUP.md](RSS_SETUP.md)。

## 方案对比

| 方案 | 成本 | 稳定性 | 推荐 |
|------|------|--------|------|
| **WeWe RSS 自建** | 免费（需 Docker） | 较高，自己掌控 | **首选** |
| 他人托管的 WeWe RSS | 视服务商 | 中等 | 临时可用 |
| 其他 RSS 服务 | 各异 | 各异 | 只要输出标准 RSS 即可 |

---

## 推荐：WeWe RSS 自建

GitHub：[cooderl/wewe-rss](https://github.com/cooderl/wewe-rss)

### 1. 启动服务（Docker）

项目已提供 compose 文件：

```powershell
cd F:\AUTO-FUND-AGENT\deploy
docker compose -f docker-compose.wewe-rss.yml up -d
```

浏览器打开：**http://localhost:4000**

> 部署到云服务器时，把 `4000` 端口映射到公网，并修改 compose 里的 `SERVER_ORIGIN_URL` 为你的域名或 IP。

### 2. 登录微信读书账号

1. 进入 **账号管理** → **添加账号**
2. 用微信扫码登录 **微信读书**
3. **不要勾选**「24 小时后自动退出」

### 3. 订阅 4 个公众号

1. 进入 **公众号源** → **添加**
2. 提交公众号文章分享链接（在微信里打开公众号任意文章 → 分享 → 复制链接）
3. 依次添加：
   - 蓝鲸跃财
   - 天天的理财日记
   - 价值跃迁-only
   - 鸭哥养基

**注意**：添加频率不要太高，否则可能被微信读书限流，一般等 24 小时恢复。

### 4. 复制 RSS 链接

每个公众号订阅成功后，WeWe RSS 会生成一条 RSS 地址，格式类似：

```
http://localhost:4000/feeds/MP_WXS_xxxxxxxx.rss
```

在 WeWe RSS 后台找到对应公众号，复制 **RSS 链接**。

### 5. 填入 `.env`

```env
RSS_LANJING=http://localhost:4000/feeds/MP_WXS_xxx1.rss
RSS_TIANTIAN=http://localhost:4000/feeds/MP_WXS_xxx2.rss
RSS_JIAZHI=http://localhost:4000/feeds/MP_WXS_xxx3.rss
RSS_YAGE=http://localhost:4000/feeds/MP_WXS_xxx4.rss
```

对应关系：

| 公众号 | 环境变量 |
|--------|----------|
| 蓝鲸跃财 | `RSS_LANJING` |
| 天天的理财日记 | `RSS_TIANTIAN` |
| 价值跃迁-only | `RSS_JIAZHI` |
| 鸭哥养基 | `RSS_YAGE` |

### 6. 验证

```powershell
python -m src.tools.check_setup
```

应看到 4 条 RSS 均为 `[OK]`。

---

## 全文模式（推荐开启）

WeWe RSS 支持 `FEED_MODE=fulltext`，RSS 条目会包含文章正文 HTML，有利于 LLM 解析。

在 `deploy/docker-compose.wewe-rss.yml` 中取消注释：

```yaml
- FEED_MODE=fulltext
```

---

## 云服务器部署建议

若 AUTO-FUND-AGENT 和 WeWe RSS 部署在同一台 VPS：

- WeWe RSS：`http://127.0.0.1:4000/feeds/...`（仅本机访问，更安全）
- AUTO-FUND-AGENT 的 `.env` 里 RSS 地址用 `http://127.0.0.1:4000/...`

若分开部署，RSS 地址填 WeWe RSS 的公网 URL，并设置 `AUTH_CODE` 防止被滥用。

---

## 旧变量名兼容

若你之前使用 Feeddd 变量名，仍可使用（会自动回退读取）：

- `FEEDDD_RSS_LANJING` → 等价于 `RSS_LANJING`
- 其余同理

建议统一改为 `RSS_*` 命名。
