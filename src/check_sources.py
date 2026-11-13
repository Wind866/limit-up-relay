"""数据源健康自检：逐个探测所有已接入接口，确认哪个源挂了、该切到哪一层。

用法：
    python src/check_sources.py                 # 人类可读表格
    python src/check_sources.py --markdown     # 适合写入 GitHub Step Summary
    python src/check_sources.py --json         # 机器可读 JSON
    python src/check_sources.py --json --out docs/data/sources.json

退出码：全部接口失效 → 1（真故障）；部分失效 → 0（容灾链仍可工作）。
自检只读接口，不写 latest.json、不推飞书、不产生任何交易信号。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import sources as s  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def _probes(day):
    codes = ["002148", "600715"]
    secids = ["0.002148", "1.600715"]
    return [
        # (分组, 标识, 中文名, 接口, 调用)
        ("pool", "eastmoney", "东财涨停池（主）", "push2ex · getTopicZTPool",
         lambda: f"{len(s.em_fetch_pool('ZT', day)['items'])} 只"),
        ("pool", "eastmoney", "东财炸板池（主）", "push2ex · getTopicZBPool",
         lambda: f"{len(s.em_fetch_pool('ZB', day)['items'])} 只"),
        ("pool", "eastmoney", "东财跌停池（主）", "push2ex · getTopicDTPool",
         lambda: f"{len(s.em_fetch_pool('DT', day)['items'])} 只"),
        ("pool", "ths", "同花顺涨停池（备 1）", "data.10jqka.com.cn · limit_up_pool",
         lambda: f"{len(s.ths_fetch_limit_up(day)['items'])} 只"),
        ("pool", "ths", "同花顺连板高度（增强）", "data.10jqka.com.cn · continuous_limit_up",
         lambda: f"{len(s.ths_continuous_boards(day))} 只连板股"),
        ("pool", "sina", "新浪全市场涨幅榜（备 2）", "Market_Center.getHQNodeData",
         lambda: f"{len(s.sina_rank(False, day, max_pages=1, page_size=20))} 行"),
        ("pool", "sina", "新浪全市场跌幅榜（备 2）", "Market_Center.getHQNodeData",
         lambda: f"{len(s.sina_rank(True, day, max_pages=1, page_size=20))} 行"),
        ("quotes", "eastmoney", "东财批量行情+资金（主）", "push2 · ulist.np",
         lambda: f"{len(s.em_fetch_quotes(secids))} 只"),
        ("quotes", "eastmoney_clist", "东财榜单通道（备 1，同口径）", "push2 · clist",
         lambda: f"{len(s.em_fetch_quotes_clist(secids))} 只"),
        ("quotes", "tencent", "腾讯证券行情（备 2）", "qt.gtimg.cn",
         lambda: f"{len(s.tencent_fetch_quotes(codes))} 只"),
        ("quotes", "sina", "新浪逐票行情（备 3）", "hq.sinajs.cn",
         lambda: f"{len(s.sina_fetch_quotes(codes))} 只"),
        ("flow", "eastmoney", "东财逐日资金流（多周期）", "push2his · fflow/daykline",
         lambda: f"{len(s.em_fetch_flow_history('0.002148', 5))} 个交易日"),
        ("flow", "sina", "新浪批量资金流（口径不同）", "MoneyFlow.ssi_ssfx_flzjtj",
         lambda: f"{len(s.sina_fetch_flow(codes, batch=10))} 只"),
    ]


def run(day) -> dict:
    results = []
    for group, provider, label, endpoint, fn in _probes(day):
        t0 = time.perf_counter()
        try:
            detail = str(fn())
            ok = True
        except Exception as exc:  # noqa: BLE001 - 自检要如实记录每种失败
            detail = f"{type(exc).__name__}: {str(exc)[:110]}"
            ok = False
        results.append({
            "group": group, "provider": provider, "label": label,
            "endpoint": endpoint, "ok": ok,
            "ms": int((time.perf_counter() - t0) * 1000), "detail": detail,
        })
    ok_count = sum(1 for r in results if r["ok"])
    by_group: dict[str, dict] = {}
    for g in ("pool", "quotes", "flow"):
        rows = [r for r in results if r["group"] == g]
        by_group[g] = {
            "ok": sum(1 for r in rows if r["ok"]), "total": len(rows),
            "healthy": any(r["ok"] for r in rows),
        }
    return {
        "checked_at": s.now_cn().strftime("%Y-%m-%d %H:%M:%S %z"),
        "date": s.date_iso(day),
        "ok": ok_count, "total": len(results),
        "all_healthy": ok_count == len(results),
        "groups": by_group,
        "results": results,
    }


def text_report(d: dict) -> str:
    lines = [f"数据源健康自检 · {d['checked_at']}（北京时间）",
             "=" * 78,
             f"{'状态':<6}{'接口':<30}{'来源/域名':<34}{'耗时':>7}  摘要"]
    lines.append("-" * 78)
    for r in d["results"]:
        flag = "OK" if r["ok"] else "FAIL"
        lines.append(f"{flag:<6}{r['label']:<30}{r['endpoint'][:33]:<34}"
                     f"{str(r['ms']) + 'ms':>7}  {r['detail'][:46]}")
    lines.append("-" * 78)
    for g, cn in (("pool", "池数据"), ("quotes", "行情数据"), ("flow", "资金数据")):
        v = d["groups"][g]
        lines.append(f"  {cn}: {v['ok']}/{v['total']} 可用 → "
                     + ("正常" if v["healthy"] else "该层全部失效"))
    lines.append(f"合计 {d['ok']}/{d['total']} 个接口可用；"
                 + ("全部正常" if d["all_healthy"] else "已有失效接口，容灾链会自动降级"))
    return "\n".join(lines)


def markdown_report(d: dict) -> str:
    lines = [
        f"## 数据源健康自检 · {d['date']}",
        "",
        f"检查时点：{d['checked_at']}（北京时间）｜可用 **{d['ok']}/{d['total']}** 个接口",
        "",
        "| 状态 | 接口 | 来源 / 域名 | 耗时 | 结果 |",
        "|---|---|---|---:|---|",
    ]
    for r in d["results"]:
        lines.append(f"| {'✅' if r['ok'] else '❌'} | {r['label']} | `{r['endpoint']}` | "
                     f"{r['ms']} ms | {r['detail'][:60]} |")
    lines += ["", "> 个别接口失效属正常现象，容灾链会自动切换；"
              "仅当某一层（池 / 行情 / 资金）全部失效才需要人工处理。", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="涨停接力策略 · 数据源健康自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--markdown", action="store_true", help="输出 Markdown（GitHub Summary）")
    ap.add_argument("--out", help="把 JSON 结果写入指定文件")
    ap.add_argument("--date", help="目标日期 YYYY-MM-DD，默认今天（北京时间）")
    args = ap.parse_args()

    day = s.dt.date.fromisoformat(args.date) if args.date else s.now_cn().date()
    try:
        result = run(day)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)

    if args.json and not args.markdown:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(markdown_report(result))
    else:
        print(text_report(result))
        if args.out:
            print(f"JSON 已写入 {args.out}")

    return 0 if any(v["healthy"] for v in result["groups"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
