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


if __name__ == "__main__":
    unittest.main()
