#!/usr/bin/env python3
"""失败告警：向飞书机器人发送一条文本消息（支持加签）。

为什么单独抽出来：原来工作流里用裸 ``curl`` 发告警，而飞书机器人一旦开启「加签」，
任何**没有 sign 字段**的消息都会被拒（错误码 19021）。也就是说——告警通道在最需要
它的时候（长期无人值守）恰好是哑的。这里复用 ``src/feishu.py`` 的签名逻辑，
让告警与业务推送使用同一套凭据与校验方式。

用法：
    python scripts/alert.py "消息正文"
    python scripts/alert.py "消息正文" --run-url https://...

环境变量（按优先级）：
    ALERT_WEBHOOK   独立告警机器人（推荐，避免业务 webhook 故障时告警一起哑）
    FEISHU_WEBHOOK  业务机器人（兜底）
    FEISHU_SECRET   加签密钥（机器人开启了加签才需要；独立告警机器人也用这个）
    ALERT_SECRET    独立告警机器人的加签密钥，没配则回落到 FEISHU_SECRET

退出码：0 发送成功 / 未配置（视为无需告警）；1 发送失败。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import feishu  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def main(argv: list[str]) -> int:
    text = ""
    if len(argv) > 1 and not argv[1].startswith("-"):
        text = argv[1]
    for i, arg in enumerate(argv):
        if arg == "--run-url" and i + 1 < len(argv):
            text = f"{text}\n{argv[i + 1]}".strip()

    webhook = (os.environ.get("ALERT_WEBHOOK") or os.environ.get("FEISHU_WEBHOOK") or "").strip()
    secret = (os.environ.get("ALERT_SECRET")
              or os.environ.get("FEISHU_SECRET")
              or "").strip()
    if not webhook:
        print("[告警] 未配置 ALERT_WEBHOOK / FEISHU_WEBHOOK，跳过告警")
        return 0
    if not os.environ.get("ALERT_WEBHOOK"):
        print("[告警] 未配置独立告警机器人 ALERT_WEBHOOK，退回业务 webhook"
              "（业务 webhook 故障时本次告警也会一起失效）")

    try:
        result = feishu.send_text(webhook, secret, text or "运行失败，请查看日志")
    except Exception as exc:  # noqa: BLE001 - 告警失败只能记录，不能掩盖原始故障
        print(f"[告警] 发送异常 {type(exc).__name__}: {exc}")
        return 1

    # 飞书成功返回 code=0；加签失败是 19021，关键词校验失败是 19024
    if isinstance(result, dict) and (result.get("code") or result.get("StatusCode")) not in (0, None):
        print(f"[告警] 飞书拒绝受理：{result}")
        if result.get("code") == 19021:
            print("[告警] 19021 = 签名校验失败：该机器人开启了「加签」，请配置 ALERT_SECRET / FEISHU_SECRET")
        return 1
    print("[告警] 已发送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
