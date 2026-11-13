"""报告生成 + 基于每日真实快照的策略复盘。

复盘口径（务必如实理解）
------------------------
* 取上一交易日保存的观察池，用今日行情计算「次日涨跌幅」与「晋级率」。
* 该数值是**模拟跟踪**，不等于可实现收益：涨停次日常见一字板 / 大幅高开，
  实际难以按前收盘价成交；且未计佣金、印花税、滑点与冲击成本。
* 主力资金为按成交单笔金额推断的统计量，不是交易所席位真实资金。
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from . import datasource as ds
from . import strategy as st

DISCLAIMER = (
    "免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。"
    "市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，"
    "必要时咨询持牌专业机构。过往表现不预示未来收益。"
)


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))


def _write_js(path: str, var: str, data: Any) -> None:
    """同时输出 .js 版本，使得本地 file:// 双击打开看板也能读到数据（script 标签不受 CORS 限制）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"window.{var} = {payload};\n")


def compute_review(snap: dict, cfg: dict, snapshot_dir: str) -> dict:
    """用今日行情复盘上一交易日的观察池。"""
    today = snap.get("date", "")
    files = sorted(glob.glob(os.path.join(snapshot_dir, "*.json")))
    prev_files = [p for p in files if os.path.basename(p)[:10] < today]
    if not prev_files:
        return {
            "available": False,
            "reason": "暂无更早的交易日快照，运行 2 个交易日后自动生成复盘",
            "next_day": today,
        }

    prev_path = prev_files[-1]
    prev = _load_json(prev_path)
    prev_date = prev.get("date") or os.path.basename(prev_path)[:10]
    picks = (prev.get("candidates") or [])[:cfg.get("top_n", 25)]
    if not picks:
        return {"available": False, "reason": "上一交易日快照没有候选数据", "next_day": today}

    secids = [p["secid"] for p in picks if p.get("secid")]
    try:
        quotes = ds.fetch_quotes(secids, with_flow=False)
    except ds.DataSourceError as exc:
        return {"available": False, "reason": f"次日行情获取失败：{exc}", "next_day": today}

    lu_codes = {s["code"] for s in snap.get("limit_up", [])}
    rows = []
    for p in picks:
        q = quotes.get(p["code"], {})
        rows.append({
            "code": p["code"],
            "name": p.get("name"),
            "grade": p.get("grade"),
            "score": p.get("score"),
            "boards": p.get("boards"),
            "industry": p.get("industry"),
            "next_pct": q.get("pct"),
            "promoted": p["code"] in lu_codes,
        })

    valid = [r for r in rows if r["next_pct"] is not None]
    if not valid:
        return {"available": False, "reason": "次日行情为空（可能尚未开盘）", "next_day": today}

    def stat(group: list[dict]) -> dict:
        vals = [r["next_pct"] for r in group if r["next_pct"] is not None]
        n = len(vals)
        return {
            "count": n,
            "avg_pct": round(sum(vals) / n, 2) if n else None,
            "win_rate": round(sum(1 for v in vals if v > 0) / n * 100, 1) if n else None,
            "promote_rate": round(sum(1 for r in group if r["promoted"]) / n * 100, 1) if n else None,
            "max_pct": round(max(vals), 2) if n else None,
            "min_pct": round(min(vals), 2) if n else None,
        }

    by_grade = {}
    for g in ("A", "B", "C", "D"):
        group = [r for r in rows if r["grade"] == g]
        by_grade[g] = stat(group)

    by_board = {}
    for b in (1, 2, 3, 4):
        label = f"{b}板" if b < 4 else "4板+"
        group = [r for r in rows if (r["boards"] or 1) == b] if b < 4 else \
                [r for r in rows if (r["boards"] or 1) >= 4]
        by_board[label] = stat(group)

    hour = ds.now_cn().hour + ds.now_cn().minute / 60
    intraday = ds.now_cn().date().isoformat() == today and hour < 15.05

    return {
        "available": True,
        "source_snapshot": prev_date,
        "next_day": today,
        "as_of": snap.get("as_of"),
        "is_intraday": intraday,
        "overall": stat(valid),
        "by_grade": by_grade,
        "by_board": by_board,
        "rows": rows,
        "source": "东方财富实时行情（ulist.np），对照本仓库上一交易日观察池快照",
        "caveat": "模拟跟踪口径：按前收盘价计算次日涨跌幅，未考虑一字板无法成交、"
                  "高开滑点、佣金与印花税，不等于可实现收益。",
    }


def history_index(history_path: str, today: str, snap: dict, sentiment: dict,
                  candidates: list[dict], review: dict) -> list[dict]:
    days: list[dict] = []
    if os.path.exists(history_path):
        try:
            days = _load_json(history_path).get("days", [])
        except (ValueError, OSError):
            days = []
    top = candidates[:cfg_top(candidates)]
    entry = {
        "date": today,
        "limit_up": sentiment.get("limit_up"),
        "broken": sentiment.get("broken"),
        "break_rate": sentiment.get("break_rate"),
        "max_board": sentiment.get("max_board"),
        "sentiment": sentiment.get("level"),
        "top_score": top[0]["score"] if top else None,
        "a_count": sum(1 for c in candidates if c["grade"] == "A"),
        "avg_pct": review.get("overall", {}).get("avg_pct") if review.get("available") else None,
        "win_rate": review.get("overall", {}).get("win_rate") if review.get("available") else None,
    }
    days = [d for d in days if d.get("date") != today]
    days.append(entry)
    days.sort(key=lambda d: d.get("date") or "")
    return days[-90:]


def cfg_top(candidates: list[dict]) -> int:
    return 25


def build_report(snap: dict, cfg: dict, review: dict, history_days: list[dict],
                 market_status: str = "收盘后") -> dict:
    quotes = snap.get("quotes", {})
    sentiment = st.market_sentiment(snap)
    sectors = st.sector_strength(snap, quotes)
    candidates = st.build_candidates(snap, cfg, sectors)

    flow_leaders = sorted(
        [{"code": c["code"], "name": c["name"], "industry": c["industry"],
          "main_net_yi": c["main_net_yi"], "main_pct": c["main_pct"],
          "main_net_5d_yi": c.get("main_net_5d_yi"),
          "main_net_10d_yi": c.get("main_net_10d_yi"),
          "super_net_yi": c["super_net_yi"], "score": c["score"], "grade": c["grade"]}
         for c in candidates if c["main_net_yi"] is not None],
        key=lambda x: x["main_net_yi"], reverse=True)[:15]

    all_lu = [{
        "code": s["code"], "name": s["name"], "industry": s["industry"],
        "price": s["price"], "pct": round(s["pct"] or 0, 2),
        "boards": s["boards"], "break_count": s["break_count"],
        "turnover": round(s["turnover"] or 0, 2),
        "seal_ratio": round((s["seal_amount"] or 0) / s["float_mv"] * 100, 2) if s["float_mv"] else None,
        "float_mv_yi": st.yi(s["float_mv"]), "amount_yi": st.yi(s["amount"]),
        "first_seal": st.fmt_time(s["first_seal"]),
    } for s in snap.get("limit_up", [])]

    return {
        "meta": {
            "date": snap.get("date"),
            "as_of": snap.get("as_of"),
            "source": snap.get("source"),
            "source_time": snap.get("date"),
            "is_demo": bool(snap.get("is_demo")),
            "demo_note": snap.get("demo_note"),
            "is_stale": bool(snap.get("is_stale")),
            "stale_note": snap.get("stale_note"),
            "quality": snap.get("quality", "unknown"),
            "degraded": bool(snap.get("degraded")),
            "source_health": snap.get("source_health") or {},
            "market_status": market_status,
            "strategy": cfg.get("strategy_name"),
            "version": cfg.get("version"),
            "generated_at": ds.now_cn().strftime("%Y-%m-%d %H:%M:%S %z"),
            "disclaimer": DISCLAIMER,
            "data_caveat": (
                "主力资金（大单+超大单）为按成交单笔金额推断的统计量，非交易所席位数据；"
                "盘中运行时为实时快照，收盘后运行为当日收盘数据。"
                + (" 本期已启用备用数据源，资金/封板字段口径可能与历史不同，跨日分数不可直接比较，"
                   "详见「数据源与容灾」。" if snap.get("degraded") else "")
                + (" 当前接口全部不可用，本页为历史快照，数据已过期。" if snap.get("is_stale") else "")
            ),
        },
        "sentiment": sentiment,
        "sectors": sectors,
        "candidates": candidates,
        "all_limit_up": all_lu,
        "flow_leaders": flow_leaders,
        "review": review,
        "history_days": history_days,
        "config": {
            "weights": cfg.get("weights"),
            "factor_labels": cfg.get("factor_labels"),
            "grades": cfg.get("grades"),
            "top_n": cfg.get("top_n"),
        },
    }


def write_outputs(report: dict, snap: dict, cfg: dict, root: str) -> list[str]:
    docs = os.path.join(root, "docs", "data")
    daily = os.path.join(docs, "daily")
    raw_dir = os.path.join(root, "data", "snapshots")
    os.makedirs(daily, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)
    date = report["meta"]["date"] or ds.date_iso()

    written: list[str] = []
    # 完整报告
    _write_json(os.path.join(docs, "latest.json"), report)
    _write_js(os.path.join(docs, "latest.js"), "__DASHBOARD_DATA__", report)
    _write_json(os.path.join(daily, f"{date}.json"), report)
    written += [f"docs/data/latest.json", f"docs/data/latest.js", f"docs/data/daily/{date}.json"]

    # 历史索引（同时以 .js 形式供 file:// 读取）
    hist = {"days": report["history_days"], "updated_at": report["meta"]["generated_at"]}
    _write_json(os.path.join(docs, "history.json"), hist)
    _write_js(os.path.join(docs, "history.js"), "__HISTORY__", hist)
    written += ["docs/data/history.json", "docs/data/history.js"]

    # 复盘独立文件
    _write_json(os.path.join(docs, "review.json"), report["review"])
    written.append("docs/data/review.json")

    # 原始采集快照（供下一交易日复盘读取候选代码）
    raw = dict(snap)
    raw["candidates"] = [
        {k: c[k] for k in ("code", "name", "secid", "grade", "score", "boards", "industry")}
        for c in report["candidates"][:cfg.get("top_n", 25)]
    ]
    _write_json(os.path.join(raw_dir, f"{date}.json"), raw)
    written.append(f"data/snapshots/{date}.json")

    # 前端配置同步
    _write_json(os.path.join(docs, "config.json"), cfg)
    written.append("docs/data/config.json")
    return written
