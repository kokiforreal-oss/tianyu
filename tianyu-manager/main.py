"""Tianyu Manager 程序入口。

打开游戏数据分析窗口。进程启动和关闭仍由 core.process_manager 负责，
本入口不改动那部分逻辑。
"""

from __future__ import annotations


def main() -> int:
    """启动分析窗口。

    返回:
        Qt 事件循环的退出码。
    """
    from ui.analyzer_window import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
