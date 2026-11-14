# 涨停次日接力策略 · 每日自动观察池

基于 A 股当日涨停/炸板/跌停池与主力资金流，用多因子打分生成**次日接力观察池**，每个交易日收盘后自动运行，推送飞书交互卡片，并发布一个手机/电脑都能访问的响应式看板。

> **免责声明**：本工具基于公开行情数据与量化打分，仅用于研究与复盘，不构成投资建议。市场有风险，投资需谨慎。过往表现不预示未来收益。

---

## 一、它能做什么

| 能力 | 说明 |
|---|---|
| 每日自动运行 | 周一至周五**两次**：13:07 盘中快照（UTC 05:07）+ 15:37 收盘定稿（UTC 07:37）；准点由 Cloudflare Worker 触发，GitHub cron 仅作兜底；节假日通过接口返回日期比对自动跳过推送 |
| 飞书推送 | 自定义机器人交互卡片：市场情绪、Top 候选、主力资金聚焦、历史复盘，以及 4 个跳转/交互按钮；支持加签校验 |
| 响应式看板 | GitHub Pages 托管，手机/电脑自适应；搜索、分档/连板/行业筛选、排序、拖动权重实时重算排名、个股下钻、图表/表格切换、明暗主题、历史日期切换 |
| 主力资金分析 | 当日主力/超大单/大单/中单/小单净额拆解，叠加 5 日、10 日主力净额区分「趋势性布局」与「单日脉冲」；资金排行、板块资金合计 |
| 复盘闭环 | 每日快照提交进仓库，下一交易日自动计算观察池的次日涨跌、胜率、晋级率 |
| 多数据源容灾 | 4 家供应商 + 东财多域名共 13 个接口分层降级；主源限流时自动切换并交叉校验，看板/飞书卡片显式标注降级口径；附一键健康自检 |

技术栈：后端纯 Python 标准库，前端原生 JS + SVG，零第三方依赖（Actions 无需 `pip install`）。数据同时输出 `.json` 与 `.js`，因此直接双击 `docs/index.html` 也能看到内容。

### 运行节奏（每个交易日两次）

| 北京时间 | cron（UTC） | 口径 | 飞书卡片 |
|---|---|---|---|
| **13:07** | `7 5 * * 1-5` | 盘中实时快照 | 标题标「盘中快照」，复盘数据标「盘中口径」 |
| **15:37** | `37 7 * * 1-5` | 收盘定稿 | 标题标「收盘定稿」，用于次日接力决策 |

准点触发由 [Cloudflare Worker 统一调度器](https://github.com/Wind866/BIGApush/blob/main/cloudflare/README.md) 通过 `workflow_dispatch` 完成，上表的 GitHub cron 只作兜底。分钟数刻意避开 `:00` / `:30`，因为整点是 GitHub 调度器最拥堵的时刻。两个档期靠 `EXPECT_HHMM` 区分，推送台账按「日期-slot」判重，先到的那次真正推送、后到的秒级退出。

两次共用同一个 `date`，历史索引按日期去重，不会重复计入；`data/snapshots/YYYY-MM-DD.json` 与 `docs/data/daily/` 会由 15:37 那次覆盖为定稿，每天因此产生两次 bot 提交（commit message 带时分以便区分）。周末不触发，节假日通过接口返回日期比对自动跳过推送。

**不要指望 GitHub cron 准点**：本账号实测 34 次定时运行 0 次准时，延迟 3.3~9.7 小时，高负载时排队档期会被直接丢弃。这也是引入外部调度器的原因。要改时间必须同时改三处：`.github/workflows/daily.yml` 的 `schedule` 与 `推导计划时刻` 分支、Worker 的 `PLAN` 档期表、以及本表（**UTC = 北京时间 − 8 小时**）；CI 里的档期一致性用例会拦住文档漂移，但跨仓库的 Worker 档期表仍需人工同步。

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
python src/run_daily.py --no-push          # 抓当日真实数据，收盘后运行最佳
python src/run_daily.py --demo --no-push   # 离线演示：用随仓库附带的历史真实快照样本
python src/check_sources.py                # 逐项探测全部数据接口，定位失效源
python scripts/serve.py                    # 预览看板 http://127.0.0.1:8000
```

`check_sources.py` 支持 `--json`、`--markdown`（写入 GitHub Step Summary）、`--out <文件>`。
GitHub 仓库 **Actions → 数据源健康自检 → Run workflow** 可在云端一键体检（每周一 09:00 也会自动体检，不推送飞书）。

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
.github/workflows/daily.yml          每日定时任务（采集 → 复盘 → 评分 → 推送 → 提交快照 → 部署 Pages）
.github/workflows/check-sources.yml  数据源健康自检（手动 + 每周一自动）
src/sources.py                     多源适配层：4 家供应商、字段归一化、容灾调度、健康日志、交叉校验
src/datasource.py                  数据层统一入口（对外 API 不变）、陈旧快照回退
src/check_sources.py               数据源健康自检 CLI
src/strategy.py                    情绪判定、板块强度、七因子评分与风险扣分
src/report.py                      历史索引、次日复盘、报告输出（json + js）
src/feishu.py                      加签与交互卡片构造、推送
src/run_daily.py                   主入口
config.json                        权重、阈值、分档、data_sources 开关、免责声明
docs/                         GitHub Pages 看板（index.html / app.js / style.css）
docs/data/                    看板数据；latest.*、history.*、daily/、review.json、demo.json
data/snapshots/               每日原始快照，供次日复盘
scripts/serve.py              本地静态预览服务
```

---

## 六、数据源与容灾

### 为什么要多源

原实现全部依赖东方财富一家。**实测（2026-11-13 14:08—14:26）东财 `push2` 集群会整体限流**：`ulist.np` 与 `clist` 全部返回 `RemoteDisconnected`，此时仅靠 `82.` / `push2delay` 等同供应商镜像域名**全部无效**，必须跨供应商切换。同花顺、新浪、腾讯在相同时点均正常。

现在共接入 **4 家供应商 / 13 个接口**，按「同供应商多域名 → 跨供应商」两级降级：

| 环节 | 降级顺序（从左到右） |
|---|---|
| 涨停池 ZT | 东财 `push2ex`（https + http 多域名）→ **同花顺涨停池** → 新浪全市场涨幅榜按涨停价重建 |
| 炸板池 ZB / 跌停池 DT | 东财 `push2ex`（多域名）→ 新浪全市场涨/跌幅榜按最高价、涨跌停价重建 |
| 行情 + 当日四类单资金 | 东财 `ulist.np`（3 域名）→ 东财 `clist` 榜单通道（**同口径全字段**）→ 腾讯证券 → 新浪榜单复用 / `hq.sinajs.cn` 逐票 |
| 资金拆解补齐 | 上述都缺时，用新浪 `MoneyFlow.ssi_ssfx_flzjtj` 批量补齐当日超大单/大单/中单/小单 |
| 5 日 / 10 日 / 逐日资金 | 东财 `push2his` + `82.push2his` 双域名；失败时多周期按中性 50 分计，不影响主流程 |
| 交叉校验 | 涨停池主源为东财时，额外比对同花顺涨停家数与成分重合度；偏差会在看板标注 |

`clist` 通道是关键一层：它与 `ulist.np` 使用**完全相同的字段与口径**（f62/f184/f66/f69/f164/f174 等），实测按涨幅降序第 1 页即可覆盖当日全部涨停股（37/37，0.47 秒）。因此多数限流场景下，降级后数据仍与历史**完全可比**。

### 数据质量分级

每次采集都会把结果写入 `snapshot.source_health`，并展示在**看板顶部徽标、资金页提示条、策略说明 →「数据源与容灾」**（含每个接口的成功/失败与耗时）、以及飞书卡片头部。

| 质量 | 含义 | 影响 |
|---|---|---|
| `full` | 东财主源齐全，资金口径一致 | 与历史快照可直接比较 |
| `partial` | 至少一个备用源；封板质量/行业/多周期部分缺失，或资金由新浪补齐 | 缺失因子按中性 50 分计，**跨日分数不可直接比较** |
| `minimal` | 仅新浪量价口径，无资金拆解 | 资金图表留空（不以 0 冒充净额），评分仅供参考 |

**口径红线**：
- 任何字段缺失一律返回 `None`，绝不用 0 或猜测值冒充真实行情；
- 新浪 r0~r3 是「主动买卖单」分级，与东财「大单+超大单」**不等价**，切换后会打上 `fund_source=sina` / `fund_comparable=false`，卡片与看板显式警告，且不提供 5/10 日多周期；
- 同花顺源不提供成交额时按「流通市值 × 换手率」推导，仅用于流动性门槛筛选，并在健康报告标注为推导值；
- 主源恢复后自动切回，无需人工干预。

### 配置开关（`config.json → data_sources`）

| 键 | 默认 | 说明 |
|---|---|---|
| `eastmoney` | `true` | 东财池 + `ulist.np` 主源 |
| `eastmoney_clist` | `true` | 东财 `clist` 榜单通道（与 `ulist` 同口径） |
| `ths` | `true` | 同花顺涨停池、连板高度与交叉校验 |
| `tencent` | `true` | 腾讯证券逐票行情 |
| `sina` | `true` | 新浪榜单重建池、逐票行情 |
| `sina_flow_backfill` | `true` | 资金全缺时用新浪批量资金流补齐（口径不同，会标注） |
| `cross_check` | `true` | 东财 vs 同花顺涨停家数/成分交叉校验 |
| `timeout_seconds` / `max_retries` | `8` / `2` | 所有接口的超时与重试上限；调小可更快失败并降级 |

把某个键设为 `false` 即可单独禁用该源用于排错。自检命令：

```bash
python src/check_sources.py                 # 表格：每个接口的状态 / 耗时 / 摘要
python src/check_sources.py --markdown     # Markdown，适合 GitHub Step Summary
python src/check_sources.py --json --out docs/data/sources.json
```

### 全部接口都失效时

按顺序回退，**两种情况都不推送飞书、绝不编造行情**：
1. `data/snapshots/` 里最近一次真实快照 → 标记 `is_stale`，页面顶部显示「数据已过期，不可用于当日决策」；
2. 仓库内置 `docs/data/demo.json` 历史样本 → 标记演示数据。

---

## 七、已知局限与免责声明

- 数据来自公开行情接口，标注了来源与抓取时点（北京时间）；盘中数据会变动，**收盘后 15:37 才是定稿**。
- 「主力资金」是按成交单笔金额推断的统计量，**不是交易所席位真实资金**；备用源口径与主源不等价，跨日比较需谨慎。
- 公开接口字段与限流策略可能随时调整，`check_sources.py` 用于快速定位；接口变更后请以当期健康报告为准。
- 评分为专家规则加权，未做样本外寻优/参数优化，不应直接当作交易信号。
- 涨停次日常见一字板或大幅高开，复盘的模拟溢价**不等于可实现收益**，未计交易成本与滑点。
- 降级到量价口径时，封板时间、封单额、连板数与行业缺失，相关因子按中性处理，观察池排序的参考价值下降。

> **免责声明**：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。
