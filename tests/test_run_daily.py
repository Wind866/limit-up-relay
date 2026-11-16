"""运行入口的纯逻辑回归测试（标准库 unittest，无需任何第三方依赖）。"""
from __future__ import annotations

import os
import re
import unittest
from datetime import datetime, timedelta, timezone

from src import run_daily

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLateMinutes(unittest.TestCase):
    def test_on_time(self):
        now = datetime(2026, 11, 16, 18, 53, tzinfo=BJ)
        self.assertEqual(run_daily.late_minutes(now, "1853"), 0)

    def test_late_45_minutes(self):
        now = datetime(2026, 11, 16, 19, 38, tzinfo=BJ)
        self.assertEqual(run_daily.late_minutes(now, "1853"), 45)

    def test_invalid_expect_returns_zero(self):
        now = datetime(2026, 11, 16, 16, 22, tzinfo=BJ)
        for bad in ("", "abc", "18:53", "185"):
            self.assertEqual(run_daily.late_minutes(now, bad), 0, bad)


class TestMarketStatus(unittest.TestCase):
    def test_weekend(self):
        self.assertEqual(run_daily.market_status(datetime(2026, 11, 14, 10, 0, tzinfo=BJ)), "休市")

    def test_phases(self):
        cases = [
            (9, 0, "盘前"), (10, 0, "盘中"), (12, 0, "午间休市"),
            (14, 0, "盘中"), (15, 40, "收盘后"),
        ]
        for hour, minute, expected in cases:
            with self.subTest(hour=hour):
                self.assertEqual(
                    run_daily.market_status(datetime(2026, 11, 16, hour, minute, tzinfo=BJ)),
                    expected,
                )


class TestScheduleDocsConsistency(unittest.TestCase):
    """README 曾长期写 13:00/15:30，而 cron 实际是 13:07/15:37。

    档期常量分散在 workflow / 脚本 / 文档多处，提交历史里已两次因不同步出错，
    这条用例把漂移变成 CI 红灯。中午 12:33 的盘中档下线后，EXPECTED 只保留收盘档，
    另加一条用例确保盘中 cron 不会被悄悄加回来。
    """

    EXPECTED = {
        "53 10 * * 1-5": "18:53",
    }

    def test_workflow_cron_matches_readme(self):
        with open(os.path.join(ROOT, ".github", "workflows", "daily.yml"), encoding="utf-8") as fh:
            workflow = fh.read()
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()

        crons = re.findall(r"cron:\s*'([^']+)'", workflow)
        for cron in self.EXPECTED:
            self.assertIn(cron, crons, f"daily.yml 缺少 {cron}")
        for hhmm in self.EXPECTED.values():
            self.assertIn(hhmm, readme, f"README 缺少北京时间 {hhmm}")

    def test_no_stale_times_in_readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for stale in ("13:07", "15:37", "7 5 * * 1-5", "37 7 * * 1-5"):
            self.assertNotIn(stale, readme, f"README 仍残留旧档期 {stale}")

    def test_intraday_slot_retired(self):
        """中午 12:33 盘中档已下线：workflow 不能再注册盘中 cron，脚本要保留下线常量。"""
        with open(os.path.join(ROOT, ".github", "workflows", "daily.yml"), encoding="utf-8") as fh:
            workflow = fh.read()
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()

        for cron in ("33 4 * * 1-5", "33 5 * * 1-5", "33 7 * * 1-5"):
            self.assertNotIn(f"cron: '{cron}'", workflow, f"daily.yml 仍注册了盘中 cron {cron}")
        self.assertEqual(run_daily.RETIRED_SLOT, "1233")
        self.assertFalse(hasattr(run_daily, "INTRADAY_HOUR"), "盘中档逻辑应已移除")
        self.assertIn("12:33 的盘中快照档已下线", readme, "README 需说明中午档已下线")

    def test_fallback_crons_map_to_original_slots(self):
        """补档 cron 必须在『推导计划时刻』里映射回原档期，否则会被判成未知档期直接失败。"""
        with open(os.path.join(ROOT, ".github", "workflows", "daily.yml"), encoding="utf-8") as fh:
            workflow = fh.read()
        crons = re.findall(r"cron:\s*'([^']+)'", workflow)
        for fallback in ("53 11 * * 1-5", "53 13 * * 1-5", "53 17 * * 1-5"):
            self.assertIn(fallback, crons, f"缺少补档 cron {fallback}")
        self.assertIn("'53 10 * * 1-5'|'53 11 * * 1-5'|'53 13 * * 1-5'|'53 17 * * 1-5'", workflow)


class TestSessionDate(unittest.TestCase):
    """跨午夜补档：运行日 ≠ 数据日。

    旧逻辑把运行日当数据日，22:37 的兜底档拖到次日凌晨才起来时，
    周末被判「休市」、工作日被判「接口返回的日期不一致」，两条路都静默
    退出，前一交易日的收盘定稿永久丢失。
    """

    @staticmethod
    def _sd(y, m, d, hh=0, mm=0):
        return str(run_daily.session_date(datetime(y, m, d, hh, mm, tzinfo=BJ)))

    def test_market_open_uses_today(self):
        self.assertEqual(self._sd(2026, 11, 16, 15, 37), "2026-11-16")

    def test_after_midnight_falls_back_to_previous_session(self):
        # 22:37 档迟到 5 小时 → 次日（周二）03:37
        self.assertEqual(self._sd(2026, 11, 17, 3, 37), "2026-11-16")

    def test_weekend_falls_back_to_friday(self):
        # 周五 22:37 档拖到周六 03:37
        self.assertEqual(self._sd(2026, 11, 14, 3, 37), "2026-11-13")

    def test_pre_open_monday_falls_back_to_friday(self):
        self.assertEqual(self._sd(2026, 11, 16, 8, 0), "2026-11-13")

    def test_open_boundary(self):
        self.assertEqual(self._sd(2026, 11, 16, 9, 14), "2026-11-13")
        self.assertEqual(self._sd(2026, 11, 16, 9, 15), "2026-11-16")

    def test_late_minutes_survive_midnight(self):
        # 15:37 档跑到次日 03:37：延迟 12 小时，必须还能算出来（不能是负数）
        now = datetime(2026, 11, 17, 3, 37, tzinfo=BJ)
        self.assertEqual(run_daily.late_minutes(now, "1537"), 720)


if __name__ == "__main__":
    unittest.main()
