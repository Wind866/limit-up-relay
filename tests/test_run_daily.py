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
        now = datetime(2026, 11, 16, 15, 37, tzinfo=BJ)
        self.assertEqual(run_daily.late_minutes(now, "1537"), 0)

    def test_late_45_minutes(self):
        now = datetime(2026, 11, 16, 16, 22, tzinfo=BJ)
        self.assertEqual(run_daily.late_minutes(now, "1537"), 45)

    def test_invalid_expect_returns_zero(self):
        now = datetime(2026, 11, 16, 16, 22, tzinfo=BJ)
        for bad in ("", "abc", "15:37", "153"):
            self.assertEqual(run_daily.late_minutes(now, bad), 0, bad)


class TestIntradayGuard(unittest.TestCase):
    """盘中迟到只标注、不拦截推送（旧版曾误拦截导致静默漏推）。"""

    def test_close_slot_never_skips(self):
        self.assertFalse(run_daily.should_skip_intraday_push("1537", 300, "收盘后"))

    def test_intraday_on_time_not_skipped(self):
        self.assertFalse(run_daily.should_skip_intraday_push("1307", 0, "盘中"))

    def test_intraday_very_late_is_flagged_but_not_blocking(self):
        # 返回值只用于卡片标注；这里确认逻辑本身与「小时前缀」一致
        self.assertTrue(run_daily.should_skip_intraday_push("1307", 95, "收盘后"))
        self.assertTrue(run_daily.should_skip_intraday_push("1307", 10, "收盘后"))


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
    这条用例把漂移变成 CI 红灯。
    """

    EXPECTED = {
        "7 5 * * 1-5": "13:07",
        "37 7 * * 1-5": "15:37",
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
        for stale in ("13:00", "15:30", "0 5 * * 1-5", "30 7 * * 1-5"):
            self.assertNotIn(stale, readme, f"README 仍残留旧档期 {stale}")

    def test_intraday_hour_matches_cron(self):
        self.assertEqual(run_daily.INTRADAY_HOUR, "13")

    def test_fallback_crons_map_to_original_slots(self):
        """补档 cron 必须在『推导计划时刻』里映射回原档期，否则会被判成未知档期直接失败。"""
        with open(os.path.join(ROOT, ".github", "workflows", "daily.yml"), encoding="utf-8") as fh:
            workflow = fh.read()
        crons = re.findall(r"cron:\s*'([^']+)'", workflow)
        for fallback in ("7 6 * * 1-5", "37 8 * * 1-5"):
            self.assertIn(fallback, crons, f"缺少补档 cron {fallback}")
        self.assertIn("'7 5 * * 1-5'|'7 6 * * 1-5'", workflow)
        self.assertIn("'37 7 * * 1-5'|'37 8 * * 1-5'", workflow)


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
