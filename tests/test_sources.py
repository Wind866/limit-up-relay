"""数据源层的离线回归测试（不发任何网络请求）。

覆盖的都是「错了也不会报错、只会静默给出错数据」的地方：
资金多周期口径、批次失败隔离、涨停幅度判定、成交额缺失的剔除逻辑、
交易日校验的解析。
"""
from __future__ import annotations

import unittest
from unittest import mock

from src import sources


def _flow_rows(n: int, main: float = 1e6) -> list[dict]:
    return [{
        "date": f"2026-11-{i:02d}", "main_net": main,
        "super_net": 4e5, "big_net": 6e5, "mid_net": -2e5, "small_net": 2e5,
        "main_pct": 1.0, "super_pct": 0.4, "big_pct": 0.6,
        "mid_pct": -0.2, "small_pct": 0.2,
        "close": 10.0 + i, "pct": 1.0,
    } for i in range(1, n + 1)]


class TestFflowQuoteFields(unittest.TestCase):
    """东财资金流日线 → ulist 同口径字段。算错会直接污染资金因子。"""

    def test_windows_are_summed_from_tail(self):
        f = sources.fflow_quote_fields(_flow_rows(10))
        self.assertEqual(f["main_net"], 1e6)          # 当日 = 最后一根
        self.assertEqual(f["main_net_5d"], 5e6)       # 近 5 根求和
        self.assertEqual(f["main_net_10d"], 10e6)
        self.assertEqual(f["super_net_5d"], 2e6)
        self.assertTrue(f["fund_comparable"])
        self.assertEqual(f["fund_source"], "eastmoney_fflow")
        self.assertEqual(f["fund_as_of"], "2026-11-10")

    def test_insufficient_history_returns_none_not_partial_sum(self):
        # 次新股只有 3 个交易日：不能把 3 天之和冒充「5 日净额」
        f = sources.fflow_quote_fields(_flow_rows(3))
        self.assertIsNone(f["main_net_5d"])
        self.assertIsNone(f["main_net_10d"])
        self.assertEqual(f["main_net"], 1e6)

    def test_multi_period_pct_stays_none(self):
        # 日线接口不返回成交额，5/10 日净占比无法还原 —— 必须留空而不是猜
        f = sources.fflow_quote_fields(_flow_rows(10))
        self.assertIsNone(f["main_pct_5d"])
        self.assertIsNone(f["main_pct_10d"])

    def test_window_aligns_to_trading_days_when_halted(self):
        """停牌股必须按交易日窗口求和（停牌日贡献 0），否则会多算一根更早的日线。

        这组数字是 300237 美晨科技 2026-11-13 的真实日线与东财 f164/f174 实测值：
        11-05 停牌无记录，按「最近 10 根」求和得 -39218276，比主源偏 716 万元。
        """
        days = ["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03",
                "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10",
                "2026-11-11", "2026-11-12", "2026-11-13"]
        vals = {
            "2026-10-28": 320305.0, "2026-10-29": -1718895.0, "2026-10-30": -7158035.0,
            "2026-11-02": -1682319.0, "2026-11-03": -208650.0, "2026-11-04": 3263513.0,
            "2026-11-06": -16885377.0, "2026-11-09": -74973036.0, "2026-11-10": -20188124.0,
            "2026-11-11": -48445998.0, "2026-11-12": -10681686.0, "2026-11-13": 137741436.0,
        }
        rows = [{"date": d, "main_net": v, "super_net": 0.0, "big_net": 0.0,
                 "mid_net": 0.0, "small_net": 0.0, "main_pct": 0.0}
                for d, v in vals.items()]
        f = sources.fflow_quote_fields(rows, days)
        self.assertAlmostEqual(f["main_net_10d"], -32060241.0, places=0)
        self.assertAlmostEqual(f["main_net_5d"], -16547408.0, places=0)

    def test_empty_raises(self):
        with self.assertRaises(sources.SourceFailure):
            sources.fflow_quote_fields([])


class TestFetchQuotesResilience(unittest.TestCase):
    """单批失败不能让其它批的结果一起作废（旧版会整个抛错，行情全丢）。"""

    def _stub(self, fail_first: bool, fail_all: bool = False):
        seq = {"i": 0}

        def fake_chain(group, providers, validate=None):
            seq["i"] += 1
            if fail_all or (fail_first and seq["i"] == 1):
                raise sources.AllSourcesFailed("quotes", [{"label": "甲", "ok": False}])
            return sources.Outcome(
                {"600000": {"code": "600000", "fund_available": True}},
                "eastmoney", "东方财富", "full", "ep", [])
        return fake_chain

    def test_failing_batch_is_isolated(self):
        with mock.patch.object(sources, "chain", self._stub(fail_first=True)):
            merged, meta = sources.fetch_quotes(
                ["0.000001", "1.600000"], sources.dt.date(2026, 11, 13),
                {"data_sources": {}}, with_flow=True, batch=1)
        self.assertEqual(list(merged), ["600000"])
        self.assertEqual(meta["coverage"], "1/2")
        self.assertEqual(meta["failed_batches"], 1)

    def test_all_batches_failing_raises(self):
        with mock.patch.object(sources, "chain", self._stub(fail_first=True, fail_all=True)):
            with self.assertRaises(sources.AllSourcesFailed):
                sources.fetch_quotes(["0.000001"], sources.dt.date(2026, 11, 13),
                                     {"data_sources": {}}, with_flow=True, batch=1)


class TestApplyFlowPatch(unittest.TestCase):
    def test_does_not_override_real_fund_and_keeps_detail_rows(self):
        quotes = {"600000": {"code": "600000", "fund_available": True},
                  "600001": {"code": "600001", "fund_available": False}}
        patch = {
            "600000": {"main_net": 9.0, "fund_available": True, "flow_rows": [{"date": "x"}]},
            "600001": {"main_net": 1.0, "fund_available": True, "flow_rows": [{"date": "y"}]},
        }
        details: dict[str, list] = {}
        n = sources.apply_flow_patch(quotes, patch, details)
        self.assertEqual(n, 1)
        # 已经有真实资金口径的票不能被覆盖
        self.assertNotIn("main_net", quotes["600000"])
        self.assertEqual(quotes["600001"]["main_net"], 1.0)
        # 明细行不应被塞进行情记录，但要能交给复盘的 flow_history
        self.assertNotIn("flow_rows", quotes["600001"])
        self.assertIn("600001", details)


class TestQualityCaliber(unittest.TestCase):
    def _pool(self, q="full"):
        return sources.Outcome({}, "eastmoney", "东方财富涨停池", q, "ep", [])

    def test_fflow_backfill_restores_full(self):
        # 关键：同口径回补后必须仍算 full，否则每天都被标成降级
        self.assertEqual(
            sources.quality_of({"ZT": self._pool()}, {
                "has_fund": True, "fund_comparable": True,
                "fund_source": "eastmoney_fflow"}), "full")

    def test_sina_caliber_is_partial(self):
        self.assertEqual(
            sources.quality_of({"ZT": self._pool()}, {
                "has_fund": True, "fund_comparable": False,
                "fund_source": "sina"}), "partial")

    def test_no_fund_with_minimal_pool(self):
        self.assertEqual(
            sources.quality_of({"ZT": self._pool("minimal")},
                               {"has_fund": False, "fund_comparable": False}), "minimal")


class TestFlowBackfillCircuitBreaker(unittest.TestCase):
    """回补必须会被熔断。

    实测教训：6 并发一次打 37 个请求，不但本次全失败，还把本来可用的 push2his
    打成 RemoteDisconnected，连逐日资金明细一起丢掉 —— 回补自己变成了故障源。
    """

    def test_aborts_after_consecutive_failures(self):
        calls = {"n": 0}

        def boom(secid, limit=15):
            calls["n"] += 1
            raise sources.SourceFailure("RemoteDisconnected")

        secids = [f"1.60000{i}" for i in range(8)]
        with mock.patch.object(sources, "em_fetch_flow_history", boom), \
             mock.patch.object(sources, "market_trading_days", lambda *a, **k: []):
            with self.assertRaises(sources.SourceFailure) as ctx:
                sources.em_fetch_flow_quotes(secids)
        self.assertIn("熔断", str(ctx.exception))
        self.assertLessEqual(calls["n"], 3, "熔断后不应继续消耗配额")

    def test_success_path(self):
        rows = _flow_rows(12)
        with mock.patch.object(sources, "em_fetch_flow_history",
                               lambda sid, limit=15: rows), \
             mock.patch.object(sources, "market_trading_days", lambda *a, **k: []):
            out = sources.em_fetch_flow_quotes(["1.600000", "0.000001"])
        self.assertEqual(set(out), {"600000", "000001"})
        self.assertEqual(out["600000"]["main_net_5d"], 5e6)
        self.assertEqual(out["600000"]["fund_source"], "eastmoney_fflow")
        self.assertIn("flow_rows", out["600000"])

    def test_skips_entirely_when_over_cap(self):
        """超过上限就整体不做：宁可统一降级，也不要半套口径混进同一张排行表。"""
        with mock.patch.object(sources, "em_fetch_flow_history",
                               lambda *a, **k: _flow_rows(12)), \
             mock.patch.object(sources, "market_trading_days", lambda *a, **k: []):
            with self.assertRaises(sources.SourceFailure) as ctx:
                sources.em_fetch_flow_quotes([f"1.60000{i}" for i in range(5)],
                                             max_stocks=3)
        self.assertIn("混合口径", str(ctx.exception))

    def test_partial_under_half_is_rejected(self):
        """覆盖率不足一半就整体放弃，避免半套口径混进评分。"""
        rows = _flow_rows(12)
        state = {"i": 0}

        def flaky(secid, limit=15):
            state["i"] += 1
            if state["i"] > 2:
                raise sources.SourceFailure("throttled")
            return rows

        secids = [f"1.60000{i}" for i in range(8)]
        with mock.patch.object(sources, "em_fetch_flow_history", flaky), \
             mock.patch.object(sources, "market_trading_days", lambda *a, **k: []):
            with self.assertRaises(sources.SourceFailure):
                sources.em_fetch_flow_quotes(secids)


class TestFundSourceAggregation(unittest.TestCase):
    """口径归属按每只票实际写入的来源汇总：

    ulist 当日快照 与 fflow 日线回补同属东财口径，混用仍可比；
    掺进新浪「主动买卖单」才算不可比。旧写法用「中途改标记」，
    会把东财内部的两个通道也误判成 mixed。
    """

    def _run(self, sina_patch=None):
        def fake_chain(group, providers, validate=None):
            return sources.Outcome({
                "600000": {"code": "600000", "fund_available": True, "fund_source": "eastmoney"},
                "000001": {"code": "000001", "fund_available": False},
            }, "eastmoney", "东方财富行情＋资金流", "full", "ep", [])

        def fake_fflow(secids, **kw):
            return {"000001": {"main_net": 1.0, "fund_available": True,
                               "fund_source": "eastmoney_fflow", "flow_rows": []}}

        def fake_sina(codes, **kw):
            return {c: {"main_net": 2.0, "fund_available": True, "fund_source": "sina"}
                    for c in codes}

        with mock.patch.object(sources, "chain", fake_chain), \
             mock.patch.object(sources, "em_fetch_flow_quotes", fake_fflow), \
             mock.patch.object(sources, "sina_fetch_flow", fake_sina):
            return sources.fetch_quotes(["1.600000", "0.000001"],
                                        sources.dt.date(2026, 11, 13),
                                        {"data_sources": {}}, with_flow=True)[1]

    def test_eastmoney_plus_fflow_is_still_comparable(self):
        meta = self._run()
        self.assertIn(meta["fund_source"], ("eastmoney", "eastmoney_fflow"))
        self.assertTrue(meta["fund_comparable"])
        self.assertEqual(meta["fund_coverage"], 2)

    def test_sina_mixed_is_not_comparable(self):
        def fake_chain(group, providers, validate=None):
            return sources.Outcome({
                "600000": {"code": "600000", "fund_available": True, "fund_source": "eastmoney"},
                "000001": {"code": "000001", "fund_available": False},
            }, "eastmoney", "东方财富行情＋资金流", "full", "ep", [])

        def boom(*a, **k):
            raise sources.SourceFailure("push2his blocked")

        def fake_sina(codes, **kw):
            return {c: {"main_net": 2.0, "fund_available": True, "fund_source": "sina"}
                    for c in codes}

        with mock.patch.object(sources, "chain", fake_chain), \
             mock.patch.object(sources, "em_fetch_flow_quotes", boom), \
             mock.patch.object(sources, "sina_fetch_flow", fake_sina):
            meta = sources.fetch_quotes(["1.600000", "0.000001"],
                                         sources.dt.date(2026, 11, 13),
                                         {"data_sources": {}}, with_flow=True)[1]
        self.assertEqual(meta["fund_source"], "mixed")
        self.assertFalse(meta["fund_comparable"])


class TestLimitPct(unittest.TestCase):
    def test_gem_st_is_twenty_not_five(self):
        # 创业板 ST 涨跌幅仍是 20%；先匹配 "ST" 会把涨停价算错一半
        self.assertEqual(sources.limit_pct("300123", "*ST某某"), 20.0)
        self.assertEqual(sources.limit_pct("688123", "ST某某"), 20.0)

    def test_main_board_st_is_five(self):
        self.assertEqual(sources.limit_pct("600123", "ST某某"), 5.0)

    def test_normal_and_bj(self):
        self.assertEqual(sources.limit_pct("600123", "某某股份"), 10.0)
        self.assertEqual(sources.limit_pct("300123", "某某科技"), 20.0)
        self.assertEqual(sources.limit_pct("830123", "某某"), 30.0)


class TestTradingDate(unittest.TestCase):
    def _payload(self, stamp: str) -> str:
        parts = ["1", "上证指数", "000001"] + ["0"] * 27 + [stamp]
        return 'v_sh000001="' + "~".join(parts) + '";'

    def test_parses_date_from_index_timestamp(self):
        sources._TRADING_DATE_CACHE.clear()
        with mock.patch.object(sources, "http_text",
                               lambda *a, **k: self._payload("20261113161445")):
            self.assertEqual(sources.trading_date_from_tencent(), "2026-11-13")

    def test_returns_none_on_garbage(self):
        sources._TRADING_DATE_CACHE.clear()
        with mock.patch.object(sources, "http_text", lambda *a, **k: "v_sh000001=\"\";"):
            self.assertIsNone(sources.trading_date_from_tencent())

    def test_returns_none_when_network_fails(self):
        sources._TRADING_DATE_CACHE.clear()

        def boom(*a, **k):
            raise sources.SourceFailure("down")
        with mock.patch.object(sources, "http_text", boom):
            self.assertIsNone(sources.trading_date_from_tencent())


if __name__ == "__main__":
    unittest.main()
