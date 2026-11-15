"""归档保留窗口的回归测试（标准库 unittest，无第三方依赖）。

重点不是「能删」，而是「不该删的一个都没删」：归档目录里同时躺着
``demo.json`` / ``latest.json`` / ``.js`` 等文件，清理逻辑必须只认
``YYYY-MM-DD.json``。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src import report, retention


class TestPruneDir(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.daily = os.path.join(self.root, "docs", "data", "daily")
        os.makedirs(self.daily)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _touch(self, *names):
        for n in names:
            with open(os.path.join(self.daily, n), "w", encoding="utf-8") as fh:
                fh.write("{}")

    def test_keeps_newest_n_and_removes_rest(self):
        names = [f"2026-11-{d:02d}.json" for d in range(1, 11)]
        self._touch(*names)
        removed = retention.prune_dir(self.daily, 3)
        self.assertEqual(len(removed), 7)
        self.assertEqual(sorted(os.listdir(self.daily)),
                         ["2026-11-08.json", "2026-11-09.json", "2026-11-10.json"])
        # 删掉的必须是最旧的，且按路径返回
        self.assertIn(os.path.join(self.daily, "2026-11-01.json"), removed)

    def test_under_limit_is_noop(self):
        self._touch("2026-11-09.json", "2026-11-10.json")
        self.assertEqual(retention.prune_dir(self.daily, 5), [])
        self.assertEqual(len(os.listdir(self.daily)), 2)

    def test_exactly_at_limit_is_noop(self):
        self._touch(*[f"2026-11-{d:02d}.json" for d in range(1, 6)])
        self.assertEqual(retention.prune_dir(self.daily, 5), [])
        self.assertEqual(len(os.listdir(self.daily)), 5)

    def test_non_dated_files_are_never_touched(self):
        """demo.json / latest.json / history.js 不是按日归档，删了会直接坏页面。"""
        keepers = ["demo.json", "latest.json", "latest.js", "history.json",
                   "review.json", "2026-11-10.json", "not-a-date.json",
                   "2026-11-1.json.bak"]
        self._touch(*keepers)
        self._touch(*[f"2026-10-{d:02d}.json" for d in range(1, 9)])
        retention.prune_dir(self.daily, 2)
        left = set(os.listdir(self.daily))
        for name in keepers:
            self.assertIn(name, left, name)
        self.assertIn("2026-11-10.json", left)
        self.assertEqual(len(left), len(keepers) + 1)

    def test_missing_dir_and_zero_keep_are_safe(self):
        missing = os.path.join(self.root, "nope")
        self.assertEqual(retention.prune_dir(missing, 5), [])
        self._touch("2026-11-09.json", "2026-11-10.json")
        # keep<=0 视为「不清理」而不是「全清」，避免误配把归档一次清空
        self.assertEqual(retention.prune_dir(self.daily, 0), [])
        self.assertEqual(len(os.listdir(self.daily)), 2)


class TestPruneArchives(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for sub in (("docs", "data", "daily"), ("data", "snapshots")):
            d = os.path.join(self.root, *sub)
            os.makedirs(d)
            for day in range(1, 9):
                with open(os.path.join(d, f"2026-11-{day:02d}.json"), "w",
                          encoding="utf-8") as fh:
                    fh.write("{}")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_both_dirs_are_pruned(self):
        removed = retention.prune_archives(self.root, daily_keep=3, snapshot_keep=2)
        self.assertEqual(len(removed), 5 + 6)
        self.assertEqual(len(os.listdir(os.path.join(self.root, "docs", "data", "daily"))), 3)
        self.assertEqual(len(os.listdir(os.path.join(self.root, "data", "snapshots"))), 2)

    def test_window_is_wider_than_history_index(self):
        """history.json 只留 90 天，daily 归档必须留得比它多，否则下拉里点开就 404。"""
        with open(report.__file__, encoding="utf-8") as fh:
            self.assertIn("days[-90:]", fh.read())
        self.assertGreater(retention.DAILY_KEEP, 90)


if __name__ == "__main__":
    unittest.main()
