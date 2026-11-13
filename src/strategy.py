"""涨停次日接力 · 多因子评分模型。

模型逻辑（每个因子先归一化到 0-100，再按 config.weights 加权，最后扣风险分）

  1. 封板强度 seal      封单额/流通市值、首次封板时间、炸板次数
  2. 连板高度 board     低位 1-2 板赔率优于 4 板以上高位股（leader-game：高位追涨赔率最差）
  3. 主力资金 fund      当日主力净额、超大单强度、近 5 日连续性（fund-flow：不孤立看单日）
  4. 量能换手 volume    换手过低承接不足，过高说明分歧巨大
  5. 板块效应 sector    同行业涨停家数 + 板块最高板（主流题材优于孤立脉冲）
  6. 市值流动性 liq     流通市值适中、成交额充足，避开流动性陷阱
  7. 涨停基因 momentum  近期涨停次数（活跃度），过热则回落

重要：这是「观察池排序」，不是收益预测。所有权重、阈值集中在 config.json，
看板里可以实时调整权重并重算排名，便于做敏感性检验；历史表现由 review 模块
基于每日快照真实计算，不做事后拟合。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _piecewise(x: float | None, points: list[tuple[float, float]]) -> float:
    """分段线性映射；x 为 None 时返回中性 50，避免用 0 冒充真实值。"""
    if x is None:
        return 50.0
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _minutes(hhmmss: Any) -> float | None:
    """9:25 记为 0 分钟，用于衡量封板早晚。"""
    try:
        v = int(hhmmss)
        hh, mm = v // 10000, (v // 100) % 100
        return (hh * 60 + mm) - (9 * 60 + 25)
    except (TypeError, ValueError):
        return None


def fmt_time(hhmmss: Any) -> str:
    try:
        v = int(hhmmss)
        return f"{v // 10000:02d}:{(v // 100) % 100:02d}:{v % 100:02d}"
    except (TypeError, ValueError):
        return "--"


def yi(value: float | None) -> float | None:
    return None if value is None else round(value / 1e8, 2)


# ---------------------------------------------------------------------------
# 市场情绪与板块
# ---------------------------------------------------------------------------

def market_sentiment(snap: dict) -> dict:
    """涨停结构判断：数量、炸板率、连板梯队完整度、跌停数。"""
    lu = snap.get("limit_up", [])
    counts = snap.get("counts", {})
    n_zt = int(counts.get("limit_up") or len(lu))
    n_zb = int(counts.get("broken") or len(snap.get("broken", [])))
    n_dt = int(counts.get("limit_down") or len(snap.get("limit_down", [])))
    denom = n_zt + n_zb
    break_rate = round(n_zb / denom * 100, 1) if denom else None

    ladder: dict[str, int] = defaultdict(int)
    for s in lu:
        b = int(s.get("boards") or 1)
        key = "1板" if b <= 1 else "2板" if b == 2 else "3板" if b == 3 else "4板+"
        ladder[key] += 1
    boards = [int(s.get("boards") or 1) for s in lu]
    max_board = max(boards) if boards else 0
    second = max([b for b in boards if b < max_board], default=0)
    gap = max_board - second >= 2 and max_board >= 4

    score = 0
    score += 2 if n_zt >= 60 else 1 if n_zt >= 40 else -1 if n_zt < 20 else 0
    if break_rate is not None:
        score += 2 if break_rate < 20 else 1 if break_rate < 35 else -2 if break_rate > 45 else 0
    score += 2 if max_board >= 5 else 1 if max_board >= 3 else -1 if max_board <= 1 else 0
    score += -2 if n_dt > 20 else -1 if n_dt > 8 else 0
    if gap:
        score -= 1

    if score >= 5:
        level, note = "亢奋", "情绪高位，注意一致性过强带来的兑现风险"
    elif score >= 3:
        level, note = "活跃", "赚钱效应扩散，接力环境相对友好"
    elif score >= 1:
        level, note = "修复", "结构性机会为主，优先跟随主流题材"
    elif score >= -1:
        level, note = "分歧", "高位波动加大，控制参与度、只看最强分支"
    else:
        level, note = "退潮", "炸板与跌停增多，接力赔率差，建议以观察为主"

    return {
        "limit_up": n_zt,
        "broken": n_zb,
        "limit_down": n_dt,
        "break_rate": break_rate,
        "max_board": max_board,
        "ladder": dict(ladder),
        "ladder_gap": gap,
        "score": score,
        "level": level,
        "note": note,
        "basis": "涨停/炸板/跌停家数、炸板率、最高连板与梯队断层（数据来源：东方财富涨停池，时点见页首）",
    }


def sector_strength(snap: dict, quotes: dict) -> list[dict]:
    """行业维度：涨停家数、最高板、板块主力净额合计、领涨代码。"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for s in snap.get("limit_up", []):
        grouped[s.get("industry") or "未分类"].append(s)

    out = []
    for name, members in grouped.items():
        codes = [m["code"] for m in members]
        main = sum((quotes.get(c, {}).get("main_net") or 0) for c in codes)
        leader = max(members, key=lambda m: (int(m.get("boards") or 1),
                                             m.get("seal_amount") or 0))
        out.append({
            "industry": name,
            "count": len(members),
            "max_board": max((int(m.get("boards") or 1) for m in members), default=0),
            "main_net": round(main, 2),
            "main_net_yi": yi(main),
            "leader": leader["name"],
            "leader_code": leader["code"],
            "members": codes,
        })
    out.sort(key=lambda x: (x["count"], x["max_board"], x["main_net"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 单股评分
# ---------------------------------------------------------------------------

def _eligible(stock: dict, cfg: dict) -> tuple[bool, str]:
    uni = cfg.get("universe", {})
    name = (stock.get("name") or "").upper()
    code = stock.get("code") or ""
    if uni.get("exclude_st", True) and ("ST" in name or "退" in name):
        return False, "ST/退市整理期，风险剔除"
    if uni.get("exclude_bj", True) and code.startswith(("4", "8", "92")):
        return False, "北交所/三板，涨跌幅机制不同"
    if (stock.get("amount") or 0) < uni.get("min_amount_yuan", 0):
        return False, "成交额不足，流动性剔除"
    return True, ""


def _trade_plan(grade: str, stock: dict, cfg: dict) -> dict:
    """条件式观察要点，不给硬性买卖指令。"""
    cap = {"A": "观察仓参考上限 10%", "B": "观察仓参考上限 5%", "C": "仅观察，不设仓位", "D": "不纳入"}[grade]
    pct = stock.get("pct") or 10
    board_type = "20cm" if pct >= 15 else "30cm" if pct >= 25 else "10cm"
    return {
        "auction": "竞价高开 2%~6%、竞价成交额 > 前日成交额 3% 且未出现巨额撤单时纳入观察；高开 >8% 或低开 >2% 视为分歧信号",
        "intraday": "回踩分时均价不破、二次封板量能小于首封，属承接良好；反复开板且放量则视为分歧加剧",
        "risk": f"跌破前一日涨停价 {stock.get('price')} 元或板块最高板炸板，视为接力逻辑失效",
        "position": cap,
        "board_type": board_type,
        "conditions": [
            "次日大盘/题材未出现系统性退潮",
            "所属板块仍有涨停梯队、无明显断层",
            "个股竞价量能与高开幅度匹配，非一字板无量空涨",
        ],
    }


def score_stock(stock: dict, snap: dict, sectors: list[dict], cfg: dict) -> dict | None:
    ok, reason = _eligible(stock, cfg)
    if not ok:
        return None

    code = stock["code"]
    quotes = snap.get("quotes", {})
    q = quotes.get(code, {})
    rules = cfg.get("risk_rules", {})
    hist = (snap.get("flow_history") or {}).get(code) or []
    has_hist = bool(hist)

    fmv = stock.get("float_mv") or 0
    amount = stock.get("amount") or 0
    seal_ratio = (stock.get("seal_amount") or 0) / fmv * 100 if fmv else None
    mv_yi = fmv / 1e8 if fmv else None
    amount_yi = amount / 1e8 if amount else None
    turn = stock.get("turnover")
    boards = int(stock.get("boards") or 1)
    breaks = int(stock.get("break_count") or 0)
    t_first = _minutes(stock.get("first_seal"))

    # 1) 封板强度：封单占比 50% + 封板时间 28% + 炸板次数 22%
    s_ratio = _piecewise(seal_ratio, [(0, 0), (0.3, 20), (1, 45), (3, 75), (8, 100)])
    s_time = _piecewise(t_first, [(0, 100), (30, 92), (90, 70), (180, 50), (280, 25), (330, 5)])
    s_break = _piecewise(breaks, [(0, 100), (1, 78), (2, 58), (3, 38), (4, 22), (5, 8)])
    f_seal = 0.50 * s_ratio + 0.28 * s_time + 0.22 * s_break

    # 2) 连板高度：2 板最优，4 板以上赔率显著下降
    f_board = {1: 86, 2: 100, 3: 72, 4: 46, 5: 28}.get(boards, 15 if boards >= 6 else 86)

    # 3) 主力资金：当日净额 45% + 超大单 30% + 近 5 日连续性 25%
    main_net = q.get("main_net")
    main_ratio = (main_net / fmv * 100) if (main_net is not None and fmv) else None
    s_main = _piecewise(main_ratio, [(-2, 0), (0, 35), (0.5, 55), (1.5, 75), (4, 100)])
    s_super = _piecewise(q.get("super_pct"), [(-10, 10), (0, 45), (5, 70), (15, 100)])
    # 连续性：用 5 日 / 10 日主力净额判断趋势性布局 vs 单日脉冲（fund-flow：不孤立看单日）
    net5, net10 = q.get("main_net_5d"), q.get("main_net_10d")
    if net5 is not None or net10 is not None:
        r5 = (net5 or 0) / fmv * 100 if fmv else 0
        r10 = (net10 or 0) / fmv * 100 if fmv else 0
        s_5 = _piecewise(r5, [(-2, 10), (0, 40), (1, 65), (3, 85), (8, 100)])
        s_10 = _piecewise(r10, [(-3, 10), (0, 40), (2, 70), (6, 95), (15, 100)])
        agree = 100 if (net5 or 0) > 0 and (net10 or 0) > 0 else \
                60 if (net5 or 0) > 0 else 25
        s_cont = 0.5 * s_5 + 0.3 * s_10 + 0.2 * agree
        trend = "连续净流入（偏趋势）" if (net5 or 0) > 0 and (net10 or 0) > 0 else \
                "5日转正、10日仍流出（可能是新启动）" if (net5 or 0) > 0 else \
                "多周期净流出（资金未共振）"
        cont_desc = f"5日主力 {yi(net5)} 亿 / 10日 {yi(net10)} 亿 · {trend}"
    else:
        s_cont, cont_desc = 50.0, "多周期资金数据未取到，连续性按中性 50 分计"
    f_fund = 0.45 * s_main + 0.30 * s_super + 0.25 * s_cont

    # 4) 换手：6%~18% 为观察区，>35% 视为分歧过大
    f_volume = _piecewise(turn, [(0, 25), (2, 45), (5, 75), (8, 95), (15, 100),
                                 (22, 80), (30, 50), (40, 20), (60, 5)])

    # 5) 板块效应
    industry = stock.get("industry") or "未分类"
    sec = next((s for s in sectors if s["industry"] == industry), None)
    n_sector = sec["count"] if sec else 1
    h_sector = sec["max_board"] if sec else boards
    s_count = _piecewise(n_sector, [(1, 30), (2, 50), (3, 68), (5, 85), (8, 100)])
    s_leader = _piecewise(h_sector, [(1, 40), (2, 65), (3, 85), (5, 100)])
    f_sector = 0.6 * s_count + 0.4 * s_leader

    # 6) 市值与流动性
    s_mv = _piecewise(mv_yi, [(0, 10), (20, 45), (30, 75), (50, 95), (120, 100),
                              (200, 90), (400, 60), (800, 25), (3000, 10)])
    s_amt = _piecewise(amount_yi, [(0, 0), (0.5, 25), (1, 50), (3, 80), (8, 100)])
    f_liq = 0.6 * s_mv + 0.4 * s_amt

    # 7) 涨停基因：近期涨停次数，过热回落
    ct = (stock.get("stat") or {}).get("ct")
    try:
        ct = int(ct)
    except (TypeError, ValueError):
        ct = None
    f_mom = _piecewise(ct, [(0, 45), (1, 60), (2, 78), (3, 92), (5, 100), (8, 75)])

    factors = {
        "seal": round(f_seal, 1),
        "board": round(f_board, 1),
        "fund": round(f_fund, 1),
        "volume": round(f_volume, 1),
        "sector": round(f_sector, 1),
        "liquidity": round(f_liq, 1),
        "momentum": round(f_mom, 1),
    }

    # 风险扣分（逐项留痕，前端可展开）
    penalties: list[dict] = []
    def add(label: str, point: int, detail: str) -> None:
        penalties.append({"label": label, "point": -abs(point), "detail": detail})

    if boards >= rules.get("high_board_from", 4):
        add("高位连板", rules.get("high_board_penalty", 10), f"{boards} 连板，高位接力赔率显著下降")
    if breaks >= rules.get("break_count_from", 3):
        add("反复炸板", rules.get("break_count_penalty", 8), f"日内炸板 {breaks} 次，封板不牢")
    if turn is not None and turn > rules.get("turnover_high", 35):
        add("换手过热", rules.get("turnover_high_penalty", 8), f"换手 {turn:.1f}%，分歧过大")
    if main_net is not None and main_net < 0:
        add("主力净流出", rules.get("main_outflow_penalty", 12), f"主力净流出 {yi(main_net)} 亿")
    if seal_ratio is not None and seal_ratio < rules.get("seal_ratio_low", 0.3):
        add("封单偏薄", rules.get("seal_ratio_low_penalty", 6), f"封单仅占流通市值 {seal_ratio:.2f}%")
    if mv_yi is not None and (mv_yi < rules.get("mv_low_yi", 20) or mv_yi > rules.get("mv_high_yi", 500)):
        add("市值偏离", rules.get("mv_penalty", 5), f"流通市值 {mv_yi:.1f} 亿，偏离舒适区")
    if stock.get("first_seal") is not None and (stock.get("first_seal") or 0) >= rules.get("late_seal_from", 143000):
        add("尾盘偷袭", rules.get("late_seal_penalty", 6), f"{fmt_time(stock.get('first_seal'))} 才首次封板")
    pct = stock.get("pct") or 10
    if pct >= 15:
        add("20cm/30cm 标的", cfg.get("universe", {}).get("penalty_20cm", 4),
            f"涨停幅度 {pct:.1f}%，波动与回撤大于主板 10cm")

    weights = cfg.get("weights", {})
    wsum = sum(weights.values()) or 1
    base = sum(factors[k] * weights.get(k, 0) for k in factors) / wsum
    total_penalty = sum(p["point"] for p in penalties)
    score = round(_clip(base + total_penalty), 1)

    grades = cfg.get("grades", {"A": 75, "B": 65, "C": 55})
    grade = "A" if score >= grades.get("A", 75) else \
            "B" if score >= grades.get("B", 65) else \
            "C" if score >= grades.get("C", 55) else "D"
    grade_label = {"A": "重点观察", "B": "备选观察", "C": "谨慎观察", "D": "不纳入"}[grade]

    # 生成可读的入选理由（取最强的两个 / 最弱的一个因子）
    labels = cfg.get("factor_labels", {})
    ordered = sorted(factors.items(), key=lambda kv: kv[1], reverse=True)
    reasons = [f"{labels.get(k, k)} {v:.0f} 分" for k, v in ordered[:2]]
    reasons.append(f"需留意 {labels.get(ordered[-1][0], ordered[-1][0])} {ordered[-1][1]:.0f} 分")

    tags = []
    if sec and sec["leader_code"] == code and sec["count"] >= 2:
        tags.append("板块领涨")
    if s_time >= 85:
        tags.append("早盘秒板")
    if breaks == 0:
        tags.append("零炸板")
    if main_net and main_net > 0 and s_cont >= 70:
        tags.append("资金连续")
    if n_sector >= 3:
        tags.append("题材共振")
    if boards >= 4:
        tags.append("高位风险")

    return {
        "code": code,
        "name": stock.get("name"),
        "secid": stock.get("secid"),
        "industry": industry,
        "price": stock.get("price"),
        "pct": round(pct, 2),
        "boards": boards,
        "board_type": "20cm" if pct >= 15 else "10cm",
        "turnover": round(turn, 2) if turn is not None else None,
        "seal_amount_yi": yi(stock.get("seal_amount")),
        "seal_ratio": round(seal_ratio, 2) if seal_ratio is not None else None,
        "float_mv_yi": yi(fmv),
        "amount_yi": yi(amount),
        "first_seal": fmt_time(stock.get("first_seal")),
        "last_seal": fmt_time(stock.get("last_seal")),
        "break_count": breaks,
        "sector_count": n_sector,
        "sector_max_board": h_sector,
        "main_net_yi": yi(main_net) if main_net is not None else None,
        "main_pct": q.get("main_pct"),
        "super_net_yi": yi(q.get("super_net")) if q.get("super_net") is not None else None,
        "big_net_yi": yi(q.get("big_net")) if q.get("big_net") is not None else None,
        "mid_net_yi": yi(q.get("mid_net")) if q.get("mid_net") is not None else None,
        "small_net_yi": yi(q.get("small_net")) if q.get("small_net") is not None else None,
        "main_net_5d_yi": yi(q.get("main_net_5d")) if q.get("main_net_5d") is not None else None,
        "main_net_10d_yi": yi(q.get("main_net_10d")) if q.get("main_net_10d") is not None else None,
        "super_net_5d_yi": yi(q.get("super_net_5d")) if q.get("super_net_5d") is not None else None,
        "big_net_5d_yi": yi(q.get("big_net_5d")) if q.get("big_net_5d") is not None else None,
        "main_pct_5d": q.get("main_pct_5d"),
        "main_pct_10d": q.get("main_pct_10d"),
        "flow_continuity": cont_desc,
        "flow_detail_available": has_hist,
        "flow_history": hist[-15:],
        "factors": factors,
        "penalties": penalties,
        "base_score": round(base, 1),
        "penalty_total": total_penalty,
        "score": score,
        "grade": grade,
        "grade_label": grade_label,
        "reasons": reasons,
        "tags": tags,
        "plan": _trade_plan(grade, stock, cfg),
        "quote_source": "东方财富 ulist.np 实时资金流（当日）",
        "excluded": False,
        "exclude_reason": reason,
    }


def build_candidates(snap: dict, cfg: dict, sectors: list[dict] | None = None) -> list[dict]:
    sectors = sectors if sectors is not None else sector_strength(snap, snap.get("quotes", {}))
    rows = [score_stock(s, snap, sectors, cfg) for s in snap.get("limit_up", [])]
    rows = [r for r in rows if r is not None]
    rows.sort(key=lambda r: (r["score"], r["seal_ratio"] or 0), reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def re_rank(rows: list[dict], weights: dict) -> list[dict]:
    """供前端实时调权重使用：保持与后端同一套公式（基础分 + 风险扣分）。"""
    wsum = sum(weights.values()) or 1
    out = []
    for r in rows:
        base = sum(r["factors"].get(k, 0) * weights.get(k, 0) for k in r["factors"]) / wsum
        s = round(_clip(base + r.get("penalty_total", 0)), 1)
        item = dict(r)
        item["score"] = s
        out.append(item)
    out.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out
