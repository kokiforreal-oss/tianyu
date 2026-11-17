"""测试用模拟进程。

用它代替真实游戏客户端，验证启动、正常退出和拒绝强制结束。
"""

from __future__ import annotations

import argparse
import signal
import time


def main() -> int:
    """按模式休眠、立即退出，或忽略 SIGTERM。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["exit-on-term", "ignore-term", "exit-immediately"],
        default="exit-on-term",
    )
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    del args.token

    if args.mode == "exit-immediately":
        return 3

    stop = False

    def handle_term(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    if args.mode == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, handle_term)

    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline and not stop:
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
