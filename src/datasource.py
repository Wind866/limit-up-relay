"""数据层统一入口：多源采集 → 归一化快照。

对外 API 与旧版保持一致（fetch_pool / fetch_quotes / fetch_flow_history /
collect / load_demo），因此 strategy、report、feishu 无需改动；真正的多源
容灾逻辑在 ``src/sources.py``。

容灾优先级（详见 sources.py 模块文档）::

    涨停池   东方财富(多域名) → 同花顺 → 新浪全市场榜单
    行情资金 东方财富(多域名) → 腾讯证券 → 新浪榜单复用 → 新浪逐票
    逐日资金 东方财富(多域名，可选增强，失败不影响主流程)

任一环节降级都会在 ``snapshot.source_health`` 留痕，并传递到看板与飞书卡片。
所有来源都失效时抛 DataSourceError，由 run_daily 决定回退到最近真实快照
或内置演示样本，绝不伪造行情。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any

from . import sources as src

# ---- 兼容旧调用：直接透传常用工具 -----------------------------------------
DataSourceError = src.SourceFailure
now_cn = src.now_cn
date_compact = src.date_compact
date_iso = src.date_iso
CN_TZ = src.CN_TZ
# 独立于池数据源的「真实交易日」信号，供节假日守卫兜底
market_trading_date = src.trading_date_from_tencent

FLOW_FIELDS = src.FLOW_FIELDS
QUOTE_FIELDS = src.QUOTE_FIELDS


def urllib_quote(text: str) -> str:
    """兼容旧签名的冒号转义（新实现用 urllib.parse.quote）。"""
    import urllib.parse
    return urllib.parse.quote(text, safe="")


def load_config(root: str | None = None) -> dict:
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


# ---- 对外的单功能接口 ------------------------------------------------------

def fetch_pool(kind: str, day: dt.date | None = None,
               page_size: int = 200, cfg: dict | None = None) -> dict:
    """拉取涨停(ZT)/炸板(ZB)/跌停(DT)池；自动跨源降级。"""
    day = day or now_cn().date()
    config = cfg or load_config()
    src.configure(config)
    try:
        value, _ = src.fetch_pool(kind, day, config)
        return value
    except src.AllSourcesFailed as exc:
        raise DataSourceError(str(exc)) from exc


def fetch_quotes(secids: list[str], with_flow: bool = True,
                 batch: int = 45, cfg: dict | None = None) -> dict[str, dict]:
    """批量取行情/资金；每批独立降级，返回 {code: {...}}。"""
    if not secids:
        return {}
    config = cfg or load_config()
    src.configure(config)
    try:
        value, _ = src.fetch_quotes(secids, now_cn().date(),
                                    config, with_flow, batch)
        return value
    except src.AllSourcesFailed as exc:
        raise DataSourceError(str(exc)) from exc


def fetch_flow_history(secid: str, limit: int = 15,
                       retries: int = 1) -> list[dict]:
    """个股逐日资金流（可选增强）。多域名失败返回空列表而非抛错。"""
    return src.fetch_flow_history(secid, load_config(), limit)


# ---- 用行情回填备用源缺失的量价字段 ---------------------------------------

def _enrich_pool(items: list[dict], quotes: dict[str, dict]) -> int:
    """备用池缺成交额/换手/市值时，用其他供应商的真实行情回填。

    同花顺源的成交额是「流通市值×换手率」推导值，若拿到真实成交额则覆盖
    并清除 amount_estimated 标记。只回填值为 None 或标记为推导的字段，
    不覆盖主源已有真实值。
    """
    filled = 0
    for item in items:
        q = quotes.get(item["code"])
        if not q:
            continue
        for key in ("amount", "float_mv", "total_mv", "turnover", "price", "pct"):
            if (item.get(key) is None or (key == "amount" and item.get("amount_estimated"))) \
                    and q.get(key) is not None:
                item[key] = q[key]
                filled += 1
        if item.get("amount_estimated") and q.get("amount") is not None:
            item["amount_estimated"] = False
        # 同花顺/新浪池没有行业，东财 clist 通道带 f100 时可回填，恢复板块共振分析
        if item.get("industry") in (None, "", "未分类") and q.get("industry"):
            item["industry"] = q["industry"]
            filled += 1
    return filled


# ---- 全量采集 --------------------------------------------------------------

def collect(day: dt.date | None = None, flow_top: int = 0,
            extra_secids: list[str] | None = None,
            cfg: dict | None = None) -> dict:
    """一次性采集当日全量数据，并在快照里写入数据源健康报告。"""
    day = day or now_cn().date()
    cfg = cfg if cfg is not None else load_config()
    src.configure(cfg)
    src.HEALTH.reset()
    notes: list[str] = []

    outcomes: dict[str, src.Outcome] = {}
    pools: dict[str, dict] = {}
    for kind in ("ZT", "ZB", "DT"):
        try:
            value, outcome = src.fetch_pool(kind, day, cfg)
            pools[kind] = value
            outcomes[kind] = outcome
        except src.AllSourcesFailed as exc:
            if kind == "ZT":
                raise DataSourceError(str(exc)) from exc
            # 炸板/跌停池是情绪指标的补充，全挂时记 0 并明确标注，不阻断主流程
            pools[kind] = {"qdate": date_iso(day), "total": 0, "items": []}
            notes.append(f"{kind} 池全部数据源失效，情绪指标按 0 计（已在看板标注）")

    zt, zb, dt_pool = pools["ZT"], pools["ZB"], pools["DT"]

    # 交叉校验：主源为东财时额外比对同花顺家数/成分；主源本身是同花顺则跳过
    zt_provider = outcomes.get("ZT").provider if outcomes.get("ZT") else ""
    cross = (src.cross_check_limit_up(day, zt["items"], cfg)
             if zt_provider != "ths" else
             {"available": False, "reason": "涨停池主源即同花顺，无需自我校验"})

    secids = [x["secid"] for x in zt["items"]]
    if extra_secids:
        secids += [s for s in extra_secids if s not in secids]
    try:
        quotes, qmeta = src.fetch_quotes(secids, day, cfg) if secids else ({}, {
            "providers": {}, "coverage": "0/0", "has_fund": False,
            "fund_coverage": 0, "fund_source": "none",
            "fund_comparable": False, "fund_backfilled": 0, "attempts": []})
    except src.AllSourcesFailed as exc:
        quotes, qmeta = {}, {
            "providers": {}, "coverage": f"0/{len(secids)}", "has_fund": False,
            "fund_coverage": 0, "fund_source": "none",
            "fund_comparable": False, "fund_backfilled": 0, "attempts": []}
        notes.append(f"行情全部数据源失效：{exc}")

    for kind in ("ZT", "ZB", "DT"):
        _enrich_pool(pools[kind]["items"], quotes)

    # 逐日资金明细：优先复用「东财资金流日线回补」过程中已经取到的日线，
    # 避免对同一只票再发一次请求（限流窗口里每省一次请求都很值）。
    histories: dict[str, list[dict]] = dict(qmeta.get("flow_details") or {})
    prefetched = set(histories)
    for item in zt["items"][:flow_top]:
        if item["code"] in prefetched:
            continue
        rows = src.fetch_flow_history(item["secid"], cfg)
        if rows:
            histories[item["code"]] = rows
        time.sleep(0.08)

    quality = src.quality_of(outcomes, qmeta)
    notes.extend(src.build_notes(outcomes, qmeta, cross, quality))

    groups: dict[str, dict] = {}
    for kind, o in outcomes.items():
        groups[f"pool:{kind}"] = {
            "provider": o.provider, "label": o.label, "quality": o.quality,
            "endpoint": o.endpoint,
            "count": len(pools[kind]["items"]),
            "fallback_used": any(not a["ok"] for a in o.attempts),
        }
    for kind in ("ZT", "ZB", "DT"):
        if f"pool:{kind}" not in groups:
            groups[f"pool:{kind}"] = {
                "provider": "none", "label": "全部失效", "quality": "none",
                "endpoint": "-", "count": 0, "fallback_used": True}
    groups["quotes"] = {
        "label": "行情与资金",
        "quality": ("full" if qmeta.get("fund_comparable") else
                    "partial" if qmeta.get("has_fund") else "minimal"),
        "endpoint": "、".join(qmeta["providers"].keys()) or "-",
        "providers": qmeta["providers"], "coverage": qmeta["coverage"],
        "has_fund": qmeta["has_fund"], "fund_coverage": qmeta["fund_coverage"],
        "fund_source": qmeta.get("fund_source", "none"),
        "fund_comparable": qmeta.get("fund_comparable", False),
        "fund_backfilled": qmeta.get("fund_backfilled", 0),
        "failed_batches": qmeta.get("failed_batches", 0),
    }
    groups["flow_history"] = {
        "available": len(histories), "attempted": min(flow_top, len(zt["items"])),
    }

    health = src.HEALTH.to_dict(groups, quality, notes, cross)
    source_desc = src.describe_sources(outcomes, qmeta)

    return {
        "date": zt["qdate"],
        "as_of": now_cn().strftime("%Y-%m-%d %H:%M:%S %z"),
        "source": source_desc,
        "is_demo": False,
        "quality": quality,
        "degraded": quality != "full",
        "source_health": health,
        "limit_up": zt["items"],
        "broken": zb["items"],
        "limit_down": dt_pool["items"],
        "quotes": quotes,
        "flow_history": histories,
        "counts": {
            "limit_up": zt["total"],
            "broken": zb["total"],
            "limit_down": dt_pool["total"],
        },
    }


def load_demo(path: str) -> dict:
    """读取随仓库附带的真实历史快照样本，强制标记为演示数据。"""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["is_demo"] = True
    data["demo_note"] = (
        f"演示用途：本页为 {data.get('date', '历史')} 的真实行情快照样本，"
        "不是当前交易日数据，不可用于实盘决策。"
    )
    return data


def load_recent_snapshot(snap_dir: str, before: str) -> dict | None:
    """全部数据源失效时，回退到最近一次真实快照（显式标注为陈旧数据）。"""
    try:
        # 含当天：15:37 全挂时，13:07 那次成功快照正是最佳回退目标
        files = sorted(f for f in os.listdir(snap_dir)
                       if f.endswith(".json") and f[:-5] <= before)
    except OSError:
        return None
    for name in reversed(files[-5:]):
        try:
            with open(os.path.join(snap_dir, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("limit_up"):
                data["is_stale"] = True
                data["stale_note"] = (
                    f"全部行情接口不可用，本页回退到 {data.get('date')} 的真实快照（非最新），"
                    "不可作为当前行情使用。待接口恢复后重新运行即可刷新。"
                )
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return None
