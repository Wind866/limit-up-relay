# 涨停次日接力策略 · 每日自动观察池

> 基于涨停/炸板池与主力资金流的多因子打分，生成次日接力观察池；每交易日 18:53 收盘定稿，推送飞书并发布响应式看板。
> 准点由 Cloudflare Worker 触发，GitHub cron 仅作兜底；后端零第三方依赖。

## 快速开始

1. 创建 **Public** 空仓库并推送代码（必须包含 `.github/`、`docs/data/`、`data/snapshots/`）。
2. Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**（必须手动设置）。
3. 飞书群添加自定义机器人，建议开启加签。
4. 配置 Secrets：

| Secret | 必填 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 是 | 机器人 Webhook；不填则只生成数据、不推送 |
| `FEISHU_SECRET` | 建议 | 加签密钥 |
| `PAGES_URL` | 否 | 留空自动推导为 `https://<owner>.github.io/<repo>/` |
| `ALERT_WEBHOOK` / `ALERT_SECRET` | 建议 | 独立告警机器人及加签密钥 |

5. Actions → `daily.yml` → Run workflow（mode=`close`）验证卡片与看板。

## 运行节奏

| 北京时间 | cron（UTC） | 说明 |
| --- | --- | --- |
| 18:53 | `53 10 * * 1-5` | 收盘定稿，每日唯一正式档 |
| 19:53 / 21:53 / 次日 01:53 | `53 11/13/17 * * 1-5` | 兜底补档，按「日期-档期」判重 |

> 中午 12:33 的盘中快照档已下线（2026-11-16）；workflow 与脚本均有残留触发拦截。

## 本地开发

```bash
python src/run_daily.py --no-push
python -m unittest discover -s tests
```

也可直接双击 `docs/index.html`：数据同时输出 `.json` 与 `.js`，无需服务器。

## 目录结构

- `src/`：采集、策略、报告、推送守卫与保留期管理（纯标准库）
- `docs/`：Pages 看板与数据；`data/snapshots/`：每日快照
- `.push-state/ledger.json`：推送幂等台账，随快照同一次提交入库

## 安全说明

- Webhook 与加签密钥只通过 Secrets / `.env`（本地）提供；`.env.example` 仅为模板。
- 加签要么两个机器人都开，要么都不开；`19021` 表示加签校验失败。
- 台账只在飞书确认推送成功后写入；删除台账会导致重复推送。

## 排错

- **看板 404**：Pages Source 未选 GitHub Actions；改完需重新 Run，不能用旧 run 的 Re-run。
- **提交每日快照失败**：检查 workflow 是否包含 `git add docs/data data/snapshots .push-state` 与 `git pull --rebase`。
- **飞书收不到失败告警**：单独配置 `ALERT_WEBHOOK` / `ALERT_SECRET`，不要只依赖业务机器人。

## 免责声明

本工具基于公开行情与量化打分，仅用于研究与复盘，不构成投资建议。市场有风险，投资需谨慎；过往表现不预示未来收益。

## License

MIT

## 详细文档

- [策略逻辑、数据源与完整排错](docs/README-full.md)
- [Cloudflare Worker 统一调度器](https://github.com/Wind866/BIGApush/blob/main/cloudflare/README.md)
