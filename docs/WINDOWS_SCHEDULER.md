# Windows 定时任务

博主一般在 **14:00 左右**发文，因此**不需要**每 30 分钟轮询。  
推荐：**每个工作日固定跑一次**——先拉 RSS 解析入库，再发企业微信汇总。

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

## 推荐：一个定时任务（Poll + Digest）

| 脚本 | 作用 |
|------|------|
| **`deploy\run_daily.bat`** | 先 `poll` 拉取解析入库，再 `digest` 推送汇总 |
| 日志 | `logs\daily.log` |

### 任务计划程序配置

1. 打开「任务计划程序」→ 创建基本任务
2. 名称：`AUTO-FUND daily`
3. 触发器：**每周**，勾选 **周一至周五**，时间 **14:20**（博主约 14:00 发文，留约 20 分钟缓冲）
4. 操作：启动程序
   - 程序：`F:\AUTO-FUND-AGENT\deploy\run_daily.bat`
   - 起始于：`F:\AUTO-FUND-AGENT`
5. 条件：取消「只有在使用交流电源时才启动」（笔记本）
6. `digest.py` 内部会判断 **A 股交易日**，节假日自动跳过推送

### 流程说明

```
14:20  run_daily.bat
         ├─ poll   拉 4 个博主 RSS → LLM 解析 → 写飞书
         └─ digest 读飞书 24h 操作 + 待确认 → 企业微信群推送
```

## 可选：拆成两个任务

若希望 **14:30 整** 才推送（方案默认时间），可拆成：

| 任务 | 时间 | 脚本 |
|------|------|------|
| 仅入库 | 周一至五 14:15 | `deploy\run_poll.bat` |
| 仅推送 | 周一至五 14:30 | `deploy\run_digest.bat` |

一般 **一个 `run_daily.bat` 即可**，不必高频 poll。

## 日志查看

日志由 Python 通过 `--log-file` 以 **UTF-8** 写入，**不要用** PowerShell 的 `>>`、`Tee-Object` 或 `Out-File` 重定向到 `daily.log`（会变成 UTF-16 乱码）。

```powershell
deploy\run_daily.bat
Get-Content F:\AUTO-FUND-AGENT\logs\daily.log -Tail 30 -Encoding utf8
```

若 Cursor 仍乱码：右下角选 **UTF-8** 重新打开。旧的 UTF-16 日志会在下次运行时自动改名为 `daily.log.old`。

## 上云

稳定后参考 [DEPLOY.md](DEPLOY.md)，使用 `deploy/auto-fund-daily.timer`（工作日 14:20，poll + digest 串联）。
