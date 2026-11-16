#!/usr/bin/env python3
"""推送幂等守卫 · 基于仓库内台账（标准库实现，无第三方依赖）。

## 为什么是「本地文件台账」

分三步演进，每一步都在修前一步的真问题：

1. **查 Actions API 有无 success 的 run**（最初）—— 非交易日跳过、盘中迟到不推、
   preview/demo 调试、手动 ``--no-push`` 这些运行**也全是 success**，会把当天真正
   要发的那条消息误判成「已推过」而跳过（静默漏推）。已废弃。

2. **用 GitHub Contents API 直接提交台账**（上一版）—— 判重准确了，但它会在远端
   分支上**抢先产生一个 commit**。紧接着工作流的「提交每日快照」步骤要 ``git push``
   自己那份数据提交，本地 HEAD 已落后于远端 → 必然 non-fast-forward 被拒 →
   该步骤失败 → 后续「配置 Pages / 上传产物 / 部署 Pages」全部被 skip，
   看板从此不再更新。2026-11-14 19:56 那次运行 failure 就是这个原因
   （远端 HEAD 是 ``chore(state): 更新推送台账 [skip ci]``，而快照提交没进去）。
   而且它写死了 ``branch=main``，默认分支叫 master 的仓库会静默失效。

3. **本地文件台账**（本版）—— 只读写工作区内的 ``.push-state/ledger.json``，
   由工作流的提交步骤与数据快照**一起** commit & push。因此：
   * 不再抢跑远端，不会制造 non-fast-forward；
   * 不依赖 ``GITHUB_TOKEN`` 与分支名，fork、私有仓库、本地运行行为一致；
   * 没有 Contents API 的 sha 冲突重试，逻辑从 ~120 行降到 ~40 行。

代价：台账要等 ``git push`` 成功才算落库。所以工作流的提交步骤必须带
``git pull --rebase --autostash`` 与推送重试；真的推不上去时这一次重复推送一条，
并触发失败告警 —— 这比「为了落台账把看板搞挂」划算得多。

## 档期（edition）

- 单档任务（早间 / 晚间 / 收盘）：默认「当前时刻减 cutoff_hour 小时」落在哪天，就算哪档。
  默认 8 等效于「北京时间早 08:00 换日」：晚间 21:53 正常触发与次日凌晨 03:00 延迟触发、
  收盘 19:33 与次日 01:25 延迟触发，都会归到同一档。
- cutoff 怎么选：收盘可用 12（换日推迟到中午，覆盖更长延迟）；
  **早间 08:13 必须用 8（或 0），不能用 12** —— 08:13 减 12 小时会落到前一天，
  与中午的延迟档分家，反而造成重复推送。
- 涨停接力（本仓库）：中午 12:33 盘中档已下线，只剩 18:53 收盘档，但调用时仍传
  slot="1853"，档期键为 "日期-1853"，与历史台账同构；slot 机制保留，多档任务可直接复用。

## 失败策略：一律 fail-open

台账读不到、写不了、JSON 坏了，都**不阻断推送**，也**不跳过推送**。
宁可偶尔重复一条，也不能因为守卫本身出问题导致当天没有消息。

## 环境变量

  PUSH_LEDGER_PATH   台账路径，默认 <仓库根>/.push-state/ledger.json
  FORCE_PUSH=1       强制跳过检查（手动重推用）
  PUSH_GUARD_DISABLE=1  完全关闭守卫（应急）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

BJ_TZ = timezone(timedelta(hours=8))
LEDGER_REL = os.path.join(".push-state", "ledger.json")
DEFAULT_CUTOFF_HOUR = 8
MAX_RECORDS = 200

__all__ = [
    "should_skip", "mark_pushed", "edition_date", "edition_key",
    "already_pushed", "DEFAULT_CUTOFF_HOUR", "ledger_path",
]


def ledger_path() -> str:
    """台账文件位置：环境变量优先，否则相对本文件回推到仓库根。"""
    env = os.environ.get("PUSH_LEDGER_PATH", "").strip()
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, LEDGER_REL)


def edition_date(moment: datetime | None = None, cutoff_hour: int = DEFAULT_CUTOFF_HOUR) -> date:
    """把实际运行时刻归到它所属的推送档期。"""
    moment = moment or datetime.now(BJ_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BJ_TZ)
    return (moment.astimezone(BJ_TZ) - timedelta(hours=cutoff_hour)).date()


def edition_key(workflow_file: str = "", slot: str | None = None,
                cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
                now: datetime | None = None) -> str:
    """档期键：日期，或 日期-slot（同一天多档的任务）。"""
    key = edition_date(now, cutoff_hour).isoformat()
    if slot:
        key = f"{key}-{slot}"
    return key


def _read_ledger() -> tuple[list, bool]:
    """返回 (records, available)。available=False 表示无法确认，调用方应 fail-open。"""
    path = ledger_path()
    if not os.path.exists(path):
        return [], True          # 台账还没建，第一次运行
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        records = data.get("records") or []
        if not isinstance(records, list):
            raise ValueError("records 不是列表")
        return records, True
    except (OSError, ValueError, TypeError) as exc:
        print(f"[幂等] 台账不可读（{type(exc).__name__}: {exc}），按未推送处理")
        return [], False


def _write_ledger(records: list) -> bool:
    """原子写：先写同目录临时文件再 os.replace，避免半截 JSON 让下次无法解析。"""
    path = ledger_path()
    body = {
        "version": 1,
        "updated_at": datetime.now(BJ_TZ).isoformat(timespec="seconds"),
        "records": records[-MAX_RECORDS:],
    }
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(body, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError as exc:
        print(f"[幂等] 台账写入失败（{type(exc).__name__}: {exc}），不影响本次推送")
        return False


def _forced() -> bool:
    return os.environ.get("FORCE_PUSH", "").strip().lower() in ("1", "true", "yes")


def _has_record(records: list, workflow_file: str, edition: str) -> dict | None:
    for rec in records:
        if rec.get("workflow") == workflow_file and rec.get("edition") == str(edition):
            return rec
    return None


def already_pushed(workflow_file: str, edition: str,
                   cutoff_hour: int = DEFAULT_CUTOFF_HOUR) -> tuple[bool, str]:
    """兼容旧接口：查台账里本档期是否已推送成功。"""
    records, available = _read_ledger()
    if not available:
        return False, "台账不可用，按未推送处理"
    rec = _has_record(records, workflow_file, str(edition))
    if rec:
        return True, f"档期 {edition} 已在 {rec.get('ts', '?')} 推送成功（run {rec.get('run_id', '?')}）"
    return False, f"档期 {edition} 尚无成功推送记录"


def should_skip(workflow_file: str, force: bool = False,
                now: datetime | None = None,
                cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
                slot: str | None = None) -> bool:
    """主入口：True 表示本档期已经推过，直接退出，不要再发消息。"""
    if os.environ.get("PUSH_GUARD_DISABLE", "").strip() == "1":
        print("[幂等] PUSH_GUARD_DISABLE=1，守卫已关闭")
        return False
    if force or _forced():
        print("[幂等] FORCE 已开启，跳过检查，强制推送")
        return False

    key = edition_key(workflow_file, slot, cutoff_hour, now)
    records, available = _read_ledger()
    if not available:
        print("[幂等] 台账不可用，fail-open：照常推送（可能重复，但不漏推）")
        return False
    rec = _has_record(records, workflow_file, key)
    if rec:
        print(f"⏭ 跳过本次推送：档期 {key} 已在 {rec.get('ts', '?')} 推送成功"
              f"（run {rec.get('run_id', '?')}）")
        print("   （外部准点触发 + GitHub cron 延迟触发时，只有先到的那次真的推；"
              "要强制重推请设 FORCE_PUSH=1）")
        return True
    print(f"[幂等] 档期 {key} 尚无成功推送记录，继续推送")
    return False


def mark_pushed(workflow_file: str,
                cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
                slot: str | None = None) -> bool:
    """**只在飞书确实推送成功之后**调用。写入台账，供后续重复触发判重。"""
    if os.environ.get("PUSH_GUARD_DISABLE", "").strip() == "1":
        return False

    key = edition_key(workflow_file, slot, cutoff_hour)
    record = {
        "workflow": workflow_file,
        "edition": key,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "ts": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    records, available = _read_ledger()
    if not available:
        # 台账损坏时用空表覆盖重建：保住本档期记录比保留历史更重要
        records = []
    if _has_record(records, workflow_file, key):
        print(f"[幂等] 档期 {key} 已有记录，无需重复写入")
        return True
    if _write_ledger(records + [record]):
        print(f"[幂等] 已记录推送成功：{key}（由随后的提交步骤一并入库）")
        return True
    return False


def _main(argv: list[str]) -> int:
    workflow = "evening-news.yml"
    for arg in argv[1:]:
        if not arg.startswith("-"):
            workflow = arg
    force = "--force" in argv
    slot = next((a.split("=", 1)[1] for a in argv if a.startswith("--slot=")), None)
    cutoff = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--cutoff=")), DEFAULT_CUTOFF_HOUR)
    skip = should_skip(workflow, force=force, cutoff_hour=cutoff, slot=slot)
    print(f"workflow={workflow} edition={edition_key(workflow, slot, cutoff)} "
          f"→ {'SKIP' if skip else 'PUSH'}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
