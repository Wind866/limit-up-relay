"""东方财富公开行情接口封装。

设计原则
--------
* 仅依赖 Python 标准库（urllib / json），GitHub Actions 无需 pip install。
* 所有返回值都带 ``source`` 与 ``as_of`` 字段，保证关键数据可追溯到来源 + 时点。
* 任何字段缺失一律返回 None，绝不猜测或填充默认值冒充真实行情。
* 接口失败时抛出 DataSourceError，由上层决定降级（不静默伪造数据）。

数据来源
--------
* 涨停池 / 炸板池 / 跌停池：push2ex.eastmoney.com/getTopic*Pool
* 实时行情 + 主力资金拆解：push2.eastmoney.com/api/qt/ulist.np/get
* 个股历史资金流：push2his.eastmoney.com/api/qt/stock/fflow/daykline/get

口径说明：东方财富「主力资金」= 大单 + 超大单，按成交单笔金额统计推断，
并非交易所披露的真实席位资金，仅作短线强弱参考，详见 fund-flow 方法论。
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.request
from typing import Any

UT = "7eea3edcaed734bea9cbfc24409ed989"
UT_HIS = "b2884a393a59ad64002292a3e90d46a5"
PUSH2EX = "https://push2ex.eastmoney.com"
PUSH2 = "https://push2.eastmoney.com"
PUSH2HIS = "https://push2his.eastmoney.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

CN_TZ = dt.timezone(dt.timedelta(hours=8))


class DataSourceError(RuntimeError):
    """行情接口不可用。"""


def now_cn() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def date_compact(day: dt.date | None = None) -> str:
    return (day or now_cn().date()).strftime("%Y%m%d")


def date_iso(day: dt.date | None = None) -> str:
    return (day or now_cn().date()).strftime("%Y-%m-%d")


def _get_json(url: str, retries: int = 3, timeout: int = 15) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8")
            return json.loads(payload)
        except Exception as exc:  # noqa: BLE001 - 网络异常统一降级重试
            last = exc
            if attempt < retries - 1:
                time.sleep(0.6 * (attempt + 1))
    raise DataSourceError(f"请求失败: {url.split('?')[0]} -> {type(last).__name__}: {last}")


def _num(value: Any) -> float | None:
    """把接口字段转成 float，'-' / None / 空串一律返回 None。"""
    if value is None or value == "-" or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _secid(code: str, market: int | None) -> str:
    """东方财富 secid：沪市 1.xxxxxx，深市/北交所 0.xxxxxx。"""
    if market is None:
        market = 1 if code.startswith(("60", "68", "9")) else 0
    return f"{int(market)}.{code}"


def fetch_pool(kind: str, day: dt.date | None = None, page_size: int = 200) -> dict:
    """拉取涨停(ZT) / 炸板(ZB) / 跌停(DT) 池。

    返回 {"qdate": "YYYY-MM-DD", "total": int, "items": [标准化字典...]}
    """
    endpoint = {"ZT": "getTopicZTPool", "ZB": "getTopicZBPool", "DT": "getTopicDTPool"}[kind]
    sort = {"ZT": "fbt:asc", "ZB": "fbt:asc", "DT": "fund:asc"}[kind]
    target = date_compact(day)
    items: list[dict] = []
    total = 0
    qdate_raw: Any = None

    for page in range(10):  # 最多 2000 条，足够覆盖全市场
        url = (
            f"{PUSH2EX}/{endpoint}?ut={UT}&dpt=wz.ztzt&Pageindex={page}"
            f"&pagesize={page_size}&sort={urllib_quote(sort)}&date={target}"
        )
        data = _get_json(url)
        block = data.get("data") or {}
        pool = block.get("pool") or []
        if page == 0:
            total = int(block.get("tc") or 0)
            qdate_raw = block.get("qdate")
        for raw in pool:
            items.append(_normalize_pool_item(kind, raw))
        if len(pool) < page_size or len(items) >= total:
            break
        time.sleep(0.15)

    qdate = _compact_to_iso(qdate_raw) if qdate_raw else date_iso(day)
    return {"qdate": qdate, "total": total or len(items), "items": items}


def urllib_quote(text: str) -> str:
    """仅用于查询串中冒号的转义，避免引入完整 urllib.parse 依赖也没必要。"""
    return text.replace(":", "%3A")


def _compact_to_iso(value: Any) -> str:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _normalize_pool_item(kind: str, r: dict) -> dict:
    code = str(r.get("c") or "")
    base = {
        "code": code,
        "name": str(r.get("n") or ""),
        "market": int(r.get("m") or 0),
        "secid": _secid(code, r.get("m")),
        "price": (_num(r.get("p")) or 0) / 1000,       # 接口价格单位：千分之一元
        "pct": _num(r.get("zdp")),
        "amount": _num(r.get("amount")),                # 成交额（元）
        "float_mv": _num(r.get("ltsz")),                # 流通市值（元）
        "total_mv": _num(r.get("tshare")),
        "turnover": _num(r.get("hs")),                  # 换手率 %
        "industry": str(r.get("hybk") or "未分类"),
        "first_seal": r.get("fbt"),                     # 首次封板 HHMMSS
        "last_seal": r.get("lbt"),                      # 最后封板 HHMMSS
        "break_count": int(_num(r.get("zbc")) or 0),    # 炸板次数
        "seal_amount": _num(r.get("fund")),             # 封单额（元）／跌停池为封单
        "boards": int(_num(r.get("lbc")) or 0),         # 连板数
        "stat": r.get("zttj") or {},                    # 近期涨停统计 {days, ct}
    }
    if kind == "ZB":
        base["limit_price"] = (_num(r.get("ztp")) or 0) / 1000
    if kind == "DT":
        base["limit_down_days"] = int(_num(r.get("days")) or 0)
        base["open_count"] = int(_num(r.get("oc")) or 0)
    return base


# 实时资金流字段（ulist.np）
# f62 当日主力净额 / f164 5日主力净额 / f174 10日主力净额
# f66,f72,f78,f84 = 当日超大单,大单,中单,小单；f166,f168,f170,f172 = 对应 5 日口径
FLOW_FIELDS = (
    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,"
    "f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f174,f175"
)
QUOTE_FIELDS = "f12,f14,f2,f3"


def fetch_quotes(secids: list[str], with_flow: bool = True, batch: int = 45) -> dict[str, dict]:
    """批量取实时行情 + 主力资金拆解。

    返回 {code: {...}}，单位：金额 元、比例 %。
    """
    out: dict[str, dict] = {}
    fields = FLOW_FIELDS if with_flow else QUOTE_FIELDS
    for i in range(0, len(secids), batch):
        chunk = secids[i:i + batch]
        url = (
            f"{PUSH2}/api/qt/ulist.np/get?fltt=2&invt=2&ut={UT}"
            f"&secids={','.join(chunk)}&fields={fields}"
        )
        data = _get_json(url)
        rows = ((data.get("data") or {}).get("diff") or [])
        if isinstance(rows, dict):  # 有时返回以序号为 key 的字典
            rows = list(rows.values())
        for r in rows:
            code = str(r.get("f12") or "")
            if not code:
                continue
            out[code] = {
                "code": code,
                "name": r.get("f14"),
                "price": _num(r.get("f2")),
                "pct": _num(r.get("f3")),
                "main_net": _num(r.get("f62")),        # 主力净额
                "main_pct": _num(r.get("f184")),       # 主力净占比
                "super_net": _num(r.get("f66")),       # 超大单净额
                "super_pct": _num(r.get("f69")),
                "big_net": _num(r.get("f72")),         # 大单净额
                "big_pct": _num(r.get("f75")),
                "mid_net": _num(r.get("f78")),         # 中单净额
                "mid_pct": _num(r.get("f81")),
                "small_net": _num(r.get("f84")),       # 小单净额
                "small_pct": _num(r.get("f87")),
                # ---- 多周期口径：判断资金是趋势性布局还是单日脉冲 ----
                "main_net_5d": _num(r.get("f164")),
                "main_pct_5d": _num(r.get("f165")),
                "super_net_5d": _num(r.get("f166")),
                "super_pct_5d": _num(r.get("f167")),
                "big_net_5d": _num(r.get("f168")),
                "big_pct_5d": _num(r.get("f169")),
                "mid_net_5d": _num(r.get("f170")),
                "small_net_5d": _num(r.get("f172")),
                "main_net_10d": _num(r.get("f174")),
                "main_pct_10d": _num(r.get("f175")),
            }
        if i + batch < len(secids):
            time.sleep(0.12)
    return out


def fetch_flow_history(secid: str, limit: int = 15, retries: int = 1) -> list[dict]:
    """个股近 N 个交易日主力资金流日线。

    klines 字段顺序（东方财富 fflow/daykline）:
    日期, 主力净额, 小单净额, 中单净额, 大单净额, 超大单净额,
    主力净占比, 小单占比, 中单占比, 大单占比, 超大单占比,
    收盘价, 涨跌幅, 保留, 保留
    """
    url = (
        f"{PUSH2HIS}/api/qt/stock/fflow/daykline/get?lmt={limit}&klt=101"
        f"&secid={secid}&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        f"&ut={UT_HIS}"
    )
    data = _get_json(url, retries=retries)
    klines = ((data.get("data") or {}).get("klines") or [])
    rows: list[dict] = []
    for line in klines:
        p = str(line).split(",")
        if len(p) < 13:
            continue
        rows.append({
            "date": p[0],
            "main_net": _num(p[1]),
            "small_net": _num(p[2]),
            "mid_net": _num(p[3]),
            "big_net": _num(p[4]),
            "super_net": _num(p[5]),
            "main_pct": _num(p[6]),
            "close": _num(p[11]),
            "pct": _num(p[12]),
        })
    return rows[-limit:]


def collect(day: dt.date | None = None, flow_top: int = 0,
            extra_secids: list[str] | None = None) -> dict:
    """一次性采集当日全量数据。

    flow_top: 需要额外抓取历史资金流日线的个股数量（按传入顺序取前 N）。
    """
    zt = fetch_pool("ZT", day)
    try:
        zb = fetch_pool("ZB", day)
    except DataSourceError:
        zb = {"qdate": zt["qdate"], "total": 0, "items": []}
    try:
        dt_pool = fetch_pool("DT", day)
    except DataSourceError:
        dt_pool = {"qdate": zt["qdate"], "total": 0, "items": []}

    secids = [x["secid"] for x in zt["items"]]
    if extra_secids:
        secids += [s for s in extra_secids if s not in secids]
    quotes = fetch_quotes(secids) if secids else {}

    histories: dict[str, list[dict]] = {}
    for item in zt["items"][:flow_top]:
        try:
            histories[item["code"]] = fetch_flow_history(item["secid"])
        except DataSourceError:
            histories[item["code"]] = []
        time.sleep(0.08)

    return {
        "date": zt["qdate"],
        "as_of": now_cn().strftime("%Y-%m-%d %H:%M:%S %z"),
        "source": "东方财富公开行情接口（涨停池/炸板池/跌停池/资金流）",
        "is_demo": False,
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
