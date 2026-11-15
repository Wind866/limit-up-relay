"""按日期归档文件的保留窗口（``docs/data/daily`` 与 ``data/snapshots``）。

两个目录都是「每个交易日新增一个 ``YYYY-MM-DD.json``」，不设上限时仓库会以
每交易日约 180 KB 持续增长（一年 40 MB 以上），clone 与 Pages 部署都会越来越慢，
而 Pages 每次部署都要整目录上传。

删掉的都是不可能再被读到的文件：

* ``docs/data/daily/``  —— 前端日期下拉读 ``history.json`` 的 ``days``，而
  :func:`report.history_index` 只保留最近 90 天；这里留 120 天，比业务需要更宽，
  避免边界那天点开就 404。
* ``data/snapshots/``   —— :func:`report.compute_review` 只取「today 之前最近的一份」，
  ``datasource.load_recent_snapshot`` 也只取最新一份；留 45 天足够人工回查。

只匹配 ``YYYY-MM-DD.json``，目录里的其它文件（``demo.json``、``latest.json``、
``history.json`` 等）一律不动 —— 误删它们的代价远大于多留几个归档。
"""

from __future__ import annotations

import os
import re

#: 与 report.history_index 的 90 天窗口对齐并留出余量
DAILY_KEEP = 120
#: 复盘只需要上一交易日那一份，45 天是给人工回查的余量
SNAPSHOT_KEEP = 45

_DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")

__all__ = ["DAILY_KEEP", "SNAPSHOT_KEEP", "prune_dir", "prune_archives"]


def prune_dir(directory: str, keep: int) -> list[str]:
    """只保留文件名日期最新的 ``keep`` 个，返回被删除的绝对路径。"""
    if keep <= 0 or not os.path.isdir(directory):
        return []
    names = sorted(n for n in os.listdir(directory) if _DATE_FILE.match(n))
    dropped = names[:-keep] if len(names) > keep else []
    removed: list[str] = []
    for name in dropped:
        path = os.path.join(directory, name)
        try:
            os.remove(path)
        except OSError as exc:  # 权限 / 已被别的进程删掉：记录但不阻断主流程
            print(f"⚠️ 归档清理跳过 {path}：{exc}")
            continue
        removed.append(path)
    return removed


def prune_archives(root: str, daily_keep: int = DAILY_KEEP,
                   snapshot_keep: int = SNAPSHOT_KEEP) -> list[str]:
    """清理两个归档目录，返回被删除的文件路径（按路径排序，便于日志稳定输出）。"""
    removed = prune_dir(os.path.join(root, "docs", "data", "daily"), daily_keep)
    removed += prune_dir(os.path.join(root, "data", "snapshots"), snapshot_keep)
    return removed
