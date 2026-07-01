# Windows 定时任务

博主一般在 **14:00 左右**发文，因此**不需要**高频轮询。  
推荐：**每个工作日跑三次任务**——14:30 和 14:35 拉 RSS 解析入库，14:40 发企业微信汇总。

## 前置

1. WeWe RSS 容器常驻：`deploy\start-wewe-rss.bat` 或 Docker Desktop 开机自启
2. `.env` 已配置 RSS / 飞书 / 企业微信 / LLM
3. 飞书 `FollowList` 中 4 个博主 `active=true`

## 手动测试

```powershell
cd F:\AUTO-FUND-AGENT
.venv\Scripts\Activate.ps1

python -m src.tools.validate_feishu
python -m src.jobs.poll
python -m src.jobs.digest --dry-run --force
```

或一次跑完（与定时任务相同）：

```powershell
deploy\run_daily.bat
Get-Content logs\daily.log -Tail 30
```

## 推荐：两个定时任务

| 脚本 | 作用 |
|------|------|
| **`deploy\run_poll.bat`** | 14:30 和 14:35 拉取 RSS，最多处理每个博主 5 篇最新未读文章 |
| **`deploy\run_digest.bat`** | 14:40 读取飞书并推送企业微信汇总 |
| 日志 | `logs\poll.log` / `logs\digest.log` |

### 任务计划程序配置

创建第一个任务：

1. 打开「任务计划程序」→ 创建基本任务
2. 名称：`AUTO-FUND poll`
3. 触发器：**每周**，勾选 **周一至周五**，时间 **14:30**
4. 操作：启动程序
   - 程序：`F:\AUTO-FUND-AGENT\deploy\run_poll.bat`
   - 起始于：`F:\AUTO-FUND-AGENT`

创建第二个任务：

1. 名称：`AUTO-FUND poll retry`
2. 触发器：**每周**，勾选 **周一至周五**，时间 **14:35**
3. 操作：启动程序
   - 程序：`F:\AUTO-FUND-AGENT\deploy\run_poll.bat`
   - 起始于：`F:\AUTO-FUND-AGENT`

创建第三个任务：

1. 名称：`AUTO-FUND digest`
2. 触发器：**每周**，勾选 **周一至周五**，时间 **14:40**
3. 操作：启动程序
   - 程序：`F:\AUTO-FUND-AGENT\deploy\run_digest.bat`
   - 起始于：`F:\AUTO-FUND-AGENT`

两个任务都建议在「条件」里取消「只有在使用交流电源时才启动」（笔记本）。`digest.py` 内部会判断 **A 股交易日**，节假日自动跳过推送。

### 流程说明

```
14:30  run_poll.bat
         └─ poll   拉 4 个博主 RSS → 每个博主最多处理 5 篇最新未读文章 → LLM 解析 → 写飞书

14:35  run_poll.bat
         └─ poll   补抓第二次 RSS 刷新后出现的新文章；已处理文章不会重复入库

14:40  run_digest.bat
         └─ digest 读飞书 24h 操作 + 待确认 → 企业微信群推送
```

`deploy\run_daily.bat` 仍保留给手动串联测试使用，但定时任务建议使用上面的两个脚本。

## 日志查看

日志由 Python 通过 `--log-file` 以 **UTF-8** 写入，**不要用** PowerShell 的 `>>`、`Tee-Object` 或 `Out-File` 重定向到 `daily.log`（会变成 UTF-16 乱码）。

```powershell
deploy\run_daily.bat
Get-Content F:\AUTO-FUND-AGENT\logs\daily.log -Tail 30 -Encoding utf8
```

若 Cursor 仍乱码：右下角选 **UTF-8** 重新打开。旧的 UTF-16 日志会在下次运行时自动改名为 `daily.log.old`。

## 上云

稳定后参考 [DEPLOY.md](DEPLOY.md)，使用 `deploy/auto-fund-poll.timer`（工作日 14:30/14:35）和 `deploy/auto-fund-digest.timer`（工作日 14:40）。
