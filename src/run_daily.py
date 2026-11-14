"""每日运行入口：采集 → 复盘 → 评分 → 生成看板数据 → 推送飞书。

本地：
    python src/run_daily.py                 # 抓当日真实数据（收盘后运行最佳）
    python src/run_daily.py --demo         # 使用历史真实快照样本（离线演示）
    python src/run_daily.py --no-push      # 不推飞书
    python scripts/serve.py                # 本地预览看板 http://127.0.0.1:8000

GitHub Actions：见 .github/workflows/daily.yml，交易日北京时间 13:07（盘中快照）、15:37（收盘定稿）自动执行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import datasource as ds  # noqa: E402
from src import feishu, push_guard, report, strategy as st  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def market_status(now: ds.dt.datetime) -> str:
    if now.weekday() >= 5:
        return "休市"
    t = now.hour * 60 + now.minute
    if t < 9 * 60 + 15:
        return "盘前"
    if 9 * 60 + 15 <= t < 11 * 60 + 30 or 13 * 60 <= t < 15 * 60:
        return "盘中"
    if 11 * 60 + 30 <= t < 13 * 60:
        return "午间休市"
    return "收盘后"


def log(msg: str) -> None:
    print(f"[relay] {msg}", flush=True)


LATE_GRACE_MINUTES = 20          # 超过这个延迟就要在日志与卡片上标注
INTRADAY_HOUR = "13"             # 盘中快照的计划小时（HH），必须与 daily.yml 的盘中 cron 一致
INTRADAY_MAX_LATE_MINUTES = 90   # 盘中快照迟到超过该值：卡片标注时点，仍照常推送


def late_minutes(now: ds.dt.datetime, expect: str) -> int:
    """返回比计划时刻晚多少分钟。expect 形如 '1537'，未提供或非法时返回 0。"""
    expect = (expect or "").strip()
    if len(expect) != 4 or not expect.isdigit():
        return 0
    planned = now.replace(hour=int(expect[:2]), minute=int(expect[2:]),
                          second=0, microsecond=0)
    return int((now - planned).total_seconds() // 60)


def should_skip_intraday_push(expect: str, late: int, status: str) -> bool:
    """盘中快照是否属于「已非盘中口径」（只用于标注，不再拦截推送）。

    两种情形都算「数据已非盘中口径」：
      1) 迟到 ≥90 分钟；
      2) 迟到不多但运行时刻已经收盘（如 13:07 的任务 15:10 才起来）。
    用小时前缀判断而非精确比对 HHMM，避免改 cron 时这里忘了同步（旧写法踩过这个坑）。
    """
    if not expect.startswith(INTRADAY_HOUR):
        return False
    return late >= INTRADAY_MAX_LATE_MINUTES or status != "盘中"


def main() -> int:
    ap = argparse.ArgumentParser(description="涨停次日接力策略 · 每日运行")
    ap.add_argument("--date", help="目标日期 YYYY-MM-DD，默认今天（北京时间）")
    ap.add_argument("--demo", action="store_true", help="使用随仓库附带的历史真实快照样本")
    ap.add_argument("--no-push", action="store_true", help="不推送飞书")
    ap.add_argument("--force", action="store_true", help="跳过交易日检查 / 强制推送")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--root", default=ROOT)
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    now = ds.now_cn()
    target = ds.dt.date.fromisoformat(args.date) if args.date else now.date()
    status = market_status(now)

    # ---------- 0. 定时延迟守卫 ----------
    # GitHub 的 schedule 只保证"尽力而为"，实测可能晚几小时才触发。
    # EXPECT_HHMM 由 workflow 在 schedule 触发时注入（如 1537），其余触发为空。
    expect = os.getenv("EXPECT_HHMM", "")
    late = late_minutes(now, expect)
    if late >= LATE_GRACE_MINUTES:
        log(f"⚠️ 计划 {expect[:2]}:{expect[2:]} 运行，实际晚了 {late} 分钟（调度延迟）")
    # 迟到只标注、不拦截：准点由外部 Worker 触发，GitHub cron 延迟到达时
    # 由 push_guard 读台账判重；外部定时器未部署时，迟到的一条也比完全没有强。
    if not args.demo and should_skip_intraday_push(expect, late, status):
        log(f"盘中快照迟到 {late} 分钟（当前状态：{status}）→ 卡片会标注实际时点，仍照常推送")

    if target.weekday() >= 5 and not args.force and not args.demo:
        log(f"{target} 为周末，非交易日，跳过（--force 可强制运行）")
        return 0

    # ---------- 1. 采集 ----------
    demo_path = os.path.join(args.root, "docs", "data", "demo.json")
    if args.demo:
        if not os.path.exists(demo_path):
            log(f"演示样本不存在：{demo_path}")
            return 2
        snap = ds.load_demo(demo_path)
        log(f"使用历史真实快照样本：{snap['date']}（标记为演示数据）")
        log("注意：演示模式会覆盖 docs/data/latest.*；恢复真实数据请重新运行 python src/run_daily.py --no-push")
    else:
        try:
            log(f"采集 {target} 涨停池 / 炸板池 / 跌停池 / 资金流…")
            snap = ds.collect(day=target, flow_top=0)
        except ds.DataSourceError as exc:
            log(f"行情接口全部不可用：{exc}")
            # 优先用最近一次真实快照（比内置 demo 新），并强制标记为陈旧
            stale = ds.load_recent_snapshot(
                os.path.join(args.root, "data", "snapshots"), target.isoformat())
            if stale:
                snap = stale
                args.no_push = True
                log(f"降级到最近一次真实快照 {stale['date']}（已标记陈旧，不推送飞书）")
            elif os.path.exists(demo_path):
                snap = ds.load_demo(demo_path)
                log(f"降级到历史真实快照样本 {snap['date']}（演示数据不推送）")
            else:
                return 3

        h = snap.get("source_health") or {}
        if h:
            qg = h.get("groups", {}).get("quotes", {})
            log(f"数据源健康：质量 {h.get('quality')} / 失败尝试 {h.get('failed_count')} 次 / "
                f"行情覆盖 {qg.get('coverage')} / 资金口径 {qg.get('fund_source')}")
            for note in h.get("notes", [])[:4]:
                log("  · " + note)

        qdate = snap.get("date")
        if qdate != target.isoformat() and not args.force:
            log(f"接口返回最近交易日 {qdate}，与 {target} 不一致 → 判定为节假日/休市，"
                "仅生成本地数据，不推送飞书")
            args.no_push = True

        # 可选增强：对最高分候选尝试补抓逐日资金流（该接口偶发限流，失败不影响主流程）
        if snap.get("limit_up"):
            prelim = st.build_candidates(snap, cfg)
            picked = [(c["code"], c["secid"]) for c in prelim[:cfg.get("flow_detail_top", 6)]]
            snap["flow_history"] = {}
            for code, secid in picked:
                try:
                    snap["flow_history"][code] = ds.fetch_flow_history(secid, retries=1)
                except ds.DataSourceError:
                    pass
            got = sum(1 for v in snap["flow_history"].values() if v)
            qall = snap.get("quotes", {})
            multi = sum(1 for v in qall.values() if v.get("main_net_5d") is not None)
            log(f"逐日资金流明细：{got}/{len(picked)} 只可用；批量接口多周期资金覆盖 "
                f"{multi}/{len(qall)} 只")

    # ---------- 2. 复盘 ----------
    snap_dir = os.path.join(args.root, "data", "snapshots")
    if snap.get("is_demo"):
        review = {"available": False, "reason": "演示模式不做复盘", "next_day": snap.get("date")}
    else:
        review = report.compute_review(snap, cfg, snap_dir)
    if review.get("available"):
        o = review["overall"]
        log(f"复盘：样本 {o['count']} 只，次日平均 {o['avg_pct']:+.2f}%，胜率 {o['win_rate']}%")

    # ---------- 3. 生成报告 ----------
    hist_path = os.path.join(args.root, "docs", "data", "history.json")
    sentiment = st.market_sentiment(snap)
    sectors = st.sector_strength(snap, snap.get("quotes", {}))
    cands = st.build_candidates(snap, cfg, sectors)
    days = report.history_index(hist_path, snap["date"], snap, sentiment, cands, review)
    result = report.build_report(snap, cfg, review, days, status, late_minutes=late)
    files = report.write_outputs(result, snap, cfg, args.root)
    log("已生成：" + ", ".join(files))

    # ---------- 4. 飞书推送 ----------
    # 双档任务（13:07 / 15:37）共用一个 workflow，用 EXPECT_HHMM 作为 slot，
    # 让台账按「日期-slot」判重，同一天的两个档互不干扰。
    slot = expect if (len(expect) == 4 and expect.isdigit()) else None
    force = os.getenv("FORCE_PUSH") == "1" or args.force
    if args.no_push:
        log("按参数跳过飞书推送")
        push_result = {"skipped": True, "reason": "--no-push"}
    elif push_guard.should_skip("daily.yml", force=force, cutoff_hour=12, slot=slot):
        log("⏭ 本档期已推送成功，跳过重复推送")
        push_result = {"skipped": True, "reason": "push_guard"}
    else:
        push_result = feishu.push(result, force=force)
        # 只有飞书确实推送成功才写台账；降级/跳过/失败都不写
        if not push_result.get("skipped") and push_result.get("ok") is True:
            push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot=slot)
    log(f"飞书推送：{json.dumps(push_result, ensure_ascii=False)[:300]}")

    # ---------- 5. 终端摘要 ----------
    s = result["sentiment"]
    log(f"=== {snap['date']} | 情绪 {s['level']} | 涨停 {s['limit_up']} / 炸板 {s['broken']} "
        f"/ 跌停 {s['limit_down']} | 最高 {s['max_board']} 板 | A 档 "
        f"{sum(1 for c in cands if c['grade'] == 'A')} 只 ===")
    for c in cands[:5]:
        log(f"  {c['rank']:>2}. {c['name']}({c['code']}) {c['score']}分 {c['grade']} "
            f"{c['boards']}板 {c['industry']} 主力{c['main_net_yi']}亿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
