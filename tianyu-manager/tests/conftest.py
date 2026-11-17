"""测试公共夹具。

清理时仍然核对 PID 和进程创建时间，避免测试残留处理误伤其他进程。
"""

from __future__ import annotations

from pathlib import Path

import psutil
import pytest

from core.process_manager import ProcessManager


def _stop_recorded_processes(manager: ProcessManager) -> None:
    """结束本管理器记录过、且创建时间仍然吻合的测试进程。"""
    for instance in manager.managed_instances():
        identity = manager.recorded_identity(instance.instance_id)
        if identity is None:
            continue
        pid, create_time = identity
        try:
            process = psutil.Process(pid)
            if abs(process.create_time() - create_time) > 1.0:
                continue
            process.kill()
            process.wait(timeout=2)
        except (psutil.Error, psutil.TimeoutExpired):
            continue


@pytest.fixture
def process_manager(tmp_path: Path):
    """提供独立的进程管理器，并在用例结束后回收它启动的模拟进程。"""
    manager = ProcessManager(quick_exit_window=0.35, log_dir=tmp_path / "logs")
    try:
        yield manager
    finally:
        _stop_recorded_processes(manager)
        manager.close()
