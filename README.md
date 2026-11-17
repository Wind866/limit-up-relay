# 涨停次日接力策略 · 每日自动观察池

<p>
  <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Wind866/limit-up-relay/ci.yml?label=CI">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B%20stdlib-3776AB">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-3DA639">
  <img alt="Push" src="https://img.shields.io/badge/push-Feishu-00B0F0">
</p>

> 基于涨停/炸板池与主力资金流做多因子打分，生成**次日接力观察池**；每交易日 18:53 收盘定稿，推送飞书交互卡片并发布响应式看板。后端零第三方依赖，前端零框架。

看板：<https://wind866.github.io/limit-up-relay/>

## 它做什么

- **情绪打分**：统计涨停/炸板/跌停家数、连板高度、封板率，给出当日市场情绪的量化读数。
- **多因子接力池**：涨停时间、封单强度、主力净流入、换手与位置等因子加权，输出次日可跟踪的候选与分档。
- **收盘复盘**：把昨日候选与今日实际表现对照，评分为负的因子会被记录，用于迭代权重。
- **纯静态交付**：数据同时输出 `.json` 与 `.js`，双击 `docs/index.html` 即可查看。

## 快速开始

### 1. 拿到代码

```bash
git clone https://github.com/Wind866/limit-up-relay.git
cd limit-up-relay
```

必须是 **Public** 仓库，且推送时包含 `.github/`、`docs/data/`、`data/snapshots/`。

### 2. 配置 Secrets

仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 必填 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 是 | 机器人 Webhook；不填则只生成数据、不推送 |
| `FEISHU_SECRET` | 建议 | 加签密钥 |
| `PAGES_URL` | 否 | 留空自动推导为 `https://<owner>.github.io/<repo>/` |
| `ALERT_WEBHOOK` | 建议 | 独立告警机器人 |
| `ALERT_SECRET` | 否 | 告警机器人加签密钥 |

### 3. 打开 Pages

**Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**（必须手动设置）。

### 4. 手动验证一次

**Actions → 每日涨停接力策略 → Run workflow**（`mode=close`），确认卡片与看板都正常。

## 运行节奏

| 北京时间 | cron（UTC） | 说明 |
| --- | --- | --- |
| 18:53 | `53 10 * * 1-5` | 收盘定稿，每日唯一正式档 |
| 19:53 / 21:53 | `53 11/13 * * 1-5` | 兜底补档，按「日期-档期」判重（均为当天，不跨日） |

- **当天任务当天完成**：兜底档全部收敛在当天（最晚 21:53）。若调度延迟拖到次日才触发，
  `run_daily.py` 的跨日守卫会跳过采集与推送、写业务失败标记，由 workflow 判红并告警，
  不静默补跑上一交易日；确需补跑可在 Actions 手动运行时勾选 `force`。
- 准点由 Cloudflare Worker 派发；仓库内 cron 仅作兜底。
- 中午 12:33 的盘中快照档已下线（2026-11-16），workflow 与脚本均保留触发拦截。
- 台账只在飞书确认推送成功后写入；删除台账会导致重复推送。

## 目录结构

```text
src/
  run_daily.py       主流程入口（含档期与交易日闸门）
  sources.py         行情/涨停池数据源（标准库 urllib）
  datasource.py      数据装配与本地快照
  strategy.py        情绪打分与接力池排序
  report.py          看板数据、历史索引、复盘
  feishu.py          签名与卡片推送
  push_guard.py      推送幂等台账
  retention.py       归档保留期（daily 120 天 / snapshots 45 天）
  check_sources.py   数据源健康自检
docs/
  index.html         看板（原生 JS + 原生 SVG）
  data/              latest.json/.js、daily/、history.json
data/snapshots/      每日原始快照
scripts/serve.py     本地预览服务器
tests/               CI 门禁：语法 / 单元 / 档期一致性
```

## 本地开发

```bash
python src/run_daily.py --no-push     # 跑一遍，不推送
python -m unittest discover -s tests
python scripts/serve.py               # 本地起服务看板
```

也可直接双击 `docs/index.html`：数据同时输出 `.json` 与 `.js`，无需服务器。

## 数据与配置口径

| 项 | 说明 |
| --- | --- |
| 依赖 | 仅 Python 3.10+ 标准库（urllib / json / hmac / hashlib），CI 不执行 `pip install` |
| 归档保留 | `docs/data/daily/` 留 120 天（前端下拉最多读 90 天）；`data/snapshots/` 留 45 天 |
| 判重口径 | 按「日期-档期」记账；当天完成，跨日运行改为告警而非补跑 |
| 数据源 | 东方财富公开接口；失效时 `check-sources.yml` 会判红 |

## 安全说明

- Webhook 与加签密钥**只**通过 Secrets / `.env`（本地）提供，`.env.example` 仅为模板。
- 加签要么两个机器人都开，要么都不开；`19021` 表示加签校验失败。
- 台账只认飞书返回成功，避免「报错但已扣档」。
- 所有 Action 固定到 commit SHA，并由 dependabot 每周提升级 PR。

## 排错

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 看板 404 | Pages Source 未选 GitHub Actions | 改完需重新 Run，不能用旧 run 的 Re-run |
| 每日快照提交失败 | workflow 缺少 `git add docs/data data/snapshots .push-state` 或未 `git pull --rebase` | 按 `.github/workflows/daily.yml` 的提交段对齐 |
| 飞书收不到失败告警 | 只依赖业务机器人 | 单独配置 `ALERT_WEBHOOK` / `ALERT_SECRET` |
| 收到重复卡片 | 台账被删或未提交 | 恢复 `.push-state/ledger.json` 或接受一次重复 |

## 相关文档

- [策略逻辑、数据源与完整排错](docs/README-full.md)
- [统一调度 Worker](https://github.com/Wind866/BIGApush/blob/main/cloudflare/README.md)

## 免责声明

本工具基于公开行情与量化打分，仅用于研究与复盘，不构成投资建议。市场有风险，投资需谨慎；过往表现不预示未来收益。

## License

MIT
