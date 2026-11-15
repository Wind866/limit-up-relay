"""推送台账（本地文件版）与选股剔除规则的回归测试。

台账那一组是为了钉住 2026-11-14 那次线上故障：旧版用 GitHub Contents API
单独提交台账，抢先把远端 HEAD 推到前面，导致随后「提交每日快照」的 git push
必然 non-fast-forward 被拒 → Pages 部署被 skip → 看板停更。
现在台账只写本地工作区，由同一个提交步骤一并推送，这里保证它还能正常判重。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import feishu, push_guard, strategy

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLocalLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, ".push-state", "ledger.json")
        self.patch = mock.patch.dict(os.environ, {"PUSH_LEDGER_PATH": self.path})
        self.patch.start()
        os.environ.pop("FORCE_PUSH", None)
        os.environ.pop("PUSH_GUARD_DISABLE", None)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_first_run_is_not_skipped(self):
        self.assertFalse(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1537"))

    def test_mark_then_skip_roundtrip(self):
        self.assertTrue(push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1537"))
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1537"))

    def test_two_slots_do_not_interfere(self):
        self.assertTrue(push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1307"))
        self.assertFalse(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1537"))
        self.assertTrue(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1307"))

    def test_mark_is_idempotent(self):
        push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1537")
        push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1537")
        with open(self.path, encoding="utf-8") as fh:
            records = json.load(fh)["records"]
        self.assertEqual(len([r for r in records if r["edition"].endswith("-1537")]), 1)

    def test_corrupt_ledger_fails_open_and_recovers(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ 这不是 json")
        # 坏台账不能拦住推送
        self.assertFalse(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1537"))
        # 但写入要能自己修复
        self.assertTrue(push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1537"))
        self.assertTrue(push_guard.should_skip("daily.yml", cutoff_hour=12, slot="1537"))

    def test_force_overrides_ledger(self):
        push_guard.mark_pushed("daily.yml", cutoff_hour=12, slot="1537")
        self.assertFalse(push_guard.should_skip("daily.yml", force=True,
                                                cutoff_hour=12, slot="1537"))

    def test_ledger_caps_record_count(self):
        records = [{"workflow": "w", "edition": f"d{i}"} for i in range(push_guard.MAX_RECORDS + 30)]
        self.assertTrue(push_guard._write_ledger(records))
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["records"]), push_guard.MAX_RECORDS)


class TestNoRemoteCommit(unittest.TestCase):
    """台账不能再依赖 GitHub Contents API：那会在远端抢先产生 commit。"""

    def test_push_guard_has_no_github_api_dependency(self):
        with open(os.path.join(ROOT, "src", "push_guard.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("api.github.com", src)
        self.assertNotIn("base64", src)


class TestEligibility(unittest.TestCase):
    CFG = {"universe": {"exclude_st": True, "exclude_bj": True,
                        "min_amount_yuan": 50_000_000}}

    def test_missing_amount_is_not_excluded(self):
        # 备用源不提供成交额时，旧写法 `or 0` 会把整批标的剔除、观察池清空
        ok, _ = strategy._eligible({"code": "600000", "name": "某某", "amount": None},
                                   self.CFG)
        self.assertTrue(ok)

    def test_low_amount_is_excluded(self):
        ok, reason = strategy._eligible(
            {"code": "600000", "name": "某某", "amount": 1_000_000}, self.CFG)
        self.assertFalse(ok)
        self.assertIn("成交额", reason)

    def test_st_and_bj_still_excluded(self):
        self.assertFalse(strategy._eligible(
            {"code": "600000", "name": "*ST某某", "amount": 1e9}, self.CFG)[0])
        self.assertFalse(strategy._eligible(
            {"code": "830123", "name": "某某", "amount": 1e9}, self.CFG)[0])


class TestAlertSigning(unittest.TestCase):
    """失败告警必须带加签。

    旧版工作流用裸 curl 发 ``msg_type=text``，一旦飞书机器人开启「加签」，
    消息会被直接拒（19021）—— 长期无人值守时告警等于永久哑掉。
    """

    def _capture(self, secret: str) -> dict:
        seen: dict = {}

        def fake_post(url, payload, timeout, attempts=2):
            seen.update(payload)
            return {"code": 0}

        with mock.patch.object(feishu, "_post", fake_post):
            feishu.send_text("http://example.invalid/hook", secret, "任务失败")
        return seen

    def test_payload_is_signed(self):
        import base64
        import hashlib
        import hmac
        seen = self._capture("s3cret")
        self.assertEqual(seen["msg_type"], "text")
        self.assertIn("timestamp", seen)
        expected = base64.b64encode(
            hmac.new(f"{seen['timestamp']}\ns3cret".encode("utf-8"),
                     digestmod=hashlib.sha256).digest()).decode()
        self.assertEqual(seen["sign"], expected)

    def test_no_secret_omits_sign(self):
        seen = self._capture("")
        self.assertNotIn("sign", seen)
        self.assertNotIn("timestamp", seen)


class TestKeepAlive(unittest.TestCase):
    """保活工作流必须真的能提交。

    GitHub 在公开仓库「连续 60 天无活动」时会自动禁用定时工作流，且重新启用必须
    改 cron 值，普通 commit 不够。keep-alive 就是为这个存在的 —— 但它曾经
    ``git add .github/keep-alive.log`` 而 .gitignore 里有 ``*.log``，
    首次运行就会因 "paths are ignored" 失败。安全网自己先挂，等于没有。
    """

    def test_heartbeat_log_is_not_ignored(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            rules = [ln.strip() for ln in fh]
        self.assertIn("*.log", rules)
        self.assertIn("!.github/keep-alive.log", rules,
                      "*.log 会吞掉心跳日志，keep-alive 的 git add 会失败")

    def test_workflow_force_adds_heartbeat(self):
        with open(os.path.join(ROOT, ".github", "workflows", "keep-alive.yml"),
                  encoding="utf-8") as fh:
            wf = fh.read()
        self.assertIn("git add -f .github/keep-alive.log", wf)


class TestWorkflowCommitStep(unittest.TestCase):
    """提交步骤必须把台账一起带上，并且先 rebase 再推 —— 否则又会抢跑远端。"""

    def setUp(self):
        with open(os.path.join(ROOT, ".github", "workflows", "daily.yml"), encoding="utf-8") as fh:
            self.wf = fh.read()

    def test_push_state_is_committed_with_data(self):
        self.assertIn(".push-state", self.wf)
        self.assertIn("git add docs/data data/snapshots .push-state", self.wf)

    def test_commit_step_rebases_before_push(self):
        self.assertIn("git pull --rebase --autostash", self.wf)

    def test_alert_goes_through_signed_script(self):
        self.assertIn("scripts/alert.py", self.wf)
        self.assertNotIn('"msg_type":"text"', self.wf)

    def test_pages_steps_are_gated(self):
        self.assertIn("steps.pages.outputs.enabled == 'true'", self.wf)


class TestAlertPreflight(unittest.TestCase):
    """`scripts/alert.py --check`：加签缺失只能靠自查发现，不能靠猜。"""

    @staticmethod
    def _module():
        import importlib.util
        path = os.path.join(ROOT, "scripts", "alert.py")
        spec = importlib.util.spec_from_file_location("_relay_alert", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_no_webhook_fails_the_check(self):
        mod = self._module()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mod.check_env(), 1)

    def test_webhook_without_secret_warns_and_hides_url(self):
        import contextlib
        import io
        mod = self._module()
        buf = io.StringIO()
        env = {"FEISHU_WEBHOOK": "https://open.feishu.cn/hook/secret-url"}
        with mock.patch.dict(os.environ, env, clear=True), \
             contextlib.redirect_stdout(buf):
            self.assertEqual(mod.check_env(), 0)
        out = buf.getvalue()
        self.assertIn("19021", out)
        self.assertNotIn("secret-url", out)   # 体检输出不落明文 webhook

    def test_sign_error_carries_actionable_hint(self):
        report = {"meta": {"date": "2026-11-16"}}
        with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK": "https://x",
                                          "FEISHU_SECRET": ""}, clear=True), \
             mock.patch.object(feishu, "build_card", return_value={"elements": []}), \
             mock.patch.object(feishu, "send", return_value={"code": 19021}):
            out = feishu.push(report)
        self.assertFalse(out["ok"])
        self.assertIn("FEISHU_SECRET", out["hint"])


if __name__ == "__main__":
    unittest.main()
