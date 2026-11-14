"""幂等台账与飞书加签的回归测试。

全部走纯函数，不读网络、不写仓库、不触碰任何 Secret。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import unittest
from datetime import datetime, timedelta, timezone

from src import feishu, push_guard

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestEditionKey(unittest.TestCase):
    def test_default_cutoff_is_eight(self):
        self.assertEqual(push_guard.DEFAULT_CUTOFF_HOUR, 8)

    def test_late_night_belongs_to_previous_edition(self):
        # 晚间 22:13 正常触发与次日 01:25 延迟触发应归到同一档
        normal = datetime(2026, 11, 16, 22, 13, tzinfo=BJ)
        delayed = datetime(2026, 11, 17, 1, 25, tzinfo=BJ)
        self.assertEqual(
            push_guard.edition_date(normal), push_guard.edition_date(delayed)
        )

    def test_slot_separates_two_editions_same_day(self):
        now = datetime(2026, 11, 16, 16, 0, tzinfo=BJ)
        a = push_guard.edition_key("daily.yml", slot="1307", cutoff_hour=12, now=now)
        b = push_guard.edition_key("daily.yml", slot="1537", cutoff_hour=12, now=now)
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith("-1307"))
        self.assertTrue(b.endswith("-1537"))


class TestFeishuSign(unittest.TestCase):
    def test_sign_is_hmac_sha256_base64(self):
        secret, ts = "test-secret", "1700000000"
        expected = base64.b64encode(
            hmac.new(f"{ts}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        self.assertEqual(feishu.gen_sign(secret, ts), expected)


class TestGuardFailOpen(unittest.TestCase):
    """台账不可用时必须 fail-open：宁可重复一条，也不能漏推。"""

    def test_disable_switch_short_circuits(self):
        old = os.environ.get("PUSH_GUARD_DISABLE")
        os.environ["PUSH_GUARD_DISABLE"] = "1"
        try:
            self.assertFalse(push_guard.should_skip("daily.yml"))
        finally:
            if old is None:
                os.environ.pop("PUSH_GUARD_DISABLE", None)
            else:
                os.environ["PUSH_GUARD_DISABLE"] = old

    def test_force_short_circuits(self):
        old = os.environ.pop("FORCE_PUSH", None)
        try:
            self.assertFalse(push_guard.should_skip("daily.yml", force=True))
        finally:
            if old is not None:
                os.environ["FORCE_PUSH"] = old


class TestRepoHygiene(unittest.TestCase):
    def test_gitignore_does_not_hide_tests(self):
        path = os.path.join(ROOT, ".gitignore")
        if not os.path.exists(path):
            self.skipTest("本仓库无 .gitignore")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("test_") or stripped in ("tests/", "tests"):
                    self.fail(f".gitignore 会吞掉测试文件：{stripped}")


if __name__ == "__main__":
    unittest.main()
