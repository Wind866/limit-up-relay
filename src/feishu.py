"""飞书自定义机器人 · 交互式卡片推送。

支持：
* 加签校验（FEISHU_SECRET，推荐开启）
* 交互按钮：打开看板、跳转资金流明细、标记已阅（回调）
* 未配置 webhook 时静默跳过，不阻断每日数据产出

配置：GitHub Actions Secrets 中设置 FEISHU_WEBHOOK / FEISHU_SECRET / PAGES_URL。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from typing import Any


def gen_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def send(webhook: str, secret: str, card: dict, timeout: int = 12) -> dict:
    payload: dict[str, Any] = {"msg_type": "interactive", "card": card}
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = gen_sign(secret, ts)
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _md(text: str) -> dict:
    return {"tag": "div", "text": {"tag": "lark_md", "content": text}}


def _field(label: str, value: str) -> dict:
    return {"is_short": True, "text": {"tag": "lark_md", "content": f"**{label}**\n{value}"}}


def build_card(report: dict, pages_url: str, repo_url: str = "") -> dict:
    meta = report["meta"]
    s = report["sentiment"]
    cands = report["candidates"]
    top = [c for c in cands if c["grade"] in ("A", "B")][:6]
    date = meta["date"]
    status_label = "盘中快照" if meta.get("market_status") == "盘中" else "收盘定稿"

    template = "red" if s["level"] in ("亢奋", "活跃") else \
               "orange" if s["level"] == "修复" else \
               "green" if s["level"] == "退潮" else "grey"

    lines = [
        f"**交易日 {date}｜情绪：{s['level']}**",
        f"涨停 **{s['limit_up']}** 家 · 炸板 **{s['broken']}** 家 · 跌停 **{s['limit_down']}** 家"
        f" · 炸板率 **{s['break_rate'] if s['break_rate'] is not None else '--'}%** · 最高 **{s['max_board']}** 板",
        f"{s['note']}",
    ]
    if meta.get("is_demo"):
        lines.insert(0, f"> ⚠️ 演示数据：{meta.get('demo_note')}")
    if meta.get("is_stale"):
        lines.insert(0, f"> ⚠️ {meta.get('stale_note')}")
    if meta.get("degraded"):
        qg = (meta.get("source_health") or {}).get("groups", {}).get("quotes", {})
        fund_note = ("资金口径已切换，跨日分数不可直接比较"
                     if not qg.get("fund_comparable", True) else "资金口径与历史一致")
        lines.insert(0, f"> ⚠️ **数据源降级（{meta.get('quality', '--')}）**：主接口不可用，"
                        f"已自动切换备用源；{fund_note}。详情见看板「数据源与容灾」。")
    if meta.get("market_status") == "盘中":
        lines.append("> 当前为盘中实时快照，收盘后 15:30 会再跑一次定稿")

    late = int(meta.get("late_minutes") or 0)
    if late >= 20:
        lines.insert(0, f"> ⚠️ **延迟运行**：比计划时间晚 **{late} 分钟**（GitHub 定时调度延迟），"
                        f"「{meta.get('market_status', '--')}」口径可能已与卡片标题不符，请以看板时间为准。")

    elements: list[dict] = [
        _md("\n".join(lines)),
        {"tag": "hr"},
        {"tag": "div", "fields": [
            _field("A 档重点观察", f"{sum(1 for c in cands if c['grade'] == 'A')} 只"),
            _field("B 档备选", f"{sum(1 for c in cands if c['grade'] == 'B')} 只"),
            _field("候选池最高分", f"{cands[0]['score'] if cands else '--'} 分"),
            _field("主流题材", (report["sectors"][0]["industry"] if report["sectors"] else "--")),
        ]},
        {"tag": "hr"},
    ]

    if top:
        rows = ["**次日接力观察池（按综合评分排序）**", ""]
        for i, c in enumerate(top, 1):
            main = c["main_net_yi"]
            main_txt = f"{main:+.2f}亿" if main is not None else "--"
            d5 = c.get("main_net_5d_yi")
            d5_txt = f"，5日{d5:+.2f}亿" if d5 is not None else ""
            rows.append(
                f"**{i}. {c['name']} `{c['code']}`　{c['score']}分 / {c['grade']}**\n"
                f"{c['boards']}板 · {c['industry']} · 封单{c['seal_ratio']}% · 换手{c['turnover']}% · 主力 {main_txt}{d5_txt}"
                f"　|　{c['reasons'][0]}"
            )
        elements.append(_md("\n".join(rows)))
    else:
        elements.append(_md("今日无 A/B 档候选，接力环境偏弱，建议以观察为主。"))

    flows = report.get("flow_leaders", [])[:3]
    if flows:
        fl = ["**主力资金聚焦**（当日 / 5 日 / 10 日净额，单位亿元）", ""]
        for f in flows:
            d5 = f.get("main_net_5d_yi")
            d10 = f.get("main_net_10d_yi")
            fl.append(
                f"· {f['name']} `{f['code']}`　**{f['main_net_yi']:+.2f}** / "
                f"{d5:+.2f} / {d10:+.2f}　（{f['industry']}，评分 {f['score']}）"
                if d5 is not None and d10 is not None else
                f"· {f['name']} `{f['code']}`　**{f['main_net_yi']:+.2f}** 亿　（{f['industry']}）"
            )
        fl.append("<font color='grey'>多周期同向净流入更接近趋势性布局，单日大额流入可能只是事件性脉冲。</font>")
        elements += [{"tag": "hr"}, _md("\n".join(fl))]

    review = report.get("review", {})
    if review.get("available"):
        o = review["overall"]
        elements += [
            {"tag": "hr"},
            _md(f"**上一交易日观察池复盘**（{review['source_snapshot']} → {date}）\n"
                f"样本 {o['count']} 只 · 次日平均 **{o['avg_pct']:+.2f}%** · 胜率 **{o['win_rate']}%** · 晋级率 **{o['promote_rate']}%**"
                + ("（盘中口径）" if review.get("is_intraday") else "")),
        ]

    elements += [
        {"tag": "hr"},
        _md("**次日观察要点**：竞价高开 2%~6% 且量能匹配、板块梯队完整；"
            "高开 >8% 或低开 >2% 视为分歧。跌破前一日涨停价视为逻辑失效。"),
        _md(f"<font color='grey'>数据来源：{meta['source']}｜时点 {meta['as_of']}（北京时间）"
            f"｜数据质量 {meta.get('quality', '--')}。主力资金为按成交单笔金额推断的统计量，"
            "非席位真实资金。备用源口径可能与主源不同，跨日比较需谨慎。</font>"),
        _md("<font color='grey'>**免责声明**：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。"
            "市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，"
            "必要时咨询持牌专业机构。过往表现不预示未来收益。</font>"),
    ]

    actions: list[dict] = []
    if pages_url:
        actions.append({"tag": "button", "text": {"tag": "plain_text", "content": "打开交互看板"},
                        "type": "primary", "url": pages_url})
        actions.append({"tag": "button", "text": {"tag": "plain_text", "content": "主力资金明细"},
                        "type": "default", "url": pages_url.rstrip("/") + "/#flow"})
        actions.append({"tag": "button", "text": {"tag": "plain_text", "content": "数据源状态"},
                        "type": "default", "url": pages_url.rstrip("/") + "/#about"})
    if repo_url:
        actions.append({"tag": "button", "text": {"tag": "plain_text", "content": "策略与部署说明"},
                        "type": "default", "url": repo_url})
    actions.append({"tag": "button", "text": {"tag": "plain_text", "content": "标记已阅"},
                    "type": "default", "value": {"action": "ack", "date": date}})
    elements.append({"tag": "action", "actions": actions})

    return {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"涨停次日接力观察池 · {date} · {status_label}"},
            "subtitle": {"tag": "plain_text", "content": f"情绪{s['level']} | 共 {len(cands)} 只入池 | {status_label} | 自动运行"},
            "template": template,
        },
        "elements": elements,
    }


def push(report: dict, webhook: str | None = None, secret: str | None = None,
         pages_url: str | None = None, repo_url: str | None = None,
         force: bool = False) -> dict:
    webhook = webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = secret if secret is not None else os.getenv("FEISHU_SECRET", "")
    pages_url = pages_url or os.getenv("PAGES_URL", "")
    repo_url = repo_url or os.getenv("REPO_URL", "")

    # 演示数据无论如何都不混入正式推送，除非显式设置 FORCE_PUSH=1
    if report["meta"].get("is_demo") and os.getenv("FORCE_PUSH") != "1":
        return {"skipped": True, "reason": "演示数据默认不推送，设置 FORCE_PUSH=1 可强制推送"}
    if not webhook:
        return {"skipped": True, "reason": "未配置 FEISHU_WEBHOOK，跳过推送（数据仍已生成）"}
    try:
        card = build_card(report, pages_url, repo_url)
        result = send(webhook, secret, card)
        ok = result.get("StatusCode") == 0 or result.get("code") == 0
        return {"skipped": False, "ok": ok, "response": result}
    except Exception as exc:  # noqa: BLE001
        return {"skipped": False, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
