# 涨停次日接力策略 · 每日自动观察池

基于 A 股当日涨停/炸板/跌停池与主力资金流，用多因子打分生成**次日接力观察池**，每个交易日收盘后自动运行，推送飞书交互卡片，并发布一个手机/电脑都能访问的响应式看板。

> **免责声明**：本工具基于公开行情数据与量化打分，仅用于研究与复盘，不构成投资建议。市场有风险，投资需谨慎。过往表现不预示未来收益。

---

## 一、它能做什么

| 能力 | 说明 |
|---|---|
| 每日自动运行 | GitHub Actions，周一至周五北京时间 15:30（UTC 07:30）；节假日通过接口返回日期比对自动跳过推送 |
| 飞书推送 | 自定义机器人交互卡片：市场情绪、Top 候选、主力资金聚焦、历史复盘，以及 4 个跳转/交互按钮；支持加签校验 |
| 响应式看板 | GitHub Pages 托管，手机/电脑自适应；搜索、分档/连板/行业筛选、排序、拖动权重实时重算排名、个股下钻、图表/表格切换、明暗主题、历史日期切换 |
| 主力资金分析 | 当日主力/超大单/大单/中单/小单净额拆解，叠加 5 日、10 日主力净额区分「趋势性布局」与「单日脉冲」；资金排行、板块资金合计 |
| 复盘闭环 | 每日快照提交进仓库，下一交易日自动计算观察池的次日涨跌、胜率、晋级率 |

技术栈：后端纯 Python 标准库，前端原生 JS + SVG，零第三方依赖（Actions 无需 `pip install`）。数据同时输出 `.json` 与 `.js`，因此直接双击 `docs/index.html` 也能看到内容。

---

## 二、部署到 GitHub（5 步）

> **两个最容易踩的坑**
> 1. `.github/workflows/daily.yml` 位于隐藏目录，**用网页拖拽上传极易漏传**，漏了就完全没有自动运行。请走 `git push`。
> 2. 仓库必须设为 **Public**：免费版 GitHub 账号的私有仓库无法启用 GitHub Pages（会提示升级）。

```bash
cd limit-up-relay
git init -b main
git add .
git commit -m "init: limit-up relay strategy"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

当前本地目录**已经完成** `git init` / `git add` / `git commit`（首次提交已含全部 25 个文件），所以只需执行最后两行。

**首次 push 的登录方式**：本机装有 Git Credential Manager，`git push` 会弹出浏览器让你登录并授权 GitHub，点同意即可，**不需要手动创建令牌**。若没弹窗而是要求输入密码（GitHub 已不支持账号密码），二选一：

- 执行 `git config --global credential.helper manager` 后重试；
- 或到 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) 生成勾选 `repo` 的令牌，push 时用户名填 GitHub 用户名、密码粘贴该令牌。

若 `git push` 卡住或超时，多为网络问题，检查代理后重试。可用 `git config --global http.proxy http://127.0.0.1:端口` 配置（端口换成你本机代理的实际端口）。

1. 在 GitHub 网页右上角 **+ → New repository** 创建**空仓库**（建议名 `limit-up-relay`，选 **Public**，**不要勾选** Add a README / .gitignore / license，否则首次 push 会冲突），然后推送整个目录（**含 `.github/`、`.env.example`、`docs/data/`、`data/snapshots/`**）。`.gitignore` 会排除 `__pycache__/`、`.env`、`*.log`、预览截图等。
2. **（必需，别跳过）** 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。这一步是手动的：工作流用的默认 `GITHUB_TOKEN` 无权创建 Pages 站点，跳过它会导致 `配置 GitHub Pages` 步骤失败、看板 404。
3. 飞书群 → 设置 → 群机器人 → 添加「自定义机器人」，复制 Webhook，开启「加签」并复制密钥。
4. 仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：

   | Secret | 必填 | 说明 |
   |---|---|---|
   | `FEISHU_WEBHOOK` | 是 | 飞书机器人 Webhook；不填则只生成数据、跳过推送，不报错 |
   | `FEISHU_SECRET` | 建议 | 加签密钥；机器人未开启加签则留空 |
   | `PAGES_URL` | 否 | 留空会自动推导为 `https://<owner>.github.io/<repo>/` |

   仓库地址 `REPO_URL` 由 Actions 自动注入，无需配置。**切勿把真实 webhook/密钥写进文件提交**（`.env.example` 只是模板）。
5. **Actions → 每日涨停接力策略 → Run workflow**（mode=`close`）手动跑一次验证：飞书收到卡片、Pages 看板能打开、仓库里出现当日快照。

定时任务偶有 5~15 分钟延迟，属 GitHub 正常现象。

### 排错：Actions 前几步成功，但「配置 GitHub Pages」失败 / 看板 404

**现象**：Actions 里采集、评分、快照提交全部成功，只有 `配置 GitHub Pages` 一步报红，`https://<owner>.github.io/<repo>/` 返回 404，飞书卡片里的「打开交互看板」「主力资金明细」按钮也全部 404。

**原因**：仓库的 Pages 站点尚未创建，或构建源不是 GitHub Actions，`actions/configure-pages` 读取站点配置失败，导致上传和部署步骤被跳过。

**处理**：

1. 网页上进入 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**，保存。这是唯一必需的一步，且**无法由工作流自动完成**：`actions/configure-pages` 的 `enablement` 参数要求提供额外的 Personal Access Token，默认 `GITHUB_TOKEN` 权限不足，所以本工作流不启用它，而是在前面加了一步中文检查，未启用时会打印这条指引并提前失败。
2. 到 **Actions → 每日涨停接力策略 → Run workflow → Run workflow** 手动新跑一次。**不要用失败运行里的 Re-run**：Re-run 沿用旧提交当时的 workflow 定义，修复不会生效。

部署成功后 Pages 链接即可访问，飞书卡片里的按钮也会随之恢复。

页面内 `#flow`、`#sector`、`#review`、`#about` 锚点可直接跳转到「主力资金流向 / 板块强度 / 历史复盘 / 策略说明」页签。

---

## 三、本地运行

```bash
python src/run_daily.py --no-push      # 抓当日真实数据，收盘后运行最佳
python src/run_daily.py --demo --no-push   # 离线演示：用随仓库附带的历史真实快照样本
python scripts/serve.py                # 预览看板 http://127.0.0.1:8000
```

常用参数：`--date YYYY-MM-DD`（指定日期）、`--force`（跳过交易日检查/强制推送）、`--config`（指定配置）、`--no-push`（不推飞书）。

演示模式会用历史样本覆盖 `docs/data/latest.*`，并明确标注「历史样本，非当前行情」，默认不推送飞书；恢复真实数据重新跑一次 `--no-push` 即可。

本地推送需设置环境变量（见 `.env.example`）：`FEISHU_WEBHOOK`、`FEISHU_SECRET`，可选 `PAGES_URL`、`REPO_URL`、`FORCE_PUSH=1`。

---

## 四、策略逻辑

评分 = **7 因子加权基础分 − 逐项风险扣分**，权重与阈值全部在 [`config.json`](config.json)：

| 因子 | 权重 | 含义 |
|---|---|---|
| 封板强度 `seal` | 18 | 封单额/流通市值、封板时间、炸板次数 |
| 连板高度 `board` | 14 | 连板数与梯队位置 |
| 主力资金 `fund` | 22 | 当日主力/超大单净额 + 5 日/10 日连续性 |
| 量能换手 `volume` | 12 | 换手率与成交额 |
| 板块效应 `sector` | 14 | 同行业涨停家数、板块资金合力 |
| 市值流动性 `liquidity` | 10 | 流通市值适中度 |
| 涨停基因 `momentum` | 10 | 历史涨停活跃度 |

风险扣分：高位板（≥4 板）、反复炸板、换手过高、主力净流出、封单偏薄、市值过小/过大、尾盘封板等。分档 A≥75 / B≥65 / C≥55。

看板「七因子与权重」页可拖动滑块实时重算排名（仅前端模拟，不改云端配置）；要永久生效请修改 `config.json` 并推送。

---

## 五、目录结构

```
.github/workflows/daily.yml   每日定时任务（采集 → 复盘 → 评分 → 推送 → 提交快照 → 部署 Pages）
src/datasource.py             东方财富数据源（涨停/炸板/跌停池、行情、资金流），含重试与降级
src/strategy.py               情绪判定、板块强度、七因子评分与风险扣分
src/report.py                 历史索引、次日复盘、报告输出（json + js）
src/feishu.py                 加签与交互卡片构造、推送
src/run_daily.py              主入口
config.json                   权重、阈值、分档、免责声明
docs/                         GitHub Pages 看板（index.html / app.js / style.css）
docs/data/                    看板数据；latest.*、history.*、daily/、review.json、demo.json
data/snapshots/               每日原始快照，供次日复盘
scripts/serve.py              本地静态预览服务
```

---

## 六、数据来源与已知局限

- 数据来自东方财富公开接口，标注了来源与抓取时点（北京时间）；盘中数据会变动，**收盘后运行才是定稿**。
- 「主力资金」是按成交单笔金额推断的统计量，**不是交易所席位真实资金**。
- 评分为专家规则加权，未做样本外寻优/参数优化，不应直接当作交易信号。
- 涨停次日常见一字板或大幅高开，复盘的模拟溢价**不等于可实现收益**，未计交易成本与滑点。
- 逐日资金流明细接口偶发限流，已降级为可选增强；5 日/10 日多周期分析由批量接口覆盖，不受影响。
- 接口不可用时自动降级到 `docs/data/demo.json` 历史样本，并标记为演示数据、不推送，避免误报。
